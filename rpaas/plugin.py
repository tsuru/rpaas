#!/usr/bin/env python

# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import argparse
import os
import urllib
import sys
import uuid
import io
import json

try:
    from urllib2 import urlopen, Request, HTTPError
except ImportError:
    from urllib.request import urlopen, Request, HTTPError

try:
    from urlparse import urlparse
except ImportError:
    from urllib.parse import urlparse


def encode_multipart_formdata(files):
    boundary = '----------{}'.format(str(uuid.uuid4()))
    data = []
    for (key, filename, value) in files:
        data.append('--' + boundary)
        data.append('Content-Disposition: form-data; name="{}"; filename="{}"'.format(key, filename))
        data.append('Content-Type: application/octet-stream')
        data.append('')
        data.append(value)
    data.append('--' + boundary + '--')
    data.append('')
    body = '\r\n'.join(data)
    content_type = 'multipart/form-data; boundary={}'.format(boundary)
    return content_type, body


class CommandNotFoundError(Exception):

    def __init__(self, name):
        super(Exception, self).__init__(name)
        self.name = name

    def __str__(self):
        return """command "{}" not found""".format(self.name)

    def __unicode__(self):
        return unicode(str(self))


def scale(args):
    service, instance, quantity = get_scale_args(args)
    result = proxy_request(service, instance, "/resources/{}/scale".format(instance),
                           body="quantity={}".format(quantity))
    if result.getcode() == 201:
        msg = "Instance successfully scaled to {} unit".format(quantity)
        if quantity > 1:
            msg += "s"
        sys.stdout.write(msg + "\n")
    else:
        msg = result.read().decode('utf-8').rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


def update(args):
    service, instance, plan, flavor = get_update_args(args)
    if flavor:
        flavor = "flavor_name={}".format(flavor)
    if plan:
        plan = "plan_name={}".format(plan)
    result = proxy_request(service, instance, "/resources/{}".format(instance),
                           body="{}".format("&".join(filter(None, [plan, flavor]))), method='PUT')
    if result.getcode() == 201:
        msg = "Instance successfully updated"
        sys.stdout.write(msg + "\n")
    else:
        msg = result.read().decode('utf-8').rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


def certificate(args):
    args = get_certificate_args(args)
    rpaas_path = "/resources/{}/certificate".format(args.instance)
    with io.open(args.certificate, 'rb') as f:
        cert = f.read()
    with io.open(args.key, 'rb') as f:
        key = f.read()

    content_type, body = encode_multipart_formdata((
        ('cert', args.certificate, cert),
        ('key', args.key, key),
    ))
    result = proxy_request(args.service, args.instance, rpaas_path,
                           body=body,
                           headers={'Content-Type': content_type})
    if result.getcode() == 200:
        sys.stdout.write("Certificate successfully updated\n")
    else:
        msg = result.read().decode('utf-8').rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


def nginx_block(value):
    if value in ('server', 'http'):
        return value
    raise argparse.ArgumentTypeError('Block must be "server" or "http"')


