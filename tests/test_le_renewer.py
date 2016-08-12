# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime
import mock
import time
import unittest

import redis

from rpaas import storage, tasks
from rpaas.ssl_plugins import le_renewer

tasks.app.conf.CELERY_ALWAYS_EAGER = True


class LeRenewerTestCase(unittest.TestCase):

    def setUp(self):
        self.config = {
            "MONGO_DATABASE": "le_renewer_test",
            "RPAAS_SERVICE_NAME": "test_rpaas_renewer",
            "LE_RENEWER_RUN_INTERVAL": 2,
        }
        self.storage = storage.MongoDBStorage(self.config)
        colls = self.storage.db.collection_names(False)
        for coll in colls:
            self.storage.db.drop_collection(coll)

        now = datetime.datetime.utcnow()
        certs = [
            {"_id": "instance0", "domain": "i0.tsuru.io",
             "created": now - datetime.timedelta(days=88)},
            {"_id": "instance1", "domain": "i1.tsuru.io",
             "created": now - datetime.timedelta(days=89)},
            {"_id": "instance2", "domain": "i2.tsuru.io",
             "created": now},
            {"_id": "instance3", "domain": "i3.tsuru.io",
             "created": now - datetime.timedelta(days=30)},
            {"_id": "instance4", "domain": "i4.tsuru.io",
             "created": now - datetime.timedelta(days=90)},
            {"_id": "instance5", "domain": "i5.tsuru.io",
             "created": now - datetime.timedelta(days=365)},
            {"_id": "instance6", "domain": "i6.tsuru.io",
             "created": now - datetime.timedelta(days=87)},
            {"_id": "instance7", "domain": "i7.tsuru.io",
             "created": now - datetime.timedelta(days=86)},
        ]
        for cert in certs:
            self.storage.db[self.storage.le_certificates_collection].insert(cert)
        redis.StrictRedis().delete("le_renewer:last_run")

    def tearDown(self):
        self.storage.db[self.storage.le_certificates_collection].remove()

    @mock.patch("rpaas.ssl.generate_crt")
    @mock.patch("rpaas.ssl.generate_csr")
    @mock.patch("rpaas.ssl.generate_key")
    def test_renew_certificates(self, generate_key, generate_csr, generate_crt):
        generate_key.return_value = "secret-key"
        generate_csr.return_value = "domain-csr"
        renewer = le_renewer.LeRenewer(self.config)
        renewer.start()
        time.sleep(1)
        renewer.stop()
        self.assertEqual([mock.call()] * 5, generate_key.mock_calls)
        expected_csr_calls = [mock.call("secret-key", "i0.tsuru.io"),
                              mock.call("secret-key", "i1.tsuru.io"),
                              mock.call("secret-key", "i4.tsuru.io"),
                              mock.call("secret-key", "i5.tsuru.io"),
                              mock.call("secret-key", "i6.tsuru.io")]
        self.assertEqual(expected_csr_calls, generate_csr.mock_calls)
        expected_crt_calls = [mock.call(self.config, "instance0", "le", "domain-csr",
                                        "secret-key", "i0.tsuru.io"),
                              mock.call(self.config, "instance1", "le", "domain-csr",
                                        "secret-key", "i1.tsuru.io"),
                              mock.call(self.config, "instance4", "le", "domain-csr",
                                        "secret-key", "i4.tsuru.io"),
                              mock.call(self.config, "instance5", "le", "domain-csr",
                                        "secret-key", "i5.tsuru.io"),
                              mock.call(self.config, "instance6", "le", "domain-csr",
                                        "secret-key", "i6.tsuru.io")]
        self.assertEqual(expected_crt_calls, generate_crt.mock_calls)
