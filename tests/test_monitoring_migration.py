# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_reporting as fixtures
from tests.test_monitoring_workflow import workflow
from tests.test_monitoring_blocks import response
from spikes.monitoring import Monitoring
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.monitoring_migration import MonitoringMigration,retired_ids
from spikes.monitoring_placement import local_node_id
from spikes.projects import Projects
from spikes.reporting_schema import encoded
from spikes.metadata import ValidationError


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.monitoring=Monitoring(self.f.node,Projects(self.f.node))
        self.migration=MonitoringMigration(self.monitoring)
        request=workflow(self.f.project,self.f.git.head())
        self.saved=MonitoringDefinitions(self.f.node).save_workflow(request,str(uuid4()))
        self.ids=sorted(s['watch_id'] for s in self.saved['stages'].values())
        self.node_id=local_node_id(self.f.node)

    def preview(self):return self.migration.preview(self.f.project,self.ids,30,self.node_id)

    def apply(self,preview=None,operation=None,**kwargs):
        preview=preview or self.preview()
        return self.migration.apply(self.f.project,self.ids,30,self.node_id,preview['preview_sha256'],operation or str(uuid4()),confirm=True,**kwargs)

    def test_preview_is_readonly_exact_and_conversion_is_idempotent(self):
        head=self.f.git.head();p=self.preview()
        self.assertEqual(p['issues'],[]);self.assertEqual(len(p['blocks']),5)
        self.assertEqual(head,self.f.git.head())
        operation=str(uuid4());result=self.apply(p,operation)
        self.assertEqual(result,self.apply(p,operation));head=self.f.git.head()
        self.assertEqual(self.migration.resume(self.f.project,operation),result)
        self.assertEqual(self.f.git.head(),head)
        self.assertEqual(retired_ids(self.f.node,self.f.project),set(self.ids))
        catalog=self.monitoring.composable.catalog(self.f.project)
        self.assertEqual(len(catalog['blocks']),5);self.assertTrue(all(b['runtime'] is None for b in catalog['blocks']))
        with self.assertRaisesRegex(ValidationError,'již bylo'):self.preview()
        rows=MonitoringDefinitions(self.f.node).read(self.f.project)['definitions']
        self.assertTrue(all(r['converted'] for r in rows))

    def test_stale_preview_and_wrong_digest_have_no_project_effect(self):
        p=self.preview();head=self.f.git.head()
        with self.assertRaisesRegex(ValidationError,'Náhled'):
            self.migration.apply(self.f.project,self.ids,30,self.node_id,'0'*64,str(uuid4()),confirm=True)
        self.assertEqual(self.f.git.head(),head)
        from spikes.artifacts import Artifacts
        Artifacts(self.f.node).save(dict(project_id=self.f.project,artifact_id=str(uuid4()),title='Other change',body='Unrelated',base_head=head,new=True),str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'Náhled'):self.apply(p)

    def test_old_execution_and_editing_are_disabled_but_history_remains(self):
        originals={s['definition_ref']['path']:self.f.git.snapshot(self.f.git.head())[s['definition_ref']['path']] for s in self.saved['stages'].values()}
        self.apply()
        snapshot=self.f.git.snapshot(self.f.git.head())
        for path,raw in originals.items():self.assertEqual(snapshot[path],raw)
        collection=self.saved['stages']['collection'];processing=self.saved['stages']['processing']
        cfg=dict(project_id=self.f.project,watch_id=collection['watch_id'],definition_ref=collection['definition_ref'],
            input_id=json.loads(originals[collection['definition_ref']['path']])['value']['inputs'][0]['id'],enabled=True,mode='pipeline')
        with self.assertRaisesRegex(ValidationError,'převedeno'):self.monitoring.rss_runtime.configure(cfg,confirm=True)
        with self.assertRaisesRegex(ValidationError,'převedeno'):
            MonitoringDefinitions(self.f.node).run_workflow(self.f.project,processing['definition_ref'],'2026-10-05')
        definition=json.loads(originals[collection['definition_ref']['path']])['value']
        with self.assertRaisesRegex(ValidationError,'převedeno'):
            MonitoringDefinitions(self.f.node).save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=collection['watch_id'],previous=[collection['definition_ref']],privacy='project',definition=definition),str(uuid4()))

    def collect(self):
        row=self.saved['stages']['collection']
        pin=row['definition_ref'];definition=json.loads(self.f.git.snapshot(pin['commit_id'])[pin['path']])['value']
        # test_monitoring_workflow's default keyword selects "first".
        self.monitoring.rss_runtime.fetcher=lambda *a,**k:response('first energy evidence')
        self.monitoring.rss_runtime.configure(dict(project_id=self.f.project,watch_id=row['watch_id'],
            definition_ref=pin,input_id=definition['inputs'][0]['id'],enabled=True,mode='pipeline'),confirm=True)
        self.monitoring.rss_runtime.tick(self.f.project)

    def test_selected_findings_are_imported_once_with_exact_original_provenance(self):
        self.collect();p=self.preview();self.assertEqual(p['issues'],[])
        self.assertEqual(len(p['findings']),1)
        result=self.apply(p);self.assertEqual(result['imported_findings'],1)
        pool=next(b for b in p['blocks'] if b['value']['kind']=='pool')
        rows=self.monitoring.composable.pools.view(self.f.project,pool['id'])
        self.assertEqual(len(rows),1);self.assertIn('first energy evidence',rows[0]['revisions'][0]['item']['content'])
        data=self.monitoring.reporting.read(self.f.project)
        marker=next(r for r in data['records'] if r['type']=='MonitoringMigration')
        self.assertEqual(marker['value']['finding_refs'],[p['findings'][0]['ref']])
        self.assertFalse(self.monitoring.rss_runtime.status(self.f.project)['bindings'][0]['enabled'])

    def test_unknown_rss_poll_blocks_migration_until_reconciled(self):
        row=self.saved['stages']['collection'];pin=row['definition_ref'];d=json.loads(self.f.git.snapshot(pin['commit_id'])[pin['path']])['value']
        self.monitoring.rss_runtime.configure(dict(project_id=self.f.project,watch_id=row['watch_id'],definition_ref=pin,
            input_id=d['inputs'][0]['id'],enabled=True,mode='pipeline'),confirm=True)
        def lost(*a,**k):raise TimeoutError('interrupted')
        self.monitoring.rss_runtime.fetcher=lost;self.monitoring.rss_runtime.tick(self.f.project)
        p=self.preview();self.assertTrue(any('RSS' in i['reason'] for i in p['issues']))
        with self.assertRaisesRegex(ValidationError,'nevyřešené'):self.apply(p)
        self.assertEqual(retired_ids(self.f.node,self.f.project),set())

    def test_report_chain_is_blocked_instead_of_silently_flattened(self):
        from tests.test_monitoring_definitions import definition
        value=definition('Monthly','monthly',upstream=self.saved['stages']['processing']['watch_id'])
        MonitoringDefinitions(self.f.node).save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=str(uuid4()),previous=[],privacy='project',definition=value),str(uuid4()))
        p=self.preview();self.assertTrue(any('Navazující' in i['reason'] for i in p['issues']))
        with self.assertRaisesRegex(ValidationError,'nevyřešené'):self.apply(p)

    def test_process_crashes_resume_same_operation_without_new_commit_or_fetch(self):
        script='''
import json,os,sys
from spikes.monitoring import Monitoring
from spikes.monitoring_migration import MonitoringMigration
from spikes.projects import Projects
m=MonitoringMigration(Monitoring(sys.argv[1],Projects(sys.argv[1])))
p=json.load(open(sys.argv[2]))
def stop(stage):
 if stage==sys.argv[4]:os._exit(73)
m.apply(p['project_id'],[s['id'] for s in p['sources']],p['retention_days'],p['processing_node_id'],p['preview_sha256'],sys.argv[3],confirm=True,checkpoint=stop)
'''
        # One fixture per boundary preserves deterministic source identity and ids.
        for stage in ('migration-prepared','prepared','before-ref','ref-updated','migration-definitions','pool-inserted','migration-pools','migration-paused','migration-completed'):
            with self.subTest(stage=stage):
                f=MigrationTests('test_preview_is_readonly_exact_and_conversion_is_idempotent');f.setUp()
                try:
                    f.collect();p=f.preview();op=str(uuid4());path=f.f.base/'migration.json';path.write_bytes(encoded(p))
                    count=int(f.f.git.run('rev-list','--count','HEAD').stdout)
                    result=subprocess.run([sys.executable,'-c',script,str(f.f.node),str(path),op,stage],capture_output=True,text=True,timeout=40)
                    self.assertEqual(result.returncode,73,result.stderr)
                    f.f.ws.recover()
                    if stage in {'ref-updated','migration-definitions','pool-inserted','migration-pools','migration-paused'}:
                        source=next(b for b in p['blocks'] if b['value']['kind']=='source')
                        with self.assertRaisesRegex(ValidationError,'dokončete'):
                            f.monitoring.composable.configure(f.f.project,source['id'],True,confirm=True)
                    with patch('spikes.rss_reader.fetch_response',side_effect=AssertionError('No new fetch')):
                        saved=f.migration.resume(f.f.project,op)
                    self.assertEqual(saved,f.migration.resume(f.f.project,op))
                    self.assertEqual(int(f.f.git.run('rev-list','--count','HEAD').stdout),count+1)
                    pool=next(b for b in p['blocks'] if b['value']['kind']=='pool')
                    self.assertEqual(len(f.monitoring.composable.pools.view(f.f.project,pool['id'])),1)
                finally:f.doCleanups()

    def test_multi_period_document_watch_requires_explicit_pools_then_converts_all_periods(self):
        from spikes.monitoring import PROFILES
        from spikes.monitoring_blocks import MonitoringBlocks
        from tests.test_monitoring_blocks import block
        legacy=dict(id=str(uuid4()),name='Original multi-period',goal='Track sources',active=False,privacy='project',timezone='Europe/Prague',
            start='2026-03-23',inputs=[self.f.policy_id],urls=[],access_note='',periods=dict(PROFILES),presentation=True,
            mode='deterministic',binding=None,tags=['history'])
        self.monitoring.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch=legacy,new=True),str(uuid4()))
        p=self.migration.preview(self.f.project,[legacy['id']],30,self.node_id)
        self.assertTrue(p['issues'])
        pool=block('pool','Explicit new inputs',dict(retention_days=30))
        MonitoringBlocks(self.f.node).save(self.f.project,self.f.git.head(),[pool],str(uuid4()))
        mapping={legacy['id']:[pool['id']]}
        p=self.migration.preview(self.f.project,[legacy['id']],30,self.node_id,pool_bindings=mapping)
        self.assertFalse(p['issues']);self.assertEqual(len([b for b in p['blocks'] if b['value']['kind']=='processing']),4)
        self.migration.apply(self.f.project,[legacy['id']],30,self.node_id,p['preview_sha256'],str(uuid4()),confirm=True,pool_bindings=mapping)
        self.assertFalse(self.monitoring.granted(self.f.project,legacy))
        with self.assertRaisesRegex(ValidationError,'převedeno'):
            self.monitoring.save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch=legacy,new=False),str(uuid4()))

    def test_import_preserves_original_observer_and_deduplicates_future_intake(self):
        self.collect();p=self.preview();observer=p['findings'][0]['observer_node_id']
        self.apply(p)
        pool=next(b for b in p['blocks'] if b['value']['kind']=='pool')
        current=self.monitoring.composable.pools.view(self.f.project,pool['id'])
        self.assertEqual(current[0]['observations'][0]['node_id'],observer)
        source=next(b for b in p['blocks'] if b['value']['kind']=='source')
        runtime=self.monitoring.composable;runtime.fetcher=lambda *a,**kw:response('first energy evidence')
        runtime.configure(self.f.project,source['id'],True,confirm=True);runtime.tick(self.f.project)
        view=runtime.pools.view(self.f.project,pool['id'])
        self.assertEqual(len(view),1);self.assertEqual(len(view[0]['revisions']),1)

    def test_migration_receipt_inherits_explicit_pool_privacy(self):
        from spikes.monitoring_blocks import MonitoringBlocks
        from tests.test_monitoring_blocks import block
        pool=block('pool','Confidential inputs',dict(retention_days=30));pool['privacy']='confidential'
        MonitoringBlocks(self.f.node).save(self.f.project,self.f.git.head(),[pool],str(uuid4()))
        processing=self.saved['stages']['processing']['watch_id']
        # Include collection to retire both old stages; explicit mapping replaces processing inputs.
        mapping={processing:[pool['id']]}
        p=self.migration.preview(self.f.project,self.ids,30,self.node_id,pool_bindings=mapping)
        self.assertFalse(p['issues'])
        self.migration.apply(self.f.project,self.ids,30,self.node_id,p['preview_sha256'],str(uuid4()),confirm=True,pool_bindings=mapping)
        marker=next(r for r in self.monitoring.reporting.read(self.f.project)['records'] if r['type']=='MonitoringMigration')
        self.assertEqual(marker['privacy'],'confidential')

    def test_unknown_original_observer_is_preserved_as_unknown(self):
        self.collect();p=self.preview();p['findings'][0]['observer_node_id']=None
        rows=self.migration._pool_rows(self.f.project,p,str(uuid4()))
        from spikes.message_pools import validate_entry
        for row in rows:validate_entry(row,self.f.project)
        self.assertIsNone(next(r for r in rows if r['kind']=='observation')['value']['node_id'])

    def test_precommit_stale_intent_can_be_cancelled_but_committed_conversion_cannot(self):
        p=self.preview();operation=str(uuid4());changed=[False]
        def race(stage):
            if stage=='migration-prepared' and not changed[0]:
                changed[0]=True
                from spikes.artifacts import Artifacts
                Artifacts(self.f.node).save(dict(project_id=self.f.project,base_head=self.f.git.head(),artifact_id=str(uuid4()),title='Concurrent edit',body='Other work',new=True),str(uuid4()))
        with self.assertRaises(ValidationError):self.apply(p,operation,checkpoint=race)
        self.assertTrue(any('migration' in issue['reason'] for issue in self.preview()['issues']))
        self.assertEqual(self.migration.cancel(self.f.project,operation,confirm=True),dict(cancelled=True))
        self.assertEqual(self.migration.inventory(self.f.project)['pending'],[])
        p=self.preview();committed=str(uuid4());self.apply(p,committed)
        with self.assertRaisesRegex(ValidationError,'již byly uloženy'):
            self.migration.cancel(self.f.project,committed,confirm=True)

    def test_migration_audit_can_pin_a_bounded_feed_history_without_relaxing_other_records(self):
        from spikes.reporting_schema import validate_record
        self.apply()
        row=deepcopy(next(r for r in self.monitoring.reporting.read(self.f.project)['records'] if r['type']=='MonitoringMigration'))
        base=deepcopy(row['provenance']['inputs'][0])
        refs=[]
        for _ in range(500):
            r=deepcopy(base);r['artifact_id']=str(uuid4());r['path']='artifacts/'+r['artifact_id']+'/record.json';refs.append(r)
        row['value']['finding_refs']=refs;row['provenance']['inputs']=refs+row['provenance']['inputs']
        validate_record(row)
        other=self.f.record(self.f.task);other['provenance']['inputs']=refs
        with self.assertRaisesRegex(ValidationError,'list'):validate_record(other)
        row['provenance']['inputs']*=2
        with self.assertRaisesRegex(ValidationError,'provenance'):validate_record(row)

    def test_channel_name_predicates_are_not_silently_reinterpreted(self):
        source=self.saved['stages']['collection'];pin=source['definition_ref']
        value=json.loads(self.f.git.snapshot(pin['commit_id'])[pin['path']])['value']
        value['selection']['pipeline']['steps'].insert(0,dict(id='channel',kind='restrict',channels=['Original feed name'],languages=[],required_fields=[]))
        MonitoringDefinitions(self.f.node).save(dict(project_id=self.f.project,base_head=self.f.git.head(),watch_id=source['watch_id'],previous=[pin],privacy='project',definition=value),str(uuid4()))
        p=self.preview();self.assertTrue(any('názvu kanálu' in issue['reason'] for issue in p['issues']))
        with self.assertRaisesRegex(ValidationError,'nevyřešené'):self.apply(p)


