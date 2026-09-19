# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Desktop chat orchestration through Context Builder and an exact Ollama binding."""
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from uuid import uuid4

from spikes.chat_threads import ChatThreads
from spikes.chat_records import ChatRecords
from spikes.backend_contract import BackendResponseError, BackendUnknown
from spikes.configuration import parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
                                    ConversationSelection)
from spikes.metadata import ValidationError, require, timestamp, uuid
from spikes.ollama_backend import (BACKENDS, OllamaAdapter, OllamaBindings,
                                   OllamaRuns)
from spikes.openai_backend import (OpenAIBinding, OpenAIBindings, OpenAICredentials,
                                   OpenAIModelCatalog)
from spikes.project_creation import ProjectCreation


PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


class ChatService:
    def __init__(self, node_path, projects, *, state_dir=None, adapter_factory=None):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.state_dir = (Path(state_dir).absolute() if state_dir else
                          self.node_path.parent / ('.' + self.node_path.name + '.chat'))
        self.session_id = str(uuid4())
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
