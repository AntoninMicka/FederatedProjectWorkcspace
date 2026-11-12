# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import subprocess
import sys
import unittest
from uuid import uuid4
from tests import test_monitoring_blocks as blocks_fixture
from tests import test_reporting_scheduler as scheduler_fixture
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from spikes.report_outputs import published_outputs,output_title
from spikes.metadata import ValidationError


class ReportOutputTests(unittest.TestCase):
    def test_presentation_source_metadata_rejects_deep_or_ambiguous_json(self):
        from spikes.report_outputs import PRESENTATION_SOURCE,presentation_source
        pin=dict(project_id=str(uuid4()),artifact_id=str(uuid4()),commit_id='a'*40,
                 path='',sha256='b'*64)
        pin['path']='artifacts/'+pin['artifact_id']+'/content.md'
        metadata=dict(tags=['monitoring-derived-presentation'],description=PRESENTATION_SOURCE+json.dumps(pin))
        self.assertEqual(presentation_source(metadata),pin)
        metadata['description']=PRESENTATION_SOURCE+'['*1100+'0'+']'*1100
        self.assertIsNone(presentation_source(metadata))
        raw=json.dumps(pin);metadata['description']=PRESENTATION_SOURCE+'{"project_id":"'+str(uuid4())+'",'+raw[1:]
        self.assertIsNone(presentation_source(metadata))

    def issued_block(self):
        f=blocks_fixture.BlockTests('test_report_publication_is_reviewed_and_idempotent')
        f.setUp();self.addCleanup(f.doCleanups)
        f.activate();f.service.tick(f.f.project);run=str(uuid4())
        draft=f.service.process(f.f.project,f.specs[3]['id'],run)
        issued=f.service.publish(f.f.project,run,draft['result']['approval_digest'],confirm=True)
        return f,issued['report_ref']['artifact_id']

    def test_derived_presentation_pins_source_replays_and_preserves_old_deck_after_correction(self):
        from spikes.artifacts import Artifacts
        from spikes.presentation_documents import PresentationDocuments,decode_deck
        from spikes.report_outputs import presentation_source
        f,output_id=self.issued_block();pid=f.f.project;head=f.f.git.head()
        f.monitoring.adapter_factory=lambda *a:self.fail('Presentation dispatched a model')
        with self.assertRaises(ValidationError):
            f.monitoring.output_presentation(pid,output_id,head,confirm=False)
        with self.assertRaises(ValidationError):
            f.monitoring.output_presentation(pid,output_id,'0'*40,confirm=True)
        self.assertEqual(f.f.git.head(),head)
        result=f.monitoring.output_presentation(pid,output_id,head,confirm=True)
        self.assertEqual(result,f.monitoring.output_presentation(pid,output_id,head,confirm=True))
        reused=f.monitoring.output_presentation(pid,output_id,f.f.git.head(),confirm=True)
        self.assertEqual(reused['artifact_id'],result['artifact_id'])
        files=f.f.git.snapshot(f.f.git.head());path='artifacts/'+result['artifact_id']+'/content.md';original=files[path]
        metadata=json.loads(files[path.rsplit('/',1)[0]+'/metadata.json'])
        self.assertEqual(presentation_source(metadata),result['report_ref'])
        self.assertEqual(metadata['privacy'],'project')
        deck=decode_deck(original.decode());self.assertIn(result['report_ref']['sha256'],deck['slides'][0]['notes'])
        docs=PresentationDocuments(f.f.node).open(pid)['documents']
        self.assertEqual(next(d for d in docs if d['id']==result['artifact_id'])['report_source'],result['report_ref'])
        view=f.monitoring.current_view(pid);self.assertFalse(view['outputs'][0]['presentations'][0]['potentially_stale'])
        Artifacts(f.f.node).save(dict(project_id=pid,artifact_id=output_id,title='Opravená zpráva',body='# Oprava\nNová evidence',
            new=False,base_head=f.f.git.head()),str(uuid4()))
        view=f.monitoring.current_view(pid);self.assertTrue(view['outputs'][0]['presentations'][0]['potentially_stale'])
        self.assertEqual(f.f.git.snapshot(f.f.git.head())[path],original)
        replacement=f.monitoring.output_presentation(pid,output_id,view['commit_id'],confirm=True)
        self.assertNotEqual(replacement['artifact_id'],result['artifact_id'])
        links=f.monitoring.current_view(pid)['outputs'][0]['presentations']
        self.assertEqual(len(links),2);self.assertEqual(sum(not p['potentially_stale'] for p in links),1)
        self.assertEqual(f.f.git.snapshot(f.f.git.head())[path],original)

    def test_presentation_process_crash_recovers_original_operation_before_and_after_ref(self):
        for stage in ('before-ref','ref-updated'):
            with self.subTest(stage=stage):
                f,output_id=self.issued_block();head=f.f.git.head()
                script='''
import os,sys
from spikes.monitoring import Monitoring
from spikes.projects import Projects
def checkpoint(stage):
 if stage==sys.argv[5]:os._exit(73)
Monitoring(sys.argv[1],Projects(sys.argv[1])).output_presentation(sys.argv[2],sys.argv[3],sys.argv[4],confirm=True,checkpoint=checkpoint)
'''
                child=subprocess.run([sys.executable,'-c',script,str(f.f.node),f.f.project,output_id,head,stage],capture_output=True,text=True,timeout=20)
                self.assertEqual(child.returncode,73,child.stderr)
                recovered=Monitoring(f.f.node,Projects(f.f.node))
                result=recovered.output_presentation(f.f.project,output_id,head,confirm=True)
                published_head=f.f.git.head()
                self.assertEqual(recovered.output_presentation(f.f.project,output_id,head,confirm=True),result)
                self.assertEqual(f.f.git.head(),published_head)
                links=recovered.current_view(f.f.project)['outputs'][0]['presentations']
                self.assertEqual(len(links),1);self.assertEqual(links[0]['artifact_id'],result['artifact_id'])

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
