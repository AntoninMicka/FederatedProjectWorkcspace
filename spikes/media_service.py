# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit image approval, durable dispatch, preview and Workspace publication."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from types import MappingProxyType
from uuid import uuid4

from spikes.backend_contract import BackendResponseError, BackendUnknown
from spikes.configuration import committed_project, parse_node, read_config
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder,
                                    PreparedContext, TaskInstruction)
from spikes.media_backend import (ComfyBindings, ComfyImageAdapter,
    ImageGenerationRequest, MEDIA_BACKENDS, MediaRuns, OpenAIImageAdapter,
    OpenAIImageBinding)
from spikes.metadata import (MAX_FILE, MAX_METADATA, require, timestamp, uuid,
                             validate_metadata, validate_snapshot)
from spikes.openai_backend import OpenAIBindings, OpenAICredentials
from spikes.project_creation import ProjectCreation
from spikes.summary_tasks import SummaryTasks


PRIVACY = {'public', 'project', 'confidential', 'local-only'}
PREVIEW_LIMIT = 4 * 1024 * 1024
_SHA256 = re.compile(r'[0-9a-f]{64}')


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


class OpenAIImageBindings:
    """Atomic node-local image binding; the credential remains in its shared store."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        self.path = self.root / 'openai-image-binding.json'

    def save(self, binding):
        require(isinstance(binding, OpenAIImageBinding),
                'Validated OpenAI Images binding is required')
        raw = _canonical(binding.serialize()) + b'\n'
        temporary = self.root / ('.openai-image-binding-' + binding.binding_id + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.close(fd); fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if fd >= 0: os.close(fd)
            if temporary.exists(): temporary.unlink()

    def load(self):
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe OpenAI Images binding file')
            raw = os.read(fd, 64 * 1024 + 1)
        finally: os.close(fd)
        require(len(raw) <= 64 * 1024, 'OpenAI Images binding is too large')
        try: value = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise ValueError('Invalid OpenAI Images binding JSON') from exc
        return OpenAIImageBinding.parse(value)


class MediaService:
    request_schema = 'fpw-image-request-v1'
    policy_revision = 'image-generation-v1'

    def __init__(self, node_path, projects=None, *, state_dir=None,
                 adapter_factories=None):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.state_dir = (Path(state_dir).absolute() if state_dir else
                          self.node_path.parent / ('.' + self.node_path.name + '.chat'))
        self.adapter_factories = adapter_factories or {}

    def _identity(self, owner_id=None):
        node = parse_node(read_config(self.node_path), location=self.node_path)
        user = owner_id or ProjectCreation(self.node_path).author_id()
        uuid(user)
        return node['id'], user

    def _root(self):
        if not os.path.lexists(self.state_dir): self.state_dir.mkdir(mode=0o700)
        info = self.state_dir.lstat()
        require(self.state_dir.absolute() == self.state_dir.resolve()
                and stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Media state directory requires owned mode 0700 without symlinks')
        return self.state_dir

    def _stores(self):
        root = self._root()
        return SummaryTasks(root, 'media-approvals.sqlite'), MediaRuns(root)

    def configure_comfy(self, value):
        binding = MEDIA_BACKENDS.parse_binding(value)
        require(binding.adapter_id == 'comfyui', 'ComfyUI binding is required')
        ComfyBindings(self._root()).save(binding)
        return {'binding': binding.serialize()}

    def configure_openai(self, value):
        require(isinstance(value, dict) and set(value) == {'model', 'timeout_seconds'},
                'Invalid OpenAI Images configuration')
        root = self._root()
        shared = OpenAIBindings(root).load()
        credential = OpenAICredentials(root).status(shared.credential_ref)
        require(credential['available'] and credential['revision'] == shared.credential_revision,
                'Configured OpenAI credential is unavailable')
        binding = OpenAIImageBinding.parse({
            'schema_version': 1, 'binding_id': str(uuid4()),
            'revision': str(uuid4()), 'adapter': 'openai-images',
            'boundary': 'external-provider',
            'endpoint': 'https://api.openai.com/v1/images/generations',
            'model': value['model'], 'target_id': 'api.openai.com',
            'credential_ref': shared.credential_ref,
            'credential_revision': shared.credential_revision,
            'timeout_seconds': value['timeout_seconds']})
        OpenAIImageBindings(root).save(binding)
        return {'binding': self._public_binding(binding)}

    @staticmethod
    def _public_binding(binding):
        value = binding.serialize()
        value.pop('credential_ref', None)
        value.pop('credential_revision', None)
        if binding.adapter_id == 'comfyui':
            value.pop('workflow', None)
            value.pop('parameters', None)
        return value

    def status(self, owner_id=None):
        root = self._root()
        bindings = {}
        for adapter, store in (('openai-images', OpenAIImageBindings(root)),
                               ('comfyui', ComfyBindings(root))):
            try: bindings[adapter] = self._public_binding(store.load())
            except FileNotFoundError: bindings[adapter] = None
        node_id, user_id = self._identity(owner_id)
        tasks, _ = self._stores()
        approvals = []
        for task in tasks.list(node_id, user_id):
            approvals.append({'approval_id': task['task_id'], 'run_id': task['run_id'],
                'project_id': task['manifest']['project_id'],
                'project_commit': task['manifest']['project_commit'],
                'privacy': task['privacy'], 'state': task['state'],
                'result_sha256': task['response_sha256'], 'publish': task['publish'],
                'receipt': task['receipt']})
        return {'bindings': bindings, 'approvals': approvals}

    def _binding(self, adapter_id):
        root = self._root()
        if adapter_id == 'openai-images': return OpenAIImageBindings(root).load()
        if adapter_id == 'comfyui': return ComfyBindings(root).load()
        raise ValueError('Unsupported image adapter')

    def _adapter(self, binding, runs):
        factory = self.adapter_factories.get(binding.adapter_id)
        if factory: return factory(runs)
        if binding.adapter_id == 'openai-images':
            return OpenAIImageAdapter(runs, OpenAICredentials(self._root()))
        return ComfyImageAdapter(runs)

    @classmethod
    def _validate_preview_request(cls, request):
        required = {'schema', 'approval_id', 'run_id', 'manifest_id', 'project_id',
                    'expected_head', 'adapter', 'prompt', 'size', 'quality', 'seed',
                    'privacy'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid image preview request')
        require(request['schema'] == cls.request_schema, 'Unsupported image request')
        for key in ('approval_id', 'run_id', 'manifest_id', 'project_id'):
            uuid(request[key])
        require(isinstance(request['expected_head'], str)
                and bool(re.fullmatch(r'[0-9a-f]{40,64}', request['expected_head'])),
                'Invalid expected project commit')
        require(request['adapter'] in {'openai-images', 'comfyui'},
                'Unsupported image adapter')
        require(request['privacy'] in PRIVACY, 'Invalid image privacy')

    def preview(self, request, *, owner_id=None):
        self._validate_preview_request(request)
        require(self.projects is not None, 'Project registry is unavailable')
        binding = self._binding(request['adapter'])
        node_id, user_id = self._identity(owner_id)
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        require(workspace.git.head() == request['expected_head'],
                'Project changed before image approval preview')
        authority = Authority('image:' + request['approval_id'], user_id, node_id,
                              self.policy_revision, frozenset())
        prompt_input = request['approval_id']
        prepared = ContextBuilder(workspace, request['project_id']).prepare(
            manifest_id=request['manifest_id'], run_id=request['run_id'],
            authority=authority, target=binding.target(),
            ad_hoc_inputs=(AdHocInput(prompt_input, request['prompt'].encode(),
                                      request['privacy']),),
            task=TaskInstruction('creator', 'image-creator-v1',
                'Generate exactly one PNG image from the approved prompt.', prompt_input))
        image_request = ImageGenerationRequest.parse({
            key: request[key] for key in
            ('run_id', 'prompt', 'size', 'quality', 'seed')} |
            {'manifest_sha256': hashlib.sha256(prepared.manifest_bytes).hexdigest()})
        tasks, runs = self._stores()
        row = self._adapter(binding, runs).prepare(image_request, binding)
        approval = {'approval_id': request['approval_id'], 'run_id': request['run_id'],
            'manifest_id': request['manifest_id'], 'project_id': request['project_id'],
            'project_commit': request['expected_head'], 'privacy': request['privacy'],
            'prompt': request['prompt'], 'size': request['size'],
            'quality': request['quality'], 'seed': request['seed'],
            'target': self._public_binding(binding), 'provider_request': row['request']}
        preview_sha256 = hashlib.sha256(_canonical(approval)).hexdigest()
        approval['preview_sha256'] = preview_sha256
        stored = dict(request, approval_preview_sha256=preview_sha256)
        tasks.prepare(task_id=request['approval_id'], node_id=node_id, user_id=user_id,
            request=stored, manifest=dict(prepared.manifest), payload=prepared.payload,
            privacy=request['privacy'])
        tasks.bind(request['approval_id'], node_id, user_id)
        return approval

    def confirm(self, request, *, owner_id=None):
        required = {'approval_id', 'project_id', 'preview_sha256', 'approved', 'privacy'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid image approval confirmation')
        uuid(request['approval_id']); uuid(request['project_id'])
        require(request['approved'] is True and request['privacy'] in PRIVACY
                and isinstance(request['preview_sha256'], str)
                and bool(_SHA256.fullmatch(request['preview_sha256'])),
                'Image dispatch requires an exact positive confirmation')
        node_id, user_id = self._identity(owner_id)
        tasks, runs = self._stores()
        task = tasks.get(request['approval_id'], node_id, user_id)
        original = task['request']
        require(original['project_id'] == request['project_id']
                and original['privacy'] == request['privacy']
                and original['approval_preview_sha256'] == request['preview_sha256'],
                'Image confirmation differs from approval preview')
        if task['state'] == 'succeeded':
            return self._result(request['approval_id'], task, runs)
        require(task['state'] == 'run-bound', 'Image approval cannot be dispatched again')
        binding = self._binding(original['adapter'])
        require(task['manifest']['target'] == {
            'binding_id': binding.binding_id, 'binding_revision': binding.revision,
            'boundary': binding.boundary, 'target_id': binding.target_id,
            'model': binding.target().model}, 'Image binding changed after preview')
        prepared = PreparedContext(MappingProxyType(task['manifest']),
                                   _canonical(task['manifest']), task['payload'])
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        authority = Authority('image:' + request['approval_id'], user_id, node_id,
                              self.policy_revision, frozenset())
        handoff = ContextBuilder(workspace, request['project_id']).authorize_for_dispatch(
            prepared, authority=authority, target=binding.target())
        image_request = ImageGenerationRequest.parse({
            'run_id': original['run_id'], 'manifest_sha256': handoff.manifest_sha256,
            'prompt': original['prompt'], 'size': original['size'],
            'quality': original['quality'], 'seed': original['seed']})
        try:
            row = self._adapter(binding, runs).dispatch(image_request, binding)
            result = {'schema': 'fpw-image-result-v1', 'run_id': original['run_id'],
                'image_sha256': row['image_sha256'], 'metadata': row['metadata'],
                'preview_available': len(row['image']) <= PREVIEW_LIMIT}
            task = tasks.succeed(request['approval_id'], node_id, user_id,
                                 _canonical(result).decode())
            return self._result(request['approval_id'], task, runs)
        except BackendUnknown as exc:
            tasks.finish(request['approval_id'], node_id, user_id, 'unknown', str(exc)); raise
        except (BackendResponseError, ValueError) as exc:
            tasks.finish(request['approval_id'], node_id, user_id, 'failed', str(exc)); raise

    @staticmethod
    def _result(approval_id, task, runs):
        result = json.loads(task['response'])
        row = runs.get(task['run_id'], include_image=True)
        require(row is not None and row['state'] == 'succeeded'
                and row['image_sha256'] == result['image_sha256'],
                'Durable image result differs from approval')
        value = dict(result, approval_id=approval_id,
                     result_sha256=task['response_sha256'], privacy=task['privacy'],
                     project_id=task['manifest']['project_id'],
                     project_commit=task['manifest']['project_commit'])
        if result['preview_available']:
            value['image_base64'] = base64.b64encode(row['image']).decode()
        return value

    def publish(self, request, *, owner_id=None, checkpoint=lambda stage: None):
        required = {'approval_id', 'result_sha256', 'project_id', 'expected_head',
                    'artifact_id', 'title', 'created_at', 'operation_id', 'privacy'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid image publication request')
        for key in ('approval_id', 'project_id', 'artifact_id', 'operation_id'):
            uuid(request[key])
        require(isinstance(request['result_sha256'], str)
                and bool(_SHA256.fullmatch(request['result_sha256'])),
                'Invalid image result digest')
        require(isinstance(request['expected_head'], str)
                and bool(re.fullmatch(r'[0-9a-f]{40,64}', request['expected_head'])),
                'Invalid expected project commit')
        require(isinstance(request['title'], str)
                and request['title'].strip() == request['title']
                and 0 < len(request['title']) <= 200
                and not any(char in request['title'] for char in '\0\r\n'),
                'Invalid image title')
        timestamp(request['created_at'])
        require(request['privacy'] in PRIVACY, 'Invalid image privacy')
        node_id, user_id = self._identity(owner_id)
        tasks, runs = self._stores()
        task = tasks.get(request['approval_id'], node_id, user_id)
        require(task['state'] in {'succeeded', 'publishing', 'published'},
                'Image result is not publishable')
        require(task['response_sha256'] == request['result_sha256']
                and task['privacy'] == request['privacy']
                and task['manifest']['project_id'] == request['project_id']
                and task['manifest']['project_commit'] == request['expected_head'],
                'Image publication differs from confirmed result')
        task = tasks.begin_publish(request['approval_id'], node_id, user_id, request)
        checkpoint('publishing')
        if task['state'] == 'published':
            return {'state': 'published', 'artifact_id': request['artifact_id'],
                    'result_sha256': task['response_sha256'], 'receipt': task['receipt']}
        row = runs.get(task['run_id'], include_image=True)
        require(row is not None and row['state'] == 'succeeded'
                and isinstance(row['image'], bytes)
                and len(row['image']) <= MAX_FILE
                and hashlib.sha256(row['image']).hexdigest() == row['image_sha256'],
                'Durable image bytes are unavailable or changed')
        original = task['request']; manifest = task['manifest']
        execution = row['execution']
        workspace = self.projects.workspace(request['project_id'], blocking=False)
        intent = dict(request, action='publish-generated-image', author_id=user_id,
                      run_id=task['run_id'], image_sha256=row['image_sha256'])

        def prepare(ws):
            head = ws.git.head()
            require(head == request['expected_head'],
                    'Project changed before image publication')
            committed_project(ws.git, head, request['project_id'])
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            require(request['artifact_id'] not in entities, 'Artifact ID already exists')
            provider = row['metadata'].get('provider', {})
            generation = {'schema': 'fpw-image-generation-v1',
                'adapter': execution['adapter_id'],
                'binding_id': execution['binding_id'],
                'binding_revision': execution['binding_revision'],
                'capability_revision': execution['capability_revision'],
                'run_id': task['run_id'], 'request_sha256': task['request_digest'],
                'manifest_sha256': hashlib.sha256(_canonical(manifest)).hexdigest(),
                'size': original['size'], 'quality': original['quality'],
                'seed': original['seed'], 'result_sha256': row['image_sha256'],
                'target': manifest['target']}
            if execution['adapter_id'] == 'comfyui':
                generation['workflow'] = {
                    'revision': provider.get('workflow_revision'),
                    'sha256': provider.get('workflow_sha256'),
                    'prompt_id': provider.get('prompt_id'),
                    'output': provider.get('image')}
            metadata = {'schema_version': 3, 'id': request['artifact_id'],
                'title': request['title'], 'kind': 'source',
                'created_at': request['created_at'], 'author_id': user_id,
                'privacy': request['privacy'], 'provenance': 'llm-generated',
                'file': 'image.png', 'generation': generation}
            validate_metadata(metadata, sidecar=True)
            encoded = (json.dumps(metadata, ensure_ascii=False,
                sort_keys=True, indent=2) + '\n').encode()
            require(len(encoded) <= MAX_METADATA, 'Image metadata exceeds 64 KiB')
            prefix = f'artifacts/{request["artifact_id"]}/'
            changes = {prefix + 'image.png': row['image'],
                       prefix + 'metadata.json': encoded}
            candidate = dict(files); candidate.update(changes); validate_snapshot(candidate)
            return changes, 'Local workspace author', user_id + '@local.invalid', \
                'Publish generated image'

        receipt = workspace.transact(request['operation_id'], intent, prepare,
            expected_head=request['expected_head'], checkpoint=checkpoint)
        checkpoint('workspace-complete')
        task = tasks.complete_publish(request['approval_id'], node_id, user_id, receipt)
        checkpoint('published')
        return {'state': 'published', 'artifact_id': request['artifact_id'],
                'result_sha256': task['response_sha256'], 'receipt': receipt}
