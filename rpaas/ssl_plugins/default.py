# -*- coding: utf-8 -*-
from rpaas.ssl_plugins import BaseSSLPlugin
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
import datetime
import uuid


class Default(BaseSSLPlugin):
	''' Generate self-signed certificate
	'''

	def __init__(self):
		pass

	def auth(self, username, password):
		return True

	def upload_csr(self, csr):
		pass

	def download_crt(self, key=None):
		one_day = datetime.timedelta(1, 0, 0)

		private_key = serialization.load_pem_private_key(
		    key,
		    password=None,
		    backend=default_backend()
		)

		public_key = private_key.public_key()

		builder = x509.CertificateBuilder()
		builder = builder.subject_name(x509.Name([
		    x509.NameAttribute(NameOID.COMMON_NAME, u'tsuru.io'),
		]))
		builder = builder.issuer_name(x509.Name([
		    x509.NameAttribute(NameOID.COMMON_NAME, u'tsuru.io'),
		]))
		builder = builder.not_valid_before(datetime.datetime.today() - one_day)
		builder = builder.not_valid_after(datetime.datetime(2018, 8, 2))
		builder = builder.serial_number(int(uuid.uuid4()))
		builder = builder.public_key(public_key)
		builder = builder.add_extension(
			x509.BasicConstraints(ca=False, path_length=None), critical=True,
		)
		certificate = builder.sign(
			private_key=private_key, algorithm=hashes.SHA256(),
			backend=default_backend()
		)

		return certificate.public_bytes(serialization.Encoding.PEM)