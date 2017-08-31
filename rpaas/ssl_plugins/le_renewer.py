# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import time
import os

from rpaas import tasks, scheduler


class LeRenewer(scheduler.JobScheduler):
    """
    LeRenewer is a thread that prevents certificate LE expiration. It just adds
    a task to the queue, so workers can properly do the job.

    It should run on the API role, as it depends on environment variables for
    working.
    """

    def __init__(self, config=None, *args, **kwargs):
        super(LeRenewer, self).__init__(config, *args, **kwargs)
        self.config = config or dict(os.environ)
        self.interval = int(self.config.get("LE_RENEWER_RUN_INTERVAL", 86400))
        self.last_run_key = self.get_last_run_key("LE_RENEWER")

    def run(self):
        self.running = True
        while self.running:
            if self.try_lock():
                tasks.RenewCertsTask().delay(self.config)
            time.sleep(self.interval / 2)
