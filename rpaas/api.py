# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import inspect
import json
import os
import logging
from socket import gaierror

from flask import Flask, Response, request
from raven.contrib.flask import Sentry
import hm.log

from rpaas import (admin_api, router_api, admin_plugin, auth, get_manager, manager,
                   plugin, storage, tasks)
from rpaas.misc import (validate_name, validate_content, ValidationError, require_plan, check_option_enable)

api = Flask(__name__)
api.register_blueprint(router_api.router)
api.debug = check_option_enable(os.environ.get("API_DEBUG"))
handler = logging.StreamHandler()
if api.debug:
    logging.basicConfig(level=logging.DEBUG)
    handler.setLevel(logging.DEBUG)
else:
    handler.setLevel(logging.WARN)
api.logger.addHandler(handler)
hm.log.set_handler(handler)

if check_option_enable(os.environ.get("RUN_LE_RENEWER")):
    from rpaas.ssl_plugins import le_renewer
    le_renewer.LeRenewer().start()

SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    api.config['SENTRY_DSN'] = SENTRY_DSN
    sentry = Sentry(api)

if check_option_enable(os.environ.get("RUN_RESTORE_MACHINE")):
    from rpaas.healing import RestoreMachine
    RestoreMachine().start()

if check_option_enable(os.environ.get("RUN_RESTORE_MACHINE")) and \
   check_option_enable(os.environ.get("RUN_CHECK_MACHINE")):
    from rpaas.healing import CheckMachine
    CheckMachine().start()

if check_option_enable(os.environ.get("RUN_SESSION_RESUMPTION")):
    from rpaas.session_resumption import SessionResumption
    SessionResumption().start()


@api.route("/resources/plans", methods=["GET"])
@api.route("/resources/<name>/plans", methods=["GET"])
@auth.required
def plans(name=None):
    plans = get_manager().storage.list_plans()
    return json.dumps([p.to_dict() for p in plans])


@api.route("/resources/flavors", methods=["GET"])
@api.route("/resources/<name>/flavors", methods=["GET"])
@auth.required
def flavors(name=None):
    flavors = get_manager().storage.list_flavors()
    return json.dumps([f.to_dict() for f in flavors])


@api.route("/resources", methods=["POST"])
@auth.required
def add_instance():
    if "RPAAS_NEW_SERVICE" in os.environ:
        return "New instance disabled. Use {} service instead".format(os.environ["RPAAS_NEW_SERVICE"]), 405
    name = request.form.get("name")
    try:
        validate_name(name)
    except ValidationError as e:
        return str(e), 400
    team = request.form.get("team")
    if not team:
        return "team name is required", 400
    plan = request.form.get("plan")
    if require_plan() and not plan:
        return "plan is required", 400
    flavor = request.form.get("flavor")
    if not flavor:
        flavor = None
        tags = request.form.getlist("tags")
        for tag in tags:
            if 'flavor:' in tag:
                flavor = tag.split(':')[1]
    try:
        get_manager().new_instance(name, team=team,
                                   plan_name=plan, flavor_name=flavor)
    except storage.PlanNotFoundError:
        return "invalid plan", 400
    except storage.FlavorNotFoundError:
        return "invalid flavor", 400
    except storage.DuplicateError:
        return "{} instance already exists".format(name), 409
    except manager.QuotaExceededError as e:
        return str(e), 403
    return "", 201


@api.route("/resources/<name>", methods=["PUT"])
@auth.required
def update_instance(name):
    plan = request.form.get("plan_name")
    if not plan:
        plan = request.form.get("plan")
    flavor = request.form.get("flavor")
    if not flavor:
        flavor = None
        tags = request.form.getlist("tags")
        for tag in tags:
            if 'flavor:' in tag:
                flavor = tag.split(':')[1]
    if not plan and not flavor:
        return "Plan or flavor is required", 404
    try:
        get_manager().update_instance(name, plan, flavor)
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except storage.PlanNotFoundError:
        return "Plan not found", 404
    except storage.FlavorNotFoundError:
        return "RpaaS flavor not found", 404
    return "", 204


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
    except tasks.NotReadyError as e:
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
        get_manager().unbind(name)
    except tasks.NotReadyError as e:
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


