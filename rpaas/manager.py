# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

# coding: utf-8

import hm.managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA
from hm.model.load_balancer import LoadBalancer

from rpaas import storage, tasks, nginx


PENDING = 'pending'
FAILURE = 'failure'


class Manager(object):
    def __init__(self, config=None):
        self.config = config
        self.storage = storage.MongoDBStorage(config)
        self.nginx_manager = nginx.NginxDAV(config)

    def new_instance(self, name):
        task = tasks.NewInstanceTask().delay(self.config, name)
        self.storage.store_task(name, task.task_id)

    def remove_instance(self, name):
        self.storage.remove_task(name)
        tasks.RemoveInstanceTask().delay(self.config, name)

    def bind(self, name, app_host):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        binding_data = self.storage.find_binding(name)
        if binding_data:
            binded_host = binding_data.get('app_host')
            if binded_host == app_host:
                # Nothing to do, already binded
                return
            raise BindError('This service can only be binded to one application.')
        self.storage.store_binding(name, app_host)
        for host in lb.hosts:
            self.nginx_manager.update_binding(host.dns_name, '/', app_host)

    def unbind(self, name, app_host):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.remove_binding(name)
        for host in lb.hosts:
            self.nginx_manager.delete_binding(host.dns_name, '/')

    def info(self, name):
        addr = self._get_address(name)
        return [{"label": "Address", "value": addr}]

    def status(self, name):
        return self._get_address(name)

    def update_certificate(self, name, cert, key):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.update_binding_certificate(name, cert, key)
        for host in lb.hosts:
            self.nginx_manager.update_certificate(host.dns_name, cert, key)

    def _get_address(self, name):
        lb = LoadBalancer.find(name)
        if lb is None:
            task = self.storage.find_task(name)
            if task:
                result = tasks.NewInstanceTask().AsyncResult(task['task_id'])
                if result.status in ['FAILURE', 'REVOKED']:
                    return FAILURE
                return PENDING
            raise storage.InstanceNotFoundError()
        self.storage.remove_task(name)
        return lb.address

    def scale_instance(self, name, quantity):
        if quantity <= 0:
            raise ScaleError("Can't have 0 instances")
        tasks.ScaleInstanceTask().delay(self.config, name, quantity)

    def add_redirect(self, name, path, destination):
        path = path.strip()
        if path == '/':
            raise RedirectError("You cannot set a redirect for / location, bind to another app for that.")
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.add_binding_redirect(name, path, destination)
        for host in lb.hosts:
            self.nginx_manager.update_binding(host.dns_name, path, destination)

    def delete_redirect(self, name, path):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        path = path.strip()
        self.storage.delete_binding_redirect(name, path)
        for host in lb.hosts:
            self.nginx_manager.delete_binding(host.dns_name, path)

    def list_redirects(self, name):
        return self.storage.find_binding(name)


class BindError(Exception):
    pass


class ScaleError(Exception):
    pass


class RedirectError(Exception):
    pass
