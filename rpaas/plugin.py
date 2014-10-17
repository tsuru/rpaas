#!/usr/bin/env python

# Copyright 2014 varnishapi authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import argparse
import os
import urllib2
import sys


class CommandNotFoundError(Exception):

    def __init__(self, name):
        super(Exception, self).__init__(name)
        self.name = name

    def __str__(self):
        return """command "{}" not found""".format(self.name)

    def __unicode__(self):
        return unicode(str(self))


def scale(args):
    instance, quantity = get_scale_args(args)
    result = proxy_request(instance, "/resources/{}/scale".format(instance),
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


def get_scale_args(args):
    parser = argparse.ArgumentParser("scale")
    parser.add_argument("-i", "--instance")
    parser.add_argument("-n", "--quantity", type=int)
    parsed_args = parser.parse_args(args)
    if parsed_args.instance is None or parsed_args.quantity is None:
        parser.print_usage(sys.stderr)
        sys.exit(2)
    if parsed_args.quantity < 1:
        sys.stderr.write("quantity must be a positive integer\n")
        sys.exit(2)
    return parsed_args.instance, parsed_args.quantity


def get_env(name):
    env = os.environ.get(name)
    if not env:
        sys.stderr.write("ERROR: missing {}\n".format(name))
        sys.exit(2)
    return env


def proxy_request(instance_name, path, body=None):
    target = get_env("TSURU_TARGET").rstrip("/")
    token = get_env("TSURU_TOKEN")
    url = "{}/services/proxy/{}?callback={}".format(target, instance_name,
                                                    path)
    request = urllib2.Request(url)
    request.add_header("Authorization", "bearer " + token)
    if body:
        request.add_data(body)
    return urllib2.urlopen(request)


def get_command(name):
    commands = {
        "scale": scale,
    }
    command = commands.get(name)
    if not command:
        raise CommandNotFoundError(name)
    return command


def main(cmd, args):
    try:
        command = get_command(cmd)
        command(args)
    except CommandNotFoundError as e:
        sys.stderr.write(unicode(e) + u"\n")
        sys.exit(2)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
