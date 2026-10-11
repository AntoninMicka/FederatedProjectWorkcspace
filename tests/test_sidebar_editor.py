# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""The sidebar opens the shared document/TODO editor in both runtimes."""
import unittest

from spikes.desktop_ui import HTML, JS


class SidebarEditorTests(unittest.TestCase):
    def test_shared_sidebar_actions_and_dirty_draft_guard(self):
        self.assertIn('id="new-document"', HTML)
        self.assertIn('id="create-main-todo"', HTML)
        self.assertIn("querySelector('#new-document').addEventListener", JS)
        self.assertIn('function openMainTodoEditor()', JS)
        self.assertIn("todo ? 'Upravit seznam úkolů' : 'Vytvořit seznam úkolů'", JS)
        self.assertIn("window.confirm('Zahodit rozepsané změny dokumentu?", JS)
        self.assertIn("window.addEventListener('beforeunload'", JS)
        self.assertIn('artifactEditorAttempt={signature,operation_id:crypto.randomUUID()', JS)
        self.assertNotIn("location.hash='create-main-todo'", JS)


if __name__ == '__main__':
    unittest.main()
