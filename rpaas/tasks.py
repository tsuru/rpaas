# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import copy
import datetime
import logging
import os
import sys
from urlparse import urlparse

from celery import Celery, Task
import hm.managers.cloudstack  # NOQA
import hm.lb_managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA

from hm import config
from hm.model.host import Host
from hm.model.load_balancer import LoadBalancer

from rpaas import (consul_manager, hc, nginx, sslutils, ssl_plugins,
                   storage, celery_sentinel, acl, lock)
from rpaas.misc import check_option_enable

possible_redis_envs = ['SENTINEL_ENDPOINT', 'DBAAS_SENTINEL_ENDPOINT', 'REDIS_ENDPOINT']

celery_sentinel.register_celery_alias()


def setup_redis_url():
    env_val = None
    env_name = None
    for e in possible_redis_envs:
        env_name = e
        env_val = os.environ.get(e)
        if env_val:
            break
    if not env_val:
        redis_host = os.environ.get('REDIS_HOST', 'localhost')
        redis_port = os.environ.get('REDIS_PORT', '6379')
        redis_password = os.environ.get('REDIS_PASSWORD', '')
        auth_prefix = ''
        if redis_password:
            auth_prefix = ':{}@'.format(redis_password)
        return "redis://{}{}:{}/0".format(auth_prefix, redis_host, redis_port), {}
    url = urlparse(env_val)
    if url.scheme == 'sentinel':
        path_parts = url.path.split(':')
        if len(path_parts) != 2:
            raise Exception('invalid connection url in {}: {}'.format(env_name, env_val))
        options = {
            'service_name': path_parts[1],
            'password': url.password,
        }
        host_parts = url.netloc.split('@')
        servers = host_parts[len(host_parts) - 1].split(',')
        sentinels = []
        for s in servers:
            host_port = s.split(':')
            if len(host_port) != 2:
                raise Exception('invalid connection url in {}: {}'.format(env_name, env_val))
            sentinels.append(
                (host_port[0], host_port[1])
            )
        options['sentinels'] = sentinels
        return "redis-sentinel://", options
    return env_val, {}


def initialize_celery():
    redis_url, broker_options = setup_redis_url()
    app = Celery('tasks', broker=redis_url, backend=redis_url)
    app.conf.update(
        CELERY_TASK_SERIALIZER='json',
        CELERY_RESULT_SERIALIZER='json',
        CELERY_ACCEPT_CONTENT=['json'],
        BROKER_TRANSPORT_OPTIONS=broker_options,
        CELERY_SENTINEL_BACKEND_SETTINGS=broker_options,
    )
    ssl_plugins.register_plugins()
    return app


app = initialize_celery()


class NotReadyError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


class TaskManager(object):

    def __init__(self, config=None):
        self.storage = storage.MongoDBStorage(config)

    def ensure_ready(self, name):
        task = self.storage.find_task(name)
        if task.count() >= 1:
            raise NotReadyError("Async task still running")

    def remove(self, name):
        try:
            self.ensure_ready(name)
        except NotReadyError:
            self.storage.remove_task(name)
        else:
            raise TaskNotFoundError("Task {} not found for removal".format(name))

    def create(self, name):
        self.storage.store_task(name)

    def update(self, name, task_id):
        self.storage.update_task(name, task_id)


