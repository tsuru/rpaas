# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os

from rpaas import manager


def get_manager():
    return manager.Manager(dict(os.environ))
