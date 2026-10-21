# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from spikes.project_creation import CreationConflict
from spikes.project_creation_actions import ProjectCreationActions
from spikes.projects import Projects


class ProjectCreationActionsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.node = self.root / 'state' / 'node.json'

    def request(self, title='Shared project', operation_id=None, capability=None,
                remember=False):
        return {'title': title, 'operation_id': operation_id or str(uuid4()),
                'location_capability': capability, 'remember_parent': remember}

    def test_default_preview_is_read_only_and_confirm_retry_has_one_receipt(self):
        projects_root = self.root / 'configured-projects'
        actions = ProjectCreationActions(self.node, projects_root=projects_root)
        request = self.request()
        plan = actions.preview(request)
        self.assertFalse(projects_root.exists())
        self.assertEqual(plan['target_label'], str(projects_root / ('projekt-' + request['operation_id'])))
        first = actions.confirm(plan)
        second = actions.confirm(plan)
        self.assertEqual(first, second)
        self.assertEqual([first['id']], [item['id'] for item in Projects(self.node).list()])

    def test_preview_digest_and_target_label_are_bound_to_exact_intent(self):
        actions = ProjectCreationActions(self.node, projects_root=self.root / 'projects')
        plan = actions.preview(self.request())
        for key, value in [('title', 'Changed'), ('target_label', '/tmp/elsewhere'),
                           ('preview_sha256', '0' * 64)]:
            changed = dict(plan, **{key: value})
            with self.subTest(key=key), self.assertRaises(CreationConflict):
                actions.confirm(changed)
        self.assertFalse(self.node.exists())

    def test_confirm_requires_a_plan_issued_by_same_backend_instance(self):
        operation = str(uuid4())
        first = ProjectCreationActions(self.node, projects_root=self.root / 'projects')
        plan = first.preview(self.request(operation_id=operation))
        second = ProjectCreationActions(self.node, projects_root=self.root / 'projects')
        with self.assertRaises(CreationConflict):
            second.confirm(plan)
        self.assertFalse(self.node.exists())

    def test_web_adapter_rejects_location_capabilities_and_remember_parent(self):
        actions = ProjectCreationActions(self.node, projects_root=self.root / 'projects')
        with self.assertRaises(CreationConflict):
            actions.preview(self.request(capability=str(uuid4())))
        with self.assertRaises(CreationConflict):
            actions.preview(self.request(remember=True))

    def test_desktop_picker_capability_is_exact_and_operation_scoped(self):
        target = self.root / 'chosen-empty'; target.mkdir(mode=0o700); target.chmod(0o700)
        actions = ProjectCreationActions(self.node, desktop_locations=True)
        operation = str(uuid4())
        selected = actions.register_location(target, operation)
        plan = actions.preview(self.request(operation_id=operation,
            capability=selected['location_capability'], remember=True))
        self.assertEqual(plan['target_label'], str(target))
        receipt = actions.confirm(plan)
        self.assertEqual(receipt, actions.confirm(plan))
        from spikes.configuration import parse_node, read_config
        node = parse_node(read_config(self.node), location=self.node)
        self.assertEqual(target, Path(node['projects'][0]['root']))
        with self.assertRaises(CreationConflict):
            actions.preview(self.request(capability=selected['location_capability']))


if __name__ == '__main__':
    unittest.main()
