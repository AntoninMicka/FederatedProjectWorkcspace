# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from contextlib import closing
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.action_autonomy import digest
from spikes.autonomy_service import AutonomyService
from spikes.backend_contract import BackendUnknown
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git
from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.local_api import running_api
from spikes.web_search import SearchUnknown
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

    def dynamic_plan(self, steps, *, max_steps=1, max_cost=1):
        return {'schema_version': 3, 'workflow_id': self.workflow_id,
            'project_id': self.project_id, 'expected_head': self.git.head(),
            'mode': 'manual', 'privacy': 'project', 'countdown_seconds': 3,
            'policy': {'actions': [
                {'id': 'analysis.read-only', 'version': '1.0'}],
                'permissions': ['project-read'],
                'execution_boundaries': ['local-node']},
            'budget': {'max_steps': max_steps, 'max_cost_units': max_cost,
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
            def prepare_search(self, request):
                calls.append(('prepare-search', request)); return {'state': 'proposed'}
            def edit_search(self, workflow_id, query):
                calls.append(('edit-search', workflow_id, query)); return {'state': 'queued'}
            def send_now(self, workflow_id, step_id, dispatch_digest):
                calls.append(('send-now', workflow_id, step_id, dispatch_digest))
                return {'state': 'queued'}
            def propose_revision(self, request):
                calls.append(('revision-propose', request)); return {'state': 'queued'}
            def confirm_revision(self, workflow_id, proposal_id, approval_digest):
                calls.append(('revision-confirm', workflow_id, proposal_id,
                              approval_digest)); return {'state': 'queued'}
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
            response = driver.request(server, path='/v1/autonomy/search/prepare',
                body=json.dumps({'workflow_id': self.workflow_id}).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            response = driver.request(server, path='/v1/autonomy/search/edit',
                body=json.dumps({'workflow_id': self.workflow_id,
                                 'query': 'upravený dotaz'}).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            response = driver.request(server, path='/v1/autonomy/send-now',
                body=json.dumps({'workflow_id': self.workflow_id,
                    'step_id': str(uuid4()), 'dispatch_digest': '1' * 64}).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            proposal = {'workflow_id': self.workflow_id, 'proposal_id': str(uuid4())}
            response = driver.request(server, path='/v1/autonomy/revision/propose',
                body=json.dumps(proposal).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
            response = driver.request(server, path='/v1/autonomy/revision/confirm',
                body=json.dumps({'workflow_id': self.workflow_id,
                    'proposal_id': proposal['proposal_id'],
                    'approval_digest': '2' * 64}).encode())
            self.assertIn(b' 200 ', response.split(b'\r\n', 1)[0])
        self.assertEqual(calls[:3], [('list', self.project_id),
                                    ('attach', self.workflow_id), ('pause-all', None)])
        self.assertTrue({'/v1/autonomy/status', '/v1/autonomy/replace',
                         '/v1/autonomy/advance',
                         '/v1/autonomy/search/prepare',
                         '/v1/autonomy/search/edit', '/v1/autonomy/send-now',
                         '/v1/autonomy/revision/propose',
                         '/v1/autonomy/revision/confirm',
                         '/v1/autonomy/pause-all'} <= DesktopHandler.post_paths)
        for marker in ('id="autonomy-queue"', 'id="autonomy-plan-json"',
                       'id="autonomy-plan-example"',
                       'id="autonomy-plan-dynamic-example"',
                       '#autonomy-list', '.search-autonomy{',
                       "autonomyRequest('/v1/autonomy/advance'",
                       "projectRequest('/v1/autonomy/search/prepare'",
                       "autonomyRequest('/v1/autonomy/send-now'",
                       "autonomyRequest('/v1/autonomy/revision/propose'",
                       "autonomyRequest('/v1/autonomy/revision/confirm'",
                       "dynamicRevisionDraft(workflow,kind)",
                       'elapsedSeconds+300',
                       'const autonomyViewState=new Map()',
                       "matches('.autonomy-revision-editor textarea')",
                       'view.draft=textarea.value',
                       'className=\'search-autonomy-countdown\'',
                       "setInterval(refreshAutonomyLease,5000)"):
            self.assertIn(marker, HTML if marker.startswith('id=') else
                          CSS if marker.startswith(('#', '.')) else JS)

    def test_service_stages_and_confirms_exact_dynamic_budget_revision(self):
        first = self.step('analysis.read-only', {'selection_sha256': '1' * 64})
        proposed = self.service.prepare(self.dynamic_plan([first]))
        self.service.attach(self.workflow_id)
        self.service.activate(self.workflow_id, proposed['activation_digest'])
        self.service.advance(self.workflow_id)
        self.service.approve(self.workflow_id, first['step_id'])
        completed = self.service.advance(self.workflow_id)
        self.assertEqual((completed['plan_schema_version'],
                          completed['remaining_steps'], completed['remaining_cost']),
                         (3, 0, 0))
        second = self.step('analysis.read-only', {'selection_sha256': '1' * 64},
                           depends=[first['step_id']])
        revision = {'schema_version': 1, 'proposal_id': str(uuid4()),
            'workflow_id': self.workflow_id,
            'base_revision': completed['plan_revision'],
            'base_plan_digest': completed['plan_revisions'][-1]['plan_digest'],
            'kind': 'append', 'reason': 'Pokračovat druhou analýzou.',
            'step': second, 'repeat_of': None,
            'budget': {'max_steps': 2, 'max_cost_units': 2,
                       'max_seconds': 3600}}
        pending = self.service.propose_revision(revision)
        stored = pending['revision_proposals'][-1]
        self.assertEqual((stored['state'], pending['plan_revision']), ('pending', 1))
        self.service.detach(self.workflow_id)
        with self.assertRaisesRegex(ValidationError, 'live pending'):
            self.service.confirm_revision(self.workflow_id, revision['proposal_id'],
                                          stored['approval_digest'])
        self.service.attach(self.workflow_id)
        confirmed = self.service.confirm_revision(
            self.workflow_id, revision['proposal_id'], stored['approval_digest'])
        self.assertEqual((confirmed['plan_revision'], confirmed['remaining_steps'],
                          len(confirmed['steps'])), (2, 0, 2))

    def test_search_ui_plan_can_be_edited_and_sent_now_through_exact_queue_step(self):
        task_id, parent_id = str(uuid4()), str(uuid4())
        class SearchChat(ChatStub):
            def candidate(inner, request, state):
                preview = {'schema_version': 2, **request,
                    'query': request['query'], 'purpose': 'Ověřit tvrzení',
                    'privacy': 'project', 'round_index': 2,
                    'parent_search_id': request['parent_search_id'], 'result_limit': 3,
                    'budget': {'max_rounds': 3, 'max_queries': 3,
                               'max_results': 30, 'max_seconds': 300},
                    'language': 'cs-CZ',
                    'binding': {'adapter': 'searxng', 'endpoint': 'http://127.0.0.1:8888',
                                'target_id': 'local-process'},
                    'message_ids': [], 'artifact_ids': [], 'warning': 'Untrusted.'}
                return dict(preview, preview_sha256=digest(preview), state=state)
            def task_search_autonomy_candidate(inner, request):
                inner.calls.append(('autonomy-candidate', request))
                return {'request': request, 'preview': inner.candidate(request, 'candidate'),
                        'project_id': self.project_id, 'expected_head': self.git.head()}
            def task_search_candidate(inner, request):
                inner.calls.append(('candidate', request))
                return inner.candidate(request, 'candidate')
            def task_search_preview(inner, request):
                inner.calls.append(('preview', request))
                return inner.candidate(request, 'prepared')
            def task_search_confirm(inner, request):
                inner.calls.append(('confirm', request))
                return {'state': 'completed', 'search_workflow': {
                    'rounds': [{'round_index': 2}], 'next_queries': []}}
        chat = SearchChat()
        service = AutonomyService(self.node, Projects(self.node), state_dir=self.state,
            chat_service=chat, role_workflow_service=self.roles, countdown_seconds=0)
        proposed = service.prepare_search({'workflow_id': self.workflow_id,
            'task_id': task_id, 'mode': 'automatic', 'countdown_seconds': 4,
            'parent_search_id': parent_id, 'query': 'první návrh'})
        self.assertEqual((proposed['state'], proposed['countdown_seconds']), ('proposed', 4))
        service.attach(self.workflow_id)
        service.activate(self.workflow_id, proposed['activation_digest'])
        edited = service.edit_search(self.workflow_id, 'upravený dotaz')
        self.assertEqual(edited['steps'][0]['input']['preview']['query'], 'upravený dotaz')
        self.assertEqual(edited['revisions'][0]['state'], 'cancelled')
        countdown = service.advance(self.workflow_id)
        self.assertEqual(countdown['state'], 'countdown')
        dispatched = service.send_now(self.workflow_id, countdown['steps'][0]['step_id'],
                                      countdown['steps'][0]['dispatch_digest'])
        self.assertEqual(dispatched['steps'][0]['state'], 'completed')
        self.assertEqual([call[0] for call in chat.calls].count('confirm'), 1)

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

    def test_unknown_search_effect_is_not_retried_by_autonomy_adapter(self):
        task_id, search_id = str(uuid4()), str(uuid4())
        request = {'task_id': task_id, 'search_id': search_id,
            'synthesis_run_id': str(uuid4()), 'synthesis_manifest_id': str(uuid4())}
        preview = {'schema_version': 2, **request, 'query': 'uncertain',
            'purpose': 'Test', 'privacy': 'project', 'round_index': 1,
            'parent_search_id': None, 'result_limit': 3,
            'budget': {'max_rounds': 3, 'max_queries': 3,
                       'max_results': 30, 'max_seconds': 300},
            'language': 'cs-CZ', 'binding': {'adapter': 'searxng'},
            'message_ids': [], 'artifact_ids': [], 'warning': 'Untrusted.'}
        preview_sha256 = digest(preview)
        class SearchChat(ChatStub):
            def task_search_candidate(inner, value):
                inner.calls.append(('candidate', value))
                return dict(preview, preview_sha256=preview_sha256, state='candidate')
            def task_search_preview(inner, value):
                inner.calls.append(('preview', value))
                return dict(preview, preview_sha256=preview_sha256, state='prepared')
            def task_search_confirm(inner, value):
                inner.calls.append(('confirm', value))
                raise SearchUnknown('search outcome unknown')
        chat = SearchChat()
        service = AutonomyService(self.node, Projects(self.node), state_dir=self.state,
            chat_service=chat, role_workflow_service=self.roles, countdown_seconds=0)
        step_id = str(uuid4())
        plan = {'schema_version': 2, 'workflow_id': self.workflow_id,
            'project_id': self.project_id, 'expected_head': self.git.head(),
            'mode': 'automatic', 'privacy': 'project', 'countdown_seconds': 3,
            'continuation': {'kind': 'iterative-search-v1', 'task_id': task_id,
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'follow_up_policy': 'first-proposed-v1'},
            'budget': {'max_steps': 3, 'max_cost_units': 3, 'max_seconds': 300},
            'steps': [{'step_id': step_id,
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'privacy': 'project', 'cost_units': 1, 'depends_on': [],
                'input': {'request': request, 'preview': preview,
                          'preview_sha256': preview_sha256}}]}
        proposed = service.prepare(plan); service.attach(self.workflow_id)
        service.activate(self.workflow_id, proposed['activation_digest'])
        service.advance(self.workflow_id)
        with closing(sqlite3.connect(service.queue.path)) as db:
            db.execute("UPDATE steps SET not_before='2000-01-01T00:00:00Z' "
                       "WHERE step_id=?", (step_id,)); db.commit()
        service.attach(self.workflow_id)
        unknown = service.advance(self.workflow_id)
        self.assertEqual((unknown['state'], unknown['steps'][0]['state']),
                         ('unknown', 'unknown'))
        with self.assertRaisesRegex(ValidationError, 'not runnable'):
            service.advance(self.workflow_id)
        self.assertEqual([item[0] for item in chat.calls].count('confirm'), 1)

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

    def test_research_planner_materializes_one_confirmed_budget_revision(self):
        research_id, planner_run_id = str(uuid4()), str(uuid4())
        source_run_id, task_id, search_id = (str(uuid4()) for _ in range(3))
        source_ref = {'task_id': task_id, 'search_id': search_id,
            'source_id': 'source-' + 'a' * 32, 'run_id': source_run_id,
            'adapter': 'static-html-v1', 'binding_revision': 'reader-r1',
            'url': 'https://example.test/evidence',
            'origin': 'https://example.test', 'raw_sha256': '1' * 64,
            'text_sha256': '2' * 64, 'projection_sha256': '3' * 64}
        selection = {'selected_source_run_ids': [source_run_id],
                     'rejected': [], 'limitations': []}
        goal = 'Prepare a bounded report draft.'
        report_input = {'research_id': research_id, 'goal': goal,
            'goal_sha256': hashlib.sha256(goal.encode()).hexdigest(),
            'run_id': str(uuid4()), 'manifest_id': str(uuid4()),
            'selected_source_run_ids': [source_run_id],
            'selection_sha256': digest(selection), 'analysis_run_id': None,
            'analysis_sha256': None, 'task_id': task_id}
        candidate = {'action': {'id': 'research.compose-report', 'version': '1.0'},
            'privacy': 'project', 'cost_units': 8, 'input': report_input}
        proposal = {'decision': 'append', 'reason': 'Evidence is selected.',
            'target_action': 'research.compose-report', 'candidate': candidate,
            'repeat_step_id': None, 'finish_reason': None}
        planner_output = {'schema_version': 1, 'kind': 'research-next-step',
            'research_id': research_id, 'run_id': planner_run_id,
            'manifest_id': str(uuid4()), **proposal,
            'proposal_sha256': digest(proposal)}

        class ResearchChat(ChatStub):
            def research_model_action(inner, action_id, value, execution):
                inner.calls.append((action_id, value, execution))
                return planner_output

            def research_public_source(inner, run_id):
                if run_id != source_run_id:
                    raise ValueError('unknown source')
                return {'reference': source_ref, 'project_id': self.project_id,
                        'privacy': 'project', 'content': b'Evidence',
                        'projection_schema': 'public-source-structured-v1'}

        chat = ResearchChat()
        service = AutonomyService(self.node, Projects(self.node),
            state_dir=self.state, chat_service=chat,
            role_workflow_service=self.roles, countdown_seconds=0)
        ledger = []
        planner_input = {'research_id': research_id, 'goal': goal,
            'goal_sha256': hashlib.sha256(goal.encode()).hexdigest(),
            'run_id': planner_run_id, 'manifest_id': planner_output['manifest_id'],
            'profile_id': 'quick-search-v1', 'profile_version': '1.0',
            'plan_revision': 1, 'ledger': ledger,
            'ledger_sha256': digest(ledger), 'remaining_budget': {
                'max_steps': 0, 'max_cost_units': 0, 'max_seconds': 900}}
        planner = self.step('research.plan-next', planner_input)
        planner['cost_units'] = 2
        dynamic = {'schema_version': 3, 'workflow_id': self.workflow_id,
            'project_id': self.project_id, 'expected_head': self.git.head(),
            'mode': 'manual', 'privacy': 'project', 'countdown_seconds': 3,
            'policy': {'actions': [
                {'id': 'research.plan-next', 'version': '1.0'},
                {'id': 'research.compose-report', 'version': '1.0'}],
                'permissions': ['project-read', 'external-dispatch'],
                'execution_boundaries': ['private-network']},
            'budget': {'max_steps': 1, 'max_cost_units': 2,
                       'max_seconds': 900}, 'steps': [planner]}
        proposed = service.prepare(dynamic); service.attach(self.workflow_id)
        service.activate(self.workflow_id, proposed['activation_digest'])
        awaiting = service.advance(self.workflow_id)
        self.assertEqual(awaiting['steps'][0]['state'], 'awaiting-approval')
        service.approve(self.workflow_id, planner['step_id'])
        pending = service.advance(self.workflow_id)
        self.assertEqual(pending['steps'][0]['state'], 'completed')
        self.assertEqual(len(pending['revision_proposals']), 1)
        revision = pending['revision_proposals'][0]
        self.assertEqual(revision['state'], 'pending')
        self.assertEqual(revision['proposal']['budget'], {
            'max_steps': 2, 'max_cost_units': 10, 'max_seconds': 900})

        restarted = AutonomyService(self.node, Projects(self.node),
            state_dir=self.state, chat_service=chat,
            role_workflow_service=self.roles, countdown_seconds=0)
        recovered = restarted.get(self.workflow_id)
        node_id, user_id = restarted._identity()
        replayed = restarted._materialize_planner(recovered, node_id, user_id)
        self.assertEqual(len(replayed['revision_proposals']), 1)
        restarted.attach(self.workflow_id)
        confirmed = restarted.confirm_revision(self.workflow_id,
            revision['proposal_id'], revision['approval_digest'])
        self.assertEqual((confirmed['plan_revision'], len(confirmed['steps'])),
                         (2, 2))
        self.assertEqual(confirmed['steps'][1]['action']['id'],
                         'research.compose-report')
        self.assertEqual(len(chat.calls), 1)

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
