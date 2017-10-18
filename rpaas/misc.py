# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import re
import urlparse


class ValidationError(Exception):
    pass


def check_option_enable(option):
    if option is not None and str(option) in ('True', 'true', '1'):
        return True
    return False


def validate_name(name):
    if not name or re.search("^[0-9a-z-]+$", name) is None or len(name) > 25:
        raise ValidationError(
            "instance name must match [0-9a-z-] and length up to 25 chars")


def require_plan():
    return "RPAAS_REQUIRE_PLAN" in os.environ


def host_from_destination(destination):
    if '//' not in destination:
        destination = '%s%s' % ('http://', destination)
    return urlparse.urlparse(destination).hostname, urlparse.urlparse(destination).port
