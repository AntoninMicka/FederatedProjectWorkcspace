# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Strict node-local Ollama binding contract; transport is added separately."""
from dataclasses import dataclass
from contextlib import closing
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
from urllib.parse import urlsplit

from spikes.context_builder import Target
from spikes.metadata import require, uuid


class UnknownRun(RuntimeError):
    pass


class OllamaResponseError(RuntimeError):
    pass


@dataclass(frozen=True)
class OllamaBinding:
    binding_id: str
    revision: str
    boundary: str
    endpoint: str
    model: str
    target_id: str
    tls_cert_sha256: str | None = None

    @classmethod
    def parse(cls, value):
        require(isinstance(value, dict), 'Ollama binding must be an object')
        common = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                  'endpoint', 'model', 'target_id'}
        require(value.keys() in (common, common | {'tls_cert_sha256'}),
                'Unknown or missing Ollama binding field')
        require(value['schema_version'] == 1 and value['adapter'] == 'ollama',
                'Unsupported Ollama binding')
        uuid(value['binding_id'])
        for key in ('revision', 'endpoint', 'model', 'target_id'):
            require(isinstance(value[key], str) and value[key].strip() == value[key]
                    and bool(value[key]) and not any(c in value[key] for c in '\0\r\n'),
                    f'Invalid Ollama {key}')
        require(value['boundary'] in {'same-node', 'private-network'},
                'Ollama boundary must be same-node or private-network')
        parsed = urlsplit(value['endpoint'])
        require(not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in {'', '/'}, 'Invalid Ollama endpoint')
        require(parsed.port is not None, 'Ollama endpoint requires an explicit port')
        try:
            address = ipaddress.ip_address(parsed.hostname or '')
        except ValueError as exc:
            raise ValueError('Ollama endpoint requires a numeric IP address') from exc
        pin = value.get('tls_cert_sha256')
        if value['boundary'] == 'same-node':
            require(parsed.scheme == 'http' and address.is_loopback,
                    'same-node Ollama requires a numeric loopback HTTP endpoint')
            require(pin is None and value['target_id'] == 'local-process',
                    'same-node Ollama must identify the local process without TLS pin')
        else:
            require(parsed.scheme == 'https' and address.is_private and not address.is_loopback,
                    'private-network Ollama requires a private numeric HTTPS endpoint')
            require(isinstance(pin, str) and bool(re.fullmatch(r'[0-9a-f]{64}', pin)),
                    'private-network Ollama requires a SHA-256 TLS certificate pin')
            uuid(value['target_id'])
        return cls(value['binding_id'], value['revision'], value['boundary'],
                   value['endpoint'].rstrip('/'), value['model'], value['target_id'], pin)

    def target(self):
        return Target(self.binding_id, self.revision, self.boundary,
                      self.target_id, self.model)


class OllamaRuns:
    """Authoritative local state for an Ollama dispatch; never stored in project Git."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700, 'Run state directory requires owned mode 0700')
        self.path = self.root / 'ollama-runs.sqlite'

    def connect(self):
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077, 'Unsafe Ollama run journal')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS runs ('
                   'run_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, state TEXT NOT NULL, '
                   'response TEXT, error TEXT)')
        db.commit()
        return closing(db)

    def get(self, run_id):
        uuid(run_id)
        with self.connect() as db:
            row = db.execute('SELECT request_digest,state,response,error FROM runs WHERE run_id=?',
                             (run_id,)).fetchone()
            return None if row is None else dict(request_digest=row[0], state=row[1],
                                                  response=json.loads(row[2]) if row[2] else None,
                                                  error=row[3])


class OllamaAdapter:
    def __init__(self, runs, transport=None):
        require(isinstance(runs, OllamaRuns), 'Ollama run store is required')
        self.runs = runs
        self.transport = transport or self._http_transport

    def dispatch(self, handoff, binding):
        from spikes.context_builder import DispatchHandoff
        require(isinstance(handoff, DispatchHandoff) and isinstance(binding, OllamaBinding),
                'Authorized handoff and Ollama binding are required')
        require(handoff.target == binding.target(), 'Ollama binding differs from authorized target')
        request = json.dumps(dict(model=binding.model, prompt=handoff.payload.decode('utf-8'),
                                  stream=False), sort_keys=True,
                             separators=(',', ':')).encode()
        digest = hashlib.sha256(handoff.manifest_sha256.encode() + b'\0' + request).hexdigest()
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT request_digest,state,response,error FROM runs WHERE run_id=?',
                             (handoff.run_id,)).fetchone()
            if row:
                require(row[0] == digest, 'Run ID belongs to a different Ollama request')
                if row[1] == 'succeeded':
                    return json.loads(row[2])
                if row[1] in {'dispatching', 'unknown'}:
                    raise UnknownRun('Ollama result is unknown; automatic retry is forbidden')
                raise OllamaResponseError(row[3] or 'Ollama run failed; explicit new run required')
            db.execute('INSERT INTO runs(run_id,request_digest,state) VALUES (?,?,?)',
                       (handoff.run_id, digest, 'prepared'))
            db.commit()
        # Revalidate the exact binding again immediately before crossing the transport boundary.
        require(handoff.target == binding.target(), 'Ollama binding changed before dispatch')
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            result = db.execute("UPDATE runs SET state='dispatching' WHERE run_id=? AND state='prepared'",
                                (handoff.run_id,))
            require(result.rowcount == 1, 'Ollama run state changed before dispatch')
            db.commit()
        try:
            response = self.transport(binding, request)
            if not (isinstance(response, dict) and response.get('model') == binding.model
                    and isinstance(response.get('response'), str)):
                raise OllamaResponseError('Invalid Ollama response')
        except OllamaResponseError as exc:
            with self.runs.connect() as db, db:
                db.execute("UPDATE runs SET state='failed',error=? WHERE run_id=? AND state='dispatching'",
                           (str(exc), handoff.run_id))
            raise
        except Exception as exc:
            with self.runs.connect() as db, db:
                db.execute("UPDATE runs SET state='unknown',error=? WHERE run_id=? AND state='dispatching'",
                           (type(exc).__name__, handoff.run_id))
            raise UnknownRun('Ollama dispatch outcome is unknown') from exc
        encoded = json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        with self.runs.connect() as db, db:
            result = db.execute("UPDATE runs SET state='succeeded',response=? "
                                "WHERE run_id=? AND state='dispatching'", (encoded, handoff.run_id))
            require(result.rowcount == 1, 'Ollama completion state changed')
        return response

    @staticmethod
    def _http_transport(binding, request):
        parsed = urlsplit(binding.endpoint)
        if binding.boundary == 'same-node':
            connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=30)
        else:
            context = ssl._create_unverified_context()
            connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=30,
                                                       context=context)
        try:
            connection.connect()
            if binding.tls_cert_sha256:
                certificate = connection.sock.getpeercert(binary_form=True)
                require(hashlib.sha256(certificate).hexdigest() == binding.tls_cert_sha256,
                        'Ollama TLS certificate pin mismatch')
            connection.request('POST', '/api/generate', body=request,
                               headers={'Content-Type': 'application/json',
                                        'Accept': 'application/json'})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise OllamaResponseError('Ollama redirect is forbidden')
            if response.status != 200:
                raise OllamaResponseError(f'Ollama returned HTTP {response.status}')
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise OllamaResponseError('Ollama response exceeds 16 MiB')
            try:
                return json.loads(raw)
            except (UnicodeError, ValueError) as exc:
                raise OllamaResponseError('Invalid Ollama JSON response') from exc
        finally:
            connection.close()
