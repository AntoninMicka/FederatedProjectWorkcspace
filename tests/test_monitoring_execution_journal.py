# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest
from uuid import uuid4

from tests import test_reporting as fixtures
from spikes.metadata import ValidationError
from spikes.monitoring_execution_journal import ExecutionJournal, logical_key
from spikes.reporting_scheduler import ReportingScheduler


class ExecutionJournalTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.now = 1000
        self.scheduler = ReportingScheduler(self.f.node, clock=lambda: self.now)
        self.journal = ExecutionJournal(self.scheduler)
        self.key = dict(project_id=self.f.project, project_ref='refs/heads/main',
                        watch_id=str(uuid4()), input_id=str(uuid4()), effect_kind='rss.fetch', slot='2026-11-07')
        self.intent = dict(definition_revision='a'*64, inputs_sha256='b'*64, cutoff='2026-11-07T00:00:00Z')
        self.assignment = dict(agreement_id=str(uuid4()), agreement_revision=1, coordinator_epoch=1,
                               executor_node_id=str(uuid4()), assignment_revision=1)

    def reserve(self):
        return self.journal.reserve(self.key, self.intent, self.assignment, 1100)

    @staticmethod
    def ticket(record):
        return (record['effect_id'], record['assignment']['executor_node_id'], record['fence'], record['intent_sha256'])

    def test_restart_replay_and_revision_changes_cannot_create_second_effect(self):
        first = self.reserve()
        self.journal = ExecutionJournal(ReportingScheduler(self.f.node, clock=lambda: self.now))
        self.assertEqual(self.reserve(), first)
        changed = deepcopy(self.intent);changed['definition_revision'] = 'c'*64
        with self.assertRaisesRegex(ValidationError, 'already pinned'):
            self.journal.reserve(self.key, changed, self.assignment, 1100)
        assignment = dict(self.assignment, coordinator_epoch=2, executor_node_id=str(uuid4()))
        with self.assertRaisesRegex(ValidationError, 'already pinned'):
            self.journal.reserve(self.key, self.intent, assignment, 1100)
        self.assertEqual(self.journal.get(first['effect_id']), first)

    def test_concurrent_coordinators_share_one_begin_permission(self):
        record = self.reserve()
        journals = [ExecutionJournal(ReportingScheduler(self.f.node, clock=lambda: self.now)) for _ in range(4)]
        def begin(journal):
            try:
                journal.begin(*self.ticket(record))
                return True
            except ValidationError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(begin, journals)), 1)
        self.assertEqual(self.journal.get(record['effect_id'])['state'], 'begun')

    def test_lost_begin_acknowledgement_blocks_retry_expiry_and_new_slot(self):
        record = self.reserve();self.journal.begin(*self.ticket(record))
        self.now = 2000
        restarted = ExecutionJournal(ReportingScheduler(self.f.node, clock=lambda: self.now))
        self.assertEqual(restarted.get(record['effect_id'])['state'], 'begun')
        with self.assertRaisesRegex(ValidationError, 'already begun'):
            restarted.begin(*self.ticket(record))
        with self.assertRaisesRegex(ValidationError, 'backend reconciliation'):
            restarted.reassign_unstarted(*self.ticket(record), new_executor_node_id=str(uuid4()),
                                        begin_deadline=2100, confirmed=True)
        next_key = dict(self.key, slot='2026-11-08')
        with self.assertRaisesRegex(ValidationError, 'blocks this stream'):
            restarted.reserve(next_key, self.intent, self.assignment, 2100)

    def test_expired_unstarted_ticket_can_move_with_fenced_history(self):
        record = self.reserve();self.now = 1200
        with self.assertRaisesRegex(ValidationError, 'expired'):
            self.journal.begin(*self.ticket(record))
        moved = self.journal.reassign_unstarted(*self.ticket(record), new_executor_node_id=str(uuid4()),
                                                begin_deadline=1300, confirmed=True)
        self.assertEqual(moved['effect_id'], record['effect_id'])
        self.assertEqual(moved['fence'], 2)
        self.assertEqual(moved['history'][0]['assignment'], record['assignment'])
        with self.assertRaisesRegex(ValidationError, 'Stale'):
            self.journal.begin(*self.ticket(record))
        self.assertEqual(self.journal.begin(*self.ticket(moved))['state'], 'begun')

    def test_unknown_accepts_only_original_result_without_claiming_import(self):
        record = self.reserve();self.journal.begin(*self.ticket(record))
        self.journal.unknown(*self.ticket(record))
        descriptor = dict(payload_sha256='d'*64, backend_effect_id=str(uuid4()))
        result = self.journal.result(*self.ticket(record), descriptor)
        self.assertEqual(result['state'], 'result-awaiting-import')
        self.assertEqual(self.journal.result(*self.ticket(record), descriptor), result)
        with self.assertRaisesRegex(ValidationError, 'cannot be replaced'):
            self.journal.result(*self.ticket(record), dict(descriptor, payload_sha256='e'*64))
        with self.assertRaisesRegex(ValidationError, 'backend reconciliation'):
            self.journal.reassign_unstarted(*self.ticket(record), new_executor_node_id=str(uuid4()),
                                           begin_deadline=1100, confirmed=True)
        with self.assertRaisesRegex(ValidationError, 'blocks this stream'):
            self.journal.reserve(dict(self.key, slot='next'), self.intent, self.assignment, 1100)

    def test_wrong_peer_hash_and_fence_do_not_advance_state(self):
        record = self.reserve()
        ticket = list(self.ticket(record))
        for index, value in ((1, str(uuid4())), (2, True), (2, 2), (3, 'e'*64)):
            wrong = ticket[:];wrong[index] = value
            with self.assertRaisesRegex(ValidationError, 'mismatched'):
                self.journal.begin(*wrong)
        self.assertEqual(self.journal.get(record['effect_id']), record)

    def test_v3_migration_preserves_rss_and_missing_journal_fails_closed(self):
        with self.scheduler.db() as db:
            db.execute('INSERT INTO rss_bindings VALUES(?,?)', ('existing', b'{}'))
            db.execute('DROP TABLE execution_effects');db.execute('UPDATE schema_info SET version=3')
        migrated = ReportingScheduler(self.f.node)
        with migrated.db() as db:
            self.assertEqual(db.execute('SELECT * FROM rss_bindings').fetchall(), [('existing', b'{}')])
        migrated.path.unlink()
        with self.assertRaisesRegex(ValidationError, 'missing'):
            ReportingScheduler(self.f.node)

    def test_logical_scope_rejects_extra_revision_and_invalid_ids(self):
        self.assertEqual(logical_key(self.key), logical_key(deepcopy(self.key)))
        with self.assertRaises(ValidationError):
            logical_key(dict(self.key, executor_node_id=str(uuid4())))
        with self.assertRaises(ValidationError):
            logical_key(dict(self.key, watch_id='not-a-uuid'))

    def test_transition_rollback_leaves_original_reservation(self):
        record = self.reserve()
        original = self.journal._save
        def interrupted(db, changed):
            original(db, changed)
            raise RuntimeError('interrupted before commit')
        self.journal._save = interrupted
        with self.assertRaisesRegex(RuntimeError, 'before commit'):
            self.journal.begin(*self.ticket(record))
        restarted = ExecutionJournal(ReportingScheduler(self.f.node, clock=lambda: self.now))
        self.assertEqual(restarted.get(record['effect_id']), record)
        self.assertEqual(restarted.begin(*self.ticket(record))['state'], 'begun')

    def test_missing_v4_table_does_not_bootstrap_an_empty_authority(self):
        self.reserve()
        with self.scheduler.db() as db:
            db.execute('DROP TABLE execution_effects')
        with self.assertRaisesRegex(ValidationError, 'schema or owner'):
            ReportingScheduler(self.f.node)


if __name__ == '__main__':
    unittest.main()
