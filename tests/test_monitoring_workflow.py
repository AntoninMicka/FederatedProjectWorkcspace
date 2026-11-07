# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import json
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_reporting as fixtures
from tests.test_monitoring_definitions import definition
from tests.test_monitoring_filters import pipeline
from spikes.metadata import ValidationError
from spikes.monitoring_definitions import MonitoringDefinitions
from spikes.monitoring_definition_schema import validate_definition
from spikes.monitoring import Monitoring
from spikes.projects import Projects
from spikes.reporting_schema import encoded


def workflow(project_id, head):
    collection=str(uuid4());processing=str(uuid4())
    c=definition('Těžba');c['selection']['pipeline']=pipeline()
    p=definition('Zpracování','weekly',upstream=collection)
    p['schedule']['trigger']='manual'
    p['inputs'][0].update(take='findings',include_drafts=False,
                         policy=dict(window='ending-in-period',approval='selected',missing='wait'))
    return dict(project_id=project_id,base_head=head,privacy='project',
                collection=dict(watch_id=collection,previous=[],definition=c),
                processing=dict(watch_id=processing,previous=[],definition=p))


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.service=MonitoringDefinitions(self.f.node)

    def test_independent_nodes_and_trigger_are_saved_once_without_dispatch(self):
        request=workflow(self.f.project,self.f.git.head())
        request['collection']['definition']['placement']=dict(mode='node',node_id=str(uuid4()),capabilities=[])
        request['processing']['definition']['placement']=dict(mode='node',node_id=str(uuid4()),capabilities=[])
        request['processing']['definition']['schedule']['trigger']='scheduled'
        operation=str(uuid4());count=int(self.f.git.run('rev-list','--count','HEAD').stdout)
        with patch('spikes.source_collector.SourceCollector.fetch',side_effect=AssertionError('No dispatch')):
            saved=self.service.save_workflow(request,operation)
            self.assertEqual(self.service.save_workflow(request,operation),saved)
        self.assertEqual(int(self.f.git.run('rev-list','--count','HEAD').stdout),count+1)
        rows=self.service.read(self.f.project)['definitions'];self.assertEqual(len(rows),2)
        self.assertEqual({r['runtime_state'] for r in rows},{'not-connected'})
        self.assertEqual({r['definition']['placement']['node_id'] for r in rows},
                         {request[name]['definition']['placement']['node_id'] for name in ('collection','processing')})
        with self.assertRaisesRegex(ValidationError,'Remote'):
            self.service.run_workflow(self.f.project,saved['stages']['processing']['definition_ref'],'2026-10-05')

    def test_invalid_second_stage_writes_neither_definition(self):
        request=workflow(self.f.project,self.f.git.head());head=self.f.git.head()
        request['processing']['definition']['inputs'][0]['watch_id']=str(uuid4())
        with self.assertRaisesRegex(ValidationError,'consume selected'):
            self.service.save_workflow(request,str(uuid4()))
        self.assertEqual(self.f.git.head(),head)
        self.assertEqual(self.service.read(self.f.project)['definitions'],[])

    def test_two_stage_edit_retains_ids_and_original_revisions(self):
        request=workflow(self.f.project,self.f.git.head())
        first=self.service.save_workflow(request,str(uuid4()))
        request['base_head']=self.f.git.head()
        for name in ('collection','processing'):
            request[name]['previous']=[first['stages'][name]['definition_ref']]
        request['processing']['definition']['schedule']['trigger']='scheduled'
        self.service.save_workflow(request,str(uuid4()))
        rows=self.service.read(self.f.project)['definitions']
        self.assertEqual({r['watch_id'] for r in rows},{request[n]['watch_id'] for n in ('collection','processing')})
        for name in ('collection','processing'):
            pin=first['stages'][name]['definition_ref']
            self.assertIn(pin['path'],self.f.git.snapshot(self.f.git.head()))

    def test_manual_processing_waits_for_stored_findings_without_fetch(self):
        saved=self.service.save_workflow(workflow(self.f.project,self.f.git.head()),str(uuid4()))
        with patch('spikes.source_collector.SourceCollector.fetch',side_effect=AssertionError('No fetch')):
            result=self.service.run_workflow(self.f.project,saved['stages']['processing']['definition_ref'],'2026-10-05')
        self.assertEqual(result['state'],'waiting-inputs')

    def test_trigger_is_closed_and_old_definitions_remain_valid(self):
        value=definition();validate_definition(value)
        for trigger in ('manual','scheduled'):
            value['schedule']['trigger']=trigger;validate_definition(value)
        for trigger in ('automatic',True,{},None):
            value['schedule']['trigger']=trigger
            with self.assertRaises((ValidationError,TypeError)):validate_definition(value)

    def test_inventory_is_read_only_and_contains_no_connection_material(self):
        from spikes.administration import Administration
        admin=Administration(self.f.node,deployment='desktop')
        service=Monitoring(self.f.node,Projects(self.f.node))
        self.assertEqual(len(service.execution_nodes(admin)['nodes']),1)
        self.assertFalse(admin.root.exists())
        actor=dict(id=None,node_role='federation-admin',memberships={})
        state=admin.request(actor,dict(action='list'));peer=str(uuid4())
        state=admin.request(actor,dict(action='add-peer',expected_commit=state['commit_id'],node_id=peer,
                                     name='Omnia test',endpoint='https://192.168.100.2:8443',fingerprint='a'*64))
        self.assertEqual(len(service.execution_nodes(admin)['nodes']),1)
        state=admin.request(actor,dict(action='set-trust',expected_commit=state['commit_id'],node_id=peer,trust='approved'))
        inventory=service.execution_nodes(admin)
        self.assertEqual(inventory['nodes'][-1],dict(id=peer,name='Omnia test',local=False))
        self.assertNotIn('endpoint',json.dumps(inventory));self.assertNotIn('fingerprint',json.dumps(inventory))

    def test_process_crash_recovers_both_stages_with_one_receipt(self):
        script='''
import json,os,sys
from spikes.monitoring_definitions import MonitoringDefinitions
def stop(stage):
 if stage==sys.argv[4]:os._exit(73)
MonitoringDefinitions(sys.argv[1]).save_workflow(json.load(open(sys.argv[2])),sys.argv[3],checkpoint=stop)
'''
        for stage in ('prepared','files-applied','before-ref','ref-updated','indexed','completed'):
            with self.subTest(stage=stage):
                request=workflow(self.f.project,self.f.git.head());operation=str(uuid4())
                path=self.f.base/'workflow.json';path.write_bytes(encoded(request))
                count=int(self.f.git.run('rev-list','--count','HEAD').stdout)
                result=subprocess.run([sys.executable,'-c',script,str(self.f.node),str(path),operation,stage],
                                      capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,73,result.stderr)
                self.f.ws.recover();saved=self.service.save_workflow(request,operation)
                self.assertEqual(self.f.git.head(),saved['receipt']['commit_id'])
                self.assertEqual(int(self.f.git.run('rev-list','--count','HEAD').stdout),count+1)
