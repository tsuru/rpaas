# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

from hm import storage


class InstanceNotFoundError(Exception):
    pass


class MongoDBStorage(storage.MongoDBStorage):
    hcs_collections = "hcs"
    tasks_collection = "tasks"

    def store_hc(self, hc):
        self.db[self.hcs_collections].update({"name": hc["name"]}, hc, upsert=True)

    def retrieve_hc(self, name):
        hc = self.db[self.hcs_collections].find_one({"name": name})
        if hc:
            del hc["_id"]
        return hc

    def remove_hc(self, name):
        self.db[self.hcs_collections].remove({"name": name})

    def store_task(self, name, task_id):
        self.db[self.tasks_collection].insert({'_id': name, 'task_id': task_id})

    def remove_task(self, name):
        self.db[self.tasks_collection].remove({'_id': name})

    def find_task(self, name):
        return self.db[self.tasks_collection].find_one({'_id': name})
