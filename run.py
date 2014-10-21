# Copyright 2014 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

from rpaas import api

api.api.run(debug=True, host='0.0.0.0', port=8888)
