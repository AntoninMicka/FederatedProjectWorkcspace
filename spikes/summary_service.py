# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit local summary preview orchestration; project publication is separate."""
import hashlib
import json
import os
from pathlib import Path
import stat

from spikes.chat_threads import ChatThreads
from spikes.configuration import parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
    ConversationSelection, DispatchHandoff, ProjectInput, TaskInstruction)
from spikes.metadata import ValidationError, require, uuid, validate_snapshot
from spikes.ollama_backend import (OllamaAdapter, OllamaBinding, OllamaBindings,
                                   OllamaResponseError, OllamaRuns, UnknownRun)
from spikes.project_creation import ProjectCreation
from spikes.summary_tasks import SummaryTasks


PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
SUMMARY_INSTRUCTION = ('Create a faithful Markdown summary using only the supplied sources. '
                       'Separate established facts from uncertainty and do not invent missing context.')


class SummaryService:
    def __init__(self, node_path, projects, *, state_dir=None, chat_state_dir=None,
                 adapter_factory=None):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.state_dir = (Path(state_dir).absolute() if state_dir else
                          self.node_path.parent / ('.' + self.node_path.name + '.summary'))
        self.chat_state_dir = (Path(chat_state_dir).absolute() if chat_state_dir else
                               self.node_path.parent / ('.' + self.node_path.name + '.chat'))
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
                'Summary state directory requires owned mode 0700 without symlinks')
        return self.state_dir

    def _stores(self):
        root = self._root()
        runs = OllamaRuns(root)
        adapter = self.adapter_factory(runs) if self.adapter_factory else OllamaAdapter(runs)
        return SummaryTasks(root), OllamaBindings(root), adapter

    def configure(self, value):
        binding = OllamaBinding.parse(value)
        require(binding.boundary == 'same-node', 'Summary preview requires same-node Ollama')
        _, bindings, _ = self._stores()
        bindings.save(binding)
        return binding.serialize()

    def status(self):
        node_id, user_id = self._identity()
        tasks, bindings, _ = self._stores()
        try:
            binding = bindings.load().serialize()
        except FileNotFoundError:
            binding = None
        return {'binding': binding, 'tasks': tasks.list(node_id, user_id)}

    @staticmethod
    def _request(request):
        require(isinstance(request, dict) and set(request) == {
            'schema', 'task_id', 'run_id', 'manifest_id', 'project_id',
            'expected_head', 'role_id', 'role_revision', 'target', 'selection', 'focus'},
            'Invalid summary request')
        require(request['schema'] == 'fpw-summary-request-v1', 'Unsupported summary request')
        require(request['role_id'] == 'summarizer'
                and request['role_revision'] == 'summarizer-v1',
                'Unsupported summary role')
        for key in ('task_id', 'run_id', 'manifest_id', 'project_id'):
            uuid(request[key])
        require(isinstance(request['expected_head'], str)
                and len(request['expected_head']) in {40, 64}
                and all(c in '0123456789abcdef' for c in request['expected_head']),
                'Invalid expected project commit')
        selection = request['selection']
        require(isinstance(selection, dict) and selection.get('kind') in {'artifacts', 'messages'},
                'Invalid summary selection')
        if selection['kind'] == 'artifacts':
            require(set(selection) == {'kind', 'artifact_ids'}, 'Invalid artifact selection')
            ids = selection['artifact_ids']
        else:
            require(set(selection) == {'kind', 'thread_id', 'thread_revision', 'message_ids'},
                    'Invalid message selection')
            uuid(selection['thread_id'])
            require(type(selection['thread_revision']) is int and selection['thread_revision'] >= 0,
                    'Invalid thread revision')
            ids = selection['message_ids']
        require(isinstance(ids, list) and 1 <= len(ids) <= 64
                and len(ids) == len(set(ids)), 'Selection requires 1 to 64 unique IDs')
        for value in ids:
            uuid(value)
        focus = request['focus']
        if focus is not None:
            require(isinstance(focus, dict) and set(focus) == {'input_id', 'content', 'privacy'},
                    'Invalid summary focus')
            uuid(focus['input_id'])
            require(focus['input_id'] not in ids and focus['privacy'] in PRIVACY_ORDER
                    and isinstance(focus['content'], str) and bool(focus['content'].strip())
                    and '\0' not in focus['content']
                    and len(focus['content'].encode()) <= 16 * 1024,
                    'Invalid or oversized summary focus')
        return selection, ids, focus

    @staticmethod
    def _handoff(task, binding):
        manifest = task['manifest']
        require(manifest['target'] == dict(binding_id=binding.binding_id,
            binding_revision=binding.revision, boundary=binding.boundary,
            target_id=binding.target_id, model=binding.model),
            'Configured Ollama binding differs from durable summary target')
        raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':')).encode()
        return DispatchHandoff(task['run_id'], task['manifest_id'],
                               hashlib.sha256(raw).hexdigest(), binding.target(), task['payload'])

    def preview(self, request, *, checkpoint=lambda stage: None):
        selection, ids, focus = self._request(request)
        node_id, user_id = self._identity()
        tasks, bindings, adapter = self._stores()
        binding = bindings.load()
        require(binding.boundary == 'same-node', 'Summary preview requires same-node Ollama')
        require(request['target'] == binding.serialize(),
                'Summary request target differs from configured Ollama binding')

        try:
            existing = tasks.get(request['task_id'], node_id, user_id)
        except ValidationError as exc:
            if 'unavailable to this owner' not in str(exc):
                raise
            existing = None
        if existing is not None:
            canonical = json.dumps(request, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':')).encode()
            require(hashlib.sha256(canonical).hexdigest() == existing['request_digest'],
                    'Task ID belongs to a different summary request')
            if existing['state'] == 'succeeded':
                return self._result(request['task_id'], existing)
            require(existing['state'] == 'run-bound',
                    'Summary task cannot be retried automatically')
            handoff = self._handoff(existing, binding)
        else:
            workspace = self.projects.workspace(request['project_id'], blocking=False)
            require(workspace.git.head() == request['expected_head'],
                    'Project changed before summary dispatch')
            files = workspace.git.snapshot(request['expected_head'])
            entities = validate_snapshot(files)
            project_inputs, ad_hoc_inputs, conversation = (), (), None
            privacy = []
            if selection['kind'] == 'artifacts':
                require(all(value in entities for value in ids),
                        'Selected project artifact is unavailable')
                project_inputs = tuple(ProjectInput(value) for value in ids)
                privacy.extend(entities[value]['privacy'] for value in ids)
                readable = frozenset(ids)
            else:
                thread = ChatThreads(self.chat_state_dir).get(selection['thread_id'], node_id, user_id)
                require(thread['project_id'] == request['project_id'],
                        'Chat thread is not assigned to this project')
                require(thread['revision'] == selection['thread_revision'],
                        'Chat thread changed before summary dispatch')
                messages = {item['message_id']: item for item in thread['messages']}
                require(all(value in messages for value in ids),
                        'Selected chat message is unavailable')
                require([item['message_id'] for item in thread['messages']
                         if item['message_id'] in ids] == ids,
                        'Selected messages must use thread order')
                selected = [messages[value] for value in ids]
                ad_hoc_inputs = tuple(AdHocInput(item['message_id'],
                    item['content'].encode(), item['privacy']) for item in selected)
                privacy.extend(item['privacy'] for item in selected)
                conversation = ConversationSelection(thread['thread_id'], thread['revision'],
                    tuple(ids), tuple(item['role'] for item in selected))
                readable = frozenset()
            focus_id = None
            if focus is not None:
                focus_id = focus['input_id']
                ad_hoc_inputs += (AdHocInput(focus_id, focus['content'].encode(), focus['privacy']),)
                privacy.append(focus['privacy'])
            authority = Authority('summary:' + request['task_id'], user_id, node_id,
                                  'desktop-summary-v1', readable)
            builder = ContextBuilder(workspace, request['project_id'])
            prepared = builder.prepare(manifest_id=request['manifest_id'], run_id=request['run_id'],
                authority=authority, target=binding.target(), project_inputs=project_inputs,
                ad_hoc_inputs=ad_hoc_inputs, conversation=conversation,
                task=TaskInstruction(request['role_id'], request['role_revision'],
                                     SUMMARY_INSTRUCTION, focus_id))
            if conversation is not None:
                current = ChatThreads(self.chat_state_dir).get(selection['thread_id'], node_id, user_id)
                require(current['revision'] == selection['thread_revision'],
                        'Chat thread changed during context preparation')
            handoff = builder.authorize_for_dispatch(prepared, authority=authority,
                                                     target=binding.target())
            strongest = max(privacy, key=PRIVACY_ORDER.__getitem__)
            tasks.prepare(task_id=request['task_id'], node_id=node_id, user_id=user_id,
                request=request, manifest=dict(prepared.manifest), payload=prepared.payload,
                privacy=strongest)
            checkpoint('prepared')
            tasks.bind(request['task_id'], node_id, user_id)
            checkpoint('run-bound')
        try:
            adapter.prepare(handoff, binding)
            response = adapter.dispatch(handoff, binding)
            checkpoint('response-received')
            task = tasks.succeed(request['task_id'], node_id, user_id, response['response'])
            checkpoint('succeeded')
            return self._result(request['task_id'], task)
        except UnknownRun as exc:
            tasks.finish(request['task_id'], node_id, user_id, 'unknown', str(exc)); raise
        except (OllamaResponseError, ValidationError) as exc:
            tasks.finish(request['task_id'], node_id, user_id, 'failed', str(exc)); raise

    @staticmethod
    def _result(task_id, task):
        return dict(task_id=task_id, state=task['state'], run_id=task['run_id'],
                    manifest_id=task['manifest_id'], privacy=task['privacy'],
                    project_id=task['manifest']['project_id'],
                    project_commit=task['manifest']['project_commit'],
                    response=task['response'], response_sha256=task['response_sha256'])
