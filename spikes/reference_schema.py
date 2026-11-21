# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Portable local Git reference descriptors; foreign bytes never enter the index.

A source project records an explicit share grant (ADR 0086); a target project
records a pinned reference. Neither grants project access by itself.
"""
import re

from spikes.metadata import (MAX_FILE, MAX_METADATA, UnsupportedVersion, parse_json, require,
                             safe_path, timestamp, uuid)
from spikes.reporting_schema import PRIVACY, digest, encoded, fields, hex_id, text

SCHEMA_V1 = 'fpw-artifact-reference-v1'
SCHEMA = 'fpw-artifact-reference-v2'
SCHEMAS = (SCHEMA_V1, SCHEMA)
FORK = 'fpw-artifact-fork-v1'
SHARE = 'fpw-artifact-share-v1'
MAX_TARGETS = 64
PURPOSES = ('share', 'output')  # output: a project result offered to its consumers.
MAX_REASON = 1000


def _version(value, prefix, supported, kind):
    """Typed fail-closed refusal of an unknown descriptor version (ADR 0085)."""
    match = re.fullmatch(re.escape(prefix) + r'v([0-9]{1,6})', value) if isinstance(value, str) else None
    found = int(match.group(1)) if match else None
    if found not in supported:
        raise UnsupportedVersion(kind, found, supported)
    return found


def reason(value):
    text(value)
    require(len(value) <= MAX_REASON and '\0' not in value, 'Invalid sharing reason')
    return value


def single_line(value, maximum=200):
    text(value)
    require(len(value) <= maximum and not any(c in value for c in '\r\n'), 'Invalid single-line text')
    return value


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


def attachment(value):
    """Target-side provenance of a v2 reference: which share and why it is used."""
    fields(value, 'share_id originator_id attached_by reason')
    uuid(value['share_id']); uuid(value['originator_id']); uuid(value['attached_by'])
    reason(value['reason'])
    return value


def descriptor(value):
    require(isinstance(value, dict), 'Invalid reference descriptor')
    version = _version(value.get('schema'), 'fpw-artifact-reference-', (1, 2), 'artifact-reference')
    if version == 1:
        fields(value, 'schema source')
    else:
        fields(value, 'schema source share')
        attachment(value['share'])
    pin(value['source'])
    return value


def share_record(value):
    """Source-side grant: one artifact, explicit allowed targets, originator, reason."""
    require(isinstance(value, dict), 'Invalid share record')
    _version(value.get('schema'), 'fpw-artifact-share-', (1,), 'artifact-share')
    fields(value, 'schema artifact_id purpose targets originator_id reason created_at revoked')
    uuid(value['artifact_id']); uuid(value['originator_id']); reason(value['reason'])
    require(value['purpose'] in PURPOSES, 'Invalid share purpose')
    timestamp(value['created_at'])
    targets = value['targets']
    require(isinstance(targets, list) and 1 <= len(targets) <= MAX_TARGETS, 'Share needs 1-64 targets')
    for target in targets: uuid(target)
    require(targets == sorted(set(targets)), 'Share targets must be unique and sorted')
    revoked = value['revoked']
    if revoked is not None:
        fields(revoked, 'at by')
        timestamp(revoked['at'], 'revoked.at'); uuid(revoked['by'])
    return value


def active(record, target_project_id):
    return record['revoked'] is None and target_project_id in record['targets']


def shares(files, entities):
    """Share grants in this (source) project; tagged sidecar share.json only."""
    result = {}
    refs = None
    for id_, meta in entities.items():
        tagged = SHARE in meta.get('tags', [])
        if not tagged and meta.get('file') != 'share.json':
            continue
        data = files[f'artifacts/{id_}/' + meta['file']]
        if not tagged:
            require(b'fpw-artifact-share-' not in data, 'Untagged share descriptor')
            continue
        require(meta['kind'] == 'document' and meta['file'] == 'share.json', 'Share requires share.json sidecar')
        require(len(data) <= MAX_METADATA, 'Share descriptor exceeds metadata limit')
        value = share_record(parse_json(data, maximum=MAX_METADATA))
        require(data == encoded(value), 'Share requires canonical share.json')
        require(id_ != value['artifact_id'], 'Share must name another artifact')
        shared = entities.get(value['artifact_id'])
        if shared is not None:  # A deleted artifact leaves an audited, unusable grant.
            if refs is None:
                refs = references(files, entities)
            require(value['artifact_id'] not in refs and SHARE not in shared.get('tags', []),
                    'Only own artifacts can be shared; reference chains are unsupported')
        result[id_] = value
    return result


def references(files, entities):
    result = {}
    for id_, meta in entities.items():
        if meta['kind'] == 'source' or not meta.get('file', '').endswith('.json'):
            continue
        path = f'artifacts/{id_}/' + meta['file']
        data = files[path]
        tagged = any(t in meta.get('tags', []) for t in SCHEMAS)
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
        require(after[id_]['schema'] == value['schema'] and after[id_].get('share') == value.get('share'),
                'Reference share provenance is immutable')
        a, b = before_entities[id_], after_entities[id_]
        require(all(a.get(k) == b.get(k) for k in ('id', 'kind', 'created_at', 'author_id', 'file'))
                and PRIVACY[b['privacy']] >= PRIVACY[a['privacy']], 'Reference identity/privacy changed')
    granted, regranted = shares(before_files, before_entities), shares(after_files, after_entities)
    for id_, value in granted.items():
        # Revocation keeps the audited record; Git history keeps earlier grants.
        require(id_ in regranted, 'Share record cannot be deleted; revoke it instead')
        after = regranted[id_]
        require(all(after[k] == value[k] for k in ('artifact_id', 'purpose', 'originator_id', 'created_at')),
                'Share identity is immutable')
        if value['revoked'] is not None:
            require(after == value, 'Revoked share is final')
        require(PRIVACY[after_entities[id_]['privacy']] >= PRIVACY[before_entities[id_]['privacy']],
                'Share privacy relaxation')
    for id_, meta in before_entities.items():
        if FORK in meta.get('tags', []):
            after_meta = after_entities.get(id_)
            if after_meta is not None:
                require(FORK in after_meta.get('tags', []) and after_meta.get('description') == meta.get('description'),
                        'Fork provenance is immutable')
