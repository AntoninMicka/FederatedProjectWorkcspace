"""Executable M0 schema and bounded metadata parsing, independent of storage."""
from datetime import datetime
import json
from pathlib import PurePosixPath
import re
from uuid import UUID

import yaml

MAX_METADATA = 64 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_SNAPSHOT = 64 * 1024 * 1024
STATES = {
    'assumptions': {'open', 'confirmed', 'rejected'},
    'hypotheses': {'open', 'supported', 'rejected'},
    'questions': {'open', 'answered', 'closed'},
    'risks': {'open', 'mitigated', 'accepted', 'closed'},
    'decisions': {'proposed', 'accepted', 'rejected', 'superseded'},
    'rejected-variants': {'rejected', 'reopened'},
    'sources': {'unverified', 'verified', 'rejected'},
    'reviews': {'open', 'verified', 'rejected'},
    'tasks': {'open', 'in-progress', 'done', 'cancelled'},
}
REQUIRED = {'schema_version', 'id', 'title', 'kind', 'created_at', 'author_id', 'privacy', 'provenance'}
OPTIONAL = {'description', 'tags', 'source_url', 'relations'}


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def uuid(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value, 'Expected canonical UUID')
    except (ValueError, AttributeError) as exc:
        raise ValidationError('Expected canonical UUID') from exc


def safe_path(value):
    require(isinstance(value, str) and bool(value), 'Expected relative path')
    parts = value.split('/')
    require(not any(p in {'', '.', '..', '.git'} for p in parts), 'Unsafe path')
    require(not any(c in value for c in '\\:\x00\r\n'), 'Unsafe path')
    require(not PurePosixPath(value).is_absolute(), 'Absolute path')
    return parts


def pairs(items):
    result = {}
    for key, value in items:
        require(isinstance(key, str) and key not in result, 'Duplicate or non-string key')
        result[key] = value
    return result


def bounded(data):
    require(isinstance(data, bytes) and len(data) <= MAX_METADATA, 'Metadata exceeds 64 KiB')
    try:
        return data.decode('utf-8')
    except UnicodeError as exc:
        raise ValidationError('Metadata must be UTF-8') from exc


def parse_json(data):
    text = bounded(data)
    # Limit nesting before the recursive JSON decoder, ignoring quoted brackets.
    depth, quoted, escape = 0, False, False
    for char in text:
        if quoted:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            require(depth <= 16, 'Metadata nesting exceeds 16')
        elif char in ']}':
            depth -= 1
    try:
        return json.loads(text, object_pairs_hook=pairs,
                          parse_constant=lambda _: require(False, 'Non-finite JSON number'))
    except (ValueError, RecursionError) as exc:
        raise ValidationError(str(exc)) from exc


class StrictLoader(yaml.SafeLoader):
    pass


