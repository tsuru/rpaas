# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os

from rpaas import manager

_manager = None


def get_manager():
    global _manager
    if _manager is None:
        _manager = manager.Manager(dict(os.environ))
    return _manager
