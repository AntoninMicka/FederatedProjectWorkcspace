# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from unittest.mock import patch

from scripts.migrate_task_history_text import audit, apply
from spikes.task_activity_text import ActivityText
from tests import test_task_records as fixtures


class TaskHistoryTextTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TaskRecordTests()
        with patch.object(ActivityText, 'drain', return_value=[]):
            self.f.setUp()
            self.request = self.f.request(comment=('Celý komentář bez zkrácení. '*30)+'\nDruhý řádek.')
            self.f.service.execute(self.request)
        self.addCleanup(self.f.doCleanups)
        self.work = self.f.work
        self.store = ActivityText(self.work)
        with self.work._db() as db:
            self.source = {r['id']: dict(r) for r in db.execute('SELECT * FROM operations')
                if json.loads(r['doc']).get('record_type') in {'task-activity', 'task-record-publish'}}

    def test_verified_migration_preserves_exact_rows_task_states_and_replay(self):
        plan = audit(self.work)
        self.assertEqual(len(plan['entries']), 2)
        result = apply(self.work, plan)
        self.assertEqual(set(result['migrated']), set(self.source))
        destination = self.store.read(self.f.f.f.pid)
        for identifier, row in self.source.items():
            self.assertEqual(destination[identifier], row)
        self.assertEqual(audit(self.work)['entries'], [])
        head = self.work.projects.repository(self.f.f.f.pid).head()
        self.f.service.execute(self.request)
        self.assertEqual(self.work.projects.repository(self.f.f.f.pid).head(), head)
        self.assertFalse(self.f.f.active()['blocked'])

    def test_project_commit_and_sqlite_delete_interruptions_keep_source_until_readback(self):
        def stop_at(wanted):
            def stop(stage):
                if stage == wanted: raise RuntimeError('interrupted')
            return stop
        for stage in ['committed', 'task-history-text-before-delete-commit']:
            with self.assertRaises(RuntimeError): self.store.drain(checkpoint=stop_at(stage))
            with self.work._db() as db:
                for identifier, original in self.source.items():
                    self.assertEqual(dict(db.execute('SELECT * FROM operations WHERE id=?', (identifier,)).fetchone()), original)
        self.assertEqual(set(self.store.drain()), set(self.source))
        head = self.work.projects.repository(self.f.f.f.pid).head()
        self.assertEqual(self.store.drain(), [])
        self.assertEqual(self.work.projects.repository(self.f.f.f.pid).head(), head)

    def test_changed_audit_refuses_cleanup_before_project_write(self):
        plan = audit(self.work)
        identifier = next(iter(self.source))
        with self.work._db(write=True) as db:
            op = json.loads(self.source[identifier]['doc']); op['updated_at'] += 1
            self.work._save_operation(db, identifier, op)
        head = self.work.projects.repository(self.f.f.f.pid).head()
        with self.assertRaises(ValueError): apply(self.work, plan)
        self.assertEqual(self.work.projects.repository(self.f.f.f.pid).head(), head)
        with self.work._db() as db:
            self.assertIsNotNone(db.execute('SELECT 1 FROM operations WHERE id=?', (identifier,)).fetchone())


if __name__ == '__main__':
    unittest.main()
