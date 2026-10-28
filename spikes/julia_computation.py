# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Pinned, fail-closed local Julia computations and explicit publication."""
from contextlib import closing
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import sqlite3
import stat
import subprocess
import tempfile
import time
import tomllib

from spikes.metadata import (MAX_FILE, MAX_METADATA, parse_json, require, safe_path,
                             timestamp, uuid, validate_snapshot)
from spikes.output_execution import MaterializationCache, canonical, digest


COMPUTATION_SCHEMA = 'fpw-julia-computation-v1'
RUN_SCHEMA = 'fpw-julia-run-v1'
RESULT_SCHEMA = 'fpw-julia-result-v1'
BUNDLE_SCHEMA = 'fpw-julia-result-bundle-v1'
RUNTIME_SCHEMA = 'fpw-julia-runtime-v1'
RUN_STATES = {'prepared', 'dispatching', 'succeeded', 'failed',
              'cancel_requested', 'cancelled', 'unknown'}
PRIVACY = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}
SHA256 = re.compile(r'[0-9a-f]{64}')
COMMIT = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')
IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _sha(value, label):
    require(isinstance(value, str) and bool(SHA256.fullmatch(value)), f'Invalid {label}')


def _text(value, label, maximum=256):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and len(value.encode()) <= maximum and not any(c in value for c in '\0\r\n'),
            f'Invalid {label}')


def _bounded_int(value, label, minimum=1, maximum=2 ** 63 - 1):
    require(type(value) is int and minimum <= value <= maximum, f'Invalid {label}')


def _path(value, label):
    parts = safe_path(value)
    require(len(value.encode()) <= 512, f'Invalid {label}')
    return parts


def validate_computation(value):
    """Validate the closed portable descriptor without touching runtime state."""
    require(isinstance(value, dict) and set(value) == {
        'schema', 'computation_id', 'title', 'entrypoint', 'environment',
        'inputs', 'parameters', 'outputs', 'execution_policy'},
        'Invalid Julia computation')
    require(value['schema'] == COMPUTATION_SCHEMA, 'Unsupported Julia computation schema')
    uuid(value['computation_id']); _text(value['title'], 'computation title')
    entry = value['entrypoint']
    require(isinstance(entry, dict) and set(entry) == {
        'artifact_id', 'path', 'git_blob', 'sha256'}, 'Invalid Julia entrypoint')
    uuid(entry['artifact_id']); _path(entry['path'], 'entrypoint path')
    require(entry['path'].endswith('.jl') and bool(COMMIT.fullmatch(entry['git_blob'])),
            'Invalid Julia entrypoint reference')
    _sha(entry['sha256'], 'entrypoint sha256')
    environment = value['environment']
    require(isinstance(environment, dict) and set(environment) == {
        'project_path', 'project_sha256', 'manifest_path', 'manifest_sha256',
        'julia_compat'}, 'Invalid Julia environment')
    for field in ('project_path', 'manifest_path'):
        _path(environment[field], field)
    require(environment['project_path'].endswith('Project.toml')
            and (environment['manifest_path'].endswith('Manifest.toml')
                 or re.search(r'Manifest-v\d+\.\d+\.toml$', environment['manifest_path'])),
            'Invalid Julia Project/Manifest paths')
    for field in ('project_sha256', 'manifest_sha256'):
        _sha(environment[field], field)
    require(isinstance(environment['julia_compat'], str)
            and bool(re.fullmatch(r'\d+\.\d+\.\d+', environment['julia_compat'])),
            'Julia compatibility must pin an exact patch version')
    inputs = value['inputs']
    require(isinstance(inputs, list) and len(inputs) <= 64, 'Invalid Julia inputs')
    names = set()
    for item in inputs:
        require(isinstance(item, dict) and set(item) == {
            'name', 'artifact_id', 'path', 'git_blob', 'sha256', 'media_type',
            'required'}, 'Invalid Julia input')
        require(isinstance(item['name'], str) and IDENTIFIER.fullmatch(item['name'])
                and item['name'] not in names, 'Invalid or duplicate Julia input name')
        names.add(item['name']); uuid(item['artifact_id']); _path(item['path'], 'input path')
        require(bool(COMMIT.fullmatch(item['git_blob'])), 'Invalid input blob')
        _sha(item['sha256'], 'input sha256'); _text(item['media_type'], 'input media type')
        require(type(item['required']) is bool, 'Invalid input cardinality')
    parameters = value['parameters']
    require(isinstance(parameters, list) and len(parameters) <= 64,
            'Invalid Julia parameters')
    names = set()
    for item in parameters:
        require(isinstance(item, dict) and set(item) == {
            'name', 'type', 'required', 'default', 'constraints'},
            'Invalid Julia parameter')
        require(isinstance(item['name'], str) and IDENTIFIER.fullmatch(item['name'])
                and item['name'] not in names, 'Invalid or duplicate Julia parameter name')
        names.add(item['name'])
        require(item['type'] in {'boolean', 'string', 'integer', 'number', 'array', 'object'}
                and type(item['required']) is bool and isinstance(item['constraints'], dict),
                'Invalid Julia parameter contract')
        # A required parameter may intentionally have no default; it must then be
        # supplied by validate_parameters() when a concrete run is prepared.
        _validate_parameter(item['default'], item, allow_missing=True)
    outputs = value['outputs']
    require(isinstance(outputs, list) and 1 <= len(outputs) <= 32,
            'Invalid Julia outputs')
    names = set()
    for item in outputs:
        require(isinstance(item, dict) and set(item) == {
            'name', 'kind', 'media_type', 'required', 'max_bytes'},
            'Invalid Julia output')
        require(isinstance(item['name'], str) and IDENTIFIER.fullmatch(item['name'])
                and item['name'] not in names, 'Invalid or duplicate Julia output name')
        names.add(item['name'])
        require(item['kind'] in {'table', 'chart', 'report', 'dataset', 'file'},
                'Invalid Julia output kind')
        _text(item['media_type'], 'output media type')
        require(type(item['required']) is bool, 'Invalid output cardinality')
        _bounded_int(item['max_bytes'], 'output max_bytes', maximum=MAX_FILE)
    policy = value['execution_policy']
    require(isinstance(policy, dict) and set(policy) == {
        'network', 'timeout_ms', 'cpu_threads', 'max_processes', 'memory_bytes',
        'output_bytes', 'output_files', 'stdout_bytes', 'stderr_bytes'},
        'Invalid Julia execution policy')
    require(policy['network'] == 'deny', 'Julia v1 requires denied network')
    for field, maximum in (('timeout_ms', 86_400_000), ('cpu_threads', 256),
                           ('max_processes', 256), ('memory_bytes', 2 ** 50),
                           ('output_bytes', 64 * 1024 * 1024), ('output_files', 256),
                           ('stdout_bytes', 16 * 1024 * 1024),
                           ('stderr_bytes', 16 * 1024 * 1024)):
        _bounded_int(policy[field], field, maximum=maximum)
    require(sum(item['max_bytes'] for item in outputs) <= policy['output_bytes'],
            'Declared Julia outputs exceed execution policy')
    return json.loads(canonical(value))


