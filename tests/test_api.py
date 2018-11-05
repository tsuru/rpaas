# -*- coding: utf-8 -*-

# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import base64
import inspect
import json
import os
import unittest
from io import BytesIO

from rpaas import admin_plugin, api, plugin, storage
from . import managers


class APITestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["MONGO_DATABASE"] = "api_test"
        cls.storage = storage.MongoDBStorage()
        cls.manager = managers.FakeManager(storage=cls.storage)
        api.get_manager = lambda: cls.manager
        cls.api = api.api.test_client()

    def setUp(self):
        self.manager.reset()
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)
        os.environ["INSTANCE_LENGTH"] = "25"

    def test_plans(self):
        resp = self.api.get("/resources/plans")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("[]", resp.data)
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        resp = self.api.get("/resources/plans")
        self.assertEqual(200, resp.status_code)
        expected = [
            {"name": "small", "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}},
            {"name": "huge", "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}},
        ]
        self.assertEqual(expected, json.loads(resp.data))

    def test_flavors(self):
        resp = self.api.get("/resources/flavors")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("[]", resp.data)
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "vanilla",
             "description": "nginx 1.12",
             "config": {"nginx_version": "1.12"}}
        )
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "orange",
             "description": "nginx 1.13",
             "config": {"nginx_version": "1.13"}}
        )
        resp = self.api.get("/resources/flavors")
        self.assertEqual(200, resp.status_code)
        expected = [
            {"name": "vanilla", "description": "nginx 1.12",
             "config": {"nginx_version": "1.12"}},
            {"name": "orange", "description": "nginx 1.13",
             "config": {"nginx_version": "1.13"}},
        ]
        self.assertEqual(expected, json.loads(resp.data))

    def test_start_instance(self):
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("someapp", self.manager.instances[0].name)

    def test_start_instance_with_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1", "plan": "small"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("someapp", self.manager.instances[0].name)
        self.assertEqual("small", self.manager.instances[0].plan)

    def test_start_instance_with_plan_and_flavor(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "vanilla",
             "description": "some cool flavor",
             "config": {"nginx_version": "1.12"}}
        )
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1",
                                                 "plan": "small", "flavor": "vanilla"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("someapp", self.manager.instances[0].name)
        self.assertEqual("small", self.manager.instances[0].plan)
        self.assertEqual("vanilla", self.manager.instances[0].flavor)

    def test_start_instance_with_flavor_as_tag(self):
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "vanilla",
             "description": "some cool flavor",
             "config": {"nginx_version": "1.12"}}
        )
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1",
                                                 "tags": ["whatever", "flavor:vanilla"]})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("someapp", self.manager.instances[0].name)
        self.assertEqual("vanilla", self.manager.instances[0].flavor)

    def test_start_instance_with_flavor_and_empty_tags(self):
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "vanilla",
             "description": "some cool flavor",
             "config": {"nginx_version": "1.12"}}
        )
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1",
                                                 "flavor": "vanilla", "tags": ""})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("someapp", self.manager.instances[0].name)
        self.assertEqual("vanilla", self.manager.instances[0].flavor)

    def test_start_instance_with_invalid_names_and_sizes(self):
        del os.environ["INSTANCE_LENGTH"]
        resp = self.api.post("/resources", data={"names": "someapp"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("instance name must match [0-9a-z-]", resp.data)
        resp = self.api.post("/resources", data={"name": "test_1"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("instance name must match [0-9a-z-]", resp.data)
        resp = self.api.post("/resources", data={"name": "test1#"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("instance name must match [0-9a-z-]", resp.data)
        os.environ["INSTANCE_LENGTH"] = "25"
        resp = self.api.post("/resources", data={"name": 26 * "t"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("instance name must match [0-9a-z-] and length up to 25 chars", resp.data)
        self.assertEqual([], self.manager.instances)
        del os.environ["INSTANCE_LENGTH"]
        resp = self.api.post("/resources", data={"name": 50 * "t", "team": "team1"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual(self.manager.instances[0].name, 50 * "t")

    def test_start_instance_without_team(self):
        resp = self.api.post("/resources", data={"name": "someapp"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("team name is required", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_start_instance_without_required_plan(self):
        os.environ["RPAAS_REQUIRE_PLAN"] = "1"
        try:
            resp = self.api.post("/resources", data={"name": "someapp", "team": "team1"})
            self.assertEqual(400, resp.status_code)
            self.assertEqual("plan is required", resp.data)
            self.assertEqual([], self.manager.instances)
        finally:
            del os.environ["RPAAS_REQUIRE_PLAN"]

    def test_start_instance_plan_not_found(self):
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1",
                                                 "plan": "small"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid plan", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_start_instance_flavor_not_found(self):
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1",
                                                 "flavor": "vanilla"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid flavor", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_start_instance_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources", method="POST",
                                   data={"names": "someapp"},
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_update_instance(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        self.manager.new_instance("someapp", plan_name="small")
        resp = self.api.put("/resources/someapp", data={"plan_name": "huge"})
        self.assertEqual(204, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertEqual("huge", self.manager.instances[0].plan)
        resp = self.api.put("/resources/someapp", data={"plan": "small"})
        self.assertEqual(204, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertEqual("small", self.manager.instances[0].plan)

    def test_update_instance_tag_with_flavor(self):
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "vanilla",
             "description": "some cool flavor",
             "config": {"nginx": "1.12"}}
        )
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "orange",
             "description": "some cool flavor",
             "config": {"nginx": "1.13"}}
        )
        self.manager.new_instance("someapp", flavor_name="vanilla")
        resp = self.api.put("/resources/someapp", data={"flavor": "orange"})
        self.assertEqual(204, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertEqual("orange", self.manager.instances[0].flavor)
        resp = self.api.put("/resources/someapp", data={"tags": "flavor:vanilla"})
        self.assertEqual(204, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertEqual("vanilla", self.manager.instances[0].flavor)

    def test_update_instance_not_found(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        self.manager.new_instance("someapp", plan_name="small")
        resp = self.api.put("/resources/someapp2", data={"plan_name": "huge"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_update_instance_no_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        self.manager.new_instance("someapp", plan_name="small")
        resp = self.api.put("/resources/someapp", data={"plan_name": ""})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Plan or flavor is required", resp.data)

    def test_update_invalid_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        self.manager.new_instance("someapp", plan_name="small")
        resp = self.api.put("/resources/someapp", data={"plan_name": "large"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Plan not found", resp.data)

    def test_update_invalid_flavor(self):
        self.storage.db[self.storage.flavors_collection].insert(
            {"_id": "orange",
             "description": "some cool flavor",
             "config": {"nginx": "1.13"}}
        )
        self.manager.new_instance("someapp", flavor_name="orange")
        resp = self.api.put("/resources/someapp", data={"flavor": "vanilla"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("RpaaS flavor not found", resp.data)

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
        resp = self.api.post("/resources/someapp/bind-app",
                             data={"app-host": "someapp.cloud.tsuru.io"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("null", resp.data)
        self.assertEqual("application/json", resp.mimetype)
        self.assertTrue(self.manager.instances[0].bound)

    def test_bind_without_app_host(self):
        resp = self.api.post("/resources/someapp/bind-app",
                             data={"app_hooost": "someapp.cloud.tsuru.io"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("app-host is required", resp.data)

    def test_bind_instance_not_found(self):
        resp = self.api.post("/resources/someapp/bind-app",
                             data={"app-host": "someapp.cloud.tsuru.io"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_bind_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp/bind-app", method="POST",
                                   data={"app-host": "someapp.cloud.tsuru.io"},
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_unbind(self):
        self.manager.new_instance("someapp")
        self.manager.bind("someapp", "someapp.cloud.tsuru.io")
        resp = self.api.delete("/resources/someapp/bind-app",
                               data={"app-host": "someapp.cloud.tsuru.io"},
                               headers={'Content-Type':
                                        'application/x-www-form-urlencoded'})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertFalse(self.manager.instances[0].bound)

    def test_unbind_instance_not_found(self):
        resp = self.api.delete("/resources/someapp/bind-app", data={"app-host":
                                                                    "someapp.cloud.tsuru.io"},
                               headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_unbind_unauthorized(self):
        self.set_auth_env("rpaas", "rpaas123")
        self.addCleanup(self.delete_auth_env)
        resp = self.open_with_auth("/resources/someapp/bind-app",
                                   data={"app-host": "someapp.cloud.tsuru.io"},
                                   headers={'Content-Type': 'application/x-www-form-urlencoded'},
                                   method="DELETE",
                                   user="rpaas", password="wat")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_bind_unit(self):
        resp = self.api.post("/resources/someapp/bind",
                             data={"app-host": "someapp.cloud.tsuru.io"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("", resp.data)

    def test_unbind_unit(self):
        resp = self.api.delete("/resources/someapp/bind",
                               data={"app-host": "someapp.cloud.tsuru.io"})
        self.assertEqual(200, resp.status_code)
        self.assertEqual("", resp.data)

    def test_info(self):
        self.manager.new_instance("someapp")
        resp = self.api.get("/resources/someapp")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertEqual({"name": "someapp", "plan": None}, data)

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

    def test_node_status(self):
        instance = self.manager.new_instance("someapp")
        instance.node_status = {"node-1": [{'status': 'ok', 'address': '10.10.1.1'}]}
        resp = self.api.get("/resources/someapp/node_status")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertDictEqual({"node-1": [{'status': 'ok', 'address': '10.10.1.1'}]}, data)

    def test_node_status_not_found(self):
        resp = self.api.get("/resources/someapp/node_status")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

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

    def test_restore_machine_disabled(self):
        if "RUN_RESTORE_MACHINE" in os.environ:
            del os.environ["RUN_RESTORE_MACHINE"]
        resp = self.api.post("/resources/someapp/restore_machine", data={"machine": "foo"})
        self.assertEqual(412, resp.status_code)
        self.assertEqual("Restore machine not enabled", resp.data)
        os.environ["RUN_RESTORE_MACHINE"] = "0"
        resp = self.api.post("/resources/someapp/restore_machine", data={"machine": "foo"})
        self.assertEqual(412, resp.status_code)
        self.assertEqual("Restore machine not enabled", resp.data)

    def test_restore_machine_missing_machine(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        resp = self.api.post("/resources/someapp/restore_machine")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("missing machine name", resp.data)

    def test_restore_machine_instance_not_found(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        resp = self.api.post("/resources/otherapp/restore_machine", data={"machine": "bar"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_restore_machine_instance_machine_not_found(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/restore_machine", data={"machine": "bar"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance machine not found", resp.data)

    def test_restore_machine_success(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/restore_machine", data={"machine": "foo"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("", resp.data)

    def test_cancel_restore_machine_disabled(self):
        if "RUN_RESTORE_MACHINE" in os.environ:
            del os.environ["RUN_RESTORE_MACHINE"]
        resp = self.api.delete("/resources/someapp/restore_machine", data={"machine": "foo"})
        self.assertEqual(412, resp.status_code)
        self.assertEqual("Restore machine not enabled", resp.data)

    def test_cancel_restore_machine_missing_machine(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        resp = self.api.delete("/resources/someapp/restore_machine")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("missing machine name", resp.data)

    def test_cancel_restore_machine_instance_not_found(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        resp = self.api.delete("/resources/otherapp/restore_machine", data={"machine": "bar"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance not found", resp.data)

    def test_cancel_restore_machine_instance_machine_not_found(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        self.manager.new_instance("someapp")
        resp = self.api.delete("/resources/someapp/restore_machine", data={"machine": "bar"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Instance machine not found", resp.data)

    def test_cancel_restore_machine_success(self):
        os.environ["RUN_RESTORE_MACHINE"] = "1"
        self.manager.new_instance("someapp")
        resp = self.api.delete("/resources/someapp/restore_machine", data={"machine": "foo"})
        self.assertEqual(201, resp.status_code)
        self.assertEqual("", resp.data)

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

    def test_admin_plugin(self):
        expected = inspect.getsource(admin_plugin)
        resp = self.api.get("/admin/plugin")
        self.assertEqual(200, resp.status_code)
        self.assertEqual(expected, resp.data)

    def test_update_certificate_as_file(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/certificate", data={
            'cert': (BytesIO('cert content'), ''),
            'key': (BytesIO('key content'), ''),
        })
        self.assertEqual(200, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertEqual('cert content', instance.cert)
        self.assertEqual('key content', instance.key)

    def test_update_certificate_as_form(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/certificate", data={
            'cert': BytesIO('cert content'),
            'key': BytesIO('key content'),
        })
        self.assertEqual(200, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertEqual('cert content', instance.cert)
        self.assertEqual('key content', instance.key)

    def test_add_route(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/route", data={
            'path': '/somewhere',
            'destination': 'something'
        })
        self.assertEqual(201, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertDictEqual(instance.routes.get('/somewhere'), {
            'destination': 'something',
            'content': None,
            'https_only': False
        })

    def test_add_route_forcing_https(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/route", data={
            'path': '/somewhere',
            'destination': 'something',
            'https_only': 'true'
        })
        self.assertEqual(201, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertDictEqual(instance.routes.get('/somewhere'), {
            'destination': 'something',
            'content': None,
            'https_only': True
        })

    def test_add_route_with_content(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/route", data={
            'path': '/somewhere',
            'content': 'my content'
        })
        self.assertEqual(201, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertDictEqual(instance.routes.get('/somewhere'), {
            'destination': None,
            'content': 'my content',
            'https_only': False
        })

    def test_add_route_with_utf8_content(self):
        self.manager.new_instance("someapp")
        resp = self.api.post("/resources/someapp/route", data={
            'path': '/somewhere',
            'content': 'my content ☺'
        })
        self.assertEqual(201, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertDictEqual(instance.routes.get('/somewhere'), {
            'destination': None,
            'content': 'my content ☺',
            'https_only': False
        })

    def test_delete_route(self):
        instance = self.manager.new_instance("someapp")
        instance.routes['/somewhere'] = 'true.com'
        resp = self.api.delete("/resources/someapp/route", data={
            'path': '/somewhere'
        }, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(200, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertIsNone(instance.routes.get('/somewhere'))

    def test_list_routes(self):
        instance = self.manager.new_instance("someapp")
        instance.routes = {"routes": [{'/somewhere': 'true.com'}]}
        resp = self.api.get("/resources/someapp/route")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertDictEqual({"routes": [{'/somewhere': 'true.com'}]}, data)

    def test_purge_location(self):
        resp = self.api.post("/resources/someapp/purge", data={
            'path': '/somewhere', 'preserve_path': True
        }, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(200, resp.status_code)
        self.assertEqual('Path found and purged on 3 servers', resp.data)
        resp = self.api.post("/resources/someapp/purge", data={
            'path': '/somewhere', 'preserve_path': 'False'
        }, headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assertEqual(200, resp.status_code)
        self.assertEqual('Path found and purged on 4 servers', resp.data)

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

    def test_add_block(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/block', data={
            'content': 'something',
            'block_name': 'http'
        })
        self.assertEqual(201, resp.status_code)
        _, instance = self.manager.find_instance('someapp')
        self.assertDictEqual(instance.blocks.get('http'), {
            'content': u'something',
        })

    def test_add_block_without_content(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/block', data={
            'content': None,
            'block_name': 'http'
        })
        self.assertEqual(400, resp.status_code)

    def test_add_block_without_block_name(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/block', data={
            'content': 'something',
            'block_name': None
        })
        self.assertEqual(400, resp.status_code)

    def test_add_block_not_server_http(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/block', data={
            'content': 'something',
            'block_name': 'location'
        })
        self.assertEqual(400, resp.status_code)

    def test_delete_block(self):
        instance = self.manager.new_instance("someapp")
        instance.blocks['server'] = 'true.com'
        resp = self.api.delete("/resources/someapp/block/server", headers={
            'Content-Type': 'application/x-www-form-urlencoded'
        })
        self.assertEqual(200, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertIsNone(instance.blocks.get('server'))

    def test_list_blocks(self):
        instance = self.manager.new_instance("someapp")
        instance.blocks = [{'http': 'https', 'server': 'true.com'}]
        resp = self.api.get("/resources/someapp/block")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertDictEqual({"blocks": [{'http': 'https',
                                          'server': 'true.com'}]}, data)

    def test_start_instance_with_instance_disabled_with_alternative_service(self):
        os.environ["RPAAS_NEW_SERVICE"] = "rpaas_test_new_service"
        resp = self.api.post("/resources", data={"name": "someapp", "team": "team1"})
        self.assertEqual(405, resp.status_code)
        self.assertEqual("New instance disabled. Use rpaas_test_new_service service instead", resp.data)
        del os.environ["RPAAS_NEW_SERVICE"]

    def test_add_lua(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/lua', data={
            'content': 'something',
            'lua_module_name': 'somelua',
            'lua_module_type': 'server',
        })
        self.assertEqual(201, resp.status_code)
        _, instance = self.manager.find_instance('someapp')
        self.assertDictEqual(instance.lua_modules.get('somelua').get("server"), {
            'content': u'something',
        })

    def test_add_lua_without_content(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/lua', data={
            'content': None,
            'lua_module_name': 'somelua',
            'lua_module_type': 'worker',
        })
        self.assertEqual(400, resp.status_code)

    def test_add_lua_without_lua_name(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/lua', data={
            'content': 'something',
            'lua_module_name': None,
            'lua_module_type': 'server',
        })
        self.assertEqual(400, resp.status_code)

    def test_add_lua_not_server_worker(self):
        self.manager.new_instance('someapp')
        resp = self.api.post('/resources/someapp/lua', data={
            'content': 'something',
            'lua_module_name': 'somelua',
            'lua_module_type': 'test',
        })
        self.assertEqual(400, resp.status_code)

    def test_list_lua_modules(self):
        instance = self.manager.new_instance("someapp")
        instance.lua_modules = {"somemodule": {"server": "lua code"}, "anothermodule": {"worker": "lua code"}}
        resp = self.api.get("/resources/someapp/lua")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertDictEqual({"modules": instance.lua_modules}, data)

    def test_delete_lua_module(self):
        instance = self.manager.new_instance("someapp")
        instance.lua_modules['server'] = {"somelua": "content"}
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        resp = self.api.delete("/resources/someapp/lua", headers=headers, data={
            'lua_module_name': 'somelua',
            'lua_module_type': 'server',
        })
        self.assertEqual(200, resp.status_code)
        _, instance = self.manager.find_instance("someapp")
        self.assertEquals(instance.lua_modules.get('server'), {})
