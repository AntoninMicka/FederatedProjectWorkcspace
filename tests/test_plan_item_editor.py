# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import shutil
import subprocess
import unittest
from uuid import uuid4

from spikes.metadata import ValidationError
from spikes.plan_item_editor import PlanItems, item_span, subtree_span
from spikes.projects import Projects
from tests import test_artifact_actions as artifact_tests


BODY = '''<!-- fpw-plan-profile: software-development/v1 -->
# Roadmapa — zachovat komentáře a formát
```md
- [ ] [TASK-01] Pouze příklad, nikoli definice
```
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - [ ] [BATCH-01] Dávka
    - type: batch
    <!-- vlastní neznámý komentář -->
    - [ ] [TASK-01] První
      - type: task
      - Popis s háčky
      - [ ] Podmínka

    - [ ] [TASK-02] Druhý
      - type: task
      - depends_on: TASK-01

# Konec — mimo položky
'''


class PlanItemTests(unittest.TestCase):
    def setUp(self):
        artifact_tests.ArtifactActionTests.setUp(self)
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Roadmapa', body=BODY.replace('\n', '\r\n'), new=False), str(uuid4()))['commit_id']
        self.editor = PlanItems(self.node)

    def opened(self, task='TASK-01'):
        return self.editor.open(self.project, self.artifact, task, self.head)

    def request(self, model=None, **changes):
        model = model or self.opened()
        return {k: model[k] for k in ('project_id', 'artifact_id', 'task_id', 'expected_head', 'fragment_sha256', 'body')} | changes

    def test_only_own_block_is_loaded_and_only_its_bytes_are_saved(self):
        model = self.opened(); self.assertNotIn('TASK-02', model['body'])
        self.assertNotIn('Pouze příklad', model['body']); self.assertNotIn('# Konec', model['body'])
        batch = self.opened('BATCH-01')
        self.assertNotIn('TASK-01', batch['body']); self.assertIn('neznámý komentář', batch['body'])
        git = Projects(self.node).repository(self.project); before = git.snapshot(self.head)
        request = self.request(model, body=model['body'].replace('První', 'Upravený').replace('[ ] Podmínka', '[x] Podmínka'))
        operation = str(uuid4()); result = self.editor.save(request, operation)
        self.assertEqual(result, self.editor.save(request, operation))
        after = git.snapshot(result['commit_id']); path = f'artifacts/{self.artifact}/content.md'
        self.assertEqual({path}, {p for p in before if before[p] != after[p]})
        self.assertEqual(before[path].replace(model['body'].encode(), request['body'].encode(), 1), after[path])
        with self.assertRaises(ValidationError): self.editor.save(request | {'body': request['body']+'\n'}, operation)

    def test_invalid_scope_ids_dependencies_hierarchy_and_stale_revision_do_not_write(self):
        model = self.opened(); before = Projects(self.node).repository(self.project).snapshot(self.head)
        for changes in [dict(fragment_sha256='0'*64), dict(expected_head='0'*40),
                        dict(body=model['body'].replace('TASK-01', 'TASK-99')),
                        dict(body=model['body']+'    - [ ] [TASK-03] Injected\r\n      - type: task\r\n'),
                        dict(body=model['body']+'      - depends_on: TASK-02\r\n'),
                        dict(body=model['body'].replace('type: task', 'type: batch')),
                        dict(body=model['body']+'# Unrelated heading\r\n'),
                        dict(body=model['body'].rstrip()), dict(body='\0')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.editor.save(self.request(model, **changes), str(uuid4()))
        git = Projects(self.node).repository(self.project)
        self.assertEqual(self.head, git.head()); self.assertEqual(before, git.snapshot(self.head))
        with self.assertRaises(ValueError): self.opened('TASK-99')
        with self.assertRaises(ValueError): self.editor.open(self.project, str(uuid4()), 'TASK-01', self.head)

    def test_writer_recovery_at_prepare_files_commit_and_index_replays_exactly_once(self):
        for stage in ('prepared', 'files-applied', 'ref-updated', 'indexed', 'completed'):
            model = self.opened(); request = self.request(model, body=model['body'].replace('První', stage))
            # Each iteration must have a real change.
            request['body'] = request['body'].replace('type: task', 'type: task\r\n      - '+stage)
            operation = str(uuid4())
            def stop(current):
                if current == stage: raise RuntimeError('power loss')
            with self.subTest(stage=stage), self.assertRaises(RuntimeError):
                self.editor.save(request, operation, checkpoint=stop)
            result = self.editor.save(request, operation)
            self.assertEqual(result, self.editor.save(request, operation))
            git = Projects(self.node).repository(self.project)
            self.assertEqual('1', git.run('rev-list', '--count', self.head+'..'+result['commit_id']).stdout.strip())
            self.head = result['commit_id']
            self.assertEqual(request['body'], self.opened()['body'])
            self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])

    def test_item_in_referenced_definition_document_preserves_main_roadmap(self):
        external = str(uuid4())
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=external,
            base_head=self.head, title='Definitions', new=True,
            body='<!-- fpw-plan-document: definitions/v1 -->\n- [ ] [TASK-EXT] External\n  - type: task\n'), str(uuid4()))['commit_id']
        root = ('<!-- fpw-plan-profile: software-development/v1 -->\n'
                '- [ ] [MILESTONE-01] Milník\n  - type: milestone\n'
                f'  - [ ] [BATCH-01] [Dávka](artifacts/{external}/content.md)\n    - type: batch\n')
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Roadmapa', new=False, body=root), str(uuid4()))['commit_id']
        git = Projects(self.node).repository(self.project); before = git.snapshot(self.head)
        model = self.editor.open(self.project, external, 'TASK-EXT', self.head)
        self.assertEqual('BATCH-01', model['parent_id'])
        result = self.editor.save(self.request(model, body=model['body'].replace('External', 'Edited')), str(uuid4()))
        after = git.snapshot(result['commit_id'])
        self.assertEqual({f'artifacts/{external}/content.md'}, {p for p in before if before[p] != after[p]})

    def test_frontmatter_bytes_and_neighboring_text_are_preserved(self):
        import yaml
        git = Projects(self.node).repository(self.project); files = git.snapshot(self.head)
        sidecar = f'artifacts/{self.artifact}/metadata.json'; path = f'artifacts/{self.artifact}/content.md'
        metadata = json.loads(files[sidecar])
        metadata.pop('file')
        prefix = ('---\n# Preserve YAML comment and ordering\n'+yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)+'---\n').encode()
        changes = {sidecar: None, path: prefix+files[path]}
        workspace = self.editor.projects.workspace(self.project)
        self.head = workspace.transact(str(uuid4()), {'fixture':'frontmatter'},
            lambda ws: (changes, 'Fixture', 'fixture@local.invalid', 'Frontmatter fixture'), expected_head=self.head)['commit_id']
        model = self.opened(); body = model['body'].replace('První', 'Edited')
        result = self.editor.save(self.request(model, body=body), str(uuid4()))
        self.assertEqual(changes[path].replace(model['body'].encode(), body.encode(), 1), git.snapshot(result['commit_id'])[path])

    def test_authenticated_http_open_save_rejects_filesystem_fields(self):
        from spikes.desktop_ui import DesktopHandler
        from spikes.local_api import running_api
        from tests.test_local_api import LocalAPITests
        driver = LocalAPITests()
        request = dict(project_id=self.project, artifact_id=self.artifact, task_id='TASK-01', expected_head=self.head)
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            path = '/v1/artifacts/editor/plan-item/open'
            response = driver.request(server, path=path, body=json.dumps(request).encode())
            self.assertTrue(response.startswith(b'HTTP/1.0 200'), response)
            model = json.loads(response.split(b'\r\n\r\n', 1)[1])
            self.assertNotIn('TASK-02', model['body'])
            driver.rejected(server, path=path, body=json.dumps(request).encode(), headers={'Authorization': None})
            driver.rejected(server, path=path, body=json.dumps(request | {'path': '/etc/passwd'}).encode())
            save = dict(operation_id=str(uuid4()), item=self.request(model, body=model['body'].replace('První', 'HTTP')))
            response = driver.request(server, path='/v1/artifacts/editor/plan-item/save', body=json.dumps(save).encode())
            self.assertTrue(response.startswith(b'HTTP/1.0 200'), response)

    def test_network_privacy_rejects_open_and_save_before_writing(self):
        self.head = self.artifacts.save(dict(project_id=self.project, artifact_id=str(uuid4()),
            base_head=self.head, title='Private', body='Local data', new=True),
            str(uuid4()), privacy='local-only')['commit_id']
        model = self.opened(); network = PlanItems(self.node, network=True)
        with self.assertRaisesRegex(ValueError, 'local-only'):
            network.open(self.project, self.artifact, 'TASK-01', self.head)
        with self.assertRaisesRegex(ValueError, 'local-only'):
            network.save(self.request(model, body=model['body'].replace('První', 'Denied')), str(uuid4()))
        self.assertEqual(self.head, Projects(self.node).repository(self.project).head())


