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
from spikes.metadata import ValidationError, validate_snapshot
from spikes.project_creation import ProjectCreation
from spikes.reference_schema import SCHEMA, FORK, references
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
        self.pin=self.service.source_pin(self.source,self.source_id)
        self.preview=self.service.preview(self.target,self.reference_id,self.pin,'Local reference label')
        self.operation=str(uuid4())
        self.receipt=self.service.write(self.preview,self.operation,digest(encoded(self.preview)),confirm=True)

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
        self.assertEqual(json.loads(pointer),dict(schema=SCHEMA,source=self.pin))
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
        with self.assertRaisesRegex(ValidationError,'differs'):self.service.preview(self.target,str(uuid4()),bad,'Bad pin')
        files=self.target_ws.git.snapshot(self.target_ws.git.head());path=f'artifacts/{self.reference_id}/reference.json'
        changed=json.loads(files[path]);changed['schema']='fpw-artifact-reference-v2';files[path]=encoded(changed)
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


if __name__=='__main__':unittest.main()
