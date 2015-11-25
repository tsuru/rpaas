# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

from rpaas import storage


class FakeInstance(object):

    def __init__(self, name, state, plan):
        self.name = name
        self.state = state
        self.units = 1
        self.plan = plan
        self.bound = []
        self.routes = {}

    def bind(self, app_host):
        self.bound.append(app_host)

    def unbind(self, app_host):
        self.bound.remove(app_host)


class FakeManager(object):

    def __init__(self, storage=None):
        self.instances = []
        self.storage = storage

    def new_instance(self, name, state="running", team=None, plan_name=None):
        if plan_name:
            self.storage.find_plan(plan_name)
        instance = FakeInstance(name, state, plan_name)
        self.instances.append(instance)
        return instance

    def bind(self, name, app_host):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        instance.bind(app_host)

    def unbind(self, name, app_host):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        instance.unbind(app_host)

    def remove_instance(self, name):
        index, _ = self.find_instance(name)
        if index == -1:
            raise storage.InstanceNotFoundError()
        del self.instances[index]

    def info(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        return {"name": instance.name}

    def status(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        return instance.state

    def scale_instance(self, name, quantity):
        if quantity < 1:
            raise ValueError("invalid quantity: %d" % quantity)
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        difference = quantity - instance.units
        instance.units += difference
        self.instances[index] = instance

    def update_certificate(self, name, cert, key):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        instance.cert = cert
        instance.key = key

    def find_instance(self, name):
        for i, instance in enumerate(self.instances):
            if instance.name == name:
                return i, instance
        return -1, None

    def add_route(self, name, path, destination, content):
        _, instance = self.find_instance(name)
        instance.routes[path] = {'destination': destination, 'content': content}

    def delete_route(self, name, path):
        _, instance = self.find_instance(name)
        del instance.routes[path]

    def list_routes(self, name):
        _, instance = self.find_instance(name)
        return instance.routes

    def purge_location(self, name, path):
        _, instance = self.find_instance(name)
        return 4

    def reset(self):
        self.instances = []
