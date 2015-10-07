# -*- coding: utf-8 -*-
from rpaas.ssl_plugins import BaseSSLPlugin
import requests
import base64
import os


class Certapi(BaseSSLPlugin):

    def __init__(self, id=None):
        self.base_url = os.getenv('RPAAS_PLUGIN_CERTAPI_URL', None)
        self.username = os.getenv('RPAAS_PLUGIN_CERTAPI_USERNAME', None)
        self.password = os.getenv('RPAAS_PLUGIN_CERTAPI_PASSWORD', None)
        self.token = None
        self.id = id
        # self.auth()

    def auth(self):
        auth_token = requests.post(self.base_url+'/api/auth', data={'username': self.username, 'password': self.password})
        self.token = auth_token.json()['token']

    def upload_csr(self, data):
        return 0
        get_id = requests.post(self.base_url+'/api/csr', data=data)
        self.id = get_id.json()['id']
        return self.id

    def download_crt(self, id=None):
        return 'dsjjsdhfbiusehgf9s8yr9783h9'
        id = id if id else self.id
        get_cert = requests.get(self.base_url+'/api/crt/%s'%id)
        return base64.b64decode(get_cert.json()['crt'])
