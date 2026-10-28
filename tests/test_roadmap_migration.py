# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Inventory is read-only, source-scoped and never approves task identities."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from spikes.metadata import ValidationError
from spikes.roadmap_migration import HOST_SOURCES, PinnedRepository, inventory, markdown_occurrences
from spikes.storage import Git

ROOT = Path(__file__).resolve().parents[1]


class MigrationFixture:
    def repository(self, name='host'):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / name
        root.mkdir()
        git = Git(root)
        git.run('init', '--initial-branch=main')
        return git

    def write(self, git, path, value):
        target = git.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(value if isinstance(value, bytes) else value.encode())

    def host(self):
        git = self.repository()
        for path, _ in HOST_SOURCES:
            self.write(git, path, '# Support\n')
        self.write(git, HOST_SOURCES[0][0], '# Roadmap\n- [ ] Požadavek bez ID\n')
        self.write(git, 'TODO.md', '# TODO — DEV-01\n- [ ] [planned] **DEV-01-A — Práce**\n')
        self.write(git, 'BACKLOG.md', '- [ ] **[planned] V-01 — Validace**\n')
        self.write(git, 'WORK_LOG.md', '## DONE-01 — Historie\n- [x] **DONE-01-A — Hotovo**\n')
        self.write(git, 'docs/roadmap-graph.json', json.dumps({
            'schema': 'fpw-roadmap-graph-v1', 'nodes': [
                {'id': 'DEV-01', 'depends_on': []}, {'id': 'V-01', 'depends_on': []}]}))
        return git

