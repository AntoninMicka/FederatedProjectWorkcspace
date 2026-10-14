# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Bounded Google Drive Picker import with durable local staging."""
from contextlib import contextmanager
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request
from uuid import uuid4

from spikes.journal import sync_dir
from spikes.metadata import MAX_FILE, require, timestamp, uuid, validate_snapshot
from spikes.projects import Projects
from spikes.source_import import MAX_BATCH, Sources, request_from_bytes


SCOPE = 'https://www.googleapis.com/auth/drive.file'
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
GOOGLE_ISSUER = 'https://accounts.google.com'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
GOOGLE_VIEW_HOSTS = frozenset({'drive.google.com', 'docs.google.com'})
FOLDER = 'application/vnd.google-apps.folder'
EXPORTS = {
    'application/vnd.google-apps.document': ('application/pdf', '.pdf'),
    'application/vnd.google-apps.spreadsheet': ('application/pdf', '.pdf'),
    'application/vnd.google-apps.presentation': ('application/pdf', '.pdf'),
}
RAW = {
    'text/markdown': '.md',
    'application/pdf': '.pdf',
    'image/png': '.png',
    'image/jpeg': '.jpg',
}
MAX_FILES = 20
MAX_FOLDERS = 50
MAX_DEPTH = 5
MAX_PAGES = 10
MAX_EXPORT = 10 * 1024 * 1024
SESSION_SECONDS = 600
_FILE_ID = re.compile(r'[A-Za-z0-9_-]{1,200}')
_CLIENT_ID = re.compile(r'[A-Za-z0-9._-]{10,512}')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def google_time(value):
    require(isinstance(value, str), 'Drive nevrátil platný čas vzniku.')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    result = parsed.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    timestamp(result, 'source_created_at')
    return result


def safe_name(name, suffix):
    require(isinstance(name, str) and name.strip()
            and not any(ord(char) < 32 or ord(char) == 127 for char in name),
            'Drive položka nemá bezpečný název.')
    leaf = name.replace('\\', '_').replace('/', '_').strip()
    if Path(leaf).suffix.lower() not in ({'.jpg', '.jpeg'} if suffix == '.jpg' else {suffix}):
        leaf += suffix
    raw = leaf.encode('utf-8')
    if len(raw) > 200:
        stem = Path(leaf).stem
        while len((stem + suffix).encode('utf-8')) > 200:
            stem = stem[:-1]
        leaf = stem + suffix
    require(bool(Path(leaf).stem), 'Drive položka nemá bezpečný název.')
    return leaf


