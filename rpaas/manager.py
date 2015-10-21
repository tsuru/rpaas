# coding: utf-8

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import copy

import hm.managers.cloudstack  # NOQA
import hm.lb_managers.networkapi_cloudstack  # NOQA
from hm.model.load_balancer import LoadBalancer

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.exceptions import InvalidSignature

import os
from base64 import b64encode
import socket

from rpaas import storage, tasks, nginx
import rpaas.ssl_plugins
from rpaas.ssl_plugins import *
import inspect
import json

PENDING = 'pending'
FAILURE = 'failure'


class Manager(object):
    def __init__(self, config=None):
        self.config = config
        self.storage = storage.MongoDBStorage(config)
        self.nginx_manager = nginx.NginxDAV(config)

    def new_instance(self, name, team=None, plan=None):
        if plan:
            plan = self.storage.find_plan(plan)
        used, quota = self.storage.find_team_quota(team)
        if len(used) >= quota:
            raise QuotaExceededError(len(used), quota)
        if not self.storage.increment_quota(team, used, name):
            raise Exception("concurrent operations updating team quota")
        lb = LoadBalancer.find(name)
        if lb is not None:
            raise storage.DuplicateError(name)
        self.storage.store_task(name)
        config = copy.deepcopy(self.config)
        self._add_tags(name, config)
        if plan:
            config.update(plan.config)
            self.storage.store_instance_metadata(name, plan=plan.to_dict())
        task = tasks.NewInstanceTask().delay(config, name)
        self.storage.update_task(name, task.task_id)

    def _add_tags(self, instance_name, config):
        tags = ["rpaas_instance:"+instance_name]
        extra_tags = config.get("INSTANCE_EXTRA_TAGS", "")
        if extra_tags:
            del config["INSTANCE_EXTRA_TAGS"]
            tags.append(extra_tags)
        config["INSTANCE_TAGS"] = ",".join(tags)

    def remove_instance(self, name):
        self.storage.decrement_quota(name)
        self.storage.remove_task(name)
        self.storage.remove_binding(name)
        self.storage.remove_instance_metadata(name)
        tasks.RemoveInstanceTask().delay(self.config, name)

    def bind(self, name, app_host):
        self._ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        binding_data = self.storage.find_binding(name)
        if binding_data:
            binded_host = binding_data.get('app_host')
            if binded_host == app_host:
                # Nothing to do, already binded
                return
            if binded_host is not None:
                raise BindError('This service can only be binded to one application.')
        for host in lb.hosts:
            self.nginx_manager.update_binding(host.dns_name, '/', app_host)
        self.storage.store_binding(name, app_host)

    def unbind(self, name, app_host):
        self._ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        binding_data = self.storage.find_binding(name)
        if not binding_data:
            return
        self.storage.remove_root_binding(name)
        for host in lb.hosts:
            self.nginx_manager.delete_binding(host.dns_name, '/')

    def info(self, name):
        addr = self._get_address(name)
        routes_data = []
        binding_data = self.storage.find_binding(name)
        if binding_data:
            paths = binding_data.get('paths') or []
            for path_data in paths:
                routes_data.append("path = {}".format(path_data['path']))
                dst = path_data.get('destination')
                content = path_data.get('content')
                if dst:
                    routes_data.append("destination = {}".format(dst))
                if content:
                    routes_data.append("content = {}".format(content))
        lb = LoadBalancer.find(name)
        host_count = 0
        if lb:
            host_count = len(lb.hosts)
        return [
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

    def status(self, name):
        return self._get_address(name)

    def update_certificate(self, name, cert, key):
        self._ensure_ready(name)
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        if not self._verify_crt(cert, key):
            raise SslError('Invalid certificate')
        self.storage.update_binding_certificate(name, cert, key)
        for host in lb.hosts:
            self.nginx_manager.update_certificate(host.dns_name, cert, key)

    def _get_address(self, name):
        task = self.storage.find_task(name)
        if task:
            result = tasks.NewInstanceTask().AsyncResult(task['task_id'])
            if result.status in ['FAILURE', 'REVOKED']:
                return FAILURE
            return PENDING
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        return lb.address

    def scale_instance(self, name, quantity):
        self._ensure_ready(name)
        if quantity <= 0:
            raise ScaleError("Can't have 0 instances")
        self.storage.store_task(name)
        config = copy.deepcopy(self.config)
        metadata = self.storage.find_instance_metadata(name)
        if metadata and metadata.get("plan"):
            plan = metadata.get("plan")
            config.update(plan.get("config") or {})
        task = tasks.ScaleInstanceTask().delay(config, name, quantity)
        self.storage.update_task(name, task.task_id)

    def add_route(self, name, path, destination, content):
        self._ensure_ready(name)
        path = path.strip()
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.replace_binding_path(name, path, destination, content)
        for host in lb.hosts:
            self.nginx_manager.update_binding(host.dns_name, path, destination, content)

    def delete_route(self, name, path):
        self._ensure_ready(name)
        path = path.strip()
        if path == '/':
            raise RouteError("You cannot remove a route for / location, unbind the app.")
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()
        self.storage.delete_binding_path(name, path)
        for host in lb.hosts:
            self.nginx_manager.delete_binding(host.dns_name, path)

    def list_routes(self, name):
        return self.storage.find_binding(name)

    def _ensure_ready(self, name):
        task = self.storage.find_task(name)
        if task:
            raise NotReadyError("Async task still running")

    def _verify_crt(self, raw_crt, raw_key):
        ''' Verify if a random private key signed message is valid
        '''
        try:
            crt = x509.load_pem_x509_certificate(raw_crt, default_backend())
            key = serialization.load_pem_private_key(raw_key, None, default_backend())

            signer = key.signer(
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA1()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            message = b"A message I want to sign"
            signer.update(message)
            signature = signer.finalize()

            public_key = crt.public_key()
            verifier = public_key.verifier(
                signature,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA1()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            verifier.update(message)
            verifier.verify()
        except:
            return False
        return True

    def _generate_key(self):
        # Generate our key
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )

        # Return serialized private key
        return key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption(),
                )

    def _generate_csr(self, key, domainname):
        # Generate a CSR
        private_key = serialization.load_pem_private_key(
            key,
            password=None,
            backend=default_backend()
        )
        csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
            # Provide various details about who we are.
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"BR"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"RJ"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u"Rio de Janeiro"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"globo.com"),
            x509.NameAttribute(NameOID.COMMON_NAME, domainname),
        ])).add_extension(
            x509.SubjectAlternativeName([
                # Sites we want this certificate for.
                x509.DNSName(domainname),
            ]),
            critical=False,
        # Sign the CSR with our private key.
        ).sign(private_key, hashes.SHA256(), default_backend())

        # Return serialized CSR
        return csr.public_bytes(serialization.Encoding.PEM)

    def _check_dns(self, name, domain):
        ''' Check if the DNS name is registered for the rpaas VIP
        @param domain Domain name
        @param vip rpaas ip
        '''
        address = self._get_address(name)
        if address == FAILURE or address == PENDING:
            return False

        answer = socket.getaddrinfo(domain, 0,0,0,0)
        if address not in [ip[4][0] for ip in answer]:
            return False

        return True

    def activate_ssl(self, name, domain, plugin='default'):
        lb = LoadBalancer.find(name)
        if lb is None:
            raise storage.InstanceNotFoundError()

        # Check if DNS is registered for rpaas ip
        # if not self._check_dns(name, domain):
        #     raise SslError('rpaas IP is not registered for this DNS name')


        # Key and CSR generated to request a certificate
        key = self._generate_key()
        csr = self._generate_csr(key, domain)

        # load plugin if get it as an arg
        if plugin.isalpha() and \
            plugin in rpaas.ssl_plugins.__all__ and \
            plugin not in ['default', '__init__']:

            try:
                p_ssl = getattr(getattr(__import__('rpaas'), 'ssl_plugins'), plugin)

                for obj_name, obj in inspect.getmembers(p_ssl):
                    if obj_name != 'BaseSSLPlugin' and \
                    inspect.isclass(obj) and \
                    issubclass(obj, rpaas.ssl_plugins.BaseSSLPlugin):
                        c_ssl = obj

                        # TODO
                        hosts = [host.dns_name for host in lb.hosts]
                        c_ssl = obj(domain, os.environ.get('RPAAS_PLUGIN_LE_EMAIL', 'admin@'+domain), hosts)
                        # ODOT

                self.storage.store_task(name)

                # task = tasks.DownloadCertTask().delay(self.config, name, plugin, csr, key, domain)


                # TODO
                # Upload csr and get an Id
                plugin_id = c_ssl.upload_csr(csr)
                crt = c_ssl.download_crt(id=str(plugin_id))

                # Download the certificate and update nginx with it
                if crt:
                    try:
                        js_crt = json.loads(crt)
                        cert = js_crt['crt']
                        cert = cert+js_crt['chain'] if 'chain' in js_crt else cert
                        key = js_crt['key'] if 'key' in js_crt else key
                    except:
                        cert = crt

                    for host in lb.hosts:
                        self.update_certificate(host.dns_name, cert, key)

                else:
                    raise Exception('Could not download certificate')
                # ODOT


                self.storage.update_task(name, task.task_id)
                return ''

            except Exception, e:
                raise e
                raise SslError('rpaas IP is not registered for this DNS name')

        else:
            # default
            p_ssl = rpaas.ssl_plugins.default.Default()
            cert = p_ssl.download_crt(key=key)
            self.update_certificate(name, cert, key)
            return ''




class BindError(Exception):
    pass


class NotReadyError(Exception):
    pass


class ScaleError(Exception):
    pass


class RouteError(Exception):
    pass

class SslError(Exception):
    pass

class QuotaExceededError(Exception):
    def __init__(self, used, quota):
        super(QuotaExceededError, self).__init__("quota execeeded {}/{} used".format(used, quota))
