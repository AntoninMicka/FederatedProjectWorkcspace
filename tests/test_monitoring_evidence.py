# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from datetime import datetime
import unittest
from uuid import uuid4
from zoneinfo import ZoneInfo
from tests import test_report_protection as fixture
from tests.test_monitoring_blocks import response
from spikes.monitoring_evidence import next_processing


class EvidenceTests(unittest.TestCase):
    setUp=fixture.ProtectionTests.setUp
    clock=fixture.ProtectionTests.clock
    activate=fixture.ProtectionTests.activate
    draft=fixture.ProtectionTests.draft
    job=fixture.ProtectionTests.job

    def pool(self):return self.service.pool_view(self.f.project,self.specs[1]['id'])

    def test_pending_tracks_each_consumer_and_failed_runs_do_not_consume(self):
        self.clock();self.activate();self.service.tick(self.f.project,lane='intake')
        self.assertEqual(self.pool()['processing_status']['pending_count'],1)
        first=self.draft();self.assertEqual(self.pool()['processing_status']['pending_count'],0)
        self.assertTrue(self.pool()['processing_status']['items'][0]['included'])
        other=deepcopy(self.specs[3]);other['id']=str(uuid4())
        self.service.blocks.save(self.f.project,self.f.git.head(),[other],str(uuid4()))
        status=self.pool()['processing_status'];self.assertEqual(status['pending_count'],1)
        self.assertEqual(status['items'][0]['waiting_for'],[other['id']])
        with self.service.pools.db() as db:
            db.execute("UPDATE block_jobs SET state='failed' WHERE id=?",(first['id'],))
            db.execute("DELETE FROM pool_entries WHERE kind='report-outcome'")
        self.assertFalse(self.pool()['processing_status']['items'][0]['included'])

    def test_items_outside_processing_window_are_not_claimed_as_waiting(self):
        self.clock();self.activate();self.service.tick(self.f.project,lane='intake')
        self.instant[0]+=8*86400
        status=self.pool()['processing_status']
        self.assertEqual(status['pending_count'],0)
        self.assertEqual(status['items'][0]['outside_window_for'],[self.specs[3]['id']])

    def test_exact_refs_detect_late_correction_without_mutating_report(self):
        self.clock();self.activate();self.service.tick(self.f.project,lane='intake');first=self.draft()
        before=self.job(first['id']);evidence=before['input_evidence'];self.assertFalse(evidence['potentially_stale'])
        self.assertEqual(evidence['inputs'][0]['item_entry'],before['intent']['pools'][self.specs[1]['id']][0]['revisions'][0]['item_entry'])
        self.instant[0]+=901;self.service.fetcher=lambda *a,**kw:response('Opravená energie')
        self.service.tick(self.f.project,lane='intake')
        after=self.job(first['id']);self.assertTrue(after['input_evidence']['potentially_stale'])
        # A delayed transfer can carry an earlier collection timestamp than build.
        from spikes.monitoring_evidence import Evidence
        from spikes.message_pools import stamp
        rows=self.service.pools.export_readonly(self.service.node,self.f.project,clock=self.service.clock,transferable=False)
        blocks=self.service.blocks.read(self.f.project)['blocks']
        self.assertTrue(Evidence(self.service.pools,self.f.project,blocks,rows,[]).report(before['intent'],stamp(self.instant[0]+1800))['potentially_stale'])
        self.assertEqual(before['result'],after['result']);self.assertEqual(before['intent'],after['intent'])
        head=self.f.git.head()
        with self.service.pools.read_db() as db:count=db.execute('SELECT count(*) FROM block_jobs').fetchone()[0]
        self.service.catalog(self.f.project);self.pool()
        self.assertEqual(head,self.f.git.head())
        with self.service.pools.read_db() as db:self.assertEqual(count,db.execute('SELECT count(*) FROM block_jobs').fetchone()[0])

    def test_redundant_observation_is_not_a_content_correction(self):
        self.clock();self.activate();self.service.tick(self.f.project,lane='intake');first=self.draft()
        self.instant[0]+=901;self.service.tick(self.f.project,lane='intake')
        self.assertFalse(self.job(first['id'])['input_evidence']['potentially_stale'])

    def test_published_provenance_survives_runtime_history_and_expiry(self):
        self.clock();self.activate();self.service.tick(self.f.project,lane='intake');first=self.draft()
        self.instant[0]=first['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        final=self.job(first['id'])['result'];issued=self.service.publish(self.f.project,first['id'],final['approval_digest'],confirm=True)
        with self.service.pools.db() as db:
            db.execute('DELETE FROM block_jobs');db.execute("DELETE FROM pool_entries WHERE kind='report-outcome'")
        self.assertEqual(self.pool()['processing_status']['pending_count'],0)
        head=self.f.git.head();output=self.monitoring.output(self.f.project,issued['report_ref']['artifact_id'],head)
        self.assertTrue(output['input_evidence']['inputs'][0]['available'])
        self.instant[0]+=40*86400
        expired=self.monitoring.output(self.f.project,issued['report_ref']['artifact_id'],head)['input_evidence']['inputs'][0]
        self.assertFalse(expired['available']);self.assertIsNone(expired['title']);self.assertNotIn('content',expired)
        import shutil
        shutil.rmtree(self.service.pools.root)
        self.monitoring.output(self.f.project,issued['report_ref']['artifact_id'],head)
        self.assertFalse(self.service.pools.root.exists(),'Reading a published report must not initialize a pool database')

    def test_filter_rejection_summary_contains_no_rejected_text(self):
        self.clock();spec=deepcopy(self.specs[2]);block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==spec['id'])
        spec['previous']=[block['ref']];spec['value']['config']['pipeline']['steps'].insert(0,dict(id='keywords',kind='keywords',fields=['title','content'],all=[],any=['NEEXISTUJE'],none=[],case_sensitive=False))
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        self.activate();self.service.tick(self.f.project,lane='intake')
        source=next(b for b in self.service.catalog(self.f.project)['blocks'] if b['id']==self.specs[0]['id'])
        summary=source['latest_intake']['result']['selection_summary']
        self.assertEqual(summary[0]['decision'],'discarded');self.assertEqual(summary[0]['count'],1)
        self.assertNotIn('Energie dnes',str(summary));self.assertEqual(self.pool()['messages'],[])


