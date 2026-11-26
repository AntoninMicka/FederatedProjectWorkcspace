# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only hierarchy projection over native relation evidence (PROJECT-RELATIONS-01-C).

No source copies, persistent cache, memberships, writes or provider dispatch.
Output-only relationships are deliberately outside this slice's coverage.
"""
from collections import deque

from spikes.administration import AccessDenied
from spikes.configuration import committed_project
from spikes.context_builder import BOUNDARIES
from spikes.cross_references import ReferenceUnavailable
from spikes.metadata import STATES, require, safe_path, uuid, validate_snapshot
from spikes.project_relations import ProjectRelations
from spikes.project_relation_schema import APPROVAL, evidence_id
from spikes.reference_schema import SHARE, references, _version
from spikes.reporting_schema import PRIVACY, digest, encoded, fields, hex_id
from spikes.workspace import PendingOperation

SCHEMA = 'fpw-project-relation-input-v1'
MAX_DEPTH = 16
MAX_PATHS = 1024
MAX_ITEMS = 10000
MAX_CATALOG_BYTES = 8 * 1024 * 1024


class RelationViewUnavailable(ReferenceUnavailable):
    """Bounded, content-free reason; never include inaccessible project names."""


class ProjectRelationResolver:
    def __init__(self, node_path, *, user_id=None, allowed_projects=None):
        self.relations = ProjectRelations(node_path, user_id=user_id, allowed_projects=allowed_projects)
        self.references = self.relations.references
        self.user_id = self.references.user_id

    def _source_in_scope(self, project_id):
        scope = self.references.allowed_projects
        return scope is None or project_id in scope

    def _context(self, recipient):
        access = self.relations._authorize(recipient)
        try:
            heads, states = self.relations._scan()
            projection = self.relations._projection(states)
        except (ValueError, OSError, PendingOperation):
            raise RelationViewUnavailable('graph-unavailable') from None
        # Only a registered, authorized recipient can start a derived path.
        if recipient not in heads:
            raise RelationViewUnavailable('graph-unavailable')
        return dict(recipient=recipient, access=access, heads=heads, states=states, projection=projection,
                    revision=digest(encoded(dict(heads=heads, projection=projection))))

    def _finish(self, context):
        fresh = self._context(context['recipient'])
        if fresh['access'] != context['access'] or fresh['revision'] != context['revision']:
            raise RelationViewUnavailable('snapshot-changed')

    @staticmethod
    def _proof(row, context):
        p = row['proposal']; states, heads = context['states'], context['heads']
        approvals = []
        for pid in sorted((p['source_project_id'], p['target_project_id'])):
            id_ = evidence_id(p['id'], p['revision'], pid, 'approval')
            record = states[pid]['records'][id_]
            require(record['schema'] == APPROVAL, 'Invalid native relation approval')
            approvals.append(dict(project_id=pid, artifact_id=id_, commit_id=heads[pid],
                                  sha256=digest(encoded(record))))
        return dict(relation_id=p['id'], owner_project_id=p['owner_project_id'], revision=p['revision'],
                    proposal_sha256=digest(encoded(p)), proposal_commit=heads[p['owner_project_id']],
                    source_project_id=p['source_project_id'], target_project_id=p['target_project_id'],
                    type=p['type'], policy=p['policy'], approvals=approvals)

    def _paths(self, context):
        graph = {}
        for row in context['projection'].values():
            p = row['proposal']
            if row['state'] == 'active' and p['type'] == 'parent_of':
                graph.setdefault(p['source_project_id'], []).append(row)
        for rows in graph.values():
            rows.sort(key=lambda r: r['proposal']['id'])
        root = context['recipient']
        paths, todo, count = {root: [[]]}, deque([(root, [], (root,))]), 1
        while todo:
            pid, path, visited = todo.popleft()
            for row in graph.get(pid, ()):
                target = row['proposal']['target_project_id']
                if not self._source_in_scope(target):
                    continue  # No count, name or existence of the excluded subtree leaks.
                if target in visited or len(path) >= MAX_DEPTH or count >= MAX_PATHS:
                    raise RelationViewUnavailable('coverage-limit')
                next_path = path + [self._proof(row, context)]
                paths.setdefault(target, []).append(next_path)
                todo.append((target, next_path, visited + (target,))); count += 1
        return paths

    def _snapshot(self, project_id, head, *, historical=False):
        try:
            ws = self.references.artifacts.workspace(project_id)
            ws.repair_index()
            with ws.journal.lock(shared=True), ws.journal.connect() as db:
                ws._read_shared(db)
                current = ws.git.head()
                committed_project(ws.git, current, project_id)
                if historical:
                    hex_id(head, True)
                    if ws.git.run('merge-base', '--is-ancestor', head, current, check=False).returncode:
                        raise RelationViewUnavailable('invalid-pin')
                    meta = committed_project(ws.git, head, project_id, check_worktree=False)
                else:
                    if current != head:
                        raise RelationViewUnavailable('snapshot-changed')
                    meta = committed_project(ws.git, head, project_id)
                files = ws.git.snapshot(head); entities = validate_snapshot(files)
                if ws.git.head() != current:
                    raise RelationViewUnavailable('snapshot-changed')
                return meta, files, entities
        except RelationViewUnavailable:
            raise
        except (ValueError, OSError, PendingOperation):
            raise RelationViewUnavailable('source-unavailable') from None

    @staticmethod
    def _controlled(meta):
        return SHARE in meta.get('tags', ()) or any(
            t.startswith('fpw-project-relation-') for t in meta.get('tags', ()))

    @staticmethod
    def _content(files, entities, id_, reference_ids=None):
        meta = entities.get(id_)
        if meta is None or ProjectRelationResolver._controlled(meta):
            raise RelationViewUnavailable('artifact-unavailable')
        if id_ in (reference_ids if reference_ids is not None else references(files, entities)):
            # A stored pointer cannot extend the hierarchy grant to a third project.
            raise RelationViewUnavailable('xref-resolution-required')
        prefix = f'artifacts/{id_}/'
        paths = [p for p in files if p.startswith(prefix) and not p.endswith('/metadata.json')]
        if not paths:
            paths = [p for p in files if p.startswith('registries/') and p.endswith('/' + id_ + '.json')]
        require(len(paths) == 1, 'Project entity has no unique content')
        return paths[0], files[paths[0]], meta

    @staticmethod
    def _source(project_id, head, path, raw, metadata):
        return dict(project_id=project_id, repository='fpw-project-git:' + project_id,
                    artifact_id=metadata['id'], commit_id=head, path=path, sha256=digest(raw),
                    metadata_sha256=digest(encoded(metadata)), privacy=metadata['privacy'])

    @staticmethod
    def _validate_source(value):
        fields(value, 'project_id repository artifact_id commit_id path sha256 metadata_sha256 privacy')
        uuid(value['project_id']); uuid(value['artifact_id']); hex_id(value['commit_id'], True)
        hex_id(value['sha256']); hex_id(value['metadata_sha256'])
        require(value['repository'] == 'fpw-project-git:' + value['project_id'], 'Invalid source repository')
        parts = safe_path(value['path'])
        require(len(parts) == 3 and ((parts[:2] == ['artifacts', value['artifact_id']] and parts[2] != 'metadata.json')
                or (parts[0] == 'registries' and parts[1] in STATES and parts[2] == value['artifact_id'] + '.json')),
                'Invalid project entity path')
        require(isinstance(value['privacy'], str) and value['privacy'] in PRIVACY, 'Invalid source privacy')

    @staticmethod
    def _boundary(boundary, privacy):
        require(boundary in BOUNDARIES, 'Invalid execution boundary')
        if privacy == 'local-only' and boundary != 'same-node':
            raise RelationViewUnavailable('privacy-boundary')

    def catalog(self, project_id, *, boundary='same-node'):
        """Own and inherited entities, deduplicated by project/artifact/commit."""
        context = self._context(project_id); self._boundary(boundary, 'project')
        paths = self._paths(context); items, sources = [], []
        for pid in sorted(paths):
            head = context['heads'][pid]
            project, files, entities = self._snapshot(pid, head)
            source_row = dict(project_id=pid, title=project['title'], commit_id=head,
                              inherited=pid != project_id, paths=paths[pid])
            sources.append(source_row)
            refs = references(files, entities)
            for id_, meta in sorted(entities.items()):
                if self._controlled(meta) or (meta['privacy'] == 'local-only' and boundary != 'same-node'):
                    continue
                row = dict(artifact_id=id_, source_project_id=pid, commit_id=head, title=meta['title'],
                           kind=meta['kind'], privacy=meta['privacy'], inherited=pid != project_id,
                           read_only=True, available=id_ not in refs)
                if id_ in refs:
                    row.update(source=None, reason='xref-resolution-required')
                else:
                    path, raw, metadata = self._content(files, entities, id_, refs)
                    row['source'] = self._source(pid, head, path, raw, metadata)
                items.append(row)
                if len(items) > MAX_ITEMS:
                    raise RelationViewUnavailable('coverage-limit')
        result = dict(project_id=project_id, commit_id=context['heads'][project_id], revision=context['revision'],
                      sources=sources, items=items, complete=True, coverage=['own', 'parent_of'],
                      boundary=boundary, privacy_filtered=boundary != 'same-node')
        if len(encoded(result)) > MAX_CATALOG_BYTES:
            raise RelationViewUnavailable('coverage-limit')
        self._finish(context)
        return result

    def pin(self, project_id, source_project_id, artifact_id, *, relation_ids=None, boundary='same-node'):
        """Pin current own/inherited bytes and exactly one explicit authorization path."""
        context = self._context(project_id); uuid(source_project_id); uuid(artifact_id)
        paths = self._paths(context).get(source_project_id, ())
        if relation_ids is not None:
            require(isinstance(relation_ids, (list, tuple)), 'Invalid relation path selection')
            paths = [p for p in paths if [e['relation_id'] for e in p] == list(relation_ids)]
        if not paths:
            raise RelationViewUnavailable('not-authorized')
        path = paths[0]
        head = context['heads'][source_project_id]
        _, files, entities = self._snapshot(source_project_id, head)
        name, raw, meta = self._content(files, entities, artifact_id)
        self._boundary(boundary, meta['privacy'])
        value = dict(schema=SCHEMA, recipient_project_id=project_id,
                     source=self._source(source_project_id, head, name, raw, meta),
                     authorization=dict(kind='project-relation' if path else 'project', scope='data',
                                        recipient_access_revision=context['access'], path=path))
        self._finish(context)
        return value

    def _verify_path(self, authorization, source_project_id, context):
        fields(authorization, 'kind scope recipient_access_revision path')
        require(authorization['scope'] == 'data', 'Unsupported relation input scope')
        if authorization['recipient_access_revision'] != context['access']:
            raise RelationViewUnavailable('authority-changed')
        path = authorization['path']; pid = context['recipient']; seen = {pid}
        require(isinstance(path, list) and len(path) <= MAX_DEPTH, 'Invalid pinned relation path')
        require(authorization['kind'] == ('project-relation' if path else 'project'), 'Invalid authorization kind')
        for edge in path:
            require(isinstance(edge, dict), 'Invalid relation proof')
            uuid(edge.get('relation_id'))
            row = context['projection'].get(edge.get('relation_id'))
            if not row or row['state'] != 'active' or row['proposal']['type'] != 'parent_of':
                raise RelationViewUnavailable('relation-unavailable')
            expected = self._proof(row, context)
            require(set(edge) == set(expected), 'Invalid relation proof fields')
            normalized = dict(edge, proposal_commit=expected['proposal_commit'], approvals=[])
            require(isinstance(edge['approvals'], list) and len(edge['approvals']) == 2, 'Invalid approval proof')
            for approval, current in zip(edge['approvals'], expected['approvals']):
                fields(approval, 'project_id artifact_id commit_id sha256')
                normalized['approvals'].append(dict(approval, commit_id=current['commit_id']))
                _, files, _ = self._snapshot(current['project_id'], approval['commit_id'], historical=True)
                if digest(files.get(f"artifacts/{current['artifact_id']}/relation.json", b'')) != current['sha256']:
                    raise RelationViewUnavailable('invalid-pin')
            require(normalized == expected, 'Pinned relation revision/proof differs')
            _, owner_files, _ = self._snapshot(expected['owner_project_id'], edge['proposal_commit'], historical=True)
            if digest(owner_files.get(f"artifacts/{expected['relation_id']}/relation.json", b'')) != expected['proposal_sha256']:
                raise RelationViewUnavailable('invalid-pin')
            target = expected['target_project_id']
            if expected['source_project_id'] != pid or target in seen or not self._source_in_scope(target):
                raise RelationViewUnavailable('not-authorized')
            pid = target; seen.add(pid)
        if pid != source_project_id or not self._source_in_scope(source_project_id):
            raise RelationViewUnavailable('not-authorized')

    def read(self, pin, *, boundary='same-node'):
        """Read pinned bytes after live reauthorization; never repin or switch paths."""
        fields(pin, 'schema recipient_project_id source authorization')
        _version(pin['schema'], 'fpw-project-relation-input-', (1,), 'project-relation-input')
        context = self._context(pin['recipient_project_id'])
        self._validate_source(pin['source']); source = pin['source']; pid = source['project_id']
        self._verify_path(pin['authorization'], pid, context)
        head = context['heads'][pid]
        _, current_files, current_entities = self._snapshot(pid, head)
        current_path, current_raw, current_meta = self._content(current_files, current_entities, source['artifact_id'])
        _, files, entities = self._snapshot(pid, source['commit_id'], historical=True)
        path, raw, meta = self._content(files, entities, source['artifact_id'])
        require(self._source(pid, source['commit_id'], path, raw, meta) == source, 'Pinned source differs')
        privacy = max(source['privacy'], current_meta['privacy'], key=PRIVACY.get)
        self._boundary(boundary, privacy)
        latest = self._source(pid, head, current_path, current_raw, current_meta)
        changed = any(latest[k] != source[k] for k in ('path', 'sha256', 'metadata_sha256'))
        result = dict(raw=raw, metadata=meta, privacy=privacy, source=source, source_head=head,
                      authorization=pin['authorization'], newer=latest if changed else None,
                      read_only=True, inherited=pid != context['recipient'])
        self._finish(context)
        return result
