# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import unittest

import consul

from rpaas import consul_manager


class ConsulManagerTestCase(unittest.TestCase):

    def setUp(self):
        os.environ.setdefault("RPAAS_SERVICE_NAME", "test-suite-rpaas")
        os.environ.setdefault("CONSUL_HOST", "127.0.0.1")
        self.consul = consul.Consul()
        self.consul.kv.delete("test-suite-rpaas", recurse=True)
        self.manager = consul_manager.ConsulManager()

    def test_write_location_root(self):
        self.manager.write_location("myrpaas", "/", destination="http://myapp.tsuru.io")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/locations/ROOT")
        expected = self.manager.config_manager.generate_host_config(path="/",
                                                                    destination="http://myapp.tsuru.io")
        self.assertEqual(expected, item[1]["Value"])

    def test_write_location_non_root(self):
        self.manager.write_location("myrpaas", "/admin/app_sites/",
                                    destination="http://myapp.tsuru.io")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/locations/___admin___app_sites___")
        expected = self.manager.config_manager.generate_host_config(path="/admin/app_sites/",
                                                                    destination="http://myapp.tsuru.io")
        self.assertEqual(expected, item[1]["Value"])

    def test_write_location_content(self):
        self.manager.write_location("myrpaas", "/admin/app_sites/",
                                    destination="http://myapp.tsuru.io",
                                    content="something nice")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/locations/___admin___app_sites___")
        self.assertEqual("something nice", item[1]["Value"])

    def test_set_certificate(self):
        self.manager.set_certificate("myrpaas", "certificate", "key")
        cert_item = self.consul.kv.get("test-suite-rpaas/myrpaas/ssl/cert")
        self.assertEqual("certificate", cert_item[1]["Value"])
        key_item = self.consul.kv.get("test-suite-rpaas/myrpaas/ssl/key")
        self.assertEqual("key", key_item[1]["Value"])

    def test_remove_location_root(self):
        self.manager.write_location("myrpaas", "/",
                                    destination="http://myapp.tsuru.io",
                                    content="something nice")
        self.manager.remove_location("myrpaas", "/")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/locations/ROOT")
        self.assertIsNone(item[1])

    def test_remove_location_non_root(self):
        self.manager.write_location("myrpaas", "/admin/app_sites/",
                                    destination="http://myapp.tsuru.io",
                                    content="something nice")
        self.manager.remove_location("myrpaas", "/admin/app_sites/")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/locations/___admin___app_sites___")
        self.assertIsNone(item[1])
