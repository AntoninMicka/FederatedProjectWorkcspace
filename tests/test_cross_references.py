# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from spikes.administration import Administration, AccessDenied
from spikes.artifacts import Artifacts
from spikes.context_builder import Authority, ContextBuilder, ProjectInput, Target
from spikes.cross_references import CrossReferences, ReferenceUnavailable
from spikes.metadata import UnsupportedVersion, ValidationError, validate_snapshot, validate_transition
from spikes.project_creation import ProjectCreation
from spikes.reference_schema import SCHEMA, SCHEMA_V1, FORK, SHARE, references, shares
from spikes.reporting_schema import digest, encoded


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='cross references ');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.node=self.base/'node.json'
        creator=ProjectCreation(self.node)
        self.source=creator.create('Source project',self.base/'source',str(uuid4()))['id']
        self.target=creator.create('Target project',self.base/'target',str(uuid4()))['id']
        self.author=creator.author_id();self.artifacts=Artifacts(self.node)
        self.source_ws=self.artifacts.workspace(self.source);self.target_ws=self.artifacts.workspace(self.target)
        self.source_id=str(uuid4());self.reference_id=str(uuid4())
        self.artifacts.save(dict(project_id=self.source,base_head=self.source_ws.git.head(),artifact_id=self.source_id,
            title='Original source title',body='Přesné původní bajty.\n',new=True),str(uuid4()))
        self.service=CrossReferences(self.node)
        self.share_id=self.share()
        self.pin=self.service.source_pin(self.source,self.source_id)
        self.preview=self.service.preview(self.target,self.reference_id,self.pin,'Local reference label',
                                          share_id=self.share_id,reason_text='Podklad pro cílový projekt')
        self.operation=str(uuid4())
        self.receipt=self.service.write(self.preview,self.operation,digest(encoded(self.preview)),confirm=True)

    def share(self, *, service=None, targets=None, artifact_id=None):
        service=service or self.service; share_id=str(uuid4())
        value=service.share_preview(self.source,share_id,artifact_id or self.source_id,
                                    targets or [self.target],'Sdílení pro cílový projekt')
        service.share_write(value,str(uuid4()),digest(encoded(value)),confirm=True)
        return share_id

    def change_source(self,body='New source revision\n',title='New source title'):
        return self.artifacts.save(dict(project_id=self.source,base_head=self.source_ws.git.head(),artifact_id=self.source_id,
            title=title,body=body,new=False),str(uuid4()))

    def context(self, *, service=None, boundary='same-node'):
        service=service or self.service
        authority=Authority('reference-test',service.user_id,str(uuid4()),'v1',frozenset({self.reference_id}))
        target=Target(str(uuid4()),'v1',boundary,'runtime','model')
        builder=ContextBuilder(self.target_ws,self.target,references=service)
        prepared=builder.prepare(manifest_id=str(uuid4()),run_id=str(uuid4()),authority=authority,target=target,
            project_inputs=(ProjectInput(self.reference_id),))
        return builder,prepared,authority,target

    def user(self):
        admin=Administration(self.node)
        actor=dict(id=None,node_role='federation-admin',memberships={})
        def change(**data):
            current=admin.request(actor,dict(action='list'))
            return admin.request(actor,dict(expected_commit=current['commit_id'],**data))
        response=change(action='create-user',name='Reader',node_role='member')
        uid=response['users'][0]['id']
        change(action='update-user',user_id=uid,active=True,node_role='member',
               memberships={self.source:'reader',self.target:'editor'})
        return CrossReferences(self.node,user_id=uid),change,uid

    def test_reference_stores_only_pointer_and_view_renders_exact_pinned_revision(self):
        files=self.target_ws.git.snapshot(self.target_ws.git.head())
        pointer=files[f'artifacts/{self.reference_id}/reference.json']
        self.assertEqual(json.loads(pointer),dict(schema=SCHEMA,source=self.pin,share=dict(
            share_id=self.share_id,originator_id=self.author,attached_by=self.author,reason='Podklad pro cílový projekt')))
        self.assertNotIn('Přesné'.encode(),b''.join(files.values()))
        view=self.service.view(self.target,self.reference_id)
        self.assertTrue(view['read_only']);self.assertFalse(view['stale'])
        self.assertEqual(base64.b64decode(view['content_b64']),'Přesné původní bajty.\n'.encode())
        self.assertEqual(view['preview']['format'],'markdown')
        self.assertEqual(view['title'],'Original source title')
        self.assertFalse(any(p.is_symlink() for p in (self.target_ws.git.root/'artifacts').rglob('*')))

    def test_newer_revision_is_offered_and_only_explicit_repin_changes_reference(self):
        self.change_source()
        view=self.service.view(self.target,self.reference_id)
        self.assertEqual(view['state'],'newer-available')
        self.assertEqual(view['source'],self.pin)
        self.assertEqual(base64.b64decode(view['content_b64']),'Přesné původní bajty.\n'.encode())
        updated=self.service.preview(self.target,self.reference_id,view['newer'],'Local reference label',update=True)
        with self.assertRaises(ValidationError):self.service.write(updated,str(uuid4()),digest(encoded(updated)))
        self.service.write(updated,str(uuid4()),digest(encoded(updated)),confirm=True)
        self.assertEqual(base64.b64decode(self.service.view(self.target,self.reference_id)['content_b64']),b'New source revision\n')

    def test_unrelated_source_commit_does_not_offer_a_content_update(self):
        self.source_ws.git.run('commit','--allow-empty','-m','Unrelated history')
        self.assertIsNone(self.service.view(self.target,self.reference_id)['newer'])

    def test_offline_cache_is_stale_display_only_and_never_context_or_fork_input(self):
        self.service.view(self.target,self.reference_id)
        root=self.source_ws.git.root;offline=root.with_name('source-offline');root.rename(offline)
        self.addCleanup(lambda:offline.rename(root) if offline.exists() else None)
        view=self.service.view(self.target,self.reference_id)
        self.assertEqual(view['state'],'offline-stale');self.assertTrue(view['privacy_unverified'])
        self.assertEqual(base64.b64decode(view['content_b64']),'Přesné původní bajty.\n'.encode())
        with self.assertRaises((OSError,ValueError)):self.context()
        with self.assertRaises((OSError,ValueError)):self.service.fork_preview(self.target,self.reference_id,str(uuid4()))
        with self.assertRaises(ValueError):self.service.view(self.target,self.reference_id,boundary='external-provider')

    def test_current_deletion_denies_cached_content(self):
        self.service.view(self.target,self.reference_id)
        self.artifacts.delete(dict(project_id=self.source,artifact_id=self.source_id,base_head=self.source_ws.git.head()),str(uuid4()))
        with self.assertRaisesRegex(ReferenceUnavailable,'deleted'):self.service.view(self.target,self.reference_id)
        with self.assertRaises(ReferenceUnavailable):self.context()

    def test_live_account_revocation_denies_view_offline_cache_and_dispatch(self):
        service,change,uid=self.user()
        service.view(self.target,self.reference_id)
        builder,prepared,authority,target=self.context(service=service)
        change(action='update-user',user_id=uid,active=True,node_role='member',memberships={self.target:'editor'})
        with self.assertRaises(AccessDenied):service.view(self.target,self.reference_id)
        with self.assertRaises(AccessDenied):builder.authorize_for_dispatch(prepared,authority=authority,target=target)
        self.assertEqual(service.index(self.target)['references'],[dict(reference_id=self.reference_id,state='unavailable')])
        root=self.source_ws.git.root;offline=root.with_name('source-offline');root.rename(offline)
        self.addCleanup(lambda:offline.rename(root) if offline.exists() else None)
        with self.assertRaises(AccessDenied):service.view(self.target,self.reference_id)

    def test_privacy_is_rechecked_after_prepare_and_local_only_never_leaves_node(self):
        builder,prepared,authority,target=self.context(boundary='external-provider')
        path=f'artifacts/{self.source_id}/metadata.json';files=self.source_ws.git.snapshot(self.source_ws.git.head())
        meta=json.loads(files[path]);meta['privacy']='local-only'
        self.source_ws.apply({path:encoded(meta)},author_name='Local',author_email='local@example.invalid',message='Tighten source privacy')
        with self.assertRaisesRegex(ValidationError,'local-only'):
            builder.authorize_for_dispatch(prepared,authority=authority,target=target)
        with self.assertRaisesRegex(ValidationError,'local-only'):self.context(boundary='external-provider')
        view=self.service.view(self.target,self.reference_id)
        self.assertEqual(view['privacy'],'local-only')

    def test_context_manifest_contains_actual_bytes_and_rechecks_pinned_source_proof(self):
        builder,prepared,authority,target=self.context()
        item=prepared.manifest['inputs'][0]
        self.assertEqual(item['source'],'cross-project-reference');self.assertTrue(item['read_only'])
        self.assertEqual(item['sha256'],self.pin['sha256'])
        self.assertEqual(item['reference']['source'],self.pin)
        content=base64.b64decode(json.loads(prepared.payload)['inputs'][0]['content_b64'])
        self.assertEqual(content,'Přesné původní bajty.\n'.encode())
        self.assertEqual(builder.authorize_for_dispatch(prepared,authority=authority,target=target).payload,prepared.payload)
        self.change_source()
        with self.assertRaisesRegex(ValidationError,'changed after preparation'):
            builder.authorize_for_dispatch(prepared,authority=authority,target=target)

    def test_context_without_actor_scoped_resolver_fails_closed(self):
        authority=Authority('no-resolver',self.author,str(uuid4()),'v1',frozenset({self.reference_id}))
        target=Target(str(uuid4()),'v1','same-node','runtime','model')
        with self.assertRaisesRegex(ValidationError,'resolver'):
            ContextBuilder(self.target_ws,self.target).prepare(manifest_id=str(uuid4()),run_id=str(uuid4()),
                authority=authority,target=target,project_inputs=(ProjectInput(self.reference_id),))

    def test_fork_is_explicit_new_identity_with_immutable_provenance_and_independent_edits(self):
        new_id=str(uuid4());preview=self.service.fork_preview(self.target,self.reference_id,new_id)
        with self.assertRaises(ValidationError):self.service.fork(preview,str(uuid4()),digest(encoded(preview)))
        operation=str(uuid4());receipt=self.service.fork(preview,operation,digest(encoded(preview)),confirm=True)
        files=self.target_ws.git.snapshot(receipt['commit_id']);meta=json.loads(files[f'artifacts/{new_id}/metadata.json'])
        self.assertEqual(json.loads(meta['description'])['source'],self.pin)
        self.assertIn(FORK,meta['tags']);self.assertEqual(files[f'artifacts/{new_id}/content.md'],'Přesné původní bajty.\n'.encode())
        self.artifacts.save(dict(project_id=self.target,artifact_id=new_id,base_head=self.target_ws.git.head(),title='Fork edit',body='Independent edit',new=False),str(uuid4()))
        self.assertEqual(base64.b64decode(self.service.view(self.target,self.reference_id)['content_b64']),'Přesné původní bajty.\n'.encode())
        self.assertEqual(self.service.fork(preview,operation,digest(encoded(preview)),confirm=True)['commit_id'],receipt['commit_id'])
        files=self.target_ws.git.snapshot(self.target_ws.git.head());meta=json.loads(files[f'artifacts/{new_id}/metadata.json']);meta['description']='Forged provenance'
        with self.assertRaisesRegex(ValidationError,'provenance'):
            self.target_ws.apply({f'artifacts/{new_id}/metadata.json':encoded(meta)},author_name='Local',author_email='local@example.invalid',message='Forge fork provenance')

    def test_fork_cannot_reuse_source_id(self):
        preview=self.service.fork_preview(self.target,self.reference_id,self.source_id)
        with self.assertRaisesRegex(ValidationError,'new source identity'):
            self.service.fork(preview,str(uuid4()),digest(encoded(preview)),confirm=True)

    def test_tampered_pin_unknown_version_and_cache_symlink_are_rejected(self):
        bad=dict(self.pin,sha256='0'*64)
        with self.assertRaisesRegex(ValidationError,'differs'):
            self.service.preview(self.target,str(uuid4()),bad,'Bad pin',share_id=self.share_id,reason_text='Důvod')
        files=self.target_ws.git.snapshot(self.target_ws.git.head());path=f'artifacts/{self.reference_id}/reference.json'
        changed=json.loads(files[path]);changed['schema']='fpw-artifact-reference-v3';files[path]=encoded(changed)
        with self.assertRaises(UnsupportedVersion) as caught:validate_snapshot(files)
        self.assertEqual((caught.exception.found,caught.exception.update),(3,'this-node'))
        changed['schema']=SCHEMA;del changed['share'];files[path]=encoded(changed)
        with self.assertRaises(ValidationError):validate_snapshot(files)
        cache=self.service._cache_path(self.pin);cache.unlink();cache.symlink_to(self.node)
        root=self.source_ws.git.root;offline=root.with_name('source-offline');root.rename(offline)
        self.addCleanup(lambda:offline.rename(root) if offline.exists() else None)
        with self.assertRaises(OSError):self.service.view(self.target,self.reference_id)

    def test_reference_index_rebuild_and_no_foreign_content_materialization(self):
        self.target_ws.index.path.unlink()
        index=self.service.index(self.target)
        self.assertEqual(index['references'][0]['source'],self.pin)
        self.assertEqual(index['commit_id'],self.target_ws.git.head())
        self.assertNotIn('content_b64',index['references'][0])
        self.assertEqual(self.target_ws.index.read(self.target_ws.git),[(self.reference_id,'Local reference label')])

    def test_same_operation_replays_and_stale_target_never_silently_rebases(self):
        self.assertEqual(self.service.write(self.preview,self.operation,digest(encoded(self.preview)),confirm=True)['commit_id'],self.receipt['commit_id'])
        updated=self.service.preview(self.target,self.reference_id,self.pin,'Renamed local label',update=True)
        self.artifacts.save(dict(project_id=self.target,artifact_id=str(uuid4()),base_head=self.target_ws.git.head(),title='Concurrent',body='edit',new=True),str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'target changed'):
            self.service.write(updated,str(uuid4()),digest(encoded(updated)),confirm=True)

    def test_real_process_crashes_recover_pointer_without_source_or_duplicate_commit(self):
        script='''
import json,os,sys
from spikes.cross_references import CrossReferences
from spikes.reporting_schema import encoded,digest
request=json.load(open(sys.argv[2]))
def checkpoint(stage):
 if stage==sys.argv[4]:os._exit(73)
CrossReferences(sys.argv[1]).write(request,sys.argv[3],digest(encoded(request)),confirm=True,checkpoint=checkpoint)
'''
        for stage in ['prepared','file:0','files-applied','commit-ready','before-ref','ref-updated','committed','indexed','completed']:
            with self.subTest(stage=stage):
                preview=self.service.preview(self.target,self.reference_id,self.pin,'Label '+stage,update=True)
                operation=str(uuid4());path=self.base/'write.json';path.write_bytes(encoded(preview))
                count=int(self.target_ws.git.run('rev-list','--count','HEAD').stdout)
                child=subprocess.run([sys.executable,'-c',script,str(self.node),str(path),operation,stage],capture_output=True,text=True,timeout=25)
                self.assertEqual(child.returncode,73,child.stderr)
                root=self.source_ws.git.root;offline=root.with_name('source-offline');root.rename(offline)
                try:
                    self.target_ws.recover()
                    result=self.service.write(preview,operation,digest(encoded(preview)),confirm=True)
                finally:offline.rename(root)
                self.assertEqual(result['commit_id'],self.target_ws.git.head())
                self.assertEqual(int(self.target_ws.git.run('rev-list','--count','HEAD').stdout),count+1)
                self.assertEqual(self.target_ws.git.run('status','--porcelain').stdout,'')

    def test_cli_pin_and_read_only_view(self):
        for args in [('pin',self.source,self.source_id),('view',self.target,self.reference_id),('index',self.target)]:
            result=subprocess.run([sys.executable,'-m','spikes.cross_references','--node',str(self.node),*args],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            value=json.loads(result.stdout)['value']
            if args[0]=='view':self.assertTrue(value['read_only'])

    def test_fork_crash_after_intent_recovers_without_source_and_no_duplicate_copy(self):
        preview=self.service.fork_preview(self.target,self.reference_id,str(uuid4()))
        operation=str(uuid4())
        def stop(stage):
            if stage=='prepared':raise RuntimeError('power loss simulation')
        with self.assertRaises(RuntimeError):
            self.service.fork(preview,operation,digest(encoded(preview)),confirm=True,checkpoint=stop)
        root=self.source_ws.git.root;offline=root.with_name('source-offline');root.rename(offline)
        self.addCleanup(lambda:offline.rename(root) if offline.exists() else None)
        receipt=self.service.fork(preview,operation,digest(encoded(preview)),confirm=True)
        self.assertEqual(receipt['commit_id'],self.target_ws.git.head())
        self.assertEqual(self.service.fork(preview,operation,digest(encoded(preview)),confirm=True)['commit_id'],receipt['commit_id'])
        self.assertIn(f"artifacts/{preview['new_id']}/content.md",self.target_ws.git.snapshot(receipt['commit_id']))

    def test_offline_cache_hash_tampering_cannot_supply_modified_bytes(self):
        path=self.service._cache_path(self.pin);value=json.loads(path.read_bytes())
        value['raw']=base64.b64encode(b'Forged bytes').decode();path.write_bytes(encoded(value))
        root=self.source_ws.git.root;offline=root.with_name('source-offline');root.rename(offline)
        self.addCleanup(lambda:offline.rename(root) if offline.exists() else None)
        with self.assertRaisesRegex(ValidationError,'hash mismatch'):self.service.view(self.target,self.reference_id)

    def test_pending_source_never_falls_back_to_cached_current_data(self):
        from spikes.workspace import PendingOperation
        def stop(stage):
            if stage=='prepared':raise RuntimeError('source pending')
        with self.assertRaises(RuntimeError):
            self.artifacts.save(dict(project_id=self.source,artifact_id=self.source_id,base_head=self.source_ws.git.head(),
                title='Pending source',body='Pending replacement',new=False),str(uuid4()),checkpoint=stop)
        with self.assertRaises(PendingOperation):self.service.view(self.target,self.reference_id)
        with self.assertRaises(PendingOperation):self.context()

    def test_delegated_request_scope_is_not_widened_by_global_node_owner_permissions(self):
        scoped=CrossReferences(self.node,user_id=self.author,allowed_projects={self.target},writable_projects=set())
        with self.assertRaises(AccessDenied):scoped.view(self.target,self.reference_id)
        with self.assertRaises(AccessDenied):self.context(service=scoped)
        scoped=CrossReferences(self.node,user_id=self.author,allowed_projects={self.target,self.source},writable_projects=set())
        self.assertTrue(scoped.view(self.target,self.reference_id)['read_only'])
        with self.assertRaises(AccessDenied):scoped.fork_preview(self.target,self.reference_id,str(uuid4()))

    def test_runnable_demo_keeps_old_bytes_until_user_confirms_update(self):
        destination=self.base/'isolated-demo'
        child=subprocess.run([sys.executable,'-m','scripts.reference_demo',str(destination)],capture_output=True,text=True,timeout=30)
        self.assertEqual(child.returncode,0,child.stderr)
        info=json.loads(child.stdout)
        self.assertEqual(info['state'],'newer-available')
        self.assertEqual(info['pinned_text'],'První připnutá revize.\n')
        payload=json.loads((destination/'context-payload.json').read_bytes())
        self.assertEqual(base64.b64decode(payload['inputs'][0]['content_b64']),'První připnutá revize.\n'.encode())
        self.assertTrue((destination/'update-preview.json').is_file())

    # XREF-02-A: explicit source share contract (ADR 0086).
    def test_new_reference_requires_live_share_listing_the_target(self):
        with self.assertRaises(ValidationError):
            self.service.preview(self.target,str(uuid4()),self.pin,'Bez sdílení')
        with self.assertRaises(ReferenceUnavailable) as caught:
            self.service.preview(self.target,str(uuid4()),self.pin,'Cizí ID',share_id=str(uuid4()),reason_text='Důvod')
        self.assertEqual(caught.exception.state,'not-shared')
        third=ProjectCreation(self.node).create('Third project',self.base/'third',str(uuid4()))['id']
        with self.assertRaises(ReferenceUnavailable) as caught:
            self.service.preview(third,str(uuid4()),self.pin,'Jiný cíl',share_id=self.share_id,reason_text='Důvod')
        self.assertEqual(caught.exception.state,'not-shared')
        other=self.share(targets=[third])
        view_id=str(uuid4())
        value=self.service.preview(third,view_id,self.pin,'Povolený cíl',share_id=other,reason_text='Důvod')
        self.service.write(value,str(uuid4()),digest(encoded(value)),confirm=True)
        self.assertEqual(self.service.view(third,view_id)['share']['share_id'],other)

    def test_share_record_is_canonical_audited_and_cannot_be_deleted(self):
        files=self.source_ws.git.snapshot(self.source_ws.git.head())
        record=json.loads(files[f'artifacts/{self.share_id}/share.json'])
        self.assertEqual((record['schema'],record['artifact_id'],record['purpose'],record['targets'],record['originator_id'],record['revoked']),
                         (SHARE,self.source_id,'share',[self.target],self.author,None))
        self.assertEqual(shares(files,validate_snapshot(files))[self.share_id],record)
        self.assertNotIn(b'Original source title',files[f'artifacts/{self.share_id}/metadata.json'])
        removed={k:v for k,v in files.items() if not k.startswith(f'artifacts/{self.share_id}/')}
        with self.assertRaisesRegex(ValidationError,'revoke'):validate_transition(files,removed)
        for change in (dict(originator_id=str(uuid4())),dict(artifact_id=str(uuid4())),dict(targets=[self.target,self.target]),
                       dict(purpose='output'),dict(purpose='unknown')):
            changed=dict(files);changed[f'artifacts/{self.share_id}/share.json']=encoded(dict(record,**change))
            with self.assertRaises(ValidationError):validate_transition(files,changed)
        revoked=dict(record,revoked=dict(at='2026-11-21T00:00:00Z',by=self.author))
        final=dict(files);final[f'artifacts/{self.share_id}/share.json']=encoded(revoked)
        validate_transition(files,final)
        again=dict(final);again[f'artifacts/{self.share_id}/share.json']=encoded(record)
        with self.assertRaisesRegex(ValidationError,'final'):validate_transition(final,again)

    def test_output_purpose_is_a_share_from_producer_to_consumer(self):
        share_id=str(uuid4())
        value=self.service.share_preview(self.source,share_id,self.source_id,[self.target],'Výsledek pro nadřazený projekt',purpose='output')
        self.assertEqual((value['record']['purpose'],value['title']),('output','Výstup projektu'))
        self.service.share_write(value,str(uuid4()),digest(encoded(value)),confirm=True)
        ref=str(uuid4())
        attach=self.service.preview(self.target,ref,self.pin,'Výstup',share_id=share_id,reason_text='Použití výstupu')
        self.service.write(attach,str(uuid4()),digest(encoded(attach)),confirm=True)
        self.assertEqual(self.service.view(self.target,ref)['state'],'current')
        with self.assertRaises(ValidationError):
            self.service.share_preview(self.source,str(uuid4()),self.source_id,[self.target],'Špatně',purpose='mirror')

    def test_forged_share_originator_or_artifact_is_not_a_grant(self):
        files=self.target_ws.git.snapshot(self.target_ws.git.head());path=f'artifacts/{self.reference_id}/reference.json'
        value=json.loads(files[path])
        for share in (dict(value['share'],originator_id=str(uuid4())),):
            with self.assertRaises(ReferenceUnavailable) as caught:
                self.service.live(value['source'],share=share,target=self.target)
            self.assertEqual(caught.exception.state,'not-shared')
        other=str(uuid4())
        self.artifacts.save(dict(project_id=self.source,base_head=self.source_ws.git.head(),artifact_id=other,
            title='Jiný',body='Jiný podklad.\n',new=True),str(uuid4()))
        with self.assertRaises(ReferenceUnavailable):
            self.service.preview(self.target,str(uuid4()),self.service.source_pin(self.source,other),'Jiný',
                                 share_id=self.share_id,reason_text='Důvod')

    def test_share_needs_source_write_and_visible_targets_and_attach_needs_source_read(self):
        reader,change,uid=self.user()
        with self.assertRaises(AccessDenied):
            reader.share_preview(self.source,str(uuid4()),self.source_id,[self.target],'Bez práva zápisu')
        third=ProjectCreation(self.node).create('Hidden project',self.base/'hidden',str(uuid4()))['id']
        change(action='update-user',user_id=uid,active=True,node_role='member',
               memberships={self.source:'editor',self.target:'editor'})
        with self.assertRaises(AccessDenied):
            reader.share_preview(self.source,str(uuid4()),self.source_id,[third],'Nepřístupný cíl')
        with self.assertRaisesRegex(ValidationError,'itself'):
            reader.share_preview(self.source,str(uuid4()),self.source_id,[self.source],'Sám do sebe')
        change(action='update-user',user_id=uid,active=True,node_role='member',memberships={self.target:'editor'})
        with self.assertRaises(AccessDenied):reader.view(self.target,self.reference_id)
        with self.assertRaises(AccessDenied):
            reader.preview(self.target,str(uuid4()),self.pin,'Bez zdroje',share_id=self.share_id,reason_text='Důvod')

    def test_reference_and_share_records_cannot_be_shared_again(self):
        with self.assertRaisesRegex(ValidationError,'shared'):
            self.service.share_preview(self.source,str(uuid4()),self.share_id,[self.target],'Řetěz')
        with self.assertRaises(ValidationError):
            self.service.share_preview(self.target,str(uuid4()),self.reference_id,[self.source],'Řetěz reference')

    def test_repin_keeps_share_provenance_and_shared_deletion_stays_valid(self):
        self.change_source()
        newer=self.service.view(self.target,self.reference_id)['newer']
        with self.assertRaises(ValidationError):
            self.service.preview(self.target,self.reference_id,newer,'Label',update=True,share_id=self.share_id,reason_text='Jiný důvod')
        value=self.service.preview(self.target,self.reference_id,newer,'Label',update=True)
        self.service.write(value,str(uuid4()),digest(encoded(value)),confirm=True)
        files=self.target_ws.git.snapshot(self.target_ws.git.head())
        self.assertEqual(json.loads(files[f'artifacts/{self.reference_id}/reference.json'])['share']['reason'],'Podklad pro cílový projekt')
        before=dict(files);path=f'artifacts/{self.reference_id}/reference.json'
        changed=dict(files);changed[path]=encoded(dict(json.loads(files[path]),share=dict(json.loads(files[path])['share'],reason='Přepsáno')))
        with self.assertRaisesRegex(ValidationError,'share provenance'):validate_transition(before,changed)
        source=self.source_ws.git.snapshot(self.source_ws.git.head())
        deleted={k:v for k,v in source.items() if not k.startswith(f'artifacts/{self.source_id}/')}
        self.assertIn(self.share_id,shares(deleted,validate_snapshot(deleted)))

    def test_legacy_v1_reference_still_resolves_and_repins_without_share(self):
        legacy=str(uuid4());ws=self.target_ws;head=ws.git.head()
        meta=dict(schema_version=1,id=legacy,title='Legacy',kind='document',created_at='2026-11-04T00:00:00Z',
                  author_id=self.author,privacy='project',provenance='user',file='reference.json',tags=[SCHEMA_V1])
        def prepare(workspace):
            return ({f'artifacts/{legacy}/metadata.json':encoded(meta),
                     f'artifacts/{legacy}/reference.json':encoded(dict(schema=SCHEMA_V1,source=self.pin))},
                    'Legacy','legacy@local.invalid','Legacy XREF-01 reference')
        ws.transact(str(uuid4()),dict(action='legacy-test'),prepare,expected_head=head)
        view=self.service.view(self.target,legacy)
        self.assertEqual((view['schema'],view['share'],view['state']),(SCHEMA_V1,None,'current'))
        self.change_source()
        value=self.service.preview(self.target,legacy,self.service.view(self.target,legacy)['newer'],'Legacy',update=True)
        self.service.write(value,str(uuid4()),digest(encoded(value)),confirm=True)
        files=ws.git.snapshot(ws.git.head())
        self.assertEqual(json.loads(files[f'artifacts/{legacy}/reference.json'])['schema'],SCHEMA_V1)

    def test_cli_creates_share_and_attaches_reference(self):
        def run(*args):
            child=subprocess.run([sys.executable,'-m','spikes.cross_references','--node',str(self.node),*args],
                                 capture_output=True,text=True,timeout=60)
            self.assertEqual(child.returncode,0,child.stderr);return json.loads(child.stdout)
        share_id,ref=str(uuid4()),str(uuid4())
        share=run('share-preview',self.source,share_id,self.source_id,'CLI důvod','--target',self.target,'--purpose','output')
        self.assertEqual(share['value']['record']['purpose'],'output')
        path=self.base/'share.json';path.write_text(json.dumps(share))
        run('share-write',str(path),'--operation-id',str(uuid4()),'--sha256',share['sha256'],'--confirm')
        pin=run('pin',self.source,self.source_id);pin_path=self.base/'pin.json';pin_path.write_text(json.dumps(pin))
        preview=run('preview',self.target,ref,str(pin_path),'CLI odkaz','--share',share_id,'--reason','CLI použití')
        prev=self.base/'prev.json';prev.write_text(json.dumps(preview))
        run('write',str(prev),'--operation-id',str(uuid4()),'--sha256',preview['sha256'],'--confirm')
        self.assertEqual(run('view',self.target,ref)['value']['share']['reason'],'CLI použití')
        revoke=run('revoke-preview',self.source,share_id);rev=self.base/'revoke.json';rev.write_text(json.dumps(revoke))
        run('revoke',str(rev),'--operation-id',str(uuid4()),'--sha256',revoke['sha256'],'--confirm')
        with self.assertRaises(ReferenceUnavailable) as caught:self.service.view(self.target,ref,offline=False)
        self.assertEqual(caught.exception.state,'share-revoked')
        detach=run('detach-preview',self.target,ref);det=self.base/'detach.json';det.write_text(json.dumps(detach))
        run('detach',str(det),'--operation-id',str(uuid4()),'--sha256',detach['sha256'],'--confirm')
        self.assertNotIn(ref,references(*self.target_files()))

    def target_files(self):
        files=self.target_ws.git.snapshot(self.target_ws.git.head());return files,validate_snapshot(files)

    def test_revocation_ends_future_access_but_keeps_audit_and_legitimate_fork(self):
        fork_id=str(uuid4());fork=self.service.fork_preview(self.target,self.reference_id,fork_id)
        self.service.fork(fork,str(uuid4()),digest(encoded(fork)),confirm=True)
        reader,change,uid=self.user()
        with self.assertRaises(AccessDenied):reader.revoke_preview(self.source,self.share_id)
        value=self.service.revoke_preview(self.source,self.share_id);sha=digest(encoded(value))
        with self.assertRaises(ValidationError):self.service.revoke(value,str(uuid4()),'0'*64,confirm=True)
        forged=dict(value,revoked=dict(value['revoked'],by=uid))
        with self.assertRaises(ValidationError):self.service.revoke(forged,str(uuid4()),digest(encoded(forged)),confirm=True)
        operation=str(uuid4());receipt=self.service.revoke(value,operation,sha,confirm=True)
        self.assertEqual(self.service.revoke(value,operation,sha,confirm=True),receipt)  # Lost response replays.
        files=self.source_ws.git.snapshot(self.source_ws.git.head())
        record=shares(files,validate_snapshot(files))[self.share_id]
        self.assertEqual(record['revoked'],dict(at=value['revoked']['at'],by=self.author))
        self.assertEqual({k:record[k] for k in ('artifact_id','targets','reason')},
                         {k:value['record'][k] for k in ('artifact_id','targets','reason')})
        with self.assertRaisesRegex(ValidationError,'already revoked'):self.service.revoke_preview(self.source,self.share_id)
        for attempt in (lambda:self.service.view(self.target,self.reference_id,offline=False),
                        lambda:self.service.view(self.target,self.reference_id),
                        lambda:self.service.fork_preview(self.target,self.reference_id,str(uuid4())),
                        lambda:self.context(),
                        lambda:self.service.preview(self.target,str(uuid4()),self.pin,'Znovu',share_id=self.share_id,reason_text='Znovu')):
            with self.assertRaises(ReferenceUnavailable) as caught:attempt()
            self.assertEqual(caught.exception.state,'share-revoked')
        target,entities=self.target_files()
        self.assertIn(self.reference_id,references(target,entities))  # The pointer stays as a visible state.
        self.assertEqual(target[f'artifacts/{fork_id}/{self.pin["path"].split("/")[-1]}'],'Přesné původní bajty.\n'.encode())
        self.assertIn(FORK,entities[fork_id]['tags'])

    def test_stale_revocation_preview_is_rejected(self):
        value=self.service.revoke_preview(self.source,self.share_id)
        self.share()
        with self.assertRaises(ValidationError):self.service.revoke(value,str(uuid4()),digest(encoded(value)),confirm=True)
        self.assertIsNone(shares(*(lambda f:(f,validate_snapshot(f)))(self.source_ws.git.snapshot(self.source_ws.git.head())))[self.share_id]['revoked'])

    def test_detach_removes_only_the_pointer_and_keeps_source_share_and_history(self):
        old_head=self.target_ws.git.head()
        reader,change,uid=self.user()
        change(action='update-user',user_id=uid,active=True,node_role='member',
               memberships={self.source:'reader',self.target:'reader'})
        with self.assertRaises(AccessDenied):reader.detach_preview(self.target,self.reference_id)
        value=self.service.detach_preview(self.target,self.reference_id)
        self.change_source();newer=self.service.view(self.target,self.reference_id)['newer']
        repin=self.service.preview(self.target,self.reference_id,newer,'Local reference label',update=True)
        self.service.write(repin,str(uuid4()),digest(encoded(repin)),confirm=True)
        with self.assertRaises(ValidationError):  # The reviewed pointer changed meanwhile.
            self.service.detach(value,str(uuid4()),digest(encoded(value)),confirm=True)
        value=self.service.detach_preview(self.target,self.reference_id);operation=str(uuid4())
        receipt=self.service.detach(value,operation,digest(encoded(value)),confirm=True)
        self.assertEqual(self.service.detach(value,operation,digest(encoded(value)),confirm=True),receipt)
        files,entities=self.target_files();self.assertNotIn(self.reference_id,entities)
        source=self.source_ws.git.snapshot(self.source_ws.git.head())
        self.assertIsNone(shares(source,validate_snapshot(source))[self.share_id]['revoked'])
        self.assertIn(self.source_id,validate_snapshot(source))
        self.assertIn('Podklad pro cílový'.encode(),self.target_ws.git.snapshot(old_head)[f'artifacts/{self.reference_id}/reference.json'])

    def test_repin_never_rewrites_an_already_prepared_manifest(self):
        builder,prepared,authority,target=self.context()
        pinned=deepcopy(prepared.manifest['inputs'][0])
        self.assertEqual(pinned['reference']['share']['share_id'],self.share_id)
        self.change_source();newer=self.service.view(self.target,self.reference_id)['newer']
        repin=self.service.preview(self.target,self.reference_id,newer,'Local reference label',update=True)
        self.service.write(repin,str(uuid4()),digest(encoded(repin)),confirm=True)
        self.assertEqual(prepared.manifest['inputs'][0],pinned)
        self.assertEqual(pinned['reference']['source'],self.pin)
        with self.assertRaises(ValidationError):  # Old evidence is never re-sent with new bytes.
            builder.authorize_for_dispatch(prepared,authority=authority,target=target)
        fresh=self.context()[1].manifest['inputs'][0]
        self.assertEqual(fresh['reference']['source'],newer)
        self.assertEqual(base64.b64decode(json.loads(self.context()[1].payload)['inputs'][0]['content_b64']),b'New source revision\n')

    def offline(self):
        root=self.source_ws.git.root;offline=root.with_name('source-offline');root.rename(offline)
        self.addCleanup(lambda:offline.rename(root) if offline.exists() else None)
        return lambda:offline.rename(root)

    def test_known_revocation_is_not_bypassed_by_any_users_offline_cache(self):
        member,change,uid=self.user()
        member.view(self.target,self.reference_id);self.service.view(self.target,self.reference_id)
        value=self.service.revoke_preview(self.source,self.share_id)
        self.service.revoke(value,str(uuid4()),digest(encoded(value)),confirm=True)
        with self.assertRaises(ReferenceUnavailable):self.service.view(self.target,self.reference_id)
        self.offline()
        for service in (self.service,member):  # Node owner included; the member never saw it live.
            with self.assertRaises(ReferenceUnavailable) as caught:service.view(self.target,self.reference_id)
            self.assertEqual(caught.exception.state,'share-revoked')

    def test_known_deletion_is_not_bypassed_by_offline_cache(self):
        member,change,uid=self.user();member.view(self.target,self.reference_id)
        self.service.view(self.target,self.reference_id)
        self.artifacts.delete(dict(project_id=self.source,artifact_id=self.source_id,base_head=self.source_ws.git.head()),str(uuid4()))
        with self.assertRaises(ReferenceUnavailable):member.view(self.target,self.reference_id)
        self.offline()
        with self.assertRaisesRegex(ReferenceUnavailable,'deleted'):self.service.view(self.target,self.reference_id)
        with self.assertRaises((OSError,ValueError)):self.context()  # Context never falls back to a cache.

    def test_target_specific_loss_does_not_hide_other_targets_and_live_success_clears_it(self):
        self.service.view(self.target,self.reference_id)
        self.service.forget(self.pin,self.service.local(self.target,self.reference_id)[1]['share'],'not-shared',str(uuid4()))
        self.service.view(self.target,self.reference_id)  # Other target only: cache is rebuilt and stays usable.
        share=self.service.local(self.target,self.reference_id)[1]['share']
        self.service.forget(self.pin,share,'not-shared',self.target)
        restore=self.offline()
        with self.assertRaisesRegex(ReferenceUnavailable,'not-shared'):self.service.view(self.target,self.reference_id)
        restore();self.assertEqual(self.service.view(self.target,self.reference_id)['state'],'current')
        self.offline();self.assertEqual(self.service.view(self.target,self.reference_id)['state'],'offline-stale')

    def run_crashing(self, method, preview, stage, operation):
        script='''
import json,os,sys
from spikes.cross_references import CrossReferences
from spikes.reporting_schema import encoded,digest
request=json.load(open(sys.argv[2]))
def checkpoint(stage):
 if stage==sys.argv[4]:os._exit(73)
getattr(CrossReferences(sys.argv[1]),sys.argv[5])(request,sys.argv[3],digest(encoded(request)),confirm=True,checkpoint=checkpoint)
'''
        path=self.base/f'{method}.json';path.write_bytes(encoded(preview))
        child=subprocess.run([sys.executable,'-c',script,str(self.node),str(path),operation,stage,method],
                             capture_output=True,text=True,timeout=25)
        self.assertEqual(child.returncode,73,child.stderr)

    def test_real_process_crashes_of_share_revoke_and_detach_recover_without_duplicates(self):
        stages=['prepared','files-applied','before-ref','committed','completed']
        cases=[('share_write',self.source_ws,lambda:self.service.share_preview(self.source,str(uuid4()),self.source_id,[self.target],'Pád')),
               ('revoke',self.source_ws,lambda:self.service.revoke_preview(self.source,self.share())),
               ('detach',self.target_ws,lambda:self.attach_new())]
        for method,ws,make in cases:
            for stage in stages:
                with self.subTest(method=method,stage=stage):
                    preview=make();operation=str(uuid4())
                    count=int(ws.git.run('rev-list','--count','HEAD').stdout)
                    self.run_crashing(method,preview,stage,operation)
                    ws.recover()  # Lost response: the same confirmation replays the receipt.
                    result=getattr(self.service,method)(preview,operation,digest(encoded(preview)),confirm=True)
                    self.assertEqual(result['commit_id'],ws.git.head())
                    self.assertEqual(int(ws.git.run('rev-list','--count','HEAD').stdout),count+1)
                    self.assertEqual(ws.git.run('status','--porcelain').stdout,'')

    def attach_new(self):
        ref=str(uuid4());value=self.service.preview(self.target,ref,self.service.source_pin(self.source,self.source_id),
                                                     'Další odkaz',share_id=self.share_id,reason_text='Pád')
        self.service.write(value,str(uuid4()),digest(encoded(value)),confirm=True)
        return self.service.detach_preview(self.target,ref)

    def test_attach_crash_after_source_read_completes_and_later_revocation_wins(self):
        ref=str(uuid4());value=self.service.preview(self.target,ref,self.pin,'Po pádu',share_id=self.share_id,reason_text='Pád')
        operation=str(uuid4());self.run_crashing('write',value,'prepared',operation)
        revoke=self.service.revoke_preview(self.source,self.share_id)
        self.service.revoke(revoke,str(uuid4()),digest(encoded(revoke)),confirm=True)
        self.target_ws.recover()  # The journal holds the approved descriptor; no new source read is needed.
        receipt=self.service.write(value,operation,digest(encoded(value)),confirm=True)
        self.assertEqual(receipt['commit_id'],self.target_ws.git.head())
        self.assertIn(ref,references(*self.target_files()))
        with self.assertRaisesRegex(ReferenceUnavailable,'share-revoked'):self.service.view(self.target,ref)

    def test_project_export_carries_only_the_descriptor_never_source_bytes(self):
        from spikes.git_transfer import export_bundle
        payload,head,count=export_bundle(self.node,self.target,frozenset({'public','project','confidential'}))
        bundle=self.base/'target.bundle';bundle.write_bytes(payload);clone=self.base/'clone'
        subprocess.run(['git','clone','-q',str(bundle),str(clone)],check=True,capture_output=True)
        revs=subprocess.run(['git','-C',str(clone),'rev-list','--all'],check=True,capture_output=True,text=True).stdout.split()
        found=subprocess.run(['git','-C',str(clone),'grep','-l','Přesné původní bajty',*revs],capture_output=True,text=True)
        self.assertEqual(found.stdout,'')
        names=subprocess.run(['git','-C',str(clone),'ls-tree','-r','--name-only',head],capture_output=True,text=True,check=True).stdout
        self.assertIn(f'artifacts/{self.reference_id}/reference.json',names)


if __name__=='__main__':unittest.main()
