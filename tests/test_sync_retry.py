# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import unittest
from unittest.mock import patch

from spikes.federation_sync import ContentSyncControl, SyncBusy
from spikes.sync_retry import AutomaticRetry


class SyncRetryTests(unittest.TestCase):
    def test_only_failed_target_is_paced_and_success_resets_delay(self):
        retry = AutomaticRetry(); clock = [1000.0]
        control = ContentSyncControl.__new__(ContentSyncControl)
        control.node = Path('/tmp/retry-test-node')
        candidates = [dict(peer_id='peer', project_id=p, eligible=True)
                      for p in ('slow', 'healthy')]
        failures = [True]; calls = []
        def synchronize(peer, project):
            calls.append(project)
            if project == 'slow' and failures[0]:
                raise SyncBusy(resource='git-budget')
        control.service = object()
        with patch('spikes.sync_fingerprint.probe', return_value=None), \
             patch('spikes.federation_sync.automatic_retry', retry), \
             patch('spikes.sync_retry.time.monotonic', side_effect=lambda: clock[0]), \
             patch.object(control, 'settings', return_value={'automatic_enabled': True}), \
             patch.object(control, 'candidates', return_value=candidates), \
             patch.object(control, 'synchronize', side_effect=synchronize):
            self.assertEqual(control.run_automatic()['attempted'], 2)
            self.assertEqual(control.run_automatic()['attempted'], 1)
            clock[0] += 60
            self.assertEqual(control.run_automatic()['attempted'], 2)
            clock[0] += 60
            self.assertEqual(control.run_automatic()['attempted'], 1)
            clock[0] += 60; failures[0] = False
            self.assertEqual(control.run_automatic()['attempted'], 2)
            self.assertEqual(control.run_automatic()['attempted'], 2)
        self.assertEqual(calls.count('slow'), 4)

    def test_timeout_cooldown_is_bounded_and_has_no_persistent_authority(self):
        retry = AutomaticRetry(); key = ('node', 'peer', 'project'); clock = [0.0]
        with patch('spikes.sync_retry.time.monotonic', side_effect=lambda: clock[0]):
            for delay in (60, 120, 240, 480, 900, 900):
                retry.failed(key)
                self.assertFalse(retry.ready(key))
                self.assertEqual(retry.remaining(key), delay)
                clock[0] += delay
                self.assertTrue(retry.ready(key))
                self.assertEqual(retry.remaining(key), 0)
            self.assertTrue(AutomaticRetry().ready(key))
            for n in range(200): retry.failed(('node', 'peer', str(n)))
            self.assertEqual(len(retry.failures), 128)
