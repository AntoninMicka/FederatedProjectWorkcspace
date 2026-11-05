# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import subprocess
import sys
import time
import unittest
from uuid import uuid4

from tests import test_reporting as fixtures
from spikes.metadata import ValidationError
from spikes.reporting import operation_uuid
from spikes.reporting_scheduler import ReportingScheduler, calendar_period
from spikes.reporting_schema import encoded, moment


class CalendarTests(unittest.TestCase):
    def test_calendar_dst_and_month_quarter_year_boundaries(self):
        for start,hours in [('2026-03-23T00:00:00+01:00',167),('2026-10-19T00:00:00+02:00',169)]:
            p=calendar_period(start,'weekly','Europe/Prague','iso-calendar-v1')
            self.assertEqual((moment(p['end_utc'])-moment(p['start_utc'])).total_seconds()/3600,hours)
        for kind,start,end in [('monthly','2024-02-01T00:00:00+01:00','2024-03-01'),
            ('quarterly','2026-10-01T00:00:00+02:00','2027-01-01'),
            ('annual','2026-01-01T00:00:00+01:00','2027-01-01')]:
            self.assertTrue(calendar_period(start,kind,'Europe/Prague','v1')['end_local'].startswith(end))
        for start in ['2026-03-24T00:00:00+01:00','2026-03-23T01:00:00+01:00','2026-03-23T00:00:00+02:00']:
            with self.subTest(start=start),self.assertRaises(ValidationError):
                calendar_period(start,'weekly','Europe/Prague','v1')