def route(args):
    args = get_route_args(args)
    req_path = "/resources/{}/route".format(args.instance)
    params = {}
    method = "GET"

    if args.content and args.content.startswith('@'):
        with open(args.content[1:]) as f:
            args.content = f.read()

    if args.action == 'add':
        params['path'] = args.path
        if args.destination:
            params['destination'] = args.destination
        if args.content:
            params['content'] = args.content
        if args.https_only:
            params['https_only'] = True
        method = "POST"
        message = "added"
    elif args.action == 'remove':
        params['path'] = args.path
        method = "DELETE"
        message = "removed"
    try:
        body = urllib.urlencode(params)
    except AttributeError:
        body = urllib.parse.urlencode(params)
    result = proxy_request(args.service, args.instance, req_path,
                           body=body,
                           method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    content = result.read().decode('utf-8').rstrip("\n")
    if result.getcode() in [200, 201]:
        if args.action == 'list':
            parsed = json.loads(content)
            routes = parsed.get('paths') or []
            out = []
            sys.stdout.write("Routes:\n")
            for route in routes:
                out.append("path = {}".format(route.get('path')))
                if route.get('content'):
                    out.append("content = {}".format(route.get('content')))
                    continue
                if route.get('https_only'):
                    out.append("destination = {} (https only)".format(route.get('destination')))
                else:
                    out.append("destination = {}".format(route.get('destination')))
            sys.stdout.write('\n'.join(out) + '\n')
        else:
            sys.stdout.write("route successfully {}\n".format(message))
    else:
        sys.stderr.write("ERROR: " + content + "\n")
        sys.exit(1)


def block(args):
    args = get_block_args(args)
    req_path = "/resources/{}/block".format(args.instance)
    params = {}
    method = "GET"

    if args.content and args.content.startswith('@'):
        with open(args.content[1:]) as f:
            args.content = f.read()

    if args.action == 'add':
        params['block_name'] = args.block_name
        params['content'] = args.content
        method = "POST"
        message = "added"
    elif args.action == 'remove':
        req_path = "{}/{}".format(req_path, args.block_name)
        method = "DELETE"
        message = "removed"
    try:
        body = urllib.urlencode(params)
    except AttributeError:
        body = urllib.parse.urlencode(params)
    result = proxy_request(args.service, args.instance, req_path,
                           body=body,
                           method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    content = result.read().decode('utf-8').rstrip("\n")
    if result.getcode() in [200, 201]:
        if args.action == 'list':
            parsed = json.loads(content)
            blocks = parsed.get('blocks') or []
            out = ["block_name: content", ""]
            for block in blocks:
                out.append("{}: {}".format(block.get('block_name'), block.get('content')))
            sys.stdout.write('\n'.join(out) + '\n')
        else:
            sys.stdout.write("block successfully {}\n".format(message))
    else:
        sys.stderr.write("ERROR: " + content + "\n")
        sys.exit(1)


def nginx_lua_block(value):
    if value in ('server', 'worker'):
        return value
    raise argparse.ArgumentTypeError('Type must be "server" or "worker"')


def get_lua_args(args):
    parser = argparse.ArgumentParser("lua")
    parser.add_argument("action", choices=["add", "list", "remove"],
                        help="Action, add or remove blocks from nginx config")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Instance name")
    parser.add_argument("-t", "--type", required=False,
                        help="Lua module type. Should be server or worker.", type=nginx_lua_block)
    parser.add_argument("-n", "--module-name", required=False, help="Lua module name.")
    parser.add_argument("-c", "--content", required=False,
                        help="Raw lua module content")
    parsed = parser.parse_args(args)
    if parsed.action == 'add' and (not parsed.module_name):
        sys.stderr.write("block_name and content are required\n")
        sys.exit(2)
    return parsed


def lua(args):
    args = get_lua_args(args)
    req_path = "/resources/{}/lua".format(args.instance)
    params = {}
    method = "GET"

    if args.content and args.content.startswith('@'):
        with open(args.content[1:]) as f:
            args.content = f.read()

    if args.action == 'add':
        params['lua_module_name'] = args.module_name
        params['lua_module_type'] = args.type
        params['content'] = args.content
        method = "POST"
        message = "added"
    elif args.action == 'remove':
        params['lua_module_name'] = args.module_name
        params['lua_module_type'] = args.type
        method = "DELETE"
        message = "removed"

    try:
        body = urllib.urlencode(params)
    except AttributeError:
        body = urllib.parse.urlencode(params)
    result = proxy_request(args.service, args.instance, req_path,
                           body=body,
                           method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    content = result.read().decode('utf-8').rstrip("\n")
    if result.getcode() in [200, 201]:
        if args.action == 'list':
            parsed = json.loads(content)
            luas = parsed.get('modules') or []
            out = ["module_name: content", ""]
            for lua in luas:
                out.append("{}: {}".format(lua.get('lua_name'), lua.get('content')))
            sys.stdout.write('\n'.join(out) + '\n')
        else:
            sys.stdout.write("lua module successfully {}\n".format(message))
    else:
        sys.stderr.write("ERROR: " + content + "\n")
        sys.exit(1)


def purge(args):
    service, instance, path, preserve_path = get_purge_args(args)
    req_path = "/resources/{}/purge".format(instance)
    params = {}
    method = "POST"
    params['path'] = path
    params['preserve_path'] = preserve_path
    try:
        body = urllib.urlencode(params)
    except AttributeError:
        body = urllib.parse.urlencode(params)
    result = proxy_request(service, instance, req_path,
                           body=body,
                           method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    content = result.read().decode('utf-8').rstrip("\n")
    if result.getcode() == 200:
        sys.stdout.write(content + '\n')
    else:
        sys.stderr.write("ERROR: " + content + "\n")
        sys.exit(1)


def get_certificate_args(args):
    parser = argparse.ArgumentParser("certificate")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Instance name")
    parser.add_argument("-c", "--certificate", required=True, help="Certificate file name")
    parser.add_argument("-k", "--key", required=True, help="Key file name")
    parsed = parser.parse_args(args)
    return parsed


def get_ssl_args(args):
    parser = argparse.ArgumentParser("ssl")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Service instance name")
    parser.add_argument("-d", "--domain", required=True, help="Registered domain name")
    parser.add_argument("-p", "--plugin", required=False, help="Authorization plugin")
    parsed = parser.parse_args(args)
    return parsed


def get_update_args(args):
    parser = argparse.ArgumentParser("update")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Service instance name")
    parser.add_argument("-p", "--plan", required=False, help="New plan name")
    parser.add_argument("-f", "--flavor", required=False, help="New rpaas flavor name")
    parsed = parser.parse_args(args)
    return parsed.service, parsed.instance, parsed.plan, parsed.flavor


def ssl(args):
    args = get_ssl_args(args)
    rpaas_path = "/resources/{}/ssl".format(args.instance)
    params = {}
    params['domain'] = args.domain
    params['plugin'] = args.plugin if 'plugin' in args else 'default'
    try:
        body = urllib.urlencode(params)
    except AttributeError:
        body = urllib.parse.urlencode(params)
    method = "POST"
    result = proxy_request(args.service, args.instance, rpaas_path, body=body, method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if result.getcode() in [200, 201]:
        sys.stdout.write("Certificate successfully updated\n")
    else:
        msg = result.read().decode('utf-8').rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


def status(args):
    service, instance = get_status_args(args)
    req_path = "/resources/{}/node_status".format(instance)
    method = "GET"
    result = proxy_request(service, instance, req_path,
                           method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    content = result.read().decode('utf-8').rstrip("\n")
    if result.getcode() == 200:
        parsed_vms = json.loads(content)
        out = ["Node Name: Status - Address", ""]
        for vm in parsed_vms:
            address = "*"
            if 'address' in parsed_vms[vm]:
                address = parsed_vms[vm]['address']
            out.append("{}: {} - {}".format(vm, parsed_vms[vm]['status'], address))
        sys.stdout.write('\n'.join(out) + '\n')
    else:
        sys.stderr.write("ERROR: " + content + "\n")
        sys.exit(1)


def info(args):
    service, instance = get_info_args(args)
    result = proxy_request(service, instance, "/resources/{}/plans".format(instance), method="GET")
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    plans = json.loads(body)
    sys.stdout.write("List of available plans:\n\n")
    for plan in plans:
        sys.stdout.write("{name}\t\t{description}\n".format(**plan))
    sys.stdout.write("\n\n")
    result = proxy_request(service, instance, "/resources/{}/flavors".format(instance), method="GET")
    body = result.read().rstrip("\n")
    if result.getcode() != 200:
        sys.stderr.write("ERROR: " + body + "\n")
        sys.exit(1)
    flavors = json.loads(body)
    sys.stdout.write("List of available flavors:\n\n")
    for flavor in flavors:
        sys.stdout.write("{name}\t\t{description}\n".format(**flavor))


def get_info_args(args):
    parser = argparse.ArgumentParser("info")
    parser.add_argument("-s", "--service", required=True)
    parser.add_argument("-i", "--instance", required=True)
    parsed_args = parser.parse_args(args)
    return parsed_args.service, parsed_args.instance


def get_status_args(args):
    parser = argparse.ArgumentParser("status")
    parser.add_argument("-s", "--service", required=True)
    parser.add_argument("-i", "--instance", required=True)
    parsed_args = parser.parse_args(args)
    return parsed_args.service, parsed_args.instance


def get_scale_args(args):
    parser = argparse.ArgumentParser("scale")
    parser.add_argument("-s", "--service", required=True)
    parser.add_argument("-i", "--instance", required=True)
    parser.add_argument("-n", "--quantity", type=int, required=True)
    parsed_args = parser.parse_args(args)
    if parsed_args.quantity < 0:
        sys.stderr.write("quantity should be >= 0\n")
        sys.exit(2)
    return parsed_args.service, parsed_args.instance, parsed_args.quantity


def get_route_args(args):
    parser = argparse.ArgumentParser("route")
    parser.add_argument("action", choices=["add", "list", "remove"],
                        help="Action, add or remove url")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Instance name")
    parser.add_argument("-p", "--path", required=False, help="Path to route")
    parser.add_argument("-d", "--destination", required=False, help="Destination host")
    parser.add_argument("--https_only", required=False, action="store_true",
                        help="Force redirect to https - only for destination")
    parser.add_argument("-c", "--content", required=False,
                        help="(advanced) raw nginx location content")
    parsed = parser.parse_args(args)
    if parsed.action == 'add':
        if not parsed.destination and not parsed.content:
            sys.stderr.write("destination xor content are required to add action\n")
            sys.exit(2)
        if parsed.destination and parsed.content:
            sys.stderr.write("cannot have both destination and content\n")
            sys.exit(3)
    if parsed.action != 'list' and not parsed.path:
        sys.stderr.write("path is required to add/remove action\n")
        sys.exit(2)
    return parsed


def get_block_args(args):
    parser = argparse.ArgumentParser("block")
    parser.add_argument("action", choices=["add", "list", "remove"],
                        help="Action, add or remove blocks from nginx config")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Instance name")
    parser.add_argument("-b", "--block_name", required=False, help="Block in nginx", type=nginx_block)
    parser.add_argument("-c", "--content", required=False,
                        help="Raw nginx block content")
    parsed = parser.parse_args(args)
    if parsed.action == 'add' and (not parsed.block_name or not parsed.content):
        sys.stderr.write("block_name and content are required\n")
        sys.exit(2)
    if parsed.action == 'remove' and not parsed.block_name:
        sys.stderr.write("block_name is required\n")
        sys.exit(2)
    return parsed


def get_purge_args(args):
    parser = argparse.ArgumentParser("purge")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Instance name")
    parser.add_argument("-l", "--location", required=True, help="Location to be purged")
    parser.add_argument("-p", "--preserve_path", required=False, action='store_true',
                        help="Use location as-is for cache key")
    parsed_args = parser.parse_args(args)
    parsed_url = urlparse(parsed_args.location)
    if parsed_url.path == '':
        sys.stderr.write("purge: path is required for purge location\n")
        sys.exit(2)
    if parsed_url.query == '':
        location = parsed_url.path
    else:
        location = "{}?{}".format(parsed_url.path, parsed_url.query)
    if parsed_args.preserve_path:
        location = parsed_args.location
    return parsed_args.service, parsed_args.instance, location, parsed_args.preserve_path


def get_env(name):
    env = os.environ.get(name)
    if not env:
        sys.stderr.write("ERROR: missing {}\n".format(name))
        sys.exit(2)
    return env


def proxy_request(service_name, instance_name, path, body=None, headers=None, method='POST'):
    target = get_env("TSURU_TARGET").rstrip("/")
    token = get_env("TSURU_TOKEN")
    url = "{}/services/{}/proxy/{}?callback={}".format(target, service_name, instance_name,
                                                       path)
    request = Request(url)
    request.add_header("Authorization", "bearer " + token)
    request.get_method = lambda: method
    if body:
        try:
            request.add_data(body)
        except AttributeError:
            request.data = body.encode('utf-8')
    if headers:
        for key, value in headers.items():
            request.add_header(key, value)
    try:
        return urlopen(request)
    except HTTPError as error:
        return error
    except Exception:
        raise


def available_commands():
    return {
        "scale": scale,
        "certificate": certificate,
        "route": route,
        "purge": purge,
        "ssl": ssl,
        "block": block,
        "status": status,
        "update": update,
        "lua": lua,
        "info": info
    }


def get_command(name):
    command = available_commands().get(name)
    if not command:
        raise CommandNotFoundError(name)
    return command


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
