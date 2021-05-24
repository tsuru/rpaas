# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime
import time
import unittest
import redis

from freezegun import freeze_time
from mock import patch, call
from rpaas import storage, tasks
from rpaas import healing, consul_manager
from hm import managers, log
from hm.model.host import Host
from requests.exceptions import ConnectionError

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class RestoreHostError(Exception):
    pass


class FakeManager(managers.BaseManager):

    host_id = 0
    hosts = []
    fail_ids = []

    def __init__(self, config=None):
        super(FakeManager, self).__init__(config)

    def create_host(self, name=None, alternative_id=0):
        id = self.host_id
        FakeManager.host_id += 1
        return Host(id=id, dns_name=FakeManager.hosts.pop(0), alternative_id=alternative_id)

    def restore_host(self, id, reset_template=False, reset_tags=False):
        if id in self.fail_ids:
            raise RestoreHostError(ConnectionError("iaas restore error"))
        log.logging.info("Machine {} restored".format(id))

    def start_host(self, id):
        pass

    def stop_host(self, id, forced=False):
        pass

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
            {"_id": "restore_10.1.1.1", "host": "10.1.1.1", "instance": "foo",
             "created": now - datetime.timedelta(minutes=8)},
            {"_id": "restore_10.2.2.2", "host": "10.2.2.2", "instance": "bar",
             "created": now - datetime.timedelta(minutes=3)},
            {"_id": "restore_10.3.3.3", "host": "10.3.3.3", "instance": "foo",
             "created": now - datetime.timedelta(minutes=5)},
            {"_id": "restore_10.4.4.4", "host": "10.4.4.4", "instance": "foo",
             "created": now - datetime.timedelta(minutes=10)},
            {"_id": "restore_10.5.5.5", "host": "10.5.5.5", "instance": "bar",
             "created": now - datetime.timedelta(minutes=15)},
        ]
        FakeManager.host_id = 0
        FakeManager.hosts = ['10.1.1.1', '10.2.2.2', '10.3.3.3', '10.4.4.4', '10.5.5.5']

        for task in tasks:
            Host.create("fake", task['instance'], self.config)
            self.storage.store_task(task)

        redis.StrictRedis().flushall()

    def tearDown(self):
        FakeManager.fail_ids = []

    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_success(self, log, nginx):
        nginx_manager = nginx.Nginx.return_value
        restorer = healing.RestoreMachine(self.config)
        restorer.start()
        time.sleep(1)
        restorer.stop()
        self.assertEqual(log.info.call_args_list, [call("Machine 0 restored"), call("Machine 2 restored"),
                                                   call("Machine 3 restored"), call("Machine 4 restored")])
        nginx_expected_calls = [call('10.1.1.1', timeout=600), call('10.3.3.3', timeout=600),
                                call('10.4.4.4', timeout=600), call('10.5.5.5', timeout=600)]
        self.assertEqual(nginx_expected_calls, nginx_manager.wait_healthcheck.call_args_list)
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(tasks, ['restore_10.2.2.2'])

    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_dry_mode(self, log, nginx):
        self.config['RESTORE_MACHINE_DRY_MODE'] = "1"
        nginx_manager = nginx.Nginx.return_value
        restorer = healing.RestoreMachine(self.config)
        restorer.start()
        time.sleep(1)
        restorer.stop()
        self.assertListEqual(log.info.call_args_list, [])
        self.assertListEqual(nginx_manager.wait_healthcheck.call_args_list, [])
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(tasks, ['restore_10.2.2.2'])

    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_iaas_fail(self, log, nginx):
        FakeManager.fail_ids = [2]
        restorer = healing.RestoreMachine(self.config)
        nginx_manager = nginx.Nginx.return_value
        restorer.start()
        time.sleep(1)
        restorer.stop()
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(['restore_10.2.2.2', 'restore_10.3.3.3',
                              'restore_10.4.4.4', 'restore_10.5.5.5'], tasks)
        self.assertEqual(log.info.call_args_list, [call("Machine 0 restored")])
        self.assertEqual(nginx_manager.wait_healthcheck.call_args_list, [call('10.1.1.1', timeout=600)])
        log.reset_mock()
        nginx.reset_mock()
        redis.StrictRedis().delete("restore_machine:test_rpaas_machine_restore:last_run")
        restorer = healing.RestoreMachine(self.config)
        restorer.start()
        time.sleep(1)
        restorer.stop()
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertEqual(log.info.call_args_list, [call("Machine 4 restored")])
        self.assertEqual(nginx_manager.wait_healthcheck.call_args_list, [call('10.5.5.5', timeout=600)])
        self.assertListEqual(['restore_10.2.2.2', 'restore_10.3.3.3', 'restore_10.4.4.4'], tasks)
        log.reset_mock()
        nginx.reset_mock()
        redis.StrictRedis().delete("restore_machine:test_rpaas_machine_restore:last_run")
        FakeManager.fail_ids = []
        with freeze_time("2016-02-03 12:06:00"):
            restorer = healing.RestoreMachine(self.config)
            restorer.start()
            time.sleep(1)
            restorer.stop()
            tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
            self.assertEqual(log.info.call_args_list, [call("Machine 1 restored"), call("Machine 2 restored"),
                                                       call("Machine 3 restored")])
            nginx_expected_calls = [call('10.2.2.2', timeout=600),
                                    call('10.3.3.3', timeout=600),
                                    call('10.4.4.4', timeout=600)]
            self.assertEqual(nginx_expected_calls, nginx_manager.wait_healthcheck.call_args_list)
            self.assertListEqual(tasks, [])

    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_ignore_restore_on_locking(self, log, nginx):
        redis_lock = redis.StrictRedis().lock('restore_lock', timeout=600, blocking_timeout=1)
        self.assertTrue(redis_lock.acquire(blocking=False))
        restorer = healing.RestoreMachine(self.config)
        nginx_manager = nginx.Nginx.return_value
        restorer.start()
        time.sleep(1)
        restorer.stop()
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(['restore_10.1.1.1', 'restore_10.2.2.2', 'restore_10.3.3.3',
                              'restore_10.4.4.4', 'restore_10.5.5.5'], tasks)
        self.assertEqual(log.info.call_args_list, [])
        self.assertEqual(nginx_manager.wait_healthcheck.call_args_list, [])
        redis_lock.release()

    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_removing_locking_on_success(self, log, nginx):
        redis_lock = redis.StrictRedis().lock('restore_lock', timeout=600, blocking_timeout=1)
        self.assertTrue(redis_lock.acquire(blocking=False))
        redis_lock.release()
        restorer = healing.RestoreMachine(self.config)
        nginx_manager = nginx.Nginx.return_value
        restorer = healing.RestoreMachine(self.config)
        restorer.start()
        time.sleep(1)
        restorer.stop()
        nginx_expected_calls = [call('10.1.1.1', timeout=600), call('10.3.3.3', timeout=600),
                                call('10.4.4.4', timeout=600), call('10.5.5.5', timeout=600)]
        self.assertEqual(nginx_expected_calls, nginx_manager.wait_healthcheck.call_args_list)
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(tasks, ['restore_10.2.2.2'])
        self.assertTrue(redis_lock.acquire(blocking=False))
        redis_lock.release()

    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_removing_locking_on_failure(self, log, nginx):
        redis_lock = redis.StrictRedis().lock('restore_lock', timeout=600, blocking_timeout=1)
        self.assertTrue(redis_lock.acquire(blocking=False))
        redis_lock.release()
        FakeManager.fail_ids = [2]
        restorer = healing.RestoreMachine(self.config)
        nginx_manager = nginx.Nginx.return_value
        restorer = healing.RestoreMachine(self.config)
        restorer.start()
        time.sleep(1)
        restorer.stop()
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(['restore_10.2.2.2', 'restore_10.3.3.3',
                              'restore_10.4.4.4', 'restore_10.5.5.5'], tasks)
        self.assertEqual(log.info.call_args_list, [call("Machine 0 restored")])
        self.assertEqual(nginx_manager.wait_healthcheck.call_args_list, [call('10.1.1.1', timeout=600)])
        self.assertTrue(redis_lock.acquire(blocking=False))
        redis_lock.release()

    @patch.object(storage.MongoDBStorage, "store_healing")
    @patch.object(storage.MongoDBStorage, "update_healing")
    @patch.object(tasks.lock.Lock, "extend_lock")
    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_extending_time_btw_restores(self, log, nginx, extend_lock, update_healing,
                                                         store_healing):
        time_now = datetime.datetime.utcnow()
        with patch.object(tasks.datetime.datetime, 'utcnow') as mock_time_now:
            time_side_effect = []
            for x in range(9):
                time_side_effect.append(time_now + datetime.timedelta(seconds=10 * x))
            mock_time_now.side_effect = time_side_effect
            nginx_manager = nginx.Nginx.return_value
            restorer = healing.RestoreMachine(self.config)
            restorer.start()
            time.sleep(1)
            restorer.stop()
            self.assertEqual(extend_lock.call_args_list, [call("restore_lock", extra_time=10),
                                                          call("restore_lock", extra_time=10),
                                                          call("restore_lock", extra_time=10)])
            nginx_expected_calls = [call('10.1.1.1', timeout=600), call('10.3.3.3', timeout=600),
                                    call('10.4.4.4', timeout=600), call('10.5.5.5', timeout=600)]
            self.assertEqual(nginx_expected_calls, nginx_manager.wait_healthcheck.call_args_list)
            tasks_restore = []
            for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}}):
                tasks_restore.append(task['_id'])
            self.assertListEqual(tasks_restore, ['restore_10.2.2.2'])

    @patch.object(tasks.lock.Lock, "extend_lock")
    @patch("rpaas.tasks.nginx")
    @patch("hm.log.logging")
    def test_restore_machine_store_healing_events(self, log, nginx, extend_lock):
        time_now = datetime.datetime.utcnow()

        def healing_time(x):
            return time_now + datetime.timedelta(seconds=x)
        with patch.object(tasks.datetime.datetime, 'utcnow') as mock_time_now:
            time_side_effect = []
            for x in range(18):
                time_side_effect.append(time_now + datetime.timedelta(seconds=10 * x))
            mock_time_now.side_effect = time_side_effect
            FakeManager.fail_ids = [4]
            restorer = healing.RestoreMachine(self.config)
            restorer.start()
            time.sleep(1)
            restorer.stop()
            expected_healings = [{'end_time': healing_time(40), 'machine': '10.1.1.1',
                                  'start_time': healing_time(30), 'status': 'success'},
                                 {'end_time': healing_time(80), 'machine': '10.3.3.3',
                                  'start_time': healing_time(70), 'status': 'success'},
                                 {'end_time': healing_time(120), 'machine': '10.4.4.4',
                                  'start_time': healing_time(110), 'status': 'success'}]
            foo_instances_healings = []
            filter_fields = {"status": 1, "start_time": 1, "machine": 1, "end_time": 1}
            healing_collection = self.storage.db[self.storage.healing_collection]
            for event in healing_collection.find({"instance": "foo"}, filter_fields):
                del event['_id']
                foo_instances_healings.append(event)
            self.assertListEqual(foo_instances_healings, expected_healings)
            expected_healings = [{'end_time': healing_time(160), 'machine': '10.5.5.5',
                                  'start_time': healing_time(150), 'status': 'iaas restore error'}]
            bar_instances_healings = []
            for event in healing_collection.find({"instance": "bar"}, filter_fields):
                del event['_id']
                bar_instances_healings.append(event)
            self.assertListEqual(bar_instances_healings, expected_healings)


