import unittest
import os

import mock

import rpaas.manager
from rpaas.manager import Manager, ScaleError
from rpaas import tasks, storage

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class ManagerTestCase(unittest.TestCase):

    def setUp(self):
        os.environ['MONGO_DATABASE'] = 'host_manager_test'
        self.storage = storage.MongoDBStorage()
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)
        self.lb_patcher = mock.patch('rpaas.tasks.LoadBalancer')
        self.host_patcher = mock.patch('rpaas.tasks.Host')
        self.LoadBalancer = self.lb_patcher.start()
        self.Host = self.host_patcher.start()
        self.config = {
            'HOST_MANAGER': 'my-host-manager',
            'LB_MANAGER': 'my-lb-manager'
        }

    def tearDown(self):
        self.lb_patcher.stop()
        self.host_patcher.stop()

    def test_new_instance(self):
        manager = Manager(self.config)
        manager.new_instance('x')
        host = self.Host.create.return_value
        lb = self.LoadBalancer.create.return_value
        self.Host.create.assert_called_with('my-host-manager', 'x', self.config)
        self.LoadBalancer.create.assert_called_with('my-lb-manager', 'x', self.config)
        lb.add_host.assert_called_with(host)
        self.assertIsNotNone(self.storage.find_task('x'))

    def test_remove_instance(self):
        self.storage.store_task('x', 'something-id')
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock()]
        manager = Manager(self.config)
        manager.remove_instance('x')
        self.LoadBalancer.find.assert_called_with('x', self.config)
        for h in lb.hosts:
            h.destroy.assert_called_once()
        lb.destroy.assert_called_once()
        self.assertIsNone(self.storage.find_task('x'))

    @mock.patch('rpaas.manager.LoadBalancer')
    def test_info(self, LoadBalancer):
        self.storage.store_task('x', 'something-id')
        lb = LoadBalancer.find.return_value
        lb.address = '192.168.1.1'
        manager = Manager(self.config)
        info = manager.info('x')
        self.assertIsNone(self.storage.find_task('x'))
        LoadBalancer.find.assert_called_with('x')
        self.assertItemsEqual(info, [{"label": "Address", "value": "192.168.1.1"}])
        self.assertEqual(manager.status('x'), '192.168.1.1')

    @mock.patch('rpaas.manager.tasks')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_info_status_pending(self, LoadBalancer, tasks):
        LoadBalancer.find.return_value = None
        self.storage.store_task('x', 'something-id')
        async_init = tasks.NewInstanceTask.return_value.AsyncResult
        async_init.return_value.status = 'PENDING'
        manager = Manager(self.config)
        info = manager.info('x')
        self.assertItemsEqual(info, [{"label": "Address", "value": "pending"}])
        LoadBalancer.find.assert_called_with('x')
        async_init.assert_called_with('something-id')
        self.assertEqual(manager.status('x'), 'pending')

    @mock.patch('rpaas.manager.tasks')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_info_status_failure(self, LoadBalancer, tasks):
        LoadBalancer.find.return_value = None
        self.storage.store_task('x', 'something-id')
        async_init = tasks.NewInstanceTask.return_value.AsyncResult
        async_init.return_value.status = 'FAILURE'
        manager = Manager(self.config)
        info = manager.info('x')
        self.assertItemsEqual(info, [{"label": "Address", "value": "failure"}])
        LoadBalancer.find.assert_called_with('x')
        async_init.assert_called_with('something-id')
        self.assertEqual(manager.status('x'), 'failure')

    def test_scale_instance_up(self):
        lb = self.LoadBalancer.find.return_value
        lb.name = 'x'
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.scale_instance('x', 5)
        self.Host.create.assert_called_with('my-host-manager', 'x', self.config)
        self.assertEqual(self.Host.create.call_count, 3)
        lb.add_host.assert_called_with(self.Host.create.return_value)
        self.assertEqual(lb.add_host.call_count, 3)

    @mock.patch('rpaas.tasks.nginx')
    def test_scale_instance_up_apply_binding_new_instances(self, nginx):
        self.storage.store_binding('x', 'myhost.com')
        self.storage.update_binding_certificate('x', 'my cert', 'my key')
        self.storage.add_binding_redirect('x', '/trantor', 'olivaw.com')
        lb = self.LoadBalancer.find.return_value
        lb.name = 'x'
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.scale_instance('x', 5)
        self.Host.create.assert_called_with('my-host-manager', 'x', self.config)
        self.assertEqual(self.Host.create.call_count, 3)
        lb.add_host.assert_called_with(self.Host.create.return_value)
        self.assertEqual(lb.add_host.call_count, 3)
        nginx.NginxDAV.assert_called_once_with(self.config)
        created_host = self.Host.create.return_value
        nginx_manager = nginx.NginxDAV.return_value
        nginx_manager.update_binding.assert_any_call(created_host.dns_name, '/', 'myhost.com')
        nginx_manager.update_binding.assert_any_call(created_host.dns_name, '/trantor', 'olivaw.com')
        nginx_manager.update_certificate.assert_any_call(created_host.dns_name, 'my cert', 'my key')

    def test_scale_instance_down(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.scale_instance('x', 1)
        lb.hosts[0].destroy.assert_called_once
        lb.remove_host.assert_called_once_with(lb.hosts[0])

    def test_scale_instance_error(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        with self.assertRaises(ScaleError):
            manager.scale_instance('x', 0)

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_bind_instance(self, LoadBalancer, nginx):
        lb = LoadBalancer.find.return_value
        nginx_manager = nginx.NginxDAV.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        lb.hosts[0].dns_name = 'h1'
        lb.hosts[1].dns_name = 'h2'
        manager = Manager(self.config)
        manager.bind('x', 'apphost.com')
        binding_data = self.storage.find_binding('x')
        self.assertDictEqual(binding_data, {'_id': 'x', 'app_host': 'apphost.com'})
        LoadBalancer.find.assert_called_with('x')
        nginx_manager.update_binding.assert_any_call('h1', '/', 'apphost.com')
        nginx_manager.update_binding.assert_any_call('h2', '/', 'apphost.com')

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_bind_instance_multiple_bind_hosts(self, LoadBalancer, nginx):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        manager.bind('x', 'apphost.com')
        binding_data = self.storage.find_binding('x')
        self.assertDictEqual(binding_data, {'_id': 'x', 'app_host': 'apphost.com'})
        LoadBalancer.find.assert_called_with('x')
        nginx_manager = nginx.NginxDAV.return_value
        nginx_manager.update_binding.assert_any_call(lb.hosts[0].dns_name, '/', 'apphost.com')
        nginx_manager.update_binding.assert_any_call(lb.hosts[1].dns_name, '/', 'apphost.com')
        nginx_manager.reset_mock()
        manager.bind('x', 'apphost.com')
        self.assertEqual(len(nginx_manager.mock_calls), 0)
        with self.assertRaises(rpaas.manager.BindError):
            manager.bind('x', 'another.host.com')
        self.assertEqual(len(nginx_manager.mock_calls), 0)

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_update_certificate(self, LoadBalancer, nginx):
        self.storage.store_binding('inst', 'app.host.com')
        lb = LoadBalancer.find.return_value
        nginx_manager = nginx.NginxDAV.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.update_certificate('inst', 'cert', 'key')

        LoadBalancer.find.assert_called_with('inst')
        nginx_manager.update_certificate.assert_any_call(lb.hosts[0].dns_name, 'cert', 'key')
        nginx_manager.update_certificate.assert_any_call(lb.hosts[1].dns_name, 'cert', 'key')

    @mock.patch('rpaas.manager.LoadBalancer')
    def test_update_certificate_no_binding(self, LoadBalancer):
        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.update_certificate('inst', 'cert', 'key')
        LoadBalancer.find.assert_called_with('inst')

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_add_redirect(self, LoadBalancer, nginx):
        self.storage.store_binding('inst', 'app.host.com')
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.add_redirect('inst', '/somewhere', 'my.other.host')

        LoadBalancer.find.assert_called_with('inst')
        binding_data = self.storage.find_binding('inst')
        self.assertDictEqual(binding_data, {
            '_id': 'inst',
            'app_host': 'app.host.com',
            'redirects': [
                {
                    'path': '/somewhere',
                    'destination': 'my.other.host',
                }
            ]
        })
        nginx_manager = nginx.NginxDAV.return_value
        nginx_manager.update_binding.assert_any_call(lb.hosts[0].dns_name, '/somewhere', 'my.other.host')
        nginx_manager.update_binding.assert_any_call(lb.hosts[1].dns_name, '/somewhere', 'my.other.host')

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_add_redirect_no_binding(self, LoadBalancer, nginx):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.add_redirect('inst', '/somewhere', 'my.other.host')
        LoadBalancer.find.assert_called_with('inst')
        self.assertEqual(len(nginx.NginxDAV.return_value.mock_calls), 0)

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_add_redirect_to_root(self, LoadBalancer, nginx):
        manager = Manager(self.config)
        with self.assertRaises(rpaas.manager.RedirectError):
            manager.add_redirect('inst', '/', 'my.other.host')
        self.assertEqual(len(LoadBalancer.mock_calls), 0)
        self.assertEqual(len(nginx.NginxDAV.return_value.mock_calls), 0)

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_delete_redirect(self, LoadBalancer, nginx):
        self.storage.store_binding('inst', 'app.host.com')
        self.storage.add_binding_redirect('inst', '/arrakis', 'dune.com')
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        manager.delete_redirect('inst', '/arrakis')

        LoadBalancer.find.assert_called_with('inst')
        binding_data = self.storage.find_binding('inst')
        self.assertDictEqual(binding_data, {
            '_id': 'inst',
            'app_host': 'app.host.com',
            'redirects': []
        })
        nginx_manager = nginx.NginxDAV.return_value
        nginx_manager.delete_binding.assert_any_call(lb.hosts[0].dns_name, '/arrakis')
        nginx_manager.delete_binding.assert_any_call(lb.hosts[1].dns_name, '/arrakis')

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_delete_redirect_error_no_redirect(self, LoadBalancer, nginx):
        self.storage.store_binding('inst', 'app.host.com')
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]

        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.delete_redirect('inst', '/')
        LoadBalancer.find.assert_called_with('inst')
        self.assertEqual(len(nginx.NginxDAV.return_value.mock_calls), 0)

    @mock.patch('rpaas.manager.nginx')
    @mock.patch('rpaas.manager.LoadBalancer')
    def test_delete_redirect_no_binding(self, LoadBalancer, nginx):
        lb = LoadBalancer.find.return_value
        lb.hosts = [mock.Mock(), mock.Mock()]
        manager = Manager(self.config)
        with self.assertRaises(storage.InstanceNotFoundError):
            manager.delete_redirect('inst', '/zahadum')
        LoadBalancer.find.assert_called_with('inst')
        self.assertEqual(len(nginx.NginxDAV.return_value.mock_calls), 0)
