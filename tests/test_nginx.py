# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import unittest

import mock

from rpaas.nginx import Nginx, NginxError


class NginxTestCase(unittest.TestCase):

    def setUp(self):
        self.cache_headers = [{'Accept-Encoding': 'gzip'}, {'Accept-Encoding': 'identity'}]

    def test_init_default(self):
        nginx = Nginx()
        self.assertEqual(nginx.nginx_manage_port, '8089')
        self.assertEqual(nginx.nginx_purge_path, '/purge')
        self.assertEqual(nginx.nginx_healthcheck_path, '/healthcheck')

    def test_init_config(self):
        nginx = Nginx({
            'NGINX_PURGE_PATH': '/2',
            'NGINX_MANAGE_PORT': '4',
            'NGINX_LOCATION_TEMPLATE_DEFAULT_TXT': '5',
            'NGINX_LOCATION_TEMPLATE_ROUTER_TXT': '6',
            'NGINX_HEALTHCHECK_PATH': '7',
        })
        self.assertEqual(nginx.nginx_purge_path, '/2')
        self.assertEqual(nginx.nginx_manage_port, '4')
        self.assertEqual(nginx.config_manager.location_template_default, '5')
        self.assertEqual(nginx.config_manager.location_template_router, '6')
        self.assertEqual(nginx.nginx_healthcheck_path, '7')

    @mock.patch('rpaas.nginx.requests')
    def test_init_config_location_url(self, requests):
        def mocked_requests_get(*args, **kwargs):
            class MockResponse:
                def __init__(self, text, status_code):
                    self.text = text
                    self.status_code = status_code
            if args[0] == 'http://my.com/default':
                return MockResponse("my result default", 200)
            elif args[0] == 'http://my.com/router':
                return MockResponse("my result router", 200)

        with mock.patch('rpaas.nginx.requests.get', side_effect=mocked_requests_get) as requests_get:
            nginx = Nginx({
                'NGINX_LOCATION_TEMPLATE_DEFAULT_URL': 'http://my.com/default',
                'NGINX_LOCATION_TEMPLATE_ROUTER_URL': 'http://my.com/router',
            })
        self.assertEqual(nginx.config_manager.location_template_default, 'my result default')
        self.assertEqual(nginx.config_manager.location_template_router, 'my result router')
        expected_calls = [mock.call('http://my.com/default'),
                          mock.call('http://my.com/router')]
        requests_get.assert_has_calls(expected_calls)

    @mock.patch('rpaas.nginx.requests')
    def test_purge_location_successfully(self, requests):
        nginx = Nginx()

        response = mock.Mock()
        response.status_code = 200
        response.text = 'purged'

        side_effect = mock.Mock()
        side_effect.status_code = 404
        side_effect.text = "Not Found"

        requests.request.side_effect = [response, side_effect, response, side_effect]
        purged = nginx.purge_location('myhost', '/foo/bar')
        self.assertTrue(purged)
        self.assertEqual(requests.request.call_count, 4)
        expec_responses = []
        for scheme in ['http', 'https']:
            for header in self.cache_headers:
                expec_responses.append(mock.call('get', 'http://myhost:8089/purge/{}/foo/bar'.format(scheme),
                                       headers=header, timeout=2))
        requests.request.assert_has_calls(expec_responses)

    @mock.patch('rpaas.nginx.requests')
    def test_purge_location_preserve_path_successfully(self, requests):
        nginx = Nginx()

        response = mock.Mock()
        response.status_code = 200
        response.text = 'purged'

        requests.request.side_effect = [response]
        purged = nginx.purge_location('myhost', 'http://example.com/foo/bar', True)
        self.assertTrue(purged)
        self.assertEqual(requests.request.call_count, 2)
        expected_responses = []
        for header in self.cache_headers:
            expected_responses.append(mock.call('get', 'http://myhost:8089/purge/http://example.com/foo/bar',
                                      headers=header, timeout=2))
        requests.request.assert_has_calls(expected_responses)

    @mock.patch('rpaas.nginx.requests')
    def test_purge_location_not_found(self, requests):
        nginx = Nginx()

        response = mock.Mock()
        response.status_code = 404
        response.text = 'Not Found'

        requests.request.side_effect = [response, response, response, response]
        purged = nginx.purge_location('myhost', '/foo/bar')
        self.assertFalse(purged)
        self.assertEqual(requests.request.call_count, 4)
        expec_responses = []
        for scheme in ['http', 'https']:
            for header in self.cache_headers:
                expec_responses.append(mock.call('get', 'http://myhost:8089/purge/{}/foo/bar'.format(scheme),
                                       headers=header, timeout=2))
        requests.request.assert_has_calls(expec_responses)

    @mock.patch('rpaas.nginx.requests')
    def test_wait_healthcheck(self, requests):
        nginx = Nginx()
        count = [0]
        response = mock.Mock()
        response.status_code = 200
        response.text = 'WORKING'

        def side_effect(method, url, timeout, **params):
            count[0] += 1
            if count[0] < 2:
                raise Exception('some error')
            return response

        requests.request.side_effect = side_effect
        nginx.wait_healthcheck('myhost.com', timeout=5)
        self.assertEqual(requests.request.call_count, 2)
        requests.request.assert_called_with('get', 'http://myhost.com:8089/healthcheck', timeout=2)

    @mock.patch('rpaas.nginx.requests')
    def test_wait_app_healthcheck(self, requests):
        nginx = Nginx()
        count = [0]
        response = mock.Mock()
        response.status_code = 200
        response.text = '\n\nWORKING'

        def side_effect(method, url, timeout, **params):
            count[0] += 1
            if count[0] < 2:
                raise Exception('some error')
            return response

        requests.request.side_effect = side_effect
        nginx.wait_healthcheck('myhost.com', timeout=5, manage_healthcheck=False)
        self.assertEqual(requests.request.call_count, 2)
        requests.request.assert_called_with('get', 'http://myhost.com:8080/_nginx_healthcheck/', timeout=2)

    @mock.patch('rpaas.nginx.requests')
    def test_wait_app_healthcheck_invalid_response(self, requests):
        nginx = Nginx()
        count = [0]
        response = mock.Mock()
        response.status_code = 200
        response.text = '\nFAIL\n'

        def side_effect(method, url, timeout, **params):
            count[0] += 1
            if count[0] < 2:
                raise Exception('some error')
            return response

        requests.request.side_effect = side_effect
        with self.assertRaises(NginxError):
            nginx.wait_healthcheck('myhost.com', timeout=5, manage_healthcheck=False)
        self.assertEqual(requests.request.call_count, 6)
        requests.request.assert_called_with('get', 'http://myhost.com:8080/_nginx_healthcheck/', timeout=2)

    @mock.patch('rpaas.nginx.requests')
    def test_wait_healthcheck_timeout(self, requests):
        nginx = Nginx()

        def side_effect(method, url, timeout, **params):
            raise Exception('some error')

        requests.request.side_effect = side_effect
        with self.assertRaises(Exception):
            nginx.wait_healthcheck('myhost.com', timeout=2)
        self.assertGreaterEqual(requests.request.call_count, 2)
        requests.request.assert_called_with('get', 'http://myhost.com:8089/healthcheck', timeout=2)

    @mock.patch('os.path')
    @mock.patch('rpaas.nginx.requests')
    def test_add_session_ticket_success(self, requests, os_path):
        nginx = Nginx({'CA_CERT': 'cert data'})
        os_path.exists.return_value = True
        response = mock.Mock()
        response.status_code = 200
        response.text = '\n\nticket was succsessfully added'
        requests.request.return_value = response
        nginx.add_session_ticket('host-1', 'random data', timeout=2)
        requests.request.assert_called_once_with('post', 'https://host-1:8090/session_ticket', timeout=2,
                                                 data='random data', verify='/tmp/rpaas_ca.pem')

    @mock.patch('rpaas.nginx.requests')
    def test_missing_ca_cert(self, requests):
        nginx = Nginx()
        with self.assertRaises(NginxError):
            nginx.add_session_ticket('host-1', 'random data', timeout=2)
