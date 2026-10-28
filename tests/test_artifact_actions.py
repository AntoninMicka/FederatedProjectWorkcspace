# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from spikes.artifact_actions import ArtifactActions
from spikes.artifacts import Artifacts, main_todo_id
from spikes.metadata import ValidationError
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import StaleIndex


class ArtifactActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.node = self.base/'node.json'
        self.project = ProjectCreation(self.node).create('Project', str(self.base/'project'), str(uuid4()))['id']
        self.artifact = main_todo_id(self.project); view = Projects(self.node).open(self.project)
        self.artifacts = Artifacts(self.node)
        self.head = self.artifacts.save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=view['commit_id'], title='Tasks', body='- [ ] One\n', new=True), str(uuid4()))['commit_id']
        self.actions = ArtifactActions(self.node)

    def test_open_save_retry_preview_and_confirm_delete(self):
        opened = self.actions.open(self.project, self.artifact, self.head)
        self.assertEqual(opened['document']['body'], '- [ ] One\n')
        operation = str(uuid4())
        request = dict(project_id=self.project, artifact_id=self.artifact, base_head=self.head,
            title='Renamed', body='- [x] One\n', new=False, filename='renamed.md',
            metadata={'description':'Done', 'tags':['todo']})
        first = self.actions.save(request, operation); second = self.actions.save(request, operation)
        self.assertEqual(first, second)
        preview = self.actions.deletion_preview(self.project, self.artifact, first['commit_id'])
        with self.assertRaisesRegex(ValidationError, 'preview changed'):
            self.actions.delete(self.project, self.artifact, first['commit_id'], '0'*64, str(uuid4()))
        delete_operation = str(uuid4())
        deleted = self.actions.delete(self.project, self.artifact, first['commit_id'],
                                      preview['preview_sha256'], delete_operation)
        self.assertEqual(deleted, self.actions.delete(self.project, self.artifact,
                         first['commit_id'], preview['preview_sha256'], delete_operation))
        self.assertEqual(Projects(self.node).open(self.project)['commit_id'], deleted['commit_id'])
        self.assertEqual(Projects(self.node).open(self.project)['artifacts'], [])

    def test_create_validates_current_project_and_reuses_receipt(self):
        artifact, operation = str(uuid4()), str(uuid4())
        request = dict(project_id=self.project, artifact_id=artifact, base_head=self.head,
            title='New document', body='# New\n', new=True, filename='new.md',
            metadata={'description':'Created in shared editor', 'tags':['shared']})
        first = self.actions.save(request, operation)
        self.assertEqual(first, self.actions.save(request, operation))
        opened = self.actions.open(self.project, artifact, first['commit_id'])
        self.assertEqual(opened['document']['body'], '# New\n')

    def test_create_rejects_stale_head_before_preparing_write(self):
        request = dict(project_id=self.project, artifact_id=str(uuid4()),
            base_head='0' * 40, title='Stale', body='text\n', new=True)
        with self.assertRaisesRegex(ValidationError, 'changed'):
            self.actions.save(request, str(uuid4()))
        self.assertEqual(Projects(self.node).open(self.project)['commit_id'], self.head)

    def test_task_plan_draft_validation_is_read_only_and_revision_pinned(self):
        body = '''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - [ ] [BATCH-01] Dávka
    - type: batch
    - [ ] [TASK-01] Úkol
      - type: task
'''
        head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Tasks', body=body, new=False),
            str(uuid4()))['commit_id']
        before = Projects(self.node).open(self.project)['commit_id']
        result = self.actions.validate_task_plan(
            self.project, self.artifact, head, body.replace('Úkol', 'Upravený úkol'))
        self.assertTrue(result['valid'])
        self.assertEqual(3, result['nodes'])
        self.assertEqual(before, Projects(self.node).open(self.project)['commit_id'])
        with self.assertRaisesRegex(ValidationError, 'Kořenový uzel'):
            self.actions.validate_task_plan(
                self.project, self.artifact, head,
                body.replace('type: milestone', 'type: task', 1))
        with self.assertRaises(StaleIndex):
            self.actions.validate_task_plan(self.project, self.artifact, '0' * 40, body)
