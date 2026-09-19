# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Desktop chat orchestration through Context Builder and an exact Ollama binding."""
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from uuid import uuid4

from spikes.chat_threads import ChatThreads
from spikes.chat_records import ChatRecords
from spikes.backend_contract import BackendResponseError, BackendUnknown
from spikes.configuration import parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
                                    ConversationSelection, DispatchHandoff,
                                    PreparedContext)
from spikes.external_dispatch import ExternalDispatches
from spikes.metadata import ValidationError, require, timestamp, uuid
from spikes.ollama_backend import (BACKENDS, OllamaAdapter, OllamaBindings,
                                   OllamaRuns)
from spikes.openai_backend import (OpenAIAdapter, OpenAIBinding, OpenAIBindings,
                                   OpenAICredentials, OpenAIModelCatalog,
                                   OpenAIResponseError, OpenAIRuns,
                                   OpenAIUnknownRun)
from spikes.project_creation import ProjectCreation


PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


class ChatService:
    def __init__(self, node_path, projects, *, state_dir=None, adapter_factory=None,
                 external_adapter_factory=None):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.state_dir = (Path(state_dir).absolute() if state_dir else
                          self.node_path.parent / ('.' + self.node_path.name + '.chat'))
        self.session_id = str(uuid4())
        self.adapter_factory = adapter_factory
        self.external_adapter_factory = external_adapter_factory

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
                'Chat state directory requires owned mode 0700 without symlinks')
        return self.state_dir

    def _stores(self):
        root = self._root()
        threads, runs = ChatThreads(root), OllamaRuns(root)
        adapter = self.adapter_factory(runs) if self.adapter_factory else OllamaAdapter(runs)
        return threads, OllamaBindings(root), adapter

    def configure(self, value):
        binding = BACKENDS.parse_binding(value)
        _, bindings, _ = self._stores()
        bindings.save(binding)
        return self.status()

    def status(self):
        node_id, user_id = self._identity()
        threads, bindings, _ = self._stores()
        try:
            binding = bindings.load().serialize()
        except FileNotFoundError:
            binding = None
        rows = threads.list(node_id, user_id)
        return {'binding': binding, 'threads': rows}

    def external_status(self):
        root = self._root()
        try:
            binding = OpenAIBindings(root).load()
        except FileNotFoundError:
            return {'binding': None, 'credential': None, 'model_catalog': None}
        try:
            catalog = OpenAIModelCatalog(root, OpenAICredentials(root)).load(binding)
        except (FileNotFoundError, ValueError):
            catalog = None
        return {'binding': binding.serialize(),
                'credential': OpenAICredentials(root).status(binding.credential_ref),
                'model_catalog': catalog}

    def configure_external(self, value):
        require(isinstance(value, dict), 'External backend request must be an object')
        fields = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                  'endpoint', 'model', 'target_id', 'max_output_tokens',
                  'timeout_seconds', 'secret'}
        require(set(value) == fields, 'Unknown or missing external backend field')
        secret = value['secret']
        root = self._root(); credentials = OpenAICredentials(root)
        reference = 'credential:openai-' + str(uuid4())
        credential = credentials.put(reference, secret)
        candidate = dict(value); candidate.pop('secret')
        candidate.update(credential_ref=reference,
                         credential_revision=credential['revision'])
        try:
            binding = OpenAIBinding.parse(candidate)
            bindings = OpenAIBindings(root)
            try:
                previous = bindings.load()
            except FileNotFoundError:
                previous = None
            bindings.save(binding)
        except Exception:
            credentials.delete(reference)
            raise
        if previous is not None and previous.credential_ref != reference:
            credentials.delete(previous.credential_ref)
        return self.external_status()

    def external_models(self, catalog_factory=OpenAIModelCatalog):
        root = self._root()
        binding = OpenAIBindings(root).load()
        credentials = OpenAICredentials(root)
        return catalog_factory(root, credentials).refresh(binding)

    @staticmethod
    def _external_fields(request):
        required = {'approval_id', 'project_id', 'expected_head', 'thread_id', 'turn_id',
                    'message_id', 'run_id', 'manifest_id', 'assistant_message_id',
                    'selected_message_ids', 'content', 'privacy', 'created_at'}
        require(isinstance(request, dict) and set(request) == required,
                'Unknown or missing external preview field')
        for key in ('approval_id', 'project_id', 'thread_id', 'turn_id', 'message_id',
                    'run_id', 'manifest_id', 'assistant_message_id'):
            uuid(request[key])
        timestamp(request['created_at'])
        require(request['privacy'] in {'public', 'project', 'confidential'},
                'local-only data cannot be sent to an external provider')
        require(isinstance(request['content'], str) and bool(request['content'].strip())
                and len(request['content'].encode()) <= 1024 * 1024,
                'Invalid external chat content')
        selected = request['selected_message_ids']
        require(isinstance(selected, list) and len(selected) == len(set(selected)),
                'Selected message IDs must be a unique list')
        for value in selected:
            uuid(value)
        require(request['message_id'] not in selected,
                'New message cannot already be selected')
        require(isinstance(request['expected_head'], str)
                and len(request['expected_head']) in {40, 64}, 'Invalid expected project commit')
        return request

    def external_preview(self, request):
        request = self._external_fields(request)
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        require(workspace.git.head() == request['expected_head'],
                'Project changed before external preview')
        root = self._root(); node_id, user_id = self._identity()
        threads = ChatThreads(root)
        rows = {row['thread_id']: row for row in threads.list(node_id, user_id)}
        thread = rows.get(request['thread_id'])
        require(thread is not None or not request['selected_message_ids'],
                'Selected chat thread is unavailable')
        messages = {item['message_id']: item for item in (thread or {}).get('messages', [])}
        require(all(value in messages for value in request['selected_message_ids']),
                'Selected chat message is unavailable')
        ordered = [item['message_id'] for item in (thread or {}).get('messages', [])
                   if item['message_id'] in request['selected_message_ids']]
        require(ordered == request['selected_message_ids'],
                'Selected messages must use thread order')
        selected = [messages[value] for value in request['selected_message_ids']] + [
            {'message_id': request['message_id'], 'content': request['content'],
             'privacy': request['privacy'], 'role': 'user'}]
        require(not any(item['privacy'] == 'local-only' for item in selected),
                'local-only data cannot be sent to an external provider')
        binding = OpenAIBindings(root).load()
        authority = Authority('external-approval:' + request['approval_id'], user_id, node_id,
                              'external-chat-v1', frozenset())
        inputs = tuple(AdHocInput(item['message_id'], item['content'].encode(), item['privacy'])
                       for item in selected)
        prepared = ContextBuilder(workspace, request['project_id']).prepare(
            manifest_id=request['manifest_id'], run_id=request['run_id'], authority=authority,
            target=binding.target(), ad_hoc_inputs=inputs,
            conversation=ConversationSelection(request['thread_id'],
                0 if thread is None else thread['revision'],
                tuple(item['message_id'] for item in selected),
                tuple(item['role'] for item in selected)))
        handoff = DispatchHandoff(request['run_id'], request['manifest_id'],
            hashlib.sha256(prepared.manifest_bytes).hexdigest(), binding.target(), prepared.payload)
        provider_request, _, _ = OpenAIAdapter._request(handoff, binding)
        strongest = max((item['privacy'] for item in selected),
                        key=PRIVACY_ORDER.__getitem__)
        binding_bytes = json.dumps(binding.serialize(), sort_keys=True,
                                   separators=(',', ':')).encode()
        binding_sha256 = hashlib.sha256(binding_bytes).hexdigest()
        preview_sha256 = hashlib.sha256(prepared.manifest_bytes + b'\0' + prepared.payload
            + b'\0' + provider_request + b'\0' + binding_bytes).hexdigest()
        ExternalDispatches(root).prepare(approval_id=request['approval_id'], node_id=node_id,
            user_id=user_id, request=request, manifest=prepared.manifest_bytes,
            payload=prepared.payload, provider_request=provider_request,
            preview_sha256=preview_sha256, binding_sha256=binding_sha256,
            privacy=strongest,
            created_at=request['created_at'])
        payload = json.loads(prepared.payload)
        return {'approval_id': request['approval_id'], 'preview_sha256': preview_sha256,
                'project_commit': prepared.manifest['project_commit'],
                'target': {'provider': 'OpenAI', 'endpoint': binding.endpoint,
                           'boundary': binding.boundary, 'model': binding.model},
                'privacy': strongest, 'payload_size': len(prepared.payload),
                'inputs': [{'message_id': part['input_id'],
                            'content': base64.b64decode(part['content_b64']).decode('utf-8'),
                            'privacy': selected[index]['privacy']}
                           for index, part in enumerate(payload['inputs'])],
                'provider_request': json.loads(provider_request)}

    def external_cancel(self, request):
        require(isinstance(request, dict) and set(request) == {'approval_id'},
                'Invalid external cancellation')
        node_id, user_id = self._identity()
        result = ExternalDispatches(self._root()).finish(
            request['approval_id'], node_id, user_id, 'cancelled')
        return {'approval_id': result['approval_id'], 'state': result['state']}

    def external_confirm(self, request):
        required = {'approval_id', 'preview_sha256', 'approved', 'privacy'}
        require(isinstance(request, dict) and set(request) == required
                and request['approved'] is True,
                'Explicit external approval is required')
        node_id, user_id = self._identity(); root = self._root()
        store = ExternalDispatches(root)
        approval = store.get(request['approval_id'], node_id, user_id)
        if approval['state'] == 'succeeded':
            return approval['result']
        if approval['state'] == 'unknown':
            raise OpenAIUnknownRun(approval['error'] or 'External result is unknown')
        if approval['state'] == 'failed':
            raise OpenAIResponseError(approval['error'] or 'External dispatch failed')
        require(approval['state'] == 'prepared', 'External preview is already closed')
        require(request['preview_sha256'] == approval['preview_sha256']
                and request['privacy'] == approval['privacy'],
                'External preview approval does not match')
        original = self._external_fields(approval['request'])
        workspace = self.projects.workspace(original['project_id'], blocking=False)
        binding = OpenAIBindings(root).load()
        current_binding_sha256 = hashlib.sha256(json.dumps(binding.serialize(),
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        require(current_binding_sha256 == approval['binding_sha256'],
                'External binding or credential changed after preview')
        manifest = json.loads(approval['manifest'])
        prepared = PreparedContext(MappingProxyType(manifest), approval['manifest'],
                                   approval['payload'])
        authority = Authority('external-approval:' + original['approval_id'], user_id, node_id,
                              'external-chat-v1', frozenset())
        builder = ContextBuilder(workspace, original['project_id'])
        handoff = builder.authorize_for_dispatch(prepared, authority=authority,
                                                 target=binding.target())
        current_request, _, _ = OpenAIAdapter._request(handoff, binding)
        require(current_request == approval['provider_request'],
                'Provider request changed after preview')
        threads = ChatThreads(root)
        rows = {row['thread_id']: row for row in threads.list(node_id, user_id)}
        thread = rows.get(original['thread_id'])
        expected_revision = manifest['conversation']['thread_revision']
        if thread is not None and thread['revision'] != expected_revision:
            matching_turns = [item for item in thread['turns']
                              if item['turn_id'] == original['turn_id']]
            matching_messages = [item for item in thread['messages']
                                  if item['message_id'] == original['message_id']]
            require(len(matching_turns) == 1 and len(matching_messages) == 1
                    and matching_turns[0]['user_message_id'] == original['message_id']
                    and matching_messages[0]['content'] == original['content']
                    and matching_messages[0]['privacy'] == original['privacy']
                    and matching_messages[0]['created_at'] == original['created_at'],
                    'Chat thread changed after external preview')
            turn = matching_turns[0]
            require(turn['run_id'] in {None, original['run_id']}
                    and turn['manifest_id'] in {None, original['manifest_id']},
                    'External turn differs from approved request')
            if turn['state'] == 'completed':
                response = OpenAIRuns(root).get(original['run_id'])['response']
                require(isinstance(response, dict), 'Completed external response is unavailable')
                result = {'thread': thread, 'turn': threads.get_turn(
                              original['turn_id'], node_id, user_id),
                          'target': binding.serialize(),
                          'provider_response_id': response.get('id'),
                          'usage': response.get('usage')}
                store.finish(original['approval_id'], node_id, user_id,
                             'succeeded', result=result)
                return result
            if turn['state'] in {'unknown', 'failed'}:
                store.finish(original['approval_id'], node_id, user_id,
                             turn['state'], error=turn['error'])
                if turn['state'] == 'unknown':
                    raise OpenAIUnknownRun(turn['error'] or 'External result is unknown')
                raise OpenAIResponseError(turn['error'] or 'External dispatch failed')
            require(thread['revision'] == expected_revision + 1
                    and turn['state'] in {'prepared', 'run-bound'},
                    'Chat thread changed after external preview')
        else:
            require((0 if thread is None else thread['revision']) == expected_revision,
                    'Chat thread changed after external preview')
        if thread is None:
            threads.create(thread_id=original['thread_id'], node_id=node_id, user_id=user_id,
                           created_at=original['created_at'])
        if thread is None or thread['revision'] == expected_revision:
            threads.prepare_turn(thread_id=original['thread_id'], node_id=node_id, user_id=user_id,
                turn_id=original['turn_id'], message_id=original['message_id'],
                content=original['content'], privacy=original['privacy'],
                created_at=original['created_at'])
        threads.bind_run(turn_id=original['turn_id'], node_id=node_id, user_id=user_id,
                         run_id=original['run_id'], manifest_id=original['manifest_id'])
        adapter = (self.external_adapter_factory(OpenAIRuns(root), OpenAICredentials(root))
                   if self.external_adapter_factory else
                   OpenAIAdapter(OpenAIRuns(root), OpenAICredentials(root)))
        try:
            adapter.prepare(handoff, binding)
            response = adapter.dispatch(handoff, binding)
            completed = threads.complete(turn_id=original['turn_id'], node_id=node_id,
                user_id=user_id, run_id=original['run_id'],
                message_id=original['assistant_message_id'], content=response['response'],
                privacy=approval['privacy'], created_at=now())
        except BackendUnknown as exc:
            threads.finish(turn_id=original['turn_id'], node_id=node_id, user_id=user_id,
                           run_id=original['run_id'], state='unknown', error=str(exc))
            store.finish(original['approval_id'], node_id, user_id, 'unknown', error=str(exc))
            raise
        except (BackendResponseError, ValidationError) as exc:
            threads.finish(turn_id=original['turn_id'], node_id=node_id, user_id=user_id,
                           run_id=original['run_id'], state='failed', error=str(exc))
            store.finish(original['approval_id'], node_id, user_id, 'failed', error=str(exc))
            raise
        result = {'thread': threads.get(original['thread_id'], node_id, user_id),
                  'turn': completed, 'target': binding.serialize(),
                  'provider_response_id': response.get('id'), 'usage': response.get('usage')}
        store.finish(original['approval_id'], node_id, user_id, 'succeeded', result=result)
        return result

    def assign(self, **request):
        return ChatRecords(self.node_path, self.projects, state_dir=self._root()).assign(**request)

    def publish_snapshot(self, request, operation_id):
        return ChatRecords(self.node_path, self.projects, state_dir=self._root()).publish(
            request, operation_id)

    def publish_output(self, request, operation_id):
        return ChatRecords(self.node_path, self.projects, state_dir=self._root()).publish_output(
            request, operation_id)

    def send(self, *, project_id, expected_head, thread_id, turn_id, message_id,
             run_id, manifest_id, assistant_message_id, selected_message_ids,
             content, privacy, created_at):
        for value in (project_id, thread_id, turn_id, message_id, run_id,
                      manifest_id, assistant_message_id):
            uuid(value)
        timestamp(created_at)
        require(privacy in PRIVACY_ORDER, 'Unknown chat privacy')
        require(isinstance(selected_message_ids, list)
                and len(selected_message_ids) == len(set(selected_message_ids)),
                'Selected message IDs must be a unique list')
        for value in selected_message_ids:
            uuid(value)
        require(message_id not in selected_message_ids, 'New message cannot already be selected')

        workspace = self.projects.workspace(project_id, blocking=False)
        require(workspace.git.head() == expected_head, 'Project changed before chat dispatch')
        node_id, user_id = self._identity()
        threads, bindings, adapter = self._stores()
        owned = {row['thread_id'] for row in threads.list(node_id, user_id)}
        if thread_id not in owned:
            threads.create(thread_id=thread_id, node_id=node_id, user_id=user_id,
                           created_at=created_at)
        threads.prepare_turn(thread_id=thread_id, node_id=node_id, user_id=user_id,
                             turn_id=turn_id, message_id=message_id, content=content,
                             privacy=privacy, created_at=created_at)
        thread = threads.get(thread_id, node_id, user_id)
        messages = {item['message_id']: item for item in thread['messages']}
        require(all(value in messages for value in selected_message_ids),
                'Selected chat message is unavailable')
        ordered = [item['message_id'] for item in thread['messages']
                   if item['message_id'] in selected_message_ids]
        require(ordered == selected_message_ids, 'Selected messages must use thread order')
        selected = [messages[value] for value in selected_message_ids] + [messages[message_id]]

        binding = bindings.load()
        authority = Authority(self.session_id, user_id, node_id, 'desktop-chat-v1', frozenset())
        inputs = tuple(AdHocInput(item['message_id'], item['content'].encode('utf-8'),
                                  item['privacy']) for item in selected)
        builder = ContextBuilder(workspace, project_id)
        prepared = builder.prepare(manifest_id=manifest_id, run_id=run_id,
                                   authority=authority, target=binding.target(),
                                   ad_hoc_inputs=inputs,
                                   conversation=ConversationSelection(
                                       thread_id, thread['revision'],
                                       tuple(item['message_id'] for item in selected),
                                       tuple(item['role'] for item in selected)))
        current = threads.get(thread_id, node_id, user_id)
        require(current['revision'] == thread['revision']
                and tuple(item['message_id'] for item in current['messages']) ==
                    tuple(item['message_id'] for item in thread['messages']),
                'Chat thread changed during context preparation')
        handoff = builder.authorize_for_dispatch(prepared, authority=authority,
                                                 target=binding.target())
        threads.bind_run(turn_id=turn_id, node_id=node_id, user_id=user_id, run_id=run_id,
                         manifest_id=manifest_id)
        try:
            adapter.prepare(handoff, binding)
            response = adapter.dispatch(handoff, binding)
        except BackendUnknown as exc:
            threads.finish(turn_id=turn_id, node_id=node_id, user_id=user_id,
                           run_id=run_id, state='unknown', error=str(exc))
            raise
        except BackendResponseError as exc:
            threads.finish(turn_id=turn_id, node_id=node_id, user_id=user_id,
                           run_id=run_id, state='failed', error=str(exc))
            raise
        except ValidationError as exc:
            threads.finish(turn_id=turn_id, node_id=node_id, user_id=user_id,
                           run_id=run_id, state='failed', error=str(exc))
            raise
        output_privacy = max((item['privacy'] for item in selected),
                             key=PRIVACY_ORDER.__getitem__)
        completed = threads.complete(turn_id=turn_id, node_id=node_id, user_id=user_id,
                                     run_id=run_id, message_id=assistant_message_id,
                                     content=response['response'], privacy=output_privacy,
                                     created_at=now())
        return {'thread': threads.get(thread_id, node_id, user_id), 'turn': completed,
                'target': binding.serialize()}
