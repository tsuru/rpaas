# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import ipaddress
import json
import requests
from networkapiclient import (Ip, Network)
from requests.auth import HTTPBasicAuth


class Dumb(object):

    def __init__(self, storage):
        self.storage = storage

    def add_acl(self, name, src, dst):
        self.storage.store_acl_network(name, src, dst)

    def remove_acl(self, name, src):
        self.storage.remove_acl_network(name, src)


class AclApiError(Exception):
    pass


class AclManager(object):

    def __init__(self, config, storage):
        self.storage = storage
        self.service_name = config.get("RPAAS_SERVICE_NAME", "rpaas")
        self.acl_api_host = config.get("ACL_API_HOST")
        self.acl_api_user = config.get("ACL_API_USER")
        self.acl_api_password = config.get("ACL_API_PASSWORD")
        self.acl_api_timeout = int(config.get("ACL_API_TIMEOUT", 30))
        self.acl_port_range_start = config.get("ACL_PORT_RANGE_START", "32768")
        self.acl_port_range_end = config.get("ACL_PORT_RANGE_END", "61000")
        self.network_api_url = config.get("NETWORK_API_URL", None)
        self.acl_auth_basic = HTTPBasicAuth(self.acl_api_user, self.acl_api_password)
        if self.network_api_url:
            self.network_api_username = config.get("NETWORK_API_USERNAME")
            self.network_api_password = config.get("NETWORK_API_PASSWORD")
            self.ip_client = Ip.Ip(self.network_api_url, self.network_api_username, self.network_api_password)
            self.network_client = Network.Network(self.network_api_url, self.network_api_username,
                                                  self.network_api_password)

    def add_acl(self, name, src, dst):
        src_network = self._get_network_from_ip(src)
        if src_network == src:
            src_network = str(ipaddress.ip_network(unicode(src_network)))
        src = str(ipaddress.ip_network(unicode(src)))
        dst = self._get_network_from_ip(dst)
        if self._check_acl_exists(name, src, dst):
            return
        request_data = self._request_data("permit", name, src, dst)
        response = self._make_request("PUT", "api/ipv4/acl/{}".format(src_network), request_data)
        try:
            response = json.loads(response)
            if not response.get("jobs"):
                raise AclApiError
        except:
            raise AclApiError("no valid json with 'jobs' returned")
        self.storage.store_acl_network(name, src, dst)

    def remove_acl(self, name, src):
        src = str(ipaddress.ip_network(unicode(src)))
        acl_data = self.storage.find_acl_network({"name": name, "acls.source": src})
        if acl_data and 'acls' in acl_data and acl_data['acls']:
            destinations = []
            for acl in acl_data['acls']:
                if src == acl['source']:
                    destinations += acl['destination']
            for dst in destinations:
                request_data = self._request_data("permit", name, src, dst)
                for env, vlan, acl_id in self._iter_on_acl_query_results(request_data):
                    response = self._make_request("DELETE", "api/ipv4/acl/{}/{}/{}".format(env, vlan, acl_id), None)
                    try:
                        response = json.loads(response)
                        if not response.get("job"):
                            raise AclApiError
                    except:
                        raise AclApiError("no valid json with 'job' returned")
            self.storage.remove_acl_network(name, src)

    def _check_acl_exists(self, name, src, dst):
        acl_data = self.storage.find_acl_network({"name": name, "acls.source": src})
        if acl_data and 'acls' in acl_data and acl_data['acls']:
            for acl in acl_data['acls']:
                if src == acl['source'] and dst in acl['destination']:
                    return True
        return False

    def _iter_on_acl_query_results(self, request_data):
        response = self._make_request("POST", "api/ipv4/acl/search", request_data)
        query_results = json.loads(response)
        for environment in query_results.get('envs', []):
            for vlan in environment.get('vlans', []):
                environment_id = vlan['environment']
                vlan_id = vlan['num_vlan']
                for rule in vlan.get('rules', []):
                    rule_id = rule['id']
                    yield environment_id, vlan_id, rule_id

    def _request_data(self, action, name, src, dst):
        description = "{} {} rpaas access for {} instance {}".format(
            action, src, self.service_name, name
        )
        data = {"kind": "object#acl", "rules": []}
        rule = {"protocol": "tcp",
                "source": src,
                "destination": dst,
                "description": description,
                "action": action,
                "l4-options": {"dest-port-start": self.acl_port_range_start,
                               "dest-port-end": self.acl_port_range_end,
                               "dest-port-op": "range"}
                }
        data['rules'].append(rule)
        return data

    def _make_request(self, method, path, data):
        params = {}
        url = "{}/{}".format(self.acl_api_host, path)
        if data:
            params['json'] = data
        rsp = requests.request(method.lower(), url, timeout=self.acl_api_timeout,
                               auth=self.acl_auth_basic, **params)
        if rsp.status_code not in [200, 201]:
            raise AclApiError(
                "Error applying ACL: {}: {}".format(url, rsp.text))
        return rsp.text

    def _get_network_from_ip(self, ip):
        if not self.network_api_url:
            return ip
        ips = self.ip_client.get_ipv4_or_ipv6(ip)
        ips = ips['ips']
        if not isinstance(ips, list):
            ips = [ips]
        net_ip = ips[0]
        network = self.network_client.get_network_ipv4(net_ip['networkipv4'])
        network = network['network']
        return str(ipaddress.ip_network(unicode("{}/{}".format(ip, network['block'])), strict=False))
