# -*- coding: utf-8 -*-

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

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

_plugins = {}


def register_plugins():
    from . import default, le
    _plugins["le"] = le.LE
    _plugins["default"] = default.Default


def get(name):
    return _plugins.get(name)
