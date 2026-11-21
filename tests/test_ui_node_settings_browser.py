# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Node settings, native project actions and the publication CMS in a real browser (AUDIT-B7-T1).

Replaces the source-text assertions of
``test_node_settings_are_global_and_backend_form_is_not_duplicated``.
"""
from functools import partial
import json
import shutil
from unittest.mock import patch
from uuid import uuid4

from spikes.project_creation import ProjectCreation
from spikes.publication_cms import PublicationCms
from tests.browser_harness import Reply
from tests.test_publication_cms import cms_module
from tests.ui_flow_case import FakeApi, UiFlowCase, require_browser


@require_browser
class DesktopRuntimeTests(UiFlowCase):
    def test_desktop_shows_node_controls_and_hides_web_account_admin(self):
        page = self.start(configure_search=False)
        hidden = page.evaluate("""Object.fromEntries(['backend-metrics','backend-metrics-indicator',
          'openai-resource-provider','presenter-fullscreen','federation-tab','project-location-controls',
          'sidebar-register-project','open-notebooklm-import','settings-profile-tab','settings-access-tab',
          'settings-users-tab'].map(id=>[id,document.getElementById(id).hidden]))""")
        expected = {name: False for name in hidden}
        expected['settings-users-tab'] = True
        self.assertEqual(hidden, expected)
        self.assertEqual(page.evaluate("document.body.dataset.runtime"), 'desktop')
        self.assertTrue(page.evaluate("""document.querySelector('[data-settings-item="settings-users-tab"]').hidden"""))
        self.assertFalse(page.evaluate("""document.querySelector('[data-settings-item="settings-profile-tab"]').hidden"""))
        self.assertEqual(page.evaluate("document.querySelectorAll('#chat-backend-form').length"), 1)


@require_browser
class NativeProjectActionTests(UiFlowCase):
    def test_missing_location_is_repaired_or_unregistered_through_the_native_shell(self):
        gone = self.node.parent / 'gone'
        missing = ProjectCreation(self.node).create('Ztracený projekt', str(gone), str(uuid4()))['id']
        shutil.rmtree(gone)
        page = self.start(configure_search=False)
        rows = page.evaluate("[...document.querySelectorAll('#sidebar-project-list li')].map(x=>x.textContent)")
        self.assertIn('Odebrat nedostupnou registraci…', rows[1])
        self.assertNotIn('Opravit umístění…', rows[0], 'Only an unavailable project offers repair')
        self.click_text('Opravit umístění…', '#sidebar-project-list')
        self.assertEqual(page.native_actions()[-1][0], 'relocate-project-location')
        self.assertEqual(page.native_actions()[-1][1]['project_id'], missing)
        self.assertEqual(page.text('#sidebar-project-status'), 'Otevírám systémový výběr nového umístění…')
        self.click_text('Odebrat nedostupnou registraci…', '#sidebar-project-list')
        self.assertTrue(page.evaluate("document.querySelector('#project-registration-remove-dialog').open"))
        self.assertEqual(page.text('#project-registration-remove-id'), missing)
        actions = len(page.native_actions())
        page.evaluate("document.querySelector('#project-registration-remove-dialog button[value=cancel]').click()")
        page.settle()
        self.assertEqual(len(page.native_actions()), actions, 'Cancel requests nothing')
        self.click_text('Odebrat nedostupnou registraci…', '#sidebar-project-list')
        page.click('#project-registration-remove-confirm')
        self.assertEqual(page.native_actions()[-1], ('unregister-missing-project', {
            'project_id': missing, 'nonce': page.native_actions()[-1][1]['nonce']}))

    def test_interrupted_operation_offers_native_recovery(self):
        page = self.start(configure_search=False)
        self.assertTrue(page.evaluate("document.querySelector('#sidebar-project-recover').hidden"))
        page.evaluate("setNativeProjectOperationStatus('Operace byla přerušena.',true)")
        self.assertTrue(page.visible('#sidebar-project-recover'))
        page.click('#sidebar-project-recover')
        self.assertEqual(page.native_actions()[-1][0], 'recover-project-operation')
        self.assertTrue(page.evaluate("document.querySelector('#sidebar-project-recover').hidden"))
        self.assertEqual(page.text('#sidebar-project-status'), 'Obnovuji přerušenou operaci…')

    def test_new_project_location_is_chosen_natively_after_a_title(self):
        page = self.start(configure_search=False)
        page.click('#sidebar-create-project')
        page.wait_js("!document.querySelector('#project-create-view').hidden", 'create view')
        page.click('#choose-project-location')
        self.assertEqual(page.native_actions(), [], 'No picker without a project title')
        page.fill('#new-project-title', 'Nový projekt')
        page.click('#choose-project-location')
        self.assertEqual(page.native_actions()[-1][0], 'choose-project-location')
        request = page.evaluate('projectCreationPickerRequest()')
        page.evaluate(f"setProjectCreationLocation({{operation_id:{json.dumps(request['operation_id'])},"
                      "location_label:'~/Projekty/novy',location_token:'t'})")
        self.assertEqual(page.text('#project-location-label'), 'Vybrané umístění: ~/Projekty/novy')
        page.evaluate("setProjectCreationLocation({operation_id:'stale',location_label:'jinde'})")
        self.assertEqual(page.text('#project-location-label'), 'Vybrané umístění: ~/Projekty/novy')


@require_browser
class SettingsNavigationTests(UiFlowCase):
    def test_settings_open_from_the_sidebar_and_close_back_to_the_project_tab(self):
        page = self.start()
        self.open_project_chat()
        page.click('#settings-sidebar-tab')
        page.evaluate("""document.querySelector('#sidebar-settings-list [data-settings-tab="settings-backend-tab"]').click()""")
        page.wait_js("!document.querySelector('#settings-view').hidden", 'settings')
        self.assertTrue(page.evaluate("document.querySelector('#project-view').hidden"))
        self.assertEqual(page.evaluate("document.querySelector('#settings-backend-tab').getAttribute('aria-selected')"),
                         'true')
        self.assertFalse(page.evaluate("Boolean(document.querySelector('#settings-view dialog#administration'))"))
        # closeSettings() is what the desktop smoke run uses to leave settings.
        page.evaluate('closeSettings()')
        page.wait_idle()
        self.assertFalse(page.evaluate("document.querySelector('#project-view').hidden"))
        self.assertEqual(page.evaluate("document.querySelector('#chat-tab').getAttribute('aria-selected')"), 'true')

    def test_federation_settings_render_administration_inside_the_settings_card(self):
        page = self.start(configure_search=False)
        page.evaluate("openSettings('settings-federation-tab')")
        page.wait_idle()
        self.assertTrue(page.visible('#administration'))
        self.assertTrue(page.evaluate("document.querySelector('#administration').classList.contains('settings-card')"))
        self.assertIn('/v1/administration', [item['path'] for item in page.api.requests])

    def test_finished_sync_is_not_shown_as_a_running_phase(self):
        """AUDIT-B7-T1: the last phase of a successful sync is history."""
        page = self.start(configure_search=False)
        lines = lambda value: page.evaluate(f'contentSyncDiagnosticLines({json.dumps(value)})')
        base = {'phase': 'local-publication-pool-apply', 'elapsed_ms': 24300,
                'peer_phase': 'receive-prepare-response', 'error_type': None}
        self.assertEqual(lines(dict(base, state='finished')),
                         ['Poslední synchronizace: dokončena za 24.3 s', None])
        self.assertEqual(lines(dict(base, state='running')),
                         ['Diagnostika: místní uložení: pooly · 24.3 s',
                          'Protistrana: příprava odpovědi'])
        self.assertEqual(lines(dict(base, state='failed', error_type='TimeoutError'))[0],
                         'Diagnostika: místní uložení: pooly · 24.3 s · TimeoutError')

    def test_ollama_binding_is_saved_from_its_dialog(self):
        page = self.start(configure_ollama=False, configure_search=False)
        page.evaluate('openSettings()')
        page.wait_idle()
        page.evaluate("openBackendSettings({backend_id:'ollama',display_name:'Ollama',detail:''})")
        page.fill('#chat-backend-form [name=endpoint]', self.ollama.endpoint)
        page.fill('#chat-backend-form [name=model]', 'gemma3')
        page.evaluate("document.querySelector('#chat-backend-form').requestSubmit()")
        page.wait(lambda: self.requests('/v1/chat/configure'), 'configure request')
        page.wait_idle()
        sent = self.requests('/v1/chat/configure')[0]['body']
        self.assertEqual((sent['adapter'], sent['endpoint'], sent['model']), ('ollama', self.ollama.endpoint, 'gemma3'))
        status = page.evaluate("projectRequest('/v1/chat/status',{}).then(r=>r.binding)")
        self.assertEqual((status['endpoint'], status['model']), (self.ollama.endpoint, 'gemma3'))


@require_browser
class PublicationCmsTests(UiFlowCase):
    def setUp(self):
        super().setUp()
        # A reviewed module in a temporary root: the default modules.local is a
        # private, Git-ignored checkout that CI does not have.
        module, reviewed, _ = cms_module(self.node.parent)
        self.stack.enter_context(patch('spikes.desktop.PublicationCms', partial(
            PublicationCms, reviewed_sources=reviewed, module_roots=(module.parent,))))

    def open_cms(self, api=None):
        page = self.start(configure_search=False, api=api)
        page.evaluate("openSettings('settings-cms-tab')")
        page.wait_idle()
        page.click('#cms-enable')
        page.wait_js("!document.querySelector('#cms-editor').hidden", 'CMS editor')
        page.wait_idle()
        return page

    def test_module_is_enabled_explicitly_and_needs_one_section(self):
        page = self.start(configure_search=False)
        page.evaluate("openSettings('settings-cms-tab')")
        page.wait_idle()
        self.assertEqual(page.text('#cms-status'), 'Publikační CMS modul je dostupný, ale není povolený.')
        self.assertTrue(page.evaluate("document.querySelector('#cms-editor').hidden"))
        page.click('#cms-enable')
        page.wait_js("!document.querySelector('#cms-editor').hidden", 'CMS editor')
        enable = self.requests('/v1/publication-cms/configure')[0]['body']
        self.assertEqual(enable, {'module_id': 'cz.proofofidea.publication-experiment-registry', 'enabled': True})
        for section in ('profile', 'cv', 'timeline'):
            page.evaluate(f"""(()=>{{const box=document.querySelector('#cms-section-{section}');
              if(box.checked){{box.checked=false;box.dispatchEvent(new Event('change'));}}}})()""")
        self.assertEqual(page.evaluate("['profile','cv','timeline'].filter(n=>document.querySelector('#cms-section-'+n).checked).length"), 1)
        self.assertEqual(page.text('#cms-status'), 'Každá doména musí mít povolenou alespoň jednu část.')
        page.fill('#cms-new-hostname', 'https://example.org/x')
        page.click('#cms-add-domain')
        self.assertEqual(page.text('#cms-status'), 'Zadejte platnou doménu bez protokolu a cesty.')
        page.fill('#cms-new-hostname', 'novy.example.org')
        page.click('#cms-add-domain')
        self.assertEqual(page.evaluate("document.querySelector('#cms-hostname').value"), 'novy.example.org')
        page.click('#cms-disable')
        page.wait_js("document.querySelector('#cms-editor').hidden", 'module disabled')
        self.assertEqual(self.requests('/v1/publication-cms/configure')[-1]['body']['enabled'], False)

    def test_preview_is_sandboxed_and_generation_needs_its_exact_digest(self):
        api = FakeApi()
        api.route('/v1/publication-cms/generate', lambda body: {
            'generated_hostnames': [site['hostname'] for site in body['config']['sites']],
            'module_version': '0.4.0', 'output': 'dist/sites'})
        page = self.open_cms(api)
        page.fill('#cms-title', '<img src=x onerror=window.__pwned=1>Titulek')
        page.click('#cms-preview-button')
        page.wait_js("!document.querySelector('#cms-preview').hidden", 'CMS preview')
        frame = page.evaluate("""(()=>{const frame=document.querySelector('#cms-preview-frame');
          return {sandbox:frame.getAttribute('sandbox'),srcdoc:frame.srcdoc.length>0,
                  parent:document.querySelectorAll('#cms-preview img').length};})()""")
        self.assertEqual(frame['sandbox'], '')
        self.assertTrue(frame['srcdoc'])
        self.assertEqual(frame['parent'], 0)
        self.assertIsNone(page.evaluate('window.__pwned ?? null'))
        preview = self.requests('/v1/publication-cms/preview')[0]
        digest = page.response_json(preview)['preview_sha256']
        self.assertIn(digest, page.text('#cms-request-preview'))
        self.assertTrue(page.evaluate("document.querySelector('#cms-generate-button').disabled"))
        page.click('#cms-confirm')
        page.click('#cms-generate-button')
        page.wait(lambda: self.requests('/v1/publication-cms/generate'), 'generate request')
        generated = self.requests('/v1/publication-cms/generate')[0]['body']
        self.assertEqual((generated['preview_sha256'], generated['approved']), (digest, True))
        page.wait_idle()
        self.assertIn('Vygenerováno', page.text('#cms-status'))

    def test_deployment_token_is_not_kept_and_release_needs_confirmation(self):
        api = FakeApi()
        status = {'configured': True, 'state': 'outdated', 'domains': [
            {'hostname': 'proofofidea.cz', 'content': 'outdated', 'custom_domain': 'active'}]}
        api.route('/v1/publication-cms/deployment/status', status)
        api.route('/v1/publication-cms/deployment/configure', {'message': 'Konfigurace uložena.'})
        api.route('/v1/publication-cms/deployment/preview', {
            'preview_sha256': 'd' * 64, 'release': {'files': 3}, 'domains': status['domains']})
        api.route('/v1/publication-cms/deployment/confirm', Reply({'message': 'Nasazeno.', 'state': 'current'}))
        page = self.open_cms(api)
        page.evaluate("openSettings('settings-cms-tab')")  # status of an enabled module
        page.wait_idle()
        self.assertIn('proofofidea.cz · obsah: outdated · Custom Domain: active',
                      page.text('#cms-deployment-domains'))
        page.fill('#cms-deployment-form [name=api_token]', 'secret-token-123')
        page.evaluate("document.querySelector('#cms-deployment-form').requestSubmit()")
        page.settle()
        self.assertEqual(self.requests('/v1/publication-cms/deployment/configure'), [],
                         'Required account and worker are enforced before sending')
        page.fill('#cms-deployment-form [name=account_id]', 'a' * 32)
        page.fill('#cms-deployment-form [name=worker_name]', 'portal')
        page.evaluate("document.querySelector('#cms-deployment-form').requestSubmit()")
        page.wait(lambda: self.requests('/v1/publication-cms/deployment/configure'), 'configure')
        page.wait_idle()
        sent = self.requests('/v1/publication-cms/deployment/configure')[0]['body']
        self.assertEqual((sent['api_token'], sent['account_id'], sent['provider']),
                         ('secret-token-123', 'a' * 32, 'cloudflare'))
        self.assertEqual(page.evaluate("document.querySelector('#cms-deployment-form [name=api_token]').value"), '')
        page.click('#cms-deployment-preview-button')
        page.wait_js("!document.querySelector('#cms-deployment-preview').hidden", 'deployment preview')
        self.assertTrue(page.evaluate("document.querySelector('#cms-deployment-run').disabled"))
        page.click('#cms-deployment-confirm')
        page.click('#cms-deployment-run')
        page.wait(lambda: self.requests('/v1/publication-cms/deployment/confirm'), 'confirm')
        confirm = self.requests('/v1/publication-cms/deployment/confirm')[0]['body']
        self.assertEqual((confirm['preview_sha256'], confirm['approved']), ('d' * 64, True))
