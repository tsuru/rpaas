# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json
import unittest

from rpaas import api, admin_api, storage
from . import managers


class AdminAPITestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        admin_api.register_views(api.api, api.plans)
        cls.storage = storage.MongoDBStorage()
        cls.manager = managers.FakeManager(storage=cls.storage)
        api.get_manager = lambda: cls.manager
        cls.api = api.api.test_client()

    def setUp(self):
        self.manager.reset()
        self.storage.db[self.storage.plans_collection].remove()

    def test_list_plans(self):
        resp = self.api.get("/admin/plans")
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

    def test_create_plan(self):
        data = {
            "name": "small",
            "description": "small instance",
            "config": {"serviceofferingid": "abcdef1234", "NAME": "super"},
        }
        raw_data = json.dumps(data)
        resp = self.api.post("/admin/plans", data=raw_data,
                             headers={"Content-Type": "application/json"})
        self.assertEqual(201, resp.status_code)
        plan = self.storage.find_plan("small")
        self.assertEqual("small", plan.name)
        self.assertEqual("small instance", plan.description)
        self.assertEqual(data["config"], plan.config)

    def test_create_plan_duplicate(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        data = json.dumps({"name": "small",
                           "description": "small instance",
                           "config": {
                               "serviceofferingid": "abcdef1234",
                               "NAME": "super",
                           }})
        resp = self.api.post("/admin/plans", data=data,
                             headers={"Content-Type": "application/json"})
        self.assertEqual(409, resp.status_code)

    def test_create_plan_invalid(self):
        config = {"serviceofferingid": "abcdef1234", "NAME": "super"}
        resp = self.api.post("/admin/plans",
                             data=json.dumps({"description": "small instance", "config": config}),
                             headers={"Content-Type": "application/json"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid plan - name is required", resp.data)
        resp = self.api.post("/admin/plans",
                             data=json.dumps({"name": "small", "config": config}),
                             headers={"Content-Type": "application/json"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid plan - description is required", resp.data)
        resp = self.api.post("/admin/plans",
                             data=json.dumps({"name": "small", "description": "something small"}),
                             headers={"Content-Type": "application/json"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid plan - config is required", resp.data)

    def test_retrieve_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        plan = self.storage.find_plan("small")
        resp = self.api.get("/admin/plans/small")
        self.assertEqual(200, resp.status_code)
        self.assertEqual(plan.to_dict(), json.loads(resp.data))

    def test_retrieve_plan_not_found(self):
        resp = self.api.get("/admin/plans/small")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("plan not found", resp.data)

    def test_update_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        config = {"serviceofferingid": "abcdef1234", "NAME": "super"}
        resp = self.api.put("/admin/plans/small",
                            data=json.dumps({"description": "small instance", "config": config}),
                            headers={"Content-Type": "application/json"})
        self.assertEqual(200, resp.status_code)
        plan = self.storage.find_plan("small")
        self.assertEqual("small", plan.name)
        self.assertEqual("small instance", plan.description)
        self.assertEqual(config, plan.config)

    def test_update_plan_partial(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        config = {"serviceofferingid": "abcdef1234", "NAME": "super"}
        resp = self.api.put("/admin/plans/small",
                            data=json.dumps({"config": config}),
                            headers={"Content-Type": "application/json"})
        self.assertEqual(200, resp.status_code)
        plan = self.storage.find_plan("small")
        self.assertEqual("small", plan.name)
        self.assertEqual("some cool plan", plan.description)
        self.assertEqual(config, plan.config)

    def test_update_plan_not_found(self):
        config = {"serviceofferingid": "abcdef1234", "NAME": "super"}
        resp = self.api.put("/admin/plans/small",
                            data=json.dumps({"config": config}),
                            headers={"Content-Type": "application/json"})
        self.assertEqual(404, resp.status_code)
        self.assertEqual("plan not found", resp.data)

    def test_delete_plan(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        resp = self.api.delete("/admin/plans/small")
        self.assertEqual(200, resp.status_code)
        with self.assertRaises(storage.PlanNotFoundError):
            self.storage.find_plan("small")

    def test_delete_plan_not_found(self):
        resp = self.api.delete("/admin/plans/small")
        self.assertEqual(404, resp.status_code)
        self.assertEqual("plan not found", resp.data)
