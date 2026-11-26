# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Typed, append-only relation evidence. This schema alone grants no access."""
from uuid import UUID, uuid5
from datetime import datetime

from spikes.metadata import MAX_FILE, MAX_METADATA, parse_json, require, timestamp, uuid
from spikes.reference_schema import _version, reason
from spikes.reporting_schema import digest, encoded, fields, hex_id

PROPOSAL = 'fpw-project-relation-v1'
APPROVAL = 'fpw-project-relation-approval-v1'
REVOCATION = 'fpw-project-relation-revocation-v1'
SCHEMAS = (PROPOSAL, APPROVAL, REVOCATION)
POLICY = 'typed-paths-v1'
TYPES = ('parent_of', 'depends_on', 'relates_to')
# Native Python capability, never accepted from a serialized request.
_WRITE = object()


def evidence_id(relation_id, revision, project_id, kind):
    return str(uuid5(UUID(relation_id), f'{revision}:{project_id}:{kind}'))


def record(value):
    require(isinstance(value, dict), 'Invalid project relation record')
    schema = value.get('schema')
    prefix = next((s[:-2] for s in reversed(SCHEMAS) if isinstance(schema, str) and schema.startswith(s[:-1])),
                  'fpw-project-relation-')
    _version(schema, prefix, (1,), 'project-relation')
    require(schema in SCHEMAS, 'Unknown relation record')
    if schema == PROPOSAL:
        fields(value, 'schema id owner_project_id source_project_id target_project_id type revision policy '
                      'originator_id updated_by reason created_at updated_at state')
        for key in ('id', 'owner_project_id', 'source_project_id', 'target_project_id', 'originator_id', 'updated_by'):
            uuid(value[key])
        a, b = value['source_project_id'], value['target_project_id']
        require(a != b and value['owner_project_id'] == min(a, b), 'Invalid relation endpoints/owner')
        require(value['type'] in TYPES and (value['type'] != 'relates_to' or a < b), 'Invalid relation direction/type')
        require(value['policy'] == POLICY and value['state'] == 'proposed', 'Unsupported relation policy/state')
        timestamp(value['created_at']); timestamp(value['updated_at'])
        require(datetime.fromisoformat(value['updated_at'].replace('Z', '+00:00')) >=
                datetime.fromisoformat(value['created_at'].replace('Z', '+00:00')), 'Relation timestamp precedes creation')
        reason(value['reason'])
    else:
        common = ('schema id relation_id owner_project_id revision proposal_sha256 project_id operation_id ')
        fields(value, common + ('approved_by approved_at' if schema == APPROVAL else
                                'approval_id revoked_by revoked_at reason'))
        for key in ('id', 'relation_id', 'owner_project_id', 'project_id', 'operation_id'):
            uuid(value[key])
        hex_id(value['proposal_sha256'])
        actor, at = ('approved_by', 'approved_at') if schema == APPROVAL else ('revoked_by', 'revoked_at')
        uuid(value[actor]); timestamp(value[at])
        kind = 'approval' if schema == APPROVAL else 'revocation'
        require(value['id'] == evidence_id(value['relation_id'], value['revision'], value['project_id'], kind),
                'Noncanonical relation evidence identity')
        if schema == REVOCATION:
            reason(value['reason']); uuid(value['approval_id'])
            require(value['approval_id'] == evidence_id(value['relation_id'], value['revision'], value['project_id'], 'approval'),
                    'Revocation names another approval')
    require(type(value['revision']) is int and value['revision'] > 0, 'Invalid relation revision')
    return value


def records(files, entities):
    result = {}
    for id_, meta in entities.items():
        tags = meta.get('tags', [])
        data = files.get(f'artifacts/{id_}/' + meta.get('file', ''), b'')
        tagged = any(t.startswith('fpw-project-relation-') for t in tags)
        declared = b'fpw-project-relation-' in data and meta.get('file', '').endswith('.json') and meta['kind'] != 'source'
        if not tagged and not declared:
            continue
        value = parse_json(data, maximum=MAX_FILE)
        if not tagged and not (isinstance(value, dict) and isinstance(value.get('schema'), str)
                               and value['schema'].startswith('fpw-project-relation-')):
            continue  # A schema name quoted inside another JSON document is ordinary data.
        require(len(data) <= MAX_METADATA, 'Relation record exceeds metadata limit')
        record(value)
        require(meta['kind'] == 'document' and meta.get('file') == 'relation.json'
                and value['schema'] in tags and id_ == value['id'] and data == encoded(value),
                'Relation requires canonical tagged relation.json')
        require(meta['privacy'] in {'project', 'confidential', 'local-only'}, 'Relation evidence cannot be public')
        result[id_] = value
    return result


