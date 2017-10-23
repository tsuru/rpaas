# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json

from flask import request, Response, Blueprint

from rpaas import (auth, get_manager, storage, manager, tasks, consul_manager)
from rpaas.misc import (validate_name, require_plan, ValidationError)

router = Blueprint('router', __name__, url_prefix='/router')
supported_extra_features = []  # possible values: "cname", "tls", "healthcheck"


@router.url_value_preprocessor
def add_name_prefix(endpoint, values):
    if 'name' in values:
        values['name'] = 'router-{}'.format(values['name'])


@router.route("/backend/<name>", methods=["GET"])
@auth.required
def get_backend(name):
    try:
        addr = get_manager().status(name)
    except storage.InstanceNotFoundError:
        return "Backend not found", 404
    if addr == manager.FAILURE:
        return addr, 500
    if addr == manager.PENDING:
        addr = ""
    return Response(response=json.dumps({"address": addr}), status=200,
                    mimetype="application/json")


@router.route("/backend/<name>", methods=["POST"])
@auth.required
def add_backend(name):
    try:
        validate_name(name)
    except ValidationError as e:
        return str(e), 400
    data = request.get_json()
    if not data:
        return "could not decode body json", 400
    team = data.get('team') or data.get('tsuru.io/app-teamowner')
    plan = data.get('plan')
    if not team:
        return "team name is required", 400
    if require_plan() and not plan:
        return "plan is required", 400
    try:
        get_manager().new_instance(name, team=team,
                                   plan_name=plan)
    except storage.PlanNotFoundError:
        return "invalid plan", 400
    except storage.DuplicateError:
        return "{} backend already exists".format(name), 409
    except manager.QuotaExceededError as e:
        return str(e), 403
    return "", 201


@router.route("/backend/<name>", methods=["PUT"])
@auth.required
def update_backend(name):
    data = request.get_json()
    if not data:
        return "could not decode body json", 400
    plan = data.get('plan')
    if not plan:
        return "Plan is required", 400
    try:
        get_manager().update_instance(name, plan)
    except tasks.NotReadyError as e:
        return "Backend not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Backend not found", 404
    except storage.PlanNotFoundError:
        return "Plan not found", 404
    return "", 204


@router.route("/backend/<name>", methods=["DELETE"])
@auth.required
def delete_backend(name):
    try:
        get_manager().remove_instance(name)
    except storage.InstanceNotFoundError:
        return "Backend not found", 404
    except consul_manager.InstanceAlreadySwappedError:
        return "Instance with swap enabled", 412
    return "", 200


@router.route("/backend/<name>/routes", methods=["GET"])
@auth.required
def list_routes(name):
    try:
        routes = get_manager().list_upstreams(name, name)
        routes = ["http://{}".format(route) for route in routes]
    except tasks.NotReadyError as e:
        return "Backend not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Backend not found", 404
    return Response(response=json.dumps({"addresses": list(routes)}), status=200,
                    mimetype="application/json")


@router.route("/backend/<name>/routes", methods=["POST"])
@auth.required
def add_routes(name):
    data = request.get_json()
    if not data:
        return "could not decode body json", 400
    addresses = data.get('addresses')
    if not addresses:
        return "Addresses cannot be empty", 400
    m = get_manager()
    try:
        m.bind(name, name, router_mode=True)
        m.add_upstream(name, name, addresses, True)
    except tasks.NotReadyError as e:
        return "Backend not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Backend not found", 404
    return "", 200
    # TODO: wait nginx reload and report status?


@router.route("/backend/<name>/routes/remove", methods=["POST"])
@auth.required
def delete_routes(name):
    data = request.get_json()
    if not data:
        return "could not decode body json", 400
    addresses = data.get('addresses')
    if not addresses:
        return "Addresses cannot be empty", 400
    m = get_manager()
    try:
        m.remove_upstream(name, name, addresses)
        routes = m.list_upstreams(name, name)
        if len(routes) < 1:
            m.unbind(name)
    except tasks.NotReadyError as e:
        return "Backend not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Backend not found", 404
    return "", 200
    # TODO: wait nginx reload and report status?


@router.route("/backend/<name>/swap", methods=["POST"])
@auth.required
def swap(name):
    data = request.get_json()
    if not data:
        return "Could not decode body json", 400
    if data.get('cnameOnly'):
        return "Swap cname only not supported", 400
    target_instance = data.get('target')
    if not target_instance:
        return "Target instance cannot be empty", 400
    m = get_manager()
    try:
        m.swap(name, "router-{}".format(target_instance))
    except tasks.NotReadyError as e:
        return "Backend not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Backend not found", 404
    except consul_manager.InstanceAlreadySwappedError:
        return "Instance already swapped", 412
    return "", 200


@router.route("/certificate/<cname>", methods=["GET"])
@auth.required
def get_certificate(cname):
    # TODO: tsuru api must change to also send the backend name.
    pass


@router.route("/certificate/<cname>", methods=["PUT"])
@auth.required
def update_certificate(cname):
    # TODO: tsuru api must change to also send the backend name.
    pass


@router.route("/certificate/<cname>", methods=["DELETE"])
@auth.required
def delete_certificate(cname):
    # TODO: tsuru api must change to also send the backend name.
    pass


@router.route("/support/<feature>", methods=["GET"])
@auth.required
def supports(feature):
    if feature in supported_extra_features:
        return "", 200
    return "", 404
