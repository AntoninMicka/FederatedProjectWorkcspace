# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""One manual node worker, cooperative admission, no replay after dispatch."""
import fcntl
import threading
import time
import shutil
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.sync_diagnostics import snapshot as diagnostic
from spikes.federation_sync import (ContentSyncControl, ManualSyncTasks, _database,
                                    private_root)
from tests import test_artifacts as fixtures


class ManualSyncQueueTests(unittest.TestCase):
    setUp = fixtures.ArtifactTests.setUp

    def pending(self, peer, project):
        operation = str(uuid4())
        with _database(self.node) as db:
            db.execute('INSERT INTO outbound VALUES (?,?,?,?,?,?)',
                (peer, project, operation, '{}', b'exact saved payload', '[]'))
        return operation

    def test_batch_has_one_worker_queued_cancel_never_dispatches_and_limit_is_bounded(self):
        tasks = ManualSyncTasks(max_pending=3); peer = str(uuid4())
        ids = [str(uuid4()) for _ in range(4)]
        operation = self.pending(peer, ids[1])
        entered, release = threading.Event(), threading.Event(); calls = []
        active = 0; peak = 0
        def transfer(node, peer_id, project_id, **options):
            nonlocal active, peak
            calls.append(project_id); active += 1; peak = max(peak, active)
            if project_id == ids[0]:
                entered.set()
                if not release.wait(5): raise AssertionError('Transfer not released')
            active -= 1
            tasks._status(node, peer_id, project_id, 'idle', 'Content synchronized')
            return {'state': 'idle'}
        with patch('spikes.federation_sync.synchronize', side_effect=transfer), \
                patch('spikes.federation_sync._MANUAL_SYNCS', tasks):
            try:
                self.assertTrue(tasks.start(self.node, 'desktop', peer, ids[0]))
                self.assertTrue(entered.wait(2))
                self.assertTrue(tasks.start(self.node, 'desktop', peer, ids[1]))
                self.assertTrue(tasks.start(self.node, 'desktop', peer, ids[2]))
                self.assertFalse(tasks.start(self.node, 'desktop', peer, ids[1]))
                with self.assertRaisesRegex(ValueError, 'queue is full'):
                    tasks.start(self.node, 'desktop', peer, ids[3])
                threads = {row['thread'] for row in tasks.tasks.values()}
                self.assertEqual(len(threads), 1); worker = threads.pop()
                with _database(self.node) as db:
                    self.assertEqual(db.execute('SELECT state FROM runtime WHERE project_id=?',
                                                (ids[1],)).fetchone()[0], 'queued')
                self.assertTrue(tasks.cancel(self.node, peer, ids[1]))
                control = ContentSyncControl(self.node, deployment='desktop')
                with patch.object(control, 'candidates', side_effect=AssertionError('Automatic must yield')):
                    self.assertEqual(control.run_automatic(), {'enabled': True, 'attempted': 0})
            finally:
                release.set()
                for row in list(tasks.tasks.values()): row['thread'].join(5)
            self.assertFalse(worker.is_alive())
            self.assertEqual(peak, 1)
            self.assertEqual(calls, [ids[0], ids[2]])
            self.assertEqual(tasks.tasks, {}); self.assertEqual(tasks.workers, {})
            with _database(self.node) as db:
                self.assertEqual(db.execute('SELECT state FROM runtime WHERE project_id=?',
                                            (ids[1],)).fetchone()[0], 'cancelled')
                self.assertEqual(db.execute('SELECT operation_id,bundle FROM outbound').fetchone(),
                                 (operation, b'exact saved payload'))

    def test_waiting_for_existing_node_owner_cancels_without_dispatch_or_new_operation(self):
        tasks = ManualSyncTasks(); peer = str(uuid4()); operation = self.pending(peer, self.id)
        owner = private_root(self.node) / 'federation-content-sync.lock'
        with owner.open('a+b') as handle, \
                patch('spikes.federation_sync.synchronize', side_effect=AssertionError('Unexpected dispatch')):
            owner.chmod(0o600); fcntl.flock(handle, fcntl.LOCK_EX)
            self.assertTrue(tasks.start(self.node, 'desktop', peer, self.id))
            worker = next(iter(tasks.tasks.values()))['thread']
            try:
                deadline = time.monotonic()+2
                while time.monotonic() < deadline:
                    value = diagnostic(self.node, peer, self.id)
                    if value and value['phase'] == 'wait-lock': break
                    time.sleep(.01)
                self.assertEqual(diagnostic(self.node, peer, self.id)['phase'], 'wait-lock')
                self.assertTrue(tasks.cancel(self.node, peer, self.id))
                worker.join(2)
                self.assertFalse(worker.is_alive(), 'Cancellation waited for another owner')
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
                worker.join(3)
        with _database(self.node) as db:
            self.assertEqual(db.execute('SELECT operation_id,bundle FROM outbound').fetchone(),
                             (operation, b'exact saved payload'))
            self.assertEqual(db.execute('SELECT state FROM runtime').fetchone()[0], 'cancelled')

    def test_failed_dispatch_does_not_retry_and_does_not_strand_next_project(self):
        tasks = ManualSyncTasks(); peer = str(uuid4()); next_project = str(uuid4())
        operation = self.pending(peer, self.id)
        entered, release = threading.Event(), threading.Event(); calls = []
        def transfer(node, peer_id, project_id, **options):
            calls.append(project_id)
            if project_id == self.id:
                entered.set(); release.wait(5)
                raise ConnectionError('Response lost')
            return {'state': 'idle'}
        with patch('spikes.federation_sync.synchronize', side_effect=transfer):
            try:
                tasks.start(self.node, 'desktop', peer, self.id)
                self.assertTrue(entered.wait(2))
                tasks.start(self.node, 'desktop', peer, next_project)
                worker = next(iter(tasks.tasks.values()))['thread']
            finally:
                release.set()
                for row in list(tasks.tasks.values()): row['thread'].join(5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(calls, [self.id, next_project])
        with _database(self.node) as db:
            self.assertEqual(db.execute('SELECT operation_id,bundle FROM outbound').fetchone(),
                             (operation, b'exact saved payload'))
            self.assertEqual(db.execute('SELECT state FROM runtime WHERE project_id=?',
                                        (self.id,)).fetchone()[0], 'offline')

    def test_queue_lost_before_worker_start_is_not_resumed_or_cleared(self):
        tasks = ManualSyncTasks(); peer = str(uuid4()); operation = self.pending(peer, self.id)
        with patch('spikes.federation_sync.threading.Thread.start', side_effect=RuntimeError('Cannot start')):
            with self.assertRaises(RuntimeError): tasks.start(self.node, 'desktop', peer, self.id)
        self.assertEqual(tasks.tasks, {}); self.assertEqual(tasks.workers, {})
        with patch('spikes.federation_sync._MANUAL_SYNCS', ManualSyncTasks()):
            statuses = ContentSyncControl(self.node, deployment='desktop').statuses()
        self.assertEqual(statuses[peer+':'+self.id]['state'], 'cancelled')
        with _database(self.node) as db:
            self.assertEqual(db.execute('SELECT operation_id,bundle FROM outbound').fetchone(),
                             (operation, b'exact saved payload'))

    def test_background_admission_wait_has_deadline_without_transport_retry(self):
        peer = str(uuid4()); operation = self.pending(peer, self.id)
        owner = private_root(self.node) / 'federation-content-sync.lock'
        control = ContentSyncControl(self.node, deployment='desktop')
        with owner.open('a+b') as handle, \
                patch('spikes.federation_sync.synchronize', side_effect=AssertionError('Unexpected dispatch')):
            owner.chmod(0o600); fcntl.flock(handle, fcntl.LOCK_EX)
            started = time.monotonic()
            with self.assertRaises(BlockingIOError): control.synchronize(peer, self.id, owner_wait=.1)
            self.assertLess(time.monotonic()-started, 1)
        with _database(self.node) as db:
            self.assertEqual(db.execute('SELECT operation_id,bundle FROM outbound').fetchone(),
                             (operation, b'exact saved payload'))


    def test_automatic_attempt_defers_to_a_running_outbound_sync_without_recording_failure(self):
        """AUDIT-B7-T1: lane contention is not an error, a retry backoff or a new state."""
        from spikes.federation_sync import OutboundDeferred, automatic_retry
        from spikes.sync_fingerprint import observation
        peer = str(uuid4()); self.pending(peer, self.id)
        control = ContentSyncControl(self.node, deployment='desktop')
        with patch('spikes.federation_sync.synchronize', return_value={'state': 'idle'}):
            control.synchronize(peer, self.id)  # the last real run
        before = diagnostic(self.node, peer, self.id)
        with _database(self.node) as db:
            db.execute("INSERT OR REPLACE INTO runtime VALUES (?,?,'idle','Content synchronized','[]','[]')",
                       (peer, self.id))
        owner = private_root(self.node) / 'federation-content-sync.lock'
        candidate = {'peer_id': peer, 'project_id': self.id, 'eligible': True, 'reason': None}
        with owner.open('a+b') as handle, \
                patch('spikes.federation_sync.synchronize', side_effect=AssertionError('dispatch')), \
                patch.object(control, 'candidates', return_value=[candidate]), \
                patch('spikes.sync_fingerprint.probe', return_value=None):
            owner.chmod(0o600); fcntl.flock(handle, fcntl.LOCK_EX)
            with self.assertRaises(OutboundDeferred):
                control.synchronize(peer, self.id, defer_when_busy=True)
            self.assertEqual(control.run_automatic(), {'enabled': True, 'attempted': 0})
        with _database(self.node) as db:
            self.assertEqual(db.execute('SELECT state,detail FROM runtime').fetchone(),
                             ('idle', 'Content synchronized'))
        after = diagnostic(self.node, peer, self.id)
        self.assertEqual((after['state'], after['phase']), (before['state'], before['phase']))
        self.assertIsNone(after['error_type'])
        self.assertTrue(automatic_retry.ready((str(self.node.absolute()), peer, self.id)))
        self.assertNotEqual((observation(self.node, peer, self.id) or {}).get('state'), 'unavailable')

    def test_manual_worker_waits_for_a_streamed_owner_up_to_the_stream_cap(self):
        from spikes.peer_transport import CONTENT_SYNC_MAX_WAIT
        tasks = ManualSyncTasks(); peer = str(uuid4()); seen = []
        def run(control, peer_id, project_id, **options):
            seen.append(options['owner_wait'])
        with patch.object(ContentSyncControl, 'synchronize', run):
            tasks.start(self.node, 'desktop', peer, self.id)
            for row in list(tasks.tasks.values()): row['thread'].join(5)
        self.assertEqual(seen, [CONTENT_SYNC_MAX_WAIT])
        with self.assertRaises(ValueError):
            ContentSyncControl(self.node, deployment='desktop').synchronize(
                peer, self.id, owner_wait=CONTENT_SYNC_MAX_WAIT + 1)

@unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
class SyncQueueUITests(unittest.TestCase):
    def test_queued_work_is_polled_and_busy_summary_never_claims_success(self):
        from spikes.web_administration import ADMIN_JS as JS
        functions='\n'.join(line for line in JS.splitlines() if line.startswith(
            ('function contentSyncSummary(', 'function contentSyncIsBusy(')))
        script="const assert=require('node:assert/strict');let administrationState={content_sync_statuses:{one:{state:'queued'}}};\n"+functions+"""
assert.equal(contentSyncIsBusy(),true);
const chats={active_mappings:0,shared:0,received:0};
for(const state of ['queued','running','busy','offline','error','conflict']){
 assert.equal(contentSyncSummary({state,detail:'Not finished',chat_summary:chats}),'Not finished');
}
assert(contentSyncSummary({state:'idle',chat_summary:chats}).includes('Git data byla synchronizována'));
administrationState.content_sync_statuses.one.state='idle';assert.equal(contentSyncIsBusy(),false);
"""
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_status_poll_survives_busy_without_retrying_mutations_or_denied_access(self):
        from spikes.web_administration import ADMIN_JS as JS
        start=JS.index('async function adminRequest(')
        request=JS[start:JS.index('\n}',start)+2]
        functions='\n'.join(line for line in JS.splitlines() if line.startswith(
            ('function contentSyncSummary(', 'function contentSyncIsBusy(', 'function scheduleContentSyncPoll(')))
        script="""
const assert=require('node:assert/strict');
let administrationState={content_sync_statuses:{'peer:project':{state:'queued'}}},contentSyncPoll=null,timer=null;
const setTimeout=fn=>{assert.equal(timer,null);timer=fn;return 1;};
function showAdminStatus(){}function renderAdministration(){scheduleContentSyncPoll();}
const document={dispatchEvent(){}};class CustomEvent{constructor(name,options){}}
"""+request+'\n'+functions+"""
(async()=>{
 global.fetch=async()=>({ok:false,status:503,json:async()=>({error:'busy'})});
 await assert.rejects(adminRequest({action:'list'}),error=>error.status===503);
 let calls=0;
 adminRequest=async request=>{assert.deepEqual(request,{action:'list'});calls++;
  if(calls===1)throw Object.assign(Error('busy'),{status:503});
  return {content_sync_statuses:{'peer:project':{state:'idle',detail:'Done'}}};
 };
 const run=async()=>{const callback=timer;timer=null;await callback();};
 scheduleContentSyncPoll();await run();assert(timer,'Busy stopped status polling');
 await run();assert.equal(timer,null);assert.equal(calls,2);
 administrationState.content_sync_statuses['peer:project'].state='queued';
 adminRequest=async request=>{assert.deepEqual(request,{action:'list'});throw Object.assign(Error('denied'),{status:401});};
 scheduleContentSyncPoll();await run();assert.equal(timer,null,'Unauthorized poll must stop');
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