def _validate_parameter(value, descriptor, *, allow_missing=False):
    if value is None:
        require(allow_missing, f'Missing required parameter {descriptor["name"]}')
        return
    kind, limits = descriptor['type'], descriptor['constraints']
    require(set(limits) <= {'minimum', 'maximum', 'min_length', 'max_length',
                            'enum', 'max_items', 'properties'},
            'Unknown Julia parameter constraint')
    valid = ((kind == 'boolean' and type(value) is bool)
             or (kind == 'string' and isinstance(value, str))
             or (kind == 'integer' and type(value) is int)
             or (kind == 'number' and type(value) in {int, float})
             or (kind == 'array' and isinstance(value, list))
             or (kind == 'object' and isinstance(value, dict)))
    require(valid, f'Invalid value for parameter {descriptor["name"]}')
    if type(value) in {int, float}:
        require(value == value and value not in {float('inf'), float('-inf')},
                'Non-finite Julia parameter')
        require('minimum' not in limits or value >= limits['minimum'], 'Parameter below minimum')
        require('maximum' not in limits or value <= limits['maximum'], 'Parameter above maximum')
    if isinstance(value, str):
        require(len(value.encode()) <= limits.get('max_length', 8192)
                and len(value) >= limits.get('min_length', 0), 'Invalid parameter length')
    if isinstance(value, list):
        require(len(value) <= limits.get('max_items', 256), 'Too many parameter items')
    if isinstance(value, dict):
        properties = limits.get('properties', {})
        require(isinstance(properties, dict) and set(value) <= set(properties),
                'Unknown object parameter property')
    if 'enum' in limits:
        require(isinstance(limits['enum'], list) and value in limits['enum'],
                'Parameter is outside enum')


def validate_parameters(computation, value):
    require(isinstance(value, dict) and len(canonical(value)) <= MAX_METADATA,
            'Invalid Julia parameters')
    descriptors = {item['name']: item for item in computation['parameters']}
    require(set(value) <= set(descriptors), 'Unknown Julia parameter')
    result = {}
    for name, descriptor in descriptors.items():
        candidate = value.get(name, descriptor['default'])
        _validate_parameter(candidate, descriptor, allow_missing=not descriptor['required'])
        if candidate is not None:
            result[name] = candidate
    return json.loads(canonical(result))


def _tree_digest(root):
    root = Path(root).absolute()
    require(root.is_dir() and not root.is_symlink(), 'Invalid Julia depot')
    value = hashlib.sha256(); count = total = 0
    for parent, directories, files in os.walk(root, followlinks=False):
        directories.sort(); files.sort()
        for name in directories:
            require(not (Path(parent) / name).is_symlink(), 'Julia depot contains symlink')
        for name in files:
            path = Path(parent) / name; info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and not info.st_mode & 0o022,
                    'Unsafe Julia depot file')
            count += 1; total += info.st_size
            require(count <= 100000 and total <= 4 * 1024 ** 3, 'Julia depot exceeds limits')
            raw = path.read_bytes(); relative = path.relative_to(root).as_posix()
            value.update(relative.encode()); value.update(b'\0'); value.update(digest(raw).encode())
            value.update(b'\0')
    return value.hexdigest()


