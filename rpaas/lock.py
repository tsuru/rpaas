# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.


class Lock(object):

    def __init__(self, redis_conn):
        self.redis_conn = redis_conn

    def lock(self, lock_name, timeout):
        self.redis_lock = self.redis_conn.lock(name=lock_name, timeout=timeout,
                                               blocking_timeout=1)
        return self.redis_lock.acquire(blocking=False)

    def unlock(self):
        self.redis_lock.release()

    def extend_lock(self, extra_time):
        self.redis_lock.extend(extra_time)
