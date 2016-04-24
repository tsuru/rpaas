# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import unittest
import mock

import consul

from rpaas import consul_manager


class ConsulManagerTestCase(unittest.TestCase):

    def setUp(self):
        self.master_token = "rpaas-test"
        os.environ.setdefault("RPAAS_SERVICE_NAME", "test-suite-rpaas")
        os.environ.setdefault("CONSUL_HOST", "127.0.0.1")
        os.environ.setdefault("CONSUL_TOKEN", self.master_token)
        self.consul = consul.Consul(token=self.master_token)
        self.consul.kv.delete("test-suite-rpaas", recurse=True)
        self._remove_tokens()
        self.manager = consul_manager.ConsulManager(os.environ)

    def _remove_tokens(self):
        for token in self.consul.acl.list():
            if token["ID"] not in (self.master_token, "anonymous"):
                self.consul.acl.destroy(token["ID"])

    def test_generate_token(self):
        token = self.manager.generate_token("myrpaas")
        acl = self.consul.acl.info(token)
        expected_rules = consul_manager.ACL_TEMPLATE.format(service_name="test-suite-rpaas",
                                                            instance_name="myrpaas")
        self.assertEqual("test-suite-rpaas/myrpaas/token", acl["Name"])
        self.assertEqual(expected_rules, acl["Rules"])
        self.assertEqual("client", acl["Type"])

    def test_destroy_token(self):
        token = self.manager.generate_token("myrpaas")
        self.manager.destroy_token(token)
        self.assertIsNone(self.consul.acl.info(token))

    def test_destroy_instance(self):
        self.manager.write_healthcheck("myrpaas")
        self.manager.write_location("myrpaas", "/", destination="http://myapp.tsuru.io")
        self.manager.destroy_instance("myrpaas")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/healthcheck")
        self.assertIsNone(item[1])
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/locations/ROOT")
        self.assertIsNone(item[1])

    def test_remove_node(self):
        self.consul.kv.put("test-suite-rpaas/myrpaas/status/test-server", "service OK")
        self.consul.kv.put("test-suite-rpaas/myrpaas/status/test-server-2", "service OK")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/status/test-server")
        self.assertEqual(item[1]["Value"], "service OK")
        self.manager.remove_node("myrpaas", "test-server")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/status/test-server")
        self.assertIsNone(item[1])
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/status/test-server-2")
        self.assertEqual(item[1]["Value"], "service OK")

    def test_node_hostname(self):
        host = mock.Mock()
        host.dns_name = '127.0.0.1'
        node_hostname = self.manager.node_hostname(host)
        self.assertEqual('rpaas-test', node_hostname)

    def test_node_hostname_not_found(self):
        host = mock.Mock()
        host.dns_name = '10.0.0.1'
        node_hostname = self.manager.node_hostname(host)
        self.assertEqual(None, node_hostname)

    def test_node_status(self):
        self.consul.kv.put("test-suite-rpaas/myrpaas/status/my-server-1", "service OK")
        self.consul.kv.put("test-suite-rpaas/myrpaas/status/my-server-2", "service DEAD")
        node_status = self.manager.node_status("myrpaas")
        self.assertDictEqual(node_status, {'my-server-1': 'service OK', 'my-server-2': 'service DEAD'})

    def test_write_healthcheck(self):
        self.manager.write_healthcheck("myrpaas")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/healthcheck")
        self.assertEqual("true", item[1]["Value"])

    def test_remove_healthcheck(self):
        self.manager.write_healthcheck("myrpaas")
        self.manager.remove_healthcheck("myrpaas")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/healthcheck")
        self.assertIsNone(item[1])

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

    def test_write_location_content_strip(self):
        self.manager.write_location("myrpaas", "/admin/app_sites/",
                                    destination="http://myapp.tsuru.io",
                                    content=" something nice              \n")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/locations/___admin___app_sites___")
        self.assertEqual("something nice", item[1]["Value"])

    def test_write_block_http_content(self):
        self.manager.write_block("myrpaas", "http",
                                 content=" something nice in http         \n")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/blocks/http/ROOT")
        expected_block = ("## Begin custom RpaaS http block ##\n"
                          "something nice in http"
                          "\n## End custom RpaaS http block ##")
        self.assertEqual(expected_block, item[1]["Value"])

    def test_write_block_server_content(self):
        self.manager.write_block("myrpaas", "server",
                                 content=" something nice in server         \n")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/blocks/server/ROOT")
        expected_block = ("## Begin custom RpaaS server block ##\n"
                          "something nice in server"
                          "\n## End custom RpaaS server block ##")
        self.assertEqual(expected_block, item[1]["Value"])

    def test_get_certificate(self):
        origin_cert, origin_key = "cert", "key"
        self.consul.kv.put("test-suite-rpaas/myrpaas/ssl/cert", origin_cert)
        self.consul.kv.put("test-suite-rpaas/myrpaas/ssl/key", origin_key)
        cert, key = self.manager.get_certificate("myrpaas")
        self.assertEqual(origin_cert, cert)
        self.assertEqual(origin_key, key)

    def test_get_certificate_undefined(self):
        with self.assertRaises(ValueError):
            self.manager.get_certificate("myrpaas")

    def test_set_certificate(self):
        self.manager.set_certificate("myrpaas", "certificate", "key")
        cert_item = self.consul.kv.get("test-suite-rpaas/myrpaas/ssl/cert")
        self.assertEqual("certificate", cert_item[1]["Value"])
        key_item = self.consul.kv.get("test-suite-rpaas/myrpaas/ssl/key")
        self.assertEqual("key", key_item[1]["Value"])

    def test_set_certificate_crlf(self):
        self.manager.set_certificate("myrpaas", "certificate\r\nvalid\r\n", "key\r\nvalid\r\n\r\n")
        cert_item = self.consul.kv.get("test-suite-rpaas/myrpaas/ssl/cert")
        self.assertEqual("certificate\nvalid\n", cert_item[1]["Value"])
        key_item = self.consul.kv.get("test-suite-rpaas/myrpaas/ssl/key")
        self.assertEqual("key\nvalid\n\n", key_item[1]["Value"])

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

    def test_remove_block_server_root(self):
        self.manager.write_block("myrpaas", "server",
                                 "something nice in server")
        self.manager.remove_block("myrpaas", "server")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/blocks/server/ROOT")
        empty_block_value = '## Begin custom RpaaS server block ##\n\n## End custom RpaaS server block ##'
        self.assertEqual(item[1]['Value'], empty_block_value)

    def test_remove_block_http_root(self):
        self.manager.write_block("myrpaas", "http", "something nice in http")
        self.manager.remove_block("myrpaas", "http")
        item = self.consul.kv.get("test-suite-rpaas/myrpaas/blocks/http/ROOT")
        empty_block_value = '## Begin custom RpaaS http block ##\n\n## End custom RpaaS http block ##'
        self.assertEqual(item[1]['Value'], empty_block_value)

    def test_list_no_block(self):
        items = self.manager.list_blocks("myrpaas")
        self.assertEqual(items, [])

    def test_list_one_block(self):
        self.manager.write_block("myrpaas", "server",
                                 "something nice in server")
        items = self.manager.list_blocks("myrpaas")
        self.assertEqual(1, len(items))
        self.assertEqual("something nice in server\n", items[0]["content"])

    def test_list_block(self):
        self.manager.write_block("myrpaas", "server",
                                 "something nice in server")
        self.manager.write_block("myrpaas", "http", "something nice in http")
        items = self.manager.list_blocks("myrpaas")
        self.assertEqual(2, len(items))
        self.assertEqual("something nice in http\n", items[0]["content"])
        self.assertEqual("something nice in server\n", items[1]["content"])
