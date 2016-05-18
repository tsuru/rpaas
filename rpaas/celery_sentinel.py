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
from redis.sentinel import Sentinel


class RedisSentinelBackend(RedisBackend):

    def __init__(self, sentinels=None, sentinel_timeout=None, socket_timeout=None,
                 min_other_sentinels=0, service_name=None, **kwargs):
        super(RedisSentinelBackend, self).__init__(**kwargs)
        self.sentinel_conf = self.app.conf['CELERY_SENTINEL_BACKEND_SETTINGS'] or {}

    @property
    def client(self):
        sentinel = Sentinel(
            self.sentinel_conf.get('sentinels'),
            min_other_sentinels=self.sentinel_conf.get("min_other_sentinels", 0),
            password=self.sentinel_conf.get("password"),
            sentinel_kwargs={"socket_timeout": self.sentinel_conf.get("sentinel_timeout")},
        )
        return sentinel.master_for(self.sentinel_conf.get("service_name"), Redis,
                                   socket_timeout=self.sentinel_conf.get("socket_timeout"))


class SentinelChannel(Channel):

    from_transport_options = Channel.from_transport_options + (
        "service_name",
        "sentinels",
        "password",
        "min_other_sentinels",
        "sentinel_timeout",
    )

    def _sentinel_managed_pool(self, async=False):
        sentinel = Sentinel(
            self.sentinels,
            min_other_sentinels=getattr(self, "min_other_sentinels", 0),
            password=getattr(self, "password", None),
            sentinel_kwargs={"socket_timeout": getattr(self, "sentinel_timeout", None)},
        )
        return sentinel.master_for(self.service_name, self.Client,
                                   socket_timeout=self.socket_timeout).connection_pool

    def _get_pool(self, async=False):
        return self._sentinel_managed_pool(async)


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


def register_celery_alias(alias="redis-sentinel"):
    BACKEND_ALIASES[alias] = "rpaas.celery_sentinel.RedisSentinelBackend"
    TRANSPORT_ALIASES[alias] = "rpaas.celery_sentinel.RedisSentinelTransport"
    try:
        patch_flower_broker()
    except:
        logging.exception('ignored error patching flower')
