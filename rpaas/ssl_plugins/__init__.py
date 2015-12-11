# -*- coding: utf-8 -*-

from abc import ABCMeta, abstractmethod


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

__all__ = ["default", "le", "le_authenticator"]
