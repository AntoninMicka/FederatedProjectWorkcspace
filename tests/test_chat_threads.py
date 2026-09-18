# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from spikes.chat_threads import ChatThreads
from spikes.metadata import ValidationError


NOW = '2026-09-18T12:00:00Z'


class ChatThreadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.state = Path(self.temporary.name) / 'state'; self.state.mkdir(mode=0o700)
        self.store = ChatThreads(self.state)
        self.thread_id, self.node_id, self.user_id = map(lambda _: str(uuid4()), range(3))
        self.store.create(thread_id=self.thread_id, node_id=self.node_id,
                          user_id=self.user_id, created_at=NOW)

    def prepare(self, **changes):
        request = dict(thread_id=self.thread_id, node_id=self.node_id, user_id=self.user_id,
                       turn_id=str(uuid4()), message_id=str(uuid4()), content='Question',
                       privacy='project', created_at=NOW)
        request.update(changes)
        return request

    def test_lifecycle_survives_restart_and_reconciliation_is_idempotent(self):
        request = self.prepare(); run_id = str(uuid4()); answer_id = str(uuid4())
        prepared = self.store.prepare_turn(**request)
        self.assertEqual(prepared['state'], 'prepared')
        restarted = ChatThreads(self.state)
        self.assertEqual(restarted.prepare_turn(**request)['state'], 'prepared')
        self.assertEqual(restarted.bind_run(turn_id=request['turn_id'], node_id=self.node_id,
                                           user_id=self.user_id, run_id=run_id)['state'], 'run-bound')
        completed = ChatThreads(self.state).complete(
            turn_id=request['turn_id'], node_id=self.node_id, user_id=self.user_id,
            run_id=run_id, message_id=answer_id, content='Answer', privacy='project',
            created_at='2026-09-18T12:00:01Z')
        self.assertEqual(completed['state'], 'completed')
        # Retrying any earlier receipt after completion returns the same durable turn.
        self.assertEqual(restarted.prepare_turn(**request)['state'], 'completed')
        self.assertEqual(restarted.bind_run(turn_id=request['turn_id'], node_id=self.node_id,
                                           user_id=self.user_id, run_id=run_id)['state'], 'completed')
        restarted.complete(turn_id=request['turn_id'], node_id=self.node_id,
                           user_id=self.user_id, run_id=run_id, message_id=answer_id,
                           content='Answer', privacy='project',
                           created_at='2026-09-18T12:00:01Z')
        thread = restarted.get(self.thread_id, self.node_id, self.user_id)
        self.assertEqual([message['role'] for message in thread['messages']],
                         ['user', 'assistant'])
        self.assertEqual([message['sequence'] for message in thread['messages']], [1, 2])
        self.assertEqual(thread['revision'], 2)

    def test_crash_before_each_commit_rolls_back_without_partial_state(self):
        request = self.prepare()
        def crash(stage):
            raise RuntimeError(stage)
        with self.assertRaisesRegex(RuntimeError, 'prepared'):
            self.store.prepare_turn(**request, checkpoint=crash)
        self.assertEqual(self.store.get(self.thread_id, self.node_id, self.user_id)['messages'], [])
        self.store.prepare_turn(**request)
        run_id = str(uuid4())
        with self.assertRaisesRegex(RuntimeError, 'run-bound'):
            self.store.bind_run(turn_id=request['turn_id'], node_id=self.node_id,
                                user_id=self.user_id, run_id=run_id, checkpoint=crash)
        self.assertEqual(self.store.get_turn(request['turn_id'], self.node_id,
                                             self.user_id)['state'], 'prepared')
        self.store.bind_run(turn_id=request['turn_id'], node_id=self.node_id,
                            user_id=self.user_id, run_id=run_id)
        with self.assertRaisesRegex(RuntimeError, 'completed'):
            self.store.complete(turn_id=request['turn_id'], node_id=self.node_id,
                                user_id=self.user_id, run_id=run_id,
                                message_id=str(uuid4()), content='Answer', privacy='project',
                                created_at=NOW, checkpoint=crash)
        thread = self.store.get(self.thread_id, self.node_id, self.user_id)
        self.assertEqual(len(thread['messages']), 1)
        self.assertEqual(self.store.get_turn(request['turn_id'], self.node_id,
                                             self.user_id)['state'], 'run-bound')

    def test_unknown_failure_and_archive_are_explicit(self):
        request = self.prepare(); run_id = str(uuid4())
        self.store.prepare_turn(**request)
        with self.assertRaisesRegex(ValidationError, 'active turn'):
            self.store.archive(self.thread_id, self.node_id, self.user_id)
        self.store.bind_run(turn_id=request['turn_id'], node_id=self.node_id,
                            user_id=self.user_id, run_id=run_id)
        terminal = self.store.finish(turn_id=request['turn_id'], node_id=self.node_id,
                                     user_id=self.user_id, run_id=run_id, state='unknown',
                                     error='lost response')
        self.assertEqual(terminal['state'], 'unknown')
        self.assertEqual(self.store.finish(turn_id=request['turn_id'], node_id=self.node_id,
                                          user_id=self.user_id, run_id=run_id, state='unknown',
                                          error='lost response'), terminal)
        archived = self.store.archive(self.thread_id, self.node_id, self.user_id)
        self.assertEqual(archived['status'], 'archived')
        with self.assertRaisesRegex(ValidationError, 'archived'):
            self.store.prepare_turn(**self.prepare())

    def test_owner_validation_input_limits_and_corruption_fail_closed(self):
        other = str(uuid4())
        with self.assertRaisesRegex(ValidationError, 'owner'):
            self.store.get(self.thread_id, self.node_id, other)
        for changes in ({'privacy': 'secret'}, {'content': ' '},
                        {'content': 'x' * (1024 * 1024 + 1)}):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.store.prepare_turn(**self.prepare(**changes))
        request = self.prepare(); self.store.prepare_turn(**request)
        with sqlite3.connect(self.store.path) as db:
            db.execute("UPDATE messages SET content=X'80' WHERE message_id=?",
                       (request['message_id'],))
        with self.assertRaises((ValidationError, ValueError)):
            self.store.get(self.thread_id, self.node_id, self.user_id)

    def test_concurrent_appends_have_one_strict_order(self):
        requests = [self.prepare(content='Question ' + str(index)) for index in range(2)]
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda request: ChatThreads(self.state).prepare_turn(**request), requests))
        thread = self.store.get(self.thread_id, self.node_id, self.user_id)
        self.assertEqual([message['sequence'] for message in thread['messages']], [1, 2])
        self.assertEqual({message['content'] for message in thread['messages']},
                         {'Question 0', 'Question 1'})

    def test_schema_version_permissions_and_unknown_tables_are_rejected(self):
        self.store.path.chmod(0o644)
        with self.assertRaisesRegex(ValidationError, 'Unsafe'):
            ChatThreads(self.state).connect()
        self.store.path.chmod(0o600)
        with sqlite3.connect(self.store.path) as db:
            db.execute('UPDATE schema_info SET version=2')
        with self.assertRaisesRegex(ValidationError, 'version'):
            ChatThreads(self.state).connect()

        other_state = Path(self.temporary.name) / 'other'; other_state.mkdir(mode=0o700)
        path = other_state / 'chat-threads.sqlite'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE foreign_table(value TEXT)')
        path.chmod(0o600)
        with self.assertRaisesRegex(ValidationError, 'schema'):
            ChatThreads(other_state).connect()


if __name__ == '__main__':
    unittest.main()
