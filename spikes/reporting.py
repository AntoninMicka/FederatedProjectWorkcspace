# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Local, user-operated reporting over the registered Workspace writer.

The CLI accepts reviewed JSON, not model output. It has no HTTP endpoint or
external effect. A publication is one idempotent Workspace operation; manual
MON-01 does not create a scheduled ReportRun or advance a scheduler cutoff.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import UUID, uuid5

from spikes.artifacts import Artifacts
from spikes.configuration import committed_project
from spikes.metadata import parse_json, require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.storage import StaleIndex
from spikes.reporting_schema import (SCHEMA, TYPES, PRIVACY, digest, encoded, fields, hex_id,
                                     records, ref, references, validate_record, validate_git, canonical_events)


def operation_uuid(operation_id, label):
    uuid(operation_id)
    return str(uuid5(UUID(operation_id), label))


def pinned(project_id, commit_id, artifact_id, files, entities):
    uuid(project_id); uuid(artifact_id); hex_id(commit_id, True)
    meta = entities.get(artifact_id)
    require(meta is not None and 'file' in meta, 'Pin requires an artifact with sidecar content')
    path = f'artifacts/{artifact_id}/' + meta['file']
    return dict(project_id=project_id, artifact_id=artifact_id, commit_id=commit_id,
                path=path, sha256=digest(files[path]))