class PlanStructureTests(unittest.TestCase):
    def setUp(self):
        artifact_tests.ArtifactActionTests.setUp(self)
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Roadmapa', body=BODY, new=False), str(uuid4()))['commit_id']
        self.editor = PlanItems(self.node)
        self.git = Projects(self.node).repository(self.project)
        self.path = f'artifacts/{self.artifact}/content.md'

    def create(self, parent='BATCH-01', operation=None, **changes):
        request = dict(project_id=self.project, parent_id=parent, expected_head=self.head, task_id=None,
                       title='Nová', description='', depends_on=[]) | changes
        return self.editor.create(request, operation or str(uuid4()))

    def nodes(self, head):
        return {n['id']: n for n in self.editor.plan(self.git.snapshot(head), self.project, head)[0]['nodes']}

    def text(self, head):
        return self.git.snapshot(head)[self.path].decode()

    def rejected(self, call, *args, **kwargs):
        before = self.git.snapshot(self.head)
        with self.assertRaises(ValueError):
            call(*args, **kwargs)
        self.assertEqual(self.head, self.git.head()); self.assertEqual(before, self.git.snapshot(self.head))

    def test_create_appends_last_child_and_preserves_every_other_byte(self):
        result = self.create(title='Třetí', description='Řádek jedna\n\n Řádek dva ', depends_on=['TASK-02'], task_id='TASK-03')
        self.assertEqual('TASK-03', result['task_id'])
        block = ('    - [ ] [TASK-03] Třetí\n      - type: task\n      - depends_on: TASK-02\n'
                 '      - Řádek jedna\n      - Řádek dva\n')
        marker = '      - depends_on: TASK-01\n'
        self.assertEqual(BODY.replace(marker, marker+block), self.text(result['commit_id']))
        node = self.nodes(result['commit_id'])['TASK-03']
        self.assertEqual(('BATCH-01', 'task', ['TASK-02'], 'Řádek jedna\nŘádek dva'),
                         (node['parent_id'], node['type'], node['depends_on'], node['description']))

    def test_create_uses_profile_type_for_each_level_and_replay_keeps_generated_id(self):
        operation = str(uuid4()); request = dict(project_id=self.project, parent_id='MILESTONE-01',
            expected_head=self.head, task_id=None, title='Dávka 2', description='', depends_on=[])
        batch = self.editor.create(request, operation)
        self.assertEqual(batch, self.editor.create(request, operation))
        self.assertEqual('1', self.git.run('rev-list', '--count', self.head+'..'+batch['commit_id']).stdout.strip())
        nodes = self.nodes(batch['commit_id']); self.assertEqual('batch', nodes[batch['task_id']]['type'])
        self.head = batch['commit_id']
        task = self.create(batch['task_id'])
        self.assertEqual((batch['task_id'], 'task'), (lambda n: (n['parent_id'], n['type']))(self.nodes(task['commit_id'])[task['task_id']]))
        self.head = task['commit_id']
        root = self.create(None, title='Milník 2')
        node = self.nodes(root['commit_id'])[root['task_id']]
        self.assertEqual((None, 'milestone'), (node['parent_id'], node['type']))
        self.assertTrue(self.text(root['commit_id']).endswith('# Konec — mimo položky\n'))
        self.assertLess(self.text(root['commit_id']).index(root['task_id']), self.text(root['commit_id']).index('# Konec'))

    def test_create_rejects_invalid_requests_without_writing(self):
        for changes in [dict(parent='TASK-01'), dict(parent='UNKNOWN-01'), dict(task_id='TASK-01'), dict(task_id='bad id'),
                        dict(title=''), dict(title='a\nb'), dict(title='x'*501), dict(title=f'[Soubor](artifacts/{self.artifact}/content.md)'),
                        dict(depends_on=['UNKNOWN-01']), dict(depends_on=['TASK-01', 'TASK-01']), dict(depends_on='TASK-01'),
                        dict(description='depends_on: TASK-01'), dict(description='[ ] podmínka'), dict(description='type: batch'),
                        dict(description='[ ] [TASK-09] Vložený uzel'), dict(expected_head='0'*40)]:
            with self.subTest(changes=changes):
                self.rejected(self.create, **changes)

    def test_create_under_completed_parent_is_rejected(self):
        body = BODY.replace('- [ ] [BATCH-01]', '- [x] [BATCH-01]')
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact, base_head=self.head,
                                           title='Roadmapa', body=body, new=False), str(uuid4()))['commit_id']
        self.rejected(self.create)

    def test_create_in_linked_batch_writes_definition_file_and_crlf(self):
        external = str(uuid4())
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=external, base_head=self.head,
            title='Definitions', new=True,
            body='<!-- fpw-plan-document: definitions/v1 -->\r\n- [ ] [TASK-EXT] External\r\n  - type: task'), str(uuid4()))['commit_id']
        root = ('<!-- fpw-plan-profile: software-development/v1 -->\n- [ ] [MILESTONE-01] Milník\n  - type: milestone\n'
                f'  - [ ] [BATCH-01] [Dávka](artifacts/{external}/content.md)\n    - type: batch\n')
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact, base_head=self.head,
                                           title='Roadmapa', new=False, body=root), str(uuid4()))['commit_id']
        before = self.git.snapshot(self.head)
        result = self.create(task_id='TASK-NEW')
        after = self.git.snapshot(result['commit_id']); path = f'artifacts/{external}/content.md'
        self.assertEqual({path}, {p for p in before if before[p] != after[p]})
        self.assertEqual(before[path] + b'\r\n- [ ] [TASK-NEW] Nov\xc3\xa1\r\n  - type: task', after[path])
        self.assertEqual('BATCH-01', self.nodes(result['commit_id'])['TASK-NEW']['parent_id'])
        self.head = result['commit_id']
        self.assertIn('samostatný soubor', self.editor.delete_preview(self.project, 'BATCH-01', self.head)['blocker'])
        self.rejected(self.editor.delete, self.delete_request('BATCH-01'), str(uuid4()))

    def dependencies(self, task, targets):
        return self.editor.set_dependencies(dict(project_id=self.project, task_id=task, expected_head=self.head, depends_on=targets), str(uuid4()))

    def test_dependencies_are_added_changed_and_removed_in_own_lines_only(self):
        added = self.dependencies('TASK-01', ['BATCH-01'])
        self.assertEqual(BODY.replace('[TASK-01] První\n      - type: task\n', '[TASK-01] První\n      - type: task\n      - depends_on: BATCH-01\n'),
                         self.text(added['commit_id']))
        self.head = added['commit_id']
        removed = self.dependencies('TASK-02', [])
        self.assertEqual(self.text(self.head).replace('      - depends_on: TASK-01\n', ''), self.text(removed['commit_id']))
        self.assertEqual([], self.nodes(removed['commit_id'])['TASK-02']['depends_on'])

    def test_dependency_aliases_and_multiple_lines_collapse_preserving_other_text(self):
        body = BODY.replace('      - depends_on: TASK-01\n', '      - závisí na: TASK-01\n      - Text\n      - blocked_by: BATCH-01\n')
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact, base_head=self.head,
                                           title='Roadmapa', body=body, new=False), str(uuid4()))['commit_id']
        result = self.dependencies('TASK-02', ['TASK-01', 'MILESTONE-01'])
        self.assertEqual(BODY.replace('      - depends_on: TASK-01\n', '      - závisí na: TASK-01, MILESTONE-01\n      - Text\n'), self.text(result['commit_id']))

    def test_dependency_errors_do_not_write(self):
        for task, targets in [('TASK-01', ['TASK-02']), ('TASK-01', ['TASK-01']), ('TASK-01', ['UNKNOWN-01']),
                              ('TASK-02', ['TASK-01']), ('UNKNOWN-01', []), ('TASK-01', 'TASK-02')]:
            with self.subTest(task=task, targets=targets):
                self.rejected(self.dependencies, task, targets)

    def test_dependency_declared_by_other_item_blocks_relation_is_not_silently_dropped(self):
        body = BODY.replace('      - depends_on: TASK-01\n', '').replace('- [ ] [TASK-01] První\n      - type: task\n', '- [ ] [TASK-01] První\n      - type: task\n      - blocks: TASK-02\n')
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact, base_head=self.head,
                                           title='Roadmapa', body=body, new=False), str(uuid4()))['commit_id']
        with self.assertRaisesRegex(ValueError, 'blocks'):
            self.dependencies('TASK-02', [])
        result = self.dependencies('TASK-02', ['TASK-01', 'BATCH-01'])
        self.assertIn('      - depends_on: BATCH-01\n', self.text(result['commit_id']))
        self.assertNotIn('TASK-01, BATCH-01', self.text(result['commit_id']))

    def delete_request(self, task):
        return dict(project_id=self.project, task_id=task, expected_head=self.head)

    def test_delete_preview_lists_subtree_and_blocks_dependents_without_writing(self):
        preview = self.editor.delete_preview(self.project, 'TASK-01', self.head)
        self.assertEqual((['TASK-01'], ['TASK-02']), ([n['id'] for n in preview['removed']], preview['dependents']))
        self.assertIn('TASK-02', preview['blocker'])
        self.rejected(self.editor.delete, self.delete_request('TASK-01'), str(uuid4()))
        tree = self.editor.delete_preview(self.project, 'MILESTONE-01', self.head)
        self.assertEqual(['MILESTONE-01', 'BATCH-01', 'TASK-01', 'TASK-02'], [n['id'] for n in tree['removed']])
        self.assertIn('neobsahuje', tree['blocker'])
        self.rejected(self.editor.delete, self.delete_request('MILESTONE-01'), str(uuid4()))
        with self.assertRaises(ValueError): self.editor.delete_preview(self.project, 'UNKNOWN-01', self.head)

    def test_delete_removes_exact_block_or_nested_subtree_and_stays_in_history(self):
        result = self.editor.delete(self.delete_request('TASK-02'), str(uuid4()))
        self.assertEqual(BODY.replace('    - [ ] [TASK-02] Druhý\n      - type: task\n      - depends_on: TASK-01\n', ''), self.text(result['commit_id']))
        self.assertIn(b'TASK-02', self.git.snapshot(self.head)[self.path])
        self.head = result['commit_id']
        second = self.create('MILESTONE-01', task_id='BATCH-02', title='Zůstává')
        self.head = second['commit_id']
        third = self.editor.delete(self.delete_request('BATCH-01'), str(uuid4()))
        self.assertEqual({'MILESTONE-01', 'BATCH-02'}, set(self.nodes(third['commit_id'])))
        text = self.text(third['commit_id'])
        self.assertIn('Pouze příklad', text); self.assertIn('# Konec', text); self.assertNotIn('neznámý komentář', text)

    def test_delete_blocked_by_declared_blocks_and_subgraph_reference(self):
        body = BODY.replace('      - depends_on: TASK-01\n', '').replace('- [ ] [TASK-01] První\n      - type: task\n', '- [ ] [TASK-01] První\n      - type: task\n      - blocks: TASK-02\n')
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact, base_head=self.head,
                                           title='Roadmapa', body=body, new=False), str(uuid4()))['commit_id']
        self.assertEqual(['TASK-02'], self.editor.delete_preview(self.project, 'TASK-01', self.head)['dependents'])
        self.head = self.artifacts.save(dict(project_id=self.project, artifact_id=str(uuid4()), base_head=self.head,
            title='Výřez', body='- [ ] [TASK-02] výběr\n', new=True, metadata=dict(tags=['plan-subgraph'])), str(uuid4()))['commit_id']
        self.assertIn('TASK-02', self.editor.delete_preview(self.project, 'TASK-02', self.head)['blocker'])
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact, base_head=self.head,
                                           title='Roadmapa', body=BODY, new=False), str(uuid4()))['commit_id']
        preview = self.editor.delete_preview(self.project, 'TASK-02', self.head)
        self.assertEqual([], preview['dependents']); self.assertIn('Výřez', preview['blocker'])
        self.rejected(self.editor.delete, self.delete_request('TASK-02'), str(uuid4()))

    def test_writer_recovery_replays_every_structural_change_exactly_once(self):
        calls = {
            'create': lambda r, o, c: self.editor.create(dict(project_id=self.project, parent_id='BATCH-01', expected_head=self.head,
                task_id=None, title=r, description='', depends_on=[]), o, checkpoint=c),
            'dependencies': lambda r, o, c: self.editor.set_dependencies(dict(project_id=self.project, task_id='TASK-01',
                expected_head=self.head, depends_on=['MILESTONE-01'] if 'MILESTONE-01' not in self.nodes(self.head)['TASK-01']['depends_on'] else []), o, checkpoint=c),
        }
        for name, call in calls.items():
            for stage in ('prepared', 'files-applied', 'ref-updated', 'indexed', 'completed'):
                operation = str(uuid4()); head = self.head
                def stop(current):
                    if current == stage: raise RuntimeError('power loss')
                with self.subTest(name=name, stage=stage):
                    wanted = self.nodes(head)['TASK-01']['depends_on']
                    target = [] if wanted else ['MILESTONE-01']
                    run = (lambda c: call(stage, operation, c)) if name == 'create' else (lambda c: self.editor.set_dependencies(
                        dict(project_id=self.project, task_id='TASK-01', expected_head=head, depends_on=target), operation, checkpoint=c))
                    with self.assertRaises(RuntimeError): run(stop)
                    result = run(lambda current: None)
                    self.assertEqual(result, run(lambda current: None))
                    self.assertEqual('1', self.git.run('rev-list', '--count', head+'..'+result['commit_id']).stdout.strip())
                    self.head = result['commit_id']
                    self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])
        for stage in ('prepared', 'files-applied', 'ref-updated', 'indexed', 'completed'):
            created = self.create(title='Ke smazání '+stage, task_id='DROP-'+stage.upper().replace('-', ''))
            self.head = created['commit_id']; head = self.head; operation = str(uuid4())
            request = self.delete_request(created['task_id'])
            def stop(current):
                if current == stage: raise RuntimeError('power loss')
            with self.subTest(delete=stage):
                with self.assertRaises(RuntimeError): self.editor.delete(request, operation, checkpoint=stop)
                result = self.editor.delete(request, operation)
                self.assertEqual(result, self.editor.delete(request, operation))
                self.assertEqual('1', self.git.run('rev-list', '--count', head+'..'+result['commit_id']).stdout.strip())
                self.assertNotIn(created['task_id'], self.nodes(result['commit_id']))
                self.head = result['commit_id']

    def test_authenticated_http_routes_and_network_privacy(self):
        from spikes.desktop_ui import DesktopHandler
        from spikes.local_api import running_api
        from tests.test_local_api import LocalAPITests
        driver = LocalAPITests(); base = '/v1/artifacts/editor/plan-item/'
        def post(server, path, value):
            response = driver.request(server, path=base+path, body=json.dumps(value).encode())
            return response.split(b' ', 2)[1], json.loads(response.split(b'\r\n\r\n', 1)[1])
        item = dict(project_id=self.project, parent_id='BATCH-01', expected_head=self.head, task_id='TASK-03',
                    title='HTTP', description='', depends_on=[])
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            status, created = post(server, 'create', dict(operation_id=str(uuid4()), item=item)); self.assertEqual(b'200', status, created)
            status, error = post(server, 'create', dict(operation_id=str(uuid4()), item=item | {'expected_head': created['commit_id'], 'task_id': 'TASK-01'}))
            self.assertEqual(b'422', status); self.assertIn('TASK-01', error['error'])
            status, changed = post(server, 'dependencies', dict(operation_id=str(uuid4()), item=dict(project_id=self.project, task_id='TASK-03', expected_head=created['commit_id'], depends_on=['TASK-02'])))
            self.assertEqual(b'200', status, changed)
            request = dict(project_id=self.project, task_id='TASK-03', expected_head=changed['commit_id'])
            status, preview = post(server, 'delete/preview', request); self.assertEqual(b'200', status, preview)
            self.assertIsNone(preview['blocker'])
            driver.rejected(server, path=base+'delete/preview', body=json.dumps(request | {'path': '/etc/passwd'}).encode())
            driver.rejected(server, path=base+'delete', body=json.dumps(request).encode(), headers={'Authorization': None})
            status, deleted = post(server, 'delete', dict(operation_id=str(uuid4()), item=request)); self.assertEqual(b'200', status, deleted)
        self.head = deleted['commit_id']
        self.head = self.artifacts.save(dict(project_id=self.project, artifact_id=str(uuid4()), base_head=self.head,
            title='Private', body='Local data', new=True), str(uuid4()), privacy='local-only')['commit_id']
        network = PlanItems(self.node, network=True)
        for call, args in [(network.delete_preview, (self.project, 'TASK-02', self.head)),
                           (network.delete, (self.delete_request('TASK-02'), str(uuid4()))),
                           (network.set_dependencies, (dict(project_id=self.project, task_id='TASK-02', expected_head=self.head, depends_on=[]), str(uuid4()))),
                           (network.create, (dict(project_id=self.project, parent_id=None, expected_head=self.head, task_id=None, title='x', description='', depends_on=[]), str(uuid4())))]:
            with self.assertRaisesRegex(ValueError, 'local-only'): call(*args)
        self.assertEqual(self.head, self.git.head())

    @unittest.skipUnless(shutil.which('node'), 'Node required for plan controls')
    def test_plan_controls_keep_operation_on_lost_reply_and_block_queued_deletion(self):
        from spikes.desktop_ui import JS
        controls = JS[JS.index('let planChangeAttempt=null;'):JS.index('function openPlanItemForm(')]
        deletion = JS[JS.index('async function openPlanDeletion('):JS.index('function appendPlanItemActions(')]
        harness = r'''
const assert=require('node:assert/strict');
const node=tag=>({tag,children:[],textContent:'',disabled:false,replaceChildren(...c){this.children=c;},append(...c){this.children.push(...c);},setAttribute(){},addEventListener(n,f){this.on=f;}});
const document={createElement:node};
let activeProject={id:'p',head:'h',readOnly:false},taskQueueView={task_ids:[]},taskPlanProjection={nodes:[{id:'BATCH-01',title:'b'}]};
let failed=true,calls=[],shown=[],count=0;
const crypto={randomUUID:()=>'op-'+(++count)};
const preview={expected_head:'h',removed:[{id:'TASK-01',title:'t',checked:true}],blocker:null};
async function projectRequest(path,request){calls.push({path,request});if(path.endsWith('/preview'))return preview;if(failed)throw Error('unknown');return {project_id:'p',commit_id:'new',task_id:'TASK-01'};}
async function openRegisteredProject(){}async function openTaskPlan(){return true;}function showTaskPlanDetail(item){shown.push(item.id);}
'''
        checks = r'''
(async()=>{
const status=node('p'),item={project_id:'p',task_id:'X'};
assert.equal(await submitPlanChange('create',item,status,r=>r.task_id),false);const first=calls.at(-1).request.operation_id;assert.match(status.textContent,/stejnou operaci/);
assert.equal(await submitPlanChange('create',item,status,r=>r.task_id),false);assert.equal(calls.at(-1).request.operation_id,first);
await submitPlanChange('create',{...item,task_id:'Y'},status,r=>r.task_id);const other=calls.at(-1).request.operation_id;assert.notEqual(other,first);
activeProject.readOnly=true;const before=calls.length;assert.equal(await submitPlanChange('create',item,status,r=>r.task_id),false);assert.equal(calls.length,before);activeProject.readOnly=false;
failed=false;
const host=node('div');taskQueueView={task_ids:['TASK-01']};await openPlanDeletion(host,{id:'TASK-01',parent_id:'BATCH-01'});
let confirm=host.children.find(c=>c.tag==='button');assert.equal(confirm.disabled,true);assert.match(host.children.at(-1).textContent,/fronty/);
taskQueueView={task_ids:[]};await openPlanDeletion(host,{id:'TASK-01',parent_id:'BATCH-01'});confirm=host.children.find(c=>c.tag==='button');assert.equal(confirm.disabled,false);
await confirm.on();assert(calls.at(-1).path.endsWith('/plan-item/delete'));assert.deepEqual(shown,['BATCH-01']);assert.equal(activeProject.head,'new');
preview.blocker='Na položce závisí: Z';await openPlanDeletion(host,{id:'TASK-01',parent_id:null});assert.equal(host.children.find(c=>c.tag==='button').disabled,true);
})().catch(error=>{console.error(error);process.exit(1);});
'''
        result = subprocess.run(['node', '-e', harness+controls+deletion+checks], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)


