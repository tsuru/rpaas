# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import json

from flask import request

from rpaas import auth, get_manager, storage, plan


@auth.required
def create_plan():
    manager = get_manager()
    p = plan.Plan(**request.json)
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
    manager = get_manager()
    try:
        manager.storage.update_plan(name, **request.json)
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


def register_views(app, list_plans):
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
