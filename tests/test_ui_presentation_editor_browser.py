# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Presentation editor and the native desktop bridge in a real browser (AUDIT-B7-T1).

Replaces the source-text assertions of
``test_presentation_editor_is_integrated_in_shared_workspace``.
"""
import re
from pathlib import Path

from tests.ui_flow_case import UiFlowCase, require_browser

# Page globals Qt calls through runJavaScript (spikes/desktop.py).
DESKTOP = Path(__file__).resolve().parents[1] / 'spikes' / 'desktop.py'


def native_bridge_functions():
    source = DESKTOP.read_text()
    calls = re.findall(r"runJavaScript\(\s*f?['\"]([^'\"]*)", source)
    calls += re.findall(r"typeof (\w+)===", source)
    names = set()
    for text in calls:
        for name in re.findall(r'(?<![.\w])([A-Za-z_]\w*)\(', text):
            names.add(name)
        names.update(re.findall(r'^(\w+)$', text))
    return sorted(names - {'JSON', 'document', 'history'})


@require_browser
class PresentationEditorTests(UiFlowCase):
    def open_editor(self):
        page = self.start(configure_search=False)
        page.evaluate("[...document.querySelectorAll('#sidebar-project-list button')]"
                      ".find(b=>b.textContent==='Otevřít').click()")
        page.wait_js('activeProject?.id', 'project to open')
        page.wait_idle()
        page.evaluate('openPresentationEditor()')
        page.wait_idle()
        return page

    def save_new_deck(self, title='Moje prezentace'):
        page = self.page
        page.fill('#presentation-deck-title', title)
        page.click('#presentation-editor-save')
        page.wait_js("document.querySelector('#presentation-editor-status').textContent"
                     ".startsWith('Prezentace byla uložena')", 'deck to be saved')
        page.wait_idle()

    def test_new_deck_is_saved_into_the_project_and_listed_in_outputs(self):
        page = self.open_editor()
        self.assertEqual(self.requests('/v1/presentations/open')[0]['body'].keys(), {'project_id', 'expected_head'})
        self.assertTrue(page.visible('#presentation-editor-workspace'))
        self.assertTrue(page.evaluate("document.querySelector('#presentation-editor-save').disabled"),
                        'Nothing to save before an edit')
        self.assertEqual(page.text('#presentation-editor-status'),
                         'Nová prezentace vznikne až po kliknutí na Uložit do projektu.')
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#presentation-template-select option')]"
                                       ".map(o=>o.value)"),
                         ['title', 'content', 'two-column', 'visual', 'closing'])
        self.save_new_deck()
        saved = self.requests('/v1/presentations/save')[0]['body']
        self.assertEqual(saved['document']['new'], True)
        self.assertEqual(saved['document']['deck']['title'], 'Moje prezentace')
        self.assertEqual(page.status(self.requests('/v1/presentations/save')[0]), 200)
        listed = page.evaluate("[...document.querySelectorAll('#sidebar-presentation-list li strong,"
                               "#sidebar-presentation-list li')].map(x=>x.textContent)")
        self.assertTrue(any('Moje prezentace' in text for text in listed), listed)
        self.assertEqual(page.evaluate("document.querySelector('#sidebar-presentation-list')"
                                       ".getAttribute('aria-label')"), 'Prezentace ve výstupech projektu')
        self.assert_no_page_errors()

    def test_sidebar_actions_edit_and_run_the_saved_deck(self):
        page = self.open_editor()
        self.save_new_deck('Spustitelná prezentace')
        artifact = self.requests('/v1/presentations/save')[0]['body']['document']['artifact_id']
        before = len(page.api.requests)
        self.click_text('Spustit', '#sidebar-presentation-list')
        page.wait_js("document.body.classList.contains('presenter-active')", 'presenter')
        page.wait_idle()
        used = self.requests('/v1/presentations/use', before)
        self.assertEqual(used[0]['body']['artifact_id'], artifact)
        self.assertEqual(self.requests('/v1/presentation/status', before)[0]['body'], {'action': 'start'})
        # The presenter projects the saved deck, not the built-in demo deck.
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#presenter-deck-list li')]"
                                       ".map(x=>x.textContent)"), ['01 Nový slide', '02 Prostor pro Vaše dotazy'])

    def test_two_column_layout_splits_bullets_in_the_preview(self):
        page = self.open_editor()
        page.fill('#presentation-slide-bullets', 'A\nB\nC\nD')
        page.fill('#presentation-slide-layout', 'two-column')
        columns = page.evaluate("""[...document.querySelectorAll('#presentation-panel *')]
          .filter(e=>e.children.length===2&&[...e.children].every(c=>c.tagName==='UL'))
          .map(e=>[...e.children].map(list=>[...list.children].map(li=>li.textContent)))""")
        self.assertIn([['A', 'B'], ['C', 'D']], columns)

    def test_pdf_export_goes_through_reviewed_plan_and_native_target(self):
        page = self.open_editor()
        self.save_new_deck('Tiskový deck')
        page.click('#presentation-editor-print')
        page.wait_js("document.querySelector('#presentation-print-dialog').open", 'print dialog')
        preview = self.requests('/v1/presentations/export/preview')[0]['body']
        self.assertEqual(set(preview), {'project_id', 'artifact_id', 'expected_head'})
        self.assertIn('Prezentace: Tiskový deck', page.text('#presentation-print-details'))
        self.assertTrue(page.evaluate("document.querySelector('#presentation-print-run').disabled"))
        page.click('#presentation-print-choose')
        action, fields = page.native_actions()[-1]
        self.assertEqual(action, 'choose-presentation-pdf')
        request = page.evaluate('presentationPdfTargetRequest()')
        self.assertEqual(fields['nonce'], request['nonce'])
        # Qt answers with the chosen target; a stale nonce is ignored.
        page.evaluate("setPresentationPdfTarget({nonce:'stale',path:'/tmp/x.pdf',exists:false})")
        self.assertEqual(page.text('#presentation-print-target'), 'Cíl PDF zatím není vybraný.')
        page.evaluate(f"setPresentationPdfTarget({{nonce:{request['nonce']!r},path:'/tmp/deck.pdf',exists:true}})")
        self.assertIn('existující soubor bude atomicky přepsán', page.text('#presentation-print-target'))
        self.assertIsNone(page.evaluate('presentationPdfExportRequest()'), 'Export needs the confirmation')
        page.click('#presentation-print-confirm')
        self.assertFalse(page.evaluate("document.querySelector('#presentation-print-run').disabled"))
        page.click('#presentation-print-run')
        action, fields = page.native_actions()[-1]
        self.assertEqual((action, fields['nonce']), ('export-presentation-pdf', request['nonce']))
        self.assertEqual(page.evaluate('presentationPdfExportRequest()'),
                         {'nonce': request['nonce'], 'preview_sha256': request['preview_sha256']})
        page.evaluate("setPresentationPdfNativeError('Disk je plný.')")
        self.assertEqual(page.text('#presentation-print-warning'), 'Disk je plný.')


@require_browser
class NativeBridgeTests(UiFlowCase):
    def test_every_function_qt_calls_exists_in_the_page(self):
        names = native_bridge_functions()
        for expected in ('presentationPdfTargetRequest', 'setPresentationPdfTarget',
                         'setPresentationPdfNativeError', 'presentationPdfExportRequest',
                         'closePresenterDisplayConfiguration'):
            self.assertIn(expected, names)
        page = self.start(configure_search=False)
        missing = page.evaluate(f"{names!r}.filter(name=>typeof globalThis[name]!=='function'"
                                "&&typeof eval('typeof '+name+'===\"function\"?'+name+':undefined')!=='function')")
        self.assertEqual(missing, [])

    def test_presenter_displays_are_requested_from_the_native_shell(self):
        page = self.start(configure_search=False)
        page.evaluate("""showPresenterDisplayConfiguration({token:'t-1',screens:[
          {index:0,label:'Notebook'},{index:1,label:'Projektor'}]})""")
        self.assertTrue(page.evaluate("document.querySelector('#presenter-display-form').closest('dialog').open"))
        page.fill('#presenter-display-form [name=speaker]', '0')
        page.fill('#presenter-display-form [name=audience]', '0')
        self.assertTrue(page.evaluate("document.querySelector('#presenter-display-apply').disabled"))
        self.assertEqual(page.text('#presenter-display-status'), 'Řečník a diváci musí mít různé displeje.')
        page.fill('#presenter-display-form [name=audience]', '1')
        page.click('#presenter-display-identify')
        action, fields = page.native_actions()[-1]
        self.assertEqual((action, fields['token'], fields['speaker'], fields['audience']),
                         ('presenter-displays-identify', 't-1', '0', '1'))
        page.evaluate("document.querySelector('#presenter-display-form').requestSubmit()")
        self.assertEqual(page.native_actions()[-1][0], 'presenter-displays-apply')
        page.click('#presenter-display-cancel')
        self.assertEqual(page.native_actions()[-1][0], 'presenter-displays-cancel')
        page.evaluate('closePresenterDisplayConfiguration()')
        self.assertFalse(page.evaluate("document.querySelector('#presenter-display-form').closest('dialog').open"))
