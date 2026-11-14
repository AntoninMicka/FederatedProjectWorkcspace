# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Late inputs, durable deadlines and independent RSS/model effects."""
from copy import deepcopy
import json
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_monitoring_blocks as fixtures
from tests.test_monitoring_blocks import response
from spikes.composable_monitoring import ComposableMonitoring
from spikes.metadata import ValidationError
from spikes.message_pools import stamp
from spikes.reporting_schema import digest, encoded


class ProtectionTests(unittest.TestCase):
    setUp = fixtures.BlockTests.setUp
    activate = fixtures.BlockTests.activate

    def clock(self):
        self.instant = [self.service.clock()]
        self.monitoring.clock = lambda: self.instant[0]
        self.service.clock = self.service.pools.clock = self.monitoring.clock

    def draft(self):
        return self.service.process(self.f.project, self.specs[3]['id'], str(uuid4()))

    def job(self, run_id):
        return next(j for j in self.service.catalog(self.f.project)['jobs'] if j['id'] == run_id)

    def test_late_content_regenerates_once_and_blocks_old_approval(self):
        self.clock(); self.activate()
        first = self.draft(); deadline = first['result']['protection']['until']
        with self.assertRaisesRegex(ValidationError, 'protection'):
            self.service.publish(self.f.project, first['id'], first['result']['approval_digest'], confirm=True)
        self.instant[0] += 120
        self.service.tick(self.f.project, lane='intake')
        self.service.tick(self.f.project, lane='processing')
        self.assertTrue(self.job(first['id'])['result']['protection']['changed'])
        self.assertNotIn('Energie dnes', self.job(first['id'])['result']['markdown'])
        self.instant[0] = deadline
        restarted = ComposableMonitoring(self.monitoring)
        restarted.tick(self.f.project, lane='processing')
        final = self.job(first['id'])['result']
        self.assertTrue(final['protection']['finalized'])
        self.assertEqual(final['protection']['until'], deadline)
        self.assertIn('Energie dnes', final['markdown'])
        self.assertNotIn('Energie dnes', final['initial_draft']['markdown'])
        with self.assertRaisesRegex(ValidationError, 'approval'):
            restarted.publish(self.f.project, first['id'], first['result']['approval_digest'], confirm=True)
        child = self.job(final['protection']['regenerated_run_id'])
        with self.assertRaisesRegex(ValidationError, 'original report'):
            restarted.publish(self.f.project, child['id'], child['result']['approval_digest'], confirm=True)
        count = len(self.service.catalog(self.f.project)['jobs'])
        restarted.tick(self.f.project, lane='processing')
        self.assertEqual(len(self.service.catalog(self.f.project)['jobs']), count)
        issued = restarted.publish(self.f.project, first['id'], final['approval_digest'], confirm=True)
        self.assertEqual(issued, restarted.publish(self.f.project, first['id'], final['approval_digest'], confirm=True))

    def test_duplicate_observation_does_not_regenerate_and_deadline_is_not_approval(self):
        self.clock(); self.activate(); self.service.tick(self.f.project, lane='intake')
        first = self.draft()
        self.instant[0] += 901
        self.service.tick(self.f.project, lane='intake')
        self.service.tick(self.f.project, lane='processing')
        self.assertFalse(self.job(first['id'])['result']['protection']['changed'])
        self.instant[0] = first['result']['protection']['until']+7200
        # Wall clock alone never bypasses the final check.
        with self.assertRaisesRegex(ValidationError, 'protection'):
            self.service.publish(self.f.project, first['id'], first['result']['approval_digest'], confirm=True)
        self.service.tick(self.f.project, lane='processing')
        final = self.job(first['id'])['result']
        self.assertTrue(final['protection']['finalized'])
        self.assertNotIn('regenerated_run_id', final['protection'])
        self.assertEqual(final['approval_digest'], first['result']['approval_digest'])

    def test_content_correction_regenerates_and_deadline_starts_after_build(self):
        self.clock(); self.activate(); self.service.tick(self.f.project,lane='intake')
        saved=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==self.specs[3]['id'])
        spec=deepcopy(self.specs[3]);spec['previous']=[saved['ref']];spec['value']['config']['mode']='llm'
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        began=self.instant[0]; calls=[]
        def model(*args,**kwargs):
            calls.append(args);self.instant[0]+=120;return 'Model result '+str(len(calls))
        with patch.object(self.service,'_model',side_effect=model):
            first=self.draft()
            self.assertEqual(first['result']['protection']['until'],began+120+3600)
            self.instant[0]+=901
            self.service.fetcher=lambda *a,**kw:response('Opravený obsah')
            self.service.tick(self.f.project,lane='intake')
            self.service.tick(self.f.project,lane='processing')
            self.assertEqual(len(calls),1)  # No model call during protection.
            self.assertTrue(self.job(first['id'])['result']['protection']['changed'])
            self.instant[0]=first['result']['protection']['until']
            self.service.tick(self.f.project,lane='processing')
        self.assertEqual(len(calls),2)
        final=self.job(first['id'])['result']
        self.assertTrue(final['protection']['finalized'])
        self.assertEqual(final['protection']['until'],first['result']['protection']['until'])
        self.assertEqual(final['markdown'],'Model result 2')

    def test_original_window_includes_late_old_item_but_excludes_future_publication(self):
        self.clock(); first = self.draft(); anchor=self.instant[0]
        from spikes.source_connectors import RSSConnector, SourceContext
        by_id={b['id']:b for b in self.service.blocks.read(self.f.project)['blocks']}
        source=by_id[self.specs[0]['id']]
        context=SourceContext(source['id'], source['value']['config']['locator'], stamp(anchor+100), 'project', '30 days', channel='Test')
        items=RSSConnector().normalize(dict(raw=response()['raw'],url=context.locator),context)['items']
        items[0]['published_at']=stamp(anchor-60)
        newer=deepcopy(items[0]); newer.update(id='f'*64,url='https://example.org/future',original_id='future',published_at=stamp(anchor+60))
        newer.update(content='Future article',content_sha256=digest(b'Future article'))
        newer['id']=digest(encoded([newer['connector'],newer['source_id'],newer['original_id']]))
        # Reuse connector validation to build valid content revisions.
        rows=self.service._selected(self.f.project,source,items+[newer],[by_id[self.specs[2]['id']]],by_id,context.discovered_at)
        self.service.pools.merge(self.f.project,rows)
        self.assertEqual(len(self.service.pools.view(self.f.project,self.specs[1]['id'])),2)
        self.instant[0]=first['result']['protection']['until']
        self.service.tick(self.f.project,lane='processing')
        final=self.job(first['id']);self.assertTrue(final['result']['protection']['finalized'])
        self.assertEqual(final['intent']['period_end'],anchor)
        revisions=[r for groups in final['intent']['pools'].values() for g in groups for r in g['revisions']]
        self.assertEqual(len(revisions),1)
        self.assertEqual(revisions[0]['item']['published_at'],stamp(anchor-60))

    def test_unknown_regeneration_is_visible_blocked_and_never_retried(self):
        self.clock(); first=self.draft(); self.activate()
        self.service.tick(self.f.project,lane='intake')
        self.instant[0]=first['result']['protection']['until']
        def crash(stage):
            if stage=='processing-dispatching': raise SystemExit('power loss')
        with self.assertRaises(SystemExit):
            self.service.tick(self.f.project,lane='processing',checkpoint=crash)
        restarted=ComposableMonitoring(self.monitoring)
        restarted.tick(self.f.project,lane='processing')
        final=self.job(first['id'])['result']
        self.assertFalse(final['protection']['finalized'])
        self.assertIn('unknown',final['protection']['error'])
        with patch.object(restarted,'_process',side_effect=AssertionError('paid retry')):
            restarted.tick(self.f.project,lane='processing')
        with self.assertRaisesRegex(ValidationError,'protection'):
            restarted.publish(self.f.project,first['id'],first['result']['approval_digest'],confirm=True)

    def test_existing_unrelated_run_cannot_be_used_as_regeneration(self):
        from spikes.monitoring import ident
        self.clock(); first=self.draft()
        child=ident(first['id'],'protection-final')
        self.service.process(self.f.project,self.specs[3]['id'],child)
        self.activate();self.service.tick(self.f.project,lane='intake')
        self.instant[0]=first['result']['protection']['until']
        self.service.tick(self.f.project,lane='processing')
        result=self.job(first['id'])['result']
        self.assertFalse(result['protection']['finalized'])
        self.assertIn('another intent',result['protection']['error'])

    def test_restart_after_regeneration_commit_reuses_exact_frozen_result(self):
        self.clock(); first=self.draft(); self.activate()
        self.service.tick(self.f.project,lane='intake')
        self.instant[0]=first['result']['protection']['until']
        def crash(stage):
            if stage=='processing-committed': raise SystemExit('power loss')
        with self.assertRaises(SystemExit):
            self.service.tick(self.f.project,lane='processing',checkpoint=crash)
        restarted=ComposableMonitoring(self.monitoring)
        with patch.object(restarted,'_model',side_effect=AssertionError('second model call')):
            restarted.tick(self.f.project,lane='processing')
        self.assertTrue(self.job(first['id'])['result']['protection']['finalized'])
        self.assertIn('Energie dnes',self.job(first['id'])['result']['markdown'])

    def test_intake_runs_while_processing_is_busy_without_marking_it_unknown(self):
        self.clock(); self.activate()
        entered=threading.Event(); release=threading.Event(); errors=[]
        saved=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==self.specs[3]['id'])
        spec=deepcopy(self.specs[3]);spec['previous']=[saved['ref']];spec['value']['config']['mode']='llm'
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        def slow(*args,**kwargs):
            entered.set(); self.assertTrue(release.wait(10)); return 'Model result'
        def worker():
            try:
                with patch.object(self.service,'_model',side_effect=slow):self.draft()
            except BaseException as exc:errors.append(exc)
        thread=threading.Thread(target=worker);thread.start()
        try:
            self.assertTrue(entered.wait(10))
            # The independent runtime shares the real SQLite journal and flocks.
            intake=ComposableMonitoring(self.monitoring,fetcher=lambda *a,**kw:response())
            intake.tick(self.f.project,lane='intake')
            self.assertEqual(len(intake.pools.view(self.f.project,self.specs[1]['id'])),1)
            live=[j for j in intake.catalog(self.f.project)['jobs'] if j['intent']['kind']=='processing']
            self.assertEqual(live[0]['state'],'dispatching')
        finally:
            release.set();thread.join(10)
        self.assertFalse(thread.is_alive());self.assertEqual(errors,[])
        processing=[j for j in self.service.catalog(self.f.project)['jobs'] if j['intent']['kind']=='processing']
        self.assertEqual(processing[0]['state'],'review')
