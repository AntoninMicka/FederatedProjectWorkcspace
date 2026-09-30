# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Cloudflare Workers deployment adapter for one host-routed publication portal."""
import base64
from contextlib import contextmanager
from datetime import date
import fcntl
import hashlib
import http.client
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import ssl
import stat
from urllib.parse import quote

from spikes.metadata import require, uuid


API_HOST = 'api.cloudflare.com'
PORTAL_ID = 'main'
MAX_RESPONSE = 4 * 1024 * 1024
MAX_ASSETS = 1000
MAX_ASSET_BYTES = 25 * 1024 * 1024
ACCOUNT_ID = re.compile(r'[0-9a-f]{32}')
WORKER_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,62}')
WORKER_SCRIPT = '''const HOSTS = new Set(__HOSTS__);
export default {
  async fetch(request, env) {
    if (request.method !== "GET" && request.method !== "HEAD")
      return new Response("Method not allowed", {status: 405});
    const url = new URL(request.url);
    const hostname = url.hostname.toLowerCase();
    if (!HOSTS.has(hostname)) return new Response("Unknown host", {status: 404});
    const path = url.pathname === "/" ? "/index.html" : url.pathname;
    const assetUrl = new URL("/" + hostname + path, url.origin);
    return env.ASSETS.fetch(new Request(assetUrl, {method: request.method, headers: request.headers}));
  }
};
'''


class CloudflareUnavailable(RuntimeError):
    """Provider could not be read safely."""


