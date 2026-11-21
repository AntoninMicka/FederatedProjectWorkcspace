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

    def test_directions_do_not_overwrite_each_other_or_share_nested_phase(self):
        @diagnostics.observed(direction='inbound')
        def incoming(node,peer,project):
            diagnostics.phase('receive-verify')
        @diagnostics.observed
        def outgoing(node,peer,project):
            diagnostics.phase('download');incoming(node,peer,project)
            self.assertEqual(diagnostics.current_phase(),'download')
        outgoing('/tmp/directional-node','peer','project')
        self.assertEqual(diagnostics.snapshot('/tmp/directional-node','peer','project',direction='outbound')['phase'],'download')
        self.assertEqual(diagnostics.snapshot('/tmp/directional-node','peer','project',direction='inbound')['phase'],'receive-verify')
        self.assertEqual(len(diagnostics.observations('/tmp/directional-node')),2)

    def test_safe_resource_metadata_never_logs_exception_text_or_arbitrary_peer_values(self):
        from spikes.request_ownership import ProjectBusy
        @diagnostics.observed
        def outgoing(node,peer,project):
            error=ProjectBusy('secret-token private-payload',resource='sync-journal')
            error.peer_phase='receive-prepare-response';raise error
        with self.assertLogs('spikes.sync_diagnostics',level='WARNING') as logs:
            with self.assertRaises(ProjectBusy):outgoing('/tmp/resource-node','peer','project')
        value=diagnostics.snapshot('/tmp/resource-node','peer','project')
        self.assertEqual(value['busy_resource'],'sync-journal')
        self.assertEqual(value['peer_phase'],'receive-prepare-response')
        self.assertNotIn('secret-token',str(value)+str(logs.output))
        self.assertNotIn('private-payload',str(value)+str(logs.output))
        @diagnostics.observed
        def bad(node,peer,project):
            error=ProjectBusy('private',resource={'secret-token':True})
            error.peer_phase='private-payload';raise error
        with self.assertRaises(ProjectBusy):bad('/tmp/resource-node','peer','bad')
        value=diagnostics.snapshot('/tmp/resource-node','peer','bad')
        self.assertNotIn('busy_resource',value);self.assertNotIn('peer_phase',value)

    def test_failure_log_lists_how_long_each_phase_took(self):
        now = [100.0]

        @diagnostics.observed
        def transfer(node, peer, project):
            now[0] += 1.5
            diagnostics.phase('receive-verify-history')
            now[0] += 2.5
            diagnostics.phase('receive-publication-git')
            now[0] += .25
            raise TimeoutError('private-payload')

        with patch.object(diagnostics.time, 'monotonic', lambda: now[0]), \
                self.assertLogs('spikes.sync_diagnostics', level='WARNING') as logs, \
                self.assertRaises(TimeoutError):
            transfer('/tmp/duration-node', 'peer', 'project')
        line = logs.output[-1]
        self.assertIn('elapsed_ms=4250', line)
        self.assertIn('phases=prepare:1500,receive-verify-history:2500,'
                      'receive-publication-git:250', line)
        self.assertNotIn('private-payload', line)

    def test_slow_success_is_logged_with_phases_and_fast_success_is_silent(self):
        now = [0.0]

        @diagnostics.observed(direction='inbound')
        def receive(node, peer, project, seconds):
            diagnostics.phase('receive-publication-chats')
            now[0] += seconds

        with patch.object(diagnostics.time, 'monotonic', lambda: now[0]):
            with self.assertNoLogs('spikes.sync_diagnostics', level='WARNING'):
                receive('/tmp/slow-node', 'peer', 'fast', 1)
            with self.assertLogs('spikes.sync_diagnostics', level='WARNING') as logs:
                receive('/tmp/slow-node', 'peer', 'slow', diagnostics.SLOW_MS / 1000)
        self.assertIn('sync_slow direction=inbound elapsed_ms=30000', logs.output[-1])
        self.assertIn('receive-publication-chats:30000', logs.output[-1])

    def test_publication_subphases_are_safe_peer_phases(self):
        for name in diagnostics.PUBLICATION_PHASES:
            self.assertEqual(diagnostics.safe_peer_phase(name), name)
