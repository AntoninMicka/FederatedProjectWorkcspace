# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.backend_contract import BackendResponseError, BackendUnknown
from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaBindings
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.role_workflow_service import (WORKFLOW_END, WORKFLOW_MARKER,
                                          RoleWorkflowService)
from spikes.role_workflows import RoleWorkflows
from spikes.metadata import ValidationError, validate_snapshot
from spikes.storage import Git
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from tests import test_local_api


class RoleWorkflowServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.node = self.base / 'node.json'; self.root = self.base / 'project'
        created = ProjectCreation(self.node).create('Project', str(self.root), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.root)
        self.public_id, self.private_id = str(uuid4()), str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=self.public_id, base_head=self.git.head(), title='Public source',
            body='Known public fact.\n', new=True), str(uuid4()))
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=self.private_id, base_head=self.git.head(), title='Private source',
            body='Confidential risk.\n', new=True), str(uuid4()), privacy='confidential')
        self.state = self.base / 'workflow-state'; self.state.mkdir(mode=0o700)
        self.calls = []
        self.base_binding = dict(schema_version=1, binding_id=str(uuid4()), revision='one',
            adapter='ollama', boundary='same-node', endpoint='http://127.0.0.1:11434',
            model='creator-model', target_id='local-process')
        OllamaBindings(self.state).save(OllamaBinding.parse(self.base_binding))

        def factory(runs):
            def transport(binding, raw):
                request = json.loads(raw); self.calls.append(request)
                response = ('# Draft\n\nBounded result.\n' if binding.model == 'creator-model'
                            else '# Review\n\nOne concrete weakness.\n')
                return {'model': binding.model, 'response': response}
            return OllamaAdapter(runs, transport=transport)
        self.factory = factory
        self.service = RoleWorkflowService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=factory)

    def binding(self, model, **changes):
        value = dict(self.base_binding)
        if model != value['model']:
            value['revision'] += '.run-model-' + hashlib.sha256(
                model.encode()).hexdigest()[:16]
        value['model'] = model
        value.update(changes)
        return value

    def request(self, **changes):
        value = dict(schema='fpw-role-workflow-v1', workflow_id=str(uuid4()),
            project_id=self.project_id, expected_head=self.git.head(),
            purpose={'input_id': str(uuid4()), 'content': 'Prepare a decision note.',
                     'privacy': 'project'},
            creator={'step_id': str(uuid4()), 'run_id': str(uuid4()),
                'manifest_id': str(uuid4()), 'role_id': 'creator',
                'role_revision': 'creator-v1', 'target': self.binding('creator-model'),
                'artifact_ids': [self.public_id]},
            opponent={'step_id': str(uuid4()), 'run_id': str(uuid4()),
                'manifest_id': str(uuid4()), 'role_id': 'opponent',
                'role_revision': 'opponent-v1', 'target': self.binding('opponent-model'),
                'artifact_ids': [self.private_id]})
        value.update(changes)
        return value

    def test_two_confirmed_steps_are_durable_isolated_and_hash_bound(self):
        request = self.request(); head = self.git.head()
        workflow = self.service.prepare(request)
        creator, opponent = workflow['steps']
        self.assertEqual((creator['state'], opponent['state']), ('prepared', 'unused'))
        self.assertEqual(self.calls, [])
        self.assertEqual(creator['privacy'], 'project')
        self.assertEqual(creator['provider_request']['model'], 'creator-model')
        with self.assertRaisesRegex(ValueError, 'approval differs'):
            self.service.dispatch_creator(request['workflow_id'], '0' * 64)

        workflow = self.service.dispatch_creator(request['workflow_id'],
                                                  creator['approval_digest'])
        creator = workflow['steps'][0]
        self.assertEqual((creator['state'], creator['response_sha256']),
                         ('succeeded', hashlib.sha256(
                             creator['response'].encode()).hexdigest()))
        self.assertRegex(creator['completed_at'], r'^\d{4}-\d{2}-\d{2}T.*Z$')
        self.assertEqual(creator['output']['schema'], 'fpw-workflow-step-output-v1')
        self.assertIsNone(creator['output']['previous_step_id'])
        self.assertEqual(creator['output']['sha256'], creator['response_sha256'])
        self.assertEqual(len(self.calls), 1)
        workflow = self.service.prepare_opponent(request['workflow_id'])
        opponent = workflow['steps'][1]
        self.assertEqual(opponent['state'], 'prepared')
        self.assertEqual(opponent['privacy'], 'confidential')
        prompt = opponent['provider_request']['prompt']
        self.assertIn('Critically review', prompt)
        self.assertIn('Bounded result.', prompt)
        self.assertIn('Confidential risk.', prompt)
        self.assertNotIn('Prepare a decision note.', prompt)
        self.assertNotIn('Create a bounded Markdown draft', prompt)
        self.assertEqual(len(self.calls), 1)

        workflow = self.service.dispatch_opponent(request['workflow_id'],
                                                   opponent['approval_digest'])
        self.assertEqual(workflow['steps'][1]['state'], 'succeeded')
        self.assertEqual(workflow['steps'][1]['output']['previous_step_id'],
                         request['creator']['step_id'])
        self.assertEqual([call['model'] for call in self.calls],
                         ['creator-model', 'opponent-model'])
        self.assertEqual(self.git.head(), head)

        restarted = RoleWorkflowService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=self.factory)
        final = restarted.dispatch_opponent(request['workflow_id'],
                                             opponent['approval_digest'])
        self.assertEqual(final['steps'][1]['state'], 'succeeded')
        self.assertEqual(len(self.calls), 2)

    def test_same_explicit_model_still_passes_only_materialized_handoff(self):
        request = self.request()
        request['opponent']['target'] = self.binding('creator-model')
        request['opponent']['artifact_ids'] = []
        workflow = self.service.prepare(request)
        workflow = self.service.dispatch_creator(
            request['workflow_id'], workflow['steps'][0]['approval_digest'])
        workflow = self.service.prepare_opponent(request['workflow_id'])
        prompt = workflow['steps'][1]['provider_request']['prompt']
        self.assertIn('Bounded result.', prompt)
        self.assertNotIn('Prepare a decision note.', prompt)
        self.assertNotIn('Known public fact.', prompt)
        workflow = self.service.dispatch_opponent(
            request['workflow_id'], workflow['steps'][1]['approval_digest'])
        self.assertEqual([call['model'] for call in self.calls],
                         ['creator-model', 'creator-model'])
        self.assertEqual(workflow['steps'][1]['state'], 'succeeded')

    @unittest.skipUnless(os.environ.get('WORKFLOW_OLLAMA_TEST') == '1',
                         'Set WORKFLOW_OLLAMA_TEST=1 for live Ollama workflow smoke')
    def test_live_ollama_creator_opponent_handoff(self):
        model = os.environ.get('WORKFLOW_OLLAMA_MODEL', 'phi:latest')
        self.base_binding.update(model=model, revision='live-one')
        OllamaBindings(self.state).save(OllamaBinding.parse(self.base_binding))
        service = RoleWorkflowService(self.node, Projects(self.node), state_dir=self.state)
        request = self.request(purpose={'input_id': str(uuid4()),
            'content': 'Write one short sentence, then review only that sentence.',
            'privacy': 'project'})
        request['creator']['target'] = self.binding(model)
        request['opponent']['target'] = self.binding(model)
        request['opponent']['artifact_ids'] = []
        workflow = service.prepare(request)
        workflow = service.dispatch_creator(
            request['workflow_id'], workflow['steps'][0]['approval_digest'])
        workflow = service.prepare_opponent(request['workflow_id'])
        creator = workflow['steps'][0]
        opponent_prompt = workflow['steps'][1]['provider_request']['prompt']
        self.assertIn(creator['response'], opponent_prompt)
        self.assertNotIn(request['purpose']['content'], opponent_prompt)
        workflow = service.dispatch_opponent(
            request['workflow_id'], workflow['steps'][1]['approval_digest'])
        self.assertEqual([step['state'] for step in workflow['steps']],
                         ['succeeded', 'succeeded'])
        self.assertEqual(workflow['steps'][1]['output']['previous_step_id'],
                         creator['step_id'])

    def test_crash_after_backend_success_reconciles_without_second_dispatch(self):
        request = self.request(); workflow = self.service.prepare(request)
        approval = workflow['steps'][0]['approval_digest']
        def checkpoint(stage):
            if stage == 'response-received':
                raise RuntimeError('workflow crash')
        with self.assertRaisesRegex(RuntimeError, 'workflow crash'):
            self.service.dispatch_creator(request['workflow_id'], approval,
                                          checkpoint=checkpoint)
        self.assertEqual(len(self.calls), 1)
        recovered = self.service.dispatch_creator(request['workflow_id'], approval)
        self.assertEqual(recovered['steps'][0]['state'], 'succeeded')
        self.assertEqual(len(self.calls), 1)

    def test_restart_recovers_each_dispatch_checkpoint_without_duplicate_effect(self):
        for stage, calls_before_restart in (
                ('run-bound', 0), ('response-received', 1), ('succeeded', 1)):
            with self.subTest(stage=stage):
                request = self.request(); workflow = self.service.prepare(request)
                approval = workflow['steps'][0]['approval_digest']
                before = len(self.calls)

                def checkpoint(current, expected=stage):
                    if current == expected:
                        raise RuntimeError('workflow crash at ' + expected)

                with self.assertRaisesRegex(RuntimeError, 'workflow crash'):
                    self.service.dispatch_creator(request['workflow_id'], approval,
                                                  checkpoint=checkpoint)
                self.assertEqual(len(self.calls) - before, calls_before_restart)
                restarted = RoleWorkflowService(self.node, Projects(self.node),
                    state_dir=self.state, adapter_factory=self.factory)
                recovered = restarted.dispatch_creator(request['workflow_id'], approval)
                self.assertEqual(recovered['steps'][0]['state'], 'succeeded')
                self.assertEqual(len(self.calls) - before, 1)

    def test_unknown_is_durable_and_cannot_be_retried(self):
        attempts = []
        def factory(runs):
            def transport(binding, raw):
                attempts.append(raw); raise TimeoutError('lost')
            return OllamaAdapter(runs, transport=transport)
        service = RoleWorkflowService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=factory)
        request = self.request(); workflow = service.prepare(request)
        approval = workflow['steps'][0]['approval_digest']
        with self.assertRaises(BackendUnknown):
            service.dispatch_creator(request['workflow_id'], approval)
        with self.assertRaisesRegex(ValueError, 'cannot be retried'):
            service.dispatch_creator(request['workflow_id'], approval)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(service.get(request['workflow_id'])['steps'][0]['state'], 'unknown')

    def test_known_and_oversized_failures_require_consciously_new_run(self):
        responses = [
            {'model': 'wrong-model', 'response': 'invalid'},
            {'model': 'creator-model', 'response': 'x' * (1024 * 1024 + 1)},
            {'model': 'creator-model', 'response': '# Fresh result\n'},
        ]
        attempts = []

        def factory(runs):
            def transport(binding, raw):
                attempts.append(json.loads(raw))
                return responses[len(attempts) - 1]
            return OllamaAdapter(runs, transport=transport)

        service = RoleWorkflowService(self.node, Projects(self.node),
            state_dir=self.state, adapter_factory=factory)
        for exception, message in ((BackendResponseError, 'Invalid Ollama response'),
                                   (ValidationError, 'exceeds 1 MiB')):
            request = self.request(); workflow = service.prepare(request)
            approval = workflow['steps'][0]['approval_digest']
            with self.assertRaisesRegex(exception, message):
                service.dispatch_creator(request['workflow_id'], approval)
            self.assertEqual(service.get(request['workflow_id'])['steps'][0]['state'],
                             'failed')
            with self.assertRaisesRegex(ValueError, 'cannot be retried'):
                service.dispatch_creator(request['workflow_id'], approval)

        fresh = self.request(); workflow = service.prepare(fresh)
        workflow = service.dispatch_creator(
            fresh['workflow_id'], workflow['steps'][0]['approval_digest'])
        self.assertEqual(workflow['steps'][0]['state'], 'succeeded')
        self.assertEqual(len(attempts), 3)

    def test_selected_result_publication_is_idempotent_and_preserves_provenance(self):
        request = self.request(); workflow = self.service.prepare(request)
        workflow = self.service.dispatch_creator(
            request['workflow_id'], workflow['steps'][0]['approval_digest'])
        workflow = self.service.prepare_opponent(request['workflow_id'])
        workflow = self.service.dispatch_opponent(
            request['workflow_id'], workflow['steps'][1]['approval_digest'])
        selected = workflow['steps'][1]
        publication = {'workflow_id': request['workflow_id'],
            'step_id': selected['step_id'], 'result_sha256': selected['response_sha256'],
            'project_id': self.project_id, 'expected_head': self.git.head(),
            'artifact_id': str(uuid4()), 'title': 'Independent review',
            'created_at': '2026-10-06T12:00:00Z', 'operation_id': str(uuid4())}
        original = self.git.head()
        with self.assertRaisesRegex(RuntimeError, 'publication crash'):
            self.service.publish(publication, checkpoint=lambda stage: (
                (_ for _ in ()).throw(RuntimeError('publication crash'))
                if stage == 'publishing' else None))
        self.assertEqual(self.git.head(), original)
        self.assertEqual(self.service.get(request['workflow_id'])['publish_state'],
                         'publishing')

        seen = False
        def checkpoint(stage):
            nonlocal seen
            if stage == 'workspace-complete' and not seen:
                seen = True
                raise RuntimeError('publication crash')
        with self.assertRaisesRegex(RuntimeError, 'publication crash'):
            self.service.publish(publication, checkpoint=checkpoint)
        committed = self.git.head()
        result = self.service.publish(publication)
        self.assertEqual((result['state'], result['receipt']['commit_id']),
                         ('published', committed))
        self.assertEqual(self.service.publish(publication)['receipt']['commit_id'], committed)
        self.assertEqual(self.git.head(), committed)
        files = self.git.snapshot(committed); entities = validate_snapshot(files)
        metadata = entities[publication['artifact_id']]
        self.assertEqual((metadata['privacy'], metadata['provenance']),
                         ('confidential', 'llm-generated'))
        self.assertEqual({item['target_id'] for item in metadata['relations']},
                         {self.public_id, self.private_id})
        raw = files[f'artifacts/{publication["artifact_id"]}/content.md']
        record = json.loads(raw.split(WORKFLOW_MARKER.encode(), 1)[1]
                            .split(WORKFLOW_END.encode(), 1)[0])
        self.assertEqual(record['schema'], 'fpw-role-workflow-provenance-v1')
        self.assertEqual(record['selected_step']['result_sha256'],
                         selected['response_sha256'])
        self.assertEqual(record['previous_step']['step_id'],
                         request['creator']['step_id'])
        self.assertNotIn('content', record['previous_step'])
        self.assertNotIn('endpoint', record['selected_step']['execution'])
        self.assertNotIn('tls_cert_sha256', record['selected_step']['execution'])

        with self.assertRaisesRegex(ValueError, 'unavailable to this owner'):
            self.service.get(request['workflow_id'], owner_id=str(uuid4()))

    def test_stale_head_identity_and_privacy_boundary_fail_closed(self):
        duplicate = str(uuid4())
        request = self.request()
        request['opponent']['run_id'] = request['creator']['run_id']
        with self.assertRaisesRegex(ValueError, 'identities must be distinct'):
            self.service.prepare(request)

        request = self.request(expected_head='0' * 40)
        with self.assertRaisesRegex(ValueError, 'Project changed'):
            self.service.prepare(request)

        request = self.request()
        request['creator']['target']['binding_id'] = str(uuid4())
        with self.assertRaisesRegex(ValueError, 'not the configured'):
            self.service.prepare(request)

        request = self.request(purpose={'input_id': str(uuid4()),
            'content': 'Local purpose', 'privacy': 'local-only'})
        with self.assertRaisesRegex(ValueError, 'Web workflow cannot expose local-only'):
            self.service.prepare(request, owner_id=str(uuid4()), allow_local_only=False)

        request = self.request(purpose={'input_id': duplicate, 'content': 'Local purpose',
                                       'privacy': 'local-only'})
        request['creator']['target'] = self.binding('creator-model', revision='lan',
            boundary='private-network', endpoint='https://10.0.0.2:11434',
            target_id=str(uuid4()), tls_cert_sha256='a' * 64)
        OllamaBindings(self.state).save(OllamaBinding.parse(request['creator']['target']))
        with self.assertRaisesRegex(ValueError, 'local-only requires same-node'):
            self.service.prepare(request)
        self.assertEqual(self.calls, [])

    def test_stale_selection_policy_head_and_binding_fail_before_dispatch(self):
        request = self.request(); workflow = self.service.prepare(request)
        changed = json.loads(json.dumps(request))
        changed['creator']['artifact_ids'] = [self.private_id]
        with self.assertRaisesRegex(ValueError, 'different request'):
            self.service.prepare(changed)

        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=str(uuid4()), base_head=self.git.head(), title='Changed HEAD',
            body='new bytes\n', new=True), str(uuid4()))
        with self.assertRaisesRegex(ValueError, 'Project changed'):
            self.service.dispatch_creator(
                request['workflow_id'], workflow['steps'][0]['approval_digest'])

        request = self.request(); workflow = self.service.prepare(request)
        with patch.object(RoleWorkflowService, 'policy_revision', 'changed-policy'):
            with self.assertRaisesRegex(ValueError, 'Authority changed'):
                self.service.dispatch_creator(
                    request['workflow_id'], workflow['steps'][0]['approval_digest'])

        request = self.request(); workflow = self.service.prepare(request)
        changed_binding = dict(self.base_binding, revision='two')
        OllamaBindings(self.state).save(OllamaBinding.parse(changed_binding))
        with self.assertRaisesRegex(ValueError, 'invalid model revision'):
            self.service.dispatch_creator(
                request['workflow_id'], workflow['steps'][0]['approval_digest'])

    def test_authenticated_desktop_api_keeps_prepare_dispatch_and_publish_separate(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler,
                         projects=Projects(self.node)) as server:
            server.role_workflow_service = self.service
            request = self.request()
            response = driver.request(server, path='/v1/workflows/prepare',
                                      body=json.dumps(request).encode())
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head); workflow = json.loads(body)
            self.assertEqual(self.calls, [])
            response = driver.request(server, path='/v1/workflows/creator/dispatch',
                body=json.dumps({'workflow_id': request['workflow_id'],
                    'project_id': self.project_id,
                    'approval_digest': workflow['steps'][0]['approval_digest']}).encode())
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            self.assertEqual(json.loads(body)['steps'][0]['state'], 'succeeded')
            self.assertEqual(len(self.calls), 1)
            response = driver.request(server, path='/v1/workflows/status',
                body=json.dumps({'project_id': self.project_id}).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            driver.rejected(server, path='/v1/workflows/status',
                            body=json.dumps({'project_id': self.project_id}).encode(),
                            headers={'Authorization': None})

    def test_v1_journal_migrates_publication_columns_transactionally(self):
        legacy = self.base / 'legacy-workflows'; legacy.mkdir(mode=0o700)
        path = legacy / 'role-workflows.sqlite'
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE schema_info(version INTEGER NOT NULL);
                INSERT INTO schema_info VALUES(1);
                CREATE TABLE workflows(
                    workflow_id TEXT PRIMARY KEY,node_id TEXT NOT NULL,user_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,expected_head TEXT NOT NULL,
                    request_digest TEXT NOT NULL,request_json BLOB NOT NULL);
                CREATE TABLE steps(
                    workflow_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
                    step_id TEXT NOT NULL UNIQUE,run_id TEXT NOT NULL UNIQUE,
                    manifest_id TEXT NOT NULL UNIQUE,role_id TEXT NOT NULL,
                    role_revision TEXT NOT NULL,state TEXT NOT NULL,approval_digest TEXT,
                    preview_json BLOB,manifest BLOB,payload BLOB,privacy TEXT,
                    provider_request BLOB,response BLOB,response_sha256 TEXT,
                    completed_at TEXT,error TEXT,PRIMARY KEY(workflow_id,ordinal));
            ''')
        path.chmod(0o600)
        with RoleWorkflows(legacy).connect() as db:
            self.assertEqual(db.execute('SELECT version FROM schema_info').fetchone(), (2,))
            columns = [row[1] for row in db.execute('PRAGMA table_info(workflows)')]
            self.assertEqual(columns[-4:], ['publish_state', 'publish_digest',
                                            'publish_json', 'receipt_json'])


if __name__ == '__main__':
    unittest.main()
