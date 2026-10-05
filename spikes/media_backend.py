# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Fail-closed image generation adapters and node-local BLOB run journal."""
from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
import base64
import binascii
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
import struct
import time
from urllib.parse import urlencode, urlsplit
import zlib

from spikes.backend_contract import (BackendCapabilities, BackendExecution,
                                     BackendRegistry, BackendResponseError,
                                     BackendUnknown)
from spikes.metadata import require, uuid


OPENAI_IMAGES_ENDPOINT = 'https://api.openai.com/v1/images/generations'
MAX_PROMPT = 32 * 1024
MAX_IMAGE = 16 * 1024 * 1024
MAX_JSON = 24 * 1024 * 1024
MAX_WORKFLOW = 1024 * 1024
MAX_POLLS = 120
SIZES = {'1024x1024': (1024, 1024), '1536x1024': (1536, 1024),
         '1024x1536': (1024, 1536)}
QUALITIES = {'auto', 'low', 'medium', 'high'}
_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_REFERENCE = re.compile(r'credential:[A-Za-z0-9][A-Za-z0-9._-]{0,127}')
_SHA256 = re.compile(r'[0-9a-f]{64}')


class MediaUnknownRun(BackendUnknown):
    pass


class MediaResponseError(BackendResponseError):
    pass


def _text(value, label):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and not any(char in value for char in '\0\r\n'), f'Invalid {label}')
    return value


@dataclass(frozen=True)
class ImageGenerationRequest:
    run_id: str
    manifest_sha256: str
    prompt: str
    size: str
    quality: str
    seed: int | None

    @classmethod
    def parse(cls, value):
        required = {'run_id', 'manifest_sha256', 'prompt', 'size', 'quality', 'seed'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing image request field')
        uuid(value['run_id'])
        require(isinstance(value['manifest_sha256'], str)
                and bool(_SHA256.fullmatch(value['manifest_sha256'])),
                'Invalid Context Manifest digest')
        require(isinstance(value['prompt'], str) and bool(value['prompt'].strip())
                and len(value['prompt'].encode('utf-8')) <= MAX_PROMPT,
                'Image prompt must be non-empty and at most 32 KiB')
        require(value['size'] in SIZES, 'Unsupported image size')
        require(value['quality'] in QUALITIES, 'Unsupported image quality')
        require(value['seed'] is None or (type(value['seed']) is int
                and 0 <= value['seed'] < 2 ** 63),
                'Invalid image seed')
        return cls(**value)


@dataclass(frozen=True)
class OpenAIImageBinding:
    binding_id: str
    revision: str
    model: str
    credential_ref: str
    credential_revision: int
    timeout_seconds: int

    adapter_id = 'openai-images'
    boundary = 'external-provider'
    endpoint = OPENAI_IMAGES_ENDPOINT
    target_id = 'api.openai.com'

    @classmethod
    def parse(cls, value):
        required = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                    'endpoint', 'model', 'target_id', 'credential_ref',
                    'credential_revision', 'timeout_seconds'}
        require(isinstance(value, dict) and set(value) == required,
                'Unknown or missing OpenAI Images binding field')
        require(value['schema_version'] == 1 and value['adapter'] == cls.adapter_id
                and value['boundary'] == cls.boundary
                and value['endpoint'] == cls.endpoint and value['target_id'] == cls.target_id,
                'OpenAI Images binding requires the fixed official endpoint')
        uuid(value['binding_id']); _text(value['revision'], 'binding revision')
        require(isinstance(value['model'], str) and bool(_MODEL.fullmatch(value['model'])),
                'Invalid OpenAI image model')
        require(isinstance(value['credential_ref'], str)
                and bool(_REFERENCE.fullmatch(value['credential_ref'])),
                'Invalid OpenAI credential reference')
        require(type(value['credential_revision']) is int
                and value['credential_revision'] >= 1, 'Invalid credential revision')
        require(type(value['timeout_seconds']) is int
                and 1 <= value['timeout_seconds'] <= 180, 'Invalid OpenAI timeout')
        return cls(value['binding_id'], value['revision'], value['model'],
                   value['credential_ref'], value['credential_revision'],
                   value['timeout_seconds'])

    def capabilities(self):
        return BackendCapabilities(1, 'openai-images-v1',
                                   frozenset({'generate-image'}),
                                   frozenset({'image/png'})).validate()

    def serialize(self):
        return {'schema_version': 1, 'binding_id': self.binding_id,
                'revision': self.revision, 'adapter': self.adapter_id,
                'boundary': self.boundary, 'endpoint': self.endpoint,
                'model': self.model, 'target_id': self.target_id,
                'credential_ref': self.credential_ref,
                'credential_revision': self.credential_revision,
                'timeout_seconds': self.timeout_seconds}

    def target(self):
        from spikes.context_builder import Target
        return Target(self.binding_id, self.revision, self.boundary,
                      self.target_id, self.model)


