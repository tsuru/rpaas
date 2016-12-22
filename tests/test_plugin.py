# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import unittest
import re

import mock
import argparse

from rpaas import plugin


class CommandNotFoundErrorTestCase(unittest.TestCase):

    def test_init(self):
        error = plugin.CommandNotFoundError("scale")
        self.assertEqual(("scale",), error.args)
        self.assertEqual("scale", error.name)

    def test_str(self):
        error = plugin.CommandNotFoundError("scale")
        self.assertEqual('command "scale" not found', str(error))

    def test_unicode(self):
        error = plugin.CommandNotFoundError("scale")
        self.assertEqual(u'command "scale" not found', unicode(error))


class TsuruPluginTestCase(unittest.TestCase):

    def set_envs(self):
        os.environ["TSURU_TARGET"] = self.target = "https://cloud.tsuru.io/"
        os.environ["TSURU_TOKEN"] = self.token = "abc123"

    def delete_envs(self):
        del os.environ["TSURU_TARGET"], os.environ["TSURU_TOKEN"]

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_scale(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        self.set_envs()
        self.addCleanup(self.delete_envs)
        result = mock.Mock()
        result.getcode.return_value = 201
        urlopen.return_value = result
        plugin.scale(["-s", "myservice", "-i", "myinstance", "-n", "10"])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinstance?" +
                                   "callback=/resources/myinstance/scale")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        request.add_data.assert_called_with("quantity=10")
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Instance successfully scaled to 10 units\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_scale_singular(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        self.set_envs()
        self.addCleanup(self.delete_envs)
        result = mock.Mock()
        result.getcode.return_value = 201
        urlopen.return_value = result
        plugin.scale(["-s", "myservice", "-i", "myinstance", "-n", "1"])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinstance?" +
                                   "callback=/resources/myinstance/scale")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        request.add_data.assert_called_with("quantity=1")
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Instance successfully scaled to 1 unit\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stderr")
    def test_scale_failure(self, stderr, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        self.set_envs()
        self.addCleanup(self.delete_envs)
        result = mock.Mock()
        result.getcode.return_value = 400
        result.read.return_value = "Invalid quantity"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-s", "myservice", "-i", "myinstance", "-n", "10"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinstance?" +
                                   "callback=/resources/myinstance/scale")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        request.add_data.assert_called_with("quantity=10")
        urlopen.assert_called_with(request)
        stderr.write.assert_called_with("ERROR: Invalid quantity\n")

    @mock.patch("sys.stderr")
    def test_scale_no_target(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-s", "myservice", "-i", "myinstance", "-n", "10"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with("ERROR: missing TSURU_TARGET\n")

    @mock.patch("sys.stderr")
    def test_scale_no_token(self, stderr):
        self.set_envs()
        self.addCleanup(self.delete_envs)
        del os.environ["TSURU_TOKEN"]
        self.addCleanup(self.set_envs)
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-s", "myservice", "-i", "myinstance", "-n", "10"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with("ERROR: missing TSURU_TOKEN\n")

    @mock.patch("sys.stderr")
    def test_scale_missing_service(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-n", "1"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        expected_msg = "scale: error: argument -s/--service is required\n"
        stderr.write.assert_called_with(expected_msg)

    @mock.patch("sys.stderr")
    def test_scale_missing_instance(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-s", "myservice", "-n", "1"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        expected_msg = "scale: error: argument -i/--instance is required\n"
        stderr.write.assert_called_with(expected_msg)

    @mock.patch("sys.stderr")
    def test_scale_missing_quantity(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-s", "myservice", "-i", "abc"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        expected_msg = "scale: error: argument -n/--quantity is required\n"
        stderr.write.assert_called_with(expected_msg)

    @mock.patch("sys.stderr")
    def test_scale_invalid_quantity(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-s", "myservice", "-i", "abc", "-n", "0"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        expected_msg = "quantity must be a positive integer\n"
        stderr.write.assert_called_with(expected_msg)

    def test_get_command(self):
        cmd = plugin.get_command("scale")
        self.assertEqual(plugin.scale, cmd)

    def test_get_command_not_found(self):
        with self.assertRaises(plugin.CommandNotFoundError) as cm:
            plugin.get_command("something i don't know")
        exc = cm.exception
        self.assertEqual("something i don't know", exc.name)

    def test_main(self):
        original_scale = plugin.scale

        def clean():
            plugin.scale = original_scale
        self.addCleanup(clean)
        plugin.scale = mock.Mock()
        base_args = ["hello", "world"]
        plugin.main(["scale"] + base_args)
        plugin.scale.assert_called_with(base_args)

    @mock.patch("sys.stderr")
    def test_main_command_not_found(self, stderr):
        args = ["hello", "world"]
        with self.assertRaises(SystemExit) as cm:
            plugin.main(["wat"] + args)
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with(u'command "wat" not found\n')

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_certificate(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        with mock.patch("io.open", mock.mock_open()) as open:
            open.return_value.read.return_value = 'my content'
            plugin.certificate(['-s', 'service1', '-i', 'inst1', '-c', 'cert.crt', '-k', 'key.key'])
            open.assert_any_call('cert.crt', 'rb')
            open.assert_any_call('key.key', 'rb')
        Request.assert_called_with(self.target +
                                   "services/service1/proxy/inst1?" +
                                   "callback=/resources/inst1/certificate")
        request.add_header.assert_has_call("Authorization", "bearer " + self.token)
        data = request.add_data.call_args[0][0]

        has_content = re.search(r'cert\.crt.*my content.*key\.key.*my content', data, re.DOTALL)
        self.assertTrue(has_content)
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Certificate successfully updated\n")

    @mock.patch("sys.stderr")
    def test_route_args(self, stderr):
        parsed = plugin.get_route_args(
            ['add', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out', '-d', 'destination.host'])
        self.assertEqual(parsed.action, 'add')
        self.assertEqual(parsed.path, '/path/out')
        self.assertEqual(parsed.destination, 'destination.host')
        parsed = plugin.get_route_args(
            ['add', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out', '-c', 'my content'])
        self.assertEqual(parsed.action, 'add')
        self.assertEqual(parsed.path, '/path/out')
        self.assertEqual(parsed.content, 'my content')
        parsed = plugin.get_route_args(['remove', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out'])
        self.assertEqual(parsed.action, 'remove')
        self.assertEqual(parsed.path, '/path/out')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_route_args(['add', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out'])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('destination xor content are required to add action\n')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_route_args([
                'add', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out',
                '-d', 'destination.host', '-c', 'my content',
            ])
        exc = cm.exception
        self.assertEqual(3, exc.code)
        stderr.write.assert_called_with('cannot have both destination and content\n')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_route_args(['-s', 'myservice', '-i', 'myinst', '-p', '/path/out'])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('route: error: too few arguments\n')

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_route(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.route(['add', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out', '-d', 'destination.host'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/route")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("path=%2Fpath%2Fout&destination=destination.host")
        self.assertEqual(request.get_method(), 'POST')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("route successfully added\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_route_file_content(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        path = os.path.join(os.path.dirname(__file__), "testdata", "location")
        plugin.route(['add', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out', '-c', '@'+path])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/route")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("content=content%0A&path=%2Fpath%2Fout")
        self.assertEqual(request.get_method(), 'POST')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("route successfully added\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_block_add_file_content(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        path = os.path.join(os.path.dirname(__file__), "testdata", "block_http")
        plugin.block(['add', '-s', 'myservice', '-i', 'myinst', '-b', 'http', '-c', '@'+path])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/block")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("content=content%0A&block_name=http")
        self.assertEqual(request.get_method(), 'POST')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("block successfully added\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_block_add(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.block(['add', '-s', 'myservice', '-i', 'myinst', '-b', 'http', '-c', 'lalala'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/block")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("content=lalala&block_name=http")
        self.assertEqual(request.get_method(), 'POST')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("block successfully added\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_block_remove(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.block(['remove', '-s', 'myservice', '-i', 'myinst', '-b', 'http'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/block/http")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        self.assertEqual(request.get_method(), 'DELETE')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("block successfully removed\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_block_list(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        urlopen.return_value.read.return_value = '{"_id": "myinst", ' + \
            '"blocks": [{"block_name": "http", "content": "my content"}, ' + \
            '{"block_name": "server", "content": "server content"}]}'
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.block(['list', '-s', 'myservice', '-i', 'myinst'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/block")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual(request.get_method(), 'GET')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("""block_name: content

http: my content
server: server content
""")

    @mock.patch("sys.stderr")
    def test_block_args(self, stderr):
        parsed = plugin.get_block_args(
            ['add', '-s', 'myservice', '-i', 'myinst', '-b', 'http', '-c', 'my block'])
        self.assertEqual(parsed.action, 'add')
        self.assertEqual(parsed.block_name, 'http')
        self.assertEqual(parsed.content, 'my block')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_block_args(['add', '-s', 'myservice', '-i', 'myinst', '-b', 'server'])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('block_name and content are required\n')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_block_args([
                'add', '-s', 'myservice', '-i', 'myinst', '-c', 'my content',
            ])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('block_name and content are required\n')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_block_args(
                ['remove', '-s', 'myservice', '-i', 'myinst', '-b', 'blabla']
            )
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with(
            'block: error: argument -b/--block_name: Block must be "server" or "http"\n'
        )
        with self.assertRaises(SystemExit) as cm:
            plugin.get_block_args(
                ['remove', '-s', 'myservice', '-i', 'myinst']
            )
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('block_name is required\n')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_block_args(
                ['-s', 'myservice', '-i', 'myinst', '-b', 'http']
            )
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('block: error: too few arguments\n')

    def test_nginx_block(self):
        self.assertEqual('http', plugin.nginx_block('http'))
        with self.assertRaises(argparse.ArgumentTypeError):
            plugin.nginx_block('lelele')

    @mock.patch("sys.stderr")
    def test_purge_args(self, stderr):
        _, _, path, _ = plugin.get_purge_args(['-s', 'myservice', '-i', 'myinst', '-l', '/foo/bar'])
        self.assertEqual(path, '/foo/bar')
        _, _, path, _ = plugin.get_purge_args(['-s', 'myservice', '-i', 'myinst', '-l', '/foo/bar?a=b&c=d'])
        self.assertEqual(path, '/foo/bar?a=b&c=d')

        _, _, path, preserve_path = plugin.get_purge_args(['-s', 'myservice', '-i', 'myinst', '-l',
                                                           'http://www.example.com/'])
        self.assertFalse(preserve_path)
        self.assertEqual(path, '/')

        _, _, path, preserve_path = plugin.get_purge_args(['-s', 'myservice', '-i', 'myinst', '-l',
                                                           'http://www.example.com/?a=b', '-p'])
        self.assertTrue(preserve_path)
        self.assertEqual(path, 'http://www.example.com/?a=b')

        _, _, path, preserve_path = plugin.get_purge_args(['-s', 'myservice', '-i', 'myinst', '-l',
                                                           'http://www.example.com/'])
        self.assertFalse(preserve_path)
        self.assertEqual(path, '/')

        _, _, path, _ = plugin.get_purge_args(['-s', 'myservice', '-i', 'myinst', '-l', 'www.example.com/'])
        self.assertEqual(path, 'www.example.com/')
        with self.assertRaises(SystemExit) as cm:
            _, _, path, _ = plugin.get_purge_args(['-s', 'myservice', '-i', 'myinst', '-l',
                                                   'http://www.example.com'])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('purge: path is required for purge location\n')

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_purge(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.purge(['-s', 'myservice', '-i', 'myinst', '-l', '/foo/bar?a=b&c=d'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/purge")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("path=%2Ffoo%2Fbar%3Fa%3Db%26c%3Dd&preserve_path=False")
        self.assertEqual(request.get_method(), 'POST')
        urlopen.assert_called_with(request)

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_status(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        urlopen.return_value.read.return_value = '{"vm-1":{"status": "Reload OK","address": "10.1.1.1"},' + \
                                                 '"vm-2":{"status": "Reload FAIL","address": "10.2.2.2"},' + \
                                                 '"vm-3":{"status": "Reload Ok"}}'
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.status(['-s', 'myservice', '-i', 'myinst'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/node_status")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        self.assertEqual(request.get_method(), 'GET')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("""Node Name: Status - Address

vm-1: Reload OK - 10.1.1.1
vm-2: Reload FAIL - 10.2.2.2
vm-3: Reload Ok - *
""")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_route_with_content(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.route(['add', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out', '-c', 'my content'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/route")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("content=my+content&path=%2Fpath%2Fout")
        self.assertEqual(request.get_method(), 'POST')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("route successfully added\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_route_remove(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.route(['remove', '-s', 'myservice', '-i', 'myinst', '-p', '/path/out'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/route")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("path=%2Fpath%2Fout")
        self.assertEqual(request.get_method(), 'DELETE')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("route successfully removed\n")

    @mock.patch("rpaas.plugin.urlopen")
    @mock.patch("rpaas.plugin.Request")
    @mock.patch("sys.stdout")
    def test_route_list(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        urlopen.return_value.read.return_value = '{"_id": "myinst", ' + \
            '"paths": [{"path": "/a", "content": "desta"}, {"path": "/b", "content": "destb"}]}'
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.route(['list', '-s', 'myservice', '-i', 'myinst'])
        Request.assert_called_with(self.target +
                                   "services/myservice/proxy/myinst?" +
                                   "callback=/resources/myinst/route")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual(request.get_method(), 'GET')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("path = /a\ncontent = desta\npath = /b\ncontent = destb\n")
