# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed OpenAI Responses adapter with node-local credentials and runs."""
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import sqlite3
import ssl
import stat

from spikes.backend_contract import (BackendCapabilities, BackendExecution,
                                     BackendResponseError, BackendUnknown, ROLES)
from spikes.context_builder import DispatchHandoff, Target
from spikes.metadata import require, uuid
from spikes.ollama_backend import BACKENDS, BackendRuns, OllamaAdapter


OPENAI_ENDPOINT = 'https://api.openai.com/v1/responses'
OPENAI_TIMEOUT = 180
MAX_RESPONSE = 16 * 1024 * 1024
MAX_MODEL_RESPONSE = 1024 * 1024
_REFERENCE = re.compile(r'credential:[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_RESPONSES_MODEL = re.compile(r'(?:gpt-[A-Za-z0-9._-]+|o[134](?:-[A-Za-z0-9._-]+)?)')
_NON_TEXT_MODEL_MARKERS = ('audio', 'image', 'realtime', 'search', 'transcribe',
                           'tts', 'embedding', 'moderation')


class OpenAIUnknownRun(BackendUnknown):
    pass


class OpenAIResponseError(BackendResponseError):
    pass


@dataclass(frozen=True)
class OpenAIBinding:
    binding_id: str
    revision: str
    endpoint: str
    model: str
    target_id: str
    credential_ref: str
    credential_revision: int
    max_output_tokens: int
    timeout_seconds: int

    adapter_id = 'openai-responses'
    boundary = 'external-provider'

    @classmethod
    def parse(cls, value):
        required = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                    'endpoint', 'model', 'target_id', 'credential_ref',
                    'credential_revision', 'max_output_tokens', 'timeout_seconds'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing OpenAI binding field')
        require(value['schema_version'] == 1 and value['adapter'] == cls.adapter_id
                and value['boundary'] == cls.boundary,
                'Unsupported OpenAI binding')
        uuid(value['binding_id'])
        require(value['target_id'] == 'api.openai.com' and value['endpoint'] == OPENAI_ENDPOINT,
                'OpenAI binding requires the fixed official Responses endpoint')
        for key in ('revision', 'model'):
            require(isinstance(value[key], str) and value[key].strip() == value[key]
                    and bool(value[key]) and not any(c in value[key] for c in '\0\r\n'),
                    f'Invalid OpenAI {key}')
        require(bool(_MODEL_ID.fullmatch(value['model'])),
                'OpenAI binding requires a valid model ID')
        require(isinstance(value['credential_ref'], str)
                and bool(_REFERENCE.fullmatch(value['credential_ref'])),
                'OpenAI binding requires an opaque credential reference')
        require(type(value['credential_revision']) is int
                and value['credential_revision'] >= 1,
                'Invalid OpenAI credential revision')
        require(type(value['max_output_tokens']) is int
                and 1 <= value['max_output_tokens'] <= 128000,
                'Invalid OpenAI output token limit')
        require(type(value['timeout_seconds']) is int
                and 1 <= value['timeout_seconds'] <= OPENAI_TIMEOUT,
                'Invalid OpenAI timeout')
        return cls(value['binding_id'], value['revision'], value['endpoint'],
                   value['model'], value['target_id'], value['credential_ref'],
                   value['credential_revision'], value['max_output_tokens'],
                   value['timeout_seconds'])

    def target(self):
        return Target(self.binding_id, self.revision, self.boundary,
                      self.target_id, self.model)

    def capabilities(self):
        return BackendCapabilities(1, 'openai-responses-v1',
                                   frozenset({'generate-text'}),
                                   frozenset({'text', 'json'})).validate()

    def serialize(self):
        return dict(schema_version=1, binding_id=self.binding_id,
                    revision=self.revision, adapter=self.adapter_id,
                    boundary=self.boundary, endpoint=self.endpoint,
                    model=self.model, target_id=self.target_id,
                    credential_ref=self.credential_ref,
                    credential_revision=self.credential_revision,
                    max_output_tokens=self.max_output_tokens,
                    timeout_seconds=self.timeout_seconds)


class OpenAIBindings:
    """Atomic node-local OpenAI binding configuration outside project Git."""
    def __init__(self, state_dir):
        self.root = _safe_root(state_dir)
        self.path = self.root / 'openai-binding.json'

    def save(self, binding):
        require(isinstance(binding, OpenAIBinding), 'Validated OpenAI binding is required')
        raw = (json.dumps(binding.serialize(), sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        _atomic_write(self.root, self.path, raw, '.openai-binding-' + binding.binding_id)

    def load(self):
        return OpenAIBinding.parse(_read_json(self.path, 'OpenAI binding'))


class OpenAICredentials:
    """Write-only node-local secret values addressed by opaque references."""
    def __init__(self, state_dir, filename='openai-credentials.sqlite'):
        self.root = _safe_root(state_dir)
        require(filename in {'openai-credentials.sqlite', 'openai-admin-credentials.sqlite'},
                'Invalid OpenAI credential store')
        self.path = self.root / filename

    def connect(self):
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe OpenAI credential store')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS credentials ('
                   'reference TEXT PRIMARY KEY, secret TEXT NOT NULL, revision INTEGER NOT NULL)')
        db.commit()
        return closing(db)

    def put(self, reference, secret):
        require(isinstance(reference, str) and bool(_REFERENCE.fullmatch(reference)),
                'Invalid credential reference')
        require(isinstance(secret, str) and secret.strip() == secret
                and 20 <= len(secret) <= 4096 and not any(c in secret for c in '\0\r\n'),
                'Invalid OpenAI credential')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision FROM credentials WHERE reference=?',
                             (reference,)).fetchone()
            revision = 1 if row is None else row[0] + 1
            db.execute('INSERT INTO credentials(reference,secret,revision) VALUES (?,?,?) '
                       'ON CONFLICT(reference) DO UPDATE SET secret=excluded.secret,'
                       'revision=excluded.revision', (reference, secret, revision))
            db.commit()
        return {'reference': reference, 'available': True, 'revision': revision}

    def status(self, reference):
        require(isinstance(reference, str) and bool(_REFERENCE.fullmatch(reference)),
                'Invalid credential reference')
        with self.connect() as db:
            row = db.execute('SELECT revision FROM credentials WHERE reference=?',
                             (reference,)).fetchone()
        return {'reference': reference, 'available': row is not None,
                'revision': None if row is None else row[0]}

    def resolve(self, reference):
        require(isinstance(reference, str) and bool(_REFERENCE.fullmatch(reference)),
                'Invalid credential reference')
        with self.connect() as db:
            row = db.execute('SELECT secret,revision FROM credentials WHERE reference=?',
                             (reference,)).fetchone()
        require(row is not None, 'OpenAI credential is unavailable')
        return row[0], row[1]

    def delete(self, reference):
        require(isinstance(reference, str) and bool(_REFERENCE.fullmatch(reference)),
                'Invalid credential reference')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('DELETE FROM credentials WHERE reference=?',
                                 (reference,)).rowcount
            db.commit()
        return {'reference': reference, 'available': False, 'deleted': bool(changed)}


class OpenAIModelCatalog:
    """Bounded node-local projection of model IDs visible to one credential."""
    def __init__(self, state_dir, credentials, transport=None):
        require(isinstance(credentials, OpenAICredentials),
                'OpenAI credential store is required')
        self.root = _safe_root(state_dir)
        self.path = self.root / 'openai-models.json'
        self.credentials = credentials
        self.transport = transport or self._http_transport

    def refresh(self, binding):
        require(isinstance(binding, OpenAIBinding), 'OpenAI binding is required')
        secret, revision = self.credentials.resolve(binding.credential_ref)
        require(revision == binding.credential_revision,
                'OpenAI credential revision differs from binding')
        models = self._parse(self.transport(binding, secret))
        value = {'schema_version': 1, 'binding_id': binding.binding_id,
                 'credential_revision': revision,
                 'fetched_at': datetime.now(timezone.utc).isoformat(),
                 'models': models}
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        _atomic_replace(self.root, self.path, raw, '.openai-models-')
        return value

    def load(self, binding):
        require(isinstance(binding, OpenAIBinding), 'OpenAI binding is required')
        value = _read_json(self.path, 'OpenAI model catalog')
        required = {'schema_version', 'binding_id', 'credential_revision',
                    'fetched_at', 'models'}
        require(isinstance(value, dict) and set(value) == required
                and value['schema_version'] == 1
                and value['binding_id'] == binding.binding_id
                and value['credential_revision'] == binding.credential_revision,
                'OpenAI model catalog does not match the current binding')
        value['models'] = self._validate_models(value['models'])
        require(isinstance(value['fetched_at'], str) and value['fetched_at'],
                'Invalid OpenAI model catalog timestamp')
        return value

    @staticmethod
    def _parse(value):
        require(isinstance(value, dict) and value.get('object') == 'list'
                and isinstance(value.get('data'), list)
                and len(value['data']) <= 10000,
                'Invalid OpenAI model list')
        models = []
        for item in value['data']:
            require(isinstance(item, dict) and isinstance(item.get('id'), str),
                    'Invalid OpenAI model entry')
            model = item['id']
            if (_MODEL_ID.fullmatch(model) and _RESPONSES_MODEL.fullmatch(model)
                    and not any(marker in model.lower()
                                for marker in _NON_TEXT_MODEL_MARKERS)):
                models.append(model)
        return OpenAIModelCatalog._validate_models(sorted(set(models)))

    @staticmethod
    def _validate_models(models):
        require(isinstance(models, list) and len(models) <= 10000
                and all(isinstance(model, str) and _MODEL_ID.fullmatch(model)
                        for model in models)
                and models == sorted(set(models)),
                'Invalid OpenAI model catalog')
        return models

    @staticmethod
    def _http_transport(binding, secret):
        connection = http.client.HTTPSConnection('api.openai.com', 443,
            timeout=binding.timeout_seconds, context=ssl.create_default_context())
        try:
            connection.request('GET', '/v1/models',
                headers={'Authorization': 'Bearer ' + secret})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise OpenAIResponseError('OpenAI model list redirect is forbidden')
            if response.status < 200 or response.status >= 300:
                raise OpenAIResponseError('OpenAI model list was rejected with HTTP '
                                          + str(response.status))
            raw = response.read(MAX_MODEL_RESPONSE + 1)
            require(len(raw) <= MAX_MODEL_RESPONSE,
                    'OpenAI model list exceeds 1 MiB')
            return json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise OpenAIResponseError('Invalid OpenAI model list JSON') from exc
        finally:
            connection.close()


class OpenAIRuns(BackendRuns):
    def __init__(self, state_dir):
        super().__init__(state_dir, 'openai-runs.sqlite')


class OpenAIAdapter:
    def __init__(self, runs, credentials, transport=None, stream_transport=None):
        require(isinstance(runs, OpenAIRuns), 'OpenAI run store is required')
        require(isinstance(credentials, OpenAICredentials),
                'OpenAI credential store is required')
        self.runs = runs
        self.credentials = credentials
        self.transport = transport or self._http_transport
        self.stream_transport = stream_transport or self._http_stream_transport

    @staticmethod
    def _execution(binding, role=None, output_format='text'):
        capabilities = binding.capabilities()
        if role is None:
            operation = 'generate-text'; role_id = role_revision = ''
        else:
            role = ROLES.resolve(role.role_id, role.revision)
            require(role.output_format == output_format,
                    'Role output format differs from backend request')
            operation = role.operation
            role_id, role_revision = role.role_id, role.revision
        capabilities.require(operation, output_format)
        return BackendExecution(binding.adapter_id, binding.binding_id, binding.revision,
                                capabilities.revision, operation, output_format,
                                role_id, role_revision)

    @staticmethod
    def _request(handoff, binding, role=None, output_format='text', stream=False):
        require(isinstance(handoff, DispatchHandoff) and isinstance(binding, OpenAIBinding),
                'Authorized handoff and OpenAI binding are required')
        require(handoff.target == binding.target(),
                'OpenAI binding differs from authorized target')
        require(type(stream) is bool, 'Invalid OpenAI streaming choice')
        body = dict(model=binding.model, input=OllamaAdapter._prompt(handoff.payload),
                    store=False, stream=stream, truncation='disabled',
                    max_output_tokens=binding.max_output_tokens)
        if output_format == 'json':
            body['text'] = {'format': {'type': 'json_object'}}
        request = json.dumps(body, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()
        execution = OpenAIAdapter._execution(binding, role, output_format)
        digest = hashlib.sha256(handoff.manifest_sha256.encode() + b'\0' + request
                                + b'\0' + execution.canonical() + b'\0'
                                + binding.credential_ref.encode() + b'\0'
                                + str(binding.credential_revision).encode()).hexdigest()
        return request, digest, execution

    def prepare(self, handoff, binding, role=None, output_format='text', stream=False):
        _, credential_revision = self.credentials.resolve(binding.credential_ref)
        require(credential_revision == binding.credential_revision,
                'OpenAI credential revision differs from binding')
        _, digest, execution = self._request(
            handoff, binding, role, output_format, stream=stream)
        return self.runs.prepare(handoff.run_id, digest, digest, execution,
                                 handoff.manifest_sha256)

    def dispatch(self, handoff, binding, role=None, output_format='text'):
        return self._dispatch(handoff, binding, role, output_format, False, None)

    def dispatch_stream(self, handoff, binding, on_delta, role=None, output_format='text'):
        require(callable(on_delta), 'OpenAI stream delta callback is required')
        return self._dispatch(handoff, binding, role, output_format, True, on_delta)

    def _dispatch(self, handoff, binding, role, output_format, stream, on_delta):
        request, digest, execution = self._request(
            handoff, binding, role, output_format, stream=stream)
        row = self.runs.prepare(handoff.run_id, digest, digest, execution,
                                handoff.manifest_sha256)
        if row['state'] == 'succeeded':
            return row['response']
        if row['state'] in {'dispatching', 'unknown'}:
            raise OpenAIUnknownRun('OpenAI result is unknown; automatic retry is forbidden')
        if row['state'] != 'prepared':
            raise OpenAIResponseError(row['error'] or
                                      'OpenAI run failed; explicit new run required')
        secret, credential_revision = self.credentials.resolve(binding.credential_ref)
        require(credential_revision == binding.credential_revision,
                'OpenAI credential revision differs from binding')
        require(handoff.target == binding.target(), 'OpenAI binding changed before dispatch')
        current_secret, current_revision = self.credentials.resolve(binding.credential_ref)
        require(current_revision == credential_revision and current_secret == secret,
                'OpenAI credential changed before dispatch')
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE runs SET state='dispatching' "
                                 "WHERE run_id=? AND state='prepared'",
                                 (handoff.run_id,))
            require(changed.rowcount == 1, 'OpenAI run state changed before dispatch')
            db.commit()
        try:
            response = (self.stream_transport(binding, request, secret, on_delta)
                        if stream else self.transport(binding, request, secret))
            normalized = self._response(response, binding)
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            self._finish(handoff.run_id, 'unknown', None, 'OpenAI response was lost')
            raise OpenAIUnknownRun('OpenAI request outcome is unknown; do not retry automatically') from exc
        except ValueError as exc:
            self._finish(handoff.run_id, 'failed', None, str(exc))
            raise OpenAIResponseError(str(exc)) from exc
        except Exception as exc:
            self._finish(handoff.run_id, 'failed', None, str(exc))
            raise
        self._finish(handoff.run_id, 'succeeded', normalized, None)
        return normalized

    def _finish(self, run_id, state, response, error):
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE runs SET state=?,response=?,error=? '
                                 "WHERE run_id=? AND state='dispatching'",
                                 (state, json.dumps(response, sort_keys=True,
                                                    separators=(',', ':')) if response else None,
                                  error, run_id))
            require(changed.rowcount == 1, 'OpenAI run state changed while completing')
            db.commit()

    @staticmethod
    def _response(value, binding):
        require(isinstance(value, dict) and set(value) >= {'id', 'status', 'model', 'output'},
                'Invalid OpenAI response')
        require(value['status'] == 'completed' and value['model'] == binding.model,
                'OpenAI response did not complete with the requested model')
        output = value['output']
        require(isinstance(output, list) and bool(output),
                'OpenAI response has no output items')
        require(all(isinstance(item, dict) and item.get('type') in {'reasoning', 'message'}
                    for item in output),
                'OpenAI response contains an unsupported active output item')
        messages = [item for item in output if item.get('type') == 'message']
        require(len(messages) == 1,
                'OpenAI response must contain exactly one output message')
        message = messages[0]
        require(isinstance(message, dict) and message.get('type') == 'message'
                and set(message) >= {'type', 'content'},
                'OpenAI response contains an unsupported output item')
        content = message['content']
        require(isinstance(content, list) and bool(content)
                and all(isinstance(item, dict) and item.get('type') == 'output_text'
                        and isinstance(item.get('text'), str) for item in content),
                'OpenAI response contains an unsupported content item')
        result = {'id': value['id'], 'model': value['model'],
                  'response': ''.join(item['text'] for item in content)}
        if isinstance(value.get('usage'), dict):
            usage = value['usage']
            allowed = {'input_tokens', 'output_tokens', 'total_tokens'}
            if set(usage) >= allowed and all(type(usage[key]) is int and usage[key] >= 0
                                             for key in allowed):
                result['usage'] = {key: usage[key] for key in sorted(allowed)}
        return result

    @staticmethod
    def _http_transport(binding, request, secret):
        connection = http.client.HTTPSConnection('api.openai.com', 443,
            timeout=binding.timeout_seconds, context=ssl.create_default_context())
        try:
            connection.request('POST', '/v1/responses', body=request,
                headers={'Authorization': 'Bearer ' + secret,
                         'Content-Type': 'application/json'})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise OpenAIResponseError('OpenAI redirect is forbidden')
            if response.status < 200 or response.status >= 300:
                raise OpenAIResponseError('OpenAI request was rejected with HTTP '
                                          + str(response.status))
            raw = response.read(MAX_RESPONSE + 1)
            require(len(raw) <= MAX_RESPONSE, 'OpenAI response exceeds 16 MiB')
            return json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise OpenAIResponseError('Invalid OpenAI response JSON') from exc
        finally:
            connection.close()

    @staticmethod
    def _http_stream_transport(binding, request, secret, on_delta):
        connection = http.client.HTTPSConnection('api.openai.com', 443,
            timeout=binding.timeout_seconds, context=ssl.create_default_context())
        try:
            connection.request('POST', '/v1/responses', body=request,
                headers={'Authorization': 'Bearer ' + secret,
                         'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise OpenAIResponseError('OpenAI redirect is forbidden')
            if response.status < 200 or response.status >= 300:
                raise OpenAIResponseError('OpenAI request was rejected with HTTP '
                                          + str(response.status))
            total = 0; data = []; deltas = []; completed = None; sequence = -1
            while True:
                raw = response.readline(MAX_RESPONSE + 1)
                if not raw:
                    break
                total += len(raw)
                require(total <= MAX_RESPONSE, 'OpenAI stream exceeds 16 MiB')
                require(len(raw) <= MAX_RESPONSE and raw.endswith(b'\n'),
                        'Invalid OpenAI SSE line')
                line = raw.rstrip(b'\r\n')
                if line.startswith(b'data:'):
                    data.append(line[5:].lstrip())
                elif not line:
                    if not data:
                        continue
                    event = json.loads(b'\n'.join(data)); data = []
                    require(isinstance(event, dict) and isinstance(event.get('type'), str),
                            'Invalid OpenAI SSE event')
                    current = event.get('sequence_number')
                    if current is not None:
                        require(type(current) is int and current > sequence,
                                'Invalid OpenAI SSE sequence')
                        sequence = current
                    if event['type'] == 'response.output_text.delta':
                        delta = event.get('delta')
                        require(isinstance(delta, str), 'Invalid OpenAI text delta')
                        deltas.append(delta); on_delta(delta)
                    elif event['type'] == 'response.completed':
                        require(completed is None and isinstance(event.get('response'), dict),
                                'Invalid OpenAI completed event')
                        completed = event['response']
                    elif event['type'] in {'response.failed', 'error'}:
                        raise OpenAIResponseError('OpenAI stream reported failure')
            if data or completed is None:
                raise ConnectionError('OpenAI stream ended before completion')
            normalized = OpenAIAdapter._response(completed, binding)
            require(''.join(deltas) == normalized['response'],
                    'OpenAI stream deltas differ from final response')
            return completed
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise OpenAIResponseError('Invalid OpenAI SSE JSON') from exc
        finally:
            connection.close()


def _safe_root(state_dir):
    root = Path(state_dir).absolute()
    info = root.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            'OpenAI state directory requires owned mode 0700')
    return root


def _atomic_write(root, path, raw, prefix):
    temporary = root / (prefix + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.close(fd); fd = -1
        os.replace(temporary, path)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary.exists():
            temporary.unlink()


def _atomic_replace(root, path, raw, prefix):
    temporary = root / (prefix + os.urandom(8).hex() + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.close(fd); fd = -1
        os.replace(temporary, path)
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary.exists():
            temporary.unlink()


def _read_json(path, label):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe ' + label + ' file')
        raw = os.read(fd, 64 * 1024 + 1)
    finally:
        os.close(fd)
    require(len(raw) <= 64 * 1024, label + ' exceeds 64 KiB')
    try:
        return json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Invalid ' + label + ' JSON') from exc


BACKENDS.register(OpenAIBinding.adapter_id, OpenAIBinding.parse)
