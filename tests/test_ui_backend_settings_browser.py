# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Backend settings forms in a real browser (AUDIT-B7-T1).

Replaces the backend-settings part of the source-text assertions of
``test_chat_ui_uses_authenticated_api_and_explicit_message_selection``.
External providers are scripted, so no request leaves the machine.
"""
from tests.browser_harness import Reply
from tests.ui_flow_case import FakeApi, UiFlowCase, require_browser

CATALOG = {'freshness': 'fresh', 'fetched_at': '2026-11-20T12:00:00+00:00', 'refresh_error': None, 'offers': [
    {'provider_id': 'openai', 'provider_model_id': 'gpt-smoke', 'protocol': 'openai-responses-v1',
     'availability': 'available', 'freshness': 'fresh',
     'capabilities': [{'name': 'generate-text', 'state': 'reported', 'supported': True}]},
    {'provider_id': 'openai', 'provider_model_id': 'removed-smoke', 'protocol': 'openai-responses-v1',
     'availability': 'removed', 'freshness': 'stale',
     'capabilities': [{'name': 'streaming', 'state': 'conflicting', 'supported': False}]}]}


@require_browser
class BackendSettingsTests(UiFlowCase):
    def open_backend(self, backend_id, api=None, **start):
        page = self.start(api=api, **start)
        page.evaluate('openSettings()')
        page.wait_idle()
        page.evaluate(f"openBackendSettings({{backend_id:{backend_id!r},display_name:'X',detail:''}})")
        return page

    def test_openai_models_and_key_are_handled_without_keeping_the_secret(self):
        api = FakeApi()
        api.route('/v1/external/models', CATALOG)
        api.route('/v1/external/configure', lambda body: {'binding': {'model': body['model']}})
        page = self.open_backend('openai-responses', api)
        form = '#external-backend-form'
        self.assertEqual(page.evaluate(f"document.querySelector('{form} [name=secret]').type"), 'password')
        self.assertEqual(page.evaluate(f"document.querySelector('{form} a.provider-link').href"),
                         'https://platform.openai.com/api-keys')
        page.click('#external-load-models')
        page.wait(lambda: self.requests('/v1/external/models'), 'models')
        page.wait_idle()
        self.assertEqual(page.evaluate("[...document.querySelectorAll('#external-models option')].map(o=>o.value)"),
                         ['gpt-smoke'])
        catalog = page.text('#model-catalog-status')
        self.assertIn('Aktuální snapshot', catalog)
        self.assertIn('Binding nebyl změněn', catalog)
        rows = page.evaluate("[...document.querySelectorAll('#model-catalog-offers li')].map(x=>x.textContent)")
        self.assertIn('generate-text: reported', rows[0])
        self.assertIn('streaming: conflicting', rows[1])
        self.assertIn('Načteno 1 nabídek pro textový Responses backend', page.text('#settings-external-status'))
        page.fill(f'{form} [name=model]', 'gpt-smoke')
        page.fill(f'{form} [name=secret]', 'sk-' + 'x' * 30)
        page.evaluate(f"document.querySelector('{form}').requestSubmit()")
        page.wait(lambda: self.requests('/v1/external/configure'), 'configure')
        page.wait_idle()
        sent = self.requests('/v1/external/configure')[0]['body']
        self.assertEqual((sent['adapter'], sent['model'], sent['secret']), ('openai-responses', 'gpt-smoke', 'sk-' + 'x' * 30))
        self.assertEqual(page.evaluate(f"document.querySelector('{form} [name=secret]').value"), '')
        self.assertEqual(page.text('#settings-external-status'),
                         'Externí backend gpt-smoke byl uložen; klíč server nevrátil.')

    def test_atlascloud_needs_a_key_an_offer_and_confirmed_removal(self):
        api = FakeApi()
        offers = {'knowledge_revision': 'k1', 'freshness': 'fresh', 'offers': [
            {'offer_id': 'atlas:qwen', 'provider_id': 'atlascloud', 'provider_model_id': 'qwen/qwen3', 'protocol': 'openai-chat-completions-v1',
             'availability': 'available', 'freshness': 'fresh', 'display_model_id': 'qwen3',
             'capabilities': [{'name': 'generate-text', 'state': 'reported', 'supported': True},
                              {'name': 'text-output', 'state': 'reported', 'supported': True}]}]}
        api.route('/v1/atlascloud/models', {'binding': None, 'capabilities': {'streaming': True}, 'model_catalog': offers})
        api.route('/v1/atlascloud/configure', lambda body: {'binding': {'model': body['model'], 'protocol': body['protocol']},
                                                           'capabilities': {'streaming': True}, 'model_catalog': offers})
        api.route('/v1/atlascloud/remove', {'model_catalog': offers})
        page = self.open_backend('atlascloud-text', api)
        form = '#atlascloud-backend-form'
        self.assertEqual(page.evaluate(f"document.querySelector('{form} a.provider-link').href"),
                         'https://www.atlascloud.ai/dashboard/api-keys')
        page.click('#atlascloud-load-models')
        self.assertEqual(page.text('#settings-atlascloud-status'), 'Nejprve vložte AtlasCloud API klíč.')
        self.assertEqual(self.requests('/v1/atlascloud/models'), [])
        page.fill(f'{form} [name=secret]', 'atlas-' + 'k' * 30)
        page.click('#atlascloud-load-models')
        page.wait(lambda: self.requests('/v1/atlascloud/models'), 'models')
        page.wait_idle()
        self.assertEqual(self.requests('/v1/atlascloud/models')[0]['body'], {'secret': 'atlas-' + 'k' * 30})
        page.fill(f'{form} [name=offer_id]', 'atlas:qwen')
        self.assertEqual(page.evaluate(f"document.querySelector('{form} [name=protocol_label]').value"),
                         'openai-chat-completions-v1')
        page.evaluate(f"document.querySelector('{form}').requestSubmit()")
        page.wait(lambda: self.requests('/v1/atlascloud/configure'), 'configure')
        page.wait_idle()
        sent = self.requests('/v1/atlascloud/configure')[0]['body']
        self.assertEqual((sent['offer_id'], sent['protocol'], sent['knowledge_revision']),
                         ('atlas:qwen', 'openai-chat-completions-v1', 'k1'))
        self.assertEqual(page.evaluate(f"document.querySelector('{form} [name=secret]').value"), '')
        page.dialog_answers.append(False)
        page.evaluate("document.querySelector('#atlascloud-remove').hidden=false")
        page.click('#atlascloud-remove')
        page.settle()
        self.assertEqual(self.requests('/v1/atlascloud/remove'), [])
        page.click('#atlascloud-remove')
        page.wait(lambda: self.requests('/v1/atlascloud/remove'), 'remove')
        self.assertEqual(self.requests('/v1/atlascloud/remove')[0]['body'], {'confirmed': True})

    def test_ollama_is_checked_without_saving_and_failed_save_reloads_the_confirmed_binding(self):
        api = FakeApi()
        page = self.open_backend('ollama', api, configure_ollama=False, configure_search=False)
        form = '#chat-backend-form'
        page.fill(f'{form} [name=endpoint]', self.ollama.endpoint)
        page.fill(f'{form} [name=model]', 'gemma3')
        page.click('#chat-backend-test')
        page.wait(lambda: self.requests('/v1/chat/test'), 'test')
        page.wait_idle()
        self.assertEqual(page.text('#settings-backend-status'), 'Ollama je dostupná a model gemma3 je připraven.')
        self.assertEqual(self.requests('/v1/chat/configure'), [], 'A check saves nothing')
        self.assertIsNone(page.evaluate("projectRequest('/v1/chat/status',{}).then(r=>r.binding)"))
        # A pinned certificate may be pasted with colons; the binding carries plain hex.
        self.assertIsNone(page.evaluate(f"document.querySelector('{form} [name=tls_cert_sha256]').getAttribute('pattern')"))
        self.assertEqual(page.evaluate("normalizeFingerprint(' SHA256 Fingerprint=68:34:AB ')"), '6834ab')
        api.route('/v1/chat/configure', Reply({'error': 'Uložení selhalo.'}, status=422))
        page.evaluate(f"document.querySelector('{form}').requestSubmit()")
        page.wait(lambda: self.requests('/v1/chat/configure'), 'configure')
        page.wait_idle()
        self.assertEqual(page.text('#settings-backend-status'),
                         'Uložení selhalo. Poslední potvrzené nastavení bylo znovu načteno.')


@require_browser
class ProfileAndAccessTests(UiFlowCase):
    def test_user_profile_is_loaded_and_saved_explicitly(self):
        page = self.start(configure_search=False)
        page.evaluate("openSettings('settings-profile-tab')")
        page.wait_idle()
        loads = [item for item in self.requests('/v1/user-profile') if item['body'] == {'action': 'load'}]
        self.assertEqual(len(loads), 1)
        self.assertTrue(page.visible('#user-profile-form'))
        field = page.evaluate("[...document.querySelectorAll('#user-profile-form input[type=text],"
                              "#user-profile-form input:not([type])')].find(x=>x.name)?.name")
        page.fill(f'#user-profile-form [name={field}]', 'Antonín')
        page.evaluate("document.querySelector('#user-profile-form').requestSubmit()")
        page.wait(lambda: [item for item in self.requests('/v1/user-profile') if item['body'].get('action') == 'save'],
                  'profile save')
        page.wait_idle()
        saved = [item for item in self.requests('/v1/user-profile') if item['body'].get('action') == 'save'][0]
        self.assertEqual(saved['body']['profile'][field], 'Antonín')
        self.assertEqual(page.status(saved), 200)

    def test_desktop_application_access_is_fixed_to_this_computer(self):
        page = self.start(configure_search=False)
        page.evaluate("openSettings('settings-access-tab')")
        page.wait_idle()
        self.assertTrue(page.visible('#settings-access-panel'))
        self.assertEqual(self.requests('/v1/application-access'), [], 'The desktop never asks the server')
        self.assertEqual(page.evaluate("document.querySelector('#application-access-form').elements.mode.value"),
                         'localhost')
        self.assertTrue(page.evaluate("[...document.querySelector('#application-access-form').elements]"
                                      ".every(control=>control.disabled)"))
        self.assertEqual(page.text('#application-access-context'),
                         'Desktopová aplikace je pevně dostupná pouze na tomto počítači.')
