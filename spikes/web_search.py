# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit, bounded SearXNG search with durable no-retry recovery."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import stat
from urllib.parse import urlencode, urlsplit

from spikes.metadata import require, timestamp, uuid
from spikes.ollama_backend import normalize_tls_fingerprint


MAX_QUERY_BYTES = 4096
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_TITLE_BYTES = 1024
MAX_SNIPPET_BYTES = 8192
MAX_URL_BYTES = 8192


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')


def _digest(value):
    return hashlib.sha256(value).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _bounded_text(value, label, limit, *, allow_empty=False):
    require(isinstance(value, str) and '\0' not in value
            and len(value.encode('utf-8')) <= limit
            and (allow_empty or bool(value.strip())), f'Invalid SearXNG {label}')
    return value.strip()


class SearchUnknown(RuntimeError):
    def __init__(self, message, *, code='outcome-unknown'):
        super().__init__(message); self.code = code


class SearchResponseError(RuntimeError):
    def __init__(self, message, *, code='response-invalid'):
        super().__init__(message); self.code = code


class _SearchTransportUnknown(RuntimeError):
    def __init__(self, message, *, code='transport-interrupted'):
        super().__init__(message); self.code = code


@dataclass(frozen=True)
class SearXNGResult:
    title: str
    url: str
    snippet: str

    def serialize(self):
        return {'title': self.title, 'url': self.url, 'snippet': self.snippet}


@dataclass(frozen=True)
class SearXNGBinding:
    binding_id: str
    revision: str
    boundary: str
    endpoint: str
    target_id: str
    result_limit: int
    timeout_seconds: int
    tls_cert_sha256: str | None = None

    adapter_id = 'searxng'

    @classmethod
    def parse(cls, value):
        require(isinstance(value, dict), 'SearXNG binding must be an object')
        common = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                  'endpoint', 'target_id', 'result_limit', 'timeout_seconds'}
        require(value.keys() in (common, common | {'tls_cert_sha256'}),
                'Unknown or missing SearXNG binding field')
        require(value['schema_version'] == 1 and value['adapter'] == 'searxng',
                'Unsupported SearXNG binding')
        uuid(value['binding_id'])
        for key in ('revision', 'endpoint', 'target_id'):
            require(isinstance(value[key], str) and value[key].strip() == value[key]
                    and bool(value[key]) and not any(c in value[key] for c in '\0\r\n'),
                    f'Invalid SearXNG {key}')
        require(value['boundary'] in {'same-node', 'private-network'},
                'SearXNG boundary must be same-node or private-network')
        require(type(value['result_limit']) is int and 1 <= value['result_limit'] <= 10,
                'SearXNG result limit must be between 1 and 10')
        require(type(value['timeout_seconds']) is int and 1 <= value['timeout_seconds'] <= 60,
                'SearXNG timeout must be between 1 and 60 seconds')
        parsed = urlsplit(value['endpoint'])
        require(not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in {'', '/'},
                'Invalid SearXNG endpoint')
        require(parsed.port is not None, 'SearXNG endpoint requires an explicit port')
        try:
            address = ipaddress.ip_address(parsed.hostname or '')
        except ValueError as exc:
            raise ValueError('SearXNG endpoint requires a numeric IP address') from exc
        pin = normalize_tls_fingerprint(value.get('tls_cert_sha256'))
        if value['boundary'] == 'same-node':
            require(parsed.scheme == 'http' and address.is_loopback,
                    'same-node SearXNG requires a numeric loopback HTTP endpoint')
            require(pin is None and value['target_id'] == 'local-process',
                    'same-node SearXNG must identify the local process without TLS pin')
        else:
            require(parsed.scheme == 'https' and address.is_private and not address.is_loopback,
                    'private-network SearXNG requires a private numeric HTTPS endpoint')
            require(isinstance(pin, str) and bool(re.fullmatch(r'[0-9a-f]{64}', pin)),
                    'private-network SearXNG requires a SHA-256 TLS certificate pin')
            uuid(value['target_id'])
        return cls(value['binding_id'], value['revision'], value['boundary'],
                   value['endpoint'].rstrip('/'), value['target_id'],
                   value['result_limit'], value['timeout_seconds'], pin)

    def serialize(self):
        value = {'schema_version': 1, 'binding_id': self.binding_id,
                 'revision': self.revision, 'adapter': self.adapter_id,
                 'boundary': self.boundary, 'endpoint': self.endpoint,
                 'target_id': self.target_id, 'result_limit': self.result_limit,
                 'timeout_seconds': self.timeout_seconds}
        if self.tls_cert_sha256:
            value['tls_cert_sha256'] = self.tls_cert_sha256
        return value


