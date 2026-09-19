# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Strict node-local Ollama binding contract; transport is added separately."""
from dataclasses import dataclass
from contextlib import closing
import base64
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

from spikes.backend_contract import (BackendCapabilities, BackendExecution,
                                     BackendRegistry, BackendResponseError,
                                     BackendUnknown, ROLES)
from spikes.context_builder import Target
from spikes.metadata import require, uuid


OLLAMA_GENERATE_TIMEOUT = 180


class UnknownRun(BackendUnknown):
    pass


class OllamaResponseError(BackendResponseError):
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

    adapter_id = 'ollama'

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

    def serialize(self):
        value = dict(schema_version=1, binding_id=self.binding_id, revision=self.revision,
                     adapter='ollama', boundary=self.boundary, endpoint=self.endpoint,
                     model=self.model, target_id=self.target_id)
        if self.tls_cert_sha256:
            value['tls_cert_sha256'] = self.tls_cert_sha256
        return value

    def capabilities(self):
        return BackendCapabilities(1, 'ollama-generate-v1',
                                   frozenset({'generate-text'}),
                                   frozenset({'text', 'json'})).validate()


BACKENDS = BackendRegistry()
BACKENDS.register('ollama', OllamaBinding.parse)


class OllamaBindings:
    """Atomic node-local binding configuration outside project Git."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Binding state directory requires owned mode 0700')
        self.path = self.root / 'ollama-binding.json'

    def save(self, binding):
        require(isinstance(binding, OllamaBinding), 'Validated Ollama binding is required')
        raw = (json.dumps(binding.serialize(), ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        temporary = self.root / ('.ollama-binding-' + binding.binding_id + '.tmp')
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.close(fd); fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary.exists():
                temporary.unlink()

    def load(self):
        flags = os.O_RDONLY | os.O_NOFOLLOW
        fd = os.open(self.path, flags)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe Ollama binding file')
            raw = os.read(fd, 64 * 1024 + 1)
        finally:
            os.close(fd)
        require(len(raw) <= 64 * 1024, 'Ollama binding exceeds 64 KiB')
        try:
            value = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise ValueError('Invalid Ollama binding JSON') from exc
        return OllamaBinding.parse(value)


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
        columns = {row[1] for row in db.execute('PRAGMA table_info(runs)')}
        additions = {
            'adapter_id': 'TEXT', 'binding_id': 'TEXT', 'binding_revision': 'TEXT',
            'capability_revision': 'TEXT', 'operation': 'TEXT', 'output_format': 'TEXT',
            'role_id': 'TEXT', 'role_revision': 'TEXT', 'manifest_sha256': 'TEXT'}
        for name, kind in additions.items():
            if name not in columns:
                db.execute(f'ALTER TABLE runs ADD COLUMN {name} {kind}')
        db.commit()
        return closing(db)

    def get(self, run_id):
        uuid(run_id)
        with self.connect() as db:
            row = db.execute('SELECT request_digest,state,response,error,adapter_id,binding_id,'
                             'binding_revision,capability_revision,operation,output_format,'
                             'role_id,role_revision,manifest_sha256 FROM runs WHERE run_id=?',
                             (run_id,)).fetchone()
            return None if row is None else dict(request_digest=row[0], state=row[1],
                                                  response=json.loads(row[2]) if row[2] else None,
                                                  error=row[3], adapter_id=row[4], binding_id=row[5],
                                                  binding_revision=row[6], capability_revision=row[7],
                                                  operation=row[8], output_format=row[9],
                                                  role_id=row[10], role_revision=row[11],
                                                  manifest_sha256=row[12])

    def prepare(self, run_id, digest, legacy_digest, execution, manifest_sha256):
        execution.validate()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT request_digest,state,adapter_id,binding_id,'
                             'binding_revision,capability_revision,operation,output_format,'
                             'role_id,role_revision,manifest_sha256 FROM runs WHERE run_id=?',
                             (run_id,)).fetchone()
            identity = (execution.adapter_id, execution.binding_id,
                        execution.binding_revision, execution.capability_revision,
                        execution.operation, execution.output_format,
                        execution.role_id or None, execution.role_revision or None,
                        manifest_sha256)
            if row:
                if row[2] is None:
                    require(row[0] == legacy_digest, 'Run ID belongs to a different legacy request')
                    if row[1] == 'prepared':
                        db.execute('UPDATE runs SET request_digest=?,adapter_id=?,binding_id=?,binding_revision=?,'
                                   'capability_revision=?,operation=?,output_format=?,role_id=?,'
                                   'role_revision=?,manifest_sha256=? WHERE run_id=? AND '
                                   'state=? AND adapter_id IS NULL',
                                   (digest,) + identity + (run_id, 'prepared'))
                else:
                    require(row[0] == digest and tuple(row[2:]) == identity,
                            'Run ID belongs to a different backend execution')
            else:
                db.execute('INSERT INTO runs(run_id,request_digest,state,adapter_id,binding_id,'
                           'binding_revision,capability_revision,operation,output_format,role_id,'
                           'role_revision,manifest_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                           (run_id, digest, 'prepared') + identity)
            db.commit()
        return self.get(run_id)


class OllamaAdapter:
    def __init__(self, runs, transport=None):
        require(isinstance(runs, OllamaRuns), 'Ollama run store is required')
        self.runs = runs
        self.transport = transport or self._http_transport

    @staticmethod
    def _prompt(payload):
        try:
            value = json.loads(payload)
        except (UnicodeError, ValueError):
            return payload.decode('utf-8')
        task = value.get('task') if isinstance(value, dict) else None
        conversation = value.get('conversation') if isinstance(value, dict) else None
        if task is not None:
            inputs = value.get('inputs')
            require(isinstance(inputs, list) and bool(inputs) and isinstance(task, dict)
                    and set(task) == {'role_id', 'role_revision', 'instruction',
                                      'focus_input_id'},
                    'Invalid task payload for Ollama')
            require(all(isinstance(task[key], str) and task[key] for key in
                        ('role_id', 'role_revision', 'instruction')),
                    'Invalid task payload for Ollama')
            decoded = []
            for source in inputs:
                require(isinstance(source, dict)
                        and set(source) == {'input_id', 'content_b64'},
                        'Invalid task input for Ollama')
                try:
                    content = base64.b64decode(source['content_b64'], validate=True).decode('utf-8')
                except (TypeError, ValueError, UnicodeError) as exc:
                    raise ValueError('Ollama task input is not valid UTF-8') from exc
                decoded.append((source['input_id'], content))
            roles = {}
            if conversation is not None:
                require(isinstance(conversation, list), 'Invalid task conversation for Ollama')
                roles = {item['message_id']: item['role'] for item in conversation
                         if isinstance(item, dict) and set(item) == {'message_id', 'role'}
                         and item['role'] in {'user', 'assistant'}}
                require(len(roles) == len(conversation), 'Invalid task conversation for Ollama')
                selected_ids = [input_id for input_id, _ in decoded
                                if input_id != task['focus_input_id']]
                require(selected_ids == [item['message_id'] for item in conversation],
                        'Task conversation does not match input order')
            sections = ['Instruction:\n' + task['instruction']]
            for input_id, content in decoded:
                if input_id == task['focus_input_id']:
                    label = 'Focus'
                elif input_id in roles:
                    label = 'User message' if roles[input_id] == 'user' else 'Assistant message'
                else:
                    label = 'Source ' + input_id
                sections.append(label + ':\n' + content)
            sections.append('Summary:\n')
            return '\n\n'.join(sections)
        if conversation is None:
            return payload.decode('utf-8')
        inputs = value.get('inputs')
        require(isinstance(inputs, list) and isinstance(conversation, list)
                and len(inputs) == len(conversation) and bool(inputs),
                'Invalid conversation payload for Ollama')
        transcript = []
        for source, message in zip(inputs, conversation):
            require(isinstance(source, dict) and isinstance(message, dict)
                    and set(source) == {'input_id', 'content_b64'}
                    and set(message) == {'message_id', 'role'}
                    and source['input_id'] == message['message_id']
                    and message['role'] in {'user', 'assistant'},
                    'Invalid conversation payload for Ollama')
            try:
                content = base64.b64decode(source['content_b64'], validate=True).decode('utf-8')
            except (TypeError, ValueError, UnicodeError) as exc:
                raise ValueError('Ollama conversation message is not valid UTF-8') from exc
            transcript.append(('User' if message['role'] == 'user' else 'Assistant')
                              + ':\n' + content)
        transcript.append('Assistant:\n')
        return '\n\n'.join(transcript)

    @staticmethod
    def _execution(binding, role=None, output_format='text'):
        capabilities = binding.capabilities()
        if role is not None:
            role = ROLES.resolve(role.role_id, role.revision)
            require(role.output_format == output_format,
                    'Role output format differs from backend request')
            operation = role.operation
            role_id, role_revision = role.role_id, role.revision
        else:
            operation = 'generate-text'; role_id = role_revision = ''
        capabilities.require(operation, output_format)
        return BackendExecution(binding.adapter_id, binding.binding_id, binding.revision,
                                capabilities.revision, operation, output_format,
                                role_id, role_revision)

    @staticmethod
    def _request(handoff, binding, role=None, output_format='text'):
        from spikes.context_builder import DispatchHandoff
        require(isinstance(handoff, DispatchHandoff) and isinstance(binding, OllamaBinding),
                'Authorized handoff and Ollama binding are required')
        require(handoff.target == binding.target(), 'Ollama binding differs from authorized target')
        request = json.dumps(dict(model=binding.model, prompt=OllamaAdapter._prompt(handoff.payload),
                                  stream=False), sort_keys=True,
                             separators=(',', ':')).encode()
        execution = OllamaAdapter._execution(binding, role, output_format)
        base = handoff.manifest_sha256.encode() + b'\0' + request
        legacy_digest = hashlib.sha256(base).hexdigest()
        digest = hashlib.sha256(base + b'\0' + execution.canonical()).hexdigest()
        return request, digest, legacy_digest, execution

    def prepare(self, handoff, binding, role=None, output_format='text'):
        _, digest, legacy_digest, execution = self._request(
            handoff, binding, role, output_format)
        return self.runs.prepare(handoff.run_id, digest, legacy_digest, execution,
                                 handoff.manifest_sha256)

    def dispatch(self, handoff, binding, role=None, output_format='text'):
        request, digest, legacy_digest, execution = self._request(
            handoff, binding, role, output_format)
        row = self.runs.prepare(handoff.run_id, digest, legacy_digest, execution,
                                handoff.manifest_sha256)
        if row['state'] == 'succeeded':
            return row['response']
        if row['state'] in {'dispatching', 'unknown'}:
            raise UnknownRun('Ollama result is unknown; automatic retry is forbidden')
        if row['state'] != 'prepared':
            raise OllamaResponseError(row['error'] or 'Ollama run failed; explicit new run required')
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
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=OLLAMA_GENERATE_TIMEOUT)
        else:
            context = ssl._create_unverified_context()
            connection = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=OLLAMA_GENERATE_TIMEOUT,
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
