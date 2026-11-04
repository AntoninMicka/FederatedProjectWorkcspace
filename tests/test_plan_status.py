# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Work states and recursive summaries remain separate from accepted completion."""
from itertools import product
import os
import sys
import shutil
import subprocess
import unittest
from uuid import uuid4

from spikes.plan_status_ui import PLAN_STATUS_JS
from tests import test_task_graph as graph_tests


class PlanStatusTests(unittest.TestCase):
    fixture = graph_tests.TaskGraphTests.fixture

    def graph(self, children, group='sum'):
        return self.fixture('''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - status: sum
  - [ ] [BATCH-01] Dávka
    - type: batch
    - status: ''' + group + '\n' + children)

    @staticmethod
    def child(identifier, status):
        return (f'    - [{"x" if status == "completed" else " "}] [TASK-{identifier}] {identifier}\n'
                f'      - type: task\n      - status: {status}\n')

    def test_every_pair_of_states_has_deterministic_summary_without_acceptance(self):
        states = ('planned', 'in progress', 'resolved', 'failed', 'completed', 'deferred')
        expected = (
            ('planned', 'in progress', 'in progress', 'failed', 'in progress', 'planned'),
            ('in progress', 'in progress', 'in progress', 'failed', 'in progress', 'in progress'),
            ('in progress', 'in progress', 'resolved', 'failed', 'resolved', 'in progress'),
            ('failed', 'failed', 'failed', 'failed', 'failed', 'failed'),
            ('in progress', 'in progress', 'resolved', 'failed', 'completed', 'in progress'),
            ('planned', 'in progress', 'in progress', 'failed', 'in progress', 'deferred'),
        )
        for (a, first), (b, second) in product(enumerate(states), repeat=2):
            with self.subTest(first=first, second=second):
                graph = self.graph(self.child('A', first) + self.child('B', second))
                self.assertEqual('ready', graph['status'], graph)
                nodes = {n['id']: n for n in graph['nodes']}
                for identifier in ('BATCH-01', 'MILESTONE-01'):
                    self.assertEqual(expected[a][b], nodes[identifier]['status'])
                    self.assertFalse(nodes[identifier]['checked'])
                self.assertEqual(2, sum(nodes['BATCH-01']['status_counts'].values()))

    def test_literal_sum_marker_and_conflicting_metadata(self):
        source = '- [SUM] [MILESTONE-DEV] DEV\n  - type: milestone\n'
        graph = self.fixture('<!-- fpw-plan-profile: software-development/v1 -->\n'+source)
        self.assertEqual('ready', graph['status'], graph)
        self.assertEqual(('sum', 'planned', False),
                         tuple(graph['nodes'][0][k] for k in ('status_mode', 'status', 'checked')))
        self.assertEqual('invalid', self.fixture(source+'  - status: failed\n')['status'])
        self.assertEqual('invalid', self.fixture('- [SUM] [TASK-01] T\n  - type: task\n')['status'])

    def test_start_gate_requires_resolved_work_and_at_most_one_running_dependency(self):
        from spikes.task_graph import dependency_start_blockers
        cases = [
            ([], True), (['resolved'], True), (['completed'], True),
            (['in progress'], True), (['resolved', 'completed', 'in progress'], True),
            (['in progress', 'in progress'], False), (['planned', 'resolved'], False),
            (['failed', 'completed'], False), (['deferred', 'in progress'], False),
            (['unknown'], False),
        ]
        for states, expected in cases:
            with self.subTest(states=states):
                nodes = {f'TASK-{i}': {'status': status} for i, status in enumerate(states)}
                self.assertEqual(expected, not dependency_start_blockers(list(nodes), nodes))

    def test_empty_manual_override_and_legacy_description(self):
        graph = self.graph('')
        self.assertEqual({'planned'}, {n['status'] for n in graph['nodes']})
        graph = self.graph(self.child('A', 'failed'), group='deferred')
        nodes = {n['id']: n for n in graph['nodes']}
        self.assertEqual('deferred', nodes['BATCH-01']['status'])
        legacy = self.fixture('- [ ] [TASK-01] Legacy\n  - Stav: připraveno k předání rozsahu\n')
        self.assertEqual('ready', legacy['status'])
        self.assertEqual('Stav: připraveno k předání rozsahu', legacy['nodes'][0]['description'])

    def test_invalid_leaf_sum_duplicate_unknown_and_unaccepted_done_reject(self):
        for text in ('sum', 'made-up', 'completed', 'planned\n      - status: failed'):
            with self.subTest(text=text):
                graph = self.graph(self.child('A', 'planned').replace('status: planned', 'status: '+text))
                self.assertEqual('invalid', graph['status'])

    def test_linked_children_participate_in_sum_and_resolved_allows_start_only(self):
        external = str(uuid4())
        graph = self.fixture('''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] M
  - type: milestone
  - status: sum
  - [ ] [BATCH-01] [B](artifacts/''' + external + '''/content.md)
    - type: batch
    - status: sum
''', documents=[(external, 'Linked', '''<!-- fpw-plan-document: definitions/v1 -->
- [ ] [TASK-A] A
  - type: task
  - status: resolved
- [ ] [TASK-B] B
  - type: task
  - depends_on: TASK-A
''')])
        self.assertEqual('ready', graph['status'], graph)
        nodes = {n['id']: n for n in graph['nodes']}
        self.assertEqual('in progress', nodes['BATCH-01']['status'])
        self.assertFalse(nodes['TASK-B']['blocked'])
        self.assertTrue(nodes['TASK-B']['ready'])
        self.assertFalse(nodes['TASK-B']['completion_ready'])
        self.assertIn('SUM', graph['svg'])

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires Qt/WebEngine')
    def test_browser_edits_sum_group_and_projects_state_into_queue(self):
        result = subprocess.run([sys.executable, '-m', 'tests.ui.plan_status_smoke'],
                                text=True, capture_output=True, timeout=35)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn('plan status browser OK', result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_scoped_status_draft_preserves_crlf_fences_unknown_text_and_checkbox_rules(self):
        code = r'''
const assert=require('node:assert/strict');
const original='    - [ ] [TASK-A] Title\r\n      - type: task\r\n      - Stav: historical prose\r\n      ```md\r\n      - status: failed\r\n      ```\r\n';
const updated=planStatusDraft(original,'in progress');
assert(updated.includes('      - status: in progress\r\n'));assert(updated.includes('- Stav: historical prose\r\n'));
assert(updated.endsWith('      - status: failed\r\n      ```\r\n'));assert(!updated.replaceAll('\r\n','').includes('\n'));
assert(planStatusDraft(updated,'completed').startsWith('    - [x]'));
assert(planStatusDraft(planStatusDraft(updated,'completed'),'resolved').startsWith('    - [ ]'));
assert.equal(planStatusDraft(updated,'failed').split('status: failed').length,3);
assert(planStatusDraft(original,'sum').startsWith('    - [ ]'));
const sum='- [SUM] [MILESTONE-DEV] DEV\n  - type: milestone\n';
assert.equal(planStatusDraft(sum,'sum'),sum);
assert(planStatusDraft(sum,'planned').startsWith('- [ ] [MILESTONE-DEV]'));
assert(planStatusDraft(sum,'completed').startsWith('- [x] [MILESTONE-DEV]'));
'''
        from spikes.desktop_ui import JS
        parser = JS[JS.index('function parseTaskPlanDraft('):JS.index('function replaceTaskPlanLine(')]
        code += "\nassert(parseTaskPlanDraft('<!-- fpw-plan-profile: software-development/v1 -->\\n'+sum).safe);"
        subprocess.run(['node', '-e', PLAN_STATUS_JS + parser + code], check=True)
