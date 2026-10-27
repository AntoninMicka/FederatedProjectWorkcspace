# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared Workspace projection and explicit control for the existing Julia runner."""
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import threading

from spikes.configuration import parse_node, read_config
from spikes.julia_computation import JuliaExecutor, validate_computation
from spikes.metadata import (MAX_METADATA, parse_json, require, safe_path, uuid,
                             validate_snapshot)
from spikes.output_execution import digest
from spikes.project_creation import ProjectCreation


PREVIEW_BYTES = 512 * 1024


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
                result.append({'definition': reference, 'computation': computation})
        require(git.head() == expected_head,
                'Project changed during Julia projection')
        return {'schema': 'fpw-julia-workspace-v1', 'project_id': project_id,
                'project_commit': expected_head, 'definitions': result}

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
