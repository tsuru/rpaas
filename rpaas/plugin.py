#!/usr/bin/env python

# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import argparse
import os
import urllib2
import sys
import uuid
import io


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
    result = proxy_request(args.instance, rpaas_path,
                           body=body,
                           headers={'Content-Type': content_type})
    if result.getcode() == 200:
        sys.stdout.write("Certificate successfully updated\n")
    else:
        msg = result.read().rstrip("\n")
        sys.stderr.write("ERROR: " + msg + "\n")
        sys.exit(1)


def get_certificate_args(args):
    parser = argparse.ArgumentParser("certificate")
    parser.add_argument("-i", "--instance", required=True, help="Service instance name")
    parser.add_argument("-c", "--certificate", required=True, help="Certificate file name")
    parser.add_argument("-k", "--key", required=True, help="Key file name")
    parsed = parser.parse_args(args)
    return parsed


def get_scale_args(args):
    parser = argparse.ArgumentParser("scale")
    parser.add_argument("-i", "--instance", required=True)
    parser.add_argument("-n", "--quantity", type=int, required=True)
    parsed_args = parser.parse_args(args)
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


def proxy_request(instance_name, path, body=None, headers=None):
    target = get_env("TSURU_TARGET").rstrip("/")
    token = get_env("TSURU_TOKEN")
    url = "{}/services/proxy/{}?callback={}".format(target, instance_name,
                                                    path)
    request = urllib2.Request(url)
    request.add_header("Authorization", "bearer " + token)
    if body:
        request.add_data(body)
    if headers:
        for key, value in headers.items():
            request.add_header(key, value)
    return urllib2.urlopen(request)


commands = {
    "scale": scale,
    "certificate": certificate,
}


def get_command(name):
    command = commands.get(name)
    if not command:
        raise CommandNotFoundError(name)
    return command


def help_commands():
    sys.stderr.write('Available commands:\n')
    for key in commands.keys():
        sys.stderr.write(' {}\n'.format(key))


def main():
    if len(sys.argv) < 2:
        help_commands()
        return
    cmd, args = sys.argv[1], sys.argv[2:]
    try:
        command = get_command(cmd)
        command(args)
    except CommandNotFoundError as e:
        help_commands()
        sys.stderr.write(unicode(e) + u"\n")
        sys.exit(2)

if __name__ == "__main__":
    main()