@dataclass(frozen=True)
class ComfyImageBinding:
    binding_id: str
    revision: str
    boundary: str
    endpoint: str
    target_id: str
    workflow_revision: str
    workflow_sha256: str
    workflow: dict
    parameters: dict
    output_node_id: str
    timeout_seconds: int
    tls_cert_sha256: str | None = None

    adapter_id = 'comfyui'

    @classmethod
    def parse(cls, value):
        required = {'schema_version', 'binding_id', 'revision', 'adapter', 'boundary',
                    'endpoint', 'target_id', 'workflow_revision', 'workflow_sha256',
                    'workflow', 'parameters', 'output_node_id', 'timeout_seconds'}
        require(isinstance(value, dict) and set(value) in (required,
                required | {'tls_cert_sha256'}), 'Unknown or missing ComfyUI binding field')
        require(value['schema_version'] == 1 and value['adapter'] == cls.adapter_id,
                'Unsupported ComfyUI binding')
        uuid(value['binding_id'])
        for key in ('revision', 'workflow_revision', 'output_node_id'):
            _text(value[key], 'ComfyUI ' + key)
        require(value['boundary'] in {'same-node', 'private-network'},
                'Invalid ComfyUI boundary')
        parsed = urlsplit(value['endpoint'])
        require(not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in {'', '/'} and parsed.port is not None,
                'Invalid ComfyUI endpoint')
        try:
            address = ipaddress.ip_address(parsed.hostname or '')
        except ValueError as exc:
            raise ValueError('ComfyUI endpoint requires a numeric IP address') from exc
        pin = value.get('tls_cert_sha256')
        if value['boundary'] == 'same-node':
            require(parsed.scheme == 'http' and address.is_loopback and pin is None
                    and value['target_id'] == 'local-process',
                    'same-node ComfyUI requires numeric loopback HTTP')
        else:
            require(parsed.scheme == 'https' and address.is_private and not address.is_loopback
                    and isinstance(pin, str) and bool(_SHA256.fullmatch(pin)),
                    'private ComfyUI requires private HTTPS and certificate pin')
            uuid(value['target_id'])
        require(type(value['timeout_seconds']) is int
                and 1 <= value['timeout_seconds'] <= 180, 'Invalid ComfyUI timeout')
        require(isinstance(value['workflow'], dict) and bool(value['workflow']),
                'ComfyUI workflow must be an object')
        canonical = json.dumps(value['workflow'], sort_keys=True,
                               separators=(',', ':')).encode()
        require(len(canonical) <= MAX_WORKFLOW
                and hashlib.sha256(canonical).hexdigest() == value['workflow_sha256'],
                'ComfyUI workflow hash or size is invalid')
        require(isinstance(value['parameters'], dict)
                and set(value['parameters']) == {'prompt', 'width', 'height', 'seed'},
                'ComfyUI parameter map must contain only allowlisted parameters')
        for name, spec in value['parameters'].items():
            require(isinstance(spec, dict) and set(spec) == {'node_id', 'input'},
                    f'Invalid ComfyUI {name} parameter map')
            node = value['workflow'].get(spec['node_id'])
            require(isinstance(node, dict) and isinstance(node.get('class_type'), str)
                    and isinstance(node.get('inputs'), dict)
                    and spec['input'] in node['inputs'], f'Unknown ComfyUI {name} input')
        require(value['output_node_id'] in value['workflow'], 'Unknown ComfyUI output node')
        return cls(value['binding_id'], value['revision'], value['boundary'],
                   value['endpoint'].rstrip('/'), value['target_id'],
                   value['workflow_revision'], value['workflow_sha256'],
                   deepcopy(value['workflow']), deepcopy(value['parameters']),
                   value['output_node_id'], value['timeout_seconds'], pin)

    def capabilities(self):
        return BackendCapabilities(1, 'comfyui-image-v1',
                                   frozenset({'generate-image'}),
                                   frozenset({'image/png'})).validate()

    def serialize(self):
        value = {'schema_version': 1, 'binding_id': self.binding_id,
                 'revision': self.revision, 'adapter': self.adapter_id,
                 'boundary': self.boundary, 'endpoint': self.endpoint,
                 'target_id': self.target_id,
                 'workflow_revision': self.workflow_revision,
                 'workflow_sha256': self.workflow_sha256,
                 'workflow': deepcopy(self.workflow),
                 'parameters': deepcopy(self.parameters),
                 'output_node_id': self.output_node_id,
                 'timeout_seconds': self.timeout_seconds}
        if self.tls_cert_sha256:
            value['tls_cert_sha256'] = self.tls_cert_sha256
        return value

    def target(self):
        from spikes.context_builder import Target
        return Target(self.binding_id, self.revision, self.boundary,
                      self.target_id, self.workflow_revision)

    def render(self, request):
        workflow = deepcopy(self.workflow)
        width, height = SIZES[request.size]
        values = {'prompt': request.prompt, 'width': width,
                  'height': height, 'seed': request.seed}
        for name, spec in self.parameters.items():
            workflow[spec['node_id']]['inputs'][spec['input']] = values[name]
        return workflow


