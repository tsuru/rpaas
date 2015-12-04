#!/usr/bin/env python

# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import argparse
import os
import urllib
import urllib2
import sys
import uuid
import io
import json
import urlparse


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
        msg = result.read().rstrip("\n")
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
        msg = result.read().rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


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
        method = "POST"
        message = "added"
    elif args.action == 'remove':
        params['path'] = args.path
        method = "DELETE"
        message = "removed"
    body = urllib.urlencode(params)
    result = proxy_request(args.service, args.instance, req_path,
                           body=body,
                           method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if result.getcode() in [200, 201]:
        if args.action == 'list':
            parsed = json.loads(result.read())
            routes = parsed.get('routes') or []
            out = ["path: destination", ""]
            for route in routes:
                out.append("{}: {}".format(route.get('path'), route.get('destination')))
            sys.stdout.write('\n'.join(out) + '\n')
        else:
            sys.stdout.write("route successfully {}\n".format(message))
    else:
        msg = result.read().rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


def purge(args):
    service, instance, path = get_purge_args(args)
    req_path = "/resources/{}/purge".format(instance)
    params = {}
    method = "POST"
    params['path'] = path
    body = urllib.urlencode(params)
    result = proxy_request(service, instance, req_path,
                           body=body,
                           method=method,
                           headers={'Content-Type': 'application/x-www-form-urlencoded'})
    if result.getcode() == 200:
        sys.stdout.write(result.read() + '\n')
    else:
        msg = result.read().rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
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
    parser.add_argument("-a", "--auth", required=False, help="Authorization plugin")
    parsed = parser.parse_args(args)
    return parsed


def ssl(args):
    args = get_ssl_args(args)
    rpaas_path = "/resources/{}/ssl".format(args.instance)
    params = {}
    params['domain'] = args.domain
    params['plugin'] = args.plugin if 'plugin' in args else 'default'
    body = urllib.urlencode(params)
    method = "POST"
    try:
        result = proxy_request(args.service, args.instance, rpaas_path, body=body, method=method,
                               headers={'Content-Type': 'application/x-www-form-urlencoded'})
    except Exception, e:
        sys.stderr.write("ERROR: "+str(e)+"\n")
        sys.exit(1)
    if result.getcode() in [200, 201]:
        sys.stdout.write("Certificate successfully updated\n")
    else:
        msg = result.read().rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


def get_scale_args(args):
    parser = argparse.ArgumentParser("scale")
    parser.add_argument("-s", "--service", required=True)
    parser.add_argument("-i", "--instance", required=True)
    parser.add_argument("-n", "--quantity", type=int, required=True)
    parsed_args = parser.parse_args(args)
    if parsed_args.quantity < 1:
        sys.stderr.write("quantity must be a positive integer\n")
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


def get_purge_args(args):
    parser = argparse.ArgumentParser("purge")
    parser.add_argument("-s", "--service", required=True, help="Service name")
    parser.add_argument("-i", "--instance", required=True, help="Instance name")
    parser.add_argument("-l", "--location", required=True, help="Location to be purged")
    parsed_args = parser.parse_args(args)
    parsed_url = urlparse.urlparse(parsed_args.location)
    if parsed_url.path == '':
        sys.stderr.write("purge: path is required for purge location\n")
        sys.exit(2)
    if parsed_url.query == '':
        location = parsed_url.path
    else:
        location = "{}?{}".format(parsed_url.path, parsed_url.query)
    return parsed_args.service, parsed_args.instance, location


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
    request = urllib2.Request(url)
    request.add_header("Authorization", "bearer " + token)
    request.get_method = lambda: method
    if body:
        request.add_data(body)
    if headers:
        for key, value in headers.items():
            request.add_header(key, value)
    return urllib2.urlopen(request)


def available_commands():
    return {
        "scale": scale,
        "certificate": certificate,
        "route": route,
        "purge": purge,
        "ssl": ssl,
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
