# -*- coding: utf-8 -*-

import glob

from abc import ABCMeta, abstractmethod
from os.path import dirname, basename, isfile


class BaseSSLPlugin(object):
    __metaclass__ = ABCMeta

    @abstractmethod
    def __init__(self, domain, *args, **kwargs):
        pass

    @abstractmethod
    def upload_csr(self, *args, **kwargs):
        raise NotImplementedError()

    @abstractmethod
    def download_crt(self, *args, **kwargs):
        raise NotImplementedError()

    @abstractmethod
    def revoke(self):
        raise NotImplementedError()

modules = glob.glob(dirname(__file__)+"/*.py")
__all__ = [basename(f)[:-3] for f in modules if isfile(f)]