class MigrationSyncTests(unittest.TestCase):
    def test_signed_sync_transfers_retirement_and_pool_without_grants_or_relabeling_observer(self):
        from tests import test_federation_sync as fixture
        f=fixture.FederationSyncTests('test_initial_import_and_fast_forward_work_in_both_directions')
        f.setUp();self.addCleanup(f.doCleanups)
        monitoring=Monitoring(f.nodes[0],Projects(f.nodes[0]));migration=MonitoringMigration(monitoring)
        saved=MonitoringDefinitions(f.nodes[0]).save_workflow(workflow(f.project_id,monitoring.projects.repository(f.project_id).head()),str(uuid4()))
        ids=[r['watch_id'] for r in saved['stages'].values()]
        source=saved['stages']['collection'];pin=source['definition_ref']
        git=monitoring.projects.repository(f.project_id);value=json.loads(git.snapshot(pin['commit_id'])[pin['path']])['value']
        monitoring.rss_runtime.fetcher=lambda *a,**k:response('first remote evidence')
        monitoring.rss_runtime.configure(dict(project_id=f.project_id,watch_id=source['watch_id'],input_id=value['inputs'][0]['id'],definition_ref=pin,enabled=True,mode='pipeline'),confirm=True)
        monitoring.rss_runtime.tick(f.project_id)
        f.exchange(0,1)
        p=migration.preview(f.project_id,ids,30,f.node_ids[0]);self.assertFalse(p['issues'])
        migration.apply(f.project_id,ids,30,f.node_ids[0],p['preview_sha256'],str(uuid4()),confirm=True)
        f.exchange(0,1)
        other=Monitoring(f.nodes[1],Projects(f.nodes[1]))
        self.assertEqual(retired_ids(f.nodes[1],f.project_id),set(ids))
        self.assertTrue(all(b['runtime'] is None for b in other.composable.catalog(f.project_id)['blocks']))
        pool=next(b for b in p['blocks'] if b['value']['kind']=='pool')
        rows=other.composable.pools.view(f.project_id,pool['id'])
        self.assertEqual(len(rows),1)
        self.assertEqual({o['node_id'] for o in rows[0]['observations']},{f.node_ids[0]})
        with self.assertRaisesRegex(ValidationError,'převedeno'):
            MonitoringDefinitions(f.nodes[1]).run_workflow(f.project_id,saved['stages']['processing']['definition_ref'],'2026-10-05')
