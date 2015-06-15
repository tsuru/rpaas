# Copyright 2015 rpaas authors. All rights reserved.
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
    quota_collection = "quota"

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
        try:
            self.delete_binding_path(name, '/')
        except:
            pass
        self.db[self.bindings_collection].update({'_id': name}, {
            '$set': {'app_host': app_host},
            '$push': {'paths': {
                'path': '/',
                'destination': app_host
            }}
        }, upsert=True)

    def update_binding_certificate(self, name, cert, key):
        result = self.db[self.bindings_collection].update({'_id': name}, {'$set': {
            'cert': cert,
            'key': key,
        }})
        if result['n'] == 0:
            raise InstanceNotFoundError()

    def remove_binding(self, name):
        self.db[self.bindings_collection].remove({'_id': name})

    def remove_root_binding(self, name):
        self.delete_binding_path(name, '/')
        self.db[self.bindings_collection].update({'_id': name}, {
            '$unset': {'app_host': '1'}
        })

    def find_binding(self, name):
        return self.db[self.bindings_collection].find_one({'_id': name})

    def replace_binding_path(self, name, path, destination=None, content=None):
        try:
            self.delete_binding_path(name, path)
        except:
            pass
        self.db[self.bindings_collection].update({'_id': name}, {'$push': {'paths': {
            'path': path,
            'destination': destination,
            'content': content,
        }}}, upsert=True)

    def delete_binding_path(self, name, path):
        result = self.db[self.bindings_collection].update({
            '_id': name,
            'paths.path': path,
        }, {
            '$pull': {
                'paths': {
                    'path': path
                }
            }
        })
        if result['n'] == 0:
            raise InstanceNotFoundError()

    def find_team_quota(self, teamname):
        quota = self.db[self.quota_collection].find_one({'_id': teamname})
        if quota is None:
            quota = {'_id': teamname, 'used': [], 'quota': 5}
            self.db[self.quota_collection].insert(quota)
        return quota['used'], quota['quota']

    def increment_quota(self, teamname, prev_used, servicename):
        result = self.db[self.quota_collection].update(
            {'_id': teamname, 'used': prev_used},
            {'$addToSet': {'used': servicename}})
        return result['n'] == 1

    def decrement_quota(self, servicename):
        self.db[self.quota_collection].update({}, {'$pull': {'used': servicename}}, multi=True)
