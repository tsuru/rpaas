# Copyright 2014 varnishapi authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import functools
import os

import flask


def check_auth(auth):
    username = os.environ.get("API_USERNAME")
    password = os.environ.get("API_PASSWORD")
    if not username or not password:
        return True
    return auth and auth.username == username and auth.password == password


def required(fn):
    @functools.wraps(fn)
    def decorated(*args, **kwargs):
        auth = flask.request.authorization
        if not check_auth(auth):
            return "you do not have access to this resource", 401
        return fn(*args, **kwargs)
    return decorated
