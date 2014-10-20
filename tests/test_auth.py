# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import base64
import os
import unittest

import flask

from rpaas import auth


class AuthTestCase(unittest.TestCase):

    def setUp(self):
        self.called = False
        self.app = flask.Flask(__name__)
        self.client = self.app.test_client()

        @self.app.route("/")
        @auth.required
        def myfn():
            self.called = True
            return "hello world"

    def set_envs(self):
        os.environ["API_USERNAME"] = self.username = "rpaas"
        os.environ["API_PASSWORD"] = self.password = "rpaas123"

    def delete_envs(self):
        del os.environ["API_USERNAME"], os.environ["API_PASSWORD"]

    def get(self, url, user, password):
        encoded = base64.b64encode(user + ":" + password)
        return self.client.open(url, method="GET",
                                headers={"Authorization": "Basic " + encoded})

    def test_authentication_required_no_auth_in_environment(self):
        resp = self.get("/", "", "")
        self.assertEqual(200, resp.status_code)
        self.assertEqual("hello world", resp.data)

    def test_authentication_required_no_auth_provided(self):
        self.set_envs()
        self.addCleanup(self.delete_envs)
        resp = self.client.get("/")
        self.assertEqual(401, resp.status_code)
        self.assertEqual("you do not have access to this resource", resp.data)

    def test_authentication_required_wrong_data(self):
        pairs = [("joao", "joao123"), ("joao", "rpaas123"),
                 ("rpaas", "joao123")]
        self.set_envs()
        self.addCleanup(self.delete_envs)
        for user, password in pairs:
            resp = self.get("/", user, password)
            self.assertEqual(401, resp.status_code)
            self.assertEqual("you do not have access to this resource", resp.data)

    def test_authentication_required_right_data(self):
        self.set_envs()
        self.addCleanup(self.delete_envs)
        resp = self.get("/", self.username, self.password)
        self.assertEqual(200, resp.status_code)
        self.assertEqual("hello world", resp.data)
