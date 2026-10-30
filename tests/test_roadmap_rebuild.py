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
from spikes.roadmap_rebuild import (ROADMAP_LLM_TIMEOUT, RoadmapRebuild,
                                    build_candidate, render_candidate, source_catalog,
                                    validate_audit, validate_extraction)
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
                if 'MILESTONE-M1' in block['numbered_text']:
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

    def test_catalog_expands_historical_shorthand_and_numbers_prompt_source(self):
        path = self.repository/'WORK_LOG.md'
        path.write_text('# Work log\n\n## Historie\n\n'
                        '- [x] **BATCH-OLD-A/B/AH-01 — společný historický bod.**\n',
                        encoding='utf-8')
        commit = self.git.commit('Historical shorthand')
        value = source_catalog(self.repository, revision=commit)
        block = next(item for item in value['blocks']
                     if item['source'].endswith('WORK_LOG.md') and item['line_start'] > 1)
        self.assertEqual({'BATCH-OLD-A', 'BATCH-OLD-B', 'BATCH-OLD-AH-01'},
                         set(block['allowed_source_ids']))

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

    def test_transport_null_and_block_wrapper_parent_are_normalized(self):
        block = {'block_id': 'block-1', 'line_start': 10, 'line_end': 20,
                 'allowed_source_ids': [], 'reference_source_ids': []}
        entities = []
        for index, parent in enumerate(('null', 'source:block-1'), 1):
            entities.append(dict(entity_key=f'e{index}', kind='description', source_ids=[],
                title='Kontext', status='unknown', maturity='unknown', parent_ref=parent,
                dependency_refs=[], line_start=10 + index, line_end=10 + index,
                summary='Zdrojový kontext.'))
        value = {'schema': 'fpw-roadmap-source-extraction-v2', 'block_id': 'block-1',
                 'entities': entities, 'ambiguities': [], 'summary': 'Kontext.'}
        validated = validate_extraction(json.dumps(value), block)
        self.assertEqual([None, None], [item['parent_ref'] for item in validated['entities']])

    def test_nonformal_maturity_becomes_reviewable_source_ambiguity(self):
        block = {'block_id': 'block-1', 'source': 'WORK_LOG.md',
                 'line_start': 10, 'line_end': 20, 'allowed_source_ids': []}
        value = {'schema': 'fpw-roadmap-source-extraction-v2', 'block_id': 'block-1',
                 'entities': [dict(entity_key='e1', kind='task', source_ids=[],
                     title='Ověřený bod', status='completed', maturity='test-validated',
                     parent_ref=None, dependency_refs=[], line_start=11, line_end=12,
                     summary='Zdroj používá neformální úroveň.')],
                 'ambiguities': [], 'summary': 'Historický bod.'}
        extraction = validate_extraction(json.dumps(value), block)
        self.assertEqual('unknown', extraction['entities'][0]['maturity'])
        candidate = build_candidate({'blocks': [block]}, [extraction])
        self.assertFalse(candidate['ready'])
        self.assertEqual('source-ambiguity', candidate['issues'][0]['kind'])

    def test_disallowed_model_id_preserves_content_as_blocking_ambiguity(self):
        block = {'block_id': 'block-1', 'source': 'BACKLOG.md',
                 'line_start': 1, 'line_end': 5, 'allowed_source_ids': []}
        value = {'schema': 'fpw-roadmap-source-extraction-v2', 'block_id': 'block-1',
                 'entities': [dict(entity_key='e1', kind='task', source_ids=['INVENTED-01'],
                     title='Obsah bez doloženého ID', status='planned', maturity='unknown',
                     parent_ref=None, dependency_refs=[], line_start=1, line_end=5,
                     summary='Obsah zůstane zachován.')],
                 'ambiguities': [], 'summary': 'Nejisté ID.'}
        extraction = validate_extraction(json.dumps(value), block)
        self.assertEqual([], extraction['entities'][0]['source_ids'])
        candidate = build_candidate({'blocks': [block]}, [extraction])
        self.assertEqual('source-ambiguity', candidate['issues'][0]['kind'])
        self.assertFalse(candidate['ready'])

    def test_derived_run_reuses_only_valid_extractions_with_lineage(self):
        RoadmapRebuild.prepare(self.node, self.run_dir, self.repository,
                               revision=self.commit)
        RoadmapRebuild(self.node, self.run_dir, adapter_factory=self.factory).run(limit=1)
        derived_dir = self.base/'derived'
        derived = RoadmapRebuild.derive(self.node, derived_dir, self.run_dir)
        status = derived.status()
        self.assertEqual(1, status['extracted'])
        self.assertEqual(0, status['failed_extractions'])
        manifest = json.loads((derived_dir/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(str(self.run_dir), manifest['derived_from']['run_dir'])
        self.assertEqual(1, len(manifest['derived_from']['reused_extractions']))
        self.assertEqual(600, ROADMAP_LLM_TIMEOUT)
        self.assertEqual({'response_timeout_seconds': ROADMAP_LLM_TIMEOUT},
                         manifest['transport'])

    def test_derived_run_reuses_audit_only_for_unchanged_candidate_input(self):
        RoadmapRebuild.prepare(self.node, self.run_dir, self.repository,
                               revision=self.commit)
        status = {}
        while not status.get('complete'):
            status = RoadmapRebuild(self.node, self.run_dir,
                                    adapter_factory=self.factory).run(limit=100)
        derived_dir = self.base/'derived-complete'
        derived = RoadmapRebuild.derive(self.node, derived_dir, self.run_dir)
        reused = derived.status()
        self.assertEqual(reused['blocks'], reused['extracted'])
        self.assertEqual(reused['blocks'], reused['audited'])
        manifest = json.loads((derived_dir/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(reused['blocks'],
                         len(manifest['derived_from']['reused_audits']))
        block_id = json.loads((self.run_dir/'catalog.json').read_text(
            encoding='utf-8'))['blocks'][0]['block_id']
        guided_dir = self.base/'derived-guided'
        guided = RoadmapRebuild.derive(self.node, guided_dir, self.run_dir,
            retry_extractions=[block_id], audit_overrides=[(block_id, 'Human review')])
        self.assertEqual(reused['blocks'] - 1, guided.status()['extracted'])
        guided_manifest = json.loads((guided_dir/'manifest.json').read_text(encoding='utf-8'))
        self.assertIn(block_id, guided_manifest['guided_extractions'])
        self.assertEqual('equivalent', guided_manifest['audit_overrides'][0]['verdict'])

    def test_candidate_renderer_marks_unresolved_dependency_and_cycle(self):
        nodes = [
            {'candidate_id': 'BATCH-01', 'title': 'Dávka', 'status': 'planned',
             'kind': 'batch', 'parent_id': None, 'depends_on': [None]},
            {'candidate_id': 'TASK-01', 'title': 'Úkol', 'status': 'planned',
             'kind': 'task', 'parent_id': 'BATCH-01', 'depends_on': []},
            {'candidate_id': 'BATCH-01', 'title': 'Cyklus', 'status': 'planned',
             'kind': 'batch', 'parent_id': 'TASK-01', 'depends_on': []}]
        rendered = render_candidate({'ready': False, 'nodes': nodes,
                                     'supporting_records': [], 'issues': []})
        self.assertIn('depends_on: <unresolved>', rendered)
        self.assertIn('[cycle] BATCH-01', rendered)

    def test_positive_audit_findings_are_redundant_not_terminal(self):
        block = {'block_id': 'block-1', 'line_start': 1, 'line_end': 5}
        value = {'schema': 'fpw-roadmap-source-audit-v1', 'block_id': 'block-1',
                 'verdict': 'correct',
                 'scores': {key: 100 for key in ('coverage', 'hierarchy', 'status',
                                                  'provenance', 'dependencies')},
                 'findings': [{'line_start': 1, 'line_end': 5, 'candidate_id': 'B-01',
                               'kind': 'correct', 'reason': 'Obsah odpovídá.'}],
                 'summary': 'Kandidát odpovídá.'}
        self.assertEqual([], validate_audit(json.dumps(value), block)['findings'])

    def test_reconciliation_prefers_completed_history_and_preserves_variants(self):
        blocks = [
            {'block_id': 'backlog', 'source': 'BACKLOG.md', 'role': 'backlog',
             'order': 0, 'line_start': 1, 'line_end': 2, 'allowed_source_ids': ['B-01']},
            {'block_id': 'history', 'source': 'WORK_LOG.md', 'role': 'history',
             'order': 0, 'line_start': 1, 'line_end': 2, 'allowed_source_ids': ['B-01']}]
        def extraction(block_id, status, summary):
            return {'schema': 'fpw-roadmap-source-extraction-v2', 'block_id': block_id,
                    'entities': [dict(entity_key='e1', kind='batch', source_ids=['B-01'],
                        title='Dávka', status=status, maturity='implemented', parent_ref=None,
                        dependency_refs=[], line_start=1, line_end=2, summary=summary)],
                    'ambiguities': [], 'summary': summary}
        values = [validate_extraction(json.dumps(extraction('backlog', 'planned', 'Plán.')),
                                      blocks[0]),
                  validate_extraction(json.dumps(extraction('history', 'completed', 'Hotovo.')),
                                      blocks[1])]
        candidate = build_candidate({'blocks': blocks}, values)
        node = candidate['nodes'][0]
        self.assertEqual(('completed', 'Hotovo.'), (node['status'], node['summary']))
        self.assertEqual(1, len(node['variants']))
        self.assertNotIn('reconciliation-ambiguity',
                         {item['kind'] for item in candidate['issues']})

    def test_reconciliation_blocks_equal_authority_structural_disagreement(self):
        blocks = [
            {'block_id': key, 'source': 'WORK_LOG.md', 'role': 'history',
             'order': index, 'line_start': 1, 'line_end': 1,
             'allowed_source_ids': ['SAME-01']}
            for index, key in enumerate(('first', 'second'))]
        values = []
        for block, kind in zip(blocks, ('batch', 'task')):
            value = {'schema': 'fpw-roadmap-source-extraction-v2',
                     'block_id': block['block_id'], 'entities': [dict(
                         entity_key='e1', kind=kind, source_ids=['SAME-01'], title=kind,
                         status='completed', maturity='implemented', parent_ref=None,
                         dependency_refs=[], line_start=1, line_end=1, summary=kind)],
                     'ambiguities': [], 'summary': kind}
            values.append(validate_extraction(json.dumps(value), block))
        candidate = build_candidate({'blocks': blocks}, values)
        self.assertIn('reconciliation-ambiguity',
                      {item['kind'] for item in candidate['issues']})

    def test_reconciliation_scopes_same_id_per_repository(self):
        blocks = [
            {'block_id': 'host', 'source': 'federated-workspace:ROADMAP.md',
             'repository_id': 'federated-workspace', 'role': 'requirements', 'order': 0,
             'line_start': 1, 'line_end': 1, 'allowed_source_ids': ['M1']},
            {'block_id': 'module', 'source': 'example.module:ROADMAP.md',
             'repository_id': 'example.module', 'role': 'requirements', 'order': 0,
             'line_start': 1, 'line_end': 1, 'allowed_source_ids': ['M1']}]
        values = []
        for block, title in zip(blocks, ('Host M1', 'Module M1')):
            value = {'schema': 'fpw-roadmap-source-extraction-v2',
                     'block_id': block['block_id'], 'entities': [dict(
                         entity_key='e1', kind='milestone', source_ids=['M1'], title=title,
                         status='planned', maturity='designed', parent_ref=None,
                         dependency_refs=[], line_start=1, line_end=1, summary=title)],
                     'ambiguities': [], 'summary': title}
            values.append(validate_extraction(json.dumps(value), block))
        candidate = build_candidate({'blocks': blocks}, values)
        self.assertEqual({('federated-workspace', 'Host M1'),
                          ('example.module', 'Module M1')},
                         {(node['repository_id'], node['title'])
                          for node in candidate['nodes']})
        self.assertNotIn('reconciliation-ambiguity',
                         {item['kind'] for item in candidate['issues']})

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
