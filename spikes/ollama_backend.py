# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Strict node-local Ollama binding contract; transport is added separately."""
from dataclasses import dataclass
from contextlib import closing
from datetime import datetime, timezone
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

from spikes.artifact_preview import pdf_text
from spikes.backend_contract import (BackendCapabilities, BackendExecution,
                                     BackendRegistry, BackendResponseError,
                                     BackendUnknown, ROLES)
from spikes.context_builder import Target
from spikes.metadata import require, uuid
from spikes.node_telemetry import (OllamaRuntimePolicy, observed_at,
                                   runtime_binding_revision_matches, unknown)


OLLAMA_GENERATE_TIMEOUT = 180
OLLAMA_FIRST_TOKEN_TIMEOUT = 60
OLLAMA_IDLE_TIMEOUT = 30
MAX_STREAM_LINE = 1024 * 1024
MAX_STREAM_EVENTS = 65536
MAX_STREAM_RESPONSE = 16 * 1024 * 1024


def _closed_object(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required,
            'additionalProperties': False}


_TEXT = {'type': 'string', 'minLength': 1}
_ID_LIST = {'type': 'array', 'items': _TEXT, 'uniqueItems': True}
_PRESENTATION_PROPOSAL_FORMAT = _closed_object({
    'schema_version': {'type': 'integer', 'enum': [1]},
    'kind': {'type': 'string', 'enum': ['presentation-proposal']},
    'operation': {'type': 'string', 'enum': ['create', 'update']},
    'target_artifact_id': {'type': ['string', 'null']},
    'title': _TEXT,
    'source_artifact_ids': _ID_LIST,
    'slides': {'type': 'array', 'minItems': 1, 'maxItems': 100,
               'items': _closed_object({
                   'slide_id': {'type': ['string', 'null']},
                   'title': _TEXT,
                   'bullets': {'type': 'array', 'maxItems': 12,
                               'items': _TEXT},
                   'notes': {'type': 'string'},
                   'layout': _TEXT,
               }, ['slide_id', 'title', 'bullets', 'notes', 'layout'])},
}, ['schema_version', 'kind', 'operation', 'target_artifact_id', 'title',
    'source_artifact_ids', 'slides'])
_DIRECT_ANSWER_FORMAT = _closed_object({
    'schema_version': {'type': 'integer', 'enum': [1]},
    'kind': {'type': 'string', 'enum': ['direct-answer']},
    'content': _TEXT,
}, ['schema_version', 'kind', 'content'])
_DOCUMENT_DRAFT_FORMAT = _closed_object({
    'schema_version': {'type': 'integer', 'enum': [1]},
    'kind': {'type': 'string', 'enum': ['artifact-draft']},
    'artifact_kind': {'type': 'string', 'enum': ['document']},
    'title': _TEXT,
    'content': _TEXT,
}, ['schema_version', 'kind', 'artifact_kind', 'title', 'content'])
_TASK_ROUTER_FORMAT = {
    'type': 'object',
    'oneOf': [
        _DIRECT_ANSWER_FORMAT,
        _DOCUMENT_DRAFT_FORMAT,
        _PRESENTATION_PROPOSAL_FORMAT,
        _closed_object({
            'schema_version': {'type': 'integer', 'enum': [1]},
            'kind': {'type': 'string', 'enum': ['web-search', 'external-request']},
            'purpose': _TEXT,
            'query': _TEXT,
            'message_ids': _ID_LIST,
            'artifact_ids': _ID_LIST,
        }, ['schema_version', 'kind', 'purpose', 'query', 'message_ids',
            'artifact_ids']),
    ],
}


def normalize_tls_fingerprint(value):
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    normalized = re.sub(r'(?i)^sha256\s*fingerprint\s*=\s*', '', normalized)
    return normalized.replace(':', '').lower()


class UnknownRun(BackendUnknown):
    def __init__(self, message, *, code='outcome-unknown'):
        super().__init__(message)
        self.code = code


class OllamaResponseError(BackendResponseError):
    def __init__(self, message, *, code='response-invalid'):
        super().__init__(message)
        self.code = code


