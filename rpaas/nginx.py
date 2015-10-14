# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import time
import datetime

import requests

from hm import config


class NginxError(Exception):
    pass


class NginxDAV(object):
    def __init__(self, conf=None):
        self.nginx_reload_path = config.get_config('NGINX_RELOAD_PATH', '/reload', conf)
        self.nginx_manage_port = config.get_config('NGINX_MANAGE_PORT', '8089', conf)
        self.nginx_dav_put_path = config.get_config('NGINX_DAV_PUT_PATH', '/dav', conf)
        self.nginx_healthcheck_path = config.get_config('NGINX_HEALTHCHECK_PATH', '/healthcheck', conf)
        self.nginx_location_template = self._load_location_template(conf)

    def update_binding(self, host, path, destination=None, content=None):
        if not content:
            content = self._generate_host_config(path, destination)
        self._dav_put(host, self._location_file_name(path), content)
        self._reload(host)

    def update_certificate(self, host, cert_data, key_data):
        self._dav_put(host, 'ssl/nginx.crt', cert_data)
        self._dav_put(host, 'ssl/nginx.key', key_data)
        self._reload(host)

    def delete_binding(self, host, path):
        self._dav_delete(host, self._location_file_name(path))
        self._reload(host)

    def wait_healthcheck(self, host, timeout=30):
        t0 = datetime.datetime.now()
        timeout = datetime.timedelta(seconds=timeout)
        while True:
            try:
                self._get_healthcheck(host)
                break
            except:
                now = datetime.datetime.now()
                if now > t0 + timeout:
                    raise
                time.sleep(1)

    def acme_conf(self, host, route, data):
        raw = '''location /.well-known/acme-challenge/'''+route+''' {
        add_header Content-Type application/jose+json;
        echo '''+data+''';
    }'''
        self._dav_put(host, 'acme.conf', raw)
        self._reload(host)

    def _location_file_name(self, path):
        return 'location_{}.conf'.format(path.replace('/', ':'))

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

    def _generate_host_config(self, path, destination):
        return self.nginx_location_template.format(
            path=path.rstrip('/') + '/',
            host=destination,
        )

    def _dav_request(self, method, host, name, content):
        path = "/{}/{}".format(self.nginx_dav_put_path.strip('/'), name)
        url = "http://{}:{}{}".format(host, self.nginx_manage_port, path)
        rsp = requests.request(method, url, data=content)
        if rsp.status_code > 299:
            raise NginxError("Error trying to update file in nginx: {} {}: {}".format(method, url, rsp.text))
        return rsp

    def _dav_put(self, host, name, content):
        return self._dav_request('PUT', host, name, content)

    def _dav_delete(self, host, name):
        return self._dav_request('DELETE', host, name, None)

    def _reload(self, host):
        url = "http://{}:{}/{}".format(host, self.nginx_manage_port, self.nginx_reload_path.lstrip('/'))
        rsp = requests.get(url)
        if rsp.status_code > 299:
            raise NginxError("Error trying to reload config in nginx: {}: {}".format(url, rsp.text))

    def _get_healthcheck(self, host):
        url = "http://{}:{}/{}".format(host, self.nginx_manage_port, self.nginx_healthcheck_path.lstrip('/'))
        rsp = requests.get(url, timeout=2)
        if rsp.status_code != 200:
            raise NginxError("Error trying to check healthcheck in nginx: {}: {}".format(url, rsp.text))
