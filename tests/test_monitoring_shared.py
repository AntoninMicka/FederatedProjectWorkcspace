# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Two-node signed exchange of activation and non-operational report outcomes."""
from copy import deepcopy
import json
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_message_pool_sync as fixtures
from spikes.composable_monitoring import ComposableMonitoring
from spikes.message_pools import entry
from spikes import monitoring_shared as shared
from spikes.metadata import ValidationError


class SharedMonitoringTests(unittest.TestCase):
    def setUp(self):
        fixtures.PoolSyncTests.setUp(self)
        self.instant=[time.time()]
        for s in self.services:
            s.clock=s.monitoring.clock=s.pools.clock=lambda:self.instant[0]

    def rows(self,node=0):
        with self.services[node].pools.read_db() as db:return shared.read_rows(db,self.pid)

    def local_jobs(self,node=0):
        with self.services[node].pools.read_db() as db:
            return [(r[0],r[1],json.loads(r[2])) for r in db.execute('SELECT id,state,document FROM block_jobs WHERE project=?',(self.pid,))]

    def job(self,id_,node=0):
        return next(j for j in self.services[node].catalog(self.pid)['jobs'] if j['id']==id_)

    def llm(self):
        s=self.services[0];b=next(b for b in s.blocks.read(self.pid)['blocks'] if b['id']==self.specs[3]['id'])
        spec=deepcopy(self.specs[3]);spec['previous']=[b['ref']];spec['value']['config']['mode']='llm'
        s.blocks.save(self.pid,s.blocks.read(self.pid)['commit_id'],[spec],str(uuid4()));self.f.exchange(0,1)

    def test_activation_and_pause_transfer_but_only_assigned_node_runs_schedule(self):
        a,b=self.services
        block=next(r for r in a.blocks.read(self.pid)['blocks'] if r['id']==self.specs[3]['id'])
        spec=deepcopy(self.specs[3]);spec['previous']=[block['ref']];spec['value']['config']['schedule'].update(kind='daily',time='00:00')
        a.blocks.save(self.pid,a.blocks.read(self.pid)['commit_id'],[spec],str(uuid4()));self.f.exchange(0,1)
        b.configure(self.pid,self.specs[0]['id'],True,confirm=True)
        b.configure(self.pid,spec['id'],True,confirm=True)  # from the non-executor
        self.f.exchange(1,0)
        a.tick(self.pid);b.tick(self.pid)
        self.assertTrue(next(r for r in a.catalog(self.pid)['blocks'] if r['id']==spec['id'])['runtime']['enabled'])
        self.assertEqual(sum(j[2].get('kind')=='processing' for j in self.local_jobs(0)),1)
        self.assertFalse(any(j[2].get('kind')=='processing' for j in self.local_jobs(1)))
        a.configure(self.pid,spec['id'],False,confirm=True);a.configure(self.pid,self.specs[0]['id'],False,confirm=True)
        self.f.exchange(0,1);self.f.exchange(0,1)
        self.instant[0]+=86400
        a.tick(self.pid);b.tick(self.pid)
        for s in self.services:
            self.assertFalse(next(r for r in s.catalog(self.pid)['blocks'] if r['id']==spec['id'])['runtime']['enabled'])
        self.assertEqual(sum(j[2].get('kind')=='processing' for j in self.local_jobs(0)),1)

    def test_shared_draft_reprocesses_on_clicking_node_with_its_own_model(self):
        self.llm();a,b=self.services;run=str(uuid4())
        with patch.object(a,'_model',return_value='První zpráva') as model:
            first=a.process(self.pid,self.specs[3]['id'],run);self.assertEqual(model.call_count,1)
        self.f.exchange(0,1)
        job=self.job(run,1);self.assertTrue(job['shared']);self.assertEqual(job['result']['markdown'],'První zpráva')
        self.assertFalse(any(j[0]==run for j in self.local_jobs(1)))
        serialized=json.dumps(job['intent'])
        self.assertNotIn('manifest',serialized);self.assertNotIn('credentials',serialized)
        self.instant[0]=first['result']['protection']['until']
        with patch.object(b,'_model',return_value='Lokálně přepracovaná zpráva') as model:
            new=b.reprocess(self.pid,run,str(uuid4()),confirm=True);self.assertEqual(model.call_count,1)
        self.assertEqual(self.job(new['id'],1)['intent']['executor_node_id'],self.f.node_ids[1])
        self.assertEqual(self.job(run,1)['intent']['executor_node_id'],self.f.node_ids[0])
        self.f.exchange(1,0)
        self.assertEqual(self.job(new['id'],0)['result']['markdown'],'Lokálně přepracovaná zpráva')

    def test_error_transfers_without_secrets_and_explicit_retry_is_local(self):
        self.llm();a,b=self.services;run=str(uuid4())
        with patch.object(a,'_model',side_effect=TimeoutError('Model nedostupný; Bearer SECRET api_key=HIDDEN https://user:PASS@example.org/api?token=QUERY {"api_key":"JSON-SECRET"}')):
            with self.assertRaises(TimeoutError):a.process(self.pid,self.specs[3]['id'],run)
        self.f.exchange(0,1)
        job=self.job(run,1);self.assertEqual(job['state'],'unknown')
        error=job['result']['error'];self.assertIn('Model nedostupný',error)
        for secret in ['SECRET','HIDDEN','PASS','QUERY','JSON-SECRET']:self.assertNotIn(secret,error)
        self.assertFalse(any(j[0]==run for j in self.local_jobs(1)))
        with patch.object(b,'_model',return_value='Ruční oprava na druhém uzlu') as model:
            new=b.reprocess(self.pid,run,str(uuid4()),confirm=True);self.assertEqual(model.call_count,1)
        self.assertEqual(new['state'],'review');self.assertEqual(self.job(run,1)['state'],'unknown')

    def test_concurrent_activation_conflict_preserves_pause_and_explicit_resolution(self):
        a,b=self.services;source=self.specs[0]['id']
        a.configure(self.pid,source,True,confirm=True);self.f.exchange(0,1)
        a.configure(self.pid,source,True,confirm=True);b.configure(self.pid,source,False,confirm=True)
        self.f.exchange(0,1);self.f.exchange(1,0)
        for s in self.services:
            runtime=next(r for r in s.catalog(self.pid)['blocks'] if r['id']==source)['runtime']
            self.assertFalse(runtime['enabled']);self.assertTrue(runtime['activation_conflict'])
        a.configure(self.pid,source,True,confirm=True);self.f.exchange(0,1)
        runtime=next(r for r in b.catalog(self.pid)['blocks'] if r['id']==source)['runtime']
        self.assertTrue(runtime['enabled']);self.assertFalse(runtime['activation_conflict'])

    def test_activation_crash_rolls_back_state_and_causal_record_together(self):
        s=self.services[0];before=self.rows()
        def crash(stage):raise SystemExit('power loss')
        with self.assertRaises(SystemExit):s.configure(self.pid,self.specs[0]['id'],True,confirm=True,checkpoint=crash)
        self.assertEqual(self.rows(),before)
        self.assertIsNone(next(r for r in s.catalog(self.pid)['blocks'] if r['id']==self.specs[0]['id'])['runtime'])

    def test_result_commit_and_share_are_atomic_and_dispatch_recovery_never_calls_model(self):
        a,b=self.services
        for stage in ['processing-dispatching','processing-result','processing-committed']:
            run=str(uuid4())
            def crash(current):
                if current==stage:raise SystemExit('power loss')
            with self.assertRaises(SystemExit):a._attempt(self.pid,self.specs[3]['id'],run,checkpoint=crash)
            restarted=ComposableMonitoring(a.monitoring)
            with patch.object(restarted,'_model',side_effect=AssertionError('automatic paid retry')):
                restarted.tick(self.pid,lane='processing')
            self.f.exchange(0,1)
            job=self.job(run,1)
            self.assertEqual(job['state'],'review' if stage=='processing-committed' else 'unknown')
            self.assertFalse(any(j[0]==run for j in self.local_jobs(1)))

    def test_remote_review_publication_is_shared_without_worker_journal_import(self):
        a,b=self.services;first=a.process(self.pid,self.specs[3]['id'],str(uuid4()))
        self.instant[0]=first['result']['protection']['until'];a.tick(self.pid,lane='processing');self.f.exchange(0,1)
        job=self.job(first['id'],1)
        issued=b.publish(self.pid,first['id'],job['result']['approval_digest'],confirm=True)
        self.assertFalse(any(j[0]==first['id'] for j in self.local_jobs(1)))
        self.f.exchange(1,0)
        self.assertEqual(self.job(first['id'])['state'],'published')
        self.assertEqual(a.publish(self.pid,first['id'],job['result']['approval_digest'],confirm=True)['report_ref'],issued['report_ref'])

    def test_received_period_result_prevents_repeat_after_executor_definition_change(self):
        self.llm();a,b=self.services
        block=next(x for x in a.blocks.read(self.pid)['blocks'] if x['id']==self.specs[3]['id'])
        spec=deepcopy(self.specs[3]);spec['previous']=[block['ref']];spec['value']['config']['mode']='llm'
        spec['value']['config']['schedule'].update(kind='daily',time='00:00')
        a.blocks.save(self.pid,a.blocks.read(self.pid)['commit_id'],[spec],str(uuid4()))
        a.configure(self.pid,spec['id'],True,confirm=True)
        with patch.object(a,'_model',return_value='Již vytvořená zpráva'):a.tick(self.pid,lane='processing')
        self.f.exchange(0,1)
        block=next(x for x in a.blocks.read(self.pid)['blocks'] if x['id']==spec['id'])
        spec['previous']=[block['ref']];spec['value']['config']['node_id']=self.f.node_ids[1]
        a.blocks.save(self.pid,a.blocks.read(self.pid)['commit_id'],[spec],str(uuid4()));self.f.exchange(0,1)
        with patch.object(b,'_model',side_effect=AssertionError('duplicate known period')):
            b.tick(self.pid,lane='processing')
        self.assertFalse(any(j[2].get('kind')=='processing' for j in self.local_jobs(1)))
        first=next(j for j in a.catalog(self.pid)['jobs'] if j['intent'].get('kind')=='processing')
        self.instant[0]=first['result']['protection']['until']
        with patch.object(a,'_model',return_value='Ruční místní běh po změně plánovaného uzlu'):
            new=a.reprocess(self.pid,first['id'],str(uuid4()),confirm=True)
        self.assertEqual(self.job(new['id'])['intent']['executor_node_id'],self.f.node_ids[0])

    def test_existing_activation_migrates_once_and_remote_pause_survives_restart(self):
        a,b=self.services;source=next(x for x in a.blocks.read(self.pid)['blocks'] if x['id']==self.specs[0]['id'])
        from spikes.reporting_schema import encoded
        old=dict(enabled=True,revision=source['ref']['artifact_id'],consent='legacy',next_due=self.instant[0]+900,validators={},last_success=None,error=None)
        with a.pools.db() as db:db.execute('INSERT INTO block_bindings VALUES(?,?,?)',(self.pid,source['id'],encoded(old)))
        a.tick(self.pid,lane='intake');a.tick(self.pid,lane='intake')
        self.assertEqual(sum(r['kind']=='activation' for r in self.rows()),1)
        self.f.exchange(0,1);b.configure(self.pid,source['id'],False,confirm=True);self.f.exchange(1,0)
        restarted=ComposableMonitoring(a.monitoring);restarted.tick(self.pid,lane='intake')
        runtime=next(x for x in restarted.catalog(self.pid)['blocks'] if x['id']==source['id'])['runtime']
        self.assertFalse(runtime['enabled']);self.assertFalse(runtime['activation_conflict'])

    def test_outcome_retention_removes_text_but_retains_activation_history(self):
        self.llm();a=self.services[0];a.configure(self.pid,self.specs[3]['id'],True,confirm=True)
        with patch.object(a,'_model',return_value='PRIVATE-EXPIRED-REPORT-TEXT'):
            first=a.process(self.pid,self.specs[3]['id'],str(uuid4()))
        self.instant[0]+=86401;a.pools.export(self.pid)
        with a.pools.read_db() as db:
            raw=b''.join(r[0] for r in db.execute('SELECT document FROM pool_entries WHERE project=?',(self.pid,)))
            self.assertIsNone(db.execute('SELECT id FROM block_jobs WHERE id=?',(first['id'],)).fetchone())
        self.assertNotIn(b'PRIVATE-EXPIRED-REPORT-TEXT',raw)
        self.assertTrue(any(r['kind']=='activation' for r in self.rows()))
        self.assertFalse(any(r['kind']=='report-outcome' for r in self.rows()))

    def test_shared_approval_and_definition_pin_are_verified_before_merge(self):
        from spikes.pool_sync import apply
        from spikes.reporting_schema import encoded
        a,b=self.services;a.process(self.pid,self.specs[3]['id'],str(uuid4()))
        row=next(r for r in self.rows() if r['kind']=='report-outcome')
        bad=deepcopy(row['value']);bad['result']['approval_digest']='0'*64
        with self.assertRaisesRegex(ValidationError,'approval digest'):
            apply(self.f.nodes[1],self.pid,encoded([entry(self.pid,'report-outcome',bad)]))
        bad=deepcopy(row['value']);bad['block_ref']['sha256']='0'*64;bad['intent']['block']['ref']['sha256']='0'*64
        with self.assertRaisesRegex(ValidationError,'pin differs'):
            apply(self.f.nodes[1],self.pid,encoded([entry(self.pid,'report-outcome',bad)]))
        bad=deepcopy(row['value']);bad['state']='published'
        from spikes.monitoring import ident
        aid=ident(bad['run_id'],'report')
        bad['result']['report_ref']=dict(project_id=self.pid,artifact_id=aid,commit_id=b.blocks.read(self.pid)['commit_id'],path='artifacts/'+aid+'/content.md',sha256='0'*64)
        with self.assertRaisesRegex(ValidationError,'Pin requires an artifact'):
            apply(self.f.nodes[1],self.pid,encoded([entry(self.pid,'report-outcome',bad)]))
        self.assertFalse(any(r['kind']=='report-outcome' for r in self.rows(1)))

    def test_local_only_shared_records_stay_local_and_invalid_operational_payload_is_rejected(self):
        a=self.services[0];a.configure(self.pid,self.specs[0]['id'],True,confirm=True)
        rows=a.pools.export(self.pid);activation=next(r for r in rows if r['kind']=='activation')
        local=entry(self.pid,'activation',dict(activation['value'],privacy='local-only',event_id=str(uuid4())))
        a.pools.merge(self.pid,[local]);self.assertNotIn(local,a.pools.export(self.pid,transferable=True))
        first=a.process(self.pid,self.specs[3]['id'],str(uuid4()))
        row=next(r for r in self.rows() if r['kind']=='report-outcome')
        bad=deepcopy(row['value']);bad['intent']['manifest']={'credentials':'SECRET'}
        with self.assertRaisesRegex(ValidationError,'operational'):
            a.pools.merge(self.pid,[entry(self.pid,'report-outcome',bad)])
