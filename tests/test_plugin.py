# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import unittest
import re

import mock

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

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_scale(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        self.set_envs()
        self.addCleanup(self.delete_envs)
        result = mock.Mock()
        result.getcode.return_value = 201
        urlopen.return_value = result
        plugin.scale(["-i", "myinstance", "-n", "10"])
        Request.assert_called_with(self.target +
                                   "services/proxy/myinstance?" +
                                   "callback=/resources/myinstance/scale")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        request.add_data.assert_called_with("quantity=10")
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Instance successfully scaled to 10 units\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_scale_singular(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        self.set_envs()
        self.addCleanup(self.delete_envs)
        result = mock.Mock()
        result.getcode.return_value = 201
        urlopen.return_value = result
        plugin.scale(["-i", "myinstance", "-n", "1"])
        Request.assert_called_with(self.target +
                                   "services/proxy/myinstance?" +
                                   "callback=/resources/myinstance/scale")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        request.add_data.assert_called_with("quantity=1")
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Instance successfully scaled to 1 unit\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
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
            plugin.scale(["-i", "myinstance", "-n", "10"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/myinstance?" +
                                   "callback=/resources/myinstance/scale")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        request.add_data.assert_called_with("quantity=10")
        urlopen.assert_called_with(request)
        stderr.write.assert_called_with("ERROR: Invalid quantity\n")

    @mock.patch("sys.stderr")
    def test_scale_no_target(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-i", "myinstance", "-n", "10"])
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
            plugin.scale(["-i", "myinstance", "-n", "10"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with("ERROR: missing TSURU_TOKEN\n")

    @mock.patch("sys.stderr")
    def test_scale_missing_instance(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-n", "1"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        expected_msg = "scale: error: argument -i/--instance is required\n"
        stderr.write.assert_called_with(expected_msg)

    @mock.patch("sys.stderr")
    def test_scale_missing_quantity(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-i", "abc"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        expected_msg = "scale: error: argument -n/--quantity is required\n"
        stderr.write.assert_called_with(expected_msg)

    @mock.patch("sys.stderr")
    def test_scale_invalid_quantity(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-i", "abc", "-n", "0"])
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

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_certificate(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        with mock.patch("io.open", mock.mock_open()) as open:
            open.return_value.read.return_value = 'my content'
            plugin.certificate(['-i', 'inst1', '-c', 'cert.crt', '-k', 'key.key'])
            open.assert_any_call('cert.crt', 'rb')
            open.assert_any_call('key.key', 'rb')
        Request.assert_called_with(self.target +
                                   "services/proxy/inst1?" +
                                   "callback=/resources/inst1/certificate")
        request.add_header.assert_has_call("Authorization", "bearer " + self.token)
        data = request.add_data.call_args[0][0]

        has_content = re.search(r'cert\.crt.*my content.*key\.key.*my content', data, re.DOTALL)
        self.assertTrue(has_content)
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Certificate successfully updated\n")

    @mock.patch("sys.stderr")
    def test_redirect_args(self, stderr):
        parsed = plugin.get_redirect_args(
            ['add', '-i', 'myinst', '-p', '/path/out', '-d', 'destination.host'])
        self.assertEqual(parsed.action, 'add')
        self.assertEqual(parsed.path, '/path/out')
        self.assertEqual(parsed.destination, 'destination.host')
        parsed = plugin.get_redirect_args(['remove', '-i', 'myinst', '-p', '/path/out'])
        self.assertEqual(parsed.action, 'remove')
        self.assertEqual(parsed.path, '/path/out')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_redirect_args(['add', '-i', 'myinst', '-p', '/path/out'])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('destination is required to add action\n')
        with self.assertRaises(SystemExit) as cm:
            plugin.get_redirect_args(['-i', 'myinst', '-p', '/path/out'])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with('redirect: error: too few arguments\n')

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_redirect(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.redirect(['add', '-i', 'myinst', '-p', '/path/out', '-d', 'destination.host'])
        Request.assert_called_with(self.target +
                                   "services/proxy/myinst?" +
                                   "callback=/resources/myinst/redirect")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("path=/path/out&destination=destination.host")
        self.assertEqual(request.get_method(), 'POST')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Redirect successfully added\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_redirect_remove(self, stdout, Request, urlopen):
        request = Request.return_value
        urlopen.return_value.getcode.return_value = 200
        self.set_envs()
        self.addCleanup(self.delete_envs)
        plugin.redirect(['remove', '-i', 'myinst', '-p', '/path/out'])
        Request.assert_called_with(self.target +
                                   "services/proxy/myinst?" +
                                   "callback=/resources/myinst/redirect")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type", "application/x-www-form-urlencoded")
        request.add_data.assert_called_with("path=/path/out")
        self.assertEqual(request.get_method(), 'DELETE')
        urlopen.assert_called_with(request)
        stdout.write.assert_called_with("Redirect successfully removed\n")
