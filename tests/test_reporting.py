# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.metadata import ValidationError, validate_snapshot
from spikes.journal import RecoveryConflict
from spikes.project_creation import ProjectCreation
from spikes.reporting import Reporting, canonical_events, operation_uuid
from spikes.reporting_schema import DIMENSIONS, date_value, digest, encoded, period, validate_record


def unknown_date():
    return dict(precision='unknown', start=None, end=None, basis=[])


def scope():
    return dict(entities=[], categories=[], geographies=[], tags=[])


def calendar_period():
    return dict(kind='weekly', timezone='Europe/Prague', calendar_revision='iso-calendar-v1',
                start_local='2026-03-23T00:00:00+01:00', end_local='2026-03-30T00:00:00+02:00',
                start_utc='2026-03-22T23:00:00Z', end_utc='2026-03-29T22:00:00Z')


class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='reporting ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.node = self.base / 'node.json'
        creation = ProjectCreation(self.node)
        created = creation.create('Reporting fixture', self.base / 'project', str(uuid4()))
        self.project = created['id']
        self.service = Reporting(self.node)
        self.ws = self.service.artifacts.workspace(self.project)
        self.git = self.ws.git
        self.author = creation.author_id()
        self.policy_id = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project, base_head=self.git.head(),
                                      artifact_id=self.policy_id, title='Ruční policy', body='Pouze ruční review.',
                                      new=True), str(uuid4()))
        self.policy = self.service.pin(self.project, self.policy_id)
        self.scale = self.store('EvaluationScale', dict(schema='fpw-reporting-scale-v1', title='Evidence scale',
            comparison_policy='same-revision-only', dimensions={
                key: [dict(value=value, label=str(value), criteria='Explicit criterion ' + str(value))
                      for value in (['insufficient', 'low', 'medium', 'high'] if key == 'confidence' else range(6))]
                for key in DIMENSIONS}))
        self.task = self.store('ReportingTask', dict(schema='fpw-reporting-task-v1', title='Watch', goal='Co se změnilo?',
            scope=scope(), source_policy=self.policy, selection_policy=self.policy, scale_ref=self.scale,
            calendar=dict(timezone='Europe/Prague', calendar_revision='iso-calendar-v1', periods=['weekly']),
            outputs=dict(formats=['markdown'], language='cs', required_sections=['# Přehled']),
            execution=dict(llm='disabled', context_policy=self.policy, publication_policy=self.policy),
            retention_policy=self.policy))

    def spec(self, kind, value, previous=None, entity_id=None, **extra):
        return dict(type=kind, value=value, previous=previous or [], entity_id=entity_id, privacy='project', **extra)

    def request(self, spec):
        return dict(project_id=self.project, base_head=self.git.head(), records=[spec])

    def store(self, kind, value, previous=None, entity_id=None, confirm=False, **extra):
        operation = str(uuid4())
        receipt = self.service.apply(self.request(self.spec(kind, value, previous, entity_id, **extra)),
                                     operation, confirm=confirm)
        return self.service.pin(self.project, operation_uuid(operation, 'record:0'), receipt['commit_id'])

    def record(self, reference):
        return json.loads(self.git.snapshot(reference['commit_id'])[reference['path']])

    def source(self, title='Primární zdroj'):
        return self.store('Source', dict(schema='fpw-reporting-source-v1', task_ref=self.task,
            title=title, locator='https://example.invalid/evidence', declared_author=None, source_role='primary',
            publication_date=unknown_date(), imported_at=None, retrieved_at=None, capture_state='reference-only',
            raw_ref=None, availability='available', license=dict(identifier=None, terms_ref=None,
                capture_allowed=False, retention_policy=self.policy)))

    def event(self, sources=None):
        sources = sources or [self.source()]
        return self.store('Event', dict(schema='fpw-reporting-event-v1', task_ref=self.task, title='Událost',
            summary='Deklarovaná schopnost, zatím nehodnoceno.', event_date=unknown_date(), detected_at=None,
            imported_at=None, categories=[], entities=[], geographies=[], tags=[], sources=sources,
            claims=[dict(claim_id=str(uuid4()), text='Demonstrovaná schopnost', scope='Laboratoř', stage='demonstration')],
            assessments=[], correction_reason=None))

    def review(self):
        return dict(decision='confirmed', actor_id=None, at=None, policy_revision=self.policy,
                    note='Osobně jsem zkontroloval přesné vstupy a text.')

    def story_value(self, events):
        return dict(schema='fpw-reporting-story-v1', task_ref=self.task, title='Příběh',
                    summary='Souvislosti', events=events, decisions=[])

    def publication(self, events=None, sources=None):
        return dict(schema='fpw-reporting-snapshot-v1', task_ref=self.task, rules_ref=self.policy,
            scale_refs=[self.scale], period=calendar_period(),
            knowledge_cutoff=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            input_head=self.git.head(), baseline_snapshot=None, events=events or [], sources=sources or [],
            stories=[], assessments=[], selection=[dict(event_ref=e, reason='new') for e in events or []],
            query=dict(selection_policy_ref=self.policy, scope=scope(), include_unknown_dates=True, include_late=True),
            methodology_changes=[], markdown=None,
            generation=dict(mode='manual', run_id=None, context_manifest_ref=None, result_sha256=None),
            approval=self.review(), limitations=['Neznámé datum; ruční reference bez archivovaných bajtů.'],
            reproducibility='limited-inputs', corrects=None, correction_reason=None)

    def publish(self, value=None):
        return self.store('ReportSnapshot', value or self.publication(), confirm=True,
                          markdown='# Přehled\n\nNebyla doložena významná změna.\n')

    def test_manual_event_multiple_sources_and_read_projection(self):
        sources = [self.source(), self.source('Odporující zdroj')]
        event = self.event(sources)
        result = self.service.read(self.project)
        self.assertEqual(self.record(event)['value']['sources'], sources)
        self.assertIn(event['artifact_id'], result['tips'])
        self.assertEqual(result['commit_id'], self.git.head())
        record = self.record(event)
        self.assertEqual(record['recorded_by'], self.author)
        self.assertEqual(record['value']['imported_at'], record['recorded_at'])

    def test_lost_response_same_operation_returns_receipt_and_changed_request_rejects(self):
        spec = self.spec('Story', self.story_value([self.event()]))
        request, operation = self.request(spec), str(uuid4())
        first = self.service.apply(request, operation)
        self.assertEqual(first['commit_id'], self.service.apply(request, operation)['commit_id'])
        self.assertEqual(self.git.head(), first['commit_id'])
        request['records'][0]['value']['title'] = 'Different intent'
        with self.assertRaisesRegex(ValidationError, 'different request'):
            self.service.apply(request, operation)

    def test_concurrent_edit_rejects_without_writing(self):
        event = self.event(); before = self.record(event)
        value = deepcopy(before['value']); value['summary'] = 'Oprava'; value['correction_reason'] = 'Nový důkaz'
        request = self.request(self.spec('Event', value, [event], before['entity_id']))
        self.source('Další zdroj')
        head = self.git.head()
        with self.assertRaisesRegex(ValidationError, 'Project changed'):
            self.service.apply(request, str(uuid4()))
        self.assertEqual(self.git.head(), head)

    def test_event_correction_keeps_original_and_import_time(self):
        event = self.event(); before = self.record(event)
        value = deepcopy(before['value']); value['sources'].append(self.source('Odporující zdroj'))
        value['correction_reason'] = 'Doplnění odporujícího zdroje'
        changed = self.store('Event', value, [event], before['entity_id'])
        self.assertEqual(self.record(event), before)
        self.assertEqual(self.record(changed)['value']['imported_at'], before['value']['imported_at'])
        self.assertEqual(len(self.record(changed)['value']['sources']), 2)

    def test_duplicate_then_retract_restores_projection_and_preserves_decisions(self):
        events = [self.event(), self.event()]
        ids = [self.record(e)['entity_id'] for e in events]
        value = self.story_value(events)
        value['decisions'] = [dict(decision_id=str(uuid4()), kind='duplicate', event_ids=ids,
            canonical_event_id=ids[0], reverses=None, reason='Totožná událost', review=self.review())]
        story = self.store('Story', value, confirm=True)
        before = self.record(story)
        self.assertEqual(canonical_events(before), {ids[1]: ids[0]})
        value = deepcopy(before['value'])
        value['decisions'].append(dict(decision_id=str(uuid4()), kind='retract', event_ids=ids,
            canonical_event_id=None, reverses=value['decisions'][0]['decision_id'],
            reason='Rozdílné události podle nového zdroje', review=self.review()))
        successor = self.store('Story', value, [story], before['entity_id'], confirm=True)
        self.assertEqual(canonical_events(self.record(successor)), {})
        self.assertEqual(self.record(story), before)
        value = deepcopy(self.record(successor)['value']); value['decisions'] = []
        with self.assertRaisesRegex(ValidationError, 'append-only'):
            self.store('Story', value, [successor], before['entity_id'])

    def test_review_requires_explicit_local_confirmation(self):
        events = [self.event()]; value = self.story_value(events)
        value['decisions'] = [dict(decision_id=str(uuid4()), kind='link', event_ids=[self.record(events[0])['entity_id']],
            canonical_event_id=None, reverses=None, reason='Souvislost', review=self.review())]
        with self.assertRaisesRegex(ValidationError, '--confirm'):
            self.store('Story', value)
        value['decisions'][0]['review']['actor_id'] = str(uuid4())
        with self.assertRaisesRegex(ValidationError, 'identity/time'):
            self.store('Story', value, confirm=True)

    def test_published_markdown_is_exact_and_correction_is_new_identity(self):
        issued = self.publish(); old = self.record(issued)
        markdown_ref = old['value']['markdown']
        content = self.git.snapshot(issued['commit_id'])[markdown_ref['path']]
        self.assertEqual(digest(content), markdown_ref['sha256'])
        value = self.publication(); value['corrects'] = issued; value['correction_reason'] = 'Oprava formulace'
        corrected = self.publish(value)
        self.assertNotEqual(self.record(corrected)['entity_id'], old['entity_id'])
        self.assertEqual(self.record(issued), old)
        self.assertEqual(self.record(corrected)['value']['corrects'], issued)

    def test_second_base_publication_is_rejected_even_with_new_operation_and_cutoff(self):
        self.publish()
        value = self.publication(); value['knowledge_cutoff'] = '2099-02-01T00:00:00Z'
        with self.assertRaisesRegex(ValidationError, 'base publication'):
            self.publish(value)

    def test_repinning_same_task_in_a_later_commit_does_not_bypass_period_reservation(self):
        self.publish()
        self.task = self.service.pin(self.project, self.task['artifact_id'])
        self.policy = self.service.pin(self.project, self.policy_id)
        with self.assertRaisesRegex(ValidationError, 'base publication'):
            self.publish()

    def test_parallel_successors_are_semantic_conflict_in_generic_writer(self):
        event = self.event(); before = self.record(event)
        value = deepcopy(before['value']); value['correction_reason'] = 'První oprava'
        self.store('Event', value, [event], before['entity_id'])
        value['correction_reason'] = 'Souběžná oprava stejného rodiče'
        with self.assertRaisesRegex(ValidationError, 'Conflicting reporting revision tips'):
            self.store('Event', value, [event], before['entity_id'])

    def test_foreign_edit_during_recovery_is_preserved_and_same_intent_can_finish(self):
        operation = str(uuid4())
        request = self.request(self.spec('ReportSnapshot', self.publication(),
            markdown='# Přehled\n\nNebyla doložena významná změna.\n'))
        def interrupt(stage):
            if stage == 'before-ref':
                raise RuntimeError('Simulated interruption before CAS')
        with self.assertRaisesRegex(RuntimeError, 'Simulated interruption'):
            self.service.apply(request, operation, confirm=True, checkpoint=interrupt)
        path = self.git.root / f'artifacts/{operation_uuid(operation, "markdown:0")}/report.md'
        candidate = path.read_bytes(); foreign = candidate + b'Foreign edit\n'
        path.write_bytes(foreign)
        with self.assertRaises(RecoveryConflict):
            self.ws.recover()
        self.assertEqual(path.read_bytes(), foreign)
        path.write_bytes(candidate)
        self.ws.recover()
        result = self.service.apply(request, operation, confirm=True)
        self.assertEqual(result['commit_id'], self.git.head())

    def test_generic_writer_cannot_overwrite_delete_or_rename_record(self):
        event = self.event()
        path = event['path']; original = self.git.snapshot(self.git.head())[path]
        modified = json.loads(original); modified['value']['summary'] = 'Forged correction'
        changes = [{path: encoded(modified)},
                   {path: None, path.rsplit('/', 1)[0] + '/metadata.json': None}]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.ws.apply(change, author_name='Local', author_email='local@example.invalid', message='Bypass')
        self.assertEqual(self.git.snapshot(self.git.head())[path], original)

    def test_exact_pinned_hash_privacy_and_project_are_enforced(self):
        source = self.source()
        for key, value in [('sha256', '0' * 64), ('project_id', str(uuid4())), ('commit_id', 'f' * 40)]:
            with self.subTest(key=key):
                bad = dict(source, **{key: value})
                with self.assertRaises((ValidationError, subprocess.CalledProcessError)):
                    self.event([bad])
        original = self.record(source)
        value = deepcopy(original['value']); value['title'] = 'Private source'
        spec = self.spec('Source', value); spec['privacy'] = 'local-only'
        operation = str(uuid4()); result = self.service.apply(self.request(spec), operation)
        private = self.service.pin(self.project, operation_uuid(operation, 'record:0'), result['commit_id'])
        with self.assertRaisesRegex(ValidationError, 'privacy'):
            self.event([private])

    def test_report_must_include_conflicting_sources_and_disclose_reference_limits(self):
        sources = [self.source(), self.source('Odporující')]; event = self.event(sources)
        value = self.publication([event], sources[:1])
        with self.assertRaisesRegex(ValidationError, 'omits event evidence'):
            self.publish(value)
        value['sources'] = sources; value['reproducibility'] = 'exact-inputs'
        with self.assertRaisesRegex(ValidationError, 'reproduction limits'):
            self.publish(value)
        value['reproducibility'] = 'limited-inputs'
        issued = self.publish(value)
        self.assertEqual(len(self.record(issued)['value']['sources']), 2)

    def test_verified_operation_cannot_be_published_without_confirmed_evidence(self):
        source = self.source(); event = self.event([source]); original = self.record(event)
        value = deepcopy(original['value']); value['claims'][0]['stage'] = 'verified-operation'
        value['correction_reason'] = 'Nové tvrzení'
        event = self.store('Event', value, [event], original['entity_id'])
        with self.assertRaisesRegex(ValidationError, 'confirmed independent/primary evidence'):
            self.publish(self.publication([event], [source]))

    def test_invalid_closed_schema_duplicate_json_unknown_version_and_dates(self):
        event = self.event(); record = self.record(event)
        for modify in [lambda r: r.update(extra='forbidden'),
                       lambda r: r.update(schema='fpw-reporting-record-v2'),
                       lambda r: r['value'].update(extra=True),
                       lambda r: r['value']['event_date'].update(start='2026-01-01')]:
            invalid = deepcopy(record); modify(invalid)
            with self.assertRaises(ValidationError):
                validate_record(invalid)
        files = self.git.snapshot(self.git.head())
        files[event['path']] = files[event['path']].replace(b'"schema":', b'"schema":"duplicate","schema":', 1)
        with self.assertRaises(ValidationError):
            validate_snapshot(files)

    def test_ordinary_json_and_raw_reporting_captures_remain_opaque(self):
        event = self.event(); record = self.record(event)
        raw_id, doc_id = str(uuid4()), str(uuid4())
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        files = {}
        for id_, kind, data in [(raw_id, 'source', encoded(record)), (doc_id, 'document', b'{"ordinary":true}')]:
            files[f'artifacts/{id_}/record.json'] = data
            files[f'artifacts/{id_}/metadata.json'] = encoded(dict(schema_version=1, id=id_, title='Opaque JSON',
                kind=kind, created_at=now, author_id=self.author, privacy='project', provenance='user', file='record.json'))
        self.ws.apply(files, author_name='Local', author_email='local@example.invalid', message='Capture opaque JSON')
        projection = self.service.read(self.project)
        self.assertNotIn(raw_id, projection['tips'])
        self.assertNotIn(doc_id, projection['tips'])

    def test_dst_is_seven_local_days_and_167_hours(self):
        value = calendar_period(); period(value)
        start = datetime.fromisoformat(value['start_utc'].replace('Z', '+00:00'))
        end = datetime.fromisoformat(value['end_utc'].replace('Z', '+00:00'))
        self.assertEqual((end - start).total_seconds() / 3600, 167)
        value['end_local'] = '2026-03-30T00:00:00+01:00'
        with self.assertRaises(ValidationError):
            period(value)
        with self.assertRaises(ValidationError):
            date_value(dict(precision='day', start='2026-02-30', end='2026-03-01', basis=[self.policy]))

    def test_stale_index_rebuild_preserves_reporting(self):
        issued = self.publish(); old = self.record(issued)
        self.ws.index.path.unlink()
        self.assertIn(issued['artifact_id'], self.service.read(self.project)['tips'])
        self.assertEqual(self.record(issued), old)

    def test_real_cli_list_pin_and_operation_retry(self):
        request = self.request(self.spec('Story', self.story_value([self.event()])))
        operation = str(uuid4()); path = self.base / 'cli-request.json'; path.write_bytes(encoded(request))
        def cli(*args):
            result = subprocess.run([sys.executable, '-m', 'spikes.reporting', '--node', str(self.node), *args],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        issued = cli('apply', str(path), '--operation-id', operation)
        self.assertEqual(cli('apply', str(path), '--operation-id', operation)['commit_id'], issued['commit_id'])
        reference = cli('pin', self.project, operation_uuid(operation, 'record:0'))
        self.assertEqual(reference['commit_id'], issued['commit_id'])
        self.assertEqual(cli('list', self.project)['commit_id'], issued['commit_id'])

    def test_process_crash_recovery_before_and_after_git_cas_has_one_publication(self):
        script = '''
import json, os, sys
from spikes.reporting import Reporting
def checkpoint(stage):
    if stage == sys.argv[4]: os._exit(73)
Reporting(sys.argv[1]).apply(json.load(open(sys.argv[2])), sys.argv[3], confirm=True, checkpoint=checkpoint)
'''
        for stage in ['prepared', 'file:0', 'applied', 'files-applied', 'commit-ready', 'before-ref',
                      'ref-updated', 'committed', 'indexed', 'completed']:
            with self.subTest(stage=stage):
                # Each subsequent crash publishes a correction of the last tip.
                value = self.publication()
                prior = [r for r in self.service.read(self.project)['records'] if r['type'] == 'ReportSnapshot']
                if prior:
                    corrected = {r['value']['corrects']['artifact_id'] for r in prior
                                 if r['value']['corrects'] is not None}
                    latest = next(r for r in prior if r['revision_id'] not in corrected)
                    value['corrects'] = self.service.pin(self.project, latest['revision_id'])
                    value['correction_reason'] = 'Crash recovery fixture correction'
                request = self.request(self.spec('ReportSnapshot', value,
                    markdown='# Přehled\n\nNebyla doložena významná změna.\n'))
                operation = str(uuid4()); path = self.base / 'request.json'; path.write_bytes(encoded(request))
                before_count = int(self.git.run('rev-list', '--count', 'HEAD').stdout)
                process = subprocess.run([sys.executable, '-c', script, str(self.node), str(path), operation, stage],
                                         capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 73, process.stderr)
                self.ws.recover()
                receipt = self.service.apply(request, operation, confirm=True)
                self.assertEqual(self.git.head(), receipt['commit_id'])
                self.assertEqual(int(self.git.run('rev-list', '--count', 'HEAD').stdout), before_count + 1)
                self.assertEqual(self.git.run('status', '--porcelain').stdout, '')


if __name__ == '__main__':
    unittest.main()