# Keep timestamps as strings so JSON and YAML share one schema.
StrictLoader.yaml_implicit_resolvers = {
    key: [(tag, regex) for tag, regex in rules if tag != 'tag:yaml.org,2002:timestamp']
    for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def mapping(loader, node):
    return pairs((loader.construct_object(k, deep=True), loader.construct_object(v, deep=True))
                 for k, v in node.value)


StrictLoader.add_constructor('tag:yaml.org,2002:map', mapping)


def frontmatter(data):
    require(len(data) <= MAX_FILE, 'Artifact exceeds 16 MiB')
    lines = data.splitlines(keepends=True)
    require(lines and lines[0].rstrip(b'\r\n') == b'---', 'Missing frontmatter')
    end = next((i for i in range(1, len(lines)) if lines[i].rstrip(b'\r\n') == b'---'), None)
    require(end is not None, 'Unclosed frontmatter')
    text = bounded(b''.join(lines[1:end]))
    try:
        depth = 0
        for event in yaml.parse(text, Loader=StrictLoader):
            require(not isinstance(event, yaml.AliasEvent) and not getattr(event, 'anchor', None),
                    'YAML anchors and aliases are unsupported')
            require(not getattr(event, 'tag', None), 'Explicit YAML tags are unsupported')
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
                require(depth <= 16, 'Metadata nesting exceeds 16')
            elif isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
        result = yaml.load(text, Loader=StrictLoader)
        data.decode('utf-8')
        return result
    except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
        raise ValidationError(str(exc)) from exc


def validate_metadata(meta, *, sidecar=False, registry=None):
    require(isinstance(meta, dict), 'Metadata must be an object')
    extra = {'file'} if sidecar else ({'status', 'body'} if registry else set())
    require(REQUIRED | extra <= meta.keys(), 'Missing required metadata')
    require(meta.keys() <= REQUIRED | OPTIONAL | extra, 'Unknown metadata field')
    require(type(meta['schema_version']) is int and meta['schema_version'] == 1, 'Unknown schema version')
    uuid(meta['id'])
    uuid(meta['author_id'])
    for key in ['title', 'kind', 'created_at', 'privacy', 'provenance']:
        require(isinstance(meta[key], str) and bool(meta[key].strip()), f'Invalid {key}')
    require(bool(re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z', meta['created_at'])),
            'created_at must be UTC RFC3339 ending in Z')
    try:
        datetime.fromisoformat(meta['created_at'].replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValidationError('Invalid calendar timestamp') from exc
    require(meta['privacy'] in {'public', 'project', 'confidential', 'local-only'}, 'Invalid privacy')
    require(meta['provenance'] in {'user', 'external', 'llm-generated', 'llm-transformed', 'snapshot'},
            'Invalid provenance')
    for key in ('description', 'source_url'):
        if key in meta:
            require(isinstance(meta[key], str), f'Invalid {key}')
    if 'tags' in meta:
        require(isinstance(meta['tags'], list) and all(isinstance(t, str) and t.strip() for t in meta['tags']),
                'Invalid tags')
    relations = meta.get('relations', [])
    require(isinstance(relations, list), 'Invalid relations')
    for relation in relations:
        require(isinstance(relation, dict) and relation.keys() == {'type', 'target_id'}, 'Invalid relation')
        require(isinstance(relation['type'], str) and bool(relation['type'].strip()), 'Invalid relation type')
        uuid(relation['target_id'])
    if sidecar:
        require(len(safe_path(meta['file'])) == 1 and meta['file'] != 'metadata.json', 'Invalid sidecar file')
    if registry:
        require(registry in STATES and meta['kind'] == registry, 'Invalid registry kind')
        require(isinstance(meta['status'], str) and meta['status'] in STATES[registry], 'Invalid registry status')
        require(isinstance(meta['body'], str), 'Invalid registry body')
    else:
        require(meta['kind'] in {'document', 'source', 'snapshot'}, 'Invalid artifact kind')
    return meta


def validate_snapshot(files):
    """Validate artifact/registry projection only; project/node configuration is separate."""
    require(len(files) <= 10000 and sum(len(v) for v in files.values()) <= MAX_SNAPSHOT,
            'Snapshot exceeds PoC limits')
    groups, entities = {}, {}

    def insert(meta):
        require(meta['id'] not in entities, 'Duplicate ID')
        entities[meta['id']] = meta

    for path, data in files.items():
        parts = safe_path(path)
        require(isinstance(data, bytes) and len(data) <= MAX_FILE, 'File exceeds PoC limit')
        require(len(parts) == 3, 'Invalid entity layout')
        if parts[0] == 'artifacts':
            uuid(parts[1])
            groups.setdefault(parts[1], {})[parts[2]] = data
        elif parts[0] == 'registries':
            require(parts[1] in STATES and parts[2].endswith('.json'), 'Invalid registry path')
            meta = validate_metadata(parse_json(data), registry=parts[1])
            require(parts[2] == meta['id'] + '.json', 'Registry filename must match ID')
            insert(meta)
        else:
            raise ValidationError('Unsupported snapshot path')
    for artifact_id, entries in groups.items():
        if 'metadata.json' in entries:
            meta = validate_metadata(parse_json(entries['metadata.json']), sidecar=True)
            require(set(entries) == {'metadata.json', meta['file']}, 'Missing or extra sidecar content')
        else:
            require(len(entries) == 1, 'Expected one Markdown artifact')
            name, data = next(iter(entries.items()))
            require(name.endswith('.md'), 'Binary artifact needs sidecar')
            meta = validate_metadata(frontmatter(data))
        require(meta['id'] == artifact_id, 'Artifact directory must match ID')
        insert(meta)
    for meta in entities.values():
        for relation in meta.get('relations', []):
            require(relation['target_id'] in entities, 'Dangling relation')
    return entities