class DriveAccessError(ValueError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class GoogleDriveHTTP:
    """Small exact-host transport; provider bodies never enter exception text."""

    def __init__(self, timeout=60):
        self.timeout = timeout
        self.opener = build_opener(_NoRedirect)

    def _request(self, url, *, method='GET', headers=None, body=None, limit=256 * 1024):
        parsed = urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname in {
            'oauth2.googleapis.com', 'www.googleapis.com'}, 'Nepovolený Google endpoint.')
        request = Request(url, method=method, headers=headers or {}, data=body)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(limit + 1)
                require(len(raw) <= limit, 'Google odpověď překročila povolený limit.')
                return raw
        except HTTPError as exc:
            if exc.code in {400, 401, 403}:
                raise DriveAccessError('Přístup ke Google Drive byl odmítnut nebo odvolán.') from exc
            raise DriveAccessError('Google Drive požadavek selhal.') from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise DriveAccessError('Google Drive není dostupný.') from exc

    def _json(self, url, **kwargs):
        raw = self._request(url, **kwargs)
        try:
            value = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise DriveAccessError('Google Drive nevrátil platná metadata.') from exc
        require(isinstance(value, dict), 'Google Drive nevrátil platná metadata.')
        return value

    def exchange(self, client_id, client_secret, code, verifier, redirect_uri):
        body = urlencode({'client_id': client_id, 'client_secret': client_secret,
            'code': code, 'code_verifier': verifier, 'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'}).encode()
        return self._json(TOKEN_URL, method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded'}, body=body)

    def refresh(self, client_id, client_secret, refresh_token):
        body = urlencode({'client_id': client_id, 'client_secret': client_secret,
            'refresh_token': refresh_token, 'grant_type': 'refresh_token'}).encode()
        return self._json(TOKEN_URL, method='POST',
            headers={'Content-Type': 'application/x-www-form-urlencoded'}, body=body)

    @staticmethod
    def _headers(token):
        return {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}

    def metadata(self, token, file_id):
        fields = ('id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,version,'
                  'webViewLink,capabilities(canDownload),trashed,parents,driveId')
        url = ('https://www.googleapis.com/drive/v3/files/' + quote(file_id, safe='')
               + '?' + urlencode({'fields': fields, 'supportsAllDrives': 'false'}))
        return self._json(url, headers=self._headers(token))

    def children(self, token, folder_id, page_token=None):
        fields = ('nextPageToken,incompleteSearch,files(id,name,mimeType,size,md5Checksum,'
                  'modifiedTime,createdTime,version,webViewLink,capabilities(canDownload),'
                  'trashed,parents,driveId)')
        query = {'q': "'" + folder_id + "' in parents and trashed=false",
                 'spaces': 'drive', 'corpora': 'user', 'pageSize': '100',
                 'orderBy': 'name', 'fields': fields, 'supportsAllDrives': 'false',
                 'includeItemsFromAllDrives': 'false'}
        if page_token:
            query['pageToken'] = page_token
        return self._json('https://www.googleapis.com/drive/v3/files?' + urlencode(query),
                          headers=self._headers(token))

    def download(self, token, file_id, *, export_mime_type=None):
        if export_mime_type:
            url = ('https://www.googleapis.com/drive/v3/files/' + quote(file_id, safe='')
                   + '/export?' + urlencode({'mimeType': export_mime_type}))
        else:
            url = ('https://www.googleapis.com/drive/v3/files/' + quote(file_id, safe='')
                   + '?' + urlencode({'alt': 'media', 'supportsAllDrives': 'false'}))
        return self._request(url, headers={'Authorization': 'Bearer ' + token},
                             limit=MAX_FILE)


class GoogleDriveImport:
    def __init__(self, node_path, *, transport=None, timeout=60):
        self.node_path = Path(node_path).absolute()
        self.root = self.node_path.parent / ('.' + self.node_path.name + '.google-drive')
        self.database = self.root / 'google-drive.sqlite'
        self.staging = self.root / 'staging'
        self.transport = transport or GoogleDriveHTTP(timeout=timeout)

    @contextmanager
    def locked(self):
        self.root.mkdir(mode=0o700, exist_ok=True)
        info = self.root.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700
                and self.root.absolute() == self.root.resolve(),
                'Google Drive stav musí být soukromý adresář bez symlinků.')
        fd = os.open(self.root / 'writer.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            fd = os.open(self.database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            with sqlite3.connect(self.database, timeout=2) as db:
                db.executescript('''
                    PRAGMA synchronous=FULL;
                    CREATE TABLE IF NOT EXISTS configuration (
                      singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                      client_id TEXT NOT NULL, client_secret TEXT NOT NULL,
                      revision INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS tokens (
                      actor_id TEXT PRIMARY KEY, access_token TEXT NOT NULL,
                      refresh_token TEXT NOT NULL, expires_at REAL NOT NULL,
                      credential_revision INTEGER NOT NULL);
                    CREATE TABLE IF NOT EXISTS selections (
                      id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, state_sha256 TEXT NOT NULL UNIQUE,
                      verifier TEXT NOT NULL, redirect_uri TEXT NOT NULL, project_id TEXT NOT NULL,
                      expected_head TEXT NOT NULL, privacy TEXT NOT NULL,
                      credential_revision INTEGER NOT NULL, created_at REAL NOT NULL,
                      status TEXT NOT NULL, picked_ids TEXT, plan TEXT, error TEXT);
                    CREATE TABLE IF NOT EXISTS imports (
                      id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, record TEXT NOT NULL,
                      done INTEGER NOT NULL DEFAULT 0);
                    CREATE UNIQUE INDEX IF NOT EXISTS one_pending_drive_import
                      ON imports(done) WHERE done=0;
                    PRAGMA user_version=1;
                ''')
                db.commit(); sync_dir(self.root)
                yield db

    def configure(self, client_id, client_secret):
        require(isinstance(client_id, str) and bool(_CLIENT_ID.fullmatch(client_id.strip())),
                'Neplatné OAuth client ID.')
        require(isinstance(client_secret, str) and 8 <= len(client_secret) <= 512
                and not any(ord(char) < 32 for char in client_secret),
                'Neplatný OAuth client secret.')
        with self.locked() as db:
            require(not db.execute('SELECT 1 FROM imports WHERE done=0').fetchone(),
                    'Nejprve dokončete potvrzený Drive import.')
            row = db.execute('SELECT client_id,client_secret,revision FROM configuration '
                             'WHERE singleton=1').fetchone()
            if row and hmac.compare_digest(row[0], client_id.strip()) \
                    and hmac.compare_digest(row[1], client_secret):
                revision = row[2]
            else:
                revision = (row[2] + 1) if row else 1
                db.execute('INSERT INTO configuration VALUES (1,?,?,?) '
                           'ON CONFLICT(singleton) DO UPDATE SET client_id=excluded.client_id,'
                           'client_secret=excluded.client_secret,revision=excluded.revision',
                           (client_id.strip(), client_secret, revision))
                db.execute('DELETE FROM tokens')
                db.execute("UPDATE selections SET status='failed',error='credential-changed' "
                           "WHERE status IN ('authorizing','selected','planned')")
                db.commit()
            return {'configured': True, 'credential_revision': revision,
                    'scope': SCOPE, 'client_id_hint': client_id.strip()[-24:]}

    def status(self, actor_id=None):
        if not self.database.exists():
            return {'configured': False, 'credential_revision': None, 'scope': SCOPE,
                    'pending_import': False, 'pending_selection': None}
        with self.locked() as db:
            row = db.execute('SELECT client_id,revision FROM configuration WHERE singleton=1').fetchone()
            selection = None
            if actor_id is None:
                pending = db.execute('SELECT 1 FROM imports WHERE done=0').fetchone()
            else:
                actor_id = self._actor(actor_id)
                pending = db.execute('SELECT 1 FROM imports WHERE done=0 AND actor_id=?',
                                     (actor_id,)).fetchone()
                if row:
                    selected = db.execute(
                        "SELECT id,project_id,expected_head,privacy,status FROM selections "
                        "WHERE actor_id=? AND credential_revision=? "
                        "AND status IN ('selected','planned') ORDER BY created_at DESC LIMIT 1",
                        (actor_id, row[1])).fetchone()
                    if selected:
                        selection = {'selection_id': selected[0], 'project_id': selected[1],
                                     'expected_head': selected[2], 'privacy': selected[3],
                                     'status': selected[4]}
            return {'configured': bool(row), 'credential_revision': row[1] if row else None,
                    'scope': SCOPE, 'client_id_hint': row[0][-24:] if row else None,
                    'pending_import': bool(pending), 'pending_selection': selection}

    @staticmethod
    def _actor(actor_id):
        uuid(actor_id); return actor_id

    def authorize(self, actor_id, request, redirect_uri):
        actor_id = self._actor(actor_id)
        require(isinstance(request, dict) and set(request) == {
            'project_id', 'expected_head', 'privacy'}, 'Neplatný Drive výběr.')
        uuid(request['project_id'])
        require(request['privacy'] in {'public', 'project', 'confidential', 'local-only'},
                'Neplatná privacy Drive importu.')
        project = Projects(self.node_path).open(request['project_id'])
        require(project['commit_id'] == request['expected_head'],
                'Projekt se změnil. Otevřete jej znovu.')
        parsed = urlsplit(redirect_uri)
        desktop_callback = (parsed.scheme == 'http' and parsed.hostname == '127.0.0.1'
                            and parsed.path in {'', '/'})
        web_callback = (parsed.scheme == 'https'
                        and parsed.path == '/oauth/google-drive/callback')
        require(not parsed.query and not parsed.fragment and not parsed.username
                and not parsed.password and (desktop_callback or web_callback),
                'Neplatná OAuth callback adresa.')
        selection_id, state = str(uuid4()), secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        with self.locked() as db:
            config = db.execute('SELECT client_id,revision FROM configuration WHERE singleton=1').fetchone()
            require(config is not None, 'Nejprve nastavte Google OAuth klienta.')
            db.execute('INSERT INTO selections VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (selection_id, actor_id, hashlib.sha256(state.encode()).hexdigest(), verifier,
                 redirect_uri, request['project_id'], request['expected_head'], request['privacy'],
                 config[1], time.time(), 'authorizing', None, None, None))
            db.commit()
        query = {'client_id': config[0], 'scope': SCOPE, 'redirect_uri': redirect_uri,
                 'response_type': 'code', 'access_type': 'offline', 'prompt': 'consent',
                 'trigger_onepick': 'true', 'allow_multiple': 'true',
                 'allow_folder_selection': 'true', 'state': state,
                 'code_challenge': challenge, 'code_challenge_method': 'S256',
                 'include_granted_scopes': 'false'}
        return {'selection_id': selection_id, 'authorization_url': AUTH_URL + '?' + urlencode(query),
                'scope': SCOPE, 'expires_in': SESSION_SECONDS}

    def callback(self, state, code, picked_file_ids, error=None):
        require(isinstance(state, str) and 20 <= len(state) <= 256,
                'Neplatný OAuth state.')
        state_sha = hashlib.sha256(state.encode()).hexdigest()
        with self.locked() as db:
            row = db.execute('SELECT * FROM selections WHERE state_sha256=?', (state_sha,)).fetchone()
            require(row is not None and row[10] == 'authorizing'
                    and time.time() - row[9] <= SESSION_SECONDS,
                    'OAuth výběr neexistuje nebo vypršel.')
            if error:
                db.execute("UPDATE selections SET status='failed',error='cancelled' WHERE id=?",
                           (row[0],)); db.commit()
                return {'selection_id': row[0], 'status': 'failed'}
            require(isinstance(code, str) and 1 <= len(code) <= 4096,
                    'Google nevrátil autorizační kód.')
            picked = picked_file_ids.split(',') if isinstance(picked_file_ids, str) else []
            require(1 <= len(picked) <= MAX_FILES and all(_FILE_ID.fullmatch(item) for item in picked)
                    and len(set(picked)) == len(picked), 'Google Picker nevrátil platný výběr.')
            config = db.execute('SELECT client_id,client_secret,revision FROM configuration '
                                'WHERE singleton=1').fetchone()
            require(config is not None and config[2] == row[8],
                    'OAuth konfigurace se během výběru změnila.')
            token = self.transport.exchange(config[0], config[1], code, row[3], row[4])
            access = token.get('access_token'); refresh = token.get('refresh_token')
            require(isinstance(access, str) and access and isinstance(refresh, str) and refresh,
                    'Google nevrátil obnovitelný per-file token.')
            require(token.get('scope') in (None, SCOPE)
                    and token.get('token_type', 'Bearer') == 'Bearer',
                    'Google vrátil jiný OAuth scope nebo token type.')
            expires = token.get('expires_in', 3600)
            require(type(expires) is int and 60 <= expires <= 86400,
                    'Google vrátil neplatnou expiraci tokenu.')
            db.execute('INSERT INTO tokens VALUES (?,?,?,?,?) ON CONFLICT(actor_id) DO UPDATE SET '
                       'access_token=excluded.access_token,refresh_token=excluded.refresh_token,'
                       'expires_at=excluded.expires_at,credential_revision=excluded.credential_revision',
                       (row[1], access, refresh, time.time() + expires, row[8]))
            db.execute("UPDATE selections SET status='selected',picked_ids=? WHERE id=?",
                       (canonical(picked), row[0])); db.commit()
            return {'selection_id': row[0], 'status': 'selected'}

    def _token(self, db, actor_id, credential_revision):
        config = db.execute('SELECT client_id,client_secret,revision FROM configuration '
                            'WHERE singleton=1').fetchone()
        require(config is not None and config[2] == credential_revision,
                'Google OAuth konfigurace se změnila.')
        row = db.execute('SELECT access_token,refresh_token,expires_at,credential_revision '
                         'FROM tokens WHERE actor_id=?', (actor_id,)).fetchone()
        require(row is not None and row[3] == credential_revision,
                'Google Drive přístup chybí nebo byl změněn.')
        if row[2] > time.time() + 30:
            return row[0]
        token = self.transport.refresh(config[0], config[1], row[1])
        access, expires = token.get('access_token'), token.get('expires_in', 3600)
        require(isinstance(access, str) and access and type(expires) is int
                and 60 <= expires <= 86400, 'Google neobnovil platný access token.')
        db.execute('UPDATE tokens SET access_token=?,expires_at=? WHERE actor_id=?',
                   (access, time.time() + expires, actor_id)); db.commit()
        return access

    @staticmethod
    def _validate_metadata(item):
        required = {'id', 'name', 'mimeType', 'createdTime', 'modifiedTime',
                    'version', 'capabilities', 'trashed'}
        require(isinstance(item, dict) and required <= item.keys()
                and isinstance(item['id'], str) and _FILE_ID.fullmatch(item['id'])
                and item['trashed'] is False and not item.get('driveId')
                and isinstance(item['capabilities'], dict)
                and (item['mimeType'] == FOLDER
                     or item['capabilities'].get('canDownload') is True),
                'Drive položka není dostupná ke stažení nebo patří Shared Drive.')
        require(isinstance(item['version'], str) and item['version'].isdigit(),
                'Drive položka nemá stabilní revizi.')
        return item

    def _selection_files(self, token, picked):
        roots = [self._validate_metadata(self.transport.metadata(token, item)) for item in picked]
        folders = [item for item in roots if item['mimeType'] == FOLDER]
        require(not folders or len(roots) == 1,
                'Vyberte buď jednu složku, nebo jednotlivé soubory.')
        if not folders:
            return roots
        files, queue, visited, pages = [], [(folders[0], 0)], set(), 0
        while queue:
            folder, depth = queue.pop(0)
            require(depth < MAX_DEPTH and len(visited) < MAX_FOLDERS,
                    'Vybraná složka překračuje limit hloubky nebo počtu složek.')
            require(folder['id'] not in visited, 'Drive složka obsahuje cyklus.')
            visited.add(folder['id']); page_token = None
            while True:
                pages += 1; require(pages <= MAX_PAGES, 'Vybraná složka má příliš mnoho stránek.')
                result = self.transport.children(token, folder['id'], page_token)
                require(result.get('incompleteSearch') in (None, False)
                        and isinstance(result.get('files'), list),
                        'Google Drive vrátil neúplný seznam složky.')
                for raw in result['files']:
                    item = self._validate_metadata(raw)
                    if item['mimeType'] == FOLDER:
                        queue.append((item, depth + 1))
                    else:
                        files.append(item)
                        require(len(files) <= MAX_FILES,
                                'Vybraná složka obsahuje více než 20 souborů.')
                page_token = result.get('nextPageToken')
                if not page_token:
                    break
                require(isinstance(page_token, str) and len(page_token) <= 4096,
                        'Google Drive vrátil neplatné stránkování.')
        require(files, 'Vybraná složka neobsahuje podporovaný soubor.')
        return files

    @staticmethod
    def _signature(item):
        return {key: item.get(key) for key in ('id', 'name', 'mimeType', 'size',
            'md5Checksum', 'modifiedTime', 'createdTime', 'version', 'webViewLink', 'driveId')}

    def _project_sources(self, project_id, head):
        ws = Projects(self.node_path).workspace(project_id, blocking=False,
                                                  deadline=time.monotonic() + 30)
        with ws.journal.lock(), ws.journal.connect() as db:
            require(not db.execute('SELECT 1 FROM pending').fetchone(),
                    'Projekt má nedokončenou Workspace operaci.')
            require(ws.git.head() == head, 'Projekt se změnil. Obnovte Drive náhled.')
            files = ws.git.snapshot(head); entities = validate_snapshot(files)
            return [(id_, meta) for id_, meta in entities.items() if meta['kind'] == 'source']

    def _build_plan(self, db, row):
        token = self._token(db, row[1], row[8])
        picked = json.loads(row[11])
        files = self._selection_files(token, picked)
        existing = self._project_sources(row[5], row[6])
        planned, blockers, declared = [], [], 0
        for item in files:
            mime = item['mimeType']
            export = EXPORTS.get(mime)
            if export:
                export_mime, suffix = export
            else:
                require(mime in RAW, 'Drive výběr obsahuje nepodporovaný typ souboru.')
                export_mime, suffix = None, RAW[mime]
                size = item.get('size')
                require(isinstance(size, str) and size.isdigit() and int(size) <= MAX_FILE,
                        'Drive soubor přesahuje 16 MiB nebo nemá doloženou velikost.')
                declared += int(size)
            require(declared <= MAX_BATCH, 'Drive výběr přesahuje 64 MiB.')
            url = item.get('webViewLink')
            try:
                parsed_url = urlsplit(url) if isinstance(url, str) else None
                valid_url = (parsed_url is not None and parsed_url.scheme == 'https'
                             and parsed_url.hostname in GOOGLE_VIEW_HOSTS
                             and parsed_url.username is None and parsed_url.password is None
                             and parsed_url.port is None and bool(parsed_url.path))
            except ValueError:
                valid_url = False
            require(valid_url, 'Drive vrátil neplatný odkaz na zdroj.')
            matches = [(id_, meta) for id_, meta in existing if url and meta.get('source_url') == url]
            same = [id_ for id_, meta in matches
                    if meta.get('import', {}).get('source_revision') == item['version']]
            supersedes = None
            if same:
                blockers.append('Revize „' + item['name'] + '“ už je v projektu importována.')
            elif len(matches) == 1:
                supersedes = matches[0][0]
            elif len(matches) > 1:
                blockers.append('Zdroj „' + item['name']
                                + '“ má více předchůdců; novou revizi určete ručně.')
            planned.append({'file_id': item['id'], 'name': item['name'],
                'filename': safe_name(item['name'], suffix), 'title': item['name'],
                'source_url': url, 'source_created_at': google_time(item['createdTime']),
                'source_revision': item['version'], 'source_mime_type': mime,
                'export_mime_type': export_mime, 'size': item.get('size'),
                'md5_checksum': item.get('md5Checksum'), 'supersedes': supersedes,
                'metadata': self._signature(item)})
        plan = {'selection_id': row[0], 'project_id': row[5], 'expected_head': row[6],
                'privacy': row[7], 'credential_revision': row[8], 'files': planned,
                'file_count': len(planned), 'declared_blob_bytes': declared,
                'export_limit_bytes': MAX_EXPORT, 'total_limit_bytes': MAX_BATCH,
                'scope': SCOPE, 'writes_to_drive': False, 'continuous_sync': False,
                'blockers': blockers}
        plan['preview_sha256'] = digest(plan)
        return plan

    def preview(self, actor_id, selection_id):
        actor_id = self._actor(actor_id); uuid(selection_id)
        with self.locked() as db:
            row = db.execute('SELECT * FROM selections WHERE id=?', (selection_id,)).fetchone()
            require(row is not None and row[1] == actor_id, 'Drive výběr není dostupný.')
            if row[10] == 'authorizing':
                return {'selection_id': selection_id, 'status': 'authorizing'}
            require(row[10] in {'selected', 'planned'}, 'Drive výběr selhal nebo vypršel.')
            plan = self._build_plan(db, row)
            db.execute("UPDATE selections SET status='planned',plan=? WHERE id=?",
                       (canonical(plan), selection_id)); db.commit()
            return {'selection_id': selection_id, 'status': 'planned', 'plan': plan}

    def confirm(self, actor_id, plan, operation_id):
        actor_id = self._actor(actor_id); uuid(operation_id)
        require(isinstance(plan, dict), 'Neplatný Drive importní plán.')
        with self.locked() as db:
            existing = db.execute('SELECT record,done FROM imports WHERE id=?',
                                  (operation_id,)).fetchone()
            if existing:
                record = json.loads(existing[0])
                require(record['actor_id'] == actor_id
                        and hmac.compare_digest(record['plan_digest'], digest(plan)),
                        'ID operace už patří jinému Drive importu.')
                return record['receipt'] if existing[1] else self._finish(db, record)
            selection_id = plan.get('selection_id'); uuid(selection_id)
            row = db.execute('SELECT * FROM selections WHERE id=?', (selection_id,)).fetchone()
            require(row is not None and row[1] == actor_id and row[10] == 'planned'
                    and json.loads(row[12]) == plan,
                    'Drive plán nebyl vydán tímto backendem nebo se změnil.')
            require(not plan['blockers'], 'Drive plán obsahuje blokující duplicitu.')
            current = self._build_plan(db, row)
            require(current == plan, 'Drive výběr, revize nebo projekt se změnily.')
            require(not db.execute('SELECT 1 FROM imports WHERE done=0').fetchone(),
                    'Nejprve dokončete jiný Drive import.')
            record = {'operation_id': operation_id, 'actor_id': actor_id,
                'plan': plan, 'plan_digest': digest(plan), 'created_at': utc_now(),
                'artifact_ids': {item['file_id']: str(uuid4()) for item in plan['files']},
                'downloads': {}, 'receipt': None}
            db.execute('INSERT INTO imports VALUES (?,?,?,0)',
                       (operation_id, actor_id, canonical(record))); db.commit()
            return self._finish(db, record)

    def _save(self, db, record, done=False):
        db.execute('UPDATE imports SET record=?,done=? WHERE id=?',
                   (canonical(record), int(done), record['operation_id'])); db.commit()

    def _stage(self, record, item, token):
        directory = self.staging / record['operation_id']
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700
                and directory.absolute() == directory.resolve(), 'Neplatný Drive staging.')
        target = directory / item['file_id']
        known = record['downloads'].get(item['file_id'])
        if known and target.exists():
            raw = target.read_bytes()
            require(len(raw) == known['size'] and hashlib.sha256(raw).hexdigest() == known['sha256'],
                    'Stažený Drive staging byl změněn.')
            return raw
        before = self._validate_metadata(self.transport.metadata(token, item['file_id']))
        require(self._signature(before) == item['metadata'], 'Drive soubor se od náhledu změnil.')
        raw = self.transport.download(token, item['file_id'],
                                      export_mime_type=item['export_mime_type'])
        require(len(raw) <= MAX_FILE, 'Stažený nebo exportovaný soubor přesahuje 16 MiB.')
        if item['export_mime_type']:
            require(len(raw) <= MAX_EXPORT, 'Google export přesahuje limit 10 MiB.')
        after = self._validate_metadata(self.transport.metadata(token, item['file_id']))
        require(self._signature(after) == item['metadata'], 'Drive soubor se během stahování změnil.')
        if item['md5_checksum'] and not item['export_mime_type']:
            require(hashlib.md5(raw, usedforsecurity=False).hexdigest() == item['md5_checksum'],
                    'Stažené Drive bajty neodpovídají providerovému MD5.')
        temporary = target.with_suffix('.part')
        if temporary.exists(): temporary.unlink()
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, target); sync_dir(directory)
        return raw

    def _finish(self, db, record):
        plan = record['plan']
        token = self._token(db, record['actor_id'], plan['credential_revision'])
        requests, total = [], 0
        for item in plan['files']:
            raw = self._stage(record, item, token); total += len(raw)
            require(total <= MAX_BATCH, 'Stažená Drive dávka přesahuje 64 MiB.')
            sha = hashlib.sha256(raw).hexdigest()
            record['downloads'][item['file_id']] = {'sha256': sha, 'size': len(raw)}
            self._save(db, record)
            request = request_from_bytes(plan['project_id'], plan['expected_head'],
                item['filename'], raw, item['title'], '', ['google-drive'], plan['privacy'],
                source_url=item['source_url'], source_created_at=item['source_created_at'],
                source_revision=item['source_revision'], supersedes=item['supersedes'],
                source_mime_type=item['source_mime_type'],
                export_mime_type=item['export_mime_type'])
            request['artifact_id'] = record['artifact_ids'][item['file_id']]
            request['created_at'] = record['created_at']
            requests.append(request)
        receipt = Sources(self.node_path).import_sources(requests, record['operation_id'],
            author_id=record['actor_id'])
        record['receipt'] = {'operation_id': record['operation_id'],
            'project_id': plan['project_id'], 'commit_id': receipt['commit_id'],
            'artifact_ids': list(record['artifact_ids'].values()),
            'file_count': len(requests), 'total_bytes': total}
        self._save(db, record, done=True)
        directory = self.staging / record['operation_id']
        if directory.exists():
            shutil.rmtree(directory); sync_dir(directory.parent)
        return record['receipt']

    def recover(self, actor_id=None):
        if not self.database.exists():
            return None
        with self.locked() as db:
            query, values = 'SELECT record FROM imports WHERE done=0', ()
            if actor_id is not None:
                query += ' AND actor_id=?'; values = (self._actor(actor_id),)
            row = db.execute(query, values).fetchone()
            return self._finish(db, json.loads(row[0])) if row else None

    def pending(self, actor_id):
        if not self.database.exists():
            return None
        with self.locked() as db:
            row = db.execute('SELECT record FROM imports WHERE done=0 AND actor_id=?',
                             (self._actor(actor_id),)).fetchone()
            if not row:
                return None
            record = json.loads(row[0])
            return {'project_id': record['plan']['project_id'],
                    'privacy': record['plan']['privacy']}

    def selection(self, actor_id, selection_id):
        uuid(selection_id)
        if not self.database.exists():
            return None
        with self.locked() as db:
            row = db.execute('SELECT project_id,privacy FROM selections '
                             'WHERE id=? AND actor_id=?',
                             (selection_id, self._actor(actor_id))).fetchone()
            return {'project_id': row[0], 'privacy': row[1]} if row else None
