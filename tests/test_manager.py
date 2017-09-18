# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import copy
import unittest
import os

import mock

import rpaas.manager
from rpaas.manager import Manager, ScaleError, QuotaExceededError
from rpaas import tasks, storage, nginx

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class ManagerTestCase(unittest.TestCase):

    def setUp(self):
        os.environ["MONGO_DATABASE"] = "host_manager_test"
        os.environ.setdefault("RPAAS_SERVICE_NAME", "test-suite-rpaas")
        self.storage = storage.MongoDBStorage()
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)
        plan = {"_id": "small",
                "description": "some cool plan",
                "config": {"serviceofferingid": "abcdef123456"}}
        self.plan = copy.deepcopy(plan)
        self.plan["name"] = plan["_id"]
        del self.plan["_id"]
        self.storage.db[self.storage.plans_collection].insert(plan)
        self.lb_patcher = mock.patch("rpaas.tasks.LoadBalancer")
        self.host_patcher = mock.patch("rpaas.tasks.Host")
        self.LoadBalancer = self.lb_patcher.start()
        self.Host = self.host_patcher.start()
        self.config = {
            "HOST_MANAGER": "my-host-manager",
            "LB_MANAGER": "my-lb-manager",
            "serviceofferingid": "abcdef123459",
            "CONSUL_HOST": "127.0.0.1",
            "CONSUL_TOKEN": "rpaas-test",
        }

    def tearDown(self):
        self.lb_patcher.stop()
        self.host_patcher.stop()

    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance(self, nginx):
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        manager.new_instance("x")
        host = self.Host.create.return_value
        lb = self.LoadBalancer.create.return_value
        config = copy.deepcopy(self.config)
        config["HOST_TAGS"] = "rpaas_service:test-suite-rpaas,rpaas_instance:x,consul_token:abc-123"
        self.Host.create.assert_called_with("my-host-manager", "x", config)
        self.LoadBalancer.create.assert_called_with("my-lb-manager", "x", config)
        lb.add_host.assert_called_with(host)
        self.assertEquals(self.storage.find_task("x").count(), 0)
        nginx.Nginx.assert_called_once_with(config)
        nginx_manager = nginx.Nginx.return_value
        nginx_manager.wait_healthcheck.assert_called_once_with(host.dns_name, timeout=600)
        manager.consul_manager.write_healthcheck.assert_called_once_with("x")

    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_host_create_fail_and_raises(self, nginx):
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        lb = self.LoadBalancer.create.return_value
        self.Host.create.side_effect = Exception("Host create failure")
        host = self.Host.create.return_value
        manager.new_instance("x")
        lb.add_host.assert_not_called()
        lb.destroy.assert_not_called()
        host.destroy.assert_not_called()
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_host_create_fail_and_rollback(self, nginx):
        config = copy.deepcopy(self.config)
        config["RPAAS_ROLLBACK_ON_ERROR"] = "1"
        manager = Manager(config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        lb = self.LoadBalancer.create.return_value
        self.Host.create.side_effect = Exception("Host create failure")
        host = self.Host.create.return_value
        manager.new_instance("x")
        lb.assert_not_called()
        lb.add_host.assert_not_called()
        lb.destroy.assert_not_called()
        host.destroy.assert_not_called()
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_lb_create_fail_and_rollback(self, nginx):
        config = copy.deepcopy(self.config)
        config["RPAAS_ROLLBACK_ON_ERROR"] = "1"
        manager = Manager(config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        self.LoadBalancer.create.side_effect = Exception("LB create failure")
        lb = self.LoadBalancer.create.return_value
        host = self.Host.create.return_value
        manager.new_instance("x")
        lb.add_host.assert_not_called()
        lb.destroy.assert_not_called()
        host.destroy.assert_called_once()
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.tasks.hc.Dumb")
    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_hc_create_fail_and_rollback(self, nginx, hc):
        config = copy.deepcopy(self.config)
        config["RPAAS_ROLLBACK_ON_ERROR"] = "1"
        manager = Manager(config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        lb = self.LoadBalancer.create.return_value
        host = self.Host.create.return_value
        dumb_hc = hc.return_value
        dumb_hc.create.side_effect = Exception("HC create failure")
        manager.new_instance("x")
        self.LoadBalancer.create.assert_called_once()
        lb.add_host.assert_not_called()
        lb.destroy.assert_called_once()
        host.destroy.assert_called_once()
        lb.remove_host.assert_not_called()
        dumb_hc.destroy.assert_called_once()
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.tasks.hc.Dumb")
    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_nginx_wait_healthcheck_fail_and_rollback(self, nginx, hc):
        config = copy.deepcopy(self.config)
        config["RPAAS_ROLLBACK_ON_ERROR"] = "1"
        manager = Manager(config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        lb = self.LoadBalancer.create.return_value
        host = self.Host.create.return_value
        dumb_hc = hc.return_value
        nginx_manager = nginx.Nginx.return_value
        nginx_manager.wait_healthcheck.side_effect = Exception("Nginx timeout")
        manager.new_instance("x")
        self.LoadBalancer.create.assert_called_once()
        lb.add_host.assert_called_once()
        dumb_hc.add_url.assert_not_called()
        lb.destroy.assert_called_once()
        host.destroy.assert_called_once()
        lb.remove_host.assert_not_called()
        dumb_hc.destroy.assert_called_once()
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_with_plan(self, nginx):
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        manager.new_instance("x", plan_name="small")
        host = self.Host.create.return_value
        config = copy.deepcopy(self.config)
        config.update(self.plan["config"])
        config["HOST_TAGS"] = "rpaas_service:test-suite-rpaas,rpaas_instance:x,consul_token:abc-123"
        lb = self.LoadBalancer.create.return_value
        self.Host.create.assert_called_with("my-host-manager", "x", config)
        self.LoadBalancer.create.assert_called_with("my-lb-manager", "x", config)
        lb.add_host.assert_called_with(host)
        self.assertEquals(manager.storage.find_task("x").count(), 0)
        nginx.Nginx.assert_called_once_with(config)
        nginx_manager = nginx.Nginx.return_value
        nginx_manager.wait_healthcheck.assert_called_once_with(host.dns_name, timeout=600)
        metadata = manager.storage.find_instance_metadata("x")
        self.assertEqual({"_id": "x", "plan_name": "small", "consul_token": "abc-123"}, metadata)

    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_with_extra_tags(self, nginx):
        config = copy.deepcopy(self.config)
        config["INSTANCE_EXTRA_TAGS"] = "enable_monitoring:1"
        manager = Manager(config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        manager.new_instance("x")
        host = self.Host.create.return_value
        config["HOST_TAGS"] = ("rpaas_service:test-suite-rpaas,rpaas_instance:x,"
                               "consul_token:abc-123,enable_monitoring:1")
        del config["INSTANCE_EXTRA_TAGS"]
        lb = self.LoadBalancer.create.return_value
        self.Host.create.assert_called_with("my-host-manager", "x", config)
        self.LoadBalancer.create.assert_called_with("my-lb-manager", "x", config)
        lb.add_host.assert_called_with(host)
        self.assertEquals(manager.storage.find_task("x").count(), 0)
        nginx.Nginx.assert_called_once_with(config)
        nginx_manager = nginx.Nginx.return_value
        nginx_manager.wait_healthcheck.assert_called_once_with(host.dns_name, timeout=600)

    def test_new_instance_plan_not_found(self):
        manager = Manager(self.config)
        with self.assertRaises(storage.PlanNotFoundError):
            manager.new_instance("x", plan_name="supersmall")

    @mock.patch("rpaas.tasks.nginx")
    def test_new_instance_over_quota(self, nginx):
        manager = Manager(self.config)
        for name in ["a", "b", "c", "d", "e"]:
            manager.new_instance(name, "myteam")
        with self.assertRaises(QuotaExceededError) as cm:
            manager.new_instance("f", "myteam")
        self.assertEqual(str(cm.exception), "quota execeeded 5/5 used")
        manager.new_instance("f", "otherteam")

    def test_new_instance_error_already_running(self):
        self.storage.store_task("x")
        manager = Manager(self.config)
        with self.assertRaises(storage.DuplicateError):
            manager.new_instance("x")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_new_instance_error_already_exists(self, LoadBalancer):
        LoadBalancer.find.return_value = "something"
        manager = Manager(self.config)
        with self.assertRaises(storage.DuplicateError):
            manager.new_instance("x")
        LoadBalancer.find.assert_called_once_with("x")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_update_instance(self, LoadBalancer):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        LoadBalancer.find.return_value = "something"
        self.storage.store_instance_metadata("x", plan_name=self.plan["name"], consul_token="abc-123")
        manager = Manager(self.config)
        manager.update_instance("x", "huge")
        return_metadata = {'_id': 'x', 'plan_name': 'huge', 'consul_token': 'abc-123'}
        self.assertEquals(self.storage.find_instance_metadata("x"), return_metadata)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_update_instance_invalid_plan(self, LoadBalancer):
        LoadBalancer.find.return_value = "something"
        self.storage.store_instance_metadata("x", plan_name=self.plan["name"], consul_token="abc-123")
        manager = Manager(self.config)
        with self.assertRaises(storage.PlanNotFoundError):
            manager.update_instance("x", "large")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_update_instance_not_found(self, LoadBalancer):
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"serviceofferingid": "abcdef123459"}}
        )
        LoadBalancer.find.return_value = None
        self.storage.store_instance_metadata("x", plan_name=self.plan["name"], consul_token="abc-123")
        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.update_instance("x", "huge")

    def test_remove_instance(self):
        self.storage.store_instance_metadata("x", plan_name="small", consul_token="abc-123")
        self.storage.store_le_certificate("x", "foobar.com")
        self.storage.store_le_certificate("x", "example.com")
        self.storage.store_le_certificate("y", "test.com")
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock()]
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.remove_instance("x")
        config = copy.deepcopy(self.config)
        config.update(self.plan["config"])
        self.LoadBalancer.find.assert_called_with("x", config)
        for h in lb.hosts:
            h.destroy.assert_called_once()
        lb.destroy.assert_called_once()
        self.assertEquals(self.storage.find_task("x").count(), 0)
        self.assertIsNone(self.storage.find_instance_metadata("x"))
        self.assertEquals([cert for cert in self.storage.find_le_certificates({"name": "x"})], [])
        self.assertEquals([cert['name'] for cert in self.storage.find_le_certificates({"name": "y"})][0], "y")
        manager.consul_manager.destroy_token.assert_called_with("abc-123")
        manager.consul_manager.destroy_instance.assert_called_with("x")

    def test_remove_instance_no_token(self):
        self.storage.store_instance_metadata("x", plan_name="small")
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock()]
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.remove_instance("x")
        config = copy.deepcopy(self.config)
        config.update(self.plan["config"])
        self.LoadBalancer.find.assert_called_with("x", config)
        for h in lb.hosts:
            h.destroy.assert_called_once()
        lb.destroy.assert_called_once()
        self.assertEquals(self.storage.find_task("x").count(), 0)
        self.assertIsNone(self.storage.find_instance_metadata("x"))
        manager.consul_manager.destroy_token.assert_not_called()

    def test_remove_instance_remove_task_on_exception(self):
        self.storage.store_instance_metadata("x", plan_name="small")
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(side_effect=Exception("test"))]
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.remove_instance("x")
        self.assertEquals(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.tasks.nginx")
    def test_remove_instance_decrement_quota(self, nginx):
        manager = Manager(self.config)
        for name in ["a", "b", "c", "d", "e"]:
            manager.new_instance(name)
        with self.assertRaises(QuotaExceededError):
            manager.new_instance("f")
        manager.remove_instance("e")
        manager.new_instance("f")
        manager.remove_instance("e")
        with self.assertRaises(QuotaExceededError):
            manager.new_instance("g")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_restore_machine_instance(self, LoadBalancer):
        manager = Manager(self.config)
        lb = LoadBalancer.find.return_value
        lb.adress = "10.1.1.1"
        self.storage.store_instance_metadata("foo", consul_token="abc")
        self.storage.db[self.storage.hosts_collection].insert({"_id": 0, "dns_name": "10.1.1.1",
                                                               "manager": "fake", "group": "foo",
                                                               "alternative_id": 0})
        manager.restore_machine_instance('foo', '10.1.1.1')
        task = self.storage.find_task("restore_10.1.1.1")
        self.assertEqual(task[0]['host'], "10.1.1.1")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_restore_machine_invalid_dns_name(self, LoadBalancer):
        manager = Manager(self.config)
        lb = LoadBalancer.find.return_value
        lb.adress = "10.2.2.2"
        self.storage.store_instance_metadata("foo", consul_token="abc")
        with self.assertRaises(rpaas.manager.InstanceMachineNotFoundError):
            manager.restore_machine_instance('foo', '10.1.1.1')

    def test_restore_machine_instance_cancel(self):
        manager = Manager(self.config)
        self.storage.store_task("restore_10.1.1.1")
        manager.restore_machine_instance('foo', '10.1.1.1', True)
        task = self.storage.find_task("restore_10.1.1.1")
        self.assertEquals(task.count(), 0)

    def test_restore_machine_instance_cancel_invalid_task(self):
        manager = Manager(self.config)
        with self.assertRaises(rpaas.tasks.TaskNotFoundError):
            manager.restore_machine_instance('foo', '10.1.1.1', True)

    @mock.patch("rpaas.manager.nginx")
    @mock.patch("rpaas.manager.LoadBalancer")
    def test_restore_instance_successfully(self, LoadBalancer, nginx):
        self.config["CLOUDSTACK_TEMPLATE_ID"] = "default_template"
        self.config["INSTANCE_EXTRA_TAGS"] = "x:y"
        self.config["RPAAS_RESTORE_DELAY"] = 1
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"CLOUDSTACK_TEMPLATE_ID": "1234", "INSTANCE_EXTRA_TAGS": "a:b,c:d"}}
        )
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = '10.1.1.1'
        lb.hosts[0].id = 'xxx'
        lb.hosts[1].dns_name = '10.2.2.2'
        lb.hosts[1].id = 'yyy'
        self.storage.store_instance_metadata("x", plan_name="huge", consul_token="abc-123")
        manager = Manager(self.config)
        responses = [response for response in manager.restore_instance("x")]
        while "." in responses:
            responses.remove(".")
        expected_responses = ["Restoring host (1/2) xxx ", ": successfully restored\n",
                              "Restoring host (2/2) yyy ", ": successfully restored\n"]
        self.assertListEqual(responses, expected_responses)
        self.assertDictContainsSubset(LoadBalancer.find.call_args[1],
                                      {'CLOUDSTACK_TEMPLATE_ID': u'1234', 'HOST_TAGS': u'a:b,c:d'})
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.manager.nginx")
    @mock.patch("rpaas.manager.LoadBalancer")
    def test_restore_instance_failed_restore(self, LoadBalancer, nginx):
        self.config["CLOUDSTACK_TEMPLATE_ID"] = "default_template"
        self.config["INSTANCE_EXTRA_TAGS"] = "x:y"
        self.config["RPAAS_RESTORE_DELAY"] = 1
        self.storage.db[self.storage.plans_collection].insert(
            {"_id": "huge",
             "description": "some cool huge plan",
             "config": {"CLOUDSTACK_TEMPLATE_ID": "1234", "INSTANCE_EXTRA_TAGS": "a:b,c:d"}}
        )
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = '10.1.1.1'
        lb.hosts[0].id = 'xxx'
        lb.hosts[1].dns_name = '10.2.2.2'
        lb.hosts[1].id = 'yyy'
        self.storage.store_instance_metadata("x", plan_name="huge", consul_token="abc-123")
        manager = Manager(self.config)
        nginx_manager = nginx.Nginx.return_value
        nginx_manager.wait_healthcheck.side_effect = ["OK", Exception("timeout to response")]
        responses = [response for response in manager.restore_instance("x")]
        while "." in responses:
            responses.remove(".")
        nginx_manager.wait_healthcheck.assert_called_with(host='10.2.2.2', timeout=600,
                                                          manage_healthcheck=False)
        expected_responses = ["Restoring host (1/2) xxx ", ": successfully restored\n",
                              "Restoring host (2/2) yyy ", ": failed to restore - 'timeout to response'\n"]
        self.assertListEqual(responses, expected_responses)
        self.assertDictContainsSubset(LoadBalancer.find.call_args[1],
                                      {'CLOUDSTACK_TEMPLATE_ID': u'1234', 'HOST_TAGS': u'a:b,c:d'})
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.manager.nginx")
    @mock.patch("rpaas.manager.LoadBalancer")
    def test_restore_instance_service_instance_not_found(self, LoadBalancer, nginx):
        self.config["CLOUDSTACK_TEMPLATE_ID"] = "default_template"
        self.config["INSTANCE_EXTRA_TAGS"] = "x:y"
        self.config["RPAAS_RESTORE_DELAY"] = 1
        LoadBalancer.find.return_value = None
        manager = Manager(self.config)
        responses = [host for host in manager.restore_instance("x")]
        self.assertListEqual(responses, ["instance x not found\n"])
        self.assertEqual(self.storage.find_task("x").count(), 0)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_node_status(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = '10.1.1.1'
        lb.hosts[1].dns_name = '10.2.2.2'
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.node_hostname.side_effect = ['vm-1', 'vm-2']
        manager.consul_manager.node_status.return_value = {'vm-1': 'OK', 'vm-2': 'DEAD'}
        node_status = manager.node_status("x")
        LoadBalancer.find.assert_called_with("x")
        self.assertDictEqual(node_status, {'vm-1': {'status': 'OK', 'address': '10.1.1.1'},
                                           'vm-2': {'status': 'DEAD', 'address': '10.2.2.2'}})

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_node_status_no_hostname(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = '10.1.1.1'
        lb.hosts[1].dns_name = '10.2.2.2'
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.node_hostname.side_effect = ['vm-1', None]
        manager.consul_manager.node_status.return_value = {'vm-1': 'OK', 'vm-2': 'DEAD'}
        node_status = manager.node_status("x")
        LoadBalancer.find.assert_called_with("x")
        self.assertDictEqual(node_status, {'vm-1': {'status': 'OK', 'address': '10.1.1.1'},
                                           'vm-2': {'status': 'DEAD'}})

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_info(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.address = "192.168.1.1"
        manager = Manager(self.config)
        info = manager.info("x")
        LoadBalancer.find.assert_called_with("x")
        self.assertItemsEqual(info, [
            {"label": "Address", "value": "192.168.1.1"},
            {"label": "Instances", "value": "0"},
            {"label": "Routes", "value": ""},
        ])
        self.assertEqual(manager.status("x"), "192.168.1.1")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_info_with_plan(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.address = "192.168.1.1"
        self.storage.store_instance_metadata("x", plan_name="small")
        self.addCleanup(self.storage.remove_instance_metadata, "x")
        manager = Manager(self.config)
        info = manager.info("x")
        LoadBalancer.find.assert_called_with("x")
        self.assertItemsEqual(info, [
            {"label": "Address", "value": "192.168.1.1"},
            {"label": "Instances", "value": "0"},
            {"label": "Routes", "value": ""},
            {"label": "Plan", "value": "small"},
        ])
        self.assertEqual(manager.status("x"), "192.168.1.1")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_info_with_binding(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        self.storage.replace_binding_path("inst", "/arrakis", None, "location /x {\n}")
        lb = LoadBalancer.find.return_value
        lb.address = "192.168.1.1"
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        info = manager.info("inst")
        LoadBalancer.find.assert_called_with("inst")
        self.assertItemsEqual(info, [
            {"label": "Address", "value": "192.168.1.1"},
            {"label": "Instances", "value": "2"},
            {"label": "Routes", "value": """path = /
destination = app.host.com
path = /arrakis
content = location /x {
}"""},
        ])
        self.assertEqual(manager.status("inst"), "192.168.1.1")

    @mock.patch("rpaas.manager.tasks")
    def test_info_status_pending(self, tasks):
        self.storage.store_task("x")
        self.storage.update_task("x", "something-id")
        async_init = tasks.NewInstanceTask.return_value.AsyncResult
        async_init.return_value.status = "PENDING"
        manager = Manager(self.config)
        info = manager.info("x")
        self.assertItemsEqual(info, [
            {"label": "Address", "value": "pending"},
            {"label": "Instances", "value": "0"},
            {"label": "Routes", "value": ""},
        ])
        async_init.assert_called_with("something-id")
        self.assertEqual(manager.status("x"), "pending")

    @mock.patch("rpaas.manager.tasks")
    def test_info_status_failure(self, tasks):
        self.storage.store_task("x")
        self.storage.update_task("x", "something-id")
        async_init = tasks.NewInstanceTask.return_value.AsyncResult
        async_init.return_value.status = "FAILURE"
        manager = Manager(self.config)
        info = manager.info("x")
        self.assertItemsEqual(info, [
            {"label": "Address", "value": "failure"},
            {"label": "Instances", "value": "0"},
            {"label": "Routes", "value": ""},
        ])
        async_init.assert_called_with("something-id")
        self.assertEqual(manager.status("x"), "failure")

    @mock.patch("rpaas.tasks.nginx")
    def test_scale_instance_up(self, nginx):
        lb = self.LoadBalancer.find.return_value
        lb.name = "x"
        lb.hosts = [mock.Mock(), mock.Mock()]
        self.storage.store_instance_metadata("x", consul_token="abc-123")
        self.addCleanup(self.storage.remove_instance_metadata, "x")
        config = copy.deepcopy(self.config)
        config["HOST_TAGS"] = "rpaas_service:test-suite-rpaas,rpaas_instance:x,consul_token:abc-123"
        manager = Manager(self.config)
        manager.scale_instance("x", 5)
        self.Host.create.assert_called_with("my-host-manager", "x", config)
        self.assertEqual(self.Host.create.call_count, 3)
        lb.add_host.assert_called_with(self.Host.create.return_value)
        self.assertEqual(lb.add_host.call_count, 3)
        nginx_manager = nginx.Nginx.return_value
        created_host = self.Host.create.return_value
        expected_calls = [mock.call(created_host.dns_name, timeout=600),
                          mock.call(created_host.dns_name, timeout=600),
                          mock.call(created_host.dns_name, timeout=600)]
        self.assertEqual(expected_calls, nginx_manager.wait_healthcheck.call_args_list)

    @mock.patch("rpaas.tasks.nginx")
    def test_scale_instance_up_no_token(self, nginx):
        lb = self.LoadBalancer.find.return_value
        lb.name = "x"
        lb.hosts = [mock.Mock(), mock.Mock()]
        config = copy.deepcopy(self.config)
        config["HOST_TAGS"] = "rpaas_service:test-suite-rpaas,rpaas_instance:x,consul_token:abc-123"
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        manager.scale_instance("x", 5)
        self.Host.create.assert_called_with("my-host-manager", "x", config)
        self.assertEqual(self.Host.create.call_count, 3)
        lb.add_host.assert_called_with(self.Host.create.return_value)
        self.assertEqual(lb.add_host.call_count, 3)
        nginx_manager = nginx.Nginx.return_value
        created_host = self.Host.create.return_value
        expected_calls = [mock.call(created_host.dns_name, timeout=600),
                          mock.call(created_host.dns_name, timeout=600),
                          mock.call(created_host.dns_name, timeout=600)]
        self.assertEqual(expected_calls, nginx_manager.wait_healthcheck.call_args_list)

    @mock.patch("rpaas.tasks.nginx")
    def test_scale_instance_up_with_plan(self, nginx):
        lb = self.LoadBalancer.find.return_value
        lb.name = "x"
        lb.hosts = [mock.Mock(), mock.Mock()]
        self.storage.store_instance_metadata("x", plan_name=self.plan["name"],
                                             consul_token="abc-123")
        self.addCleanup(self.storage.remove_instance_metadata, "x")
        config = copy.deepcopy(self.config)
        config.update(self.plan["config"])
        config["HOST_TAGS"] = "rpaas_service:test-suite-rpaas,rpaas_instance:x,consul_token:abc-123"
        manager = Manager(self.config)
        manager.scale_instance("x", 5)
        self.Host.create.assert_called_with("my-host-manager", "x", config)
        self.assertEqual(self.Host.create.call_count, 3)
        lb.add_host.assert_called_with(self.Host.create.return_value)
        self.assertEqual(lb.add_host.call_count, 3)
        nginx_manager = nginx.Nginx.return_value
        created_host = self.Host.create.return_value
        expected_calls = [mock.call(created_host.dns_name, timeout=600),
                          mock.call(created_host.dns_name, timeout=600),
                          mock.call(created_host.dns_name, timeout=600)]
        self.assertEqual(expected_calls, nginx_manager.wait_healthcheck.call_args_list)

    def test_scale_instance_error_task_running(self):
        self.storage.store_task("x")
        manager = Manager(self.config)
        with self.assertRaises(rpaas.tasks.NotReadyError):
            manager.scale_instance("x", 5)

    def test_scale_instance_down(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        self.storage.store_instance_metadata("x", consul_token="abc-123")
        self.addCleanup(self.storage.remove_instance_metadata, "x")
        manager = Manager(self.config)
        manager.scale_instance("x", 1)
        lb.hosts[0].destroy.assert_called_once
        lb.remove_host.assert_called_once_with(lb.hosts[0])

    @mock.patch("rpaas.tasks.consul_manager")
    def test_scale_instance_down_with_healing_enabled(self, consul_manager):
        consul = consul_manager.ConsulManager.return_value
        config = copy.deepcopy(self.config)
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = '10.2.2.2'
        lb.hosts[0].id = '1234'
        self.storage.store_instance_metadata("x", consul_token="abc-123")
        self.addCleanup(self.storage.remove_instance_metadata, "x")
        consul.node_hostname.return_value = 'rpaas-2'
        manager = Manager(config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.generate_token.return_value = "abc-123"
        manager.scale_instance("x", 1)
        lb.hosts[0].destroy.assert_called_once
        lb.remove_host.assert_called_once_with(lb.hosts[0])
        consul.remove_node.assert_called_once_with('x', 'rpaas-2', '1234')

    def test_scale_instance_error(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        with self.assertRaises(ScaleError):
            manager.scale_instance("x", 0)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_bind_instance(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = "h1"
        lb.hosts[1].dns_name = "h2"
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.bind("x", "apphost.com")
        binding_data = self.storage.find_binding("x")
        self.assertDictEqual(binding_data, {
            "_id": "x",
            "app_host": "apphost.com",
            "paths": [{"path": "/", "destination": "apphost.com"}]
        })
        LoadBalancer.find.assert_called_with("x")
        manager.consul_manager.write_location.assert_called_with("x", "/", destination="apphost.com",
                                                                 router_mode=False)

    def test_bind_instance_error_task_running(self):
        self.storage.store_task("x")
        manager = Manager(self.config)
        with self.assertRaises(rpaas.tasks.NotReadyError):
            manager.bind("x", "apphost.com")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_bind_instance_multiple_bind_hosts(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.bind("x", "apphost.com")
        binding_data = self.storage.find_binding("x")
        self.assertDictEqual(binding_data, {
            "_id": "x",
            "app_host": "apphost.com",
            "paths": [{"path": "/", "destination": "apphost.com"}]
        })
        LoadBalancer.find.assert_called_with("x")
        manager.consul_manager.write_location.assert_called_with("x", "/", destination="apphost.com",
                                                                 router_mode=False)
        manager.consul_manager.reset_mock()
        manager.bind("x", "apphost.com")
        self.assertEqual(0, len(manager.consul_manager.mock_calls))
        with self.assertRaises(rpaas.manager.BindError):
            manager.bind("x", "another.host.com")
        self.assertEqual(0, len(manager.consul_manager.mock_calls))

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_bind_instance_with_route(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = "h1"
        lb.hosts[1].dns_name = "h2"
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.add_route("x", "/somewhere", "my.other.host", None)
        manager.bind("x", "apphost.com")
        binding_data = self.storage.find_binding("x")
        self.assertDictEqual(binding_data, {
            "_id": "x",
            "app_host": "apphost.com",
            "paths": [
                {"path": "/somewhere", "destination": "my.other.host", "content": None},
                {"path": "/", "destination": "apphost.com"}
            ]
        })
        LoadBalancer.find.assert_called_with("x")
        manager.consul_manager.write_location.assert_any_call("x", "/somewhere", destination="my.other.host",
                                                              content=None)
        manager.consul_manager.write_location.assert_any_call("x", "/", destination="apphost.com", router_mode=False)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_unbind_instance(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.unbind("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "paths": []
        })
        LoadBalancer.find.assert_called_with("inst")
        content_instance_not_bound = nginx.NGINX_LOCATION_INSTANCE_NOT_BOUND
        manager.consul_manager.write_location.assert_called_with("inst", "/", content=content_instance_not_bound)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_unbind_instance_with_extra_path(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        self.storage.replace_binding_path("inst", "/me", "somewhere.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.unbind("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "paths": [
                {"path": "/me", "destination": "somewhere.com", "content": None}
            ]
        })
        LoadBalancer.find.assert_called_with("inst")
        content_instance_not_bound = nginx.NGINX_LOCATION_INSTANCE_NOT_BOUND
        manager.consul_manager.write_location.assert_called_with("inst", "/", content=content_instance_not_bound)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_unbind_and_bind_instance_with_extra_path(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        self.storage.replace_binding_path("inst", "/me", "somewhere.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.unbind("inst")
        manager.bind("inst", "app2.host.com")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "app_host": "app2.host.com",
            "paths": [
                {"path": "/me", "destination": "somewhere.com", "content": None},
                {"path": "/", "destination": "app2.host.com"}
            ]
        })
        LoadBalancer.find.assert_called_with("inst")
        content_instance_not_bound = nginx.NGINX_LOCATION_INSTANCE_NOT_BOUND
        expected_calls = [mock.call("inst", "/", content=content_instance_not_bound),
                          mock.call("inst", "/", destination="app2.host.com", router_mode=False)]
        manager.consul_manager.write_location.assert_has_calls(expected_calls)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_update_certificate(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.update_certificate("inst", "cert", "key")

        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.set_certificate.assert_called_with("inst", "cert", "key")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_update_certificate_no_binding(self, LoadBalancer):
        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.update_certificate("inst", "cert", "key")
        LoadBalancer.find.assert_called_with("inst")

    def test_update_certificate_error_task_running(self):
        self.storage.store_task("inst")
        manager = Manager(self.config)
        with self.assertRaises(rpaas.tasks.NotReadyError):
            manager.update_certificate("inst", "cert", "key")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_add_route(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.add_route("inst", "/somewhere", "my.other.host", None)

        LoadBalancer.find.assert_called_with("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "app_host": "app.host.com",
            "paths": [
                {
                    "path": "/",
                    "destination": "app.host.com",
                },
                {
                    "path": "/somewhere",
                    "destination": "my.other.host",
                    "content": None,
                }
            ]
        })
        manager.consul_manager.write_location.assert_called_with("inst", "/somewhere",
                                                                 destination="my.other.host",
                                                                 content=None)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_add_route_with_content(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.add_route("inst", "/somewhere", None, "location /x { something; }")

        LoadBalancer.find.assert_called_with("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "app_host": "app.host.com",
            "paths": [
                {
                    "path": "/",
                    "destination": "app.host.com",
                },
                {
                    "path": "/somewhere",
                    "destination": None,
                    "content": "location /x { something; }",
                }
            ]
        })
        manager.consul_manager.write_location.assert_called_with("inst", "/somewhere", destination=None,
                                                                 content="location /x { something; }")

    def test_add_route_error_task_running(self):
        self.storage.store_task("inst")
        manager = Manager(self.config)
        with self.assertRaises(rpaas.tasks.NotReadyError):
            manager.add_route("inst", "/somewhere", "my.other.host", None)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_add_route_no_binding_creates_one(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.add_route("inst", "/somewhere", "my.other.host", None)

        LoadBalancer.find.assert_called_with("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "paths": [
                {
                    "path": "/somewhere",
                    "destination": "my.other.host",
                    "content": None,
                }
            ]
        })
        manager.consul_manager.write_location.assert_called_with("inst", "/somewhere",
                                                                 destination="my.other.host",
                                                                 content=None)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_delete_route(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        self.storage.replace_binding_path("inst", "/arrakis", "dune.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.delete_route("inst", "/arrakis")

        LoadBalancer.find.assert_called_with("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "app_host": "app.host.com",
            "paths": [{"path": "/", "destination": "app.host.com"}]
        })
        manager.consul_manager.remove_server_upstream.assert_called_once_with("inst", "dune.com", "dune.com")
        manager.consul_manager.remove_location.assert_called_with("inst", "/arrakis")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_delete_route_also_point_to_root(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        self.storage.replace_binding_path("inst", "/arrakis", "app.host.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.delete_route("inst", "/arrakis")

        LoadBalancer.find.assert_called_with("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "app_host": "app.host.com",
            "paths": [{"path": "/", "destination": "app.host.com"}]
        })
        manager.consul_manager.remove_server_upstream.assert_not_called()
        manager.consul_manager.remove_location.assert_called_with("inst", "/arrakis")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_delete_route_only_remove_upstream_on_last_reference(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        self.storage.replace_binding_path("inst", "/arrakis", "dune.com")
        self.storage.replace_binding_path("inst", "/atreides", "dune.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.delete_route("inst", "/arrakis")

        LoadBalancer.find.assert_called_with("inst")
        binding_data = self.storage.find_binding("inst")
        self.assertDictEqual(binding_data, {
            "_id": "inst",
            "app_host": "app.host.com",
            "paths": [{"path": "/", "destination": "app.host.com"},
                      {"path": "/atreides", "destination": "dune.com", "content": None}]
        })
        manager.consul_manager.remove_server_upstream.assert_not_called()
        manager.consul_manager.remove_location.assert_called_with("inst", "/arrakis")

    def test_delete_route_error_task_running(self):
        self.storage.store_task("inst")
        manager = Manager(self.config)
        with self.assertRaises(rpaas.tasks.NotReadyError):
            manager.delete_route("inst", "/arrakis")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_delete_route_error_no_route(self, LoadBalancer):
        self.storage.store_binding("inst", "app.host.com")
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.delete_route("inst", "/somewhere")
        LoadBalancer.find.assert_called_with("inst")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_delete_route_no_binding(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.delete_route("inst", "/zahadum")
        LoadBalancer.find.assert_called_with("inst")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_add_block_with_content(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.add_block("inst", "server", "location /x { something; }")

        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.write_block.assert_called_with(
            "inst", "server", "location /x { something; }"
        )

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_delete_block(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.delete_block("inst", "http")

        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.remove_block.assert_called_with("inst", "http")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_list_block(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.list_blocks.return_value = [
                {u'block_name': 'server',
                 u'content': 'something nice in server'},
                {u'block_name': 'http',
                 u'content': 'something nice in http'}
        ]
        blocks = manager.list_blocks("inst")

        self.assertDictEqual(blocks[0], {'block_name': 'server',
                                         'content': 'something nice in server'})
        self.assertDictEqual(blocks[1], {'block_name': 'http',
                                         'content': 'something nice in http'})
        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.list_blocks.assert_called_with("inst")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_empty_list_blocks(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.list_blocks.return_value = []
        blocks = manager.list_blocks("inst")

        self.assertEqual(blocks, [])
        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.list_blocks.assert_called_with("inst")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_purge_location(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.nginx_manager = mock.Mock()
        manager.nginx_manager.purge_location.side_effect = [True, True]
        purged_hosts = manager.purge_location("inst", "/foo/bar", True)

        LoadBalancer.find.assert_called_with("inst")

        self.assertEqual(purged_hosts, 2)
        manager.nginx_manager.purge_location.assert_any_call(lb.hosts[0].dns_name, "/foo/bar", True)
        manager.nginx_manager.purge_location.assert_any_call(lb.hosts[1].dns_name, "/foo/bar", True)

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_add_lua_with_content(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.add_lua("inst", "my_module", "server", "lua code")

        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.write_lua.assert_called_with(
            "inst", "my_module", "server", "lua code"
        )

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_list_lua_modules(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.consul_manager.list_lua_modules.return_value = {"somelua": {"server": "lua code"}}
        modules = manager.list_lua("inst")

        self.assertDictEqual(modules, {"somelua": {"server": "lua code"}})
        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.list_lua_modules.assert_called_with("inst")

    @mock.patch("rpaas.manager.LoadBalancer")
    def test_delete_lua(self, LoadBalancer):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.consul_manager = mock.Mock()
        manager.delete_lua("inst", "server", "module")

        LoadBalancer.find.assert_called_with("inst")
        manager.consul_manager.remove_lua.assert_called_with("inst", "server", "module")
