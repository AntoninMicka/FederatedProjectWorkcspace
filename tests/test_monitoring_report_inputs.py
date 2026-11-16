# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
import unittest
from uuid import uuid4
from tests import test_report_protection as fixture
from spikes.metadata import ValidationError
from spikes.monitoring_report_inputs import read_link,expected_slots


class ReportInputTests(unittest.TestCase):
    setUp=fixture.ProtectionTests.setUp
    clock=fixture.ProtectionTests.clock
    job=fixture.ProtectionTests.job

    def setUp(self):
        fixture.ProtectionTests.setUp(self);self.clock()

    def downstream(self,source=None,title='Měsíční syntéza'):
        spec=deepcopy(self.specs[3]);spec['id']=str(uuid4());spec['value']['title']=title
        spec['value']['config'].update(pool_ids=[],search_ids=[],report_task_ids=[source or self.specs[3]['id']],lookback_days=31)
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()));return spec

    def issue(self,task=None,source=None):
        if source:
            draft=self.service.reprocess(self.f.project,source,str(uuid4()),confirm=True)
        else:draft=self.service.process(self.f.project,task or self.specs[3]['id'],str(uuid4()))
        until=draft['result']['protection']['until'];self.instant[0]=max(self.instant[0],until)
        self.service.tick(self.f.project,lane='processing')
        result=self.job(draft['id'])['result']
        issued=self.service.publish(self.f.project,draft['id'],result['approval_digest'],confirm=True)
        return draft['id'],issued

    def test_stable_creator_pinned_edition_and_no_connector_fetch(self):
        source,edition=self.issue();down=self.downstream()
        self.service.fetcher=lambda *a,**k:self.fail('No repeated collection')
        self.service.searcher=lambda *a,**k:self.fail('No supplemental search')
        draft=self.service.process(self.f.project,down['id'],str(uuid4()));job=self.job(draft['id'])
        link=job['intent']['report_inputs'][0]
        self.assertEqual(link['task_id'],self.specs[3]['id']);self.assertEqual(link['run_id'],source)
        self.assertEqual(link['ref']['artifact_id'],edition['report_ref']['artifact_id'])
        self.assertIn('Vydaná vstupní zpráva:',draft['result']['markdown'])
        self.assertEqual(read_link(self.service.blocks.reporting,self.f.project,link,'project')['processing_id'],self.specs[3]['id'])
        self.assertEqual(self.service.process(self.f.project,down['id'],draft['id']),draft)

    def test_llm_manifest_contains_exact_issued_artifact_and_unknown_is_not_replayed(self):
        from spikes.ollama_backend import OllamaBinding,OllamaBindings,OllamaAdapter
        source,edition=self.issue();down=self.downstream()
        block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==down['id'])
        down['previous']=[block['ref']];down['value']['config']['mode']='llm'
        self.service.blocks.save(self.f.project,self.f.git.head(),[down],str(uuid4()))
        root=self.service.node.parent/('.'+self.service.node.name+'.chat');root.mkdir(mode=0o700,exist_ok=True)
        binding=OllamaBinding.parse(dict(schema_version=1,binding_id=str(uuid4()),revision='v1',adapter='ollama',boundary='same-node',endpoint='http://127.0.0.1:11434',model='synthetic',target_id='local-process'))
        OllamaBindings(root).save(binding);calls=[]
        def transport(binding,request):
            calls.append(request);return dict(model=binding.model,response='Syntéza z vydané zprávy',done=True)
        self.monitoring.adapter_factory=lambda runs:OllamaAdapter(runs,transport=transport,runtime_probe=lambda b:dict(status='unknown'))
        run=str(uuid4());draft=self.service.process(self.f.project,down['id'],run)
        self.assertEqual(draft['state'],'review');self.assertEqual(len(calls),1)
        manifest=self.job(run)['intent']['manifest']
        self.assertTrue(any(i.get('input_id')==edition['report_ref']['artifact_id'] and i.get('source')=='project' for i in manifest['inputs']))
        self.service.process(self.f.project,down['id'],run);self.assertEqual(len(calls),1)
        def lost(binding,request):calls.append(request);raise TimeoutError('lost response')
        self.monitoring.adapter_factory=lambda runs:OllamaAdapter(runs,transport=lost,runtime_probe=lambda b:dict(status='unknown'))
        uncertain=str(uuid4())
        with self.assertRaises(Exception):self.service.process(self.f.project,down['id'],uncertain)
        self.assertEqual(self.service.process(self.f.project,down['id'],uncertain)['state'],'unknown')
        self.assertEqual(len(calls),2)


    def test_missing_issued_inputs_fail_without_model_or_draft_substitution(self):
        self.service.process(self.f.project,self.specs[3]['id'],str(uuid4()))
        down=self.downstream();run=str(uuid4())
        self.service._model=lambda *a,**k:self.fail('Missing input must fail before model')
        with self.assertRaisesRegex(ValidationError,'Chybí vydané'):
            self.service.process(self.f.project,down['id'],run)
        self.assertEqual(self.job(run)['state'],'failed')

    def test_cycles_and_privacy_are_rejected_atomically(self):
        down=self.downstream();source=deepcopy(self.specs[3]);block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==source['id'])
        source['previous']=[block['ref']];source['value']['config']['report_task_ids']=[down['id']]
        head=self.f.git.head()
        with self.assertRaisesRegex(ValidationError,'Cycle'):
            self.service.blocks.save(self.f.project,head,[source],str(uuid4()))
        self.assertEqual(self.f.git.head(),head)
        duplicate=deepcopy(down);duplicate['id']=str(uuid4());duplicate['value']['config']['report_task_ids']*=2
        with self.assertRaisesRegex(ValidationError,'Duplicate reporting entry'):
            self.service.blocks.save(self.f.project,head,[duplicate],str(uuid4()))
        lowered=deepcopy(down);lowered['id']=str(uuid4());lowered['privacy']='public'
        with self.assertRaisesRegex(ValidationError,'privacy'):
            self.service.blocks.save(self.f.project,head,[lowered],str(uuid4()))

    def test_rename_preserves_creator_and_issued_edition(self):
        source,_=self.issue();down=self.downstream()
        spec=deepcopy(self.specs[3]);block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==spec['id'])
        spec['previous']=[block['ref']];spec['value']['title']='Přejmenovaná týdenní zpráva'
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        draft=self.service.process(self.f.project,down['id'],str(uuid4()))
        self.assertEqual(self.job(draft['id'])['intent']['report_inputs'][0]['run_id'],source)

    def test_correction_marks_monthly_and_annual_outputs_and_new_run_uses_replacement(self):
        source,_=self.issue();month=self.downstream();monthly,monthly_edition=self.issue(month['id'])
        annual=self.downstream(month['id'],'Roční syntéza');yearly,_=self.issue(annual['id'])
        before=self.job(yearly)['result']['markdown']
        corrected,new_edition=self.issue(source=source)
        self.assertTrue(self.job(monthly)['input_evidence']['potentially_stale'])
        self.assertTrue(self.job(yearly)['input_evidence']['potentially_stale'])
        outputs=self.monitoring.current_view(self.f.project)['outputs']
        self.assertTrue(next(o for o in outputs if o.get('run_id')==yearly)['potentially_stale'])
        self.assertEqual(self.job(yearly)['result']['markdown'],before)
        frozen=self.job(monthly)['intent']['report_inputs'][0]
        self.assertEqual(read_link(self.service.blocks.reporting,self.f.project,frozen,'project')['run_id'],source)
        new=self.service.reprocess(self.f.project,monthly,str(uuid4()),confirm=True)
        links=self.job(new['id'])['intent']['report_inputs'];self.assertEqual(len(links),1);self.assertEqual(links[0]['run_id'],corrected)

    def test_competing_corrections_are_not_silently_selected(self):
        source,_=self.issue();self.issue(source=source);self.issue(source=source);down=self.downstream()
        with self.assertRaisesRegex(ValidationError,'Souběžné opravy'):
            self.service.process(self.f.project,down['id'],str(uuid4()))

    def test_report_only_protection_does_not_regenerate_on_unrelated_git_commit(self):
        self.issue();down=self.downstream();draft=self.service.process(self.f.project,down['id'],str(uuid4()))
        extra=deepcopy(self.specs[1]);extra['id']=str(uuid4())
        self.service.blocks.save(self.f.project,self.f.git.head(),[extra],str(uuid4()))
        self.instant[0]=draft['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        guard=self.job(draft['id'])['result']['protection']
        self.assertTrue(guard['finalized']);self.assertNotIn('regenerated_run_id',guard)

    def test_late_scheduled_source_is_selected_by_slot_not_actual_build(self):
        from datetime import datetime,timezone
        from spikes.monitoring_report_inputs import select
        self.instant[0]=datetime(2026,11,8,10,tzinfo=timezone.utc).timestamp();anchor=self.instant[0]
        spec=deepcopy(self.specs[3]);block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==spec['id'])
        spec['previous']=[block['ref']];spec['value']['config']['schedule'].update(kind='daily',time='00:00')
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        self.instant[0]+=7200;source,_=self.issue()
        snapshot=self.service.blocks.reporting.read_snapshot(self.f.project,read_only=True)
        links,_,_=select(snapshot,self.f.project,[spec['id']],anchor-86400,anchor,'project')
        self.assertEqual(links[0]['run_id'],source)

    def test_late_correction_regenerates_only_at_protection_end(self):
        source,_=self.issue();down=self.downstream();draft=self.service.process(self.f.project,down['id'],str(uuid4()))
        original=self.job(draft['id'])['intent']['report_inputs']
        corrected,_=self.issue(source=source)
        self.service.tick(self.f.project,lane='processing')
        middle=self.job(draft['id'])
        self.assertTrue(middle['result']['protection']['changed']);self.assertFalse(middle['result']['protection']['finalized'])
        self.assertEqual(middle['intent']['report_inputs'],original)
        self.instant[0]=draft['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        final=self.job(draft['id'])
        self.assertTrue(final['result']['protection']['finalized'])
        self.assertEqual(final['intent']['report_inputs'][0]['run_id'],corrected)
        self.assertEqual(final['result']['initial_draft']['report_inputs'],original)

    def test_incomplete_issued_periods_produce_publishable_llm_summary_with_warning(self):
        source,_=self.issue();down=self.downstream()
        spec=deepcopy(self.specs[3]);block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==spec['id'])
        spec['previous']=[block['ref']];spec['value']['config']['schedule']['kind']='weekly'
        self.service.blocks.save(self.f.project,self.f.git.head(),[spec],str(uuid4()))
        block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==down['id'])
        down['previous']=[block['ref']];down['value']['config']['mode']='llm'
        self.service.blocks.save(self.f.project,self.f.git.head(),[down],str(uuid4()))
        calls=[]
        def model(*args,**kwargs):calls.append(args);return 'Shrnutí dostupných vydání.'
        self.service._model=model
        draft=self.service.process(self.f.project,down['id'],str(uuid4()))
        job=self.job(draft['id']);self.assertEqual(draft['state'],'review');self.assertEqual(len(calls),1)
        gap=job['intent']['report_gaps'][0]
        self.assertEqual(gap['task_id'],spec['id']);self.assertTrue(gap['periods']);self.assertFalse(gap['missing_all'])
        self.assertIn('Neúplné pokrytí',calls[0][2]);self.assertIn('Neúplné pokrytí',draft['result']['markdown'])
        self.assertIn('Shrnutí dostupných vydání.',draft['result']['markdown'])
        self.instant[0]=draft['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        final=self.job(draft['id']);self.assertTrue(final['result']['protection']['finalized'])
        self.assertEqual(len(calls),1)
        published=self.service.publish(self.f.project,draft['id'],final['result']['approval_digest'],confirm=True)
        output=self.monitoring.output(self.f.project,published['report_ref']['artifact_id'],self.f.git.head())
        self.assertEqual(output['report_gaps'],job['intent']['report_gaps'])
        self.assertEqual(output['input_evidence']['report_gaps'],job['intent']['report_gaps'])
        self.assertIn('Neúplné pokrytí',output['markdown'])

    def test_missing_entire_report_source_does_not_block_available_pool(self):
        self.service.configure(self.f.project,self.specs[0]['id'],True,confirm=True);self.service.tick(self.f.project,lane='intake')
        down=self.downstream();block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==down['id'])
        down['previous']=[block['ref']];down['value']['config']['pool_ids']=[self.specs[1]['id']]
        self.service.blocks.save(self.f.project,self.f.git.head(),[down],str(uuid4()))
        result=self.service.process(self.f.project,down['id'],str(uuid4()))
        self.assertEqual(result['state'],'review');self.assertIn('Energie dnes',result['result']['markdown'])
        self.assertTrue(self.job(result['id'])['intent']['report_gaps'][0]['missing_all'])

    def test_late_missing_source_clears_gap_only_at_guard_end(self):
        self.issue();other=deepcopy(self.specs[3]);other['id']=str(uuid4());other['value']['title']='Druhý denní zdroj'
        self.service.blocks.save(self.f.project,self.f.git.head(),[other],str(uuid4()))
        pending=self.service.process(self.f.project,other['id'],str(uuid4()))
        self.instant[0]=pending['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        down=self.downstream();block=next(b for b in self.service.blocks.read(self.f.project)['blocks'] if b['id']==down['id'])
        down['previous']=[block['ref']];down['value']['config']['report_task_ids'].append(other['id'])
        self.service.blocks.save(self.f.project,self.f.git.head(),[down],str(uuid4()))
        draft=self.service.process(self.f.project,down['id'],str(uuid4()))
        self.assertTrue(self.job(draft['id'])['intent']['report_gaps'][0]['missing_all'])
        completed=self.job(pending['id'])['result']
        self.service.publish(self.f.project,pending['id'],completed['approval_digest'],confirm=True)
        self.service.tick(self.f.project,lane='processing')
        middle=self.job(draft['id']);self.assertTrue(middle['result']['protection']['changed']);self.assertIn('report_gaps',middle['intent'])
        self.instant[0]=draft['result']['protection']['until'];self.service.tick(self.f.project,lane='processing')
        final=self.job(draft['id']);self.assertTrue(final['result']['protection']['finalized']);self.assertNotIn('report_gaps',final['intent'])
        self.assertEqual(len(final['intent']['report_inputs']),2);self.assertTrue(final['result']['initial_draft']['report_gaps'])
        self.assertNotIn('Neúplné pokrytí',final['result']['markdown'])


class ReportChainSyncTests(unittest.TestCase):
    def setUp(self):
        import time
        from tests import test_message_pool_sync as sync_fixture
        sync_fixture.PoolSyncTests.setUp(self)
        self.instant=[time.time()]
        for service in self.services:service.clock=service.pools.clock=service.monitoring.clock=lambda:self.instant[0]

    def test_chain_inputs_sync_as_pins_and_receiving_node_runs_locally(self):
        from spikes.monitoring_report_inputs import read_link
        from spikes import pool_sync
        from spikes.message_pools import entry
        from spikes.reporting_schema import encoded
        source,target=self.services
        down=deepcopy(self.specs[3]);down['id']=str(uuid4());down['value']['title']='Měsíční zpráva'
        other=deepcopy(self.specs[3]);other['id']=str(uuid4());other['value']['title']='Chybějící denní zdroj'
        down['value']['config'].update(pool_ids=[],search_ids=[],report_task_ids=[self.specs[3]['id'],other['id']],lookback_days=31)
        source.blocks.save(self.pid,source.blocks.read(self.pid)['commit_id'],[down,other],str(uuid4()))
        initial=source.process(self.pid,self.specs[3]['id'],str(uuid4()))
        self.instant[0]=initial['result']['protection']['until'];source.tick(self.pid,lane='processing')
        result=next(j for j in source.catalog(self.pid)['jobs'] if j['id']==initial['id'])['result']
        issued=source.publish(self.pid,initial['id'],result['approval_digest'],confirm=True)
        self.f.exchange(0,1)
        result=target.process(self.pid,down['id'],str(uuid4()))
        target_job=next(j for j in target.catalog(self.pid)['jobs'] if j['id']==result['id'])
        link=target_job['intent']['report_inputs'][0]
        self.assertEqual(link['ref']['artifact_id'],issued['report_ref']['artifact_id'])
        self.assertEqual(target_job['intent']['executor_node_id'],self.f.node_ids[1])
        read_link(target.blocks.reporting,self.pid,link,'project')
        self.f.exchange(1,0)
        shared=next(j for j in source.catalog(self.pid)['jobs'] if j['id']==result['id'])
        self.assertTrue(shared['shared']);self.assertEqual(shared['intent']['report_inputs'],target_job['intent']['report_inputs'])
        self.assertEqual(shared['intent']['report_gaps'],target_job['intent']['report_gaps'])
        # A logical state row cannot relabel the creator of a valid Git artifact.
        rows=target.pools.export(self.pid,transferable=True)
        event=next(r for r in rows if r['kind']=='report-outcome' and r['value']['run_id']==result['id'])
        tampered=deepcopy(event['value'])
        tampered['intent']['report_gaps'][0]['periods']=['2026-01-01']
        with self.assertRaisesRegex(ValidationError,'approval digest'):
            pool_sync.apply(self.f.nodes[0],self.pid,encoded([entry(self.pid,'report-outcome',tampered)]))
        value=deepcopy(event['value']);value['intent']['report_inputs'][0]['run_id']=str(uuid4())
        from spikes.monitoring_report_inputs import approval
        pool_refs=sorted((pool,r['item_entry']) for pool,groups in value['intent']['pools'].items() for g in groups for r in g['revisions'])
        value['result']['approval_digest']=approval(value['result']['markdown'],pool_refs,value['intent']['report_inputs'],value['intent'].get('report_gaps',[]))
        forged=entry(self.pid,'report-outcome',value)
        with self.assertRaisesRegex(ValidationError,'creator or edition'):
            pool_sync.apply(self.f.nodes[0],self.pid,encoded([forged]))
