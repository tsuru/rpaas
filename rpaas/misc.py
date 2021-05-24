# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import re
import urlparse
import json


class ValidationError(Exception):
    pass


def check_option_enable(option):
    if option is not None and str(option) in ('True', 'true', '1'):
        return True
    return False


def validate_content(content):
    if not content:
        return
    deny_patterns = os.environ.get("CONFIG_DENY_PATTERNS")
    if not deny_patterns:
        return
    patterns = json.loads(deny_patterns)
    for pattern in patterns:
        if re.search(pattern, content):
            raise ValidationError("content contains the forbidden pattern {}".format(pattern))


def validate_name(name):
    instance_length = None
    if os.environ.get("INSTANCE_LENGTH"):
        instance_length = int(os.environ.get("INSTANCE_LENGTH"))
    if not name or re.search("^[0-9a-z-]+$", name) is None or (instance_length and len(name) > instance_length):
        validation_error_msg = "instance name must match [0-9a-z-]"
        if instance_length:
            validation_error_msg = "{} and length up to {} chars".format(validation_error_msg, instance_length)
        raise ValidationError(validation_error_msg)


def require_plan():
    return "RPAAS_REQUIRE_PLAN" in os.environ


def host_from_destination(destination):
    if '//' not in destination:
        destination = '%s%s' % ('http://', destination)
    return urlparse.urlparse(destination).hostname, urlparse.urlparse(destination).port
