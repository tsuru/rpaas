# -*- coding: utf-8 -*-
from rpaas.ssl_plugins import BaseSSLPlugin
import rpaas

import json
import logging
import os
import pipes
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import argparse
import atexit
import functools
import logging.handlers
import pkg_resources
import traceback

import configargparse
import configobj

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import rsa
import OpenSSL

from acme import client as acme_client
from acme import jose
from acme import messages
from acme import challenges

from letsencrypt import account
from letsencrypt import auth_handler
from letsencrypt import configuration
from letsencrypt import continuity_auth
from letsencrypt import crypto_util
from letsencrypt import colored_logging
import rpaas.ssl_plugins.le_constants as constants
from letsencrypt import errors
from letsencrypt import error_handler
from letsencrypt import interfaces
from letsencrypt import le_util
from letsencrypt import reverter
from letsencrypt import client
from letsencrypt import storage
from letsencrypt import log
from letsencrypt import reporter

from letsencrypt.plugins import common
from letsencrypt.plugins import disco as plugins_disco

from letsencrypt.display import ops as display_ops
from letsencrypt.display import util as display_util
from letsencrypt.display import enhancements

import zope.component
import zope.interface
import zope.interface.exceptions
import zope.interface.verify

import letsencrypt


logger = logging.getLogger(__name__)


class LE(BaseSSLPlugin):

    def __init__(self, domain, email, hosts=[]):
        self.domain = domain
        self.email = email
        self.hosts = [str(x) for x in hosts]

    def upload_csr(self, csr=None):
        return None

    def download_crt(self, id=None):
        try:
            crt, chain, key = main(['auth', '--text', '--domains', str(self.domain), '-m', self.email, '--hosts']+self.hosts)
        else:
            return json.dumps({'crt': crt, 'chain': chain, 'key': key})
        finally:
            nginx_manager = rpaas.get_manager().nginx_manager
            for host in self.hosts:
                nginx_manager.delete_acme_conf(host)






"""Let's Encrypt client API."""
def _acme_from_config_key(config, key):
    # TODO: Allow for other alg types besides RS256
    return acme_client.Client(directory=config.server, key=key,
                              verify_ssl=(not config.no_verify_ssl))


def register(config, account_storage, tos_cb=None):
    """Register new account with an ACME CA.

    This function takes care of generating fresh private key,
    registering the account, optionally accepting CA Terms of Service
    and finally saving the account. It should be called prior to
    initialization of `Client`, unless account has already been created.

    :param .IConfig config: Client configuration.

    :param .AccountStorage account_storage: Account storage where newly
        registered account will be saved to. Save happens only after TOS
        acceptance step, so any account private keys or
        `.RegistrationResource` will not be persisted if `tos_cb`
        returns ``False``.

    :param tos_cb: If ACME CA requires the user to accept a Terms of
        Service before registering account, client action is
        necessary. For example, a CLI tool would prompt the user
        acceptance. `tos_cb` must be a callable that should accept
        `.RegistrationResource` and return a `bool`: ``True`` iff the
        Terms of Service present in the contained
        `.Registration.terms_of_service` is accepted by the client, and
        ``False`` otherwise. ``tos_cb`` will be called only if the
        client acction is necessary, i.e. when ``terms_of_service is not
        None``. This argument is optional, if not supplied it will
        default to automatic acceptance!

    :raises letsencrypt.errors.Error: In case of any client problems, in
        particular registration failure, or unaccepted Terms of Service.
    :raises acme.errors.Error: In case of any protocol problems.

    :returns: Newly registered and saved account, as well as protocol
        API handle (should be used in `Client` initialization).
    :rtype: `tuple` of `.Account` and `acme.client.Client`

    """
    # Log non-standard actions, potentially wrong API calls
    if account_storage.find_all():
        logger.info("There are already existing accounts for %s", config.server)
    if config.email is None:
        logger.warn("Registering without email!")

    # Each new registration shall use a fresh new key
    key = jose.JWKRSA(key=jose.ComparableRSAKey(
        rsa.generate_private_key(
            public_exponent=65537,
            key_size=config.rsa_key_size,
            backend=default_backend())))
    acme = _acme_from_config_key(config, key)
    # TODO: add phone?
    regr = acme.register(messages.NewRegistration.from_data(email=config.email))

    if regr.terms_of_service is not None:
        if tos_cb is not None and not tos_cb(regr):
            raise errors.Error(
                "Registration cannot proceed without accepting "
                "Terms of Service.")
        regr = acme.agree_to_tos(regr)

    acc = account.Account(regr, key)
    account.report_new_account(acc, config)
    account_storage.save(acc)
    return acc, acme


