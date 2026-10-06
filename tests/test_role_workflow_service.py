# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.backend_contract import BackendUnknown
from spikes.ollama_backend import OllamaAdapter
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.role_workflow_service import RoleWorkflowService
from spikes.storage import Git


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

    @staticmethod
    def binding(model, **changes):
        value = dict(schema_version=1, binding_id=str(uuid4()), revision='one',
            adapter='ollama', boundary='same-node', endpoint='http://127.0.0.1:11434',
            model=model, target_id='local-process')
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

    def test_stale_head_identity_and_privacy_boundary_fail_closed(self):
        duplicate = str(uuid4())
        request = self.request()
        request['opponent']['run_id'] = request['creator']['run_id']
        with self.assertRaisesRegex(ValueError, 'identities must be distinct'):
            self.service.prepare(request)

        request = self.request(expected_head='0' * 40)
        with self.assertRaisesRegex(ValueError, 'Project changed'):
            self.service.prepare(request)

        request = self.request(purpose={'input_id': duplicate, 'content': 'Local purpose',
                                       'privacy': 'local-only'})
        request['creator']['target'] = self.binding('creator-model', revision='lan',
            boundary='private-network', endpoint='https://10.0.0.2:11434',
            target_id=str(uuid4()), tls_cert_sha256='a' * 64)
        with self.assertRaisesRegex(ValueError, 'local-only requires same-node'):
            self.service.prepare(request)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
