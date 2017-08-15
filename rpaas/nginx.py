# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import time
import datetime
import os

import requests

from hm import config


class NginxError(Exception):
    pass


def retry_request(f):
    def f_retry(self, *args, **kwargs):
        timeout = kwargs.get("timeout")
        if not timeout:
            timeout = 30
        t0 = datetime.datetime.now()
        timeout = datetime.timedelta(seconds=timeout)
        while True:
            try:
                f(self, *args, **kwargs)
                break
            except:
                now = datetime.datetime.now()
            if now > t0 + timeout:
                raise
            time.sleep(1)
    return f_retry


class ConfigManager(object):

    def __init__(self, conf=None):
        self.location_template = self._load_location_template(conf)

    def generate_host_config(self, path, destination):
        return self.location_template.format(
            path=path.rstrip('/') + '/',
            host=destination,
        )

    def _load_location_template(self, conf):
        template_txt = config.get_config('NGINX_LOCATION_TEMPLATE_TXT', None, conf)
        if template_txt:
            return template_txt
        template_url = config.get_config('NGINX_LOCATION_TEMPLATE_URL', None, conf)
        if template_url:
            rsp = requests.get(template_url)
            if rsp.status_code > 299:
                raise NginxError("Error trying to load location template: {} - {}".
                                 format(rsp.status_code, rsp.text))
            return rsp.text
        return """
location {path} {{
    proxy_set_header Host {host};
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_pass http://{host}:80/;
    proxy_redirect ~^http://{host}(:\d+)?/(.*)$ {path}$2;
}}
"""


class Nginx(object):

    def __init__(self, conf=None):
        self.nginx_manage_port = config.get_config('NGINX_MANAGE_PORT', '8089', conf)
        self.nginx_manage_port_tls = config.get_config('NGINX_MANAGE_PORT_TLS', '8090', conf)
        self.nginx_purge_path = config.get_config('NGINX_PURGE_PATH', '/purge', conf)
        self.nginx_expected_healthcheck = config.get_config('NGINX_HEALTHECK_EXPECTED',
                                                            'WORKING', conf)
        self.nginx_healthcheck_path = config.get_config('NGINX_HEALTHCHECK_PATH',
                                                        '/healthcheck', conf)
        self.nginx_healthcheck_app_path = config.get_config('NGINX_HEALTHCHECK_APP_PATH',
                                                            '/_nginx_healthcheck/', conf)
        self.nginx_app_port = config.get_config('NGINX_APP_PORT', '8080', conf)
        self.nginx_app_expected_healthcheck = config.get_config('NGINX_HEALTHECK_APP_EXPECTED',
                                                                'WORKING', conf)
        self.ca_cert = config.get_config('CA_CERT', None, conf)
        self.ca_path = "/tmp/rpaas_ca.pem"
        self.config_manager = ConfigManager(conf)

    def purge_location(self, host, path, preserve_path=False):
        purge_path = self.nginx_purge_path.lstrip('/')
        purged = False
        if preserve_path:
            for encoding in ['gzip', 'identity']:
                try:
                    self._nginx_request(host, "{}/{}".format(purge_path, path),
                                        {'Accept-Encoding': encoding})
                    purged = True
                except:
                    pass
            return purged
        for scheme in ['http', 'https']:
            for encoding in ['gzip', 'identity']:
                try:
                    self._nginx_request(host, "{}/{}{}".format(purge_path, scheme, path),
                                        {'Accept-Encoding': encoding})
                    purged = True
                except:
                    pass
        return purged

    @retry_request
    def wait_healthcheck(self, host, timeout=30, manage_healthcheck=True):
        if manage_healthcheck:
            healthcheck_path = self.nginx_healthcheck_path.lstrip('/')
            expected_response = self.nginx_expected_healthcheck
            port = self.nginx_manage_port
        else:
            healthcheck_path = self.nginx_healthcheck_app_path.lstrip('/')
            expected_response = self.nginx_app_expected_healthcheck
            port = self.nginx_app_port
        self._nginx_request(host, healthcheck_path, port=port, expected_response=expected_response)

    @retry_request
    def add_session_ticket(self, host, data, timeout=30):
        self._nginx_request(host, 'session_ticket', data=data, method='POST', secure=True,
                            expected_response='ticket was succsessfully added')

    def _nginx_request(self, host, path, headers=None, port=None,
                       expected_response=None, secure=False, method='GET', data=None):
        params = {}
        if secure:
            if not port:
                port = self.nginx_manage_port_tls
            protocol = 'https'
            self._ensure_ca_cert_file()
            params['verify'] = self.ca_path
        else:
            if not port:
                port = self.nginx_manage_port
            protocol = 'http'
        url = "{}://{}:{}/{}".format(protocol, host, port, path)
        if method not in ['POST', 'PUT', 'GET']:
            raise NginxError("Unsupported method {}".format(method))
        if headers:
            params['headers'] = headers
        if data:
            params['data'] = data
        rsp = requests.request(method.lower(), url, timeout=2, **params)
        if rsp.status_code != 200 or (expected_response and expected_response not in rsp.text):
            raise NginxError(
                "Error trying to access admin path in nginx: {}: {}".format(url, rsp.text))

    def _ensure_ca_cert_file(self):
        if not self.ca_cert:
            raise NginxError("CA_CERT should be set for nginx https internal requests")
        if not os.path.exists(self.ca_path):
            with open(self.ca_path, "w") as ca_file:
                ca_file.write(self.ca_cert)