@api.route("/resources/<name>/node_status", methods=["GET"])
@auth.required
def node_status(name):
    try:
        node_status = get_manager().node_status(name)
        return Response(response=json.dumps(node_status), status=200,
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
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except ValueError as e:
        msg = " ".join(e.args)
        if "invalid literal" in msg:
            return "invalid quantity: %s" % quantity, 400
        return msg, 400
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    return "", 201


@api.route("/resources/<name>/restore_machine", methods=["POST"])
@auth.required
def restore_machine(name):
    if not check_option_enable(os.environ.get("RUN_RESTORE_MACHINE")):
        return "Restore machine not enabled", 412
    machine = request.form.get("machine")
    if not machine:
        return "missing machine name", 400
    try:
        get_manager().restore_machine_instance(name, machine)
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except manager.InstanceMachineNotFoundError:
        return "Instance machine not found", 404
    return "", 201


@api.route("/resources/<name>/restore_machine", methods=["DELETE"])
@auth.required
def cancel_restore_machine(name):
    if not check_option_enable(os.environ.get("RUN_RESTORE_MACHINE")):
        return "Restore machine not enabled", 412
    machine = request.form.get("machine")
    if not machine:
        return "missing machine name", 400
    try:
        get_manager().restore_machine_instance(name, machine, True)
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except manager.InstanceMachineNotFoundError:
        return "Instance machine not found", 404
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
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except manager.SslError:
        return "Invalid key or certificate", 412
    return "", 200


@api.route("/resources/<name>/route", methods=["POST"])
@auth.required
def add_route(name):
    path = request.form.get('path')
    if not path:
        return 'missing path', 400
    destination = request.form.get('destination')
    content = request.form.get('content')
    https_only = bool(request.form.get('https_only')) or False
    if not destination and not content:
        return 'either content xor destination are required', 400
    if destination and content:
        return 'cannot have both content and destination', 400
    if content:
        content = content.encode("utf-8")
    try:
        validate_content(content)
    except ValidationError as e:
        return str(e), 400
    try:
        get_manager().add_route(name, path, destination, content, https_only)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except tasks.NotReadyError as e:
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
    except tasks.NotReadyError as e:
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


@api.route("/resources/<name>/block", methods=["POST"])
@auth.required
def add_block(name):
    content = request.form.get('content')
    try:
        validate_content(content)
    except ValidationError as e:
        return str(e), 400
    block_name = request.form.get('block_name')
    if block_name not in ('server', 'http'):
        return 'invalid block_name (valid values are "server" or "http")', 400
    if not content:
        return 'missing content', 400
    try:
        get_manager().add_block(name, block_name, content)
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "", 201


@api.route("/resources/<name>/block/<block_name>", methods=["DELETE"])
@auth.required
def delete_block(name, block_name):
    try:
        get_manager().delete_block(name, block_name)
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "", 200


@api.route("/resources/<name>/block", methods=["GET"])
@auth.required
def list_block(name):
    try:
        blocks = {'blocks': get_manager().list_blocks(name)}
        return Response(response=json.dumps(blocks), status=200,
                        mimetype="application/json")
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412


@api.route("/resources/<name>/purge", methods=["POST"])
def purge_location(name):
    path = request.form.get('path')
    preserve_path = request.form.get('preserve_path')
    if preserve_path in (False, 'False'):
        preserve_path = False
    if not path:
        return 'missing required path', 400
    try:
        instances_purged = get_manager().purge_location(name, path, preserve_path)
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "Path found and purged on {} servers".format(instances_purged), 200


@api.route("/resources/<name>/purge/bulk", methods=["POST"])
def purge_bulk_location(name):
    purges = request.get_json()
    result = []
    if not purges or not isinstance(purges, list):
        return 'missing required list of purges', 400

    for purge in purges:
        path = purge.get("path")
        preserve_path = purge.get("preserve_path", False)
        try:
            instances_purged = get_manager().purge_location(name, path, preserve_path)
            result.append({"path": path, "instances_purged": instances_purged})
        except storage.InstanceNotFoundError:
            return "Instance not found", 404
        except tasks.NotReadyError as e:
            return "Instance not ready: {}".format(e), 412

    response = api.response_class(
        response=json.dumps(result),
        status=200,
        mimetype='application/json'
    )
    return response


@api.route("/resources/<name>/ssl", methods=["POST"])
@auth.required
def add_https(name):
    domain = request.form.get('domain')
    if not domain:
        return "missing domain name", 400
    plugin = request.form.get('plugin', 'default')
    try:
        get_manager().activate_ssl(name, domain, plugin)
        return "", 200
    except storage.InstanceNotFoundError:
        return "Instance not found", 404
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    except gaierror:
        return "can't find domain", 404
    except manager.SslError, e:
        return str(e), 412
    except Exception, e:
        if api.debug:
            raise e
        return 'Unexpected error', 500
    return "", 200


@api.route("/resources/<name>/lua", methods=["POST"])
@auth.required
def add_lua(name):
    content = request.form.get('content')
    lua_module = request.form.get('lua_module_name')
    lua_module_type = request.form.get('lua_module_type')
    if lua_module_type not in ("server", "worker"):
        return 'Lua module type should be server or worker.', 400
    if not lua_module:
        return 'You should provide a lua module name.', 400
    if not content:
        return 'missing content', 400
    try:
        get_manager().add_lua(name, lua_module, lua_module_type, content)
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "", 201


@api.route("/resources/<name>/lua", methods=["GET"])
@auth.required
def list_lua(name):
    try:
        modules = get_manager().list_lua(name)
        return Response(json.dumps({"modules": modules}), status=200, mimetype="application/json")
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412


@api.route("/resources/<name>/lua", methods=["DELETE"])
@auth.required
def delete_lua(name):
    try:
        lua_module = request.form.get('lua_module_name')
        lua_module_type = request.form.get('lua_module_type')
        if lua_module_type not in ("server", "worker"):
            return 'Lua module type should be server or worker.', 400
        if not lua_module:
            return 'You should provide a lua module name.', 400
        get_manager().delete_lua(name, lua_module, lua_module_type)
    except tasks.NotReadyError as e:
        return "Instance not ready: {}".format(e), 412
    return "", 200


@api.route("/plugin", methods=["GET"])
def get_plugin():
    return inspect.getsource(plugin)


@api.route("/admin/plugin", methods=["GET"])
def get_admin_plugin():
    return inspect.getsource(admin_plugin)


admin_api.register_views(api, plans, flavors)


def main():
    api.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8888)))


if __name__ == '__main__':
    main()
