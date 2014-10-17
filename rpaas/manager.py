# coding: utf-8

from hm import config
from hm.model.host import Host
from hm.model.load_balancer import LoadBalancer

from rpaas import hc, storage


class Manager(object):
    def __init__(self, config=None):
        self.config = config
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

    def new_instance(self, name):
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

    def remove_instance(self, name):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            host.destroy()
        lb.destroy()
        self.hc.destroy(name)

    def bind(self, name, app_host):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            pass
            # self.manager.write_vcl(unit.dns_name, unit.secret, app_host)

    def unbind(self, name, host):
        pass

    def info(self, name):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return [{"label": "Address", "value": lb.address or "<pending>"}]

    def status(self, name):
        return "TODO"

    def scale_instance(self, name, quantity):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        diff = quantity - len(lb.hosts)
        is_add = True
        if diff < 0:
            is_add = False
            diff = abs(diff)
            if diff >= len(lb.hosts):
                raise Exception("At least 1 instance must remain")
        for i in xrange(diff):
            if is_add:
                host = Host.create(self.host_manager_name, name)
                lb.add_host(host)
                self.hc.add_url(name, host.dns_name)
            else:
                host = lb.hosts[i]
                host.destroy()
                lb.remove_host(host)
                self.hc.remove_url(name, host.dns_name)
