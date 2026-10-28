# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.metadata import ValidationError
from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.project_creation import ProjectCreation
from spikes.roadmap_history import rewrite_source_links
from spikes.roadmap_mapping import bind_target_preview, build_mapping, node_title, source_block, validate_mapping_binding
from spikes.roadmap_migration import canonical, inventory, markdown_occurrences
from scripts.roadmap_migration_plan import write_preview
from tests.test_roadmap_migration import MigrationFixture, ROOT


class MappingFixture(MigrationFixture):
    def fixture(self, *, conflict=False):
        git = self.host()
        self.write(git, 'TODO.md', '# TODO — DEV-01\n\n'
                   'Aktivní feature dávka: **Migrace plánu**.\n\n'
                   '- [ ] [in progress] **DEV-01-A — Převést data**\n'
                   '  Zachovat popis i neznámý komentář.\n'
                   '  - [x] Zdrojové bajty zachovány\n'
                   '  - [ ] Potvrdit cílový plán\n')
        self.write(git, 'BACKLOG.md', '- [ ] [planned] **FUTURE-01 — Široký požadavek**\n')
        self.write(git, 'WORK_LOG.md', '## DONE-01 — Historická feature\n\n'
                   '- [x] [completed] **DONE-01-A — Ověření**\n')
        self.write(git, 'docs/roadmap-graph.json', json.dumps({
            'schema': 'fpw-roadmap-graph-v1', 'nodes': [
                {'id': 'DEV-01', 'milestone': 'DEV', 'depends_on': []},
                {'id': 'DONE-01', 'milestone': 'DEV', 'depends_on': ['FUTURE-01'] if conflict else []},
                {'id': 'FUTURE-01', 'milestone': 'DEV', 'depends_on': []}]}))
        git.commit('Mapping fixture')
        return git