def transition(before_files, after_files, before_entities, after_entities):
    before, after = records(before_files, before_entities), records(after_files, after_entities)
    for id_, old in before.items():
        require(id_ in after, 'Relation history cannot be deleted; revoke instead')
        new = after[id_]
        if new == old:
            continue
        require(old['schema'] == new['schema'] == PROPOSAL, 'Relation evidence is immutable')
        require(all(old[k] == new[k] for k in ('id', 'owner_project_id', 'originator_id', 'created_at'))
                and {old['source_project_id'], old['target_project_id']} == {new['source_project_id'], new['target_project_id']},
                'Relation identity is immutable')
        require(new['revision'] == old['revision'] + 1, 'Relation revision must advance by one')
    for id_, new in after.items():
        if id_ not in before and new['schema'] == PROPOSAL:
            require(new['revision'] == 1 and new['originator_id'] == new['updated_by'], 'Invalid first relation revision')


def protect(before_files, after_files, before_entities, after_entities, capability):
    """All generic native writers refuse relation mutations, including import/merge."""
    before, after = records(before_files, before_entities), records(after_files, after_entities)
    controlled = set(before) | set(after)
    changed = before != after or any(before_entities.get(i) != after_entities.get(i) for i in controlled)
    require(not changed or capability is _WRITE, 'Project relations require the authorized native lifecycle')


def conflicts(proposals):
    """Conflicting structural components fail closed, including mixed cycles."""
    bad, keys, graph = set(), {}, {}
    for p in proposals:
        key = (p['type'], p['source_project_id'], p['target_project_id'])
        keys.setdefault(key, []).append(p['id'])
        if p['type'] != 'relates_to':
            graph.setdefault(p['source_project_id'], set()).add(p['target_project_id'])
    for ids in keys.values():
        if len(ids) > 1:
            bad.update(ids)
    def reaches(start, target):
        seen, todo = set(), [start]
        while todo:
            node = todo.pop()
            if node == target:
                return True
            if node not in seen:
                seen.add(node); todo.extend(graph.get(node, ()))
        return False
    for p in proposals:
        if p['type'] != 'relates_to' and reaches(p['target_project_id'], p['source_project_id']):
            bad.add(p['id'])
    # Retain the entire conflicting structural component, never select a winner.
    touched = {p[k] for p in proposals if p['id'] in bad for k in ('source_project_id', 'target_project_id')}
    while True:
        linked = [p for p in proposals if p['type'] != 'relates_to' and
                  touched.intersection((p['source_project_id'], p['target_project_id']))]
        expanded = touched | {p[k] for p in linked for k in ('source_project_id', 'target_project_id')}
        if expanded == touched:
            break
        touched = expanded
    bad.update(p['id'] for p in linked)
    return bad


def reachability(proposals):
    """Topology-only impact; artifact reads and derived authorization belong to C–F."""
    graph = {}
    for p in proposals:
        a, b = p['source_project_id'], p['target_project_id']
        limit = 'data' if p['type'] == 'parent_of' else 'outputs'
        graph.setdefault(a, []).append((b, limit))
        if p['type'] == 'relates_to':
            graph.setdefault(b, []).append((a, limit))
    result = set()
    for start in graph:
        todo, seen = [(start, 'data')], set()
        while todo:
            node, limit = todo.pop()
            if (node, limit) in seen:
                continue
            seen.add((node, limit))
            if node != start:
                result.add((start, node, limit))
            for nxt, edge in graph.get(node, ()):
                todo.append((nxt, 'outputs' if 'outputs' in (limit, edge) else 'data'))
    return result
