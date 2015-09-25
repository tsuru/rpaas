# -*- coding: utf-8 -*-
from os.path import dirname, basename, isfile
import glob
from abc import ABCMeta, abstractmethod


class BaseSSLPlugin(object):
	__metaclass__ = ABCMeta

	@abstractmethod
	def __init__(self, *args, **kwargs):
		pass

	@abstractmethod
	def auth(self, username, password, *args, **kwargs):
		raise NotImplementedError()

	@abstractmethod
	def upload_csr(self, *args, **kwargs):
		raise NotImplementedError()

	@abstractmethod
	def download_crt(self, *args, **kwargs):
		raise NotImplementedError()


modules = glob.glob(dirname(__file__)+"/*.py")
__all__ = [ basename(f)[:-3] for f in modules if isfile(f)]