class SearXNGBindings:
    """Atomic node-local search configuration outside project Git."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Search binding state requires owned mode 0700')
        self.path = self.root / 'searxng-binding.json'

    def save(self, binding):
        require(isinstance(binding, SearXNGBinding), 'Validated SearXNG binding is required')
        raw = _canonical(binding.serialize()) + b'\n'
        temporary = self.root / ('.searxng-binding-' + _digest(raw + os.urandom(32)) + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.close(fd); fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if fd >= 0: os.close(fd)
            if temporary.exists(): temporary.unlink()

    def load(self):
        fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe SearXNG binding file')
            raw = os.read(fd, 64 * 1024 + 1)
        finally:
            os.close(fd)
        require(len(raw) <= 64 * 1024, 'SearXNG binding exceeds 64 KiB')
        try: value = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise ValueError('Invalid SearXNG binding JSON') from exc
        return SearXNGBinding.parse(value)


class SearchRuns:
    """Authoritative state for an explicitly approved search network effect."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Search run state requires owned mode 0700')
        self.path = self.root / 'search-runs.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe search run journal')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('''CREATE TABLE IF NOT EXISTS searches(
            search_id TEXT PRIMARY KEY, task_id TEXT NOT NULL UNIQUE,
            node_id TEXT NOT NULL, user_id TEXT NOT NULL, project_id TEXT NOT NULL,
            request_json TEXT NOT NULL, request_digest TEXT NOT NULL,
            preview_json TEXT NOT NULL, preview_sha256 TEXT NOT NULL,
            binding_json TEXT NOT NULL, state TEXT NOT NULL,
            result_json TEXT, error TEXT, error_code TEXT)''')
        columns = [row[1] for row in db.execute('PRAGMA table_info(searches)')]
        require(columns == ['search_id', 'task_id', 'node_id', 'user_id', 'project_id',
            'request_json', 'request_digest', 'preview_json', 'preview_sha256',
            'binding_json', 'state', 'result_json', 'error', 'error_code'],
            'Unknown search run schema')
        db.commit(); return closing(db)

    @staticmethod
    def _row(row):
        if row is None: return None
        return {'search_id': row[0], 'task_id': row[1], 'node_id': row[2],
                'user_id': row[3], 'project_id': row[4],
                'request': json.loads(row[5]), 'request_digest': row[6],
                'preview': json.loads(row[7]), 'preview_sha256': row[8],
                'binding': json.loads(row[9]), 'state': row[10],
                'result': None if row[11] is None else json.loads(row[11]),
                'error': row[12], 'error_code': row[13]}

    def get(self, search_id):
        uuid(search_id)
        with self.connect() as db:
            row = db.execute('SELECT * FROM searches WHERE search_id=?', (search_id,)).fetchone()
        return self._row(row)

    def for_task(self, task_id, node_id, user_id):
        for value in (task_id, node_id, user_id): uuid(value)
        with self.connect() as db:
            row = db.execute('SELECT * FROM searches WHERE task_id=?', (task_id,)).fetchone()
        if row is None: return None
        require(row[2:4] == (node_id, user_id), 'Search preview is unavailable to this user')
        return self._row(row)

    def prepare(self, *, search_id, task_id, node_id, user_id, project_id,
                request, preview, binding):
        for value in (search_id, task_id, node_id, user_id, project_id): uuid(value)
        require(isinstance(binding, SearXNGBinding), 'Invalid search binding')
        raw_request = _canonical(request).decode(); request_digest = _digest(raw_request.encode())
        raw_preview = _canonical(preview).decode(); preview_sha256 = _digest(raw_preview.encode())
        raw_binding = _canonical(binding.serialize()).decode()
        identity = (task_id, node_id, user_id, project_id, raw_request, request_digest,
                    raw_preview, preview_sha256, raw_binding)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT task_id,node_id,user_id,project_id,request_json,'
                'request_digest,preview_json,preview_sha256,binding_json FROM searches '
                'WHERE search_id=?', (search_id,)).fetchone()
            if row:
                require(row == identity, 'Search ID belongs to a different request')
            else:
                require(db.execute('SELECT 1 FROM searches WHERE task_id=?',
                                   (task_id,)).fetchone() is None,
                        'Task already has a different search preview')
                db.execute('INSERT INTO searches VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)',
                    (search_id,) + identity + ('prepared',))
            db.commit()
        return self.get(search_id)

    def transition(self, search_id, current, following, *, result=None, error=None, code=None):
        encoded = None if result is None else _canonical(result).decode()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE searches SET state=?,result_json=?,error=?,error_code=? '
                'WHERE search_id=? AND state=?',
                (following, encoded, error, code, search_id, current))
            require(changed.rowcount == 1, 'Search run state changed concurrently')
            db.commit()
        return self.get(search_id)

    def cancel_task(self, task_id, node_id, user_id):
        row = self.for_task(task_id, node_id, user_id)
        if row is None or row['state'] in {'failed', 'succeeded', 'cancelled'}:
            return row
        require(row['state'] == 'prepared',
                'Active or unknown web search cannot be cancelled')
        return self.transition(row['search_id'], 'prepared', 'cancelled')


