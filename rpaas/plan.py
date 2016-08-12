# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.


class InvalidPlanError(Exception):

    def __init__(self, field):
        self.field = field

    def __unicode__(self):
        return u"invalid plan - {} is required".format(self.field)


class Plan(object):
    def __init__(self, name, description, config):
        self.name = name
        self.description = description
        self.config = config

    def validate(self):
        if not self.name:
            raise InvalidPlanError("name")
        if not self.description:
            raise InvalidPlanError("description")
        if not self.config:
            raise InvalidPlanError("config")

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "config": self.config}