def _distribution_digest(root):
    """Hash the extracted runtime tree, including safe internal symlinks."""
    root = Path(root).resolve(strict=True)
    require(root.is_dir() and not root.stat().st_mode & 0o022,
            'Unsafe Julia distribution root')
    value = hashlib.sha256(); count = total = 0
    for path in sorted(root.rglob('*'), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix(); info = path.lstat(); count += 1
        require(count <= 200000, 'Julia distribution exceeds file limit')
        if stat.S_ISLNK(info.st_mode):
            resolved = path.resolve(strict=True)
            require(resolved == root or root in resolved.parents,
                    'Julia distribution symlink escapes runtime root')
            marker = b'L'; payload = os.readlink(path).encode()
        elif stat.S_ISDIR(info.st_mode):
            require(not info.st_mode & 0o022, 'Unsafe Julia distribution directory')
            marker = b'D'; payload = b''
        elif stat.S_ISREG(info.st_mode):
            require(not info.st_mode & 0o022, 'Unsafe Julia distribution file')
            total += info.st_size
            require(total <= 4 * 1024 ** 3, 'Julia distribution exceeds size limit')
            marker = b'F'; payload = digest(path.read_bytes()).encode()
        else:
            raise ValueError('Julia distribution contains special file')
        value.update(marker); value.update(b'\0'); value.update(relative.encode())
        value.update(b'\0'); value.update(payload); value.update(b'\0')
    return value.hexdigest()


def validate_runtime_binding(value, *, verify=True):
    require(isinstance(value, dict) and set(value) == {
        'schema', 'binding_id', 'revision', 'executable', 'version', 'platform',
        'executable_sha256', 'distribution_sha256', 'sysimage', 'sysimage_sha256',
        'depot', 'depot_sha256'}, 'Invalid Julia runtime binding')
    require(value['schema'] == RUNTIME_SCHEMA, 'Unsupported Julia runtime binding')
    uuid(value['binding_id']); _text(value['revision'], 'runtime revision')
    require(value['platform'] == f'linux-{platform.machine().lower()}',
            'Julia runtime platform differs from host')
    require(bool(re.fullmatch(r'\d+\.\d+\.\d+', value['version'])),
            'Invalid Julia runtime version')
    for field in ('executable', 'sysimage', 'depot'):
        require(isinstance(value[field], str) and Path(value[field]).is_absolute(),
                f'Invalid runtime {field}')
    executable, sysimage = Path(value['executable']), Path(value['sysimage'])
    runtime_root = executable.parent.parent
    require(runtime_root in sysimage.parents, 'Julia sysimage is outside runtime distribution')
    for field in ('executable_sha256', 'distribution_sha256', 'sysimage_sha256',
                  'depot_sha256'):
        _sha(value[field], field)
    if not verify:
        return json.loads(canonical(value))
    depot = Path(value['depot'])
    for path, field in ((executable, 'executable'), (sysimage, 'sysimage'),
                        (depot, 'depot')):
        require(path.resolve(strict=True) == path, f'Runtime {field} has a symlink component')
    for path, field in ((executable, 'executable'), (sysimage, 'sysimage')):
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and not path.is_symlink()
                and not info.st_mode & 0o022, f'Unsafe Julia {field}')
    require(os.access(executable, os.X_OK), 'Julia executable is not executable')
    require(digest(executable.read_bytes()) == value['executable_sha256'],
            'Julia executable differs from binding')
    require(digest(sysimage.read_bytes()) == value['sysimage_sha256'],
            'Julia sysimage differs from binding')
    require(_distribution_digest(runtime_root) == value['distribution_sha256'],
            'Julia distribution differs from binding')
    require(_tree_digest(value['depot']) == value['depot_sha256'],
            'Julia depot differs from binding')
    return json.loads(canonical(value))