class Reporting:
    def __init__(self, node_path):
        self.node_path = node_path
        self.artifacts = Artifacts(node_path)

    def read(self, project_id):
        ws = self.artifacts.workspace(project_id)
        # Explicit local read is a recovery entrypoint, like Artifacts.open.
        ws.recover()
        with ws.journal.lock(), ws.journal.connect() as db:
            head = ws.git.head()
            committed_project(ws.git, head, project_id)
            files = ws.git.snapshot(head)
            entities = validate_snapshot(files)
            ws._read_locked(db, expected_head=head)
            validate_git(ws.git, files, entities)
            result = records(files, entities)
            parents = {p['artifact_id'] for record in result.values() for p in record['previous']}
            if ws.git.head() != head:
                raise StaleIndex('Project changed while reading reporting records')
            return dict(project_id=project_id, commit_id=head, records=list(result.values()),
                        tips=[id_ for id_ in result if id_ not in parents],
                        deduplication={id_: canonical_events(r) for id_, r in result.items()
                                       if r['type'] == 'Story' and id_ not in parents})

    def pin(self, project_id, artifact_id, commit_id=None):
        ws = self.artifacts.workspace(project_id)
        ws.recover()
        with ws.journal.lock(), ws.journal.connect() as db:
            head = ws.git.head()
            committed_project(ws.git, head, project_id)
            ws._read_locked(db, expected_head=head)
            commit = commit_id or head
            hex_id(commit, True)
            committed_project(ws.git, commit, project_id, check_worktree=False)
            files = ws.git.snapshot(commit)
            result = pinned(project_id, commit, artifact_id, files, validate_snapshot(files))
            if ws.git.head() != head:
                raise StaleIndex('Project changed while pinning reporting content')
            return result

    def apply(self, request, operation_id, *, confirm=False, checkpoint=lambda stage: None,
              _assistance=None):
        """Store new revisions; request and approval are frozen by transact's digest.

        IDs for the revision and Markdown sibling derive from operation_id, so
        a lost response never requires the user to guess newly generated IDs.
        Every input revision must already be pinned; staged multi-entity graphs
        are deliberately disallowed (publish definitions before their users).
        """
        fields(request, 'project_id base_head records')
        uuid(request['project_id']); hex_id(request['base_head'], True); uuid(operation_id)
        require(type(confirm) is bool, 'Invalid confirmation flag')
        require(isinstance(request['records'], list) and 1 <= len(request['records']) <= 32,
                'Expected 1 to 32 reporting revisions')
        request = deepcopy(request)
        ws = self.artifacts.workspace(request['project_id'])
        author = ProjectCreation(self.node_path).author_id()
        intent = dict(request, action='manual-reporting-v1', author_id=author, confirmed=confirm)
        assistance = deepcopy(_assistance)
        if assistance is not None:
            require(confirm, 'Explicit confirmation is required for assisted reporting')
            intent['assistance'] = assistance

        def prepare(workspace):
            head = workspace.git.head()
            require(head == request['base_head'], 'Project changed; reload before editing')
            committed_project(workspace.git, head, request['project_id'])
            files = workspace.git.snapshot(head)
            entities = validate_snapshot(files)
            existing = records(files, entities)
            now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            changes = {}
            if assistance is not None:
                # Application-owned audit, never a model-selected path. Exact
                # context projection and instruction survive loss of the backend journal;
                # raw provider responses remain outside the project Git.
                audit_id = operation_uuid(operation_id, 'assistance')
                changes[f'artifacts/{audit_id}/assistance.json'] = encoded(assistance['audit'])
                changes[f'artifacts/{audit_id}/metadata.json'] = encoded(dict(
                    schema_version=1, id=audit_id, title='Reporting — assisted proposal audit',
                    kind='snapshot', created_at=now, author_id=author, privacy=assistance['privacy'],
                    provenance='snapshot', file='assistance.json'))
            for index, spec in enumerate(request['records']):
                require(isinstance(spec, dict) and spec.keys() in (
                    {'type', 'entity_id', 'previous', 'privacy', 'value'},
                    {'type', 'entity_id', 'previous', 'privacy', 'value', 'markdown'}), 'Invalid manual record request')
                require(spec['type'] in TYPES, 'Unknown reporting type')
                id_ = operation_uuid(operation_id, f'record:{index}')
                entity_id = spec['entity_id'] or operation_uuid(operation_id, f'entity:{index}')
                uuid(entity_id)
                value = deepcopy(spec['value'])
                require(isinstance(value, dict), 'Invalid reporting value')
                previous = spec['previous']
                require(isinstance(previous, list), 'Invalid predecessors')
                old_decisions = []
                for parent in previous:
                    ref(parent)
                    before = existing.get(parent['artifact_id'])
                    require(before is not None and before['entity_id'] == entity_id, 'Unknown predecessor')
                    if spec['type'] in {'Event', 'Source'}:
                        value['imported_at'] = before['value']['imported_at']
                    if spec['type'] == 'Story':
                        old_decisions.extend(before['value']['decisions'])
                if not previous and spec['type'] in {'Event', 'Source'}:
                    value['imported_at'] = now
                # Reviews are local human decisions, never identities from JSON.
                def authorize_review(review):
                    require(confirm, 'Explicit --confirm is required for human review/publication')
                    fields(review, 'decision actor_id at policy_revision note')
                    require(review['actor_id'] is None and review['at'] is None,
                            'Manual review identity/time must be null; application supplies them')
                    review.update(actor_id=author, at=now)
                if spec['type'] == 'Story':
                    for decision in value.get('decisions', []):
                        if decision not in old_decisions:
                            authorize_review(decision['review'])
                if spec['type'] == 'EvidenceAssessment' and value.get('review') is not None:
                    authorize_review(value['review'])
                if spec['type'] == 'ReportSnapshot':
                    authorize_review(value['approval'])
                    require(not previous and spec['entity_id'] is None, 'Publication needs a fresh identity')
                    require('markdown' in spec and isinstance(spec['markdown'], str)
                            and '\0' not in spec['markdown'], 'Publication needs reviewed Markdown')
                    markdown = spec['markdown'].encode('utf-8')
                    require(len(markdown) <= 1024 * 1024, 'Markdown exceeds manual reporting limit')
                    md_id = operation_uuid(operation_id, f'markdown:{index}')
                    path = f'artifacts/{md_id}/report.md'
                    require(value.get('markdown') is None, 'Application supplies Markdown reference')
                    value['markdown'] = dict(artifact_id=md_id, path=path, sha256=digest(markdown), at='same-commit')
                    require(value['generation']['mode'] == 'manual' and
                            value['generation']['context_manifest_ref'] is None,
                            'Manual CLI cannot certify assisted provenance')
                    value['generation']['run_id'] = operation_id
                    value['generation']['result_sha256'] = digest(markdown)
                    changes[path] = markdown
                    changes[f'artifacts/{md_id}/metadata.json'] = encoded(dict(
                        schema_version=1, id=md_id, title='Reporting — Markdown', kind='snapshot',
                        created_at=now, author_id=author, privacy=spec['privacy'], provenance='snapshot', file='report.md'))
                else:
                    require('markdown' not in spec, 'Markdown belongs to a publication')
                record = dict(schema=SCHEMA, type=spec['type'], entity_id=entity_id, revision_id=id_,
                              previous=previous, recorded_at=now, recorded_by=author, privacy=spec['privacy'],
                              provenance=dict(method='user', inputs=[], run_refs=[]), value=value)
                # Explicit inputs remain present in value. Include every distinct
                # pinned dependency in provenance, never an application-made guess.
                record['provenance']['inputs'] = list({encoded(r): r for r in references(value)
                                                       if 'commit_id' in r}.values())
                if assistance is not None:
                    require(spec['type'] in {'Event', 'Story', 'EvidenceAssessment'},
                            'Assistance cannot change definitions or publish reports')
                    require(PRIVACY[spec['privacy']] >= PRIVACY[assistance['context_privacy']],
                            'Assisted reporting privacy would be relaxed')
                    record['provenance'] = dict(method='derived',
                        inputs=list({encoded(r): r for r in
                            record['provenance']['inputs'] + assistance['inputs']}.values()),
                        run_refs=[assistance['run_ref']])
                validate_record(record)
                if spec['type'] == 'Story':
                    canonical_events(record)
                require(id_ not in entities, 'Revision ID already exists')
                changes[f'artifacts/{id_}/record.json'] = encoded(record)
                changes[f'artifacts/{id_}/metadata.json'] = encoded(dict(
                    schema_version=1, id=id_, title=value.get('title', spec['type']),
                    kind='snapshot' if spec['type'] == 'ReportSnapshot' else 'document', created_at=now,
                    author_id=author, privacy=spec['privacy'],
                    provenance='llm-transformed' if assistance else 'user', file='record.json', tags=[SCHEMA]))
            return changes, 'Local workspace author', author + '@local.invalid', 'Record manual reporting revisions'

        return ws.transact(operation_id, intent, prepare, expected_head=request['base_head'], checkpoint=checkpoint)


def main():
    parser = argparse.ArgumentParser(description='Ruční reporting nad registrovaným lokálním Workspace')
    parser.add_argument('--node', required=True, help='Lokální konfigurace node.json')
    sub = parser.add_subparsers(dest='command', required=True)
    read = sub.add_parser('list'); read.add_argument('project_id')
    pin = sub.add_parser('pin'); pin.add_argument('project_id'); pin.add_argument('artifact_id')
    pin.add_argument('--commit')
    apply = sub.add_parser('apply'); apply.add_argument('request', type=Path)
    apply.add_argument('--operation-id', required=True)
    apply.add_argument('--confirm', action='store_true', help='Potvrzuji přesný obsah lidského review/vydání')
    args = parser.parse_args()
    service = Reporting(args.node)
    if args.command == 'list':
        result = service.read(args.project_id)
    elif args.command == 'pin':
        result = service.pin(args.project_id, args.artifact_id, args.commit)
    else:
        with args.request.open('rb') as stream:
            request = parse_json(stream.read(2 * 1024 * 1024 + 1), maximum=2 * 1024 * 1024)
        result = service.apply(request, args.operation_id, confirm=args.confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
