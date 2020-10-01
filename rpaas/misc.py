# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import re
import urlparse


class ValidationError(Exception):
    pass

#Function that checks whether the option passed as a parameter is enabled or not
def check_option_enable(option):
    if option is not None and str(option) in ('True', 'true', '1'):
        return True
    return False

#Function that does the name validation
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
