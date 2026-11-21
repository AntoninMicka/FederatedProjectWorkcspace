# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Presenter and public screen in a real browser (AUDIT-B7-T1).

Replaces the source-text assertions of ``test_presentation_ui_and_backend_are_exposed``.
"""
import json

from tests.ui_flow_case import FakeApi, UiFlowCase, require_browser


@require_browser
class PresenterTests(UiFlowCase):
    def open_presenter(self):
        page = self.start(configure_search=False)
        page.evaluate('openPresenter()')
        page.wait_js("document.querySelector('#presenter-live-state').textContent==='ŽIVĚ'", 'first slide')
        page.wait_idle()
        return page

    def deck(self):
        return self.page.evaluate("""[...document.querySelectorAll('#presenter-deck-list li')]
          .map(x=>x.textContent+(x.getAttribute('aria-current')==='true'?' *':''))""")

    def shown(self):
        return [item['body'] for item in self.requests('/v1/presentation/control')
                if item['body'].get('action') == 'show']

    def key(self, name):
        self.page.evaluate(f"""document.querySelector('#presenter-view').dispatchEvent(
          new KeyboardEvent('keydown',{{key:{json.dumps(name)},bubbles:true}}))""")
        self.page.wait_idle()

    def test_presenting_projects_slides_with_private_notes_and_next_preview(self):
        page = self.open_presenter()
        self.assertEqual(self.requests('/v1/presentation/status')[0]['body'], {'action': 'start'})
        self.assertTrue(page.evaluate("document.body.classList.contains('presenter-active')"))
        self.assertTrue(page.visible('#presenter-view'))
        self.assertTrue(page.visible('aside'), 'The sidebar stays available while presenting')
        self.assertEqual(self.deck()[:3], ['01 Úvod *', '02 Problém', '03 Řešení'])
        self.assertEqual(self.deck()[-1], '06 Prostor pro Vaše dotazy')
        self.assertEqual(self.shown()[0]['slide'], 0)
        self.assertIn('Úvod', page.text('#presenter-screen'))
        self.assertNotIn(page.text('#presenter-notes'), ('', 'Žádné poznámky.', 'Tento slide nemá poznámky.'))
        self.assertIn('Problém', page.text('#presenter-private-preview'))
        self.assertTrue(page.evaluate("""document.querySelector('#presenter-screen')
          .compareDocumentPosition(document.querySelector('#presenter-notes'))&Node.DOCUMENT_POSITION_FOLLOWING"""))
        self.key('ArrowRight')
        self.assertEqual(self.shown()[-1]['slide'], 1)
        self.assertEqual(self.deck()[1], '02 Problém *')
        self.assertIn('Problém', page.text('#presenter-screen'))
        self.key('ArrowLeft')
        self.assertEqual(self.shown()[-1]['slide'], 0)
        self.assertEqual(self.deck()[0], '01 Úvod *')
        self.assert_no_page_errors()

    def test_backup_is_previewed_privately_until_shown_and_counts_exposure(self):
        page = self.open_presenter()
        self.assertEqual(page.text('#presenter-slide-backup-status'), 'Přiřazené backupy: 2 z 2.')
        page.click('#presenter-backup-tab')
        self.assertEqual(page.evaluate("document.querySelector('#presenter-backup-tab').getAttribute('aria-selected')"), 'true')
        self.assertFalse(page.evaluate("document.querySelector('#presenter-backup-list').hidden"))
        all_backups = page.evaluate("document.querySelectorAll('#presenter-backups li').length")
        self.assertEqual(all_backups, 10)
        page.fill('#presenter-backup-search', 'publikum')
        titles = page.evaluate("[...document.querySelectorAll('#presenter-backups strong')].map(x=>x.textContent)")
        self.assertTrue(titles and all('publikum' in title.lower() for title in titles), titles)
        page.fill('#presenter-backup-search', '')
        shown_before = len(self.shown())
        backup = page.evaluate("document.querySelector('#presenter-backups strong').textContent")
        page.evaluate("document.querySelector('#presenter-backups button').click()")
        page.wait_idle()
        self.assertEqual(len(self.shown()), shown_before, 'Choosing a backup shows nothing publicly')
        self.assertEqual(page.text('#presenter-next-title'), 'Vybraný backup')
        self.assertIn('Zatím nepromítnuto', page.text('#presenter-private-status'))
        self.assertFalse(page.evaluate("document.querySelector('#presenter-show-private').disabled"))
        self.assertEqual(page.text('#presenter-exposure'), 'Expozice 0 · +0')
        page.click('#presenter-show-private')
        page.wait_idle()
        self.assertEqual(len(self.shown()), shown_before + 1)
        self.assertEqual(page.text('#presenter-exposure'), 'Expozice 1 · +1')
        self.assertEqual(self.deck()[1], f'02 Backup · {backup} *')
        # Return goes back to the main slide the branch started from.
        self.assertFalse(page.evaluate("document.querySelector('#presenter-return').disabled"))
        self.assertEqual(page.text('#presenter-return-anchor'), 'Návrat: Úvod')
        page.click('#presenter-return')
        page.wait_idle()
        self.assertEqual(self.shown()[-1]['slide'], 0)
        self.assertEqual(self.deck()[2], '03 Úvod *')

    def test_closing_ends_the_session_and_restores_the_workspace(self):
        page = self.open_presenter()
        page.click('#presenter-back')
        page.wait_js("document.querySelector('#presenter-view').hidden", 'presenter to close')
        self.assertEqual(self.requests('/v1/presentation/status')[-1]['body'], {'action': 'end'})
        self.assertFalse(page.evaluate("document.body.classList.contains('presenter-active')"))
        self.assertTrue(page.visible('#project-home'))

    def test_layout_keeps_three_columns_and_a_16_9_screen(self):
        page = self.open_presenter()
        layout = page.evaluate("""(()=>{
          const grid=document.querySelector('.presenter-layout'),width=grid.getBoundingClientRect().width;
          const columns=getComputedStyle(grid).gridTemplateColumns.split(' ').map(parseFloat);
          const screen=document.querySelector('#presenter-screen').getBoundingClientRect();
          return {columns:columns.map(value=>value/width),ratio:screen.width/screen.height,
                  header:parseFloat(getComputedStyle(document.querySelector('.presenter-header')).fontSize)/
                         parseFloat(getComputedStyle(document.querySelector('#presenter-view')).fontSize)};
        })()""")
        self.assertEqual(len(layout['columns']), 3)
        self.assertAlmostEqual(layout['columns'][0], 0.15, delta=0.02)
        self.assertAlmostEqual(layout['columns'][1], 0.25, delta=0.02)
        self.assertAlmostEqual(layout['ratio'], 16 / 9, delta=0.02)
        self.assertAlmostEqual(layout['header'], 1.5, delta=0.01)


@require_browser
class PresenterGamepadTests(UiFlowCase):
    def test_axes_follow_the_configured_mapping_and_fire_once_per_push(self):
        page = self.start(configure_search=False)
        actions = page.evaluate("""(()=>{
          const settings={...presenterGamepadSettings,enabled:true,tabs_axis:3,items_axis:4,main_axis:5,history_axis:6,
            neutral_threshold:0.2,activation_threshold:0.6,confirm_button:0};
          const pad=axes=>({id:'pad',axes,buttons:[{pressed:false}]});
          readPresenterGamepad(null,false,settings);
          const read=axes=>readPresenterGamepad(pad(axes),true,settings);
          return [read([0,0,0,0,0,0,0]),read([0,0,0,0.9,0,0,0]),read([0,0,0,0.9,0,0,0]),
                  read([0,0,0,0,0,0,0]),read([0,0,0,-0.9,0,0,0]),read([0,0,0,0,0.9,0,0])];
        })()""")
        self.assertEqual(actions, [[], ['tabNext'], [], [], ['tabPrevious'], ['itemNext']])

    def test_gamepad_navigation_moves_tabs_and_items(self):
        page = self.start(configure_search=False)
        page.evaluate('openPresenter()')
        page.wait_js("document.querySelector('#presenter-live-state').textContent==='ŽIVĚ'", 'first slide')
        state = page.evaluate("""(()=>{
          selectPresenterTab(1);
          const tab=presenterTabs.find(x=>x.getAttribute('aria-selected')==='true').id;
          movePresenterItem(1);
          const selected=[...document.querySelectorAll('#presenter-backup-list .presenter-gamepad-selected')];
          return {tab,selected:selected.length,status:presenterGamepadStatus.textContent,
                  backupList:!document.querySelector('#presenter-backup-list').hidden};
        })()""")
        self.assertEqual(state['tab'], 'presenter-backup-tab')
        self.assertTrue(state['backupList'])
        self.assertEqual(state['selected'], 1)
        self.assertRegex(state['status'], r'^Gamepad: Backupy · 2/\d+$')

    def test_settings_apply_for_this_run_or_save_on_this_node(self):
        page = self.start(configure_search=False)
        page.evaluate('openPresenter()')
        page.wait_idle()
        page.fill('#presenter-gamepad-tabs-axis', '3')
        page.click('#presenter-gamepad-apply')
        self.assertEqual(page.text('#presenter-gamepad-settings-status'),
                         'Nastavení je použito pro tento běh; na disk se nic nezapsalo.')
        saves = [item for item in self.requests('/v1/gamepad/settings') if item['body'].get('action') == 'save']
        self.assertEqual(saves, [])
        page.click('#presenter-gamepad-save')
        page.wait_js("document.querySelector('#presenter-gamepad-settings-status').textContent.includes('uloženo')",
                     'settings to be saved')
        saves = [item for item in self.requests('/v1/gamepad/settings') if item['body'].get('action') == 'save']
        self.assertEqual(saves[0]['body']['settings']['tabs_axis'], 3)
        self.assertEqual(page.text('#presenter-gamepad-settings-status'),
                         'Nastavení bylo uloženo pouze na tomto uzlu.')
        page.fill('#presenter-gamepad-tabs-axis', '1.5')
        page.click('#presenter-gamepad-apply')
        self.assertEqual(page.text('#presenter-gamepad-settings-status'), 'Osy a tlačítko musí být celá čísla.')


@require_browser
class PublicScreenTests(UiFlowCase):
    def test_public_screen_shows_the_projected_slide_without_speaker_notes(self):
        page = self.start(configure_search=False)
        page.evaluate('openPresenter()')
        page.wait_js("document.querySelector('#presenter-live-state').textContent==='ŽIVĚ'", 'first slide')
        notes = page.text('#presenter-notes')
        page.navigate(self.page.server.origin + '/presentation-screen')
        page.wait_js("document.querySelector('#screen h1')", 'projected slide')
        self.assertEqual(page.text('#screen h1'), 'Úvod')
        self.assertNotIn(notes, page.text('body'))
        self.assertTrue(page.evaluate("document.querySelector('#link-status').hidden"))
        reported = [item['body'] for item in self.requests('/v1/presentation/control')
                    if item['body'].get('action') == 'display-ratio']
        expected = page.evaluate("innerWidth/innerHeight>=1.55?'16:9':'4:3'")
        self.assertEqual(reported[0], {'action': 'display-ratio', 'ratio': expected})

    def test_public_screen_follows_ratio_and_waits_when_nothing_is_shown(self):
        api = FakeApi()
        state = {'visible': True, 'ratio': '16:9', 'content': {'title': 'Veřejný titulek', 'body': 'Text'}}
        api.route('/v1/presentation/public', lambda body: state)
        api.route('/v1/presentation/control', {'ok': True})
        page = self.start(configure_search=False, api=api)
        page.navigate(page.server.origin + '/presentation-screen')
        page.wait_js("document.querySelector('#screen h1')", 'slide')
        self.assertEqual(page.evaluate("document.querySelector('#screen').style.aspectRatio"), '16 / 9')
        state.update(ratio='4:3')
        page.wait_js("document.querySelector('#screen').style.aspectRatio==='4 / 3'", '4:3 ratio')
        state.update(visible=False)
        page.wait_js("document.querySelector('#screen .neutral')", 'neutral screen')
        self.assertEqual(page.text('#screen'), 'Veřejné okno čeká na schválený slide.')
