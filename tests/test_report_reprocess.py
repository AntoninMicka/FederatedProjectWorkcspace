# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit reprocessing preserves editions, deadlines and uncertain effects."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_report_protection as fixtures
from tests.test_monitoring_blocks import response
from spikes.composable_monitoring import ComposableMonitoring
from spikes.metadata import ValidationError


class ReprocessTests(unittest.TestCase):
    setUp = fixtures.ProtectionTests.setUp
    activate = fixtures.ProtectionTests.activate
    clock = fixtures.ProtectionTests.clock
    draft = fixtures.ProtectionTests.draft
    job = fixtures.ProtectionTests.job

    def replay(self, source, run_id=None, **kwargs):
        return self.service.reprocess(self.f.project,source,run_id or str(uuid4()),confirm=True,**kwargs)

    def test_only_after_deadline_new_draft_keeps_period_and_source_unchanged(self):
        self.clock();first=self.draft();before=self.job(first['id']);head=self.f.git.head()
        with self.assertRaisesRegex(ValidationError,'protection'):
            self.replay(first['id'])
        with self.assertRaisesRegex(ValidationError,'Confirm'):
            self.service.reprocess(self.f.project,first['id'],str(uuid4()),confirm=False)
        self.instant[0]=first['result']['protection']['until']
        # Even if automatic finalization has not run, explicit reprocessing is allowed.
        self.activate();self.service.tick(self.f.project,lane='intake')
        run_id=str(uuid4());new=self.replay(first['id'],run_id)
        self.assertEqual(new['state'],'review');self.assertNotIn('replacement',new['result'])
        self.assertTrue(new['result']['protection']['finalized'])
        self.assertEqual(new['result']['protection']['until'],first['result']['protection']['until'])
        self.assertIn('Energie dnes',new['result']['markdown'])
        self.assertEqual(self.job(new['id'])['intent']['period_end'],before['intent']['period_end'])
        self.assertEqual(self.job(first['id']),before)
        self.assertEqual(self.f.git.head(),head)
        self.assertEqual(new,self.replay(first['id'],run_id))
        self.instant[0]+=1
        second=self.replay(new['id'])
        self.assertEqual(second['result']['protection']['until'],first['result']['protection']['until'])
        self.assertTrue(second['result']['protection']['finalized'])

    def test_published_source_is_immutable_and_usable_after_runtime_cleanup(self):
        self.clock();self.activate();self.service.tick(self.f.project,lane='intake');first=self.draft()
        self.instant[0]=first['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        issued=self.service.publish(self.f.project,first['id'],first['result']['approval_digest'],confirm=True)
        path=issued['report_ref']['path'];original=self.f.git.snapshot(self.f.git.head())[path]
        # The runtime row is a retained copy, not the authority for published provenance.
        with self.service.pools.db() as db:db.execute('DELETE FROM block_jobs WHERE id=?',(first['id'],))
        restarted=ComposableMonitoring(self.monitoring)
        new=restarted.reprocess(self.f.project,first['id'],str(uuid4()),confirm=True)
        self.assertEqual(new['state'],'review')
        self.assertEqual(new['result']['protection']['until'],first['result']['protection']['until'])
        replacement=restarted.publish(self.f.project,new['id'],new['result']['approval_digest'],confirm=True)
        self.assertNotEqual(replacement['report_ref']['artifact_id'],issued['report_ref']['artifact_id'])
        self.assertEqual(self.f.git.snapshot(self.f.git.head())[path],original)
        self.assertEqual(len(self.monitoring.current_view(self.f.project)['outputs']),2)

    def test_expired_input_text_is_not_restored_from_published_report(self):
        self.clock();self.activate();self.service.tick(self.f.project,lane='intake');first=self.draft()
        self.instant[0]=first['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        self.service.publish(self.f.project,first['id'],first['result']['approval_digest'],confirm=True)
        self.instant[0]+=31*86400
        self.service.pools.export(self.f.project)  # actual retention cleanup, including the source job
        self.assertFalse(self.service.pools.view(self.f.project,self.specs[1]['id']))
        new=self.replay(first['id'])
        self.assertNotIn('Energie dnes',new['result']['markdown'])
        self.assertIn('Žádné vybrané zprávy',new['result']['markdown'])
        self.assertIn('Část původních vstupů již není dostupná',new['result']['markdown'])

    def test_model_crash_is_not_retried_and_explicit_new_request_is_independent(self):
        self.clock()
        saved=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==self.specs[3]['id'])
        spec=deepcopy(self.specs[3]);spec['previous']=[saved['ref']];spec['value']['config']['mode']='llm'
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        with patch.object(self.service,'_model',return_value='First model result'):first=self.draft()
        self.instant[0]=first['result']['protection']['until']
        run_id=str(uuid4())
        with patch.object(self.service,'_model',side_effect=TimeoutError('unknown model outcome')) as model:
            with self.assertRaises(TimeoutError):self.replay(first['id'],run_id)
            self.assertEqual(model.call_count,1)
        restarted=ComposableMonitoring(self.monitoring)
        with patch.object(restarted,'_model',side_effect=AssertionError('paid retry')):
            result=restarted.reprocess(self.f.project,first['id'],run_id,confirm=True)
            self.assertEqual(result['state'],'unknown')
        with patch.object(restarted,'_model',return_value='Explicit new attempt') as model:
            new=restarted.reprocess(self.f.project,first['id'],str(uuid4()),confirm=True)
            self.assertEqual(new['state'],'review');self.assertEqual(model.call_count,1)

    def test_crash_after_durable_intent_recovers_unknown_and_cannot_reuse_id(self):
        self.clock();first=self.draft();self.instant[0]=first['result']['protection']['until']
        run_id=str(uuid4())
        def crash(stage):
            if stage=='processing-dispatching':raise SystemExit('power loss')
        with self.assertRaises(SystemExit):self.replay(first['id'],run_id,checkpoint=crash)
        restarted=ComposableMonitoring(self.monitoring)
        self.assertEqual(restarted.reprocess(self.f.project,first['id'],run_id,confirm=True)['state'],'unknown')
        with self.assertRaisesRegex(ValidationError,'another intent'):
            restarted.reprocess(self.f.project,str(uuid4()),run_id,confirm=True)
        with self.assertRaisesRegex(ValidationError,'new run ID'):self.replay(first['id'],first['id'])

    def test_crash_after_result_commit_returns_original_result_without_new_model(self):
        self.clock();first=self.draft();self.instant[0]=first['result']['protection']['until'];run_id=str(uuid4())
        def crash(stage):
            if stage=='processing-committed':raise SystemExit('power loss')
        with self.assertRaises(SystemExit):self.replay(first['id'],run_id,checkpoint=crash)
        restarted=ComposableMonitoring(self.monitoring)
        with patch.object(restarted,'_process',side_effect=AssertionError('second dispatch')):
            new=restarted.reprocess(self.f.project,first['id'],run_id,confirm=True)
            self.assertEqual(new['state'],'review')

    def test_changed_processing_definition_cannot_silently_reprocess_old_report(self):
        self.clock();first=self.draft();self.instant[0]=first['result']['protection']['until']
        saved=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==self.specs[3]['id'])
        spec=deepcopy(self.specs[3]);spec['previous']=[saved['ref']]
        spec['value']['config']['instructions']='Jiné zadání zprávy.'
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        with self.assertRaisesRegex(ValidationError,'definition differs'):
            self.replay(first['id'])

    def test_unknown_original_is_unchanged_when_manually_reprocessing_failed_guard(self):
        self.clock();first=self.draft();self.instant[0]=first['result']['protection']['until']
        with self.service.pools.db() as db:
            import json
            from spikes.reporting_schema import encoded
            r=json.loads(db.execute('SELECT result FROM block_jobs WHERE id=?',(first['id'],)).fetchone()[0])
            r['protection']['error']='unknown automatic regeneration'
            db.execute('UPDATE block_jobs SET result=? WHERE id=?',(encoded(r),first['id']))
        before=self.job(first['id']);new=self.replay(first['id'])
        self.assertEqual(new['state'],'review');self.assertEqual(self.job(first['id']),before)
