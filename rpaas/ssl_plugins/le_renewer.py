# Copyright 2015 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import datetime
import os
import threading
import time

import redis

from rpaas import tasks

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


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
        self.last_run_key = self.config.get("LE_RENEWER_LAST_RUN_KEY", "le_renewer:last_run")
        self.conn = redis.StrictRedis(host=tasks.redis_host, port=tasks.redis_port,
                                      password=tasks.redis_password)

    def run(self):
        self.running = True
        while self.running:
            if self.try_lock():
                tasks.RenewCertsTask().delay(self.config)
            time.sleep(self.interval / 2)

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

    def stop(self):
        self.running = False
        self.join()
