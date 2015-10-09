#!/usr/bin/env python

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import argparse
import json
import os
import re
import sys
import urllib2

SERVICE_NAME = "%(RPAAS_SERVICE_NAME)s"
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
    result = proxy_request("/admin/plans", method="GET")
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    plans = json.loads(body)
    sys.stdout.write("List of available plans (use show-plan for details):\n\n")
    for plan in plans:
        sys.stdout.write("{name}\t\t{description}\n".format(**plan))


def create_plan(args):
    name, description, config = _change_plan_args(args, "create-plan")
    params = {"name": name, "description": description, "config": config}
    result = proxy_request("/admin/plans", body=json.dumps(params),
                           headers={"Content-Type": "application/json"})
    if result.getcode() != 201:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("Plan successfully created\n")


def update_plan(args):
    name, description, config = _change_plan_args(args, "update-plan")
    params = {"description": description, "config": config}
    result = proxy_request("/admin/plans/" + name, body=json.dumps(params),
                           headers={"Content-Type": "application/json"},
                           method="PUT")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("Plan successfully updated\n")


def _change_plan_args(args, cmd_name):
    parser = argparse.ArgumentParser(cmd_name)
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
            value = config_parts[i + 1].strip().strip('"').strip("'")
            if value != "":
                key = part[:-1]
                config[key] = value
    return parsed_args.name, parsed_args.description, config


def delete_plan(args):
    name = _plan_arg(args, "delete-plan")
    result = proxy_request("/admin/plans/" + name, method="DELETE")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("Plan successfully deleted\n")


def retrieve_plan(args):
    name = _plan_arg(args, "show-plan")
    result = proxy_request("/admin/plans/" + name, method="GET")
    data = result.read().strip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + data + "\n")
        sys.exit(1)
    plan = json.loads(data)
    _render_plan(plan)


def _render_plan(plan):
    sys.stdout.write("Name: {name}\nDescription: {description}\n".format(**plan))
    sys.stdout.write("Config:\n\n")
    vars = []
    for name, value in plan["config"].iteritems():
        vars.append("{}={}".format(name, value))
    for var in sorted(vars):
        sys.stdout.write("  {}\n".format(var))


def _plan_arg(args, cmd_name):
    parser = argparse.ArgumentParser(cmd_name)
    parser.add_argument("plan_name")
    parsed_args = parser.parse_args(args)
    return parsed_args.plan_name


def available_commands():
    return {
        "create-plan": create_plan,
        "update-plan": update_plan,
        "delete-plan": delete_plan,
        "show-plan": retrieve_plan,
        "list-plans": list_plans,
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


def proxy_request(path, body=None, headers=None, method='POST'):
    target = get_env("TSURU_TARGET").rstrip("/")
    token = get_env("TSURU_TOKEN")
    url = "{}/services/proxy/service/{}?callback={}".format(target, SERVICE_NAME,
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