class _OllamaTransportUnknown(RuntimeError):
    def __init__(self, message, *, code='transport-interrupted'):
        super().__init__(message)
        self.code = code


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
        pin = normalize_tls_fingerprint(value.get('tls_cert_sha256'))
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
        self.draft_path = self.root / 'ollama-binding-draft.json'
        self.preferences_path = self.root / 'ollama-preferences.json'

    def _save_json(self, path, value, temporary_prefix):
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        require(len(raw) <= 64 * 1024, 'Ollama setting exceeds 64 KiB')
        temporary = self.root / (temporary_prefix + hashlib.sha256(
            raw + os.urandom(32)).hexdigest() + '.tmp')
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.close(fd); fd = -1
            os.replace(temporary, path)
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

    def save(self, binding):
        require(isinstance(binding, OllamaBinding), 'Validated Ollama binding is required')
        self._save_json(self.path, binding.serialize(), '.ollama-binding-')

    def save_draft(self, value):
        self._validate_draft(value)
        self._save_json(self.draft_path, value, '.ollama-binding-draft-')

    def save_preferences(self, value):
        self._validate_preferences(value)
        self._save_json(self.preferences_path, value, '.ollama-preferences-')

    def _load_json(self, path):
        flags = os.O_RDONLY | os.O_NOFOLLOW
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe Ollama setting file')
            raw = os.read(fd, 64 * 1024 + 1)
        finally:
            os.close(fd)
        require(len(raw) <= 64 * 1024, 'Ollama setting exceeds 64 KiB')
        try:
            value = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise ValueError('Invalid Ollama setting JSON') from exc
        return value

    def load(self):
        return OllamaBinding.parse(self._load_json(self.path))

    def load_draft(self):
        value = self._load_json(self.draft_path)
        # Reuse the bounded, secret-free draft contract without requiring a valid binding.
        self._validate_draft(value)
        return value

    def load_preferences(self):
        try:
            value = self._load_json(self.preferences_path)
        except FileNotFoundError:
            return {'schema_version': 1, 'streaming': True}
        self._validate_preferences(value)
        return value

    @staticmethod
    def _validate_preferences(value):
        require(isinstance(value, dict)
                and set(value) == {'schema_version', 'streaming'},
                'Unknown or missing Ollama preference field')
        require(value['schema_version'] == 1 and type(value['streaming']) is bool,
                'Invalid Ollama preferences')

    @staticmethod
    def _validate_draft(value):
        require(isinstance(value, dict), 'Ollama binding draft must be an object')
        allowed = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                   'endpoint', 'model', 'target_id', 'tls_cert_sha256'}
        require(set(value) <= allowed and set(value) >= allowed - {'tls_cert_sha256'},
                'Unknown or missing Ollama binding draft field')
        require(value['schema_version'] == 1 and value['adapter'] == 'ollama',
                'Unsupported Ollama binding draft')
        for key in allowed - {'schema_version'}:
            if key in value:
                require(isinstance(value[key], str)
                        and len(value[key].encode()) <= 4096
                        and not any(c in value[key] for c in '\0\r\n'),
                        f'Invalid Ollama draft {key}')
        require('@' not in value['endpoint'],
                'Ollama binding draft must not contain credentials')


class BackendRuns:
    """Authoritative local backend dispatch state; never stored in project Git."""
    def __init__(self, state_dir, filename):
        self.root = Path(state_dir).absolute()
        info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700, 'Run state directory requires owned mode 0700')
        require(isinstance(filename, str) and bool(re.fullmatch(r'[a-z0-9-]+\.sqlite', filename)),
                'Invalid backend run journal name')
        self.path = self.root / filename

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
            'role_id': 'TEXT', 'role_revision': 'TEXT', 'manifest_sha256': 'TEXT',
            'error_code': 'TEXT', 'runtime_evidence': 'TEXT', 'completed_at': 'TEXT'}
        for name, kind in additions.items():
            if name not in columns:
                db.execute(f'ALTER TABLE runs ADD COLUMN {name} {kind}')
        db.commit()
        return closing(db)

    def connect_readonly(self):
        """Open an existing, initialized run journal without DDL or creation."""
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
        finally:
            os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe Ollama run journal')
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=2)
        try:
            db.execute('PRAGMA query_only=ON')
            columns = {row[1] for row in db.execute('PRAGMA table_info(runs)')}
            required = {'run_id', 'request_digest', 'state', 'response', 'error',
                        'adapter_id', 'binding_id', 'binding_revision',
                        'runtime_evidence', 'completed_at'}
            require(required <= columns, 'Run journal requires startup migration')
        except BaseException:
            db.close()
            raise
        return closing(db)

    def get(self, run_id):
        uuid(run_id)
        with self.connect() as db:
            row = db.execute('SELECT request_digest,state,response,error,adapter_id,binding_id,'
                             'binding_revision,capability_revision,operation,output_format,'
                             'role_id,role_revision,manifest_sha256,error_code,runtime_evidence,'
                             'completed_at FROM runs WHERE run_id=?',
                             (run_id,)).fetchone()
            return None if row is None else dict(request_digest=row[0], state=row[1],
                                                  response=json.loads(row[2]) if row[2] else None,
                                                  error=row[3], adapter_id=row[4], binding_id=row[5],
                                                  binding_revision=row[6], capability_revision=row[7],
                                                  operation=row[8], output_format=row[9],
                                                  role_id=row[10], role_revision=row[11],
                                                  manifest_sha256=row[12], error_code=row[13],
                                                  runtime_evidence=(json.loads(row[14])
                                                                    if row[14] else None),
                                                  completed_at=row[15])

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


