import unittest

import mock

from rpaas.manager import Manager, ScaleError


class ManagerTestCase(unittest.TestCase):

    def setUp(self):
        self.lb_patcher = mock.patch('rpaas.manager.LoadBalancer')
        self.host_patcher = mock.patch('rpaas.manager.Host')
        self.LoadBalancer = self.lb_patcher.start()
        self.Host = self.host_patcher.start()
        self.config = {
            'HOST_MANAGER': 'my-host-manager',
            'LB_MANAGER': 'my-lb-manager'
        }
        self.m = Manager(self.config)

    def tearDown(self):
        self.lb_patcher.stop()
        self.host_patcher.stop()

    def test_new_instance(self):
        self.m.new_instance('x')
        host = self.Host.create.return_value
        lb = self.LoadBalancer.create.return_value
        self.Host.create.assert_called_with('my-host-manager', 'x', self.config)
        self.LoadBalancer.create.assert_called_with('my-lb-manager', 'x', self.config)
        lb.add_host.assert_called_with(host)

    def test_remove_instance(self):
        lb = self.LoadBalancer.find.return_value
        lb.hosts = [mock.Mock()]
        self.m.remove_instance('x')
        self.LoadBalancer.find.assert_called_with('x')
        for h in lb.hosts:
            h.destroy.assert_called_once()
        lb.destroy.assert_called_once()

    def test_info(self):
        lb = self.LoadBalancer.find.return_value
        lb.address = '192.168.1.1'
        info = self.m.info('x')
        self.LoadBalancer.find.assert_called_with('x')
        self.assertItemsEqual(info, [{"label": "Address", "value": "192.168.1.1"}])

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
