# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local federation administration; no peer transport or automatic trust."""
from contextlib import contextmanager, closing
import fcntl
import getpass
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
from spikes.project_creation import ProjectCreation
from spikes.federation_accounts import MappingSignatures, validate_spec, effective_actions

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
    def __init__(self, node, *, deployment='web'):
        if deployment not in {'web', 'desktop'}:
            raise ValueError('Unknown deployment mode')
        self.deployment = deployment
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
                state = {'schema_version': 2, 'node_id': node['id'], 'users': [], 'peers': [], 'mappings': []}
                commit = self.publish(git, state, None)
            else:
                commit = head.stdout.strip()
                state = json.loads(git.run('show', commit + ':registry.json').stdout)
            self.validate(state, node['id'])
            if state['schema_version'] == 1:
                state = dict(state, schema_version=2, mappings=[])
                commit = self.publish(git, state, commit)
            yield git, state, commit, node

    def validate(self, state, node_id):
        version = state.get('schema_version')
        expected = {'schema_version', 'node_id', 'users', 'peers'} | ({'mappings'} if version == 2 else set())
        if set(state) != expected or type(version) is not int or version not in {1, 2} or state['node_id'] != node_id:
            raise ValueError('Invalid registry identity/version')
        seen = set()
        for user in state['users']:
            if set(user) != {'id', 'home_node_id', 'name', 'active', 'node_role', 'memberships', 'credential_ref', 'revision'}:
                raise ValueError('Invalid user fields')
            identifier(user['id']); identifier(user['home_node_id']); label(user['name'])
            if user['home_node_id'] != node_id:
                raise ValueError('Only local accounts may have local credentials')
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
        seen = set()
        for mapping in state.get('mappings', []):
            if set(mapping) != {'spec', 'confirmations', 'revocation'}:
                raise ValueError('Invalid mapping record')
            spec = validate_spec(mapping['spec'])
            if spec['id'] in seen or node_id not in [a['node_id'] for a in spec['accounts']]:
                raise ValueError('Invalid mapping identity')
            seen.add(spec['id'])
            if not isinstance(mapping['confirmations'], dict) or not set(mapping['confirmations']) <= {a['node_id'] for a in spec['accounts']}:
                raise ValueError('Invalid confirmations')
            envelopes = list(mapping['confirmations'].values()) + ([mapping['revocation']] if mapping['revocation'] else [])
            for envelope in envelopes:
                if envelope['spec'] != spec:
                    raise ValueError('Confirmation for another mapping')

    def local_account(self, state, user_id):
        if self.deployment == 'desktop':
            author = ProjectCreation(self.node).author_id()
            return {'id': author, 'home_node_id': state['node_id'], 'name': getpass.getuser(),
                    'active': True, 'node_role': 'federation-admin', 'memberships': {}} if user_id == author else None
        return next((u for u in state['users'] if u['id'] == user_id and u['active']), None)

    def mapping_context(self, state, spec, *, revoking=False):
        validate_spec(spec)
        local = next((a for a in spec['accounts'] if a['node_id'] == state['node_id']), None)
        account = self.local_account(state, local['user_id']) if local else None
        if not account and local and revoking and self.deployment == 'web':
            account = next((u for u in state['users'] if u['id'] == local['user_id']), None)
        if not local or not account:
            raise ValueError('Mapping requires an active local account')
        remote = next(a for a in spec['accounts'] if a != local)
        peer = next((p for p in state['peers'] if p['id'] == remote['node_id'] and (revoking or p['trust'] == 'approved')), None)
        if not peer:
            raise AccessDenied('Peer trust is not approved')
        return local, remote, peer

    def mapping_active(self, state, mapping):
        if mapping['revocation'] or len(mapping['confirmations']) != 2:
            return False
        try:
            local, remote, peer = self.mapping_context(state, mapping['spec'])
            pins = {local['node_id']: MappingSignatures(self.root).identity()['fingerprint'], remote['node_id']: peer['fingerprint']}
            for signer, envelope in mapping['confirmations'].items():
                if envelope['signer_node_id'] != signer or envelope['decision'] != 'confirm':
                    return False
                MappingSignatures.verify(envelope, pins[signer])
            return True
        except (ValueError, OSError, subprocess.SubprocessError):
            return False

    def mapped_actions(self, user_id, mapping_id, manifest, entity_id, local_actions):
        with self.locked() as (_, state, _, _):
            mapping = next((m for m in state['mappings'] if m['spec']['id'] == mapping_id), None)
            if not mapping or not self.mapping_active(state, mapping):
                return set()
            account = self.local_account(state, user_id)
            if not account or (self.deployment == 'web' and manifest.get('project_id') not in account['memberships']):
                return set()
            if self.deployment == 'web':
                roles = {'reader': {'read'}, 'reviewer': {'read', 'review'},
                         'editor': {'read', 'write'}, 'project-admin': {'read', 'write', 'review', 'manage'}}
                local_actions = set(local_actions) & roles.get(account['memberships'][manifest['project_id']], set())
            return effective_actions(manifest, entity_id, mapping['spec'], state['node_id'], user_id, local_actions)

    def mapping_request(self, state, node, request):
        action = request['action']
        export = None
        if action == 'propose-mapping' and set(request) == {'action', 'expected_commit', 'local_user_id', 'peer_node_id', 'peer_user_id', 'project_ids'}:
            spec = {'schema_version': 1, 'id': str(uuid4()), 'accounts': sorted([
                {'node_id': node['id'], 'user_id': identifier(request['local_user_id'])},
                {'node_id': identifier(request['peer_node_id']), 'user_id': identifier(request['peer_user_id'])}], key=lambda a: a['node_id']),
                'project_ids': request['project_ids']}
            self.mapping_context(state, spec)
            mapping = {'spec': spec, 'confirmations': {}, 'revocation': None}
            state['mappings'].append(mapping)
        elif action in {'confirm-mapping', 'revoke-mapping'} and set(request) == {'action', 'expected_commit', 'mapping_id'}:
            mapping = next((m for m in state['mappings'] if m['spec']['id'] == request['mapping_id']), None)
            if not mapping or mapping['revocation']:
                raise ValueError('Unknown or revoked mapping')
            if action == 'confirm-mapping':
                self.mapping_context(state, mapping['spec'])
            export = MappingSignatures(self.root).sign(mapping['spec'], node['id'], 'revoke' if action == 'revoke-mapping' else 'confirm')
            if action == 'revoke-mapping':
                mapping['revocation'] = export
            else:
                mapping['confirmations'][node['id']] = export
        elif action == 'import-mapping' and set(request) == {'action', 'expected_commit', 'envelope'}:
            envelope = request['envelope']
            if not isinstance(envelope, dict) or 'spec' not in envelope:
                raise ValueError('Invalid confirmation')
            local, remote, peer = self.mapping_context(state, envelope['spec'], revoking=envelope.get('decision') == 'revoke')
            if envelope.get('signer_node_id') != remote['node_id']:
                raise ValueError('Remote confirmation must be signed by the peer')
            MappingSignatures.verify(envelope, peer['fingerprint'])
            mapping = next((m for m in state['mappings'] if m['spec']['id'] == envelope['spec']['id']), None)
            if not mapping:
                mapping = {'spec': envelope['spec'], 'confirmations': {}, 'revocation': None}
                state['mappings'].append(mapping)
            if mapping['spec'] != envelope['spec'] or (mapping['revocation'] and envelope['decision'] != 'revoke'):
                raise ValueError('Changed or already revoked mapping')
            if envelope['decision'] == 'revoke':
                mapping['revocation'] = envelope
            else:
                mapping['confirmations'][remote['node_id']] = envelope
        else:
            raise ValueError('Invalid mapping request')
        if not set(mapping['spec']['project_ids']) <= {p['project_id'] for p in node['projects']}:
            raise ValueError('Unknown scoped projects')
        return export

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
        if self.deployment == 'desktop':
            return None  # Native process token/OS session only, no foreign account login.
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
            export = None
            registered = {p['project_id'] for p in node['projects']}
            if action == 'create-user' and set(request) == {'action', 'expected_commit', 'name', 'node_role'}:
                if self.deployment != 'web':
                    raise AccessDenied('Desktop has only its running local user')
                role = request['node_role']
                if not isinstance(role, str) or role not in NODE_ROLES or (role == 'federation-admin' and actor['node_role'] != 'federation-admin'):
                    raise AccessDenied('Cannot grant federation administrator')
                user = {'id': str(uuid4()), 'home_node_id': node['id'], 'name': label(request['name']),
                        'active': True, 'node_role': role, 'memberships': {}, 'revision': 1}
                user['credential_ref'], token = self.issue(user['id'])
                state['users'].append(user)
            elif action in {'update-user', 'rotate-key'}:
                if self.deployment != 'web':
                    raise AccessDenied('Desktop has no web account management')
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
            elif action == 'update-peer-endpoint' and set(request) == {'action', 'expected_commit', 'node_id', 'endpoint'}:
                if actor['node_role'] != 'federation-admin':
                    raise AccessDenied('Federation administrator required')
                peer = next((p for p in state['peers'] if p['id'] == request['node_id']), None)
                if peer is None or peer['trust'] != 'approved':
                    raise ValueError('Unknown or unapproved peer')
                endpoint = self.endpoint(request['endpoint'])
                if peer['endpoint'] == endpoint:
                    return self.public(state, commit, actor)
                peer.update(endpoint=endpoint, revision=peer['revision'] + 1)
            elif action == 'set-trust' and set(request) == {'action', 'expected_commit', 'node_id', 'trust'}:
                if actor['node_role'] != 'federation-admin':
                    raise AccessDenied('Federation administrator required')
                peer = next((p for p in state['peers'] if p['id'] == request['node_id']), None)
                if peer is None or not isinstance(request['trust'], str) or request['trust'] not in {'approved', 'revoked', 'pending'}:
                    raise ValueError('Invalid trust change')
                peer.update(trust=request['trust'], revision=peer['revision'] + 1)
                if request['trust'] == 'revoked':
                    for mapping in state['mappings']:
                        if not mapping['revocation'] and any(a['node_id'] == peer['id'] for a in mapping['spec']['accounts']):
                            mapping['revocation'] = MappingSignatures(self.root).sign(mapping['spec'], node['id'], 'revoke')
            elif action in {'propose-mapping', 'confirm-mapping', 'revoke-mapping', 'import-mapping'}:
                if actor['node_role'] != 'federation-admin':
                    raise AccessDenied('Federation administrator required')
                export = self.mapping_request(state, node, request)
            else:
                raise ValueError('Unknown administration operation')
            commit = self.publish(git, state, commit)
            result = self.public(state, commit, actor)
            if token:
                result['access_key'] = token
            if export:
                result['mapping_envelope'] = export
            return result

    def public(self, state, commit, actor):
        users = [{k: v for k, v in u.items() if k != 'credential_ref'} for u in state['users']]
        if self.deployment == 'desktop':
            users = [self.local_account(state, ProjectCreation(self.node).author_id())]
        return {'node_id': state['node_id'], 'commit_id': commit,
                'users': users, 'deployment': self.deployment,
                'peers': state['peers'] if actor['node_role'] == 'federation-admin' else [],
                'mapping_identity': MappingSignatures(self.root).identity() if actor['node_role'] == 'federation-admin' else None,
                'mappings': [dict(m, active=self.mapping_active(state, m)) for m in state['mappings']] if actor['node_role'] == 'federation-admin' else [],
                'federation_admin': actor['node_role'] == 'federation-admin',
                'transport': 'not-implemented'}
