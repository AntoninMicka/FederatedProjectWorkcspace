# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B4-T1: no swallowed background errors and no state chosen by message text."""
import json
import logging
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from spikes import rss_subscription_sync
from spikes.action_autonomy import AutonomyQueue
from spikes.background_workers import report_failure
from spikes.configuration import DuplicateProjectRegistration, parse_node, read_config
from spikes.federation_catalog import CatalogControl, CatalogScheduler
from spikes.federation_sync import ContentSyncControl, ManualSyncTasks, _database
from spikes.julia_computation import JuliaRunStore
from spikes.metadata import OwnerUnavailable, ValidationError
from spikes.output_execution import OutputExecutionStore
from spikes.replication_control import ReplicationControl
from spikes.role_workflows import RoleWorkflows
from spikes.summary_tasks import SummaryTasks
from tests import test_artifacts as fixtures
from tests.fixtures import encoded

LOGGER = 'spikes.background'
SECRET = 'private-detail-7f3a'


class ReportFailureTests(unittest.TestCase):
    def test_expected_failure_is_info_without_traceback(self):
        with self.assertLogs(LOGGER, logging.INFO) as logs:
            self.assertTrue(report_failure('worker-a', ConnectionError(SECRET), target='peer-1'))
        self.assertEqual(logs.records[0].levelno, logging.INFO)
        self.assertIsNone(logs.records[0].exc_info)
        self.assertEqual(logs.records[0].getMessage(),
                         'background_failed worker=worker-a target=peer-1 reason=ConnectionError')
        self.assertNotIn(SECRET, logs.output[0])

    def test_unknown_failure_is_warning_with_traceback(self):
        with self.assertLogs(LOGGER, logging.INFO) as logs:
            self.assertFalse(report_failure('worker-a', RuntimeError(SECRET)))
        record = logs.records[0]
        self.assertEqual(record.levelno, logging.WARNING)
        self.assertIs(record.exc_info[0], RuntimeError)
        self.assertNotIn(SECRET, record.getMessage())

    def test_caller_can_declare_additional_expected_classes(self):
        class Busy(Exception):
            pass
        with self.assertLogs(LOGGER, logging.INFO) as logs:
            self.assertTrue(report_failure('worker-a', Busy(), expected=(Busy,)))
        self.assertEqual(logs.records[0].levelno, logging.INFO)


class CatalogLoopTests(unittest.TestCase):
    def control(self):
        control = object.__new__(CatalogControl)
        control.node, control.deployment, control.store = Path('/nonexistent'), 'desktop', MagicMock()
        return control

    def test_unknown_error_records_generic_peer_state_and_reraises(self):
        control = self.control()
        with patch('spikes.federation_catalog.synchronize', side_effect=RuntimeError(SECRET)):
            with self.assertRaises(RuntimeError):
                control.synchronize('peer-1')
        control.store.runtime.assert_called_once_with('peer-1', 'error', 'RuntimeError')

    def test_automatic_loop_logs_and_continues_with_next_peer(self):
        control = self.control()
        peers = [dict(id=f'peer-{n}', trust='approved', sharing_level='same-team',
                      endpoint='https://192.0.2.1') for n in (1, 2)]
        control.administration = MagicMock()
        control.administration.request.return_value = {'peers': peers}
        with patch.object(control, 'synchronize', side_effect=[RuntimeError(SECRET), None]) as call, \
                self.assertLogs(LOGGER, logging.INFO) as logs:
            control.run_automatic()
        self.assertEqual([c.args[0] for c in call.call_args_list], ['peer-1', 'peer-2'])
        self.assertIn('worker=federation-catalog target=peer-1 reason=RuntimeError',
                      logs.records[0].getMessage())
        self.assertEqual(logs.records[0].levelno, logging.WARNING)

    def test_scheduler_iteration_failure_is_logged_and_retried_sooner(self):
        scheduler = object.__new__(CatalogScheduler)
        scheduler.interval, scheduler.control = 60, MagicMock()
        scheduler.stopping = MagicMock()
        scheduler.stopping.is_set.side_effect = [False, True]
        scheduler.control.run_automatic.side_effect = TypeError(SECRET)
        with self.assertLogs(LOGGER, logging.INFO) as logs:
            scheduler._run()
        scheduler.stopping.wait.assert_called_once_with(5)
        self.assertIn('worker=federation-catalog target=- reason=TypeError', logs.records[0].getMessage())


