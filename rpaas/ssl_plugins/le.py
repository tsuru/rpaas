#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import json
import OpenSSL

from letsencrypt.client import Client, register
from letsencrypt.configuration import NamespaceConfig
from letsencrypt.account import AccountMemoryStorage
from letsencrypt import crypto_util

import zope.component

from rpaas.ssl_plugins import BaseSSLPlugin
import rpaas
from le_authenticator import RpaasLeAuthenticator

logger = logging.getLogger(__name__)


class LE(BaseSSLPlugin):

    def __init__(self, domain, email, hosts=[]):
        self.domain = domain
        self.email = email
        self.hosts = [str(x) for x in hosts]

    def upload_csr(self, csr=None):
        return None

    def download_crt(self, id=None):
        try:
            crt, chain, key = main([self.domain], self.email, self.hosts)
        except Exception, e:
            raise e
        else:
            return json.dumps({'crt': crt, 'chain': chain, 'key': key})
        finally:
            nginx_manager = rpaas.get_manager().nginx_manager
            for host in self.hosts:
                nginx_manager.delete_acme_conf(host)


class ConfigNamespace(object):
    def __init__(self):
        self.server = 'https://acme-staging.api.letsencrypt.org/directory'
        self.config_dir = './le/conf'
        self.work_dir = './le/work'
        self.http01_port = None
        self.tls_sni_01_port = 5001
        self.email = 'vicente.fiebig@corp.globo.com'
        self.rsa_key_size = 2048
        self.no_verify_ssl = False
        self.key_dir = './le/key'
        self.accounts_dir = './le/account'
        self.backup_dir = './le/bkp'
        self.csr_dir = './le/csr'
        self.in_progress_dir = './le/progress'
        self.temp_checkpoint_dir = './le/tmp'
        self.renewer_config_file = './le/renew'
        self.strict_permissions = False


def main(domains=[], email=None, hosts=[]):
    ns = ConfigNamespace()
    config = NamespaceConfig(ns)
    zope.component.provideUtility(config)

    ams = AccountMemoryStorage()
    acc, acme = register(config, ams)
    
    authenticator = RpaasLeAuthenticator(hosts=hosts, config=config, name='')
    installer = None
    lec = Client(config, acc, authenticator, installer, acme)
    certr, chain, key, _ = lec.obtain_certificate(domains)
    return (
            OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, certr.body),
            crypto_util.dump_pyopenssl_chain(chain),
            key.pem
        )