MEDIA_BACKENDS = BackendRegistry()
MEDIA_BACKENDS.register(OpenAIImageBinding.adapter_id, OpenAIImageBinding.parse)
MEDIA_BACKENDS.register(ComfyImageBinding.adapter_id, ComfyImageBinding.parse)


class ComfyBindings:
    """Atomic node-local ComfyUI configuration outside project Git."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute(); info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'ComfyUI binding directory requires owned mode 0700')
        self.path = self.root / 'comfyui-binding.json'

    def save(self, binding):
        require(isinstance(binding, ComfyImageBinding), 'Validated ComfyUI binding is required')
        raw = (json.dumps(binding.serialize(), sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        require(len(raw) <= MAX_WORKFLOW + 64 * 1024, 'ComfyUI binding is too large')
        temporary = self.root / ('.comfyui-binding-' + binding.binding_id + '.tmp')
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
                    'Unsafe ComfyUI binding file')
            raw = os.read(fd, MAX_WORKFLOW + 64 * 1024 + 1)
        finally: os.close(fd)
        require(len(raw) <= MAX_WORKFLOW + 64 * 1024, 'ComfyUI binding is too large')
        try: value = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise ValueError('Invalid ComfyUI binding JSON') from exc
        return ComfyImageBinding.parse(value)


def validate_png(raw, expected_size):
    require(isinstance(raw, bytes) and len(raw) <= MAX_IMAGE, 'PNG exceeds 16 MiB')
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise MediaResponseError('Invalid PNG signature')
    offset = 8; chunks = []; width = height = None; saw_idat = False
    while offset < len(raw):
        if len(raw) - offset < 12:
            raise MediaResponseError('Truncated PNG chunk')
        length = struct.unpack('>I', raw[offset:offset + 4])[0]
        if length > MAX_IMAGE or offset + 12 + length > len(raw):
            raise MediaResponseError('Invalid PNG chunk length')
        kind = raw[offset + 4:offset + 8]
        data = raw[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack('>I', raw[offset + 8 + length:offset + 12 + length])[0]
        if zlib.crc32(kind + data) & 0xffffffff != expected_crc:
            raise MediaResponseError('Invalid PNG chunk CRC')
        if not chunks and kind != b'IHDR':
            raise MediaResponseError('PNG IHDR must be first')
        if kind == b'IHDR':
            if chunks or length != 13:
                raise MediaResponseError('Invalid or duplicate PNG IHDR')
            width, height, depth, color, compression, filtering, interlace = struct.unpack(
                '>IIBBBBB', data)
            if (width, height) != expected_size or width * height > 1536 * 1536:
                raise MediaResponseError('PNG dimensions differ from request')
            valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
                            4: {8, 16}, 6: {8, 16}}
            if compression != 0 or filtering != 0 or interlace not in {0, 1} \
                    or depth not in valid_depths.get(color, set()):
                raise MediaResponseError('Unsupported PNG header')
        elif kind == b'IDAT':
            saw_idat = True
        elif kind == b'IEND':
            if length != 0 or not saw_idat or offset + 12 != len(raw):
                raise MediaResponseError('Invalid PNG end')
            chunks.append(kind); break
        chunks.append(kind); offset += 12 + length
    if not chunks or chunks[-1] != b'IEND':
        raise MediaResponseError('PNG has no valid IEND')
    return {'mime': 'image/png', 'width': width, 'height': height,
            'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


class MediaRuns:
    """Authoritative node-local image dispatch state and result bytes."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute(); info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Media run directory requires owned mode 0700')
        self.path = self.root / 'media-runs.sqlite'

    def connect(self):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd); os.close(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe media run journal')
        db = sqlite3.connect(self.path, timeout=30)
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS runs ('
                   'run_id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, state TEXT NOT NULL,'
                   'execution TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, request TEXT NOT NULL,'
                   'metadata TEXT, image BLOB, image_sha256 TEXT, error TEXT)')
        db.commit(); return closing(db)

    def get(self, run_id, include_image=False):
        uuid(run_id)
        with self.connect() as db:
            row = db.execute('SELECT request_digest,state,execution,manifest_sha256,request,'
                             'metadata,image,image_sha256,error FROM runs WHERE run_id=?',
                             (run_id,)).fetchone()
        if row is None: return None
        result = {'request_digest': row[0], 'state': row[1],
                  'execution': json.loads(row[2]), 'manifest_sha256': row[3],
                  'request': json.loads(row[4]),
                  'metadata': json.loads(row[5]) if row[5] else None,
                  'image_sha256': row[7], 'error': row[8]}
        if include_image: result['image'] = row[6]
        return result

    def prepare(self, request, provider_request, execution):
        execution.validate()
        provider_json = json.dumps(provider_request, sort_keys=True, separators=(',', ':'))
        execution_json = execution.canonical().decode()
        semantic_json = json.dumps({
            'prompt': request.prompt, 'size': request.size,
            'quality': request.quality, 'seed': request.seed},
            sort_keys=True, separators=(',', ':'))
        digest = hashlib.sha256((request.manifest_sha256 + '\0' + semantic_json + '\0'
                                 + provider_json + '\0' + execution_json).encode()).hexdigest()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT request_digest FROM runs WHERE run_id=?',
                             (request.run_id,)).fetchone()
            if row:
                require(row[0] == digest, 'Run ID belongs to a different image request')
            else:
                db.execute('INSERT INTO runs(run_id,request_digest,state,execution,'
                           'manifest_sha256,request) VALUES (?,?,?,?,?,?)',
                           (request.run_id, digest, 'prepared', execution_json,
                            request.manifest_sha256, provider_json))
            db.commit()
        return self.get(request.run_id, include_image=True)