class SpanTests(unittest.TestCase):
    def test_fenced_examples_and_child_nodes_do_not_change_physical_offsets(self):
        start, end = item_span(BODY, 'TASK-01')
        self.assertTrue(BODY[start:end].startswith('    - [ ] [TASK-01] První\n'))
        self.assertTrue(BODY[end:].startswith('\n    - [ ] [TASK-02]'))
        with self.assertRaises(ValueError): item_span(BODY, 'UNKNOWN-01')

    def test_subtree_ends_before_lower_indent_and_keeps_fenced_lines_inside(self):
        start, end = subtree_span(BODY, 'BATCH-01')
        self.assertTrue(BODY[start:end].startswith('  - [ ] [BATCH-01]'))
        self.assertTrue(BODY[start:end].endswith('depends_on: TASK-01\n')); self.assertTrue(BODY[end:].startswith('\n# Konec'))
        body = '- [ ] [A-1] A\n  ```\ntext at root\n  ```\n  - note\n- [ ] [B-1] B\n'
        self.assertEqual(body.index('- [ ] [B-1]'), subtree_span(body, 'A-1')[1])
        self.assertEqual(len(body), subtree_span(body, 'B-1')[1])

    @unittest.skipUnless(shutil.which('node'), 'Node required for editor controls')
    def test_scoped_editor_preserves_dirty_guard_draft_and_operation_on_lost_reply(self):
        from spikes.desktop_ui import JS
        fill = JS[JS.index('function fillArtifactEditor('):JS.index('async function closeArtifactEditor(')]
        controls = JS[JS.index('async function openPlanItemEditor('):JS.index('async function openNewArtifactEditor(')]
        harness = r'''
const assert=require('node:assert/strict');
const field=()=>({value:'',disabled:false,readOnly:false,label:{hidden:false},closest(){return this.label;},focus(){}});
const elements=new Map(),button={disabled:false};
const document={querySelector(id){if(!elements.has(id))elements.set(id,{textContent:''});return elements.get(id);}};
const artifactEditorForm={elements:Object.fromEntries(['body','title','filename','description','tags'].map(n=>[n,field()])),querySelector:()=>button};
let activeProject={id:'p',head:'h',mainTodoId:'main',readOnly:false},artifactEditorItem=null,artifactEditorAttempt=null,artifactEditorBaseline=null,artifactEditorDirty=false;
let allow=false,failed=true,calls=[],filled=[],artifactEditorView={hidden:true},taskPlanProjection={nodes:[]};
const artifactEditorStatus={textContent:''},artifactRawWidget={configure:()=>Promise.resolve()};
const crypto={randomUUID:()=>String(calls.length)};
function resetTaskFileEditEditor(){}function artifactEditorState(){return artifactEditorForm.elements.body.value;}function configureTaskPlanEditor(){}
function hideArtifactDeletion(){}function showWorkspacePage(v){v.hidden=false;}async function canLeaveWorkspaceEditors(){return allow;}
const model={project_id:'p',artifact_id:'a',task_id:'TASK-01',expected_head:'h',fragment_sha256:'digest',body:'one item',title:'Title'};
async function projectRequest(path,request){calls.push({path,request});if(path.endsWith('/open'))return model;if(failed)throw Error('unknown');return {project_id:'p',commit_id:'new'};}
'''
        checks = r'''
(async()=>{
const task={id:'TASK-01',source:{artifact_id:'a'}};
await openPlanItemEditor(task);assert.equal(calls.length,0,'dirty guard cancellation');
allow=true;await openPlanItemEditor(task);assert.equal(calls.length,1);assert.equal(artifactEditorForm.elements.body.value,'one item');
assert.equal(artifactEditorForm.elements.title.disabled,true);assert.equal(artifactEditorForm.elements.title.label.hidden,true);
artifactEditorForm.elements.body.value='draft';artifactEditorDirty=true;
assert.equal(await savePlanItemEditor(false),false);const attempt=artifactEditorAttempt;
assert.equal(artifactEditorForm.elements.body.value,'draft');assert(artifactEditorDirty);assert.equal(button.disabled,false);assert.equal(artifactEditorForm.elements.body.readOnly,false);
assert.equal(await savePlanItemEditor(false),false);assert.equal(artifactEditorAttempt,attempt);assert.equal(calls.at(-1).request.operation_id,attempt.operation_id);
failed=false;assert.equal(await savePlanItemEditor(false),true);assert.equal(activeProject.head,'new');assert.equal(artifactEditorDirty,false);
fillArtifactEditor({title:'Whole document',body:'content'});assert.equal(artifactEditorForm.elements.title.disabled,false);assert.equal(artifactEditorForm.elements.title.label.hidden,false);
})().catch(error=>{console.error(error);process.exit(1);});
'''
        result = subprocess.run(['node', '-e', harness+fill+controls+checks], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
