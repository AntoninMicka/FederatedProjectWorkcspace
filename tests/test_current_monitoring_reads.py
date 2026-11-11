# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_rss_monitoring as rss_fixture
from tests import test_monitoring_blocks as block_fixture
from tests import test_federation_sync as sync_fixture
from spikes.artifacts import Artifacts
from spikes.federation_sync import _prepare, SyncReceiver
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from spikes.reporting import Reporting
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation


class CurrentMonitoringReadTests(unittest.TestCase):
    def test_captured_rss_and_pool_entries_are_not_project_documents(self):
        f=rss_fixture.RSSMonitoringTests('test_15_minute_collection_is_independent_of_daily_output_and_never_calls_llm')
        f.setUp();self.addCleanup(f.doCleanups)
        f.runtime.tick(f.f.project)
        findings=f.findings();self.assertTrue(findings)
        excluded={r['revision_id'] for r in findings}|{r['value']['raw_ref']['artifact_id'] for r in findings}
        view=Projects(f.f.node).open(f.f.project)
        self.assertFalse(excluded & {r['id'] for r in view['artifacts']})
        catalog=Artifacts(f.f.node).open(f.f.project)
        self.assertFalse(excluded & {r['id'] for r in catalog['documents']+catalog['sources']})
        stored_ids={path.split('/')[1] for path in f.f.git.snapshot(f.f.git.head())
                    if path.startswith('artifacts/')}
        self.assertTrue(excluded <= stored_ids)
        b=block_fixture.BlockTests('test_shared_blocks_usage_and_atomic_validation');b.setUp();self.addCleanup(b.doCleanups)
        b.activate();b.service.tick(b.f.project)
        pool=b.service.pools.export(b.f.project);self.assertTrue(pool)
        documents=Projects(b.f.node).open(b.f.project)['artifacts']
        self.assertFalse({r['id'] for r in pool} & {r['id'] for r in documents})
        self.assertFalse({r['value']['item']['title'] for r in pool if r['kind']=='item'}
                         & {r['title'] for r in documents})

    def test_registry_records_do_not_become_documents(self):
        from tests import test_reporting as fixture
        from tests.fixtures import registry
        f=fixture.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        f.setUp();self.addCleanup(f.doCleanups)
        identity=str(uuid4())
        path='registries/decisions/'+identity+'.json'
        f.ws.transact(str(uuid4()),dict(action='test-registry'),
            lambda _:({path:registry('Registry decision',identity)},'Test','test@example.org','Add registry'))
        view=Projects(f.node).open(f.project)
        self.assertNotIn(identity,{row['id'] for row in view['artifacts']})
        self.assertIn(path,f.git.snapshot(f.git.head()))

    def test_slow_reporting_validation_does_not_block_real_sync_publication(self):
        f=sync_fixture.FederationSyncTests('test_initial_import_and_fast_forward_work_in_both_directions')
        f.setUp();self.addCleanup(f.doCleanups);f.exchange(0,1)
        entered=threading.Event();release=threading.Event();errors=[]
        original=__import__('spikes.reporting',fromlist=['validate_git']).validate_git
        def validate(*args,**kwargs):
            entered.set()
            if not release.wait(10):raise AssertionError('validation was not released')
            return original(*args,**kwargs)
        def read():
            try:Reporting(f.nodes[1]).read_snapshot(f.project_id,read_only=True)
            except Exception as exc:errors.append(exc)
        with patch('spikes.reporting.validate_git',validate):
            reader=threading.Thread(target=read,daemon=True);reader.start()
            try:
                self.assertTrue(entered.wait(3))
                new_head=f.commit_marker(0,'Sync while reporting reads old HEAD')
                request,payload,*_=_prepare(f.services[0],f.node_ids[1],f.project_id,str(uuid4()),[],force_bundle=True)
                response,_=SyncReceiver(f.nodes[1],f.services[1]).receive(request,payload)
                self.assertFalse(response['conflict'])
                self.assertEqual(Projects(f.nodes[1]).repository(f.project_id).head(),new_head)
                self.assertTrue(reader.is_alive())
            finally:release.set();reader.join(5)
        self.assertFalse(reader.is_alive());self.assertEqual(len(errors),1)
        self.assertIsInstance(errors[0],StaleIndex)

    def test_readonly_snapshot_refuses_pending_intent_without_recovery_or_index_creation(self):
        f=block_fixture.BlockTests('test_shared_blocks_usage_and_atomic_validation');f.setUp();self.addCleanup(f.doCleanups)
        ws=Projects(f.f.node).workspace(f.f.project,for_snapshot=True)
        before=ws.git.head()
        with self.assertRaises(PermissionError):
            ws.transact(str(uuid4()),dict(action='forbidden'),lambda *_:self.fail('writer reached'))
        self.assertEqual(ws.git.head(),before)
        with self.assertRaises(PermissionError):ws.recover()
        with ws.journal.connect() as db:db.execute('INSERT INTO pending VALUES(?,?,?)',('artifacts/x/body.md',None,b'draft'))
        with patch('spikes.workspace.Index',side_effect=AssertionError('index initialization')), \
             patch('spikes.workspace.Workspace.recover',side_effect=AssertionError('recovery')):
            with self.assertRaises(PendingOperation):Reporting(f.f.node).read_snapshot(f.f.project,read_only=True)
        with ws.journal.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM pending').fetchone()[0],1)

    def test_current_view_uses_one_snapshot_without_legacy_services_or_per_block_pinning(self):
        f=block_fixture.BlockTests('test_shared_blocks_usage_and_atomic_validation');f.setUp();self.addCleanup(f.doCleanups)
        with patch.object(Monitoring,'jobs',side_effect=AssertionError('legacy jobs')), \
             patch.object(Monitoring,'view',side_effect=AssertionError('legacy view')), \
             patch.object(Reporting,'pin',side_effect=AssertionError('per-block pin')):
            view=f.monitoring.current_view(f.f.project)
        self.assertEqual(len(view['block_catalog']['blocks']),5)
        self.assertEqual(view['commit_id'],view['block_catalog']['commit_id'])
        self.assertNotIn('watches',view);self.assertNotIn('definitions',view)

    def test_idle_block_scheduler_never_opens_project_or_scans_git_catalog(self):
        f=block_fixture.BlockTests('test_shared_blocks_usage_and_atomic_validation');f.setUp();self.addCleanup(f.doCleanups)
        with patch.object(f.monitoring.projects,'catalog',side_effect=AssertionError('Git catalog')), \
             patch.object(f.monitoring,'_writable',side_effect=AssertionError('project owner')), \
             patch('spikes.monitoring_blocks.MonitoringBlocks.read',side_effect=AssertionError('Git validation')):
            f.monitoring.tick_blocks()
        self.assertFalse(f.monitoring.last_errors)

    def test_source_not_due_does_not_revalidate_git_or_open_project_owner(self):
        f=block_fixture.BlockTests('test_shared_blocks_usage_and_atomic_validation');f.setUp();self.addCleanup(f.doCleanups)
        f.activate();f.service.tick(f.f.project)
        with patch.object(f.service.blocks,'read',side_effect=AssertionError('not due')), \
             patch.object(f.monitoring,'_writable',side_effect=AssertionError('project owner')), \
             patch.object(f.service,'fetcher',side_effect=AssertionError('network')):
            f.service.tick(f.f.project)

    def test_normal_start_never_runs_legacy_scheduler(self):
        f=block_fixture.BlockTests('test_shared_blocks_usage_and_atomic_validation');f.setUp();self.addCleanup(f.doCleanups)
        with patch('spikes.monitoring.threading.Thread') as thread:
            f.monitoring.start();loop=thread.call_args.kwargs['target']
            with patch.object(f.monitoring.stop_event,'wait',side_effect=[False,True]), \
                 patch.object(f.monitoring,'tick',side_effect=AssertionError('legacy tick')), \
                 patch.object(f.monitoring,'tick_blocks') as tick:
                loop();tick.assert_called_once_with()
