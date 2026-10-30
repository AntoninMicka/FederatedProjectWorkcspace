# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import io
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaBindings
from spikes.roadmap_migration import HOST_SOURCES
from spikes.roadmap_rebuild import (RoadmapRebuild, build_candidate, source_catalog,
                                    validate_extraction)
from spikes.storage import Git
from scripts.roadmap_rebuild import progress_reporter


class RoadmapRebuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name); self.repository = self.base/'source'; self.repository.mkdir()
        self.git = Git(self.repository); self.git.run('init', '--initial-branch=main')
        for path, _role in HOST_SOURCES:
            target = self.repository/path; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('# Support\n', encoding='utf-8')
        (self.repository/HOST_SOURCES[0][0]).write_text(
            '# Roadmap\n\n## MILESTONE-M1 — Milník\n\n'
            '- [ ] [MILESTONE-M1] Milník\n'
            '  - [ ] [BATCH-01] Dávka\n'
            '    - [ ] [TASK-01] Úloha\n', encoding='utf-8')
        (self.repository/'TODO.md').write_text('# TODO — DEV-01\n\n## Kontext\n\nAktivní dávka.\n', encoding='utf-8')
        (self.repository/'BACKLOG.md').write_text('# Backlog\n\n## Později\n\nBudoucí práce.\n', encoding='utf-8')
        (self.repository/'WORK_LOG.md').write_text('# Work log\n\n## Historie\n\nDoložený výsledek.\n', encoding='utf-8')
        (self.repository/'docs/roadmap-graph.json').write_text(json.dumps({
            'schema': 'fpw-roadmap-graph-v1', 'nodes': [
                {'id': 'MILESTONE-M1', 'depends_on': []},
                {'id': 'BATCH-01', 'depends_on': []},
                {'id': 'TASK-01', 'depends_on': []}]}), encoding='utf-8')
        self.commit = self.git.commit('Source fixture')
        self.node = self.base/'node.json'; self.node.write_text('{}', encoding='utf-8')
        chat = self.node.parent/('.' + self.node.name + '.chat'); chat.mkdir(mode=0o700)
        self.binding = OllamaBinding.parse(dict(schema_version=1, binding_id=str(uuid4()),
            revision='fixture-v1', adapter='ollama', boundary='same-node',
            endpoint='http://127.0.0.1:11434', model='fixture', target_id='local-process'))
        OllamaBindings(chat).save(self.binding)
        self.run_dir = self.base/'run'

    def factory(self, runs):
        def transport(binding, request):
            prompt = json.loads(request)['prompt']
            focus = json.loads(prompt.split('Focus:\n', 1)[1].rsplit('\n\nSummary:', 1)[0])
            if 'source_block' in focus:
                block = focus['source_block']
                value = {'schema': 'fpw-roadmap-source-audit-v1',
                         'block_id': block['block_id'], 'verdict': 'correct',
                         'scores': {key: 100 for key in ('coverage', 'hierarchy', 'status',
                                                         'provenance', 'dependencies')},
                         'findings': [], 'summary': 'Zdroj je zachován.'}
            else:
                block = focus['block']; entities = []
                if 'MILESTONE-M1' in block['text']:
                    entities = [
                        dict(entity_key='e1', kind='milestone', source_ids=['MILESTONE-M1'], title='Milník',
                             status='planned', maturity='unknown', parent_ref=None, dependency_refs=[],
                             line_start=block['line_start'], line_end=block['line_start'], summary='Milník.'),
                        dict(entity_key='e2', kind='batch', source_ids=['BATCH-01'], title='Dávka', status='planned',
                             maturity='unknown', parent_ref='entity:e1', dependency_refs=[], line_start=block['line_start'] + 1,
                             line_end=block['line_start'] + 1, summary='Dávka.'),
                        dict(entity_key='e3', kind='task', source_ids=['TASK-01'], title='Úloha', status='planned',
                             maturity='unknown', parent_ref='entity:e2', dependency_refs=[], line_start=block['line_start'] + 2,
                             line_end=block['line_start'] + 2, summary='Úloha.')]
                else:
                    entities = [dict(entity_key='e1', kind='description', source_ids=[], title=block['title'],
                        status='unknown', maturity='unknown', parent_ref=None, dependency_refs=[],
                        line_start=block['line_start'], line_end=block['line_start'],
                        summary='Zachovaný popis.')]
                value = {'schema': 'fpw-roadmap-source-extraction-v2',
                         'block_id': block['block_id'], 'entities': entities,
                         'ambiguities': [], 'summary': 'Extrahovaný celek.'}
            return {'model': binding.model, 'response': json.dumps(value, ensure_ascii=False)}
        return OllamaAdapter(runs, transport=transport)

    def test_catalog_preserves_sequence_and_does_not_read_a_target(self):
        value = source_catalog(self.repository, revision=self.commit)
        self.assertEqual('fpw-roadmap-source-catalog-v1', value['schema'])
        self.assertGreaterEqual(value['summary']['blocks'], 4)
        roadmap = [item for item in value['blocks'] if item['source'].endswith(HOST_SOURCES[0][0])]
        self.assertIn('MILESTONE-M1', roadmap[-1]['text'])
        self.assertNotIn('MPL-2', roadmap[0]['allowed_source_ids'])
        self.assertIn('MILESTONE-M1', roadmap[-1]['allowed_source_ids'])
        self.assertEqual(roadmap[-1]['sha256'], __import__('hashlib').sha256(
            roadmap[-1]['text'].encode()).hexdigest())
        self.assertNotIn('target', json.dumps(value))

    def test_run_is_resumable_and_publishes_candidate_then_audit(self):
        service = RoadmapRebuild.prepare(self.node, self.run_dir, self.repository,
                                         revision=self.commit)
        events = []
        first = RoadmapRebuild(self.node, self.run_dir, adapter_factory=self.factory).run(
            limit=1, progress=events.append)
        self.assertEqual(1, first['extracted']); self.assertFalse(first['candidate'])
        self.assertEqual(['dispatch', 'result'], [item['event'] for item in events])
        self.assertEqual('extract', events[-1]['phase'])
        status = first
        while not status['complete']:
            status = RoadmapRebuild(self.node, self.run_dir,
                                    adapter_factory=self.factory).run(limit=100)
        self.assertTrue(status['candidate'])
        self.assertTrue(status['report']['candidate_ready'])
        self.assertTrue(status['report']['import_ready'])
        self.assertEqual(100, status['report']['fidelity'])
        candidate = json.loads((self.run_dir/'candidate.json').read_text(encoding='utf-8'))
        self.assertEqual({'MILESTONE-M1', 'BATCH-01', 'TASK-01'},
                         {item['candidate_id'] for item in candidate['nodes']})
        before = status
        after = RoadmapRebuild(self.node, self.run_dir,
                               adapter_factory=lambda _runs: self.fail('must not redispatch')).run(limit=100)
        self.assertEqual(before['report'], after['report'])

    def test_invalid_model_response_is_terminal_for_block_and_does_not_loop(self):
        RoadmapRebuild.prepare(self.node, self.run_dir, self.repository,
                               revision=self.commit)
        calls = []
        def broken(runs):
            def transport(binding, request):
                calls.append(request); return {'model': binding.model, 'response': '{}'}
            return OllamaAdapter(runs, transport=transport)
        service = RoadmapRebuild(self.node, self.run_dir, adapter_factory=broken)
        total = service.status()['blocks']
        first = service.run(limit=100000)
        self.assertEqual(total, first['failed_extractions'])
        self.assertEqual(total * 3, len(calls))
        second = service.run(limit=100000)
        self.assertEqual(total, second['failed_extractions'])
        self.assertEqual(total * 3, len(calls))  # Final failures are not retried.
        failed = [item for item in (self.run_dir/'results').glob('extract-*.failed.json')
                  if '.attempt-' not in item.name]
        self.assertEqual(total, len(failed))
        self.assertTrue(all('response fields differ' in json.loads(
            item.read_text(encoding='utf-8'))['error'] for item in failed))

    def test_run_rejects_tampered_catalog_before_model_dispatch(self):
        RoadmapRebuild.prepare(self.node, self.run_dir, self.repository,
                               revision=self.commit)
        path = self.run_dir/'catalog.json'; value = json.loads(path.read_text(encoding='utf-8'))
        value['blocks'][0]['text'] += 'tampered'
        path.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'catalog changed'):
            RoadmapRebuild(self.node, self.run_dir,
                           adapter_factory=lambda _runs: self.fail('must not dispatch')).run()

    def test_validation_error_gets_bounded_repair_with_same_source(self):
        RoadmapRebuild.prepare(self.node, self.run_dir, self.repository,
                               revision=self.commit)
        calls = []
        def repairing(runs):
            def transport(binding, request):
                prompt = json.loads(request)['prompt']; calls.append(prompt)
                focus = json.loads(prompt.split('Focus:\n', 1)[1].rsplit('\n\nSummary:', 1)[0])
                if 'previous_response' in focus:
                    block = focus['source_block']['block']
                    value = {'schema': 'fpw-roadmap-source-extraction-v2',
                             'block_id': block['block_id'], 'entities': [dict(
                                 entity_key='e1', kind='description', source_ids=[],
                                 title=block['title'], status='unknown', maturity='unknown',
                                 parent_ref=None, dependency_refs=[], line_start=block['line_start'],
                                 line_end=block['line_start'], summary='Opravený popis.')],
                             'ambiguities': [], 'summary': 'Opraveno.'}
                elif 'source_block' in focus:
                    block = focus['source_block']
                    value = {'schema': 'fpw-roadmap-source-audit-v1',
                             'block_id': block['block_id'], 'verdict': 'correct',
                             'scores': {key: 100 for key in ('coverage', 'hierarchy', 'status',
                                                             'provenance', 'dependencies')},
                             'findings': [], 'summary': 'Správně.'}
                else:
                    value = {}
                return {'model': binding.model, 'response': json.dumps(value, ensure_ascii=False)}
            return OllamaAdapter(runs, transport=transport)
        result = RoadmapRebuild(self.node, self.run_dir,
                                adapter_factory=repairing).run(limit=100000)
        self.assertTrue(result['complete'])
        self.assertEqual(0, result['failed_extractions'])
        attempts = list((self.run_dir/'results').glob('extract-*.attempt-1.failed.json'))
        self.assertEqual(result['blocks'], len(attempts))
        self.assertTrue(any('validation_error' in call for call in calls))

    def test_cli_progress_reports_phase_elapsed_percent_and_eta(self):
        stream = io.StringIO(); report = progress_reporter(stream)
        report(dict(event='dispatch', phase='extract', block=2, blocks=10, attempt=1,
                    logical_done=1, logical_total=20))
        report(dict(event='result', phase='extract', block=2, blocks=10, attempt=1,
                    outcome='completed', logical_done=2, logical_total=20))
        output = stream.getvalue()
        self.assertIn('extract 2/10', output)
        self.assertIn('2/20 (10.0 %)', output)
        self.assertIn('běží', output)
        self.assertIn('ETA', output)

    def test_non_executable_context_can_belong_to_parent(self):
        block = {'block_id': 'block-1', 'line_start': 10, 'line_end': 20,
                 'allowed_source_ids': ['BATCH-01']}
        value = {'schema': 'fpw-roadmap-source-extraction-v2', 'block_id': 'block-1',
                 'entities': [
                     dict(entity_key='e1', kind='batch', source_ids=['BATCH-01'],
                          title='Dávka', status='completed', maturity='implemented',
                          parent_ref=None, dependency_refs=[], line_start=10, line_end=11,
                          summary='Dokončená dávka.'),
                     dict(entity_key='e2', kind='history', source_ids=[], title='Ověření',
                          status='unknown', maturity='unknown', parent_ref='entity:e1',
                          dependency_refs=[], line_start=12, line_end=14,
                          summary='Historický důkaz dávky.')],
                 'ambiguities': [], 'summary': 'Dávka a její historie.'}
        validated = validate_extraction(json.dumps(value), block)
        self.assertEqual('entity:e1', validated['entities'][1]['parent_ref'])

    def test_combined_source_ids_create_review_issue_instead_of_failure(self):
        block = {'block_id': 'block-1', 'source': 'BACKLOG.md', 'line_start': 1,
                 'line_end': 5, 'allowed_source_ids': ['ER-01', 'ER-03']}
        value = {'schema': 'fpw-roadmap-source-extraction-v2', 'block_id': 'block-1',
                 'entities': [dict(entity_key='e1', kind='batch',
                     source_ids=['ER-01', 'ER-03'], title='Společná dávka', status='planned',
                     maturity='designed', parent_ref=None, dependency_refs=[], line_start=1,
                     line_end=3, summary='Zdroj výslovně spojuje oba požadavky.'),
                     dict(entity_key='e2', kind='task', source_ids=[], title='Navazující úkol',
                          status='planned', maturity='designed', parent_ref='source:ER-01',
                          dependency_refs=[], line_start=4, line_end=5,
                          summary='Úkol patří pod společnou dávku.')],
                 'ambiguities': [], 'summary': 'Seskupený požadavek.'}
        extraction = validate_extraction(json.dumps(value), block)
        candidate = build_candidate({'blocks': [block]}, [extraction])
        self.assertTrue(candidate['nodes'][0]['candidate_id'].startswith('MIG-BATCH-'))
        self.assertEqual('combined-source-ids', candidate['issues'][0]['kind'])
        nodes = {item['title']: item for item in candidate['nodes']}
        self.assertEqual(nodes['Společná dávka']['candidate_id'],
                         nodes['Navazující úkol']['parent_id'])


if __name__ == '__main__':
    unittest.main()
