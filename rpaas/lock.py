# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.


class Lock(object):

    def __init__(self, redis_conn):
        self.redis_conn = redis_conn
        self.redis_locks = []

    def lock(self, lock_name, timeout):
        position = self._find_lock_pos(lock_name)
        if position is not None:
            return self.redis_locks[position].acquire(blocking=False)
        self.redis_locks.append(self.redis_conn.lock(name=lock_name, timeout=timeout, blocking_timeout=1))
        position = self._find_lock_pos(lock_name)
        return self.redis_locks[position].acquire(blocking=False)

    def unlock(self, lock_name):
        position = self._find_lock_pos(lock_name)
        if position is not None:
            self.redis_locks[position].release()
            del self.redis_locks[position]

    def extend_lock(self, lock_name, extra_time):
        position = self._find_lock_pos(lock_name)
        if position is not None:
            self.redis_locks[position].extend(extra_time)

    def _find_lock_pos(self, lock_name):
        if not self.redis_locks:
            return None
        position = [i for i, x in enumerate(self.redis_locks) if x.name == lock_name]
        if position:
            return position.pop()
        return None
