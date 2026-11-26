# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.artifacts import Artifacts
from spikes.cross_references import CrossReferences
from spikes.markdown_documents import main_todo_id
from spikes.metadata import UnsupportedVersion, ValidationError
from spikes.project_creation import ProjectCreation
from spikes.project_relation_resolver import ProjectRelationResolver, RelationViewUnavailable
from spikes.project_relations import ProjectRelations
from spikes.reporting_schema import encoded


class HierarchyResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='hierarchy resolver ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base / 'node.json'
        creator = ProjectCreation(self.node)
        self.ids = [creator.create(name, self.base / name, str(uuid4()))['id']
                    for name in ('parent', 'child', 'nested', 'other')]
        self.a, self.b, self.c, self.x = self.ids
        self.artifacts = Artifacts(self.node); self.lifecycle = ProjectRelations(self.node)
        self.resolver = ProjectRelationResolver(self.node)

    def save(self, pid, body, *, id_=None, new=True, privacy='project'):
        id_ = id_ or str(uuid4()); ws = self.artifacts.workspace(pid)
        request = dict(project_id=pid, artifact_id=id_, base_head=ws.git.head(),
                       title='Podklad ' + body.splitlines()[0][:20], body=body, new=new, privacy=privacy)
        self.artifacts.save(request, str(uuid4()))
        return id_

    def relation(self, a, b, kind='parent_of'):
        proposal = self.lifecycle.proposal_preview(a, b, kind, 'Oprávněná spolupráce')
        self.lifecycle.confirm(proposal['preview'], proposal['sha256'], str(uuid4()), confirm=True)
        rid = proposal['preview']['record']['id']; owner = min(a, b)
        for pid in (a, b):
            op = str(uuid4()); envelope = self.lifecycle.evidence_preview(owner, rid, pid, op)
            self.lifecycle.confirm(envelope['preview'], envelope['sha256'], op, confirm=True)
        return rid

    def revoke(self, a, b, rid, *, checkpoint=lambda stage: None):
        op = str(uuid4()); envelope = self.lifecycle.evidence_preview(min(a, b), rid, a, op, revoke=True, reason='Odvoláno')
        return self.lifecycle.confirm(envelope['preview'], envelope['sha256'], op, confirm=True, checkpoint=checkpoint)

    def member(self, memberships):
        admin = Administration(self.node); actor = dict(id=None, node_role='federation-admin', memberships={})
        def change(**data):
            state = admin.request(actor, dict(action='list'))
            return admin.request(actor, dict(expected_commit=state['commit_id'], **data))
        uid = change(action='create-user', name='Čtenář rodiče', node_role='member')['users'][0]['id']
        change(action='update-user', user_id=uid, active=True, node_role='member', memberships=memberships)
        return ProjectRelationResolver(self.node, user_id=uid), change, uid

    @staticmethod
    def keys(catalog):
        return {(r['source_project_id'], r['artifact_id']) for r in catalog['items']}

    def nested(self):
        ab = self.relation(self.a, self.b); bc = self.relation(self.b, self.c)
        return ab, bc

    def diamond(self):
        ab, bc = self.nested()
        ax = self.relation(self.a, self.x); xc = self.relation(self.x, self.c)
        return ab, bc, ax, xc

    def test_parent_sees_new_nested_data_plans_and_registries_without_shares_or_copies(self):
        self.nested()
        own = self.save(self.a, 'Pouze rodič'); child = self.save(self.b, 'První podklad'); nested = self.save(self.c, 'Vnořený podklad')
        for pid in (self.b, self.c):
            self.save(pid, '# Plán projektu\n', id_=main_todo_id(pid))
        registry_id = str(uuid4()); ws = self.artifacts.workspace(self.c)
        registry = dict(schema_version=1, id=registry_id, title='Projektové riziko', kind='risks',
                        created_at='2026-11-26T00:00:00Z', author_id=self.lifecycle.user_id,
                        privacy='project', provenance='user', status='open', body='Ověřené riziko')
        ws.apply({f'registries/risks/{registry_id}.json': encoded(registry)},
                 author_name='Test', author_email='test@local.invalid', message='Create project registry entity')
        binary_id = str(uuid4()); binary = b'\x00\xff\x10native source bytes'
        source_meta = dict(schema_version=1, id=binary_id, title='Binární podklad', kind='source',
                           created_at='2026-11-26T00:00:00Z', author_id=self.lifecycle.user_id,
                           privacy='project', provenance='external', file='input.bin')
        ws.apply({f'artifacts/{binary_id}/metadata.json': encoded(source_meta),
                  f'artifacts/{binary_id}/input.bin': binary},
                 author_name='Test', author_email='test@local.invalid', message='Store original source bytes')
        root_ws = self.artifacts.workspace(self.a); before = root_ws.git.head()
        view = self.resolver.catalog(self.a); keys = self.keys(view)
        self.assertTrue({(self.a, own), (self.b, child), (self.c, nested), (self.c, registry_id),
                         (self.c, binary_id), (self.b, main_todo_id(self.b)), (self.c, main_todo_id(self.c))} <= keys)
        self.assertFalse(any(self.x == row['source_project_id'] for row in view['items']))
        for pid, id_, content in ((self.b, child, b'Prvn\xc3\xad podklad'), (self.c, nested, 'Vnořený podklad'.encode()),
                                  (self.c, registry_id, encoded(registry)), (self.c, binary_id, binary)):
            pin = self.resolver.pin(self.a, pid, id_); result = self.resolver.read(pin)
            self.assertEqual(result['raw'], content)
            self.assertTrue(result['read_only']); self.assertTrue(result['inherited'])
            self.assertEqual(result['source']['artifact_id'], id_)
        added = self.save(self.b, 'Nový podklad bez sdílení')
        self.assertIn((self.b, added), self.keys(self.resolver.catalog(self.a)))
        self.assertEqual(root_ws.git.head(), before)
        self.assertNotIn('Nový podklad'.encode(), b''.join(root_ws.git.snapshot(before).values()))
        self.assertFalse(self.resolver.references.cache.exists())
        for pid in (self.b, self.c):
            self.assertEqual(self.resolver.references.project_state(pid)['shares'], {})
        self.assertNotIn((self.a, own), self.keys(self.resolver.catalog(self.c)))

    def test_parent_reader_needs_no_child_membership_and_inactive_account_loses_access(self):
        self.nested(); id_ = self.save(self.c, 'Vnořený obsah bez členství')
        reader, change, uid = self.member({self.a: 'reader'})
        with self.assertRaises(AccessDenied):
            reader.references.authorize(self.c)
        pin = reader.pin(self.a, self.c, id_)
        self.assertEqual(reader.read(pin)['raw'], 'Vnořený obsah bez členství'.encode())
        change(action='update-user', user_id=uid, active=False, node_role='member', memberships={self.a: 'reader'})
        with self.assertRaises(AccessDenied):
            reader.catalog(self.a)
        with self.assertRaises(AccessDenied):
            reader.read(pin)

    def test_diamond_deduplicates_entities_and_preserves_alternative_reasons(self):
        self.diamond(); id_ = self.save(self.c, 'Jediný zdroj dvěma cestami')
        view = self.resolver.catalog(self.a)
        rows = [r for r in view['items'] if (r['source_project_id'], r['artifact_id']) == (self.c, id_)]
        self.assertEqual(len(rows), 1)
        source = next(s for s in view['sources'] if s['project_id'] == self.c)
        self.assertEqual(len(source['paths']), 2)
        for pid in (self.b, self.x):
            other = self.x if pid == self.b else self.b
            self.assertNotIn(other, {r['source_project_id'] for r in self.resolver.catalog(pid)['items']})
        self.assertEqual(view, self.resolver.catalog(self.a))

    def test_equal_entity_uuids_in_different_projects_remain_distinct(self):
        self.nested(); id_ = str(uuid4())
        self.save(self.b, 'Zdroj B', id_=id_); self.save(self.c, 'Zdroj C', id_=id_)
        rows = [r for r in self.resolver.catalog(self.a)['items'] if r['artifact_id'] == id_]
        self.assertEqual(len(rows), 2)
        for pid, body in ((self.b, 'Zdroj B'), (self.c, 'Zdroj C')):
            self.assertEqual(self.resolver.read(self.resolver.pin(self.a, pid, id_))['raw'], body.encode())

    def test_output_edges_do_not_widen_hierarchy_coverage_or_expose_other_family(self):
        self.relation(self.a, self.b)
        self.relation(self.a, self.x, 'depends_on'); self.relation(self.x, self.c)
        self.save(self.x, 'Interní cizí podklad'); self.save(self.c, 'Nepřípustné rozšíření výstupové cesty')
        view = self.resolver.catalog(self.a)
        self.assertEqual(view['coverage'], ['own', 'parent_of', 'depends_on', 'relates_to'])
        self.assertTrue({r['source_project_id'] for r in view['items']} <= {self.a, self.b})
        self.assertTrue(all(s['scopes'] == ['outputs'] for s in view['sources'] if s['project_id'] in {self.x, self.c}))

    def test_request_scope_is_not_widened_by_derived_access(self):
        self.nested(); id_ = self.save(self.c, 'Mimo scope requestu')
        scoped = ProjectRelationResolver(self.node, allowed_projects={self.a, self.b})
        view = scoped.catalog(self.a)
        self.assertEqual({s['project_id'] for s in view['sources']}, {self.a, self.b})
        self.assertNotIn(self.c, repr(view))
        with self.assertRaises(RelationViewUnavailable):
            scoped.pin(self.a, self.c, id_)
        pin = self.resolver.pin(self.a, self.c, id_)
        with self.assertRaises(RelationViewUnavailable):
            scoped.read(pin)

    def test_pinned_source_keeps_old_bytes_and_reports_new_revision_then_rejects_deleted_entity(self):
        self.relation(self.a, self.b); id_ = self.save(self.b, 'Původní verze')
        pin = self.resolver.pin(self.a, self.b, id_); original = deepcopy(pin)
        self.save(self.b, 'Nová verze', id_=id_, new=False)
        result = self.resolver.read(pin)
        self.assertEqual(result['raw'], 'Původní verze'.encode()); self.assertIsNotNone(result['newer'])
        self.assertEqual(pin, original)
        fresh = self.resolver.pin(self.a, self.b, id_)
        self.assertEqual(self.resolver.read(fresh)['raw'], 'Nová verze'.encode())
        ws = self.artifacts.workspace(self.b)
        self.artifacts.delete(dict(project_id=self.b, artifact_id=id_, base_head=ws.git.head()), str(uuid4()))
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(pin)
        self.assertNotIn((self.b, id_), self.keys(self.resolver.catalog(self.a)))

    def test_revoked_pinned_path_never_switches_to_alternative_path(self):
        ab, bc, ax, xc = self.diamond(); id_ = self.save(self.c, 'Dvě původní cesty')
        pin = self.resolver.pin(self.a, self.c, id_, relation_ids=[ab, bc])
        self.revoke(self.b, self.c, bc)
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(pin)
        fresh = self.resolver.pin(self.a, self.c, id_)
        self.assertEqual([e['relation_id'] for e in fresh['authorization']['path']], [ax, xc])
        self.assertEqual(self.resolver.read(fresh)['raw'], 'Dvě původní cesty'.encode())

    def test_local_only_boundary_checks_current_privacy_and_never_discloses_filtered_counts(self):
        self.relation(self.a, self.b)
        local = self.save(self.b, 'Lokální tajný podklad', privacy='local-only')
        project = self.save(self.b, 'Původně projektový podklad')
        pin = self.resolver.pin(self.a, self.b, project)
        external = self.resolver.catalog(self.a, boundary='external-provider')
        self.assertNotIn(local, repr(external)); self.assertTrue(external['privacy_filtered'])
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.pin(self.a, self.b, local, boundary='external-provider')
        self.save(self.b, 'Nyní lokální podklad', id_=project, new=False, privacy='local-only')
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(pin, boundary='external-provider')
        self.assertEqual(self.resolver.read(pin)['privacy'], 'local-only')

    def test_foreign_reference_is_explicitly_unavailable_and_grants_no_third_project_access(self):
        secret = self.save(self.x, 'Cizí chráněný obsah')
        refs = CrossReferences(self.node); sid = str(uuid4())
        offer = refs.share_preview(self.x, sid, secret, [self.b], 'Jen příjemci B')
        refs.share_write(offer, str(uuid4()), __import__('hashlib').sha256(encoded(offer)).hexdigest(), confirm=True)
        refid = str(uuid4()); pin = refs.source_pin(self.x, secret)
        attach = refs.preview(self.b, refid, pin, 'Lokální název reference', share_id=sid, reason_text='Pro projekt B')
        refs.write(attach, str(uuid4()), __import__('hashlib').sha256(encoded(attach)).hexdigest(), confirm=True)
        self.relation(self.a, self.b)
        reader, _, _ = self.member({self.a: 'reader'})
        view = reader.catalog(self.a); row = next(r for r in view['items'] if r['artifact_id'] == refid)
        self.assertFalse(row['available']); self.assertEqual(row['reason'], 'xref-resolution-required')
        self.assertIsNone(row['source']); self.assertNotIn(self.x, repr(view)); self.assertNotIn(secret, repr(view))
        with self.assertRaises(RelationViewUnavailable):
            reader.pin(self.a, self.b, refid)
        self.assertEqual(refs.view(self.b, refid)['state'], 'current')

    def test_drafts_are_not_committed_data_and_pending_journal_does_not_autorecover(self):
        rid = self.relation(self.a, self.b); id_ = self.save(self.b, 'Uložený text')
        pin = self.resolver.pin(self.a, self.b, id_); ws = self.artifacts.workspace(self.b)
        path = pin['source']['path']; original = (ws.git.root / path).read_bytes()
        (ws.git.root / path).write_bytes(b'Unsaved draft')
        self.assertEqual(self.resolver.read(pin)['raw'], 'Uložený text'.encode())
        (ws.git.root / path).write_bytes(original)
        def crash(stage):
            if stage == 'prepared':
                raise RuntimeError('stopped before commit')
        with self.assertRaises(RuntimeError):
            self.revoke(self.a, self.b, rid, checkpoint=crash)
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.catalog(self.a)
        owner_ws = self.artifacts.workspace(self.a)
        owner_ws.recover()
        self.assertNotIn((self.b, id_), self.keys(self.resolver.catalog(self.a)))

    def test_source_head_change_during_catalog_fails_without_a_partial_success(self):
        self.relation(self.a, self.b); id_ = self.save(self.b, 'Před změnou')
        original = self.resolver._snapshot; changed = False
        def moving_snapshot(pid, head, **kwargs):
            nonlocal changed
            result = original(pid, head, **kwargs)
            if pid == self.b and not changed:
                changed = True; self.save(self.b, 'Během čtení', id_=id_, new=False)
            return result
        with patch.object(self.resolver, '_snapshot', side_effect=moving_snapshot):
            with self.assertRaises(RelationViewUnavailable):
                self.resolver.catalog(self.a)
        self.assertIn((self.b, id_), self.keys(self.resolver.catalog(self.a)))

    def test_pin_schema_content_and_history_proofs_cannot_be_forged(self):
        self.relation(self.a, self.b); id_ = self.save(self.b, 'Ověřená data')
        pin = self.resolver.pin(self.a, self.b, id_)
        bad = deepcopy(pin); bad['source']['sha256'] = '0' * 64
        with self.assertRaises(ValidationError):
            self.resolver.read(bad)
        bad = deepcopy(pin); bad['schema'] = 'fpw-project-relation-input-v3'
        with self.assertRaises(UnsupportedVersion):
            self.resolver.read(bad)
        bad = deepcopy(pin); bad['authorization']['path'] = []; bad['authorization']['kind'] = 'project'
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(bad)
        bad = deepcopy(pin)
        bad['authorization']['path'][0]['approvals'][0]['commit_id'] = self.artifacts.workspace(self.x).git.head()
        with self.assertRaises(RelationViewUnavailable):
            self.resolver.read(bad)
        bad = deepcopy(pin); bad['authorization']['path'][0]['target_project_id'] = self.x
        with self.assertRaises(ValidationError):
            self.resolver.read(bad)

    def test_no_result_is_returned_after_permission_change_or_coverage_limit(self):
        self.nested(); reader, change, uid = self.member({self.a: 'reader'})
        self.save(self.b, 'První položka'); self.save(self.c, 'Druhá položka')
        original = reader._snapshot; changed = False
        def revoke_permission(pid, head, **kwargs):
            nonlocal changed
            result = original(pid, head, **kwargs)
            if not changed:
                changed = True
                change(action='update-user', user_id=uid, active=True, node_role='member', memberships={})
            return result
        with patch.object(reader, '_snapshot', side_effect=revoke_permission):
            with self.assertRaises(AccessDenied):
                reader.catalog(self.a)
        for setting, limit in (('MAX_DEPTH', 1), ('MAX_PATHS', 1), ('MAX_ITEMS', 1), ('MAX_CATALOG_BYTES', 1)):
            with self.subTest(setting=setting), patch('spikes.project_relation_resolver.' + setting, limit):
                with self.assertRaises(RelationViewUnavailable):
                    self.resolver.catalog(self.a)
