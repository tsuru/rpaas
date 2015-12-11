# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import logging
import pipes
import time

import zope.interface

from acme import challenges

from letsencrypt import interfaces
from letsencrypt.plugins import common


logger = logging.getLogger(__name__)


class RpaasLeAuthenticator(common.Plugin):
    """RPAAS Authenticator.

    This plugin create a authentticator for Tsuru RPAAS.
    """
    zope.interface.implements(interfaces.IAuthenticator)
    zope.interface.classProvides(interfaces.IPluginFactory)
    hidden = True

    description = "Configure RPAAS HTTP server"

    CMD_TEMPLATE = """\
location /{achall.URI_ROOT_PATH}/{encoded_token} {{
    default_type text/plain;
    echo -n '{validation}';
}}
"""
    """Command template."""

    def __init__(self, instance_name, *args, **kwargs):
        super(RpaasLeAuthenticator, self).__init__(*args, **kwargs)
        self._root = './le'
        self._httpd = None
        self.instance_name = instance_name
        self.consul_manager = kwargs.get('consul_manager')

    def get_chall_pref(self, domain):
        return [challenges.HTTP01]

    def perform(self, achalls):
        responses = []
        for achall in achalls:
            responses.append(self._perform_single(achall))
        return responses

    def _perform_single(self, achall):
        response, validation = achall.response_and_validation()

        self._notify_and_wait(self.CMD_TEMPLATE.format(
            achall=achall, validation=pipes.quote(validation),
            encoded_token=achall.chall.encode("token")))

        if response.simple_verify(
                achall.chall, achall.domain,
                achall.account_key.public_key(), self.config.http01_port):
            return response
        else:
            logger.error(
                "Self-verify of challenge failed, authorization abandoned.")
            return None

    def _notify_and_wait(self, message):
        self.consul_manager.write_location(self.instance_name, "/acme-validate",
                                           content=message)
        time.sleep(6)

    def cleanup(self, achalls):
        pass
