# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import time
import unittest
from uuid import uuid4

from tests import test_message_pool_sync as pool_fixture
from spikes.federation_sync import _prepare,SyncReceiver
from spikes.pool_input_guard import IncompletePoolTransfer,require_available
from spikes.monitoring import ident


class InputGuardTests(unittest.TestCase):
    def setUp(self):
        self.f=pool_fixture.PoolSyncTests('test_pool_crash_in_signed_exchange_rolls_forward_once')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.instant=time.time()
        self.source,self.target=self.f.services
        for service in self.f.services:
            service.clock=service.pools.clock=service.monitoring.clock=lambda:self.instant
        self.pid=self.f.pid;self.processing=self.f.specs[3]['id'];self.pool=self.f.specs[1]['id']

    def interrupt(self,stage='pool-inserted'):
        self.source.configure(self.pid,self.f.specs[0]['id'],True,confirm=True)
        self.source.tick(self.pid)
        env,payload,*_=_prepare(self.f.f.services[0],self.f.f.node_ids[1],self.pid,str(uuid4()),[],force_bundle=True)
        receiver=SyncReceiver(self.f.f.nodes[1],self.f.f.services[1])
        def crash(point):
            if point==stage:raise RuntimeError('interrupted')
        with self.assertRaisesRegex(RuntimeError,'interrupted'):receiver.receive(env,payload,crash)
        return receiver,env,payload

    def test_partial_transfer_fails_and_manual_retry_after_recovery_succeeds(self):
        receiver,env,payload=self.interrupt();run=str(uuid4())
        self.target._model=lambda *a,**kw:self.fail('Model must not run')
        with self.assertRaises(IncompletePoolTransfer):self.target.process(self.pid,self.processing,run)
        failed=next(j for j in self.target.catalog(self.pid)['jobs'] if j['id']==run)
        self.assertEqual(failed['state'],'failed');self.assertIn('Neúplný přenos',failed['result']['error'])
        self.assertTrue(any(r['kind']=='report-outcome' for r in self.target.pools.export(self.pid)))
        # Transfer the failure through the real signed sidecar, without applying
        # the response (which would itself repair the missing source data).
        error_env,error_payload,*_=_prepare(self.f.f.services[1],self.f.f.node_ids[0],self.pid,str(uuid4()),[],force_bundle=True)
        SyncReceiver(self.f.f.nodes[0],self.f.f.services[0]).receive(error_env,error_payload)
        received=next(j for j in self.source.catalog(self.pid)['jobs'] if j['id']==run)
        self.assertEqual(received['state'],'failed');self.assertTrue(received['shared'])
        receiver.receive(env,payload)
        retried=self.target.reprocess(self.pid,run,str(uuid4()),confirm=True)
        self.assertEqual(retried['state'],'review');self.assertIn('Energie dnes',retried['result']['markdown'])
        self.assertEqual(next(j for j in self.target.catalog(self.pid)['jobs'] if j['id']==run)['state'],'failed')

    def test_prepared_and_confirmation_crashes_remain_blocked(self):
        for stage in ('pool-receive-prepared','pool-receive-confirmed'):
            with self.subTest(stage=stage):
                receiver,env,payload=self.interrupt(stage)
                with self.assertRaises(IncompletePoolTransfer):self.target.process(self.pid,self.processing,str(uuid4()))
                receiver.receive(env,payload)
                self.assertEqual(self.target.process(self.pid,self.processing,str(uuid4()))['state'],'review')
                # The next transfer needs genuinely missing content.
                with self.target.pools.db() as db:db.execute('DELETE FROM pool_entries WHERE project=?',(self.pid,))

    def test_legacy_journal_and_scope_and_redundant_data(self):
        _,env,_=self.interrupt()
        with self.target.pools.db() as db:
            db.execute('DELETE FROM block_jobs WHERE id=?',(ident(env['exchange']['operation_id'],'pool-received'),))
        with self.assertRaises(IncompletePoolTransfer):self.target.process(self.pid,self.processing,str(uuid4()))
        require_available(self.target.pools,self.pid,[str(uuid4())],[],since=0,until=self.instant)
        require_available(self.target.pools,self.pid,[],[],since=0,until=self.instant)
        require_available(self.target.pools,str(uuid4()),[self.pool],[],since=0,until=self.instant)
        self.target.pools.merge(self.pid,self.source.pools.export(self.pid))
        self.assertEqual(self.target.process(self.pid,self.processing,str(uuid4()))['state'],'review')

    def test_late_failure_prevents_finalization_and_preserves_cached_draft(self):
        run=str(uuid4());draft=self.target.process(self.pid,self.processing,run)
        self.interrupt()
        self.assertEqual(self.target.process(self.pid,self.processing,run),draft)
        self.instant=draft['result']['protection']['until']
        self.target.tick(self.pid,lane='processing')
        job=next(j for j in self.target.catalog(self.pid)['jobs'] if j['id']==run)
        self.assertFalse(job['result']['protection']['finalized'])
        self.assertIn('Neúplný přenos',job['result']['protection']['error'])

    def test_late_failure_prevents_publication_with_separate_failure(self):
        run=str(uuid4());draft=self.target.process(self.pid,self.processing,run)
        self.instant=draft['result']['protection']['until'];self.target.tick(self.pid,lane='processing')
        self.interrupt()
        with self.assertRaises(IncompletePoolTransfer):
            self.target.publish(self.pid,run,draft['result']['approval_digest'],confirm=True)
        jobs=self.target.catalog(self.pid)['jobs']
        self.assertEqual(next(j for j in jobs if j['id']==run)['state'],'review')
        self.assertTrue(any(j['state']=='failed' and j['intent'].get('reprocess_of')==run for j in jobs))

    def test_window_expiry_and_covered_inputs(self):
        from spikes.pool_input_guard import manifest
        self.interrupt()
        rows=self.source.pools.export(self.pid)
        expected=manifest(rows)
        covered=[(r['pool_id'],r['item_entry']) for r in expected]
        require_available(self.target.pools,self.pid,[self.pool],[],since=0,until=self.instant,covered=covered)
        require_available(self.target.pools,self.pid,[self.pool],[],since=self.instant+86400,until=self.instant+172800)
        self.instant+=40*86400
        require_available(self.target.pools,self.pid,[self.pool],[],since=0,until=self.instant)

    def test_committed_import_is_available_even_without_transport_response(self):
        receiver,env,payload=self.interrupt('pool-committed')
        self.assertEqual(self.target.process(self.pid,self.processing,str(uuid4()))['state'],'review')
        receiver.receive(env,payload)
