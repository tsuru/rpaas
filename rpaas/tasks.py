import os

from celery import Celery, Task
import hm.managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA
from hm import config
from hm.model.host import Host
from hm.model.load_balancer import LoadBalancer

from rpaas import hc, nginx, storage


redis_broker = os.environ.get('REDIS_BROKER', 'redis://localhost:6379/8')
app = Celery('tasks', broker=redis_broker, backend=redis_broker)
app.conf.update(
    CELERY_TASK_SERIALIZER='json',
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
        hc_url = self._get_conf("HCAPI_URL", None)
        if hc_url:
            self.hc = hc.HCAPI(storage.MongoDBStorage(),
                               url=hc_url,
                               user=self._get_conf("HCAPI_USER"),
                               password=self._get_conf("HCAPI_PASSWORD"),
                               hc_format=self._get_conf("HCAPI_FORMAT", "http://{}:8080/"))

    def _get_conf(self, key, default=config.undefined):
        return config.get_config(key, default, self.config)


class NewInstanceTask(BaseManagerTask):

    def run(self, config, name):
        self.init_config(config)
        host = Host.create(self.host_manager_name, name, self.config)
        lb = None
        try:
            lb = LoadBalancer.create(self.lb_manager_name, name, self.config)
            lb.add_host(host)
            self.hc.create(name)
            self.hc.add_url(name, host.dns_name)
        except:
            if lb is not None:
                lb.destroy()
            host.destroy()
            raise


class RemoveInstanceTask(BaseManagerTask):

    def run(self, config, name):
        self.init_config(config)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            host.destroy()
        lb.destroy()
        self.hc.destroy(name)


class BindInstanceTask(BaseManagerTask):

    def run(self, config, name, app_host):
        self.init_config(config)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            self.nginx_manager.update_binding(host.dns_name, app_host)


class ScaleInstanceTask(BaseManagerTask):

    def run(self, config, name, quantity):
        self.init_config(config)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        diff = quantity - len(lb.hosts)
        if diff == 0:
            return
        for i in xrange(abs(diff)):
            if diff > 0:
                host = Host.create(self.host_manager_name, name, self.config)
                lb.add_host(host)
                self.hc.add_url(name, host.dns_name)
            else:
                host = lb.hosts[i]
                host.destroy()
                lb.remove_host(host)
                self.hc.remove_url(name, host.dns_name)
