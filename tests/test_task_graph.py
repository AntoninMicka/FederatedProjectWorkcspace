# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4

from spikes.markdown_documents import main_todo_id
from spikes.task_graph import project_task_graph, task_graph_svg
from spikes.desktop_ui import HTML, JS


class TaskGraphTests(unittest.TestCase):
    def fixture(self, body, subgraphs=()):
        project_id = str(uuid4()); todo_id = main_todo_id(project_id)
        entities = {todo_id: {'id': todo_id, 'kind': 'document', 'title': 'Hlavní TODO',
                              'file': 'content.md', 'tags': []}}
        files = {f'artifacts/{todo_id}/content.md': body.encode(),
                 f'artifacts/{todo_id}/metadata.json': b'{}'}
        for title, text in subgraphs:
            artifact_id = str(uuid4())
            entities[artifact_id] = {'id': artifact_id, 'kind': 'document', 'title': title,
                                     'file': 'content.md', 'tags': ['plan-subgraph']}
            files[f'artifacts/{artifact_id}/content.md'] = text.encode()
            files[f'artifacts/{artifact_id}/metadata.json'] = b'{}'
        return project_task_graph(files, entities, project_id, 'a' * 40)

    def test_canonical_relations_readiness_critical_path_and_subgraph(self):
        value = self.fixture('''# TODO
- [x] [TASK-01] Základ
- [ ] [TASK-02] Druhý
  - závisí na: TASK-01
  - duplikuje: TASK-04
- [ ] [TASK-03] Třetí
  - blokován: TASK-02
- [ ] [TASK-04] Alternativa
  - souvisí s: TASK-03
''', [('Aktivní řez', '- [ ] [TASK-02]\n- [x] [TASK-03] ignorovaný název\n')])
        self.assertEqual('ready', value['status'])
        self.assertEqual(['TASK-01', 'TASK-02', 'TASK-03'], value['critical_path'])
        self.assertEqual(['TASK-02', 'TASK-04'], value['ready'])
        self.assertEqual(['TASK-03'], value['blocked'])
        self.assertEqual(['TASK-02', 'TASK-03'], value['subgraphs'][0]['task_ids'])
        second = next(item for item in value['nodes'] if item['id'] == 'TASK-02')
        self.assertEqual(['TASK-01'], second['depends_on'])
        self.assertEqual(['TASK-04'], second['relations']['duplicates'])
        fourth = next(item for item in value['nodes'] if item['id'] == 'TASK-04')
        self.assertEqual(['TASK-02'], fourth['relations']['duplicates'])

    def test_blocks_is_stored_as_inverse_dependency(self):
        value = self.fixture('- [ ] [TASK-01] První\n  - blokuje: TASK-02\n- [ ] [TASK-02] Druhý\n')
        second = next(item for item in value['nodes'] if item['id'] == 'TASK-02')
        self.assertEqual(['TASK-01'], second['depends_on'])

    def test_invalid_id_unknown_duplicate_cycle_and_subgraph_fail_closed(self):
        cases = [
            '- [ ] Bez ID\n',
            '- [ ] [TASK-01] A\n- [ ] [TASK-01] B\n',
            '- [ ] [TASK-01] A\n  - depends_on: TASK-99\n',
            '- [ ] [TASK-01] A\n  - depends_on: TASK-02\n- [ ] [TASK-02] B\n  - depends_on: TASK-01\n',
        ]
        for body in cases:
            with self.subTest(body=body):
                value = self.fixture(body)
                self.assertEqual('invalid', value['status']); self.assertEqual([], value['nodes'])
        value = self.fixture('- [ ] [TASK-01] A\n', [('Chybný', '- [ ] [TASK-99]\n')])
        self.assertEqual('invalid', value['status'])
        value = self.fixture('- [ ] [TASK-01] A\n  - duplicates: TASK-02\n- [ ] [TASK-02] B\n  - duplicates: TASK-01\n')
        self.assertEqual('invalid', value['status'])

    def test_fences_are_ignored_and_svg_is_deterministic_and_escaped(self):
        value = self.fixture('```\n- [ ] Bez ID\n```\n- [ ] [TASK-01] <script>&\n')
        first = task_graph_svg(value); second = task_graph_svg(value)
        self.assertEqual(first, second)
        self.assertIn('&lt;script&gt;&amp;', first); self.assertNotIn('<script>', first)

    def test_shared_ui_places_plan_after_tasks_and_uses_safe_svg_dom(self):
        self.assertLess(HTML.index('id="todo-tab"'), HTML.index('id="plan-tab"'))
        self.assertLess(HTML.index('id="plan-tab"'), HTML.index('id="artifacts-tab"'))
        for marker in ('Hlavní graf', 'Podgrafy', 'renderTaskPlanSidebar(result.plan)',
                       "roadmapElement('svg'", 'textContent=item.title'):
            self.assertIn(marker, HTML + JS)


if __name__ == '__main__':
    unittest.main()
