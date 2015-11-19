#!/usr/bin/env python

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import argparse
import copy
import json
import os
import re
import sys
import urllib
import urllib2

CONFIG_REGEXP = re.compile(r"(\w+=)")


class CommandNotFoundError(Exception):

    def __init__(self, name):
        super(Exception, self).__init__(name)
        self.name = name

    def __str__(self):
        return """command "{}" not found""".format(self.name)

    def __unicode__(self):
        return unicode(str(self))


def list_plans(args):
    service_name = _service_arg(args, "list-plans")
    result = proxy_request(service_name, "/admin/plans", method="GET")
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    plans = json.loads(body)
    sys.stdout.write("List of available plans (use show-plan for details):\n\n")
    for plan in plans:
        sys.stdout.write("{name}\t\t{description}\n".format(**plan))


def create_plan(args):
    service_name, name, description, config = _change_plan_args(args, "create-plan")
    params = {
        "name": name,
        "description": description,
        "config": json.dumps(config),
    }
    result = proxy_request(service_name, "/admin/plans", body=urllib.urlencode(params),
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    if result.getcode() != 201:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("Plan successfully created\n")


def update_plan(args):
    service_name, name, description, config = _change_plan_args(args, "update-plan")
    plan = _retrieve_plan(service_name, name)
    config = _merge_config(plan["config"], config)
    params = {
        "description": description,
        "config": json.dumps(config),
    }
    result = proxy_request(service_name, "/admin/plans/"+name, body=urllib.urlencode(params),
                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                           method="PUT")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("Plan successfully updated\n")


def _merge_config(current, changes):
    current_copy = copy.deepcopy(current)
    current_copy.update(changes)
    return {k: v for k, v in current_copy.iteritems() if v}


def delete_plan(args):
    service_name, name = _plan_arg(args, "delete-plan")
    result = proxy_request(service_name, "/admin/plans/"+name, method="DELETE")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("Plan successfully deleted\n")


def retrieve_plan(args):
    service_name, name = _plan_arg(args, "show-plan")
    plan = _retrieve_plan(service_name, name)
    _render_plan(plan)


def _retrieve_plan(service_name, name):
    result = proxy_request(service_name, "/admin/plans/"+name, method="GET")
    data = result.read().strip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + data + "\n")
        sys.exit(1)
    return json.loads(data)


def _render_plan(plan):
    sys.stdout.write("Name: {name}\nDescription: {description}\n".format(**plan))
    sys.stdout.write("Config:\n\n")
    vars = []
    for name, value in plan["config"].iteritems():
        vars.append("{}={}".format(name, value))
    for var in sorted(vars):
        sys.stdout.write("  {}\n".format(var))


def _change_plan_args(args, cmd_name):
    parser = _base_args(cmd_name)
    parser.add_argument("-n", "--name", required=True)
    parser.add_argument("-d", "--description", required=True)
    parser.add_argument("-c", "--config", required=True)
    parsed_args = parser.parse_args(args)
    config_parts = CONFIG_REGEXP.split(parsed_args.config)[1:]
    if len(config_parts) < 2:
        sys.stderr.write("ERROR: Invalid config format, supported format is KEY=VALUE\n")
        sys.exit(2)
    config = {}
    for i, part in enumerate(config_parts):
        if part.endswith("="):
            value = config_parts[i+1].strip().strip('"').strip("'")
            key = part[:-1]
            config[key] = value
    return parsed_args.service, parsed_args.name, parsed_args.description, config


def _plan_arg(args, cmd_name):
    parser = _base_args(cmd_name)
    parser.add_argument("plan_name")
    parsed_args = parser.parse_args(args)
    return parsed_args.service, parsed_args.plan_name


def show_quota(args):
    parser = _base_args("show-quota")
    parser.add_argument("-t", "--team", required=True)
    parsed_args = parser.parse_args(args)
    result = proxy_request(parsed_args.service, "/admin/quota/"+parsed_args.team,
                           method="GET")
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    quota = json.loads(body)
    sys.stdout.write("Quota usage: {usage}/{total_available}.\n".format(
        usage=len(quota["used"]),
        total_available=quota["quota"],
    ))


def set_quota(args):
    pass


def _base_args(cmd_name):
    parser = argparse.ArgumentParser(cmd_name)
    parser.add_argument("-s", "--service", required=True)
    return parser


def _service_arg(args, cmd_name):
    parser = _base_args(cmd_name)
    parsed_args = parser.parse_args(args)
    return parsed_args.service


def available_commands():
    return {
        "create-plan": create_plan,
        "update-plan": update_plan,
        "delete-plan": delete_plan,
        "show-plan": retrieve_plan,
        "list-plans": list_plans,
        "show-quota": show_quota,
        "set-quota": set_quota,
    }


def get_command(name):
    command = available_commands().get(name)
    if not command:
        raise CommandNotFoundError(name)
    return command


def get_env(name):
    env = os.environ.get(name)
    if not env:
        sys.stderr.write("ERROR: missing {}\n".format(name))
        sys.exit(2)
    return env


def proxy_request(service_name, path, body=None, headers=None, method='POST'):
    target = get_env("TSURU_TARGET").rstrip("/")
    token = get_env("TSURU_TOKEN")
    url = "{}/services/proxy/service/{}?callback={}".format(target, service_name,
                                                            path)
    request = urllib2.Request(url)
    request.add_header("Authorization", "bearer " + token)
    request.get_method = lambda: method
    if body:
        request.add_data(body)
    if headers:
        for key, value in headers.items():
            request.add_header(key, value)
    try:
        return urllib2.urlopen(request)
    except urllib2.HTTPError as e:
        sys.stderr.write("ERROR: {} - {}\n".format(e.code, e.reason))
        sys.stderr.write("       {}\n".format(e.read()))
        sys.exit(1)


def help_commands():
    sys.stderr.write('Available commands:\n')
    for key in available_commands().keys():
        sys.stderr.write(' {}\n'.format(key))


def main(args=None):
    if args is None:
        args = sys.argv[1:]
    if len(args) == 0:
        help_commands()
        return
    cmd, args = args[0], args[1:]
    try:
        command = get_command(cmd)
        command(args)
    except CommandNotFoundError as e:
        help_commands()
        sys.stderr.write(unicode(e) + u"\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
