# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import unittest
from uuid import uuid4

from spikes.markdown_documents import main_todo_id
from spikes.task_graph import project_task_graph, task_graph_svg
from spikes.desktop_ui import CSS, HTML, JS


class TaskGraphTests(unittest.TestCase):
    def fixture(self, body, subgraphs=(), documents=()):
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
        for artifact_id, title, text in documents:
            entities[artifact_id] = {'id': artifact_id, 'kind': 'document', 'title': title,
                                     'file': 'content.md', 'tags': []}
            files[f'artifacts/{artifact_id}/content.md'] = text.encode()
            files[f'artifacts/{artifact_id}/metadata.json'] = b'{}'
        return project_task_graph(files, entities, project_id, 'a' * 40)

    def test_inline_and_linked_batch_children_materialize_the_same_hierarchy(self):
        inline = self.fixture('''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Editor plánu
  - type: milestone
  - [ ] [BATCH-01] Task editor
    - type: batch
    - [ ] [TASK-01] Sestavit widgety
      - type: task
''')
        document_id = str(uuid4())
        linked = self.fixture(f'''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Editor plánu
  - type: milestone
  - [ ] [BATCH-01] [Task editor](artifacts/{document_id}/content.md)
    - type: batch
''', documents=[(document_id, 'Task editor', '''<!-- fpw-plan-document: definitions/v1 -->
- [ ] [TASK-01] Sestavit widgety
  - type: task
''')])
        self.assertEqual('ready', inline['status'])
        self.assertEqual('ready', linked['status'])
        fields = lambda value: [(item['id'], item['title'], item['type'],
                                 item['parent_id'], item['hierarchy_depth'])
                                for item in value['nodes']]
        self.assertEqual(fields(inline), fields(linked))
        external = next(item for item in linked['nodes'] if item['id'] == 'TASK-01')
        self.assertEqual(document_id, external['source']['artifact_id'])
        self.assertEqual(2, external['line'])

    def test_profiled_bundle_rejects_ambiguous_or_unsafe_hierarchy(self):
        document_id = str(uuid4())
        prefix = '''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
'''
        cases = [
            prefix + '  - [ ] [BATCH-01] Batch\n    - type: batch\n'
                     '    - [ ] [TASK-01] Task\n      - type: milestone\n',
            prefix + f'  - [ ] [BATCH-01] [Batch](artifacts/{document_id}/content.md)\n'
                     '    - type: batch\n    - [ ] [TASK-01] Inline\n      - type: task\n',
            prefix + '  - [ ] [BATCH-01] [Batch](artifacts/00000000-0000-4000-8000-000000000099/content.md)\n'
                     '    - type: batch\n',
        ]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual('invalid', self.fixture(body)['status'])

    def test_profiled_descriptions_and_cross_milestone_batch_dependency(self):
        value = self.fixture('''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Import
  - type: milestone
  - Importovat projektové podklady.
  - Rozsah: hlavní i doplňkové soubory.
  - [x] [BATCH-01] Načíst roadmapu
    - type: batch
    - Načíst hlavní i doplňkové roadmapy.
    - [ ] [TASK-01] Načíst soubor
      - type: task
      - Zachovat původní bajty souboru.
      - [x] Import zachová původní bajty.
      - [ ] Náhled nevykreslí aktivní HTML.
- [ ] [MILESTONE-02] Zobrazení
  - type: milestone
  - Zobrazit importovaný plán.
  - [ ] [BATCH-02] Vykreslit roadmapu
    - type: batch
    - Navázat na import z prvního milníku.
    - depends_on: BATCH-01
''')
        self.assertEqual('ready', value['status'])
        nodes = {item['id']: item for item in value['nodes']}
        self.assertEqual('Importovat projektové podklady.\nRozsah: hlavní i doplňkové soubory.',
                         nodes['MILESTONE-01']['description'])
        self.assertEqual('Načíst hlavní i doplňkové roadmapy.', nodes['BATCH-01']['description'])
        self.assertEqual('Zachovat původní bajty souboru.', nodes['TASK-01']['description'])
        self.assertEqual([{'checked': True, 'text': 'Import zachová původní bajty.'},
                          {'checked': False, 'text': 'Náhled nevykreslí aktivní HTML.'}],
                         nodes['TASK-01']['checklist'])
        self.assertEqual([], nodes['BATCH-01']['checklist'])
        self.assertEqual(5, len(nodes))
        self.assertEqual(['BATCH-01'], nodes['BATCH-02']['depends_on'])
        self.assertEqual(1, nodes['BATCH-02']['dependency_depth'])
        self.assertNotIn('type: batch', nodes['BATCH-02']['description'])
        self.assertIn('Importovat projektové podklady.', value['svg'])
        self.assertIn('Navázat na import z prvního milníku.', value['svg'])
        self.assertIn('class="edge"', value['svg'])
        self.assertNotIn('TASK-01', value['svg'])

    def test_profiled_checklist_is_bounded_and_only_allowed_below_task(self):
        invalid_parent = self.fixture('''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - [ ] [BATCH-01] Dávka
    - type: batch
    - [ ] Podmínka bez tasku
''')
        self.assertEqual('invalid', invalid_parent['status'])
        too_many = '\n'.join('      - [ ] Podmínka %d' % index for index in range(101))
        value = self.fixture('''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - [ ] [BATCH-01] Dávka
    - type: batch
    - [ ] [TASK-01] Úkol
      - type: task
%s
''' % too_many)
        self.assertEqual('invalid', value['status'])
        self.assertIn('100', value['error'])

    def test_profiled_description_limit_fails_closed(self):
        value = self.fixture('''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - %s
''' % ('x' * 8193))
        self.assertEqual('invalid', value['status'])
        self.assertIn('8 KiB', value['error'])

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
        for marker in ('Hlavní graf /', 'sidebar-plan-tree', 'Podgrafy', 'renderTaskPlanSidebar(result.plan)',
                       "roadmapElement('svg'", 'textContent=item.title',
                       'renderProfiledTaskRoadmap', 'plan-milestone-label',
                       'renderProfiledTaskLevel', 'plan-task-card', 'Podmínky splnění',
                       'position:sticky', "item.type==='batch'"):
            self.assertIn(marker, HTML + CSS + JS)


if __name__ == '__main__':
    unittest.main()
