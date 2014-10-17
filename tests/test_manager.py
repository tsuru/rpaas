import unittest

import mock

from rpaas.manager import Manager


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
