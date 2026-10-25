# SPDX-FileCopyrightText: 2026 Antonín Micka
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed AtlasCloud Responses adapter over an exact reviewed offer."""
from contextlib import closing
from dataclasses import dataclass
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
from spikes.model_catalog import ModelKnowledgeStore, project_catalog
from spikes.ollama_backend import BACKENDS, BackendRuns, OllamaAdapter


ATLASCLOUD_ENDPOINT = 'https://api.atlascloud.ai/v1/responses'
ATLASCLOUD_PROTOCOL = 'openai-responses-v1'
ATLASCLOUD_TIMEOUT = 180
MAX_RESPONSE = 16 * 1024 * 1024
_REFERENCE = re.compile(r'credential:atlascloud-[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,255}')
_OFFER_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}')
_CAPABILITIES = frozenset({'generate-text', 'text-output', 'json-output', 'streaming'})


class AtlasCloudUnknownRun(BackendUnknown):
    pass


class AtlasCloudResponseError(BackendResponseError):
    pass


@dataclass(frozen=True)
class AtlasCloudBinding:
    binding_id: str
    revision: str
    endpoint: str
    model: str
    target_id: str
    credential_ref: str
    credential_revision: int
    offer_id: str
    protocol: str
    knowledge_revision: str
    capability_names: frozenset
    max_output_tokens: int
    timeout_seconds: int

    adapter_id = 'atlascloud-responses'
    boundary = 'external-provider'

    @classmethod
    def parse(cls, value):
        required = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                    'endpoint', 'model', 'target_id', 'credential_ref',
                    'credential_revision', 'offer_id', 'protocol',
                    'knowledge_revision', 'capabilities', 'max_output_tokens',
                    'timeout_seconds'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing AtlasCloud binding field')
        require(value['schema_version'] == 1 and value['adapter'] == cls.adapter_id
                and value['boundary'] == cls.boundary,
                'Unsupported AtlasCloud binding')
        uuid(value['binding_id'])
        require(value['endpoint'] == ATLASCLOUD_ENDPOINT
                and value['target_id'] == 'api.atlascloud.ai',
                'AtlasCloud binding requires the fixed official Responses endpoint')
        require(value['protocol'] == ATLASCLOUD_PROTOCOL,
                'Unsupported AtlasCloud protocol')
        for key in ('revision', 'knowledge_revision'):
            require(isinstance(value[key], str) and value[key].strip() == value[key]
                    and bool(value[key]) and not any(c in value[key] for c in '\0\r\n'),
                    'Invalid AtlasCloud ' + key.replace('_', ' '))
        require(isinstance(value['model'], str) and bool(_MODEL_ID.fullmatch(value['model'])),
                'AtlasCloud binding requires a valid model ID')
        require(isinstance(value['offer_id'], str)
                and bool(_OFFER_ID.fullmatch(value['offer_id'])),
                'AtlasCloud binding requires a valid offer ID')
        require(isinstance(value['credential_ref'], str)
                and bool(_REFERENCE.fullmatch(value['credential_ref'])),
                'AtlasCloud binding requires an opaque credential reference')
        require(type(value['credential_revision']) is int
                and value['credential_revision'] >= 1,
                'Invalid AtlasCloud credential revision')
        capabilities = value['capabilities']
        require(isinstance(capabilities, list) and capabilities == sorted(set(capabilities))
                and set(capabilities) <= _CAPABILITIES
                and {'generate-text', 'text-output'} <= set(capabilities),
                'Invalid AtlasCloud capability snapshot')
        require(type(value['max_output_tokens']) is int
                and 1 <= value['max_output_tokens'] <= 128000,
                'Invalid AtlasCloud output token limit')
        require(type(value['timeout_seconds']) is int
                and 1 <= value['timeout_seconds'] <= ATLASCLOUD_TIMEOUT,
                'Invalid AtlasCloud timeout')
        return cls(value['binding_id'], value['revision'], value['endpoint'],
                   value['model'], value['target_id'], value['credential_ref'],
                   value['credential_revision'], value['offer_id'], value['protocol'],
                   value['knowledge_revision'], frozenset(capabilities),
                   value['max_output_tokens'], value['timeout_seconds'])

    def target(self):
        return Target(self.binding_id, self.revision, self.boundary,
                      self.target_id, self.model)

    def capabilities(self):
        formats = {'text'}
        if 'json-output' in self.capability_names:
            formats.add('json')
        digest = hashlib.sha256((self.knowledge_revision + '\0' + self.offer_id + '\0'
            + '\0'.join(sorted(self.capability_names))).encode()).hexdigest()[:24]
        return BackendCapabilities(1, 'atlascloud-reviewed-' + digest,
                                   frozenset({'generate-text'}),
                                   frozenset(formats)).validate()

    def serialize(self):
        return {'schema_version': 1, 'binding_id': self.binding_id,
                'revision': self.revision, 'adapter': self.adapter_id,
                'boundary': self.boundary, 'endpoint': self.endpoint,
                'model': self.model, 'target_id': self.target_id,
                'credential_ref': self.credential_ref,
                'credential_revision': self.credential_revision,
                'offer_id': self.offer_id, 'protocol': self.protocol,
                'knowledge_revision': self.knowledge_revision,
                'capabilities': sorted(self.capability_names),
                'max_output_tokens': self.max_output_tokens,
                'timeout_seconds': self.timeout_seconds}


class AtlasCloudBindings:
    def __init__(self, state_dir):
        self.root = _safe_root(state_dir)
        self.path = self.root / 'atlascloud-binding.json'

    def save(self, binding):
        require(isinstance(binding, AtlasCloudBinding),
                'Validated AtlasCloud binding is required')
        raw = (json.dumps(binding.serialize(), sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        _atomic_write(self.root, self.path, raw, '.atlascloud-binding-')

    def load(self):
        return AtlasCloudBinding.parse(_read_json(self.path, 'AtlasCloud binding'))


class AtlasCloudCredentials:
    def __init__(self, state_dir):
        self.root = _safe_root(state_dir)
        self.path = self.root / 'atlascloud-credentials.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe AtlasCloud credential store')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS credentials ('
                   'reference TEXT PRIMARY KEY, secret TEXT NOT NULL, revision INTEGER NOT NULL)')
        db.commit()
        return closing(db)

    def put(self, reference, secret):
        require(isinstance(reference, str) and bool(_REFERENCE.fullmatch(reference)),
                'Invalid AtlasCloud credential reference')
        require(isinstance(secret, str) and secret.strip() == secret
                and 20 <= len(secret) <= 4096 and not any(c in secret for c in '\0\r\n'),
                'Invalid AtlasCloud credential')
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
                'Invalid AtlasCloud credential reference')
        with self.connect() as db:
            row = db.execute('SELECT revision FROM credentials WHERE reference=?',
                             (reference,)).fetchone()
        return {'reference': reference, 'available': row is not None,
                'revision': None if row is None else row[0]}

    def resolve(self, reference):
        require(isinstance(reference, str) and bool(_REFERENCE.fullmatch(reference)),
                'Invalid AtlasCloud credential reference')
        with self.connect() as db:
            row = db.execute('SELECT secret,revision FROM credentials WHERE reference=?',
                             (reference,)).fetchone()
        require(row is not None, 'AtlasCloud credential is unavailable')
        return row[0], row[1]

    def delete(self, reference):
        require(isinstance(reference, str) and bool(_REFERENCE.fullmatch(reference)),
                'Invalid AtlasCloud credential reference')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('DELETE FROM credentials WHERE reference=?',
                                 (reference,)).rowcount
            db.commit()
        return {'reference': reference, 'available': False, 'deleted': bool(changed)}


class AtlasCloudCatalog:
    """Reviewed-only projection until AtlasCloud documents a discovery API."""
    def __init__(self, state_dir):
        self.root = _safe_root(state_dir)

    def load(self):
        knowledge = ModelKnowledgeStore(self.root).load_or_empty(
            '1970-01-01T00:00:00+00:00')
        projected = project_catalog(knowledge, [])
        projected['offers'] = [item for item in projected['offers']
                               if item['provider_id'] == 'atlascloud']
        projected.update(provider_id='atlascloud', discovery='unavailable',
                         freshness='reviewed', refresh_error=None)
        return projected

    def validate_binding_offer(self, candidate):
        require(isinstance(candidate, dict), 'AtlasCloud binding candidate is required')
        catalog = self.load()
        require(candidate.get('knowledge_revision') == catalog['knowledge_revision'],
                'AtlasCloud model knowledge changed before binding save')
        offers = [item for item in catalog['offers']
                  if item['offer_id'] == candidate.get('offer_id')]
        require(len(offers) == 1, 'AtlasCloud offer is not reviewed')
        offer = offers[0]
        require(offer['provider_model_id'] == candidate.get('model')
                and offer['protocol'] == candidate.get('protocol'),
                'AtlasCloud offer differs from binding')
        supported = sorted(item['name'] for item in offer['capabilities']
                           if item['supported'] and item['state'] in {'reviewed', 'reported'})
        require({'generate-text', 'text-output'} <= set(supported),
                'AtlasCloud offer lacks required text capabilities')
        requested = candidate.get('capabilities')
        require(isinstance(requested, list) and set(requested) <= set(supported),
                'AtlasCloud binding requests an unsupported capability')
        return offer


class AtlasCloudRuns(BackendRuns):
    def __init__(self, state_dir):
        super().__init__(state_dir, 'atlascloud-runs.sqlite')


class AtlasCloudAdapter:
    def __init__(self, runs, credentials, transport=None, stream_transport=None):
        require(isinstance(runs, AtlasCloudRuns), 'AtlasCloud run store is required')
        require(isinstance(credentials, AtlasCloudCredentials),
                'AtlasCloud credential store is required')
        self.runs = runs; self.credentials = credentials
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
            operation = role.operation; role_id = role.role_id; role_revision = role.revision
        capabilities.require(operation, output_format)
        return BackendExecution(binding.adapter_id, binding.binding_id, binding.revision,
            capabilities.revision, operation, output_format, role_id, role_revision)

    @staticmethod
    def _request(handoff, binding, role=None, output_format='text', stream=False):
        require(isinstance(handoff, DispatchHandoff)
                and isinstance(binding, AtlasCloudBinding),
                'Authorized handoff and AtlasCloud binding are required')
        require(handoff.target == binding.target(),
                'AtlasCloud binding differs from authorized target')
        require(type(stream) is bool, 'Invalid AtlasCloud streaming choice')
        require(not stream or 'streaming' in binding.capability_names,
                'AtlasCloud offer does not support streaming')
        body = {'model': binding.model, 'input': OllamaAdapter._prompt(handoff.payload),
                'store': False, 'stream': stream, 'truncation': 'disabled',
                'max_output_tokens': binding.max_output_tokens}
        if output_format == 'json':
            require('json-output' in binding.capability_names,
                    'AtlasCloud offer does not support JSON output')
            body['text'] = {'format': {'type': 'json_object'}}
        request = json.dumps(body, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()
        execution = AtlasCloudAdapter._execution(binding, role, output_format)
        digest = hashlib.sha256(handoff.manifest_sha256.encode() + b'\0' + request
            + b'\0' + execution.canonical() + b'\0' + binding.credential_ref.encode()
            + b'\0' + str(binding.credential_revision).encode()).hexdigest()
        return request, digest, execution

    def prepare(self, handoff, binding, role=None, output_format='text', stream=False):
        _, revision = self.credentials.resolve(binding.credential_ref)
        require(revision == binding.credential_revision,
                'AtlasCloud credential revision differs from binding')
        _, digest, execution = self._request(handoff, binding, role, output_format, stream)
        return self.runs.prepare(handoff.run_id, digest, digest, execution,
                                 handoff.manifest_sha256)

    def dispatch(self, handoff, binding, role=None, output_format='text'):
        return self._dispatch(handoff, binding, role, output_format, False, None)

    def dispatch_stream(self, handoff, binding, on_delta, role=None, output_format='text'):
        require(callable(on_delta), 'AtlasCloud stream delta callback is required')
        return self._dispatch(handoff, binding, role, output_format, True, on_delta)

    def _dispatch(self, handoff, binding, role, output_format, stream, on_delta):
        request, digest, execution = self._request(handoff, binding, role, output_format, stream)
        row = self.runs.prepare(handoff.run_id, digest, digest, execution,
                                handoff.manifest_sha256)
        if row['state'] == 'succeeded':
            return row['response']
        if row['state'] in {'dispatching', 'unknown'}:
            raise AtlasCloudUnknownRun(
                'AtlasCloud result is unknown; automatic retry is forbidden')
        if row['state'] != 'prepared':
            raise AtlasCloudResponseError(row['error'] or
                'AtlasCloud run failed; explicit new run required')
        secret, revision = self.credentials.resolve(binding.credential_ref)
        require(revision == binding.credential_revision,
                'AtlasCloud credential revision differs from binding')
        require(handoff.target == binding.target(),
                'AtlasCloud binding changed before dispatch')
        current_secret, current_revision = self.credentials.resolve(binding.credential_ref)
        require((current_secret, current_revision) == (secret, revision),
                'AtlasCloud credential changed before dispatch')
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE runs SET state='dispatching' "
                                 "WHERE run_id=? AND state='prepared'", (handoff.run_id,))
            require(changed.rowcount == 1,
                    'AtlasCloud run state changed before dispatch')
            db.commit()
        try:
            value = (self.stream_transport(binding, request, secret, on_delta)
                     if stream else self.transport(binding, request, secret))
            response = self._response(value, binding)
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            self._finish(handoff.run_id, 'unknown', None, 'AtlasCloud response was lost')
            raise AtlasCloudUnknownRun(
                'AtlasCloud request outcome is unknown; do not retry automatically') from exc
        except ValueError as exc:
            self._finish(handoff.run_id, 'failed', None, str(exc))
            raise AtlasCloudResponseError(str(exc)) from exc
        except Exception as exc:
            self._finish(handoff.run_id, 'failed', None, str(exc))
            raise
        self._finish(handoff.run_id, 'succeeded', response, None)
        return response

    def _finish(self, run_id, state, response, error):
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE runs SET state=?,response=?,error=? '
                "WHERE run_id=? AND state='dispatching'", (state,
                json.dumps(response, sort_keys=True, separators=(',', ':'))
                    if response else None, error, run_id))
            require(changed.rowcount == 1,
                    'AtlasCloud run state changed while completing')
            db.commit()

    @staticmethod
    def _response(value, binding):
        require(isinstance(value, dict) and set(value) >= {'id', 'status', 'model', 'output'},
                'Invalid AtlasCloud response')
        require(value['status'] == 'completed' and value['model'] == binding.model,
                'AtlasCloud response did not complete with the requested model')
        output = value['output']
        require(isinstance(output, list) and bool(output)
                and all(isinstance(item, dict)
                        and item.get('type') in {'reasoning', 'message'} for item in output),
                'AtlasCloud response contains an unsupported output item')
        messages = [item for item in output if item.get('type') == 'message']
        require(len(messages) == 1 and isinstance(messages[0].get('content'), list),
                'AtlasCloud response must contain exactly one output message')
        content = messages[0]['content']
        require(bool(content) and all(isinstance(item, dict)
                and item.get('type') == 'output_text'
                and isinstance(item.get('text'), str) for item in content),
                'AtlasCloud response contains unsupported message content')
        result = {'id': value['id'], 'model': value['model'],
                  'response': ''.join(item['text'] for item in content)}
        usage = value.get('usage')
        if isinstance(usage, dict):
            keys = {'input_tokens', 'output_tokens', 'total_tokens'}
            if set(usage) >= keys and all(type(usage[key]) is int and usage[key] >= 0
                                          for key in keys):
                result['usage'] = {key: usage[key] for key in sorted(keys)}
        return result

    @staticmethod
    def _http_transport(binding, request, secret):
        connection = http.client.HTTPSConnection('api.atlascloud.ai', 443,
            timeout=binding.timeout_seconds, context=ssl.create_default_context())
        try:
            connection.request('POST', '/v1/responses', body=request,
                headers={'Authorization': 'Bearer ' + secret,
                         'Content-Type': 'application/json'})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise AtlasCloudResponseError('AtlasCloud redirect is forbidden')
            if not 200 <= response.status < 300:
                raise AtlasCloudResponseError('AtlasCloud request was rejected with HTTP '
                                              + str(response.status))
            raw = response.read(MAX_RESPONSE + 1)
            require(len(raw) <= MAX_RESPONSE, 'AtlasCloud response exceeds 16 MiB')
            return json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise AtlasCloudResponseError('Invalid AtlasCloud response JSON') from exc
        finally:
            connection.close()

    @staticmethod
    def _http_stream_transport(binding, request, secret, on_delta):
        connection = http.client.HTTPSConnection('api.atlascloud.ai', 443,
            timeout=binding.timeout_seconds, context=ssl.create_default_context())
        try:
            connection.request('POST', '/v1/responses', body=request,
                headers={'Authorization': 'Bearer ' + secret,
                         'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
            response = connection.getresponse()
            if 300 <= response.status < 400:
                raise AtlasCloudResponseError('AtlasCloud redirect is forbidden')
            if not 200 <= response.status < 300:
                raise AtlasCloudResponseError('AtlasCloud request was rejected with HTTP '
                                              + str(response.status))
            total = 0; data = []; deltas = []; completed = None; sequence = -1
            while True:
                raw = response.readline(MAX_RESPONSE + 1)
                if not raw:
                    break
                total += len(raw)
                require(total <= MAX_RESPONSE and raw.endswith(b'\n'),
                        'Invalid AtlasCloud SSE stream')
                line = raw.rstrip(b'\r\n')
                if line.startswith(b'data:'):
                    data.append(line[5:].lstrip())
                elif line.startswith(b':'):
                    continue
                elif not line:
                    if not data:
                        continue
                    event = json.loads(b'\n'.join(data)); data = []
                    require(isinstance(event, dict) and isinstance(event.get('type'), str),
                            'Invalid AtlasCloud SSE event')
                    current = event.get('sequence_number')
                    if current is not None:
                        require(type(current) is int and current > sequence,
                                'Invalid AtlasCloud SSE sequence')
                        sequence = current
                    if event['type'] == 'response.output_text.delta':
                        delta = event.get('delta')
                        require(isinstance(delta, str), 'Invalid AtlasCloud text delta')
                        deltas.append(delta); on_delta(delta)
                    elif event['type'] == 'response.completed':
                        require(completed is None and isinstance(event.get('response'), dict),
                                'Invalid AtlasCloud completed event')
                        completed = event['response']
                    elif event['type'] in {'response.failed', 'error'}:
                        raise AtlasCloudResponseError('AtlasCloud stream reported failure')
            if data or completed is None:
                raise ConnectionError('AtlasCloud stream ended before completion')
            normalized = AtlasCloudAdapter._response(completed, binding)
            require(''.join(deltas) == normalized['response'],
                    'AtlasCloud stream deltas differ from final response')
            return completed
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AtlasCloudResponseError('Invalid AtlasCloud SSE JSON') from exc
        finally:
            connection.close()


def _safe_root(state_dir):
    root = Path(state_dir).absolute(); info = root.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            'AtlasCloud state directory requires owned mode 0700')
    return root


def _atomic_write(root, path, raw, prefix):
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


BACKENDS.register(AtlasCloudBinding.adapter_id, AtlasCloudBinding.parse)