class JuliaRunStore:
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700 and not self.root.is_symlink(),
                'Julia state directory requires owned mode 0700')
        self.path = self.root / 'julia-runs.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe Julia run journal')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL'); db.execute('BEGIN IMMEDIATE')
            db.execute('''CREATE TABLE IF NOT EXISTS runs(
                operation_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, user_id TEXT NOT NULL,
                project_id TEXT NOT NULL, project_commit TEXT NOT NULL,
                computation_id TEXT NOT NULL, request_sha256 TEXT NOT NULL,
                request_json BLOB NOT NULL, preview_json BLOB NOT NULL,
                approval_digest TEXT NOT NULL, state TEXT NOT NULL,
                error TEXT, receipt_json BLOB, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            require([row[1] for row in db.execute('PRAGMA table_info(runs)')] == [
                'operation_id', 'node_id', 'user_id', 'project_id', 'project_commit',
                'computation_id', 'request_sha256', 'request_json', 'preview_json',
                'approval_digest', 'state', 'error', 'receipt_json', 'created_at',
                'updated_at'], 'Unsupported Julia run journal schema')
            db.commit(); return closing(db)
        except Exception:
            db.close(); raise

    @staticmethod
    def _owner(row, node_id, user_id):
        require(row is not None and row[0] == node_id and row[1] == user_id,
                'Julia run is unavailable to this owner')

    def prepare(self, request, preview, node_id, user_id):
        operation_id = request['operation_id']; uuid(operation_id); uuid(node_id); uuid(user_id)
        raw, preview_raw = canonical(request), canonical(preview)
        approval = digest(raw + b'\0' + preview_raw); created = now()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,request_sha256,request_json,'
                'preview_json,approval_digest FROM runs WHERE operation_id=?',
                (operation_id,)).fetchone()
            expected = (node_id, user_id, digest(raw), raw, preview_raw, approval)
            if row:
                self._owner(row, node_id, user_id)
                require(row == expected, 'Operation ID belongs to a different Julia run')
            else:
                db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
                    operation_id, node_id, user_id, request['project_id'],
                    request['project_commit'], request['computation']['computation_id'],
                    digest(raw), raw, preview_raw, approval, 'prepared', None, None,
                    created, created))
            db.commit()
        return self.get(operation_id, node_id, user_id)

    def transition(self, operation_id, node_id, user_id, expected, state, *, error=None,
                   receipt=None):
        require(state in RUN_STATES and expected <= RUN_STATES, 'Invalid Julia run state')
        receipt_raw = canonical(receipt) if receipt is not None else None
        if error is not None:
            require(isinstance(error, str) and 0 < len(error.encode()) <= 4096,
                    'Invalid Julia run error')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,state,error,receipt_json FROM runs '
                             'WHERE operation_id=?', (operation_id,)).fetchone()
            self._owner(row, node_id, user_id)
            if row[2] in expected:
                db.execute('UPDATE runs SET state=?,error=?,receipt_json=?,updated_at=? '
                           'WHERE operation_id=?',
                           (state, error, receipt_raw, now(), operation_id))
            else:
                require(row[2:] == (state, error, receipt_raw),
                        'Julia run transition conflicts with durable state')
            db.commit()
        return self.get(operation_id, node_id, user_id)

    def get(self, operation_id, node_id, user_id):
        uuid(operation_id); uuid(node_id); uuid(user_id)
        with self.connect() as db:
            row = db.execute('SELECT node_id,user_id,project_id,project_commit,'
                'computation_id,request_sha256,request_json,preview_json,approval_digest,'
                'state,error,receipt_json,created_at,updated_at FROM runs WHERE operation_id=?',
                (operation_id,)).fetchone()
        self._owner(row, node_id, user_id)
        request, preview = json.loads(row[6]), json.loads(row[7])
        require(canonical(request) == row[6] and digest(row[6]) == row[5]
                and canonical(preview) == row[7]
                and digest(row[6] + b'\0' + row[7]) == row[8]
                and row[9] in RUN_STATES, 'Stored Julia run changed')
        receipt = json.loads(row[11]) if row[11] is not None else None
        if receipt is not None:
            require(row[9] in {'succeeded', 'failed', 'cancelled'}
                    and canonical(receipt) == row[11],
                    'Stored Julia receipt changed')
        timestamp(row[12], 'created_at'); timestamp(row[13], 'updated_at')
        return {'operation_id': operation_id, 'node_id': row[0], 'user_id': row[1],
                'project_id': row[2], 'project_commit': row[3],
                'computation_id': row[4], 'request_sha256': row[5],
                'request': request, 'preview': preview, 'approval_digest': row[8],
                'state': row[9], 'error': row[10], 'receipt': receipt,
                'created_at': row[12], 'updated_at': row[13]}

    def list(self, project_id, node_id, user_id, *, limit=50):
        """Return bounded owner-scoped records without weakening get validation."""
        uuid(project_id); uuid(node_id); uuid(user_id)
        require(type(limit) is int and 1 <= limit <= 100, 'Invalid Julia run list limit')
        with self.connect() as db:
            rows = db.execute(
                'SELECT operation_id FROM runs WHERE project_id=? AND node_id=? AND user_id=? '
                'ORDER BY updated_at DESC, operation_id LIMIT ?',
                (project_id, node_id, user_id, limit)).fetchall()
        return [self.get(row[0], node_id, user_id) for row in rows]

    def cancel(self, operation_id, node_id, user_id):
        """Durably request cancellation; the owning executor terminates its group."""
        record = self.get(operation_id, node_id, user_id)
        if record['state'] == 'prepared':
            return self.transition(operation_id, node_id, user_id,
                                   {'prepared'}, 'cancelled',
                                   error='Julia run was cancelled before dispatch')
        if record['state'] == 'dispatching':
            return self.transition(operation_id, node_id, user_id,
                                   {'dispatching'}, 'cancel_requested')
        require(record['state'] in {'cancel_requested', 'cancelled'},
                'Julia run is not cancellable')
        return record


class DirectTestSandbox:
    """Explicitly injected test-only subprocess boundary; never a production default."""
    production = False

    def command(self, binding, snapshot, environment, work, output, request, computation):
        return [binding['executable'], f'--project={environment}', '--startup-file=no',
                '--history-file=no', '--gcthreads=1,0',
                f'--threads={computation["execution_policy"]["cpu_threads"]}',
                '--', str(snapshot / computation['entrypoint']['path']),
                '--fpw-request', str(request), '--fpw-output', str(output)]


class BubblewrapSandbox:
    production = True

    def __init__(self, executable='/usr/bin/bwrap'):
        self.executable = Path(executable)
        require(self.executable.is_file() and os.access(self.executable, os.X_OK),
                'bubblewrap is unavailable')

    def command(self, binding, snapshot, environment, work, output, request, computation):
        runtime_root = Path(binding['executable']).parent.parent
        sysimage = Path(binding['sysimage']).relative_to(runtime_root).as_posix()
        args = [str(self.executable), '--die-with-parent', '--new-session', '--unshare-all',
                '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                '--dir', '/home', '--dir', '/work', '--dir', '/output', '--dir', '/depot-overlay']
        for source in ('/usr', '/bin', '/lib', '/lib64'):
            if Path(source).exists():
                args += ['--ro-bind', source, source]
        args += ['--ro-bind', str(runtime_root), '/runtime',
                 '--ro-bind', str(snapshot), '/project',
                 '--ro-bind', str(environment), '/environment',
                 '--ro-bind', binding['depot'], '/depot',
                 '--bind', str(work), '/work', '--bind', str(output), '/output',
                 '--setenv', 'HOME', '/home', '--setenv', 'PATH', '/runtime/bin:/usr/bin:/bin',
                 '--setenv', 'JULIA_DEPOT_PATH', '/depot-overlay:/depot',
                 '--setenv', 'JULIA_LOAD_PATH', '@:@stdlib',
                 '--setenv', 'JULIA_PKG_OFFLINE', 'true', '--chdir', '/work', '--',
                 '/runtime/bin/' + Path(binding['executable']).name,
                 '--project=/environment', '--sysimage=/runtime/' + sysimage,
                 '--startup-file=no', '--history-file=no', '--gcthreads=1,0',
                 f'--threads={computation["execution_policy"]["cpu_threads"]}', '--',
                 '/project/' + computation['entrypoint']['path'],
                 '--fpw-request', '/work/' + request.name, '--fpw-output', '/output']
        return args


def _limits(policy):
    def apply():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        cpu = max(1, (policy['timeout_ms'] + 999) // 1000)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        resource.setrlimit(resource.RLIMIT_AS, (policy['memory_bytes'], policy['memory_bytes']))
        # RLIMIT_NPROC is per real UID, not per process tree. Base the absolute
        # ceiling on the current UID population so an already busy node does not
        # prevent bubblewrap from creating its PID/user namespaces.
        uid = os.getuid(); existing = 0
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit():
                continue
            try:
                if entry.stat().st_uid == uid:
                    existing += len(list((entry / 'task').iterdir()))
            except FileNotFoundError:
                pass
        # The kernel counts threads too; reserve the declared Julia threads and
        # two short-lived bubblewrap namespace helpers separately.
        processes = (existing + policy['max_processes'] +
                     policy['cpu_threads'] + 1)
        resource.setrlimit(resource.RLIMIT_NPROC, (processes, processes))
        file_size = max(policy['output_bytes'], policy['stdout_bytes'],
                        policy['stderr_bytes'])
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_size, file_size))
        resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    return apply


class JuliaExecutor:
    def __init__(self, *, git, state_dir, runtime_binding, sandbox=None):
        self.git = git; self.state_dir = Path(state_dir).absolute()
        self.binding = validate_runtime_binding(runtime_binding, verify=False)
        self.sandbox = sandbox
        self.store = JuliaRunStore(self.state_dir)
        self.cache = MaterializationCache(self.state_dir)

    def _blob(self, commit, reference):
        path = reference['path']; _path(path, 'Git path')
        rows = [row for row in self.git.run('ls-tree', commit, '--', path).stdout.splitlines() if row]
        require(len(rows) == 1, 'Pinned Julia file is missing')
        info, actual = rows[0].split('\t', 1); mode, kind, oid = info.split()
        require(actual == path and mode == '100644' and kind == 'blob'
                and oid == reference.get('git_blob', oid), 'Pinned Julia blob differs')
        raw = self.git.run('cat-file', 'blob', oid, binary=True).stdout
        require(digest(raw) == reference['sha256'], 'Pinned Julia bytes differ')
        return raw, oid

    def _sources(self, project_id, commit, computation, extra_references=()):
        require(self.git.head() == commit, 'Project changed before Julia operation')
        entities = validate_snapshot(self.git.snapshot(commit))
        refs = [*extra_references, computation['entrypoint'], *computation['inputs']]
        values, privacies = {}, []
        for reference in refs:
            entity = entities.get(reference['artifact_id'])
            require(entity is not None
                    and reference['path'].startswith(f'artifacts/{reference["artifact_id"]}/'),
                    'Julia reference is not owned by its artifact')
            raw, oid = self._blob(commit, reference)
            require(oid == reference['git_blob'], 'Julia source blob changed')
            values[reference['path']] = raw; privacies.append(entity['privacy'])
        environment = computation['environment']
        for field, sha_field in (('project_path', 'project_sha256'),
                                 ('manifest_path', 'manifest_sha256')):
            parts = safe_path(environment[field])
            require(len(parts) == 3 and parts[0] == 'artifacts'
                    and parts[1] in entities, 'Julia environment is not a project artifact')
            privacies.append(entities[parts[1]]['privacy'])
            reference = {'path': environment[field], 'sha256': environment[sha_field]}
            raw, _ = self._blob(commit, reference); values[reference['path']] = raw
        require(self.git.head() == commit, 'Project changed while reading Julia inputs')
        privacy = max(privacies, key=PRIVACY.get)
        return values, privacy

    def _preflight(self, computation, sources):
        require(computation['environment']['julia_compat'] == self.binding['version'],
                'Julia runtime version differs from computation')
        project = tomllib.loads(sources[computation['environment']['project_path']].decode())
        manifest = tomllib.loads(sources[computation['environment']['manifest_path']].decode())
        require(isinstance(project, dict) and isinstance(manifest, dict),
                'Invalid Julia Project/Manifest')
        require(manifest.get('julia_version') == self.binding['version']
                and isinstance(manifest.get('manifest_format'), str)
                and isinstance(manifest.get('project_hash'), str)
                and bool(COMMIT.fullmatch(manifest['project_hash'])),
                'Julia Manifest does not match pinned runtime or Project contract')

    def prepare(self, operation_id, node_id, user_id, project_id, computation, parameters,
                definition_reference=None):
        uuid(project_id); computation = validate_computation(computation)
        validate_runtime_binding(self.binding)
        parameters = validate_parameters(computation, parameters)
        references = () if definition_reference is None else (definition_reference,)
        commit = self.git.head(); sources, privacy = self._sources(
            project_id, commit, computation, references)
        self._preflight(computation, sources)
        request = {'schema': RUN_SCHEMA, 'operation_id': operation_id,
            'project_id': project_id, 'project_commit': commit,
            'computation': computation, 'computation_sha256': digest(canonical(computation)),
            'parameters': parameters, 'parameters_sha256': digest(canonical(parameters)),
            'runtime': {key: self.binding[key] for key in self.binding if key not in {
                'executable', 'sysimage', 'depot'}}, 'privacy': privacy,
            'sources': [{'path': path, 'sha256': digest(raw), 'size': len(raw)}
                        for path, raw in sorted(sources.items())]}
        if definition_reference is not None:
            request['definition'] = definition_reference
        preview = {'schema': RUN_SCHEMA, 'project_commit': commit,
            'computation_id': computation['computation_id'], 'title': computation['title'],
            'privacy': privacy, 'parameters': parameters, 'outputs': computation['outputs'],
            'runtime': {'binding_id': self.binding['binding_id'],
                        'revision': self.binding['revision'],
                        'version': self.binding['version'],
                        'platform': self.binding['platform']},
            'effects': ['local-process', 'local-materialization'],
            'not_included': ['project-write', 'network', 'publication']}
        return self.store.prepare(request, preview, node_id, user_id)

    def _revalidate(self, record):
        computation = validate_computation(record['request']['computation'])
        require(validate_runtime_binding(self.binding) == self.binding
                and record['request']['runtime'] == {key: self.binding[key]
                    for key in self.binding if key not in {'executable', 'sysimage', 'depot'}},
                'Julia runtime binding changed')
        references = (() if record['request'].get('definition') is None
                      else (record['request']['definition'],))
        sources, privacy = self._sources(record['project_id'], record['project_commit'],
                                         computation, references)
        self._preflight(computation, sources)
        require(record['request']['sources'] == [
            {'path': path, 'sha256': digest(raw), 'size': len(raw)}
            for path, raw in sorted(sources.items())]
            and privacy == record['request']['privacy'], 'Julia inputs changed')
        return computation, sources

    @staticmethod
    def _write_snapshot(root, sources):
        for name, raw in sources.items():
            target = root.joinpath(*safe_path(name)); target.parent.mkdir(parents=True, mode=0o700,
                                                                          exist_ok=True)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())

    @staticmethod
    def _write_environment(root, sources, computation):
        environment = computation['environment']
        for source, name in ((environment['project_path'], 'Project.toml'),
                             (environment['manifest_path'], 'Manifest.toml')):
            target = root / name
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o400)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(sources[source]); handle.flush(); os.fsync(handle.fileno())

    def _bundle(self, output, computation):
        result_path = output / 'fpw-julia-result-v1.json'
        require(result_path.is_file() and not result_path.is_symlink()
                and result_path.stat().st_size <= MAX_METADATA, 'Julia result manifest is missing')
        raw = result_path.read_bytes(); value = parse_json(raw, MAX_METADATA)
        require(canonical(value) == raw and isinstance(value, dict)
                and set(value) == {'schema', 'outputs'} and value['schema'] == RESULT_SCHEMA
                and isinstance(value['outputs'], list), 'Invalid Julia result manifest')
        declared = {item['name']: item for item in computation['outputs']}; seen = set(); files = []
        for item in value['outputs']:
            require(isinstance(item, dict) and set(item) == {
                'name', 'kind', 'media_type', 'path', 'size', 'sha256'},
                'Invalid Julia result output')
            name = item['name']; contract = declared.get(name)
            require(contract is not None and name not in seen
                    and item['kind'] == contract['kind']
                    and item['media_type'] == contract['media_type'],
                    'Julia result differs from output contract')
            seen.add(name); parts = _path(item['path'], 'result path')
            path = output.joinpath(*parts); info = path.lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and not path.is_symlink() and info.st_size == item['size']
                    and info.st_size <= contract['max_bytes'], 'Unsafe Julia output')
            content = path.read_bytes(); require(digest(content) == item['sha256'],
                                                 'Julia output hash differs')
            files.append(dict(item, content_b64=base64.b64encode(content).decode()))
        require(all(not item['required'] or item['name'] in seen
                    for item in computation['outputs']), 'Required Julia output is missing')
        require(len(files) <= computation['execution_policy']['output_files']
                and sum(item['size'] for item in files)
                    <= computation['execution_policy']['output_bytes'],
                'Julia outputs exceed policy')
        allowed = {'fpw-julia-result-v1.json', *(item['path'] for item in value['outputs'])}
        actual = set()
        for parent, directories, names in os.walk(output, followlinks=False):
            for name in directories:
                path = Path(parent) / name
                require(stat.S_ISDIR(path.lstat().st_mode) and not path.is_symlink(),
                        'Julia output contains an unsafe directory')
            for name in names:
                path = Path(parent) / name
                require(stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink(),
                        'Julia output contains an unsafe file')
                actual.add(path.relative_to(output).as_posix())
        require(actual == allowed, 'Julia output contains undeclared files')
        return canonical({'schema': BUNDLE_SCHEMA, 'outputs': files})

    @staticmethod
    def _terminate(process):
        if process.poll() is not None:
            return process.returncode
        os.killpg(process.pid, signal.SIGTERM)
        try:
            return process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            return process.wait(timeout=2)

    def cancel(self, operation_id, node_id, user_id):
        return self.store.cancel(operation_id, node_id, user_id)

    @staticmethod
    def _diagnostics(operation_id, stdout, stderr, exit_code):
        stdout_raw, stderr_raw = stdout.read_bytes(), stderr.read_bytes()
        return {'schema': RUN_SCHEMA, 'operation_id': operation_id,
                'exit_code': exit_code,
                'stdout_sha256': digest(stdout_raw), 'stdout_size': len(stdout_raw),
                'stdout_b64': base64.b64encode(stdout_raw).decode(),
                'stderr_sha256': digest(stderr_raw), 'stderr_size': len(stderr_raw),
                'stderr_b64': base64.b64encode(stderr_raw).decode(),
                'completed_at': now()}

    def execute(self, operation_id, node_id, user_id, approval_digest,
                checkpoint=lambda stage: None):
        record = self.store.get(operation_id, node_id, user_id)
        require(record['state'] == 'prepared', 'Julia run is not prepared')
        require(approval_digest == record['approval_digest'],
                'Julia run confirmation differs from preview')
        computation, sources = self._revalidate(record)
        self.store.transition(operation_id, node_id, user_id, {'prepared'}, 'dispatching')
        checkpoint('dispatching')
        temporary = Path(tempfile.mkdtemp(prefix='.julia-run-', dir=self.state_dir))
        snapshot, environment = temporary / 'project', temporary / 'environment'
        work, output = temporary / 'work', temporary / 'output'
        for path in (snapshot, environment, work, output): path.mkdir(mode=0o700)
        try:
            self._write_snapshot(snapshot, sources)
            self._write_environment(environment, sources, computation)
            request_path = work / 'request.json'; request_path.write_bytes(canonical(record['request']))
            request_path.chmod(0o400)
            stdout, stderr = work / 'stdout.log', work / 'stderr.log'
            sandbox = self.sandbox if self.sandbox is not None else BubblewrapSandbox()
            command = sandbox.command(self.binding, snapshot, environment, work, output,
                                           request_path, computation)
            try:
                with stdout.open('wb') as out, stderr.open('wb') as err:
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=out,
                        stderr=err, env={'LC_ALL': 'C', 'PATH': '/usr/bin:/bin'},
                        start_new_session=True, preexec_fn=_limits(computation['execution_policy']))
                    deadline = time.monotonic() + computation['execution_policy']['timeout_ms'] / 1000
                    while process.poll() is None:
                        current = self.store.get(operation_id, node_id, user_id)['state']
                        if current == 'cancel_requested':
                            self._terminate(process)
                            error = 'Julia run was cancelled and its process group was terminated'
                            diagnostics = self._diagnostics(
                                operation_id, stdout, stderr, process.returncode)
                            self.store.transition(operation_id, node_id, user_id,
                                                  {'cancel_requested'}, 'cancelled', error=error,
                                                  receipt=diagnostics)
                            raise InterruptedError(error)
                        if time.monotonic() >= deadline:
                            self._terminate(process)
                            error = 'Julia run timed out and its process group was terminated'
                            diagnostics = self._diagnostics(
                                operation_id, stdout, stderr, process.returncode)
                            self.store.transition(operation_id, node_id, user_id,
                                                  {'dispatching'}, 'cancelled', error=error,
                                                  receipt=diagnostics)
                            raise TimeoutError(error)
                        time.sleep(0.02)
                    code = process.returncode
            except Exception as exc:
                if isinstance(exc, (InterruptedError, TimeoutError)): raise
                error = str(exc) or exc.__class__.__name__
                self.store.transition(operation_id, node_id, user_id,
                                      {'dispatching'}, 'failed', error=error)
                raise
            checkpoint('process-finished')
            try:
                for path, limit, label in ((stdout, computation['execution_policy']['stdout_bytes'], 'stdout'),
                                           (stderr, computation['execution_policy']['stderr_bytes'], 'stderr')):
                    require(path.stat().st_size <= limit, f'Julia {label} exceeds policy')
            except Exception as exc:
                self.store.transition(operation_id, node_id, user_id,
                                      {'dispatching'}, 'failed',
                                      error=str(exc) or exc.__class__.__name__,
                                      receipt=self._diagnostics(
                                          operation_id, stdout, stderr, code))
                raise
            if code != 0:
                error = f'Julia process failed with exit code {code}'
                self.store.transition(operation_id, node_id, user_id,
                                      {'dispatching'}, 'failed', error=error,
                                      receipt=self._diagnostics(
                                          operation_id, stdout, stderr, code))
                raise RuntimeError(error)
            try:
                bundle = self._bundle(output, computation)
            except Exception as exc:
                self.store.transition(operation_id, node_id, user_id,
                                      {'dispatching'}, 'failed',
                                      error=str(exc) or exc.__class__.__name__,
                                      receipt=self._diagnostics(
                                          operation_id, stdout, stderr, code))
                raise
            cache_receipt = {'schema_version': 1, 'operation_id': operation_id,
                'plan_id': operation_id, 'plan_sha256': record['request_sha256'],
                'step_id': computation['computation_id'],
                'manifest_sha256': record['request_sha256'], 'output_port': 'result-bundle',
                'output_sha256': digest(bundle), 'output_size': len(bundle),
                'contract': {'schema': BUNDLE_SCHEMA, 'mime_type': 'application/json',
                    'format': 'julia-result-bundle', 'privacy': record['request']['privacy']},
                'completed_at': now()}
            cache_receipt = self.cache.publish(operation_id, computation['computation_id'],
                                               bundle, cache_receipt)
            checkpoint('materialization-published')
            receipt = self._diagnostics(operation_id, stdout, stderr, code)
            receipt.update(request_sha256=record['request_sha256'], cache=cache_receipt)
            return self.store.transition(operation_id, node_id, user_id,
                                         {'dispatching', 'cancel_requested'}, 'succeeded',
                                         receipt=receipt)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def reconcile(self, operation_id, node_id, user_id):
        record = self.store.get(operation_id, node_id, user_id)
        if record['state'] not in {'dispatching', 'cancel_requested'}: return record
        try:
            bundle, cache_receipt = self.cache.load_generation(
                operation_id, record['computation_id'])
            require(cache_receipt['plan_sha256'] == record['request_sha256']
                    and cache_receipt['output_sha256'] == digest(bundle),
                    'Recovered Julia materialization differs')
            receipt = {'schema': RUN_SCHEMA, 'operation_id': operation_id,
                'request_sha256': record['request_sha256'], 'cache': cache_receipt,
                'exit_code': 0, 'stdout_sha256': None, 'stdout_size': None,
                'stdout_b64': None, 'stderr_sha256': None, 'stderr_size': None,
                'stderr_b64': None, 'completed_at': now(),
                'recovered': True}
            return self.store.transition(operation_id, node_id, user_id,
                                         {'dispatching', 'cancel_requested'}, 'succeeded',
                                         receipt=receipt)
        except (ValueError, OSError):
            return self.store.transition(operation_id, node_id, user_id,
                {'dispatching', 'cancel_requested'}, 'unknown',
                error='Interrupted Julia dispatch has no complete receipt')

    def status(self, operation_id, node_id, user_id):
        record = self.store.get(operation_id, node_id, user_id)
        if record['state'] != 'succeeded': return dict(record, freshness=record['state'])
        try:
            self._revalidate(record); freshness = 'current'
        except (ValueError, OSError, subprocess.SubprocessError):
            freshness = 'stale'
        return dict(record, freshness=freshness)

    def _output(self, operation_id, node_id, user_id, output_name, *, revalidate):
        record = self.store.get(operation_id, node_id, user_id)
        require(record['state'] == 'succeeded', 'Julia run has no publishable output')
        if revalidate:
            self._revalidate(record)
        bundle, receipt = self.cache.load_generation(operation_id, record['computation_id'])
        require(receipt == record['receipt']['cache'], 'Julia cache differs from run receipt')
        value = parse_json(bundle, 64 * 1024 * 1024)
        require(canonical(value) == bundle, 'Julia bundle changed')
        item = next((item for item in value['outputs'] if item['name'] == output_name), None)
        require(item is not None, 'Julia output does not exist')
        content = base64.b64decode(item['content_b64'], validate=True)
        require(len(content) == item['size'] and digest(content) == item['sha256'],
                'Julia bundled output changed')
        return content, item, record

    def output(self, operation_id, node_id, user_id, output_name):
        return self._output(operation_id, node_id, user_id, output_name, revalidate=True)

    def publish(self, publication_id, operation_id, node_id, user_id, output_name,
                artifact_id, title, filename, workspace, expected_head, author_id,
                privacy=None, checkpoint=lambda stage: None,
                author_name='Local workspace author', author_email=None):
        uuid(publication_id); uuid(artifact_id); uuid(author_id); _text(title, 'artifact title')
        _text(author_name, 'author name')
        author_email = author_id + '@local.invalid' if author_email is None else author_email
        _text(author_email, 'author email')
        require(len(safe_path(filename)) == 1 and filename != 'metadata.json',
                'Published filename must be one safe path component')
        content, item, record = self._output(operation_id, node_id, user_id, output_name,
                                             revalidate=False)
        effective = record['request']['privacy']
        privacy = effective if privacy is None else privacy
        require(privacy in PRIVACY and PRIVACY[privacy] >= PRIVACY[effective],
                'Julia output privacy cannot be relaxed')
        request = {'action': 'publish-julia-output', 'run_id': operation_id,
            'request_sha256': record['request_sha256'], 'output_name': output_name,
            'output_sha256': item['sha256'], 'artifact_id': artifact_id,
            'base_head': expected_head, 'privacy': privacy}
        if workspace.receipt(publication_id) is None:
            self._revalidate(record)

        def prepare(ws):
            require(ws.git.head() == expected_head, 'Project changed before Julia publication')
            entities = validate_snapshot(ws.git.snapshot(expected_head))
            require(artifact_id not in entities, 'Artifact ID already exists')
            computation = record['request']['computation']; environment = computation['environment']
            provenance = {'schema': RUN_SCHEMA, 'operation_id': operation_id,
                'computation_id': computation['computation_id'],
                'project_commit': record['project_commit'],
                'request_sha256': record['request_sha256'],
                'parameters_sha256': record['request']['parameters_sha256'],
                'runtime': record['request']['runtime'],
                'environment': {'project_sha256': environment['project_sha256'],
                    'manifest_sha256': environment['manifest_sha256']},
                'output': {'name': output_name, 'sha256': item['sha256'],
                           'media_type': item['media_type'], 'kind': item['kind']},
                'inputs': record['request']['sources']}
            metadata = {'schema_version': 4, 'id': artifact_id, 'title': title,
                'kind': 'snapshot', 'created_at': now(), 'author_id': author_id,
                'privacy': privacy, 'provenance': 'snapshot', 'file': filename,
                'computation': provenance}
            prefix = f'artifacts/{artifact_id}/'
            changes = {prefix + filename: content,
                prefix + 'metadata.json': (json.dumps(metadata, ensure_ascii=False,
                    sort_keys=True, indent=2) + '\n').encode()}
            return changes, author_name, author_email, \
                'Publish Julia computation output'

        return workspace.transact(publication_id, request, prepare,
            expected_head=expected_head, checkpoint=checkpoint)
