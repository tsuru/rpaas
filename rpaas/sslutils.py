# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json
import os
import datetime
import ipaddress
import base64

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from hm.model.load_balancer import LoadBalancer


from rpaas import consul_manager, ssl_plugins, storage


def generate_session_ticket(length=48):
    return base64.b64encode(os.urandom(length))


def generate_key(serialized=False):
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    if serialized:
        return key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    return key


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


def generate_admin_crt(config, host):
    private_key = generate_key()
    public_key = private_key.public_key()
    one_day = datetime.timedelta(1, 0, 0)
    ca_cert = config.get("CA_CERT", None)
    ca_key = config.get("CA_KEY", None)
    cert_expiration = config.get("CERT_ADMIN_EXPIRE", 1825)
    if not ca_cert or not ca_key:
        raise Exception('CA_CERT or CA_KEY not defined')
    ca_key = serialization.load_pem_private_key(str(ca_key), password=None, backend=default_backend())
    ca_cert = x509.load_pem_x509_certificate(str(ca_cert), backend=default_backend())
    builder = x509.CertificateBuilder()
    builder = builder.subject_name(x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, host),
    ]))
    builder = builder.issuer_name(ca_cert.subject)
    builder = builder.not_valid_before(datetime.datetime.today() - one_day)
    builder = builder.not_valid_after(datetime.datetime.today() + datetime.timedelta(days=cert_expiration))
    builder = builder.serial_number(x509.random_serial_number())
    builder = builder.public_key(public_key)
    builder = builder.add_extension(
        x509.SubjectAlternativeName(
            [x509.IPAddress(ipaddress.IPv4Address(host))]
        ),
        critical=False
    )
    builder = builder.add_extension(
        x509.BasicConstraints(ca=False, path_length=None), critical=True,
    )
    certificate = builder.sign(
        private_key=ca_key, algorithm=hashes.SHA256(),
        backend=default_backend()
    )
    private_key = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    certificate = certificate.public_bytes(serialization.Encoding.PEM)
    return private_key, certificate