class CalendarEvidenceTests(unittest.TestCase):
    def at(self,text):return datetime.fromisoformat(text).replace(tzinfo=ZoneInfo('Europe/Prague')).timestamp()
    def test_calendar_boundaries_and_overdue(self):
        now=self.at('2026-11-15T12:00');schedule=dict(kind='weekly',time='07:00',timezone='Europe/Prague')
        self.assertEqual(next_processing(schedule,now),now)
        self.assertEqual(next_processing(schedule,now,'2026-11-09'),self.at('2026-11-16T07:00'))
        schedule['kind']='monthly';self.assertEqual(next_processing(schedule,now,'2026-11-01'),self.at('2026-12-01T07:00'))
        schedule['kind']='annual';self.assertEqual(next_processing(schedule,now,'2026-01-01'),self.at('2027-01-01T07:00'))
        schedule['kind']='quarterly';self.assertEqual(next_processing(schedule,now,'2026-10-01'),self.at('2027-01-01T07:00'))
        schedule['kind']='manual';self.assertIsNone(next_processing(schedule,now))
    def test_dst_gap_and_fold_match_worker_wall_clock(self):
        schedule=dict(kind='daily',time='02:30',timezone='Europe/Prague')
        self.assertEqual(next_processing(schedule,self.at('2026-03-28T12:00'),'2026-03-28'),self.at('2026-03-29T03:00'))
        self.assertEqual(next_processing(schedule,self.at('2026-10-24T12:00'),'2026-10-24'),self.at('2026-10-25T02:30'))

        repeated=datetime(2026,10,25,2,10,tzinfo=ZoneInfo('Europe/Prague'),fold=1).timestamp()
        expected=datetime(2026,10,25,2,30,tzinfo=ZoneInfo('Europe/Prague'),fold=1).timestamp()
        self.assertEqual(next_processing(schedule,repeated,'2026-10-24'),expected)
        self.assertEqual(next_processing(schedule,repeated,'2026-10-25'),self.at('2026-10-26T02:30'))
