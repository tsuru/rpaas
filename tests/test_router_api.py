# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import unittest
import json
import os

from rpaas import api, router_api, storage, consul_manager
from . import managers


class RouterAPITestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["MONGO_DATABASE"] = "router_api_test"
        cls.storage = storage.MongoDBStorage()
        cls.manager = managers.FakeManager(storage=cls.storage)
        router_api.get_manager = lambda: cls.manager
        cls.api = api.api.test_client()

    def setUp(self):
        self.manager.reset()
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)

    def test_add_backend(self):
        resp = self.api.post("/router/backend/someapp", data=json.dumps({"team": "team1"}),
                             content_type="application/json")
        self.assertEqual(201, resp.status_code)
        self.assertEqual("router-someapp", self.manager.instances[0].name)

    def test_add_backend_alternative_team_field(self):
        resp = self.api.post("/router/backend/someapp", data=json.dumps({"tsuru.io/app-teamowner": "team1"}),
                             content_type="application/json")
        self.assertEqual(201, resp.status_code)
        self.assertEqual("router-someapp", self.manager.instances[0].name)

    def test_add_backend_without_team(self):
        resp = self.api.post("/router/backend/someapp", data=json.dumps({"team": ""}),
                             content_type="application/json")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("team name is required", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_add_backend_with_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        resp = self.api.post("/router/backend/someapp", data=json.dumps({"team": "team1", "plan": "small"}),
                             content_type="application/json")
        self.assertEqual(201, resp.status_code)
        self.assertEqual("router-someapp", self.manager.instances[0].name)
        self.assertEqual("small", self.manager.instances[0].plan)

    def test_get_backend(self):
        self.manager.new_instance("router-someapp", state='10.0.0.5')
        resp = self.api.get("/router/backend/someapp")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertDictEqual({'address': '10.0.0.5'}, data)

    def test_get_backend_not_found(self):
        resp = self.api.get("/router/backend/someapp")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Backend not found", resp.data)

    def test_get_backend_pending(self):
        self.manager.new_instance("router-someapp", state="pending")
        resp = self.api.get("/router/backend/someapp")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertDictEqual({'address': ''}, data)

    def test_get_backend_error(self):
        self.manager.new_instance("router-someapp", state="failure")
        resp = self.api.get("/router/backend/someapp")
        self.assertEqual(500, resp.status_code)

    def test_update_backend(self):
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
        self.manager.new_instance("router-someapp", plan_name="small")
        resp = self.api.put("/router/backend/someapp", data=json.dumps({"plan": "huge"}),
                            content_type="application/json")
        self.assertEqual("", resp.data)
        self.assertEqual(204, resp.status_code)
        self.assertEqual("huge", self.manager.instances[0].plan)

    def test_update_backend_not_found(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        resp = self.api.put("/router/backend/someapp2", data=json.dumps({"plan": "huge"}),
                            content_type="application/json")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Backend not found", resp.data)

    def test_update_backend_no_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.manager.new_instance("router-someapp", plan_name="small")
        resp = self.api.put("/router/backend/someapp", data=json.dumps({"plan": ""}),
                            content_type="application/json")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("Plan is required", resp.data)

    def test_update_backend_plan_not_found(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        self.manager.new_instance("router-someapp", plan_name="small")
        resp = self.api.put("/router/backend/someapp", data=json.dumps({"plan": "p1"}),
                            content_type="application/json")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Plan not found", resp.data)

    def test_delete_backend(self):
        self.manager.new_instance("router-someapp")
        resp = self.api.delete("/router/backend/someapp")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_delete_backend_not_found(self):
        resp = self.api.delete("/router/backend/someapp")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Backend not found", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_delete_backend_swap_enabled_error(self):
        resp = self.api.delete("/router/backend/swap_error")
        self.assertEqual(412, resp.status_code)
        self.assertEqual("Instance with swap enabled", resp.data)
        self.assertEqual([], self.manager.instances)

    def test_list_routes(self):
        self.manager.new_instance("router-someapp")
        self.manager.add_upstream(
            "router-someapp", "router-someapp", "10.0.0.1:123")
        self.manager.add_upstream(
            "router-someapp", "router-someapp", "10.0.0.2:123")
        resp = self.api.get("/router/backend/someapp/routes")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertEqual(["http://10.0.0.1:123", "http://10.0.0.2:123"],
                         sorted(data['addresses']))

    def test_list_routes_empty(self):
        self.manager.new_instance("router-someapp")
        resp = self.api.get("/router/backend/someapp/routes")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("application/json", resp.mimetype)
        data = json.loads(resp.data)
        self.assertDictEqual({'addresses': []}, data)

    def test_add_routes(self):
        self.manager.new_instance("router-someapp")
        resp = self.api.post("/router/backend/someapp/routes", data=json.dumps({'addresses': ['addr1', 'addr2']}),
                             content_type="application/json")
        self.assertEqual(200, resp.status_code)
        routes = self.manager.list_upstreams(
            "router-someapp", "router-someapp")
        self.assertEqual(["addr1", "addr2"], sorted(list(routes)))

    def test_get_status(self):
        instance = self.manager.new_instance("router-someapp")
        instance.node_status = {'vm-1': {'status': 'OK', 'address': '10.1.1.1'},
                                'vm-2': {'status': 'DEAD', 'address': '10.2.2.2'}}
        resp = self.api.get("/router/backend/someapp/status")
        self.assertEqual(200, resp.status_code)
        self.assertEqual(resp.data, '{"status": "vm-1 - 10.1.1.1: OK\\nvm-2 - 10.2.2.2: DEAD"}')

    def test_remove_routes(self):
        self.manager.new_instance("router-someapp")
        self.manager.add_upstream(
            "router-someapp", "router-someapp", "10.0.0.1:123")
        self.manager.add_upstream(
            "router-someapp", "router-someapp", "10.0.0.2:123")
        resp = self.api.post("/router/backend/someapp/routes/remove", data=json.dumps({'addresses': ["10.0.0.2:123"]}),
                             content_type="application/json")
        self.assertEqual(200, resp.status_code)
        routes = self.manager.list_upstreams(
            "router-someapp", "router-someapp")
        self.assertEqual(["10.0.0.1:123"], sorted(list(routes)))

    def test_remove_all_routes(self):
        self.manager.new_instance("router-someapp")
        self.manager.add_upstream(
            "router-someapp", "router-someapp", "10.0.0.1:123")
        self.manager.add_upstream(
            "router-someapp", "router-someapp", "10.0.0.2:123")
        self.manager.bind("router-someapp", "router-someapp")
        self.assertTrue(self.manager.check_bound("router-someapp"))
        resp = self.api.post("/router/backend/someapp/routes/remove", data=json.dumps({'addresses': ["10.0.0.2:123",
                                                                                                     "10.0.0.1:123"]}),
                             content_type="application/json")
        self.assertEqual(200, resp.status_code)
        routes = self.manager.list_upstreams(
            "router-someapp", "router-someapp")
        self.assertEqual(set([]), routes)
        routes = self.manager.list_routes("router-someapp")
        self.assertFalse(self.manager.check_bound("router-someapp"))

    def test_swap_success(self):
        self.manager.new_instance("router-app1")
        self.manager.new_instance("router-app2")
        resp = self.api.post("/router/backend/app1/swap", data=json.dumps({'target': 'app2'}),
                             content_type="application/json")
        self.assertEqual(200, resp.status_code)

    def test_swap_empty_json_error(self):
        resp = self.api.post("/router/backend/app1/swap", data=json.dumps({}),
                             content_type="application/json")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("Could not decode body json", resp.data)

    def test_swap_cname_only_not_suppported_error(self):
        resp = self.api.post("/router/backend/app1/swap", data=json.dumps({'target': 'app2', 'cnameOnly': 'true'}),
                             content_type="application/json")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("Swap cname only not supported", resp.data)

    def test_swap_target_instance_empty_error(self):
        resp = self.api.post("/router/backend/app1/swap", data=json.dumps({'a': 'b'}),
                             content_type="application/json")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("Target instance cannot be empty", resp.data)

    def test_swap_target_backend_not_found_error(self):
        resp = self.api.post("/router/backend/app1/swap", data=json.dumps({'target': 'app2'}),
                             content_type="application/json")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Backend not found", resp.data)

    def test_swap_instance_already_swapped_error(self):
        self.manager.new_instance("router-app1")
        resp = self.api.post("/router/backend/app1/swap", data=json.dumps({'target': 'app2'}),
                             content_type="application/json")
        self.assertEqual(412, resp.status_code)
        self.assertEqual("Instance already swapped", resp.data)

    def test_get_certificate_success(self):
        self.manager.new_instance("router-someapp")
        self.manager.update_certificate("router-someapp", "cert", "key")
        resp = self.api.get("/router/backend/someapp/certificate/test.com")
        self.assertEqual(200, resp.status_code)
        data = json.loads(resp.data)
        self.assertDictEqual({'certificate': 'cert'}, data)

    def test_get_certificate_instance_not_found_error(self):
        resp = self.api.get("/router/backend/someapp/certificate/test.com")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Backend not found", resp.data)

    def test_get_certificate_not_found_error(self):
        self.manager.new_instance("router-someapp")
        resp = self.api.get("/router/backend/someapp/certificate/test.com")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Certificate not found", resp.data)

    def test_update_certificate_sucess(self):
        self.manager.new_instance("router-someapp")
        with self.assertRaises(consul_manager.CertificateNotFoundError):
            self.manager.get_certificate("router-someapp")
        resp = self.api.put("/router/backend/someapp/certificate/test.com",
                            data=json.dumps({'certificate': 'cert', 'key': 'key'}),
                            content_type="application/json")
        self.assertEqual(200, resp.status_code)
        certificate, key = self.manager.get_certificate("router-someapp")
        self.assertEqual(certificate, "cert")
        self.assertEqual(key, "key")

    def test_update_certificate_instance_not_found_error(self):
        resp = self.api.put("/router/backend/someapp/certificate/test.com",
                            data=json.dumps({'certificate': 'cert', 'key': 'key'}),
                            content_type="application/json")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Backend not found", resp.data)

    def test_update_certificate_key_or_certificate_missing_error(self):
        resp = self.api.put("/router/backend/someapp/certificate/test.com",
                            data=json.dumps({'certificate': 'cert'}),
                            content_type="application/json")
        self.assertEqual(400, resp.status_code)
        self.assertEqual("Certificate or key is missing", resp.data)

    def test_delete_certificate_success(self):
        self.manager.new_instance("router-someapp")
        self.manager.update_certificate("router-someapp", "cert", "key")
        resp = self.api.delete("/router/backend/someapp/certificate/test.com")
        self.assertEqual(200, resp.status_code)
        with self.assertRaises(consul_manager.CertificateNotFoundError):
            self.manager.get_certificate("router-someapp")

    def test_delete_certificate_instance_not_found_error(self):
        resp = self.api.delete("/router/backend/someapp/certificate/test.com")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("Backend not found", resp.data)
