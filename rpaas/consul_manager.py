# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import consul
import os

from . import nginx

ACL_TEMPLATE = """key "{service_name}/{instance_name}" {{
    policy = "read"
}}

key "{service_name}/{instance_name}/status" {{
    policy = "write"
}}

service "nginx" {{
    policy = "write"
}}
"""


class ConsulManager(object):

    def __init__(self, config):
        host = config.get("CONSUL_HOST")
        port = int(config.get("CONSUL_PORT", "8500"))
        token = config.get("CONSUL_TOKEN")
        self.client = consul.Consul(host=host, port=port, token=token)
        self.config_manager = nginx.ConfigManager(config)
        self.service_name = config.get("RPAAS_SERVICE_NAME", "rpaas")

    def generate_token(self, instance_name):
        rules = ACL_TEMPLATE.format(service_name=self.service_name,
                                    instance_name=instance_name)
        acl_name = "{}/{}/token".format(self.service_name, instance_name)
        return self.client.acl.create(name=acl_name, rules=rules)

    def destroy_token(self, acl_id):
        self.client.acl.destroy(acl_id)

    def destroy_instance(self, instance_name):
        self.client.kv.delete(self._key(instance_name), recurse=True)

    def write_healthcheck(self, instance_name):
        self.client.kv.put(self._key(instance_name, "healthcheck"), "true")

    def remove_healthcheck(self, instance_name):
        self.client.kv.delete(self._key(instance_name, "healthcheck"))

    def service_healthcheck(self):
        _, instances = self.client.health.service("nginx", tag=self.service_name)
        return instances

    def list_node(self):
        _, nodes = self.client.catalog.nodes()
        return nodes

    def remove_node(self, instance_name, server_name, host_id):
        self.client.kv.delete(self._server_status_key(instance_name, server_name))
        self.client.kv.delete(self._ssl_cert_path(instance_name, "", host_id), recurse=True)
        self.client.agent.force_leave(server_name)

    def node_hostname(self, host):
        for node in self.list_node():
            if node['Address'] == host:
                return node['Node']
        return None

    def node_status(self, instance_name):
        node_status = self.client.kv.get(self._server_status_key(instance_name), recurse=True)
        node_status_list = {}
        if node_status is not None:
            for node in node_status[1]:
                node_server_name = node['Key'].split('/')[-1]
                node_status_list[node_server_name] = node['Value']
        return node_status_list

    def write_location(self, instance_name, path, destination=None, content=None):
        if content:
            content = content.strip()
        else:
            content = self.config_manager.generate_host_config(path, destination)
        self.client.kv.put(self._location_key(instance_name, path), content)

    def remove_location(self, instance_name, path):
        self.client.kv.delete(self._location_key(instance_name, path))

    def write_block(self, instance_name, block_name, content):
        content = self._block_header_footer(content, block_name)
        self.client.kv.put(self._block_key(instance_name, block_name), content)

    def remove_block(self, instance_name, block_name):
        self.write_block(instance_name, block_name, None)

    def list_blocks(self, instance_name, block_name=None):
        blocks = self.client.kv.get(self._block_key(instance_name, block_name),
                                    recurse=True)
        block_list = []
        if blocks[1]:
            for block in blocks[1]:
                block_name = block['Key'].split('/')[-2]
                block_value = self._block_header_footer(block['Value'], block_name,  True)
                if not block_value:
                    continue
                block_list.append({'block_name': block_name, 'content': block_value})
        return block_list

    def _block_header_footer(self, content, block_name, remove=False):
        begin_block = "## Begin custom RpaaS {} block ##\n".format(block_name)
        end_block = "## End custom RpaaS {} block ##".format(block_name)
        if remove:
            content = content.replace(begin_block, "")
            content = content.replace(end_block, "")
            return content.strip()
        if content:
            content = begin_block + content.strip() + '\n' + end_block
        else:
            content = begin_block + end_block
        return content

    def write_lua(self, instance_name, lua_module_name, lua_module_type, content):
        content_block = self._lua_module_escope(lua_module_name, content)
        key = self._lua_key(instance_name, lua_module_name, lua_module_type)
        return self.client.kv.put(key, content_block)

    def _lua_module_escope(self, lua_module_name, content=""):
        begin_escope = "-- Begin custom RpaaS {} lua module --".format(lua_module_name)
        end_escope = "-- End custom RpaaS {} lua module --".format(lua_module_name)
        content_stripped = ""
        if content:
            content_stripped = content.strip()
        escope = "{0}\n{1}\n{2}".format(begin_escope, content_stripped, end_escope)
        return escope

    def list_lua_modules(self, instance_name):
        modules = self.client.kv.get(self._lua_key(instance_name), recurse=True)
        module_list = []
        if modules[1]:
            for module in modules[1]:
                module_name = module['Key'].split('/')[-2]
                module_value = module['Value']
                module_list.append({'module_name': module_name, 'content': module_value})
        return module_list

    def remove_lua(self, instance_name, lua_module_name, lua_module_type):
        self.write_lua(instance_name, lua_module_name, lua_module_type, None)

    def get_certificate(self, instance_name, host_id=None):
        cert = self.client.kv.get(self._ssl_cert_path(instance_name, "cert", host_id))[1]
        key = self.client.kv.get(self._ssl_cert_path(instance_name, "key", host_id))[1]
        if not cert or not key:
            raise ValueError("certificate not defined")
        return cert["Value"], key["Value"]

    def set_certificate(self, instance_name, cert_data, key_data, host_id=None):
        self.client.kv.put(self._ssl_cert_path(instance_name, "cert", host_id),
                           cert_data.replace("\r\n", "\n"))
        self.client.kv.put(self._ssl_cert_path(instance_name, "key", host_id),
                           key_data.replace("\r\n", "\n"))

    def _ssl_cert_path(self, instance_name, key_type, host_id=None):
        if host_id:
            return os.path.join(self._key(instance_name, "ssl/{}".format(host_id)), key_type)
        return os.path.join(self._key(instance_name, "ssl"), key_type)

    def _location_key(self, instance_name, path):
        location_key = "ROOT"
        if path != "/":
            location_key = path.replace("/", "___")
        return self._key(instance_name, "locations/" + location_key)

    def _block_key(self, instance_name, block_name=None):
        block_key = "ROOT"
        if block_name:
            block_path_key = self._key(instance_name,
                                       "blocks/%s/%s" % (block_name,
                                                         block_key))
        else:
            block_path_key = self._key(instance_name, "blocks")
        return block_path_key

    def _server_status_key(self, instance_name, server_name=None):
        if server_name:
            return self._key(instance_name, "status/%s" % server_name)
        return self._key(instance_name, "status")

    def _lua_key(self, instance_name, lua_module_name="", lua_module_type=""):
        base_key = "lua_module"
        if lua_module_name and lua_module_type:
            base_key = "lua_module/{0}/{1}".format(lua_module_type, lua_module_name)
        return self._key(instance_name, base_key)

    def _key(self, instance_name, suffix=None):
        key = "{}/{}".format(self.service_name, instance_name)
        if suffix:
            key += "/" + suffix
        return key
