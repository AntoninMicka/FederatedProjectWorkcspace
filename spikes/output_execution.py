# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Durable fail-closed execution of reviewed output composition plans."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile

from spikes.metadata import MAX_METADATA, parse_json, require, safe_path, timestamp, uuid
from spikes.output_capabilities import canonical_output_capability
from spikes.output_plans import (canonical_output_plan, canonical_output_policy,
                                 validate_output_plan)
from spikes.output_renderers import REVIEWED_RENDERERS, RENDERER_REVISION


PLAN_STATES = {'prepared', 'running', 'completed', 'failed', 'unknown'}
STEP_STATES = {'pending', 'dispatching', 'completed', 'failed', 'unknown', 'blocked'}
MAX_PREVIEW_TEXT = 8192
MAX_MATERIALIZATION = 64 * 1024 * 1024


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


class OutputExecutionStore:
    """Node-local execution authority; materialized bytes live separately."""

    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Output execution state directory requires owned mode 0700')
        self.path = self.root / 'output-executions.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe output execution journal')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if not tables:
                db.executescript('''
                    CREATE TABLE schema_info(version INTEGER NOT NULL);
                    INSERT INTO schema_info VALUES(1);
                    CREATE TABLE executions(
                        operation_id TEXT PRIMARY KEY,
                        node_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        project_id TEXT NOT NULL,
                        project_commit TEXT NOT NULL,
                        request_digest TEXT NOT NULL,
                        request_json BLOB NOT NULL,
                        preview_json BLOB NOT NULL,
                        approval_digest TEXT NOT NULL,
                        state TEXT NOT NULL CHECK(state IN
                            ('prepared','running','completed','failed','unknown')),
                        error TEXT,
                        receipt_json BLOB);
                    CREATE TABLE execution_steps(
                        operation_id TEXT NOT NULL,
                        ordinal INTEGER NOT NULL,
                        step_id TEXT NOT NULL UNIQUE,
                        state TEXT NOT NULL CHECK(state IN
                            ('pending','dispatching','completed','failed','unknown','blocked')),
                        manifest_json BLOB,
                        manifest_sha256 TEXT,
                        output_sha256 TEXT,
                        output_size INTEGER,
                        generation_path TEXT,
                        receipt_json BLOB,
                        error TEXT,
                        PRIMARY KEY(operation_id,ordinal),
                        FOREIGN KEY(operation_id) REFERENCES executions(operation_id));
                ''')
            else:
                require(tables == {'schema_info', 'executions', 'execution_steps'},
                        'Unknown or incomplete output execution schema')
                require(db.execute('SELECT version FROM schema_info').fetchall() == [(1,)],
                        'Unsupported output execution schema version')
                require([row[1] for row in db.execute('PRAGMA table_info(executions)')] ==
                    ['operation_id', 'node_id', 'user_id', 'project_id',
                     'project_commit', 'request_digest', 'request_json', 'preview_json',
                     'approval_digest', 'state', 'error', 'receipt_json']
                    and [row[1] for row in db.execute(
                        'PRAGMA table_info(execution_steps)')] ==
                    ['operation_id', 'ordinal', 'step_id', 'state', 'manifest_json',
                     'manifest_sha256', 'output_sha256', 'output_size',
                     'generation_path', 'receipt_json', 'error'],
                    'Unknown or incomplete output execution schema')
            db.commit()
            return closing(db)
        except Exception:
            db.close(); raise

    @staticmethod
    def _owner(row, node_id, user_id):
        require(row is not None and row[0] == node_id and row[1] == user_id,
                'Output execution is unavailable to this owner')

    def prepare(self, request, preview, approval_digest, node_id, user_id):
        operation_id = request['operation_id']
        for value in (operation_id, node_id, user_id, request['plan']['project_id']):
            uuid(value)
        request_raw, preview_raw = canonical(request), canonical(preview)
        request_digest = digest(request_raw)
        require(approval_digest == digest(request_raw + b'\0' + preview_raw),
                'Invalid output execution approval digest')
        steps = request['plan']['steps']
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,request_digest,request_json,'
                             'preview_json,approval_digest FROM executions WHERE operation_id=?',
                             (operation_id,)).fetchone()
            expected = (node_id, user_id, request_digest, request_raw,
                        preview_raw, approval_digest)
            if row:
                self._owner(row, node_id, user_id)
                require(row == expected, 'Operation ID belongs to a different execution')
            else:
                db.execute('INSERT INTO executions VALUES(?,?,?,?,?,?,?,?,?,?,'
                           'NULL,NULL)', (operation_id, node_id, user_id,
                           request['plan']['project_id'], request['plan']['project_commit'],
                           request_digest, request_raw, preview_raw, approval_digest,
                           'prepared'))
                db.executemany('INSERT INTO execution_steps VALUES(?,?,?,?,NULL,NULL,NULL,'
                               'NULL,NULL,NULL,NULL)',
                    [(operation_id, ordinal, step['step_id'], 'pending')
                     for ordinal, step in enumerate(steps, 1)])
            db.commit()
        return self.get(operation_id, node_id, user_id)

    def begin_step(self, operation_id, step_id, node_id, user_id, manifest):
        manifest_raw = canonical(manifest); manifest_hash = digest(manifest_raw)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT e.node_id,e.user_id,e.state,s.state,s.manifest_json,'
                's.manifest_sha256 FROM executions e JOIN execution_steps s '
                'ON s.operation_id=e.operation_id WHERE e.operation_id=? AND s.step_id=?',
                (operation_id, step_id)).fetchone()
            self._owner(row, node_id, user_id)
            if row[3] == 'pending':
                require(row[2] in {'prepared', 'running'}, 'Execution cannot start a step')
                db.execute("UPDATE executions SET state='running' WHERE operation_id=?",
                           (operation_id,))
                db.execute("UPDATE execution_steps SET state='dispatching',manifest_json=?,"
                           'manifest_sha256=? WHERE operation_id=? AND step_id=?',
                           (manifest_raw, manifest_hash, operation_id, step_id))
            else:
                require(row[3] == 'dispatching' and row[4:] == (manifest_raw, manifest_hash),
                        'Output step is not safely dispatchable')
            db.commit()
        return manifest_hash

    def complete_step(self, operation_id, step_id, node_id, user_id, receipt):
        receipt_raw = canonical(receipt)
        require(receipt.get('operation_id') == operation_id
                and receipt.get('step_id') == step_id,
                'Materialization receipt belongs to another execution step')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT e.node_id,e.user_id,s.state,s.manifest_sha256,'
                's.receipt_json FROM executions e JOIN execution_steps s '
                'ON s.operation_id=e.operation_id WHERE e.operation_id=? AND s.step_id=?',
                (operation_id, step_id)).fetchone()
            self._owner(row, node_id, user_id)
            require(receipt['manifest_sha256'] == row[3],
                    'Materialization receipt belongs to another manifest')
            if row[2] == 'dispatching':
                db.execute("UPDATE execution_steps SET state='completed',output_sha256=?,"
                    'output_size=?,generation_path=?,receipt_json=? '
                    'WHERE operation_id=? AND step_id=?',
                    (receipt['output_sha256'], receipt['output_size'],
                     receipt['generation_path'], receipt_raw, operation_id, step_id))
            else:
                require(row[2] == 'completed' and row[4] == receipt_raw,
                        'Completed output step differs from durable receipt')
            db.commit()

    def finish(self, operation_id, node_id, user_id, state, error=None, receipt=None):
        require(state in {'completed', 'failed', 'unknown'},
                'Invalid output execution terminal state')
        require((error is None) == (state == 'completed'),
                'Output execution terminal error is inconsistent')
        if error is not None:
            require(isinstance(error, str) and 0 < len(error.encode()) <= 4096,
                    'Invalid output execution error')
        receipt_raw = canonical(receipt) if receipt is not None else None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT node_id,user_id,state,error,receipt_json '
                             'FROM executions WHERE operation_id=?',
                             (operation_id,)).fetchone()
            self._owner(row, node_id, user_id)
            if row[2] in {'prepared', 'running'}:
                db.execute('UPDATE executions SET state=?,error=?,receipt_json=? '
                           'WHERE operation_id=?',
                           (state, error, receipt_raw, operation_id))
            else:
                require(row[2:] == (state, error, receipt_raw),
                        'Execution differs from durable terminal result')
            db.commit()

    def mark_step(self, operation_id, step_id, node_id, user_id, state, error):
        require(state in {'failed', 'unknown', 'blocked'} and isinstance(error, str)
                and 0 < len(error.encode()) <= 4096, 'Invalid output step failure')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT e.node_id,e.user_id,s.state,s.error '
                'FROM executions e JOIN execution_steps s ON s.operation_id=e.operation_id '
                'WHERE e.operation_id=? AND s.step_id=?',
                (operation_id, step_id)).fetchone()
            self._owner(row, node_id, user_id)
            if row[2] in {'pending', 'dispatching'}:
                db.execute('UPDATE execution_steps SET state=?,error=? '
                           'WHERE operation_id=? AND step_id=?',
                           (state, error, operation_id, step_id))
            else:
                require(row[2:] == (state, error), 'Output step failure differs')
            db.commit()

    def get(self, operation_id, node_id, user_id):
        uuid(operation_id); uuid(node_id); uuid(user_id)
        with self.connect() as db:
            execution = db.execute('SELECT node_id,user_id,project_id,project_commit,'
                'request_digest,request_json,preview_json,approval_digest,state,error,'
                'receipt_json FROM executions WHERE operation_id=?',
                (operation_id,)).fetchone()
            self._owner(execution, node_id, user_id)
            rows = db.execute('SELECT ordinal,step_id,state,manifest_json,manifest_sha256,'
                'output_sha256,output_size,generation_path,receipt_json,error '
                'FROM execution_steps WHERE operation_id=? ORDER BY ordinal',
                (operation_id,)).fetchall()
        request, preview = json.loads(execution[5]), json.loads(execution[6])
        require(canonical(request) == execution[5]
                and digest(execution[5]) == execution[4]
                and canonical(preview) == execution[6]
                and digest(execution[5] + b'\0' + execution[6]) == execution[7],
                'Stored output execution request or preview changed')
        require(execution[8] in PLAN_STATES, 'Invalid stored execution state')
        steps = []
        for row in rows:
            require(row[2] in STEP_STATES, 'Invalid stored output step state')
            manifest = json.loads(row[3]) if row[3] is not None else None
            receipt = json.loads(row[8]) if row[8] is not None else None
            if manifest is None:
                require(row[2] in {'pending', 'blocked'} and row[4] is None,
                        'Non-dispatched output step contains a manifest')
            else:
                require(canonical(manifest) == row[3] and digest(row[3]) == row[4],
                        'Stored output step manifest changed')
            if receipt is not None:
                require(row[2] == 'completed' and canonical(receipt) == row[8]
                        and (receipt['output_sha256'], receipt['output_size'],
                             receipt['generation_path']) == row[5:8],
                        'Stored materialization receipt changed')
            keys = ('ordinal', 'step_id', 'state', 'manifest', 'manifest_sha256',
                    'output_sha256', 'output_size', 'generation_path', 'receipt', 'error')
            steps.append(dict(zip(keys, row[:3] + (manifest,) + row[4:8]
                                  + (receipt, row[9]))))
        receipt = json.loads(execution[10]) if execution[10] is not None else None
        if receipt is not None:
            require(execution[8] == 'completed' and canonical(receipt) == execution[10],
                    'Stored execution receipt changed')
        return {'operation_id': operation_id, 'node_id': execution[0],
                'user_id': execution[1], 'project_id': execution[2],
                'project_commit': execution[3], 'request_digest': execution[4],
                'request': request, 'preview': preview, 'approval_digest': execution[7],
                'state': execution[8], 'error': execution[9], 'receipt': receipt,
                'steps': steps}


