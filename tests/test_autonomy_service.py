# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
import json
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.autonomy_service import AutonomyService
from spikes.backend_contract import BackendUnknown
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.local_api import running_api
from tests import test_local_api


class ChatStub:
    def __init__(self, unknown=False):
        self.calls = []; self.unknown = unknown

    def external_confirm(self, request):
        self.calls.append(request)
        if self.unknown:
            raise BackendUnknown('external outcome unknown')
        return {'approval_id': request['approval_id'], 'state': 'succeeded'}


class RoleStub:
    def __init__(self, project_id, creator_sha256):
        self.project_id = project_id; self.creator_sha256 = creator_sha256
        self.prepared = []; self.published = []

    def get(self, workflow_id):
        return {'workflow_id': workflow_id, 'project_id': self.project_id,
            'steps': [{'state': 'succeeded', 'response_sha256': self.creator_sha256}]}

    def prepare_opponent(self, workflow_id):
        self.prepared.append(workflow_id)
        return {'steps': [{}, {'step_id': str(uuid4()), 'state': 'prepared',
                               'approval_digest': '9' * 64}]}

    def publish(self, request):
        self.published.append(request)
        return {'commit_id': 'b' * 40, 'operation_id': request['operation_id']}


class AutonomyServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.node = self.base / 'node.json'; self.project = self.base / 'project'
        created = ProjectCreation(self.node).create(
            'Autonomy project', str(self.project), str(uuid4()))
        self.project_id = created['id']; self.git = Git(self.project)
        self.state = self.base / 'state'; self.state.mkdir(mode=0o700)
        self.creator_sha256 = '3' * 64
        self.chat = ChatStub(); self.roles = RoleStub(
            self.project_id, self.creator_sha256)
        self.service = AutonomyService(self.node, Projects(self.node),
            state_dir=self.state, chat_service=self.chat,
            role_workflow_service=self.roles, countdown_seconds=0)
        self.workflow_id = str(uuid4())

    def step(self, action_id, value, *, privacy='project', depends=None):
        return {'step_id': str(uuid4()),
            'action': {'id': action_id, 'version': '1.0'},
            'privacy': privacy, 'cost_units': 1,
            'depends_on': list(depends or []), 'input': value}

    def plan(self, steps, *, privacy='public'):
        return {'schema_version': 1, 'workflow_id': self.workflow_id,
            'project_id': self.project_id, 'expected_head': self.git.head(),
            'mode': 'automatic', 'privacy': privacy,
            'budget': {'max_steps': 16, 'max_cost_units': 100,
                       'max_seconds': 3600}, 'steps': steps}

    def activate(self, plan):
        proposed = self.service.prepare(plan)
        self.service.attach(self.workflow_id)
        return self.service.activate(self.workflow_id,
                                     proposed['activation_digest'])

    def test_existing_external_handoff_and_publication_journals_are_orchestrated(self):
        external = self.step('query.external', {'approval_id': str(uuid4()),
            'preview_sha256': '2' * 64, 'privacy': 'public'}, privacy='public')
        role_workflow_id = str(uuid4())
        handoff = self.step('workflow.role-handoff', {
            'workflow_id': role_workflow_id,
            'creator_sha256': self.creator_sha256}, depends=[external['step_id']])
        artifact_id, operation_id = str(uuid4()), str(uuid4())
        request = {'workflow_id': role_workflow_id,
            'step_id': str(uuid4()), 'result_sha256': self.creator_sha256,
            'project_id': self.project_id, 'expected_head': self.git.head(),
            'artifact_id': artifact_id, 'title': 'Approved result',
            'created_at': '2026-10-23T12:00:00Z', 'operation_id': operation_id}
        output = self.step('artifact.create-local', {
            'target': 'artifact:' + artifact_id, 'content_type': 'text/markdown',
            'content_sha256': self.creator_sha256, 'privacy': 'project',
            'provenance': {'workflow_id': role_workflow_id,
                           'step_id': request['step_id']}, 'request': request},
            depends=[handoff['step_id']])
        self.activate(self.plan([external, handoff, output]))

        awaiting = self.service.advance(self.workflow_id)
        self.assertEqual(awaiting['steps'][0]['state'], 'awaiting-approval')
        self.assertEqual(self.chat.calls, [])
        self.service.approve(self.workflow_id, external['step_id'])
        self.service.advance(self.workflow_id)
        self.service.advance(self.workflow_id)
        awaiting = self.service.advance(self.workflow_id)
        self.assertEqual(awaiting['steps'][2]['state'], 'awaiting-approval')
        self.assertEqual(len(self.chat.calls), 1)
        self.assertEqual(self.roles.prepared, [role_workflow_id])
        self.assertEqual(self.roles.published, [])
        self.service.approve(self.workflow_id, output['step_id'])
        completed_step = self.service.advance(self.workflow_id)
        self.assertEqual(completed_step['steps'][2]['state'], 'completed')
        completed = self.service.advance(self.workflow_id)
        self.assertEqual(completed['state'], 'completed')
        self.assertEqual(self.roles.published, [request])
        self.assertEqual(completed['steps'][2]['result']['artifact_id'], artifact_id)

    def test_desktop_api_exposes_bounded_queue_controls(self):
        calls = []
        class Service:
            def list(self, project_id=None):
                calls.append(('list', project_id))
                return {'schema_version': 1, 'global_paused': False, 'workflows': []}
            def attach(self, workflow_id):
                calls.append(('attach', workflow_id)); return {'workflow_id': workflow_id}
            def pause_all(self):
                calls.append(('pause-all', None)); return self.list()
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            server.autonomy_service = Service()
            response = driver.request(server, path='/v1/autonomy/status',
                body=json.dumps({'project_id': self.project_id}).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            response = driver.request(server, path='/v1/autonomy/attach',
                body=json.dumps({'workflow_id': self.workflow_id}).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            response = driver.request(server, path='/v1/autonomy/pause-all', body=b'{}')
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
        self.assertEqual(calls[:3], [('list', self.project_id),
                                    ('attach', self.workflow_id), ('pause-all', None)])
        self.assertTrue({'/v1/autonomy/status', '/v1/autonomy/replace',
                         '/v1/autonomy/advance',
                         '/v1/autonomy/pause-all'} <= DesktopHandler.post_paths)
        for marker in ('id="autonomy-queue"', 'id="autonomy-plan-json"',
                       'id="autonomy-plan-example"',
                       '#autonomy-list',
                       "autonomyRequest('/v1/autonomy/advance'",
                       "setInterval(refreshAutonomyLease,5000)"):
            self.assertIn(marker, HTML if marker.startswith('id=') else
                          CSS if marker.startswith('#') else JS)

    def test_unknown_domain_effect_is_terminal_and_stale_head_blocks_dispatch(self):
        self.chat.unknown = True
        external = self.step('query.external', {'approval_id': str(uuid4()),
            'preview_sha256': '2' * 64, 'privacy': 'public'}, privacy='public')
        self.activate(self.plan([external]))
        self.service.advance(self.workflow_id)
        self.service.approve(self.workflow_id, external['step_id'])
        result = self.service.advance(self.workflow_id)
        self.assertEqual((result['state'], result['steps'][0]['state']),
                         ('unknown', 'unknown'))

        self.workflow_id = str(uuid4()); self.chat.unknown = False
        analysis = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        self.activate(self.plan([analysis], privacy='project'))
        Artifacts(self.node).save(dict(project_id=self.project_id,
            artifact_id=str(uuid4()), base_head=self.git.head(), title='Changed',
            body='Changed after activation.\n', new=True), str(uuid4()))
        with self.assertRaisesRegex(ValidationError, 'Project changed'):
            self.service.advance(self.workflow_id)

    def test_exact_local_output_fields_are_rechecked_by_domain_adapter(self):
        role_workflow_id = str(uuid4())
        artifact_id = str(uuid4())
        request = {'workflow_id': role_workflow_id, 'step_id': str(uuid4()),
            'result_sha256': self.creator_sha256, 'project_id': self.project_id,
            'expected_head': self.git.head(), 'artifact_id': artifact_id,
            'title': 'Approved result', 'created_at': '2026-10-23T12:00:00Z',
            'operation_id': str(uuid4())}
        output = self.step('artifact.create-local', {
            'target': 'artifact:' + str(uuid4()), 'content_type': 'text/markdown',
            'content_sha256': self.creator_sha256, 'privacy': 'project',
            'provenance': {'workflow_id': role_workflow_id,
                           'step_id': request['step_id']}, 'request': request})
        self.activate(self.plan([output], privacy='project'))
        self.service.advance(self.workflow_id)
        self.service.approve(self.workflow_id, output['step_id'])
        with self.assertRaisesRegex(ValidationError, 'output differs'):
            self.service.advance(self.workflow_id)
        result = self.service.list(self.project_id)['workflows'][0]
        self.assertEqual((result['state'], result['steps'][0]['state']),
                         ('failed', 'failed'))
        self.assertEqual(self.roles.published, [])

    def test_web_projection_hides_local_only_plans(self):
        local = self.step('analysis.read-only', {'selection_sha256': '1' * 64},
                          privacy='local-only')
        self.service.prepare(self.plan([local], privacy='local-only'))
        self.assertEqual(len(self.service.list(self.project_id)['workflows']), 1)
        self.assertEqual(self.service.list(
            self.project_id, allow_local_only=False)['workflows'], [])
        with self.assertRaisesRegex(ValidationError, 'does not expose local-only'):
            self.service.get(self.workflow_id, allow_local_only=False)

        self.workflow_id = str(uuid4())
        with self.assertRaisesRegex(ValidationError, 'does not expose local-only'):
            self.service.prepare(self.plan([local], privacy='local-only'),
                                 allow_local_only=False)

    def test_service_replaces_only_an_undispatched_current_head_plan(self):
        analysis = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        original = self.plan([analysis], privacy='project')
        self.service.prepare(original)
        changed = dict(original, mode='manual',
                       budget={'max_steps': 2, 'max_cost_units': 2,
                               'max_seconds': 120})
        result = self.service.replace(changed)
        self.assertEqual((result['state'], result['mode']), ('proposed', 'manual'))
        self.assertEqual(result['budget']['max_cost_units'], 2)


if __name__ == '__main__':
    unittest.main()
