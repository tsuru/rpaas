# Copyright 2014 varnishapi authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import inspect
import json
import os

from flask import Flask, Response, request

from rpaas import auth, plugin, manager, storage


api = Flask(__name__)
api.debug = os.environ.get("API_DEBUG", "0") in ("True", "true", "1")


@api.route("/resources", methods=["POST"])
@auth.required
def add_instance():
    name = request.form.get("name")
    if not name:
        return "name is required", 400
    get_manager().new_instance(name)
    return "", 201


@api.route("/resources/<name>", methods=["DELETE"])
@auth.required
def remove_instance(name):
    try:
        get_manager().remove_instance(name)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return "", 200


@api.route("/resources/<name>", methods=["POST"])
@auth.required
def bind(name):
    app_host = request.form.get("app-host")
    if not app_host:
        return "app-host is required", 400
    try:
        get_manager().bind(name, app_host)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return Response(response="null", status=201,
                    mimetype="application/json")


@api.route("/resources/<name>/hostname/<host>", methods=["DELETE"])
@auth.required
def unbind(name, host):
    try:
        get_manager().unbind(name, host)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return "", 200


@api.route("/resources/<name>", methods=["GET"])
@auth.required
def info(name):
    try:
        info = get_manager().info(name)
        if "secret" in info:
            del info["secret"]
        return Response(response=json.dumps(info), status=200,
                        mimetype="application/json")
    except storage.InstanceNotFoundError:
        return "Instance not found", 404


@api.route("/resources/<name>/status", methods=["GET"])
@auth.required
def status(name):
    states = {"started": 204, "pending": 202, "scaling": 204}
    try:
        status = get_manager().status(name)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return status, states.get(status, 500)


@api.route("/resources/<name>/scale", methods=["POST"])
@auth.required
def scale_instance(name):
    quantity = request.form.get("quantity")
    if not quantity:
        return "missing quantity", 400
    try:
        get_manager().scale_instance(name, int(quantity))
    except ValueError as e:
        msg = " ".join(e.args)
        if "invalid literal" in msg:
            return "invalid quantity: %s" % quantity, 400
        return msg, 400
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return "", 201


@api.route("/plugin", methods=["GET"])
def get_plugin():
    return inspect.getsource(plugin)


def get_manager():
    return manager.Manager()
