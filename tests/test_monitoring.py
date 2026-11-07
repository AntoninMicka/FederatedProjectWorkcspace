# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,time,unittest
from uuid import uuid4
from tests import test_reporting as fixtures
from spikes.monitoring import Monitoring,PROFILES,MARKER,ident
from spikes.reporting_scheduler import calendar_period
from spikes.metadata import ValidationError
from spikes.projects import Projects
from spikes.artifacts import Artifacts
from spikes.presentation_documents import PresentationDocuments

class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReportingTests('test_manual_event_multiple_sources_and_read_projection');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.node=self.f.node;self.pid=self.f.project
        self.service=Monitoring(self.node,Projects(self.node))
        self.cfg=dict(id=str(uuid4()),name='Pokrok',goal='Sledovat doložené změny a rozpory.',active=True,privacy='project',
            timezone='Europe/Prague',start='2026-03-23',inputs=[self.f.policy_id],urls=[],access_note='',
            periods=dict(PROFILES),presentation=True,mode='deterministic',binding=None,tags=['robotika'])
        self.save()

    def save(self,new=True):
        return self.service.save(dict(project_id=self.pid,base_head=self.f.git.head(),watch=self.cfg,new=new),str(uuid4()))

    def period(self,start='2026-03-23T00:00:00+01:00',kind='weekly'):
        return calendar_period(start,kind,'Europe/Prague','iso-calendar-v1')

    def test_watch_restart_report_review_publication_presentation_and_two_periods(self):
        self.service=Monitoring(self.node,Projects(self.node))
        first=self.service.execute(self.pid,self.cfg,self.period())
        self.assertEqual(first['state'],'review')
        view=self.service.view(self.pid);report=next(r for r in view['reports'] if r['id']==first['run_id'])
        self.assertIn('Nebyla doložena významná změna.',report['markdown'])
        self.service.publish(self.pid,first['run_id'],report['approval_digest'],True)
        head=self.f.git.head();self.service.publish(self.pid,first['run_id'],report['approval_digest'],True)
        self.assertEqual(head,self.f.git.head())
        decks=PresentationDocuments(self.node).open(self.pid)['documents']
        self.assertEqual(len(decks),1);self.assertNotIn('error',decks[0])
        second=self.service.execute(self.pid,self.cfg,self.period('2026-03-30T00:00:00+02:00'))
        self.assertEqual(second['state'],'review');self.assertIsNotNone(second['baseline_snapshot'])
        report=self.service.scheduler.preview(second['run_id'])
        self.service.publish(self.pid,second['run_id'],report['approval_digest'],True)
        self.assertEqual(len(PresentationDocuments(self.node).open(self.pid)['documents']),2)

    def test_period_profiles_have_distinct_purpose_and_structure(self):
        first=self.service.execute(self.pid,self.cfg,self.period())
        monthly=self.service.execute(self.pid,self.cfg,self.period('2026-03-01T00:00:00+01:00','monthly'))
        a=self.service.scheduler.preview(first['run_id'])['request']['records'][0]['markdown']
        b=self.service.scheduler.preview(monthly['run_id'])['request']['records'][0]['markdown']
        self.assertIn('Novinky a opravy',a);self.assertIn('Významné události a možné průlomy',b)
        self.assertIn(PROFILES['monthly'],b)

    def test_generic_document_edit_cannot_activate_network_or_a_model(self):
        cfg=deepcopy(self.cfg);cfg['goal']='Untrusted change'
        Artifacts(self.node).save(dict(project_id=self.pid,base_head=self.f.git.head(),artifact_id=cfg['id'],title=cfg['name'],
            body=MARKER+json.dumps(cfg),new=False),str(uuid4()))
        self.assertFalse(self.service.granted(self.pid,cfg))
        with self.assertRaisesRegex(ValidationError,'potvrzení'):
            self.service.execute(self.pid,cfg,self.period())

    def test_pause_and_no_implicit_auto_publication(self):
        job=self.service.execute(self.pid,self.cfg,self.period());self.assertEqual(job['state'],'review')
        count=len([r for r in self.f.service.read(self.pid)['records'] if r['type']=='ReportSnapshot'])
        self.assertEqual(count,0)
        self.cfg['active']=False;self.save(False)
        with self.assertRaisesRegex(ValidationError,'pozastavené'):
            self.service.run_now(self.pid,self.cfg['id'])

    def test_local_only_cannot_authorize_external_collection(self):
        self.cfg.update(privacy='local-only',urls=['https://example.test/source.txt'],access_note='Explicit test terms')
        with self.assertRaisesRegex(ValidationError,'local-only'):
            self.save(False)

    def test_correction_preserves_original_report_and_deck_and_marks_superseded(self):
        job=self.service.execute(self.pid,self.cfg,self.period())
        preview=self.service.scheduler.preview(job['run_id'])
        self.service.publish(self.pid,job['run_id'],preview['approval_digest'],True)
        original=self.service.scheduler.get(job['run_id'])['workspace_receipt']['snapshot']
        old_files=self.f.git.snapshot(self.f.git.head())
        aid=ident(job['run_id'],'deck');old_deck={p:b for p,b in old_files.items() if p.startswith('artifacts/'+aid+'/')}
        fixed=self.service.correct(self.pid,job['run_id'])
        self.assertEqual(fixed['state'],'review')
        preview=self.service.scheduler.preview(fixed['run_id'])
        self.assertEqual(preview['request']['records'][0]['value']['corrects'],original)
        self.service.publish(self.pid,fixed['run_id'],preview['approval_digest'],True)
        view=self.service.view(self.pid)
        self.assertTrue(next(r for r in view['reports'] if r['id']==job['run_id'])['superseded'])
        self.assertEqual(self.service.correct(self.pid,job['run_id'])['run_id'],fixed['run_id'])
        files=self.f.git.snapshot(self.f.git.head())
        self.assertEqual(old_deck,{p:b for p,b in files.items() if p.startswith('artifacts/'+aid+'/')})

    def model(self,transport):
        from spikes.ollama_backend import OllamaBindings,OllamaBinding,OllamaAdapter
        root=self.node.parent/('.'+self.node.name+'.chat');root.mkdir(mode=0o700,exist_ok=True)
        binding=OllamaBinding.parse(dict(schema_version=1,binding_id=str(uuid4()),revision='v1',adapter='ollama',
            boundary='same-node',endpoint='http://127.0.0.1:11434',model='synthetic',target_id='local-process'))
        OllamaBindings(root).save(binding)
        self.cfg.update(mode='llm',binding=vars(binding.target()));self.save(False)
        self.service.adapter_factory=lambda runs:OllamaAdapter(runs,transport=transport,runtime_probe=lambda b:dict(status='unknown'))

    def test_model_manifest_assisted_provenance_and_explicit_human_publication(self):
        calls=[]
        def transport(binding,request):
            calls.append(request)
            return dict(model=binding.model,response='# Přehled\nNebyla doložena významná změna.\n## Omezení\nSyntetický test.\n',done=True)
        self.model(transport)
        job=self.service.execute(self.pid,self.cfg,self.period());self.assertEqual(job['state'],'review')
        preview=self.service.scheduler.preview(job['run_id']);value=preview['request']['records'][0]['value']
        self.assertEqual(value['generation']['mode'],'assisted');self.assertIsNotNone(value['generation']['context_manifest_ref'])
        self.assertEqual(len(calls),1)
        self.service.publish(self.pid,job['run_id'],preview['approval_digest'],True)
        self.assertEqual(len(calls),1)

    def test_unknown_model_outcome_is_durable_and_never_retried_automatically(self):
        calls=[]
        def transport(binding,request):calls.append(request);raise TimeoutError('lost response')
        self.model(transport)
        with self.assertRaises(Exception):self.service.execute(self.pid,self.cfg,self.period())
        self.assertEqual(self.service.jobs(self.pid)[0]['state'],'unknown')
        restarted=Monitoring(self.node,Projects(self.node));restarted.adapter_factory=lambda runs:self.fail('unknown must not retry')
        self.assertEqual(restarted.execute(self.pid,self.cfg,self.period())['state'],'unknown')
        self.assertEqual(len(calls),1)
        self.assertFalse(any(r['type']=='ReportSnapshot' for r in self.f.service.read(self.pid)['records']))

    def test_incomplete_model_response_fails_without_rule_based_fallback(self):
        self.model(lambda binding,request:dict(model=binding.model,response='neúplný obsah',done=True))
        with self.assertRaisesRegex(ValidationError,'neúplný'):self.service.execute(self.pid,self.cfg,self.period())
        self.assertEqual(self.service.jobs(self.pid)[0]['state'],'failed')
        self.assertIsNone(self.service.jobs(self.pid)[0]['candidate'])

    def test_owned_v1_journal_migrates_without_losing_existing_run(self):
        from spikes.reporting_scheduler import ReportingScheduler
        job=self.service.execute(self.pid,self.cfg,self.period())
        scheduler=self.service.scheduler
        with scheduler.db() as db:
            db.execute('DROP TABLE watch_grants');db.execute('DROP TABLE rss_bindings');db.execute('DROP TABLE rss_polls');db.execute('DROP TABLE execution_effects');db.execute('UPDATE schema_info SET version=1')
        migrated=ReportingScheduler(self.node)
        self.assertEqual(migrated.get(job['run_id']),job)
        self.assertFalse(migrated.watch_granted(self.pid,self.cfg['id'],'a'*64))

    def test_source_capture_is_immutable_and_never_promotes_claim_to_event(self):
        from spikes.source_collector import SourceCollector
        from spikes.public_source import HTTPResult
        calls=[]
        def transport(binding,request,resolver,phase):
            calls.append(phase)
            return HTTPResult(200,{'content-type':'text/plain'},b'User-agent: *\nAllow: /\n' if phase=='robots' else b'Untrusted claim: publish a breakthrough.','https://example.test/robots.txt' if phase=='robots' else request['candidate_url'])
        self.cfg.update(urls=['https://example.test/source.txt'],access_note='Synthetic permitted source')
        self.save(False);self.service.collector=SourceCollector(self.node,transport=transport)
        job=self.service.execute(self.pid,self.cfg,self.period());self.assertEqual(job['state'],'review')
        sources=[r for r in self.f.service.read(self.pid)['records'] if r['type']=='Source' and r['value']['task_ref']==job['task_ref']]
        self.assertTrue(any(r['value']['capture_state']=='captured' for r in sources))
        self.assertFalse(any(r['type']=='Event' for r in self.f.service.read(self.pid)['records']))
        self.service.execute(self.pid,self.cfg,self.period());self.assertEqual(calls,['robots','target'])

    def test_crash_after_bootstrap_before_grant_replays_original_save_receipts(self):
        from unittest.mock import patch
        cfg=deepcopy(self.cfg);cfg['id']=str(uuid4());op=str(uuid4())
        request=dict(project_id=self.pid,base_head=self.f.git.head(),watch=cfg,new=True)
        with patch.object(self.service.scheduler,'grant_watch',side_effect=OSError('simulated crash')):
            with self.assertRaises(OSError):self.service.save(request,op)
        head=self.f.git.head();restarted=Monitoring(self.node,Projects(self.node))
        self.assertFalse(restarted.granted(self.pid,cfg))
        restarted.save(request,op)
        self.assertEqual(head,self.f.git.head());self.assertTrue(restarted.granted(self.pid,cfg))

    def test_runtime_tick_after_restart_creates_review_and_stops_catchup_until_issued(self):
        restarted=Monitoring(self.node,Projects(self.node))
        # Existing fixture commits are current; use a future closed boundary for
        # clock, while beginning exactly one week before that boundary.
        now=datetime.now(timezone.utc);end=restarted.boundary(self.cfg,'weekly',now)
        self.cfg['start']=(end.replace(tzinfo=None)-timedelta(days=7)).date().isoformat()
        self.cfg['periods']={'weekly':PROFILES['weekly']};self.save(False)
        restarted=Monitoring(self.node,Projects(self.node))
        restarted.tick(self.pid)
        jobs=restarted.jobs(self.pid);self.assertEqual(len(jobs),1);self.assertEqual(jobs[0]['state'],'review')
        restarted.tick(self.pid);self.assertEqual(restarted.jobs(self.pid),jobs)

    def test_exact_old_event_evidence_is_retained_after_source_correction(self):
        task=self.service.ready(self.pid,self.cfg);self.f.task=task
        source=self.f.source();event=self.f.event([source]);old=self.f.record(source)
        value=deepcopy(old['value']);value['title']='Opravený zdroj'
        self.f.store('Source',value,[source],old['entity_id'])
        job=self.service.execute(self.pid,self.cfg,self.period())
        value=self.service.scheduler.preview(job['run_id'])['request']['records'][0]['value']
        self.assertIn(source,value['sources']);self.assertTrue(any(p['artifact_id']==event['artifact_id'] and p['sha256']==event['sha256'] for p in value['events']))
        self.assertEqual(len(value['sources']),3)  # exact old pin, corrected tip and project input

    def test_unknown_source_collection_keeps_original_run_and_never_retries(self):
        from spikes.source_collector import SourceCollector
        calls=[]
        def lost(*args):calls.append('dispatch');raise TimeoutError('lost response')
        self.cfg.update(urls=['https://example.test/source.txt'],access_note='Synthetic permitted source');self.save(False)
        self.service.collector=SourceCollector(self.node,transport=lost)
        with self.assertRaises(Exception):self.service.execute(self.pid,self.cfg,self.period())
        count=len(calls)
        restarted=Monitoring(self.node,Projects(self.node),collector=SourceCollector(self.node,transport=lost))
        with self.assertRaisesRegex(ValidationError,'neznámý'):restarted.execute(self.pid,self.cfg,self.period())
        self.assertEqual(len(calls),count)
        captures=restarted.view(self.pid)['collections'][self.cfg['id']]
        self.assertEqual(captures[0]['state'],'unknown')

    def test_known_failed_model_retries_only_by_explicit_action_with_new_attempt(self):
        calls=[];valid=[False]
        def transport(binding,request):
            calls.append(request)
            return dict(model=binding.model,response='# Přehled\nNebyla doložena významná změna.\n## Omezení\nTest.' if valid[0] else 'incomplete',done=True)
        self.model(transport)
        with self.assertRaises(ValidationError):self.service.execute(self.pid,self.cfg,self.period())
        job=self.service.jobs(self.pid)[0];self.assertEqual(len(calls),1)
        self.service.execute(self.pid,self.cfg,self.period());self.assertEqual(len(calls),1)
        valid[0]=True
        job=self.service.retry(self.pid,job['run_id'],True)
        self.assertEqual(job['state'],'review');self.assertEqual(len(calls),2)
        self.assertEqual(len(job['attempts']),2)

    def test_progress_regression_and_methodology_change_are_distinct(self):
        from spikes.reporting_schema import digest,encoded,DIMENSIONS
        task=self.service.ready(self.pid,self.cfg);self.f.task=task
        tv=self.f.record(task)['value'];self.f.policy=tv['selection_policy'];self.f.scale=tv['scale_ref']
        source=self.f.source();event=self.f.event([source]);er=self.f.record(event);claim=er['value']['claims'][0]
        value=dict(schema='fpw-reporting-assessment-v1',task_ref=task,
            subject=dict(event_id=er['entity_id'],claim_id=claim['claim_id'],claim_sha256=digest(encoded(claim))),
            scale_ref=self.f.scale,ratings={k:('high' if k=='confidence' else 2) for k in DIMENSIONS},
            evidence=[dict(source_ref=source,locator=None,relation='supports',independence_group='primary-test',rationale='Syntetický konkrétní důkaz')],
            limitations=['Syntetický test, nikoliv reálný průlom.'],review=self.f.review())
        assessment=self.f.store('EvidenceAssessment',value,confirm=True)
        def report(start):
            job=self.service.execute(self.pid,self.cfg,self.period(start))
            preview=self.service.scheduler.preview(job['run_id']);body=preview['request']['records'][0]
            self.service.publish(self.pid,job['run_id'],preview['approval_digest'],True)
            return body
        report('2026-03-23T00:00:00+01:00')
        entity=self.f.record(assessment)['entity_id'];value['ratings']['maturity']=3
        assessment=self.f.store('EvidenceAssessment',value,[assessment],entity,confirm=True)
        self.assertIn('Pokrok ve stejné škále.',report('2026-03-30T00:00:00+02:00')['markdown'])
        value['ratings']['maturity']=1;assessment=self.f.store('EvidenceAssessment',value,[assessment],entity,confirm=True)
        self.assertIn('Regrese ve stejné škále.',report('2026-04-06T00:00:00+02:00')['markdown'])
        self.cfg['periods']['weekly']='Změněná metodika: porovnávej jen doložené provozní výsledky.';self.save(False)
        body=report('2026-04-13T00:00:00+02:00')
        self.assertIn('Změna metodiky nebo zadání',body['markdown'])
        self.assertNotIn('Pokrok ve stejné škále.',body['markdown']);self.assertTrue(body['value']['methodology_changes'])

    def test_late_discovery_import_and_annual_unfinished_study_are_explicit(self):
        task=self.service.ready(self.pid,self.cfg);self.f.task=task
        source=self.f.source();event=self.f.event([source]);old=self.f.record(event)
        value=deepcopy(old['value']);value.update(event_date=dict(precision='day',start='2025-01-02',end='2025-01-03',basis=[source]),correction_reason='Přesnější datum')
        late=self.f.store('Event',value,[event],old['entity_id'])
        job=self.service.execute(self.pid,self.cfg,self.period())
        preview=self.service.scheduler.preview(job['run_id'])
        self.assertIn('late-discovery',preview['request']['records'][0]['markdown'])
        self.service.publish(self.pid,job['run_id'],preview['approval_digest'],True)
        value['detected_at']='2025-06-01T00:00:00Z';value['correction_reason']='Doplněno původní zjištění'
        value['correction_reason']=None
        self.f.store('Event',value)
        job=self.service.execute(self.pid,self.cfg,self.period('2026-03-30T00:00:00+02:00'))
        self.assertIn('late-import',self.service.scheduler.preview(job['run_id'])['request']['records'][0]['markdown'])
        Artifacts(self.node).save(dict(project_id=self.pid,base_head=self.f.git.head(),artifact_id=self.f.policy_id,
            title='Případová studie',body='# Případová studie\nStav: rozpracovaná, chybí nezávislá validace.\n',new=False),str(uuid4()))
        job=self.service.execute(self.pid,self.cfg,self.period('2025-01-01T00:00:00+01:00','annual'))
        body=self.service.scheduler.preview(job['run_id'])['request']['records'][0]['markdown']
        self.assertIn('rozpracovaná, chybí nezávislá validace',body)
        self.assertIn('artifacts/'+self.f.policy_id+'/',body)

    def test_future_event_is_context_and_never_a_past_period_achievement(self):
        task=self.service.ready(self.pid,self.cfg);self.f.task=task
        source=self.f.source();event=self.f.event([source]);old=self.f.record(event)
        value=deepcopy(old['value']);value.update(title='Budoucí demonstrace',
            event_date=dict(precision='day',start='2027-01-01',end='2027-01-02',basis=[source]),correction_reason='Doplněno plánované datum')
        self.f.store('Event',value,[event],old['entity_id'])
        job=self.service.execute(self.pid,self.cfg,self.period())
        body=self.service.scheduler.preview(job['run_id'])['request']['records'][0]
        self.assertTrue(all(s['reason']=='context' for s in body['value']['selection']))
        self.assertNotIn('Budoucí demonstrace',body['markdown']);self.assertIn('Nebyla doložena významná změna.',body['markdown'])
        job=self.service.execute(self.pid,self.cfg,self.period('2026-03-01T00:00:00+01:00','monthly'))
        body=self.service.scheduler.preview(job['run_id'])['request']['records'][0]['markdown']
        self.assertIn('Budoucí událost mimo sledované období',body)
