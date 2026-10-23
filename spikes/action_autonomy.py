# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed action registry and durable opt-in orchestration queue."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat

from spikes.metadata import parse_json, require, uuid


MAX_ACTIONS = 64
MAX_STEPS = 32
MAX_JSON = 1024 * 1024
UI_LEASE_SECONDS = 15
IDENTIFIER = re.compile(r'[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*')
INPUT_IDENTIFIER = re.compile(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*')
VERSION = re.compile(r'[0-9]+\.[0-9]+')
HASH = re.compile(r'[0-9a-f]{64}')
GIT_HEAD = re.compile(r'[0-9a-f]{40,64}')
PRIVACY = {'public', 'project', 'confidential', 'local-only'}
EFFECTS = {'read-only', 'external-request', 'role-handoff', 'local-content-create'}
CONFIRMATIONS = {'none', 'before-dispatch', 'exact-local-output'}
MODES = {'manual', 'automatic'}
REVIEWED_ACTIONS = Path(__file__).resolve().parents[1] / 'modules' / 'orchestration-actions'


def canonical(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode()
    require(len(raw) <= MAX_JSON, 'Autonomy value exceeds 1 MiB')
    return raw


def digest(value):
    raw = value if isinstance(value, bytes) else canonical(value)
    return hashlib.sha256(raw).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _fields(value, expected, name):
    require(isinstance(value, dict) and set(value) == expected,
            f'Unknown or missing autonomy {name} field')


def _identifier(value, field):
    require(isinstance(value, str) and bool(IDENTIFIER.fullmatch(value)),
            f'Invalid autonomy {field}')


def _identifiers(value, field, *, allow_empty=False):
    require(isinstance(value, list) and len(value) <= 32
            and (allow_empty or bool(value)), f'Invalid autonomy {field}')
    for item in value:
        _identifier(item, field)
    require(len(value) == len(set(value)), f'Duplicate autonomy {field}')


def _input_identifiers(value):
    require(isinstance(value, list) and len(value) <= 32,
            'Invalid autonomy required input')
    require(all(isinstance(item, str) and INPUT_IDENTIFIER.fullmatch(item)
                for item in value), 'Invalid autonomy required input')
    require(len(value) == len(set(value)), 'Duplicate autonomy required input')


def parse_action_descriptor(data):
    value = parse_json(data)
    _fields(value, {'schema_version', 'action_id', 'version', 'display_name',
                    'effect', 'permissions', 'privacy', 'required_inputs',
                    'max_cost_units', 'automatable', 'confirmation'},
            'action descriptor')
    require(value['schema_version'] == 1 and type(value['schema_version']) is int,
            'Unsupported autonomy action schema')
    _identifier(value['action_id'], 'action ID')
    require(isinstance(value['version'], str) and VERSION.fullmatch(value['version']),
            'Invalid autonomy action version')
    require(isinstance(value['display_name'], str)
            and value['display_name'].strip() == value['display_name']
            and 0 < len(value['display_name']) <= 128,
            'Invalid autonomy action display name')
    require(value['effect'] in EFFECTS, 'Unsupported autonomy action effect')
    _identifiers(value['permissions'], 'permission', allow_empty=True)
    _identifiers(value['privacy'], 'privacy class')
    require(set(value['privacy']) <= PRIVACY, 'Unsupported autonomy privacy class')
    _input_identifiers(value['required_inputs'])
    require(type(value['max_cost_units']) is int
            and 0 <= value['max_cost_units'] <= 1_000_000,
            'Invalid autonomy action cost')
    require(type(value['automatable']) is bool,
            'Autonomy action automatable must be boolean')
    require(value['confirmation'] in CONFIRMATIONS,
            'Unsupported autonomy confirmation')
    require(value['automatable'] or value['confirmation'] != 'none',
            'Manual-only action requires confirmation')
    require(value['effect'] != 'local-content-create'
            or value['confirmation'] == 'exact-local-output',
            'Local content creation requires exact output confirmation')
    return value


class ActionRegistry:
    def __init__(self, descriptors):
        require(isinstance(descriptors, list)
                and 0 < len(descriptors) <= MAX_ACTIONS,
                'Invalid autonomy action registry')
        self._actions = {}
        for descriptor in descriptors:
            parsed = parse_action_descriptor(canonical(descriptor))
            key = (parsed['action_id'], parsed['version'])
            require(key not in self._actions, 'Duplicate autonomy action')
            self._actions[key] = parsed

    def resolve(self, action_id, version):
        value = self._actions.get((action_id, version))
        require(value is not None, 'Unsupported autonomy action or version')
        return deepcopy(value)

    def list(self):
        return [deepcopy(self._actions[key]) for key in sorted(self._actions)]


def load_action_registry(directory=REVIEWED_ACTIONS):
    root = Path(directory)
    require(root.is_dir() and not root.is_symlink(),
            'Autonomy action registry must be a regular directory')
    entries = sorted(root.iterdir(), key=lambda item: item.name)
    require(0 < len(entries) <= MAX_ACTIONS, 'Invalid autonomy action registry')
    descriptors = []
    for path in entries:
        require(path.name.endswith('.action.json'),
                'Unexpected autonomy action registry entry')
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode),
                'Autonomy action descriptor must be a regular file')
        descriptors.append(parse_action_descriptor(path.read_bytes()))
    return ActionRegistry(descriptors)