class RoadmapMigrationTests(MigrationFixture, unittest.TestCase):
    def test_formats_unicode_offsets_comments_and_examples(self):
        raw = ('# TODO — DEV-01\r\n'
               '- [ ] **[planned] V-01 — Žluťoučký**\r\n'
               '- [x] [completed] **TASK-01 (implemented)** — hotovo\n'
               '- [ ] [TASK-02] Úkol\n'
               '  - [ ] bez identity\n'
               '<!--\n- [ ] [HIDDEN-01] skryto\n-->\n'
               '````md\n- [ ] [EXAMPLE-01] příklad\n```\n````\n').encode()
        items, _ = markdown_occurrences(raw)
        self.assertEqual([item['id'] for item in items], ['DEV-01', 'V-01', 'TASK-01', 'TASK-02', None])
        self.assertEqual(items[1]['declared_status'], 'planned')
        self.assertEqual(items[2]['checkbox_state'], 'checked')
        for item in items:
            self.assertEqual(raw[item['byte_start']:item['byte_end']].decode().rstrip('\r\n'), item['text'])

    def test_unterminated_examples_fail_instead_of_hiding_remaining_content(self):
        for raw in (b'```\n- [ ] hidden', b'<!-- hidden\n- [ ] hidden'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValidationError, 'manual source review'):
                markdown_occurrences(raw)

    def test_pins_commit_bytes_and_leaves_dirty_worktree_untouched(self):
        git = self.host()
        base = git.commit('Fixture')
        self.write(git, 'TODO.md', '# Changed outside inventory\n')
        before = git.run('status', '--porcelain=v1').stdout
        first = inventory(git.root, revision=base)
        second = inventory(git.root, revision=base)
        self.assertEqual(first, second)
        self.assertEqual(git.head(), base)
        self.assertEqual(git.run('status', '--porcelain=v1').stdout, before)
        source = next(item for item in first['sources'] if item['path'] == 'TODO.md')
        original = git.run('show', base + ':TODO.md', binary=True).stdout
        self.assertEqual(source['sha256'], hashlib.sha256(original).hexdigest())
        self.assertTrue(any(item['id'] == 'DEV-01' for item in first['definitions']))
        self.assertFalse(first['import_ready'])
        self.assertEqual(first['issues'], [])
        self.assertTrue(all(item['privacy'] == 'pending-review' for item in first['sources']))
        proposed = first['anonymous_mapping_proposals']
        self.assertEqual(len(proposed), 1)
        self.assertEqual(proposed[0]['proposed_role'], 'requirement')
        self.assertEqual(proposed[0]['proposed_id'], 'MIG-REQ-0001')
        self.assertFalse(proposed[0]['mapping_approved'])

    def test_selected_git_symlink_missing_and_oversize_sources_fail_closed(self):
        git = self.host()
        git.commit('Fixture')
        path = git.root / 'BACKLOG.md'
        path.unlink(); path.symlink_to('TODO.md')
        base = git.commit('Symlink')
        repo = PinnedRepository(git.root, 'test', base)
        for name, error in [('BACKLOG.md', 'Non-regular'), ('missing.md', 'Missing pinned'),
                            ('../TODO.md', 'Invalid source path')]:
            with self.subTest(name=name), self.assertRaisesRegex(ValidationError, error):
                repo.read(name)
        with patch('spikes.roadmap_migration.MAX_FILE', 1):
            with self.assertRaisesRegex(ValidationError, 'exceeds inventory limit'):
                repo.read('TODO.md')

    def test_duplicate_states_are_reported_without_choosing_a_winner(self):
        git = self.host()
        self.write(git, 'BACKLOG.md', '- [ ] [SAME-01] nový\n')
        self.write(git, 'WORK_LOG.md', '- [x] [SAME-01] dříve hotový\n')
        git.commit('Conflicting source evidence')
        value = inventory(git.root)
        group = next(item for item in value['definitions'] if item['id'] == 'SAME-01')
        self.assertEqual(group['checkbox_states'], ['checked', 'unchecked'])
        self.assertEqual(value['summary']['different_state_ids'], 1)
        self.assertNotIn('canonical', group)
        self.assertFalse(group['mapping_approved'])
        self.assertIn('BACKLOG.md:', group['proposed_definition'])
        self.assertEqual(len(value['anonymous_checkboxes']), 1)

    def test_module_requires_explicit_selection_and_keeps_id_scope(self):
        git = self.host()
        raw = (ROOT / 'modules/publication-experiment-registry.module.json').read_bytes()
        manifest = json.loads(raw)
        module_id = manifest['module_id']
        self.write(git, 'modules/example.module.json', raw)
        self.write(git, 'BACKLOG.md', '- [ ] [SHARED-01] Hostitel\n')
        git.commit('Registered module')
        unselected = inventory(git.root)
        self.assertFalse(unselected['modules'][0]['included'])
        self.assertTrue(any(item['kind'] == 'unselected-module' for item in unselected['issues']))
        module = self.repository('module')
        self.write(module, 'module.json', raw)
        self.write(module, 'ROADMAP.md', '- [ ] [SHARED-01] Modul\n')
        commit = module.commit('Module fixture')
        value = inventory(git.root, modules=[(module_id, module.root, commit)])
        shared = [item for item in value['definitions'] if item['id'] == 'SHARED-01']
        self.assertEqual(len(shared), 2)
        self.assertTrue(all(not item['needs_reconciliation'] for item in shared))
        self.assertTrue(value['modules'][0]['included'])
        self.assertNotIn(str(module.root), json.dumps(value))
        # Uncommitted files are not imported as if they belonged to the pin.
        self.write(module, 'TODO.md', '- [ ] [UNTRACKED-01] neimportovat\n')
        self.assertEqual(value, inventory(git.root, modules=[(module_id, module.root, commit)]))
        manifest['module_version'] = '99.0.0'
        self.write(module, 'module.json', json.dumps(manifest))
        other = module.commit('Changed declaration')
        with self.assertRaisesRegex(ValidationError, 'differs from host'):
            inventory(git.root, modules=[(module_id, module.root, other)])

    def test_explicit_selection_limits_and_missing_graph_definitions_are_reported(self):
        git = self.host()
        self.write(git, 'docs/roadmap-graph.json', json.dumps({
            'schema': 'fpw-roadmap-graph-v1', 'nodes': [{'id': 'MISSING-01', 'depends_on': []}]}))
        git.commit('Graph reference')
        value = inventory(git.root)
        self.assertIn({'kind': 'graph-id-without-definition', 'id': 'MISSING-01'}, value['issues'])
        with patch('spikes.roadmap_migration.MAX_FILES', 1):
            with self.assertRaisesRegex(ValidationError, 'bounded selection'):
                inventory(git.root)
        with self.assertRaisesRegex(ValidationError, 'Unknown or duplicate selected module'):
            inventory(git.root, modules=[('unknown', git.root, 'HEAD')])

    def test_nested_directory_cannot_impersonate_a_module_repository(self):
        git = self.host()
        git.commit('Fixture')
        nested = git.root / 'unversioned-module'
        nested.mkdir()
        with self.assertRaisesRegex(ValidationError, 'repository root'):
            PinnedRepository(nested, 'module', 'HEAD')

    def test_requirement_proposals_avoid_existing_ids_and_do_not_reopen_history(self):
        git = self.host()
        self.write(git, 'BACKLOG.md', '- [ ] [MIG-REQ-0001] Existující identita\n')
        self.write(git, 'WORK_LOG.md', '- [x] Historický důkaz bez ID\n')
        git.commit('Reserved requirement identity')
        value = inventory(git.root)
        proposals = value['anonymous_mapping_proposals']
        self.assertEqual(proposals[0]['proposed_id'], 'MIG-REQ-0002')
        self.assertEqual(proposals[1]['proposed_role'], 'historical-evidence')
        self.assertIsNone(proposals[1]['proposed_id'])

    def test_invalid_dependency_hints_do_not_become_an_importable_graph(self):
        git = self.host()
        cases = [
            [{'id': 'ONE-01', 'depends_on': ['MISSING-01']}],
            [{'id': 'ONE-01', 'depends_on': []}, {'id': 'ONE-01', 'depends_on': []}],
            [{'id': 'ONE-01', 'depends_on': ['TWO-01']},
             {'id': 'TWO-01', 'depends_on': ['ONE-01']}],
            [{'id': 'ONE-01', 'depends_on': ['ONE-01']}],
        ]
        for index, nodes in enumerate(cases):
            self.write(git, 'docs/roadmap-graph.json', json.dumps({
                'schema': 'fpw-roadmap-graph-v1', 'nodes': nodes}))
            git.commit('Invalid graph fixture ' + str(index))
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                inventory(git.root)
