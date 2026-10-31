# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Reviewed three-way source updates through the native Workspace transaction.

The caller supplies the reviewed, stable-identity candidate, not arbitrary LLM
output. This same-node service neither scans sources nor resolves conflicts.
"""
import base64
import re
from pathlib import Path

from spikes.configuration import committed_project
from spikes.metadata import MAX_FILE, MAX_SNAPSHOT, require, safe_path, uuid, validate_transition
from spikes.projects import Projects
from spikes.roadmap_bundle import digest
from spikes.roadmap_migration import canonical
from spikes.roadmap_validation import _actor
from spikes.storage import Git
from spikes.task_graph import project_task_graph


def _commit(value):
    require(isinstance(value, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', value),
            'Expected full pinned commit ID')


def _path(value):
    parts = safe_path(value)
    require(len(parts) == 3 and parts[0] == 'artifacts', 'Expected managed artifact path')
    uuid(parts[1])
    return value


def _bytes(value):
    return None if value is None else base64.b64encode(value).decode('ascii')


class RoadmapSourceUpdate:
    def __init__(self, node):
        self.node = Path(node).resolve(strict=True)

    @staticmethod
    def _request(project_id, baseline_commit, expected_head, source_root,
                 source_revision, managed_paths, incoming_files, decisions):
        uuid(project_id)
        for commit in (baseline_commit, expected_head, source_revision):
            _commit(commit)
        require(isinstance(managed_paths, (list, tuple)) and managed_paths
                and all(isinstance(path, str) for path in managed_paths)
                and len(managed_paths) == len(set(managed_paths)), 'Invalid managed paths')
        require(isinstance(incoming_files, dict) and isinstance(decisions, dict),
                'Expected candidate files and explicit decisions')
        require(len(set(managed_paths) | set(incoming_files)) <= 10000,
                'Update exceeds file limit')
        for path in set(managed_paths) | set(incoming_files):
            _path(path)
        require(all(isinstance(raw, bytes) and len(raw) <= MAX_FILE
                    for raw in incoming_files.values())
                and sum(map(len, incoming_files.values())) <= MAX_SNAPSHOT,
                'Update exceeds byte limits')
        require(all(path in set(managed_paths) | set(incoming_files)
                    and choice in {'keep', 'source'} for path, choice in decisions.items()),
                'Invalid source review decision')
        return dict(schema='fpw-roadmap-source-update-v1', project_id=project_id,
                    baseline_commit=baseline_commit, expected_head=expected_head,
                    source_root=str(Path(source_root).resolve(strict=True)),
                    source_revision=source_revision, managed_paths=sorted(managed_paths),
                    incoming_files={path: _bytes(raw) for path, raw in sorted(incoming_files.items())},
                    decisions=dict(sorted(decisions.items())))

    def _preview(self, git, request):
        require(git.head() == request['expected_head'], 'Project changed before source update')
        committed_project(git, request['expected_head'], request['project_id'])
        require(git.run('merge-base', '--is-ancestor', request['baseline_commit'],
                        request['expected_head'], check=False).returncode == 0,
                'Import baseline is not an ancestor of current HEAD')
        source = Git(request['source_root'])
        require(source.run('rev-parse', '--verify', request['source_revision'] + '^{commit}').stdout.strip()
                == request['source_revision'], 'Source commit differs')
        baseline = git.snapshot(request['baseline_commit'])
        current = git.snapshot(request['expected_head'])
        managed = set(request['managed_paths'])
        require(managed <= baseline.keys(), 'Managed baseline path is missing')
        ids = {path.split('/')[1] for path in managed}
        require({path for path in baseline if path.startswith('artifacts/')
                 and path.split('/')[1] in ids} == managed,
                'Managed baseline must include complete artifacts')
        incoming = {path: base64.b64decode(raw) for path, raw in request['incoming_files'].items()}
        candidate, rows, unresolved = dict(current), [], []
        for path in sorted(managed | incoming.keys()):
            before = baseline.get(path) if path in managed else None
            local, proposed = current.get(path), incoming.get(path)
            removed = path in managed and path not in incoming
            conflict = proposed != before and local != before and local != proposed
            choice = request['decisions'].get(path)
            if (removed or conflict) and choice is None:
                unresolved.append(path)
            after = (local if choice == 'keep' or (choice is None and proposed == before)
                     else proposed)
            if after is None:
                candidate.pop(path, None)
            else:
                candidate[path] = after
            rows.append(dict(path=path, baseline=_bytes(before), current=_bytes(local),
                             incoming=_bytes(proposed), result=_bytes(after), removed=removed,
                             conflict=conflict, decision=choice,
                             changed=local != after))
        error = None
        try:
            entities = validate_transition(current, candidate)
            # The project configuration and task graph are validated together,
            # with all unlisted live artifacts retained in the candidate.
            graph = project_task_graph(candidate, entities, request['project_id'], request['expected_head'])
            require(graph['status'] == 'ready', graph.get('error', 'Invalid merged task graph'))
        except ValueError as exc:
            error = str(exc)
        require(git.head() == request['expected_head'], 'Project changed during source update preview')
        report = dict(schema='fpw-roadmap-source-update-preview-v1', request=request,
                      rows=rows, unresolved=unresolved, validation_error=error,
                      ready=not unresolved and error is None and any(row['changed'] for row in rows))
        report['preview_sha256'] = digest(canonical(report))
        changes = {path: candidate.get(path) for path in managed | incoming.keys()
                   if candidate.get(path) != current.get(path)}
        return report, changes

    def preview(self, project_id, baseline_commit, expected_head, source_root,
                source_revision, managed_paths, incoming_files, *, decisions=None):
        request = self._request(project_id, baseline_commit, expected_head, source_root,
                                source_revision, managed_paths, incoming_files,
                                {} if decisions is None else decisions)
        return self._preview(Projects(self.node).repository(project_id), request)[0]

    def apply(self, project_id, baseline_commit, expected_head, source_root,
              source_revision, managed_paths, incoming_files, operation_id,
              expected_preview_sha256, *, decisions=None, checkpoint=lambda stage: None):
        request = self._request(project_id, baseline_commit, expected_head, source_root,
                                source_revision, managed_paths, incoming_files,
                                {} if decisions is None else decisions)
        require(isinstance(expected_preview_sha256, str)
                and re.fullmatch(r'[0-9a-f]{64}', expected_preview_sha256),
                'Explicit source update preview confirmation required')
        author = _actor(self.node)
        workspace = Projects(self.node).workspace(project_id)

        def prepare(active):
            report, changes = self._preview(active.git, request)
            require(report['preview_sha256'] == expected_preview_sha256,
                    'Source update preview confirmation differs')
            require(report['ready'], 'Resolve source update review before applying')
            return changes, 'Local workspace author', author + '@local.invalid', 'Update reviewed roadmap source'

        return workspace.transact(operation_id,
            dict(update=request, preview_sha256=expected_preview_sha256), prepare,
            expected_head=expected_head, checkpoint=checkpoint)
