# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime
import time
import unittest
import redis
import consul

from freezegun import freeze_time
from mock import patch, call
from rpaas import storage, tasks
from rpaas import session_resumption, consul_manager
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class LoadBalancerFake(object):

    def __init__(self, name):
        self.name = name
        self.hosts = []


class HostFake(object):

    def __init__(self, id, group, dns_name):
        self.id = id
        self.group = group
        self.dns_name = dns_name
        self.fail_property = None

    def set_fail(self, name):
        self.fail_property = name

    def unset_fail(self, name):
        self.fail_property = None

    def __getattribute__(self, name):
        fail_property = object.__getattribute__(self, "fail_property")
        if fail_property and fail_property == name:
            raise AttributeError("{} not defined".format(name))
        return object.__getattribute__(self, name)


@freeze_time("2016-02-03 12:00:00")
class SessionResumptionTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ca_key, cls.ca_cert = cls.generate_ca()

    @classmethod
    def generate_ca(cls):
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, u"BR"),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"RJ"),
            x509.NameAttribute(NameOID.LOCALITY_NAME, u"Rio de Janeiro"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"Tsuru Inc"),
            x509.NameAttribute(NameOID.COMMON_NAME, u"tsuru.io"),
        ])
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=10)
        ).add_extension(
            x509.SubjectAlternativeName([x509.DNSName(u"tsuru.io")]),
            critical=False,
        ).sign(key, hashes.SHA256(), default_backend())

        key = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        cert = cert.public_bytes(serialization.Encoding.PEM)
        return key, cert

    def setUp(self):
        self.master_token = "rpaas-test"
        self.config = {
            "CONSUL_HOST": "127.0.0.1",
            "CONSUL_TOKEN": self.master_token,
            "MONGO_DATABASE": "session_resumption_test",
            "RPAAS_SERVICE_NAME": "test_rpaas_session_resumption",
            "HOST_MANAGER": "fake",
            "SESSION_RESUMPTION_RUN_INTERVAL": 2,
            "CA_CERT": self.ca_cert,
            "CA_KEY": self.ca_key
        }
        self.consul = consul.Consul(token=self.master_token)
        self.consul.kv.delete("test_rpaas_session_resumption", recurse=True)
        self.storage = storage.MongoDBStorage(self.config)
        self.consul_manager = consul_manager.ConsulManager(self.config)
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)
        redis.StrictRedis().flushall()

    @patch("rpaas.tasks.ssl.generate_session_ticket")
    @patch("rpaas.tasks.LoadBalancer")
    @patch("rpaas.tasks.nginx")
    def test_renew_session_tickets(self, nginx, load_balancer, ticket):
        nginx_manager = nginx.Nginx.return_value
        lb1 = LoadBalancerFake("instance-a")
        lb2 = LoadBalancerFake("instance-b")
        lb1.hosts = [HostFake("xxx", "instance-a", "10.1.1.1"), HostFake("yyy", "instance-a", "10.1.1.2")]
        lb2.hosts = [HostFake("aaa", "instance-b", "10.2.2.2"), HostFake("bbb", "instance-b", "10.2.2.3")]
        load_balancer.list.return_value = [lb1, lb2]
        ticket.side_effect = ["ticket1", "ticket2", "ticket3", "ticket4"]
        session = session_resumption.SessionResumption(self.config)
        session.start()
        time.sleep(1)
        session.stop()
        nginx_expected_calls = [call('10.1.1.1', 'ticket1'), call('10.1.1.2', 'ticket1'),
                                call('10.2.2.2', 'ticket2'), call('10.2.2.3', 'ticket2')]
        self.assertEqual(nginx_expected_calls, nginx_manager.add_session_ticket.call_args_list)
        cert_a, key_a = self.consul_manager.get_certificate("instance-a", "xxx")
        cert_b, key_b = self.consul_manager.get_certificate("instance-b", "bbb")
        redis.StrictRedis().delete("session_resumption:last_run")
        redis.StrictRedis().delete("session_resumption:instance:instance-a")
        nginx_manager.reset_mock()
        session = session_resumption.SessionResumption(self.config)
        session.start()
        time.sleep(1)
        session.stop()
        nginx_expected_calls = [call('10.1.1.1', 'ticket3'), call('10.1.1.2', 'ticket3')]
        self.assertEqual(nginx_expected_calls, nginx_manager.add_session_ticket.call_args_list)
        self.assertTupleEqual((cert_a, key_a), self.consul_manager.get_certificate("instance-a", "xxx"))
        self.assertTupleEqual((cert_b, key_b), self.consul_manager.get_certificate("instance-b", "bbb"))

    @patch("rpaas.tasks.ssl.generate_session_ticket")
    @patch("rpaas.tasks.LoadBalancer")
    @patch("rpaas.tasks.nginx")
    def test_renew_session_tickets_fail_and_unlock(self, nginx, load_balancer, ticket):
        nginx_manager = nginx.Nginx.return_value
        lb1_host2 = HostFake("yyy", "instance-a", "10.1.1.2")
        lb1_host2.set_fail("dns_name")
        lb1 = LoadBalancerFake("instance-a")
        lb2 = LoadBalancerFake("instance-b")
        lb1.hosts = [HostFake("xxx", "instance-a", "10.1.1.1"), lb1_host2]
        lb2.hosts = [HostFake("aaa", "instance-b", "10.2.2.2"), HostFake("bbb", "instance-b", "10.2.2.3")]
        load_balancer.list.return_value = [lb1, lb2]
        ticket.side_effect = ["ticket1", "ticket2", "ticket3"]
        session = session_resumption.SessionResumption(self.config)
        session.start()
        time.sleep(1)
        session.stop()
        nginx_expected_calls = [call('10.1.1.1', 'ticket1'), call('10.2.2.2', 'ticket2'),
                                call('10.2.2.3', 'ticket2')]
        self.assertEqual(nginx_expected_calls, nginx_manager.add_session_ticket.call_args_list)
        redis.StrictRedis().delete("session_resumption:last_run")
        lb1_host2.unset_fail("dns_name")
        nginx_manager.reset_mock()
        session = session_resumption.SessionResumption(self.config)
        session.start()
        time.sleep(1)
        session.stop()
        nginx_expected_calls = [call('10.1.1.1', 'ticket3'), call('10.1.1.2', 'ticket3')]
        self.assertEqual(nginx_expected_calls, nginx_manager.add_session_ticket.call_args_list)
