# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import unittest

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
        expected_msg = "usage: scale [-h] [-i INSTANCE] [-n QUANTITY]\n"
        stderr.write.assert_called_with(expected_msg)

    @mock.patch("sys.stderr")
    def test_scale_missing_quantity(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            plugin.scale(["-i", "abc"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        expected_msg = "usage: scale [-h] [-i INSTANCE] [-n QUANTITY]\n"
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
        args = ["hello", "world"]
        plugin.main("scale", args)
        plugin.scale.assert_called_with(args)

    @mock.patch("sys.stderr")
    def test_main_command_not_found(self, stderr):
        args = ["hello", "world"]
        with self.assertRaises(SystemExit) as cm:
            plugin.main("wat", args)
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with(u'command "wat" not found\n')