class Client(object):
    """ACME protocol client.

    :ivar .IConfig config: Client configuration.
    :ivar .Account account: Account registered with `register`.
    :ivar .AuthHandler auth_handler: Authorizations handler that will
        dispatch DV and Continuity challenges to appropriate
        authenticators (providing `.IAuthenticator` interface).
    :ivar .IAuthenticator dv_auth: Prepared (`.IAuthenticator.prepare`)
        authenticator that can solve the `.constants.DV_CHALLENGES`.
    :ivar .IInstaller installer: Installer.
    :ivar acme.client.Client acme: Optional ACME client API handle.
       You might already have one from `register`.

    """

    def __init__(self, config, account_, dv_auth, installer, acme=None):
        """Initialize a client."""
        self.config = config
        self.account = account_
        self.dv_auth = dv_auth
        self.installer = installer

        # Initialize ACME if account is provided
        if acme is None and self.account is not None:
            acme = _acme_from_config_key(config, self.account.key)
        self.acme = acme

        # TODO: Check if self.config.enroll_autorenew is None. If
        # so, set it based to the default: figure out if dv_auth is
        # standalone (then default is False, otherwise default is True)

        if dv_auth is not None:
            cont_auth = continuity_auth.ContinuityAuthenticator(config,
                                                                installer)
            self.auth_handler = auth_handler.AuthHandler(
                dv_auth, cont_auth, self.acme, self.account)
        else:
            self.auth_handler = None

    def _obtain_certificate(self, domains, csr):
        """Obtain certificate.

        Internal function with precondition that `domains` are
        consistent with identifiers present in the `csr`.

        :param list domains: Domain names.
        :param .le_util.CSR csr: DER-encoded Certificate Signing
            Request. The key used to generate this CSR can be different
            than `authkey`.

        :returns: `.CertificateResource` and certificate chain (as
            returned by `.fetch_chain`).
        :rtype: tuple

        """
        if self.auth_handler is None:
            msg = ("Unable to obtain certificate because authenticator is "
                   "not set.")
            logger.warning(msg)
            raise errors.Error(msg)
        if self.account.regr is None:
            raise errors.Error("Please register with the ACME server first.")

        logger.debug("CSR: %s, domains: %s", csr, domains)

        authzr = self.auth_handler.get_authorizations(domains)
        certr = self.acme.request_issuance(
            jose.ComparableX509(OpenSSL.crypto.load_certificate_request(
                OpenSSL.crypto.FILETYPE_ASN1, csr.data)),
            authzr)
        return certr, self.acme.fetch_chain(certr)

    def obtain_certificate_from_csr(self, csr):
        """Obtain certficiate from CSR.

        :param .le_util.CSR csr: DER-encoded Certificate Signing
            Request.

        :returns: `.CertificateResource` and certificate chain (as
            returned by `.fetch_chain`).
        :rtype: tuple

        """
        return self._obtain_certificate(
            # TODO: add CN to domains?
            crypto_util.get_sans_from_csr(
                csr.data, OpenSSL.crypto.FILETYPE_ASN1), csr)

    def obtain_certificate(self, domains):
        """Obtains a certificate from the ACME server.

        `.register` must be called before `.obtain_certificate`

        :param set domains: domains to get a certificate

        :returns: `.CertificateResource`, certificate chain (as
            returned by `.fetch_chain`), and newly generated private key
            (`.le_util.Key`) and DER-encoded Certificate Signing Request
            (`.le_util.CSR`).
        :rtype: tuple

        """
        # Create CSR from names
        key = crypto_util.init_save_key(
            self.config.rsa_key_size, self.config.key_dir)
        csr = crypto_util.init_save_csr(key, domains, self.config.csr_dir)

        return self._obtain_certificate(domains, csr) + (key, csr)

    def obtain_and_enroll_certificate(self, domains, plugins):
        """Obtain and enroll certificate.

        Get a new certificate for the specified domains using the specified
        authenticator and installer, and then create a new renewable lineage
        containing it.

        :param list domains: Domains to request.
        :param plugins: A PluginsFactory object.

        :returns: A new :class:`letsencrypt.storage.RenewableCert` instance
            referred to the enrolled cert lineage, or False if the cert could
            not be obtained.

        """
        certr, chain, key, _ = self.obtain_certificate(domains)
        return (
            OpenSSL.crypto.dump_certificate(OpenSSL.crypto.FILETYPE_PEM, certr.body),
            crypto_util.dump_pyopenssl_chain(chain),
            key.pem
        )


        # TODO: remove this dirty hack
        self.config.namespace.authenticator = plugins.find_init(
            self.dv_auth).name
        if self.installer is not None:
            self.config.namespace.installer = plugins.find_init(
                self.installer).name

        # XXX: We clearly need a more general and correct way of getting
        # options into the configobj for the RenewableCert instance.
        # This is a quick-and-dirty way to do it to allow integration
        # testing to start.  (Note that the config parameter to new_lineage
        # ideally should be a ConfigObj, but in this case a dict will be
        # accepted in practice.)
        params = vars(self.config.namespace)
        config = {}
        cli_config = configuration.RenewerConfiguration(self.config.namespace)

        if (cli_config.config_dir != constants.CLI_DEFAULTS["config_dir"] or
                cli_config.work_dir != constants.CLI_DEFAULTS["work_dir"]):
            logger.warning(
                "Non-standard path(s), might not work with crontab installed "
                "by your operating system package manager")

        lineage = storage.RenewableCert.new_lineage(
            domains[0], OpenSSL.crypto.dump_certificate(
                OpenSSL.crypto.FILETYPE_PEM, certr.body),
            key.pem, crypto_util.dump_pyopenssl_chain(chain),
            params, config, cli_config)
        self._report_renewal_status(lineage)
        return lineage

    def _report_renewal_status(self, cert):
        # pylint: disable=no-self-use
        """Informs the user about automatic renewal and deployment.

        :param .RenewableCert cert: Newly issued certificate

        """
        if cert.autorenewal_is_enabled():
            if cert.autodeployment_is_enabled():
                msg = "Automatic renewal and deployment has "
            else:
                msg = "Automatic renewal but not automatic deployment has "
        elif cert.autodeployment_is_enabled():
            msg = "Automatic deployment but not automatic renewal has "
        else:
            msg = "Automatic renewal and deployment has not "

        msg += ("been enabled for your certificate. These settings can be "
                "configured in the directories under {0}.").format(
                    cert.cli_config.renewal_configs_dir)
        reporter = zope.component.getUtility(interfaces.IReporter)
        reporter.add_message(msg, reporter.LOW_PRIORITY)

    def save_certificate(self, certr, chain_cert, cert_path, chain_path):
        # pylint: disable=no-self-use
        """Saves the certificate received from the ACME server.

        :param certr: ACME "certificate" resource.
        :type certr: :class:`acme.messages.Certificate`

        :param list chain_cert:
        :param str cert_path: Candidate path to a certificate.
        :param str chain_path: Candidate path to a certificate chain.

        :returns: cert_path, chain_path (absolute paths to the actual files)
        :rtype: `tuple` of `str`

        :raises IOError: If unable to find room to write the cert files

        """
        for path in cert_path, chain_path:
            le_util.make_or_verify_dir(
                os.path.dirname(path), 0o755, os.geteuid(),
                self.config.strict_permissions)

        # try finally close
        cert_chain_abspath = None
        cert_file, act_cert_path = le_util.unique_file(cert_path, 0o644)
        # TODO: Except
        cert_pem = OpenSSL.crypto.dump_certificate(
            OpenSSL.crypto.FILETYPE_PEM, certr.body)
        try:
            cert_file.write(cert_pem)
        finally:
            cert_file.close()
        logger.info("Server issued certificate; certificate written to %s",
                    act_cert_path)

        if chain_cert:
            chain_file, act_chain_path = le_util.unique_file(
                chain_path, 0o644)
            # TODO: Except
            chain_pem = crypto_util.dump_pyopenssl_chain(chain_cert)
            try:
                chain_file.write(chain_pem)
            finally:
                chain_file.close()

            logger.info("Cert chain written to %s", act_chain_path)

            # This expects a valid chain file
            cert_chain_abspath = os.path.abspath(act_chain_path)

        return os.path.abspath(act_cert_path), cert_chain_abspath

    def deploy_certificate(self, domains, privkey_path, cert_path, chain_path):
        """Install certificate

        :param list domains: list of domains to install the certificate
        :param str privkey_path: path to certificate private key
        :param str cert_path: certificate file path (optional)
        :param str chain_path: chain file path

        """
        if self.installer is None:
            logger.warning("No installer specified, client is unable to deploy"
                           "the certificate")
            raise errors.Error("No installer available")

        chain_path = None if chain_path is None else os.path.abspath(chain_path)

        with error_handler.ErrorHandler(self.installer.recovery_routine):
            for dom in domains:
                # TODO: Provide a fullchain reference for installers like
                #       nginx that want it
                self.installer.deploy_cert(
                    dom, os.path.abspath(cert_path),
                    os.path.abspath(privkey_path), chain_path)

            self.installer.save("Deployed Let's Encrypt Certificate")
            # sites may have been enabled / final cleanup
            self.installer.restart()

    def enhance_config(self, domains, redirect=None):
        """Enhance the configuration.

        .. todo:: This needs to handle the specific enhancements offered by the
            installer. We will also have to find a method to pass in the chosen
            values efficiently.

        :param list domains: list of domains to configure

        :param redirect: If traffic should be forwarded from HTTP to HTTPS.
        :type redirect: bool or None

        :raises .errors.Error: if no installer is specified in the
            client.

        """
        if self.installer is None:
            logger.warning("No installer is specified, there isn't any "
                           "configuration to enhance.")
            raise errors.Error("No installer available")

        if redirect is None:
            redirect = enhancements.ask("redirect")

        # When support for more enhancements are added, the call to the
        # plugin's `enhance` function should be wrapped by an ErrorHandler
        if redirect:
            self.redirect_to_ssl(domains)

    def redirect_to_ssl(self, domains):
        """Redirect all traffic from HTTP to HTTPS

        :param vhost: list of ssl_vhosts
        :type vhost: :class:`letsencrypt.interfaces.IInstaller`

        """
        with error_handler.ErrorHandler(self.installer.recovery_routine):
            for dom in domains:
                try:
                    self.installer.enhance(dom, "redirect")
                except errors.PluginError:
                    logger.warn("Unable to perform redirect for %s", dom)
                    raise

            self.installer.save("Add Redirects")
            self.installer.restart()


