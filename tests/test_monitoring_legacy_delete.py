# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4
from tests import test_monitoring as legacy
from tests import test_monitoring_workflow as workflow_fixture
from spikes.monitoring_deletion import MonitoringDeletion
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from spikes.metadata import ValidationError
from spikes.storage import StaleIndex
from spikes.reporting_schema import encoded


class LegacyDeleteTests(unittest.TestCase):
    def test_plain_watch_retirement_replays_and_never_grants_old_configuration(self):
        f=legacy.MonitoringTests('test_busy_after_collection_lease_is_unknown_and_never_automatically_replayed')
        f.setUp();self.addCleanup(f.doCleanups)
        service=MonitoringDeletion(f.service);preview=service.preview(f.pid,'watch',f.cfg['id'])
        self.assertEqual(preview['blockers'],[])
        operation=str(uuid4())
        receipt=service.remove(f.pid,preview['base_head'],preview['sources'],operation,confirm=True)
        head=f.f.git.head()
        self.assertEqual(service.remove(f.pid,preview['base_head'],preview['sources'],operation,confirm=True),receipt)
        self.assertEqual(f.f.git.head(),head)
        self.assertEqual(f.service.view(f.pid)['watches'],[])
        self.assertFalse(f.service.granted(f.pid,f.cfg))
        with self.assertRaisesRegex(ValidationError,'odstraněno'):f.save()
        self.assertIn(f.cfg['id'],f.service._data(f.pid)[3])

    def test_definition_dependency_is_atomic_and_both_stages_can_be_deleted_in_order(self):
        f=workflow_fixture.WorkflowTests('test_independent_nodes_and_trigger_are_saved_once_without_dispatch')
        f.setUp();self.addCleanup(f.doCleanups)
        request=workflow_fixture.workflow(f.f.project,f.f.git.head())
        f.service.save_workflow(request,str(uuid4()))
        monitoring=Monitoring(f.f.node,Projects(f.f.node));service=MonitoringDeletion(monitoring)
        collection=request['collection']['watch_id'];processing=request['processing']['watch_id']
        preview=service.preview(f.f.project,'definition',collection)
        self.assertTrue(preview['blockers']);stale=preview;head=f.f.git.head()
        with self.assertRaisesRegex(ValidationError,'missing'):
            service.remove(f.f.project,head,preview['sources'],str(uuid4()),confirm=True)
        self.assertEqual(head,f.f.git.head())
        for identity in (processing,collection):
            preview=service.preview(f.f.project,'definition',identity)
            self.assertEqual(preview['blockers'],[])
            service.remove(f.f.project,preview['base_head'],preview['sources'],str(uuid4()),confirm=True)
            if identity==processing:
                with self.assertRaises((ValidationError,StaleIndex)):
                    service.remove(f.f.project,stale['base_head'],stale['sources'],str(uuid4()),confirm=True)
        self.assertEqual(f.service.read(f.f.project)['definitions'],[])
        records=f.service.reporting.read(f.f.project)['records']
        self.assertEqual(sum(r['type']=='WatchDefinition' for r in records),2)
        self.assertEqual(sum(r['type']=='MonitoringDeletion' for r in records),2)

    def test_unknown_rss_blocks_legacy_deletion_and_native_crash_recovers_once(self):
        f=legacy.MonitoringTests('test_busy_after_collection_lease_is_unknown_and_never_automatically_replayed')
        f.setUp();self.addCleanup(f.doCleanups)
        service=MonitoringDeletion(f.service);id_=str(uuid4())
        with f.service.scheduler.db() as db:
            db.execute('INSERT INTO rss_polls VALUES(?,?,?,?,NULL,NULL,NULL)',(id_,'binding','unknown',encoded(dict(project_id=f.pid,watch_id=f.cfg['id']))))
        preview=service.preview(f.pid,'watch',f.cfg['id']);self.assertTrue(preview['blockers'])
        with self.assertRaisesRegex(ValidationError,'neznámý'):
            service.remove(f.pid,preview['base_head'],preview['sources'],str(uuid4()),confirm=True)
        with f.service.scheduler.db() as db:db.execute("UPDATE rss_polls SET state='failed' WHERE id=?",(id_,))
        operation=str(uuid4())
        def crash(stage):
            if stage=='before-ref':raise RuntimeError('crash')
        with self.assertRaises(RuntimeError):service.remove(f.pid,preview['base_head'],preview['sources'],operation,confirm=True,checkpoint=crash)
        service.remove(f.pid,preview['base_head'],preview['sources'],operation,confirm=True)
        head=f.f.git.head()
        service.remove(f.pid,preview['base_head'],preview['sources'],operation,confirm=True)
        self.assertEqual(head,f.f.git.head())
        self.assertEqual(f.service.view(f.pid)['watches'],[])

    def test_post_ref_interruption_replays_from_deleted_current_head(self):
        f=legacy.MonitoringTests('test_busy_after_collection_lease_is_unknown_and_never_automatically_replayed')
        f.setUp();self.addCleanup(f.doCleanups)
        service=MonitoringDeletion(f.service);preview=service.preview(f.pid,'watch',f.cfg['id']);operation=str(uuid4())
        def crash(stage):
            if stage=='ref-updated':raise RuntimeError('after commit')
        with self.assertRaises(RuntimeError):service.remove(f.pid,preview['base_head'],preview['sources'],operation,confirm=True,checkpoint=crash)
        head=f.f.git.head()
        service.remove(f.pid,preview['base_head'],preview['sources'],operation,confirm=True)
        self.assertEqual(f.f.git.head(),head)
        self.assertEqual(f.service.view(f.pid)['watches'],[])
        self.assertEqual(sum(r['type']=='MonitoringDeletion' for r in f.service.reporting.read(f.pid)['records']),1)
