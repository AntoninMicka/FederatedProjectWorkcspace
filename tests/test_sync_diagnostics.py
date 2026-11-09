# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from unittest.mock import patch

from spikes import sync_diagnostics as diagnostics


class SyncDiagnosticsTests(unittest.TestCase):
    def test_failure_keeps_phase_without_exception_text_or_payload(self):
        @diagnostics.observed
        def transfer(node, peer, project):
            diagnostics.phase('upload')
            raise BrokenPipeError('secret-token private-payload')

        with self.assertLogs('spikes.sync_diagnostics', level='WARNING') as logs:
            with self.assertRaises(BrokenPipeError):
                transfer('/tmp/diagnostic-node', 'peer', 'project')
        result = diagnostics.snapshot('/tmp/diagnostic-node', 'peer', 'project')
        self.assertEqual(result['phase'], 'upload')
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['error_type'], 'BrokenPipeError')
        self.assertGreaterEqual(result['elapsed_ms'], 0)
        self.assertNotIn('secret-token', str(result) + str(logs.output))
        self.assertNotIn('private-payload', str(result) + str(logs.output))

    def test_running_observation_and_nested_calls_share_phase(self):
        @diagnostics.observed
        def inner(node, peer, project):
            diagnostics.phase('download')
            return diagnostics.snapshot(node, peer, project)

        @diagnostics.observed
        def outer(node, peer, project):
            return inner(node, peer, project)

        result = outer('/tmp/nested-node', 'peer', 'project')
        self.assertEqual(result['state'], 'running')
        self.assertEqual(result['phase'], 'download')
        self.assertEqual(diagnostics.snapshot('/tmp/nested-node', 'peer', 'project')['state'], 'finished')
        # A different node never receives this observation.
        self.assertIsNone(diagnostics.snapshot('/tmp/other-node', 'peer', 'project'))

    def test_storage_is_bounded_and_finished_time_does_not_grow(self):
        @diagnostics.observed
        def transfer(node, peer, project):
            return None

        with patch.object(diagnostics, '_latest', diagnostics.OrderedDict()):
            for i in range(diagnostics.LIMIT + 1):
                transfer('/tmp/bounded-node', 'peer', str(i))
            self.assertIsNone(diagnostics.snapshot('/tmp/bounded-node', 'peer', '0'))
            before = diagnostics.snapshot('/tmp/bounded-node', 'peer', '1')
            with patch.object(diagnostics.time, 'monotonic', return_value=10**12):
                self.assertEqual(before, diagnostics.snapshot('/tmp/bounded-node', 'peer', '1'))
