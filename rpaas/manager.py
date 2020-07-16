# coding: utf-8

# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import copy
import datetime
import os
import socket
import threading
import time

import hm.managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA
from hm.model.load_balancer import LoadBalancer
from celery.utils import uuid

from rpaas import (consul_manager, nginx, sslutils, ssl_plugins,
                   storage, tasks, acl, lock)
from rpaas.misc import check_option_enable, host_from_destination

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
        self.acl_manager = acl.Dumb(self.consul_manager)
        if check_option_enable(os.environ.get("CHECK_ACL_API", None)):
            self.acl_manager = acl.AclManager(config, self.consul_manager, lock.Lock(tasks.app.backend.client))

    def new_instance(self, name, team=None, plan_name=None, flavor_name=None):
        plan = None
        flavor = None
        if plan_name:
            plan = self.storage.find_plan(plan_name)
        if flavor_name:
            flavor = self.storage.find_flavor(flavor_name)
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
        if flavor:
            config.update(flavor.config)
            metadata["flavor_name"] = flavor_name
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
        if not self.consul_manager.check_swap_state(name, None):
            raise consul_manager.InstanceAlreadySwappedError()
        self.task_manager.create(name)
        metadata = self.storage.find_instance_metadata(name)
        config = copy.deepcopy(self.config)
        if metadata and "plan_name" in metadata:
            plan = self.storage.find_plan(metadata["plan_name"])
            if plan:
                config.update(plan.config)
        if metadata and "flavor_name" in metadata:
            flavor = self.storage.find_flavor(metadata["flavor_name"])
            if flavor:
                config.update(flavor.config)
        if metadata and metadata.get("consul_token"):
            self.consul_manager.destroy_token(metadata["consul_token"])
        self.storage.decrement_quota(name)
        self.storage.remove_task(name)
        self.storage.remove_binding(name)
        self.storage.remove_instance_metadata(name)
        tasks.RemoveInstanceTask().delay(config, name)

    def update_instance(self, name, plan_name=None, flavor_name=None):
        if plan_name and not self.storage.find_plan(plan_name):
            raise storage.PlanNotFoundError()
        if flavor_name and not self.storage.find_flavor(flavor_name):
            raise storage.FlavorNotFoundError()
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        metadata = self.storage.find_instance_metadata(name)
        if flavor_name:
            metadata['flavor_name'] = flavor_name
        if plan_name:
            metadata['plan_name'] = plan_name
        self.storage.store_instance_metadata(name, **metadata)

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

    def restore_instance(self, name):
        self.task_manager.ensure_ready(name)
        self.task_manager.create(name)
        config = copy.deepcopy(self.config)
        metadata = self.storage.find_instance_metadata(name)
        if metadata and "plan_name" in metadata:
            plan = self.storage.find_plan(metadata["plan_name"])
            config.update(plan.config or {})
        if metadata and "flavor_name" in metadata:
            flavor = self.storage.find_flavor(metadata["flavor_name"])
            config.update(flavor.config or {})
        healthcheck_timeout = int(config.get("RPAAS_HEALTHCHECK_TIMEOUT", 600))
        tags = []
        extra_tags = config.get("INSTANCE_EXTRA_TAGS", "")
        if extra_tags:
            tags.append(extra_tags)
            config["HOST_TAGS"] = ",".join(tags)
        try:
            self.task_manager.update(name, uuid())
            lb = LoadBalancer.find(name, config)
            if lb is None:
                raise storage.InstanceNotFoundError()
            length = len(lb.hosts)
            for idx, host in enumerate(lb.hosts):
                yield "Restoring host ({}/{}) {} ".format(idx + 1, length, host.id)
                stop_host_job = JobWaiting(host.stop, 0)
                stop_host_job.start()
                while stop_host_job.is_alive():
                    yield "."
                    time.sleep(1)
                if isinstance(stop_host_job.result, Exception):
                    raise stop_host_job.result
                scale_host_job = JobWaiting(host.scale, 0)
                scale_host_job.start()
                while scale_host_job.is_alive():
                    yield "."
                    time.sleep(1)
                if isinstance(scale_host_job.result, Exception):
                    raise scale_host_job.result
                restore_host_job = JobWaiting(host.restore, 0, reset_template=True, reset_tags=True)
                restore_host_job.start()
                while restore_host_job.is_alive():
                    yield "."
                    time.sleep(1)
                if isinstance(restore_host_job.result, Exception):
                    raise restore_host_job.result
                host.start()
                nginx_waiting = self.nginx_manager.wait_healthcheck
                restore_delay = int(config.get("RPAAS_RESTORE_DELAY", 30))
                nginx_healthcheck_job = JobWaiting(nginx_waiting, restore_delay, host=host.dns_name,
                                                   timeout=healthcheck_timeout, manage_healthcheck=False)
                nginx_healthcheck_job.start()
                while nginx_healthcheck_job.is_alive():
                    yield "."
                    time.sleep(1)
                if isinstance(nginx_healthcheck_job.result, Exception):
                    raise nginx_healthcheck_job.result
                yield ": successfully restored\n"
        except storage.InstanceNotFoundError:
            yield "instance {} not found\n".format(name)
        except Exception as e:
            yield ": failed to restore - {}\n".format(repr(e.message))
        finally:
            self.task_manager.remove(name)

    def bind(self, name, app_host, router_mode=False):
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
            paths = binding_data.get("paths")
            for path in paths:
                if path.get("path") == "/" and "content" in path:
                    self.storage.store_binding(name, app_host, app_host_only=True)
                    return
        bind_mode = not router_mode
        self.consul_manager.write_location(name, "/", destination=app_host, router_mode=router_mode,
                                           bind_mode=bind_mode, https_only=False)
        self.storage.store_binding(name, app_host)

    def unbind(self, name):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        binding_data = self.storage.find_binding(name)
        if not binding_data:
            return
        paths = binding_data.get("paths")
        for path in paths:
            if path.get("path") == "/" and "content" in path:
                self.storage.remove_root_binding(name, False)
                return
        bound_host = binding_data.get("app_host")
        self.storage.remove_root_binding(name, True)
        self.consul_manager.write_location(name, "/", content=nginx.NGINX_LOCATION_INSTANCE_NOT_BOUND)
        self.consul_manager.remove_server_upstream(name, "rpaas_default_upstream", bound_host)

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
                https_only = path_data.get("https_only")
                if https_only and dst:
                    dst = "{} (https only)".format(dst)
                if dst:
                    routes_data.append("destination = {}".format(dst))
                if content:
                    routes_data.append("content = {}".format(content.encode("utf-8")))
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

    def swap(self, src_instance, dst_instance):
        self.task_manager.ensure_ready(src_instance)
        self.task_manager.ensure_ready(dst_instance)
        for instance in [src_instance, dst_instance]:
            lb = LoadBalancer.find(instance)
            if lb is None:
                raise storage.InstanceNotFoundError(instance)
        self.consul_manager.swap_instances(src_instance, dst_instance)

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

    def get_certificate(self, name):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return self.consul_manager.get_certificate(name)

    def update_certificate(self, name, cert, key):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.consul_manager.set_certificate(name, cert, key)

    def delete_certificate(self, name):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.consul_manager.delete_certificate(name)

    def add_upstream(self, name, upstream_name, servers, acl=False):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        if acl:
            for host in lb.hosts:
                if not isinstance(servers, list):
                    servers = [servers]
                for server in servers:
                    dst_host, _ = host_from_destination(server)
                    self.acl_manager.add_acl(name, host.dns_name, dst_host)
        self.consul_manager.add_server_upstream(name, upstream_name, servers)

    def remove_upstream(self, name, upstream_name, servers):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.consul_manager.remove_server_upstream(name, upstream_name, servers)

    def list_upstreams(self, name, upstream_name):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return self.consul_manager.list_upstream(name, upstream_name)

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
        if quantity < 0:
            raise ScaleError("Can't have negative instances")
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
        if "flavor_name" in metadata:
            flavor = self.storage.find_flavor(metadata["flavor_name"])
            config.update(flavor.config or {})
        self._add_tags(name, config, metadata["consul_token"])
        task = tasks.ScaleInstanceTask().delay(config, name, quantity)
        self.task_manager.update(name, task.task_id)

    def add_route(self, name, path, destination, content, https_only):
        self.task_manager.ensure_ready(name)
        path = path.strip()
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.replace_binding_path(name, path, destination, content, https_only)
        self.consul_manager.write_location(name, path, destination=destination,
                                           content=content, https_only=https_only)

    def delete_route(self, name, path):
        self.task_manager.ensure_ready(name)
        path = path.strip()
        if path == "/":
            raise RouteError("You cannot remove a route for / location, unbind the app.")
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        routes = self.list_routes(name)
        destination_count = 0
        if not routes:
            raise storage.InstanceNotFoundError()
        destination = [p['destination'] for p in routes['paths'] if p['path'] == path]
        if len(destination) > 0:
            destination = destination.pop()
        else:
            destination = None
        for p in routes['paths']:
            if destination and p['destination'] == destination:
                destination_count += 1
        if destination_count == 1:
            self.consul_manager.remove_server_upstream(name, destination, destination)
        self.storage.delete_binding_path(name, path)
        self.consul_manager.remove_location(name, path)

    def list_routes(self, name):
        return self.storage.find_binding(name)

    def list_healings(self, quantity):
        return self.storage.list_healings(quantity)

    def purge_location(self, name, path, preserve_path=False):
        self.task_manager.ensure_ready(name)
        if not preserve_path:
            path = path.strip()
        lb = LoadBalancer.find(name)
        purged_hosts = 0
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            if self.nginx_manager.purge_location(host.dns_name, path, preserve_path):
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

    def add_lua(self, name, lua_module_name, lua_module_type, content):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            storage.InstanceNotFoundError()
        self.consul_manager.write_lua(name, lua_module_name, lua_module_type, content)

    def list_lua(self, name):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return self.consul_manager.list_lua_modules(name)

    def delete_lua(self, name, lua_module_name, lua_module_type):
        self.task_manager.ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.consul_manager.remove_lua(name, lua_module_name, lua_module_type)

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

        key = sslutils.generate_key(True)
        csr = sslutils.generate_csr(key, domain)

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
                task = tasks.RevokeCertTask().delay(self.config, name, plugin)
                self.task_manager.update(name, task.task_id)
                return ''
            except Exception:
                raise SslError('rpaas IP is not registered for this DNS name')

        else:
            raise SslError('SSL plugin not defined')

        return ''


class JobWaiting(threading.Thread):

    def __init__(self, job, sleep, **kwargs):
        super(JobWaiting, self).__init__()
        self.daemon = True
        self.job = job
        self.sleep = sleep
        self.job_args = kwargs
        self.result = None

    def run(self):
        try:
            self.result = self.job(**self.job_args)
            time.sleep(self.sleep)
        except Exception as e:
            self.result = e


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
