# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared Workspace projection and explicit control for the existing Julia runner."""
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import threading
import tomllib
from uuid import uuid4

from spikes.configuration import parse_node, read_config
from spikes.julia_computation import JuliaExecutor, validate_computation
from spikes.metadata import (MAX_FILE, MAX_METADATA, parse_json, require, safe_path, uuid,
                             validate_snapshot)
from spikes.output_execution import canonical, digest
from spikes.project_creation import ProjectCreation


PREVIEW_BYTES = 512 * 1024
EDITOR_BYTES = 1024 * 1024
JULIA_TEMPLATE = '''using SHA

function argument(name)
    index = findfirst(==(name), ARGS)
    index === nothing && error("Chybi argument " * name)
    return ARGS[index + 1]
end

output = argument("--fpw-output")
raw = "Vypocet Julia probehl.\\n"
write(joinpath(output, "result.txt"), raw)
sha = bytes2hex(SHA.sha256(raw))
manifest = "{\\\"outputs\\\":[{\\\"kind\\\":\\\"report\\\",\\\"media_type\\\":\\\"text/plain\\\",\\\"name\\\":\\\"result\\\",\\\"path\\\":\\\"result.txt\\\",\\\"sha256\\\":\\\"$(sha)\\\",\\\"size\\\":$(ncodeunits(raw))}],\\\"schema\\\":\\\"fpw-julia-result-v1\\\"}"
write(joinpath(output, "fpw-julia-result-v1.json"), manifest)
'''
PROJECT_TEMPLATE = '[deps]\n'
MANIFEST_TEMPLATE = '''# This file is machine-generated - editing it directly is not advised

julia_version = "1.10.12"
manifest_format = "2.0"
project_hash = "da39a3ee5e6b4b0d3255bfef95601890afd80709"

[deps]
'''
POLICY_TEMPLATE = {'network': 'deny', 'timeout_ms': 30_000, 'cpu_threads': 1,
                   'max_processes': 16, 'memory_bytes': 2 * 1024 * 1024 * 1024,
                   'output_bytes': 1024 * 1024, 'output_files': 8,
                   'stdout_bytes': 64 * 1024, 'stderr_bytes': 64 * 1024}


def default_runtime_root():
    configured = os.environ.get('XDG_STATE_HOME')
    state_home = (Path(configured) if configured and Path(configured).is_absolute()
                  else Path.home() / '.local/state')
    return state_home / 'federated-workspace/julia/1.10.12-linux-aarch64'


def _private_json(path):
    path = Path(path).absolute()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe Julia runtime binding')
        raw = handle.read(MAX_METADATA + 1)
    require(len(raw) <= MAX_METADATA, 'Julia runtime binding exceeds limit')
    return parse_json(raw, MAX_METADATA)


