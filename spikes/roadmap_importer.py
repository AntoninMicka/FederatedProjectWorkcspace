# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Recoverable, idempotent application of a reviewed roadmap bundle."""
import hashlib
from pathlib import Path

from spikes.configuration import committed_project
from spikes.metadata import require, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.roadmap_bundle import project_files
from spikes.roadmap_migration import canonical
from spikes.roadmap_validation import load_bundle, validate_bundle


def _topology(projects):
    by_operation = {project['operation_id']: project for project in projects}
    require(len(by_operation) == len(projects), 'Duplicate import operation')
    remaining, ordered = set(by_operation), []
    while remaining:
        ready = sorted(operation for operation in remaining
                       if set(by_operation[operation]['depends_on_operations']) <=
                       {item['operation_id'] for item in ordered})
        require(bool(ready), 'Import operation dependency cycle')
        for operation in ready:
            ordered.append(by_operation[operation]); remaining.remove(operation)
    return ordered


class RoadmapImporter:
    def __init__(self, node):
        self.node = Path(node).resolve(strict=True)

    def apply(self, bundle, source_review, expected_bundle_sha256, *, source_roots=(),
              checkpoint=lambda scope, stage: None):
        """Apply reviewed projects in dependency order; replay returns receipts."""
        operation, blobs = load_bundle(bundle)
        require(operation['bundle_sha256'] == expected_bundle_sha256,
                'Explicit bundle confirmation differs')
        review = validate_bundle(bundle, self.node, source_roots=source_roots,
                                 source_review=source_review)
        require(review['prewrite_checks_passed'], 'Complete pre-write review is required')
        receipts = []
        for project in _topology(operation['projects']):
            files = project_files(project, blobs)
            if project['mode'] == 'create-seeded-project':
                proposal = project['project_metadata_proposal']
                request = dict(bundle_sha256=operation['bundle_sha256'], project_id=project['project_id'],
                               target_location=project['target_location'], files=[
                                   {'path': item['path'], 'sha256': item['sha256'], 'action': item['action']}
                                   for item in project['files']])
                request_digest = hashlib.sha256(canonical(request)).hexdigest()
                receipt = ProjectCreation(self.node).create(
                    proposal['title'], project['target_location'], project['operation_id'],
                    initial_files=files, project_id=project['project_id'],
                    created_at=proposal['created_at'], request_digest=request_digest,
                    commit_message='Import reviewed roadmap project',
                    checkpoint=lambda stage, scope=project['repository_id']:
                    checkpoint(scope, stage))
            else:
                require(project['mode'] == 'replace-test-plan' and not project['deletions']
                        and project['preserve_unlisted_entities'], 'Unsupported import mode')
                workspace = Projects(self.node).workspace(project['project_id'])
                request = dict(bundle_sha256=operation['bundle_sha256'],
                               project_id=project['project_id'], files=[
                                   {'path': item['path'], 'sha256': item['sha256'], 'action': item['action']}
                                   for item in project['files']])

                def prepare(active):
                    head = active.git.head()
                    require(head == project['expected_head'], 'Project changed before roadmap import')
                    committed_project(active.git, head, project['project_id'])
                    base = active.git.snapshot(head)
                    for entry in project['files']:
                        path, raw = entry['path'], files[entry['path']]
                        if entry['action'] == 'create':
                            require(path not in base, 'Import create path already exists')
                        else:
                            require(entry['action'] == 'replace' and path in base,
                                    'Import replace path is missing')
                        base[path] = raw
                    validate_snapshot(base)
                    author = operation['prepared_by']
                    return files, 'Local workspace author', author + '@local.invalid', 'Import reviewed project roadmap'

                receipt = workspace.transact(
                    project['operation_id'], request, prepare, expected_head=project['expected_head'],
                    checkpoint=lambda stage, scope=project['repository_id']:
                    checkpoint(scope, stage))
            receipts.append(dict(repository_id=project['repository_id'], project_id=project['project_id'],
                                 operation_id=project['operation_id'], receipt=receipt))
            checkpoint('orchestrator', 'completed:' + project['operation_id'])
        return dict(schema='fpw-roadmap-import-receipt-v1', bundle_sha256=operation['bundle_sha256'],
                    completed=True, projects=receipts,
                    transaction_boundary=operation['transaction_boundary'])