class ReportingSchedulerTests(unittest.TestCase):
    for _name in ('spec','request','store','record','source','event','review','publication'):
        locals()[_name]=getattr(fixtures.ReportingTests,_name)

    def setUp(self):
        fixtures.ReportingTests.setUp(self)
        self.clock=[time.time()]
        self.scheduler=ReportingScheduler(self.node,clock=lambda:self.clock[0])
        self.intent=dict(project_id=self.project,task_ref=self.task,rules_ref=self.policy,
            input_head=self.git.head(),period=fixtures.calendar_period(),
            knowledge_cutoff=self.scheduler.stamp(),baseline_snapshot=None,delivery_required=False)
        self.task_entity=self.record(self.task)['entity_id']

    def enqueue(self,**changes):
        request=deepcopy(self.intent);request.update(changes)
        return self.scheduler.enqueue(request,str(uuid4()))

    def candidate(self,run):
        value=self.publication()
        for key in ('task_ref','rules_ref','input_head','period','knowledge_cutoff','baseline_snapshot'):
            value[key]=run[key]
        return self.request(self.spec('ReportSnapshot',value,markdown='# Přehled\n\nNebyla doložena významná změna.\n'))

    def approve(self,run):
        claim=self.scheduler.claim(run['run_id'],str(uuid4()))
        preview=self.scheduler.stage(run['run_id'],claim['lease_token'],self.candidate(run))
        self.scheduler.approve(run['run_id'],preview['approval_digest'],confirm=True)
        return preview

    def test_one_reservation_even_for_two_workers_and_fresh_pin_commit(self):
        def reserve(_):
            return self.scheduler.enqueue(deepcopy(self.intent),str(uuid4()))['run_id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids=list(pool.map(reserve,range(2)))
        self.assertEqual(ids[0],ids[1])
        self.source('New input head')
        changed=deepcopy(self.intent);changed['input_head']=self.git.head()
        with self.assertRaisesRegex(ValidationError,'reserved'):
            self.scheduler.enqueue(changed,str(uuid4()))
        alternate=deepcopy(self.intent)
        alternate['period']['start_utc']=alternate['period']['start_utc'].replace('Z','.000000Z')
        with self.assertRaisesRegex(ValidationError,'canonical timestamp'):
            self.scheduler.enqueue(alternate,str(uuid4()))

    def test_worker_fencing_expiry_unknown_and_explicit_no_effect_reconciliation(self):
        run=self.enqueue();id_=run['run_id'];first=self.scheduler.claim(id_,str(uuid4()),lease_seconds=5)
        with self.assertRaisesRegex(ValidationError,'claimable'):
            self.scheduler.claim(id_,str(uuid4()))
        self.clock[0]+=6
        with self.assertRaisesRegex(ValidationError,'unknown outcome'):
            self.scheduler.claim(id_,str(uuid4()))
        self.assertEqual(self.scheduler.get(id_)['state'],'unknown')
        with self.assertRaises(ValidationError):self.scheduler.retry(id_,confirm=True)
        with self.assertRaises(ValidationError):self.scheduler.reconcile_no_effect(id_)
        self.scheduler.reconcile_no_effect(id_,confirm=True);self.scheduler.retry(id_,confirm=True)
        self.scheduler.claim(id_,str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'Stale worker'):
            self.scheduler.stage(id_,first['lease_token'],self.candidate(run))
        self.assertEqual(len(self.scheduler.get(id_)['attempts']),2)

    def test_catch_up_is_bounded_and_idempotent_without_advancing_cutoff(self):
        first=self.scheduler.catch_up(self.project,self.task,'weekly','2026-03-23T00:00:00+01:00',limit=2)
        self.assertTrue(first['more']);self.assertEqual(len(first['runs']),2)
        self.source('Unrelated change');self.clock[0]+=1
        second=self.scheduler.catch_up(self.project,self.task,'weekly','2026-03-23T00:00:00+01:00',limit=2)
        self.assertEqual([r['run_id'] for r in first['runs']],[r['run_id'] for r in second['runs']])
        self.assertEqual(first['runs'][0]['input_head'],second['runs'][0]['input_head'])
        self.assertIsNone(self.scheduler.cutoff(self.project,self.task_entity,'weekly'))
        with self.assertRaisesRegex(ValidationError,'different delivery requirement'):
            self.scheduler.catch_up(self.project,self.task,'weekly','2026-03-23T00:00:00+01:00',limit=2,
                                    delivery_required=True)
        with self.assertRaisesRegex(ValidationError,'Earlier reporting period'):
            self.scheduler.claim(first['runs'][1]['run_id'],str(uuid4()))

    def test_failure_retry_and_completed_rerun_never_duplicate_publication(self):
        run=self.enqueue();id_=run['run_id'];claim=self.scheduler.claim(id_,str(uuid4()))
        self.scheduler.fail(id_,claim['lease_token'])
        self.assertIsNone(self.scheduler.cutoff(self.project,self.task_entity,'weekly'))
        with self.assertRaises(ValidationError):self.scheduler.retry(id_)
        self.scheduler.retry(id_,confirm=True);self.approve(run)
        done=self.scheduler.publish(id_);head=self.git.head()
        self.assertEqual(done['state'],'completed');self.assertEqual(self.scheduler.publish(id_),done)
        self.assertEqual(self.git.head(),head)
        self.assertEqual(self.scheduler.cutoff(self.project,self.task_entity,'weekly')['last_successful_cutoff'],run['knowledge_cutoff'])
        with self.assertRaisesRegex(ValidationError,'correction'):self.scheduler.retry(id_,confirm=True)
        record=self.record(done['workspace_receipt']['snapshot'])
        self.assertEqual(record['value']['generation']['run_id'],id_)

    def test_task_revision_change_does_not_mutate_inflight_run(self):
        run=self.enqueue()
        old=self.record(self.task);value=deepcopy(old['value']);value['title']='Revised watch'
        new_task=self.store('ReportingTask',value,[self.task],old['entity_id'])
        revised=self.enqueue(task_ref=new_task,input_head=self.git.head())
        self.assertNotEqual(run['run_id'],revised['run_id'])
        self.approve(run);done=self.scheduler.publish(run['run_id'])
        self.assertEqual(self.record(done['workspace_receipt']['snapshot'])['value']['task_ref'],self.task)
        self.assertEqual(self.scheduler.get(revised['run_id'])['state'],'prepared')

    def test_completed_replacement_unblocks_cancelled_old_revision_for_following_periods(self):
        old_run=self.enqueue();self.scheduler.cancel(old_run['run_id'],confirm=True)
        old=self.record(self.task);value=deepcopy(old['value']);value['title']='Explicit replacement'
        self.task=self.store('ReportingTask',value,[self.task],old['entity_id'])
        self.intent.update(task_ref=self.task,input_head=self.git.head())
        replacement=self.enqueue();self.approve(replacement);self.scheduler.publish(replacement['run_id'])
        following=self.enqueue(input_head=self.git.head(),period=calendar_period(
            '2026-03-30T00:00:00+02:00','weekly','Europe/Prague','iso-calendar-v1'))
        self.assertEqual(self.scheduler.claim(following['run_id'],str(uuid4()))['run']['state'],'collecting')
        self.assertEqual(self.scheduler.get(old_run['run_id'])['state'],'cancelled')

    def test_exact_candidate_confirmation_and_no_silent_input_replacement(self):
        run=self.enqueue();id_=run['run_id'];claim=self.scheduler.claim(id_,str(uuid4()))
        bad=self.candidate(run);bad['records'][0]['value']['input_head']='a'*40
        with self.assertRaisesRegex(ValidationError,'immutable run'):
            self.scheduler.stage(id_,claim['lease_token'],bad)
        preview=self.scheduler.stage(id_,claim['lease_token'],self.candidate(run))
        with self.assertRaises(ValidationError):self.scheduler.approve(id_,preview['approval_digest'])
        with self.assertRaises(ValidationError):self.scheduler.approve(id_,'b'*64,confirm=True)
        self.assertEqual(self.scheduler.get(id_)['state'],'review')
        recovered=ReportingScheduler(self.node).preview(id_)
        self.assertEqual(recovered['request'],self.candidate(run))
        self.assertEqual(recovered['approval_digest'],preview['approval_digest'])
        with self.assertRaises(ValidationError):self.scheduler.publish(id_)
        self.scheduler.cancel(id_,confirm=True)
        self.assertEqual(self.scheduler.get(id_)['state'],'cancelled')
        self.scheduler.retry(id_,confirm=True)
        self.assertEqual(self.scheduler.get(id_)['state'],'prepared')
        with self.assertRaisesRegex(ValidationError,'no staged candidate'):
            self.scheduler.preview(id_)

    def test_delivery_unknown_never_reissues_or_advances_cutoff(self):
        run=self.enqueue(delivery_required=True);id_=run['run_id'];self.approve(run)
        issued=self.scheduler.publish(id_);head=self.git.head();self.assertEqual(issued['state'],'issued')
        progress=self.scheduler.cutoff(self.project,self.task_entity,'weekly')
        self.assertIsNone(progress['last_successful_cutoff'])
        self.assertEqual(progress['last_issued_snapshot'],issued['workspace_receipt']['snapshot'])
        script='''
import sys,os
from spikes.reporting_scheduler import ReportingScheduler
def stop(stage):
 if stage=='delivery-intent':os._exit(73)
ReportingScheduler(sys.argv[1]).begin_delivery(sys.argv[2],'a'*64,confirm=True,checkpoint=stop)
'''
        p=subprocess.run([sys.executable,'-c',script,str(self.node),id_],capture_output=True,text=True,timeout=30)
        self.assertEqual(p.returncode,73,p.stderr)
        unknown=ReportingScheduler(self.node).get(id_)
        for operation in [lambda:self.scheduler.begin_delivery(id_,'a'*64,confirm=True),
                          lambda:self.scheduler.publish(id_),lambda:self.scheduler.retry(id_,confirm=True)]:
            with self.assertRaises(ValidationError):operation()
        self.assertEqual(self.git.head(),head)
        receipt=dict(delivery_id=unknown['deliveries'][0]['delivery_id'],idempotency_key=id_,
                     intent_sha256='a'*64,status='delivered',receipt_ref='node-local-provider-receipt:123')
        with self.assertRaises(ValidationError):self.scheduler.confirm_delivery(id_,'b'*64,receipt,confirm=True)
        done=self.scheduler.confirm_delivery(id_,'a'*64,receipt,confirm=True)
        self.assertEqual(done['state'],'completed');self.assertEqual(self.git.head(),head)
        self.assertEqual(self.scheduler.confirm_delivery(id_,'a'*64,receipt,confirm=True),done)
        self.assertIsNotNone(self.scheduler.cutoff(self.project,self.task_entity,'weekly'))

    def test_schema_and_journal_file_permissions_are_fail_closed(self):
        with self.assertRaisesRegex(ValidationError,'outside all Git'):
            ReportingScheduler(self.node,state_dir=self.git.root/'bad-run-state')
        self.scheduler.path.chmod(0o644)
        with self.assertRaisesRegex(ValidationError,'Unsafe'):
            self.scheduler.get(str(uuid4()))
        self.scheduler.path.chmod(0o600)
        with self.scheduler.db() as db:db.execute('UPDATE schema_info SET version=99')
        with self.assertRaisesRegex(ValidationError,'schema'):
            ReportingScheduler(self.node)

    def test_missing_authoritative_journal_is_not_recreated_as_an_index(self):
        self.enqueue();self.scheduler.path.unlink()
        with self.assertRaises(FileNotFoundError):self.scheduler.get(str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'missing'):
            ReportingScheduler(self.node)
        self.assertFalse(self.scheduler.path.exists())

    def test_journal_cannot_be_opened_with_a_different_node_identity(self):
        from spikes.project_creation import ProjectCreation
        node=self.base/'foreign-node.json'
        ProjectCreation(node).create('Other node',self.base/'foreign-project',str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'owner'):
            ReportingScheduler(node,state_dir=self.scheduler.root)

    def test_approved_candidate_cannot_change_after_a_restart(self):
        run=self.enqueue();id_=run['run_id'];self.approve(run);head=self.git.head()
        request=self.scheduler.preview(id_)['request'];request['records'][0]['markdown']+='\nChanged after approval.\n'
        with self.scheduler.db() as db:
            db.execute('UPDATE runs SET candidate=? WHERE run_id=?',(encoded(request),id_))
        with self.assertRaisesRegex(ValidationError,'digest changed'):
            ReportingScheduler(self.node).publish(id_)
        self.assertEqual(self.git.head(),head)

    def test_invalid_candidate_is_rejected_before_review_without_project_intent(self):
        run=self.enqueue();id_=run['run_id'];claim=self.scheduler.claim(id_,str(uuid4()))
        request=self.candidate(run);request['records'][0]['markdown']='# Přehled\nNeúplný návrh.'
        head=self.git.head()
        with self.assertRaisesRegex(ValidationError,'Empty report'):
            self.scheduler.stage(id_,claim['lease_token'],request)
        self.assertEqual(self.scheduler.get(id_)['state'],'collecting')
        self.assertEqual(self.git.head(),head);self.assertIsNone(self.ws.receipt(id_))

    def test_changed_policy_revokes_review_before_publication(self):
        from spikes.artifacts import Artifacts
        run=self.enqueue();id_=run['run_id'];claim=self.scheduler.claim(id_,str(uuid4()))
        preview=self.scheduler.stage(id_,claim['lease_token'],self.candidate(run))
        Artifacts(self.node).save(dict(project_id=self.project,base_head=self.git.head(),
            artifact_id=self.policy_id,title='Changed policy',body='New review required.',new=False),str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'changed, deleted or revoked'):
            self.scheduler.approve(id_,preview['approval_digest'],confirm=True)
        self.assertEqual(self.scheduler.get(id_)['state'],'review')

    def test_process_crashes_preserve_enqueue_collection_review_and_approval(self):
        script='''
import os,json,sys
from spikes.reporting_scheduler import ReportingScheduler
s=ReportingScheduler(sys.argv[1]);r=json.load(open(sys.argv[2]));target=sys.argv[4]
def stop(stage):
 if stage==target:os._exit(73)
s.enqueue(r['intent'],sys.argv[3],checkpoint=stop)
claim=s.claim(sys.argv[3],r['worker'])
stop('collecting')
preview=s.stage(sys.argv[3],claim['lease_token'],r['candidate'],checkpoint=stop)
s.approve(sys.argv[3],preview['approval_digest'],confirm=True,checkpoint=stop)
'''
        for stage,expected in [('run-prepared','prepared'),('collecting','collecting'),
                               ('run-review','review'),('run-approved','approved')]:
            with self.subTest(stage=stage):
                # Each independent crash case keeps its own request evidence.
                root=self.base/('crash-'+stage);root.mkdir(mode=0o700)
                # Child uses its own default journal, so independent task revisions give distinct reservations.
                old=self.record(self.task);value=deepcopy(old['value']);value['title']='Before '+stage
                self.task=self.store('ReportingTask',value,[self.task],old['entity_id'])
                self.intent.update(task_ref=self.task,input_head=self.git.head(),knowledge_cutoff=self.scheduler.stamp())
                run_id=str(uuid4());run=dict(self.intent,run_id=run_id)
                request=dict(intent=self.intent,worker=str(uuid4()),candidate=self.candidate(run))
                path=root/'request.json';path.write_bytes(encoded(request))
                p=subprocess.run([sys.executable,'-c',script,str(self.node),str(path),run_id,stage],
                                 capture_output=True,text=True,timeout=30)
                self.assertEqual(p.returncode,73,p.stderr)
                recovered=ReportingScheduler(self.node).get(run_id)
                self.assertEqual(recovered['state'],expected)
                self.assertIsNone(self.ws.receipt(run_id))
                # Earlier unfinished periods are equal here; no later report is issued by this test.

    def test_process_crash_before_after_workspace_cas_and_run_receipt(self):
        script='''
import os,sys
from spikes.reporting_scheduler import ReportingScheduler
service=ReportingScheduler(sys.argv[1])
def stop(stage):
 if stage==sys.argv[3]:os._exit(73)
service.publish(sys.argv[2],checkpoint=stop)
'''
        for stage in ('run-issuing','prepared','file:0','before-ref','ref-updated','indexed','workspace-receipt','run-completed'):
            with self.subTest(stage=stage):
                # A fresh task revision permits a distinct basic publication in the same period.
                old=self.record(self.task);value=deepcopy(old['value']);value['title']='Crash '+stage
                self.task=self.store('ReportingTask',value,[self.task],old['entity_id'])
                self.intent.update(task_ref=self.task,input_head=self.git.head(),knowledge_cutoff=self.scheduler.stamp())
                run=self.enqueue();self.approve(run);id_=run['run_id']
                count=int(self.git.run('rev-list','--count','HEAD').stdout)
                p=subprocess.run([sys.executable,'-c',script,str(self.node),id_,stage],capture_output=True,text=True,timeout=30)
                self.assertEqual(p.returncode,73,p.stderr)
                restarted=ReportingScheduler(self.node)
                done=restarted.publish(id_)
                self.assertEqual(done['state'],'completed')
                self.assertEqual(int(self.git.run('rev-list','--count','HEAD').stdout),count+1)
                self.assertEqual(restarted.publish(id_),done)
                self.assertEqual(self.git.run('status','--porcelain').stdout,'')
