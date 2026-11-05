# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from dataclasses import replace
import json
import subprocess
import sys
from uuid import uuid4
import unittest

from tests import test_reporting as fixtures
from spikes.context_builder import Authority
from spikes.metadata import ValidationError
from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaRuns, UnknownRun
from spikes.reporting import operation_uuid
from spikes.reporting_proposals import ReportingProposals, PROPOSAL
from spikes.reporting_schema import DIMENSIONS, digest, encoded


class ReportingProposalTests(unittest.TestCase):
    # Reuse the existing temporary registered Workspace fixture, without
    # inheriting/rerunning its independent publication test suite.
    for _name in ('spec', 'request', 'store', 'record', 'source', 'event', 'review', 'story_value'):
        locals()[_name] = getattr(fixtures.ReportingTests, _name)

    def setUp(self):
        fixtures.ReportingTests.setUp(self)
        old = self.record(self.task)
        value = deepcopy(old['value']); value['execution']['llm'] = 'optional'
        self.task = self.store('ReportingTask', value, [self.task], old['entity_id'])
        self.sources = [self.source('Marketing / primární tvrzení'), self.source('Odporující zdroj')]
        self.event_ref = self.event(self.sources)
        self.selected = [self.scale, self.policy, *self.sources, self.event_ref]
        self.authority = Authority('reporting-fixture', self.author, str(uuid4()), 'policy-1',
            frozenset(r['artifact_id'] for r in [self.task, *self.selected]))
        self.binding = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
            revision='binding-1', adapter='ollama', boundary='same-node',
            endpoint='http://127.0.0.1:11434', model='synthetic-model', target_id='local-process'))
        self.output = dict(schema=PROPOSAL, records=[self.spec('Story', self.story_value([self.event_ref]))],
                           limitations=['Pouze syntetický návrh, ne potvrzený provoz.'])
        self.calls = []
        root = self.base / 'backend'; root.mkdir(mode=0o700)
        self.runs = OllamaRuns(root)
        self.adapter = OllamaAdapter(self.runs, transport=self.transport,
                                    runtime_probe=lambda binding: dict(status='unknown'))
        self.proposals = ReportingProposals(self.node, self.adapter)

    def transport(self, binding, request):
        self.calls.append(request)
        return dict(model=binding.model, response=json.dumps(self.output), done=True)

    def prepare(self, role='extractor', **changes):
        args = dict(project_id=self.project, task_ref=self.task, input_refs=self.selected,
                    role=role, run_id=str(uuid4()), manifest_id=str(uuid4()),
                    authority=self.authority, binding=self.binding)
        args.update(changes)
        return self.proposals.prepare(**args)

    def generate(self, role='extractor'):
        prepared = self.prepare(role)
        head = self.git.head()
        self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        self.assertEqual(self.git.head(), head)
        return prepared, self.proposals.preview(prepared, authority=self.authority, binding=self.binding)

    def accept(self, prepared, preview, operation=None, **changes):
        args = dict(authority=self.authority, binding=self.binding, confirm=True)
        args.update(changes)
        return self.proposals.accept(prepared, operation or str(uuid4()), preview['approval_digest'], **args)

    def test_each_role_has_separate_manifest_and_never_writes_without_confirmation(self):
        for role in ('extractor', 'researcher', 'evidence-evaluator'):
            with self.subTest(role=role):
                prepared, preview = self.generate(role)
                self.assertEqual(prepared.manifest['task']['role_id'], role)
                with self.assertRaisesRegex(ValidationError, 'confirmation'):
                    self.accept(prepared, preview, confirm=False)
        self.assertEqual(len(self.calls), 3)

    def test_review_stores_exact_audit_and_all_inputs_and_replays_one_commit(self):
        prepared, preview = self.generate(); operation = str(uuid4())
        receipt = self.accept(prepared, preview, operation)
        result = self.service.pin(self.project, operation_uuid(operation, 'record:0'))
        record = self.record(result)
        self.assertEqual(record['provenance']['method'], 'derived')
        self.assertEqual(record['provenance']['run_refs'], [preview['assistance']['run_ref']])
        self.assertTrue(all(r in record['provenance']['inputs'] for r in [self.task, *self.selected]))
        audit_id = operation_uuid(operation, 'assistance')
        audit = json.loads(self.git.snapshot(self.git.head())[f'artifacts/{audit_id}/assistance.json'])
        self.assertEqual(audit['context']['target'], dict(prepared.manifest)['target'])
        self.assertNotIn('session_id', audit['context'])
        self.assertEqual(audit['proposal']['limitations'], self.output['limitations'])
        self.assertEqual(receipt, self.accept(prepared, preview, operation))
        self.assertEqual(self.git.head(), receipt['commit_id'])
        self.assertEqual(len(self.calls), 1)

    def test_model_or_prompt_change_cannot_reuse_prepared_approval(self):
        prepared, preview = self.generate()
        for binding in (replace(self.binding, model='another-model'), replace(self.binding, revision='binding-2')):
            with self.subTest(binding=binding), self.assertRaisesRegex(ValidationError, 'target changed'):
                self.accept(prepared, preview, binding=binding)
        from types import MappingProxyType
        manifest = deepcopy(dict(prepared.manifest))
        manifest['task']['instruction_sha256'] = 'a' * 64
        forged = replace(prepared, manifest=MappingProxyType(manifest), manifest_bytes=encoded(manifest))
        with self.assertRaisesRegex(ValidationError, 'instruction'):
            self.accept(forged, preview)

    def test_changed_approval_and_stale_head_are_rejected(self):
        prepared, preview = self.generate()
        with self.assertRaisesRegex(ValidationError, 'approval changed'):
            self.accept(prepared, dict(preview, approval_digest='f' * 64))
        self.source('Pozdější zdroj')
        with self.assertRaisesRegex(ValidationError, 'Project changed'):
            self.accept(prepared, preview)

    def test_revoked_access_blocks_dispatch_and_acceptance(self):
        prepared = self.prepare()
        revoked = replace(self.authority, readable_entities=frozenset())
        with self.assertRaisesRegex(ValidationError, 'revoked'):
            self.proposals.dispatch(prepared, authority=revoked, binding=self.binding)
        self.assertEqual(self.calls, [])
        self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        preview = self.proposals.preview(prepared, authority=self.authority, binding=self.binding)
        with self.assertRaisesRegex(ValidationError, 'revoked'):
            self.accept(prepared, preview, authority=revoked)

    def test_unknown_provider_outcome_is_not_automatically_retried(self):
        def lost(binding, request):
            self.calls.append(request)
            raise TimeoutError('Lost response')
        self.adapter.transport = lost; prepared = self.prepare(); head = self.git.head()
        for _ in range(2):
            with self.assertRaises(UnknownRun):
                self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.git.head(), head)
        with self.assertRaisesRegex(ValidationError, 'successful result'):
            self.proposals.preview(prepared, authority=self.authority, binding=self.binding)

    def test_unselected_refs_review_identity_and_privacy_escalation_reject(self):
        for change, message in (
            (lambda s: s.update(privacy='public'), 'privacy'),
            (lambda s: s['value'].update(task_ref=self.policy), 'reporting task'),
            (lambda s: s['value']['events'][0].update(sha256='a' * 64), 'explicit context'),
            (lambda s: s.update(type='ReportSnapshot'), 'cannot change'),
        ):
            with self.subTest(message=message):
                self.output['records'] = [self.spec('Story', self.story_value([deepcopy(self.event_ref)]))]
                change(self.output['records'][0])
                prepared = self.prepare(); self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
                with self.assertRaisesRegex(ValidationError, message):
                    self.proposals.preview(prepared, authority=self.authority, binding=self.binding)

    def test_marketing_is_not_accepted_as_verified_operation(self):
        event = deepcopy(self.record(self.event_ref)['value'])
        event['claims'][0]['stage'] = 'verified-operation'
        self.output['records'] = [self.spec('Event', event)]
        prepared = self.prepare(); self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        with self.assertRaisesRegex(ValidationError, 'separate human evidence'):
            self.proposals.preview(prepared, authority=self.authority, binding=self.binding)

    def test_conflicting_evidence_is_a_proposal_until_explicit_human_review(self):
        event = self.record(self.event_ref); claim = event['value']['claims'][0]
        value = dict(schema='fpw-reporting-assessment-v1', task_ref=self.task,
            subject=dict(event_id=event['entity_id'], claim_id=claim['claim_id'], claim_sha256=digest(encoded(claim))),
            scale_ref=self.scale, ratings={k: ('insufficient' if k == 'confidence' else None) for k in DIMENSIONS},
            evidence=[dict(source_ref=s, locator=None, relation=relation, independence_group=None,
                           rationale='Syntetický rozporný zdroj.')
                      for s, relation in zip(self.sources, ('supports', 'contradicts'))],
            limitations=['Chybí nezávislý primární provozní důkaz.'], review=self.review())
        self.output['records'] = [self.spec('EvidenceAssessment', value)]
        prepared, preview = self.generate('evidence-evaluator')
        receipt = self.accept(prepared, preview)
        record = self.record(self.service.pin(self.project, operation_uuid(receipt['operation_id'], 'record:0')))
        self.assertEqual(record['value']['ratings']['confidence'], 'insufficient')
        self.assertEqual([e['relation'] for e in record['value']['evidence']], ['supports', 'contradicts'])
        self.assertEqual(record['value']['review']['actor_id'], self.author)

    def test_disabled_task_and_missing_scale_do_not_dispatch(self):
        with self.assertRaisesRegex(ValidationError, 'scale explicitly'):
            self.prepare(input_refs=[self.policy])
        old = self.record(self.task); value = deepcopy(old['value']); value['execution']['llm'] = 'disabled'
        task = self.store('ReportingTask', value, [self.task], old['entity_id'])
        with self.assertRaisesRegex(ValidationError, 'disables LLM'):
            self.prepare(task_ref=task)
        self.assertEqual(self.calls, [])

    def test_run_without_llm_keeps_original_manual_path(self):
        event = self.event(self.sources)
        self.assertEqual(self.record(event)['provenance']['method'], 'user')
        self.assertEqual(self.calls, [])

    def test_community_signal_without_primary_evidence_stays_insufficient(self):
        sources = []
        for source in self.sources:
            old = self.record(source); value = deepcopy(old['value']); value['source_role'] = 'community'
            sources.append(self.store('Source', value, [source], old['entity_id']))
        event = self.record(self.event_ref); claim = event['value']['claims'][0]
        self.selected = [self.scale, self.policy, *sources, self.event_ref]
        self.authority = replace(self.authority, readable_entities=frozenset(
            r['artifact_id'] for r in [self.task, *self.selected]))
        value = dict(schema='fpw-reporting-assessment-v1', task_ref=self.task,
            subject=dict(event_id=event['entity_id'], claim_id=claim['claim_id'], claim_sha256=digest(encoded(claim))),
            scale_ref=self.scale, ratings={k: ('high' if k == 'confidence' else None) for k in DIMENSIONS},
            evidence=[dict(source_ref=s, locator=None, relation='supports', independence_group=None,
                           rationale='Pouze komunitní signál.') for s in sources],
            limitations=['Chybí primární důkaz.'], review=None)
        self.output['records'] = [self.spec('EvidenceAssessment', value)]
        prepared = self.prepare(); self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        with self.assertRaisesRegex(ValidationError, 'primary evidence'):
            self.proposals.preview(prepared, authority=self.authority, binding=self.binding)
        value['ratings']['confidence'] = 'insufficient'
        prepared, preview = self.generate()
        self.accept(prepared, preview)

    def test_cannot_omit_selected_contradiction_or_forge_review_identity(self):
        event = deepcopy(self.record(self.event_ref)['value'])
        event['sources'] = event['sources'][:1]
        self.output['records'] = [self.spec('Event', event)]
        prepared = self.prepare(); self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        with self.assertRaisesRegex(ValidationError, 'every selected source'):
            self.proposals.preview(prepared, authority=self.authority, binding=self.binding)
        story = self.story_value([self.event_ref]); review = self.review()
        review['actor_id'] = str(uuid4())
        story['decisions'] = [dict(decision_id=str(uuid4()), kind='link',
            event_ids=[self.record(self.event_ref)['entity_id']], canonical_event_id=None,
            reverses=None, reason='Falešná identita', review=review)]
        self.output['records'] = [self.spec('Story', story)]
        prepared = self.prepare(); self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        with self.assertRaises(ValidationError):
            preview = self.proposals.preview(prepared, authority=self.authority, binding=self.binding)
            self.accept(prepared, preview)

    def test_process_crash_keeps_audit_and_records_in_one_recoverable_commit(self):
        script = '''
import json, os, sys
from spikes.reporting import Reporting
def stop(stage):
    if stage == sys.argv[4]: os._exit(73)
preview = json.load(open(sys.argv[2]))
Reporting(sys.argv[1]).apply(preview['request'], sys.argv[3], confirm=True,
    _assistance=preview['assistance'], checkpoint=stop)
'''
        for stage in ('prepared', 'file:0', 'before-ref', 'ref-updated', 'indexed', 'completed'):
            with self.subTest(stage=stage):
                prepared, preview = self.generate(); operation = str(uuid4())
                path = self.base / 'assisted-request.json'; path.write_bytes(encoded(preview))
                count = int(self.git.run('rev-list', '--count', 'HEAD').stdout)
                process = subprocess.run([sys.executable, '-c', script, str(self.node), str(path), operation, stage],
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 73, process.stderr)
                receipt = self.accept(prepared, preview, operation)
                self.assertEqual(self.git.head(), receipt['commit_id'])
                self.assertEqual(int(self.git.run('rev-list', '--count', 'HEAD').stdout), count + 1)
                files = self.git.snapshot(self.git.head())
                self.assertIn(f'artifacts/{operation_uuid(operation, "assistance")}/assistance.json', files)
                self.assertIn(f'artifacts/{operation_uuid(operation, "record:0")}/record.json', files)
                self.assertEqual(self.git.run('status', '--porcelain').stdout, '')

    def test_local_only_input_blocks_private_network_and_taints_derived_result(self):
        from spikes.artifacts import Artifacts
        id_ = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project, base_head=self.git.head(),
            artifact_id=id_, title='Místní poznámka', body='Lokální citlivý kontext.', new=True),
            str(uuid4()), privacy='local-only')
        self.selected.append(self.service.pin(self.project, id_))
        self.authority = replace(self.authority,
            readable_entities=self.authority.readable_entities | {id_})
        remote = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
            revision='remote-v1', adapter='ollama', boundary='private-network',
            endpoint='https://192.168.10.4:11443', tls_cert_sha256='a' * 64,
            model='synthetic-model', target_id=str(uuid4())))
        with self.assertRaisesRegex(ValidationError, 'local-only'):
            self.prepare(binding=remote)
        prepared = self.prepare(); self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        with self.assertRaisesRegex(ValidationError, 'privacy'):
            self.proposals.preview(prepared, authority=self.authority, binding=self.binding)
        self.output['records'][0]['privacy'] = 'local-only'
        prepared, preview = self.generate()
        receipt = self.accept(prepared, preview)
        record = self.record(self.service.pin(self.project, operation_uuid(receipt['operation_id'], 'record:0')))
        self.assertEqual(record['privacy'], 'local-only')

    def test_foreign_owner_is_not_authorized_by_an_arbitrary_readable_set(self):
        with self.assertRaisesRegex(ValidationError, 'local owner'):
            self.prepare(authority=replace(self.authority, user_id=str(uuid4())))
        self.assertEqual(self.calls, [])

    def test_proposed_deduplication_is_reviewed_without_rewriting_events(self):
        second = self.event(self.sources)
        self.selected.append(second)
        self.authority = replace(self.authority,
            readable_entities=self.authority.readable_entities | {second['artifact_id']})
        before = [self.record(e) for e in [self.event_ref, second]]
        ids = [e['entity_id'] for e in before]
        value = self.story_value([self.event_ref, second])
        value['decisions'] = [dict(decision_id=str(uuid4()), kind='duplicate', event_ids=ids,
            canonical_event_id=ids[0], reverses=None, reason='Synteticky shodná událost', review=self.review())]
        self.output['records'] = [self.spec('Story', value)]
        prepared, preview = self.generate('researcher')
        receipt = self.accept(prepared, preview)
        story = operation_uuid(receipt['operation_id'], 'record:0')
        self.assertEqual(self.service.read(self.project)['deduplication'][story], {ids[1]: ids[0]})
        self.assertEqual([self.record(e) for e in [self.event_ref, second]], before)

    def test_audit_respects_explicitly_stricter_output_privacy(self):
        self.output['records'][0]['privacy'] = 'confidential'
        prepared, preview = self.generate()
        receipt = self.accept(prepared, preview)
        audit = operation_uuid(receipt['operation_id'], 'assistance')
        files = self.git.snapshot(self.git.head())
        self.assertEqual(json.loads(files[f'artifacts/{audit}/metadata.json'])['privacy'], 'confidential')

    def test_assessment_cannot_invent_a_subject_outside_selected_claims(self):
        value = dict(schema='fpw-reporting-assessment-v1', task_ref=self.task,
            subject=dict(event_id=str(uuid4()), claim_id=str(uuid4()), claim_sha256='a' * 64),
            scale_ref=self.scale, ratings={k: ('insufficient' if k == 'confidence' else None) for k in DIMENSIONS},
            evidence=[dict(source_ref=s, locator=None, relation='context', independence_group=None,
                           rationale='Není důkazem zvoleného tvrzení.') for s in self.sources],
            limitations=['Chybí tvrzení.'], review=None)
        self.output['records'] = [self.spec('EvidenceAssessment', value)]
        prepared = self.prepare(); self.proposals.dispatch(prepared, authority=self.authority, binding=self.binding)
        with self.assertRaisesRegex(ValidationError, 'explicitly selected event claim'):
            self.proposals.preview(prepared, authority=self.authority, binding=self.binding)

    def test_context_cannot_backdate_a_reference_before_artifact_creation(self):
        fake = dict(self.event_ref, commit_id=self.policy['commit_id'])
        with self.assertRaisesRegex(ValidationError, 'Pin requires'):
            self.prepare(input_refs=[self.scale, self.policy, *self.sources, fake])
        self.assertEqual(self.calls, [])