def parse_plan(value, registry, *, allow_materialized=False):
    require(isinstance(value, dict) and type(value.get('schema_version')) is int,
            'Unsupported autonomy plan schema')
    version = value['schema_version']
    fields = {'schema_version', 'workflow_id', 'project_id', 'expected_head',
              'mode', 'privacy', 'budget', 'steps'}
    if version == 2:
        fields |= {'countdown_seconds', 'continuation'}
    _fields(value, fields, 'plan')
    require(version in {1, 2}, 'Unsupported autonomy plan schema')
    uuid(value['workflow_id']); uuid(value['project_id'])
    require(isinstance(value['expected_head'], str)
            and bool(GIT_HEAD.fullmatch(value['expected_head'])),
            'Invalid autonomy expected HEAD')
    require(value['mode'] in MODES, 'Unsupported autonomy mode')
    require(value['privacy'] in PRIVACY, 'Unsupported autonomy plan privacy')
    _fields(value['budget'], {'max_steps', 'max_cost_units', 'max_seconds'}, 'budget')
    budget = value['budget']
    require(type(budget['max_steps']) is int and 1 <= budget['max_steps'] <= MAX_STEPS,
            'Invalid autonomy step budget')
    require(type(budget['max_cost_units']) is int
            and 0 <= budget['max_cost_units'] <= 10_000_000,
            'Invalid autonomy cost budget')
    require(type(budget['max_seconds']) is int
            and 1 <= budget['max_seconds'] <= 86_400,
            'Invalid autonomy time budget')
    require(isinstance(value['steps'], list)
            and 0 < len(value['steps']) <= budget['max_steps'],
            'Invalid autonomy plan steps')
    seen = set(); cost = 0
    for step in value['steps']:
        _fields(step, {'step_id', 'action', 'privacy', 'cost_units',
                       'depends_on', 'input'}, 'step')
        uuid(step['step_id'])
        require(step['step_id'] not in seen, 'Duplicate autonomy step ID')
        _fields(step['action'], {'id', 'version'}, 'step action')
        descriptor = registry.resolve(step['action']['id'], step['action']['version'])
        require(step['privacy'] in descriptor['privacy']
                and PRIVACY_ORDER[step['privacy']] >= PRIVACY_ORDER[value['privacy']],
                'Autonomy step weakens privacy')
        require(type(step['cost_units']) is int
                and 0 <= step['cost_units'] <= descriptor['max_cost_units'],
                'Autonomy step exceeds action cost')
        cost += step['cost_units']
        require(isinstance(step['depends_on'], list)
                and len(step['depends_on']) == len(set(step['depends_on']))
                and set(step['depends_on']) <= seen,
                'Autonomy dependencies must reference earlier steps')
        require(isinstance(step['input'], dict)
                and set(step['input']) == set(descriptor['required_inputs']),
                'Autonomy action inputs differ from registry')
        canonical(step['input'])
        if descriptor['effect'] == 'local-content-create':
            _validate_local_output(step['input'])
        if descriptor['action_id'] == 'search.iterative-query':
            _validate_search_input(step['input'])
        seen.add(step['step_id'])
    require(cost <= budget['max_cost_units'], 'Autonomy plan exceeds cost budget')
    if version == 2:
        require(type(value['countdown_seconds']) is int
                and 3 <= value['countdown_seconds'] <= 5,
                'Search autonomy countdown must be 3 to 5 seconds')
        continuation = value['continuation']
        _fields(continuation, {'kind', 'task_id', 'action', 'follow_up_policy'},
                'continuation')
        require(continuation['kind'] == 'iterative-search-v1'
                and continuation['follow_up_policy'] == 'first-proposed-v1',
                'Unsupported autonomy continuation policy')
        uuid(continuation['task_id'])
        _fields(continuation['action'], {'id', 'version'}, 'continuation action')
        require(continuation['action'] == {
            'id': 'search.iterative-query', 'version': '1.0'},
            'Unsupported autonomy continuation action')
        require(value['privacy'] != 'local-only'
                and budget['max_steps'] <= 3
                and (allow_materialized or len(value['steps']) == 1),
                'Invalid iterative search autonomy envelope')
        for step in value['steps']:
            require(step['action'] == continuation['action']
                    and step['input'].get('request', {}).get('task_id')
                    == continuation['task_id'],
                    'Search step differs from activated continuation')
    canonical(value)
    return deepcopy(value)


PRIVACY_ORDER = {'public': 0, 'project': 1, 'confidential': 2, 'local-only': 3}


def _validate_local_output(value):
    require(set(value) == {'target', 'content_type', 'content_sha256',
                           'privacy', 'provenance', 'request'},
            'Local output approval requires exact output fields')
    require(isinstance(value['target'], str) and value['target'].strip() == value['target']
            and 0 < len(value['target']) <= 512 and '\0' not in value['target'],
            'Invalid local output target')
    require(isinstance(value['content_type'], str)
            and 0 < len(value['content_type']) <= 128,
            'Invalid local output type')
    require(isinstance(value['content_sha256'], str)
            and bool(HASH.fullmatch(value['content_sha256'])),
            'Invalid local output hash')
    require(value['privacy'] in PRIVACY, 'Invalid local output privacy')
    require(isinstance(value['provenance'], dict) and bool(value['provenance']),
            'Local output provenance is required')
    canonical(value['provenance'])
    require(isinstance(value['request'], dict) and bool(value['request']),
            'Local output domain request is required')
    canonical(value['request'])


