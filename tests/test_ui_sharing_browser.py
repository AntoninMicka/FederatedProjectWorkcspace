# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""XREF-02-B in a real browser: share, attach in another project, open read-only."""
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.project_creation import ProjectCreation
from tests.ui_flow_case import UiFlowCase, require_browser


@require_browser
class SharingBrowserTests(UiFlowCase):
    def setUp(self):
        super().setUp()
        self.target = ProjectCreation(self.node).create(
            'Podprojekt', str(self.node.parent / 'target'), str(uuid4()))['id']
        artifacts = Artifacts(self.node); self.artifact = str(uuid4())
        head = artifacts.workspace(self.project_id).git.head()
        artifacts.save(dict(project_id=self.project_id, base_head=head, artifact_id=self.artifact,
                            title='Zadání podprojektu', body='# Zadání\n\nPostavit most.\n', new=True), str(uuid4()))

    def open(self, project_id):
        page = self.page
        page.evaluate(f"openRegisteredProject('{project_id}')")
        page.wait_js(f"activeProject?.id==='{project_id}'", 'project to open')
        page.wait_idle()

    def confirm_dialog(self, path):
        page = self.page
        page.wait_js("!document.querySelector('#sharing-confirm').hidden", 'reviewed preview')
        self.assertTrue(page.evaluate("document.querySelector('#sharing-confirm').disabled"))
        page.click('#sharing-approved'); page.click('#sharing-confirm')
        page.wait(lambda: self.requests(path), 'confirm')
        page.wait_js("document.querySelector('#sharing-status').textContent==='Uloženo.'", 'saved state')
        page.wait_idle()
        self.assertEqual(page.status(self.requests(path)[0]), 200)

    def test_share_attach_and_open_pinned_read_only_reference(self):
        page = self.start(configure_search=False)
        self.open(self.project_id)
        self.click_text('Sdílet do projektu', '#sidebar-artifact-list')
        page.wait_js("document.querySelector('#sharing-body input[name=sharing-target]')", 'target choices')
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#sharing-body input[name=sharing-target]')]"
                                       ".map(b=>b.parentElement.textContent)"), ['Podprojekt'])
        page.click('#sharing-body input[name=sharing-target]')
        page.fill('#sharing-reason', 'Zadání pro tým podprojektu')
        page.click('#sharing-primary')
        self.confirm_dialog('/v1/sharing/share/confirm')
        share = self.requests('/v1/sharing/share/preview')[0]['body']
        self.assertEqual((share['targets'], share['purpose']), ([self.target], 'share'))
        page.evaluate("document.querySelector('#sharing-close').click()")

        self.open(self.target)
        page.click('#open-sharing-attach')
        page.wait_js("document.querySelector('#sharing-body input[name=sharing-offer]')", 'offer list')
        page.click('#sharing-body input[name=sharing-offer]')
        self.assertEqual(page.evaluate("document.querySelector('#sharing-title').value"), 'Zadání podprojektu')
        page.fill('#sharing-reason', 'Podle zadání plníme úkoly')
        page.click('#sharing-primary')
        page.wait_js("!document.querySelector('#sharing-confirm').hidden", 'attach preview')
        summary = page.evaluate("document.querySelector('#sharing-body').textContent")
        self.assertIn('Projekt v prohlížeči', summary); self.assertIn('SHA-256 obsahu', summary)
        self.confirm_dialog('/v1/sharing/attach/confirm')
        page.evaluate("document.querySelector('#sharing-close').click()")

        page.wait_js("[...document.querySelectorAll('#sidebar-artifact-list .sidebar-shared-badge')].length===1", 'shared badge')
        self.assertNotIn('Upravit / přejmenovat', self.buttons('#sidebar-artifact-list'))
        self.assertNotIn('Sdílet do projektu', self.buttons('#sidebar-artifact-list'))
        page.evaluate("document.querySelector('#sidebar-artifact-list .sidebar-artifact-title').click()")
        page.wait(lambda: self.requests('/v1/sharing/reference/view'), 'reference view')
        page.wait_js("document.querySelector('.shared-reference-banner')", 'read-only banner')
        page.wait_idle()
        self.assertEqual(page.evaluate("document.querySelector('.shared-reference-banner').dataset.state"), 'current')
        text = page.evaluate("document.querySelector('#preview-content').textContent")
        self.assertIn('Postavit most.', text); self.assertIn('Podle zadání plníme úkoly', text)
        self.assertEqual(self.requests('/v1/artifacts/preview'), [])
        self.assert_no_page_errors()


if __name__ == '__main__':
    import unittest; unittest.main()
