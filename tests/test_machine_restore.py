# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime
import time
import unittest
import redis
from freezegun import freeze_time
from mock import patch, call
from rpaas import storage, tasks
from rpaas import scheduler
from hm import managers, log
from hm.model.host import Host

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class FakeManager(managers.BaseManager):

    host_id = 0
    hosts = ['10.2.2.2', '10.1.1.1']

    def __init__(self, config=None):
        super(FakeManager, self).__init__(config)

    def create_host(self, name=None, alternative_id=0):
        id = self.host_id
        FakeManager.host_id += 1
        return Host(id=id, dns_name=FakeManager.hosts.pop(), alternative_id=alternative_id)

    def restore_host(self, id):
        log.logging.info("Machine {} restored".format(id))

    def destroy_host(self, id):
        log.logging.info("Machine {} destroyed".format(id))


managers.register('fake', FakeManager)


@freeze_time("2016-02-03 12:00:00")
class RestoreMachineTestCase(unittest.TestCase):

    def setUp(self):
        self.config = {
            "MONGO_DATABASE": "machine_restore_test",
            "RPAAS_SERVICE_NAME": "test_rpaas_machine_restore",
            "RESTORE_MACHINE_RUN_INTERVAL": 2,
            "HOST_MANAGER": "fake"
        }

        self.storage = storage.MongoDBStorage(self.config)
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)

        now = datetime.datetime.utcnow()
        tasks = [
            {"_id": "restore_10.1.1.1", "host": "10.1.1.1",
             "created": now - datetime.timedelta(minutes=8)},
            {"_id": "restore_10.2.2.2", "host": "10.2.2.2",
             "created": now - datetime.timedelta(minutes=3)}
        ]

        for task in tasks:
            Host.create("fake", "my-group", self.config)
            self.storage.store_task(task)

        redis.StrictRedis().delete("restore_machine:last_run")

    def tearDown(self):
        self.storage.db[self.storage.tasks_collection].remove()
        self.storage.db[self.storage.hosts_collection].remove()

    @patch("hm.log.logging")
    def test_restore_machine(self, log):
        restorer = scheduler.RestoreMachine(self.config)
        restorer.start()
        time.sleep(1)
        restorer.stop()
        self.assertIsNone(self.storage.find_task("restore_10.1.1.1"))
        self.assertEqual(log.info.call_args, call("Machine 0 restored"))
