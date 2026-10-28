# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node-local, scoped IDE mailboxes. No project writer and no agent invocation."""
import base64
from contextlib import contextmanager
import hashlib
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
        with sqlite3.connect(path, timeout=5) as db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TABLE IF NOT EXISTS sessions '
                       '(id TEXT PRIMARY KEY, digest TEXT UNIQUE, record TEXT NOT NULL, revoked INTEGER DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS messages '
                       '(session TEXT, id TEXT, digest TEXT, record TEXT, receipt TEXT, PRIMARY KEY(session,id))')
            yield db

    def snapshot(self, project_id, expected_head):
        uuid(project_id)
        view = self.projects.open(project_id)
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
        pairing = dict(schema_version=1, session_id=session_id, token=token,
                       endpoint=record['origin'], repository=repository,
                       project_id=request['project_id'], expires_at=record['expires_at'])
        return dict(session_id=session_id, pairing=pairing,
                    package_base64=base64.b64encode(self.package(pairing)).decode(),
                    filename='workspace-bridge.vsix', revision=snapshot['revision'])

    def package(self, pairing):
        """Small dependency-free VSIX; session secret exists only in generated bytes."""
        manifest = json.loads((EXTENSION / 'package.json').read_text())
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('package.json', 'extension.js', 'bridge.js', 'README.md', 'LICENSE'):
                archive.writestr('extension/' + name, (EXTENSION / name).read_bytes())
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
        if self.network and record['owner'] is not None:
            administration = Administration(self.node)
            with administration.read_locked() as state:
                actor = next((u for u in state['users'] if u['id'] == record['owner']
                              and u['active'] and u['credential_ref'] == record['credential_ref']), None)
                require(Administration.allowed(actor, record['project_id']), 'Project access revoked')
                require(Administration.is_admin(actor) or actor['memberships'].get(
                    record['project_id']) in {'editor', 'project-admin'}, 'Project write access revoked')
        return record

    def exchange(self, record, request):
        require(isinstance(request, dict) and set(request) == {'session_id', 'messages'}
                and request['session_id'] == record['session_id'], 'Wrong bridge session')
        messages = request['messages']
        require(isinstance(messages, list) and len(messages) <= 20, 'Too many messages')
        # Revalidate privacy/current HEAD even for credential-only polls and retries.
        view = self.projects.open(record['project_id'])
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
                sessions.append(dict(session_id=row['id'], repository=record['repository'],
                                     revision=record['snapshot']['revision'], revoked=bool(row['revoked']),
                                     expires_at=record['expires_at'], messages=messages))
        return dict(sessions=sessions)

    def revoke(self, project_id, session_id):
        uuid(project_id); uuid(session_id)
        with self.database() as db:
            row = db.execute('SELECT record FROM sessions WHERE id=?', (session_id,)).fetchone()
            require(row and json.loads(row['record'])['project_id'] == project_id, 'Wrong project')
            db.execute('UPDATE sessions SET revoked=1 WHERE id=?', (session_id,))
        return dict(session_id=session_id, revoked=True)
