# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local federation administration; no peer transport or automatic trust."""
from contextlib import contextmanager, closing
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
from urllib.parse import urlsplit
from uuid import uuid4, UUID

from spikes.configuration import parse_node, read_config, overlap
from spikes.journal import sync_dir
from spikes.storage import Git

NODE_ROLES = {'member', 'node-admin', 'federation-admin'}
PROJECT_ROLES = {'project-admin', 'editor', 'reviewer', 'reader'}


class AccessDenied(ValueError):
    pass


def identifier(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError('Expected canonical UUID')
    return value


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 200 or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid name')
    return value.strip()


class Administration:
    def __init__(self, node):
        self.node = Path(node).absolute()
        self.root = self.node.parent / ('.' + self.node.name + '.administration')
        self.repo = self.root / 'registry.git'

    @contextmanager
    def locked(self):
        if self.node != self.node.resolve():
            raise ValueError('Node path contains symlinks')
        node = parse_node(read_config(self.node), location=self.node)
        for project in node['projects']:
            if any(overlap(self.root, Path(project[key])) for key in ('root', 'state_dir')):
                raise ValueError('Administration must be outside projects and their state')
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Unsafe administration directory')
        fd = os.open(self.root / 'lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            git = Git(self.repo)
            if not self.repo.exists():
                self.repo.mkdir(mode=0o700)
            if self.repo.is_symlink():
                raise ValueError('Registry must not be a symlink')
            # init is safely repeatable after interruption during bootstrap.
            git.run('init', '--bare', '--template=', '--initial-branch=main')
            head = git.run('rev-parse', '--verify', 'refs/heads/main', check=False)
            if head.returncode:
                state = {'schema_version': 1, 'node_id': node['id'], 'users': [], 'peers': []}
                commit = self.publish(git, state, None)
            else:
                commit = head.stdout.strip()
                state = json.loads(git.run('show', commit + ':registry.json').stdout)
            self.validate(state, node['id'])
            yield git, state, commit, node

    def validate(self, state, node_id):
        if set(state) != {'schema_version', 'node_id', 'users', 'peers'} or state['schema_version'] != 1 or state['node_id'] != node_id:
            raise ValueError('Invalid registry identity/version')
        seen = set()
        for user in state['users']:
            if set(user) != {'id', 'home_node_id', 'name', 'active', 'node_role', 'memberships', 'credential_ref', 'revision'}:
                raise ValueError('Invalid user fields')
            identifier(user['id']); identifier(user['home_node_id']); label(user['name'])
            if user['id'] in seen or type(user['active']) is not bool or user['node_role'] not in NODE_ROLES:
                raise ValueError('Invalid user')
            seen.add(user['id'])
            identifier(user['credential_ref'])
            if type(user['revision']) is not int or user['revision'] < 1 or not isinstance(user['memberships'], dict):
                raise ValueError('Invalid user revision or memberships')
            for project, role in user['memberships'].items():
                identifier(project)
                if not isinstance(role, str) or role not in PROJECT_ROLES:
                    raise ValueError('Invalid project role')
        seen = set()
        for peer in state['peers']:
            if set(peer) != {'id', 'name', 'endpoint', 'fingerprint', 'trust', 'revision'}:
                raise ValueError('Invalid peer fields')
            identifier(peer['id']); label(peer['name']); self.endpoint(peer['endpoint'])
            if peer['id'] == node_id or peer['id'] in seen or peer['trust'] not in {'pending', 'approved', 'revoked'}:
                raise ValueError('Invalid peer identity/trust')
            seen.add(peer['id'])
            if not re.fullmatch(r'[a-f0-9]{64}', peer['fingerprint']) or type(peer['revision']) is not int or peer['revision'] < 1:
                raise ValueError('Invalid peer fingerprint/revision')

    @staticmethod
    def endpoint(value):
        if not isinstance(value, str) or len(value) > 500 or any(ord(c) < 33 for c in value):
            raise ValueError('Invalid endpoint')
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Expected HTTPS endpoint without credentials')
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError('Invalid endpoint port')
        return value.rstrip('/')

    def publish(self, git, state, parent):
        self.validate(state, state['node_id'])
        blob = git.run('hash-object', '-w', '--stdin', input=json.dumps(state, ensure_ascii=False, sort_keys=True) + '\n').stdout.strip()
        tree = git.run('mktree', input='100644 blob ' + blob + '\tregistry.json\n').stdout.strip()
        args = ['commit-tree', tree]
        if parent:
            args += ['-p', parent]
        commit = git.run(*args, input='Update administration registry\n', env_extra={
            'GIT_AUTHOR_NAME': 'Workspace administration', 'GIT_COMMITTER_NAME': 'Workspace administration',
            'GIT_AUTHOR_EMAIL': state['node_id'] + '@local.invalid',
            'GIT_COMMITTER_EMAIL': state['node_id'] + '@local.invalid'}).stdout.strip()
        # Objects and ref are flushed before reporting success. No working-tree
        # publication or derived index is needed for this single-file registry.
        for directory, _, files in os.walk(self.repo):
            for name in files:
                fd = os.open(Path(directory) / name, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            sync_dir(directory)
        git.run('-c', 'core.fsync=all', 'update-ref', 'refs/heads/main', commit, parent or '0' * 40)
        sync_dir(self.repo / 'refs' / 'heads')
        sync_dir(self.root)
        return commit

    def issue(self, user_id):
        reference, token = str(uuid4()), secrets.token_urlsafe(32)
        path = self.root / 'credentials.sqlite'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        os.close(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Unsafe credential store')
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS credentials (ref TEXT PRIMARY KEY, user_id TEXT NOT NULL, digest TEXT NOT NULL)')
            db.execute('INSERT INTO credentials VALUES (?, ?, ?)', (reference, user_id, hashlib.sha256(token.encode()).hexdigest()))
        sync_dir(self.root)
        return reference, token

    def authenticate(self, auth):
        if not auth.startswith('Bearer ') or len(auth) > 256 or not self.node.exists():
            return None
        digest = hashlib.sha256(auth[7:].encode()).hexdigest()
        with self.locked() as (_, state, _, _):
            path = self.root / 'credentials.sqlite'
            if not path.exists():
                return None
            if path.is_symlink():
                raise ValueError('Unsafe credentials')
            with closing(sqlite3.connect(path)) as db, db:
                row = db.execute('SELECT ref, user_id FROM credentials WHERE digest=?', (digest,)).fetchone()
            if row:
                return next((u for u in state['users'] if u['id'] == row[1] and u['credential_ref'] == row[0] and u['active']), None)
        return None

    @staticmethod
    def is_admin(actor):
        return actor and actor['node_role'] in {'node-admin', 'federation-admin'}

    @staticmethod
    def allowed(actor, project):
        return isinstance(project, str) and (Administration.is_admin(actor) or bool(actor and project in actor['memberships']))

    def request(self, actor, request):
        if not self.is_admin(actor):
            raise AccessDenied('Administration requires node-admin')
        if not isinstance(request, dict):
            raise ValueError('Expected request object')
        action = request.get('action')
        if not isinstance(action, str):
            raise ValueError('Expected action name')
        with self.locked() as (git, state, commit, node):
            if action == 'list' and set(request) == {'action'}:
                return self.public(state, commit, actor)
            if request.get('expected_commit') != commit:
                raise AccessDenied('Registry changed; reload before editing')
            token = None
            registered = {p['project_id'] for p in node['projects']}
            if action == 'create-user' and set(request) == {'action', 'expected_commit', 'name', 'node_role'}:
                role = request['node_role']
                if not isinstance(role, str) or role not in NODE_ROLES or (role == 'federation-admin' and actor['node_role'] != 'federation-admin'):
                    raise AccessDenied('Cannot grant federation administrator')
                user = {'id': str(uuid4()), 'home_node_id': node['id'], 'name': label(request['name']),
                        'active': True, 'node_role': role, 'memberships': {}, 'revision': 1}
                user['credential_ref'], token = self.issue(user['id'])
                state['users'].append(user)
            elif action in {'update-user', 'rotate-key'}:
                user = next((u for u in state['users'] if u['id'] == request.get('user_id')), None)
                if user is None:
                    raise ValueError('Unknown user')
                if user['node_role'] == 'federation-admin' and actor['node_role'] != 'federation-admin':
                    raise AccessDenied('Cannot edit federation administrator')
                if action == 'rotate-key' and set(request) == {'action', 'expected_commit', 'user_id'}:
                    user['credential_ref'], token = self.issue(user['id'])
                elif action == 'update-user' and set(request) == {'action', 'expected_commit', 'user_id', 'active', 'node_role', 'memberships'}:
                    role, memberships = request['node_role'], request['memberships']
                    if not isinstance(role, str) or role not in NODE_ROLES or (role == 'federation-admin' and actor['node_role'] != 'federation-admin'):
                        raise AccessDenied('Cannot grant this role')
                    if not isinstance(memberships, dict) or not set(memberships) <= registered:
                        raise ValueError('Unknown projects')
                    if user['id'] == actor.get('id') and (request['active'] is not True or role != actor['node_role']):
                        raise AccessDenied('Cannot revoke your own administrative access')
                    user.update(active=request['active'], node_role=role, memberships=memberships)
                else:
                    raise ValueError('Invalid user operation')
                user['revision'] += 1
            elif action == 'add-peer' and set(request) == {'action', 'expected_commit', 'node_id', 'name', 'endpoint', 'fingerprint'}:
                if actor['node_role'] != 'federation-admin':
                    raise AccessDenied('Federation administrator required')
                if not isinstance(request['fingerprint'], str):
                    raise ValueError('Expected fingerprint text')
                state['peers'].append({'id': identifier(request['node_id']), 'name': label(request['name']),
                    'endpoint': self.endpoint(request['endpoint']), 'fingerprint': request['fingerprint'].lower(),
                    'trust': 'pending', 'revision': 1})
            elif action == 'set-trust' and set(request) == {'action', 'expected_commit', 'node_id', 'trust'}:
                if actor['node_role'] != 'federation-admin':
                    raise AccessDenied('Federation administrator required')
                peer = next((p for p in state['peers'] if p['id'] == request['node_id']), None)
                if peer is None or not isinstance(request['trust'], str) or request['trust'] not in {'approved', 'revoked', 'pending'}:
                    raise ValueError('Invalid trust change')
                peer.update(trust=request['trust'], revision=peer['revision'] + 1)
            else:
                raise ValueError('Unknown administration operation')
            commit = self.publish(git, state, commit)
            result = self.public(state, commit, actor)
            if token:
                result['access_key'] = token
            return result

    @staticmethod
    def public(state, commit, actor):
        return {'node_id': state['node_id'], 'commit_id': commit,
                'users': [{k: v for k, v in u.items() if k != 'credential_ref'} for u in state['users']],
                'peers': state['peers'] if actor['node_role'] == 'federation-admin' else [],
                'federation_admin': actor['node_role'] == 'federation-admin',
                'transport': 'not-implemented'}
