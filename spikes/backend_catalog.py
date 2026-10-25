# SPDX-FileCopyrightText: 2026 Antonín Micka
# SPDX-License-Identifier: MPL-2.0
"""Provider-neutral backend/service, model preference and resource projections."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat

from spikes.metadata import require, timestamp


SCHEMA = 1
SERVICES = frozenset({'text-generation', 'image-generation', 'web-search',
                      'storage-import', 'resource-metrics'})
RESOURCE_KINDS = frozenset({'consumption', 'cost', 'free-token-balance',
                            'prepaid-token-balance', 'credit-balance', 'quota'})
BACKENDS = (
    ('ollama', 'Ollama', ('text-generation', 'resource-metrics')),
    ('openai-responses', 'OpenAI', ('text-generation', 'image-generation',
                                    'resource-metrics')),
    ('atlascloud-text', 'AtlasCloud', ('text-generation', 'resource-metrics')),
    ('comfyui', 'ComfyUI', ('image-generation',)),
    ('searxng', 'SearXNG', ('web-search',)),
    ('google-drive', 'Google Drive', ('storage-import',)),
)
BACKEND_IDS = frozenset(item[0] for item in BACKENDS)


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def backend_catalog(states):
    """Project adapter status into one bounded, non-secret settings catalog."""
    require(isinstance(states, dict) and set(states) <= BACKEND_IDS,
            'Invalid backend state projection')
    rows = []
    for backend_id, name, services in BACKENDS:
        state = states.get(backend_id, {})
        require(isinstance(state, dict)
                and set(state) <= {'configured', 'availability', 'detail'},
                'Invalid backend state')
        configured = state.get('configured', False)
        availability = state.get('availability', 'unknown')
        require(type(configured) is bool
                and availability in {'available', 'unavailable', 'unknown', 'stale'},
                'Invalid backend status')
        detail = state.get('detail')
        require(detail is None or (isinstance(detail, str) and len(detail) <= 512
                                   and '\0' not in detail), 'Invalid backend detail')
        rows.append({'backend_id': backend_id, 'display_name': name,
                     'services': list(services), 'configured': configured,
                     'availability': availability, 'detail': detail,
                     'settings_dialog': 'backend-dialog-' + backend_id})
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    return {'schema_version': SCHEMA, 'revision': 'backend-catalog-' + digest[:24],
            'backends': rows}


def resource_metric(*, backend_id, kind, name, value, unit, scope,
                    fetched_at=None, period_start=None, period_end=None,
                    status='available', source='provider-response'):
    """Normalize reported usage, quota and balances without guessing missing values."""
    require(backend_id in {item[0] for item in BACKENDS}, 'Unknown resource backend')
    require(kind in RESOURCE_KINDS, 'Unknown backend resource kind')
    require(isinstance(name, str) and name and isinstance(unit, str) and unit
            and isinstance(scope, str) and scope, 'Invalid backend resource identity')
    require(status in {'available', 'stale', 'unsupported', 'unavailable'},
            'Invalid backend resource status')
    require((type(value) in {int, float} and value >= 0)
            if status in {'available', 'stale'} else value is None,
            'Invalid backend resource value')
    observed = fetched_at or _now(); timestamp(observed)
    for boundary in (period_start, period_end):
        require(boundary is None or isinstance(boundary, int) and boundary >= 0,
                'Invalid backend resource period')
    return {'schema_version': SCHEMA, 'backend_id': backend_id, 'kind': kind,
            'name': name, 'value': value, 'unit': unit, 'scope': scope,
            'status': status, 'fetched_at': observed, 'period_start': period_start,
            'period_end': period_end, 'source': source}


class ModelPreferences:
    """CAS-protected node-local ordering of canonical model IDs."""
    def __init__(self, state_dir):
        self.root = Path(state_dir).absolute(); info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Model preference state directory requires owned mode 0700')
        self.path = self.root / 'model-preferences.json'

    @staticmethod
    def _validate(value):
        require(isinstance(value, dict)
                and set(value) == {'schema_version', 'revision', 'updated_at',
                                   'preferred_model_ids'}
                and value['schema_version'] == SCHEMA
                and type(value['revision']) is int and value['revision'] >= 0,
                'Invalid model preferences')
        timestamp(value['updated_at'])
        ids = value['preferred_model_ids']
        require(isinstance(ids, list) and len(ids) <= 1000
                and len(ids) == len(set(ids))
                and all(isinstance(item, str) and item.strip() == item and item
                        and len(item.encode()) <= 256 and not any(c in item for c in '\0\r\n')
                        for item in ids), 'Invalid preferred model IDs')
        return {'schema_version': SCHEMA, 'revision': value['revision'],
                'updated_at': value['updated_at'], 'preferred_model_ids': list(ids)}

    def load(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {'schema_version': SCHEMA, 'revision': 0,
                    'updated_at': '1970-01-01T00:00:00Z',
                    'preferred_model_ids': []}
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe model preference file')
            raw = os.read(fd, 64 * 1024 + 1)
        finally:
            os.close(fd)
        require(len(raw) <= 64 * 1024, 'Model preferences exceed 64 KiB')
        return self._validate(json.loads(raw))

    def save(self, preferred_model_ids, expected_revision):
        require(type(expected_revision) is int and expected_revision >= 0,
                'Invalid expected model preference revision')
        current = self.load()
        require(current['revision'] == expected_revision,
                'Model preferences changed before save')
        value = self._validate({'schema_version': SCHEMA,
            'revision': expected_revision + 1, 'updated_at': _now(),
            'preferred_model_ids': preferred_model_ids})
        raw = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':')) + '\n').encode()
        require(len(raw) <= 64 * 1024, 'Model preferences exceed 64 KiB')
        temporary = self.root / ('.model-preferences-' + os.urandom(8).hex() + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        try:
            os.write(fd, raw); os.fsync(fd); os.close(fd); fd = -1
            os.replace(temporary, self.path)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if fd >= 0: os.close(fd)
            if temporary.exists(): temporary.unlink()
        return value


class BackendResetJournal:
    """Durable marker for profile-first, credential-second backend reset recovery."""
    def __init__(self, state_dir, backend_id):
        require(backend_id in BACKEND_IDS, 'Unknown backend reset target')
        self.root = Path(state_dir).absolute(); info = self.root.stat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                and stat.S_IMODE(info.st_mode) == 0o700,
                'Backend reset state directory requires owned mode 0700')
        self.backend_id = backend_id
        self.path = self.root / ('backend-reset-' + backend_id + '.json')

    def load(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_nlink == 1 and not info.st_mode & 0o077,
                    'Unsafe backend reset journal')
            raw = os.read(fd, 16 * 1024 + 1)
        finally:
            os.close(fd)
        require(len(raw) <= 16 * 1024, 'Backend reset journal exceeds 16 KiB')
        value = json.loads(raw)
        require(isinstance(value, dict)
                and set(value) == {'schema_version', 'backend_id', 'credential_refs'}
                and value['schema_version'] == SCHEMA
                and value['backend_id'] == self.backend_id
                and isinstance(value['credential_refs'], list)
                and len(value['credential_refs']) <= 8
                and len(value['credential_refs']) == len(set(value['credential_refs']))
                and all(isinstance(item, str) and item and len(item) <= 256
                        and not any(char in item for char in '\0\r\n')
                        for item in value['credential_refs']),
                'Invalid backend reset journal')
        return value

    def begin(self, credential_refs=()):
        require(self.load() is None, 'Backend reset is already pending')
        value = {'schema_version': SCHEMA, 'backend_id': self.backend_id,
                 'credential_refs': list(credential_refs)}
        raw = (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()
        temporary = self.root / ('.backend-reset-' + os.urandom(8).hex() + '.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        try:
            with os.fdopen(fd, 'wb', closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(stream.fileno())
            os.close(fd); fd = -1
            os.replace(temporary, self.path)
            self._sync_root()
        finally:
            if fd >= 0: os.close(fd)
            if temporary.exists(): temporary.unlink()
        return value

    def finish(self):
        try: self.path.unlink()
        except FileNotFoundError: return
        self._sync_root()

    def _sync_root(self):
        directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)


def durable_unlink(path):
    """Remove one node-local profile and durably record its absence."""
    path = Path(path)
    try: path.unlink()
    except FileNotFoundError: return False
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)
    return True
