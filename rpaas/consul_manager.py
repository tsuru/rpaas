# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os

import consul

from . import nginx

ACL_TEMPLATE = """key "{service_name}/{instance_name}" {{
    policy = "read"
}}

key "{service_name}/{instance_name}/error" {{
    policy = "write"
}}

service "nginx" {{
    policy = "write"
}}
"""


class ConsulManager(object):

    def __init__(self, conf=None):
        host = os.environ.get("CONSUL_HOST")
        port = int(os.environ.get("CONSUL_PORT", "8500"))
        token = os.environ.get("CONSUL_TOKEN")
        self.client = consul.Consul(host=host, port=port, token=token)
        self.config_manager = nginx.ConfigManager(conf)
        self.service_name = os.environ.get("RPAAS_SERVICE_NAME", "rpaas")

    def generate_token(self, instance_name):
        rules = ACL_TEMPLATE.format(service_name=self.service_name,
                                    instance_name=instance_name)
        acl_name = "{}/{}/token".format(self.service_name, instance_name)
        return self.client.acl.create(name=acl_name, rules=rules)

    def destroy_token(self, acl_id):
        self.client.acl.destroy(acl_id)

    def write_healthcheck(self, instance_name):
        self.client.kv.put(self._key(instance_name, "healthcheck"), "true")

    def write_location(self, instance_name, path, destination=None, content=None):
        if not content:
            content = self.config_manager.generate_host_config(path, destination)
        self.client.kv.put(self._location_key(instance_name, path), content)

    def set_certificate(self, instance_name, cert_data, key_data):
        self.client.kv.put(self._ssl_cert_key(instance_name), cert_data)
        self.client.kv.put(self._ssl_key_key(instance_name), key_data)

    def remove_location(self, instance_name, path):
        self.client.kv.delete(self._location_key(instance_name, path))

    def _ssl_cert_key(self, instance_name):
        return self._key(instance_name, "ssl/cert")

    def _ssl_key_key(self, instance_name):
        return self._key(instance_name, "ssl/key")

    def _location_key(self, instance_name, path):
        location_key = "ROOT"
        if path != "/":
            location_key = path.replace("/", "___")
        return self._key(instance_name, "locations/" + location_key)

    def _key(self, instance_name, suffix):
        return "{}/{}/{}".format(self.service_name, instance_name, suffix)
