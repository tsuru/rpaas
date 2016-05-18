# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import unittest
import os

from rpaas import tasks

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class TasksTestCase(unittest.TestCase):

    def setUp(self):
        os.environ['REDIS_HOST'] = ''
        os.environ['REDIS_PORT'] = ''
        os.environ['DBAAS_SENTINEL_ENDPOINT'] = ''
        os.environ['SENTINEL_ENDPOINT'] = ''
        os.environ['REDIS_ENDPOINT'] = ''

    def tearDown(self):
        self.setUp()

    def with_env_var(self, env_var):
        os.environ[env_var] = "sentinel://:mypass@127.0.0.1:51111,127.0.0.1:51112/service_name:mymaster"
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        ch.client.set('mykey', '1')
        self.assertEqual(ch.client.get('mykey'), '1')
        self.assertEqual(ch.client.info()['tcp_port'], 51113)
        self.assertEqual(app.backend.client.info()['tcp_port'], 51113)

    def test_default_redis_connection(self):
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        ch.client.set('mykey', '1')
        self.assertEqual(ch.client.get('mykey'), '1')
        self.assertEqual(ch.client.info()['tcp_port'], 6379)
        self.assertEqual(app.backend.client.info()['tcp_port'], 6379)

    def test_sentinel_with_many_envs(self):
        self.with_env_var('SENTINEL_ENDPOINT')
        self.setUp()
        self.with_env_var('DBAAS_SENTINEL_ENDPOINT')
        self.setUp()
        self.with_env_var('REDIS_ENDPOINT')

    def test_simple_redis_string(self):
        os.environ['REDIS_ENDPOINT'] = "redis://:mypass@127.0.0.1:51113/0"
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        ch.client.set('mykey', '1')
        self.assertEqual(ch.client.get('mykey'), '1')
        self.assertEqual(ch.client.info()['tcp_port'], 51113)
        self.assertEqual(app.backend.client.info()['tcp_port'], 51113)
