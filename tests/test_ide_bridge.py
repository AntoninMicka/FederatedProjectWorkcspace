# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from uuid import uuid4
import zipfile

from spikes.artifacts import Artifacts, main_todo_id
from spikes.ide_bridge import IdeBridge, endpoint
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects


class IdeBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.node = self.root / 'node.json'
        self.project = ProjectCreation(self.node).create('Bridge project', str(self.root / 'project'), str(uuid4()))['id']
        self.artifact = main_todo_id(self.project)
        self.head = Projects(self.node).open(self.project)['commit_id']
        self.body = '- [ ] [TASK-01] Implement feature\n- [ ] [TASK-02] Review\n'
        self.head = self.save(self.body)
        self.service = IdeBridge(self.node)

    def save(self, body, *, privacy='project', **extra):
        return Artifacts(self.node).save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Tasks', body=body,
            new=not any(a['id'] == self.artifact for a in Projects(self.node).open(self.project)['artifacts']),
            **extra), str(uuid4()), privacy=privacy)['commit_id']

    def create(self, **extra):
        return self.service.create(dict(project_id=self.project, expected_head=self.head,
            repository=str(self.root / 'project'), instructions='Use focused tests.', **extra),
            None, 'http://127.0.0.1:9999')

    def message(self, result):
        return dict(message_id=str(uuid4()), task_id='TASK-01', kind='completed', body='Verified tests.',
                    revision=result['revision'], repository_commit=self.head)

    def test_package_contains_scoped_pairing_and_no_project_write(self):
        result = self.create()
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(result['package_base64']))) as package:
            self.assertEqual(json.loads(package.read('extension/pairing.json')), result['pairing'])
            self.assertIn('extension.vsixmanifest', package.namelist())
            self.assertNotIn('FileSystemProvider', package.read('extension/extension.js').decode())
        self.assertNotIn(result['pairing']['token'], self.service.root.joinpath('bridge.sqlite').read_bytes().decode(errors='replace'))
        self.assertFalse(self.service.status(self.project)['sessions'][0]['revoked'])

    def test_retry_after_lost_response_and_collision_are_durable(self):
        created = self.create(); token = created['pairing']['token']
        session = self.service.session(token); message = self.message(created)
        request = dict(session_id=session['session_id'], messages=[message])
        first = self.service.exchange(session, request)
        restarted = IdeBridge(self.node)
        second = restarted.exchange(restarted.session(token), request)
        self.assertEqual(first['receipts'], second['receipts'])
        self.assertEqual('received', first['receipts'][0]['status'])
        self.assertEqual('pending-human-review', first['receipts'][0]['acceptance'])
        self.assertEqual(1, len(restarted.status(self.project)['sessions'][0]['messages']))
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])
        message['body'] = 'Changed under same ID'
        with self.assertRaisesRegex(ValidationError, 'different content'):
            restarted.exchange(session, request)

    def test_stale_messages_are_retained_without_accepting_completion(self):
        created = self.create(); session = self.service.session(created['pairing']['token'])
        self.head = self.save(self.body + '- [ ] [TASK-03] Changed plan\n')
        response = self.service.exchange(session, dict(session_id=session['session_id'], messages=[self.message(created)]))
        self.assertTrue(response['stale'])
        self.assertEqual('stale', response['receipts'][0]['status'])
        self.assertFalse(Projects(self.node).open(self.project)['plan']['nodes'][0]['checked'])

    def test_partial_batch_recovery_does_not_duplicate_committed_prefix(self):
        created = self.create(); session = self.service.session(created['pairing']['token'])
        first, second = self.message(created), self.message(created)
        bad = dict(second, task_id='FOREIGN')
        with self.assertRaises(ValidationError):
            self.service.exchange(session, dict(session_id=session['session_id'], messages=[first, bad]))
        self.assertEqual(1, len(self.service.status(self.project)['sessions'][0]['messages']))
        restarted = IdeBridge(self.node)
        result = restarted.exchange(restarted.session(created['pairing']['token']),
            dict(session_id=session['session_id'], messages=[first, second]))
        self.assertEqual(2, len(result['receipts']))
        self.assertEqual(2, len(restarted.status(self.project)['sessions'][0]['messages']))

    def test_wrong_scope_revision_and_revocation(self):
        created = self.create(); session = self.service.session(created['pairing']['token'])
        message = self.message(created)
        for field, value in [('task_id', 'FOREIGN'), ('revision', '0' * 64), ('kind', 'execute')]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.service.exchange(session, dict(session_id=session['session_id'], messages=[dict(message, **{field: value})]))
        with self.assertRaises(ValidationError):
            self.service.exchange(session, dict(session_id=str(uuid4()), messages=[]))
        self.service.revoke(self.project, session['session_id'])
        with self.assertRaisesRegex(ValidationError, 'revoked'):
            self.service.session(created['pairing']['token'])
        with self.assertRaisesRegex(ValidationError, 'revoked'):
            self.service.exchange(session, dict(session_id=session['session_id'], messages=[message]))

    def test_local_only_export_and_git_state_location_fail_closed(self):
        self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=str(uuid4()),
            base_head=self.head, title='Private', body='Private', new=True),
            str(uuid4()), privacy='local-only')['commit_id']
        with self.assertRaisesRegex(ValidationError, 'local-only'):
            self.create()
        nested = IdeBridge(self.root / 'project' / 'node.json')
        with self.assertRaisesRegex(ValidationError, 'outside Git'):
            with nested.database():
                pass

    def test_endpoint_validation_and_unsafe_storage(self):
        for value in ['http://remote.example:9999', 'https://user:secret@host:443', 'https://host:443/path']:
            with self.subTest(value=value), self.assertRaises(ValidationError): endpoint(value)
        target = self.root / 'foreign'; target.mkdir()
        self.service.root.symlink_to(target)
        with self.assertRaises(ValidationError): self.create()

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for extension transport tests')
    def test_extension_files_recovery_and_transport(self):
        result = subprocess.run(['node', '--test', 'tests/ide_bridge.test.js'],
                                capture_output=True, text=True, timeout=40)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