class ReplicationLoopTests(unittest.TestCase):
    def test_unknown_send_error_records_generic_error_state(self):
        control = object.__new__(ReplicationControl)
        control.node, control.deployment = Path('/nonexistent'), 'desktop'
        control.administration = MagicMock()
        control.administration.active_replication.return_value = {
            'spec': {'id': 'rep-1', 'project_id': 'project-1'}, 'remote': {'node_id': 'node-2'}}
        projects = MagicMock()
        projects.return_value.workspace.return_value.git.head.return_value = 'b' * 40
        with patch('spikes.replication_control.pending_transfer', return_value=None), \
                patch('spikes.replication_control.replication_runtime',
                      return_value={'last_head': 'a' * 40}), \
                patch('spikes.replication_control.Projects', projects), \
                patch('spikes.replication_control.send', side_effect=RuntimeError(SECRET)), \
                patch('spikes.replication_control.set_replication_runtime') as runtime:
            with self.assertRaises(RuntimeError):
                control._synchronize('rep-1')
        self.assertEqual(runtime.call_args.args[1:3], ('rep-1', 'error'))
        self.assertEqual(runtime.call_args.kwargs['detail'], 'RuntimeError')
        self.assertEqual(runtime.call_args.kwargs['last_head'], 'a' * 40)

    def test_enabled_loop_logs_each_failure(self):
        control = object.__new__(ReplicationControl)
        control.administration = MagicMock()
        control.administration.request.return_value = {'replications': [
            {'active': True, 'revocation': None, 'local_role': 'primary', 'spec': {'id': 'rep-1'}}]}
        with patch.object(control, 'synchronize', side_effect=ConnectionError(SECRET)), \
                self.assertLogs(LOGGER, logging.INFO) as logs:
            control.run_enabled()
        self.assertEqual(logs.records[0].getMessage(),
                         'background_failed worker=project-replication target=rep-1 reason=ConnectionError')


class RSSLoopTests(unittest.TestCase):
    def test_prepare_failure_records_peer_error_state(self):
        with patch.object(rss_subscription_sync, 'Administration'), \
                patch.object(rss_subscription_sync, 'prepare', side_effect=ValidationError('No peer')), \
                patch.object(rss_subscription_sync.state, 'progress') as progress:
            with self.assertRaises(ValidationError):
                rss_subscription_sync.synchronize(Path('/nonexistent'), 'peer-1')
        progress.assert_called_once_with(Path('/nonexistent'), 'peer-1', state='error',
                                         detail='ValidationError')

    def test_automatic_loop_logs_failure(self):
        with patch.object(rss_subscription_sync.state, 'view',
                          return_value={'peers': [{'id': 'peer-1', 'enabled': True}]}), \
                patch.object(rss_subscription_sync, 'synchronize', side_effect=KeyError(SECRET)), \
                self.assertLogs(LOGGER, logging.INFO) as logs:
            rss_subscription_sync.run_automatic(Path('/nonexistent'), deployment='desktop')
        self.assertEqual(logs.records[0].levelno, logging.WARNING)
        self.assertIn('worker=rss-preference-sync target=peer-1 reason=KeyError',
                      logs.records[0].getMessage())


class ContentSyncErrorTests(unittest.TestCase):
    setUp = fixtures.ArtifactTests.setUp

    def runtime(self, peer, project):
        with _database(self.node) as db:
            return db.execute('SELECT state,detail FROM runtime WHERE peer_id=? AND project_id=?',
                              (peer, project)).fetchone()

    def test_unknown_error_records_generic_runtime_state(self):
        peer, project = str(uuid4()), str(uuid4())
        with patch('spikes.federation_sync.synchronize', side_effect=RuntimeError(SECRET)):
            with self.assertRaises(RuntimeError):
                ContentSyncControl(self.node, deployment='desktop').synchronize(peer, project)
        self.assertEqual(self.runtime(peer, project), ('error', 'RuntimeError'))

    def test_manual_worker_logs_failure_after_durable_state(self):
        peer, project = str(uuid4()), str(uuid4())
        tasks = ManualSyncTasks()
        with patch('spikes.federation_sync.synchronize', side_effect=RuntimeError(SECRET)), \
                patch('spikes.federation_sync._MANUAL_SYNCS', tasks), \
                self.assertLogs(LOGGER, logging.INFO) as logs:
            self.assertTrue(tasks.start(self.node, 'desktop', peer, project))
            for task in list(tasks.tasks.values()):
                task['thread'].join(5)
        self.assertEqual(self.runtime(peer, project), ('error', 'RuntimeError'))
        self.assertIn(f'worker=manual-content-sync target={peer}/{project} reason=RuntimeError',
                      logs.records[-1].getMessage())


