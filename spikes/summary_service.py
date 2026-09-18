# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit local summary preview orchestration; project publication is separate."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from spikes.chat_threads import ChatThreads
from spikes.configuration import committed_project, parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
    ConversationSelection, DispatchHandoff, ProjectInput, TaskInstruction)
from spikes.metadata import MAX_FILE, ValidationError, require, timestamp, uuid, validate_snapshot
from spikes.ollama_backend import (OllamaAdapter, OllamaBinding, OllamaBindings,
                                   OllamaResponseError, OllamaRuns, UnknownRun)
from spikes.project_creation import ProjectCreation
from spikes.summary_tasks import SummaryTasks


PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
SUMMARY_INSTRUCTION = ('Create a faithful Markdown summary using only the supplied sources. '
                       'Separate established facts from uncertainty and do not invent missing context.')
SUMMARY_MARKER = '<!-- fpw-summary-v1\n'
SUMMARY_END = '\n-->\n'


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


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
        rows = []
        for task in tasks.list(node_id, user_id):
            rows.append(dict(task_id=task['task_id'], state=task['state'],
                run_id=task['run_id'], manifest_id=task['manifest_id'],
                project_id=task['manifest']['project_id'],
                project_commit=task['manifest']['project_commit'], privacy=task['privacy'],
                response=task['response'], response_sha256=task['response_sha256'],
                publish=task['publish'], receipt=task['receipt']))
        return {'binding': binding, 'tasks': rows}

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

    def publish(self, request, *, checkpoint=lambda stage: None):
        required = {'task_id', 'preview_sha256', 'project_id', 'expected_head',
                    'artifact_id', 'title', 'created_at', 'operation_id'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid summary publication request')
        for key in ('task_id', 'project_id', 'artifact_id', 'operation_id'):
            uuid(request[key])
        require(isinstance(request['preview_sha256'], str)
                and re.fullmatch(r'[0-9a-f]{64}', request['preview_sha256']),
                'Invalid preview digest')
        require(isinstance(request['expected_head'], str)
                and re.fullmatch(r'[0-9a-f]{40,64}', request['expected_head']),
                'Invalid expected project commit')
        require(isinstance(request['title'], str)
                and request['title'].strip() == request['title']
                and 0 < len(request['title']) <= 200
                and not any(char in request['title'] for char in '\0\r\n'),
                'Invalid summary title')
        timestamp(request['created_at'])
        node_id, user_id = self._identity()
        tasks, _, _ = self._stores()
        task = tasks.get(request['task_id'], node_id, user_id)
        require(task['state'] in {'succeeded', 'publishing', 'published'},
                'Summary preview is not publishable')
        require(task['response_sha256'] == request['preview_sha256'],
                'Summary preview changed before publication')
        require(task['manifest']['project_id'] == request['project_id']
                and task['manifest']['project_commit'] == request['expected_head'],
                'Summary publication project or HEAD differs from preview')
        task = tasks.begin_publish(request['task_id'], node_id, user_id, request)
        checkpoint('publishing')
        if task['state'] == 'published':
            return self._published_result(request['task_id'], task)

        workspace = self.projects.workspace(request['project_id'], blocking=False)
        intent = dict(request, action='publish-summary', author_id=user_id,
                      task_request_digest=task['request_digest'])

        def prepare(ws):
            head = ws.git.head()
            require(head == request['expected_head'],
                    'Project changed before summary publication')
            committed_project(ws.git, head, request['project_id'])
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            require(request['artifact_id'] not in entities, 'Artifact ID already exists')
            original = task['request']; selection = original['selection']
            manifest = task['manifest']
            if selection['kind'] == 'artifacts':
                selected_ids = selection['artifact_ids']
                require(all(value in entities for value in selected_ids),
                        'Summary source artifact is unavailable')
                by_id = {item['input_id']: item for item in manifest['inputs']
                         if item['source'] == 'project'}
                require(set(by_id) == set(selected_ids),
                        'Summary manifest source selection changed')
                for value in selected_ids:
                    item = by_id[value]
                    raw = files.get(item['path'])
                    require(raw is not None and len(raw) == item['size']
                            and hashlib.sha256(raw).hexdigest() == item['sha256']
                            and entities[value]['privacy'] == item['privacy'],
                            'Summary source artifact changed')
            else:
                thread = ChatThreads(self.chat_state_dir).get(
                    selection['thread_id'], node_id, user_id)
                require(thread['project_id'] == request['project_id']
                        and thread['revision'] == selection['thread_revision'],
                        'Summary chat selection changed')
                by_id = {item['message_id']: item for item in thread['messages']}
                ids = selection['message_ids']
                require(all(value in by_id for value in ids)
                        and [item['message_id'] for item in thread['messages']
                             if item['message_id'] in ids] == ids,
                        'Summary chat messages changed')
                manifest_messages = manifest['conversation']['messages']
                require([item['message_id'] for item in manifest_messages] == ids,
                        'Summary manifest messages changed')
                manifest_inputs = {item['input_id']: item for item in manifest['inputs']}
                for value in ids:
                    message = by_id[value]; item = manifest_inputs[value]
                    raw = message['content'].encode()
                    require(hashlib.sha256(raw).hexdigest() == item['sha256']
                            and message['privacy'] == item['privacy'],
                            'Summary chat message changed')
            manifest_sha256 = hashlib.sha256(_canonical(manifest)).hexdigest()
            sources = [dict(input_id=item['input_id'], source=item['source'],
                            sha256=item['sha256'], privacy=item['privacy'])
                       for item in manifest['inputs']]
            record = {'schema': 'fpw-summary-v1', 'task_id': request['task_id'],
                'run_id': task['run_id'], 'manifest_id': task['manifest_id'],
                'manifest_sha256': manifest_sha256,
                'role_id': original['role_id'], 'role_revision': original['role_revision'],
                'project_id': request['project_id'], 'project_commit': head,
                'sources': sources, 'target': manifest['target'],
                'preview_sha256': task['response_sha256'], 'privacy': task['privacy']}
            envelope = _canonical(record).decode()
            content = (SUMMARY_MARKER + envelope + SUMMARY_END + '\n'
                       + task['response'].rstrip() + '\n').encode()
            require(len(content) <= MAX_FILE, 'Published summary exceeds artifact limit')
            relations = ([{'type': 'summarizes', 'target_id': value}
                          for value in selection['artifact_ids']]
                         if selection['kind'] == 'artifacts' else [])
            metadata = {'schema_version': 1, 'id': request['artifact_id'],
                'title': request['title'], 'kind': 'document',
                'created_at': request['created_at'], 'author_id': user_id,
                'privacy': task['privacy'], 'provenance': 'llm-generated',
                'file': 'content.md', 'relations': relations}
            prefix = f'artifacts/{request["artifact_id"]}/'
            changes = {prefix + 'content.md': content,
                prefix + 'metadata.json': (json.dumps(metadata, ensure_ascii=False,
                    sort_keys=True, indent=2) + '\n').encode()}
            return changes, 'Local workspace author', user_id + '@local.invalid', \
                'Publish local summary'

        receipt = workspace.transact(request['operation_id'], intent, prepare,
            expected_head=request['expected_head'], checkpoint=checkpoint)
        checkpoint('workspace-complete')
        task = tasks.complete_publish(request['task_id'], node_id, user_id, receipt)
        checkpoint('published')
        return self._published_result(request['task_id'], task)

    @staticmethod
    def _result(task_id, task):
        return dict(task_id=task_id, state=task['state'], run_id=task['run_id'],
                    manifest_id=task['manifest_id'], privacy=task['privacy'],
                    project_id=task['manifest']['project_id'],
                    project_commit=task['manifest']['project_commit'],
                    response=task['response'], response_sha256=task['response_sha256'])

    @staticmethod
    def _published_result(task_id, task):
        return dict(task_id=task_id, state=task['state'], receipt=task['receipt'],
                    artifact_id=task['publish']['artifact_id'],
                    preview_sha256=task['response_sha256'])
