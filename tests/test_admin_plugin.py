# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime
import json
import os
import time
import unittest
import urllib
import urllib2
import urlparse
from io import StringIO

import mock

from rpaas import admin_plugin
from bson import json_util


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


class FakeURLopenResponse(StringIO):

    def __init__(self, *args, **kwargs):
        try:
            self.code = args[1]
        except IndexError:
            self.code = 200
            pass
        try:
            self.msg = args[2]
            self.content = args[2]
        except IndexError:
            self.msg = "OK"
            pass
        if 'headers' in kwargs:
            self.headers = kwargs['headers']
        else:
            self.headers = {'content-type': 'text/plain; charset=utf-8'}
        StringIO.__init__(self, unicode(args[0]))

    def getcode(self):
        return self.code


class TsuruAdminPluginTestCase(unittest.TestCase):

    def setUp(self):
        os.environ["TSURU_TARGET"] = self.target = "https://cloud.tsuru.io/"
        os.environ["TSURU_TOKEN"] = self.token = "abc123"
        os.environ["TZ"] = 'US/Eastern'
        time.tzset()
        self.service_name = "rpaas"
        self.maxDiff = None

    def tearDown(self):
        del os.environ["TSURU_TARGET"], os.environ["TSURU_TOKEN"]

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_proxy_request_http_error(self, stderr, Request, urlopen):
        lines = []
        stderr.write.side_effect = lambda data, **kw: lines.append(data)
        request = mock.Mock()
        Request.return_value = request
        fp = mock.Mock()
        fp.read.return_value = "something went wrong"
        urlopen.side_effect = urllib2.HTTPError("/", 400, "Bad request", {}, fp)
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.proxy_request(self.service_name, "/", body="waat",
                                       method="GET")
        exc = cm.exception
        self.assertEqual(1, exc.code)
        expected_output = r"""ERROR: 400 - Bad request
       something went wrong
"""
        self.assertEqual(expected_output, "".join(lines))

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
        admin_plugin.handle_plan(["list", "-s", self.service_name])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
        urlopen.assert_called_with(request)
        expected_calls = [
            mock.call("List of available plans (use show-plan for details):\n\n"),
            mock.call("small\t\tsmall vm\n"),
            mock.call("medium\t\tmedium vm\n"),
        ]
        self.assertEqual(expected_calls, stdout.write.call_args_list)

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_list_plans_as_default_option(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        result.read.return_value = """[
            {"name":"small","description":"small vm","config":{"serviceofferingid":"abcdef-123"}},
            {"name":"medium","description":"medium vm","config":{"serviceofferingid":"abcdef-126"}}
        ]"""
        urlopen.return_value = result
        admin_plugin.handle_plan(["-s", self.service_name])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
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
            admin_plugin.handle_plan(["list", "-s", self.service_name])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_called_with("Authorization",
                                              "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
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
        admin_plugin.handle_plan(["create", "-s", self.service_name, "-n", "small", "-d", "smalll vms", "-c",
                                  'SERVICE=abcdef-123 NAME="something nice" DATA="go go go" DATE=\'2015\''])
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
        self.assertEqual("POST", request.get_method())
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
            admin_plugin.handle_plan(["create", "-s", self.service_name, "-n", "small", "-d", "smalll vms", "-c",
                                      "SERVICE=abcdef-123"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type",
                                           "application/x-www-form-urlencoded")
        self.assertEqual("POST", request.get_method())
        stderr.write.assert_called_with("ERROR: Plan already exists\n")

    @mock.patch("sys.stderr")
    def test_create_plan_invalid_config(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.handle_plan(["create", "-s", self.service_name, "-n", "small", "-d", "smalll vms", "-c",
                                      "SERVICE"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with(
            "ERROR: Invalid config format, supported format is KEY=VALUE\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_update_plan(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        urlopen.return_value = result

        plan = {"name": "small", "description": "smalll vms",
                "config": {"SERVICE": "abcd", "GREETINGS": "hello"}}
        old_retrieve = admin_plugin._retrieve_plan
        admin_plugin._retrieve_plan = lambda service_name, name: plan

        def recover_retrieve():
            admin_plugin._retrieve_plan = old_retrieve
        self.addCleanup(recover_retrieve)

        admin_plugin.handle_plan(["update", "-s", self.service_name, "-n", "small", "-d", "smalll vms", "-c",
                                  '''SERVICE=abcdef-123 NAME="some thing" DATA="go go go" DATE=\'2015\'
                                     wat="" RANDOM_BASE64=bm90aGluZyB0byBzZWUgaGVyZQo= GREETINGS=""'''])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans/small")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type",
                                           "application/x-www-form-urlencoded")

        raw_params = request.add_data.call_args[0][0]
        parsed_params = urlparse.parse_qs(raw_params)
        parsed_params["description"] = unicode(parsed_params["description"][0])
        parsed_params["config"] = json.loads(parsed_params["config"][0])

        expected_params = {
            "description": u"smalll vms",
            "config": {"SERVICE": "abcdef-123",
                       "NAME": "some thing",
                       "DATA": "go go go",
                       "DATE": "2015",
                       "RANDOM_BASE64": "bm90aGluZyB0byBzZWUgaGVyZQo="},
        }
        self.assertEqual(expected_params, parsed_params)
        self.assertEqual("PUT", request.get_method())
        stdout.write.assert_called_with("Plan successfully updated\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_update_plan_failure(self, stderr, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request

        plan = {"name": "small", "description": "smalll vms", "config": {}}
        old_retrieve = admin_plugin._retrieve_plan
        admin_plugin._retrieve_plan = lambda service_name, name: plan

        def recover_retrieve():
            admin_plugin._retrieve_plan = old_retrieve
        self.addCleanup(recover_retrieve)

        result = mock.Mock()
        result.getcode.return_value = 404
        result.read.return_value = "plan not found\n"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.handle_plan(["update", "-s", self.service_name, "-n", "small", "-d", "smalll vms", "-c",
                                      "SERVICE=abcdef-123"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans/small")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_header.assert_any_call("Content-Type",
                                           "application/x-www-form-urlencoded")
        self.assertEqual("PUT", request.get_method())
        stderr.write.assert_called_with("ERROR: plan not found\n")

    @mock.patch("sys.stderr")
    def test_update_plan_invalid_config(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.handle_plan(["update", "-s", self.service_name, "-n", "small", "-d", "smalll vms", "-c",
                                      "SERVICE"])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with(
            "ERROR: Invalid config format, supported format is KEY=VALUE\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_show_plan(self, stdout, Request, urlopen):
        lines = []
        stdout.write.side_effect = lambda data, **kw: lines.append(data)
        plan_data = u"""{"name":"small",
                         "description":"small stuff",
                         "config":{"SERVICEOFFERINGID":"abc123",
                                   "DO_STUFF":true,
                                   "PUBLIC_NETWORK_INDEX":0,
                                   "CLOUDSTACK_ZONE_ID":"__wow__"}}"""
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        result.read.return_value = plan_data
        urlopen.return_value = result
        admin_plugin.handle_plan(["show", "-s", self.service_name, "small"])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans/small")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
        expected_output = u"""Name: small
Description: small stuff
Config:

  CLOUDSTACK_ZONE_ID=__wow__
  DO_STUFF=True
  PUBLIC_NETWORK_INDEX=0
  SERVICEOFFERINGID=abc123
"""
        self.assertEqual(expected_output, "".join(lines))

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_show_plan_failure(self, stderr, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 500
        result.read.return_value = "something went wrong"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.handle_plan(["show", "-s", self.service_name, "medium"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans/medium")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
        stderr.write.assert_called_with("ERROR: something went wrong\n")

    @mock.patch("sys.stderr")
    def test_show_plan_invalid_args(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.handle_plan(["show", "-s", self.service_name])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with("plan show: error: too few arguments\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_delete_plan(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        urlopen.return_value = result
        admin_plugin.handle_plan(["delete", "-s", self.service_name, "medium"])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans/medium")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual("DELETE", request.get_method())
        stdout.write.assert_called_with("Plan successfully deleted\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_delete_plan_failure(self, stderr, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 404
        result.read.return_value = "plan not found\n"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.handle_plan(["delete", "-s", self.service_name, "medium"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/plans/medium")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual("DELETE", request.get_method())
        stderr.write.assert_called_with("ERROR: plan not found\n")

    @mock.patch("sys.stderr")
    def test_delete_plan_invalid_args(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.handle_plan(["delete", "-s", self.service_name])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with("plan delete: error: too few arguments\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_show_quota(self, stdout, Request, urlopen):
        lines = []
        stdout.write.side_effect = lambda data, **kw: lines.append(data)
        quota_data = u"""{"used":["inst1", "inst2", "inst3"], "quota": 10}"""
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        result.read.return_value = quota_data
        urlopen.return_value = result
        admin_plugin.show_quota(["-s", self.service_name, "-t", "myteam"])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/quota/myteam")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
        expected_output = u"""Quota usage: 3/10.\n"""
        self.assertEqual(expected_output, "".join(lines))

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_show_quota_request_failure(self, stderr, Request, urlopen):
        lines = []
        stderr.write.side_effect = lambda data, **kw: lines.append(data)
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 400
        result.read.return_value = "something went wrong"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.show_quota(["-s", self.service_name, "-t", "myteam"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        self.assertEqual("ERROR: something went wrong\n", "".join(lines))

    @mock.patch("sys.stderr")
    def test_show_quota_invalid_args(self, stderr):
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.show_quota(["-s", self.service_name])
        exc = cm.exception
        self.assertEqual(2, exc.code)
        stderr.write.assert_called_with("show-quota: error: argument -t/--team is required\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_set_quota(self, stdout, Request, urlopen):
        lines = []
        stdout.write.side_effect = lambda data, **kw: lines.append(data)
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        urlopen.return_value = result
        admin_plugin.set_quota(["-s", self.service_name, "-t", "myteam", "-q", "10"])
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/quota/myteam")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        request.add_data.assert_called_with("quota=10")
        self.assertEqual("POST", request.get_method())
        expected_output = u"Quota successfully updated.\n"
        self.assertEqual(expected_output, "".join(lines))

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_set_quota_request_failure(self, stderr, Request, urlopen):
        lines = []
        stderr.write.side_effect = lambda data, **kw: lines.append(data)
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 400
        result.read.return_value = "something went wrong"
        urlopen.return_value = result
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.set_quota(["-s", self.service_name, "-t", "myteam", "-q", "10"])
        exc = cm.exception
        self.assertEqual(1, exc.code)
        self.assertEqual("ERROR: something went wrong\n", "".join(lines))

    @mock.patch("sys.stderr")
    def test_set_quota_invalid_args(self, stderr):
        arg_sets = [
            (["-s", self.service_name], "argument -t/--team is required"),
            (["-s", self.service_name, "-t", "myteam"], "argument -q/--quota is required"),
            (["-s", self.service_name, "-t", "myteam", "-q", "a"],
             "argument -q/--quota: invalid int value: 'a'"),
        ]
        for set in arg_sets:
            args, err_message = set
            with self.assertRaises(SystemExit) as cm:
                admin_plugin.set_quota(args)
            exc = cm.exception
            self.assertEqual(2, exc.code)
            stderr.write.assert_any_call("set-quota: error: " + err_message + "\n")

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_list_healings(self, stdout, Request, urlopen):
        lines = []
        stdout.write.side_effect = lambda data, **kw: lines.append(data)
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        urlopen.return_value = result
        start_time = datetime.datetime(2016, 8, 2, 10, 53, 0)
        healing_list = []
        status = ['success', None, 'Long and ugly error with a large testing description']
        for x in range(0, 3):
            end_time = start_time + datetime.timedelta(minutes=3)
            if x == 1:
                end_time = None
            data = {"instance": "myinstance", "machine": "10.10.1.{}".format(x),
                    "start_time": start_time, "end_time": end_time, "status": status[x]}
            healing_list.append(data)
            start_time = start_time + datetime.timedelta(minutes=5)
        result.read.return_value = json.dumps(healing_list, default=json_util.default)
        args = ['-s', self.service_name]
        admin_plugin.list_healings(args)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/healings?quantity=20")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
        expected_output = u"""
+------------+-----------+------------------+----------+--------------------------------+
| Instance   | Machine   | Start Time       | Duration | Status                         |
+------------+-----------+------------------+----------+--------------------------------+
| myinstance | 10.10.1.0 | Aug  02 05:53:00 | 00:03:00 | success                        |
+------------+-----------+------------------+----------+--------------------------------+
| myinstance | 10.10.1.1 | Aug  02 05:58:00 |          |                                |
+------------+-----------+------------------+----------+--------------------------------+
| myinstance | 10.10.1.2 | Aug  02 06:03:00 | 00:03:00 | Long and ugly error with a lar |
|            |           |                  |          | ge testing description         |
+------------+-----------+------------------+----------+--------------------------------+
"""
        self.assertEqual(expected_output, "".join(lines))

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_list_healings_empty_json_response(self, stdout, Request, urlopen):
        lines = []
        stdout.write.side_effect = lambda data, **kw: lines.append(data)
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        urlopen.return_value = result
        healing_list = []
        result.read.return_value = json.dumps(healing_list, default=json_util.default)
        args = ['-s', self.service_name]
        admin_plugin.list_healings(args)
        Request.assert_called_with(self.target +
                                   "services/proxy/service/rpaas?" +
                                   "callback=/admin/healings?quantity=20")
        request.add_header.assert_any_call("Authorization", "bearer " + self.token)
        self.assertEqual("GET", request.get_method())
        expected_output = u"""
+----------+---------+------------+----------+--------+
| Instance | Machine | Start Time | Duration | Status |
+----------+---------+------------+----------+--------+
"""
        self.assertEqual(expected_output, "".join(lines))

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    def test_list_healings_invalid_response(self, stderr, Request, urlopen):
        lines = []
        stderr.write.side_effect = lambda data, **kw: lines.append(data)
        request = mock.Mock()
        Request.return_value = request
        result = mock.Mock()
        result.getcode.return_value = 200
        urlopen.return_value = result
        result.read.return_value = "weird value"
        args = ['-s', self.service_name]
        with self.assertRaises(SystemExit) as cm:
            admin_plugin.list_healings(args)
        exc = cm.exception
        self.assertEqual(1, exc.code)
        expected_output = "ERROR: invalid json response - No JSON object could be decoded\n"
        self.assertEqual(expected_output, "".join(lines))

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stdout")
    def test_restore_instance_successfully(self, stdout, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        urlopen.return_value = FakeURLopenResponse("Restoring machine (1/1) x .....: successfully")
        args = ['-s', self.service_name, '-i x']
        admin_plugin.restore_instance(args)
        expected_output = "Restoring machine (1/1) x .....: successfully"
        call_list = []
        for char in expected_output:
            call_list.append(mock.call(char))
        stdout.write.assert_has_calls(call_list)

    @mock.patch("urllib2.urlopen")
    @mock.patch("urllib2.Request")
    @mock.patch("sys.stderr")
    @mock.patch("sys.stdout")
    def test_restore_instance_fail(self, stdout, stderr, Request, urlopen):
        request = mock.Mock()
        Request.return_value = request
        urlopen.return_value = FakeURLopenResponse("fail", 400, "fail")
        args = ['-s', self.service_name, '-i x']
        with self.assertRaises(SystemExit):
            admin_plugin.restore_instance(args)
        stderr.write.assert_has_calls([mock.call("ERROR: fail\n")])
