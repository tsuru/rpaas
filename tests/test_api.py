# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import base64
import inspect
import json
import os
import unittest

from rpaas import api, plugin
from . import managers


class APITestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manager = managers.FakeManager()
        api.get_manager = lambda: cls.manager
        cls.api = api.api.test_client()

    def setUp(self):
        self.manager.reset()

    def test_start_instance(self):
        resp = self.api.post("/resources", data={"name": "someapp"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("someapp", self.manager.instances[0].name)

    def test_start_instance_without_name(self):
        resp = self.api.post("/resources", data={"names": "someapp"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("name is required", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_start_instance_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources", method="POST",
                                   data={"names": "someapp"},
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_remove_instance(self):
        self.manager.new_instance("someapp")
        resp = self.api.delete("/resources/someapp")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_remove_instance_not_found(self):
        resp = self.api.delete("/resources/someapp")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_remove_instance_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp", method="DELETE",
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_bind(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/bind",
                             data={"app-host": "someapp.cloud.tsuru.io"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("null", resp.data)
        self.assertEqual("application/json", resp.mimetype)
        bind = self.manager.instances[0].bound[0]
        self.assertEqual("someapp.cloud.tsuru.io", bind)

    def test_bind_without_app_host(self):
        resp = self.api.post("/resources/someapp/bind",
                             data={"app_hooost": "someapp.cloud.tsuru.io"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("app-host is required", resp.data)

    def test_bind_instance_not_found(self):
        resp = self.api.post("/resources/someapp/bind",
                             data={"app-host": "someapp.cloud.tsuru.io"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_bind_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp/bind", method="POST",
                                   data={"app-host": "someapp.cloud.tsuru.io"},
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_unbind(self):
        self.manager.new_instance("someapp")
        self.manager.bind("someapp", "someapp.cloud.tsuru.io")
        resp = self.api.delete("/resources/someapp/bind", data={"app-host": "someapp.cloud.tsuru.io"},
                               headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertEqual([], self.manager.instances[0].bound)

    def test_unbind_instance_not_found(self):
        resp = self.api.delete("/resources/someapp/bind", data={"app-host": "someapp.cloud.tsuru.io"},
                               headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_unbind_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp/bind",
                                   data={"app-host": "someapp.cloud.tsuru.io"},
                                   headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                   method="DELETE",
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_info(self):
        self.manager.new_instance("someapp")
        resp = self.api.get("/resources/someapp")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertEqual({"name": "someapp"}, data)

    def test_info_instance_not_found(self):
        resp = self.api.get("/resources/someapp")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_info_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp", method="GET",
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_status_started(self):
        self.manager.new_instance("someapp", state="anything.anything")
        resp = self.api.get("/resources/someapp/status")
        self.assertEqual(204, resp.status_code)

    def test_status_pending(self):
        self.manager.new_instance("someapp", state="pending")
        resp = self.api.get("/resources/someapp/status")
        self.assertEqual(202, resp.status_code)

    def test_status_error(self):
        self.manager.new_instance("someapp", state="failure")
        resp = self.api.get("/resources/someapp/status")
        self.assertEqual(500, resp.status_code)

    def test_status_not_found(self):
        resp = self.api.get("/resources/someapp/status")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_status_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp/status", method="GET",
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_scale_instance(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/scale",
                             data={"quantity": "3"})
        self.assertEqual(201, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertEqual(3, instance.units)

    def test_scale_instance_invalid_quantity(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/scale",
                             data={"quantity": "chico"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid quantity: chico", resp.data)

    def test_scale_instance_negative_quantity(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/scale",
                             data={"quantity": "-2"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid quantity: -2", resp.data)

    def test_scale_instance_missing_quantity(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/scale",
                             data={"quality": "-2"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("missing quantity", resp.data)

    def test_scale_instance_not_found(self):
        resp = self.api.post("/resources/someapp/scale",
                             data={"quantity": "2"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_scale_instance_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp/scale", method="POST",
                                   data={"quantity": "2"},
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_plugin(self):
        expected = inspect.getsource(plugin)
        resp = self.api.get("/plugin")
        self.assertEqual(200, resp.status_code)
        self.assertEqual(expected, resp.data)

    def test_plugin_does_not_require_authentication(self):
        expected = inspect.getsource(plugin)
        resp = self.api.get("/plugin")
        self.assertEqual(200, resp.status_code)
        self.assertEqual(expected, resp.data)

    def open_with_auth(self, url, method, user, password, data=None, headers=None):
        encoded = base64.b64encode(user + ":" + password)
        if not headers:
            headers = {}
        headers["Authorization"] = "Basic " + encoded
        return self.api.open(url, method=method, headers=headers, data=data)

    def set_auth_env(self, user, password):
        os.environ["API_USERNAME"] = user
        os.environ["API_PASSWORD"] = password

    def delete_auth_env(self):
        del os.environ["API_USERNAME"], os.environ["API_PASSWORD"]
