# SPDX-FileCopyrightText: 2026 Antonín Micka
# SPDX-License-Identifier: MPL-2.0
"""Provider-neutral, fail-closed node-local model knowledge and discovery."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from spikes.metadata import require


CATALOG_SCHEMA = 1
MAX_MODELS = 10000
MAX_OFFERS = 10000
MAX_CATALOG_BYTES = 1024 * 1024
CAPABILITIES = ('generate-text', 'json-output', 'streaming', 'text-output')
PROTOCOLS = {'ollama-generate-v1', 'openai-responses-v1'}
_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}')


def _text(value, label, *, identifier=False):
    require(isinstance(value, str) and value.strip() == value and bool(value)
            and not any(char in value for char in '\0\r\n'), 'Invalid ' + label)
    if identifier:
        require(bool(_ID.fullmatch(value)), 'Invalid ' + label)
    return value


def _timestamp(value, label):
    _text(value, label)
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('Invalid ' + label) from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
            'Invalid ' + label)
    return value


def _root(state_dir):
    root = Path(state_dir).absolute()
    info = root.stat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            'Model catalog state directory requires owned mode 0700')
    return root


def _encode(value, label):
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':')) + '\n').encode()
    require(len(raw) <= MAX_CATALOG_BYTES, label + ' exceeds 1 MiB')
    return raw


def _atomic_replace(root, path, raw, prefix):
    temporary = root / (prefix + os.urandom(8).hex() + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
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


def _read(path, label):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_nlink == 1 and not info.st_mode & 0o077,
                'Unsafe ' + label + ' file')
        raw = os.read(fd, MAX_CATALOG_BYTES + 1)
    finally:
        os.close(fd)
    require(len(raw) <= MAX_CATALOG_BYTES, label + ' exceeds 1 MiB')
    try:
        return json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValueError('Invalid ' + label + ' JSON') from exc


def validate_capability(value, allowed_states):
    required = {'name', 'value', 'state', 'source', 'revision', 'observed_at'}
    require(isinstance(value, dict) and set(value) == required,
            'Unknown or missing model capability field')
    require(value['name'] in CAPABILITIES, 'Unknown model capability')
    require(type(value['value']) is bool, 'Invalid model capability value')
    require(value['state'] in allowed_states, 'Invalid model capability state')
    _text(value['source'], 'model capability source', identifier=True)
    _text(value['revision'], 'model capability revision', identifier=True)
    _timestamp(value['observed_at'], 'model capability timestamp')
    return dict(value)


def _capabilities(values, allowed_states):
    require(isinstance(values, list) and len(values) <= len(CAPABILITIES),
            'Invalid model capabilities')
    normalized = [validate_capability(item, allowed_states) for item in values]
    names = [item['name'] for item in normalized]
    require(len(names) == len(set(names)), 'Duplicate model capability')
    return sorted(normalized, key=lambda item: item['name'])


def _offer(value, *, discovery):
    common = {'offer_id', 'provider_id', 'provider_model_id', 'protocol',
              'capabilities'}
    required = common | ({'availability'} if discovery else {'canonical_model_id'})
    require(isinstance(value, dict) and set(value) == required,
            'Unknown or missing model offer field')
    for field in ('offer_id', 'provider_id', 'provider_model_id'):
        _text(value[field], field.replace('_', ' '), identifier=True)
    require(value['protocol'] in PROTOCOLS, 'Unsupported model offer protocol')
    result = {field: value[field] for field in common - {'capabilities'}}
    if discovery:
        require(value['availability'] in {'available', 'removed'},
                'Invalid model offer availability')
        result['availability'] = value['availability']
        result['capabilities'] = _capabilities(value['capabilities'], {'reported'})
    else:
        canonical = value['canonical_model_id']
        require(canonical is None or isinstance(canonical, str),
                'Invalid canonical model reference')
        if canonical is not None:
            _text(canonical, 'canonical model ID', identifier=True)
        result['canonical_model_id'] = canonical
        result['capabilities'] = _capabilities(value['capabilities'], {'reviewed'})
    return result


def validate_knowledge(value):
    required = {'schema_version', 'revision', 'reviewed_at', 'models', 'offers'}
    require(isinstance(value, dict) and set(value) == required
            and value['schema_version'] == CATALOG_SCHEMA,
            'Unsupported model knowledge catalog')
    _text(value['revision'], 'model knowledge revision', identifier=True)
    _timestamp(value['reviewed_at'], 'model knowledge timestamp')
    require(isinstance(value['models'], list) and len(value['models']) <= MAX_MODELS,
            'Invalid canonical model list')
    models = []
    for item in value['models']:
        require(isinstance(item, dict) and set(item) == {'model_id', 'display_name'},
                'Unknown or missing canonical model field')
        _text(item['model_id'], 'canonical model ID', identifier=True)
        _text(item['display_name'], 'canonical model display name')
        models.append(dict(item))
    model_ids = [item['model_id'] for item in models]
    require(len(model_ids) == len(set(model_ids)), 'Duplicate canonical model ID')
    require(isinstance(value['offers'], list) and len(value['offers']) <= MAX_OFFERS,
            'Invalid reviewed model offers')
    offers = [_offer(item, discovery=False) for item in value['offers']]
    offer_ids = [item['offer_id'] for item in offers]
    identities = [(item['provider_id'], item['provider_model_id'], item['protocol'])
                  for item in offers]
    require(len(offer_ids) == len(set(offer_ids)), 'Duplicate model offer ID')
    require(len(identities) == len(set(identities)), 'Duplicate provider model offer')
    require(all(item['canonical_model_id'] is None
                or item['canonical_model_id'] in set(model_ids) for item in offers),
            'Unknown canonical model reference')
    return {'schema_version': CATALOG_SCHEMA, 'revision': value['revision'],
            'reviewed_at': value['reviewed_at'],
            'models': sorted(models, key=lambda item: item['model_id']),
            'offers': sorted(offers, key=lambda item: item['offer_id'])}


def validate_discovery(value):
    required = {'schema_version', 'provider_id', 'scope_id', 'binding_revision',
                'credential_revision', 'fetched_at', 'offers'}
    require(isinstance(value, dict) and set(value) == required
            and value['schema_version'] == CATALOG_SCHEMA,
            'Unsupported model discovery snapshot')
    for field in ('provider_id', 'scope_id', 'binding_revision'):
        _text(value[field], field.replace('_', ' '), identifier=True)
    credential = value['credential_revision']
    require(credential is None or (type(credential) is int and credential >= 1),
            'Invalid model discovery credential revision')
    _timestamp(value['fetched_at'], 'model discovery timestamp')
    require(isinstance(value['offers'], list) and len(value['offers']) <= MAX_OFFERS,
            'Invalid discovered model offers')
    offers = [_offer(item, discovery=True) for item in value['offers']]
    offer_ids = [item['offer_id'] for item in offers]
    identities = [(item['provider_id'], item['provider_model_id'], item['protocol'])
                  for item in offers]
    require(all(item['provider_id'] == value['provider_id'] for item in offers),
            'Discovery offer belongs to a different provider')
    require(len(offer_ids) == len(set(offer_ids)), 'Duplicate discovered offer ID')
    require(len(identities) == len(set(identities)), 'Duplicate discovered model offer')
    return {'schema_version': CATALOG_SCHEMA, 'provider_id': value['provider_id'],
            'scope_id': value['scope_id'], 'binding_revision': value['binding_revision'],
            'credential_revision': credential, 'fetched_at': value['fetched_at'],
            'offers': sorted(offers, key=lambda item: item['offer_id'])}


def collect_discovery_pages(first_page, fetch_page, *, max_pages=100):
    """Collect explicit provider pages once each, with no retry or hidden fallback."""
    require(callable(fetch_page) and type(max_pages) is int and 1 <= max_pages <= 100,
            'Invalid model discovery pager')
    items = []; page = first_page; cursors = set()
    for _ in range(max_pages):
        require(isinstance(page, dict) and set(page) == {'items', 'next_cursor'}
                and isinstance(page['items'], list), 'Invalid model discovery page')
        items.extend(page['items'])
        require(len(items) <= MAX_OFFERS, 'Model discovery page limit exceeded')
        cursor = page['next_cursor']
        if cursor is None:
            return items
        _text(cursor, 'model discovery cursor', identifier=True)
        require(cursor not in cursors, 'Repeated model discovery cursor')
        cursors.add(cursor)
        page = fetch_page(cursor)
    raise ValueError('Model discovery page count exceeded')


class ModelKnowledgeStore:
    """Explicitly reviewed knowledge, never provider availability or credentials."""
    def __init__(self, state_dir):
        self.root = _root(state_dir)
        self.path = self.root / 'model-catalog-knowledge.json'

    def save(self, value, expected_revision=None):
        value = validate_knowledge(value)
        require(expected_revision is None or isinstance(expected_revision, str),
                'Invalid expected model knowledge revision')
        if expected_revision is not None:
            try:
                current = self.load()['revision']
            except FileNotFoundError:
                current = 'empty-v1'
            require(current == expected_revision,
                    'Model knowledge catalog changed before import')
        _atomic_replace(self.root, self.path, _encode(value, 'Model knowledge catalog'),
                        '.model-knowledge-')
        return value

    def load(self):
        return validate_knowledge(_read(self.path, 'model knowledge catalog'))

    def load_or_empty(self, now):
        try:
            return self.load()
        except FileNotFoundError:
            return {'schema_version': CATALOG_SCHEMA, 'revision': 'empty-v1',
                    'reviewed_at': now, 'models': [], 'offers': []}

    def export(self):
        return self.load()


class ModelDiscoveryStore:
    """Last complete provider snapshot for one local discovery scope."""
    def __init__(self, state_dir, provider_id, scope_id):
        self.root = _root(state_dir)
        _text(provider_id, 'provider ID', identifier=True)
        _text(scope_id, 'discovery scope ID', identifier=True)
        self.provider_id = provider_id; self.scope_id = scope_id
        digest = hashlib.sha256((provider_id + '\0' + scope_id).encode()).hexdigest()
        self.path = self.root / ('model-discovery-' + digest + '.json')

    def publish(self, value):
        value = validate_discovery(value)
        require(value['provider_id'] == self.provider_id
                and value['scope_id'] == self.scope_id,
                'Model discovery snapshot belongs to a different scope')
        try:
            previous = self.load_raw()
        except FileNotFoundError:
            previous = None
        if previous is not None:
            current = {item['offer_id']: item for item in value['offers']}
            for item in previous['offers']:
                if item['offer_id'] not in current:
                    removed = dict(item, availability='removed', capabilities=[])
                    value['offers'].append(removed)
            require(len(value['offers']) <= MAX_OFFERS, 'Too many retained model offers')
            value['offers'].sort(key=lambda item: item['offer_id'])
        _atomic_replace(self.root, self.path, _encode(value, 'Model discovery snapshot'),
                        '.model-discovery-')
        return value

    def load_raw(self):
        value = validate_discovery(_read(self.path, 'model discovery snapshot'))
        require(value['provider_id'] == self.provider_id
                and value['scope_id'] == self.scope_id,
                'Model discovery snapshot belongs to a different scope')
        return value

    def load(self, binding_revision, credential_revision, *, refresh_error=None):
        value = self.load_raw()
        fresh = (value['binding_revision'] == binding_revision
                 and value['credential_revision'] == credential_revision
                 and refresh_error is None)
        return dict(value, freshness='fresh' if fresh else 'stale',
                    refresh_error=refresh_error)


def project_catalog(knowledge, discoveries):
    """Combine exact offers without routing, fuzzy matching or optimistic union."""
    knowledge = validate_knowledge(knowledge)
    require(isinstance(discoveries, list), 'Invalid discovery projections')
    reviewed = {(item['provider_id'], item['provider_model_id'], item['protocol']): item
                for item in knowledge['offers']}
    observed = {}
    discovery_meta = {}
    for item in discoveries:
        required = {'schema_version', 'provider_id', 'scope_id', 'binding_revision',
                    'credential_revision', 'fetched_at', 'offers', 'freshness',
                    'refresh_error'}
        require(isinstance(item, dict) and set(item) == required,
                'Invalid discovery projection')
        raw = validate_discovery({key: item[key] for key in required
                                  if key not in {'freshness', 'refresh_error'}})
        require(item['freshness'] in {'fresh', 'stale'}, 'Invalid discovery freshness')
        require(item['refresh_error'] is None or item['refresh_error'] in {
            'invalid-response', 'rate-limited', 'rejected', 'unavailable'},
            'Invalid discovery refresh error')
        for offer in raw['offers']:
            key = (offer['provider_id'], offer['provider_model_id'], offer['protocol'])
            require(key not in observed, 'Duplicate offer across discovery scopes')
            observed[key] = offer
            discovery_meta[key] = {'freshness': item['freshness'],
                                   'fetched_at': item['fetched_at'],
                                   'refresh_error': item['refresh_error']}
    keys = sorted(set(reviewed) | set(observed))
    offers = []
    for key in keys:
        review = reviewed.get(key); report = observed.get(key)
        reported_caps = {item['name']: item for item in (report or {}).get('capabilities', [])}
        reviewed_caps = {item['name']: item for item in (review or {}).get('capabilities', [])}
        capabilities = []
        for name in CAPABILITIES:
            reported = reported_caps.get(name); checked = reviewed_caps.get(name)
            if reported is not None and checked is not None and reported['value'] != checked['value']:
                capabilities.append({'name': name, 'supported': False,
                                     'state': 'conflicting',
                                     'reported': reported, 'reviewed': checked})
            elif reported is not None:
                capabilities.append({'name': name, 'supported': reported['value'],
                                     'state': 'reported', 'reported': reported,
                                     'reviewed': checked})
            elif checked is not None:
                capabilities.append({'name': name, 'supported': checked['value'],
                                     'state': 'reviewed', 'reported': None,
                                     'reviewed': checked})
            else:
                capabilities.append({'name': name, 'supported': False,
                                     'state': 'unknown', 'reported': None,
                                     'reviewed': None})
        meta = discovery_meta.get(key, {'freshness': 'stale', 'fetched_at': None,
                                        'refresh_error': None})
        offers.append({'offer_id': (report or review)['offer_id'],
                       'provider_id': key[0], 'provider_model_id': key[1],
                       'protocol': key[2],
                       'canonical_model_id': None if review is None
                       else review['canonical_model_id'],
                       'availability': 'not-observed' if report is None
                       else report['availability'],
                       'freshness': meta['freshness'],
                       'fetched_at': meta['fetched_at'],
                       'refresh_error': meta['refresh_error'],
                       'capabilities': capabilities})
    return {'schema_version': CATALOG_SCHEMA,
            'knowledge_revision': knowledge['revision'],
            'knowledge_reviewed_at': knowledge['reviewed_at'],
            'models': knowledge['models'], 'offers': offers}
