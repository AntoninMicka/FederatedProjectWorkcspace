# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from spikes.chat_threads import ChatThreads
from spikes.external_dispatch import ExternalDispatches
from spikes.metadata import ValidationError
from spikes.ollama_backend import OllamaRuns
from spikes.openai_backend import OpenAIRuns
from spikes.task_outcomes import TaskOutcomes
from spikes.thread_lifecycle import ThreadLifecycle


NOW = '2026-10-11T08:00:00Z'


class NoProjects:
    def workspace(self, *_args, **_kwargs):
        raise AssertionError('unassigned thread must not open a project')


class ThreadLifecycleTests(unittest.TestCase):
    def build(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'state'; root.mkdir(mode=0o700)
        node_id, user_id, thread_id = (str(uuid4()) for _ in range(3))
        turn_id, message_id, answer_id, run_id = (str(uuid4()) for _ in range(4))
        threads = ChatThreads(root)
        threads.create(thread_id=thread_id, node_id=node_id, user_id=user_id, created_at=NOW)
        threads.prepare_turn(thread_id=thread_id, node_id=node_id, user_id=user_id,
            turn_id=turn_id, message_id=message_id, content='Question', privacy='project',
            created_at=NOW)
        threads.bind_run(turn_id=turn_id, node_id=node_id, user_id=user_id, run_id=run_id)
        threads.complete(turn_id=turn_id, node_id=node_id, user_id=user_id, run_id=run_id,
            message_id=answer_id, content='Answer', privacy='project', created_at=NOW)
        with OllamaRuns(root).connect() as db:
            db.execute('INSERT INTO runs(run_id,request_digest,state,response) VALUES(?,?,?,?)',
                       (run_id, 'a' * 64, 'succeeded', json.dumps({'response': 'Answer'})))
            db.commit()

        task_id, task_run, manifest_id = (str(uuid4()) for _ in range(3))
        request = {'task_id': task_id, 'thread_id': thread_id}
        outcome = {'schema_version': 1, 'kind': 'direct-answer', 'content': 'Task answer'}
        with TaskOutcomes(root).connect() as db:
            db.execute('INSERT INTO outcomes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (task_id, node_id, user_id, str(uuid4()), thread_id,
                 json.dumps(request), json.dumps(outcome), 'project', 'a' * 40,
                 task_run, manifest_id, NOW, 'completed', json.dumps(outcome)))
            db.commit()
        with OllamaRuns(root).connect() as db:
            db.execute('INSERT INTO runs(run_id,request_digest,state,response) VALUES(?,?,?,?)',
                       (task_run, 'b' * 64, 'succeeded', json.dumps({'response': 'Task'})))
            db.commit()

        approval_id, external_run = str(uuid4()), str(uuid4())
        external_request = {'thread_id': thread_id, 'run_id': external_run,
                            'record_chat': True,
                            'run_choice': {'mode': 'brainstorming'}}
        with ExternalDispatches(root).connect() as db:
            db.execute('INSERT INTO approvals(approval_id,node_id,user_id,request,manifest,'
                'payload,provider_request,preview_sha256,binding_sha256,privacy,created_at,'
                'state,result,error,run_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (approval_id, node_id, user_id, json.dumps(external_request), b'{}', b'{}',
                 b'{}', 'c' * 64, 'd' * 64, 'project', NOW, 'succeeded', '{}', None,
                 external_run))
            db.commit()
        with OpenAIRuns(root).connect() as db:
            db.execute('INSERT INTO runs(run_id,request_digest,state,response) VALUES(?,?,?,?)',
                       (external_run, 'e' * 64, 'succeeded', json.dumps({'response': 'External'})))
            db.commit()
        return root, node_id, user_id, thread_id

    def test_preview_and_confirm_remove_supported_local_state(self):
        root, node_id, user_id, thread_id = self.build()
        service = ThreadLifecycle(root, NoProjects())
        preview = service.preview(thread_id=thread_id, node_id=node_id, user_id=user_id)
        self.assertEqual(preview['counts'], {'messages': 2, 'turns': 1,
            'task_outcomes': 1, 'approvals': 1, 'backend_runs': 3})
        self.assertEqual(preview['blockers'], [])
        self.assertTrue(preview['published_git_history_preserved'])
        operation_id = str(uuid4())
        receipt = service.confirm(thread_id=thread_id, node_id=node_id, user_id=user_id,
            operation_id=operation_id, expected_revision=preview['expected_revision'],
            preview_sha256=preview['preview_sha256'])
        self.assertEqual(receipt['state'], 'completed')
        self.assertEqual(service.confirm(thread_id=thread_id, node_id=node_id, user_id=user_id,
            operation_id=operation_id, expected_revision=preview['expected_revision'],
            preview_sha256=preview['preview_sha256']), receipt)
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            ChatThreads(root).get(thread_id, node_id, user_id)
        for filename, table in (('task-outcomes.sqlite', 'outcomes'),
                                ('external-dispatches.sqlite', 'approvals'),
                                ('ollama-runs.sqlite', 'runs'),
                                ('openai-runs.sqlite', 'runs')):
            with sqlite3.connect(root / filename) as db:
                self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_each_committed_boundary_recovers_idempotently(self):
        for boundary in ('planned', 'marked', 'approvals', 'outcomes', 'runs', 'thread',
                         'completed'):
            with self.subTest(boundary=boundary):
                root, node_id, user_id, thread_id = self.build()
                service = ThreadLifecycle(root, NoProjects())
                preview = service.preview(thread_id=thread_id, node_id=node_id, user_id=user_id)
                operation_id = str(uuid4())
                def crash(stage):
                    if stage == boundary: raise RuntimeError(stage)
                with self.assertRaisesRegex(RuntimeError, boundary):
                    service.confirm(thread_id=thread_id, node_id=node_id, user_id=user_id,
                        operation_id=operation_id,
                        expected_revision=preview['expected_revision'],
                        preview_sha256=preview['preview_sha256'], checkpoint=crash)
                receipt = ThreadLifecycle(root, NoProjects()).confirm(
                    thread_id=thread_id, node_id=node_id, user_id=user_id,
                    operation_id=operation_id, expected_revision=preview['expected_revision'],
                    preview_sha256=preview['preview_sha256'])
                self.assertEqual(receipt['state'], 'completed')

    def test_active_and_unknown_effects_block_delete(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / 'state'; root.mkdir(mode=0o700)
        node_id, user_id, thread_id = (str(uuid4()) for _ in range(3))
        threads = ChatThreads(root)
        threads.create(thread_id=thread_id, node_id=node_id, user_id=user_id, created_at=NOW)
        request = dict(thread_id=thread_id, node_id=node_id, user_id=user_id,
            turn_id=str(uuid4()), message_id=str(uuid4()), content='Question',
            privacy='project', created_at=NOW)
        threads.prepare_turn(**request)
        lifecycle = ThreadLifecycle(root, NoProjects())
        preview = lifecycle.preview(thread_id=thread_id, node_id=node_id, user_id=user_id)
        self.assertEqual(preview['blockers'][0]['state'], 'prepared')
        with self.assertRaisesRegex(ValidationError, 'active or unknown'):
            lifecycle.confirm(thread_id=thread_id, node_id=node_id, user_id=user_id,
                operation_id=str(uuid4()), expected_revision=preview['expected_revision'],
                preview_sha256=preview['preview_sha256'])

    def test_stale_preview_foreign_owner_and_other_thread_fail_closed(self):
        root, node_id, user_id, thread_id = self.build()
        other_thread = str(uuid4())
        threads = ChatThreads(root)
        threads.create(thread_id=other_thread, node_id=node_id, user_id=user_id, created_at=NOW)
        lifecycle = ThreadLifecycle(root, NoProjects())
        with self.assertRaisesRegex(ValidationError, 'unavailable'):
            lifecycle.preview(thread_id=thread_id, node_id=node_id, user_id=str(uuid4()))
        preview = lifecycle.preview(thread_id=thread_id, node_id=node_id, user_id=user_id)
        threads.archive(thread_id, node_id, user_id)
        with self.assertRaisesRegex(ValidationError, 'changed'):
            lifecycle.confirm(thread_id=thread_id, node_id=node_id, user_id=user_id,
                operation_id=str(uuid4()), expected_revision=preview['expected_revision'],
                preview_sha256=preview['preview_sha256'])
        with lifecycle.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)
        refreshed = lifecycle.preview(thread_id=thread_id, node_id=node_id, user_id=user_id)
        lifecycle.confirm(thread_id=thread_id, node_id=node_id, user_id=user_id,
            operation_id=str(uuid4()), expected_revision=refreshed['expected_revision'],
            preview_sha256=refreshed['preview_sha256'])
        self.assertEqual(threads.get(other_thread, node_id, user_id)['thread_id'], other_thread)


if __name__ == '__main__':
    unittest.main()