def _validate_search_input(value):
    require(set(value) == {'request', 'preview', 'preview_sha256'},
            'Iterative search action requires exact input fields')
    request = value['request']; preview = value['preview']
    root = {'task_id', 'search_id', 'synthesis_run_id', 'synthesis_manifest_id'}
    follow_up = root | {'parent_search_id', 'query'}
    require(isinstance(request, dict) and set(request) in (root, follow_up),
            'Invalid iterative search action request')
    for key in root: uuid(request[key])
    if set(request) == follow_up:
        uuid(request['parent_search_id'])
        require(isinstance(request['query'], str)
                and request['query'].strip() == request['query']
                and 0 < len(request['query'].encode()) <= 4096
                and '\0' not in request['query'],
                'Invalid iterative search action query')
    preview_fields = root | {'schema_version', 'query', 'purpose', 'privacy',
        'round_index', 'parent_search_id', 'result_limit', 'budget', 'language',
        'binding', 'message_ids', 'artifact_ids', 'warning'}
    require(isinstance(preview, dict) and set(preview) == preview_fields
            and preview['schema_version'] == 2
            and all(preview[key] == request[key] for key in root)
            and preview['privacy'] in {'public', 'project', 'confidential'}
            and type(preview['round_index']) is int
            and 1 <= preview['round_index'] <= 3
            and type(preview['result_limit']) is int
            and 1 <= preview['result_limit'] <= 10
            and isinstance(preview['query'], str) and bool(preview['query'])
            and isinstance(preview['purpose'], str) and bool(preview['purpose'])
            and isinstance(preview['language'], str) and bool(preview['language'])
            and isinstance(preview['binding'], dict) and bool(preview['binding'])
            and isinstance(preview['message_ids'], list)
            and isinstance(preview['artifact_ids'], list)
            and isinstance(preview['warning'], str) and bool(preview['warning']),
            'Invalid iterative search action preview')
    require(preview['parent_search_id'] == request.get('parent_search_id')
            and preview['query'] == request.get('query', preview['query']),
            'Iterative search action request differs from preview')
    for item in preview['message_ids'] + preview['artifact_ids']: uuid(item)
    require(isinstance(preview['budget'], dict)
            and set(preview['budget']) == {
                'max_rounds', 'max_queries', 'max_results', 'max_seconds'}
            and all(type(item) is int and item > 0
                    for item in preview['budget'].values()),
            'Invalid iterative search action budget')
    require(isinstance(value['preview_sha256'], str)
            and bool(HASH.fullmatch(value['preview_sha256']))
            and digest(preview) == value['preview_sha256'],
            'Iterative search action preview digest changed')


class UnknownEffect(RuntimeError):
    """The adapter may have produced an effect but no result is provable."""


