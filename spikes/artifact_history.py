# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Read-only, HEAD-bound document history over registered project Git objects."""
from contextlib import contextmanager
import json
import re

from spikes.artifacts import Artifacts
from spikes.configuration import committed_project
from spikes.markdown_documents import document
from spikes.metadata import MAX_METADATA, ValidationError, require, uuid, validate_snapshot
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation

MAX_VERSIONS = 100


def commit_id(value):
    require(isinstance(value, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value),
            'Expected full commit ID')


class ArtifactHistory:
    def __init__(self, node_path, *, timeout=60):
        self.artifacts = Artifacts(node_path, timeout=timeout)

    @contextmanager
    def _read(self, project_id, artifact_id, expected_head):
        uuid(project_id); uuid(artifact_id); commit_id(expected_head)
        ws = self.artifacts.workspace(project_id)
        with ws.journal.lock(), ws.journal.connect() as db:
            if ws._active(db) or db.execute('SELECT 1 FROM pending').fetchone():
                raise PendingOperation('Projekt má nedokončenou operaci. Historie ji neobnovuje.')
            ws._branch()
            head = ws.git.head()
            if head != expected_head:
                raise StaleIndex('Projekt se změnil. Znovu načtěte editor a historii.')
            require(not ws.git.run('ls-files', '-u').stdout, 'Unresolved merge')
            committed_project(ws.git, head, project_id)
            files = ws.git.snapshot(head)
            entities = validate_snapshot(files)
            require(any(p.startswith(f'artifacts/{artifact_id}/') for p in files), 'Artifact is not in current project')
            document(files, entities, artifact_id)
            yield ws.git
            if ws.git.head() != head:
                raise StaleIndex('Projekt se během čtení změnil. Znovu načtěte historii.')

    def _version(self, git, project_id, artifact_id, revision):
        commit_id(revision)
        committed_project(git, revision, project_id, check_worktree=False)
        files = git.snapshot(revision)
        entities = validate_snapshot(files)
        if not any(p.startswith(f'artifacts/{artifact_id}/') for p in files):
            return None
        doc = document(files, entities, artifact_id)
        return dict(title=doc['title'], body=doc['body'], metadata=doc['metadata'])

    def list(self, project_id, artifact_id, expected_head):
        with self._read(project_id, artifact_id, expected_head) as git:
            commits = git.run('rev-list', '--full-history', '--topo-order',
                              f'--max-count={MAX_VERSIONS + 1}', expected_head, '--',
                              f'artifacts/{artifact_id}/').stdout.splitlines()
            rows = []
            for revision in commits[:MAX_VERSIONS]:
                commit_id(revision)
                require(int(git.run('cat-file', '-s', revision).stdout) <= MAX_METADATA,
                        'Commit metadata exceeds 64 KiB')
                info = git.run('show', '-s', '--format=%aI%x00%an%x00%ae%x00%B', revision).stdout
                date, author, email, message = info.split('\0', 3)
                row = dict(commit_id=revision, date=date, author=author, email=email,
                           message=message.rstrip('\n'), available=True, deleted=False)
                try:
                    row['deleted'] = self._version(git, project_id, artifact_id, revision) is None
                except (ValidationError, UnicodeError):
                    row['available'] = False
                rows.append(row)
            return dict(head=expected_head, versions=rows, truncated=len(commits) > MAX_VERSIONS)

    def compare(self, project_id, artifact_id, expected_head, older, newer):
        commit_id(older); commit_id(newer)
        with self._read(project_id, artifact_id, expected_head) as git:
            for revision in {older, newer}:
                resolved = git.run('rev-parse', '--verify', revision + '^{commit}').stdout.strip()
                require(resolved == revision, 'Expected commit object')
                require(git.run('merge-base', '--is-ancestor', revision, expected_head, check=False).returncode == 0,
                        'Revision is not reachable from the current project HEAD')
            before = self._version(git, project_id, artifact_id, older)
            after = self._version(git, project_id, artifact_id, newer)
            diff = git.run('diff', '--text', '--no-ext-diff', '--no-textconv', '--no-color', '--no-renames',
                           '--no-relative', older, newer, '--', f'artifacts/{artifact_id}/').stdout
            return dict(older=older, newer=newer, before=before, after=after, diff=diff)


def metadata_text(version):
    return json.dumps(version['metadata'], ensure_ascii=False, sort_keys=True, indent=2) if version else ''
