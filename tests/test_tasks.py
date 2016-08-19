# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import unittest
import os
import redis
import time

from rpaas import tasks

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class TasksTestCase(unittest.TestCase):

    def setUp(self):
        os.environ['REDIS_HOST'] = ''
        os.environ['REDIS_PORT'] = ''
        os.environ['DBAAS_SENTINEL_ENDPOINT'] = ''
        os.environ['SENTINEL_ENDPOINT'] = ''
        os.environ['REDIS_ENDPOINT'] = ''
        sentinel_conn = redis.StrictRedis().from_url("redis://127.0.0.1:51111")
        _, master_port = sentinel_conn.execute_command("sentinel get-master-addr-by-name mymaster")
        self.master_port = int(master_port)

    def tearDown(self):
        self.setUp()

    def with_env_var(self, env_var):
        os.environ[env_var] = "sentinel://:mypass@127.0.0.1:51111,127.0.0.1:51112/service_name:mymaster"
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        ch.client.set('mykey', env_var)
        self.assertEqual(ch.client.get('mykey'), env_var)
        self.assertEqual(ch.client.info()['tcp_port'], self.master_port)
        self.assertEqual(app.backend.client.info()['tcp_port'], self.master_port)

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
        os.environ['REDIS_ENDPOINT'] = "redis://:mypass@127.0.0.1:{}/0".format(self.master_port)
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        ch.client.set('mykey_simple_redis', '1')
        self.assertEqual(ch.client.get('mykey_simple_redis'), '1')
        self.assertEqual(ch.client.info()['tcp_port'], self.master_port)
        self.assertEqual(app.backend.client.info()['tcp_port'], self.master_port)

    def test_sentinel_master_failover(self):
        os.environ['SENTINEL_ENDPOINT'] = "sentinel://:mypass@127.0.0.1:51111/service_name:mymaster"
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        redis_conn = redis.StrictRedis().from_url("redis://:mypass@127.0.0.1:{}".format(self.master_port))
        self.assertEqual(redis_conn.info()['role'], 'master')
        redis_conn = redis.StrictRedis().from_url("redis://127.0.0.1:51111")
        redis_conn.execute_command("sentinel failover mymaster")
        redis_conn = redis.StrictRedis().from_url("redis://:mypass@127.0.0.1:{}".format(self.master_port))
        timeout_failover = 0
        while redis_conn.info()['role'] is not 'slave' and timeout_failover <= 30:
            time.sleep(1)
            timeout_failover += 1
        self.assertEqual(ch.client.info()['role'], 'master')
        ch.client.set('mykey_failover', 'sentinel_failover_key')
        self.assertEqual(ch.client.get('mykey_failover'), 'sentinel_failover_key')
        self.assertEqual(app.backend.client.get('mykey_failover'), 'sentinel_failover_key')

    def master_connected_clients(self):
        redis_conn = redis.StrictRedis().from_url("redis://:mypass@127.0.0.1:{}".format(self.master_port))
        client_conn_list = 0
        for client in redis_conn.client_list():
            if 'sentinel' in client['name'] or client['cmd'] in ['replconf', 'client']:
                continue
            client_conn_list += 1
        return client_conn_list

    def test_sentinel_connection_pool_reconnect(self):
        os.environ['SENTINEL_ENDPOINT'] = "sentinel://:mypass@127.0.0.1:51111/service_name:mymaster"
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        redis_conn = redis.StrictRedis().from_url("redis://:mypass@127.0.0.1:{}".format(self.master_port))
        client_conn_list = 0
        for client in redis_conn.client_list():
            if 'sentinel' in client['name'] or client['cmd'] in ['replconf', 'client']:
                continue
            client_conn_list += 1
            redis_conn.execute_command("client kill addr {} skipme yes type normal".format(client['addr']))
        ch.client.set('mykey_connection_pool', 'sentinel_connection_pool_2')
        self.assertEqual(ch.client.get('mykey_connection_pool'), 'sentinel_connection_pool_2')
        self.assertEqual(self.master_connected_clients(), 1)

    def test_sentinel_connection_pool_shared(self):
        os.environ['SENTINEL_ENDPOINT'] = "sentinel://:mypass@127.0.0.1:51111/service_name:mymaster"
        app = tasks.initialize_celery()
        channel = []
        app_client = []
        for x in range(10):
            channel.append(app.broker_connection().channel())
            app_client.append(app.backend.client)
            channel[x].client.set('mykey_channel_shared', 'sentinel_connection_shared_{}'.format(x))
            app_client[x].set('mykey_app_client_shared', 'sentinel_connection_shared_{}'.format(x))
            self.assertEqual(channel[x].client.get('mykey_channel_shared'),
                             'sentinel_connection_shared_{}'.format(x))
            self.assertEqual(app_client[x].get('mykey_app_client_shared'),
                             'sentinel_connection_shared_{}'.format(x))
        self.assertEqual(len(channel[9].__dict__['_sentinel_connection_pool']), 1)
        self.assertListEqual(channel[0].__dict__['_sentinel_connection_pool'],
                             channel[9].__dict__['_sentinel_connection_pool'])
        self.assertEqual(id(app_client[0].__dict__['connection_pool']),
                         id(app_client[9].__dict__['connection_pool']))
        self.assertEqual(self.master_connected_clients(), 2)
