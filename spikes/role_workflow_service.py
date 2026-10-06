# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit two-step creator/opponent orchestration without project writes."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType

from spikes.backend_contract import BackendResponseError, BackendUnknown, ROLES
from spikes.configuration import parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
                                    PreparedContext, ProjectInput, TaskInstruction)
from spikes.metadata import ValidationError, require, uuid, validate_snapshot
from spikes.ollama_backend import BACKENDS, OllamaAdapter, OllamaRuns
from spikes.project_creation import ProjectCreation
from spikes.role_workflows import RoleWorkflows, canonical, digest


PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
CREATOR_INSTRUCTION = (
    'Create a bounded Markdown draft using only the supplied sources and purpose. '
    'Separate facts from assumptions and do not invent missing context.')
OPPONENT_INSTRUCTION = (
    'Critically review the supplied creator output against only the explicit sources. '
    'List concrete weaknesses, unsupported claims, risks, and proposed corrections in Markdown.')


class RoleWorkflowService:
    request_schema = 'fpw-role-workflow-v1'
    policy_revision = 'desktop-role-workflow-v1'

    def __init__(self, node_path, projects, *, state_dir=None, adapter_factory=None):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.state_dir = (Path(state_dir).absolute() if state_dir else
                          self.node_path.parent / ('.' + self.node_path.name + '.workflows'))
        self.adapter_factory = adapter_factory

    def _identity(self):
        node = parse_node(read_config(self.node_path), location=self.node_path)
        return node['id'], ProjectCreation(self.node_path).author_id()

    def _root(self):
        if not os.path.lexists(self.state_dir):
            self.state_dir.mkdir(mode=0o700)
        info = self.state_dir.lstat()
        require(self.state_dir.absolute() == self.state_dir.resolve()
                and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Workflow state directory requires owned mode 0700 without symlinks')
        return self.state_dir

    def _stores(self):
        root = self._root(); runs = OllamaRuns(root)
        adapter = self.adapter_factory(runs) if self.adapter_factory else OllamaAdapter(runs)
        return RoleWorkflows(root), adapter

    @staticmethod
    def _target(value):
        binding = BACKENDS.parse_binding(value)
        binding.capabilities().require('generate-text', 'text')
        return binding

    @classmethod
    def _validate_request(cls, request):
        require(isinstance(request, dict) and set(request) == {
            'schema', 'workflow_id', 'project_id', 'expected_head', 'purpose',
            'creator', 'opponent'}, 'Invalid role workflow request')
        require(request['schema'] == cls.request_schema,
                'Unsupported role workflow request')
        for key in ('workflow_id', 'project_id'):
            uuid(request[key])
        require(isinstance(request['expected_head'], str)
                and bool(re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',
                                      request['expected_head'])),
                'Invalid expected project commit')
        purpose = request['purpose']
        require(isinstance(purpose, dict)
                and set(purpose) == {'input_id', 'content', 'privacy'},
                'Invalid workflow purpose')
        uuid(purpose['input_id'])
        require(isinstance(purpose['content'], str) and bool(purpose['content'].strip())
                and '\0' not in purpose['content']
                and len(purpose['content'].encode()) <= 16 * 1024
                and purpose['privacy'] in PRIVACY_ORDER,
                'Invalid or oversized workflow purpose')
        for name, role_id, revision, minimum in (
                ('creator', 'creator', 'creator-v1', 1),
                ('opponent', 'opponent', 'opponent-v1', 0)):
            step = request[name]
            require(isinstance(step, dict) and set(step) == {
                'step_id', 'run_id', 'manifest_id', 'role_id', 'role_revision',
                'target', 'artifact_ids'}, f'Invalid {name} workflow step')
            require((step['role_id'], step['role_revision']) == (role_id, revision),
                    f'Unsupported {name} workflow role')
            ROLES.resolve(role_id, revision)
            for key in ('step_id', 'run_id', 'manifest_id'):
                uuid(step[key])
            ids = step['artifact_ids']
            require(isinstance(ids, list) and minimum <= len(ids) <= 64
                    and len(ids) == len(set(ids)),
                    f'{name.capitalize()} requires {minimum} to 64 unique artifacts')
            for value in ids:
                uuid(value)
            cls._target(step['target'])
        require(request['purpose']['input_id'] not in
                request['creator']['artifact_ids'] + request['opponent']['artifact_ids'],
                'Purpose ID must not overlap selected artifacts')
        structural = [request['workflow_id']]
        for name in ('creator', 'opponent'):
            structural.extend(request[name][key]
                              for key in ('step_id', 'run_id', 'manifest_id'))
        require(len(structural) == len(set(structural)),
                'Workflow and step identities must be distinct')
        return request

    def _authority(self, workflow_id, step_id, user_id, node_id, readable):
        return Authority(f'workflow:{workflow_id}:{step_id}', user_id, node_id,
                         self.policy_revision, frozenset(readable))

    @staticmethod
    def _prepared(step):
        return PreparedContext(MappingProxyType(step['manifest']),
                               canonical(step['manifest']), step['payload'])

    @staticmethod
    def _preview(workflow_id, ordinal, step_id, prepared, provider_request, privacy):
        manifest = dict(prepared.manifest)
        return {'schema': 'fpw-role-workflow-preview-v1',
                'workflow_id': workflow_id, 'ordinal': ordinal,
                'step_id': step_id,
                'run_id': manifest['run_id'], 'manifest_id': manifest['manifest_id'],
                'project_id': manifest['project_id'],
                'project_commit': manifest['project_commit'],
                'role_id': manifest['task']['role_id'],
                'role_revision': manifest['task']['role_revision'],
                'target': manifest['target'], 'privacy': privacy,
                'inputs': manifest['inputs'],
                'provider_request_sha256': digest(provider_request)}

    @staticmethod
    def _result(workflow):
        result = dict(workflow)
        for step in result['steps']:
            raw = step.pop('provider_request')
            step.pop('payload')
            if raw is not None:
                step['provider_request'] = json.loads(raw)
            if step['response'] is not None:
                definition = workflow['request'][
                    'creator' if step['ordinal'] == 1 else 'opponent']
                step['output'] = {
                    'schema': 'fpw-workflow-step-output-v1',
                    'workflow_id': workflow['workflow_id'],
                    'step_id': step['step_id'], 'run_id': step['run_id'],
                    'manifest_id': step['manifest_id'],
                    'previous_step_id': (None if step['ordinal'] == 1 else
                                         workflow['steps'][0]['step_id']),
                    'role_id': step['role_id'],
                    'role_revision': step['role_revision'],
                    'execution': definition['target'],
                    'privacy': step['privacy'],
                    'created_at': step['completed_at'],
                    'inputs': [dict(input_id=item['input_id'], source=item['source'],
                                    privacy=item['privacy'], size=item['size'],
                                    sha256=item['sha256'])
                               for item in step['manifest']['inputs']],
                    'content': step['response'],
                    'sha256': step['response_sha256']}
        return result

    def prepare(self, request):
        request = self._validate_request(request)
        node_id, user_id = self._identity(); workflows, adapter = self._stores()
        try:
            existing = workflows.get(request['workflow_id'], node_id, user_id)
        except ValidationError as exc:
            if 'unavailable to this owner' not in str(exc):
                raise
            existing = None
        if existing is not None:
            require(existing['request_digest'] == digest(canonical(request)),
                    'Workflow ID belongs to a different request')
            return self._result(existing)

        creator = request['creator']; binding = self._target(creator['target'])
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        require(workspace.git.head() == request['expected_head'],
                'Project changed before workflow preparation')
        files = workspace.git.snapshot(request['expected_head'])
        entities = validate_snapshot(files); ids = creator['artifact_ids']
        require(all(value in entities for value in ids),
                'Selected creator artifact is unavailable')
        authority = self._authority(request['workflow_id'], creator['step_id'],
                                    user_id, node_id, ids)
        builder = ContextBuilder(workspace, request['project_id'])
        purpose = request['purpose']
        prepared = builder.prepare(manifest_id=creator['manifest_id'],
            run_id=creator['run_id'], authority=authority, target=binding.target(),
            project_inputs=tuple(ProjectInput(value) for value in ids),
            ad_hoc_inputs=(AdHocInput(purpose['input_id'], purpose['content'].encode(),
                                     purpose['privacy']),),
            task=TaskInstruction('creator', 'creator-v1', CREATOR_INSTRUCTION,
                                 purpose['input_id']))
        handoff = builder.authorize_for_dispatch(prepared, authority=authority,
                                                 target=binding.target())
        role = ROLES.resolve('creator', 'creator-v1')
        provider_request = adapter._request(handoff, binding, role, 'text')[0]
        privacy = max([purpose['privacy']] + [entities[value]['privacy'] for value in ids],
                      key=PRIVACY_ORDER.__getitem__)
        preview = self._preview(request['workflow_id'], 1, creator['step_id'], prepared,
                                provider_request, privacy)
        creator_data = {'preview': preview,
                        'approval_digest': digest(canonical(preview) + b'\0' + provider_request),
                        'manifest': canonical(dict(prepared.manifest)),
                        'payload': prepared.payload, 'privacy': privacy,
                        'provider_request': provider_request}
        workflow = workflows.prepare(request=request, node_id=node_id, user_id=user_id,
                                     creator=creator_data)
        return self._result(workflow)

    def prepare_opponent(self, workflow_id):
        uuid(workflow_id)
        node_id, user_id = self._identity(); workflows, adapter = self._stores()
        workflow = workflows.get(workflow_id, node_id, user_id)
        creator, opponent = workflow['steps']
        require(creator['state'] == 'succeeded',
                'Creator output is not available for opponent handoff')
        if opponent['state'] != 'unused':
            return self._result(workflow)
        request = workflow['request']; definition = request['opponent']
        binding = self._target(definition['target'])
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        require(workspace.git.head() == request['expected_head'],
                'Project changed before opponent handoff')
        files = workspace.git.snapshot(request['expected_head'])
        entities = validate_snapshot(files); ids = definition['artifact_ids']
        require(all(value in entities for value in ids),
                'Selected opponent artifact is unavailable')
        authority = self._authority(workflow_id, definition['step_id'], user_id,
                                    node_id, ids)
        builder = ContextBuilder(workspace, request['project_id'])
        creator_raw = creator['response'].encode('utf-8')
        prepared = builder.prepare(manifest_id=definition['manifest_id'],
            run_id=definition['run_id'], authority=authority, target=binding.target(),
            project_inputs=tuple(ProjectInput(value) for value in ids),
            ad_hoc_inputs=(AdHocInput(creator['step_id'], creator_raw,
                                     creator['privacy']),),
            task=TaskInstruction('opponent', 'opponent-v1', OPPONENT_INSTRUCTION,
                                 creator['step_id']))
        handoff = builder.authorize_for_dispatch(prepared, authority=authority,
                                                 target=binding.target())
        role = ROLES.resolve('opponent', 'opponent-v1')
        provider_request = adapter._request(handoff, binding, role, 'text')[0]
        privacy = max([creator['privacy']] + [entities[value]['privacy'] for value in ids],
                      key=PRIVACY_ORDER.__getitem__)
        preview = self._preview(workflow_id, 2, definition['step_id'], prepared,
                                provider_request, privacy)
        opponent_data = {'preview': preview,
            'approval_digest': digest(canonical(preview) + b'\0' + provider_request),
            'manifest': canonical(dict(prepared.manifest)), 'payload': prepared.payload,
            'privacy': privacy, 'provider_request': provider_request}
        workflow = workflows.prepare_opponent(workflow_id, node_id, user_id, opponent_data)
        return self._result(workflow)

    def _dispatch(self, workflow_id, ordinal, approval_digest, checkpoint):
        require(isinstance(approval_digest, str)
                and bool(re.fullmatch(r'[0-9a-f]{64}', approval_digest)),
                'Invalid workflow approval digest')
        node_id, user_id = self._identity(); workflows, adapter = self._stores()
        workflow = workflows.get(workflow_id, node_id, user_id)
        step = workflow['steps'][ordinal - 1]
        require(step['approval_digest'] == approval_digest,
                'Workflow preview approval differs from prepared request')
        if step['state'] == 'succeeded':
            return self._result(workflow)
        require(step['state'] in {'prepared', 'run-bound'},
                'Workflow step cannot be retried automatically')
        definition = workflow['request']['creator' if ordinal == 1 else 'opponent']
        binding = self._target(definition['target'])
        role = ROLES.resolve(step['role_id'], step['role_revision'])
        if ordinal == 2:
            creator = workflow['steps'][0]
            handoff_inputs = [item for item in step['manifest']['inputs']
                              if item['input_id'] == creator['step_id']]
            require(len(handoff_inputs) == 1
                    and handoff_inputs[0]['source'] == 'ad-hoc'
                    and handoff_inputs[0]['sha256'] == creator['response_sha256']
                    and handoff_inputs[0]['privacy'] == creator['privacy'],
                    'Opponent handoff differs from durable creator output')
        run = adapter.runs.get(step['run_id'])
        if run is not None and run['state'] == 'succeeded':
            workflow = workflows.succeed(workflow_id, ordinal, node_id, user_id,
                                         run['response']['response'])
            checkpoint('succeeded')
            return self._result(workflow)
        if run is not None and run['state'] in {'unknown', 'dispatching'}:
            workflow = workflows.finish(workflow_id, ordinal, node_id, user_id,
                                        'unknown', run['error'] or 'Backend outcome is unknown')
            raise BackendUnknown('Workflow dispatch outcome is unknown')
        if run is not None and run['state'] == 'failed':
            workflow = workflows.finish(workflow_id, ordinal, node_id, user_id,
                                        'failed', run['error'] or 'Backend dispatch failed')
            raise BackendResponseError('Workflow backend dispatch failed')

        workspace = self.projects.workspace(workflow['project_id'], blocking=False)
        authority = self._authority(workflow_id, step['step_id'], user_id, node_id,
                                    definition['artifact_ids'])
        builder = ContextBuilder(workspace, workflow['project_id'])
        prepared = self._prepared(step)
        handoff = builder.authorize_for_dispatch(prepared, authority=authority,
                                                 target=binding.target())
        exact_request = adapter._request(handoff, binding, role, 'text')[0]
        require(exact_request == step['provider_request'],
                'Backend request changed after workflow approval')
        adapter.prepare(handoff, binding, role, 'text')
        workflows.bind(workflow_id, ordinal, node_id, user_id)
        checkpoint('run-bound')
        try:
            response = adapter.dispatch(handoff, binding, role, 'text')
            checkpoint('response-received')
            workflow = workflows.succeed(workflow_id, ordinal, node_id, user_id,
                                         response['response'])
            checkpoint('succeeded')
            return self._result(workflow)
        except BackendUnknown as exc:
            workflows.finish(workflow_id, ordinal, node_id, user_id,
                             'unknown', str(exc)); raise
        except (BackendResponseError, ValidationError) as exc:
            workflows.finish(workflow_id, ordinal, node_id, user_id,
                             'failed', str(exc)); raise

    def dispatch_creator(self, workflow_id, approval_digest, *, checkpoint=lambda stage: None):
        uuid(workflow_id)
        return self._dispatch(workflow_id, 1, approval_digest, checkpoint)

    def dispatch_opponent(self, workflow_id, approval_digest, *, checkpoint=lambda stage: None):
        uuid(workflow_id)
        return self._dispatch(workflow_id, 2, approval_digest, checkpoint)

    def get(self, workflow_id):
        node_id, user_id = self._identity()
        workflows, _ = self._stores()
        return self._result(workflows.get(workflow_id, node_id, user_id))

    def status(self):
        node_id, user_id = self._identity(); workflows, _ = self._stores()
        return {'workflows': [self._result(value)
                              for value in workflows.list(node_id, user_id)]}