class AutonomyQueue:
    """Node-local authority for queue state; domain adapters keep their journals."""
    def __init__(self, state_dir, registry, handlers=None, *, countdown_seconds=5):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Autonomy state directory requires owned mode 0700')
        self.path = self.root / 'autonomy-queue.sqlite'
        self.registry = registry
        self.handlers = dict(handlers or {})
        require(type(countdown_seconds) is int
                and (countdown_seconds == 0 or 3 <= countdown_seconds <= 5),
                'Autonomy countdown must be zero for tests or 3 to 5 seconds')
        self.countdown_seconds = countdown_seconds
        self._initialize()

    def _connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe autonomy journal')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.row_factory = sqlite3.Row
        return db

    def _initialize(self):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'")}
            if not tables:
                db.executescript('''
                    CREATE TABLE schema_info(version INTEGER NOT NULL);
                    INSERT INTO schema_info VALUES(4);
                    CREATE TABLE settings(global_paused INTEGER NOT NULL);
                    INSERT INTO settings VALUES(0);
                    CREATE TABLE workflows(
                        workflow_id TEXT PRIMARY KEY, node_id TEXT NOT NULL,
                        user_id TEXT NOT NULL, project_id TEXT NOT NULL,
                        plan_digest TEXT NOT NULL, plan_json BLOB NOT NULL,
                        state TEXT NOT NULL, ui_attached INTEGER NOT NULL,
                        ui_seen_at TEXT, spent_cost INTEGER NOT NULL, created_at TEXT NOT NULL,
                        activated_at TEXT, activation_digest TEXT,
                        updated_at TEXT NOT NULL, error TEXT);
                    CREATE TABLE steps(
                        workflow_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                        step_id TEXT NOT NULL UNIQUE, action_id TEXT NOT NULL,
                        action_version TEXT NOT NULL, descriptor_digest TEXT NOT NULL,
                        state TEXT NOT NULL, approval_digest TEXT, not_before TEXT,
                        result_json BLOB, error TEXT,
                        PRIMARY KEY(workflow_id, ordinal),
                        FOREIGN KEY(workflow_id) REFERENCES workflows(workflow_id));
                    CREATE TABLE step_revisions(
                        workflow_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                        revision INTEGER NOT NULL, step_json BLOB NOT NULL,
                        cancelled_at TEXT NOT NULL,
                        PRIMARY KEY(workflow_id,ordinal,revision));
                ''')
            else:
                versions = [tuple(row) for row in
                            db.execute('SELECT version FROM schema_info').fetchall()]
                legacy_tables = {'schema_info', 'settings', 'workflows', 'steps'}
                require(tables in (legacy_tables, legacy_tables | {'step_revisions'})
                        and versions in ([(1,)], [(2,)], [(3,)], [(4,)]),
                        'Unknown or incomplete autonomy schema')
                workflow_columns = [row[1] for row in
                    db.execute('PRAGMA table_info(workflows)')]
                step_columns = [row[1] for row in db.execute('PRAGMA table_info(steps)')]
                revision_columns = ([row[1] for row in
                    db.execute('PRAGMA table_info(step_revisions)')]
                    if 'step_revisions' in tables else [])
                if versions == [(1,)]:
                    require(workflow_columns == ['workflow_id', 'node_id', 'user_id',
                        'project_id', 'plan_digest', 'plan_json', 'state', 'ui_attached',
                        'spent_cost', 'created_at', 'activated_at', 'updated_at', 'error']
                        and step_columns == ['workflow_id', 'ordinal', 'step_id',
                        'action_id', 'action_version', 'descriptor_digest', 'state',
                        'approval_digest', 'result_json', 'error'],
                        'Unknown or incomplete autonomy schema version 1')
                    db.execute('ALTER TABLE workflows ADD COLUMN ui_seen_at TEXT')
                    db.execute('ALTER TABLE steps ADD COLUMN not_before TEXT')
                    db.execute('UPDATE schema_info SET version=2')
                    workflow_columns.append('ui_seen_at'); step_columns.append('not_before')
                    versions = [(2,)]
                if versions == [(2,)]:
                    require('activation_digest' not in workflow_columns,
                            'Unexpected autonomy activation digest column')
                    db.execute('ALTER TABLE workflows ADD COLUMN activation_digest TEXT')
                    rows = db.execute('SELECT workflow_id,plan_digest,plan_json,activated_at '
                                      'FROM workflows').fetchall()
                    for workflow_id, plan_digest, raw_plan, activated_at in rows:
                        if activated_at is None: continue
                        plan = json.loads(bytes(raw_plan))
                        activation = digest({'workflow_id': workflow_id,
                            'plan_digest': plan_digest, 'mode': plan['mode'],
                            'budget': plan['budget']})
                        db.execute('UPDATE workflows SET activation_digest=? '
                                   'WHERE workflow_id=?', (activation, workflow_id))
                    db.execute('UPDATE schema_info SET version=3')
                    workflow_columns.append('activation_digest')
                    versions = [(3,)]
                if versions == [(3,)]:
                    require('step_revisions' not in tables,
                            'Unexpected autonomy step revision table')
                    db.execute('''CREATE TABLE step_revisions(
                        workflow_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
                        revision INTEGER NOT NULL, step_json BLOB NOT NULL,
                        cancelled_at TEXT NOT NULL,
                        PRIMARY KEY(workflow_id,ordinal,revision))''')
                    db.execute('UPDATE schema_info SET version=4')
                    tables.add('step_revisions')
                    revision_columns = ['workflow_id', 'ordinal', 'revision',
                                        'step_json', 'cancelled_at']
                require(tables == legacy_tables | {'step_revisions'},
                        'Unknown or incomplete autonomy schema')
                require(set(workflow_columns) == {'workflow_id', 'node_id', 'user_id',
                    'project_id', 'plan_digest', 'plan_json', 'state', 'ui_attached',
                    'ui_seen_at', 'spent_cost', 'created_at', 'activated_at',
                    'activation_digest', 'updated_at', 'error'}
                    and len(workflow_columns) == 15
                    and set(step_columns) == {'workflow_id', 'ordinal', 'step_id',
                    'action_id', 'action_version', 'descriptor_digest', 'state',
                    'approval_digest', 'not_before', 'result_json', 'error'}
                    and len(step_columns) == 11
                    and revision_columns == ['workflow_id', 'ordinal', 'revision',
                                              'step_json', 'cancelled_at'],
                    'Unknown or incomplete autonomy schema')
                db.execute("UPDATE steps SET state='unknown', error=? "
                           "WHERE state='dispatching'",
                           ('Restart occurred during action dispatch',))
                db.execute("UPDATE steps SET state='queued',not_before=NULL "
                           "WHERE state='countdown'")
                db.execute("UPDATE workflows SET state='unknown', ui_attached=0, ui_seen_at=NULL, "
                           "error=?, updated_at=? WHERE workflow_id IN "
                           "(SELECT workflow_id FROM steps WHERE state='unknown')",
                           ('Restart found an uncertain action effect', now()))
                db.execute("UPDATE workflows SET state='paused', ui_attached=0, ui_seen_at=NULL, "
                           "updated_at=? WHERE state IN ('queued','running','countdown')", (now(),))
                db.execute("UPDATE workflows SET ui_attached=0,ui_seen_at=NULL WHERE state NOT IN "
                           "('completed','failed','unknown','cancelled')")
            db.commit()

    @staticmethod
    def _owned(row, node_id, user_id):
        require(row is not None and row['node_id'] == node_id
                and row['user_id'] == user_id,
                'Autonomy workflow is unavailable to this owner')

    def prepare(self, plan, node_id, user_id):
        uuid(node_id); uuid(user_id)
        plan = parse_plan(plan, self.registry)
        raw = canonical(plan); plan_digest = digest(raw); created = now()
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (plan['workflow_id'],)).fetchone()
            if row:
                self._owned(row, node_id, user_id)
                require(row['plan_digest'] == plan_digest
                        and bytes(row['plan_json']) == raw,
                        'Autonomy workflow ID belongs to a different plan')
            else:
                db.execute('INSERT INTO workflows(workflow_id,node_id,user_id,project_id,'
                    'plan_digest,plan_json,state,ui_attached,ui_seen_at,spent_cost,created_at,'
                    'activated_at,activation_digest,updated_at,error) '
                    'VALUES(?,?,?,?,?,?,?,?,NULL,?,?,NULL,NULL,?,NULL)',
                    (plan['workflow_id'], node_id, user_id, plan['project_id'],
                     plan_digest, raw, 'proposed', 0, 0, created, created))
                for ordinal, step in enumerate(plan['steps']):
                    descriptor = self.registry.resolve(step['action']['id'],
                                                       step['action']['version'])
                    db.execute('INSERT INTO steps(workflow_id,ordinal,step_id,action_id,'
                        'action_version,descriptor_digest,state,approval_digest,not_before,'
                        'result_json,error) VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)',
                        (plan['workflow_id'], ordinal, step['step_id'],
                         descriptor['action_id'], descriptor['version'],
                         digest(descriptor), 'queued'))
            db.commit()
        return self.get(plan['workflow_id'], node_id, user_id)

    def get(self, workflow_id, node_id, user_id):
        with closing(self._connect()) as db:
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone()
            self._owned(row, node_id, user_id)
            steps = db.execute('SELECT * FROM steps WHERE workflow_id=? ORDER BY ordinal',
                               (workflow_id,)).fetchall()
            plan = parse_plan(json.loads(bytes(row['plan_json'])), self.registry,
                              allow_materialized=True)
            result = {key: row[key] for key in ('workflow_id', 'project_id', 'state',
                      'ui_attached', 'spent_cost', 'created_at', 'activated_at',
                      'updated_at', 'error')}
            result['ui_attached'] = self._ui_live(row)
            result['global_paused'] = bool(
                db.execute('SELECT global_paused FROM settings').fetchone()[0])
            result['mode'] = plan['mode']; result['privacy'] = plan['privacy']
            result['budget'] = plan['budget']
            result['countdown_seconds'] = (plan['countdown_seconds']
                if plan['schema_version'] == 2 else self.countdown_seconds)
            proposed_activation = digest({
                'workflow_id': workflow_id, 'plan_digest': row['plan_digest'],
                'mode': plan['mode'], 'budget': plan['budget']})
            result['activation_digest'] = row['activation_digest'] or proposed_activation
            result['remaining_cost'] = plan['budget']['max_cost_units'] - row['spent_cost']
            result['steps'] = []
            for stored, planned in zip(steps, plan['steps']):
                item = deepcopy(planned)
                descriptor = self.registry.resolve(
                    planned['action']['id'], planned['action']['version'])
                item.update(state=stored['state'], approval_digest=stored['approval_digest'],
                            not_before=stored['not_before'],
                            effect=descriptor['effect'],
                            automatable=descriptor['automatable'],
                            confirmation=descriptor['confirmation'],
                            permissions=descriptor['permissions'],
                            result=(json.loads(bytes(stored['result_json']))
                                    if stored['result_json'] is not None else None),
                            error=stored['error'])
                item['dispatch_digest'] = digest({'workflow_id': workflow_id,
                    'step_id': planned['step_id'], 'descriptor': digest(descriptor),
                    'input': planned['input'], 'privacy': planned['privacy'],
                    'not_before': stored['not_before']})
                result['steps'].append(item)
            revisions = db.execute('SELECT ordinal,revision,step_json,cancelled_at '
                'FROM step_revisions WHERE workflow_id=? ORDER BY ordinal,revision',
                (workflow_id,)).fetchall()
            result['revisions'] = [{'ordinal': item[0], 'revision': item[1],
                'step': json.loads(bytes(item[2])), 'state': 'cancelled',
                'cancelled_at': item[3]} for item in revisions]
            return result

    def list(self, node_id, user_id, project_id=None):
        """Return a bounded owner-filtered projection suitable for queue UI."""
        uuid(node_id); uuid(user_id)
        if project_id is not None:
            uuid(project_id)
        with closing(self._connect()) as db:
            parameters = [node_id, user_id]
            where = 'node_id=? AND user_id=?'
            if project_id is not None:
                where += ' AND project_id=?'; parameters.append(project_id)
            rows = db.execute('SELECT workflow_id FROM workflows WHERE ' + where
                + ' ORDER BY updated_at DESC,workflow_id LIMIT 128', parameters).fetchall()
            global_paused = bool(
                db.execute('SELECT global_paused FROM settings').fetchone()[0])
        return {'schema_version': 1, 'global_paused': global_paused,
                'workflows': [self.get(row['workflow_id'], node_id, user_id)
                              for row in rows]}

    def attach_ui(self, workflow_id, node_id, user_id):
        return self._set_attached(workflow_id, node_id, user_id, True)

    def detach_ui(self, workflow_id, node_id, user_id):
        return self._set_attached(workflow_id, node_id, user_id, False)

    def _set_attached(self, workflow_id, node_id, user_id, attached):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            state = row['state']
            if not attached and state in {'queued', 'running', 'countdown'}:
                state = 'paused'
                db.execute("UPDATE steps SET state='queued',not_before=NULL "
                           "WHERE workflow_id=? AND state='countdown'", (workflow_id,))
            seen = now() if attached else None
            db.execute('UPDATE workflows SET ui_attached=?,ui_seen_at=?,state=?,updated_at=? '
                       'WHERE workflow_id=?',
                       (int(attached), seen, state, now(), workflow_id)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    def activate(self, workflow_id, node_id, user_id, activation_digest):
        """Explicitly opt into the exact plan, mode and budget shown to the user."""
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] == 'proposed' and self._ui_live(row),
                    'Autonomy proposal requires an attached UI')
            plan = json.loads(bytes(row['plan_json']))
            expected = digest({'workflow_id': workflow_id,
                'plan_digest': row['plan_digest'], 'mode': plan['mode'],
                'budget': plan['budget']})
            require(activation_digest == expected,
                    'Autonomy activation differs from the reviewed plan')
            require(not db.execute('SELECT global_paused FROM settings').fetchone()[0],
                    'Autonomy queue is globally paused')
            activated = now()
            db.execute("UPDATE workflows SET state='queued',activated_at=?,"
                       "activation_digest=?,updated_at=? WHERE workflow_id=?",
                       (activated, expected, activated, workflow_id)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    def pause(self, workflow_id, node_id, user_id):
        return self._set_state(workflow_id, node_id, user_id, 'paused')

    def resume(self, workflow_id, node_id, user_id):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] == 'paused' and self._ui_live(row),
                    'Paused autonomy workflow requires an attached UI to resume')
            require(not db.execute('SELECT global_paused FROM settings').fetchone()[0],
                    'Autonomy queue is globally paused')
            db.execute("UPDATE workflows SET state='queued',updated_at=?,error=NULL "
                       "WHERE workflow_id=?", (now(), workflow_id)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    def _set_state(self, workflow_id, node_id, user_id, state):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] in {'queued', 'running', 'countdown',
                                     'awaiting-approval'},
                    'Autonomy workflow cannot be paused')
            db.execute("UPDATE steps SET state='queued',not_before=NULL "
                       "WHERE workflow_id=? AND state='countdown'", (workflow_id,))
            db.execute('UPDATE workflows SET state=?,updated_at=? WHERE workflow_id=?',
                       (state, now(), workflow_id)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    def pause_all(self):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE'); db.execute('UPDATE settings SET global_paused=1')
            db.execute("UPDATE steps SET state='queued',not_before=NULL "
                       "WHERE state='countdown'")
            db.execute("UPDATE workflows SET state='paused',updated_at=? "
                       "WHERE state IN ('queued','running','countdown')", (now(),)); db.commit()

    def resume_all(self):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE'); db.execute('UPDATE settings SET global_paused=0')
            db.commit()

    def approve(self, workflow_id, step_id, node_id, user_id):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] in {'queued', 'awaiting-approval'}
                    and self._ui_live(row),
                    'Autonomy approval requires an active attached workflow')
            plan = parse_plan(json.loads(bytes(row['plan_json'])), self.registry,
                              allow_materialized=True)
            planned = next((item for item in plan['steps'] if item['step_id'] == step_id), None)
            require(planned is not None, 'Unknown autonomy step')
            stored = db.execute('SELECT * FROM steps WHERE step_id=?', (step_id,)).fetchone()
            require(stored['state'] in {'queued', 'awaiting-approval'},
                    'Autonomy step cannot be approved')
            descriptor = self.registry.resolve(planned['action']['id'],
                                               planned['action']['version'])
            approval = digest({'workflow_id': workflow_id, 'step_id': step_id,
                               'descriptor': digest(descriptor),
                               'input': planned['input'], 'privacy': planned['privacy']})
            db.execute("UPDATE steps SET state='queued',approval_digest=? WHERE step_id=?",
                       (approval, step_id))
            db.execute("UPDATE workflows SET state='queued',updated_at=? WHERE workflow_id=?",
                       (now(), workflow_id)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    def replace_plan(self, plan, node_id, user_id):
        """Replace an undispatched plan; prior approvals are deliberately discarded."""
        uuid(node_id); uuid(user_id)
        plan = parse_plan(plan, self.registry)
        raw = canonical(plan); plan_digest = digest(raw)
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (plan['workflow_id'],)).fetchone()
            self._owned(row, node_id, user_id)
            require(row['state'] in {'proposed', 'queued', 'paused', 'awaiting-approval'},
                    'Autonomy plan can no longer be edited')
            states = [item[0] for item in db.execute(
                'SELECT state FROM steps WHERE workflow_id=?',
                (plan['workflow_id'],)).fetchall()]
            require(set(states) <= {'queued', 'awaiting-approval'},
                    'Autonomy plan already produced an effect')
            db.execute('DELETE FROM steps WHERE workflow_id=?', (plan['workflow_id'],))
            db.execute('UPDATE workflows SET project_id=?,plan_digest=?,plan_json=?,state=?, '
                       'spent_cost=0,activated_at=NULL,activation_digest=NULL,'
                       'updated_at=?,error=NULL '
                       'WHERE workflow_id=?',
                       (plan['project_id'], plan_digest, raw, 'proposed', now(),
                        plan['workflow_id']))
            for ordinal, step in enumerate(plan['steps']):
                descriptor = self.registry.resolve(step['action']['id'],
                                                   step['action']['version'])
                db.execute('INSERT INTO steps(workflow_id,ordinal,step_id,action_id,'
                    'action_version,descriptor_digest,state,approval_digest,not_before,'
                    'result_json,error) VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)',
                    (plan['workflow_id'], ordinal, step['step_id'],
                     descriptor['action_id'], descriptor['version'],
                     digest(descriptor), 'queued'))
            db.commit()
        return self.get(plan['workflow_id'], node_id, user_id)

    def append_step(self, workflow_id, step, node_id, user_id):
        """Materialize one bounded step under an already activated v2 policy."""
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] in {'queued', 'paused'}
                    and row['activated_at'] is not None
                    and row['activation_digest'] is not None,
                    'Autonomy continuation is not active')
            plan = parse_plan(json.loads(bytes(row['plan_json'])), self.registry,
                              allow_materialized=True)
            require(plan['schema_version'] == 2,
                    'Static autonomy plan cannot append steps')
            stored = db.execute('SELECT state FROM steps WHERE workflow_id=?',
                                (workflow_id,)).fetchall()
            require(stored and all(item[0] in {'completed', 'cancelled'} for item in stored)
                    and stored[-1][0] == 'completed',
                    'Autonomy continuation already has a pending step')
            previous = plan['steps'][-1]
            require(step.get('depends_on') == [previous['step_id']]
                    and step.get('input', {}).get('preview', {}).get('round_index')
                    == previous['input']['preview']['round_index'] + 1
                    and step.get('input', {}).get('request', {}).get('parent_search_id')
                    == previous['input']['request']['search_id'],
                    'Autonomy continuation does not extend the completed search step')
            updated = deepcopy(plan); updated['steps'].append(deepcopy(step))
            updated = parse_plan(updated, self.registry, allow_materialized=True)
            raw = canonical(updated); plan_digest = digest(raw)
            ordinal = len(plan['steps']); planned = updated['steps'][-1]
            descriptor = self.registry.resolve(planned['action']['id'],
                                               planned['action']['version'])
            db.execute('INSERT INTO steps(workflow_id,ordinal,step_id,action_id,'
                'action_version,descriptor_digest,state,approval_digest,not_before,'
                'result_json,error) VALUES(?,?,?,?,?,?,?,NULL,NULL,NULL,NULL)',
                (workflow_id, ordinal, planned['step_id'], descriptor['action_id'],
                 descriptor['version'], digest(descriptor), 'queued'))
            db.execute('UPDATE workflows SET plan_digest=?,plan_json=?,updated_at=? '
                       'WHERE workflow_id=?', (plan_digest, raw, now(), workflow_id))
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def revise_pending_step(self, workflow_id, step, node_id, user_id):
        """Replace only the pending search proposal while retaining its audit record."""
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] in {'queued', 'paused', 'countdown',
                                     'awaiting-approval'},
                    'Autonomy search step cannot be edited now')
            plan = parse_plan(json.loads(bytes(row['plan_json'])), self.registry,
                              allow_materialized=True)
            require(plan['schema_version'] == 2, 'Static autonomy step cannot be revised')
            ordinal = len(plan['steps']) - 1; previous = plan['steps'][ordinal]
            stored = db.execute('SELECT * FROM steps WHERE workflow_id=? AND ordinal=?',
                                (workflow_id, ordinal)).fetchone()
            require(stored is not None
                    and stored['state'] in {'queued', 'countdown', 'awaiting-approval'}
                    and previous['action'] == {
                        'id': 'search.iterative-query', 'version': '1.0'},
                    'Only an undispatched search step can be revised')
            require(step.get('action') == previous['action']
                    and step.get('privacy') == previous['privacy']
                    and step.get('cost_units') == previous['cost_units']
                    and step.get('depends_on') == previous['depends_on']
                    and step.get('input', {}).get('request', {}).get('task_id')
                    == previous['input']['request']['task_id']
                    and step.get('input', {}).get('preview', {}).get('round_index')
                    == previous['input']['preview']['round_index']
                    and step.get('input', {}).get('request', {}).get('parent_search_id')
                    == previous['input']['request'].get('parent_search_id'),
                    'Edited search step changed the activated policy')
            updated = deepcopy(plan); updated['steps'][ordinal] = deepcopy(step)
            updated = parse_plan(updated, self.registry, allow_materialized=True)
            revision = db.execute('SELECT COALESCE(MAX(revision),0)+1 '
                'FROM step_revisions WHERE workflow_id=? AND ordinal=?',
                (workflow_id, ordinal)).fetchone()[0]
            cancelled = now()
            db.execute('INSERT INTO step_revisions VALUES(?,?,?,?,?)',
                (workflow_id, ordinal, revision, canonical(previous), cancelled))
            descriptor = self.registry.resolve(step['action']['id'],
                                               step['action']['version'])
            db.execute('UPDATE steps SET step_id=?,action_id=?,action_version=?,'
                'descriptor_digest=?,state=?,approval_digest=NULL,not_before=NULL,'
                'result_json=NULL,error=NULL WHERE workflow_id=? AND ordinal=?',
                (step['step_id'], descriptor['action_id'], descriptor['version'],
                 digest(descriptor), 'queued', workflow_id, ordinal))
            raw = canonical(updated)
            following = 'paused' if row['state'] == 'paused' else 'queued'
            db.execute('UPDATE workflows SET plan_digest=?,plan_json=?,state=?,updated_at=? '
                       'WHERE workflow_id=?',
                       (digest(raw), raw, following, cancelled, workflow_id))
            db.commit()
        return self.get(workflow_id, node_id, user_id)

    def send_now(self, workflow_id, step_id, node_id, user_id, dispatch_digest):
        """Explicitly release one exact countdown step without weakening other checks."""
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] == 'countdown' and self._ui_live(row),
                    'Send now requires a live countdown')
            plan = parse_plan(json.loads(bytes(row['plan_json'])), self.registry,
                              allow_materialized=True)
            planned = next((item for item in plan['steps']
                            if item['step_id'] == step_id), None)
            stored = db.execute('SELECT * FROM steps WHERE step_id=?', (step_id,)).fetchone()
            require(planned is not None and stored is not None
                    and stored['state'] == 'countdown',
                    'Search step is not in countdown')
            descriptor = self.registry.resolve(planned['action']['id'],
                                               planned['action']['version'])
            expected = digest({'workflow_id': workflow_id, 'step_id': step_id,
                'descriptor': digest(descriptor), 'input': planned['input'],
                'privacy': planned['privacy'], 'not_before': stored['not_before']})
            require(dispatch_digest == expected,
                    'Send-now confirmation differs from displayed search step')
            db.execute("UPDATE steps SET not_before='1970-01-01T00:00:00Z' "
                       'WHERE step_id=?', (step_id,)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    def cancel(self, workflow_id, node_id, user_id):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] not in {'completed', 'failed', 'unknown'},
                    'Autonomy workflow is already terminal')
            require(not db.execute("SELECT 1 FROM steps WHERE workflow_id=? "
                                   "AND state='dispatching'", (workflow_id,)).fetchone(),
                    'A dispatching action cannot be cancelled')
            db.execute("UPDATE steps SET state='cancelled' WHERE workflow_id=? "
                       "AND state IN ('queued','countdown','awaiting-approval')", (workflow_id,))
            db.execute("UPDATE workflows SET state='cancelled',updated_at=? "
                       "WHERE workflow_id=?", (now(), workflow_id)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    def advance(self, workflow_id, node_id, user_id, *, permissions,
                allowed_privacy, expected_head, checkpoint=lambda stage: None):
        permissions = set(permissions); allowed_privacy = set(allowed_privacy)
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            require(row['state'] in {'queued', 'running', 'countdown'},
                    'Autonomy workflow is not runnable')
            require(self._ui_live(row),
                    'Autonomy dispatch requires a live attached UI')
            require(not db.execute('SELECT global_paused FROM settings').fetchone()[0],
                    'Autonomy queue is globally paused')
            plan = parse_plan(json.loads(bytes(row['plan_json'])), self.registry,
                              allow_materialized=True)
            require(plan['expected_head'] == expected_head,
                    'Project changed after autonomy plan preparation')
            require(row['activated_at'] is not None, 'Autonomy workflow was not activated')
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(
                row['activated_at'].replace('Z', '+00:00'))).total_seconds()
            require(elapsed <= plan['budget']['max_seconds'],
                    'Autonomy time budget is exhausted')
            stored_steps = db.execute(
                'SELECT * FROM steps WHERE workflow_id=? ORDER BY ordinal',
                (workflow_id,)).fetchall()
            require(not any(item['state'] == 'dispatching' for item in stored_steps),
                    'Autonomy workflow already has a dispatching action')
            candidate = next((pair for pair in zip(stored_steps, plan['steps'])
                              if pair[0]['state'] in {'queued', 'countdown',
                                                     'awaiting-approval'}), None)
            if candidate is None:
                require(all(item['state'] == 'completed' for item in stored_steps),
                        'Autonomy workflow has no runnable step')
                db.execute("UPDATE workflows SET state='completed',updated_at=? "
                           "WHERE workflow_id=?", (now(), workflow_id)); db.commit()
                return self.get(workflow_id, node_id, user_id)
            stored, planned = candidate
            require(all(next(item for item in stored_steps if item['step_id'] == dependency)
                        ['state'] == 'completed' for dependency in planned['depends_on']),
                    'Autonomy step dependencies are incomplete')
            descriptor = self.registry.resolve(planned['action']['id'],
                                               planned['action']['version'])
            require(digest(descriptor) == stored['descriptor_digest'],
                    'Autonomy action registry changed')
            require(set(descriptor['permissions']) <= permissions,
                    'Autonomy permissions changed or are insufficient')
            require(planned['privacy'] in allowed_privacy,
                    'Autonomy privacy is no longer allowed')
            require(row['spent_cost'] + planned['cost_units']
                    <= plan['budget']['max_cost_units'],
                    'Autonomy cost budget is exhausted')
            needs_approval = (plan['mode'] == 'manual'
                              or descriptor['confirmation'] != 'none'
                              or not descriptor['automatable'])
            if needs_approval and stored['approval_digest'] is None:
                db.execute("UPDATE steps SET state='awaiting-approval' WHERE step_id=?",
                           (planned['step_id'],))
                db.execute("UPDATE workflows SET state='awaiting-approval',updated_at=? "
                           "WHERE workflow_id=?", (now(), workflow_id)); db.commit()
                return self.get(workflow_id, node_id, user_id)
            countdown_seconds = (plan['countdown_seconds']
                if plan['schema_version'] == 2 else self.countdown_seconds)
            if (plan['mode'] == 'automatic' and not needs_approval
                    and stored['state'] == 'queued' and countdown_seconds):
                not_before = (datetime.now(timezone.utc)
                              + timedelta(seconds=countdown_seconds)).isoformat().replace(
                                  '+00:00', 'Z')
                db.execute("UPDATE steps SET state='countdown',not_before=? WHERE step_id=?",
                           (not_before, planned['step_id']))
                db.execute("UPDATE workflows SET state='countdown',updated_at=? "
                           "WHERE workflow_id=?", (now(), workflow_id)); db.commit()
                return self.get(workflow_id, node_id, user_id)
            if stored['state'] == 'countdown':
                ready = datetime.fromisoformat(stored['not_before'].replace('Z', '+00:00'))
                require(datetime.now(timezone.utc) >= ready,
                        'Autonomy countdown is still active')
            handler = self.handlers.get((descriptor['action_id'], descriptor['version']))
            require(handler is not None, 'No reviewed autonomy action handler')
            db.execute("UPDATE steps SET state='dispatching',not_before=NULL WHERE step_id=?",
                       (planned['step_id'],))
            db.execute("UPDATE workflows SET state='running',updated_at=? WHERE workflow_id=?",
                       (now(), workflow_id)); db.commit()
        checkpoint('dispatching')
        try:
            execution = {'workflow_id': workflow_id, 'step_id': planned['step_id'],
                'node_id': node_id, 'user_id': user_id,
                'project_id': plan['project_id'],
                'expected_head': plan['expected_head'],
                'approval_digest': stored['approval_digest']}
            result = handler(deepcopy(planned['input']), execution)
            raw = canonical(result)
        except UnknownEffect as exc:
            return self._finish_effect(workflow_id, planned['step_id'], node_id, user_id,
                                       'unknown', None, str(exc))
        except Exception as exc:
            self._finish_effect(workflow_id, planned['step_id'], node_id, user_id,
                                'failed', None, str(exc))
            raise
        checkpoint('effect-complete')
        return self._finish_effect(workflow_id, planned['step_id'], node_id, user_id,
                                   'completed', raw, None, planned['cost_units'])

    def _finish_effect(self, workflow_id, step_id, node_id, user_id, state,
                       result, error, cost=0):
        with closing(self._connect()) as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM workflows WHERE workflow_id=?',
                             (workflow_id,)).fetchone(); self._owned(row, node_id, user_id)
            step = db.execute('SELECT state FROM steps WHERE step_id=?', (step_id,)).fetchone()
            require(step is not None and step['state'] == 'dispatching',
                    'Autonomy step is not dispatching')
            db.execute('UPDATE steps SET state=?,result_json=?,error=? WHERE step_id=?',
                       (state, result, error, step_id))
            terminal = state if state in {'failed', 'unknown'} else 'queued'
            db.execute('UPDATE workflows SET state=?,spent_cost=spent_cost+?,updated_at=?,error=? '
                       'WHERE workflow_id=?',
                       (terminal, cost, now(), error, workflow_id)); db.commit()
        return self.get(workflow_id, node_id, user_id)

    @staticmethod
    def _ui_live(row):
        if not row['ui_attached'] or row['ui_seen_at'] is None:
            return False
        seen = datetime.fromisoformat(row['ui_seen_at'].replace('Z', '+00:00'))
        return (datetime.now(timezone.utc) - seen).total_seconds() <= UI_LEASE_SECONDS