class RoadmapMappingTests(MappingFixture, unittest.TestCase):
    def test_valid_hierarchy_preserves_requirements_history_and_checklist(self):
        git = self.fixture()
        value = inventory(git.root)
        mapping = build_mapping(value, {'federated-workspace': git.root})
        self.assertEqual(len(mapping['coverage']), len(value['occurrences']))
        graph = mapping['projects'][0]['graph']
        nodes = {node['id']: node for node in graph['nodes']}
        self.assertEqual(nodes['DEV-01']['type'], 'batch')
        self.assertEqual(nodes['DEV-01-A']['parent_id'], 'DEV-01')
        self.assertEqual(nodes['DEV-01-A']['checklist'], [
            {'checked': True, 'text': 'Zdrojové bajty zachovány'},
            {'checked': False, 'text': 'Potvrdit cílový plán'}])
        self.assertTrue(nodes['DONE-01']['checked'])
        self.assertTrue(nodes['DONE-01-A']['checked'])
        self.assertNotIn('FUTURE-01', nodes)
        future = next(row for row in mapping['definitions'] if row['id'] == 'FUTURE-01')
        self.assertEqual(future['classification'], 'requirement')
        leaf = next(row for row in mapping['definitions'] if row['id'] == 'DEV-01-A')
        self.assertIn('neznámý komentář', leaf['source_block'])
        self.assertFalse(mapping['import_ready'])
        self.assertIsNone(mapping['projects'][0]['target_project_id'])
        conditions = [row for row in mapping['coverage'].values() if row['classification'] == 'checklist']
        self.assertEqual(len(conditions), 2)
        self.assertTrue(all(row['parent_id'] == 'DEV-01-A' and row['id'] is None for row in conditions))
        anonymous = [row for row in mapping['anonymous_identities'] if row['proposed_role'] == 'checklist']
        self.assertEqual(len(anonymous), 2)
        self.assertTrue(all(row['proposed_id'] is None for row in anonymous))

    def test_historical_result_is_included_without_completing_a_future_requirement(self):
        git = self.fixture(conflict=True)
        mapping = build_mapping(inventory(git.root), {'federated-workspace': git.root})
        nodes = {node['id']: node for node in mapping['projects'][0]['graph']['nodes']}
        self.assertTrue(nodes['DONE-01']['checked'])
        self.assertNotIn('FUTURE-01', nodes)
        self.assertEqual(nodes['DONE-01']['depends_on'], [])
        self.assertEqual(mapping['historical_dependency_context'][0]['target_ids'], ['FUTURE-01'])
        self.assertIn('FUTURE-01', nodes['DONE-01']['description'])
        self.assertTrue(any(row['id'] == 'DONE-01' for row in mapping['preserved_dependency_hints']))

    def test_pinned_inventory_and_source_tampering_fail_before_any_output(self):
        git = self.fixture()
        value = inventory(git.root)
        original = build_mapping(value, {'federated-workspace': git.root})
        self.write(git, 'TODO.md', 'dirty outside source pin\n')
        self.assertEqual(original, build_mapping(value, {'federated-workspace': git.root}))
        value['summary']['source_files'] = 100
        with self.assertRaisesRegex(ValidationError, 'Inventory digest differs'):
            build_mapping(value, {'federated-workspace': git.root})
        value = inventory(git.root)
        value['sources'][0]['sha256'] = '0' * 64
        content = {k:v for k,v in value.items() if k != 'inventory_sha256'}
        value['inventory_sha256'] = hashlib.sha256(canonical(content)).hexdigest()
        with self.assertRaisesRegex(ValidationError, 'source hash differs'):
            build_mapping(value, {'federated-workspace': git.root})

    def test_source_block_preserves_comments_and_fenced_heading_examples(self):
        raw = ('- [ ] [ONE-01] Úkol\n  popis\n<!--\n# Není nadpis\n-->\n'
               '```md\n# Příklad\n```\n- [ ] [TWO-01] Další\n').encode()
        items, _ = markdown_occurrences(raw)
        block = source_block(raw, items[0])
        self.assertIn('# Není nadpis', block)
        self.assertIn('# Příklad', block)
        self.assertNotIn('TWO-01', block)

    def test_wrapped_titles_and_maturity_only_labels_preserve_full_source_text(self):
        for text, expected, excerpt in [
            ('- [x] [completed] **TASK-01 — Dlouhý\n  název**\nPopis\n', 'Dlouhý název', False),
            ('- [x] [completed] **TASK-01 (implemented)** — Skutečný popis\n  pokračuje zde.\n',
             'Skutečný popis', True),
        ]:
            items, _ = markdown_occurrences(text.encode())
            self.assertEqual(node_title(items[0], text), (expected, excerpt))

    def test_report_preserves_exact_source_bytes_and_refuses_overwrite(self):
        git = self.fixture()
        value = inventory(git.root)
        roots = {'federated-workspace': git.root}
        mapping = build_mapping(value, roots)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'report'
            before = git.run('status', '--porcelain=v1').stdout
            write_preview(output, value, mapping, roots)
            for source, relative in mapping['projects'][0]['source_references'].items():
                source_meta = next(row for row in value['sources'] if row['key'] == source)
                raw = (output/'federated-workspace'/relative).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), source_meta['sha256'])
            self.assertEqual(json.loads((output/'mapping.json').read_text()), mapping)
            for doc in mapping['projects'][0]['prose_documents']:
                self.assertEqual((output/'federated-workspace'/doc['path']).read_text(), doc['body'])
            self.assertEqual(git.run('status', '--porcelain=v1').stdout, before)
            with self.assertRaises(FileExistsError):
                write_preview(output, value, mapping, roots)

    def test_module_requires_explicit_matching_heading_and_does_not_infer_completion(self):
        git = self.fixture()
        manifest = (ROOT/'modules/publication-experiment-registry.module.json').read_bytes()
        module_id = json.loads(manifest)['module_id']
        self.write(git, 'modules/example.module.json', manifest)
        git.commit('Registered fixture module')
        module = self.repository('module')
        self.write(module, 'module.json', manifest)
        self.write(module, 'ROADMAP.md', '## M1 — Modul\n- [ ] Požadavek\n')
        self.write(module, 'TODO.md', '# TODO — PER-02: Feature\n'
                   '- [x] [completed] **PER-02-A — Hotový podúkol**\n')
        module.commit('Module fixture')
        value = inventory(git.root, modules=[(module_id, module.root, 'HEAD')])
        roots = {'federated-workspace':git.root, module_id:module.root}
        unplaced = build_mapping(value, roots)
        self.assertIn({'kind':'module-placement-required', 'repository_id':module_id}, unplaced['warnings'])
        placement = dict(repository_id=module_id,batch_id='PER-02',milestone_id='MODULE-M1',
                         milestone_title='M1 — Modul',source=module_id+':ROADMAP.md',heading='## M1 — Modul')
        mapping = build_mapping(value, roots, module_placements=[placement])
        project = next(row for row in mapping['projects'] if row['repository_id'] == module_id)
        batch = next(node for node in project['graph']['nodes'] if node['id'] == 'PER-02')
        self.assertFalse(batch['checked'])
        self.assertEqual(batch['parent_id'], 'MODULE-M1')
        placement['heading'] = '## Vymyšlený nadpis'
        with self.assertRaisesRegex(ValidationError, 'heading differs'):
            build_mapping(value, roots, module_placements=[placement])

    def test_frozen_mapping_rejects_changed_inventory_and_tampered_decisions(self):
        git = self.fixture()
        value = inventory(git.root)
        mapping = build_mapping(value, {'federated-workspace': git.root})
        validate_mapping_binding(mapping, value)
        self.write(git, 'BACKLOG.md', '- [ ] [FUTURE-01] Přejmenovaný požadavek\n')
        git.commit('Renamed source')
        with self.assertRaisesRegex(ValidationError, 'explicit rebase'):
            validate_mapping_binding(mapping, inventory(git.root))
        mapping['definitions'][0]['id'] = 'CHANGED-01'
        with self.assertRaisesRegex(ValidationError, 'Mapping digest differs'):
            validate_mapping_binding(mapping, value)

    def test_existing_target_diff_uses_registered_git_without_state_initialization(self):
        source = self.fixture()
        value = inventory(source.root)
        mapping = build_mapping(value, {'federated-workspace': source.root})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            node = root/'node.json'
            created = ProjectCreation(node).create('Target', str(root/'target'), str(uuid4()))
            project_id = created['id']
            service = Artifacts(node)
            saved = service.save(dict(project_id=project_id, artifact_id=main_todo_id(project_id),
                                      base_head=created['commit_id'], title='Původní TODO',
                                      body='# Původní plán\r\n- [ ] Zachovat\r\n', new=True), str(uuid4()))
            # Repository reads must never construct/recover a local Workspace.
            with patch('spikes.workspace.Workspace.__init__', side_effect=AssertionError('state initialization')):
                bound = bind_target_preview(mapping, node, project_id)
                self.assertEqual(bound, bind_target_preview(bound, node, project_id))
            project = bound['projects'][0]
            target = project['target_preview']
            self.assertEqual(target['expected_head'], saved['commit_id'])
            self.assertEqual(target['original_content'], '# Původní plán\r\n- [ ] Zachovat\r\n')
            self.assertIn('-# Původní plán', target['diff'])
            self.assertTrue(target['replacement_authorized'])
            self.assertFalse(target['apply_validated'])
            self.assertEqual(target['action'], 'replace-test-plan')
            self.assertNotIn('Původní plán', project['body'])
            self.assertTrue(all('Původní plán' not in doc['body'] for doc in project['prose_documents']))
            self.assertEqual(Artifacts(node).open(project_id)['commit_id'], saved['commit_id'])
            validate_mapping_binding(bound, value)

    def test_conflicting_source_states_are_not_promoted_as_resolved_tasks(self):
        git = self.fixture()
        self.write(git, 'WORK_LOG.md', '## DONE-01 — Historie\n'
                   '- [x] [DEV-01-A] Dříve hotovo\n')
        git.commit('Conflicting task evidence')
        mapping = build_mapping(inventory(git.root), {'federated-workspace':git.root})
        self.assertNotIn('DEV-01-A', [node['id'] for node in mapping['projects'][0]['graph']['nodes']])
        self.assertTrue(any(row['kind'] == 'different-source-states' for row in mapping['warnings']))

    def test_historical_batches_outside_partial_graph_and_physical_adhoc_tasks_are_included(self):
        git = self.fixture()
        with (git.root/'WORK_LOG.md').open('a', encoding='utf-8') as stream:
            stream.write('\n## F-M2-OLD-01 — Historický návrh (designed)\n\n'
                         'Doložená návrhová dávka, bez tvrzení produkční implementace.\n'
                         '- [x] [ODD-01] Ad-hoc úkol s jiným prefixem\n')
        git.commit('Historical feature absent from partial graph')
        mapping = build_mapping(inventory(git.root), {'federated-workspace':git.root})
        nodes = {node['id']:node for node in mapping['projects'][0]['graph']['nodes']}
        self.assertEqual(nodes['F-M2-OLD-01']['parent_id'], 'MILESTONE-M2')
        self.assertTrue(nodes['F-M2-OLD-01']['checked'])
        self.assertEqual(nodes['ODD-01']['parent_id'], 'F-M2-OLD-01')
        self.assertIn('designed', nodes['F-M2-OLD-01']['title'])
        self.assertIn('bez tvrzení produkční implementace', nodes['F-M2-OLD-01']['description'])

    def test_free_ideas_are_milestone_descriptions_or_separate_markdown_not_fake_tasks(self):
        git = self.fixture()
        self.write(git, 'Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md',
                   '# Roadmapa\n\n## Milestone M1 – Základ\n\n'
                   'Volná myšlenka bez charakteru úkolu.\n'
                   '**Gate M1 — splněn (PoC validated).**\n'
                   '- [ ] Obecný směr, nikoli připravená dávka.\n\n'
                   '## Nezařazené nápady\n\nZatím bez jednoznačné vazby.\n')
        git.commit('Free notes')
        mapping = build_mapping(inventory(git.root), {'federated-workspace':git.root})
        project = mapping['projects'][0]
        nodes = {node['id']:node for node in project['graph']['nodes']}
        self.assertIn('Volná myšlenka bez charakteru úkolu.', nodes['MILESTONE-M1']['description'])
        self.assertTrue(nodes['MILESTONE-M1']['checked'])
        self.assertFalse(nodes['MILESTONE-DEV']['checked'])
        self.assertFalse(any(id_.startswith('MIG-REQ-') for id_ in nodes))
        anonymous = [item for item in mapping['anonymous_identities']
                     if item['proposed_role'] in {'free-description', 'supporting-markdown'}]
        self.assertTrue(anonymous)
        self.assertTrue(all(item['proposed_id'] is None for item in anonymous))
        loose = [doc for doc in project['prose_documents'] if doc['owner_id'] is None]
        self.assertTrue(any('Zatím bez jednoznačné vazby.' in doc['body'] for doc in loose))
        self.assertTrue(all(doc['path'].endswith('.md') for doc in loose))

    def test_legacy_standalone_task_keeps_id_and_status_without_inventing_a_batch(self):
        git = self.fixture()
        with (git.root/'WORK_LOG.md').open('a', encoding='utf-8') as stream:
            stream.write('\n## Staré samostatné výstupy\n\n- [x] [M0-01] Původní dokončený experiment\n')
        git.commit('Standalone historical task')
        mapping = build_mapping(inventory(git.root), {'federated-workspace':git.root})
        project = mapping['projects'][0]
        nodes = {node['id']:node for node in project['graph']['nodes']}
        self.assertNotIn('M0-01', nodes)
        self.assertIn('M0-01', nodes['MILESTONE-M0']['description'])
        self.assertTrue(any('- [x] [M0-01]' in doc['body'] for doc in project['prose_documents']))

    def test_oversized_free_prose_stays_complete_in_linked_markdown(self):
        git = self.fixture()
        paragraph = 'Souvislý nezkrácený text ' + 'x' * 9000
        self.write(git, 'Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md',
                   '## Milestone M1 – Základ\n\n' + paragraph + '\n')
        git.commit('Long free description')
        mapping = build_mapping(inventory(git.root), {'federated-workspace':git.root})
        project = mapping['projects'][0]
        notes = [doc for doc in project['prose_documents'] if doc['owner_id'] == 'MILESTONE-M1']
        self.assertTrue(any(paragraph in doc['body'] for doc in notes))
        milestone = next(node for node in project['graph']['nodes'] if node['id'] == 'MILESTONE-M1')
        self.assertIn('Podklad:', milestone['description'])
        self.assertNotIn('x' * 100, milestone['description'])
        self.assertEqual(project['graph']['status'], 'ready')

    def test_derived_notes_reconcile_selected_links_and_deactivate_unselected_paths(self):
        source = 'federated-workspace:docs/note.md'
        text = ('[TODO](../TODO.md#active) and [contract](adr/unselected.md) '
                'and [web](https://example.test/doc)')
        rendered = rewrite_source_links(
            text, source, {source: 'docs/note.md'},
            {'federated-workspace:TODO.md': 'artifacts/00000000-0000-0000-0000-000000000000/source.md'})
        self.assertIn('[TODO](artifacts/00000000-0000-0000-0000-000000000000/source.md#active)', rendered)
        self.assertIn('[contract] (zdrojová cesta: `adr/unselected.md`)', rendered)
        self.assertIn('[web](https://example.test/doc)', rendered)