class BaseManagerTask(Task):
    ignore_result = True
    store_errors_even_if_ignored = True

    def init_config(self, config=None):
        self.config = config
        self.nginx_manager = nginx.Nginx(config)
        self.consul_manager = consul_manager.ConsulManager(config)
        self.host_manager_name = self._get_conf("HOST_MANAGER", "cloudstack")
        self.lb_manager_name = self._get_conf("LB_MANAGER", "networkapi_cloudstack")
        self.task_manager = TaskManager(config)
        self.lock_manager = lock.Lock(app.backend.client)
        self.hc = hc.Dumb()
        self.storage = storage.MongoDBStorage(config)
        self.acl_manager = acl.Dumb(self.consul_manager)
        if check_option_enable(self._get_conf("CHECK_ACL_API", None)):
            self.acl_manager = acl.AclManager(config, self.consul_manager, lock.Lock(app.backend.client))
        hc_url = self._get_conf("HCAPI_URL", None)
        if hc_url:
            self.hc = hc.HCAPI(self.storage,
                               url=hc_url,
                               user=self._get_conf("HCAPI_USER"),
                               password=self._get_conf("HCAPI_PASSWORD"),
                               hc_format=self._get_conf("HCAPI_FORMAT", "http://{}:8080/"))
        self.retry_countdown = os.environ.get("RETRY_COUNTDOWN", None)
        if self.retry_countdown:
            self.retry_countdown = int(self.retry_countdown)
        self.max_retries = os.environ.get("MAX_RETRIES", None)
        if self.max_retries:
            self.max_retries = int(self.max_retries)

    def _get_conf(self, key, default=config.undefined):
        return config.get_config(key, default, self.config)

    def _add_host(self, name, lb=None):
        healthcheck_timeout = int(self._get_conf("RPAAS_HEALTHCHECK_TIMEOUT", 600))
        created_lb = None
        try:
            if not lb:
                lb = created_lb = LoadBalancer.create(self.lb_manager_name, name, self.config)
                self.hc.create(name)
            config = copy.deepcopy(self.config)
            if hasattr(lb, 'dsr') and lb.dsr:
                config["HOST_TAGS"] = config["HOST_TAGS"] + ",dsr_ip:{}".format(lb.address)
            host = Host.create(self.host_manager_name, name, config)
            lb.add_host(host)
            self.nginx_manager.wait_healthcheck(host.dns_name, timeout=healthcheck_timeout)
            acls = self.consul_manager.find_acl_network(name)
            if acls:
                acl_host = acls.pop()
                for dst in acl_host['destination']:
                    self.acl_manager.add_acl(name, host.dns_name, dst)
            self.hc.add_url(name, host.dns_name)
        except:
            exc_info = sys.exc_info()
            rollback = self._get_conf("RPAAS_ROLLBACK_ON_ERROR", "0") in ("True", "true", "1")
            if not rollback:
                raise
            try:
                if created_lb is not None:
                    created_lb.destroy()
            except Exception as e:
                logging.error("Error in rollback trying to destroy load balancer: {}".format(e))
            try:
                if created_lb is not None:
                    self._delete_host(name, host)
                else:
                    self._delete_host(name, host, lb)
            except Exception as e:
                logging.error("Error in rollback trying to destroy host: {}".format(e))
            try:
                if lb and len(lb.hosts) == 0:
                    self.hc.destroy(name)
            except Exception as e:
                logging.error("Error in rollback trying to remove healthcheck: {}".format(e))
            raise exc_info[0], exc_info[1], exc_info[2]
        finally:
            self.storage.remove_task(name)

    def _delete_host(self, name, host, lb=None):
        try:
            node_name = self.consul_manager.node_hostname(host.dns_name)
            host.destroy()
            if lb is not None:
                lb.remove_host(host)
            if node_name is not None:
                self.consul_manager.remove_node(name, node_name, host.id)
            self.acl_manager.remove_acl(name, host.dns_name)
            self.hc.remove_url(name, host.dns_name)
        finally:
            self.storage.remove_task(name)

    def run(self, *args, **kwargs):
        try:
            self.execute(*args, **kwargs)
        except Exception as exc:
            self.retry(exc=exc, countdown=self.retry_countdown, max_retries=self.max_retries)

    def execute(self, *args, **kwargs):
        raise NotImplementedError


class NewInstanceTask(BaseManagerTask):

    def execute(self, config, name):
        self.init_config(config)
        self._add_host(name)


class RemoveInstanceTask(BaseManagerTask):

    def execute(self, config, name):
        self.init_config(config)
        lb = LoadBalancer.find(name, self.config)
        if lb is None:
            raise storage.InstanceNotFoundError()
        for host in lb.hosts:
            self._delete_host(name, host, lb)
        self.consul_manager.destroy_instance(name)
        lb.destroy()
        for cert in self.storage.find_le_certificates({'name': name}):
            self.storage.remove_le_certificate(name, cert['domain'])
        self.hc.destroy(name)


