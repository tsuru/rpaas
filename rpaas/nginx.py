# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import time
import datetime

import requests

from hm import config


class NginxError(Exception):
    pass


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
        self.nginx_purge_path = config.get_config('NGINX_PURGE_PATH', '/purge', conf)
        self.nginx_healthcheck_path = config.get_config('NGINX_HEALTHCHECK_PATH',
                                                        '/healthcheck',
                                                        conf)
        self.config_manager = ConfigManager(conf)

    def purge_location(self, host, path):
        purge_path = self.nginx_purge_path.lstrip('/')
        purged = False
        for scheme in ['http', 'https']:
            try:
                self._admin_request(host, "{}/{}{}".format(purge_path, scheme, path))
                purged = True
            except:
                pass
        return purged

    def wait_healthcheck(self, host, timeout=30):
        t0 = datetime.datetime.now()
        healthcheck_path = self.nginx_healthcheck_path.lstrip('/')
        timeout = datetime.timedelta(seconds=timeout)
        while True:
            try:
                self._admin_request(host, healthcheck_path)
                break
            except:
                now = datetime.datetime.now()
                if now > t0 + timeout:
                    raise
                time.sleep(1)

    def _admin_request(self, host, path):
        url = "http://{}:{}/{}".format(host, self.nginx_manage_port, path)
        rsp = requests.get(url, timeout=2)
        if rsp.status_code != 200:
            raise NginxError(
                "Error trying to access admin path in nginx: {}: {}".format(url, rsp.text))
