# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native local project-relation lifecycle (PROJECT-RELATIONS-01-B).

One writer/journal per project, no distributed commit and no foreign content
reads. Synced evidence without local native authority remains unavailable;
federation authority and derived content resolution are separate slices.
"""
import json
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.configuration import committed_project
from spikes.cross_references import CrossReferences
from spikes.metadata import require, uuid, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.project_relation_schema import (PROPOSAL, APPROVAL, REVOCATION, POLICY, TYPES,
    _WRITE, conflicts, evidence_id, reachability, record, records)
from spikes.reference_schema import reason as validate_reason
from spikes.reporting_schema import digest, encoded, fields, hex_id

MAX_PROJECTS = 128
MAX_RECORDS = 4096
ACTION = 'project-relation-lifecycle-v1'


class ProjectRelations:
    def __init__(self, node_path, *, user_id=None, allowed_projects=None, writable_projects=None):
        self.references = CrossReferences(node_path, user_id=user_id, allowed_projects=allowed_projects,
                                          writable_projects=writable_projects)
        self.node = self.references.node
        self.user_id = self.references.user_id
        self.artifacts = self.references.artifacts

    def _authorize(self, project_id, *, manage=False):
        access = self.references.authorize(project_id, write=manage)
        if manage and self.user_id != ProjectCreation(self.node).author_id():
            with Administration(self.node).read_locked() as state:
                actor = next((u for u in state['users'] if u['id'] == self.user_id and u['active']), None)
                if not actor or not (Administration.is_admin(actor) or actor['memberships'].get(project_id) == 'project-admin'):
                    raise AccessDenied('Project relation management denied')
        return access

    @staticmethod
    def _local_evidence(workspace, db, id_, value, head):
        """JSON actor IDs/Git authors alone are never authorization evidence."""
        if value['schema'] == PROPOSAL:
            return True  # A proposal is inert without both authenticated approvals.
        row = db.execute('SELECT record, done FROM operations WHERE id=?', (value['operation_id'],)).fetchone()
        if not row or not row[1]:
            return False
        receipt = json.loads(row[0]); commit = receipt.get('commit_id')
        if (receipt.get('relation_lifecycle') is not True or not commit or
                workspace.git.run('merge-base', '--is-ancestor', commit, head, check=False).returncode):
            return False
        path = f'artifacts/{id_}/relation.json'
        # A pre-existing unrelated receipt cannot authenticate injected evidence.
        return path in receipt['paths'] and workspace.git.snapshot(commit).get(path) == encoded(value)

    def _scan(self, *, local=None):
        """Internal topology validation returns no user content or hidden names."""
        ids = sorted(self.references.registered_projects())
        require(len(ids) <= MAX_PROJECTS, 'Project relation graph exceeds validation limit')
        states, heads, proposal_ids = {}, {}, set()
        total = 0
        for pid in ids:
            if local and pid == local[0]:
                _, ws, db, head, files = local
                entities = validate_snapshot(files)
                values = records(files, entities)
                trusted = {i for i, v in values.items() if self._local_evidence(ws, db, i, v, head)}
            else:
                ws = self.artifacts.workspace(pid); ws.repair_index()
                with ws.journal.lock(shared=True), ws.journal.connect() as db:
                    ws._read_shared(db); head = ws.git.head(); committed_project(ws.git, head, pid)
                    files = ws.git.snapshot(head); values = records(files, validate_snapshot(files))
                    trusted = {i for i, v in values.items() if self._local_evidence(ws, db, i, v, head)}
                    require(ws.git.head() == head, 'Relation graph changed while reading')
            for v in values.values():
                expected = v['owner_project_id'] if v['schema'] == PROPOSAL else v['project_id']
                require(expected == pid, 'Relation evidence is in the wrong project')
                if v['schema'] == PROPOSAL:
                    require(v['id'] not in proposal_ids, 'Conflicting relation identity')
                    proposal_ids.add(v['id'])
            total += len(values)
            require(total <= MAX_RECORDS, 'Project relation records exceed validation limit')
            heads[pid] = head
            states[pid] = dict(records=values, trusted=trusted)
        # Sequential reads do not pretend to be a multi-project atomic snapshot.
        for pid, head in heads.items():
            ws = local[1] if local and pid == local[0] else self.artifacts.workspace(pid)
            require(ws.git.head() == head, 'Relation graph changed; request a fresh preview')
        return heads, states

    @staticmethod
    def _projection(states):
        rows = {}
        for state in states.values():
            for value in state['records'].values():
                if value['schema'] != PROPOSAL:
                    continue
                p = value; rid = p['id']; endpoints = {p['source_project_id'], p['target_project_id']}
                status, approved = 'pending', []
                revoked, untrusted = False, False
                for pid in sorted(endpoints):
                    other = states.get(pid)
                    if other is None:
                        status = 'unavailable'; continue
                    for schema, kind in ((APPROVAL, 'approval'), (REVOCATION, 'revocation')):
                        id_ = evidence_id(rid, p['revision'], pid, kind)
                        proof = other['records'].get(id_)
                        if proof is None:
                            continue
                        exact = (proof['schema'] == schema and proof['proposal_sha256'] == digest(encoded(p))
                                 and proof['owner_project_id'] == p['owner_project_id'])
                        if not exact:
                            status = 'conflict'; continue
                        if id_ not in other['trusted']:
                            untrusted = True
                        elif schema == REVOCATION:
                            revoked = True
                        else:
                            approved.append(pid)
                if status != 'conflict':
                    if revoked:
                        status = 'revoked'
                    elif untrusted or not endpoints.issubset(states):
                        status = 'unavailable'
                    elif len(approved) == 2:
                        status = 'active'
                rows[rid] = dict(proposal=p, state=status, approved_projects=approved)
        bad = conflicts([r['proposal'] for r in rows.values() if r['state'] == 'active'])
        for rid in bad:
            rows[rid]['state'] = 'conflict'
        return rows

    def view(self, owner_project_id, relation_id):
        self._authorize(owner_project_id); uuid(relation_id)
        _, states = self._scan()
        value = states[owner_project_id]['records'].get(relation_id)
        require(value and value['schema'] == PROPOSAL, 'Relation unavailable')
        for pid in (value['source_project_id'], value['target_project_id']):
            self._authorize(pid)
        result = self._projection(states)[relation_id]
        return json.loads(encoded(result))

    def _envelope(self, project_id, value, heads, states, *, mode):
        rows = self._projection(states)
        before = [r['proposal'] for r in rows.values() if r['state'] == 'active']
        proposal = value if value['schema'] == PROPOSAL else states[value['owner_project_id']]['records'][value['relation_id']]
        after = [p for p in before if p['id'] != proposal['id']]
        if mode != 'revoke':
            # Activation upper bound, including future implicit sources.
            after.append(proposal)
            require(not conflicts(after), 'Relation would create a duplicate or structural cycle')
        visible = set()
        for pid in heads:
            try:
                self._authorize(pid); visible.add(pid)
            except AccessDenied:
                pass
        old, new = reachability(before), reachability(after)
        def paths(items):
            return [dict(recipient=a, provider=b, scope=scope) for a, b, scope in sorted(items)
                    if {a, b} <= visible]
        impact = dict(policy=POLICY, activation_adds=paths(new - old), removes=paths(old - new),
                      future_sources=True, visible_projects_only=True,
                      description='Policy includes future data/outputs and transitive paths; no artifact copies or individual shares.')
        preview = dict(schema='fpw-project-relation-write-v1', mode=mode, project_id=project_id,
                       heads={pid: head for pid, head in heads.items() if pid in visible},
                       graph_sha256=digest(encoded(heads)), record=value, user_id=self.user_id)
        preview['impact'] = impact
        return dict(preview=preview, sha256=digest(encoded(preview)))

    def proposal_preview(self, source_project_id, target_project_id, relation_type, reason, *, relation_id=None):
        for pid in (source_project_id, target_project_id):
            self._authorize(pid, manage=True)
        require(relation_type in TYPES, 'Invalid relation type'); validate_reason(reason)
        require(source_project_id != target_project_id, 'Project cannot relate to itself')
        if relation_type == 'relates_to':
            source_project_id, target_project_id = sorted((source_project_id, target_project_id))
        heads, states = self._scan(); owner = min(source_project_id, target_project_id)
        old = states[owner]['records'].get(relation_id) if relation_id else None
        if relation_id:
            uuid(relation_id)
            require(old and old['schema'] == PROPOSAL and
                    {old['source_project_id'], old['target_project_id']} == {source_project_id, target_project_id},
                    'Relation identity is immutable')
        now = CrossReferences.now()
        value = record(dict(schema=PROPOSAL, id=relation_id or str(uuid4()), owner_project_id=owner,
            source_project_id=source_project_id, target_project_id=target_project_id, type=relation_type,
            revision=old['revision'] + 1 if old else 1, policy=POLICY, originator_id=old['originator_id'] if old else self.user_id,
            updated_by=self.user_id, reason=reason, created_at=old['created_at'] if old else now,
            updated_at=now, state='proposed'))
        return self._envelope(owner, value, heads, states, mode='propose')

    def evidence_preview(self, owner_project_id, relation_id, project_id, operation_id, *, revoke=False, reason=None):
        uuid(operation_id); uuid(relation_id)
        self._authorize(project_id, manage=True); self._authorize(owner_project_id)
        heads, states = self._scan()
        p = states[owner_project_id]['records'].get(relation_id)
        require(p and p['schema'] == PROPOSAL and project_id in (p['source_project_id'], p['target_project_id']),
                'Relation unavailable')
        for pid in (p['source_project_id'], p['target_project_id']):
            self._authorize(pid)
        row = self._projection(states)[relation_id]
        require(row['state'] not in {'revoked', 'conflict', 'unavailable'}, 'Relation cannot be approved/revoked in this state')
        kind = 'revocation' if revoke else 'approval'
        id_ = evidence_id(relation_id, p['revision'], project_id, kind)
        require(id_ not in states[project_id]['records'], 'Relation evidence already exists')
        value = dict(schema=REVOCATION if revoke else APPROVAL, id=id_, relation_id=relation_id,
            owner_project_id=owner_project_id, revision=p['revision'], proposal_sha256=digest(encoded(p)),
            project_id=project_id, operation_id=operation_id)
        if revoke:
            validate_reason(reason)
            value.update(approval_id=evidence_id(relation_id, p['revision'], project_id, 'approval'),
                         revoked_by=self.user_id, revoked_at=CrossReferences.now(), reason=reason)
        else:
            value.update(approved_by=self.user_id, approved_at=CrossReferences.now())
        record(value)
        return self._envelope(project_id, value, heads, states, mode='revoke' if revoke else 'approve')

    def confirm(self, preview, sha256, operation_id, *, confirm=False, checkpoint=lambda stage: None):
        require(confirm is True and digest(encoded(preview)) == sha256, 'Exact relation preview must be confirmed')
        fields(preview, 'schema mode project_id heads graph_sha256 record user_id impact')
        require(preview['schema'] == 'fpw-project-relation-write-v1' and preview['user_id'] == self.user_id,
                'Invalid relation request')
        p = record(preview['record']); pid = preview['project_id']; uuid(pid); uuid(operation_id)
        mode = preview['mode']
        require(mode in {'propose', 'approve', 'revoke'} and
                p['schema'] == {'propose': PROPOSAL, 'approve': APPROVAL, 'revoke': REVOCATION}[mode], 'Invalid relation action')
        require(pid == (p['owner_project_id'] if mode == 'propose' else p['project_id']), 'Wrong relation project')
        actor = p['updated_by'] if mode == 'propose' else p['approved_by' if mode == 'approve' else 'revoked_by']
        require(actor == self.user_id, 'Relation author differs')
        if mode != 'propose':
            require(p['operation_id'] == operation_id, 'Evidence operation differs from preview')
        self._authorize(pid, manage=True)
        if mode == 'propose':
            for endpoint in (p['source_project_id'], p['target_project_id']):
                self._authorize(endpoint, manage=True)
        require(isinstance(preview['heads'], dict) and pid in preview['heads'], 'Missing relation HEAD pins')
        for project_id, head in preview['heads'].items():
            uuid(project_id); hex_id(head, True); self._authorize(project_id)
        ws = self.artifacts.workspace(pid)
        def prepare(workspace):
            managed = (p['source_project_id'], p['target_project_id']) if mode == 'propose' else (pid,)
            access = {endpoint: self._authorize(endpoint, manage=True) for endpoint in managed}
            head = workspace.git.head()
            require(head == preview['heads'][pid], 'Relation project changed')
            committed_project(workspace.git, head, pid)
            files = workspace.git.snapshot(head)
            # Same journal connection is safe inside the already held writer lock.
            with workspace.journal.connect() as db:
                heads, states = self._scan(local=(pid, workspace, db, head, files))
            require(digest(encoded(heads)) == preview['graph_sha256'], 'Relation graph changed; review a fresh preview')
            # Rebuild all semantic checks and impact; digest is not authorization.
            rebuilt = self._envelope(pid, p, heads, states, mode=mode)
            require(rebuilt['preview'] == preview, 'Relation preview differs from current impact')
            if mode != 'propose':
                current = states[p['owner_project_id']]['records'].get(p['relation_id'])
                require(current and digest(encoded(current)) == p['proposal_sha256'], 'Relation revision changed')
                require(pid in (current['source_project_id'], current['target_project_id']), 'Approval is not from a relation endpoint')
                require(self._projection(states)[p['relation_id']]['state'] in {'pending', 'active'}, 'Relation is not usable')
                require(p['id'] not in states[pid]['records'], 'Relation evidence already exists')
            else:
                require(not any(p['id'] in state['records'] for other, state in states.items() if other != pid),
                        'Relation identity belongs to another project')
            id_ = p['id']; path = f'artifacts/{id_}/'
            existing = states[pid]['records'].get(id_)
            require(mode == 'propose' or existing is None, 'Evidence already exists')
            if existing:
                meta = validate_snapshot(files)[id_]
            else:
                at = p['created_at'] if mode == 'propose' else p['approved_at' if mode == 'approve' else 'revoked_at']
                meta = dict(schema_version=1, id=id_, title='Projektová vazba: ' + mode, kind='document',
                            created_at=at, author_id=self.user_id, privacy='project', provenance='user',
                            file='relation.json', tags=[p['schema']])
            changes = {path + 'relation.json': encoded(p), path + 'metadata.json': encoded(meta)}
            require(access == {endpoint: self._authorize(endpoint, manage=True) for endpoint in managed},
                    'Relation management authority changed during preparation')
            return changes, 'Local workspace author', self.user_id + '@local.invalid', 'Project relation: ' + mode
        return ws.transact(operation_id, dict(action=ACTION, preview=preview), prepare,
                           expected_head=preview['heads'][pid], checkpoint=checkpoint, _relation_write=_WRITE)
