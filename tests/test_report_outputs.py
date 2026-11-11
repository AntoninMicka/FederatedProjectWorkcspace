# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from uuid import uuid4
from tests import test_monitoring_blocks as blocks_fixture
from tests import test_reporting_scheduler as scheduler_fixture
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from spikes.report_outputs import published_outputs,output_title
from spikes.metadata import ValidationError


class ReportOutputTests(unittest.TestCase):
    def test_composable_report_has_stable_built_name_and_direct_git_content(self):
        f=blocks_fixture.BlockTests('test_report_publication_is_reviewed_and_idempotent');f.setUp();self.addCleanup(f.doCleanups)
        f.activate();f.service.tick(f.f.project);run=str(uuid4())
        prepared=f.service.process(f.f.project,f.specs[3]['id'],run)
        expected=prepared['result']['output']['title']
        self.assertIn('2026-',expected);self.assertRegex(expected,r'\d{2}:\d{2}:\d{2}')
        issued=f.service.publish(f.f.project,run,prepared['result']['approval_digest'],confirm=True)
        view=f.monitoring.view(f.f.project);self.assertEqual(len(view['outputs']),1)
        summary=view['outputs'][0];self.assertEqual(summary['title'],expected);self.assertNotIn('markdown',summary)
        detail=f.monitoring.output(f.f.project,summary['id'],view['commit_id'])
        self.assertIn('Energie dnes',detail['markdown']);self.assertNotIn('Frozen monitoring input',detail['markdown'])
        self.assertEqual(detail['run_id'],run)
        before=f.f.git.head();f.service.publish(f.f.project,run,prepared['result']['approval_digest'],confirm=True)
        self.assertEqual(f.f.git.head(),before)
        self.assertEqual(f.monitoring.view(f.f.project)['outputs'][0]['title'],expected)
        for index in (4,3):
            catalog=f.service.catalog(f.f.project);row=next(b for b in catalog['blocks'] if b['id']==f.specs[index]['id'])
            block=dict(id=row['id'],previous=[row['ref']],privacy=row['privacy'],value=dict(row['value'],deleted=True))
            f.service.remove(f.f.project,catalog['commit_id'],block,str(uuid4()),confirm=True)
        self.assertEqual(f.monitoring.view(f.f.project)['outputs'][0]['title'],expected)
        ws,head,files,entities,records=f.monitoring._data(f.f.project)
        unrelated=str(uuid4());entities[unrelated]=dict(kind='document',file='unrelated.md')
        files['artifacts/'+unrelated+'/unrelated.md']=b'\xffunrelated opaque bytes'
        self.assertEqual(len(published_outputs(f.f.project,head,files,entities,records)),1)
        files[detail['report_ref']['path']]=b'# User-edited report without the old audit footer'
        edited=published_outputs(f.f.project,head,files,entities,records,selected=summary['id'],include_content=True)
        self.assertEqual(edited[0]['title'],expected)
        self.assertIn('User-edited report',edited[0]['markdown'])
        with self.assertRaises(ValidationError):f.monitoring.output(f.f.project,summary['id'],'0'*40)

    def test_scheduler_freezes_assembly_time_before_approval_and_keeps_content_hash(self):
        f=scheduler_fixture.ReportingSchedulerTests('test_one_reservation_even_for_two_workers_and_fresh_pin_commit')
        f.setUp();self.addCleanup(f.doCleanups)
        run=f.enqueue();preview=f.approve(run)
        output=preview['run']['candidate']['output'];markdown=f.scheduler.preview(run['run_id'])['request']['records'][0]['markdown']
        f.clock[0]+=86400
        issued=f.scheduler.publish(run['run_id']);head=f.git.head();files=f.git.snapshot(head)
        metadata=json.loads(files[issued['workspace_receipt']['snapshot']['path'].rsplit('/',1)[0]+'/metadata.json'])
        self.assertEqual(metadata['title'],output['title'])
        self.assertEqual(metadata['description'],'fpw-output-built-at:'+output['built_at'])
        projection=Monitoring(f.node,Projects(f.node)).view(f.project)
        detail=Monitoring(f.node,Projects(f.node)).output(f.project,projection['outputs'][0]['id'],head)
        self.assertEqual(detail['markdown'],markdown)
        self.assertEqual(projection['outputs'][0]['title'],output['title'])
        self.assertEqual(f.scheduler.publish(run['run_id']),issued);self.assertEqual(f.git.head(),head)
