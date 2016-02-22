# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import os
import time
from rpaas import scheduler, tasks


class RestoreMachine(scheduler.JobScheduler):
    """
    RestoreMachine is a thread for execute restore machine jobs.

    """

    def __init__(self, config=None, *args, **kwargs):
        super(RestoreMachine, self).__init__(*args, **kwargs)
        self.config = config or dict(os.environ)
        self.interval = int(self.config.get("RESTORE_MACHINE_RUN_INTERVAL", 30))
        self.last_run_key = self.config.get("RESTORE_MACHINE_LAST_RUN_KEY", "restore_machine:last_run")

    def run(self):
        self.running = True
        while self.running:
            if self.try_lock():
                tasks.RestoreMachineTask().delay(self.config)
            time.sleep(self.interval / 2)
