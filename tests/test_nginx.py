import unittest

import mock

from rpaas.nginx import NginxDAV, NginxError


class NginxDAVTestCase(unittest.TestCase):

    def setUp(self):
        self.intance = NginxDAV()

    def test_init_default(self):
        nginx = NginxDAV()
        self.assertEqual(nginx.nginx_reload_path, '/reload')
        self.assertEqual(nginx.nginx_dav_put_path, '/dav')
        self.assertEqual(nginx.nginx_manage_port, '8080')
        self.assertEqual(nginx.nginx_tsuru_upstream, 'tsuru_backend')

    def test_init_config(self):
        nginx = NginxDAV({
            'NGINX_RELOAD_PATH': '/1',
            'NGINX_DAV_PUT_PATH': '/2',
            'NGINX_TSURU_UPSTREAM': '3',
            'NGINX_PORT': '4',
        })
        self.assertEqual(nginx.nginx_reload_path, '/1')
        self.assertEqual(nginx.nginx_dav_put_path, '/2')
        self.assertEqual(nginx.nginx_tsuru_upstream, '3')
        self.assertEqual(nginx.nginx_manage_port, '4')

    @mock.patch('rpaas.nginx.requests')
    def test_update_binding(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 200
        rsp_get = requests.get.return_value
        rsp_get.status_code = 200

        nginx = NginxDAV()

        nginx.update_binding('myhost', 'mydestination')
        requests.request.assert_called_once_with('PUT', 'http://myhost:8080/dav/base_location.conf', data="""
location / {
    add_header Host mydestination;
    proxy_pass http://tsuru_backend;
}
""")
        requests.get.assert_called_once_with('http://myhost:8080/reload')

    @mock.patch('rpaas.nginx.requests')
    def test_update_binding_error_put(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 500
        rsp.body = "my error"

        nginx = NginxDAV()
        with self.assertRaises(NginxError) as context:
            nginx.update_binding('myhost', 'mydestination')
        self.assertEqual(str(context.exception), "Error trying to update config in nginx: my error")

    @mock.patch('rpaas.nginx.requests')
    def test_update_binding_error_reload(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 200
        rsp_get = requests.get.return_value
        rsp_get.status_code = 500
        rsp_get.body = "my error"

        nginx = NginxDAV()
        with self.assertRaises(NginxError) as context:
            nginx.update_binding('myhost', 'mydestination')
        self.assertEqual(str(context.exception), "Error trying to reload config in nginx: my error")
        requests.request.assert_called_once_with('PUT', 'http://myhost:8080/dav/base_location.conf', data="""
location / {
    add_header Host mydestination;
    proxy_pass http://tsuru_backend;
}
""")