class MediaAdapter:
    binding_type = object

    def __init__(self, runs, transport):
        require(isinstance(runs, MediaRuns), 'Media run store is required')
        self.runs = runs; self.transport = transport

    def _execution(self, binding):
        caps = binding.capabilities().require('generate-image', 'image/png')
        return BackendExecution(binding.adapter_id, binding.binding_id, binding.revision,
                                caps.revision, 'generate-image', 'image/png')

    def prepare(self, request, binding):
        require(isinstance(request, ImageGenerationRequest)
                and isinstance(binding, self.binding_type), 'Invalid media request or binding')
        return self.runs.prepare(request, self.provider_request(request, binding),
                                 self._execution(binding))

    def dispatch(self, request, binding):
        provider_request = self.provider_request(request, binding)
        row = self.runs.prepare(request, provider_request, self._execution(binding))
        if row['state'] == 'succeeded': return row
        if row['state'] in {'dispatching', 'unknown'}:
            raise MediaUnknownRun('Image result is unknown; automatic retry is forbidden')
        if row['state'] != 'prepared':
            raise MediaResponseError(row['error'] or 'Image run failed; use a new run ID')
        with self.runs.connect() as db, db:
            changed = db.execute("UPDATE runs SET state='dispatching' WHERE run_id=? AND state='prepared'",
                                 (request.run_id,))
            require(changed.rowcount == 1, 'Media run state changed before dispatch')
        try:
            raw, provider_metadata = self.transport(binding, provider_request)
            metadata = validate_png(raw, SIZES[request.size])
            require(isinstance(provider_metadata, dict), 'Invalid provider metadata')
            metadata['provider'] = provider_metadata
            encoded = json.dumps(metadata, sort_keys=True, separators=(',', ':'))
            with self.runs.connect() as db, db:
                changed = db.execute("UPDATE runs SET state='succeeded',metadata=?,image=?,"
                                     "image_sha256=? WHERE run_id=? AND state='dispatching'",
                                     (encoded, sqlite3.Binary(raw), metadata['sha256'], request.run_id))
                require(changed.rowcount == 1, 'Media completion state changed')
        except (MediaResponseError, ValueError) as exc:
            with self.runs.connect() as db, db:
                db.execute("UPDATE runs SET state='failed',error=? WHERE run_id=? AND state='dispatching'",
                           (str(exc), request.run_id))
            raise
        except Exception as exc:
            with self.runs.connect() as db, db:
                db.execute("UPDATE runs SET state='unknown',error=? WHERE run_id=? AND state='dispatching'",
                           (type(exc).__name__, request.run_id))
            raise MediaUnknownRun('Image dispatch outcome is unknown') from exc
        return self.runs.get(request.run_id, include_image=True)


