# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import AccessDenied, Administration
from spikes.artifact_catalog import document_ids
from spikes.artifacts import Artifacts
from spikes.metadata import MAX_METADATA, UnsupportedVersion, ValidationError, validate_snapshot, validate_transition
from spikes.project_creation import ProjectCreation
from spikes.project_relations import ProjectRelations
from spikes.project_relation_schema import (APPROVAL, PROPOSAL, REVOCATION, conflicts, evidence_id,
                                           record, records, reachability)
from spikes.reporting_schema import digest, encoded


class RelationLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='project relations ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'
        creator = ProjectCreation(self.node)
        self.ids = [creator.create(name, self.base / name, str(uuid4()))['id'] for name in ('a', 'b', 'c')]
        self.a, self.b, self.c = self.ids
        self.owner = min(self.a, self.b)
        self.service = ProjectRelations(self.node); self.artifacts = Artifacts(self.node)

    def confirm(self, envelope, operation=None, service=None, **kwargs):
        return (service or self.service).confirm(envelope['preview'], envelope['sha256'], operation or str(uuid4()),
                                                 confirm=True, **kwargs)

    def propose(self, a=None, b=None, kind='parent_of', **kwargs):
        envelope = self.service.proposal_preview(a or self.a, b or self.b, kind, 'Doložená spolupráce', **kwargs)
        self.confirm(envelope)
        return envelope['preview']['record']['id']

    def approve(self, rid, pid, owner=None, **kwargs):
        op = str(uuid4())
        envelope = self.service.evidence_preview(owner or self.owner, rid, pid, op)
        receipt = self.confirm(envelope, op, **kwargs)
        return envelope, op, receipt

    def active(self, a=None, b=None, kind='parent_of'):
        a, b = a or self.a, b or self.b
        rid = self.propose(a, b, kind); owner = min(a, b)
        self.approve(rid, a, owner); self.approve(rid, b, owner)
        return rid

    def files(self, pid):
        ws = self.artifacts.workspace(pid)
        return ws, ws.git.snapshot(ws.git.head())

    def test_two_consents_change_direction_and_revocation_keep_history(self):
        preview = self.service.proposal_preview(self.a, self.b, 'parent_of', 'Spolupráce')
        self.assertEqual(preview['preview']['impact']['activation_adds'],
                         [dict(recipient=self.a, provider=self.b, scope='data')])
        rid = preview['preview']['record']['id']; self.confirm(preview)
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'pending')
        self.approve(rid, self.a)
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'pending')
        self.approve(rid, self.b)
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'active')
        change = self.service.proposal_preview(self.b, self.a, 'depends_on', 'Změna směru', relation_id=rid)
        self.assertIn(dict(recipient=self.a, provider=self.b, scope='data'), change['preview']['impact']['removes'])
        self.confirm(change)
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'pending')
        self.assertEqual(self.service.view(self.owner, rid)['proposal']['revision'], 2)
        self.approve(rid, self.a); self.approve(rid, self.b)
        op = str(uuid4()); revoke = self.service.evidence_preview(self.owner, rid, self.b, op, revoke=True, reason='Konec spolupráce')
        self.confirm(revoke, op)
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'revoked')
        with self.assertRaises(ValidationError):
            self.service.evidence_preview(self.owner, rid, self.a, str(uuid4()))
        for pid in (self.a, self.b):
            ws, files = self.files(pid); values = records(files, validate_snapshot(files))
            self.assertTrue(any(v['schema'] == APPROVAL and v['revision'] == 1 for v in values.values()))
            self.assertFalse(set(values) & document_ids(files, validate_snapshot(files)))
        self.assertIn(REVOCATION, {v['schema'] for v in values.values()})

    def test_stale_other_head_exact_digest_and_replay_after_lost_response(self):
        preview = self.service.proposal_preview(self.a, self.b, 'relates_to', 'Spolupráce')
        with self.assertRaises(ValidationError):
            self.service.confirm(preview['preview'], '0' * 64, str(uuid4()), confirm=True)
        ws = self.artifacts.workspace(self.b)
        self.artifacts.save(dict(project_id=self.b, base_head=ws.git.head(), artifact_id=str(uuid4()),
                                 new=True, title='Nový podklad', body='Obsah'), str(uuid4()))
        with self.assertRaisesRegex(ValidationError, 'changed'):
            self.confirm(preview)
        rid = self.propose(kind='relates_to')
        envelope, op, receipt = self.approve(rid, self.a)
        self.approve(rid, self.b)
        again = self.confirm(envelope, op)
        self.assertEqual(again['commit_id'], receipt['commit_id'])
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'active')
        forged = deepcopy(envelope); forged['preview']['record']['approved_by'] = str(uuid4())
        forged['sha256'] = digest(encoded(forged['preview']))
        with self.assertRaises(ValidationError):
            self.confirm(forged, str(uuid4()))

    def test_duplicates_self_mixed_cycles_and_multiple_parents(self):
        self.active()
        for kind in ('parent_of', 'depends_on'):
            with self.assertRaises(ValidationError):
                self.service.proposal_preview(self.b, self.a, kind, 'Cyklus')
        with self.assertRaises(ValidationError):
            self.service.proposal_preview(self.a, self.b, 'parent_of', 'Duplicita')
        with self.assertRaises(ValidationError):
            self.service.proposal_preview(self.a, self.a, 'relates_to', 'Sebevazba')
        self.active(self.c, self.b)
        # Two parents must not acquire one another through their common child.
        _, states = self.service._scan()
        active = [r['proposal'] for r in self.service._projection(states).values() if r['state'] == 'active']
        paths = reachability(active)
        self.assertNotIn((self.a, self.c, 'data'), paths)
        self.assertNotIn((self.c, self.a, 'data'), paths)

    def test_symmetric_duplicates_and_output_limit_in_transitive_impact(self):
        self.active(kind='relates_to')
        with self.assertRaises(ValidationError):
            self.service.proposal_preview(self.b, self.a, 'relates_to', 'Zrcadlová duplicita')
        preview = self.service.proposal_preview(self.b, self.c, 'parent_of', 'Podprojekt')
        paths = preview['preview']['impact']['activation_adds']
        self.assertIn(dict(recipient=self.a, provider=self.c, scope='outputs'), paths)
        self.assertNotIn(dict(recipient=self.a, provider=self.c, scope='data'), paths)

    def member(self, memberships):
        admin = Administration(self.node); actor = dict(id=None, node_role='federation-admin', memberships={})
        def change(**data):
            state = admin.request(actor, dict(action='list'))
            return admin.request(actor, dict(expected_commit=state['commit_id'], **data))
        uid = change(action='create-user', name='Správce', node_role='member')['users'][0]['id']
        change(action='update-user', user_id=uid, active=True, node_role='member', memberships=memberships)
        return ProjectRelations(self.node, user_id=uid), change, uid

    def test_admin_required_both_ends_rights_rechecked_and_hidden_graph_not_leaked(self):
        member, change, uid = self.member({self.a: 'project-admin', self.b: 'editor'})
        with self.assertRaises(AccessDenied):
            member.proposal_preview(self.a, self.b, 'parent_of', 'Nepovoleno')
        change(action='update-user', user_id=uid, active=True, node_role='member',
               memberships={self.a: 'project-admin', self.b: 'project-admin'})
        preview = member.proposal_preview(self.a, self.b, 'parent_of', 'Povoleno')
        self.assertNotIn(self.c, repr(preview))
        change(action='update-user', user_id=uid, active=True, node_role='member',
               memberships={self.a: 'project-admin', self.b: 'reader'})
        with self.assertRaises(AccessDenied):
            self.confirm(preview, service=member)
        rid = self.propose()
        # Each endpoint can be approved by its own administrator.
        op = str(uuid4()); approval = member.evidence_preview(self.owner, rid, self.a, op)
        self.confirm(approval, op, service=member)
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'pending')
        with self.assertRaises(AccessDenied):
            member.evidence_preview(self.owner, rid, self.b, str(uuid4()))

    def test_generic_writers_cannot_inject_modify_or_delete_controlled_records(self):
        rid = self.propose(); ws, files = self.files(self.owner)
        with self.assertRaisesRegex(ValidationError, 'control evidence'):
            self.service.references.share_preview(self.owner, str(uuid4()), rid, [self.c], 'Pokus o sdílení')
        path = f'artifacts/{rid}/relation.json'; value = json.loads(files[path])
        value['revision'] += 1; value['reason'] = 'Podvržený návrh'
        with self.assertRaisesRegex(ValidationError, 'authorized native lifecycle'):
            ws.apply({path: encoded(value)}, author_name='Test', author_email='test@local.invalid', message='Bypass')
        with self.assertRaises(ValidationError):
            ws.apply({p: None for p in files if p.startswith(f'artifacts/{rid}/')},
                     author_name='Test', author_email='test@local.invalid', message='Delete')
        op = str(uuid4()); preview = self.service.evidence_preview(self.owner, rid, self.a, op)
        proof = preview['preview']['record']; aid = proof['id']; at = proof['approved_at']
        meta = dict(schema_version=1, id=aid, title='Fake approval', kind='document', created_at=at,
                    author_id=self.service.user_id, privacy='project', provenance='user', file='relation.json', tags=[APPROVAL])
        target = self.artifacts.workspace(self.a)
        with self.assertRaisesRegex(ValidationError, 'authorized native lifecycle'):
            target.apply({f'artifacts/{aid}/relation.json': encoded(proof), f'artifacts/{aid}/metadata.json': encoded(meta)},
                         author_name='Test', author_email='test@local.invalid', message='Inject')
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'pending')

    def test_authority_lost_during_graph_validation_cannot_prepare_an_intent(self):
        member, change, uid = self.member({self.a: 'project-admin', self.b: 'project-admin'})
        envelope = member.proposal_preview(self.a, self.b, 'parent_of', 'Původně povoleno')
        scan = member._scan
        def revoke_during_scan(**kwargs):
            result = scan(**kwargs)
            change(action='update-user', user_id=uid, active=True, node_role='member',
                   memberships={self.a: 'project-admin', self.b: 'reader'})
            return result
        ws = self.artifacts.workspace(self.owner); head = ws.git.head()
        with patch.object(member, '_scan', side_effect=revoke_during_scan):
            with self.assertRaises(AccessDenied):
                self.confirm(envelope, service=member)
        self.assertEqual(ws.git.head(), head)
        with ws.journal.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pending').fetchone()[0], 0)

    def test_crash_recovery_each_native_boundary_and_between_projects(self):
        rid = self.propose(); self.approve(rid, self.a)
        # Recovery of the second endpoint must never repeat the first transaction.
        for stage in ('prepared', 'files-applied', 'commit-created', 'commit-ready', 'before-ref',
                      'ref-updated', 'committed', 'git-indexed', 'indexed', 'completed'):
            with self.subTest(stage=stage):
                # A new revision keeps each scenario independent and invalidates old grants.
                change = self.service.proposal_preview(self.a, self.b, 'parent_of', 'Obnova ' + stage, relation_id=rid)
                self.confirm(change); self.approve(rid, self.a)
                op = str(uuid4()); preview = self.service.evidence_preview(self.owner, rid, self.b, op)
                def crash(current):
                    if current == stage:
                        raise RuntimeError('simulated crash')
                with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
                    self.confirm(preview, op, checkpoint=crash)
                service = ProjectRelations(self.node)
                # Explicit same-operation retry recovers approved journal bytes.
                receipt = self.confirm(preview, op, service=service)
                self.assertIsNotNone(receipt['commit_id'])
                self.assertEqual(service.view(self.owner, rid)['state'], 'active')
                again = self.confirm(preview, op, service=service)
                self.assertEqual(receipt['commit_id'], again['commit_id'])

    def test_synced_or_forged_evidence_without_native_receipt_grants_nothing(self):
        rid = self.active()
        _, states = self.service._scan()
        states[self.a]['trusted'].clear()
        self.assertEqual(self.service._projection(states)[rid]['state'], 'unavailable')
        # Concurrent individually valid structural changes become a fail-closed component.
        p = self.service.view(self.owner, rid)['proposal']
        q = dict(p, id=str(uuid4()), source_project_id=self.b, target_project_id=self.a, type='depends_on')
        self.assertEqual(conflicts([p, q]), {p['id'], q['id']})
        ws, files = self.files(self.a)
        proof = next(v for v in records(files, validate_snapshot(files)).values() if v['schema'] == APPROVAL)
        with ws.journal.connect() as db:
            receipt = json.loads(db.execute('SELECT record FROM operations WHERE id=?', (proof['operation_id'],)).fetchone()[0])
            receipt.pop('relation_lifecycle')
            db.execute('UPDATE operations SET record=? WHERE id=?', (json.dumps(receipt), proof['operation_id']))
            db.commit()
        self.assertEqual(self.service.view(self.owner, rid)['state'], 'unavailable')

    def test_forged_third_endpoint_and_incomplete_graph_are_rejected(self):
        rid = self.propose()
        op = str(uuid4())
        envelope = self.service.evidence_preview(self.owner, rid, self.a, op)
        proof = dict(envelope['preview']['record'], project_id=self.c,
                     id=evidence_id(rid, 1, self.c, 'approval'))
        heads, states = self.service._scan()
        forged = self.service._envelope(self.c, proof, heads, states, mode='approve')
        with self.assertRaisesRegex(ValidationError, 'endpoint'):
            self.confirm(forged, op)
        with patch('spikes.project_relations.MAX_PROJECTS', 2):
            with self.assertRaisesRegex(ValidationError, 'limit'):
                self.service.proposal_preview(self.b, self.c, 'parent_of', 'Neúplný graf')

    def test_hard_process_exit_and_revocation_recovery(self):
        rid = self.active()
        script = '''
import json, os, sys
from spikes.project_relations import ProjectRelations
service = ProjectRelations(sys.argv[1])
envelope = json.loads(sys.argv[2])
def crash(stage):
    if stage == sys.argv[4]: os._exit(71)
service.confirm(envelope['preview'], envelope['sha256'], sys.argv[3], confirm=True, checkpoint=crash)
'''
        for stage in ('prepared', 'ref-updated'):
            with self.subTest(stage=stage):
                op = str(uuid4())
                envelope = self.service.evidence_preview(self.owner, rid, self.a, op, revoke=True, reason='Odvolání po pádu')
                result = subprocess.run([sys.executable, '-c', script, str(self.node), json.dumps(envelope), op, stage],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 71, result.stderr)
                receipt = self.confirm(envelope, op, service=ProjectRelations(self.node))
                self.assertIsNotNone(receipt['commit_id'])
                self.assertEqual(self.service.view(self.owner, rid)['state'], 'revoked')
                if stage == 'prepared':
                    change = self.service.proposal_preview(self.a, self.b, 'parent_of', 'Nová spolupráce', relation_id=rid)
                    self.confirm(change); self.approve(rid, self.a); self.approve(rid, self.b)

    def test_schema_and_transition_refuse_unknown_policy_mutation_and_revision_skip(self):
        rid = self.propose(); ws, before = self.files(self.owner)
        path = f'artifacts/{rid}/relation.json'; p = json.loads(before[path])
        for changes in (dict(policy='unknown'), dict(state='active'), dict(revision=True), dict(reason='x\0y')):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                record(dict(p, **changes))
        with self.assertRaises(UnsupportedVersion):
            record(dict(p, schema='fpw-project-relation-v2'))
        for changes in (dict(revision=3), dict(source_project_id=self.c), dict(originator_id=str(uuid4()), revision=2)):
            after = dict(before); after[path] = encoded(dict(p, **changes))
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                validate_transition(before, after)

    def test_schema_name_quoted_in_other_json_is_not_a_relation_record(self):
        id_ = str(uuid4()); ws, files = self.files(self.a)
        meta = dict(schema_version=1, id=id_, title='Obyčejný JSON', kind='document',
                    created_at='2026-11-26T00:00:00Z', author_id=self.service.user_id,
                    privacy='project', provenance='user', file='example.json')
        ws.apply({f'artifacts/{id_}/metadata.json': encoded(meta),
                  f'artifacts/{id_}/example.json': encoded(dict(schema='example-v1', text=PROPOSAL + 'x' * MAX_METADATA))},
                 author_name='Test', author_email='test@local.invalid', message='Store an ordinary example')
        _, files = self.files(self.a)
        self.assertNotIn(id_, records(files, validate_snapshot(files)))