class OllamaRuns(BackendRuns):
    """Compatibility wrapper retaining the existing Ollama journal path."""
    def __init__(self, state_dir):
        super().__init__(state_dir, 'ollama-runs.sqlite')

    def latest_runtime(self, binding_id=None, binding_revision=None):
        if binding_id is not None:
            require(isinstance(binding_id, str) and binding_id,
                    'Invalid Ollama binding ID')
        if binding_revision is not None:
            require(binding_id is not None and isinstance(binding_revision, str)
                    and binding_revision, 'Invalid Ollama binding revision')
        connection = self.connect_readonly()
        if connection is None:
            return None
        with connection as db:
            query = ('SELECT run_id,runtime_evidence,completed_at,binding_revision FROM runs '
                     "WHERE state='succeeded' AND runtime_evidence IS NOT NULL")
            parameters = ()
            if binding_id is not None:
                query += ' AND binding_id=?'; parameters = (binding_id,)
            query += ' ORDER BY completed_at DESC, rowid DESC LIMIT 4096'
            rows = db.execute(query, parameters).fetchall()
        row = next((item for item in rows
                    if binding_revision is None
                    or runtime_binding_revision_matches(binding_revision, item[3])), None)
        return None if row is None else {'run_id': row[0],
            'runtime_evidence': json.loads(row[1]), 'completed_at': row[2]}