class SearXNGAdapter:
    def __init__(self, runs, transport=None):
        require(isinstance(runs, SearchRuns), 'Search adapter requires SearchRuns')
        self.runs = runs; self.transport = transport or self._http_transport

    @staticmethod
    def _result_url(value):
        value = _bounded_text(value, 'result URL', MAX_URL_BYTES)
        parsed = urlsplit(value)
        require(parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                and not parsed.username and not parsed.password,
                'Invalid SearXNG result URL')
        return value

    @classmethod
    def validate_response(cls, value, binding, query, searched_at):
        timestamp(searched_at)
        require(isinstance(value, dict) and isinstance(value.get('results'), list),
                'Invalid SearXNG response envelope')
        if 'query' in value:
            require(value['query'] == query, 'SearXNG response query changed')
        results, seen = [], set()
        for item in value['results']:
            require(isinstance(item, dict), 'Invalid SearXNG result')
            url = cls._result_url(item.get('url'))
            if url in seen: continue
            seen.add(url)
            title = _bounded_text(item.get('title'), 'result title', MAX_TITLE_BYTES)
            snippet = _bounded_text(item.get('content', ''), 'result snippet',
                                    MAX_SNIPPET_BYTES, allow_empty=True)
            results.append(SearXNGResult(title, url, snippet).serialize())
            if len(results) == binding.result_limit: break
        return {'schema_version': 1, 'query': query, 'searched_at': searched_at,
                'source': {'adapter': 'searxng', 'binding_id': binding.binding_id,
                           'binding_revision': binding.revision,
                           'boundary': binding.boundary, 'target_id': binding.target_id},
                'results': results}

    def dispatch(self, search_id, binding, *, preview_sha256, now=_now):
        require(isinstance(binding, SearXNGBinding), 'Validated SearXNG binding is required')
        row = self.runs.get(search_id)
        require(row is not None and row['preview_sha256'] == preview_sha256,
                'Search preview changed before dispatch')
        require(row['binding'] == binding.serialize(), 'SearXNG binding changed before dispatch')
        if row['state'] == 'succeeded': return row['result']
        if row['state'] in {'dispatching', 'unknown'}:
            raise SearchUnknown('Search result is unknown; automatic retry is forbidden',
                                code=row['error_code'] or 'outcome-unknown')
        if row['state'] != 'prepared':
            raise SearchResponseError(row['error'] or 'Search failed; explicit new run required',
                                      code=row['error_code'] or 'response-invalid')
        _bounded_text(row['request'].get('query'), 'query', MAX_QUERY_BYTES)
        self.runs.transition(search_id, 'prepared', 'dispatching')
        try:
            value = self.transport(binding, row['request']['query'])
            result = self.validate_response(value, binding, row['request']['query'], now())
        except SearchResponseError as exc:
            self.runs.transition(search_id, 'dispatching', 'failed',
                                 error=str(exc), code=exc.code)
            raise
        except ValueError as exc:
            error = SearchResponseError('Invalid SearXNG response',
                                        code='response-invalid')
            self.runs.transition(search_id, 'dispatching', 'failed',
                                 error=str(exc), code=error.code)
            raise error from exc
        except _SearchTransportUnknown as exc:
            self.runs.transition(search_id, 'dispatching', 'unknown',
                                 error=str(exc), code=exc.code)
            raise SearchUnknown('Search dispatch outcome is unknown', code=exc.code) from exc
        except Exception as exc:
            self.runs.transition(search_id, 'dispatching', 'unknown',
                                 error=type(exc).__name__, code='transport-unknown')
            raise SearchUnknown('Search dispatch outcome is unknown',
                                code='transport-unknown') from exc
        self.runs.transition(search_id, 'dispatching', 'succeeded', result=result)
        return result

    @staticmethod
    def _connection(binding):
        parsed = urlsplit(binding.endpoint)
        if binding.boundary == 'same-node':
            return parsed, http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=binding.timeout_seconds)
        return parsed, http.client.HTTPSConnection(
            parsed.hostname, parsed.port, timeout=binding.timeout_seconds,
            context=ssl._create_unverified_context())

    @staticmethod
    def _http_transport(binding, query):
        parsed, connection = SearXNGAdapter._connection(binding)
        try:
            try: connection.connect()
            except TimeoutError as exc:
                raise SearchResponseError('SearXNG connection timed out',
                                          code='connect-timeout') from exc
            except ssl.SSLError as exc:
                raise SearchResponseError('SearXNG TLS handshake failed',
                                          code='tls-failed') from exc
            except OSError as exc:
                raise SearchResponseError('SearXNG endpoint is unavailable',
                                          code='unavailable') from exc
            if binding.tls_cert_sha256:
                try: certificate = connection.sock.getpeercert(binary_form=True)
                except (AttributeError, OSError, ssl.SSLError) as exc:
                    raise SearchResponseError('SearXNG TLS certificate is unavailable',
                                              code='tls-failed') from exc
                if hashlib.sha256(certificate).hexdigest() != binding.tls_cert_sha256:
                    raise SearchResponseError('SearXNG TLS certificate pin mismatch',
                                              code='tls-pin-mismatch')
            path = '/search?' + urlencode({'q': query, 'format': 'json'})
            try:
                connection.request('GET', path, headers={'Accept': 'application/json'})
                response = connection.getresponse()
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                raise _SearchTransportUnknown('SearXNG response was interrupted',
                    code='response-timeout' if isinstance(exc, TimeoutError)
                    else 'transport-interrupted') from exc
            if 300 <= response.status < 400:
                raise SearchResponseError('SearXNG redirect is forbidden',
                                          code='redirect-forbidden')
            if response.status != 200:
                raise SearchResponseError(f'SearXNG returned HTTP {response.status}',
                    code={400: 'request-rejected', 401: 'access-denied',
                          403: 'access-denied', 429: 'overloaded',
                          503: 'overloaded'}.get(response.status, 'http-error'))
            try: raw = response.read(MAX_RESPONSE_BYTES + 1)
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                raise _SearchTransportUnknown('SearXNG response was interrupted',
                    code='response-timeout' if isinstance(exc, TimeoutError)
                    else 'transport-interrupted') from exc
            if len(raw) > MAX_RESPONSE_BYTES:
                raise SearchResponseError('SearXNG response exceeds 2 MiB',
                                          code='response-too-large')
            try: return json.loads(raw)
            except (UnicodeError, ValueError) as exc:
                raise SearchResponseError('Invalid SearXNG JSON response',
                                          code='invalid-json') from exc
        finally:
            try: connection.close()
            except OSError: pass

    @classmethod
    def probe(cls, binding, transport=None):
        require(isinstance(binding, SearXNGBinding), 'Validated SearXNG binding is required')
        value = (transport or cls._http_transport)(binding, 'SearXNG')
        result = cls.validate_response(value, binding, 'SearXNG', _now())
        return {'status': 'available', 'result_count': len(result['results']),
                'binding': binding.serialize()}
