# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed framework for text providers reached directly over one official host.

A provider supplies only a ``ProviderSpec``: its wire format.  Bindings, credentials,
the run journal, discovery and dispatch stay here, so every provider gets the same
recovery.  See ADR 0065.
"""
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
from typing import Callable

from spikes.backend_contract import (BackendCapabilities, BackendExecution,
                                     BackendResponseError, BackendUnknown,
                                     pin_execution, ROLES)
from spikes.context_builder import DispatchHandoff, Target
from spikes.metadata import require, uuid
from spikes.model_catalog import (collect_discovery_pages, ModelDiscoveryStore,
                                  ModelKnowledgeStore, project_catalog)
from spikes.ollama_backend import BACKENDS, BackendRuns, OllamaAdapter


MAX_TIMEOUT = 900
MAX_RESPONSE = 16 * 1024 * 1024
MAX_MODEL_RESPONSE = 2 * 1024 * 1024
DISCOVERY_TIMEOUT = 30
_MODEL_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._/:-]{0,255}')
_OFFER_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}')
_REFERENCE_TAIL = r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}'
_CAPABILITIES = frozenset({'generate-text', 'text-output', 'json-output', 'streaming'})
_ADAPTER_ID = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')


class DirectUnknownRun(BackendUnknown):
    pass


class DirectResponseError(BackendResponseError):
    pass


@dataclass(frozen=True)
class ProviderSpec:
    """Wire format of one provider; every callable is pure except for ``state``.

    ``parse_response`` raises ``ValueError`` on anything but one complete text answer
    from the requested model and returns ``{'id', 'model', 'response'}`` plus an
    optional ``usage`` with ``input_tokens``, ``output_tokens`` and ``total_tokens``.
    ``stream_event`` returns the text delta or ``None`` and raises
    ``DirectResponseError`` when the provider reports failure.  ``stream_final``
    returns a value for ``parse_response`` and raises ``ConnectionError`` when the
    stream never completed, which makes the run ``unknown``.  ``parse_models`` returns
    ``{'items': [{'model', 'capabilities'}], 'next_cursor'}`` with text models only.
    """
    adapter_id: str
    provider_id: str
    name: str
    host: str
    endpoint: str
    protocol: str
    auth_headers: Callable
    generate_path: Callable
    build_body: Callable
    parse_response: Callable
    stream_state: Callable
    stream_event: Callable
    stream_final: Callable
    models_path: Callable
    parse_models: Callable

    def __post_init__(self):
        require(bool(_ADAPTER_ID.fullmatch(self.adapter_id)), 'Invalid provider adapter ID')
        require(self.endpoint.startswith('https://' + self.host + '/'),
                'Provider endpoint must use its official HTTPS host')


def _safe_root(state_dir):
    root = Path(state_dir).absolute(); info = root.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            'Provider state directory requires owned mode 0700')
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


def _valid_secret(secret, spec):
    require(isinstance(secret, str) and secret.strip() == secret
            and 20 <= len(secret) <= 4096 and not any(c in secret for c in '\0\r\n'),
            'Invalid ' + spec.name + ' credential')
    return secret


@dataclass(frozen=True)
class DirectBinding:
    """Subclasses set ``spec``; the type then identifies the provider."""
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

    boundary = 'external-provider'
    spec = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        require(isinstance(cls.spec, ProviderSpec), 'Provider binding requires a spec')
        cls.adapter_id = cls.spec.adapter_id

    @classmethod
    def parse(cls, value):
        spec = cls.spec; name = spec.name
        required = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                    'endpoint', 'model', 'target_id', 'credential_ref',
                    'credential_revision', 'offer_id', 'protocol',
                    'knowledge_revision', 'capabilities', 'max_output_tokens',
                    'timeout_seconds'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing ' + name + ' binding field')
        require(value['schema_version'] == 1 and value['adapter'] == spec.adapter_id
                and value['boundary'] == cls.boundary, 'Unsupported ' + name + ' binding')
        uuid(value['binding_id'])
        require(value['protocol'] == spec.protocol, 'Unsupported ' + name + ' protocol')
        require(value['endpoint'] == spec.endpoint and value['target_id'] == spec.host,
                name + ' binding requires the official endpoint')
        for key in ('revision', 'knowledge_revision'):
            require(isinstance(value[key], str) and value[key].strip() == value[key]
                    and bool(value[key]) and not any(c in value[key] for c in '\0\r\n'),
                    'Invalid ' + name + ' ' + key.replace('_', ' '))
        require(isinstance(value['model'], str) and bool(_MODEL_ID.fullmatch(value['model'])),
                name + ' binding requires a valid model ID')
        require(isinstance(value['offer_id'], str)
                and bool(_OFFER_ID.fullmatch(value['offer_id'])),
                name + ' binding requires a valid offer ID')
        require(isinstance(value['credential_ref'], str) and bool(
                _reference_pattern(spec).fullmatch(value['credential_ref'])),
                name + ' binding requires an opaque credential reference')
        require(type(value['credential_revision']) is int
                and value['credential_revision'] >= 1,
                'Invalid ' + name + ' credential revision')
        capabilities = value['capabilities']
        require(isinstance(capabilities, list) and capabilities == sorted(set(capabilities))
                and set(capabilities) <= _CAPABILITIES
                and {'generate-text', 'text-output'} <= set(capabilities),
                'Invalid ' + name + ' capability snapshot')
        require(type(value['max_output_tokens']) is int
                and 1 <= value['max_output_tokens'] <= 128000,
                'Invalid ' + name + ' output token limit')
        require(type(value['timeout_seconds']) is int
                and 1 <= value['timeout_seconds'] <= MAX_TIMEOUT,
                'Invalid ' + name + ' timeout')
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
        return BackendCapabilities(1, self.adapter_id + '-profile-' + digest,
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


def _reference_pattern(spec):
    return re.compile('credential:' + re.escape(spec.adapter_id) + '-' + _REFERENCE_TAIL)


class DirectBindings:
    def __init__(self, state_dir, binding_type):
        require(isinstance(binding_type, type) and issubclass(binding_type, DirectBinding),
                'Provider binding type is required')
        self.root = _safe_root(state_dir); self.binding_type = binding_type
        self.path = self.root / (binding_type.adapter_id + '-binding.json')

    def save(self, binding):
        require(type(binding) is self.binding_type, 'Validated provider binding is required')
        raw = (json.dumps(binding.serialize(), sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        _atomic_write(self.root, self.path, raw, '.' + binding.adapter_id + '-binding-')

    def load(self):
        return self.binding_type.parse(_read_json(self.path, self.binding_type.spec.name
                                                  + ' binding'))


class DirectCredentials:
    """Write-only node-local secrets addressed by opaque references."""
    def __init__(self, state_dir, spec):
        self.root = _safe_root(state_dir); self.spec = spec
        self.path = self.root / (spec.adapter_id + '-credentials.sqlite')
        self._pattern = _reference_pattern(spec)

    def new_reference(self, value):
        return 'credential:' + self.spec.adapter_id + '-' + value

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe ' + self.spec.name + ' credential store')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS credentials ('
                   'reference TEXT PRIMARY KEY, secret TEXT NOT NULL, revision INTEGER NOT NULL)')
        db.commit()
        return closing(db)

    def _reference(self, reference):
        require(isinstance(reference, str) and bool(self._pattern.fullmatch(reference)),
                'Invalid ' + self.spec.name + ' credential reference')
        return reference

    def put(self, reference, secret):
        self._reference(reference); _valid_secret(secret, self.spec)
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
        self._reference(reference)
        with self.connect() as db:
            row = db.execute('SELECT revision FROM credentials WHERE reference=?',
                             (reference,)).fetchone()
        return {'reference': reference, 'available': row is not None,
                'revision': None if row is None else row[0]}

    def resolve(self, reference):
        self._reference(reference)
        with self.connect() as db:
            row = db.execute('SELECT secret,revision FROM credentials WHERE reference=?',
                             (reference,)).fetchone()
        require(row is not None, self.spec.name + ' credential is unavailable')
        return row[0], row[1]

    def delete(self, reference):
        self._reference(reference)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('DELETE FROM credentials WHERE reference=?',
                                 (reference,)).rowcount
            db.commit()
        return {'reference': reference, 'available': False, 'deleted': bool(changed)}


class DirectRuns(BackendRuns):
    def __init__(self, state_dir, spec):
        super().__init__(state_dir, spec.adapter_id + '-runs.sqlite')


class DirectCatalog:
    """Live discovery projected through the provider-neutral catalog."""
    binding_revision = 'direct-catalog-v1'

    def __init__(self, state_dir, spec, transport=None):
        self.root = _safe_root(state_dir); self.spec = spec
        self.scope_id = spec.adapter_id + '-v1'
        self.transport = transport or _http_catalog_transport

    def _store(self):
        return ModelDiscoveryStore(self.root, self.spec.provider_id, self.scope_id)

    def refresh(self, secret):
        spec = self.spec; _valid_secret(secret, spec)
        observed = datetime.now(timezone.utc).isoformat()
        fetch = lambda cursor: spec.parse_models(self.transport(spec, secret, cursor))
        items = collect_discovery_pages(fetch(None), fetch)
        offers = []; seen = set()
        for item in items:
            model = item.get('model') if isinstance(item, dict) else None
            names = item.get('capabilities') if isinstance(item, dict) else None
            require(isinstance(model, str) and bool(_MODEL_ID.fullmatch(model))
                    and model not in seen and isinstance(names, (set, frozenset))
                    and {'generate-text', 'text-output'} <= set(names)
                    and set(names) <= _CAPABILITIES,
                    'Invalid ' + spec.name + ' model entry')
            seen.add(model)
            revision = spec.adapter_id + '-catalog-' + hashlib.sha256(
                (model + '\0' + spec.protocol + '\0'
                 + '\0'.join(sorted(names))).encode()).hexdigest()[:24]
            capabilities = [{'name': name, 'value': True, 'state': 'reported',
                'source': spec.adapter_id + ':models-api', 'revision': revision,
                'observed_at': observed} for name in sorted(names)]
            offers.append({'offer_id': spec.provider_id + ':' + hashlib.sha256(
                (model + '\0' + spec.protocol).encode()).hexdigest()[:32],
                'provider_id': spec.provider_id, 'provider_model_id': model,
                'protocol': spec.protocol, 'availability': 'available',
                'capabilities': capabilities})
        snapshot = self._store().publish({'schema_version': 1,
            'provider_id': spec.provider_id, 'scope_id': self.scope_id,
            'binding_revision': self.binding_revision, 'credential_revision': None,
            'fetched_at': observed, 'offers': offers})
        return self._project(dict(snapshot, freshness='fresh', refresh_error=None))

    def load(self):
        try:
            discovery = self._store().load(self.binding_revision, None)
        except FileNotFoundError:
            knowledge = ModelKnowledgeStore(self.root).load_or_empty(
                '1970-01-01T00:00:00+00:00')
            projected = project_catalog(knowledge, [])
            projected['offers'] = [item for item in projected['offers']
                                   if item['provider_id'] == self.spec.provider_id]
            projected.update(provider_id=self.spec.provider_id, discovery='not-loaded',
                             freshness='missing', refresh_error=None, fetched_at=None)
            return projected
        return self._project(discovery)

    def _project(self, discovery):
        knowledge = ModelKnowledgeStore(self.root).load_or_empty(discovery['fetched_at'])
        projected = project_catalog(knowledge, [discovery])
        projected['offers'] = [item for item in projected['offers']
                               if item['provider_id'] == self.spec.provider_id]
        projected.update(provider_id=self.spec.provider_id, discovery='live',
                         freshness=discovery['freshness'],
                         refresh_error=discovery['refresh_error'],
                         fetched_at=discovery['fetched_at'])
        return projected

    def validate_binding_offer(self, candidate):
        name = self.spec.name
        require(isinstance(candidate, dict), name + ' binding candidate is required')
        catalog = self.load()
        require(candidate.get('knowledge_revision') == catalog['knowledge_revision'],
                name + ' model knowledge changed before binding save')
        offers = [item for item in catalog['offers']
                  if item['offer_id'] == candidate.get('offer_id')]
        require(len(offers) == 1, name + ' offer is unavailable')
        offer = offers[0]
        require(offer['provider_model_id'] == candidate.get('model')
                and offer['protocol'] == candidate.get('protocol'),
                name + ' offer differs from binding')
        require(offer['availability'] == 'available' and offer['freshness'] == 'fresh',
                name + ' offer is not freshly discovered')
        supported = sorted(item['name'] for item in offer['capabilities']
                           if item['supported'] and item['state'] in {'reviewed', 'reported'})
        require({'generate-text', 'text-output'} <= set(supported),
                name + ' offer lacks required text capabilities')
        requested = candidate.get('capabilities')
        require(isinstance(requested, list) and set(requested) <= set(supported),
                name + ' binding requests an unsupported capability')
        return offer


class DirectAdapter:
    """One durable provider effect per run; a lost response is never retried."""
    def __init__(self, runs, credentials, transport=None, stream_transport=None):
        require(isinstance(runs, DirectRuns), 'Provider run store is required')
        require(isinstance(credentials, DirectCredentials),
                'Provider credential store is required')
        self.runs = runs; self.credentials = credentials
        self.transport = transport or _http_transport
        self.stream_transport = stream_transport or _http_stream_transport

    @staticmethod
    def _execution(binding, role=None, output_format='text', run_selection=None):
        capabilities = binding.capabilities()
        if role is None:
            operation = 'generate-text'; role_id = role_revision = ''
        else:
            role = ROLES.resolve(role.role_id, role.revision)
            require(role.output_format == output_format,
                    'Role output format differs from backend request')
            operation = role.operation; role_id = role.role_id; role_revision = role.revision
        capabilities.require(operation, output_format)
        execution = BackendExecution(binding.adapter_id, binding.binding_id, binding.revision,
            capabilities.revision, operation, output_format, role_id, role_revision)
        return pin_execution(execution, run_selection, binding.model)

    @staticmethod
    def _request(handoff, binding, role=None, output_format='text', stream=False,
                 run_selection=None):
        require(isinstance(handoff, DispatchHandoff) and isinstance(binding, DirectBinding),
                'Authorized handoff and provider binding are required')
        name = binding.spec.name
        require(handoff.target == binding.target(),
                name + ' binding differs from authorized target')
        require(type(stream) is bool, 'Invalid ' + name + ' streaming choice')
        require(not stream or 'streaming' in binding.capability_names,
                name + ' offer does not support streaming')
        require(output_format != 'json' or 'json-output' in binding.capability_names,
                name + ' offer does not support JSON output')
        prompt = OllamaAdapter._prompt(handoff.payload)
        body = binding.spec.build_body(prompt, binding, output_format, stream)
        request = json.dumps(body, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':')).encode()
        execution = DirectAdapter._execution(binding, role, output_format, run_selection)
        digest = hashlib.sha256(handoff.manifest_sha256.encode() + b'\0' + request
            + b'\0' + binding.spec.generate_path(binding.model, stream).encode()
            + b'\0' + execution.canonical() + b'\0' + binding.credential_ref.encode()
            + b'\0' + str(binding.credential_revision).encode()).hexdigest()
        return request, digest, execution

    def prepare(self, handoff, binding, role=None, output_format='text', stream=False,
                run_selection=None):
        _, revision = self.credentials.resolve(binding.credential_ref)
        require(revision == binding.credential_revision,
                binding.spec.name + ' credential revision differs from binding')
        _, digest, execution = self._request(handoff, binding, role, output_format, stream,
                                             run_selection)
        return self.runs.prepare(handoff.run_id, digest, digest, execution,
                                 handoff.manifest_sha256, run_selection)

    def dispatch(self, handoff, binding, role=None, output_format='text', *,
                 run_selection=None):
        return self._dispatch(handoff, binding, role, output_format, False, None,
                              run_selection)

    def dispatch_stream(self, handoff, binding, on_delta, role=None, output_format='text', *,
                        run_selection=None):
        require(callable(on_delta), 'Provider stream delta callback is required')
        return self._dispatch(handoff, binding, role, output_format, True, on_delta,
                              run_selection)

    def _dispatch(self, handoff, binding, role, output_format, stream, on_delta,
                  run_selection=None):
        name = binding.spec.name
        request, digest, execution = self._request(handoff, binding, role, output_format,
                                                   stream, run_selection)
        row = self.runs.prepare(handoff.run_id, digest, digest, execution,
                                handoff.manifest_sha256, run_selection)
        if row['state'] == 'succeeded':
            return row['response']
        if row['state'] in {'dispatching', 'unknown'}:
            raise DirectUnknownRun(name + ' result is unknown; automatic retry is forbidden')
        if row['state'] != 'prepared':
            raise DirectResponseError(row['error'] or
                                      name + ' run failed; explicit new run required')
        secret, revision = self.credentials.resolve(binding.credential_ref)
        require(revision == binding.credential_revision,
                name + ' credential revision differs from binding')
        require(handoff.target == binding.target(), name + ' binding changed before dispatch')
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute("UPDATE runs SET state='dispatching' "
                                 "WHERE run_id=? AND state='prepared'", (handoff.run_id,))
            require(changed.rowcount == 1, name + ' run state changed before dispatch')
            db.commit()
        try:
            value = (self.stream_transport(binding, request, secret, on_delta)
                     if stream else self.transport(binding, request, secret))
            response = binding.spec.parse_response(value, binding)
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            self._finish(handoff.run_id, 'unknown', None, name + ' response was lost', name)
            raise DirectUnknownRun(
                name + ' request outcome is unknown; do not retry automatically') from exc
        except ValueError as exc:
            self._finish(handoff.run_id, 'failed', None, str(exc), name)
            raise DirectResponseError(str(exc)) from exc
        except Exception as exc:
            self._finish(handoff.run_id, 'failed', None, str(exc), name)
            raise
        self._finish(handoff.run_id, 'succeeded', response, None, name)
        return response

    def _finish(self, run_id, state, response, error, name):
        with self.runs.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            changed = db.execute('UPDATE runs SET state=?,response=?,error=? '
                "WHERE run_id=? AND state='dispatching'", (state,
                json.dumps(response, sort_keys=True, separators=(',', ':'))
                    if response else None, error, run_id))
            require(changed.rowcount == 1, name + ' run state changed while completing')
            db.commit()


def _connection(spec, timeout):
    return http.client.HTTPSConnection(spec.host, 443, timeout=timeout,
                                       context=ssl.create_default_context())


def _check_status(response, spec):
    # The error body is not read: it could echo request content into stored errors.
    if 300 <= response.status < 400:
        raise DirectResponseError(spec.name + ' redirect is forbidden')
    if not 200 <= response.status < 300:
        raise DirectResponseError(spec.name + ' request was rejected with HTTP '
                                  + str(response.status))


def _http_catalog_transport(spec, secret, cursor):
    connection = _connection(spec, DISCOVERY_TIMEOUT)
    try:
        connection.request('GET', spec.models_path(cursor),
                           headers={**spec.auth_headers(secret), 'Accept': 'application/json'})
        response = connection.getresponse()
        _check_status(response, spec)
        raw = response.read(MAX_MODEL_RESPONSE + 1)
        require(len(raw) <= MAX_MODEL_RESPONSE, spec.name + ' model catalog exceeds 2 MiB')
        return json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise DirectResponseError('Invalid ' + spec.name + ' model catalog') from exc
    finally:
        connection.close()


def _http_transport(binding, request, secret):
    spec = binding.spec; connection = _connection(spec, binding.timeout_seconds)
    try:
        connection.request('POST', spec.generate_path(binding.model, False), body=request,
                           headers={**spec.auth_headers(secret),
                                    'Content-Type': 'application/json'})
        response = connection.getresponse()
        _check_status(response, spec)
        raw = response.read(MAX_RESPONSE + 1)
        require(len(raw) <= MAX_RESPONSE, spec.name + ' response exceeds 16 MiB')
        return json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise DirectResponseError('Invalid ' + spec.name + ' response JSON') from exc
    finally:
        connection.close()


def read_sse(lines, on_event, *, limit=MAX_RESPONSE):
    """Feed complete JSON events from an iterable of raw SSE lines; ``[DONE]`` is skipped."""
    total = 0; data = []
    for raw in lines:
        total += len(raw)
        require(total <= limit, 'Provider SSE stream exceeds its size limit')
        if not raw.endswith(b'\n'):
            raise ConnectionError('Provider stream ended inside a line')
        line = raw.rstrip(b'\r\n')
        if line.startswith(b'data:'):
            data.append(line[5:].lstrip())
        elif not line and data:
            payload = b'\n'.join(data); data = []
            if payload != b'[DONE]':
                on_event(json.loads(payload))
    if data:
        raise ConnectionError('Provider stream ended inside an event')


def _http_stream_transport(binding, request, secret, on_delta):
    spec = binding.spec; connection = _connection(spec, binding.timeout_seconds)
    try:
        connection.request('POST', spec.generate_path(binding.model, True), body=request,
                           headers={**spec.auth_headers(secret),
                                    'Content-Type': 'application/json',
                                    'Accept': 'text/event-stream'})
        response = connection.getresponse()
        _check_status(response, spec)
        return consume_stream(spec, binding, iter(
            lambda: response.readline(MAX_RESPONSE + 1), b''), on_delta)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DirectResponseError('Invalid ' + spec.name + ' SSE JSON') from exc
    finally:
        connection.close()


def consume_stream(spec, binding, lines, on_delta):
    """Reduce an SSE stream and require the deltas to equal the provider's final answer."""
    state = spec.stream_state(); deltas = []

    def on_event(event):
        require(isinstance(event, dict), 'Invalid ' + spec.name + ' SSE event')
        delta = spec.stream_event(state, event)
        if delta is not None:
            require(isinstance(delta, str), 'Invalid ' + spec.name + ' text delta')
            deltas.append(delta); on_delta(delta)

    read_sse(lines, on_event)
    value = spec.stream_final(state)
    normalized = spec.parse_response(value, binding)
    require(''.join(deltas) == normalized['response'],
            spec.name + ' stream deltas differ from final response')
    return value


def register_direct(binding_type):
    require(isinstance(binding_type, type) and issubclass(binding_type, DirectBinding),
            'Provider binding type is required')
    BACKENDS.register(binding_type.adapter_id, binding_type.parse)
    return binding_type
