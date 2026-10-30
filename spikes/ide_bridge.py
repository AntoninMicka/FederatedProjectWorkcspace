# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local, scoped IDE mailboxes. No project writer and no agent invocation."""
import base64
from contextlib import contextmanager, closing
import hashlib
import hmac
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import time
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

from spikes.administration import Administration
from spikes.artifact_actions import ArtifactActions
from spikes.metadata import require, uuid
from spikes.projects import Projects

MAX_MESSAGE = 16384
EXTENSION = Path(__file__).resolve().parent.parent / 'extensions' / 'workspace-bridge'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def endpoint(value):
    require(isinstance(value, str), 'Invalid endpoint')
    parsed = urlsplit(value)
    require(not parsed.username and not parsed.password and not parsed.query
            and not parsed.fragment and parsed.path in {'', '/'}
            and parsed.hostname and parsed.port, 'Expected exact endpoint origin')
    require(parsed.scheme == 'https' or (parsed.scheme == 'http'
            and parsed.hostname in {'127.0.0.1', 'localhost', '::1'}), 'HTTPS required')
    return value.rstrip('/')


class IdeBridge:
    def __init__(self, node, *, network=False):
        self.node = Path(node).absolute()
        self.network = network
        self.desktop_origin = None
        self.discovery_root = None
        self.root = self.node.parent / ('.' + self.node.name + '.ide-bridge')
        # Export never silently moves local-only content to another client.
        self.projects = Projects(node, network=True)

    @contextmanager
    def database(self):
        require(self.node.parent.resolve() == self.node.parent, 'Unsafe node path')
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.lstat()
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
                and info.st_uid == os.getuid() and self.root.resolve() == self.root,
                'Unsafe bridge state directory')
        result = subprocess.run(['git', '-C', str(self.root), 'rev-parse', '--show-toplevel'],
                                capture_output=True, timeout=5)
        require(result.returncode != 0, 'Bridge state must be outside Git')
        path = self.root / 'bridge.sqlite'
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                    and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600,
                    'Unsafe bridge database')
        finally:
            os.close(fd)
        with closing(sqlite3.connect(path, timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TABLE IF NOT EXISTS sessions '
                       '(id TEXT PRIMARY KEY, digest TEXT UNIQUE, record TEXT NOT NULL, revoked INTEGER DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS messages '
                       '(session TEXT, id TEXT, digest TEXT, record TEXT, receipt TEXT, PRIMARY KEY(session,id))')
            db.execute('CREATE TABLE IF NOT EXISTS connections '
                       '(id TEXT PRIMARY KEY, digest TEXT UNIQUE, record TEXT NOT NULL, revoked INTEGER DEFAULT 0)')
            yield db

    def publish_endpoints(self):
        """Rebuild signed, credential-free desktop discovery from durable records."""
        if not self.desktop_origin or not (self.root / 'bridge.sqlite').exists():
            return
        origin = endpoint(self.desktop_origin)
        require(urlsplit(origin).scheme == 'http' and urlsplit(origin).hostname == '127.0.0.1',
                'Discovery requires desktop loopback')
        root = self.discovery_root or Path.home() / '.local/state/federated-workspace/ide-discovery'
        root.mkdir(parents=True, mode=0o700, exist_ok=True)
        from spikes.local_api import private_directory
        private_directory(root)
        result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                                capture_output=True, timeout=5)
        require(result.returncode == 128, 'Discovery must be outside Git')
        with self.database() as db:
            rows = list(db.execute('SELECT id,digest,record FROM connections WHERE revoked=0'))
            rows += list(db.execute('SELECT id,digest,record FROM sessions WHERE revoked=0 AND digest IS NOT NULL'))
        for row in rows:
            if json.loads(row['record'])['expires_at'] <= time.time():
                continue
            identifier = row['id']
            uuid(identifier)
            signature = hmac.new(bytes.fromhex(row['digest']),
                                 (identifier + '\n' + origin).encode(), hashlib.sha256).hexdigest()
            data = canonical(dict(id=identifier, endpoint=origin, signature=signature))
            temporary = root / ('.' + str(uuid4()) + '.tmp')
            try:
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, root / (identifier + '.json'))
            finally:
                temporary.unlink(missing_ok=True)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def snapshot(self, project_id, expected_head, *, writable=False):
        uuid(project_id)
        view = self.projects.open(project_id)
        require(not writable or not view['read_only'], 'Project is read-only')
        require(view['commit_id'] == expected_head, 'Project changed; reopen project')
        require(view['plan']['status'] == 'ready', 'TODO requires stable task IDs and a valid plan')
        opened = ArtifactActions(self.node, network=True).open(
            project_id, view['main_todo_id'], expected_head)
        plan = view['plan']
        # Flatten included definition documents into one read-only human snapshot.
        lines = [f'# {view["title"]} — TODO', f'\nProject: {project_id}',
                 f'Commit: {expected_head}', f'Plan revision: {plan["revision"]}\n']
        for task in plan['nodes']:
            lines.append(f'{"  " * task["hierarchy_depth"]}- [{"x" if task["checked"] else " "}] [{task["id"]}] {task["title"]}')
            if task['description']:
                lines.extend('    ' + line for line in task['description'].splitlines())
        require(self.projects.repository(project_id).head() == expected_head, 'Project changed during export')
        result = dict(project_id=project_id, project_title=view['title'], commit_id=expected_head,
                    revision=plan['revision'], tasks=plan['nodes'], todo='\n'.join(lines) + '\n',
                    source_todo=opened['document']['body'])
        require(len(canonical(result).encode()) <= 1024 * 1024, 'Bridge export exceeds 1 MiB')
        return result

    def create(self, request, actor, origin):
        require(isinstance(request, dict) and set(request) == {
            'project_id', 'expected_head', 'repository', 'instructions'}, 'Invalid pairing request')
        repository, instructions = request['repository'], request['instructions']
        require(isinstance(repository, str) and 1 <= len(repository) <= 1024
                and not any(ord(c) < 32 for c in repository), 'Repository identity required')
        require(isinstance(instructions, str) and len(instructions.encode()) <= MAX_MESSAGE
                and '\0' not in instructions, 'Invalid instructions')
        snapshot = self.snapshot(request['project_id'], request['expected_head'])
        session_id, token = str(uuid4()), secrets.token_urlsafe(32)
        record = dict(session_id=session_id, project_id=request['project_id'],
                      owner=(actor or {}).get('id'), credential_ref=(actor or {}).get('credential_ref'),
                      origin=endpoint(origin), repository=repository, instructions=instructions,
                      snapshot=snapshot, expires_at=int(time.time()) + 30 * 86400)
        with self.database() as db:
            db.execute('INSERT INTO sessions(id,digest,record) VALUES (?,?,?)',
                       (session_id, hashlib.sha256(token.encode()).hexdigest(), canonical(record)))
        self.publish_endpoints()
        pairing = dict(schema_version=1, session_id=session_id, token=token,
                       endpoint=record['origin'], repository=repository,
                       project_id=request['project_id'], expires_at=record['expires_at'])
        return dict(session_id=session_id, pairing=pairing,
                    package_base64=base64.b64encode(self.package(pairing)).decode(),
                    filename='workspace-bridge.vsix', revision=snapshot['revision'])

    def package(self, pairing=None):
        """Small dependency-free VSIX; session secret exists only in generated bytes."""
        manifest = json.loads((EXTENSION / 'package.json').read_text())
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('package.json', 'extension.js', 'bridge.js', 'README.md', 'LICENSE'):
                archive.writestr('extension/' + name, (EXTENSION / name).read_bytes())
            if pairing is not None:
                archive.writestr('extension/pairing.json', canonical(pairing))
            archive.writestr('[Content_Types].xml', '''<?xml version="1.0"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="json" ContentType="application/json"/><Default Extension="js" ContentType="application/javascript"/><Default Extension="md" ContentType="text/markdown"/><Default Extension="vsixmanifest" ContentType="text/xml"/><Default Extension="" ContentType="text/plain"/></Types>''')
            archive.writestr('extension.vsixmanifest', f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011"><Metadata><Identity Language="en-US" Id="{manifest['name']}" Version="{manifest['version']}" Publisher="{manifest['publisher']}"/><DisplayName>Workspace file bridge</DisplayName><Description xml:space="preserve">Local TODO and message bridge</Description><Tags>workspace</Tags><Categories>Other</Categories><GalleryFlags>Public</GalleryFlags><Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="{manifest['engines']['vscode']}"/><Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value=""/><Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value=""/><Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace"/></Properties><License>extension/LICENSE</License></Metadata><Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation><Dependencies/><Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets></PackageManifest>''')
        return output.getvalue()

    def session(self, token):
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token), 'Invalid bridge credential')
        with self.database() as db:
            row = db.execute('SELECT record,revoked FROM sessions WHERE digest=?',
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        require(row and not row['revoked'], 'Bridge revoked or unavailable')
        record = json.loads(row['record'])
        require(record['expires_at'] > time.time(), 'Bridge expired; pair again')
        actor = self.connection_actor(record)
        self.require_editor(actor, record['project_id'])
        return record

    def exchange(self, record, request):
        require(isinstance(request, dict) and set(request) == {'session_id', 'messages'}
                and request['session_id'] == record['session_id'], 'Wrong bridge session')
        messages = request['messages']
        require(isinstance(messages, list) and len(messages) <= 20, 'Too many messages')
        # Revalidate privacy/current HEAD even for credential-only polls and retries.
        view = self.projects.open(record['project_id'])
        require(not record.get('connection_id') or not view['read_only'], 'Project is read-only')
        stale = view['commit_id'] != record['snapshot']['commit_id']
        receipts = []
        for message in messages:
            require(isinstance(message, dict) and set(message) == {
                'message_id', 'task_id', 'kind', 'body', 'revision', 'repository_commit'}, 'Invalid message')
            uuid(message['message_id'])
            require(isinstance(message['kind'], str) and message['kind'] in {'completed', 'clarification', 'message'}, 'Invalid message kind')
            require(isinstance(message['body'], str) and 0 < len(message['body'].encode()) <= MAX_MESSAGE
                    and '\0' not in message['body'], 'Invalid message body')
            require(isinstance(message['task_id'], str) and message['task_id'] in {t['id'] for t in record['snapshot']['tasks']}, 'Unknown task')
            require(message['revision'] == record['snapshot']['revision'], 'Wrong source revision')
            require(isinstance(message['repository_commit'], str) and re.fullmatch(
                r'[0-9a-f]{40}|[0-9a-f]{64}', message['repository_commit']), 'Invalid repository commit')
            digest = hashlib.sha256(canonical(message).encode()).hexdigest()
            receipt = dict(message_id=message['message_id'], status='stale' if stale else 'received',
                           project_id=record['project_id'], revision=message['revision'],
                           acceptance='pending-human-review')
            with self.database() as db:
                # Writer lock coordinates revoke and receipt publication.
                db.execute('BEGIN IMMEDIATE')
                active = db.execute('SELECT revoked FROM sessions WHERE id=?', (record['session_id'],)).fetchone()
                require(active and not active['revoked'], 'Bridge revoked')
                if record.get('connection_id'):
                    parent = db.execute('SELECT revoked FROM connections WHERE id=?', (record['connection_id'],)).fetchone()
                    require(parent and not parent['revoked'], 'Workspace connection revoked')
                prior = db.execute('SELECT digest,receipt FROM messages WHERE session=? AND id=?',
                                   (record['session_id'], message['message_id'])).fetchone()
                if prior:
                    require(prior['digest'] == digest, 'Message ID reused with different content')
                    receipt = json.loads(prior['receipt'])
                else:
                    db.execute('INSERT INTO messages VALUES (?,?,?,?,?)',
                               (record['session_id'], message['message_id'], digest,
                                canonical(message), canonical(receipt)))
            receipts.append(receipt)
        return dict(session_id=record['session_id'], stale=stale, receipts=receipts,
                    snapshot=record['snapshot'], repository=record['repository'],
                    instructions=record['instructions'])

    def status(self, project_id):
        uuid(project_id)
        self.projects.open(project_id)
        with self.database() as db:
            sessions = []
            for row in db.execute('SELECT id,record,revoked FROM sessions ORDER BY rowid DESC LIMIT 200'):
                record = json.loads(row['record'])
                if record['project_id'] != project_id:
                    continue
                messages = [dict(message=json.loads(m['record']), receipt=json.loads(m['receipt']))
                            for m in db.execute('SELECT record,receipt FROM messages WHERE session=? ORDER BY rowid DESC LIMIT 100', (row['id'],))]
                sessions.append(dict(session_id=row['id'], connection_id=record.get('connection_id'), repository=record['repository'],
                                     revision=record['snapshot']['revision'], revoked=bool(row['revoked']),
                                     expires_at=record['expires_at'], messages=messages))
        return dict(sessions=sessions)

    def revoke(self, project_id, session_id, *, actor=None):
        uuid(project_id); uuid(session_id)
        with self.database() as db:
            row = db.execute('SELECT record FROM sessions WHERE id=?', (session_id,)).fetchone()
            require(row and json.loads(row['record'])['project_id'] == project_id, 'Wrong project')
            record = json.loads(row['record'])
            if record.get('connection_id') and actor is not None:
                require(Administration.is_admin(actor) or record['owner'] == actor.get('id'), 'Mapping belongs to another account')
            db.execute('UPDATE sessions SET revoked=1 WHERE id=?', (session_id,))
        return dict(session_id=session_id, revoked=True)

    def connection_actor(self, record):
        if not self.network or record['owner'] is None:
            return {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        with Administration(self.node).read_locked() as state:
            actor = next((u for u in state['users'] if u['id'] == record['owner']
                          and u['active'] and u['credential_ref'] == record['credential_ref']), None)
            require(actor is not None, 'Workspace account access revoked')
            return actor

    @staticmethod
    def require_editor(actor, project_id):
        require(Administration.is_admin(actor) or bool(actor and actor.get('memberships', {}).get(
            project_id) in {'editor', 'project-admin'}), 'Project write access revoked')

    def connection_create(self, request, actor, origin):
        require(isinstance(request, dict) and set(request) == {'name'}, 'Invalid connection request')
        name = request['name']
        require(isinstance(name, str) and 0 < len(name.strip()) <= 120
                and not any(ord(c) < 32 for c in name), 'Connection name required')
        connection_id, token = str(uuid4()), secrets.token_urlsafe(32)
        record = dict(connection_id=connection_id, name=name.strip(), origin=endpoint(origin),
                      owner=(actor or {}).get('id'), credential_ref=(actor or {}).get('credential_ref'),
                      expires_at=int(time.time()) + 30 * 86400)
        with self.database() as db:
            db.execute('INSERT INTO connections(id,digest,record) VALUES (?,?,?)',
                       (connection_id, hashlib.sha256(token.encode()).hexdigest(), canonical(record)))
        self.publish_endpoints()
        pairing = dict(schema_version=2, connection_id=connection_id, token=token,
                       endpoint=record['origin'], name=record['name'], expires_at=record['expires_at'])
        return dict(connection_id=connection_id, pairing=pairing,
                    package_base64=base64.b64encode(self.package(pairing)).decode(), filename='workspace-bridge.vsix')

    def connection(self, token):
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', token), 'Invalid connection credential')
        with self.database() as db:
            row = db.execute('SELECT record,revoked FROM connections WHERE digest=?',
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        require(row and not row['revoked'], 'Workspace connection revoked or unavailable')
        record = json.loads(row['record'])
        require(record['expires_at'] > time.time(), 'Workspace connection expired')
        self.connection_actor(record)
        return record

    def managed_connection(self, actor, connection_id):
        uuid(connection_id)
        with self.database() as db:
            row = db.execute('SELECT record,revoked FROM connections WHERE id=?', (connection_id,)).fetchone()
        require(row, 'Unknown Workspace connection')
        record = json.loads(row['record'])
        require(Administration.is_admin(actor) or (actor and record['owner'] == actor.get('id')),
                'Connection belongs to another account')
        return dict(record, revoked=bool(row['revoked']))

    def eligible_projects(self, actor):
        result = []
        for row in self.projects.catalog():
            if not row['available']:
                continue
            if not Administration.is_admin(actor) and (actor or {}).get('memberships', {}).get(row['id']) not in {'editor', 'project-admin'}:
                continue
            view = self.projects.open(row['id'])
            if view['read_only']:
                continue
            result.append(dict(project_id=row['id'], title=row['title'], expected_head=view['commit_id']))
        return result

    def connection_mappings(self, connection_id, actor, *, eligible=None):
        if eligible is None:
            eligible = {p['project_id'] for p in self.eligible_projects(actor)}
        with self.database() as db:
            result = []
            for row in db.execute('SELECT id,record FROM sessions WHERE revoked=0 ORDER BY rowid'):
                record = json.loads(row['record'])
                if record.get('connection_id') != connection_id or record['project_id'] not in eligible:
                    continue
                result.append(dict(session_id=row['id'], project_id=record['project_id'],
                    title=record['snapshot']['project_title'], repository=record['repository'],
                    editor_workspace=record.get('editor_workspace', ''), instructions=record['instructions'],
                    revision=record['snapshot']['revision'], expected_head=record['snapshot']['commit_id'],
                    bound=record.get('bound', False)))
        return result

    def connections_status(self, actor):
        # Native process token and server bootstrap are node-local admins.
        actor = actor or {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        with self.database() as db:
            rows = list(db.execute('SELECT record,revoked FROM connections ORDER BY rowid DESC LIMIT 200'))
        connections = []
        projects = self.eligible_projects(actor)
        eligible = {p['project_id'] for p in projects}
        for row in rows:
            record = json.loads(row['record'])
            if not Administration.is_admin(actor) and record['owner'] != actor.get('id'):
                continue
            connections.append(dict(connection_id=record['connection_id'], name=record['name'],
                revoked=bool(row['revoked']), expires_at=record['expires_at'],
                mappings=self.connection_mappings(record['connection_id'], actor, eligible=eligible)))
        return dict(connections=connections, projects=projects)

    def configure_mapping(self, actor, request):
        fields = {'connection_id', 'project_id', 'enabled', 'expected_head',
                  'repository', 'editor_workspace', 'instructions', 'expected_mapping'}
        require(isinstance(request, dict) and set(request) == fields, 'Invalid project mapping')
        actor = actor or {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        parent = self.managed_connection(actor, request['connection_id'])
        require(not parent['revoked'] and parent['expires_at'] > time.time(), 'Workspace connection unavailable')
        uuid(request['project_id']); self.require_editor(actor, request['project_id'])
        if request['expected_mapping'] is not None:
            uuid(request['expected_mapping'])
        require(type(request['enabled']) is bool, 'Invalid propagation switch')
        for key in ('repository', 'editor_workspace', 'instructions'):
            value = request[key]
            require(isinstance(value, str) and len(value.encode()) <= (MAX_MESSAGE if key == 'instructions' else 2048)
                    and '\0' not in value and (key == 'instructions' or not any(ord(c) < 32 for c in value)), 'Invalid mapping field')
        snapshot = self.snapshot(request['project_id'], request['expected_head'], writable=True) if request['enabled'] else None
        session_id = str(uuid4())
        record = dict(session_id=session_id, connection_id=parent['connection_id'], project_id=request['project_id'],
            owner=parent['owner'], credential_ref=parent['credential_ref'], origin=parent['origin'],
            expires_at=parent['expires_at'], snapshot=snapshot, repository=request['repository'],
            editor_workspace=request['editor_workspace'], instructions=request['instructions'], bound=False)
        with self.database() as db:
            db.execute('BEGIN IMMEDIATE')
            live_parent = db.execute('SELECT revoked FROM connections WHERE id=?', (parent['connection_id'],)).fetchone()
            require(live_parent and not live_parent['revoked'], 'Workspace connection revoked')
            current = [(row['id'], json.loads(row['record'])) for row in db.execute(
                'SELECT id,record FROM sessions WHERE revoked=0')]
            current = [(id_, item) for id_, item in current if item.get('connection_id') == parent['connection_id']
                       and item['project_id'] == request['project_id']]
            require(len(current) <= 1, 'Conflicting active mappings')
            previous = current[0] if current else None
            # A lost response may be retried with its original expected_mapping.
            if previous and request['enabled'] and all(previous[1].get(k) == record.get(k) for k in
                ('snapshot', 'repository', 'editor_workspace', 'instructions')):
                return dict(session_id=previous[0], enabled=True)
            if not previous and not request['enabled'] and request['expected_mapping']:
                tombstone = db.execute('SELECT record,revoked FROM sessions WHERE id=?', (request['expected_mapping'],)).fetchone()
                if tombstone and tombstone['revoked']:
                    old = json.loads(tombstone['record'])
                    require(old.get('connection_id') == parent['connection_id'] and old['project_id'] == request['project_id'], 'Wrong disabled mapping')
                    return dict(session_id=None, enabled=False)
            require(request['expected_mapping'] == (previous[0] if previous else None), 'Mapping changed; refresh settings')
            if previous:
                db.execute('UPDATE sessions SET revoked=1 WHERE id=?', (previous[0],))
            if request['enabled']:
                db.execute('INSERT INTO sessions(id,digest,record) VALUES (?,NULL,?)', (session_id, canonical(record)))
        return dict(session_id=session_id if request['enabled'] else None, enabled=request['enabled'])

    def connection_revoke(self, actor, connection_id):
        self.managed_connection(actor or {'id': None, 'node_role': 'federation-admin'}, connection_id)
        with self.database() as db:
            db.execute('UPDATE connections SET revoked=1 WHERE id=?', (connection_id,))
        return dict(connection_id=connection_id, revoked=True)

    def connection_exchange(self, parent, request):
        require(isinstance(request, dict) and request.get('connection_id') == parent['connection_id'], 'Wrong Workspace connection')
        action = request.get('action')
        actor = self.connection_actor(parent)
        if action == 'status' and set(request) == {'connection_id', 'action'}:
            projects = self.eligible_projects(actor)
            return dict(connection_id=parent['connection_id'], name=parent['name'],
                        projects=projects, mappings=self.connection_mappings(parent['connection_id'], actor,
                            eligible={p['project_id'] for p in projects}))
        if action == 'map' and set(request) == {'connection_id', 'action', 'mapping'}:
            mapping = request['mapping']
            require(isinstance(mapping, dict) and mapping.get('connection_id') == parent['connection_id'], 'Wrong connection mapping')
            return self.configure_mapping(actor, mapping)
        if action == 'bind' and set(request) == {'connection_id', 'action', 'session_id', 'repository', 'editor_workspace'}:
            uuid(request['session_id'])
            for key in ('repository', 'editor_workspace'):
                require(isinstance(request[key], str) and 0 < len(request[key]) <= 2048
                        and not any(ord(c) < 32 for c in request[key]), 'Invalid IDE project')
            with self.database() as db:
                db.execute('BEGIN IMMEDIATE')
                live = db.execute('SELECT revoked FROM connections WHERE id=?', (parent['connection_id'],)).fetchone()
                require(live and not live['revoked'], 'Workspace connection revoked')
                row = db.execute('SELECT record,revoked FROM sessions WHERE id=?', (request['session_id'],)).fetchone()
                require(row and not row['revoked'], 'Mapping no longer active')
                record = json.loads(row['record'])
                require(record.get('connection_id') == parent['connection_id'], 'Mapping belongs to another connection')
                self.require_editor(actor, record['project_id'])
                for key in ('repository', 'editor_workspace'):
                    require(record.get(key, '') in {'', request[key]}, 'Mapping target changed; refresh settings')
                    record[key] = request[key]
                record['bound'] = True
                db.execute('UPDATE sessions SET record=? WHERE id=?', (canonical(record), request['session_id']))
            return dict(session_id=record['session_id'], project_id=record['project_id'],
                        repository=record['repository'], editor_workspace=record['editor_workspace'],
                        expires_at=record['expires_at'])
        if action == 'exchange' and set(request) == {'connection_id', 'action', 'request'}:
            child = request['request']
            require(isinstance(child, dict), 'Invalid project exchange')
            uuid(child.get('session_id'))
            with self.database() as db:
                row = db.execute('SELECT record,revoked FROM sessions WHERE id=?', (child.get('session_id'),)).fetchone()
            require(row and not row['revoked'], 'Mapping no longer active')
            record = json.loads(row['record'])
            require(record.get('connection_id') == parent['connection_id'] and record.get('bound'), 'Project not bound to this connection')
            self.require_editor(actor, record['project_id'])
            return self.exchange(record, child)
        raise ValueError('Unsupported connection action')


@contextmanager
def desktop_bridge(node, server, *, discovery_root=None):
    """Publish on every desktop start, including credentials issued before discovery."""
    service = IdeBridge(node)
    service.desktop_origin = server.origin
    service.discovery_root = discovery_root
    service.publish_endpoints()
    server.ide_bridge_service = service
    try:
        yield service
    finally:
        # Keep descriptors after exit/crash; their signatures remain valid but the
        # endpoint is offline. Next start atomically replaces them before serving UI.
        server.ide_bridge_service = None
