import unittest

import mock

from rpaas.manager import Manager, ScaleError
from rpaas import tasks

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class ManagerTestCase(unittest.TestCase):

    def setUp(self):
        self.lb_patcher = mock.patch('rpaas.tasks.LoadBalancer')
        self.host_patcher = mock.patch('rpaas.tasks.Host')
        self.storage_patcher = mock.patch('rpaas.manager.storage')
        self.LoadBalancer = self.lb_patcher.start()
        self.Host = self.host_patcher.start()
        self.storage = self.storage_patcher.start()
        self.config = {
            'HOST_MANAGER': 'my-host-manager',
            'LB_MANAGER': 'my-lb-manager'
        }
        self.m = Manager(self.config)

    def tearDown(self):
        self.lb_patcher.stop()
        self.host_patcher.stop()
        self.storage_patcher.stop()

    def test_new_instance(self):
        self.m.new_instance('x')
        host = self.Host.create.return_value
        lb = self.LoadBalancer.create.return_value
        self.Host.create.assert_called_with('my-host-manager', 'x', self.config)
        self.LoadBalancer.create.assert_called_with('my-lb-manager', 'x', self.config)
        lb.add_host.assert_called_with(host)
        self.storage.MongoDBStorage.return_value.store_task.assert_called()

    def test_remove_instance(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock()]
        self.m.remove_instance('x')
        self.LoadBalancer.find.assert_called_with('x', self.config)
        for h in lb.hosts:
            h.destroy.assert_called_once()
        lb.destroy.assert_called_once()
        self.storage.MongoDBStorage.return_value.remove_task.assert_called()

    @mock.patch('rpaas.manager.storage')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_info(self, LoadBalancer, storage):
        lb = LoadBalancer.find.return_value
        lb.address = '192.168.1.1'
        manager = Manager(self.config)
        info = manager.info('x')
        storage.MongoDBStorage.return_value.remove_task.assert_called_with('x')
        LoadBalancer.find.assert_called_with('x')
        self.assertItemsEqual(info, [{"label": "Address", "value": "192.168.1.1"}])
        self.assertEqual(self.m.status('x'), '192.168.1.1')

    @mock.patch('rpaas.manager.tasks')
    @mock.patch('rpaas.manager.storage')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_info_status_pending(self, LoadBalancer, storage, tasks):
        LoadBalancer.find.return_value = None
        find_task = storage.MongoDBStorage.return_value.find_task
        find_task.return_value = {
            'task_id': 'something-id'
        }
        async_init = tasks.NewInstanceTask.return_value.AsyncResult
        async_init.return_value.status = 'PENDING'
        manager = Manager(self.config)
        info = manager.info('x')
        self.assertItemsEqual(info, [{"label": "Address", "value": "pending"}])
        LoadBalancer.find.assert_called_with('x')
        find_task.assert_called_with('x')
        async_init.assert_called_with('something-id')
        self.assertEqual(manager.status('x'), 'pending')

    @mock.patch('rpaas.manager.tasks')
    @mock.patch('rpaas.manager.storage')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_info_status_failure(self, LoadBalancer, storage, tasks):
        LoadBalancer.find.return_value = None
        find_task = storage.MongoDBStorage.return_value.find_task
        find_task.return_value = {
            'task_id': 'something-id'
        }
        async_init = tasks.NewInstanceTask.return_value.AsyncResult
        async_init.return_value.status = 'FAILURE'
        manager = Manager(self.config)
        info = manager.info('x')
        self.assertItemsEqual(info, [{"label": "Address", "value": "failure"}])
        LoadBalancer.find.assert_called_with('x')
        find_task.assert_called_with('x')
        async_init.assert_called_with('something-id')
        self.assertEqual(manager.status('x'), 'failure')

    def test_scale_instance_up(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        self.m.scale_instance('x', 5)
        self.Host.create.assert_called_with('my-host-manager', 'x', self.config)
        self.assertEqual(self.Host.create.call_count, 3)
        lb.add_host.assert_called_with(self.Host.create.return_value)
        self.assertEqual(lb.add_host.call_count, 3)

    def test_scale_instance_down(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        self.m.scale_instance('x', 1)
        lb.hosts[0].destroy.assert_called_once
        lb.remove_host.assert_called_once_with(lb.hosts[0])

    def test_scale_instance_error(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        with self.assertRaises(ScaleError):
            self.m.scale_instance('x', 0)

    @mock.patch('rpaas.tasks.nginx')
    def test_bind_instance(self, nginx):
        lb = self.LoadBalancer.find.return_value
        nginx_manager = nginx.NginxDAV.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = 'h1'
        lb.hosts[1].dns_name = 'h2'
        self.m.bind('x', 'apphost.com')
        self.LoadBalancer.find.assert_called_with('x', self.config)
        nginx_manager.update_binding.assert_any_call('h1', '/', 'apphost.com')
        nginx_manager.update_binding.assert_any_call('h2', '/', 'apphost.com')

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_update_certificate(self, LoadBalancer, nginx):
        lb = LoadBalancer.find.return_value
        nginx_manager = nginx.NginxDAV.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.update_certificate('inst', 'cert', 'key')

        nginx_manager.update_certificate.assert_any_call(lb.hosts[0].dns_name, 'cert', 'key')
        nginx_manager.update_certificate.assert_any_call(lb.hosts[1].dns_name, 'cert', 'key')
