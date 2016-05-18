# Copyright 2016 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime
import os
import threading

import redis

from rpaas import tasks

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class JobScheduler(threading.Thread):
    """
    Generic Job Scheduler.

    It should run on the API role, as it depends on environment variables for
    working.
    """

    def __init__(self, config=None, *args, **kwargs):
        super(JobScheduler, self).__init__(*args, **kwargs)
        self.daemon = True
        self.config = config or dict(os.environ)
        self.interval = int(self.config.get("JOB_SCHEDULER_RUN_INTERVAL", 30))
        self.last_run_key = self.config.get("JOB_SCHEDULER_LAST_RUN_KEY", "job_scheduler:last_run")
        self.conn = tasks.app.broker_connection().channel().client

    def try_lock(self):
        interval_delta = datetime.timedelta(seconds=self.interval)
        with self.conn.pipeline() as pipe:
            try:
                now = datetime.datetime.utcnow()
                pipe.watch(self.last_run_key)
                last_run = pipe.get(self.last_run_key)
                if last_run:
                    last_run_date = datetime.datetime.strptime(last_run, DATETIME_FORMAT)
                    if now - last_run_date < interval_delta:
                        pipe.unwatch()
                        return False
                pipe.multi()
                pipe.set(self.last_run_key, now.strftime(DATETIME_FORMAT))
                pipe.execute()
                return True
            except redis.WatchError:
                return False

    def run(self):
        raise NotImplementedError()

    def stop(self):
        self.running = False
        self.join()