def validate_key_csr(privkey, csr=None):
    """Validate Key and CSR files.

    Verifies that the client key and csr arguments are valid and correspond to
    one another. This does not currently check the names in the CSR due to
    the inability to read SANs from CSRs in python crypto libraries.

    If csr is left as None, only the key will be validated.

    :param privkey: Key associated with CSR
    :type privkey: :class:`letsencrypt.le_util.Key`

    :param .le_util.CSR csr: CSR

    :raises .errors.Error: when validation fails

    """
    # TODO: Handle all of these problems appropriately
    # The client can eventually do things like prompt the user
    # and allow the user to take more appropriate actions

    # Key must be readable and valid.
    if privkey.pem and not crypto_util.valid_privkey(privkey.pem):
        raise errors.Error("The provided key is not a valid key")

    if csr:
        if csr.form == "der":
            csr_obj = OpenSSL.crypto.load_certificate_request(
                OpenSSL.crypto.FILETYPE_ASN1, csr.data)
            csr = le_util.CSR(csr.file, OpenSSL.crypto.dump_certificate(
                OpenSSL.crypto.FILETYPE_PEM, csr_obj), "pem")

        # If CSR is provided, it must be readable and valid.
        if csr.data and not crypto_util.valid_csr(csr.data):
            raise errors.Error("The provided CSR is not a valid CSR")

        # If both CSR and key are provided, the key must be the same key used
        # in the CSR.
        if csr.data and privkey.pem:
            if not crypto_util.csr_matches_pubkey(
                    csr.data, privkey.pem):
                raise errors.Error("The key and CSR do not match")


def rollback(default_installer, checkpoints, config, plugins):
    """Revert configuration the specified number of checkpoints.

    :param int checkpoints: Number of checkpoints to revert.

    :param config: Configuration.
    :type config: :class:`letsencrypt.interfaces.IConfig`

    """
    # Misconfigurations are only a slight problems... allow the user to rollback
    installer = display_ops.pick_installer(
        config, default_installer, plugins, question="Which installer "
        "should be used for rollback?")

    # No Errors occurred during init... proceed normally
    # If installer is None... couldn't find an installer... there shouldn't be
    # anything to rollback
    if installer is not None:
        installer.rollback_checkpoints(checkpoints)
        installer.restart()


def view_config_changes(config):
    """View checkpoints and associated configuration changes.

    .. note:: This assumes that the installation is using a Reverter object.

    :param config: Configuration.
    :type config: :class:`letsencrypt.interfaces.IConfig`

    """
    rev = reverter.Reverter(config)
    rev.recovery_routine()
    rev.view_config_changes()







"""Manual plugin."""

class Authenticator(common.Plugin):
    """Manual Authenticator.

    .. todo:: Support for `~.challenges.DVSNI`.

    """
    zope.interface.implements(interfaces.IAuthenticator)
    zope.interface.classProvides(interfaces.IPluginFactory)

    description = "Manual Authenticator"

    MESSAGE_TEMPLATE = """\
Make sure your web server displays the following content at
{uri} before continuing:

{validation}

Content-Type header MUST be set to {ct}.

If you don't have HTTP server configured, you can run the following
command on the target server (as root):

{command}
"""

    # "cd /tmp/letsencrypt" makes sure user doesn't serve /root,
    # separate "public_html" ensures that cert.pem/key.pem are not
    # served and makes it more obvious that Python command will serve
    # anything recursively under the cwd

    CMD_TEMPLATE = """\
mkdir -p {root}/public_html/{response.URI_ROOT_PATH}
cd {root}/public_html
echo -n {validation} > {response.URI_ROOT_PATH}/{encoded_token}
# run only once per server:
$(command -v python2 || command -v python2.7 || command -v python2.6) -c \\
"import BaseHTTPServer, SimpleHTTPServer; \\
SimpleHTTPServer.SimpleHTTPRequestHandler.extensions_map = {{'': '{ct}'}}; \\
s = BaseHTTPServer.HTTPServer(('', {port}), SimpleHTTPServer.SimpleHTTPRequestHandler); \\
s.serve_forever()" """
    """Command template."""

    def __init__(self, *args, **kwargs):
        self.hosts = kwargs['hosts'] if kwargs['hosts'] else None
        del kwargs['hosts']
        super(Authenticator, self).__init__(*args, **kwargs)
        self._root = (tempfile.mkdtemp() if self.conf("test-mode")
                      else "/tmp/letsencrypt")
        self._httpd = None

    @classmethod
    def add_parser_arguments(cls, add):
        add("test-mode", action="store_true",
            help="Test mode. Executes the manual command in subprocess.")

    def prepare(self):  # pylint: disable=missing-docstring,no-self-use
        pass  # pragma: no cover

    def more_info(self):  # pylint: disable=missing-docstring,no-self-use
        return """\
This plugin requires user's manual intervention in setting up a HTTP
server for solving SimpleHTTP challenges and thus does not need to be
run as a privilidged process. Alternatively shows instructions on how
to use Python's built-in HTTP server and, in case of HTTPS, openssl
binary for temporary key/certificate generation.""".replace("\n", "")

    def get_chall_pref(self, domain):
        # pylint: disable=missing-docstring,no-self-use,unused-argument
        return [challenges.SimpleHTTP]

    def perform(self, achalls):  # pylint: disable=missing-docstring
        responses = []
        # TODO: group achalls by the same socket.gethostbyname(_ex)
        # and prompt only once per server (one "echo -n" per domain)
        for achall in achalls:
            responses.append(self._perform_single(achall))
        return responses

    @classmethod
    def _test_mode_busy_wait(cls, port):
        while True:
            time.sleep(1)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.connect(("localhost", port))
            except socket.error:  # pragma: no cover
                pass
            else:
                break
            finally:
                sock.close()

    def _perform_single(self, achall):
        # same path for each challenge response would be easier for
        # users, but will not work if multiple domains point at the
        # same server: default command doesn't support virtual hosts
        response, validation = achall.gen_response_and_validation(
            tls=False)  # SimpleHTTP TLS is dead: ietf-wg-acme/acme#7

        port = (response.port if self.config.simple_http_port is None
                else int(self.config.simple_http_port))
        command = self.CMD_TEMPLATE.format(
            root=self._root, achall=achall, response=response,
            validation=pipes.quote(validation.json_dumps()),
            encoded_token=achall.chall.encode("token"),
            ct=response.CONTENT_TYPE, port=port)
        if self.conf("test-mode"):
            logger.debug("Test mode. Executing the manual command: %s", command)
            try:
                self._httpd = subprocess.Popen(
                    command,
                    # don't care about setting stdout and stderr,
                    # we're in test mode anyway
                    shell=True,
                    # "preexec_fn" is UNIX specific, but so is "command"
                    preexec_fn=os.setsid)
            except OSError as error:  # ValueError should not happen!
                logger.debug(
                    "Couldn't execute manual command: %s", error, exc_info=True)
                return False
            logger.debug("Manual command running as PID %s.", self._httpd.pid)
            # give it some time to bootstrap, before we try to verify
            # (cert generation in case of simpleHttpS might take time)
            self._test_mode_busy_wait(port)
            if self._httpd.poll() is not None:
                raise errors.Error("Couldn't execute manual command")
        else:
            # write location in nginx
            route = response.uri(achall.domain, achall.challb.chall)
            route = route[route.rfind('/')+1:]
            content = pipes.quote(validation.json_dumps())

            nginx_manager = rpaas.get_manager().nginx_manager
            for host in self.hosts:
                nginx_manager.acme_conf(host, route, content)

        # return response
        if response.simple_verify(
                achall.chall, achall.domain,
                achall.account_key.public_key(), self.config.simple_http_port):
            return response
        else:
            logger.error(
                "Self-verify of challenge failed, authorization abandoned.")
            if self.conf("test-mode") and self._httpd.poll() is not None:
                # simply verify cause command failure...
                return False
            return None

    def _notify_and_wait(self, message):  # pylint: disable=no-self-use
        # TODO: IDisplay wraps messages, breaking the command
        #answer = zope.component.getUtility(interfaces.IDisplay).notification(
        #    message=message, height=25, pause=True)
        sys.stdout.write(message)
        raw_input("Press ENTER to continue")

    def cleanup(self, achalls):
        # pylint: disable=missing-docstring,no-self-use,unused-argument
        if self.conf("test-mode"):
            assert self._httpd is not None, (
                "cleanup() must be called after perform()")
            if self._httpd.poll() is None:
                logger.debug("Terminating manual command process")
                os.killpg(self._httpd.pid, signal.SIGTERM)
            else:
                logger.debug("Manual command process already terminated "
                             "with %s code", self._httpd.returncode)
            shutil.rmtree(self._root)






