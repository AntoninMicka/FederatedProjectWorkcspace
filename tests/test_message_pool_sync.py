# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import unittest
from uuid import uuid4

from tests import test_federation_sync as sync_fixture
from tests.test_monitoring_blocks import blocks, response
from spikes.monitoring import Monitoring
from spikes.composable_monitoring import ComposableMonitoring
from spikes.projects import Projects
from spikes.federation_sync import _prepare, _apply, SyncReceiver
from spikes.message_pools import MessagePools
from spikes.metadata import ValidationError


class PoolSyncTests(unittest.TestCase):
    def setUp(self):
        self.f=sync_fixture.FederationSyncTests('test_initial_import_and_fast_forward_work_in_both_directions')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.services=[ComposableMonitoring(Monitoring(n,Projects(n),clock=lambda:1794160000),
            fetcher=lambda *a,**kw:response()) for n in self.f.nodes]
        self.specs=blocks(self.f.nodes[0]);self.pid=self.f.project_id
        s=self.services[0];head=s.monitoring.projects.repository(self.pid).head()
        s.blocks.save(self.pid,head,self.specs,str(uuid4()))
        self.f.exchange(0,1)

    def test_collector_to_assigned_model_and_published_output_roundtrip(self):
        """Native signed sync, real model journal, controlled external transport."""
        from spikes.ollama_backend import OllamaBinding, OllamaBindings, OllamaAdapter
        desktop, collector = self.services
        processing = next(b for b in desktop.blocks.read(self.pid)['blocks']
                          if b['id'] == self.specs[3]['id'])
        spec = deepcopy(self.specs[3]); spec['previous'] = [processing['ref']]
        spec['value']['config']['mode'] = 'llm'
        desktop.blocks.save(self.pid, desktop.blocks.read(self.pid)['commit_id'], [spec], str(uuid4()))
        self.f.exchange(0, 1)
        calls = []
        root = self.f.nodes[0].parent / ('.' + self.f.nodes[0].name + '.chat')
        root.mkdir(mode=0o700, exist_ok=True)
        binding = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
            revision='v1', adapter='ollama', boundary='same-node',
            endpoint='http://127.0.0.1:11434', model='synthetic', target_id='local-process'))
        OllamaBindings(root).save(binding)
        def model(binding, request):
            calls.append(request)
            return dict(model=binding.model, response='# Posouzený návrh\nEnergie dnes', done=True)
        desktop.monitoring.adapter_factory = lambda runs: OllamaAdapter(runs,
            transport=model, runtime_probe=lambda b: dict(status='unknown'))
        collector.monitoring.adapter_factory = lambda *a: self.fail('Model fell back to collector')
        collector.configure(self.pid, self.specs[0]['id'], True, confirm=True)
        collector.tick(self.pid)
        self.assertEqual(calls, [])
        with self.assertRaisesRegex(ValidationError, 'another node'):
            collector._process(self.pid, spec['id'], str(uuid4()),scheduled=True)
        self.f.exchange(1, 0)
        self.assertTrue(next(b for b in desktop.catalog(self.pid)['blocks']
                              if b['id'] == self.specs[0]['id'])['runtime']['enabled'])
        run_id = str(uuid4())
        draft = desktop.process(self.pid, spec['id'], run_id)
        self.assertEqual(draft['state'], 'review'); self.assertEqual(len(calls), 1)
        self.assertEqual(desktop.process(self.pid, spec['id'], run_id), draft)
        self.assertEqual(len(calls), 1)
        job = next(j for j in desktop.catalog(self.pid)['jobs'] if j['id'] == run_id)
        frozen = job['intent']['pools'][self.specs[1]['id']][0]
        self.assertEqual(frozen['revisions'][0]['item']['content'], 'Energie dnes')
        self.assertEqual(frozen['observations'][0]['node_id'], self.f.node_ids[1])
        self.assertEqual(collector.monitoring.current_view(self.pid)['outputs'], [])
        instant=draft['result']['protection']['until']
        desktop.clock=desktop.pools.clock=desktop.monitoring.clock=lambda:instant
        desktop.tick(self.pid,lane='processing')
        issued = desktop.publish(self.pid, run_id, draft['result']['approval_digest'], confirm=True)
        presentation = desktop.monitoring.output_presentation(self.pid, issued['report_ref']['artifact_id'],
            desktop.monitoring.projects.repository(self.pid).head(), confirm=True)
        self.f.exchange(0, 1)
        received = collector.monitoring.current_view(self.pid)
        self.assertEqual(len(received['outputs']), 1)
        output = received['outputs'][0]
        self.assertEqual(output['id'], issued['report_ref']['artifact_id'])
        self.assertEqual(output['run_id'], run_id)
        self.assertEqual(output['title'], draft['result']['output']['title'])
        self.assertEqual(output['presentations'][0]['artifact_id'], presentation['artifact_id'])
        self.assertEqual(output['presentations'][0]['source_ref'], presentation['report_ref'])
        self.assertFalse(output['presentations'][0]['potentially_stale'])
        detail = collector.monitoring.output(self.pid, output['id'], received['commit_id'])
        self.assertEqual(detail['markdown'], draft['result']['markdown'])
        self.assertTrue(any(j['id']==run_id and j.get('shared') for j in received['block_catalog']['jobs']))
        with collector.pools.read_db() as db:
            self.assertIsNone(db.execute('SELECT id FROM block_jobs WHERE id=?',(run_id,)).fetchone())
        self.f.exchange(0, 1)
        self.assertEqual(collector.monitoring.current_view(self.pid)['outputs'], received['outputs'])
        self.assertEqual(len(calls), 1)

    def test_readonly_fingerprint_tracks_pool_changes_and_expiry_without_cleanup(self):
        from spikes.sync_fingerprint import collect
        from spikes.pool_sync import export
        from unittest.mock import patch
        before = collect(self.f.services[0], self.f.node_ids[1], self.pid)
        source = self.services[0]
        source.configure(self.pid, self.specs[0]['id'], True, confirm=True)
        source.tick(self.pid)
        after = collect(self.f.services[0], self.f.node_ids[1], self.pid)
        self.assertNotEqual(before, after)
        with source.pools.db() as db:
            rows_before = db.execute('SELECT * FROM pool_entries').fetchall()
        with patch('spikes.message_pools.MessagePools.__init__', side_effect=AssertionError('writer')):
            raw = export(self.f.nodes[0], self.pid, read_only=True)
            self.assertTrue(raw)
            expired = MessagePools.export_readonly(self.f.nodes[0], self.pid, clock=lambda: 9999999999)
            self.assertTrue(expired);self.assertTrue(all(r['kind']=='activation' for r in expired))
        with source.pools.db() as db:
            self.assertEqual(db.execute('SELECT * FROM pool_entries').fetchall(), rows_before)
        self.assertEqual(MessagePools.export_readonly(self.f.nodes[0], self.pid,
                         clock=source.pools.clock), source.pools.export(self.pid, transferable=True))

    def test_signed_bidirectional_pool_sync_converges_redundant_intake_without_grants(self):
        # Receiving definitions never activates either node.
        self.assertIsNone(self.services[1].catalog(self.pid)['blocks'][0]['runtime'])
        for s in self.services:
            s.configure(self.pid,self.specs[0]['id'],True,confirm=True);s.tick(self.pid)
        head=self.services[0].monitoring.projects.repository(self.pid).head()
        self.f.exchange(0,1);self.f.exchange(1,0)
        a,b=[s.pools.export(self.pid) for s in self.services]
        self.assertEqual(a,b)
        view=self.services[0].pools.view(self.pid,self.specs[1]['id'])
        self.assertEqual(len(view),1);self.assertEqual(len(view[0]['revisions']),1)
        self.assertEqual(len(view[0]['observations']),2)
        self.assertEqual(self.services[0].monitoring.projects.repository(self.pid).head(),head)
        self.f.exchange(0,1)
        self.assertEqual(self.services[1].pools.export(self.pid),b)

    def test_desktop_to_receiver_preserves_filter_task_and_collected_content(self):
        source, target = self.services
        # Read the receiver's actual catalog, not only its Git HEAD.
        rows = {b['id']: b for b in target.catalog(self.pid)['blocks']}
        for spec in self.specs:
            self.assertEqual(rows[spec['id']]['value'], spec['value'])
            self.assertEqual(rows[spec['id']]['privacy'], spec['privacy'])
            self.assertIsNone(rows[spec['id']]['runtime'])
        source.configure(self.pid, self.specs[0]['id'], True, confirm=True)
        source.tick(self.pid)
        self.f.exchange(0, 1)
        catalog = target.catalog(self.pid)
        pool = next(b for b in catalog['blocks'] if b['id'] == self.specs[1]['id'])
        self.assertEqual(pool['message_count'], 1)
        self.assertIsNotNone(pool['last_received_sync'])
        received = target.pools.view(self.pid, pool['id'])
        self.assertEqual(received[0]['revisions'][0]['item']['content'], 'Energie dnes')
        self.assertTrue(next(b for b in catalog['blocks'] if b['id']==self.specs[0]['id'])['runtime']['enabled'])
        self.assertTrue(all(b['runtime'] is None for b in catalog['blocks'] if b['id']!=self.specs[0]['id']))
        self.assertFalse(any(j['intent']['kind'] == 'processing' for j in catalog['jobs']))

    def test_deleted_blocks_sync_without_losing_pool_provenance_or_activating_receiver(self):
        source,target=self.services
        source.configure(self.pid,self.specs[0]['id'],True,confirm=True);source.tick(self.pid)
        for index in (4,2):
            catalog=source.catalog(self.pid)
            row=next(b for b in catalog['blocks'] if b['id']==self.specs[index]['id'])
            block=dict(id=row['id'],previous=[row['ref']],privacy=row['privacy'],value=dict(row['value'],deleted=True))
            source.remove(self.pid,catalog['commit_id'],block,str(uuid4()),confirm=True)
        self.f.exchange(0,1)
        received=target.catalog(self.pid)
        self.assertNotIn(self.specs[4]['id'],{b['id'] for b in received['blocks']})
        self.assertNotIn(self.specs[2]['id'],{b['id'] for b in received['blocks']})
        self.assertEqual(target.pools.view(self.pid,self.specs[1]['id'])[0]['revisions'][0]['item']['content'],'Energie dnes')
        self.assertTrue(next(b for b in received['blocks'] if b['id']==self.specs[0]['id'])['runtime']['enabled'])
        self.f.exchange(0,1)
        self.assertEqual(len(target.catalog(self.pid)['blocks']),3)

    def test_legacy_deletion_is_signed_and_receiver_keeps_original_definition(self):
        from spikes.monitoring_definitions import MonitoringDefinitions
        from spikes.monitoring_deletion import MonitoringDeletion
        from tests.test_monitoring_workflow import workflow
        definitions=MonitoringDefinitions(self.f.nodes[0])
        request=workflow(self.pid,self.services[0].blocks.read(self.pid)['commit_id'])
        definitions.save_workflow(request,str(uuid4()))
        deletion=MonitoringDeletion(self.services[0].monitoring)
        preview=deletion.preview(self.pid,'definition',request['processing']['watch_id'])
        deletion.remove(self.pid,preview['base_head'],preview['sources'],str(uuid4()),confirm=True)
        self.f.exchange(0,1)
        received=MonitoringDefinitions(self.f.nodes[1]).read(self.pid)
        self.assertEqual([r['watch_id'] for r in received['definitions']],[request['collection']['watch_id']])
        self.assertTrue(all(r['runtime_state']=='not-connected' for r in received['definitions']))
        records=self.services[1].blocks.reporting.read(self.pid)['records']
        self.assertTrue(any(r['type']=='MonitoringDeletion' for r in records))
        self.assertEqual(sum(r['type']=='WatchDefinition' for r in records),2)

    def test_published_report_is_visible_from_git_without_receiver_runtime_job(self):
        source,target=self.services
        source.configure(self.pid,self.specs[0]['id'],True,confirm=True);source.tick(self.pid)
        run=str(uuid4());prepared=source.process(self.pid,self.specs[3]['id'],run)
        instant=prepared['result']['protection']['until'];source.clock=source.pools.clock=source.monitoring.clock=lambda:instant
        source.tick(self.pid,lane='processing')
        issued=source.publish(self.pid,run,prepared['result']['approval_digest'],confirm=True)
        self.f.exchange(0,1)
        view=target.monitoring.view(self.pid)
        report=next(r for r in view['outputs'] if r['id']==issued['report_ref']['artifact_id'])
        self.assertEqual(report['title'],prepared['result']['output']['title'])
        self.assertNotIn('markdown',report)
        self.assertTrue(any(j['id']==run and j.get('shared') for j in target.catalog(self.pid)['jobs']))
        with target.pools.read_db() as db:self.assertIsNone(db.execute('SELECT id FROM block_jobs WHERE id=?',(run,)).fetchone())
        detail=target.monitoring.output(self.pid,report['id'],view['commit_id'])
        self.assertIn('Energie dnes',detail['markdown'])
        self.assertEqual(detail['run_id'],run)

    def test_sidecar_tampering_is_rejected_before_application(self):
        s=self.services[0];s.configure(self.pid,self.specs[0]['id'],True,confirm=True);s.tick(self.pid)
        env,payload,*_=_prepare(self.f.services[0],self.f.node_ids[1],self.pid,str(uuid4()),[],force_bundle=True)
        self.assertEqual(env['exchange']['schema_version'],3)
        with self.assertRaisesRegex(ValidationError,'digest'):
            SyncReceiver(self.f.nodes[1],self.f.services[1]).receive(env,payload[:-1]+b' ')
        self.assertEqual(self.services[1].pools.export(self.pid),[])

    def test_pool_crash_in_signed_exchange_rolls_forward_once(self):
        s=self.services[0];s.configure(self.pid,self.specs[0]['id'],True,confirm=True);s.tick(self.pid)
        env,payload,*_=_prepare(self.f.services[0],self.f.node_ids[1],self.pid,str(uuid4()),[],force_bundle=True)
        def crash(stage):
            if stage=='pool-inserted':raise RuntimeError('pool crash')
        receiver=SyncReceiver(self.f.nodes[1],self.f.services[1])
        with self.assertRaisesRegex(RuntimeError,'pool crash'):receiver.receive(env,payload,crash)
        from spikes.sync_diagnostics import snapshot
        diagnostic = snapshot(self.f.nodes[1], self.f.node_ids[0], self.pid)
        self.assertEqual(diagnostic['phase'], 'receive-publication')
        self.assertEqual(diagnostic['state'], 'failed')
        self.assertEqual(self.services[1].pools.export(self.pid),[])
        receiver.receive(env,payload);receiver.receive(env,payload)
        self.assertEqual(snapshot(self.f.nodes[1], self.f.node_ids[0], self.pid)['state'], 'finished')
        self.assertEqual(s.pools.export(self.pid),self.services[1].pools.export(self.pid))