class MaterializationCache:
    """Immutable complete generations under a private node-local directory."""

    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute() / 'output-materializations'
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700 and not self.root.is_symlink(),
                'Unsafe output materialization directory')

    def _path(self, operation_id, step_id):
        uuid(operation_id); uuid(step_id)
        return self.root / operation_id / step_id

    def _reference_path(self, plan_id, step_id, output_sha256):
        uuid(plan_id); uuid(step_id)
        require(isinstance(output_sha256, str) and len(output_sha256) == 64
                and all(char in '0123456789abcdef' for char in output_sha256),
                'Invalid materialization output hash')
        return self.root / 'by-plan' / plan_id / step_id / f'{output_sha256}.json'

    def _publish_reference(self, receipt):
        reference = self._reference_path(receipt['plan_id'], receipt['step_id'],
                                         receipt['output_sha256'])
        current = self.root / 'by-plan'
        for part in (receipt['plan_id'], receipt['step_id']):
            current.mkdir(mode=0o700, exist_ok=True)
            info = current.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                    and stat.S_IMODE(info.st_mode) == 0o700,
                    'Unsafe materialization reference directory')
            current = current / part
        current.mkdir(mode=0o700, exist_ok=True)
        info = current.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Unsafe materialization reference directory')
        raw = canonical(receipt)
        if reference.exists():
            require(reference.is_file() and not reference.is_symlink()
                    and reference.read_bytes() == raw,
                    'Materialization provenance reference conflicts')
            return
        fd, temporary = tempfile.mkstemp(prefix='.reference-', dir=reference.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'wb') as handle:
                handle.write(raw); handle.flush(); os.fsync(handle.fileno())
            os.replace(temporary, reference)
            parent_fd = os.open(reference.parent, os.O_RDONLY | os.O_DIRECTORY)
            os.fsync(parent_fd); os.close(parent_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def publish(self, operation_id, step_id, output, receipt):
        require(isinstance(output, bytes), 'Materialized output must be bytes')
        require(len(output) <= MAX_MATERIALIZATION, 'Materialized output exceeds cache limit')
        target = self._path(operation_id, step_id)
        target.parent.mkdir(mode=0o700, exist_ok=True)
        parent_info = target.parent.lstat()
        require(stat.S_ISDIR(parent_info.st_mode) and parent_info.st_uid == os.getuid()
                and stat.S_IMODE(parent_info.st_mode) == 0o700,
                'Unsafe output operation directory')
        if target.exists():
            _, existing = self.load_generation(operation_id, step_id)
            require(all(existing[key] == receipt[key] for key in receipt),
                    'Existing materialization belongs to another result')
            self._publish_reference(existing)
            return existing
        staging = Path(tempfile.mkdtemp(prefix='.output-', dir=target.parent))
        try:
            os.chmod(staging, 0o700)
            receipt = dict(receipt, generation_path=f'{operation_id}/{step_id}')
            (staging / 'output.bin').write_bytes(output)
            (staging / 'receipt.json').write_bytes(canonical(receipt))
            for path in (staging / 'output.bin', staging / 'receipt.json'):
                os.chmod(path, 0o600)
                with path.open('rb') as handle:
                    os.fsync(handle.fileno())
            fd = os.open(staging, os.O_RDONLY | os.O_DIRECTORY); os.fsync(fd); os.close(fd)
            os.replace(staging, target)
            fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY); os.fsync(fd); os.close(fd)
            self._publish_reference(receipt)
            return receipt
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def load_generation(self, operation_id, step_id):
        path = self._path(operation_id, step_id)
        require(path.is_dir() and not path.is_symlink(), 'Materialization is missing')
        entries = {item.name for item in path.iterdir()}
        require(entries == {'output.bin', 'receipt.json'},
                'Materialization generation is incomplete')
        for name in entries:
            info = (path / name).lstat()
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and not info.st_mode & 0o077 and info.st_nlink == 1,
                    'Unsafe materialization generation file')
        require((path / 'output.bin').stat().st_size <= MAX_MATERIALIZATION
                and (path / 'receipt.json').stat().st_size <= MAX_METADATA,
                'Materialization generation exceeds limits')
        output = (path / 'output.bin').read_bytes()
        receipt_raw = (path / 'receipt.json').read_bytes()
        receipt = parse_json(receipt_raw)
        require(receipt.keys() == {'schema_version', 'operation_id', 'plan_id',
                'plan_sha256', 'step_id', 'manifest_sha256', 'output_port',
                'output_sha256', 'output_size', 'contract', 'completed_at',
                'generation_path'}
                and receipt['schema_version'] == 1
                and receipt['contract'].keys() ==
                    {'schema', 'mime_type', 'format', 'privacy'}
                and canonical(receipt) == receipt_raw
                and receipt['generation_path'] == f'{operation_id}/{step_id}'
                and receipt['operation_id'] == operation_id
                and receipt['step_id'] == step_id
                and receipt['output_sha256'] == digest(output)
                and receipt['output_size'] == len(output),
                'Materialization generation differs from its receipt')
        timestamp(receipt['completed_at'], 'completed_at')
        return output, receipt

    def load_source(self, source):
        reference = self._reference_path(source['producer_plan_id'],
                                         source['producer_step_id'], source['sha256'])
        require(reference.is_file() and not reference.is_symlink(),
                'Trusted materialization reference is missing')
        info = reference.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and not info.st_mode & 0o077 and info.st_nlink == 1
                and info.st_size <= MAX_METADATA,
                'Unsafe materialization reference')
        raw = reference.read_bytes(); receipt = parse_json(raw)
        require(canonical(receipt) == raw, 'Materialization reference is not canonical')
        parts = receipt['generation_path'].split('/')
        require(len(parts) == 2, 'Invalid materialization generation reference')
        output, stored = self.load_generation(parts[0], parts[1])
        require(stored == receipt, 'Materialization reference differs from generation')
        require(receipt['plan_id'] == source['producer_plan_id']
                and receipt['plan_sha256'] == source['producer_plan_sha256']
                and receipt['step_id'] == source['producer_step_id']
                and receipt['output_port'] == source['producer_output_port']
                and receipt['output_sha256'] == source['sha256']
                and receipt['output_size'] == source['size']
                and receipt['contract'] == {
                    'schema': source['schema'], 'mime_type': source['mime_type'],
                    'format': source['format'], 'privacy': source['privacy']},
                'Trusted materialization reference differs from its receipt')
        return output


