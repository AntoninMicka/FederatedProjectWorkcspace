# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Adversarial boundaries for derived access; real Git and isolated journals."""
import json
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_project_relation_resolver as fixtures
from spikes.administration import AccessDenied
from spikes.chat_service import ChatService
from spikes.context_builder import (AdHocInput, Authority, ContextBuilder, RelationInput,
                                   Target, TaskInstruction, relation_input_id)
from spikes.project_creation import ProjectCreation
from spikes.project_relation_resolver import ProjectRelationResolver, RelationViewUnavailable
from spikes.project_relations import ProjectRelations
from spikes.project_relations_panel import ProjectRelationsPanel
from spikes.projects import Projects


class RelationSecurityTests(unittest.TestCase):
    setUp = fixtures.HierarchyResolverTests.setUp
    save = fixtures.HierarchyResolverTests.save
    relation = fixtures.HierarchyResolverTests.relation
    member = fixtures.HierarchyResolverTests.member
    revoke = fixtures.HierarchyResolverTests.revoke
    nested = fixtures.HierarchyResolverTests.nested

    def prepare(self, reader, pin, *, boundary='same-node'):
        alias, focus = relation_input_id(pin), str(uuid4())
        authority = Authority('security-test', reader.user_id, json.loads(self.node.read_text())['id'],
                              'derived-access-v1', frozenset({alias}))
        target = Target(str(uuid4()), 'v1', boundary, 'fixture', 'fixture-model')
        builder = ContextBuilder(self.artifacts.workspace(self.a), self.a, relations=reader)
        prepared = builder.prepare(manifest_id=str(uuid4()), run_id=str(uuid4()), authority=authority,
            target=target, relation_inputs=(RelationInput(alias,pin),),
            ad_hoc_inputs=(AdHocInput(focus,b'Use the selected source','project'),),
            task=TaskInstruction('task-output','security-v1','Use selected sources only',focus))
        return builder,prepared,authority,target

    def test_all_recipient_roles_read_without_source_membership_and_never_gain_source_write(self):
        self.relation(self.a,self.b); id_=self.save(self.b,'Zdroj pouze pro čtení')
        reader,change,uid=self.member({self.a:'reader'})
        for role in ('reader','reviewer','editor','project-admin'):
            with self.subTest(role=role):
                change(action='update-user',user_id=uid,active=True,node_role='member',memberships={self.a:role})
                pin=reader.pin(self.a,self.b,id_)
                self.assertEqual(reader.read(pin)['raw'],'Zdroj pouze pro čtení'.encode())
                with self.assertRaises(AccessDenied): reader.references.authorize(self.b,write=True)
                manager=ProjectRelations(self.node,user_id=uid)
                with self.assertRaises(AccessDenied): manager.proposal_preview(self.a,self.b,'depends_on','Nelze spravovat zdroj')

    def test_revoked_recipient_rights_block_prepared_manifest_but_preserve_provenance(self):
        self.nested();id_=self.save(self.c,'Citlivé vybrané bajty')
        reader,change,uid=self.member({self.a:'editor'})
        pin=reader.pin(self.a,self.c,id_)
        builder,prepared,authority,target=self.prepare(reader,pin)
        manifest=prepared.manifest_bytes
        self.assertNotIn('Citlivé vybrané bajty'.encode(),manifest)
        change(action='update-user',user_id=uid,active=True,node_role='member',memberships={})
        with self.assertRaises(AccessDenied): builder.authorize_for_dispatch(prepared,authority=authority,target=target)
        self.assertEqual(manifest,prepared.manifest_bytes)
        self.assertIn(pin['source']['commit_id'].encode(),manifest)
        with self.assertRaises(AccessDenied): reader.read(pin)

    def test_reclassification_blocks_external_dispatch_of_a_prepared_historical_input(self):
        self.relation(self.a,self.b);id_=self.save(self.b,'Dřívější text')
        reader,_,_=self.member({self.a:'editor'})
        pin=reader.pin(self.a,self.b,id_)
        builder,prepared,authority,target=self.prepare(reader,pin,boundary='external-provider')
        self.save(self.b,'Nyní jen místní',id_=id_,new=False,privacy='local-only')
        with self.assertRaises(RelationViewUnavailable): builder.authorize_for_dispatch(prepared,authority=authority,target=target)
        self.assertEqual(reader.read(pin)['raw'],'Dřívější text'.encode())
        self.assertEqual(reader.read(pin)['privacy'],'local-only')

    def test_held_search_provider_and_old_rows_cannot_reuse_a_revoked_path(self):
        ab,_=self.nested();id_=self.save(self.c,'Výsledek staršího hledání')
        reader,_,uid=self.member({self.a:'reader'});service=ChatService(self.node,Projects(self.node))
        with service.as_user(uid,project_ids=[self.a],writable_project_ids=[],derive_project_relations=True):
            provider=service.project_source_provider(self.a)
            row=next(r for r in provider.catalog(self.a)['items'] if r['artifact_id']==id_)
            pin=provider.pin(self.a,row['source_project_id'],row['artifact_id'])
        self.revoke(self.a,self.b,ab)
        with self.assertRaises(RelationViewUnavailable): provider.read(pin)
        with self.assertRaises(RelationViewUnavailable): provider.pin(self.a,row['source_project_id'],row['artifact_id'])
        self.assertNotIn(id_,repr(provider.catalog(self.a)))

    def test_graph_drops_the_entire_result_when_rights_are_revoked_during_title_read(self):
        self.relation(self.a,self.b)
        reader,change,uid=self.member({self.a:'reader'})
        for root in (self.a,None):
            with self.subTest(root=root):
                change(action='update-user',user_id=uid,active=True,node_role='member',memberships={self.a:'reader'})
                panel=ProjectRelationsPanel(ProjectRelations(self.node,user_id=uid),reader)
                original=panel._title;changed=False
                def title(pid,head):
                    nonlocal changed
                    value=original(pid,head)
                    if not changed:
                        changed=True
                        change(action='update-user',user_id=uid,active=True,node_role='member',memberships={})
                    return value
                with patch.object(panel,'_title',side_effect=title),self.assertRaises(AccessDenied): panel.graph(root)

    def test_overview_rechecks_authority_after_computing_action_flags(self):
        self.relation(self.a,self.b);reader,change,uid=self.member({self.a:'reader'})
        panel=ProjectRelationsPanel(ProjectRelations(self.node,user_id=uid),reader)
        original=panel._allowed;changed=False
        def allowed(pid,**kwargs):
            nonlocal changed
            value=original(pid,**kwargs)
            if not changed:
                changed=True
                change(action='update-user',user_id=uid,active=False,node_role='member',memberships={})
            return value
        with patch.object(panel,'_allowed',side_effect=allowed),self.assertRaises(AccessDenied): panel.overview(self.a)

    def test_graph_rechecks_relation_revocation_after_reading_titles(self):
        rid=self.relation(self.a,self.b)
        panel=ProjectRelationsPanel(self.lifecycle,self.resolver);original=panel._title;changed=False
        def title(pid,head):
            nonlocal changed
            value=original(pid,head)
            if not changed:
                changed=True;self.revoke(self.a,self.b,rid)
            return value
        with patch.object(panel,'_title',side_effect=title),self.assertRaises(RelationViewUnavailable): panel.graph()

    def test_second_node_git_copies_without_journals_do_not_turn_synced_approvals_into_grants(self):
        self.relation(self.a,self.b);id_=self.save(self.b,'Dostupné jen původnímu schválení')
        pin=self.resolver.pin(self.a,self.b,id_)
        second=self.base/'second-node';second.mkdir(mode=0o700);node=second/'node.json';creator=ProjectCreation(node)
        for pid in (self.a,self.b):
            source=self.artifacts.workspace(pid).git.root;target=second/pid
            subprocess.run(['git','clone','--no-hardlinks',str(source),str(target)],check=True,capture_output=True,umask=0o077)
            creator.register(target,str(uuid4()))
        resolver=ProjectRelationResolver(node)
        self.assertNotEqual(resolver.user_id,self.resolver.user_id)
        self.assertNotIn(id_,repr(resolver.catalog(self.a)))
        with self.assertRaises(RelationViewUnavailable):resolver.pin(self.a,self.b,id_)
        self.assertTrue(self.resolver.read(pin)['read_only'])
        # Git bytes remain present for this trust test; no journal or credentials were copied.
        self.assertTrue((second/self.b/pin['source']['path']).is_file())

    def test_known_native_revocation_cannot_be_undone_by_an_older_local_git_head(self):
        rid=self.relation(self.a,self.b);id_=self.save(self.b,'Přístup před odvoláním')
        pin=self.resolver.pin(self.a,self.b,id_);ws=self.artifacts.workspace(self.a)
        before=ws.git.head();self.revoke(self.a,self.b,rid);revoked=ws.git.head()
        try:
            # Isolated test repo: simulate a stale local replica/branch, keeping its journal.
            ws.git.run('reset','--hard',before)
            with self.assertRaises(RelationViewUnavailable): self.resolver.read(pin)
        finally:
            ws.git.run('reset','--hard',revoked)