''' CLI '''

# Argparse's help formatting has a lot of unhelpful peculiarities, so we want
# to replace as much of it as we can...

# This is the stub to include in help generated by argparse

SHORT_USAGE = """
  letsencrypt [SUBCOMMAND] [options] [domains]

The Let's Encrypt agent can obtain and install HTTPS/TLS/SSL certificates.  By
default, it will attempt to use a webserver both for obtaining and installing
the cert.  """

# This is the short help for letsencrypt --help, where we disable argparse
# altogether
USAGE = SHORT_USAGE + """Major SUBCOMMANDS are:

  (default) everything Obtain & install a cert in your current webserver
  auth                 Authenticate & obtain cert, but do not install it
  install              Install a previously obtained cert in a server
  revoke               Revoke a previously obtained certificate
  rollback             Rollback server configuration changes made during install
  config_changes       Show changes made to server config during installation

Choice of server for authentication/installation:

  --apache          Use the Apache plugin for authentication & installation
  --nginx           Use the Nginx plugin for authentication & installation
  --standalone      Run a standalone HTTPS server (for authentication only)
  OR:
  --authenticator standalone --installer nginx

More detailed help:

  -h, --help [topic]    print this message, or detailed help on a topic;
                        the available topics are:

   all, apache, automation, manual, nginx, paths, security, testing, or any of
   the subcommands
"""


def _find_domains(args, installer):
    if args.domains is None:
        domains = display_ops.choose_names(installer)
    else:
        domains = args.domains

    if not domains:
        raise errors.Error("Please specify --domains, or --installer that "
                           "will help in domain names autodiscovery")

    return domains


def _determine_account(args, config):
    """Determine which account to use.

    In order to make the renewer (configuration de/serialization) happy,
    if ``args.account`` is ``None``, it will be updated based on the
    user input. Same for ``args.email``.

    :param argparse.Namespace args: CLI arguments
    :param letsencrypt.interface.IConfig config: Configuration object
    :param .AccountStorage account_storage: Account storage.

    :returns: Account and optionally ACME client API (biproduct of new
        registration).
    :rtype: `tuple` of `letsencrypt.account.Account` and
        `acme.client.Client`

    """
    account_storage = account.AccountFileStorage(config)
    acme = None

    if args.account is not None:
        acc = account_storage.load(args.account)
    else:
        accounts = account_storage.find_all()
        if len(accounts) > 1:
            acc = display_ops.choose_account(accounts)
        elif len(accounts) == 1:
            acc = accounts[0]
        else:  # no account registered yet
            if args.email is None:
                args.email = display_ops.get_email()
            if not args.email:  # get_email might return ""
                args.email = None

            def _tos_cb(regr):
                return True
                if args.tos:
                    return True
                msg = ("Please read the Terms of Service at {0}. You "
                       "must agree in order to register with the ACME "
                       "server at {1}".format(
                           regr.terms_of_service, config.server))
                return zope.component.getUtility(interfaces.IDisplay).yesno(
                    msg, "Agree", "Cancel")

            try:
                acc, acme = client.register(
                    config, account_storage, tos_cb=_tos_cb)
            except errors.Error as error:
                logger.debug(error, exc_info=True)
                raise errors.Error(
                    "Unable to register an account with ACME server")

    args.account = acc.id
    return acc, acme


def _init_le_client(args, config, authenticator, installer):
    if authenticator is not None:
        # if authenticator was given, then we will need account...
        acc, acme = _determine_account(args, config)
        logger.debug("Picked account: %r", acc)
        # XXX
        #crypto_util.validate_key_csr(acc.key)
    else:
        acc, acme = None, None

    return Client(config, acc, authenticator, installer, acme=acme)


