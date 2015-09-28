# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json
import os
import unittest
import urllib

import mock

from rpaas import admin_plugin


class CommandNotFoundErrorTestCase(unittest.TestCase):

    def test_init(self):
        error = admin_plugin.CommandNotFoundError("scale")
        self.assertEqual(("scale",), error.args)
        self.assertEqual("scale", error.name)

    def test_str(self):
        error = admin_plugin.CommandNotFoundError("scale")
        self.assertEqual('command "scale" not found', str(error))

    def test_unicode(self):
        error = admin_plugin.CommandNotFoundError("scale")
        self.assertEqual(u'command "scale" not found', unicode(error))


class TsuruAdminPluginTestCase(unittest.TestCase):

    def setUp(self):
        os.environ["TSURU_TARGET"] = self.target = "https://cloud.tsuru.io/"
        os.environ["TSURU_TOKEN"] = self.token = "abc123"
        admin_plugin.SERVICE_NAME = self.service_name = "rpaas"

    def tearDown(self):
        del os.environ["TSURU_TARGET"], os.environ["TSURU_TOKEN"]

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_list_plans(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        result.read.return_value = """[
            {"name":"small","description":"small vm","config":{"serviceofferingid":"abcdef-123"}},
            {"name":"medium","description":"medium vm","config":{"serviceofferingid":"abcdef-126"}}
        ]"""
        urlopen.return_value = result
        admin_plugin.list_plans([])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        urlopen.assert_called_with(request)
        expected_calls = [
            mock.call("List of available plans (use show-plan for details):\n\n"),
            mock.call("small\t\tsmall vm\n"),
            mock.call("medium\t\tmedium vm\n"),
        ]
        self.assertEqual(expected_calls, stdout.write.call_args_list)

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_list_plans_failure(self, stderr, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 400
        result.read.return_value = "Something went wrong"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.list_plans([])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        urlopen.assert_called_with(request)
        stderr.write.assert_called_with("ERROR: Something went wrong\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_create_plan(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 201
        urlopen.return_value = result
        admin_plugin.create_plan(["-n", "small", "-d", "smalll vms", "-c",
                                  'SERVICE=abcdef-123 NAME="something nice" DATA=go go go DATE=\'2015\''])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type",
                                           "application/x-www-form-urlencoded")
        params = {
            "name": "small",
            "description": "smalll vms",
            "config": json.dumps({"SERVICE": "abcdef-123",
                                  "NAME": "something nice",
                                  "DATA": "go go go",
                                  "DATE": "2015"}),
        }
        request.add_data.assert_called_with(urllib.urlencode(params))
        stdout.write.assert_called_with("Plan successfully created\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_create_plan_failure(self, stderr, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 409
        result.read.return_value = "Plan already exists\n"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.create_plan(["-n", "small", "-d", "smalll vms", "-c",
                                      "SERVICE=abcdef-123"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type",
                                           "application/x-www-form-urlencoded")
        stderr.write.assert_called_with("ERROR: Plan already exists\n")

    @mock.patch("sys.stderr")
    def test_create_plan_invalid_config(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.create_plan(["-n", "small", "-d", "smalll vms", "-c",
                                      "SERVICE"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with("ERROR: Invalid config format, supported format is KEY=VALUE\n")