class ScaleInstanceTask(BaseManagerTask):

    def execute(self, config, name, quantity):
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
                    self._add_host(name, lb=lb)
                else:
                    self._delete_host(name, lb.hosts[i], lb)
        finally:
            self.storage.remove_task(name)


class RestoreMachineTask(BaseManagerTask):

    def execute(self, config):
        self.init_config(config)
        lock_name = self.config.get("RESTORE_LOCK_NAME", "restore_lock")
        healthcheck_timeout = int(self._get_conf("RPAAS_HEALTHCHECK_TIMEOUT", 600))
        restore_delay = int(self.config.get("RESTORE_MACHINE_DELAY", 5))
        created_in = datetime.datetime.utcnow() - datetime.timedelta(minutes=restore_delay)
        restore_query = {"_id": {"$regex": "restore_.+"}, "created": {"$lte": created_in}}
        if self.lock_manager.lock(lock_name, timeout=(healthcheck_timeout + 60)):
            for task in self.storage.find_task(restore_query):
                try:
                    start_time = datetime.datetime.utcnow()
                    self._restore_machine(task, config, healthcheck_timeout)
                    elapsed_time = datetime.datetime.utcnow() - start_time
                    self.lock_manager.extend_lock(lock_name, extra_time=elapsed_time.seconds)
                except Exception as e:
                    self.storage.update_task(task['_id'], {"last_attempt": datetime.datetime.utcnow()})
                    self.lock_manager.unlock(lock_name)
                    raise e
            self.lock_manager.unlock(lock_name)

    def _restore_machine(self, task, config, healthcheck_timeout):
        retry_failure_delay = int(self.config.get("RESTORE_MACHINE_FAILURE_DELAY", 5))
        restore_dry_mode = self.config.get("RESTORE_MACHINE_DRY_MODE", False) in ("True", "true", "1")
        retry_failure_query = {"_id": {"$regex": "restore_.+"}, "last_attempt": {"$ne": None}}
        if task['instance'] not in self._failure_instances(retry_failure_query, retry_failure_delay):
            host = self.storage.find_host_id(task['host'])
            if not restore_dry_mode:
                healing_id = self.storage.store_healing(task['instance'], task['host'])
                try:
                    Host.from_dict({"_id": host['_id'], "dns_name": task['host'],
                                    "manager": host['manager']}, conf=config).restore()
                    Host.from_dict({"_id": host['_id'], "dns_name": task['host'],
                                    "manager": host['manager']}, conf=config).start()
                    self.nginx_manager.wait_healthcheck(task['host'], timeout=healthcheck_timeout)
                    self.storage.update_healing(healing_id, "success")
                except Exception as e:
                    self.storage.update_healing(healing_id, str(e.message))
                    raise e
            self.storage.remove_task({"_id": task['_id']})

    def _failure_instances(self, retry_failure_query, retry_failure_delay):
        failure_instances = set()
        for task in self.storage.find_task(retry_failure_query):
            retry_failure = task['last_attempt'] + datetime.timedelta(minutes=retry_failure_delay)
            if (retry_failure >= datetime.datetime.utcnow()):
                failure_instances.add(task['instance'])
        return failure_instances


class CheckMachineTask(BaseManagerTask):

    def execute(self, config):
        self.init_config(config)
        for node in self.consul_manager.service_healthcheck():
            node_fail = False
            address = node['Node']['Address']
            if not self._check_machine_exists(address):
                logging.error("check_machine: machine {} not found".format(address))
                continue
            service_instance = self.config['RPAAS_SERVICE_NAME']
            for tag in node['Service']['Tags']:
                if self.config['RPAAS_SERVICE_NAME'] in tag:
                    continue
                service_instance = tag
            for check in node['Checks']:
                if check['Status'] != 'passing':
                    node_fail = True
                    break
            task_name = "restore_{}".format(address)
            if node_fail:
                try:
                    self.task_manager.ensure_ready(task_name)
                    self.task_manager.create({"_id": task_name, "host": address,
                                              "instance": service_instance,
                                              "created": datetime.datetime.utcnow()})
                except:
                    pass
            else:
                try:
                    self.task_manager.remove(task_name)
                except:
                    pass

    def _check_machine_exists(self, address):
        machine_data = self.storage.find_host_id(address)
        if machine_data is None:
            return False
        return True


