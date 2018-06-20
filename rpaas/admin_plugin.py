#!/usr/bin/env python

# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.


import argparse
import datetime
import copy
import json
import os
import sys
import time
import urllib
import urllib2
import shlex
from functools import partial

try:
    from bson import json_util
except:
    sys.stderr.write("This plugin requires json_util module\n")
    sys.exit(1)


class CommandNotFoundError(Exception):

    def __init__(self, name):
        super(Exception, self).__init__(name)
        self.name = name

    def __str__(self):
        return """command "{}" not found""".format(self.name)

    def __unicode__(self):
        return unicode(str(self))


class DisplayTable:

    def __init__(self, fields, max_field_width=30):
        self.fields_names = fields
        self.rows = []
        self.fields_widths = []
        self.max_field_width = max_field_width

    def _compute_widths(self):
        widths = [len(field) for field in self.fields_names]
        for row in self.rows:
            for index, value in enumerate(row):
                field_width = max(widths[index], len(value))
                if field_width > self.max_field_width:
                    widths[index] = self.max_field_width
                else:
                    widths[index] = field_width
        self.fields_widths = widths

    def _add_hrule(self):
        bits = []
        bits.append("\n+")
        for field, width in zip(self.fields_names, self.fields_widths):
            bits.append((width + 2) * "-")
            bits.append("+")
        return "".join(bits)

    def _align_left(self, fieldname, width):
        padding_width = width - len(fieldname)
        return fieldname + " " * padding_width

    def _write_row(self, row):
        bits = []
        bits.append("\n|")
        extra_size_row = []
        for field, width in zip(row, self.fields_widths):
            if len(field) > self.max_field_width:
                bits.append(" " + self._align_left(field[:self.max_field_width], width) + " |")
                extra_size_row.append(field[self.max_field_width:])
            else:
                bits.append(" " + self._align_left(field, width) + " |")
                extra_size_row.append("")
        if extra_size_row != ["" for x in self.fields_widths]:
            return "".join(bits) + self._write_row(extra_size_row)
        return "".join(bits)

    def add_row(self, *args):
        row = []
        for value in args:
            if value is None:
                row.append("")
                continue
            row.append(str(value))
        self.rows.append(row)

    def display(self):
        self._compute_widths()
        sys.stdout.write(self._add_hrule())
        sys.stdout.write(self._write_row(self.fields_names))
        sys.stdout.write(self._add_hrule())
        for row in self.rows:
            sys.stdout.write(self._write_row(row))
            sys.stdout.write(self._add_hrule())
        sys.stdout.write("\n")


def handle_plan_flavor(option, args):
    parser = argparse.ArgumentParser(option)
    subparsers = parser.add_subparsers(help="Action to {} option".format(option))
    parser_choice = {}
    for choice in ["list", "remove", "create", "update", "delete", "show"]:
        parser_choice[choice] = subparsers.add_parser(choice)
        parser_choice[choice] = _base_args(None, parser_choice[choice])
    if args and args[0] in ["list", "remove", "create", "update", "delete", "show"]:
        globals().get("{}_plan_flavor".format(args[0]))(option, args, parser_choice[args[0]], parser)
    else:
        parser.parse_args(args)


def list_plan_flavor(option, args, parser_choice, parser):
    parsed_args = parser.parse_args(args)
    service_name = parsed_args.service
    result = proxy_request(service_name, "/admin/{}s".format(option), method="GET")
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    data = json.loads(body)
    sys.stdout.write("List of available {0}s (use {0} show for details):\n\n".format(option))
    for d in data:
        sys.stdout.write("{name}\t\t{description}\n".format(**d))


def create_plan_flavor(option, args, parser_choice, parser):
    service_name, name, description, config = _change_plan_flavor_args(args, parser_choice, parser)
    params = {
        "name": name,
        "description": description,
        "config": json.dumps(config),
    }
    result = proxy_request(service_name, "/admin/{}s".format(option), body=urllib.urlencode(params),
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    if result.getcode() != 201:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("{} successfully created\n".format(option.capitalize()))


def update_plan_flavor(option, args, parser_choice, parser):
    service_name, name, description, config = _change_plan_flavor_args(args, parser_choice, parser)
    data = _retrieve_plan_flavor(option, service_name, name)
    config = _merge_config(data["config"], config)
    params = {
        "description": description,
        "config": json.dumps(config),
    }
    result = proxy_request(service_name, "/admin/{}s/".format(option)+name, body=urllib.urlencode(params),
                           headers={"Content-Type": "application/x-www-form-urlencoded"},
                           method="PUT")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("{} successfully updated\n".format(option.capitalize()))


def delete_plan_flavor(option, args, parser_choice, parser):
    service_name, name = _plan_flavor_arg(option, args, parser_choice, parser)
    result = proxy_request(service_name, "/admin/{}s/".format(option)+name, method="DELETE")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + result.read().strip("\n") + "\n")
        sys.exit(1)
    sys.stdout.write("{} successfully deleted\n".format(option.capitalize()))


def show_plan_flavor(option, args, parser_choice, parser):
    service_name, name = _plan_flavor_arg(option, args, parser_choice, parser)
    data = _retrieve_plan_flavor(option, service_name, name)
    _render_plan_flavor(data)


