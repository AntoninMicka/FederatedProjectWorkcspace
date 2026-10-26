# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from pathlib import Path
import tempfile
import unittest

from spikes.desktop_ui import HTML, JS, DesktopHandler
from spikes.roadmap_graph import RoadmapGraph, SCHEMA


class RoadmapGraphTests(unittest.TestCase):
    def fixture(self, nodes):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / 'docs').mkdir()
        (root / 'docs/roadmap-graph.json').write_text(json.dumps({
            'schema': SCHEMA, 'nodes': nodes}), encoding='utf-8')
        (root / 'TODO.md').write_text(
            '# TODO — NOW-01\n\nAktivní feature dávka: **Aktivní dávka**.\n',
            encoding='utf-8')
        (root / 'BACKLOG.md').write_text(
            '- [ ] [planned] **NEXT-01 — Další dávka (cílová úroveň: implemented).**\n'
            '- [ ] [planned] **LATER-01 — Pozdější dávka (cílová úroveň: implemented).**\n'
            '- [ ] [planned] **WAIT-01 — Odložená dávka.** Výslovně odloženo.\n',
            encoding='utf-8')
        (root / 'WORK_LOG.md').write_text(
            '## DONE-01 — Dokončená dávka — 2026-10-26\n', encoding='utf-8')
        (root / 'Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md').write_text(
            '# Roadmapa\n', encoding='utf-8')
        return RoadmapGraph(root)

    def test_projection_uses_authoritative_titles_and_computes_parallel_work(self):
        graph = self.fixture([
            {'id': 'DONE-01', 'milestone': 'M1', 'depends_on': []},
            {'id': 'NOW-01', 'milestone': 'M2', 'depends_on': ['DONE-01']},
            {'id': 'NEXT-01', 'milestone': 'M2', 'depends_on': ['DONE-01']},
            {'id': 'LATER-01', 'milestone': 'M2', 'depends_on': ['NEXT-01']},
            {'id': 'WAIT-01', 'milestone': 'M3', 'depends_on': []},
        ])
        value = graph.project()
        items = {item['id']: item for item in value['nodes']}
        self.assertEqual('Aktivní dávka', items['NOW-01']['title'])
        self.assertEqual('completed', items['DONE-01']['status'])
        self.assertEqual('deferred', items['WAIT-01']['status'])
        self.assertEqual(['NEXT-01'], value['parallel_ready'])
        self.assertEqual(['DONE-01', 'NEXT-01', 'LATER-01'], value['critical_path'])
        self.assertEqual(64, len(value['revision']))

    def test_unknown_dependency_duplicate_and_cycle_fail_closed(self):
        cases = [
            ([{'id': 'NOW-01', 'milestone': 'M1', 'depends_on': ['MISSING-01']}],
             'Unknown roadmap graph dependency'),
            ([{'id': 'NOW-01', 'milestone': 'M1', 'depends_on': []},
              {'id': 'NOW-01', 'milestone': 'M1', 'depends_on': []}],
             'Duplicate roadmap graph ID'),
            ([{'id': 'NOW-01', 'milestone': 'M1', 'depends_on': ['NEXT-01']},
              {'id': 'NEXT-01', 'milestone': 'M1', 'depends_on': ['NOW-01']}],
             'contains a cycle'),
        ]
        for nodes, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.fixture(nodes).project()

    def test_missing_authoritative_entry_is_rejected(self):
        graph = self.fixture([{'id': 'UNKNOWN-01', 'milestone': 'M1', 'depends_on': []}])
        with self.assertRaisesRegex(ValueError, 'has no authoritative entry: UNKNOWN-01'):
            graph.project()

    def test_unannotated_backlog_feature_is_rejected(self):
        graph = self.fixture([
            {'id': 'NOW-01', 'milestone': 'M1', 'depends_on': []},
            {'id': 'NEXT-01', 'milestone': 'M2', 'depends_on': []},
            {'id': 'LATER-01', 'milestone': 'M2', 'depends_on': []},
        ])
        with self.assertRaisesRegex(ValueError, 'no graph annotation: WAIT-01'):
            graph.project()

    def test_svg_is_deterministic_and_escapes_authoritative_text(self):
        graph = self.fixture([
            {'id': 'NOW-01', 'milestone': 'M1', 'depends_on': []},
            {'id': 'NEXT-01', 'milestone': 'M2', 'depends_on': []},
            {'id': 'LATER-01', 'milestone': 'M2', 'depends_on': []},
            {'id': 'WAIT-01', 'milestone': 'M3', 'depends_on': []},
        ])
        backlog = graph.root / 'BACKLOG.md'
        backlog.write_text(backlog.read_text(encoding='utf-8').replace(
            'Další dávka (cílová úroveň: implemented).', 'A < B & C.'), encoding='utf-8')
        value = graph.project(); svg = graph.svg(value)
        self.assertIn('A &lt; B &amp; C', svg)
        self.assertIn(value['revision'], svg)
        self.assertEqual(svg, graph.svg(value))

    def test_repository_graph_and_shared_ui_are_wired(self):
        value = RoadmapGraph().project()
        self.assertGreaterEqual(len(value['nodes']), 40)
        self.assertIn('DEV-ROADMAP-GRAPH-01', {item['id'] for item in value['nodes']})
        self.assertIn('/v1/roadmap/graph', DesktopHandler.post_paths)
        self.assertIn('id="settings-roadmap-tab"', HTML)
        self.assertIn("projectRequest('/v1/roadmap/graph',{format:'json'})", JS)
        self.assertNotIn('innerHTML', JS[JS.index('function renderRoadmap()'):JS.index('function selectSettingsTab(')])


if __name__ == '__main__':
    unittest.main()