class JuliaWorkspaceService:
    """No new persistence: project Git + Julia journal + Workspace remain authorities."""

    def __init__(self, node_path, projects, *, runtime_root=None, executor_factory=None):
        self.node_path = Path(node_path).absolute()
        self.projects = projects
        self.runtime_root = Path(runtime_root or default_runtime_root()).absolute()
        self.executor_factory = executor_factory
        self._workers = {}
        self._errors = {}
        self._lock = threading.Lock()

    def identity(self, user_id=None):
        node = parse_node(read_config(self.node_path), location=self.node_path)
        actor = user_id or ProjectCreation(self.node_path).author_id()
        uuid(actor)
        return node['id'], actor

    def _executor(self, project_id):
        git = self.projects.repository(project_id)
        if self.executor_factory is not None:
            return self.executor_factory(git)
        return JuliaExecutor(git=git,
            state_dir=(self.runtime_root / 'state').resolve(strict=True),
            runtime_binding=_private_json(self.runtime_root / 'binding.json'))

    @staticmethod
    def _definition(git, commit, path):
        parts = safe_path(path)
        require(len(parts) >= 3 and parts[0] == 'artifacts' and path.endswith('.json'),
                'Julia definition must be artifact JSON')
        uuid(parts[1])
        entities = validate_snapshot(git.snapshot(commit))
        require(parts[1] in entities, 'Julia definition artifact is missing')
        rows = [row for row in git.run('ls-tree', commit, '--', path).stdout.splitlines()
                if row]
        require(len(rows) == 1, 'Julia definition is missing')
        info, actual = rows[0].split('\t', 1); mode, kind, oid = info.split()
        require(actual == path and mode == '100644' and kind == 'blob',
                'Julia definition must be a regular Git blob')
        require(int(git.run('cat-file', '-s', oid).stdout) <= MAX_METADATA,
                'Julia definition exceeds limit')
        raw = git.run('cat-file', 'blob', oid, binary=True).stdout
        value = validate_computation(parse_json(raw, MAX_METADATA))
        return value, {'artifact_id': parts[1], 'path': path,
                       'git_blob': oid, 'sha256': digest(raw)}, entities

    @staticmethod
    def _network_safe(computation, reference, entities):
        artifact_ids = {reference['artifact_id'], computation['entrypoint']['artifact_id'],
                        *(item['artifact_id'] for item in computation['inputs'])}
        for field in ('project_path', 'manifest_path'):
            parts = safe_path(computation['environment'][field])
            require(len(parts) >= 3 and parts[0] == 'artifacts',
                    'Julia environment is not an artifact')
            artifact_ids.add(parts[1])
        return all(identifier in entities
                   and entities[identifier]['privacy'] != 'local-only'
                   for identifier in artifact_ids)

    def definitions(self, project_id, expected_head):
        uuid(project_id)
        git = self.projects.repository(project_id)
        require(git.head() == expected_head, 'Project changed before Julia projection')
        paths = git.run('ls-tree', '-r', '--name-only', expected_head).stdout.splitlines()
        result = []
        for path in paths:
            if not path.startswith('artifacts/') or not path.endswith('.json'):
                continue
            try:
                computation, reference, entities = self._definition(git, expected_head, path)
            except (ValueError, OSError, json.JSONDecodeError, UnicodeDecodeError,
                    subprocess.SubprocessError):
                continue
            if not self.projects.network or self._network_safe(
                    computation, reference, entities):
                ids = {reference['artifact_id'], computation['entrypoint']['artifact_id'],
                       safe_path(computation['environment']['project_path'])[1],
                       safe_path(computation['environment']['manifest_path'])[1]}
                editable = all(entities.get(value, {}).get('kind') == 'document'
                               and entities[value].get('provenance') == 'user'
                               for value in ids)
                result.append({'definition': reference, 'computation': computation,
                               'editable': editable})
        require(git.head() == expected_head,
                'Project changed during Julia projection')
        return {'schema': 'fpw-julia-workspace-v1', 'project_id': project_id,
                'project_commit': expected_head, 'definitions': result}

    @staticmethod
    def _editor_text(value, label, maximum=EDITOR_BYTES):
        require(isinstance(value, str) and '\0' not in value
                and len(value.encode()) <= maximum, f'Invalid {label}')
        return value

    @staticmethod
    def _artifact(files, entities, artifact_id, filename=None):
        uuid(artifact_id); item = entities.get(artifact_id)
        require(item is not None and item['kind'] == 'document'
                and item['provenance'] == 'user', 'Julia editor artifact is not editable')
        name = filename or item.get('file')
        path = f'artifacts/{artifact_id}/{name}'
        require(item.get('file') == name and path in files,
                'Julia editor artifact content is missing')
        return item, path, files[path]

    def editor_open(self, project_id, expected_head, definition_path=None):
        uuid(project_id); git = self.projects.repository(project_id)
        require(git.head() == expected_head, 'Project changed before Julia editor open')
        if definition_path is None:
            ids = {name: str(uuid4()) for name in ('model', 'project', 'manifest', 'definition')}
            return {'schema': 'fpw-julia-editor-v1', 'project_id': project_id,
                    'base_head': expected_head, 'new': True, 'artifact_ids': ids,
                    'title': 'Nový Julia výpočet', 'privacy': 'project',
                    'julia_code': JULIA_TEMPLATE, 'project_toml': PROJECT_TEMPLATE,
                    'manifest_toml': MANIFEST_TEMPLATE, 'parameters': [],
                    'outputs': [{'name': 'result', 'kind': 'report',
                        'media_type': 'text/plain', 'required': True,
                        'max_bytes': 64 * 1024}],
                    'execution_policy': dict(POLICY_TEMPLATE)}
        computation, reference, entities = self._definition(git, expected_head, definition_path)
        files = git.snapshot(expected_head)
        definition, _, _ = self._artifact(files, entities, reference['artifact_id'], 'computation.json')
        model, _, code = self._artifact(files, entities, computation['entrypoint']['artifact_id'], 'model.jl')
        project_id_ = safe_path(computation['environment']['project_path'])[1]
        manifest_id = safe_path(computation['environment']['manifest_path'])[1]
        project, _, project_raw = self._artifact(files, entities, project_id_, 'Project.toml')
        manifest, _, manifest_raw = self._artifact(files, entities, manifest_id, 'Manifest.toml')
        require(len({definition['privacy'], model['privacy'], project['privacy'], manifest['privacy']}) == 1,
                'Julia editor bundle has mixed privacy')
        require(not self.projects.network or definition['privacy'] != 'local-only',
                'Local-only Julia computation is unavailable over the network')
        return {'schema': 'fpw-julia-editor-v1', 'project_id': project_id,
                'base_head': expected_head, 'new': False,
                'definition_path': definition_path,
                'artifact_ids': {'model': model['id'], 'project': project['id'],
                    'manifest': manifest['id'], 'definition': definition['id']},
                'title': computation['title'], 'privacy': definition['privacy'],
                'julia_code': code.decode(), 'project_toml': project_raw.decode(),
                'manifest_toml': manifest_raw.decode(),
                'parameters': computation['parameters'], 'outputs': computation['outputs'],
                'execution_policy': computation['execution_policy']}

    def editor_save(self, request, *, user_id=None):
        required = {'operation_id', 'project_id', 'base_head', 'new', 'artifact_ids',
                    'title', 'privacy', 'julia_code', 'project_toml', 'manifest_toml',
                    'parameters', 'outputs', 'execution_policy'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid Julia editor request')
        uuid(request['operation_id']); uuid(request['project_id'])
        require(type(request['new']) is bool and isinstance(request['base_head'], str),
                'Invalid Julia editor revision')
        ids = request['artifact_ids']
        require(isinstance(ids, dict) and set(ids) == {'model', 'project', 'manifest', 'definition'},
                'Invalid Julia editor artifact IDs')
        for value in ids.values(): uuid(value)
        require(len(set(ids.values())) == 4, 'Julia editor artifact IDs must differ')
        title = self._editor_text(request['title'], 'Julia title', 200).strip()
        require(title and '\n' not in title and '\r' not in title, 'Invalid Julia title')
        require(request['privacy'] in {'public', 'project', 'confidential', 'local-only'},
                'Invalid Julia privacy')
        code = self._editor_text(request['julia_code'], 'Julia code').encode()
        project_raw = self._editor_text(request['project_toml'], 'Julia Project.toml').encode()
        manifest_raw = self._editor_text(request['manifest_toml'], 'Julia Manifest.toml').encode()
        require(code and len(code) <= MAX_FILE, 'Julia code is empty or oversized')
        try:
            project_value = tomllib.loads(project_raw.decode())
            manifest_value = tomllib.loads(manifest_raw.decode())
        except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ValueError('Project.toml or Manifest.toml is invalid') from exc
        require(isinstance(project_value, dict) and isinstance(manifest_value, dict)
                and manifest_value.get('julia_version') == '1.10.12'
                and isinstance(manifest_value.get('manifest_format'), str)
                and isinstance(manifest_value.get('project_hash'), str),
                'Manifest must be generated for Julia 1.10.12')
        model_path = f'artifacts/{ids["model"]}/model.jl'
        project_path = f'artifacts/{ids["project"]}/Project.toml'
        manifest_path = f'artifacts/{ids["manifest"]}/Manifest.toml'
        definition_path = f'artifacts/{ids["definition"]}/computation.json'
        workspace = self.projects.workspace(request['project_id'])
        actor = user_id or ProjectCreation(self.node_path).author_id(); uuid(actor)

        def prepare(ws):
            head = ws.git.head()
            require(head == request['base_head'],
                    'Project changed; preserve the Julia draft and reopen the editor')
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            if request['new']:
                require(not set(ids.values()) & set(entities), 'Julia artifact ID already exists')
            else:
                current, reference, _ = self._definition(ws.git, head, definition_path)
                require(reference['artifact_id'] == ids['definition']
                        and current['entrypoint']['artifact_id'] == ids['model']
                        and safe_path(current['environment']['project_path'])[1] == ids['project']
                        and safe_path(current['environment']['manifest_path'])[1] == ids['manifest'],
                        'Julia editor bundle changed')
                for key, filename in (('model', 'model.jl'), ('project', 'Project.toml'),
                                      ('manifest', 'Manifest.toml'),
                                      ('definition', 'computation.json')):
                    self._artifact(files, entities, ids[key], filename)
            model_oid = ws.git.run('hash-object', '--stdin', binary=True, input=code).stdout.decode().strip()
            computation = {'schema': 'fpw-julia-computation-v1',
                'computation_id': ids['definition'], 'title': title,
                'entrypoint': {'artifact_id': ids['model'], 'path': model_path,
                    'git_blob': model_oid, 'sha256': digest(code)},
                'environment': {'project_path': project_path,
                    'project_sha256': digest(project_raw), 'manifest_path': manifest_path,
                    'manifest_sha256': digest(manifest_raw), 'julia_compat': '1.10.12'},
                'inputs': [], 'parameters': request['parameters'],
                'outputs': request['outputs'], 'execution_policy': request['execution_policy']}
            computation = validate_computation(computation)
            now = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
            changes = {model_path: code, project_path: project_raw,
                       manifest_path: manifest_raw, definition_path: canonical(computation)}
            labels = {'model': title + ' – Julia kód', 'project': title + ' – Project.toml',
                      'manifest': title + ' – Manifest.toml', 'definition': title}
            for key, filename in (('model', 'model.jl'), ('project', 'Project.toml'),
                                  ('manifest', 'Manifest.toml'),
                                  ('definition', 'computation.json')):
                meta_path = f'artifacts/{ids[key]}/metadata.json'
                created = entities.get(ids[key], {}).get('created_at', now)
                metadata = {'schema_version': 1, 'id': ids[key], 'title': labels[key],
                    'kind': 'document', 'created_at': created, 'author_id': actor,
                    'privacy': request['privacy'], 'provenance': 'user', 'file': filename,
                    'tags': ['julia-model-v1', 'julia-' + key]}
                if not request['new']:
                    previous = entities[ids[key]]
                    metadata['author_id'] = previous['author_id']
                changes[meta_path] = (json.dumps(metadata, ensure_ascii=False,
                    sort_keys=True, indent=2) + '\n').encode()
            candidate = dict(files); candidate.update(changes); validate_snapshot(candidate)
            return changes, 'Workspace Julia editor', actor + '@local.invalid', (
                'Create Julia computation' if request['new'] else 'Update Julia computation')

        receipt = workspace.transact(request['operation_id'], request, prepare,
                                     expected_head=request['base_head'])
        return {'schema': 'fpw-julia-editor-result-v1', 'project_id': request['project_id'],
                'definition_path': definition_path,
                'commit_id': receipt.get('commit_id') or receipt.get('result', {}).get('commit_id')}

    def prepare(self, request, *, user_id=None):
        require(isinstance(request, dict) and set(request) == {
            'operation_id', 'project_id', 'expected_head', 'definition_path', 'parameters'},
            'Invalid Julia preview request')
        executor = self._executor(request['project_id'])
        require(executor.git.head() == request['expected_head'],
                'Project changed before Julia preview')
        computation, reference, entities = self._definition(
            executor.git, request['expected_head'], request['definition_path'])
        require(not self.projects.network or self._network_safe(
            computation, reference, entities),
            'Local-only Julia computation is unavailable over the network')
        node_id, actor_id = self.identity(user_id)
        record = executor.prepare(request['operation_id'], node_id, actor_id,
                                  request['project_id'], computation, request['parameters'],
                                  definition_reference=reference)
        return dict(record, definition=reference)

    @staticmethod
    def _owned(executor, operation_id, node_id, user_id, project_id):
        record = executor.store.get(operation_id, node_id, user_id)
        require(record['project_id'] == project_id, 'Julia run belongs to another project')
        return record

    def status(self, project_id, operation_id=None, *, user_id=None):
        executor = self._executor(project_id); node_id, actor_id = self.identity(user_id)
        if operation_id is not None:
            self._owned(executor, operation_id, node_id, actor_id, project_id)
            result = executor.status(operation_id, node_id, actor_id)
            key = (node_id, actor_id, operation_id)
            with self._lock:
                worker = self._workers.get(key)
                result['worker_active'] = bool(worker and worker.is_alive())
                result['dispatch_error'] = self._errors.get(key)
            return result
        return {'schema': 'fpw-julia-workspace-v1', 'project_id': project_id,
                'runs': [self.status(project_id, row['operation_id'], user_id=user_id)
                         for row in executor.store.list(project_id, node_id, actor_id)]}

    def execute(self, request, *, user_id=None):
        require(isinstance(request, dict) and set(request) == {
            'operation_id', 'project_id', 'approval_digest'},
            'Invalid Julia execution request')
        executor = self._executor(request['project_id']); node_id, actor_id = self.identity(user_id)
        record = self._owned(executor, request['operation_id'], node_id, actor_id,
                             request['project_id'])
        require(record['state'] == 'prepared'
                and record['approval_digest'] == request['approval_digest'],
                'Julia confirmation differs from prepared preview')
        key = (node_id, actor_id, request['operation_id'])
        with self._lock:
            worker = self._workers.get(key)
            require(worker is None or not worker.is_alive(), 'Julia run is already dispatching')
            self._errors.pop(key, None)

            def run():
                try:
                    executor.execute(request['operation_id'], node_id, actor_id,
                                     request['approval_digest'])
                except (ValueError, OSError, RuntimeError, TimeoutError,
                        InterruptedError, subprocess.SubprocessError) as exc:
                    # Pre-dispatch rejection intentionally leaves the durable preview
                    # prepared. The session-local diagnostic prevents a polling loop;
                    # durable post-dispatch failures are already in the Julia journal.
                    with self._lock:
                        self._errors[key] = (str(exc) or exc.__class__.__name__)[:4096]
                finally:
                    with self._lock:
                        self._workers.pop(key, None)

            worker = threading.Thread(target=run, name='julia-' + request['operation_id'][:8],
                                      daemon=True)
            self._workers[key] = worker; worker.start()
        return {'operation_id': request['operation_id'], 'accepted': True,
                'state': 'dispatching'}

    def cancel(self, project_id, operation_id, *, user_id=None):
        executor = self._executor(project_id); node_id, actor_id = self.identity(user_id)
        self._owned(executor, operation_id, node_id, actor_id, project_id)
        return executor.cancel(operation_id, node_id, actor_id)

    def reconcile(self, project_id, operation_id, *, user_id=None):
        executor = self._executor(project_id); node_id, actor_id = self.identity(user_id)
        self._owned(executor, operation_id, node_id, actor_id, project_id)
        key = (node_id, actor_id, operation_id)
        with self._lock:
            worker = self._workers.get(key)
            require(worker is None or not worker.is_alive(),
                    'Active Julia worker cannot be reconciled')
        return executor.reconcile(operation_id, node_id, actor_id)

    def output(self, project_id, operation_id, output_name, *, user_id=None):
        executor = self._executor(project_id); node_id, actor_id = self.identity(user_id)
        self._owned(executor, operation_id, node_id, actor_id, project_id)
        content, item, _ = executor.output(operation_id, node_id, actor_id, output_name)
        preview = len(content) <= PREVIEW_BYTES
        return {'output': {key: value for key, value in item.items() if key != 'content_b64'},
                'preview_available': preview,
                'content_b64': base64.b64encode(content).decode() if preview else None}

    def publish(self, request, *, user_id=None, author_name='Workspace user'):
        required = {'publication_id', 'operation_id', 'project_id', 'output_name',
                    'artifact_id', 'title', 'filename', 'expected_head', 'privacy'}
        require(isinstance(request, dict) and set(request) == required,
                'Invalid Julia publication request')
        executor = self._executor(request['project_id']); node_id, actor_id = self.identity(user_id)
        self._owned(executor, request['operation_id'], node_id, actor_id, request['project_id'])
        workspace = self.projects.workspace(request['project_id'])
        return executor.publish(request['publication_id'], request['operation_id'], node_id,
            actor_id, request['output_name'], request['artifact_id'], request['title'],
            request['filename'], workspace, request['expected_head'], actor_id,
            privacy=request['privacy'], author_name=author_name)
