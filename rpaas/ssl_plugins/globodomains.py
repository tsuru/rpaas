# -*- coding: utf-8 -*-
from rpaas.ssl_plugins import BaseSSLPlugin
import requests
import base64
import os
import urllib
import re


class InvalidToken(Exception):
    pass

class GloboDomains(BaseSSLPlugin):

    def __init__(self, domain, id=None):
        self.base_url = os.getenv('RPAAS_PLUGIN_GLOBODOMAINS_URL', None)
        self.client_id = os.getenv('RPAAS_PLUGIN_GLOBODOMAINS_ID', None)
        self.client_secret = os.getenv('RPAAS_PLUGIN_GLOBODOMAINS_SECRET', None)
        self.oauth_url = os.getenv('RPAAS_PLUGIN_GLOBODOMAINS_BSURL', None)
        self.id = id
        self._bearer = self._get_token()
        self._cookie = self._get_cookie(self._bearer)
        self._domainid = self._get_domain_id(domain)

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

    def _get_cookie(self, token):
        get_cookie = requests.get(self.base_url, headers={'Authorization': 'Bearer '+token})
        if len(get_cookie.history) > 0:
            hds = get_cookie.history[0].headers
            if 'Set-Cookie' in hds:
                return hds['Set-Cookie']
        return ''


    @property
    def bearer(self):
        return self._bearer

    @property
    def cookie(self):
        return self._cookie

    def upload_csr(self, data):
        pass

    def _get_domain_id(self, name):
        encoded_name = urllib.quote_plus(name)
        get_domain = requests.get(self.base_url+'/domains.json?name=%s'%encoded_name,
            headers={'Authorization': 'Bearer '+self.bearer, 'Cookie': self.cookie})
        js = get_domain.json()
        if u'aaData' in js:
            retag = re.compile(r'<a.*href="(.*?)">(.*?)</a>')
            reid = re.compile(r'.*?([0-9]+?)$')
            for data in js['aaData']:
                stag = retag.search(data[0])
                if stag.group(2) == name:
                    return reid.search(stag.group(1)).group(1)

    def download_crt(self, id=None):
        return 'dsjjsdhfbiusehgf9s8yr9783h9'
        id = id if id else self.id
        get_cert = requests.get(self.base_url+'/api/crt/%s'%id)
        return base64.b64decode(get_cert.json()['crt'])
