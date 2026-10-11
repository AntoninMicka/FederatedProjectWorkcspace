# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared existing-document actions over ArtifactHistory and Artifacts."""
import hashlib
import json

from spikes.artifact_history import ArtifactHistory
from spikes.artifacts import Artifacts
from spikes.metadata import require


class ArtifactActions:
    def __init__(self, node_path, *, network=False):
        self.history = ArtifactHistory(node_path, network=network)
        self.artifacts = Artifacts(node_path)

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
            self.open(request.get('project_id'), request.get('artifact_id'),
                      request.get('base_head'))
        receipt = self.artifacts.save(request, operation_id)
        return dict(project_id=request['project_id'], artifact_id=request['artifact_id'],
                    commit_id=receipt['commit_id'])

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
