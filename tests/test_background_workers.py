# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B2-T3 (B-LOCK-09, A10): shutdown never loses a live worker."""
import io
import threading
import time
import unittest
from unittest.mock import patch

from spikes.background_workers import drain, stop_all
from spikes.federation_catalog import CatalogScheduler
from spikes.federation_sync import ContentSyncScheduler
from spikes.replication_control import ReplicationScheduler


class Stuck:
    """A run that ignores stopping until released, like a slow peer call."""
    def __init__(self):
        self.entered, self.release, self.calls = threading.Event(), threading.Event(), 0

    def __call__(self, *args, **kwargs):
        self.calls += 1; self.entered.set()
        assert self.release.wait(10)


class SchedulerShutdownTests(unittest.TestCase):
    CASES = ((CatalogScheduler, 'run_automatic'), (ReplicationScheduler, 'run_enabled'),
             (ContentSyncScheduler, 'run_automatic'))

    def scheduler(self, cls, method):
        instance = cls.__new__(cls)
        instance.control = type('Control', (), {})()
        instance.interval, instance.stopping, instance.thread = 60, threading.Event(), None
        stuck = Stuck(); setattr(instance.control, method, stuck)
        return instance, stuck

    def test_unclean_stop_keeps_live_worker_and_prevents_duplicate(self):
        for cls, method in self.CASES:
            with self.subTest(scheduler=cls.__name__):
                scheduler, stuck = self.scheduler(cls, method)
                with patch('spikes.rss_subscription_sync.run_automatic', lambda *a, **k: None):
                    scheduler.start(); self.assertTrue(stuck.entered.wait(5))
                    worker = scheduler.thread
                    self.assertFalse(scheduler.stop(timeout=0.05))
                    self.assertIs(scheduler.thread, worker); self.assertTrue(worker.is_alive())
                    scheduler.start()
                    self.assertIs(scheduler.thread, worker); self.assertEqual(stuck.calls, 1)
                    stuck.release.set()
                    self.assertTrue(scheduler.stop(timeout=5))
                    self.assertIsNone(scheduler.thread); self.assertFalse(worker.is_alive())

    def test_stop_all_signals_first_and_shares_one_deadline(self):
        pairs = [self.scheduler(cls, method) for cls, method in self.CASES]
        log = io.StringIO()
        with patch('spikes.rss_subscription_sync.run_automatic', lambda *a, **k: None):
            for scheduler, stuck in pairs:
                scheduler.start(); self.assertTrue(stuck.entered.wait(5))
            started = time.monotonic()
            result = stop_all(*(s for s, _ in pairs), timeout=0.3, log=log)
            elapsed = time.monotonic() - started
            self.assertTrue(all(s.stopping.is_set() for s, _ in pairs))
            self.assertEqual(set(result.values()), {False})
            self.assertLess(elapsed, 0.3 * len(pairs))  # one shared budget, not a sum
            self.assertEqual(log.getvalue().count('background_worker_unclean'), 3)
            for _, stuck in pairs:
                stuck.release.set()
            self.assertEqual(set(stop_all(*(s for s, _ in pairs), timeout=5, log=log).values()), {True})

    def test_drain_of_absent_or_finished_thread_is_clean(self):
        self.assertEqual(drain(None, 0), (True, None))
        thread = threading.Thread(target=lambda: None); thread.start()
        self.assertEqual(drain(thread, 5), (True, None))


if __name__ == '__main__':
    unittest.main()