class CloudflareUnknown(RuntimeError):
    """A mutation may have reached the provider and must not be retried."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode()


def _atomic_write(path, data):
    temporary = path.parent / ('.' + path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.close(fd); fd = -1
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary.exists():
            temporary.unlink()


class CloudflareTransport:
    """Small stdlib client for the documented Workers static-assets API."""
    def __init__(self, timeout=30):
        self.timeout = timeout

    def _request(self, method, path, token, *, value=None, body=None, content_type=None,
                 accepted=(200,)):
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
        if value is not None:
            body = _canonical(value); content_type = 'application/json'
        if content_type:
            headers['Content-Type'] = content_type
        connection = http.client.HTTPSConnection(
            API_HOST, 443, timeout=self.timeout, context=ssl.create_default_context())
        try:
            connection.request(method, '/client/v4' + path, body=body, headers=headers)
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise CloudflareUnavailable('Cloudflare redirect is forbidden')
            raw = response.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                raise CloudflareUnavailable('Cloudflare response exceeds 4 MiB')
            if response.status == 404:
                return None
            if response.status not in accepted:
                raise CloudflareUnavailable('Cloudflare rejected the request with HTTP '
                                             + str(response.status))
            try:
                envelope = json.loads(raw)
            except (UnicodeError, ValueError) as exc:
                raise CloudflareUnavailable('Cloudflare returned invalid JSON') from exc
            if not isinstance(envelope, dict) or envelope.get('success') is not True:
                raise CloudflareUnavailable('Cloudflare returned an unsuccessful response')
            return envelope.get('result')
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise CloudflareUnavailable('Cloudflare is unavailable') from exc
        finally:
            connection.close()

    @staticmethod
    def _path(binding, suffix=''):
        account = quote(binding['account_id'], safe='')
        worker = quote(binding['worker_name'], safe='')
        return f'/accounts/{account}/workers/scripts/{worker}{suffix}'

    def status(self, binding, token):
        worker = self._request('GET', self._path(binding).replace('/scripts/', '/workers/'), token)
        if worker is None:
            return {'exists': False, 'version_id': None, 'release_sha256': None,
                    'deployment_id': None}
        value = self._request('GET', self._path(binding, '/deployments'), token)
        deployments = value.get('deployments', []) if isinstance(value, dict) else []
        if not deployments:
            return {'exists': True, 'version_id': None, 'release_sha256': None,
                    'deployment_id': None}
        deployment = deployments[0]
        versions = deployment.get('versions', []) if isinstance(deployment, dict) else []
        active = next((item for item in versions if item.get('percentage') == 100), None)
        if not active:
            return {'exists': True, 'version_id': None, 'release_sha256': None,
                    'deployment_id': deployment.get('id'), 'drifted': True}
        version_id = active.get('version_id')
        require(isinstance(version_id, str) and bool(version_id),
                'Invalid Cloudflare active deployment version')
        detail = self._request('GET', self._path(binding).replace('/scripts/', '/workers/')
                               + '/versions/' + quote(version_id, safe=''), token)
        annotations = detail.get('annotations', {}) if isinstance(detail, dict) else {}
        tag = annotations.get('workers/tag') if isinstance(annotations, dict) else None
        return {'exists': True, 'version_id': version_id,
                'release_sha256': tag if isinstance(tag, str) else None,
                'deployment_id': deployment.get('id'), 'drifted': False}

    @staticmethod
    def _assets(output, hostnames):
        result = {}
        total = 0
        for hostname in hostnames:
            root = output / hostname
            require(root.is_dir() and not root.is_symlink(),
                    'Generated site output is unavailable')
            for path in sorted(root.rglob('*')):
                if path.is_dir():
                    continue
                require(path.is_file() and not path.is_symlink()
                        and path.resolve().is_relative_to(root.resolve()),
                        'Generated site output contains an unsafe file')
                data = path.read_bytes(); total += len(data)
                require(len(result) < MAX_ASSETS and total <= MAX_ASSET_BYTES,
                        'Publication assets exceed adapter limits')
                relative = path.relative_to(root).as_posix()
                extension = path.suffix.lstrip('.')
                digest = hashlib.sha256(base64.b64encode(data) + extension.encode()).hexdigest()[:32]
                result['/' + hostname + '/' + relative] = {
                    'hash': digest, 'size': len(data), 'data': data,
                    'content_type': mimetypes.guess_type(path.name)[0] or 'application/octet-stream'}
        require(bool(result), 'Publication release has no generated assets')
        return result

    @staticmethod
    def _multipart(fields):
        boundary = 'fpw-' + os.urandom(18).hex()
        chunks = []
        for name, content_type, value in fields:
            chunks.extend([('--' + boundary + '\r\n').encode(),
                ('Content-Disposition: form-data; name="' + name + '"\r\n').encode(),
                ('Content-Type: ' + content_type + '\r\n\r\n').encode(), value, b'\r\n'])
        chunks.append(('--' + boundary + '--\r\n').encode())
        return b''.join(chunks), 'multipart/form-data; boundary=' + boundary

    def deploy(self, binding, token, output, hostnames, release_sha256, compatibility_date):
        assets = self._assets(output, hostnames)
        manifest = {path: {'hash': item['hash'], 'size': item['size']}
                    for path, item in assets.items()}
        session = self._request('POST', self._path(binding, '/assets-upload-session'), token,
                                value={'manifest': manifest})
        require(isinstance(session, dict) and isinstance(session.get('jwt'), str)
                and isinstance(session.get('buckets'), list), 'Invalid Cloudflare upload session')
        upload_token = session['jwt']
        completion = upload_token if not session['buckets'] else None
        by_hash = {item['hash']: item for item in assets.values()}
        for bucket in session['buckets']:
            require(isinstance(bucket, list) and all(item in by_hash for item in bucket),
                    'Invalid Cloudflare asset bucket')
            fields = [(digest, by_hash[digest]['content_type'],
                       base64.b64encode(by_hash[digest]['data'])) for digest in bucket]
            body, content_type = self._multipart(fields)
            uploaded = self._request('POST', f"/accounts/{binding['account_id']}/workers/assets/upload?base64=true",
                                     upload_token, body=body, content_type=content_type,
                                     accepted=(200, 201))
            require(isinstance(uploaded, dict), 'Invalid Cloudflare asset upload response')
            if isinstance(uploaded.get('jwt'), str):
                completion = uploaded['jwt']
        require(isinstance(completion, str),
                'Cloudflare asset upload did not return a completion token')
        script = WORKER_SCRIPT.replace('__HOSTS__', json.dumps(hostnames))
        version = self._request('POST', self._path(binding).replace('/scripts/', '/workers/')
                                + '/versions', token, value={
            'main_module': 'main.js', 'compatibility_date': compatibility_date,
            'annotations': {'workers/tag': release_sha256,
                            'workers/message': 'Federated Workspace publication release'},
            'bindings': [{'type': 'assets', 'name': 'ASSETS'}],
            'assets': {'jwt': completion},
            'modules': [{'name': 'main.js', 'content_type': 'application/javascript+module',
                         'content_base64': base64.b64encode(script.encode()).decode()}]})
        require(isinstance(version, dict) and isinstance(version.get('id'), str),
                'Invalid Cloudflare Worker version response')
        deployment = self._request('POST', self._path(binding, '/deployments'), token, value={
            'strategy': 'percentage',
            'versions': [{'percentage': 100, 'version_id': version['id']}],
            'annotations': {'workers/message': 'Federated Workspace publication release'}})
        require(isinstance(deployment, dict) and isinstance(deployment.get('id'), str),
                'Invalid Cloudflare deployment response')
        return {'version_id': version['id'], 'deployment_id': deployment['id']}


class PublicationDeployment:
    """Node-local binding, credentials and irreversible operation journal."""
    def __init__(self, state_dir, release_resolver, transport=None):
        self.state_dir = Path(state_dir).absolute()
        self.release_resolver = release_resolver
        self.transport = transport or CloudflareTransport()

    def _root(self):
        info = self.state_dir.lstat()
        require(self.state_dir.resolve() == self.state_dir and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                'Deployment state directory requires owned mode 0700 without symlinks')
        return self.state_dir

    @property
    def binding_path(self):
        return self._root() / 'publication-deployment-binding.json'

    @property
    def database_path(self):
        return self._root() / 'publication-deployments.sqlite'

    def _database(self):
        fd = os.open(self.database_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe publication deployment store')
        db = sqlite3.connect(self.database_path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS credentials ('
                   'portal_id TEXT PRIMARY KEY, secret TEXT NOT NULL, revision INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS operations ('
                   'operation_id TEXT PRIMARY KEY, request_sha256 TEXT NOT NULL, '
                   'request_json TEXT NOT NULL, state TEXT NOT NULL, receipt_json TEXT, error TEXT)')
        db.commit()
        return db

    @contextmanager
    def _writer(self):
        fd = os.open(self._root() / 'publication-deployments.lock',
                     os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX); yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)

    def _binding(self):
        fd = os.open(self.binding_path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe publication deployment binding')
            raw = os.read(fd, 65537)
        finally:
            os.close(fd)
        require(len(raw) <= 65536, 'Deployment binding exceeds size limit')
        value = json.loads(raw)
        require(isinstance(value, dict) and set(value) == {
            'schema_version', 'portal_id', 'provider', 'account_id', 'worker_name',
            'credential_revision'} and value['schema_version'] == 1
            and value['portal_id'] == PORTAL_ID and value['provider'] == 'cloudflare'
            and isinstance(value['account_id'], str) and ACCOUNT_ID.fullmatch(value['account_id'])
            and isinstance(value['worker_name'], str) and WORKER_NAME.fullmatch(value['worker_name'])
            and type(value['credential_revision']) is int and value['credential_revision'] >= 1,
            'Invalid publication deployment binding')
        return value

    def _credential(self, binding):
        with self._database() as db:
            row = db.execute('SELECT secret,revision FROM credentials WHERE portal_id=?',
                             (binding['portal_id'],)).fetchone()
        require(row is not None and row[1] == binding['credential_revision'],
                'Cloudflare credential is unavailable or changed')
        return row[0]

    def configure(self, request):
        require(isinstance(request, dict) and set(request) == {
            'portal_id', 'provider', 'account_id', 'worker_name', 'api_token'}
            and request['portal_id'] == PORTAL_ID and request['provider'] == 'cloudflare'
            and isinstance(request['account_id'], str) and ACCOUNT_ID.fullmatch(request['account_id'])
            and isinstance(request['worker_name'], str) and WORKER_NAME.fullmatch(request['worker_name'])
            and isinstance(request['api_token'], str) and request['api_token'].strip() == request['api_token']
            and 20 <= len(request['api_token']) <= 4096
            and not any(char in request['api_token'] for char in '\0\r\n'),
            'Invalid Cloudflare publication binding')
        with self._writer(), self._database() as db:
            pending = db.execute("SELECT 1 FROM operations WHERE state IN ('dispatching','unknown') LIMIT 1").fetchone()
            require(not pending, 'Resolve the unknown deployment before changing its binding')
            row = db.execute('SELECT revision FROM credentials WHERE portal_id=?', (PORTAL_ID,)).fetchone()
            revision = (row[0] + 1) if row else 1
            db.execute('INSERT INTO credentials VALUES(?,?,?) ON CONFLICT(portal_id) DO UPDATE SET '
                       'secret=excluded.secret,revision=excluded.revision',
                       (PORTAL_ID, request['api_token'], revision)); db.commit()
            binding = {'schema_version': 1, 'portal_id': PORTAL_ID, 'provider': 'cloudflare',
                       'account_id': request['account_id'], 'worker_name': request['worker_name'],
                       'credential_revision': revision}
            _atomic_write(self.binding_path, _canonical(binding) + b'\n')
        return {'configured': True, 'binding': binding,
                'message': 'Cloudflare připojení bylo uloženo pouze na tomto uzlu.'}

    @staticmethod
    def _summary(provider, release_sha256, hostnames):
        if not provider['exists']:
            state = 'missing'
        elif provider.get('drifted'):
            state = 'drifted'
        elif not provider.get('version_id'):
            state = 'partial'
        elif provider.get('release_sha256') == release_sha256:
            state = 'current'
        else:
            state = 'outdated'
        return {'state': state, 'release_sha256': release_sha256,
                'provider_release_sha256': provider.get('release_sha256'),
                'version_id': provider.get('version_id'),
                'deployment_id': provider.get('deployment_id'),
                'domains': [{'hostname': hostname, 'content': state,
                             'custom_domain': 'unmanaged'} for hostname in hostnames]}

    def _reconcile(self, provider):
        with self._database() as db:
            rows = db.execute("SELECT operation_id,request_json FROM operations "
                              "WHERE state IN ('dispatching','unknown') ORDER BY rowid").fetchall()
            for operation_id, raw in rows:
                request = json.loads(raw)
                if provider.get('release_sha256') == request['release_sha256']:
                    receipt = {'operation_id': operation_id, 'state': 'completed',
                               'release_sha256': request['release_sha256'],
                               'version_id': provider.get('version_id'),
                               'deployment_id': provider.get('deployment_id'),
                               'reconciled': True}
                    db.execute("UPDATE operations SET state='completed',receipt_json=?,error=NULL "
                               "WHERE operation_id=? AND state IN ('dispatching','unknown')",
                               (json.dumps(receipt, sort_keys=True), operation_id))
            db.commit()

    def _has_unknown(self):
        with self._database() as db:
            return db.execute("SELECT 1 FROM operations WHERE state IN ('dispatching','unknown') "
                              "LIMIT 1").fetchone() is not None

    def status(self):
        try:
            binding = self._binding()
        except FileNotFoundError:
            return {'configured': False, 'binding': None, 'state': 'unavailable',
                    'message': 'Cloudflare deployment zatím není připojený.', 'domains': []}
        try:
            release_sha256, hostnames, _ = self.release_resolver()
            provider = self.transport.status(binding, self._credential(binding))
            self._reconcile(provider)
            result = self._summary(provider, release_sha256, hostnames)
            if self._has_unknown():
                result['state'] = 'unknown'
            return {'configured': True,
                    'binding': {key: binding[key] for key in ('portal_id', 'provider', 'account_id', 'worker_name')},
                    **result, 'message': 'Stav byl načten přímo z Cloudflare.'}
        except (CloudflareUnavailable, ValueError, OSError, sqlite3.Error):
            unknown = self._has_unknown()
            return {'configured': True,
                    'binding': {key: binding[key] for key in ('portal_id', 'provider', 'account_id', 'worker_name')},
                    'state': 'unknown' if unknown else 'unavailable', 'domains': [],
                    'message': ('Výsledek deploymentu je neznámý a Cloudflare jej nyní nelze ověřit.'
                                if unknown else
                                'Skutečný stav Cloudflare nyní nelze bezpečně načíst.')}

    def preview(self, request):
        require(request == {}, 'Invalid deployment preview request')
        binding = self._binding(); secret = self._credential(binding)
        release_sha256, hostnames, _ = self.release_resolver()
        provider = self.transport.status(binding, secret)
        summary = self._summary(provider, release_sha256, hostnames)
        require(summary['state'] != 'missing',
                'Cloudflare Worker must be created separately before deployment')
        require(summary['state'] != 'drifted',
                'Cloudflare Worker traffic is split or drifted; reconcile it first')
        plan = {'schema_version': 1, 'portal_id': PORTAL_ID, 'provider': 'cloudflare',
                'account_id': binding['account_id'], 'worker_name': binding['worker_name'],
                'credential_revision': binding['credential_revision'],
                'release_sha256': release_sha256, 'hostnames': hostnames,
                'action': 'create-worker-version-and-deploy',
                'traffic_percentage': 100,
                'compatibility_date': date.today().isoformat(),
                'worker_script_sha256': hashlib.sha256(
                    WORKER_SCRIPT.replace('__HOSTS__', json.dumps(hostnames)).encode()).hexdigest(),
                'expected_version_id': summary.get('version_id'),
                'expected_deployment_id': summary.get('deployment_id'),
                'custom_domains': 'unchanged', 'dns': 'unchanged'}
        return {'preview_sha256': hashlib.sha256(_canonical(plan)).hexdigest(),
                'plan': plan, 'current': summary}

    def deploy(self, request):
        require(isinstance(request, dict) and set(request) == {
            'operation_id', 'preview_sha256', 'approved'} and request['approved'] is True,
            'Invalid or unconfirmed deployment request')
        uuid(request['operation_id'])
        with self._database() as db:
            existing = db.execute('SELECT request_json,state,receipt_json FROM operations '
                                  'WHERE operation_id=?', (request['operation_id'],)).fetchone()
        if existing:
            original = json.loads(existing[0])
            require(all(original.get(key) == request[key]
                        for key in ('operation_id', 'preview_sha256', 'approved')),
                    'Deployment operation ID belongs to another request')
            if existing[1] == 'completed':
                return json.loads(existing[2])
            raise CloudflareUnknown('Deployment outcome is unknown; refresh provider status')
        preview = self.preview({}); plan = preview['plan']
        require(request['preview_sha256'] == preview['preview_sha256'],
                'Deployment preview is stale or binding changed')
        stored = {**request, 'release_sha256': plan['release_sha256'], 'plan': plan}
        raw = json.dumps(stored, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        binding = self._binding(); secret = self._credential(binding)
        release_sha256, hostnames, output = self.release_resolver()
        with self._writer(), self._database() as db:
            db.execute('INSERT INTO operations VALUES(?,?,?,?,NULL,NULL)',
                       (request['operation_id'], digest, raw, 'prepared')); db.commit()
            changed = db.execute("UPDATE operations SET state='dispatching' "
                                 "WHERE operation_id=? AND state='prepared'",
                                 (request['operation_id'],))
            require(changed.rowcount == 1, 'Deployment state changed before dispatch'); db.commit()
            try:
                provider_receipt = self.transport.deploy(
                    binding, secret, output, hostnames, release_sha256,
                    plan['compatibility_date'])
            except Exception as exc:
                db.execute("UPDATE operations SET state='unknown',error=? "
                           "WHERE operation_id=? AND state='dispatching'",
                           ('Cloudflare mutation outcome is unknown', request['operation_id'])); db.commit()
                raise CloudflareUnknown(
                    'Cloudflare deployment outcome is unknown; do not retry automatically') from exc
            receipt = {'operation_id': request['operation_id'], 'state': 'completed',
                       'release_sha256': release_sha256, **provider_receipt,
                       'hostnames': hostnames, 'custom_domains': 'unchanged', 'dns': 'unchanged'}
            db.execute("UPDATE operations SET state='completed',receipt_json=? "
                       "WHERE operation_id=? AND state='dispatching'",
                       (json.dumps(receipt, ensure_ascii=False, sort_keys=True),
                        request['operation_id'])); db.commit()
            return receipt
