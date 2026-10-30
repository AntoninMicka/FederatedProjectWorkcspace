# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Blocked probes must not consume HTTP capacity or duplicate network work."""
from dataclasses import replace
import json
import threading
import unittest
from unittest.mock import patch

from spikes.backend_availability import BackendAvailability
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.ollama_backend import OllamaBinding
from tests import test_local_api, test_ollama_backend


class AvailabilityTests(unittest.TestCase):
    def setUp(self):
        self.binding = OllamaBinding.parse(test_ollama_backend.OllamaBindingTests().binding())
        self.now = 100.0
        self.sampler = BackendAvailability(clock=lambda: self.now)
        self.addCleanup(lambda: self.sampler.close(2))

    def idle(self, sampler=None):
        sampler = sampler or self.sampler
        with sampler._condition:
            self.assertTrue(sampler._condition.wait_for(
                lambda: sampler._running is None, timeout=2))

    def test_single_flight_no_queue_and_exact_binding_cache(self):
        entered, release = threading.Event(), threading.Event()
        def probe(binding, *, timeout):
            self.assertEqual(timeout, 10)
            entered.set()
            self.assertTrue(release.wait(2))
            return {'model_available': True}
        with patch('spikes.backend_availability.OllamaAdapter.probe', side_effect=probe) as call:
            try:
                first = self.sampler.status(self.binding)
                self.assertTrue(entered.wait(1))
                self.assertTrue(first['checking'])
                self.assertIsNone(first['available'])
                for _ in range(20):
                    self.assertTrue(self.sampler.status(self.binding)['checking'])
                other = replace(self.binding, endpoint='http://127.0.0.2:11434')
                result = self.sampler.status(other)
                self.assertFalse(result['checking'])
                self.assertIsNone(result['available'])
                self.assertEqual(call.call_count, 1)
            finally:
                release.set()
                self.idle()
            result = self.sampler.status(self.binding)
            self.assertTrue(result['available'])
            self.assertTrue(result['model_available'])
            self.assertFalse(result['stale'])
            self.assertIsNotNone(result['checked_at'])
            self.assertEqual(call.call_count, 1)
            self.sampler.status(other)
            self.idle()
            self.assertEqual(call.call_count, 2)
            self.assertEqual(call.call_args.args[0], other)

    def test_failed_refresh_retains_timestamp_then_publishes_unavailable(self):
        with patch('spikes.backend_availability.OllamaAdapter.probe', return_value={'model_available': False}):
            self.sampler.status(self.binding)
            self.idle()
        previous = self.sampler.status(self.binding)
        self.assertTrue(previous['available'])
        self.assertFalse(previous['model_available'])
        self.now += 31
        release, entered = threading.Event(), threading.Event()
        def fail(*args, **kwargs):
            entered.set()
            release.wait(2)
            raise OSError('/secret/private-endpoint')
        with patch('spikes.backend_availability.OllamaAdapter.probe', side_effect=fail) as call:
            try:
                stale = self.sampler.status(self.binding)
                self.assertTrue(entered.wait(1))
                self.assertTrue(stale['available'])
                self.assertTrue(stale['stale'])
                self.assertTrue(stale['checking'])
                self.assertEqual(stale['checked_at'], previous['checked_at'])
            finally:
                release.set()
                self.idle()
            failed = self.sampler.status(self.binding)
            self.assertFalse(failed['available'])
            self.assertEqual(failed['status'], 'unavailable')
            self.assertNotIn('/secret', json.dumps(failed))
            self.assertEqual(call.call_count, 1)

    def test_cache_is_bounded_and_shutdown_does_not_restart(self):
        with patch('spikes.backend_availability.OllamaAdapter.probe', return_value={'model_available': True}) as call:
            for i in range(12):
                self.sampler.status(replace(self.binding, revision=str(i)))
                self.idle()
            self.assertEqual(len(self.sampler._samples), 8)
            self.assertTrue(self.sampler.close(0))
            result = self.sampler.status(self.binding)
            self.assertIsNone(result['retry_after_ms'])
            self.assertEqual(call.call_count, 12)

    def test_close_reports_busy_and_drains_without_publishing(self):
        release = threading.Event()
        with patch('spikes.backend_availability.OllamaAdapter.probe', side_effect=lambda *a, **k: (release.wait(2) and {'model_available': True})):
            try:
                self.sampler.status(self.binding)
                self.assertFalse(self.sampler.close(0))
                self.assertFalse(self.sampler.status(replace(self.binding, revision='new'))['checking'])
            finally:
                release.set()
                self.assertTrue(self.sampler.close(2))
            self.assertEqual(len(self.sampler._samples), 0)

    def test_server_shutdown_reports_probe_grace_expiry(self):
        release = threading.Event()
        with patch('spikes.backend_availability.OllamaAdapter.probe',
                   side_effect=lambda *a, **k: (release.wait(2) and {'model_available': True})):
            try:
                with running_api('http', shutdown_timeout=0.02) as server:
                    server.backend_availability.status(self.binding)
                self.assertFalse(server.shutdown_clean)
            finally:
                release.set()
                self.assertTrue(server.backend_availability.close(2))

    def test_server_shutdown_drains_probe_before_clearing_token(self):
        release = threading.Event()
        with patch('spikes.backend_availability.OllamaAdapter.probe',
                   side_effect=lambda *a, **k: (release.wait(2) and {'model_available': True})):
            try:
                with running_api('http', shutdown_timeout=1) as server:
                    server.backend_availability.status(self.binding)
                    timer = threading.Timer(0.05, release.set)
                    timer.start()
                self.assertTrue(server.shutdown_clean)
                self.assertEqual(server.token, '')
            finally:
                release.set()
                timer.join()

    def test_desktop_blocked_probe_leaves_http_workers_and_application_free(self):
        release, entered = threading.Event(), threading.Event()
        driver = test_local_api.LocalAPITests()
        body = json.dumps(test_ollama_backend.OllamaBindingTests().binding()).encode()
        def probe(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return {'model_available': True}
        with patch('spikes.backend_availability.OllamaAdapter.probe', side_effect=probe) as call, running_api('http', handler=DesktopHandler) as server:
            try:
                server.application_lane.acquire()
                try:
                    response = driver.request(server, path='/v1/chat/availability', body=body)
                    self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
                    self.assertTrue(entered.wait(1))
                    for _ in range(8):
                        response = driver.request(server, path='/v1/chat/availability', body=body)
                        self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
                    self.assertLessEqual(server.active_worker_count(), 1)
                finally:
                    server.application_lane.release()
                response = driver.request(server, method='GET', path='/app.css', body=b'')
                self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
                self.assertEqual(call.call_count, 1)
                invalid = driver.request(server, path='/v1/chat/availability', body=b'{}')
                self.assertIn(b' 422 ', invalid.split(b'\r\n', 1)[0])
                unauthorized = driver.request(server, path='/v1/chat/availability', body=body,
                                              headers={'Authorization': 'Bearer wrong'})
                self.assertIn(b' 401 ', unauthorized.split(b'\r\n', 1)[0])
                self.assertEqual(call.call_count, 1)
            finally:
                release.set()
