# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json
import unittest
import os

from rpaas import api, admin_api, storage
from . import managers


class AdminAPITestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        admin_api.register_views(api.api, api.plans)
        os.environ["MONGO_DATABASE"] = "api_admin_test"
        cls.storage = storage.MongoDBStorage()
        cls.manager = managers.FakeManager(storage=cls.storage)
        api.get_manager = lambda: cls.manager
        cls.api = api.api.test_client()

    def setUp(self):
        self.manager.reset()
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)

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
        config = json.dumps({
            "serviceofferingid": "abcdef1234",
            "NAME": "super",
        })
        resp = self.api.post("/admin/plans", data={"name": "small",
                                                   "description": "small instance",
                                                   "config": config})
        self.assertEqual(201, resp.status_code)
        plan = self.storage.find_plan("small")
        self.assertEqual("small", plan.name)
        self.assertEqual("small instance", plan.description)
        self.assertEqual(json.loads(config), plan.config)

    def test_create_plan_duplicate(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        config = json.dumps({
            "serviceofferingid": "abcdef1234",
            "NAME": "super",
        })
        resp = self.api.post("/admin/plans", data={"name": "small",
                                                   "description": "small instance",
                                                   "config": config})
        self.assertEqual(409, resp.status_code)

    def test_create_plan_invalid(self):
        config = json.dumps({
            "serviceofferingid": "abcdef1234",
            "NAME": "super",
        })
        resp = self.api.post("/admin/plans", data={"description": "small instance",
                                                   "config": config})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid plan - name is required", resp.data)
        resp = self.api.post("/admin/plans", data={"name": "small",
                                                   "config": config})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("invalid plan - description is required", resp.data)
        resp = self.api.post("/admin/plans", data={"name": "small",
                                                   "description": "something small"})
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
        config = json.dumps({
            "serviceofferingid": "abcdef1234",
            "NAME": "super",
        })
        resp = self.api.put("/admin/plans/small", data={"description": "small instance",
                                                        "config": config})
        self.assertEqual(200, resp.status_code)
        plan = self.storage.find_plan("small")
        self.assertEqual("small", plan.name)
        self.assertEqual("small instance", plan.description)
        self.assertEqual(json.loads(config), plan.config)

    def test_update_plan_partial(self):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "small",
             "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}}
        )
        config = json.dumps({
            "serviceofferingid": "abcdef1234",
            "NAME": "super",
        })
        resp = self.api.put("/admin/plans/small", data={"config": config})
        self.assertEqual(200, resp.status_code)
        plan = self.storage.find_plan("small")
        self.assertEqual("small", plan.name)
        self.assertEqual("some cool plan", plan.description)
        self.assertEqual(json.loads(config), plan.config)

    def test_update_plan_not_found(self):
        config = json.dumps({
            "serviceofferingid": "abcdef1234",
            "NAME": "super",
        })
        resp = self.api.put("/admin/plans/small", data={"description": "small instance",
                                                        "config": config})
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

    def test_view_team_quota(self):
        self.storage.db[self.storage.quota_collection].insert(
            {"_id": "myteam",
             "used": ["inst1", "inst2"],
             "quota": 10}
        )
        resp = self.api.get("/admin/quota/myteam")
        self.assertEqual(200, resp.status_code)
        self.assertEqual({"used": ["inst1", "inst2"], "quota": 10},
                         json.loads(resp.data))
        resp = self.api.get("/admin/quota/yourteam")
        self.assertEqual(200, resp.status_code)
        self.assertEqual({"used": [], "quota": 5}, json.loads(resp.data))

    def test_set_team_quota(self):
        self.storage.db[self.storage.quota_collection].insert(
            {"_id": "myteam",
             "used": ["inst1", "inst2"],
             "quota": 10}
        )
        resp = self.api.post("/admin/quota/myteam", data={"quota": 12})
        self.assertEqual(200, resp.status_code)
        used, quota = self.storage.find_team_quota("myteam")
        self.assertEqual(["inst1", "inst2"], used)
        self.assertEqual(12, quota)
        resp = self.api.post("/admin/quota/yourteam", data={"quota": 3})
        self.assertEqual(200, resp.status_code)
        used, quota = self.storage.find_team_quota("yourteam")
        self.assertEqual([], used)
        self.assertEqual(3, quota)

    def test_set_team_quota_invalid_value(self):
        resp = self.api.post("/admin/quota/myteam", data={})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("quota must be an integer value greather than 0", resp.data)
        resp = self.api.post("/admin/quota/myteam", data={"quota": "abc"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("quota must be an integer value greather than 0", resp.data)
        resp = self.api.post("/admin/quota/myteam", data={"quota": "0"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("quota must be an integer value greather than 0", resp.data)
        resp = self.api.post("/admin/quota/myteam", data={"quota": "-3"})
        self.assertEqual(400, resp.status_code)
        self.assertEqual("quota must be an integer value greather than 0", resp.data)
