# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import json
import unittest
from uuid import uuid4

from tests import test_project_relation_resolver as fixtures
from spikes.administration import AccessDenied
from spikes.chat_service import ChatService
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder, RelationInput,
                                   Target, TaskInstruction, relation_input_id)
from spikes.project_relations import ProjectRelations
from spikes.project_relations_panel import ProjectRelationsPanel
from spikes.project_relation_resolver import ProjectRelationResolver, RelationViewUnavailable
from spikes.projects import Projects
from spikes.metadata import ValidationError


class RelationsPanelTests(unittest.TestCase):
    setUp = fixtures.HierarchyResolverTests.setUp
    save = fixtures.HierarchyResolverTests.save
    relation = fixtures.HierarchyResolverTests.relation
    member = fixtures.HierarchyResolverTests.member
    revoke = fixtures.HierarchyResolverTests.revoke
    nested = fixtures.HierarchyResolverTests.nested

    def panel(self, *, network=False):
        return ProjectRelationsPanel(self.lifecycle, self.resolver, network=network)

    def test_native_ui_proposal_two_endpoint_approvals_and_source_preview(self):
        panel = self.panel(); id_ = self.save(self.b, 'Podklad dítěte')
        envelope = panel.proposal_preview(self.a, self.a, self.b, 'parent_of', 'Dítě dodává data')
        self.assertIn(self.a, envelope['display']['titles'])
        panel.confirm(self.a, envelope['preview'], envelope['sha256'], str(uuid4()))
        rid = envelope['preview']['record']['id']; owner = min(self.a, self.b)
        for pid in (self.a, self.b):
            overview = panel.overview(pid); row = next(r for r in overview['relations'] if r['relation_id'] == rid)
            self.assertEqual(row['state'], 'pending'); self.assertTrue(row['can_approve'])
            op = str(uuid4()); approval = panel.evidence_preview(pid, owner, rid, op)
            panel.confirm(pid, approval['preview'], approval['sha256'], op)
        row = next(r for r in panel.overview(self.a)['relations'] if r['relation_id'] == rid)
        self.assertEqual(row['state'], 'active')
        view = panel.source_view(self.a, self.b, id_)
        self.assertTrue(view['read_only']); self.assertIn('Podklad dítěte', view['preview']['text'])
        self.assertEqual(panel.sources(self.a, 'nenajde-se')['items'], [])
        filtered = panel.sources(self.a, 'PODKLAD DÍTĚTE')['items']
        self.assertEqual([r['artifact_id'] for r in filtered], [id_])
        self.assertEqual(filtered[0]['reason'], 'Data podprojektu')

    def test_normal_web_account_derives_read_without_membership_but_not_management(self):
        self.relation(self.a, self.b); id_ = self.save(self.b, 'Pro editora rodiče')
        reader, change, uid = self.member({self.a: 'editor'})
        service = ChatService(self.node, Projects(self.node))
        with service.as_user(uid, project_ids=[self.a], writable_project_ids=[self.a], derive_project_relations=True):
            panel = service.project_relations_panel(self.a)
            view = panel.sources(self.a)
            self.assertIn(id_, [r['artifact_id'] for r in view['items']])
            self.assertFalse(panel.overview(self.a)['can_create'])
            pin = panel.source_pin(self.a, self.b, id_)
            self.assertEqual(pin['input_id'], relation_input_id(pin['pin']))
            with self.assertRaises(AccessDenied):
                panel.proposal_preview(self.a, self.a, self.b, 'depends_on', 'Editor nesmí měnit vztah')
        # A genuinely delegated API scope remains closed instead of inheriting the web policy.
        with service.as_user(uid, project_ids=[self.a], writable_project_ids=[self.a]):
            panel = service.project_relations_panel(self.a)
            self.assertNotIn(id_, [r['artifact_id'] for r in panel.sources(self.a)['items']])
        change(action='update-user', user_id=uid, active=True, node_role='member', memberships={self.a:'reader'})
        with service.as_user(uid, project_ids=[self.a], writable_project_ids=[], derive_project_relations=True):
            panel = service.project_relations_panel(self.a)
            self.assertIn('Pro editora rodiče', panel.source_view(self.a, self.b, id_)['preview']['text'])
            with self.assertRaises(AccessDenied): panel.source_pin(self.a, self.b, id_)

    def prepare_context(self, pin, *, boundary='same-node'):
        id_ = relation_input_id(pin); focus = str(uuid4())
        node = json.loads(self.node.read_bytes())
        authority = Authority('relation-ui', self.lifecycle.user_id, node['id'], 'relations-v1', frozenset({id_}))
        target = Target(str(uuid4()), 'v1', boundary, 'fixture', 'fixture-model')
        builder = ContextBuilder(self.artifacts.workspace(self.a), self.a, relations=self.resolver)
        prepared = builder.prepare(manifest_id=str(uuid4()), run_id=str(uuid4()), authority=authority, target=target,
            relation_inputs=(RelationInput(id_, pin),), ad_hoc_inputs=(AdHocInput(focus,b'Use the selected source','project'),),
            task=TaskInstruction('task-output','fixture-v1','Answer using only selected sources',focus))
        return builder, prepared, authority, target

    def test_explicit_manifest_contains_only_selected_source_and_exact_citation(self):
        self.nested(); id_ = self.save(self.c, 'Vybraný obsah'); self.save(self.b, 'Nezvolený tajný obsah')
        pin = self.resolver.pin(self.a, self.c, id_)
        builder, prepared, authority, target = self.prepare_context(pin)
        record = prepared.manifest['inputs'][0]
        self.assertEqual(record['source'], 'project-relation'); self.assertEqual(record['relation_pin'], pin)
        self.assertIn(pin['source']['commit_id'], record['citation'])
        payload = b'\n'.join(base64.b64decode(p['content_b64']) for p in json.loads(prepared.payload)['inputs'])
        self.assertIn('Vybraný obsah'.encode(), payload); self.assertNotIn('Nezvolený tajný obsah'.encode(), payload)
        builder.authorize_for_dispatch(prepared, authority=authority, target=target)

    def test_revoked_path_and_changed_source_block_dispatch_even_when_recipient_head_did_not_move(self):
        _, bc = self.nested(); id_ = self.save(self.c, 'Text před odesláním')
        pin = self.resolver.pin(self.a, self.c, id_)
        builder, prepared, authority, target = self.prepare_context(pin)
        head = self.artifacts.workspace(self.a).git.head()
        self.revoke(self.b, self.c, bc)
        self.assertEqual(self.artifacts.workspace(self.a).git.head(),head)
        with self.assertRaises(RelationViewUnavailable):
            builder.authorize_for_dispatch(prepared, authority=authority, target=target)

    def test_source_revision_and_privacy_are_rechecked_before_dispatch(self):
        self.relation(self.a,self.b); id_ = self.save(self.b,'Původní obsah')
        builder, prepared, authority, target = self.prepare_context(self.resolver.pin(self.a,self.b,id_))
        self.save(self.b,'Nová revize',id_=id_,new=False)
        with self.assertRaises(ValidationError):
            builder.authorize_for_dispatch(prepared,authority=authority,target=target)
        local = self.save(self.b,'Jen zde',privacy='local-only')
        with self.assertRaises(RelationViewUnavailable):
            self.prepare_context(self.resolver.pin(self.a,self.b,local),boundary='external-provider')
        self.assertNotIn(local,repr(self.panel(network=True).sources(self.a)))

    def test_output_publication_revocation_blocks_prepared_manifest(self):
        from spikes.reporting_schema import digest,encoded
        self.relation(self.a,self.b,'depends_on'); id_ = self.save(self.b,'Publikovaný vstup')
        refs=self.lifecycle.references
        offer=refs.share_preview(self.b,str(uuid4()),id_,[self.x],'Výstup',purpose='output')
        refs.share_write(offer,str(uuid4()),digest(encoded(offer)),confirm=True)
        builder, prepared, authority, target=self.prepare_context(self.resolver.pin(self.a,self.b,id_))
        revoke=refs.revoke_preview(self.b,offer['share_id']);refs.revoke(revoke,str(uuid4()),digest(encoded(revoke)),confirm=True)
        with self.assertRaises(RelationViewUnavailable):builder.authorize_for_dispatch(prepared,authority=authority,target=target)

    def test_graph_current_component_and_all_projects_include_isolated_nodes(self):
        self.nested()
        current = self.panel().graph(self.a)
        self.assertEqual({n['id'] for n in current['nodes']}, {self.a,self.b,self.c})
        self.assertEqual(len(current['edges']),2)
        all_projects = self.panel().graph()
        self.assertEqual({n['id'] for n in all_projects['nodes']},{self.a,self.b,self.c,self.x})
        self.assertTrue(all(n['navigable'] for n in all_projects['nodes']))

    def test_graph_does_not_disclose_unrelated_projects_or_pending_foreign_relations(self):
        self.nested()
        envelope=self.lifecycle.proposal_preview(self.b,self.x,'depends_on','Skrytý důvod vztahu')
        self.lifecycle.confirm(envelope['preview'],envelope['sha256'],str(uuid4()),confirm=True)
        _,_,uid=self.member({self.a:'reader'})
        service=ChatService(self.node,Projects(self.node))
        with service.as_user(uid,project_ids=[self.a],writable_project_ids=[],derive_project_relations=True):
            graph=service.project_relations_panel(None).graph()
            self.assertEqual({n['id'] for n in graph['nodes']},{self.a,self.b,self.c})
            self.assertNotIn(self.x,repr(graph));self.assertNotIn('Skrytý důvod',repr(graph))
            self.assertEqual({n['id'] for n in graph['nodes'] if n['navigable']},{self.a})
            with self.assertRaises(AccessDenied):service.project_relations_panel(self.x).graph(self.x)
        with service.as_user(uid,project_ids=[],writable_project_ids=[],derive_project_relations=True):
            self.assertEqual(service.project_relations_panel(None).graph()['nodes'],[])

    def test_graph_retains_pending_and_revoked_states_without_granting_access(self):
        e=self.lifecycle.proposal_preview(self.a,self.b,'parent_of','Navržená hierarchie')
        self.lifecycle.confirm(e['preview'],e['sha256'],str(uuid4()),confirm=True)
        self.assertEqual(self.panel().graph(self.a)['edges'][0]['state'],'pending')
        rid=e['preview']['record']['id'];op=str(uuid4())
        revoke=self.lifecycle.evidence_preview(min(self.a,self.b),rid,self.a,op,revoke=True,reason='Ukončeno')
        self.lifecycle.confirm(revoke['preview'],revoke['sha256'],op,confirm=True)
        self.assertEqual(self.panel().graph(self.a)['edges'][0]['state'],'revoked')
