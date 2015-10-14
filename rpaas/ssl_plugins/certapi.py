# -*- coding: utf-8 -*-
from rpaas.ssl_plugins import BaseSSLPlugin
import requests
import base64
import os


class Certapi(BaseSSLPlugin):

    def __init__(self, domain, id=None):
        self.base_url = os.getenv('RPAAS_PLUGIN_CERTAPI_URL', None)
        self.username = os.getenv('RPAAS_PLUGIN_CERTAPI_USERNAME', None)
        self.password = os.getenv('RPAAS_PLUGIN_CERTAPI_PASSWORD', None)
        self.certid = id
        self._bearer = self._get_token()
        self._domainid = None

    def _get_token(self):
        try:
            resp = requests.post(self.oauth_url, 
                data={
                    'grant_type':'client_credentials'
                },
                auth=(self.client_id, self.client_secret),
                verify=False)
            js = resp.json()
            return js.get('access_token').encode()
        except:
            raise InvalidToken()

    @property
    def bearer(self):
        return self._bearer


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
