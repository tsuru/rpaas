"""Manual plugin."""
import logging
import pipes
import time

import zope.interface

from acme import challenges

from letsencrypt import interfaces
from letsencrypt.plugins import common

import rpaas


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

    def __init__(self, hosts, *args, **kwargs):
        super(RpaasLeAuthenticator, self).__init__(*args, **kwargs)
        self._root = './le'
        self._httpd = None
        self.hosts = hosts

    def get_chall_pref(self, domain):
        return [challenges.HTTP01]

    def perform(self, achalls):  # pylint: disable=missing-docstring
        responses = []
        for achall in achalls:
            responses.append(self._perform_single(achall))
        return responses

    def _perform_single(self, achall):
        response, validation = achall.response_and_validation()

        port = (response.port if self.config.http01_port is None
                else int(self.config.http01_port))

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

    def _notify_and_wait(self, message):  # pylint: disable=no-self-use
        nginx_manager = rpaas.get_manager().nginx_manager
        for host in self.hosts:
            nginx_manager.acme_conf(host, message)
        time.sleep(6)
        # TODO: update rpaas nginx
        # sys.stdout.write(message)
        # raw_input("Press ENTER to continue")

    def cleanup(self, achalls):
        pass
