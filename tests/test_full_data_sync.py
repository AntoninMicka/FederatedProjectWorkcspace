# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Whole-project reporting/source closure over the existing two-node transport."""
from copy import deepcopy
import json
import base64
from pathlib import Path
import tempfile
import subprocess
import sys
from importlib.util import find_spec
import unittest
from unittest.mock import patch
from uuid import uuid4

from tests import test_reporting as reporting_fixtures
from tests import test_federation_sync as sync_fixtures
from spikes.administration import Administration
from spikes.artifacts import Artifacts
from spikes.federation_accounts import MappingSignatures
from spikes.federation_sync import _build_bundle, _prepare, SyncReceiver
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.reporting import Reporting, operation_uuid
from spikes.reporting_schema import encoded
from spikes.source_import import Sources, request_from_bytes


class FullDataSyncTests(unittest.TestCase):
    def setUp(self):
        self.f=reporting_fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.nodes=[self.f.node,self.f.base/'recipient'/'node.json']
        self.nodes[1].parent.mkdir(mode=0o700)
        ProjectCreation(self.nodes[1]).initialize_node()
        self.project_id=self.f.project
        self.actor=dict(id=None,node_role='federation-admin',memberships={})
        self.services=[Administration(n,deployment='web') for n in self.nodes]
        self.node_ids=[self.state(i)['node_id'] for i in range(2)]
        pins=[MappingSignatures(s.root).identity()['fingerprint'] for s in self.services]
        for local,remote in ((0,1),(1,0)):
            state=self.change(local,action='add-peer-relationship',relationship_type='p2p',
                              sharing_level='same-team',node_id=self.node_ids[remote],name='Fixture peer',
                              endpoint='https://127.0.0.1:8443',fingerprint=pins[remote])
            self.services[local].request(self.actor,dict(action='set-trust',expected_commit=state['commit_id'],
                                                       node_id=self.node_ids[remote],trust='approved'))

    state=sync_fixtures.FederationSyncTests.state
    change=sync_fixtures.FederationSyncTests.change
    exchange=sync_fixtures.FederationSyncTests.exchange

    def captured_source(self):
        raw=b'Synthetic authorized evidence: first observation.\n'
        request=request_from_bytes(self.project_id,self.f.git.head(),'evidence.md',raw,
                                   'Fixture evidence','Synthetic permission and retention fixture',[], 'project')
        Sources(self.nodes[0]).import_source(request,str(uuid4()))
        raw_pin=self.f.service.pin(self.project_id,request['artifact_id'])
        value=deepcopy(self.f.record(self.f.source())['value'])
        value.update(capture_state='captured',raw_ref=raw_pin,retrieved_at='2026-01-01T00:00:00Z')
        value['license'].update(identifier='synthetic-test-only',terms_ref=self.f.policy,capture_allowed=True)
        return self.f.store('Source',value),raw_pin,raw

    def corrupt_pin(self):
        source=self.f.source();record=self.f.record(source)
        revision=str(uuid4());record.update(revision_id=revision,entity_id=str(uuid4()))
        record['value']['license']['retention_policy']['sha256']='0'*64
        # Emulate an untrusted peer that bypassed the native writer.
        metadata=json.loads(self.f.git.snapshot(self.f.git.head())['artifacts/'+source['artifact_id']+'/metadata.json'])
        metadata['id']=revision
        root=self.f.git.root/'artifacts'/revision;root.mkdir()
        (root/'metadata.json').write_bytes(encoded(metadata));(root/'record.json').write_bytes(encoded(record))
        self.f.git.commit('Untrusted mismatched reporting pin')
        return source

    def test_whole_report_and_raw_evidence_roundtrip_without_connector_or_local_journals(self):
        captured,raw_pin,raw=self.captured_source();event=self.f.event([captured])
        report=self.f.publish(self.f.publication([event],[captured]));before=self.f.git.head()
        with patch('spikes.source_collector.SourceCollector.fetch',side_effect=AssertionError('No connector')):
            self.exchange(0,1)
        receiver=Projects(self.nodes[1]).workspace(self.project_id)
        self.assertEqual(receiver.git.head(),before)
        self.assertEqual(receiver.git.snapshot(before),self.f.git.snapshot(before))
        self.assertEqual(receiver.git.snapshot(raw_pin['commit_id'])[raw_pin['path']],raw)
        self.assertIn(report['artifact_id'],{r['revision_id'] for r in Reporting(self.nodes[1]).read(self.project_id)['records']})
        value=deepcopy(self.f.record(captured)['value']);value['title']='Observation added on recipient'
        operation=str(uuid4())
        Reporting(self.nodes[1]).apply(dict(project_id=self.project_id,base_head=receiver.git.head(),records=[
            dict(type='Source',entity_id=None,previous=[],privacy='project',value=value)]),operation)
        expected=receiver.git.head();self.exchange(0,1)
        self.assertEqual(self.f.git.head(),expected)
        self.assertIn(operation_uuid(operation,'record:0'),{r['revision_id'] for r in self.f.service.read(self.project_id)['records']})
        snapshot=self.f.git.snapshot(expected);self.exchange(1,0)
        self.assertEqual(self.f.git.head(),expected);self.assertEqual(receiver.git.head(),expected)
        self.assertEqual(receiver.git.snapshot(expected),snapshot)
        self.assertTrue(all(p=='project.json' or p.startswith(('artifacts/','registries/')) for p in snapshot))

    def test_sender_rejects_invalid_reporting_pin_before_preparing_transfer(self):
        self.corrupt_pin();head=self.f.git.head()
        with self.assertRaisesRegex(ValidationError,'Pinned reporting bytes mismatch'):
            _build_bundle(self.nodes[0],self.project_id,dict(mode='all'))
        self.assertEqual(self.f.git.head(),head)
        self.assertFalse(Projects(self.nodes[1]).catalog())

    def test_receiver_rejects_signed_but_semantically_invalid_bundle_before_publication(self):
        self.exchange(0,1)
        receiver=Projects(self.nodes[1]).workspace(self.project_id);before=receiver.git.head()
        self.corrupt_pin()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'malicious.bundle'
            self.f.git.run('bundle','create',str(path),'refs/heads/main')
            refs=[dict(ref='refs/heads/main',head=self.f.git.head())]
            with patch('spikes.federation_sync._build_bundle',return_value=(refs,path.read_bytes())):
                envelope,payload,*_=_prepare(self.services[0],self.node_ids[1],self.project_id,str(uuid4()),[],force_bundle=True)
        with self.assertRaisesRegex(ValidationError,'Pinned reporting bytes mismatch'):
            SyncReceiver(self.nodes[1],self.services[1]).receive(envelope,payload)
        self.assertEqual(receiver.git.head(),before)
        self.assertEqual(receiver.git.snapshot(before),self.f.git.snapshot(before))

    def test_hidden_branch_input_is_not_silently_transferred_or_treated_as_complete(self):
        self.f.git.run('checkout','-b','hidden-inputs')
        identity=str(uuid4())
        Artifacts(self.nodes[0]).save(dict(project_id=self.project_id,base_head=self.f.git.head(),
            artifact_id=identity,title='Hidden policy',body='Synthetic hidden input',new=True),str(uuid4()))
        hidden=self.f.service.pin(self.project_id,identity)
        self.f.git.run('checkout','main')
        value=deepcopy(self.f.record(self.f.source())['value']);value['license']['retention_policy']=hidden
        self.f.store('Source',value)
        # The sender can resolve the pin, but the selected branch's bundle cannot.
        with self.assertRaisesRegex(ValidationError,'Reference must pin a commit'):
            _build_bundle(self.nodes[0],self.project_id,dict(mode='selected-only',branches=['refs/heads/main']))
        refs,payload=_build_bundle(self.nodes[0],self.project_id,dict(mode='all'))
        self.assertEqual(len(refs),2);self.assertTrue(payload)

    def test_bare_repository_with_unborn_head_validates_each_reporting_commit(self):
        self.f.publish();refs,payload=_build_bundle(self.nodes[0],self.project_id,dict(mode='all'))
        from spikes.federation_sync import _validate_git_bundle
        with tempfile.TemporaryDirectory() as directory:
            _validate_git_bundle(payload,refs,self.project_id,Path(directory)/'bare.git')

    def diverge(self, *, duplicate_reports=False):
        self.exchange(0,1)
        receiver=Projects(self.nodes[1]).workspace(self.project_id)
        if duplicate_reports:
            value=self.f.publication();self.f.publish(deepcopy(value));kind='ReportSnapshot'
            extra=dict(markdown='# Přehled\n\nNebyla doložena významná změna.\n')
        else:
            value=deepcopy(self.f.record(self.f.source('Source A'))['value']);value['title']='Source B';kind='Source';extra={}
        operation=str(uuid4())
        Reporting(self.nodes[1]).apply(dict(project_id=self.project_id,base_head=receiver.git.head(),records=[
            dict(type=kind,entity_id=None,previous=[],privacy='project',value=value,**extra)]),operation,confirm=duplicate_reports)
        left=self.f.git.head();right=receiver.git.head();response=self.exchange(0,1)
        self.assertTrue(response['conflict'])
        self.assertEqual(self.f.git.head(),left);self.assertEqual(receiver.git.head(),right)
        incoming='refs/federation/incoming/'+self.node_ids[1]+'/'+response['exchange']['operation_id']+'/main'
        from spikes.conflict_resolution import ConflictResolution
        resolver=ConflictResolution(self.nodes[0]);view=resolver.preview(self.project_id,left,incoming)
        request={k:view[k] for k in ('project_id','expected_head','incoming_ref','incoming_head','base','preview_sha256')}
        request['resolutions']=[dict(path=row['path'],choice='auto') for row in view['files']]
        return resolver,request,left,right,receiver

    def test_disjoint_reporting_changes_merge_only_after_explicit_semantic_review(self):
        resolver,request,left,right,receiver=self.diverge()
        merged=resolver.confirm(request,str(uuid4()))['commit_id']
        self.assertEqual(self.f.git.run('show','-s','--format=%P',merged).stdout.split(),[left,right])
        self.exchange(0,1);self.assertEqual(receiver.git.head(),merged)
        titles={r['value'].get('title') for r in self.f.service.read(self.project_id)['records']}
        self.assertTrue({'Source A','Source B'}<=titles)

    def test_text_clean_duplicate_period_is_rejected_without_overwriting_either_branch(self):
        resolver,request,left,right,receiver=self.diverge(duplicate_reports=True)
        with self.assertRaisesRegex(ValidationError,'Period already has a base publication'):
            resolver.confirm(request,str(uuid4()))
        self.assertEqual(self.f.git.head(),left);self.assertEqual(receiver.git.head(),right)
        self.assertEqual(self.f.git.run('rev-parse',request['incoming_ref']).stdout.strip(),right)

    def test_reporting_transfer_recovers_after_real_exit_between_ref_and_index(self):
        self.exchange(0,1)
        source,_,_=self.captured_source();event=self.f.event([source])
        self.f.publish(self.f.publication([event],[source]))
        head=self.f.git.head()
        envelope,payload,*_=_prepare(self.services[0],self.node_ids[1],self.project_id,str(uuid4()),[],force_bundle=True)
        request=self.f.base/'request.json'
        request.write_bytes(encoded(dict(envelope=envelope,payload=base64.b64encode(payload).decode())))
        script='''
import base64,json,os,sys
from spikes.administration import Administration
from spikes.federation_sync import SyncReceiver
v=json.load(open(sys.argv[2]))
def stop(stage):
 if stage=='ref-updated':os._exit(73)
SyncReceiver(sys.argv[1],Administration(sys.argv[1])).receive(v['envelope'],base64.b64decode(v['payload']),checkpoint=stop)
'''
        child=subprocess.run([sys.executable,'-c',script,str(self.nodes[1]),str(request)],capture_output=True,text=True,timeout=60)
        self.assertEqual(child.returncode,73,child.stderr)
        receiver=SyncReceiver(self.nodes[1],self.services[1])
        first=receiver.receive(envelope,payload);second=receiver.receive(envelope,payload)
        self.assertEqual(first,second)
        view=Projects(self.nodes[1]).open(self.project_id)
        self.assertEqual(view['commit_id'],head)
        self.assertEqual(Projects(self.nodes[1]).workspace(self.project_id).git.snapshot(head),self.f.git.snapshot(head))

    @unittest.skipUnless(find_spec('spikes.monitoring_definitions') is not None,
                         'MON-08 schemas are developed on a separate feature branch')
    def test_monitoring_definitions_and_findings_sync_without_activating_recipient(self):
        from spikes.monitoring_definitions import MonitoringDefinitions
        from spikes.rss_monitoring import RSSMonitoring
        from tests.test_monitoring_definitions import definition
        from tests.test_monitoring_filters import pipeline
        from tests.test_rss_pilot import rss
        value=definition();value['selection']['pipeline']=pipeline();identity=str(uuid4())
        saved=MonitoringDefinitions(self.nodes[0]).save(dict(project_id=self.project_id,base_head=self.f.git.head(),
            watch_id=identity,previous=[],privacy='project',definition=value),str(uuid4()))
        collector=RSSMonitoring(self.nodes[0],fetcher=lambda *args,**kwargs:dict(status=200,raw=rss(),validators={}))
        collector.configure(dict(project_id=self.project_id,watch_id=identity,input_id=value['inputs'][0]['id'],
                                 definition_ref=saved['definition_ref'],enabled=True,mode='pipeline'),confirm=True)
        collector.tick(self.project_id)
        original=collector.status(self.project_id)
        self.assertTrue(original['findings']);self.exchange(0,1)
        definitions=MonitoringDefinitions(self.nodes[1]).read(self.project_id)['definitions']
        self.assertEqual(definitions[0]['watch_id'],identity)
        self.assertEqual(definitions[0]['runtime_state'],'not-connected')
        remote=RSSMonitoring(self.nodes[1],fetcher=lambda *args,**kwargs:(_ for _ in ()).throw(AssertionError('No remote activation')))
        remote.tick(self.project_id);status=remote.status(self.project_id)
        self.assertEqual(status['bindings'],[])
        self.assertEqual({r['revision_id'] for r in status['findings']},{r['revision_id'] for r in original['findings']})


if __name__=='__main__':
    unittest.main()
