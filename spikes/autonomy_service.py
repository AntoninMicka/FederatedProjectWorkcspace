# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Application boundary joining governed queue steps to existing domain journals."""
import os
from pathlib import Path
import stat
from uuid import UUID, uuid5

from spikes.action_autonomy import (AutonomyQueue, UnknownEffect, digest,
                                     load_action_registry)
from spikes.backend_contract import BackendUnknown
from spikes.configuration import parse_node, read_config
from spikes.metadata import require, uuid
from spikes.project_creation import ProjectCreation
from spikes.web_search import SearchUnknown


class AutonomyService:
    """Node-owner PoC; domain services remain authorities for their effects."""
    def __init__(self, node_path, projects, *, state_dir, chat_service,
                 role_workflow_service, countdown_seconds=5):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.chat_service = chat_service
        self.role_workflow_service = role_workflow_service
        self.registry = load_action_registry()
        root = Path(state_dir).absolute()
        if not os.path.lexists(root):
            root.mkdir(mode=0o700)
        info = root.lstat()
        require(root.resolve() == root and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'Autonomy state directory requires owned mode 0700 without symlinks')
        self.queue = AutonomyQueue(root, self.registry, handlers={
            ('analysis.read-only', '1.0'): self._read_only,
            ('query.external', '1.0'): self._external,
            ('search.iterative-query', '1.0'): self._search,
            ('workflow.role-handoff', '1.0'): self._role_handoff,
            ('artifact.create-local', '1.0'): self._publish_artifact,
        }, countdown_seconds=countdown_seconds)

    def _identity(self):
        node = parse_node(read_config(self.node_path), location=self.node_path)
        return node['id'], ProjectCreation(self.node_path).author_id()

    def _owned(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.get(workflow_id, node_id, user_id)

    @staticmethod
    def _local_only(workflow):
        return (workflow['privacy'] == 'local-only'
                or any(step['privacy'] == 'local-only'
                       for step in workflow['steps']))

    def prepare(self, plan, *, allow_local_only=True):
        require(isinstance(plan, dict), 'Autonomy plan must be an object')
        if not allow_local_only:
            require(plan.get('privacy') != 'local-only'
                    and all(isinstance(step, dict)
                            and step.get('privacy') != 'local-only'
                            for step in plan.get('steps', [])),
                    'Web autonomy does not expose local-only plans')
        workspace = self.projects.workspace(plan.get('project_id'), blocking=False)
        require(workspace.git.head() == plan.get('expected_head'),
                'Project changed before autonomy plan preparation')
        node_id, user_id = self._identity()
        return self.queue.prepare(plan, node_id, user_id)

    def replace(self, plan, *, allow_local_only=True):
        require(isinstance(plan, dict), 'Autonomy plan must be an object')
        if not allow_local_only:
            require(plan.get('privacy') != 'local-only'
                    and all(isinstance(step, dict)
                            and step.get('privacy') != 'local-only'
                            for step in plan.get('steps', [])),
                    'Web autonomy does not expose local-only plans')
        workspace = self.projects.workspace(plan.get('project_id'), blocking=False)
        require(workspace.git.head() == plan.get('expected_head'),
                'Project changed before autonomy plan replacement')
        node_id, user_id = self._identity()
        return self.queue.replace_plan(plan, node_id, user_id)

    def get(self, workflow_id, *, allow_local_only=True):
        result = self._owned(workflow_id)
        require(allow_local_only or not self._local_only(result),
                'Web autonomy does not expose local-only plans')
        return result

    def list(self, project_id=None, *, allow_local_only=True):
        node_id, user_id = self._identity()
        result = self.queue.list(node_id, user_id, project_id)
        if not allow_local_only:
            result['workflows'] = [workflow for workflow in result['workflows']
                                   if not self._local_only(workflow)]
        return result

    def attach(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.attach_ui(workflow_id, node_id, user_id)

    def detach(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.detach_ui(workflow_id, node_id, user_id)

    def activate(self, workflow_id, activation_digest):
        node_id, user_id = self._identity()
        return self.queue.activate(workflow_id, node_id, user_id, activation_digest)

    def approve(self, workflow_id, step_id):
        node_id, user_id = self._identity()
        return self.queue.approve(workflow_id, step_id, node_id, user_id)

    def pause(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.pause(workflow_id, node_id, user_id)

    def resume(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.resume(workflow_id, node_id, user_id)

    def cancel(self, workflow_id):
        node_id, user_id = self._identity()
        return self.queue.cancel(workflow_id, node_id, user_id)

    def pause_all(self):
        self.queue.pause_all()
        return self.list()

    def resume_all(self):
        self.queue.resume_all()
        return self.list()

    def advance(self, workflow_id):
        current = self._owned(workflow_id)
        workspace = self.projects.workspace(current['project_id'], blocking=False)
        node_id, user_id = self._identity()
        result = self.queue.advance(workflow_id, node_id, user_id,
            permissions={'project-read', 'external-dispatch', 'role-dispatch',
                         'project-write'},
            allowed_privacy={'public', 'project', 'confidential', 'local-only'},
            expected_head=workspace.git.head())
        return self._append_search_continuation(result, node_id, user_id)

    @staticmethod
    def _read_only(value, execution):
        return {'schema_version': 1, 'kind': 'read-only-analysis-reference',
                'project_id': execution['project_id'],
                'project_commit': execution['expected_head'],
                'selection_sha256': value['selection_sha256']}

    def _external(self, value, execution):
        require(value['privacy'] == 'public',
                'Autonomous external action only accepts public input')
        try:
            self.chat_service.external_confirm({
                'approval_id': value['approval_id'],
                'preview_sha256': value['preview_sha256'],
                'approved': True, 'privacy': value['privacy']})
        except BackendUnknown as exc:
            raise UnknownEffect(str(exc)) from exc
        return {'schema_version': 1, 'kind': 'external-result-reference',
                'approval_id': value['approval_id'], 'state': 'recorded'}

    def _search(self, value, execution):
        require(set(value) == {'request', 'preview', 'preview_sha256'}
                and isinstance(value['request'], dict)
                and isinstance(value['preview'], dict)
                and isinstance(value['preview_sha256'], str),
                'Invalid iterative search autonomy input')
        candidate = self.chat_service.task_search_candidate(value['request'])
        candidate_preview = dict(candidate)
        candidate_sha = candidate_preview.pop('preview_sha256', None)
        candidate_preview.pop('state', None)
        require(candidate_preview == value['preview']
                and candidate_sha == value['preview_sha256'],
                'Iterative search preview changed before dispatch')
        prepared = self.chat_service.task_search_preview(value['request'])
        require(prepared['preview_sha256'] == value['preview_sha256'],
                'Iterative search preview changed while preparing dispatch')
        try:
            projection = self.chat_service.task_search_confirm({
                'task_id': value['request']['task_id'],
                'search_id': value['request']['search_id'],
                'preview_sha256': value['preview_sha256'], 'approved': True})
        except (BackendUnknown, SearchUnknown) as exc:
            raise UnknownEffect(str(exc)) from exc
        workflow = projection.get('search_workflow') or {}
        next_queries = workflow.get('next_queries') or []
        rounds = workflow.get('rounds') or []
        return {'schema_version': 1, 'kind': 'iterative-search-reference',
                'task_id': value['request']['task_id'],
                'search_id': value['request']['search_id'],
                'preview_sha256': value['preview_sha256'],
                'state': projection['state'],
                'round_index': (rounds[-1]['round_index'] if rounds else
                                value['preview']['round_index']),
                'next_query': next_queries[0] if next_queries else None}

    @staticmethod
    def _derived_id(workflow_id, round_index, revision, label):
        return str(uuid5(UUID(workflow_id),
                         f'iterative-search:{round_index}:{revision}:{label}'))

    def _append_search_continuation(self, workflow, node_id, user_id):
        if workflow.get('state') not in {'queued', 'paused'}:
            return workflow
        steps = workflow.get('steps') or []
        if not steps or steps[-1]['action'] != {
                'id': 'search.iterative-query', 'version': '1.0'}:
            return workflow
        result = steps[-1].get('result')
        if steps[-1].get('state') != 'completed' or not isinstance(result, dict):
            return workflow
        query = result.get('next_query')
        if query is None:
            return workflow
        round_index = result['round_index'] + 1; revision = 1
        request = {'task_id': result['task_id'],
            'search_id': self._derived_id(workflow['workflow_id'], round_index,
                                          revision, 'search'),
            'synthesis_run_id': self._derived_id(workflow['workflow_id'], round_index,
                                                 revision, 'synthesis-run'),
            'synthesis_manifest_id': self._derived_id(
                workflow['workflow_id'], round_index, revision, 'synthesis-manifest'),
            'parent_search_id': result['search_id'], 'query': query}
        candidate = self.chat_service.task_search_candidate(request)
        preview = dict(candidate); preview_sha256 = preview.pop('preview_sha256')
        preview.pop('state', None)
        step = {'step_id': self._derived_id(workflow['workflow_id'], round_index,
                                            revision, 'step'),
                'action': {'id': 'search.iterative-query', 'version': '1.0'},
                'privacy': preview['privacy'], 'cost_units': 1,
                'depends_on': [steps[-1]['step_id']],
                'input': {'request': request, 'preview': preview,
                          'preview_sha256': preview_sha256}}
        return self.queue.append_step(workflow['workflow_id'], step, node_id, user_id)

    def _role_handoff(self, value, execution):
        uuid(value['workflow_id'])
        require(isinstance(value['creator_sha256'], str)
                and len(value['creator_sha256']) == 64,
                'Invalid creator result digest')
        workflow = self.role_workflow_service.get(value['workflow_id'])
        require(workflow['project_id'] == execution['project_id'],
                'Role workflow belongs to a different project')
        creator = workflow['steps'][0]
        require(creator['state'] == 'succeeded'
                and creator['response_sha256'] == value['creator_sha256'],
                'Creator result differs from autonomy handoff')
        prepared = self.role_workflow_service.prepare_opponent(value['workflow_id'])
        opponent = prepared['steps'][1]
        return {'schema_version': 1, 'kind': 'role-handoff-reference',
                'workflow_id': value['workflow_id'],
                'step_id': opponent['step_id'], 'state': opponent['state'],
                'approval_digest': opponent['approval_digest']}

    def _publish_artifact(self, value, execution):
        request = value['request']
        required = {'workflow_id', 'step_id', 'result_sha256', 'project_id',
                    'expected_head', 'artifact_id', 'title', 'created_at', 'operation_id'}
        require(set(request) == required, 'Invalid autonomy publication request')
        require(request['project_id'] == execution['project_id']
                and request['expected_head'] == execution['expected_head'],
                'Autonomy publication project or HEAD differs')
        require(value['target'] == 'artifact:' + request['artifact_id']
                and value['content_type'] == 'text/markdown'
                and value['content_sha256'] == request['result_sha256'],
                'Autonomy publication output differs from exact approval')
        require(value['provenance'] == {'workflow_id': request['workflow_id'],
                                        'step_id': request['step_id']},
                'Autonomy publication provenance differs')
        result = self.role_workflow_service.publish(request)
        return {'schema_version': 1, 'kind': 'local-artifact-reference',
                'project_id': request['project_id'],
                'artifact_id': request['artifact_id'],
                'commit_id': result['commit_id'],
                'receipt_sha256': digest(result)}
