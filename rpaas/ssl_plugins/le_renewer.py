# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import threading
import time

from rpaas import tasks


class LeRenewer(threading.Thread):
    """
    LeRenewer is a thread that prevents certificate LE expiration. It just adds
    a task to the queue, so workers can properly do the job.

    It should run on the API role, as it depends on environment variables for
    working.
    """

    def __init__(self, config=None, *args, **kwargs):
        super(LeRenewer, self).__init__(*args, **kwargs)
        self.daemon = True
        self.config = config or os.environ
        self.interval = int(self.config.get("LE_RENEWER_RUN_INTERVAL", 86400))

    def run(self):
        self.running = True
        while self.running:
            tasks.RenewCertsTask().delay(self.config)
            time.sleep(self.interval)

    def stop(self):
        self.running = False
        self.join()