def _find_duplicative_certs(domains, config, renew_config):
    """Find existing certs that duplicate the request."""

    identical_names_cert, subset_names_cert = None, None

    configs_dir = renew_config.renewal_configs_dir
    # Verify the directory is there
    le_util.make_or_verify_dir(configs_dir, mode=0o755, uid=os.geteuid())

    cli_config = configuration.RenewerConfiguration(config)
    for renewal_file in os.listdir(configs_dir):
        try:
            full_path = os.path.join(configs_dir, renewal_file)
            rc_config = configobj.ConfigObj(renew_config.renewer_config_file)
            rc_config.merge(configobj.ConfigObj(full_path))
            rc_config.filename = full_path
            candidate_lineage = storage.RenewableCert(
                rc_config, config_opts=None, cli_config=cli_config)
        except (configobj.ConfigObjError, errors.CertStorageError, IOError):
            logger.warning("Renewal configuration file %s is broken. "
                           "Skipping.", full_path)
            continue
        # TODO: Handle these differently depending on whether they are
        #       expired or still valid?
        candidate_names = set(candidate_lineage.names())
        if candidate_names == set(domains):
            identical_names_cert = candidate_lineage
        elif candidate_names.issubset(set(domains)):
            subset_names_cert = candidate_lineage

    return identical_names_cert, subset_names_cert


def _treat_as_renewal(config, domains):
    """Determine whether or not the call should be treated as a renewal.

    :returns: RenewableCert or None if renewal shouldn't occur.
    :rtype: :class:`.storage.RenewableCert`

    :raises .Error: If the user would like to rerun the client again.

    """
    renewal = False

    # Considering the possibility that the requested certificate is
    # related to an existing certificate.  (config.duplicate, which
    # is set with --duplicate, skips all of this logic and forces any
    # kind of certificate to be obtained with renewal = False.)
    if not config.duplicate:
        ident_names_cert, subset_names_cert = _find_duplicative_certs(
            domains, config, configuration.RenewerConfiguration(config))
        # I am not sure whether that correctly reads the systemwide
        # configuration file.
        question = None
        if ident_names_cert is not None:
            question = (
                "You have an existing certificate that contains exactly the "
                "same domains you requested (ref: {0}){br}{br}Do you want to "
                "renew and replace this certificate with a newly-issued one?"
            ).format(ident_names_cert.configfile.filename, br=os.linesep)
        elif subset_names_cert is not None:
            question = (
                "You have an existing certificate that contains a portion of "
                "the domains you requested (ref: {0}){br}{br}It contains these "
                "names: {1}{br}{br}You requested these names for the new "
                "certificate: {2}.{br}{br}Do you want to replace this existing "
                "certificate with the new certificate?"
            ).format(subset_names_cert.configfile.filename,
                     ", ".join(subset_names_cert.names()),
                     ", ".join(domains),
                     br=os.linesep)
        if question is None:
            # We aren't in a duplicative-names situation at all, so we don't
            # have to tell or ask the user anything about this.
            pass
        elif config.renew_by_default or zope.component.getUtility(
                interfaces.IDisplay).yesno(question, "Replace", "Cancel"):
            renewal = True
        else:
            reporter_util = zope.component.getUtility(interfaces.IReporter)
            reporter_util.add_message(
                "To obtain a new certificate that {0} an existing certificate "
                "in its domain-name coverage, you must use the --duplicate "
                "option.{br}{br}For example:{br}{br}{1} --duplicate {2}".format(
                    "duplicates" if ident_names_cert is not None else
                    "overlaps with",
                    sys.argv[0], " ".join(sys.argv[1:]),
                    br=os.linesep
                ),
                reporter_util.HIGH_PRIORITY)
            raise errors.Error(
                "User did not use proper CLI and would like "
                "to reinvoke the client.")

        if renewal:
            return ident_names_cert if ident_names_cert is not None else subset_names_cert

    return None


def _report_new_cert(cert_path):
    """Reports the creation of a new certificate to the user."""
    reporter_util = zope.component.getUtility(interfaces.IReporter)
    reporter_util.add_message("Congratulations! Your certificate has been "
                              "saved at {0}.".format(cert_path),
                              reporter_util.MEDIUM_PRIORITY)


def _auth_from_domains(le_client, config, domains, plugins):
    """Authenticate and enroll certificate."""
    # Note: This can raise errors... caught above us though.
    lineage = _treat_as_renewal(config, domains)

    if lineage is not None:
        # TODO: schoen wishes to reuse key - discussion
        # https://github.com/letsencrypt/letsencrypt/pull/777/files#r40498574
        new_certr, new_chain, new_key, _ = le_client.obtain_certificate(domains)
        # TODO: Check whether it worked! <- or make sure errors are thrown (jdk)
        lineage.save_successor(
            lineage.latest_common_version(), OpenSSL.crypto.dump_certificate(
                OpenSSL.crypto.FILETYPE_PEM, new_certr.body),
            new_key.pem, crypto_util.dump_pyopenssl_chain(new_chain))

        lineage.update_all_links_to(lineage.latest_common_version())
        # TODO: Check return value of save_successor
        # TODO: Also update lineage renewal config with any relevant
        #       configuration values from this attempt? <- Absolutely (jdkasten)
    else:
        # TREAT AS NEW REQUEST
        lineage = le_client.obtain_and_enroll_certificate(domains, plugins)
        if not lineage:
            raise errors.Error("Certificate could not be obtained")

    # _report_new_cert(lineage.cert)

    return lineage


# TODO: Make run as close to auth + install as possible
# Possible difficulties: args.csr was hacked into auth
def run(args, config, plugins):  # pylint: disable=too-many-branches,too-many-locals
    """Obtain a certificate and install."""
    # Begin authenticator and installer setup
    if args.configurator is not None and (args.installer is not None or
                                          args.authenticator is not None):
        return ("Either --configurator or --authenticator/--installer"
                "pair, but not both, is allowed")

    if args.authenticator is not None or args.installer is not None:
        installer = display_ops.pick_installer(
            config, args.installer, plugins)
        authenticator = display_ops.pick_authenticator(
            config, args.authenticator, plugins)
    else:
        # TODO: this assumes that user doesn't want to pick authenticator
        #       and installer separately...
        authenticator = installer = display_ops.pick_configurator(
            config, args.configurator, plugins)

    if installer is None or authenticator is None:
        return "Configurator could not be determined"
    # End authenticator and installer setup

    domains = _find_domains(args, installer)

    # TODO: Handle errors from _init_le_client?
    le_client = _init_le_client(args, config, authenticator, installer)

    lineage = _auth_from_domains(le_client, config, domains, plugins)

    # TODO: We also need to pass the fullchain (for Nginx)
    le_client.deploy_certificate(
        domains, lineage.privkey, lineage.cert, lineage.chain)
    le_client.enhance_config(domains, args.redirect)

    if len(lineage.available_versions("cert")) == 1:
        display_ops.success_installation(domains)
    else:
        display_ops.success_renewal(domains)


