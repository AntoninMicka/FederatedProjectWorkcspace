# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Portable local Git reference descriptors; foreign bytes never enter the index."""
from spikes.metadata import MAX_FILE, MAX_METADATA, parse_json, require, safe_path, uuid
from spikes.reporting_schema import PRIVACY, digest, encoded, fields, hex_id

SCHEMA = 'fpw-artifact-reference-v1'
FORK = 'fpw-artifact-fork-v1'


def pin(value):
    fields(value, 'project_id repository artifact_id commit_id path sha256 metadata_sha256 privacy')
    uuid(value['project_id']); uuid(value['artifact_id']); hex_id(value['commit_id'], True)
    require(value['repository'] == 'fpw-project-git:' + value['project_id'], 'Invalid source repository identity')
    parts = safe_path(value['path'])
    require(len(parts) == 3 and parts[:2] == ['artifacts', value['artifact_id']]
            and parts[2] != 'metadata.json', 'Reference must select artifact content')
    hex_id(value['sha256']); hex_id(value['metadata_sha256'])
    require(isinstance(value['privacy'], str) and value['privacy'] in PRIVACY, 'Invalid reference privacy')
    return value


def descriptor(value):
    fields(value, 'schema source')
    require(value['schema'] == SCHEMA, 'Unsupported reference version')
    pin(value['source'])
    return value


def references(files, entities):
    result = {}
    for id_, meta in entities.items():
        if meta['kind'] == 'source' or not meta.get('file', '').endswith('.json'):
            continue
        path = f'artifacts/{id_}/' + meta['file']
        data = files[path]
        tagged = SCHEMA in meta.get('tags', [])
        if not tagged and meta['file'] != 'reference.json' and b'fpw-artifact-reference-' not in data:
            continue
        try:
            value = parse_json(data, maximum=MAX_FILE)
        except ValueError:
            require(not tagged and b'fpw-artifact-reference-' not in data, 'Malformed reference JSON')
            continue
        declared = isinstance(value, dict) and isinstance(value.get('schema'), str) and value['schema'].startswith('fpw-artifact-reference-')
        if not declared and not tagged:
            continue
        require(len(data) <= MAX_METADATA, 'Reference descriptor exceeds metadata limit')
        descriptor(value)
        require(id_ != value['source']['artifact_id'], 'Reference needs a distinct local ID')
        require(meta['kind'] == 'document' and meta['file'] == 'reference.json'
                and data == encoded(value), 'Reference requires canonical reference.json sidecar')
        require(PRIVACY[meta['privacy']] >= PRIVACY[value['source']['privacy']], 'Reference privacy relaxation')
        result[id_] = value
    return result


def transition(before_files, after_files, before_entities, after_entities):
    before = references(before_files, before_entities)
    after = references(after_files, after_entities)
    for id_, value in before.items():
        if id_ not in after_entities:  # Removing a pointer never removes its source.
            continue
        require(id_ in after, 'Reference cannot become a local copy implicitly')
        first, second = value['source'], after[id_]['source']
        require(all(first[k] == second[k] for k in ('project_id', 'repository', 'artifact_id')),
                'Reference source identity is immutable')
        a, b = before_entities[id_], after_entities[id_]
        require(all(a.get(k) == b.get(k) for k in ('id', 'kind', 'created_at', 'author_id', 'file'))
                and PRIVACY[b['privacy']] >= PRIVACY[a['privacy']], 'Reference identity/privacy changed')
    for id_, meta in before_entities.items():
        if FORK in meta.get('tags', []):
            after_meta = after_entities.get(id_)
            if after_meta is not None:
                require(FORK in after_meta.get('tags', []) and after_meta.get('description') == meta.get('description'),
                        'Fork provenance is immutable')
