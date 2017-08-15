# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import time
import os
from rpaas import scheduler, tasks


class SessionResumption(scheduler.JobScheduler):
    """
    SessionResumption is a thread to renew session keys on host instances.

    """

    def __init__(self, config=None, *args, **kwargs):
        super(SessionResumption, self).__init__(*args, **kwargs)
        self.config = config or dict(os.environ)
        self.interval = int(self.config.get("SESSION_RESUMPTION_RUN_INTERVAL", 300))
        self.last_run_key = self.config.get("SESSION_RESUMPTION_LAST_RUN_KEY", "session_resumption:last_run")

    def run(self):
        self.running = True
        while self.running:
            if self.try_lock():
                tasks.SessionResumptionTask().delay(self.config)
            time.sleep(self.interval / 2)
