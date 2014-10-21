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
        self.nginx_app_port = config.get_config('NGINX_APP_PORT', '8080', conf)
        self.nginx_tsuru_upstream = config.get_config('NGINX_TSURU_UPSTREAM', 'tsuru_backend', conf)
        self.nginx_dav_put_path = config.get_config('NGINX_DAV_PUT_PATH', '/dav', conf)

    def update_binding(self, host, destination):
        conf = self._generate_host_config(destination)
        self._put(host, 'base_location.conf', conf)
        self._reload(host)

    def _generate_host_config(self, destination):
        return """
server {{
    listen {app_port};
    server_name  _tsuru_nginx_app;
    location / {{
        add_header Host {host};
        proxy_pass http://{upstream};
    }}
}}
""".format(host=destination, upstream=self.nginx_tsuru_upstream, app_port=self.nginx_app_port)

    def _put(self, host, name, content):
        path = "/{}/{}".format(self.nginx_dav_put_path.strip('/'), name)
        url = "http://{}:{}{}".format(host, self.nginx_manage_port, path)
        rsp = requests.request('PUT', url, data=content)
        if rsp.status_code > 299:
            raise NginxError("Error trying to update config in nginx: {}".format(rsp.body))

    def _reload(self, host):
        url = "http://{}:{}/{}".format(host, self.nginx_manage_port, self.nginx_reload_path.lstrip('/'))
        rsp = requests.get(url)
        if rsp.status_code > 299:
            raise NginxError("Error trying to reload config in nginx: {}".format(rsp.body))
