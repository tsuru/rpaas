import os
import logging

from celery import Celery, Task
import hm.managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA
from hm import config
from hm.model.host import Host
from hm.model.load_balancer import LoadBalancer

from rpaas import hc, nginx, storage


redis_host = os.environ.get('REDIS_HOST', 'localhost')
redis_port = os.environ.get('REDIS_PORT', '6379')
redis_broker = "redis://{}:{}/0".format(redis_host, redis_port)
app = Celery('tasks', broker=redis_broker, backend=redis_broker)
app.conf.update(
    CELERY_TASK_SERIALIZER='json',
    CELERY_RESULT_SERIALIZER='json',
    CELERY_ACCEPT_CONTENT=['json'],
)


class BaseManagerTask(Task):
    ignore_result = True
    store_errors_even_if_ignored = True

    def init_config(self, config=None):
        self.config = config
        self.nginx_manager = nginx.NginxDAV(config)
        self.host_manager_name = self._get_conf("HOST_MANAGER", "cloudstack")
        self.lb_manager_name = self._get_conf("LB_MANAGER", "networkapi_cloudstack")
        self.hc = hc.Dumb()
        self.storage = storage.MongoDBStorage(config)
        hc_url = self._get_conf("HCAPI_URL", None)
        if hc_url:
            self.hc = hc.HCAPI(self.storage,
                               url=hc_url,
                               user=self._get_conf("HCAPI_USER"),
                               password=self._get_conf("HCAPI_PASSWORD"),
                               hc_format=self._get_conf("HCAPI_FORMAT", "http://{}:8080/"))

    def _get_conf(self, key, default=config.undefined):
        return config.get_config(key, default, self.config)


class NewInstanceTask(BaseManagerTask):

    def run(self, config, name):
        self.init_config(config)
        healthcheck_timeout = int(self._get_conf("RPAAS_HEALTHCHECK_TIMEOUT", 600))
        host = Host.create(self.host_manager_name, name, self.config)
        lb = None
        try:
            lb = LoadBalancer.create(self.lb_manager_name, name, self.config)
            lb.add_host(host)
            self.nginx_manager.wait_healthcheck(host.dns_name, timeout=healthcheck_timeout)
            self.hc.create(name)
            self.hc.add_url(name, host.dns_name)
            self.storage.remove_task(name)
        except:
            rollback = self._get_conf("RPAAS_ROLLBACK_ON_ERROR", "0") in ("True", "true", "1")
            if not rollback:
                raise
            if lb is not None:
                lb.destroy()
            host.destroy()
            self.hc.destroy(name)
            raise


class RemoveInstanceTask(BaseManagerTask):

    def run(self, config, name):
        self.init_config(config)
        lb = LoadBalancer.find(name, self.config)
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            host.destroy()
        lb.destroy()
        self.hc.destroy(name)


class ScaleInstanceTask(BaseManagerTask):

    def _add_host(self, lb):
        host = Host.create(self.host_manager_name, lb.name, self.config)
        try:
            lb.add_host(host)
            self.hc.add_url(lb.name, host.dns_name)
            binding_data = self.storage.find_binding(lb.name)
            if not binding_data:
                return
            self.nginx_manager.wait_healthcheck(host.dns_name, timeout=300)
            cert, key = binding_data.get('cert'), binding_data.get('key')
            if cert and key:
                self.nginx_manager.update_certificate(host.dns_name, cert, key)
            paths = binding_data.get('paths') or []
            for path_data in paths:
                self.nginx_manager.update_binding(host.dns_name,
                                                  path_data.get('path'),
                                                  path_data.get('destination'),
                                                  path_data.get('content'))
        except:
            rollback = self._get_conf("RPAAS_ROLLBACK_ON_ERROR", "0") in ("True", "true", "1")
            if not rollback:
                raise
            try:
                host.destroy()
            except Exception as e:
                logging.log("Error in rollback trying to destroy host: {}".format(e))
            try:
                lb.remove_host(host)
            except Exception as e:
                logging.log("Error in rollback trying to remove from load balancer: {}".format(e))
            try:
                self.hc.remove_url(lb.name, host.dns_name)
            except Exception as e:
                logging.log("Error in rollback trying to remove healthcheck: {}".format(e))
            raise

    def _delete_host(self, lb, host):
        host.destroy()
        lb.remove_host(host)
        self.hc.remove_url(lb.name, host.dns_name)

    def run(self, config, name, quantity):
        try:
            self.init_config(config)
            lb = LoadBalancer.find(name, self.config)
            if lb is None:
                raise storage.InstanceNotFoundError()
            diff = quantity - len(lb.hosts)
            if diff == 0:
                return
            for i in xrange(abs(diff)):
                if diff > 0:
                    self._add_host(lb)
                else:
                    self._delete_host(lb, lb.hosts[i])
        finally:
            self.storage.remove_task(name)
