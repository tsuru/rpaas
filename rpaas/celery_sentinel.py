"""
This module adds Redis Sentinel transport support to Celery.

Migrate to https://github.com/celery/kombu/pull/559 when available on a
release.

To use it::

    import register_celery_alias
    register_celery_alias("redis-sentinel")

    celery = Celery(..., broker="redis-sentinel://...", backend="redis-sentinel://...")
"""
import logging

from celery.backends import BACKEND_ALIASES
from kombu.transport import TRANSPORT_ALIASES
from celery.backends.redis import RedisBackend
from kombu.transport.redis import Transport, Channel
from redis import Redis
from redis.sentinel import Sentinel, SentinelManagedConnection


class RedisSentinelBackend(RedisBackend):

    _redis_shared_connection = []

    def __new__(cls, *args, **kwargs):
        obj = super(RedisSentinelBackend, cls).__new__(cls, *args, **kwargs)
        obj._redis_connection = cls._redis_shared_connection
        return obj

    def __init__(self, sentinels=None, sentinel_timeout=None, socket_timeout=None,
                 min_other_sentinels=0, service_name=None, **kwargs):
        super(RedisSentinelBackend, self).__init__(**kwargs)
        self.sentinel_conf = self.app.conf['CELERY_SENTINEL_BACKEND_SETTINGS'] or {}

    @property
    def client(self):
        if not self._redis_connection:
            sentinel = Sentinel(
                self.sentinel_conf.get('sentinels'),
                min_other_sentinels=self.sentinel_conf.get("min_other_sentinels", 0),
                password=self.sentinel_conf.get("password"),
                socket_timeout=self.sentinel_conf.get("sentinel_timeout", None)
            )
            redis_connection = sentinel.master_for(self.sentinel_conf.get("service_name"), Redis,
                                                   socket_timeout=self.sentinel_conf.get("socket_timeout"))
            self._redis_connection.append(redis_connection)
        return self._redis_connection[0]


class SentinelChannel(Channel):

    from_transport_options = Channel.from_transport_options + (
        "service_name",
        "sentinels",
        "password",
        "min_other_sentinels",
        "sentinel_timeout",
        "max_connections"
    )

    def _sentinel_managed_pool(self, connection_class, async=False):
        sentinel = Sentinel(
            self.sentinels,
            min_other_sentinels=getattr(self, "min_other_sentinels", 0),
            password=getattr(self, "password", None),
            socket_timeout=getattr(self, "sentinel_timeout", None)
        )
        return sentinel.master_for(self.service_name, self.Client,
                                   socket_timeout=self.socket_timeout,
                                   connection_class=connection_class).connection_pool

    def _on_connection_disconnect(self, connection):
        if self._closing:
            self._in_poll = False
            self._in_listen = False
            if self.connection and self.connection.cycle:
                self.connection.cycle._on_connection_disconnect(connection)
            self._disconnect_pools()

    def _get_pool(self, async=False):
        channel = self

        class Connection(SentinelManagedConnection):
            def disconnect(self):
                super(Connection, self).disconnect()
                channel._on_connection_disconnect(self)
        connection_class = Connection
        self.keyprefix_fanout = self.keyprefix_fanout.format(db=0)
        return self._sentinel_managed_pool(connection_class, async)


class RedisSentinelTransport(Transport):
    Channel = SentinelChannel


def patch_flower_broker():
    import tornado.web  # NOQA
    from flower.views.broker import Broker
    from flower.utils.broker import Redis as RedisBroker
    from urlparse import urlparse

    old_new = Broker.__new__

    def new_new(_, cls, broker_url, *args, **kwargs):
        scheme = urlparse(broker_url).scheme
        if scheme == 'redis-sentinel':
            from rpaas.tasks import app
            opts = app.conf.BROKER_TRANSPORT_OPTIONS
            s = Sentinel(
                opts['sentinels'],
                password=opts['password'],
            )
            host, port = s.discover_master(opts['service_name'])
            return RedisBroker('redis://:{}@{}:{}'.format(opts['password'], host, port))
        else:
            old_new(cls, broker_url, *args, **kwargs)
    Broker.__new__ = classmethod(new_new)

    from flower.command import settings
    from flower.views.tasks import TasksView
    from rpaas import flower_uimodules
    settings['ui_modules'] = flower_uimodules

    def new_render(self, *args, **kwargs):
        self._ui_module('FixTasks', self.application.ui_modules['FixTasks'])(self)
        super(TasksView, self).render(*args, **kwargs)

    TasksView.render = new_render


def register_celery_alias(alias="redis-sentinel"):
    BACKEND_ALIASES[alias] = "rpaas.celery_sentinel.RedisSentinelBackend"
    TRANSPORT_ALIASES[alias] = "rpaas.celery_sentinel.RedisSentinelTransport"
    try:
        patch_flower_broker()
    except:
        logging.exception('ignored error patching flower')
