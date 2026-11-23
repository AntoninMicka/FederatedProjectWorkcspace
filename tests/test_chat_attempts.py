# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import subprocess
import sys
import unittest
from uuid import uuid4

from spikes.chat_attempts import ChatAttempts
from spikes.task_work import TaskWork
from tests import test_task_work as fixtures


class ChatAttemptTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.TaskWorkTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.work = self.f.service
        self.work.chat_state_dir.mkdir(mode=0o700)
        self.service = ChatAttempts(self.work)
        self.request = dict(project_id=self.f.f.pid, task_id=str(uuid4()), thread_id=str(uuid4()),
            run_id=str(uuid4()), manifest_id=str(uuid4()), content='Řádek úkolu\n' * 1800,
            privacy='project', secret='NEVER PERSIST UNKNOWN FIELDS')

    def begin(self):
        return self.service.begin('/v1/tasks/route-stream', self.request)

    def test_submitted_text_survives_process_death_without_any_model_or_git_effect(self):
        before = self.work.projects.repository(self.f.f.pid).head()
        script = '''import json,os,sys
from spikes.chat_attempts import ChatAttempts
from spikes.task_work import TaskWork
ChatAttempts(TaskWork(sys.argv[1])).begin('/v1/tasks/route',json.loads(sys.argv[2]))
os._exit(79)
'''
        result = subprocess.run([sys.executable, '-c', script, str(self.f.f.node), json.dumps(self.request)])
        self.assertEqual(result.returncode, 79)
        summary = self.service.list(self.f.f.pid)[0]
        self.assertNotIn('content', summary); self.assertEqual(len(summary['preview']), 160)
        self.assertEqual(summary['state'], 'unknown')
        restored = ChatAttempts(TaskWork(self.f.f.node)).list(self.f.f.pid, self.request['task_id'])[0]
        self.assertEqual(restored['content'], self.request['content'])
        self.assertNotIn('NEVER PERSIST', json.dumps(restored))
        self.assertEqual(self.work.projects.repository(self.f.f.pid).head(), before)

    def test_failure_is_recoverable_replay_is_bound_and_success_cannot_be_downgraded(self):
        identifier = self.begin(); self.service.finish(identifier, 422, {})
        self.assertEqual(self.begin(), identifier)
        with self.assertRaises(ValueError):
            self.service.begin('/v1/tasks/route', dict(self.request, content='Different request'))
        self.assertEqual(self.service.list(self.f.f.pid)[0]['state'], 'failed')
        self.service.finish(identifier, 200, {})
        self.service.finish(identifier, 422, {})
        self.assertEqual(self.service.list(self.f.f.pid), [])
        with self.service.store.connect() as db:
            doc=json.loads(db.execute('SELECT doc FROM chat_attempts').fetchone()[0])
        self.assertNotIn('content', doc)

    def test_identity_project_revocation_and_local_only_boundary(self):
        identifier = self.begin()
        other = TaskWork(self.f.f.node, str(uuid4()))
        self.assertEqual(ChatAttempts(other).list(self.f.f.pid), [])
        self.work.can_read = lambda pid: False
        self.assertEqual(self.service.list(self.f.f.pid, identifier), [])
        self.work.can_read = lambda pid: True
        self.service.finish(identifier, 200, {})
        self.request.update(task_id=str(uuid4()), privacy='local-only')
        self.begin(); self.work.network = True
        self.assertEqual(self.service.list(self.f.f.pid), [])
        self.assertIsNone(self.begin())

    def test_diagnostic_does_not_store_exception_text_paths_or_secrets(self):
        identifier = self.begin()
        try:
            raise ValueError('https://user:SECRET@host/private-source')
        except ValueError as exc:
            self.service.error(identifier, exc)
        doc = self.service.list(self.f.f.pid, identifier)[0]
        self.assertNotIn('SECRET', json.dumps(doc))
        self.assertEqual(doc['diagnostic']['exception_type'], 'ValueError')
        self.assertEqual(doc['diagnostic']['code'], 'request-rejected')

    def test_malformed_input_and_unknown_routes_are_not_captured(self):
        self.assertIsNone(self.service.begin('/v1/tasks/list', self.request))
        self.assertIsNone(self.service.begin('/v1/tasks/route', dict(self.request, privacy=[])))
        self.assertIsNone(self.service.begin('/v1/tasks/route', dict(self.request, project_id='bad')))

    def test_older_generic_privacy_refusal_is_explained_without_rewriting_receipt(self):
        import hashlib
        from spikes.task_file_edit import FileEditPrivacyConflict
        identifier = self.begin()
        with self.service.store.connect() as db:
            row = db.execute('SELECT doc FROM chat_attempts').fetchone()[0]
            doc = json.loads(row)
            doc['diagnostic'] = dict(code='request-rejected', message='Generic',
                reason_sha256=hashlib.sha256(FileEditPrivacyConflict.reason.encode()).hexdigest())
            raw = json.dumps(doc)
            db.execute('UPDATE chat_attempts SET doc=?', (raw,))
            db.commit()
        result = self.service.list(self.f.f.pid, identifier)[0]
        self.assertEqual(result['diagnostic']['code'], FileEditPrivacyConflict.code)
        with self.service.store.connect() as db:
            self.assertEqual(db.execute('SELECT doc FROM chat_attempts').fetchone()[0], raw)

    def test_discard_removes_text_and_late_finalization_cannot_revive_it(self):
        identifier = self.begin()
        self.service.discard(self.f.f.pid, identifier)
        self.service.finish(identifier, 422, {})
        self.assertEqual(self.service.list(self.f.f.pid, identifier), [])
        with self.service.store.connect() as db:
            doc=json.loads(db.execute('SELECT doc FROM chat_attempts').fetchone()[0])
        self.assertNotIn('content', doc); self.assertEqual(doc['state'], 'discarded')
        self.assertEqual(self.begin(), identifier)

    def test_concurrent_discard_and_failure_never_resurrect_the_prompt(self):
        from concurrent.futures import ThreadPoolExecutor
        for action in ('finish', 'error'):
            with self.subTest(action=action):
                self.request['task_id'] = str(uuid4()); identifier = self.begin()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(self.service.discard, self.f.f.pid, identifier)
                    if action == 'finish':
                        second = pool.submit(self.service.finish, identifier, 422, {})
                    else:
                        second = pool.submit(self.service.error, identifier, ValueError('private reason'))
                    first.result(); second.result()
                self.assertEqual(self.service.list(self.f.f.pid, identifier), [])
                with self.service.store.connect() as db:
                    doc=json.loads(db.execute('SELECT doc FROM chat_attempts WHERE id=?',(identifier,)).fetchone()[0])
                self.assertNotIn('content',doc);self.assertEqual(doc['state'],'discarded')
