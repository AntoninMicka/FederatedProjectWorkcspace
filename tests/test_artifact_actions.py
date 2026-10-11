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
