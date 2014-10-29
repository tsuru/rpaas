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
        self.storage = storage.MongoDBStorage()
        self.nginx_manager = nginx.NginxDAV(config)

    def new_instance(self, name):
        task = tasks.NewInstanceTask().delay(self.config, name)
        self.storage.store_task(name, task.task_id)

    def remove_instance(self, name):
        self.storage.remove_task(name)
        tasks.RemoveInstanceTask().delay(self.config, name)

    def bind(self, name, app_host):
        tasks.BindInstanceTask().delay(self.config, name, app_host)

    def unbind(self, name, app_host):
        pass

    def info(self, name):
        addr = self._get_address(name)
        return [{"label": "Address", "value": addr}]

    def status(self, name):
        return self._get_address(name)

    def update_certificate(self, name, cert, key):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
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


class ScaleError(Exception):
    pass
