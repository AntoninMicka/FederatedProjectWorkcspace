# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B2-T2: critical sections own state changes, not long work.

Lane separation of RSS view, Julia status/output/cancel and reference
routes is asserted by test_local_api and test_http_ui_admission; this module
covers the narrowed in-process sections and the bounded direct SQLite path.
"""
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.chat_threads import ChatThreads
from spikes.node_telemetry import NodeTelemetry
from spikes.request_ownership import ProjectBusy, bounded_project_requests
from spikes.rss_sources import RSSSources
from spikes.sqlite_ownership import bounded_connect
from tests.test_rss_pilot import rss

CHANNELS = ({'id': 'one', 'name': 'One', 'url': 'https://example.test/one'},)


class Gate:
    """Block exactly one call until released, and report when it is inside."""
    def __init__(self, call):
        self.call, self.inside, self.release, self.used = call, threading.Event(), threading.Event(), False

    def __call__(self, *args, **kwargs):
        if not self.used:
            self.used = True; self.inside.set()
            assert self.release.wait(10)
        return self.call(*args, **kwargs)


def background(call):
    result = []
    worker = threading.Thread(target=lambda: result.append(call())); worker.start()
    return worker, result


class RSSViewScopeTests(unittest.TestCase):
    def test_view_processing_and_store_load_run_outside_cache_mutex(self):
        service = RSSSources(channels=CHANNELS, fetcher=lambda url: rss(url))
        expected = len(service.refresh('one')['entries'])
        self.assertGreater(expected, 0)
        service.store = type('Store', (), {})()
        gate = Gate(lambda: (service.revision, service.channels)); service.store.load = gate
        worker, result = background(service.view)
        try:
            self.assertTrue(gate.inside.wait(10))
            self.assertTrue(service.lock.acquire(blocking=False)); service.lock.release()
        finally:
            gate.release.set(); worker.join(10)
        self.assertEqual(len(result[0]['entries']), expected)

    def test_normalization_does_not_hold_cache_mutex(self):
        from spikes import rss_sources
        service = RSSSources(channels=CHANNELS, fetcher=lambda url: rss(url))
        service.refresh('one')
        gate = Gate(rss_sources.RSSConnector.normalize_entry)
        with patch.object(rss_sources.RSSConnector, 'normalize_entry',
                          lambda self, *a: gate(self, *a)):
            worker, result = background(service.view)
            try:
                self.assertTrue(gate.inside.wait(10))
                with bounded_project_requests():  # a concurrent cache update is admitted
                    with patch.object(service, 'clock', lambda: 10 ** 6):
                        self.assertEqual(service.refresh('one')['channels'][0]['state'], 'ready')
            finally:
                gate.release.set(); worker.join(10)
        self.assertEqual(result[0]['channels'][0]['state'], 'ready')

    def test_stale_subscription_load_never_reverts_a_newer_save(self):
        service = RSSSources(channels=CHANNELS, fetcher=lambda url: rss(url))
        old = [dict(CHANNELS[0], poll_seconds=900)]
        newer = [dict(old[0]), dict(id='two', name='Two', url='https://example.test/two', poll_seconds=900)]
        service.store = type('Store', (), {})()
        gate = Gate(lambda: (1, old)); service.store.load = gate
        worker, result = background(service.view)
        try:
            self.assertTrue(gate.inside.wait(10))
            with service.lock:  # a save published revision 2 meanwhile
                service.channels, service.revision = newer, 2
                service.cache['two'] = dict(observation=None, error=None, state='unloaded', attempted=None)
        finally:
            gate.release.set(); worker.join(10)
        self.assertEqual((result[0]['revision'], len(result[0]['channels'])), (2, 2))


class TelemetryScopeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name); proc = self.root / 'proc'; (proc / 'net').mkdir(parents=True)
        (proc / 'meminfo').write_text('MemTotal:       1000 kB\nMemAvailable:    250 kB\n')
        (proc / 'stat').write_text('cpu  100 0 50 850 0 0 0 0\n')
        (proc / 'net/dev').write_text('Inter-| Receive | Transmit\n face |bytes packets |bytes packets\n'
                                      'eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n')
        self.proc = proc

    def test_slow_nvidia_smi_does_not_hold_sample_mutex(self):
        gate = Gate(lambda args, **_: subprocess.CompletedProcess([], 0, '40, 1024, 4096\n', ''))
        telemetry = NodeTelemetry(self.root, proc_root=self.proc, runner=gate)
        worker, result = background(telemetry.snapshot)
        try:
            self.assertTrue(gate.inside.wait(10))
            with bounded_project_requests():
                other = telemetry.snapshot('activity')
            self.assertEqual(other['metrics']['cpu']['status'], 'unknown')  # first CPU sample
        finally:
            gate.release.set(); worker.join(10)
        self.assertEqual(set(result[0]['metrics']), {'gpu', 'vram', 'cpu', 'net', 'ram', 'disk'})

    def test_stateful_deltas_remain_serialized(self):
        telemetry = NodeTelemetry(self.root, proc_root=self.proc,
                                  runner=lambda args, **_: subprocess.CompletedProcess([], 0, '1, 1, 2\n', ''))
        with telemetry._lock, bounded_project_requests(), self.assertRaises(ProjectBusy):
            telemetry.snapshot('activity')
        self.assertIn('ram', telemetry.snapshot('capacity')['metrics'])


class BoundedDirectSQLiteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / 'state'; self.state.mkdir(mode=0o700)

    def test_http_bounded_store_write_fails_fast_as_project_busy(self):
        store = ChatThreads(self.state); ids = [str(uuid4()) for _ in range(3)]
        store.create(thread_id=ids[0], node_id=ids[1], user_id=ids[2], created_at='2026-11-18T12:00:00Z')
        with closing(sqlite3.connect(store.path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            with bounded_project_requests(), self.assertRaises(ProjectBusy):
                store.archive(ids[0], ids[1], ids[2])
            self.assertLess(time.monotonic() - started, 5)
            with bounded_project_requests():  # readers still read during the writer transaction
                self.assertEqual(store.get(*ids)['thread_id'], ids[0])
            writer.rollback()

    def test_native_callers_keep_plain_connection_and_timeout(self):
        path = self.state / 'plain.sqlite'
        with closing(bounded_connect(path, timeout=30)) as db:
            self.assertIs(type(db), sqlite3.Connection)
        with bounded_project_requests(), closing(bounded_connect(path, timeout=30)) as db:
            self.assertIsNot(type(db), sqlite3.Connection)
            db.execute('CREATE TABLE t(a)'); db.commit()
            self.assertEqual(db.execute('SELECT count(*) FROM t').fetchone(), (0,))


if __name__ == '__main__':
    unittest.main()
