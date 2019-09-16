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

    def with_env_var(self, env_var, env_value, redis_port):
        os.environ[env_var] = env_value
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        ch.client.set('mykey', env_var)
        self.assertEqual(ch.client.get('mykey'), env_var)
        self.assertEqual(ch.client.info()['tcp_port'], redis_port)
        self.assertEqual(app.backend.client.info()['tcp_port'], redis_port)

    def test_default_redis_connection(self):
        app = tasks.initialize_celery()
        ch = app.broker_connection().channel()
        ch.client.set('mykey', '1')
        self.assertEqual(ch.client.get('mykey'), '1')
        self.assertEqual(ch.client.info()['tcp_port'], 6379)
        self.assertEqual(app.backend.client.info()['tcp_port'], 6379)

    def test_sentinel_with_many_envs(self):
        self.with_env_var('RANDOM_VAR', 'random_value', 6379)
        self.setUp()
        sentinel_endpoint = 'sentinel://:mypass@127.0.0.1:51111,127.0.0.1:51112/service_name:mymaster'
        self.with_env_var('SENTINEL_ENDPOINT', sentinel_endpoint, self.master_port)
        self.setUp()
        dbaas_endpoint = sentinel_endpoint
        self.with_env_var('DBAAS_SENTINEL_ENDPOINT', dbaas_endpoint, self.master_port)
        self.setUp()
        redis_endpoint = 'redis://127.0.0.1:6379/0'
        self.with_env_var('REDIS_ENDPOINT', redis_endpoint, 6379)

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
        while redis_conn.info()['role'] == 'slave' and timeout_failover <= 30:
            time.sleep(1)
            timeout_failover += 1
        self.assertEqual(ch.client.info()['role'], 'master')
        ch.client.set('mykey_failover', 'sentinel_failover_key')
        self.assertEqual(ch.client.get('mykey_failover'), 'sentinel_failover_key')
        self.assertEqual(app.backend.client.get('mykey_failover'), 'sentinel_failover_key')

    def redis_clients_manager(self, kill=False):
        redis_conn = redis.StrictRedis().from_url("redis://:mypass@127.0.0.1:{}".format(self.master_port))
        client_conn_list = 0
        for client in redis_conn.client_list():
            if 'sentinel' in client['name'] or client['cmd'] in ['replconf', 'client']:
                continue
            client_conn_list += 1
            if kill:
                redis_conn.execute_command("client kill addr {} skipme yes \
                                            type normal".format(client['addr']))
        return client_conn_list

    def test_sentinel_connection_pool_reconnect(self):
        os.environ['SENTINEL_ENDPOINT'] = "sentinel://:mypass@127.0.0.1:51111/service_name:mymaster"
        app = tasks.initialize_celery()
        app_client = app.backend.client
        self.redis_clients_manager(kill=True)
        app_client.set('mykey_connection_pool_client', 'sentinel_connection_pool')
        self.assertEqual(app_client.get('mykey_connection_pool_client'), 'sentinel_connection_pool')
        self.assertEqual(self.redis_clients_manager(), 1)

    def test_sentinel_connection_pool_shared(self):
        os.environ['SENTINEL_ENDPOINT'] = "sentinel://:mypass@127.0.0.1:51111/service_name:mymaster"
        app = tasks.initialize_celery()
        app_client = []
        for x in range(10):
            app_client.append(app.backend.client)
            app_client[x].set('mykey_app_client_shared', 'sentinel_connection_shared_{}'.format(x))
            self.assertEqual(app_client[x].get('mykey_app_client_shared'),
                             'sentinel_connection_shared_{}'.format(x))
        self.assertEqual(id(app_client[0].connection_pool), id(app_client[9].connection_pool))
        self.assertEqual(self.redis_clients_manager(), 1)
