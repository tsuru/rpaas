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
        self.nginx_tsuru_upstream = config.get_config('NGINX_TSURU_UPSTREAM', 'tsuru_backend', conf)
        self.nginx_dav_put_path = config.get_config('NGINX_DAV_PUT_PATH', '/dav', conf)
        self.nginx_location_template = self.load_location_template(conf)

    def load_location_template(self, conf):
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
    proxy_pass http://{upstream};
}}
"""

    def update_binding(self, host, path, destination):
        content = self._generate_host_config(path, destination)
        self._put(host, 'location_{}.conf'.format(path.replace('/', ':')), content)
        self._reload(host)

    def _generate_host_config(self, path, destination):
        return self.nginx_location_template.format(
            path=path,
            host=destination,
            upstream=self.nginx_tsuru_upstream,
        )

    def _put(self, host, name, content):
        path = "/{}/{}".format(self.nginx_dav_put_path.strip('/'), name)
        url = "http://{}:{}{}".format(host, self.nginx_manage_port, path)
        rsp = requests.request('PUT', url, data=content)
        if rsp.status_code > 299:
            raise NginxError("Error trying to update config in nginx: {}".format(rsp.text))

    def _reload(self, host):
        url = "http://{}:{}/{}".format(host, self.nginx_manage_port, self.nginx_reload_path.lstrip('/'))
        rsp = requests.get(url)
        if rsp.status_code > 299:
            raise NginxError("Error trying to reload config in nginx: {}".format(rsp.text))
