# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared existing-document actions over ArtifactHistory and Artifacts."""
import hashlib
import json

from spikes.artifact_history import ArtifactHistory
from spikes.artifacts import Artifacts
from spikes.metadata import require
from spikes.projects import Projects
from spikes.metadata import validate_snapshot
from spikes.markdown_documents import document
from spikes.storage import StaleIndex
from spikes.task_graph import project_task_graph


class ArtifactActions:
    def __init__(self, node_path, *, network=False):
        self.history = ArtifactHistory(node_path, network=network)
        self.artifacts = Artifacts(node_path)
        self.projects = Projects(node_path, network=network)

    def open(self, project_id, artifact_id, expected_head):
        result = self.history.compare(project_id, artifact_id, expected_head,
                                      expected_head, expected_head)
        require(result['after'] is not None, 'Document is unavailable')
        return dict(project_id=project_id, artifact_id=artifact_id,
                    commit_id=expected_head, document=result['after'])

    def save(self, request, operation_id):
        # The read validates current network privacy before any web mutation.
        workspace = self.artifacts.workspace(request.get('project_id'))
        if workspace.receipt(operation_id) is None:
            if request.get('new') is True:
                project = self.projects.open(request.get('project_id'))
                require(project['commit_id'] == request.get('base_head'),
                        'Project changed; reopen editor')
            else:
                self.open(request.get('project_id'), request.get('artifact_id'),
                          request.get('base_head'))
        receipt = self.artifacts.save(request, operation_id)
        return dict(project_id=request['project_id'], artifact_id=request['artifact_id'],
                    commit_id=receipt['commit_id'])

    def validate_task_plan(self, project_id, artifact_id, expected_head, body):
        """Validate a one-file draft against the exact committed plan bundle."""
        require(isinstance(body, str) and '\0' not in body, 'Invalid task plan draft')
        project = self.projects.open(project_id)
        if project['commit_id'] != expected_head:
            raise StaleIndex('Project changed; reopen editor')
        workspace = self.artifacts.workspace(project_id)
        with workspace.journal.lock(), workspace.journal.connect() as db:
            require(not workspace._active(db) and
                    not db.execute('SELECT 1 FROM pending').fetchone(),
                    'Project has an unfinished operation')
            workspace._branch()
            head = workspace.git.head()
            if head != expected_head:
                raise StaleIndex('Project changed; reopen editor')
            files = workspace.git.snapshot(head)
            entities = validate_snapshot(files)
            current = document(files, entities, artifact_id)
            files[current['path']] = body.encode('utf-8')
            entities = validate_snapshot(files)
            plan = project_task_graph(files, entities, project_id, head)
            require(plan['status'] == 'ready', plan.get('error', 'Plán není platný.'))
            require(workspace.git.head() == head, 'Project changed while validating plan')
            return {'valid': True, 'revision': plan['revision'],
                    'nodes': len(plan['nodes']), 'profile': plan.get('profile')}

    def deletion_preview(self, project_id, artifact_id, expected_head):
        current = self.open(project_id, artifact_id, expected_head)
        preview = dict(project_id=project_id, artifact_id=artifact_id,
                       base_head=expected_head,
                       title=current['document']['title'])
        digest = hashlib.sha256(json.dumps(preview, ensure_ascii=False, sort_keys=True,
                                           separators=(',', ':')).encode()).hexdigest()
        return dict(preview, preview_sha256=digest)

    def delete(self, project_id, artifact_id, base_head, preview_sha256,
               operation_id):
        workspace = self.artifacts.workspace(project_id)
        if workspace.receipt(operation_id) is None:
            preview = self.deletion_preview(project_id, artifact_id, base_head)
            require(preview['preview_sha256'] == preview_sha256,
                    'Deletion preview changed')
        receipt = self.artifacts.delete(dict(project_id=project_id,
                                             artifact_id=artifact_id,
                                             base_head=base_head), operation_id)
        return dict(project_id=project_id, artifact_id=artifact_id,
                    commit_id=receipt['commit_id'])
