# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit, HEAD/digest-bound resolution of one tracked local artifact edit."""
from uuid import UUID, uuid5

from spikes.artifact_git import ArtifactGit, canonical, digest
from spikes.conflict_resolution import ConflictResolution
from spikes.journal import snapshot
from spikes.metadata import require, safe_path, uuid, validate_snapshot
from spikes.reporting_schema import validate_git
from spikes.working_file import read_working_file


class _ConflictFileWriter(ArtifactGit):
    """Private engine for the explicit conflict workflow, not generic web Stage."""
    def workspace(self, pid):
        ws = self.projects.workspace(pid, blocking=False)
        ws._writable()
        return ws


class LocalChangeResolution(ConflictResolution):
    def _writer(self):
        return _ConflictFileWriter(self.node_path, network=self.network)

    def _local_plan(self, ws, project_id, expected_head, path, choice, *, reviewed_stage=False):
        require(isinstance(choice, str) and choice in {'keep', 'restore'}, 'Unknown local change decision')
        parts = safe_path(path)
        require(len(parts) == 3 and parts[0] == 'artifacts' and parts[2] != 'metadata.json',
                'Only tracked artifact content can be resolved here')
        uuid(parts[1]); writer = self._writer()
        files, base_entities, selected, meta = writer.current(ws, project_id, parts[1], expected_head)
        require(not self.network or all(m['privacy'] != 'local-only' for m in base_entities.values()),
                'Project contains local-only data')
        require(path == selected and path in files, 'Path is not the tracked artifact content')
        require(writer.metadata_unchanged(ws, path, files), 'Review changed artifact metadata first')
        staged = writer.staged(ws, path)
        raw = staged if reviewed_stage else read_working_file(ws.git.root, path)
        require(raw != files[path], 'Selected working file has no local change')
        if not reviewed_stage:
            require(staged == files[path] or (choice == 'keep' and staged == raw),
                    'Resolve the different staged version first')
        native = None
        if choice == 'keep':
            native, _ = writer._preview(ws, project_id, parts[1], expected_head, _working=raw)
        else:
            candidate = snapshot(ws.git.root); candidate[path] = files[path]
            entities = validate_snapshot(candidate)
            require(not self.network or all(m['privacy'] != 'local-only' for m in entities.values()),
                    'Project contains local-only data')
            validate_git(ws.git, candidate, entities, files, head=expected_head)
        value = dict(schema='fpw-local-change-resolution-v1', project_id=project_id,
            expected_head=expected_head, branch=ws._branch(), path=path, artifact_id=parts[1],
            title=meta['title'], choice=choice, working_sha256=digest(raw),
            head_sha256=digest(files[path]), bytes=len(raw), commit_preview=native)
        return value, raw, files[path]

    def local_preview(self, project_id, expected_head, path, choice):
        with self._read(project_id, expected_head) as (ws, _):
            value, _, _ = self._local_plan(ws, project_id, expected_head, path, choice)
            return {'preview': value, 'approval_digest': digest(canonical(value))}

    def local_confirm(self, preview, approval_digest, operation_id, message, *, confirm=False,
                      checkpoint=lambda stage: None):
        require(confirm is True, 'Explicit local change confirmation required')
        require(isinstance(preview, dict) and set(preview) == {
            'schema', 'project_id', 'expected_head', 'branch', 'path', 'artifact_id',
            'title', 'choice', 'working_sha256', 'head_sha256', 'bytes', 'commit_preview'}
            and preview['schema'] == 'fpw-local-change-resolution-v1', 'Invalid local resolution preview')
        require(digest(canonical(preview)) == approval_digest, 'Local resolution preview digest differs')
        uuid(operation_id); uuid(preview['project_id']); uuid(preview['artifact_id'])
        require(isinstance(message, str) and 0 < len(message.strip()) <= 1000 and '\0' not in message,
                'Resolution message required')
        writer = self._writer(); ws = writer.workspace(preview['project_id'])
        intent_digest = digest(canonical(dict(preview=preview, approval_digest=approval_digest, message=message)))
        if preview['choice'] == 'restore':
            request = dict(preview=preview, approval_digest=approval_digest, message=message)
            def prepare(workspace):
                current, before, after = self._local_plan(workspace, preview['project_id'],
                    preview['expected_head'], preview['path'], 'restore')
                require(current == preview, 'Working file changed; review again')
                return preview['path'], before, after, preview['expected_head']
            receipt = ws.restore_working_artifact(operation_id, request, prepare, checkpoint=checkpoint)
            return dict(operation_id=operation_id, commit_id=receipt['commit_id'],
                        choice='restore', backup_operation_id=operation_id)
        require(preview['choice'] == 'keep' and isinstance(preview['commit_preview'], dict),
                'Invalid local keep decision')
        native = preview['commit_preview']
        require(all(native.get(left) == preview[right] for left, right in [
            ('project_id', 'project_id'), ('artifact_id', 'artifact_id'), ('base_head', 'expected_head'),
            ('path', 'path'), ('head_sha256', 'head_sha256'), ('staged_sha256', 'working_sha256'),
            ('bytes', 'bytes'), ('title', 'title')]), 'Native commit differs from conflict decision')
        stage_id = str(uuid5(UUID(operation_id), 'local-conflict-stage'))
        with ws.journal.lock(), ws.journal.connect() as db:
            existing = db.execute('SELECT 1 FROM operations WHERE id=?', (operation_id,)).fetchone()
            staged = db.execute('SELECT 1 FROM operations WHERE id=?', (stage_id,)).fetchone()
            if not existing and not staged:
                current, _, _ = self._local_plan(ws, preview['project_id'],
                    preview['expected_head'], preview['path'], 'keep')
                require(current == preview, 'Working file changed; review again')
        if not existing:
            writer.stage(dict(project_id=preview['project_id'], artifact_id=preview['artifact_id'],
                base_head=preview['expected_head'], working_sha256=preview['working_sha256']),
                stage_id, checkpoint=checkpoint, _context_digest=intent_digest)
        def validate_context(workspace):
            current, _, _ = self._local_plan(workspace, preview['project_id'],
                preview['expected_head'], preview['path'], 'keep', reviewed_stage=True)
            require(current == preview, 'Staged conflict decision changed; review again')
        receipt = writer.commit(preview['commit_preview'], digest(canonical(preview['commit_preview'])),
            message, operation_id, confirm=True, checkpoint=checkpoint,
            _context_digest=intent_digest, _validate_context=validate_context)
        return dict(operation_id=operation_id, commit_id=receipt['commit_id'], choice='keep')
