# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""XREF-02-B/C in a real browser: share, attach, open read-only, repin, fork, revoke, detach."""
from uuid import uuid4

from spikes.artifact_sharing import ArtifactSharing
from spikes.artifacts import Artifacts
from spikes.cross_references import CrossReferences
from spikes.project_creation import ProjectCreation
from tests.ui_flow_case import UiFlowCase, require_browser


@require_browser
class SharingBrowserTests(UiFlowCase):
    def setUp(self):
        super().setUp()
        self.target = ProjectCreation(self.node).create(
            'Podprojekt', str(self.node.parent / 'target'), str(uuid4()))['id']
        artifacts = self.artifacts = Artifacts(self.node); self.artifact = str(uuid4())
        head = artifacts.workspace(self.project_id).git.head()
        artifacts.save(dict(project_id=self.project_id, base_head=head, artifact_id=self.artifact,
                            title='Zadání podprojektu', body='# Zadání\n\nPostavit most.\n', new=True), str(uuid4()))

    def open(self, project_id):
        page = self.page
        page.evaluate(f"openRegisteredProject('{project_id}')")
        page.wait_js(f"activeProject?.id==='{project_id}'", 'project to open')
        page.wait_idle()

    def confirm_dialog(self, path):
        page = self.page; before = len(self.requests(path))
        page.wait_js("!document.querySelector('#sharing-confirm').hidden", 'reviewed preview')
        self.assertTrue(page.evaluate("document.querySelector('#sharing-confirm').disabled"))
        page.click('#sharing-approved'); page.click('#sharing-confirm')
        page.wait(lambda: len(self.requests(path)) > before, 'confirm')
        page.wait_js("document.querySelector('#sharing-status').textContent==='Uloženo.'", 'saved state')
        page.wait_idle()
        self.assertEqual(page.status(self.requests(path)[-1]), 200)

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

    def open_reference(self, state):
        page = self.page; before = len(self.requests('/v1/sharing/reference/view'))
        page.evaluate("document.querySelector('#sidebar-artifact-list .sidebar-artifact-title').click()")
        page.wait(lambda: len(self.requests('/v1/sharing/reference/view')) > before, 'reference view')
        page.wait_js(f"document.querySelector('.shared-reference-banner')?.dataset.state==={state!r}", state)
        page.wait_idle()

    def test_repin_with_comparison_fork_revoke_and_detach(self):
        sharing = ArtifactSharing(CrossReferences(self.node))
        offer = sharing.share_preview(self.project_id, self.artifact, [self.target], 'share', 'Zadání')
        sharing.share_confirm(offer['preview'], offer['sha256'], str(uuid4()))
        attach = sharing.attach_preview(self.target, self.project_id, offer['preview']['share_id'], 'Zadání', 'Úkoly')
        sharing.attach_confirm(attach['preview'], attach['sha256'], str(uuid4()))
        ws = self.artifacts.workspace(self.project_id)
        self.artifacts.save(dict(project_id=self.project_id, base_head=ws.git.head(), artifact_id=self.artifact,
                                 title='Zadání podprojektu', body='# Zadání\n\nPostavit dva mosty.\n', new=False), str(uuid4()))
        page = self.start(configure_search=False)
        self.open(self.target)
        self.assertIn('Zadání · sdílené, jen ke čtení',
                      page.evaluate("document.querySelector('#task-artifact-list').textContent"))
        self.open_reference('newer-available')
        self.assertIn('Postavit most.', page.evaluate("document.querySelector('#preview-content').textContent"))
        self.click_text('Porovnat a aktualizovat', '#preview-content')
        page.wait_js("document.querySelector('#sharing-body .sharing-diff')", 'comparison')
        diff = page.evaluate("document.querySelector('#sharing-body .sharing-diff').textContent")
        self.assertIn('-Postavit most.', diff); self.assertIn('+Postavit dva mosty.', diff)
        self.confirm_dialog('/v1/sharing/repin/confirm')
        page.evaluate("document.querySelector('#sharing-close').click()")
        self.open_reference('current')
        self.assertIn('Postavit dva mosty.', page.evaluate("document.querySelector('#preview-content').textContent"))

        self.click_text('Vytvořit vlastní kopii', '#preview-content')
        self.confirm_dialog('/v1/sharing/fork/confirm')
        page.evaluate("document.querySelector('#sharing-close').click()")
        page.wait_js("document.querySelectorAll('#sidebar-artifact-list .sidebar-artifact-title').length===2", 'fork row')

        self.open(self.project_id)
        self.click_text('Sdílet do projektu', '#sidebar-artifact-list')
        page.wait_js("document.querySelector('#sharing-body .sharing-revoke')", 'revoke button')
        page.click('#sharing-body .sharing-revoke')
        page.wait_js("!document.querySelector('#sharing-confirm').hidden", 'revoke preview')
        self.assertIn('nelze', page.evaluate("document.querySelector('#sharing-body').textContent"))
        self.confirm_dialog('/v1/sharing/revoke/confirm')
        page.evaluate("document.querySelector('#sharing-close').click()")

        self.open(self.target)
        page.evaluate("[...document.querySelectorAll('#sidebar-artifact-list .sidebar-artifact-title')]"
                      ".find(b=>b.closest('li')?.querySelector('.sidebar-shared-badge')).click()")
        page.wait_js("document.querySelector('.shared-reference-banner')?.dataset.state==='share-revoked'", 'revoked')
        page.wait_idle()
        self.assertNotIn('Vytvořit vlastní kopii', self.buttons('#preview-content'))
        self.click_text('Odebrat z projektu', '#preview-content')
        self.confirm_dialog('/v1/sharing/detach/confirm')
        page.evaluate("document.querySelector('#sharing-close').click()")
        page.wait_js("document.querySelectorAll('#sidebar-artifact-list .sidebar-shared-badge').length===0", 'detached')
        self.assertEqual(page.evaluate("document.querySelectorAll('#sidebar-artifact-list .sidebar-artifact-title').length"), 1)
        self.assert_no_page_errors()

    def test_unregistered_source_shows_inaccessible_state_without_content_or_copy(self):
        import json
        sharing = ArtifactSharing(CrossReferences(self.node))
        offer = sharing.share_preview(self.project_id, self.artifact, [self.target], 'share', 'Zadání')
        sharing.share_confirm(offer['preview'], offer['sha256'], str(uuid4()))
        attach = sharing.attach_preview(self.target, self.project_id, offer['preview']['share_id'], 'Zadání', 'Úkoly')
        sharing.attach_confirm(attach['preview'], attach['sha256'], str(uuid4()))
        page = self.start(configure_search=False)
        self.open(self.target)
        node = json.loads(self.node.read_bytes())
        node['projects'] = [p for p in node['projects'] if p['project_id'] != self.project_id]
        self.node.write_bytes(json.dumps(node).encode())
        self.open_reference('source-inaccessible')
        text = page.evaluate("document.querySelector('#preview-content').textContent")
        self.assertIn('Samotný odkaz přístup nepřidává', text); self.assertNotIn('Postavit most.', text)
        self.assertEqual(self.buttons('#preview-content'), ['Odebrat z projektu'])
        self.assert_no_page_errors()


if __name__ == '__main__':
    import unittest; unittest.main()
