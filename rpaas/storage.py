# Copyright 2014 varnishapi authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

from hm import storage


class InstanceNotFoundError(Exception):
    pass


class MongoDBStorage(storage.MongoDBStorage):
    hcs_collections = "hcs"

    def store_hc(self, hc):
        self.db[self.hcs_collections].update({"name": hc["name"]}, hc, upsert=True)

    def retrieve_hc(self, name):
        hc = self.db[self.hcs_collections].find_one({"name": name})
        if hc:
            del hc["_id"]
        return hc

    def remove_hc(self, name):
        self.db[self.hcs_collections].remove({"name": name})