def _merge_config(current, changes):
    current_copy = copy.deepcopy(current)
    current_copy.update(changes)
    return {k: v for k, v in current_copy.iteritems() if v}


def _retrieve_plan_flavor(option, service_name, name):
    result = proxy_request(service_name, "/admin/{}s/".format(option)+name, method="GET")
    data = result.read().strip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + data + "\n")
        sys.exit(1)
    return json.loads(data)


def _render_plan_flavor(option):
    sys.stdout.write("Name: {name}\nDescription: {description}\n".format(**option))
    sys.stdout.write("Config:\n\n")
    vars = []
    for name, value in option["config"].iteritems():
        vars.append("{}={}".format(name, value))
    for var in sorted(vars):
        sys.stdout.write("  {}\n".format(var))


def _change_plan_flavor_args(args, parser_choice, parser):
    parser_choice.add_argument("-n", "--name", required=True)
    parser_choice.add_argument("-d", "--description", required=True)
    parser_choice.add_argument("-c", "--config", required=True)
    parsed_args = parser.parse_args(args)
    config_parts = shlex.split(parsed_args.config)
    if len(config_parts) < 1:
        sys.stderr.write("ERROR: Invalid config format, supported format is KEY=VALUE\n")
        sys.exit(2)
    config = {}
    for value in config_parts:
        env_parts = value.split("=")
        if len(env_parts) < 2:
            sys.stderr.write("ERROR: Invalid config format, supported format is KEY=VALUE\n")
            sys.exit(2)
        config[env_parts[0]] = "=".join(env_parts[1:])
    return parsed_args.service, parsed_args.name, parsed_args.description, config


def _plan_flavor_arg(option, args, parser_choice, parser):
    parser_choice.add_argument("{}_name".format(option))
    parsed_args = parser.parse_args(args)
    return parsed_args.service, getattr(parsed_args, "{}_name".format(option))


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
    parser = _base_args("set-quota")
    parser.add_argument("-t", "--team", required=True)
    parser.add_argument("-q", "--quota", required=True, type=int)
    parsed_args = parser.parse_args(args)
    result = proxy_request(parsed_args.service, "/admin/quota/"+parsed_args.team,
                           method="POST", body=urllib.urlencode({"quota": parsed_args.quota}))
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    sys.stdout.write("Quota successfully updated.\n")


def list_healings(args):
    parser = _base_args("list-healings")
    parser.add_argument("-n", "--quantity", default=20, required=False, type=int)
    parsed_args = parser.parse_args(args)
    result = proxy_request(parsed_args.service, "/admin/healings?quantity=" + str(parsed_args.quantity),
                           method="GET")
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    try:
        healings_list = []
        healings_list = json.loads(body, object_hook=json_util.object_hook)
    except Exception as e:
        sys.stderr.write("ERROR: invalid json response - {}\n".format(e.message))
        sys.exit(1)
    healings_table = DisplayTable(['Instance', 'Machine', 'Start Time', 'Duration', 'Status'])
    _render_healings_list(healings_table, healings_list)


def restore_instance(args):
    parser = _base_args("restore-instance")
    parser.add_argument("-i", "--instance", required=True)
    parsed_args = parser.parse_args(args)
    result = proxy_request(parsed_args.service, "/admin/restore", method="POST",
                           body=urllib.urlencode({"instance_name": parsed_args.instance}),
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
    if result.getcode() == 200:
        for msg in parser_result(result):
            sys.stdout.write(msg)
            sys.stdout.flush()
    else:
        sys.stderr.write("ERROR: " + result.content + "\n")
        sys.exit(1)


def parser_result(fileobj, buffersize=1):
    for chunk in iter(partial(fileobj.read, buffersize), ''):
        yield chunk


def _render_healings_list(healings_table, healings_list):
    for healing in healings_list:
        elapsed_time = None
        if 'end_time' in healing and healing['end_time'] is not None:
            seconds = int((healing['end_time'] - healing['start_time']).total_seconds())
            elapsed_time = '{:02}:{:02}:{:02}'.format(seconds // 3600, seconds % 3600 // 60, seconds % 60)
        start_time = (healing['start_time'] - datetime.timedelta(seconds=time.timezone)).strftime('%b  %d %X')
        healings_table.add_row(healing['instance'], healing['machine'], start_time,
                               elapsed_time, healing.get('status'))
    healings_table.display()


def _base_args(cmd_name, parser=None):
    if not parser:
        parser = argparse.ArgumentParser(cmd_name)
    parser.add_argument("-s", "--service", required=True)
    return parser


def available_commands():
    return {
        "plan": [handle_plan_flavor, "plan"],
        "flavor": [handle_plan_flavor, "flavor"],
        "show-quota": show_quota,
        "set-quota": set_quota,
        "list-healings": list_healings,
        "restore-instance": restore_instance
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
        if isinstance(command, list):
            command[0](command[1], args)
        else:
            command(args)
    except CommandNotFoundError as e:
        help_commands()
        sys.stderr.write(unicode(e) + u"\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