class CheckMachineTestCase(unittest.TestCase):

    def setUp(self):

        self.config = {
            "MONGO_DATABASE": "check_machine_test",
            "RPAAS_SERVICE_NAME": "test_rpaas_check_machine",
            "RESTORE_MACHINE_RUN_INTERVAL": 2,
            "HOST_MANAGER": "fake",
        }

        self.storage = storage.MongoDBStorage(self.config)

        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)

        self.storage.db[self.storage.hosts_collection].insert({"_id": 0, "dns_name": "10.1.1.1",
                                                               "manager": "fake", "group": "rpaas_01",
                                                               "alternative_id": 0})
        self.storage.db[self.storage.hosts_collection].insert({"_id": 1, "dns_name": "10.2.2.2",
                                                               "manager": "fake", "group": "rpaas_02",
                                                               "alternative_id": 0})
        self.storage.db[self.storage.hosts_collection].insert({"_id": 2, "dns_name": "10.3.3.3",
                                                               "manager": "fake", "group": "rpaas_02",
                                                               "alternative_id": 0})
        FakeManager.host_id = 0
        FakeManager.hosts = ['10.1.1.1', '10.2.2.2', '10.3.3.3']

        redis.StrictRedis().delete("check_machine:test_rpaas_check_machine:last_run")

    def tearDown(self):
        self.storage.db[self.storage.tasks_collection].remove()
        self.storage.db[self.storage.hosts_collection].remove()

    @patch.object(consul_manager.ConsulManager, "service_healthcheck")
    def test_check_machine_instance_failures(self, service_healthcheck):
        healthcheck = [{'Node': {'Address': '10.1.1.1'},
                        'Checks': [{'CheckId': 1, 'Status': 'passing'},
                                   {'CheckId': 2, 'Status': 'critical'},
                                   {'CheckId': 3, 'Status': 'passing'}],
                        'Service': {'Service': 'nginx', 'Tags': ['test_rpaas_check_machine', 'rpaas_01']}},
                       {'Node': {'Address': '10.2.2.2'},
                        'Checks': [{'CheckId': 1, 'Status': 'passing'},
                                   {'CheckId': 2, 'Status': 'passing'},
                                   {'CheckId': 3, 'Status': 'passing'}],
                        'Service': {'Service': 'nginx', 'Tags': ['test_rpaas_check_machine', 'rpaas_02']}},
                       {'Node': {'Address': '10.3.3.3'},
                        'Checks': [{'CheckId': 1, 'Status': 'passing'},
                                   {'CheckId': 2, 'Status': 'passing'},
                                   {'CheckId': 3, 'Status': 'critical'}],
                        'Service': {'Service': 'nginx', 'Tags': ['test_rpaas_check_machine', 'rpaas_03']}},
                       {'Node': {'Address': '10.4.4.4'},
                        'Checks': [{'CheckId': 1, 'Status': 'passing'},
                                   {'CheckId': 2, 'Status': 'critical'}],
                        'Service': {'Service': 'nginx', 'Tags': ['another_rpaas', 'rpaas_04']}}]
        service_healthcheck.return_value = healthcheck
        checker = healing.CheckMachine(self.config)
        checker.start()
        time.sleep(1)
        checker.stop()
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(tasks, ['restore_10.1.1.1', 'restore_10.3.3.3'])

    def test_check_machine_empty_healthcheck(self):
        checker = healing.CheckMachine(self.config)
        checker.start()
        time.sleep(1)
        checker.stop()
        tasks = [task['_id'] for task in self.storage.find_task({"_id": {"$regex": "restore_.+"}})]
        self.assertListEqual(tasks, [])