class OllamaAdapter:
    def __init__(self, runs, transport=None, stream_transport=None, runtime_probe=None):
        require(isinstance(runs, OllamaRuns), 'Ollama run store is required')
        self.runs = runs
        custom_transport = transport is not None or stream_transport is not None
        self.transport = transport or self._http_transport
        self.stream_transport = stream_transport or self._http_stream_transport
        require(runtime_probe is None or callable(runtime_probe),
                'Ollama runtime probe must be callable')
        self.runtime_probe = (runtime_probe if runtime_probe is not None else
                              (lambda _binding: unknown(
                                  'probe-not-configured', source='ollama:/api/ps'))
                              if custom_transport else self.probe_runtime)

    @staticmethod
    def _task_text(raw):
        if raw.startswith(b'%PDF-'):
            return pdf_text(raw), 'PDF text projection'
        try:
            return raw.decode('utf-8'), None
        except UnicodeError as exc:
            raise ValueError('Ollama task input is not valid UTF-8 or a supported PDF') from exc

    @staticmethod
    def _prompt(payload):
        try:
            value = json.loads(payload)
        except (UnicodeError, ValueError):
            return payload.decode('utf-8')
        task = value.get('task') if isinstance(value, dict) else None
        conversation = value.get('conversation') if isinstance(value, dict) else None
        language = value.get('response_language') if isinstance(value, dict) else None
        language_instruction = ''
        if language is not None:
            from spikes.response_language import LANGUAGE_SOURCES, language_tag
            require(isinstance(language, dict) and set(language) == {'tag', 'source'}
                    and language.get('source') in LANGUAGE_SOURCES
                    and language_tag(language.get('tag')) == language.get('tag'),
                    'Invalid response language payload for Ollama')
            language_name = {'cs-CZ': 'Czech', 'sk-SK': 'Slovak',
                             'en-US': 'English', 'de-DE': 'German'}.get(language['tag'])
            language_label = (f'{language_name} ({language["tag"]})'
                              if language_name else language['tag'])
            language_instruction = ('Response language requirement: write the answer in '
                                    f'{language_label}. Treat this BCP 47 tag as an explicit '
                                    'output preference. Do not translate quoted source content. '
                                    'Do not claim that compliance is guaranteed.\n\n')
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
                    raw = base64.b64decode(source['content_b64'], validate=True)
                    content, projection = OllamaAdapter._task_text(raw)
                except (TypeError, ValueError, UnicodeError) as exc:
                    raise ValueError('Ollama task input has no safe text projection') from exc
                decoded.append((source['input_id'], content, projection))
            roles = {}
            if conversation is not None:
                require(isinstance(conversation, list), 'Invalid task conversation for Ollama')
                roles = {item['message_id']: item['role'] for item in conversation
                         if isinstance(item, dict) and set(item) == {'message_id', 'role'}
                         and item['role'] in {'user', 'assistant'}}
                require(len(roles) == len(conversation), 'Invalid task conversation for Ollama')
                selected_ids = [input_id for input_id, _, _ in decoded if input_id in roles]
                require(selected_ids == [item['message_id'] for item in conversation],
                        'Task conversation does not match input order')
            sections = ['Instruction:\n' + task['instruction']]
            for input_id, content, projection in decoded:
                if input_id == task['focus_input_id']:
                    label = ('Focus ID ' + input_id if task['role_id'] in
                             {'task-router', 'task-output'}
                             else 'Focus')
                elif input_id in roles:
                    label = 'User message' if roles[input_id] == 'user' else 'Assistant message'
                    if task['role_id'] in {'external-call-planner', 'task-router',
                                           'task-output'}:
                        label += ' ID ' + input_id
                else:
                    label = 'Source ' + input_id
                if projection is not None:
                    label += ' (' + projection + ')'
                sections.append(label + ':\n' + content)
            sections.append('Summary:\n')
            return language_instruction + '\n\n'.join(sections)
        if conversation is None:
            return language_instruction + payload.decode('utf-8')
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
        return language_instruction + '\n\n'.join(transcript)

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
    def _request(handoff, binding, role=None, output_format='text', *, stream=False):
        from spikes.context_builder import DispatchHandoff
        require(isinstance(handoff, DispatchHandoff) and isinstance(binding, OllamaBinding),
                'Authorized handoff and Ollama binding are required')
        require(handoff.target == binding.target(), 'Ollama binding differs from authorized target')
        require(type(stream) is bool, 'Invalid Ollama streaming choice')
        body = dict(model=binding.model, prompt=OllamaAdapter._prompt(handoff.payload),
                    stream=stream)
        if output_format == 'json':
            if role is not None and role.role_id == 'task-router':
                body['format'] = (_PRESENTATION_PROPOSAL_FORMAT
                                  if role.revision == 'task-router-presentation-v1'
                                  else _TASK_ROUTER_FORMAT)
            elif role is not None and role.role_id == 'task-output':
                body['format'] = {
                    'task-output-conversation-v1': _DIRECT_ANSWER_FORMAT,
                    'task-output-document-v1': _DOCUMENT_DRAFT_FORMAT,
                    'task-output-presentation-v1': _PRESENTATION_PROPOSAL_FORMAT,
                }[role.revision]
            else:
                body['format'] = 'json'
        request = json.dumps(body, sort_keys=True,
                             separators=(',', ':')).encode()
        execution = OllamaAdapter._execution(binding, role, output_format)
        base = handoff.manifest_sha256.encode() + b'\0' + request
        legacy_digest = hashlib.sha256(base).hexdigest()
        digest = hashlib.sha256(base + b'\0' + execution.canonical()).hexdigest()
        return request, digest, legacy_digest, execution

    def prepare(self, handoff, binding, role=None, output_format='text', *, stream=False):
        _, digest, legacy_digest, execution = self._request(
            handoff, binding, role, output_format, stream=stream)
        return self.runs.prepare(handoff.run_id, digest, legacy_digest, execution,
                                 handoff.manifest_sha256)

    def dispatch(self, handoff, binding, role=None, output_format='text'):
        return self._dispatch(handoff, binding, role, output_format, False,
                              lambda _delta: None, lambda _status: None)

    def dispatch_stream(self, handoff, binding, on_delta, on_status=None,
                        role=None, output_format='text'):
        require(callable(on_delta), 'Ollama stream delta callback is required')
        require(on_status is None or callable(on_status),
                'Ollama stream status callback is invalid')
        return self._dispatch(handoff, binding, role, output_format, True, on_delta,
                              on_status or (lambda _status: None))

    def _dispatch(self, handoff, binding, role, output_format, stream,
                  on_delta, on_status):
        request, digest, legacy_digest, execution = self._request(
            handoff, binding, role, output_format, stream=stream)
        row = self.runs.prepare(handoff.run_id, digest, legacy_digest, execution,
                                handoff.manifest_sha256)
        if row['state'] == 'succeeded':
            return row['response']
        if row['state'] in {'dispatching', 'unknown'}:
            raise UnknownRun('Ollama result is unknown; automatic retry is forbidden',
                             code=row.get('error_code') or 'outcome-unknown')
        if row['state'] != 'prepared':
            raise OllamaResponseError(row['error'] or 'Ollama run failed; explicit new run required',
                                      code=row.get('error_code') or 'response-invalid')
        # Revalidate the exact binding again immediately before crossing the transport boundary.
        require(handoff.target == binding.target(), 'Ollama binding changed before dispatch')
        expectation = OllamaRuntimePolicy(self.runs.root).load(binding)
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            result = db.execute("UPDATE runs SET state='dispatching' WHERE run_id=? AND state='prepared'",
                                (handoff.run_id,))
            require(result.rowcount == 1, 'Ollama run state changed before dispatch')
            db.commit()
        try:
            if stream:
                on_status('connecting')
                response = self.stream_transport(
                    binding, request, on_delta, on_status)
            else:
                response = self.transport(binding, request)
            self._validate_response(response, binding)
        except OllamaResponseError as exc:
            with self.runs.connect() as db, db:
                db.execute("UPDATE runs SET state='failed',error=?,error_code=? "
                           "WHERE run_id=? AND state='dispatching'",
                           (str(exc), exc.code, handoff.run_id))
            raise
        except _OllamaTransportUnknown as exc:
            with self.runs.connect() as db, db:
                db.execute("UPDATE runs SET state='unknown',error=?,error_code=? "
                           "WHERE run_id=? AND state='dispatching'",
                           (str(exc), exc.code, handoff.run_id))
            raise UnknownRun('Ollama dispatch outcome is unknown', code=exc.code) from exc
        except Exception as exc:
            with self.runs.connect() as db, db:
                db.execute("UPDATE runs SET state='unknown',error=?,error_code=? "
                           "WHERE run_id=? AND state='dispatching'",
                           (type(exc).__name__, 'transport-unknown', handoff.run_id))
            raise UnknownRun('Ollama dispatch outcome is unknown',
                             code='transport-unknown') from exc
        try:
            runtime_evidence = self.runtime_probe(binding)
            require(isinstance(runtime_evidence, dict)
                    and runtime_evidence.get('status') in {'available', 'unknown'},
                    'Invalid Ollama runtime evidence')
        except Exception as exc:
            runtime_evidence = unknown('probe-failed', source='ollama:/api/ps')
            runtime_evidence['diagnostic'] = type(exc).__name__
        runtime_evidence = dict(runtime_evidence,
            expected_processor=expectation['expected_processor'],
            expectation_revision=expectation['revision'])
        encoded = json.dumps(response, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        encoded_runtime = json.dumps(runtime_evidence, ensure_ascii=False,
                                     sort_keys=True, separators=(',', ':'))
        completed_at = datetime.now(timezone.utc).isoformat(
            timespec='microseconds').replace('+00:00', 'Z')
        with self.runs.connect() as db, db:
            result = db.execute("UPDATE runs SET state='succeeded',response=?,"
                                "runtime_evidence=?,completed_at=? "
                                "WHERE run_id=? AND state='dispatching'",
                                (encoded, encoded_runtime, completed_at, handoff.run_id))
            require(result.rowcount == 1, 'Ollama completion state changed')
        return response

    @staticmethod
    def _validate_response(response, binding):
        if not (isinstance(response, dict) and response.get('model') == binding.model
                and isinstance(response.get('response'), str)
                and response.get('done', True) is True):
            raise OllamaResponseError('Invalid Ollama response', code='invalid-envelope')

    @staticmethod
    def _http_transport(binding, request):
        return OllamaAdapter._json_transport(
            binding, 'POST', '/api/generate', request,
            timeout=OLLAMA_GENERATE_TIMEOUT, uncertain_after_send=True)

    @staticmethod
    def _http_stream_transport(binding, request, on_delta, on_status):
        parsed = urlsplit(binding.endpoint)
        if binding.boundary == 'same-node':
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=OLLAMA_FIRST_TOKEN_TIMEOUT)
        else:
            connection = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=OLLAMA_FIRST_TOKEN_TIMEOUT,
                context=ssl._create_unverified_context())
        try:
            try:
                connection.connect()
            except TimeoutError as exc:
                raise OllamaResponseError('Ollama connection timed out',
                                          code='connect-timeout') from exc
            except ssl.SSLError as exc:
                raise OllamaResponseError('Ollama TLS handshake failed',
                                          code='tls-failed') from exc
            except OSError as exc:
                raise OllamaResponseError('Ollama endpoint is unavailable',
                                          code='unavailable') from exc
            if binding.tls_cert_sha256:
                try:
                    certificate = connection.sock.getpeercert(binary_form=True)
                except (AttributeError, OSError, ssl.SSLError) as exc:
                    raise OllamaResponseError('Ollama TLS certificate is unavailable',
                                              code='tls-failed') from exc
                if hashlib.sha256(certificate).hexdigest() != binding.tls_cert_sha256:
                    raise OllamaResponseError('Ollama TLS certificate pin mismatch',
                                              code='tls-pin-mismatch')
            try:
                connection.request('POST', '/api/generate', body=request,
                                   headers={'Accept': 'application/x-ndjson',
                                            'Content-Type': 'application/json'})
                response = connection.getresponse()
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                raise _OllamaTransportUnknown(
                    'Ollama stream was interrupted after dispatch',
                    code='first-token-timeout' if isinstance(exc, TimeoutError)
                    else 'transport-interrupted') from exc
            if 300 <= response.status < 400:
                raise OllamaResponseError('Ollama redirect is forbidden',
                                          code='redirect-forbidden')
            if response.status != 200:
                codes = {400: 'request-rejected', 401: 'access-denied',
                         403: 'access-denied', 404: 'model-unavailable',
                         429: 'overloaded', 503: 'overloaded'}
                raise OllamaResponseError(f'Ollama returned HTTP {response.status}',
                                          code=codes.get(response.status, 'http-error'))
            on_status('waiting-first-token')
            if connection.sock is not None:
                connection.sock.settimeout(OLLAMA_FIRST_TOKEN_TIMEOUT)
            chunks = []
            total = events = response_bytes = 0
            thinking_seen = False
            while True:
                try:
                    raw = response.readline(MAX_STREAM_LINE + 1)
                except (TimeoutError, OSError, http.client.HTTPException) as exc:
                    raise _OllamaTransportUnknown(
                        'Ollama stream became idle or was interrupted',
                        code='first-token-timeout' if events == 0 and isinstance(exc, TimeoutError)
                        else 'idle-timeout' if isinstance(exc, TimeoutError)
                        else 'transport-interrupted') from exc
                if not raw:
                    raise _OllamaTransportUnknown(
                        'Ollama stream ended before the final frame',
                        code='stream-incomplete')
                if len(raw) > MAX_STREAM_LINE:
                    raise OllamaResponseError('Ollama stream frame exceeds 1 MiB',
                                              code='stream-frame-too-large')
                total += len(raw); events += 1
                if total > MAX_STREAM_RESPONSE or events > MAX_STREAM_EVENTS:
                    raise OllamaResponseError('Ollama stream exceeds configured limits',
                                              code='stream-too-large')
                try:
                    frame = json.loads(raw)
                except (UnicodeError, ValueError) as exc:
                    raise OllamaResponseError('Invalid Ollama NDJSON frame',
                                              code='invalid-stream-json') from exc
                if not (isinstance(frame, dict) and frame.get('model') == binding.model
                        and isinstance(frame.get('created_at'), str)
                        and isinstance(frame.get('response'), str)
                        and isinstance(frame.get('thinking', ''), str)
                        and type(frame.get('done')) is bool and 'error' not in frame):
                    raise OllamaResponseError('Invalid Ollama stream envelope',
                                              code='invalid-stream-envelope')
                if frame['done']:
                    if frame['response']:
                        raise OllamaResponseError('Ollama final stream frame contains text',
                                                  code='invalid-stream-final')
                    numeric = ('total_duration', 'load_duration', 'prompt_eval_count',
                               'prompt_eval_cached_count', 'prompt_eval_duration',
                               'eval_count', 'eval_duration')
                    if any(name in frame and (type(frame[name]) is not int
                           or frame[name] < 0) for name in numeric):
                        raise OllamaResponseError('Invalid Ollama final stream metrics',
                                                  code='invalid-stream-final')
                    if ('done_reason' in frame and not isinstance(frame['done_reason'], str)):
                        raise OllamaResponseError('Invalid Ollama final stream reason',
                                                  code='invalid-stream-final')
                    result = dict(frame); result.pop('thinking', None)
                    result['response'] = ''.join(chunks)
                    return result
                thinking = frame.get('thinking', '')
                if thinking:
                    if connection.sock is not None:
                        connection.sock.settimeout(OLLAMA_IDLE_TIMEOUT)
                    if not chunks and not thinking_seen:
                        on_status('thinking')
                    thinking_seen = True
                    # Reasoning remains private provider output. Its bytes are bounded by
                    # the complete NDJSON limit above and are never exposed or persisted.
                delta = frame['response']
                if delta:
                    if connection.sock is not None:
                        connection.sock.settimeout(OLLAMA_IDLE_TIMEOUT)
                    if not chunks:
                        on_status('generating')
                    chunks.append(delta)
                    response_bytes += len(delta.encode())
                    if response_bytes > MAX_STREAM_RESPONSE:
                        raise OllamaResponseError('Ollama streamed text exceeds 16 MiB',
                                                  code='response-too-large')
                    on_delta(delta)
        finally:
            try:
                connection.close()
            except OSError:
                pass

    @staticmethod
    def _json_transport(binding, method, path, body=None, *, timeout, uncertain_after_send):
        parsed = urlsplit(binding.endpoint)
        if binding.boundary == 'same-node':
            connection = http.client.HTTPConnection(
                parsed.hostname, parsed.port, timeout=timeout)
        else:
            context = ssl._create_unverified_context()
            connection = http.client.HTTPSConnection(
                parsed.hostname, parsed.port, timeout=timeout,
                context=context)
        try:
            try:
                connection.connect()
            except TimeoutError as exc:
                raise OllamaResponseError('Ollama connection timed out',
                                          code='connect-timeout') from exc
            except ssl.SSLError as exc:
                raise OllamaResponseError('Ollama TLS handshake failed',
                                          code='tls-failed') from exc
            except OSError as exc:
                raise OllamaResponseError('Ollama endpoint is unavailable',
                                          code='unavailable') from exc
            if binding.tls_cert_sha256:
                try:
                    certificate = connection.sock.getpeercert(binary_form=True)
                except (AttributeError, OSError, ssl.SSLError) as exc:
                    raise OllamaResponseError('Ollama TLS certificate is unavailable',
                                              code='tls-failed') from exc
                if hashlib.sha256(certificate).hexdigest() != binding.tls_cert_sha256:
                    raise OllamaResponseError('Ollama TLS certificate pin mismatch',
                                              code='tls-pin-mismatch')
            headers = {'Accept': 'application/json'}
            if body is not None:
                headers['Content-Type'] = 'application/json'
            try:
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse()
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                if uncertain_after_send:
                    raise _OllamaTransportUnknown(
                        'Ollama transport was interrupted after dispatch',
                        code='response-timeout' if isinstance(exc, TimeoutError)
                        else 'transport-interrupted') from exc
                raise OllamaResponseError('Ollama healthcheck transport failed',
                                          code='healthcheck-unavailable') from exc
            if 300 <= response.status < 400:
                raise OllamaResponseError('Ollama redirect is forbidden', code='redirect-forbidden')
            if response.status != 200:
                codes = {400: 'request-rejected', 401: 'access-denied',
                         403: 'access-denied', 404: ('model-unavailable'
                         if path == '/api/generate' else 'api-incompatible'),
                         429: 'overloaded', 503: 'overloaded'}
                raise OllamaResponseError(f'Ollama returned HTTP {response.status}',
                                          code=codes.get(response.status, 'http-error'))
            try:
                raw = response.read(16 * 1024 * 1024 + 1)
            except (TimeoutError, OSError, http.client.HTTPException) as exc:
                if uncertain_after_send:
                    raise _OllamaTransportUnknown(
                        'Ollama response was interrupted',
                        code='response-timeout' if isinstance(exc, TimeoutError)
                        else 'transport-interrupted') from exc
                raise OllamaResponseError('Ollama healthcheck response failed',
                                          code='healthcheck-unavailable') from exc
            if len(raw) > 16 * 1024 * 1024:
                raise OllamaResponseError('Ollama response exceeds 16 MiB',
                                          code='response-too-large')
            try:
                return json.loads(raw)
            except (UnicodeError, ValueError) as exc:
                raise OllamaResponseError('Invalid Ollama JSON response',
                                          code='invalid-json') from exc
        finally:
            try:
                connection.close()
            except OSError:
                pass

    @staticmethod
    def probe(binding, *, timeout=10):
        require(isinstance(binding, OllamaBinding), 'Validated Ollama binding is required')
        value = OllamaAdapter._json_transport(
            binding, 'GET', '/api/tags', timeout=timeout, uncertain_after_send=False)
        models = value.get('models') if isinstance(value, dict) else None
        if not (isinstance(models, list) and len(models) <= 4096):
            raise OllamaResponseError('Invalid Ollama model catalog', code='invalid-envelope')
        names = []
        for item in models:
            name = item.get('name') if isinstance(item, dict) else None
            if not (isinstance(name, str) and name and len(name.encode()) <= 4096):
                raise OllamaResponseError('Invalid Ollama model catalog', code='invalid-envelope')
            names.append(name)
        return {'status': 'available', 'diagnostic': ('ok' if binding.model in names
                else 'model-unavailable'), 'model': binding.model,
                'model_available': binding.model in names, 'model_count': len(names),
                'boundary': binding.boundary, 'endpoint': binding.endpoint,
                'target_id': binding.target_id}

    @staticmethod
    def probe_runtime(binding, *, timeout=10):
        """Read current model allocation from the exact already-approved endpoint."""
        require(isinstance(binding, OllamaBinding), 'Validated Ollama binding is required')
        value = OllamaAdapter._json_transport(
            binding, 'GET', '/api/ps', timeout=timeout, uncertain_after_send=False)
        models = value.get('models') if isinstance(value, dict) else None
        if not (isinstance(models, list) and len(models) <= 4096):
            raise OllamaResponseError('Invalid Ollama runtime response',
                                      code='invalid-runtime-envelope')
        matches = []
        for item in models:
            if not isinstance(item, dict):
                raise OllamaResponseError('Invalid Ollama runtime model',
                                          code='invalid-runtime-envelope')
            name, model = item.get('name'), item.get('model')
            size, size_vram = item.get('size'), item.get('size_vram')
            if not (isinstance(name, str) and isinstance(model, str)
                    and type(size) is int and size > 0
                    and type(size_vram) is int and 0 <= size_vram <= size):
                raise OllamaResponseError('Invalid Ollama runtime model',
                                          code='invalid-runtime-envelope')
            if binding.model in {name, model}:
                matches.append((item, size, size_vram))
        if len(matches) != 1:
            result = unknown('model-not-running' if not matches else 'ambiguous-model',
                             source='ollama:/api/ps')
            result.update(observed_at=observed_at(), model=binding.model,
                          binding_id=binding.binding_id,
                          binding_revision=binding.revision,
                          boundary=binding.boundary, target_id=binding.target_id)
            return result
        item, size, size_vram = matches[0]
        processor = ('cpu' if size_vram == 0 else
                     'gpu' if size_vram == size else 'partial-gpu')
        return {'status': 'available', 'source': 'ollama:/api/ps',
                'observed_at': observed_at(), 'model': binding.model,
                'reported_name': item['name'], 'reported_model': item['model'],
                'processor': processor, 'model_bytes': size,
                'vram_bytes': size_vram,
                'vram_ratio': round(size_vram / size, 6),
                'binding_id': binding.binding_id,
                'binding_revision': binding.revision,
                'boundary': binding.boundary, 'target_id': binding.target_id}
