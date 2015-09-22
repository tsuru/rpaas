# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.


class Plan(object):
    def __init__(self, name, description, config):
        self.name = name
        self.description = description
        self.config = config

    def to_dict(self):
        return {"name": self.name,
                "description": self.description,
                "config": self.config}
