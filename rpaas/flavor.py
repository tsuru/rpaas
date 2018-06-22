# Copyright 2018 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.


class InvalidFlavorError(Exception):

    def __init__(self, field):
        self.field = field

    def __unicode__(self):
        return u"invalid rpaas flavor - {} is required".format(self.field)


class Flavor(object):
    def __init__(self, name, description, config):
        self.name = name
        self.description = description
        self.config = config

    def validate(self):
        if not self.name:
            raise InvalidFlavorError("name")
        if not self.description:
            raise InvalidFlavorError("description")
        if not self.config:
            raise InvalidFlavorError("config")

    def to_dict(self):
        return {"name": self.name, "description": self.description,
                "config": self.config}
