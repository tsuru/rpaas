"""Let's Encrypt constants."""
import os
import logging

from acme import challenges
from letsencrypt.constants import *


CLI_DEFAULTS = dict(
    config_files=[
        "./letsencrypt/cli.ini",
        # http://freedesktop.org/wiki/Software/xdg-user-dirs/
        os.path.join(os.environ.get("XDG_CONFIG_HOME", "~/.config"),
                     "letsencrypt", "cli.ini"),
    ],
    verbose_count=-(logging.WARNING / 10),
    server=os.environ.get("RPAAS_PLUGIN_LE_URL", "https://acme-staging.api.letsencrypt.org/directory"),
    rsa_key_size=2048,
    rollback_checkpoints=1,
    config_dir="./letsencrypt",
    work_dir="./letsencrypt",
    logs_dir="./letsencrypt",
    no_verify_ssl=False,
    tls_sni_01_port=challenges.TLSSNI01Response.PORT,

    auth_cert_path="./cert.pem",
    auth_chain_path="./chain.pem",
    strict_permissions=False,
)