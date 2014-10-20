# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

# coding: utf-8

import hm.managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA
from hm.model.load_balancer import LoadBalancer

from rpaas import storage, tasks


class Manager(object):
    def __init__(self, config=None):
        self.config = config

    def new_instance(self, name):
        tasks.NewInstanceTask().delay(self.config, name)

    def remove_instance(self, name):
        tasks.RemoveInstanceTask().delay(self.config, name)

    def bind(self, name, app_host):
        tasks.BindInstanceTask().delay(self.config, name, app_host)

    def unbind(self, name, host):
        # TODO
        pass

    def info(self, name):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return [{"label": "Address", "value": lb.address or "<pending>"}]

    def status(self, name):
        return "TODO"

    def scale_instance(self, name, quantity):
        if quantity <= 0:
            raise ScaleError("Can't have 0 instances")
        tasks.ScaleInstanceTask().delay(self.config, name, quantity)


class ScaleError(Exception):
    pass
