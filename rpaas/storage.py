# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime

import pymongo.errors

from hm import storage

from rpaas import plan


class InstanceNotFoundError(Exception):
    pass


class PlanNotFoundError(Exception):
    pass


class DuplicateError(Exception):
    pass


class MongoDBStorage(storage.MongoDBStorage):
    hcs_collections = "hcs"
    tasks_collection = "tasks"
    bindings_collection = "bindings"
    plans_collection = "plans"
    instance_metadata_collection = "instance_metadata"
    quota_collection = "quota"
    le_certificates_collection = "le_certificates"

    def store_hc(self, hc):
        self.db[self.hcs_collections].update({"_id": hc["_id"]}, hc, upsert=True)

    def retrieve_hc(self, name):
        return self.db[self.hcs_collections].find_one({"_id": name})

    def remove_hc(self, name):
        self.db[self.hcs_collections].remove({"_id": name})

    def store_task(self, name):
        try:
            if name.__class__ is dict:
                self.db[self.tasks_collection].insert(name)
            else:
                self.db[self.tasks_collection].insert({'_id': name})
        except pymongo.errors.DuplicateKeyError:
            raise DuplicateError(name)

    def remove_task(self, query):
        self.db[self.tasks_collection].remove(query)

    def update_task(self, name, task_id_or_spec):
        if task_id_or_spec.__class__ is dict:
            self.db[self.tasks_collection].update({'_id': name}, {'$set': task_id_or_spec})
        else:
            self.db[self.tasks_collection].update({'_id': name}, {'$set': {'task_id': task_id_or_spec}})

    def find_task(self, query):
        if query.__class__ is dict:
            return self.db[self.tasks_collection].find(query)
        return self.db[self.tasks_collection].find_one(query)

    def store_instance_metadata(self, instance_name, **data):
        data['_id'] = instance_name
        self.db[self.instance_metadata_collection].update({'_id': instance_name},
                                                          data, upsert=True)

    def find_instance_metadata(self, instance_name):
        return self.db[self.instance_metadata_collection].find_one({'_id': instance_name})

    def find_host_id(self, name):
        return self.db[self.hosts_collection].find_one({'dns_name': name})

    def remove_instance_metadata(self, instance_name):
        self.db[self.instance_metadata_collection].remove({'_id': instance_name})

    def store_plan(self, plan):
        plan.validate()
        d = plan.to_dict()
        d["_id"] = d["name"]
        del d["name"]
        try:
            self.db[self.plans_collection].insert(d)
        except pymongo.errors.DuplicateKeyError:
            raise DuplicateError(plan.name)

    def update_plan(self, name, description=None, config=None):
        update = {}
        if description:
            update["description"] = description
        if config:
            update["config"] = config
        if update:
            result = self.db[self.plans_collection].update({"_id": name},
                                                           {"$set": update})
            if not result.get("updatedExisting"):
                raise PlanNotFoundError()

    def delete_plan(self, name):
        result = self.db[self.plans_collection].remove({"_id": name})
        if result.get("n", 0) < 1:
            raise PlanNotFoundError()

    def find_plan(self, name):
        plan_dict = self.db[self.plans_collection].find_one({'_id': name})
        if not plan_dict:
            raise PlanNotFoundError()
        return self._plan_from_dict(plan_dict)

    def list_plans(self):
        plan_list = self.db[self.plans_collection].find()
        return [self._plan_from_dict(p) for p in plan_list]

    def _plan_from_dict(self, dict):
        dict["name"] = dict["_id"]
        del dict["_id"]
        return plan.Plan(**dict)

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

    def set_team_quota(self, teamname, quota):
        q = self._find_team_quota(teamname)
        q['quota'] = quota
        self.db[self.quota_collection].update({'_id': teamname}, {'$set': {'quota': quota}})
        return q

    def find_team_quota(self, teamname):
        quota = self._find_team_quota(teamname)
        return quota['used'], quota['quota']

    def _find_team_quota(self, teamname):
        quota = self.db[self.quota_collection].find_one({'_id': teamname})
        if quota is None:
            quota = {'_id': teamname, 'used': [], 'quota': 5}
            self.db[self.quota_collection].insert(quota)
        return quota

    def increment_quota(self, teamname, prev_used, servicename):
        result = self.db[self.quota_collection].update(
            {'_id': teamname, 'used': prev_used},
            {'$addToSet': {'used': servicename}})
        return result['n'] == 1

    def decrement_quota(self, servicename):
        self.db[self.quota_collection].update({}, {'$pull': {'used': servicename}}, multi=True)

    def store_le_certificate(self, name, domain):
        doc = {"_id": name, "domain": domain,
               "created": datetime.datetime.utcnow()}
        self.db[self.le_certificates_collection].update({"_id": name}, doc,
                                                        upsert=True)

    def remove_le_certificate(self, name, domain):
        self.db[self.le_certificates_collection].remove({"_id": name, "domain": domain})

    def find_le_certificates(self, query):
        if "name" in query:
            query["_id"] = query["name"]
            del query["name"]
        certificates = self.db[self.le_certificates_collection].find(query)
        for certificate in certificates:
            certificate["name"] = certificate["_id"]
            del certificate["_id"]
            yield certificate
