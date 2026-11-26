# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Project relationship UI facade; native lifecycle/resolver remain the authorities."""
from spikes.administration import AccessDenied
from spikes.artifact_preview import preview as present
from spikes.configuration import committed_project
from spikes.context_builder import relation_input_id, relation_content
from spikes.metadata import require
from spikes.project_relation_schema import PROPOSAL
from spikes.reporting_schema import digest, encoded

ROUTES = {
    '/v1/project-relations/overview': {'project_id'},
    '/v1/project-relations/sources': {'project_id', 'query'},
    '/v1/project-relations/source/view': {'project_id', 'source_project_id', 'artifact_id'},
    '/v1/project-relations/source/pin': {'project_id', 'source_project_id', 'artifact_id'},
    '/v1/project-relations/proposal/preview': {'project_id', 'source_project_id', 'target_project_id', 'relation_type', 'reason', 'relation_id'},
    '/v1/project-relations/evidence/preview': {'project_id', 'owner_project_id', 'relation_id', 'operation_id', 'revoke', 'reason'},
    '/v1/project-relations/confirm': {'project_id', 'preview', 'sha256', 'operation_id'},
}


class ProjectRelationsPanel:
    def __init__(self, lifecycle, resolver, *, network=False):
        self.lifecycle, self.resolver, self.network = lifecycle, resolver, network
        self.boundary = 'private-network' if network else 'same-node'

    def _allowed(self, pid, *, manage=False):
        try:
            self.lifecycle._authorize(pid, manage=manage)
            return True
        except AccessDenied:
            return False

    def _title(self, pid, head):
        ws = self.lifecycle.artifacts.workspace(pid)
        with ws.journal.lock(shared=True), ws.journal.connect() as db:
            ws._read_shared(db)
            require(ws.git.head() == head, 'Project changed while reading relationships')
            return committed_project(ws.git, head, pid)['title']

    def overview(self, project_id):
        self.lifecycle._authorize(project_id)
        catalog = self.resolver.catalog(project_id, boundary=self.boundary)
        heads, states = self.lifecycle._scan(); projection = self.lifecycle._projection(states)
        require(catalog['revision'] == digest(encoded(dict(heads=heads, projection=projection))),
                'Project relationships changed; refresh the overview')
        titles = {s['project_id']: s['title'] for s in catalog['sources']}
        direct, managed = set(), set()
        for pid in heads:
            if self._allowed(pid):
                direct.add(pid)
                if pid not in titles: titles[pid] = self._title(pid, heads[pid])
            if self._allowed(pid, manage=True): managed.add(pid)
        rows = []
        for row in projection.values():
            p = row['proposal']; ends = {p['source_project_id'], p['target_project_id']}
            if project_id not in ends: continue
            other = next(iter(ends - {project_id})); visible = other in titles
            readable_both = ends <= direct
            rows.append(dict(relation_id=p['id'], type=p['type'], revision=p['revision'], state=row['state'],
                orientation='symmetric' if p['type'] == 'relates_to' else 'outgoing' if p['source_project_id'] == project_id else 'incoming',
                other_project_id=other if visible else None, other_title=titles.get(other, 'Nedostupný projekt'),
                navigable=other in direct, owner_project_id=p['owner_project_id'] if visible else None,
                source_project_id=p['source_project_id'] if visible else None,
                target_project_id=p['target_project_id'] if visible else None,
                reason=p['reason'] if visible else '', approved=project_id in row['approved_projects'],
                can_edit=ends <= managed, can_approve=(project_id in managed and readable_both
                    and row['state'] == 'pending' and project_id not in row['approved_projects']),
                can_revoke=(project_id in managed and readable_both and row['state'] in {'pending', 'active'})))
        return dict(project_id=project_id, commit_id=heads[project_id],
                    can_create=project_id in managed,
                    candidates=[dict(id=pid, title=titles[pid]) for pid in sorted(managed - {project_id})],
                    relations=sorted(rows, key=lambda r: (r['other_title'], r['relation_id'])))

    def sources(self, project_id, query=''):
        self.lifecycle._authorize(project_id)
        require(isinstance(query, str) and len(query) <= 200 and '\0' not in query, 'Invalid source filter')
        result = self.resolver.catalog(project_id, boundary=self.boundary)
        by_id = {s['project_id']: s for s in result['sources']}
        writable = True
        try: self.lifecycle.references.authorize(project_id, write=True)
        except AccessDenied: writable = False
        rows = []
        for item in result['items']:
            source = by_id[item['source_project_id']]
            if query.casefold() not in (item['title'] + ' ' + source['title']).casefold(): continue
            path = (item.get('source') or {}).get('path', '').casefold()
            text = path.endswith(('.md', '.txt', '.json', '.csv', '.yaml', '.yml', '.py', '.c', '.cpp', '.h', '.sh', '.html', '.svg'))
            rows.append(dict(item, source_title=source['title'],
                             reason='Vlastní data' if not item['inherited'] else
                                    'Data podprojektu' if 'data' in item['scopes'] else 'Publikovaný výstup',
                             can_select=writable and item['available'] and text))
        return dict(result, items=rows, filter_kind='titles-and-projects', can_use=writable)

    def _read(self, project_id, source_project_id, artifact_id):
        self.lifecycle._authorize(project_id)
        pin = self.resolver.pin(project_id, source_project_id, artifact_id, boundary=self.boundary)
        resolved = self.resolver.read(pin, boundary=self.boundary)
        return pin, resolved

    def source_pin(self, project_id, source_project_id, artifact_id):
        self.lifecycle.references.authorize(project_id, write=True)
        pin, resolved = self._read(project_id, source_project_id, artifact_id)
        _, citation = relation_content(resolved)
        return dict(input_id=relation_input_id(pin), pin=pin, title=resolved['metadata']['title'], citation=citation)

    def source_view(self, project_id, source_project_id, artifact_id):
        pin, resolved = self._read(project_id, source_project_id, artifact_id)
        source = pin['source']
        presentation = present(dict(raw=resolved['raw'], path=source['path'], metadata=resolved['metadata'],
                                    sidecar='file' in resolved['metadata']))
        return dict(pin=pin, title=resolved['metadata']['title'], privacy=resolved['privacy'],
                    inherited=resolved['inherited'], read_only=True, preview=presentation)

    def proposal_preview(self, project_id, source_project_id, target_project_id, relation_type, reason, relation_id=None):
        self.lifecycle._authorize(project_id)
        require(project_id in {source_project_id, target_project_id}, 'Relation must include this project')
        return self._display(self.lifecycle.proposal_preview(source_project_id, target_project_id, relation_type, reason, relation_id=relation_id))

    def evidence_preview(self, project_id, owner_project_id, relation_id, operation_id, revoke=False, reason=None):
        require(type(revoke) is bool, 'Invalid relation action')
        return self._display(self.lifecycle.evidence_preview(owner_project_id, relation_id, project_id, operation_id, revoke=revoke, reason=reason))

    def _display(self, envelope):
        return dict(envelope, display=dict(titles={pid: self._title(pid, head)
                    for pid, head in envelope['preview']['heads'].items()}))

    def confirm(self, project_id, preview, sha256, operation_id):
        self.lifecycle._authorize(project_id)
        require(isinstance(preview, dict) and isinstance(preview.get('record'), dict), 'Invalid relation preview')
        record = preview['record']
        if record.get('schema') == PROPOSAL:
            require(project_id in {record.get('source_project_id'), record.get('target_project_id')}, 'Wrong relation context')
        else:
            require(preview.get('project_id') == project_id, 'Approve only this project endpoint')
        return self.lifecycle.confirm(preview, sha256, operation_id, confirm=True)
