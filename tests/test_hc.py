# coding: utf-8

# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json
import unittest
import os

import mock
from requests import auth

from rpaas import hc, storage


class DumbTestCase(unittest.TestCase):

    def setUp(self):
        self.hc = hc.Dumb(None)

    def test_create(self):
        self.hc.create("hello")
        self.assertEqual([], self.hc.hcs["hello"])

    def test_destroy(self):
        self.hc.create("hello")
        self.hc.destroy("hello")
        self.assertNotIn("hello", self.hc.hcs)

    def test_add_url(self):
        self.hc.create("hello")
        self.hc.add_url("hello", "myunit.tsuru.io")
        self.assertEqual(["myunit.tsuru.io"], self.hc.hcs["hello"])

    def test_remove_url(self):
        self.hc.create("hello")
        self.hc.add_url("hello", "myunit.tsuru.io")
        self.hc.remove_url("hello", "myunit.tsuru.io")
        self.assertEqual([], self.hc.hcs["hello"])


class HCAPITestCase(unittest.TestCase):

    def setUp(self):
        os.environ['MONGO_DATABASE'] = 'host_manager_test'
        self.storage = storage.MongoDBStorage()
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)
        self.hc = hc.HCAPI(self.storage, "http://localhost", hc_format="http://{}:8080/")
        self.hc._issue_request = self.issue_request = mock.Mock()

    @mock.patch("requests.request")
    def test_issue_request(self, request):
        request.return_value = resp = mock.Mock()
        hc_api = hc.HCAPI(self.storage, "http://localhost/")
        got_resp = hc_api._issue_request("GET", "/url", data={"abc": 1})
        self.assertEqual(resp, got_resp)
        request.assert_called_with("GET", "http://localhost/url",
                                   data={"abc": 1})

    @mock.patch("requests.request")
    def test_issue_authenticated_request(self, request):
        request.return_value = resp = mock.Mock()
        hc_api = hc.HCAPI(self.storage, "http://localhost/",
                          user="zabbix", password="zabbix123")
        got_resp = hc_api._issue_request("GET", "/url", data={"abc": 1})
        self.assertEqual(resp, got_resp)
        call = request.call_args_list[0]
        self.assertEqual(("GET", "http://localhost/url"), call[0])
        self.assertEqual({"abc": 1}, call[1]["data"])
        req_auth = call[1]["auth"]
        self.assertIsInstance(req_auth, auth.HTTPBasicAuth)
        self.assertEqual("zabbix", req_auth.username)
        self.assertEqual("zabbix123", req_auth.password)

    @mock.patch("uuid.uuid4")
    def test_create(self, uuid4):
        self.issue_request.return_value = mock.Mock(status_code=201)
        uuid = mock.Mock(hex="abc123")
        uuid4.return_value = uuid
        self.hc.create("myinstance")
        self.issue_request.assert_called_with("POST", "/resources",
                                              data={"name":
                                                    "rpaas_myinstance_abc123"})
        hc = self.storage.retrieve_hc("myinstance")
        self.assertDictEqual(hc, {
            "_id": "myinstance", "resource_name": "rpaas_myinstance_abc123"
        })

    def test_create_response_error(self):
        self.issue_request.return_value = mock.Mock(status_code=409,
                                                    text="something went wrong")
        with self.assertRaises(hc.HCCreationError) as cm:
            self.hc.create("myinstance")
        exc = cm.exception
        self.assertEqual(("something went wrong",), exc.args)

    def test_destroy(self):
        self.storage.store_hc({"_id": "myinstance", "resource_name": "my_resource"})
        self.hc.destroy("myinstance")
        self.issue_request.assert_called_with("DELETE", "/resources/my_resource")

    def test_add_url(self):
        self.storage.store_hc({"_id": "myinstance", "resource_name": "my_resource"})
        self.issue_request.return_value = mock.Mock(status_code=200)
        self.hc.add_url("myinstance", "something.tsuru.io")
        hcheck_url = "http://something.tsuru.io:8080/"
        data = {"name": "my_resource", "url": hcheck_url,
                "expected_string": "WORKING"}
        self.issue_request.assert_called_with("POST", "/url",
                                              data=json.dumps(data))
        hc = self.storage.retrieve_hc("myinstance")
        self.assertDictEqual(hc, {
            "_id": "myinstance",
            "resource_name": "my_resource",
            "urls": ["http://something.tsuru.io:8080/"]
        })

    def test_add_second_url(self):
        self.storage.store_hc({
            "_id": "myinstance", "resource_name": "my_resource",
            "urls": ["http://a.com:8080/health"],
        })
        self.issue_request.return_value = mock.Mock(status_code=200)
        self.hc.add_url("myinstance", "something.tsuru.io")
        hcheck_url = "http://something.tsuru.io:8080/"
        data = {"name": "my_resource", "url": hcheck_url,
                "expected_string": "WORKING"}
        self.issue_request.assert_called_with("POST", "/url",
                                              data=json.dumps(data))
        hc = self.storage.retrieve_hc("myinstance")
        self.assertDictEqual(hc, {
            "_id": "myinstance",
            "resource_name": "my_resource",
            "urls": ["http://a.com:8080/health", "http://something.tsuru.io:8080/"]
        })

    def test_add_url_request_error(self):
        self.storage.store_hc({
            "_id": "myinstance",
            "resource_name": "my_resource",
        })
        self.issue_request.return_value = mock.Mock(status_code=500,
                                                    text="failed to add url")
        with self.assertRaises(hc.URLCreationError) as cm:
            self.hc.add_url("myinstance", "wat")
        exc = cm.exception
        self.assertEqual(("failed to add url",), exc.args)

    def test_remove_url(self):
        hcheck_url = "http://something.tsuru.io:8080/"
        self.storage.store_hc({
            "_id": "myinstance", "resource_name": "my_resource",
            "urls": [hcheck_url]
        })
        self.hc.remove_url("myinstance", "something.tsuru.io")
        data = {"name": "my_resource", "url": hcheck_url}
        self.issue_request.assert_called_with("DELETE", "/url",
                                              data=json.dumps(data))
        hc = self.storage.retrieve_hc("myinstance")
        self.assertDictEqual(hc, {
            "_id": "myinstance",
            "resource_name": "my_resource",
            "urls": []
        })