class DownloadCertTask(BaseManagerTask):

    def execute(self, config, name, plugin, csr, key, domain):
        try:
            self.init_config(config)
            sslutils.generate_crt(self.config, name, plugin, csr, key, domain)
        finally:
            self.storage.remove_task(name)


class RevokeCertTask(BaseManagerTask):

    def execute(self, config, name, plugin, domain):
        try:
            self.init_config(config)
            lb = LoadBalancer.find(name, self.config)
            if lb is None:
                raise storage.InstanceNotFoundError()

            plugin_class = ssl_plugins.get(plugin)
            plugin_obj = plugin_class(domain, os.environ.get('RPAAS_PLUGIN_LE_EMAIL', 'admin@'+domain),
                                      name)
            plugin_obj.revoke()
            self.storage.remove_le_certificate(name, domain)
        except Exception, e:
            logging.error("Error in ssl plugin task: {}".format(e))
            raise e
        finally:
            self.storage.remove_task(name)


class RenewCertsTask(BaseManagerTask):

    def execute(self, config):
        self.init_config(config)
        expires_in = int(self.config.get("LE_CERTIFICATE_EXPIRATION_DAYS", 90))
        limit = datetime.datetime.utcnow() - datetime.timedelta(days=expires_in - 3)
        query = {"created": {"$lte": limit}}
        for cert in self.storage.find_le_certificates(query):
            metadata = self.storage.find_instance_metadata(cert["name"])
            config = copy.deepcopy(self.config)
            if metadata and "plan_name" in metadata:
                plan = self.storage.find_plan(metadata["plan_name"])
                config.update(plan.config)
            self.renew(cert, config)

    def renew(self, cert, config):
        key = sslutils.generate_key(True)
        csr = sslutils.generate_csr(key, cert["domain"])
        DownloadCertTask().delay(config=config, name=cert["name"], plugin="le",
                                 csr=csr, key=key, domain=cert["domain"])


class SessionResumptionTask(BaseManagerTask):

    def execute(self, config):
        self.init_config(config)
        session_resumption_rotate = int(self.config.get("SESSION_RESUMPTION_TICKET_ROTATE", 3600))
        instances_to_rotate = self.config.get("SESSION_RESUMPTION_INSTANCES", None)
        service_name = self.config.get("RPAAS_SERVICE_NAME", "rpaas")
        service_instance_lock = "session_resumption:{}:instance".format(service_name)
        instance_lock = self.config.get("SESSION_RESUMPTION_INSTANCE_LOCK_PREFIX", service_instance_lock)
        if instances_to_rotate:
            instances_to_rotate = instances_to_rotate.split(",")
        lb_data = LoadBalancer.list(conf=self.config)
        for lb in lb_data:
            if instances_to_rotate and lb.name not in instances_to_rotate:
                continue
            lock_name = "{}:{}".format(instance_lock, lb.name)
            if self.lock_manager.lock(lock_name, session_resumption_rotate):
                try:
                    self.rotate_session_ticket(lb.hosts)
                except Exception as e:
                    logging.error("Error renewing session ticket for {}: {}".format(lb.name, repr(e)))
                finally:
                    self.lock_manager.unlock(lock_name)

    def rotate_session_ticket(self, hosts):
        session_ticket = sslutils.generate_session_ticket()
        for host in hosts:
            self.add_session_ticket(host, session_ticket)

    def add_session_ticket(self, host, session_ticket):
        ticket_timeout = int(self.config.get("SESSION_RESUMPTION_TICKET_TIMEOUT", 30))
        exc_info = None
        try:
            self.consul_manager.get_certificate(host.group, host.id)
        except consul_manager.CertificateNotFoundError:
            try:
                certificate_key, certificate_crt = sslutils.generate_admin_crt(self.config, unicode(host.dns_name))
                self.consul_manager.set_certificate(host.group, certificate_crt, certificate_key, host.id)
            except:
                exc_info = sys.exc_info()
        finally:
            if isinstance(exc_info, tuple) and exc_info[0]:
                raise exc_info[0], exc_info[1], exc_info[2]
            self.nginx_manager.add_session_ticket(host.dns_name, session_ticket, ticket_timeout)