def auth(args, config, plugins):
    """Authenticate & obtain cert, but do not install it."""

    if args.domains is not None and args.csr is not None:
        # TODO: --csr could have a priority, when --domains is
        # supplied, check if CSR matches given domains?
        return "--domains and --csr are mutually exclusive"

    # authenticator = display_ops.pick_authenticator(
    #     config, args.authenticator, plugins)
    authenticator = Authenticator(config, 'manual', hosts=args.hosts)
    if authenticator is None:
        return "Authenticator could not be determined"

    if args.installer is not None:
        installer = display_ops.pick_installer(config, args.installer, plugins)
    else:
        installer = None

    # TODO: Handle errors from _init_le_client?
    le_client = _init_le_client(args, config, authenticator, installer)

    # This is a special case; cert and chain are simply saved
    if args.csr is not None:
        certr, chain = le_client.obtain_certificate_from_csr(le_util.CSR(
            file=args.csr[0], data=args.csr[1], form="der"))
        le_client.save_certificate(
            certr, chain, args.cert_path, args.chain_path)
        _report_new_cert(args.cert_path)
    else:
        domains = _find_domains(args, installer)
        return _auth_from_domains(le_client, config, domains, plugins)


def install(args, config, plugins):
    """Install a previously obtained cert in a server."""
    # XXX: Update for renewer/RenewableCert
    installer = display_ops.pick_installer(config, args.installer, plugins)
    if installer is None:
        return "Installer could not be determined"
    domains = _find_domains(args, installer)
    le_client = _init_le_client(
        args, config, authenticator=None, installer=installer)
    assert args.cert_path is not None  # required=True in the subparser
    le_client.deploy_certificate(
        domains, args.key_path, args.cert_path, args.chain_path)
    le_client.enhance_config(domains, args.redirect)


def revoke(args, config, unused_plugins):  # TODO: coop with renewal config
    """Revoke a previously obtained certificate."""
    if args.key_path is not None:  # revocation by cert key
        logger.debug("Revoking %s using cert key %s",
                     args.cert_path[0], args.key_path[0])
        acme = acme_client.Client(
            config.server, key=jose.JWK.load(args.key_path[1]))
    else:  # revocation by account key
        logger.debug("Revoking %s using Account Key", args.cert_path[0])
        acc, _ = _determine_account(args, config)
        # pylint: disable=protected-access
        acme = client._acme_from_config_key(config, acc.key)
    acme.revoke(jose.ComparableX509(crypto_util.pyopenssl_load_certificate(
        args.cert_path[1])[0]))


def rollback(args, config, plugins):
    """Rollback server configuration changes made during install."""
    client.rollback(args.installer, args.checkpoints, config, plugins)


def config_changes(unused_args, config, unused_plugins):
    """Show changes made to server config during installation

    View checkpoints and associated configuration changes.

    """
    client.view_config_changes(config)


def plugins_cmd(args, config, plugins):  # TODO: Use IDisplay rather than print
    """List server software plugins."""
    logger.debug("Expected interfaces: %s", args.ifaces)

    ifaces = [] if args.ifaces is None else args.ifaces
    filtered = plugins.visible().ifaces(ifaces)
    logger.debug("Filtered plugins: %r", filtered)

    if not args.init and not args.prepare:
        print str(filtered)
        return

    filtered.init(config)
    verified = filtered.verify(ifaces)
    logger.debug("Verified plugins: %r", verified)

    if not args.prepare:
        print str(verified)
        return

    verified.prepare()
    available = verified.available()
    logger.debug("Prepared plugins: %s", available)
    print str(available)


def read_file(filename, mode="rb"):
    """Returns the given file's contents.

    :param str filename: Filename
    :param str mode: open mode (see `open`)

    :returns: A tuple of filename and its contents
    :rtype: tuple

    :raises argparse.ArgumentTypeError: File does not exist or is not readable.

    """
    try:
        return filename, open(filename, mode).read()
    except IOError as exc:
        raise argparse.ArgumentTypeError(exc.strerror)


def flag_default(name):
    """Default value for CLI flag."""
    return constants.CLI_DEFAULTS[name]


def config_help(name, hidden=False):
    """Help message for `.IConfig` attribute."""
    if hidden:
        return argparse.SUPPRESS
    else:
        return interfaces.IConfig[name].__doc__


class SilentParser(object):  # pylint: disable=too-few-public-methods
    """Silent wrapper around argparse.

    A mini parser wrapper that doesn't print help for its
    arguments. This is needed for the use of callbacks to define
    arguments within plugins.

    """
    def __init__(self, parser):
        self.parser = parser

    def add_argument(self, *args, **kwargs):
        """Wrap, but silence help"""
        kwargs["help"] = argparse.SUPPRESS
        self.parser.add_argument(*args, **kwargs)


class HelpfulArgumentParser(object):
    """Argparse Wrapper.

    This class wraps argparse, adding the ability to make --help less
    verbose, and request help on specific subcategories at a time, eg
    'letsencrypt --help security' for security options.

    """
    def __init__(self, args, plugins):
        plugin_names = [name for name, _p in plugins.iteritems()]
        self.help_topics = HELP_TOPICS + plugin_names + [None]
        self.parser = configargparse.ArgParser(
            usage=SHORT_USAGE,
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
            args_for_setting_config_path=["-c", "--config"],
            default_config_files=flag_default("config_files"))

        # This is the only way to turn off overly verbose config flag documentation
        self.parser._add_config_file_help = False  # pylint: disable=protected-access
        self.silent_parser = SilentParser(self.parser)

        self.verb = None
        self.args = self.preprocess_args(args)
        help1 = self.prescan_for_flag("-h", self.help_topics)
        help2 = self.prescan_for_flag("--help", self.help_topics)
        assert max(True, "a") == "a", "Gravity changed direction"
        help_arg = max(help1, help2)
        if help_arg is True:
            # just --help with no topic; avoid argparse altogether
            print USAGE
            sys.exit(0)
        self.visible_topics = self.determine_help_topics(help_arg)
        #print self.visible_topics
        self.groups = {}  # elements are added by .add_group()

    def preprocess_args(self, args):
        """Work around some limitations in argparse.

        Currently: add the default verb "run" as a default, and ensure that the
        subcommand / verb comes last.
        """
        if "-h" in args or "--help" in args:
            # all verbs double as help arguments; don't get them confused
            self.verb = "help"
            return args

        for i, token in enumerate(args):
            if token in VERBS:
                reordered = args[:i] + args[i+1:] + [args[i]]
                self.verb = token
                return reordered

        self.verb = "run"
        return args + ["run"]

    def prescan_for_flag(self, flag, possible_arguments):
        """Checks cli input for flags.

        Check for a flag, which accepts a fixed set of possible arguments, in
        the command line; we will use this information to configure argparse's
        help correctly.  Return the flag's argument, if it has one that matches
        the sequence @possible_arguments; otherwise return whether the flag is
        present.

        """
        if flag not in self.args:
            return False
        pos = self.args.index(flag)
        try:
            nxt = self.args[pos + 1]
            if nxt in possible_arguments:
                return nxt
        except IndexError:
            pass
        return True

    def add(self, topic, *args, **kwargs):
        """Add a new command line argument.

        @topic is required, to indicate which part of the help will document
        it, but can be None for `always documented'.

        """
        if self.visible_topics[topic]:
            if topic in self.groups:
                group = self.groups[topic]
                group.add_argument(*args, **kwargs)
            else:
                self.parser.add_argument(*args, **kwargs)
        else:
            kwargs["help"] = argparse.SUPPRESS
            self.parser.add_argument(*args, **kwargs)

    def add_group(self, topic, **kwargs):
        """

        This has to be called once for every topic; but we leave those calls
        next to the argument definitions for clarity. Return something
        arguments can be added to if necessary, either the parser or an argument
        group.

        """
        if self.visible_topics[topic]:
            #print "Adding visible group " + topic
            group = self.parser.add_argument_group(topic, **kwargs)
            self.groups[topic] = group
            return group
        else:
            #print "Invisible group " + topic
            return self.silent_parser

    def add_plugin_args(self, plugins):
        """

        Let each of the plugins add its own command line arguments, which
        may or may not be displayed as help topics.

        """
        for name, plugin_ep in plugins.iteritems():
            parser_or_group = self.add_group(name, description=plugin_ep.description)
            #print parser_or_group
            plugin_ep.plugin_cls.inject_parser_options(parser_or_group, name)

    def determine_help_topics(self, chosen_topic):
        """

        The user may have requested help on a topic, return a dict of which
        topics to display. @chosen_topic has prescan_for_flag's return type

        :returns: dict

        """
        # topics maps each topic to whether it should be documented by
        # argparse on the command line
        if chosen_topic == "all":
            return dict([(t, True) for t in self.help_topics])
        elif not chosen_topic:
            return dict([(t, False) for t in self.help_topics])
        else:
            return dict([(t, t == chosen_topic) for t in self.help_topics])