class OutputExecutor:
    def __init__(self, *, git, state_dir, catalog, policy, renderers=None):
        self.git = git
        self.store = OutputExecutionStore(state_dir)
        self.cache = MaterializationCache(state_dir)
        self.catalog = catalog
        self.policy = json.loads(canonical_output_policy(policy))
        self.renderers = dict(REVIEWED_RENDERERS if renderers is None else renderers)

    def _artifact(self, source):
        require(self.git.head() == source['project_commit'],
                'Project changed before output execution')
        safe_path(source['path'])
        row = self.git.run('ls-tree', source['project_commit'], '--', source['path']).stdout
        lines = [line for line in row.splitlines() if line]
        require(len(lines) == 1, 'Output artifact is missing from the pinned commit')
        info, path = lines[0].split('\t', 1)
        mode, kind, oid = info.split()
        require(path == source['path'] and mode in {'100644', '100755'}
                and kind == 'blob' and oid == source['blob_id'],
                'Output artifact blob differs from the plan')
        raw = self.git.run('cat-file', 'blob', oid, binary=True).stdout
        require(len(raw) == source['size'] and digest(raw) == source['sha256'],
                'Output artifact bytes differ from the plan')
        require(self.git.head() == source['project_commit'],
                'Project changed while reading output input')
        return raw

    def _initial_sources(self, plan):
        values = {}
        for source in plan['artifacts']:
            values[source['source_id']] = self._artifact(source)
        for source in plan['materialized']:
            values[source['source_id']] = self.cache.load_source(source)
        return values

    def _request(self, operation_id, plan):
        capability_hashes = []
        for step in plan['steps']:
            descriptor = self.catalog.resolve(step['capability']['id'],
                                              step['capability']['version'])
            capability_hashes.append({
                'step_id': step['step_id'],
                'sha256': digest(canonical_output_capability(descriptor)),
            })
        return {'schema_version': 1, 'operation_id': operation_id, 'plan': plan,
                'plan_sha256': digest(canonical_output_plan(plan, self.catalog, self.policy)),
                'policy_sha256': digest(canonical_output_policy(self.policy)),
                'capability_sha256': capability_hashes}

    def prepare(self, operation_id, node_id, user_id, plan):
        plan = validate_output_plan(canonical(plan), self.catalog, self.policy)
        require(self.git.head() == plan['project_commit'],
                'Project changed before output preview')
        sources = self._initial_sources(plan)
        preview_sources = []
        source_by_id = {item['source_id']: item
                        for item in plan['artifacts'] + plan['materialized']}
        for source_id in sorted(sources):
            raw = sources[source_id]; source = source_by_id[source_id]
            text = None
            if source['mime_type'] == 'text/markdown':
                try:
                    text = raw[:MAX_PREVIEW_TEXT].decode('utf-8')
                except UnicodeError:
                    text = None
            preview_sources.append({'source_id': source_id, 'sha256': digest(raw),
                'size': len(raw), 'privacy': source['privacy'], 'text': text,
                'truncated': len(raw) > MAX_PREVIEW_TEXT})
        preview = {'schema_version': 1, 'plan_id': plan['plan_id'],
                   'project_commit': plan['project_commit'], 'privacy': plan['privacy'],
                   'steps': [{'step_id': step['step_id'],
                              'capability': step['capability'],
                              'confirmation': 'before-execution'}
                             for step in plan['steps']],
                   'sources': preview_sources,
                   'effects': ['local-materialization'],
                   'not_included': ['project-write', 'publication', 'external-effect']}
        request = self._request(operation_id, plan)
        approval = digest(canonical(request) + b'\0' + canonical(preview))
        return self.store.prepare(request, preview, approval, node_id, user_id)

    @staticmethod
    def _order(plan):
        outgoing = {step['step_id']: [] for step in plan['steps']}
        indegree = {step['step_id']: 0 for step in plan['steps']}
        for edge in plan['edges']:
            outgoing[edge['from_step_id']].append(edge['to_step_id'])
            indegree[edge['to_step_id']] += 1
        ready = sorted(key for key, value in indegree.items() if value == 0)
        result = []
        while ready:
            step_id = ready.pop(0); result.append(step_id)
            for target in sorted(outgoing[step_id]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    ready.append(target); ready.sort()
        return result

    def execute(self, operation_id, node_id, user_id, approval_digest,
                checkpoint=lambda stage: None):
        record = self.store.get(operation_id, node_id, user_id)
        require(record['state'] in {'prepared', 'running'},
                'Output execution is already terminal')
        require(approval_digest == record['approval_digest'],
                'Output execution confirmation differs from preview')
        plan = validate_output_plan(canonical(record['request']['plan']),
                                    self.catalog, self.policy)
        require(self._request(operation_id, plan) == record['request'],
                'Output execution contract changed after preview')
        initial = self._initial_sources(plan)
        steps = {step['step_id']: step for step in plan['steps']}
        edges = {edge['edge_id']: edge for edge in plan['edges']}
        outputs = {}
        for durable in record['steps']:
            if durable['state'] == 'completed':
                output, receipt = self.cache.load_generation(operation_id,
                                                             durable['step_id'])
                require(receipt == durable['receipt'],
                        'Durable step and materialization differ')
                outputs[durable['step_id']] = output
            elif durable['state'] == 'dispatching':
                raise RuntimeError('Reconcile interrupted dispatch before continuing')
            elif durable['state'] in {'failed', 'unknown', 'blocked'}:
                raise RuntimeError('Output plan contains a terminal non-success step')
        for step_id in self._order(plan):
            if step_id in outputs:
                continue
            fresh = self._initial_sources(plan)
            require({key: digest(value) for key, value in fresh.items()} ==
                    {key: digest(value) for key, value in initial.items()},
                    'Output inputs changed before step dispatch')
            step = steps[step_id]
            descriptor = self.catalog.resolve(step['capability']['id'],
                                              step['capability']['version'])
            handler = self.renderers.get((descriptor['capability_id'],
                                          descriptor['capability_version']))
            if handler is None:
                error = 'No reviewed runtime adapter for exact capability version'
                self.store.mark_step(operation_id, step_id, node_id, user_id,
                                     'failed', error)
                self._block_pending(operation_id, node_id, user_id, error)
                self.store.finish(operation_id, node_id, user_id, 'failed', error)
                raise RuntimeError(error)
            inputs, input_evidence = [], []
            for binding in step['inputs']:
                if binding['source_type'] == 'edge':
                    edge = edges[binding['source_id']]
                    raw = outputs[edge['from_step_id']]
                else:
                    raw = initial[binding['source_id']]
                inputs.append(raw)
                input_evidence.append({'input_port': binding['input_port'],
                    'source_type': binding['source_type'], 'source_id': binding['source_id'],
                    'sha256': digest(raw), 'size': len(raw)})
            manifest = {'schema_version': 1, 'manifest_id': step_id,
                'operation_id': operation_id, 'plan_id': plan['plan_id'],
                'plan_sha256': record['request']['plan_sha256'],
                'project_id': plan['project_id'], 'project_commit': plan['project_commit'],
                'step_id': step_id, 'capability': step['capability'],
                'capability_sha256': digest(canonical_output_capability(descriptor)),
                'policy_sha256': record['request']['policy_sha256'],
                'privacy': step['privacy'], 'approval_digest': approval_digest,
                'inputs': input_evidence, 'renderer_revision': RENDERER_REVISION}
            manifest_hash = self.store.begin_step(operation_id, step_id, node_id,
                                                  user_id, manifest)
            checkpoint('step-dispatching')
            try:
                output = handler(inputs, descriptor)
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                self.store.mark_step(operation_id, step_id, node_id, user_id,
                                     'failed', error)
                self._block_pending(operation_id, node_id, user_id,
                                    f'Blocked by {step_id}: {error}')
                self.store.finish(operation_id, node_id, user_id, 'failed', error)
                raise
            receipt = {'schema_version': 1, 'operation_id': operation_id,
                'plan_id': plan['plan_id'],
                'plan_sha256': record['request']['plan_sha256'],
                'step_id': step_id, 'manifest_sha256': manifest_hash,
                'output_port': descriptor['output']['port_id'],
                'output_sha256': digest(output), 'output_size': len(output),
                'contract': {'schema': descriptor['output']['schema'],
                    'mime_type': descriptor['output']['mime_types'][0],
                    'format': descriptor['output']['format'],
                    'privacy': step['privacy']}, 'completed_at': now()}
            receipt = self.cache.publish(operation_id, step_id, output, receipt)
            checkpoint('materialization-published')
            self.store.complete_step(operation_id, step_id, node_id, user_id, receipt)
            outputs[step_id] = output
        receipts = [self.cache.load_generation(operation_id, step_id)[1]
                    for step_id in self._order(plan)]
        result = {'schema_version': 1, 'operation_id': operation_id,
                  'plan_id': plan['plan_id'], 'plan_sha256': record['request']['plan_sha256'],
                  'completed_at': now(), 'steps': receipts}
        self.store.finish(operation_id, node_id, user_id, 'completed', receipt=result)
        return self.store.get(operation_id, node_id, user_id)

    def _block_pending(self, operation_id, node_id, user_id, error):
        record = self.store.get(operation_id, node_id, user_id)
        for step in record['steps']:
            if step['state'] == 'pending':
                self.store.mark_step(operation_id, step['step_id'], node_id, user_id,
                                     'blocked', error)

    def reconcile(self, operation_id, node_id, user_id):
        """Adopt an exact published generation or mark dispatch as unknown."""
        record = self.store.get(operation_id, node_id, user_id)
        dispatching = [step for step in record['steps'] if step['state'] == 'dispatching']
        require(len(dispatching) == 1 and record['state'] == 'running',
                'Execution has no single interrupted dispatch to reconcile')
        step = dispatching[0]
        try:
            _, receipt = self.cache.load_generation(operation_id, step['step_id'])
            require(receipt['manifest_sha256'] == step['manifest_sha256'],
                    'Published generation belongs to another manifest')
            self.cache._publish_reference(receipt)
        except Exception as exc:
            error = f'Interrupted dispatch could not be proven complete: {exc}'
            self.store.mark_step(operation_id, step['step_id'], node_id, user_id,
                                 'unknown', error)
            self._block_pending(operation_id, node_id, user_id, error)
            self.store.finish(operation_id, node_id, user_id, 'unknown', error)
            return self.store.get(operation_id, node_id, user_id)
        self.store.complete_step(operation_id, step['step_id'], node_id, user_id, receipt)
        return self.store.get(operation_id, node_id, user_id)
