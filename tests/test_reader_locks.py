# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B2-T1: readers share project ownership; writers stay exclusive.

Acceptance follows audit probe R1: concurrent readers never receive
ProjectBusy, a writer is still excluded, and a changed HEAD or stale index is
reported explicitly instead of returning old data as current.
"""
from contextlib import closing, contextmanager
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from uuid import uuid4

from spikes.artifact_history import ArtifactHistory
from spikes.artifacts import Artifacts, main_todo_id
from spikes.chat_threads import ChatThreads
from spikes.journal import Journal
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.reporting import Reporting
from spikes.request_ownership import ProjectBusy, bounded_project_requests
from spikes.storage import StaleIndex
from spikes.task_queue import TaskQueue
from spikes.workspace import PendingOperation

NOW = '2026-11-18T12:00:00Z'


@contextmanager
def held(factory):
    """Hold a lock in another thread, as a concurrent request would."""
    entered, release, failure = threading.Event(), threading.Event(), []
    def run():
        try:
            with factory():
                entered.set(); release.wait(10)
        except BaseException as exc:  # surfaced below, never swallowed
            failure.append(exc); entered.set()
    worker = threading.Thread(target=run); worker.start()
    try:
        assert entered.wait(10) and not failure, failure
        yield
    finally:
        release.set(); worker.join(10)


def bounded(call):
    with bounded_project_requests():
        return call()


class ProjectReaderLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name); self.node = base / 'node.json'
        self.pid = ProjectCreation(self.node).create('Readers', str(base / 'project'), str(uuid4()))['id']
        self.artifacts = Artifacts(self.node); self.aid = main_todo_id(self.pid)
        self.head = self.save('- [ ] [TASK-A] A\n', new=True)
        self.ws = self.artifacts.workspace(self.pid)

    def save(self, body, new=False):
        head = Projects(self.node).repository(self.pid).head()
        return self.artifacts.save(dict(project_id=self.pid, artifact_id=self.aid, base_head=head,
                                        title='Roadmap', body=body, new=new), str(uuid4()))['commit_id']

    def readers(self):
        history = ArtifactHistory(self.node)
        return {
            'workspace open': lambda: self.artifacts.workspace(self.pid),
            'artifacts.open': lambda: self.artifacts.open(self.pid),
            'history.list': lambda: history.list(self.pid, self.aid, self.head),
            'reporting.pin': lambda: Reporting(self.node).pin(self.pid, self.aid),
            'snapshot_checkpoint': lambda: self.ws.snapshot_checkpoint(self.head),
        }

    def test_concurrent_readers_never_receive_project_busy(self):
        for name, read in self.readers().items():
            with self.subTest(reader=name), held(lambda: self.ws.journal.lock(shared=True)):
                bounded(read)

    def test_reader_holding_its_own_lock_admits_other_readers(self):
        history = ArtifactHistory(self.node)
        with held(lambda: history._read(self.pid, self.aid, self.head)):
            for name, read in self.readers().items():
                with self.subTest(reader=name):
                    bounded(read)

    def test_writer_remains_excluded_from_readers_and_readers_from_writer(self):
        with held(lambda: self.ws.journal.lock()):
            for name, read in self.readers().items():
                with self.subTest(reader=name), self.assertRaises(ProjectBusy):
                    bounded(read)
        with held(lambda: self.ws.journal.lock(shared=True)), self.assertRaises(ProjectBusy):
            bounded(lambda: self.save('- [ ] [TASK-A] A\n- [ ] [TASK-B] B\n'))

    def test_bootstrap_stays_exclusive_for_missing_or_incomplete_journal(self):
        state = self.ws.journal.state; database = state / 'journal.sqlite'
        with closing(sqlite3.connect(database)) as db:
            db.execute('DROP INDEX one_active_operation'); db.commit()
        with held(lambda: self.ws.journal.lock(shared=True)), self.assertRaises(ProjectBusy):
            bounded(lambda: Journal(self.ws.journal.root, state))
        Journal(self.ws.journal.root, state)
        with closing(sqlite3.connect(database)) as db:
            self.assertIn(('one_active_operation',), db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'").fetchall())
        os.chmod(database, 0o640)
        Journal(self.ws.journal.root, state)
        self.assertEqual(database.stat().st_mode & 0o777, 0o600)

    def test_foreign_journal_owner_is_refused_on_shared_path(self):
        other = Path(self.tmp.name) / 'other'; other.mkdir()
        with self.assertRaisesRegex(ValueError, 'another project'):
            Journal(other, self.ws.journal.state)

    def test_changed_head_and_stale_index_are_explicit_never_old_data(self):
        with self.assertRaises(StaleIndex):
            ArtifactHistory(self.node).list(self.pid, self.aid, '0' * 40)
        index = self.ws.journal.state / 'index.sqlite'
        old = Path(self.tmp.name) / 'old-index.sqlite'; shutil.copy2(index, old)
        current = self.save('- [ ] [TASK-A] A\n- [ ] [TASK-C] C\n')
        shutil.copy2(old, index)
        with self.ws.journal.lock(shared=True), self.ws.journal.connect() as db:
            with self.assertRaises(StaleIndex):
                self.ws._read_shared(db)
        self.ws.repair_index()
        with self.ws.journal.lock(shared=True), self.ws.journal.connect() as db:
            self.assertEqual(self.ws._read_shared(db), self.ws.index.read(self.ws.git))
        self.assertEqual(self.artifacts.open(self.pid)['commit_id'], current)

    def test_pending_operation_is_not_hidden_by_shared_paths(self):
        with self.ws.journal.lock(), self.ws.journal.connect() as db:
            db.execute("INSERT INTO pending VALUES ('artifacts/x/y', NULL, NULL)"); db.commit()
        self.ws.repair_index()
        with self.ws.journal.lock(shared=True), self.ws.journal.connect() as db:
            with self.assertRaises(PendingOperation):
                self.ws._read_shared(db)
        with self.assertRaises(PendingOperation):
            self.ws.recover()


class QueueStatusLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name); self.node = base / 'node.json'
        self.pid = ProjectCreation(self.node).create('Queue', str(base / 'project'), str(uuid4()))['id']
        head = Projects(self.node).repository(self.pid).head()
        Artifacts(self.node).save(dict(project_id=self.pid, artifact_id=main_todo_id(self.pid),
            base_head=head, title='Roadmap', body='- [ ] [TASK-A] A\n', new=True), str(uuid4()))
        self.service, self.owner = TaskQueue(self.node), str(uuid4())

    def status(self):
        return bounded(lambda: self.service.execute(dict(project_id=self.pid, action='status'), self.owner))

    def test_status_shares_queue_and_journal_with_other_status_readers(self):
        view = self.status()
        with held(lambda: self.service._lock(self.pid, self.owner, shared=True)):
            self.assertEqual(self.status()['revision'], view['revision'])
        ws = Projects(self.node).workspace(self.pid)
        with held(lambda: ws.journal.lock(shared=True)):
            self.assertEqual(self.status()['revision'], view['revision'])

    def test_queue_change_stays_exclusive_against_status(self):
        view = self.status()
        with held(lambda: self.service._lock(self.pid, self.owner)), self.assertRaises(ProjectBusy):
            self.status()
        with held(lambda: self.service._lock(self.pid, self.owner, shared=True)), \
                self.assertRaises(ProjectBusy):
            bounded(lambda: self.service.execute(dict(project_id=self.pid, action='add', task_id='TASK-A',
                revision=view['revision'], expected_head=view['expected_head']), self.owner))


class StoreReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state'; self.state.mkdir(mode=0o700)
        self.ids = [str(uuid4()) for _ in range(3)]

    def test_reader_does_not_wait_for_or_open_a_writer_transaction(self):
        store = ChatThreads(self.state)
        thread, node, user = self.ids
        store.create(thread_id=thread, node_id=node, user_id=user, created_at=NOW)
        with closing(sqlite3.connect(store.path)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            self.assertEqual(store.get(thread, node, user)['thread_id'], thread)
            self.assertEqual([t['thread_id'] for t in store.list(node, user)], [thread])
            self.assertLess(time.monotonic() - started, 5)
            writer.rollback()

    def test_reader_on_absent_store_uses_writer_bootstrap(self):
        store = ChatThreads(self.state)
        self.assertIsNone(store.connect(readonly=True))
        self.assertEqual(store.list(*self.ids[1:]), [])
        self.assertTrue(store.path.exists())

    def test_reader_on_store_needing_migration_falls_back_to_writer(self):
        store = ChatThreads(self.state)
        thread, node, user = self.ids
        store.create(thread_id=thread, node_id=node, user_id=user, created_at=NOW)
        with closing(sqlite3.connect(store.path)) as db:
            db.execute('DELETE FROM schema_info'); db.execute('INSERT INTO schema_info VALUES(5)')
            db.execute('ALTER TABLE threads DROP COLUMN forked_from_thread_id')
            db.execute('ALTER TABLE threads DROP COLUMN forked_from_digest'); db.commit()
        self.assertEqual(store.get(thread, node, user)['thread_id'], thread)
        with closing(sqlite3.connect(store.path)) as db:
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchall(), [(6,)])


if __name__ == '__main__':
    unittest.main()