class TypedStateTests(unittest.TestCase):
    def test_owner_checks_raise_typed_error_with_unchanged_message(self):
        for owned, message in ((SummaryTasks._owned, 'Summary task'),
                               (RoleWorkflows._owned, 'Workflow'),
                               (AutonomyQueue._owned, 'Autonomy workflow'),
                               (JuliaRunStore._owner, 'Julia run'),
                               (OutputExecutionStore._owner, 'Output execution')):
            with self.subTest(message=message):
                with self.assertRaisesRegex(OwnerUnavailable, f'^{message} is unavailable to this owner$'):
                    owned(None, 'node', 'user')

    def test_untyped_error_with_owner_text_is_not_treated_as_missing(self):
        """A generic error containing the old phrase must propagate (B-ODD-03)."""
        from spikes.summary_service import SummaryService
        service = object.__new__(SummaryService)
        tasks = MagicMock()
        tasks.get.side_effect = ValidationError('Database row is unavailable to this owner')
        bindings = MagicMock()
        bindings.load.return_value.boundary = 'same-node'
        request = {'role_id': 'r', 'role_revision': 'x', 'task_id': str(uuid4()), 'target': 't'}
        bindings.load.return_value.serialize.return_value = 't'
        with patch.object(SummaryService, '_request', return_value=(None, None, None)), \
                patch('spikes.summary_service.ROLES'), \
                patch.object(SummaryService, '_identity', return_value=('n', 'u')), \
                patch.object(SummaryService, '_stores', return_value=(tasks, bindings, MagicMock())):
            with self.assertRaisesRegex(ValidationError, '^Database row is unavailable') as raised:
                service.preview(request)
        self.assertNotIsInstance(raised.exception, OwnerUnavailable)
        tasks.get.assert_called_once()

    def test_duplicate_registration_has_its_own_type(self):
        fixtures.ArtifactTests.setUp(self)
        node = parse_node(read_config(self.node), location=self.node)
        node['projects'].append(dict(node['projects'][0]))
        self.node.write_bytes(encoded(node))
        with self.assertRaisesRegex(DuplicateProjectRegistration, '^Duplicate registered project ID$'):
            parse_node(read_config(self.node), location=self.node)


@unittest.skipUnless(shutil.which('node'), 'Node.js required for the public screen behaviour test')
class PublicScreenTests(unittest.TestCase):
    """B-ODD-10: a failed poll of the audience screen is visible, not swallowed."""

    def test_failed_poll_shows_link_status_and_logs_once(self):
        from spikes.desktop_ui import ASSETS, PUBLIC_HTML
        self.assertIn('id="link-status"', PUBLIC_HTML)
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        script = Path(temp.name) / 'screen.js'
        script.write_text(ASSETS['/presentation-screen.js'][1], encoding='utf-8')
        harness = Path(__file__).with_name('presentation_screen_harness.cjs')
        result = subprocess.run(['node', str(harness), str(script)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        steps = {step[0]: step[1:] for step in json.loads(result.stdout)['steps']}
        self.assertEqual(steps['start'], [True, None, 0])
        self.assertEqual(steps['throw-1'], [False, 'lost', 1])
        self.assertEqual(steps['throw-2'], [False, 'lost', 1], 'repeated failure must not flood the log')
        self.assertEqual(steps['http-503'], [False, 'lost', 1])
        self.assertEqual(steps['recovered'], [True, 'ok', 1])
        self.assertEqual(steps['ratio'], [1])


if __name__ == '__main__':
    unittest.main()
