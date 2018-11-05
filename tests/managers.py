# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

from collections import defaultdict

from rpaas import storage, manager, consul_manager


class FakeInstance(object):

    def __init__(self, name, state, plan, flavor):
        self.name = name
        self.state = state
        self.units = 1
        self.plan = plan
        self.flavor = flavor
        self.bound = False
        self.routes = {}
        self.blocks = {}
        self.lua_modules = {}
        self.node_status = {}
        self.upstreams = defaultdict(set)
        self.cert = None
        self.key = None


class FakeManager(object):

    def __init__(self, storage=None):
        self.instances = []
        self.storage = storage

    def new_instance(self, name, state="running", team=None, plan_name=None, flavor_name=None):
        if plan_name:
            self.storage.find_plan(plan_name)
        if flavor_name:
            self.storage.find_flavor(flavor_name)
        instance = FakeInstance(name, state, plan_name, flavor_name)
        self.instances.append(instance)
        return instance

    def bind(self, name, app_host, router_mode=False):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        instance.bound = True

    def unbind(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        instance.bound = False

    def check_bound(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        return instance.bound

    def remove_instance(self, name):
        if name == 'router-swap_error':
            raise consul_manager.InstanceAlreadySwappedError()
        index, _ = self.find_instance(name)
        if index == -1:
            raise storage.InstanceNotFoundError()
        del self.instances[index]

    def update_instance(self, name, plan_name=None, flavor_name=None):
        index, _ = self.find_instance(name)
        if index == -1:
            raise storage.InstanceNotFoundError()
        if plan_name:
            self.storage.find_plan(plan_name)
        if flavor_name:
            self.storage.find_flavor(flavor_name)
            self.instances[index].flavor = flavor_name
        if plan_name:
            self.instances[index].plan = plan_name

    def info(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        return {"name": instance.name, "plan": instance.plan}

    def node_status(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        return instance.node_status

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

    def get_certificate(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        if not instance.cert or not instance.key:
            raise consul_manager.CertificateNotFoundError()
        return instance.cert, instance.key

    def delete_certificate(self, name):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        instance.cert = None
        instance.key = None

    def find_instance(self, name):
        for i, instance in enumerate(self.instances):
            if instance.name == name:
                return i, instance
        return -1, None

    def add_route(self, name, path, destination, content, https_only):
        _, instance = self.find_instance(name)
        instance.routes[path] = {'destination': destination, 'content': content, 'https_only': https_only}

    def delete_route(self, name, path):
        _, instance = self.find_instance(name)
        del instance.routes[path]

    def list_routes(self, name):
        _, instance = self.find_instance(name)
        return instance.routes

    def add_block(self, name, block_name, content):
        _, instance = self.find_instance(name)
        instance.blocks[block_name] = {'content': content}

    def delete_block(self, name, block_name):
        _, instance = self.find_instance(name)
        del instance.blocks[block_name]

    def list_blocks(self, name):
        _, instance = self.find_instance(name)
        return instance.blocks

    def purge_location(self, name, path, preserve_path):
        _, instance = self.find_instance(name)
        if preserve_path:
            return 3
        return 4

    def reset(self):
        self.instances = []

    def restore_machine_instance(self, name, machine, cancel_task=False):
        index, instance = self.find_instance(name)
        if index < 0:
            raise storage.InstanceNotFoundError()
        if machine != 'foo':
            raise manager.InstanceMachineNotFoundError()

    def restore_instance(self, name):
        if name in "invalid":
            yield "instance {} not found".format(name)
            return
        for machine in ["a", "b"]:
            yield "host {} restored".format(machine)
        if name in "error":
            yield "host c failed to restore"

    def add_lua(self, name, lua_module_name, lua_module_type, content):
        _, instance = self.find_instance(name)
        instance.lua_modules[lua_module_name] = {lua_module_type: {'content': content}}

    def list_lua(self, name):
        _, instance = self.find_instance(name)
        return instance.lua_modules

    def delete_lua(self, name, lua_module_name, lua_module_type):
        _, instance = self.find_instance(name)
        del instance.lua_modules[lua_module_type][lua_module_name]

    def add_upstream(self, name, upstream_name, server, acl=False):
        _, instance = self.find_instance(name)
        if isinstance(server, list):
            instance.upstreams[upstream_name] |= set(server)
        else:
            instance.upstreams[upstream_name].add(server)

    def remove_upstream(self, name, upstream_name, server):
        _, instance = self.find_instance(name)
        servers = instance.upstreams[upstream_name]
        if isinstance(server, list):
            servers -= set(server)
        else:
            if server in servers:
                servers.remove(server)
        instance.upstreams[upstream_name] = servers

    def list_upstreams(self, name, upstream_name):
        _, instance = self.find_instance(name)
        return instance.upstreams[upstream_name]

    def swap(self, instance_a, instance_b):
        _, instance_a = self.find_instance(instance_a)
        _, instance_b = self.find_instance(instance_b)
        if not instance_a:
            raise storage.InstanceNotFoundError()
        if not instance_b:
            raise consul_manager.InstanceAlreadySwappedError()
