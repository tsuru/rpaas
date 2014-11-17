# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import pymongo.errors

from hm import storage


class InstanceNotFoundError(Exception):
    pass


class DuplicateError(Exception):
    pass


class MongoDBStorage(storage.MongoDBStorage):
    hcs_collections = "hcs"
    tasks_collection = "tasks"
    bindings_collection = "bindings"

    def store_hc(self, hc):
        self.db[self.hcs_collections].update({"_id": hc["_id"]}, hc, upsert=True)

    def retrieve_hc(self, name):
        return self.db[self.hcs_collections].find_one({"_id": name})

    def remove_hc(self, name):
        self.db[self.hcs_collections].remove({"_id": name})

    def store_task(self, name):
        try:
            self.db[self.tasks_collection].insert({'_id': name})
        except pymongo.errors.DuplicateKeyError:
            raise DuplicateError(name)

    def remove_task(self, name):
        self.db[self.tasks_collection].remove({'_id': name})

    def update_task(self, name, task_id):
        self.db[self.tasks_collection].update({'_id': name}, {'$set': {'task_id': task_id}})

    def find_task(self, name):
        return self.db[self.tasks_collection].find_one({'_id': name})

    def store_binding(self, name, app_host):
        self.db[self.bindings_collection].insert({'_id': name, 'app_host': app_host})

    def update_binding_certificate(self, name, cert, key):
        result = self.db[self.bindings_collection].update({'_id': name}, {'$set': {
            'cert': cert,
            'key': key,
        }})
        if result['n'] == 0:
            raise InstanceNotFoundError()

    def remove_binding(self, name):
        self.db[self.bindings_collection].remove({'_id': name})

    def find_binding(self, name):
        return self.db[self.bindings_collection].find_one({'_id': name})

    def add_binding_redirect(self, name, path, destination):
        result = self.db[self.bindings_collection].update({'_id': name}, {'$addToSet': {'redirects': {
            'path': path,
            'destination': destination,
        }}})
        if result['n'] == 0:
            raise InstanceNotFoundError()

    def delete_binding_redirect(self, name, path):
        result = self.db[self.bindings_collection].update({
            '_id': name,
            'redirects.path': path,
        }, {
            '$pull': {
                'redirects': {
                    'path': path
                }
            }
        })
        if result['n'] == 0:
            raise InstanceNotFoundError()