class OpenAIImageAdapter(MediaAdapter):
    binding_type = OpenAIImageBinding

    def __init__(self, runs, credentials, transport=None):
        from spikes.openai_backend import OpenAICredentials
        require(isinstance(credentials, OpenAICredentials), 'OpenAI credential store is required')
        self.credentials = credentials
        super().__init__(runs, transport or self._http_transport)

    def _check_credential(self, binding):
        status = self.credentials.status(binding.credential_ref)
        require(status['available'] and status['revision'] == binding.credential_revision,
                'OpenAI credential revision differs from image binding')

    def prepare(self, request, binding):
        self._check_credential(binding)
        return super().prepare(request, binding)

    def dispatch(self, request, binding):
        self._check_credential(binding)
        return super().dispatch(request, binding)

    @staticmethod
    def provider_request(request, binding):
        require(request.seed is None, 'OpenAI Images does not support deterministic seed')
        return {'model': binding.model, 'prompt': request.prompt, 'n': 1,
                'size': request.size, 'quality': request.quality, 'output_format': 'png'}

    def _http_transport(self, binding, request):
        secret, revision = self.credentials.resolve(binding.credential_ref)
        require(revision == binding.credential_revision, 'OpenAI credential revision changed')
        connection = http.client.HTTPSConnection('api.openai.com', 443,
                                                  timeout=binding.timeout_seconds)
        try:
            connection.request('POST', '/v1/images/generations',
                               body=json.dumps(request, separators=(',', ':')).encode(),
                               headers={'Authorization': 'Bearer ' + secret,
                                        'Content-Type': 'application/json',
                                        'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise MediaResponseError(f'OpenAI Images returned HTTP {response.status}')
            raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON: raise MediaResponseError('OpenAI response exceeds 24 MiB')
            try: value = json.loads(raw)
            except (UnicodeError, ValueError) as exc:
                raise MediaResponseError('Invalid OpenAI Images JSON') from exc
            data = value.get('data') if isinstance(value, dict) else None
            if not (isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict)
                    and isinstance(data[0].get('b64_json'), str) and 'url' not in data[0]):
                raise MediaResponseError('OpenAI Images must return one inline base64 image')
            try: image = base64.b64decode(data[0]['b64_json'], validate=True)
            except (ValueError, binascii.Error) as exc:
                raise MediaResponseError('Invalid OpenAI image base64') from exc
            return image, {'created': value.get('created')}
        finally:
            connection.close()


class ComfyImageAdapter(MediaAdapter):
    binding_type = ComfyImageBinding

    def __init__(self, runs, transport=None, sleeper=time.sleep):
        self.sleeper = sleeper
        super().__init__(runs, transport or self._http_transport)

    @staticmethod
    def provider_request(request, binding):
        require(type(request.seed) is int, 'ComfyUI requires an explicit seed')
        require(request.quality == 'auto',
                'ComfyUI quality is controlled by the approved workflow')
        return {'prompt': binding.render(request), 'client_id': request.run_id,
                'output_node_id': binding.output_node_id,
                'workflow_sha256': binding.workflow_sha256,
                'workflow_revision': binding.workflow_revision}

    @staticmethod
    def _connection(binding):
        parsed = urlsplit(binding.endpoint)
        if binding.boundary == 'same-node':
            return http.client.HTTPConnection(parsed.hostname, parsed.port,
                                              timeout=binding.timeout_seconds)
        return http.client.HTTPSConnection(parsed.hostname, parsed.port,
                                           timeout=binding.timeout_seconds,
                                           context=ssl._create_unverified_context())

    def _json_call(self, binding, method, path, body=None):
        connection = self._connection(binding)
        try:
            connection.connect()
            if binding.tls_cert_sha256:
                certificate = connection.sock.getpeercert(binary_form=True)
                require(hashlib.sha256(certificate).hexdigest() == binding.tls_cert_sha256,
                        'ComfyUI TLS certificate pin mismatch')
            encoded = None if body is None else json.dumps(body, separators=(',', ':')).encode()
            connection.request(method, path, body=encoded,
                               headers={'Content-Type': 'application/json',
                                        'Accept': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise MediaResponseError(f'ComfyUI returned HTTP {response.status}')
            raw = response.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON: raise MediaResponseError('ComfyUI response exceeds 24 MiB')
            try: return json.loads(raw)
            except (UnicodeError, ValueError) as exc:
                raise MediaResponseError('Invalid ComfyUI JSON') from exc
        finally: connection.close()

    def _http_transport(self, binding, request):
        submitted = dict(prompt=request['prompt'], client_id=request['client_id'])
        reply = self._json_call(binding, 'POST', '/prompt', submitted)
        prompt_id = reply.get('prompt_id') if isinstance(reply, dict) else None
        require(isinstance(prompt_id, str)
                and bool(re.fullmatch(r'[A-Za-z0-9-]{1,128}', prompt_id)),
                'Invalid ComfyUI prompt ID')
        history = None
        for poll in range(MAX_POLLS):
            value = self._json_call(binding, 'GET', '/history/' + prompt_id)
            entry = value.get(prompt_id) if isinstance(value, dict) else None
            if isinstance(entry, dict) and isinstance(entry.get('outputs'), dict):
                history = entry; break
            if poll + 1 < MAX_POLLS: self.sleeper(1)
        if history is None: raise TimeoutError('ComfyUI result polling exhausted')
        output = history['outputs'].get(request['output_node_id'])
        images = output.get('images') if isinstance(output, dict) else None
        if not (isinstance(images, list) and len(images) == 1 and isinstance(images[0], dict)):
            raise MediaResponseError('ComfyUI must return one configured image')
        image = images[0]
        if not (set(image) >= {'filename', 'subfolder', 'type'}
                and all(isinstance(image[key], str) for key in ('filename', 'subfolder', 'type'))):
            raise MediaResponseError('Invalid ComfyUI image identity')
        query = urlencode({key: image[key] for key in ('filename', 'subfolder', 'type')})
        connection = self._connection(binding)
        try:
            connection.connect()
            if binding.tls_cert_sha256:
                cert = connection.sock.getpeercert(binary_form=True)
                require(hashlib.sha256(cert).hexdigest() == binding.tls_cert_sha256,
                        'ComfyUI TLS certificate pin mismatch')
            connection.request('GET', '/view?' + query, headers={'Accept': 'image/png'})
            response = connection.getresponse()
            if response.status != 200 or response.getheader('Content-Type', '').split(';')[0] != 'image/png':
                raise MediaResponseError('ComfyUI view did not return PNG')
            raw = response.read(MAX_IMAGE + 1)
            if len(raw) > MAX_IMAGE: raise MediaResponseError('ComfyUI image exceeds 16 MiB')
            return raw, {'prompt_id': prompt_id, 'image': image,
                         'workflow_sha256': request['workflow_sha256'],
                         'workflow_revision': request['workflow_revision']}
        finally: connection.close()
