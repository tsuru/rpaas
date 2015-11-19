# coding: utf-8

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import unittest

from rpaas import plan, storage


class MongoDBStorageTestCase(unittest.TestCase):

    def setUp(self):
        self.storage = storage.MongoDBStorage()
        self.storage.db[self.storage.quota_collection].remove()
        self.storage.db[self.storage.plans_collection].remove()
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

    def test_set_team_quota(self):
        q = self.storage.set_team_quota("myteam", 8)
        used, quota = self.storage.find_team_quota("myteam")
        self.assertEqual([], used)
        self.assertEqual(8, quota)
        self.assertEqual(used, q["used"])
        self.assertEqual(quota, q["quota"])

    def test_list_plans(self):
        plans = self.storage.list_plans()
        expected = [
            {"name": "small", "description": "some cool plan",
             "config": {"serviceofferingid": "abcdef123456"}},
            {"name": "huge", "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}},
        ]
        self.assertEqual(expected, [p.to_dict() for p in plans])

    def test_find_plan(self):
        plan = self.storage.find_plan("small")
        expected = {"name": "small", "description": "some cool plan",
                    "config": {"serviceofferingid": "abcdef123456"}}
        self.assertEqual(expected, plan.to_dict())
        with self.assertRaises(storage.PlanNotFoundError):
            self.storage.find_plan("something that doesn't exist")

    def test_store_plan(self):
        p = plan.Plan(name="super_huge", description="very huge thing",
                      config={"serviceofferingid": "abcdef123"})
        self.storage.store_plan(p)
        got_plan = self.storage.find_plan(p.name)
        self.assertEqual(p.to_dict(), got_plan.to_dict())

    def test_store_plan_duplicate(self):
        p = plan.Plan(name="small", description="small thing",
                      config={"serviceofferingid": "abcdef123"})
        with self.assertRaises(storage.DuplicateError):
            self.storage.store_plan(p)

    def test_update_plan(self):
        p = plan.Plan(name="super_huge", description="very huge thing",
                      config={"serviceofferingid": "abcdef123"})
        self.storage.store_plan(p)
        self.storage.update_plan(p.name, description="wat?",
                                 config={"serviceofferingid": "abcdef123459"})
        p = self.storage.find_plan(p.name)
        self.assertEqual("super_huge", p.name)
        self.assertEqual("wat?", p.description)
        self.assertEqual({"serviceofferingid": "abcdef123459"}, p.config)

    def test_update_plan_partial(self):
        p = plan.Plan(name="super_huge", description="very huge thing",
                      config={"serviceofferingid": "abcdef123"})
        self.storage.store_plan(p)
        self.storage.update_plan(p.name, config={"serviceofferingid": "abcdef123459"})
        p = self.storage.find_plan(p.name)
        self.assertEqual("super_huge", p.name)
        self.assertEqual("very huge thing", p.description)
        self.assertEqual({"serviceofferingid": "abcdef123459"}, p.config)

    def test_update_plan_not_found(self):
        with self.assertRaises(storage.PlanNotFoundError):
            self.storage.update_plan("my_plan", description="woot")

    def test_delete_plan(self):
        p = plan.Plan(name="super_huge", description="very huge thing",
                      config={"serviceofferingid": "abcdef123"})
        self.storage.store_plan(p)
        self.storage.delete_plan(p.name)
        with self.assertRaises(storage.PlanNotFoundError):
            self.storage.find_plan(p.name)

    def test_delete_plan_not_found(self):
        with self.assertRaises(storage.PlanNotFoundError):
            self.storage.delete_plan("super_huge")

    def test_instance_metadata_storage(self):
        self.storage.store_instance_metadata("myinstance", plan="small")
        inst_metadata = self.storage.find_instance_metadata("myinstance")
        self.assertEqual({"_id": "myinstance",
                          "plan": "small"}, inst_metadata)
        self.storage.store_instance_metadata("myinstance", plan="medium")
        inst_metadata = self.storage.find_instance_metadata("myinstance")
        self.assertEqual({"_id": "myinstance", "plan": "medium"}, inst_metadata)
        self.storage.remove_instance_metadata("myinstance")
        inst_metadata = self.storage.find_instance_metadata("myinstance")
        self.assertIsNone(inst_metadata)
