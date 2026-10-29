# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from spikes.ollama_backend import OllamaAdapter, OllamaBinding, OllamaBindings
from spikes.roadmap_migration import HOST_SOURCES
from spikes.roadmap_rebuild import RoadmapRebuild, source_catalog
from spikes.storage import Git


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
                        dict(kind='milestone', stable_id='MILESTONE-M1', title='Milník',
                             status='planned', parent_id=None, depends_on=[],
                             line_start=block['line_start'], line_end=block['line_start'], summary='Milník.'),
                        dict(kind='batch', stable_id='BATCH-01', title='Dávka', status='planned',
                             parent_id='MILESTONE-M1', depends_on=[], line_start=block['line_start'] + 1,
                             line_end=block['line_start'] + 1, summary='Dávka.'),
                        dict(kind='task', stable_id='TASK-01', title='Úloha', status='planned',
                             parent_id='BATCH-01', depends_on=[], line_start=block['line_start'] + 2,
                             line_end=block['line_start'] + 2, summary='Úloha.')]
                else:
                    entities = [dict(kind='description', stable_id=None, title=block['title'],
                        status='unknown', parent_id=None, depends_on=[],
                        line_start=block['line_start'], line_end=block['line_start'],
                        summary='Zachovaný popis.')]
                value = {'schema': 'fpw-roadmap-source-extraction-v1',
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
        self.assertEqual(roadmap[-1]['sha256'], __import__('hashlib').sha256(
            roadmap[-1]['text'].encode()).hexdigest())
        self.assertNotIn('target', json.dumps(value))

    def test_run_is_resumable_and_publishes_candidate_then_audit(self):
        service = RoadmapRebuild.prepare(self.node, self.run_dir, self.repository,
                                         revision=self.commit)
        first = RoadmapRebuild(self.node, self.run_dir, adapter_factory=self.factory).run(limit=1)
        self.assertEqual(1, first['extracted']); self.assertFalse(first['candidate'])
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
        first = service.run(limit=2)
        self.assertEqual(2, first['failed_extractions'])
        self.assertEqual(2, len(calls))
        second = service.run(limit=2)
        self.assertEqual(4, second['failed_extractions'])
        self.assertEqual(4, len(calls))  # Two new blocks, no retry of failed blocks.
        failed = list((self.run_dir/'results').glob('extract-*.failed.json'))
        self.assertEqual(4, len(failed))
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


if __name__ == '__main__':
    unittest.main()
