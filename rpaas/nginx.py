# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import requests

from hm import config


class NginxError(Exception):
    pass


class NginxDAV(object):
    def __init__(self, conf=None):
        self.nginx_reload_path = config.get_config('NGINX_RELOAD_PATH', '/reload', conf)
        self.nginx_manage_port = config.get_config('NGINX_MANAGE_PORT', '8089', conf)
        self.nginx_dav_put_path = config.get_config('NGINX_DAV_PUT_PATH', '/dav', conf)
        self.nginx_location_template = self._load_location_template(conf)

    def update_binding(self, host, path, destination):
        content = self._generate_host_config(path, destination)
        self._put(host, self._location_file_name(path), content)
        self._reload(host)

    def update_certificate(self, host, cert_data, key_data):
        self._put(host, 'ssl/nginx.crt', cert_data)
        self._put(host, 'ssl/nginx.key', key_data)
        self._reload(host)

    def delete_binding(self, host, path):
        self._delete(host, self._location_file_name(path))

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
    proxy_pass http://{host}:80;
}}
"""

    def _generate_host_config(self, path, destination):
        return self.nginx_location_template.format(
            path=path,
            host=destination,
        )

    def _request(self, method, host, name, content):
        path = "/{}/{}".format(self.nginx_dav_put_path.strip('/'), name)
        url = "http://{}:{}{}".format(host, self.nginx_manage_port, path)
        rsp = requests.request(method, url, data=content)
        if rsp.status_code > 299:
            raise NginxError("Error trying to update file in nginx: {} {}: {}".format(method, url, rsp.text))
        return rsp

    def _put(self, host, name, content):
        return self._request('PUT', host, name, content)

    def _delete(self, host, name):
        return self._request('DELETE', host, name, None)

    def _reload(self, host):
        url = "http://{}:{}/{}".format(host, self.nginx_manage_port, self.nginx_reload_path.lstrip('/'))
        rsp = requests.get(url)
        if rsp.status_code > 299:
            raise NginxError("Error trying to reload config in nginx: {}: {}".format(url, rsp.text))
