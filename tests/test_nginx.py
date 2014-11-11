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
        self.assertEqual(nginx.nginx_manage_port, '8089')
        self.assertEqual(nginx.nginx_healthcheck_path, '/healthcheck')
        self.assertEqual(nginx.nginx_location_template, """
location {path} {{
    proxy_set_header Host {host};
    proxy_pass http://{host}:80/;
}}
""")

    def test_init_config(self):
        nginx = NginxDAV({
            'NGINX_RELOAD_PATH': '/1',
            'NGINX_DAV_PUT_PATH': '/2',
            'NGINX_MANAGE_PORT': '4',
            'NGINX_LOCATION_TEMPLATE_TXT': '5',
            'NGINX_HEALTHCHECK_PATH': '6',
        })
        self.assertEqual(nginx.nginx_reload_path, '/1')
        self.assertEqual(nginx.nginx_dav_put_path, '/2')
        self.assertEqual(nginx.nginx_manage_port, '4')
        self.assertEqual(nginx.nginx_location_template, '5')
        self.assertEqual(nginx.nginx_healthcheck_path, '6')

    @mock.patch('rpaas.nginx.requests')
    def test_init_config_location_url(self, requests):
        rsp_get = requests.get.return_value
        rsp_get.status_code = 200
        rsp_get.text = 'my result'
        nginx = NginxDAV({
            'NGINX_LOCATION_TEMPLATE_URL': 'http://my.com/x',
        })
        self.assertEqual(nginx.nginx_location_template, 'my result')
        requests.get.assert_called_once_with('http://my.com/x')

    @mock.patch('rpaas.nginx.requests')
    def test_update_binding(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 200
        rsp_get = requests.get.return_value
        rsp_get.status_code = 200

        nginx = NginxDAV()

        nginx.update_binding('myhost', '/', 'mydestination')
        requests.request.assert_called_once_with('PUT', 'http://myhost:8089/dav/location_:.conf', data="""
location / {
    proxy_set_header Host mydestination;
    proxy_pass http://mydestination:80/;
}
""")
        requests.get.assert_called_once_with('http://myhost:8089/reload')

    @mock.patch('rpaas.nginx.requests')
    def test_update_binding_other_path(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 200
        rsp_get = requests.get.return_value
        rsp_get.status_code = 200

        nginx = NginxDAV()

        nginx.update_binding('myhost', '/app/route', 'mydestination')
        requests.request.assert_called_once_with('PUT', 'http://myhost:8089/dav/location_:app:route.conf', data="""
location /app/route/ {
    proxy_set_header Host mydestination;
    proxy_pass http://mydestination:80/;
}
""")
        requests.get.assert_called_once_with('http://myhost:8089/reload')

    @mock.patch('rpaas.nginx.requests')
    def test_update_binding_error_put(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 500
        rsp.text = "my error"

        nginx = NginxDAV()
        with self.assertRaises(NginxError) as context:
            nginx.update_binding('myhost', '/', 'mydestination')
        self.assertEqual(
            str(context.exception),
            "Error trying to update file in nginx: PUT http://myhost:8089/dav/location_:.conf: my error")

    @mock.patch('rpaas.nginx.requests')
    def test_update_binding_error_reload(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 200
        rsp_get = requests.get.return_value
        rsp_get.status_code = 500
        rsp_get.text = "my error"

        nginx = NginxDAV()
        with self.assertRaises(NginxError) as context:
            nginx.update_binding('myhost', '/', 'mydestination')
        self.assertEqual(
            str(context.exception),
            "Error trying to reload config in nginx: http://myhost:8089/reload: my error")
        requests.request.assert_called_once_with('PUT', 'http://myhost:8089/dav/location_:.conf', data="""
location / {
    proxy_set_header Host mydestination;
    proxy_pass http://mydestination:80/;
}
""")

    @mock.patch('rpaas.nginx.requests')
    def test_update_certificate(self, requests):
        rsp = requests.request.return_value
        rsp.status_code = 200
        rsp_get = requests.get.return_value
        rsp_get.status_code = 200

        nginx = NginxDAV()
        nginx.update_certificate('myhost', 'cert', 'key')

        requests.request.assert_has_call('PUT', 'http://myhost:8089/dav/ssl/nginx.crt', data='cert')
        requests.request.assert_has_call('PUT', 'http://myhost:8089/dav/ssl/nginx.key', data='key')
        requests.get.assert_called_once_with('http://myhost:8089/reload')

    @mock.patch('rpaas.nginx.requests')
    def test_wait_healthcheck(self, requests):
        nginx = NginxDAV()
        count = [0]
        response = mock.Mock()
        response.status_code = 200
        response.text = 'WORKING'

        def side_effect(url, timeout):
            count[0] += 1
            if count[0] < 2:
                raise Exception('some error')
            return response

        requests.get.side_effect = side_effect
        nginx.wait_healthcheck('myhost.com', timeout=5)
        self.assertEqual(requests.get.call_count, 2)
        requests.get.assert_has_call('http://myhost.com:8089/healthcheck', timeout=2)

    @mock.patch('rpaas.nginx.requests')
    def test_wait_healthcheck_timeout(self, requests):
        nginx = NginxDAV()

        def side_effect(url, timeout):
            raise Exception('some error')

        requests.get.side_effect = side_effect
        with self.assertRaises(Exception):
            nginx.wait_healthcheck('myhost.com', timeout=2)
        self.assertGreaterEqual(requests.get.call_count, 2)
        requests.get.assert_has_call('http://myhost.com:8089/healthcheck', timeout=2)
