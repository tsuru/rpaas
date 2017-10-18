# Copyright 2017 rpaas authors. All rights reserved.
# Use of this source code is governed by a BSD-style
# license that can be found in the LICENSE file.

import redis
import unittest
import time
from rpaas import lock


class LockManagerTestCase(unittest.TestCase):

    def setUp(self):
        self.redis_conn = redis.StrictRedis()
        self.redis_conn.flushall()

    def test_create_lock_when_empty_locks(self):
        lock_manager = lock.Lock(self.redis_conn)
        self.assertEqual(len(lock_manager.redis_locks), 0)
        lock_acquire = lock_manager.lock("lock1", 60)
        self.assertEqual(len(lock_manager.redis_locks), 1)
        self.assertTrue(lock_acquire)
        self.assertEqual(lock_manager.redis_locks[0].name, "lock1")

    def test_create_lock_try_to_acquire_lock_in_use(self):
        lock_manager = lock.Lock(self.redis_conn)
        lock_acquire = lock_manager.lock("lock1", 60)
        lock_acquire = lock_manager.lock("lock1", 60)
        self.assertEqual(len(lock_manager.redis_locks), 1)
        self.assertFalse(lock_acquire)

    def test_create_multiple_locks(self):
        lock_manager = lock.Lock(self.redis_conn)
        lock_acquire_1 = lock_manager.lock("lock1", 60)
        lock_acquire_2 = lock_manager.lock("lock2", 60)
        lock_acquire_3 = lock_manager.lock("lock3", 60)
        self.assertEqual(len(lock_manager.redis_locks), 3)
        self.assertTrue(lock_acquire_1)
        self.assertTrue(lock_acquire_2)
        self.assertTrue(lock_acquire_3)

    def test_unlock_and_release_lock(self):
        lock_manager = lock.Lock(self.redis_conn)
        lock_manager.lock("lock1", 60)
        lock1 = lock_manager.redis_locks[0]
        lock_manager.unlock("lock1")
        self.assertEqual(len(lock_manager.redis_locks), 0)
        with self.assertRaises(redis.exceptions.LockError) as cm:
            lock1.release()
        self.assertEqual(cm.exception.message, "Cannot release an unlocked lock")

    def test_unlock_and_release_lock_with_multiple_locks(self):
        lock_manager = lock.Lock(self.redis_conn)
        lock_acquire_1 = lock_manager.lock("lock1", 60)
        lock_acquire_2 = lock_manager.lock("lock2", 60)
        lock_acquire_3 = lock_manager.lock("lock3", 60)
        self.assertTrue(lock_acquire_1)
        self.assertTrue(lock_acquire_2)
        self.assertTrue(lock_acquire_3)
        lock2 = lock_manager.redis_locks[1]
        self.assertEqual(lock2.name, "lock2")
        lock_manager.unlock("lock2")
        self.assertEqual(len(lock_manager.redis_locks), 2)
        lock_acquire_1 = lock_manager.lock("lock1", 60)
        lock_acquire_2 = lock_manager.lock("lock2", 60)
        lock_acquire_3 = lock_manager.lock("lock3", 60)
        self.assertFalse(lock_acquire_1)
        self.assertTrue(lock_acquire_2)
        self.assertFalse(lock_acquire_3)

    def test_extend_lock_extra_time(self):
        lock_manager = lock.Lock(self.redis_conn)
        lock_acquire = lock_manager.lock("lock1", 1)
        time.sleep(2)
        with self.assertRaises(redis.exceptions.LockError) as cm:
            lock_manager.extend_lock("lock1", 30)
        self.assertEqual(cm.exception.message, "Cannot extend a lock that's no longer owned")
        self.assertTrue(lock_acquire)
        lock_1 = lock_manager.redis_locks[0]
        lock_1.acquire(blocking=False)
        lock_manager.extend_lock("lock1", 30)
        time.sleep(3)
        self.assertFalse(lock_1.acquire(blocking=False))
