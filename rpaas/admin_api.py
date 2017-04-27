# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json
from bson import json_util

from flask import request, Response

from rpaas import auth, get_manager, storage, plan


@auth.required
def healings():
    manager = get_manager()
    quantity = request.args.get("quantity", type=int)
    if quantity is None or quantity <= 0:
        quantity = 20
    healing_list = manager.storage.list_healings(quantity)
    return json.dumps(healing_list, default=json_util.default)


@auth.required
def create_plan():
    name = request.form.get("name")
    description = request.form.get("description")
    config = json.loads(request.form.get("config", "null"))
    manager = get_manager()
    p = plan.Plan(name=name, description=description, config=config)
    try:
        manager.storage.store_plan(p)
    except storage.DuplicateError:
        return "plan already exists", 409
    except plan.InvalidPlanError as e:
        return unicode(e), 400
    return "", 201


@auth.required
def retrieve_plan(name):
    manager = get_manager()
    try:
        plan = manager.storage.find_plan(name)
    except storage.PlanNotFoundError:
        return "plan not found", 404
    return json.dumps(plan.to_dict())


@auth.required
def update_plan(name):
    description = request.form.get("description")
    config = json.loads(request.form.get("config", "null"))
    manager = get_manager()
    try:
        manager.storage.update_plan(name, description, config)
    except storage.PlanNotFoundError:
        return "plan not found", 404
    return ""


@auth.required
def delete_plan(name):
    manager = get_manager()
    try:
        manager.storage.delete_plan(name)
    except storage.PlanNotFoundError:
        return "plan not found", 404
    return ""


@auth.required
def view_team_quota(team_name):
    manager = get_manager()
    used, quota = manager.storage.find_team_quota(team_name)
    return json.dumps({"used": used, "quota": quota})


@auth.required
def set_team_quota(team_name):
    quota = request.form.get("quota", "")
    try:
        quota = int(quota)
        if quota < 1:
            raise ValueError()
    except ValueError:
        return "quota must be an integer value greather than 0", 400
    manager = get_manager()
    manager.storage.set_team_quota(team_name, quota)
    return ""


@auth.required
def restore_instance():
    instance_name = request.form.get("instance_name")
    if not instance_name:
        return "instance name required", 400
    manager = get_manager()
    return Response(manager.restore_instance(instance_name), content_type='event/stream')


def register_views(app, list_plans):
    app.add_url_rule("/admin/healings", methods=["GET"],
                     view_func=healings)
    app.add_url_rule("/admin/plans", methods=["GET"],
                     view_func=list_plans)
    app.add_url_rule("/admin/plans", methods=["POST"],
                     view_func=create_plan)
    app.add_url_rule("/admin/plans/<name>", methods=["GET"],
                     view_func=retrieve_plan)
    app.add_url_rule("/admin/plans/<name>", methods=["PUT"],
                     view_func=update_plan)
    app.add_url_rule("/admin/plans/<name>", methods=["DELETE"],
                     view_func=delete_plan)
    app.add_url_rule("/admin/quota/<team_name>", methods=["GET"],
                     view_func=view_team_quota)
    app.add_url_rule("/admin/quota/<team_name>", methods=["POST"],
                     view_func=set_team_quota)
    app.add_url_rule("/admin/restore", methods=["POST"],
                     view_func=restore_instance)
