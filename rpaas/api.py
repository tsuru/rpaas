# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import inspect
import json
import os
import logging

from flask import Flask, Response, request
import hm.log

from rpaas import auth, plugin, manager, storage


api = Flask(__name__)
api.debug = os.environ.get("API_DEBUG", "0") in ("True", "true", "1")
handler = logging.StreamHandler()
if api.debug:
    logging.basicConfig(level=logging.DEBUG)
    handler.setLevel(logging.DEBUG)
else:
    handler.setLevel(logging.WARN)
api.logger.addHandler(handler)
hm.log.set_handler(handler)


@api.route("/resources/plans", methods=["GET"])
@auth.required
def plans():
    plans = get_manager().storage.list_plans()
    return json.dumps([p.to_dict() for p in plans])


@api.route("/resources", methods=["POST"])
@auth.required
def add_instance():
    name = request.form.get("name")
    if not name:
        return "name is required", 400
    team = request.form.get("team")
    if not team:
        return "team name is required", 400
    try:
        get_manager().new_instance(name, team=team)
    except storage.DuplicateError:
        return "{} instance already exists".format(name), 409
    except manager.QuotaExceededError as e:
        return str(e), 403
    return "", 201


@api.route("/resources/<name>", methods=["DELETE"])
@auth.required
def remove_instance(name):
    try:
        get_manager().remove_instance(name)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return "", 200


@api.route("/resources/<name>/bind-app", methods=["POST"])
@auth.required
def bind(name):
    app_host = request.form.get("app-host")
    if not app_host:
        return "app-host is required", 400
    try:
        get_manager().bind(name, app_host)
    except manager.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return Response(response="null", status=201,
                    mimetype="application/json")


@api.route("/resources/<name>/bind-app", methods=["DELETE"])
@auth.required
def unbind(name):
    app_host = request.form.get("app-host")
    if not app_host:
        return "app-host is required", 400
    try:
        get_manager().unbind(name, app_host)
    except manager.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return "", 200


@api.route("/resources/<name>/bind", methods=["POST"])
@auth.required
def bind_unit(name):
    return "", 201


@api.route("/resources/<name>/bind", methods=["DELETE"])
@auth.required
def unbind_unit(name):
    return "", 200


@api.route("/resources/<name>", methods=["GET"])
@auth.required
def info(name):
    try:
        info = get_manager().info(name)
        return Response(response=json.dumps(info), status=200,
                        mimetype="application/json")
    except storage.InstanceNotFoundError:
        return "Instance not found", 404


@api.route("/resources/<name>/status", methods=["GET"])
@auth.required
def status(name):
    try:
        status = get_manager().status(name)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    if status == manager.FAILURE:
        return status, 500
    if status == manager.PENDING:
        return status, 202
    return status, 204


@api.route("/resources/<name>/scale", methods=["POST"])
@auth.required
def scale_instance(name):
    quantity = request.form.get("quantity")
    if not quantity:
        return "missing quantity", 400
    try:
        get_manager().scale_instance(name, int(quantity))
    except manager.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except ValueError as e:
        msg = " ".join(e.args)
        if "invalid literal" in msg:
            return "invalid quantity: %s" % quantity, 400
        return msg, 400
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return "", 201


@api.route("/resources/<name>/certificate", methods=["POST"])
@auth.required
def update_certificate(name):
    cert = request.form.get('cert')
    if cert is None:
        cert = request.files['cert'].read()
    key = request.form.get('key')
    if key is None:
        key = request.files['key'].read()
    try:
        get_manager().update_certificate(name, cert, key)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except manager.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "", 200


@api.route("/resources/<name>/route", methods=["POST"])
@auth.required
def add_route(name):
    path = request.form.get('path')
    if not path:
        return 'missing path', 400
    destination = request.form.get('destination')
    content = request.form.get('content')
    if not destination and not content:
        return 'either content xor destination are required', 400
    if destination and content:
        return 'cannot have both content and destination', 400
    try:
        get_manager().add_route(name, path, destination, content)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except manager.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "", 201


@api.route("/resources/<name>/route", methods=["DELETE"])
@auth.required
def delete_route(name):
    path = request.form.get('path')
    if not path:
        return 'missing path', 400
    try:
        get_manager().delete_route(name, path)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except manager.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "", 200


@api.route("/resources/<name>/route", methods=["GET"])
@auth.required
def list_routes(name):
    try:
        info = get_manager().list_routes(name)
        return Response(response=json.dumps(info), status=200,
                        mimetype="application/json")
    except storage.InstanceNotFoundError:
        return "Instance not found", 404


@api.route("/plugin", methods=["GET"])
def get_plugin():
    return inspect.getsource(plugin)


def get_manager():
    return manager.Manager(dict(os.environ))


def main():
    api.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8888)))


if __name__ == '__main__':
    main()