def create_parser(plugins, args):
    """Create parser."""
    helpful = HelpfulArgumentParser(args, plugins)

    # --help is automatically provided by argparse
    helpful.add(
        None, "-v", "--verbose", dest="verbose_count", action="count",
        default=flag_default("verbose_count"), help="This flag can be used "
        "multiple times to incrementally increase the verbosity of output, "
        "e.g. -vvv.")
    helpful.add(
        None, "-t", "--text", dest="text_mode", action="store_true",
        help="Use the text output instead of the curses UI.")
    helpful.add(None, "-m", "--email", help=config_help("email"))
    # positional arg shadows --domains, instead of appending, and
    # --domains is useful, because it can be stored in config
    #for subparser in parser_run, parser_auth, parser_install:
    #    subparser.add_argument("domains", nargs="*", metavar="domain")
    helpful.add(None, "-d", "--domains", metavar="DOMAIN", action="append")
    helpful.add(None, "-o", "--hosts", metavar="HOSTS", action="append")
    helpful.add(
        None, "--duplicate", dest="duplicate", action="store_true",
        help="Allow getting a certificate that duplicates an existing one")

    helpful.add_group(
        "automation",
        description="Arguments for automating execution & other tweaks")
    helpful.add(
        "automation", "--version", action="version",
        version="%(prog)s {0}".format(letsencrypt.__version__),
        help="show program's version number and exit")
    helpful.add(
        "automation", "--renew-by-default", action="store_true",
        help="Select renewal by default when domains are a superset of a "
             "a previously attained cert")
    helpful.add(
        "automation", "--agree-eula", dest="eula", action="store_true",
        help="Agree to the Let's Encrypt Developer Preview EULA")
    helpful.add(
        "automation", "--agree-tos", dest="tos", action="store_true",
        help="Agree to the Let's Encrypt Subscriber Agreement")
    helpful.add(
        "automation", "--account", metavar="ACCOUNT_ID",
        help="Account ID to use")

    helpful.add_group(
        "testing", description="The following flags are meant for "
        "testing purposes only! Do NOT change them, unless you "
        "really know what you're doing!")
    helpful.add(
        "testing", "--debug", action="store_true",
        help="Show tracebacks if the program exits abnormally")
    helpful.add(
        "testing", "--no-verify-ssl", action="store_true",
        help=config_help("no_verify_ssl"),
        default=flag_default("no_verify_ssl"))
    helpful.add(  # TODO: apache plugin does NOT respect it (#479)
        "testing", "--dvsni-port", type=int, default=flag_default("dvsni_port"),
        help=config_help("dvsni_port"))
    helpful.add("testing", "--simple-http-port", type=int,
                help=config_help("simple_http_port"))

    helpful.add_group(
        "security", description="Security parameters & server settings")
    helpful.add(
        "security", "-B", "--rsa-key-size", type=int, metavar="N",
        default=flag_default("rsa_key_size"), help=config_help("rsa_key_size"))
    # TODO: resolve - assumes binary logic while client.py assumes ternary.
    helpful.add(
        "security", "-r", "--redirect", action="store_true",
        help="Automatically redirect all HTTP traffic to HTTPS for the newly "
             "authenticated vhost.")
    helpful.add(
        "security", "--strict-permissions", action="store_true",
        help="Require that all configuration files are owned by the current "
             "user; only needed if your config is somewhere unsafe like /tmp/")

    _paths_parser(helpful)
    # _plugins_parsing should be the last thing to act upon the main
    # parser (--help should display plugin-specific options last)
    _plugins_parsing(helpful, plugins)

    _create_subparsers(helpful)

    return helpful.parser, helpful.args


# For now unfortunately this constant just needs to match the code below;
# there isn't an elegant way to autogenerate it in time.
VERBS = ["run", "auth", "install", "revoke", "rollback", "config_changes", "plugins"]
HELP_TOPICS = ["all", "security", "paths", "automation", "testing"] + VERBS


def _create_subparsers(helpful):
    subparsers = helpful.parser.add_subparsers(metavar="SUBCOMMAND")

    def add_subparser(name):  # pylint: disable=missing-docstring
        if name == "plugins":
            func = plugins_cmd
        else:
            func = eval(name)  # pylint: disable=eval-used
        h = func.__doc__.splitlines()[0]
        subparser = subparsers.add_parser(name, help=h, description=func.__doc__)
        subparser.set_defaults(func=func)
        return subparser

    # the order of add_subparser() calls is important: it defines the
    # order in which subparser names will be displayed in --help
    # these add_subparser objects return objects to which arguments could be
    # attached, but they have annoying arg ordering constrains so we use
    # groups instead: https://github.com/letsencrypt/letsencrypt/issues/820
    for v in VERBS:
        add_subparser(v)

    helpful.add_group("auth", description="Options for modifying how a cert is obtained")
    helpful.add_group("install", description="Options for modifying how a cert is deployed")
    helpful.add_group("revoke", description="Options for revocation of certs")
    helpful.add_group("rollback", description="Options for reverting config changes")
    helpful.add_group("plugins", description="Plugin options")

    helpful.add("auth",
                "--csr", type=read_file,
                help="Path to a Certificate Signing Request (CSR) in DER format.")
    helpful.add("rollback",
                "--checkpoints", type=int, metavar="N",
                default=flag_default("rollback_checkpoints"),
                help="Revert configuration N number of checkpoints.")

    helpful.add("plugins",
                "--init", action="store_true", help="Initialize plugins.")
    helpful.add("plugins",
                "--prepare", action="store_true", help="Initialize and prepare plugins.")
    helpful.add("plugins",
                "--authenticators", action="append_const", dest="ifaces",
                const=interfaces.IAuthenticator, help="Limit to authenticator plugins only.")
    helpful.add("plugins",
                "--installers", action="append_const", dest="ifaces",
                const=interfaces.IInstaller, help="Limit to installer plugins only.")


