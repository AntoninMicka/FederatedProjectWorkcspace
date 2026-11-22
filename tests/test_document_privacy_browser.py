# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from uuid import uuid4
from tests.ui_flow_case import UiFlowCase, require_browser


@require_browser
class DocumentPrivacyBrowserTests(UiFlowCase):
    def test_whole_plan_raw_and_scoped_task_share_confirmed_source_file_privacy(self):
        from spikes.artifacts import Artifacts
        from spikes.projects import Projects
        from spikes.markdown_documents import main_todo_id
        from spikes.metadata import validate_snapshot
        from tests.test_plan_item_editor import BODY
        git = Projects(self.node).repository(self.project_id)
        target = main_todo_id(self.project_id)
        Artifacts(self.node).save(dict(project_id=self.project_id, artifact_id=target, base_head=git.head(),
            new=True, title='Plán', body=BODY), str(uuid4()))
        page = self.start(); self.open_project_chat()
        page.evaluate('openMainTodoEditor()'); page.wait_idle()
        page.click('#task-plan-mode-raw'); page.fill('#artifact-editor-privacy', 'confidential')
        before = git.head()
        page.evaluate("document.querySelector('#artifact-editor-form').requestSubmit()")
        page.wait(lambda:git.head()!=before, 'whole plan privacy save'); page.wait_idle()
        self.assertEqual(validate_snapshot(git.snapshot(git.head()))[target]['privacy'], 'confidential')
        page.evaluate("(async()=>{await openTaskPlan();await openPlanItemEditor(taskPlanProjection.nodes.find(n=>n.id==='TASK-01'));})()")
        page.wait_js("artifactEditorItem?.planItem?.task_id==='TASK-01'", 'scoped task editor'); page.wait_idle()
        self.assertEqual(page.evaluate("document.querySelector('#artifact-editor-privacy').value"), 'confidential')
        self.assertIn('celý zdrojový soubor', page.text('#artifact-editor-privacy-hint'))
        page.fill('#artifact-editor-privacy', 'project'); before = git.head()
        page.dialog_answers.append(False)
        page.evaluate("document.querySelector('#artifact-editor-form').requestSubmit()")
        page.wait_idle(); self.assertEqual(before, git.head())
        page.evaluate("document.querySelector('#artifact-editor-form').requestSubmit()")
        page.wait(lambda:git.head()!=before, 'scoped confirmed privacy save'); page.wait_idle()
        files = git.snapshot(git.head())
        self.assertEqual(validate_snapshot(files)[target]['privacy'], 'project')
        self.assertEqual(files[f'artifacts/{target}/content.md'].decode(), BODY)
        self.assert_no_page_errors()
