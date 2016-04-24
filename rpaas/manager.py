# coding: utf-8

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import copy
import datetime
import os
import socket

import hm.managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA
from hm.model.load_balancer import LoadBalancer

from rpaas import consul_manager, nginx, ssl, ssl_plugins, storage, tasks

PENDING = "pending"
FAILURE = "failure"


class Manager(object):

    def __init__(self, config=None):
        self.config = config
        self.storage = storage.MongoDBStorage(config)
        self.consul_manager = consul_manager.ConsulManager(config)
        self.nginx_manager = nginx.Nginx(config)
        self.task_manager = tasks.TaskManager(config)
        self.service_name = os.environ.get("RPAAS_SERVICE_NAME", "rpaas")

    def new_instance(self, name, team=None, plan_name=None):
        plan = None
        if plan_name:
            plan = self.storage.find_plan(plan_name)
        used, quota = self.storage.find_team_quota(team)
        if len(used) >= quota:
            raise QuotaExceededError(len(used), quota)
        if not self.storage.increment_quota(team, used, name):
            raise Exception("concurrent operations updating team quota")
        lb = LoadBalancer.find(name)
        if lb is not None:
            raise storage.DuplicateError(name)
        self.task_manager.create(name)
        config = copy.deepcopy(self.config)
        metadata = {}
        if plan:
            config.update(plan.config)
            metadata["plan_name"] = plan_name
        metadata["consul_token"] = consul_token = self.consul_manager.generate_token(name)
        self.consul_manager.write_healthcheck(name)
        self.storage.store_instance_metadata(name, **metadata)
        self._add_tags(name, config, consul_token)
        task = tasks.NewInstanceTask().delay(config, name)
        self.task_manager.update(name, task.task_id)

    def _add_tags(self, instance_name, config, consul_token):
        tags = ["rpaas_service:" + self.service_name,
                "rpaas_instance:" + instance_name,
                "consul_token:" + consul_token]
        extra_tags = config.get("INSTANCE_EXTRA_TAGS", "")
        if extra_tags:
            del config["INSTANCE_EXTRA_TAGS"]
            tags.append(extra_tags)
        config["HOST_TAGS"] = ",".join(tags)

    def remove_instance(self, name):
        metadata = self.storage.find_instance_metadata(name)
        config = copy.deepcopy(self.config)
        if metadata and "plan_name" in metadata:
            plan = self.storage.find_plan(metadata["plan_name"])
            if plan:
                config.update(plan.config)
        if metadata and metadata.get("consul_token"):
            self.consul_manager.destroy_token(metadata["consul_token"])
        self.consul_manager.destroy_instance(name)
        self.storage.decrement_quota(name)
        self.storage.remove_task(name)
        self.storage.remove_binding(name)
        self.storage.remove_instance_metadata(name)
        tasks.RemoveInstanceTask().delay(config, name)

    def restore_machine_instance(self, name, machine, cancel_task=False):
        task_name = "restore_{}".format(machine)
        if cancel_task:
            self.task_manager.remove(task_name)
            return
        self.task_manager.ensure_ready(task_name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        machine_data = self.storage.find_host_id(machine)
        if machine_data is None:
            raise InstanceMachineNotFoundError()
        self.task_manager.create({"_id": task_name, "host": machine,
                                 "instance": name, "created": datetime.datetime.utcnow()})

    def bind(self, name, app_host):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        binding_data = self.storage.find_binding(name)
        if binding_data:
            bound_host = binding_data.get("app_host")
            if bound_host == app_host:
                # Nothing to do, already bound
                return
            if bound_host is not None:
                raise BindError("This service can only be bound to one application.")
        self.consul_manager.write_location(name, "/", destination=app_host)
        self.storage.store_binding(name, app_host)

    def unbind(self, name, app_host):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        binding_data = self.storage.find_binding(name)
        if not binding_data:
            return
        self.storage.remove_root_binding(name)
        self.consul_manager.remove_location(name, "/")

    def info(self, name):
        addr = self._get_address(name)
        routes_data = []
        binding_data = self.storage.find_binding(name)
        if binding_data:
            paths = binding_data.get("paths") or []
            for path_data in paths:
                routes_data.append("path = {}".format(path_data["path"]))
                dst = path_data.get("destination")
                content = path_data.get("content")
                if dst:
                    routes_data.append("destination = {}".format(dst))
                if content:
                    routes_data.append("content = {}".format(content))
        lb = LoadBalancer.find(name)
        host_count = 0
        if lb:
            host_count = len(lb.hosts)
        data = [
            {
                "label": "Address",
                "value": addr,
            },
            {
                "label": "Instances",
                "value": str(host_count),
            },
            {
                "label": "Routes",
                "value": "\n".join(routes_data),
            },
        ]
        metadata = self.storage.find_instance_metadata(name)
        if metadata and "plan_name" in metadata:
            data.append({"label": "Plan", "value": metadata["plan_name"]})
        return data

    def status(self, name):
        return self._get_address(name)

    def node_status(self, name):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        hostnames = {}
        for host in lb.hosts:
            hostname = self.consul_manager.node_hostname(host.dns_name)
            if hostname is not None:
                hostnames[hostname] = host.dns_name
        node_status_return = {}
        for node, status in self.consul_manager.node_status(name).iteritems():
            node_status_return[node] = {'status': status}
            if node in hostnames:
                node_status_return[node]['address'] = hostnames[node]
        return node_status_return

    def update_certificate(self, name, cert, key):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.update_binding_certificate(name, cert, key)
        self.consul_manager.set_certificate(name, cert, key)

    def _get_address(self, name):
        task = self.storage.find_task(name)
        if task.count() >= 1:
            result = tasks.NewInstanceTask().AsyncResult(task[0]["task_id"])
            if result.status in ["FAILURE", "REVOKED"]:
                return FAILURE
            return PENDING
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return lb.address

    def scale_instance(self, name, quantity):
        self.task_manager.ensure_ready(name)
        if quantity <= 0:
            raise ScaleError("Can't have 0 instances")
        self.task_manager.create(name)
        config = copy.deepcopy(self.config)
        metadata = self.storage.find_instance_metadata(name)
        if not metadata or "consul_token" not in metadata:
            metadata = metadata or {}
            metadata["consul_token"] = self.consul_manager.generate_token(name)
            self.storage.store_instance_metadata(name, **metadata)
        if "plan_name" in metadata:
            plan = self.storage.find_plan(metadata["plan_name"])
            config.update(plan.config or {})
        self._add_tags(name, config, metadata["consul_token"])
        task = tasks.ScaleInstanceTask().delay(config, name, quantity)
        self.task_manager.update(name, task.task_id)

    def add_route(self, name, path, destination, content):
        self.task_manager.ensure_ready(name)
        path = path.strip()
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.replace_binding_path(name, path, destination, content)
        self.consul_manager.write_location(name, path, destination=destination,
                                           content=content)

    def delete_route(self, name, path):
        self.task_manager.ensure_ready(name)
        path = path.strip()
        if path == "/":
            raise RouteError("You cannot remove a route for / location, unbind the app.")
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.delete_binding_path(name, path)
        self.consul_manager.remove_location(name, path)

    def list_routes(self, name):
        return self.storage.find_binding(name)

    def purge_location(self, name, path):
        self.task_manager.ensure_ready(name)
        path = path.strip()
        lb = LoadBalancer.find(name)
        purged_hosts = 0
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            if self.nginx_manager.purge_location(host.dns_name, path):
                purged_hosts += 1
        return purged_hosts

    def add_block(self, name, block_name, content):
        self.task_manager.ensure_ready(name)
        block_name = block_name.strip()
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.consul_manager.write_block(name, block_name, content)

    def delete_block(self, name, block_name):
        self.task_manager.ensure_ready(name)
        block_name = block_name.strip()
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.consul_manager.remove_block(name, block_name)

    def list_blocks(self, name):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return self.consul_manager.list_blocks(name)

    def _check_dns(self, name, domain):
        ''' Check if the DNS name is registered for the rpaas VIP
        @param domain Domain name
        @param vip rpaas ip
        '''
        try:
            address = self._get_address(name)
        except:
            return False
        else:
            if address == FAILURE or address == PENDING:
                return False

        try:
            answer = socket.getaddrinfo(domain, 0, 0, 0, 0)
        except:
            return False
        else:
            if address not in [ip[4][0] for ip in answer]:
                return False

        return True

    def activate_ssl(self, name, domain, plugin='default'):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()

        if not self._check_dns(name, domain):
            raise SslError('rpaas IP is not registered for this DNS name')

        key = ssl.generate_key()
        csr = ssl.generate_csr(key, domain)

        if plugin == 'le':
            try:
                self.task_manager.create(name)
                task = tasks.DownloadCertTask().delay(self.config, name, plugin, csr, key, domain)
                self.task_manager.update(name, task.task_id)
                return ''
            except Exception:
                raise SslError('rpaas IP is not registered for this DNS name')

        else:
            p_ssl = ssl_plugins.default.Default(domain)
            cert = p_ssl.download_crt(key=key)
            self.update_certificate(name, cert, key)
            return ''

    def revoke_ssl(self, name, plugin='default'):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()

        if plugin.isalpha() and plugin in ssl_plugins.__all__ and \
           plugin not in ['default', '__init__']:

            try:
                self.task_manager.create(name)
                task = tasks.RevokeCertTask().dealy(self.config, name, plugin)
                self.task_manager.update(name, task.task_id)
                return ''
            except Exception:
                raise SslError('rpaas IP is not registered for this DNS name')

        else:
            raise SslError('SSL plugin not defined')

        return ''


class BindError(Exception):
    pass


class ScaleError(Exception):
    pass


class RouteError(Exception):
    pass


class SslError(Exception):
    pass


class InstanceMachineNotFoundError(Exception):
    pass


class QuotaExceededError(Exception):

    def __init__(self, used, quota):
        super(QuotaExceededError, self).__init__("quota execeeded {}/{} used".format(used, quota))