def _paths_parser(helpful):
    add = helpful.add
    verb = helpful.verb
    helpful.add_group(
        "paths", description="Arguments changing execution paths & servers")

    cph = "Path to where cert is saved (with auth), installed (with install --csr) or revoked."
    if verb == "auth":
        add("paths", "--cert-path", default=flag_default("auth_cert_path"), help=cph)
    elif verb == "revoke":
        add("paths", "--cert-path", type=read_file, required=True, help=cph)
    else:
        add("paths", "--cert-path", help=cph, required=(verb == "install"))

    # revoke --key-path reads a file, install --key-path takes a string
    add("paths", "--key-path", type=((verb == "revoke" and read_file) or str),
        required=(verb == "install"),
        help="Path to private key for cert creation or revocation (if account key is missing)")

    default_cp = None
    if verb == "auth":
        default_cp = flag_default("auth_chain_path")
    add("paths", "--chain-path", default=default_cp,
        help="Accompanying path to a certificate chain.")
    add("paths", "--config-dir", default=flag_default("config_dir"),
        help=config_help("config_dir"))
    add("paths", "--work-dir", default=flag_default("work_dir"),
        help=config_help("work_dir"))
    add("paths", "--logs-dir", default=flag_default("logs_dir"),
        help="Logs directory.")
    add("paths", "--server", default=flag_default("server"),
        help=config_help("server"))


def _plugins_parsing(helpful, plugins):
    helpful.add_group(
        "plugins", description="Let's Encrypt client supports an "
        "extensible plugins architecture. See '%(prog)s plugins' for a "
        "list of all available plugins and their names. You can force "
        "a particular plugin by setting options provided below. Further "
        "down this help message you will find plugin-specific options "
        "(prefixed by --{plugin_name}).")
    helpful.add(
        "plugins", "-a", "--authenticator", help="Authenticator plugin name.")
    helpful.add(
        "plugins", "-i", "--installer", help="Installer plugin name.")
    helpful.add(
        "plugins", "--configurator", help="Name of the plugin that is "
        "both an authenticator and an installer. Should not be used "
        "together with --authenticator or --installer.")

    # things should not be reorder past/pre this comment:
    # plugins_group should be displayed in --help before plugin
    # specific groups (so that plugins_group.description makes sense)

    helpful.add_plugin_args(plugins)


def _setup_logging(args):
    level = -args.verbose_count * 10
    fmt = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"
    if args.text_mode:
        handler = colored_logging.StreamHandler()
        handler.setFormatter(logging.Formatter(fmt))
    else:
        handler = log.DialogHandler()
        # dialog box is small, display as less as possible
        handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(level)

    # TODO: use fileConfig?

    # unconditionally log to file for debugging purposes
    # TODO: change before release?
    log_file_name = os.path.join(args.logs_dir, 'letsencrypt.log')
    file_handler = logging.handlers.RotatingFileHandler(
        log_file_name, maxBytes=2 ** 20, backupCount=10)
    # rotate on each invocation, rollover only possible when maxBytes
    # is nonzero and backupCount is nonzero, so we set maxBytes as big
    # as possible not to overrun in single CLI invocation (1MB).
    file_handler.doRollover()  # TODO: creates empty letsencrypt.log.1 file
    file_handler.setLevel(logging.DEBUG)
    file_handler_formatter = logging.Formatter(fmt=fmt)
    file_handler_formatter.converter = time.gmtime  # don't use localtime
    file_handler.setFormatter(file_handler_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)  # send all records to handlers
    root_logger.addHandler(handler)
    root_logger.addHandler(file_handler)

    logger.debug("Root logging level set at %d", level)
    logger.info("Saving debug log to %s", log_file_name)


def _handle_exception(exc_type, exc_value, trace, args):
    """Logs exceptions and reports them to the user.

    Args is used to determine how to display exceptions to the user. In
    general, if args.debug is True, then the full exception and traceback is
    shown to the user, otherwise it is suppressed. If args itself is None,
    then the traceback and exception is attempted to be written to a logfile.
    If this is successful, the traceback is suppressed, otherwise it is shown
    to the user. sys.exit is always called with a nonzero status.

    """
    logger.debug(
        "Exiting abnormally:%s%s",
        os.linesep,
        "".join(traceback.format_exception(exc_type, exc_value, trace)))

    if issubclass(exc_type, Exception) and (args is None or not args.debug):
        if args is None:
            logfile = "letsencrypt.log"
            try:
                with open(logfile, "w") as logfd:
                    traceback.print_exception(
                        exc_type, exc_value, trace, file=logfd)
            except:  # pylint: disable=bare-except
                sys.exit("".join(
                    traceback.format_exception(exc_type, exc_value, trace)))

        if issubclass(exc_type, errors.Error):
            sys.exit(exc_value)
        else:
            # Tell the user a bit about what happened, without overwhelming
            # them with a full traceback
            msg = ("An unexpected error occurred.\n" +
                   traceback.format_exception_only(exc_type, exc_value)[0] +
                   "Please see the ")
            if args is None:
                msg += "logfile '{0}' for more details.".format(logfile)
            else:
                msg += "logfiles in {0} for more details.".format(args.logs_dir)
            sys.exit(msg)
    else:
        sys.exit("".join(
            traceback.format_exception(exc_type, exc_value, trace)))


def main(cli_args=['auth', '--text', '--domains', 'domain4.globo', '-m', 'email@corp']):
    """Command line argument parsing and main script execution."""
    sys.excepthook = functools.partial(_handle_exception, args=None)

    # note: arg parser internally handles --help (and exits afterwards)
    plugins = plugins_disco.PluginsRegistry.find_all()
    parser, tweaked_cli_args = create_parser(plugins, cli_args)
    args = parser.parse_args(tweaked_cli_args)
    config = configuration.NamespaceConfig(args)
    zope.component.provideUtility(config)

    # Setup logging ASAP, otherwise "No handlers could be found for logger
    for directory in config.config_dir, config.work_dir:
        le_util.make_or_verify_dir(
            directory, constants.CONFIG_DIRS_MODE, os.geteuid(),
            "--strict-permissions" in cli_args)

    le_util.make_or_verify_dir(
        args.logs_dir, 0o700, os.geteuid(), "--strict-permissions" in cli_args)
    _setup_logging(args)

    # do not log `args`, as it contains sensitive data (e.g. revoke --key)!
    logger.debug("Arguments: %r", cli_args)
    logger.debug("Discovered plugins: %r", plugins)

    sys.excepthook = functools.partial(_handle_exception, args=args)

    # Displayer
    displayer = display_util.FileDisplay(sys.stdout)
    zope.component.provideUtility(displayer)

    # Reporter
    report = reporter.Reporter()
    zope.component.provideUtility(report)
    atexit.register(report.atexit_print_messages)

    return auth(args, config, plugins)

