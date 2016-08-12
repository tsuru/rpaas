# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json
import os

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from hm.model.load_balancer import LoadBalancer

from rpaas import consul_manager, ssl_plugins, storage


def generate_key():
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


def generate_csr(key, domainname):
    private_key = serialization.load_pem_private_key(key, password=None,
                                                     backend=default_backend())
    csr = x509.CertificateSigningRequestBuilder().subject_name(x509.Name([
        # Provide various details about who we are.
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"BR"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"RJ"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"Rio de Janeiro"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"globo.com"),
        x509.NameAttribute(NameOID.COMMON_NAME, domainname),
    ])).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(domainname)]),
        critical=False,
    ).sign(private_key, hashes.SHA256(), default_backend())

    return csr.public_bytes(serialization.Encoding.PEM)


def generate_crt(config, name, plugin, csr, key, domain):
    lb = LoadBalancer.find(name, config)
    if lb is None:
        raise storage.InstanceNotFoundError()
    strg = storage.MongoDBStorage(config)
    consul_mngr = consul_manager.ConsulManager(config)

    crt = None

    plugin_class = ssl_plugins.get(plugin)
    if not plugin_class:
        raise Exception("Invalid plugin {}".format(plugin))
    plugin_obj = plugin_class(domain, os.environ.get('RPAAS_PLUGIN_LE_EMAIL', 'admin@'+domain),
                              name, consul_manager=consul_mngr)

    #  Upload csr and get an Id
    plugin_id = plugin_obj.upload_csr(csr)
    crt = plugin_obj.download_crt(id=str(plugin_id))

    #  Download the certificate and update nginx with it
    if crt:
        try:
            js_crt = json.loads(crt)
            cert = js_crt['crt']
            cert = cert+js_crt['chain'] if 'chain' in js_crt else cert
            key = js_crt['key'] if 'key' in js_crt else key
        except:
            cert = crt

        consul_mngr.set_certificate(name, cert, key)
        strg.store_le_certificate(name, domain)
    else:
        raise Exception('Could not download certificate')
