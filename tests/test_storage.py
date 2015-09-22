# coding: utf-8

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import unittest

from rpaas import storage


class MongoDBStorageTestCase(unittest.TestCase):

    def setUp(self):
        self.storage = storage.MongoDBStorage()
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
