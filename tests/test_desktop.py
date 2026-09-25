# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Desktop assets/policy are mandatory; a real Qt smoke is explicitly opt-in."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest

from spikes.desktop import provider_key_url, request_policy
from spikes.desktop_ui import DesktopHandler, HTML, JS
from spikes.local_api import running_api
from tests import test_local_api


class DesktopTests(unittest.TestCase):
    def test_presenter_next_preview_follows_tab_and_includes_notes(self):
        import shutil
        if not shutil.which('node'):
            self.skipTest('Node.js is required for presenter behavior validation')
        start = JS.index('function renderPresenterContent(')
        end = JS.index('function renderPresenterSlide()', start)
        harness = """
const assert=require('node:assert/strict');
const element=()=>({textContent:'',children:[],replaceChildren(){this.children=[];},append(...items){this.children.push(...items);},dataset:{}});
const elements={};
const document={createElement:element,querySelector(id){return elements[id]??=element();}};
const presenterPrivatePreview=element(),presenterNextPreview=element();
let presenterNextSelection=null,presenterNextSelectionKind='main',presenterTabIndex=0,presenterIndex=0;
const presenterSlides=[{title:'Current'}, {title:'Next',body:'Main body',notes:'Main notes'}];
"""
        checks = """
refreshPresenterNext();
assert.equal(presenterNextSelection,presenterSlides[1]);
assert.equal(elements['#presenter-next-notes'].textContent,'Main notes');
presenterTabIndex=1;refreshPresenterNext();
assert.equal(presenterNextPreview.disabled,true);
presenterSelectedBackup={title:'Backup',body:'Backup body',notes:'Backup notes'};
refreshPresenterNext();
assert.equal(presenterNextSelectionKind,'backup');
assert.equal(presenterPrivatePreview.children[0].textContent,'Backup');
assert.equal(elements['#presenter-next-notes'].textContent,'Backup notes');
presenterTabIndex=0;refreshPresenterNext();
assert.equal(presenterNextSelection,presenterSlides[1]);
presenterIndex=1;refreshPresenterNext();
assert.equal(presenterNextPreview.disabled,true);
assert.equal(elements['#presenter-next-notes'].textContent,'Žádné poznámky.');
presenterTabIndex=1;refreshPresenterNext();
assert.equal(presenterNextSelection,presenterSelectedBackup);
renderPresenterWidget(element(),elements['#presenter-next-notes'],{title:'No notes'});
assert.equal(elements['#presenter-next-notes'].textContent,'Tento slide nemá poznámky.');
"""
        subprocess.run(['node', '-e', harness + JS[start:end] + checks], check=True)

    def test_stream_endpoint_emits_delta_and_terminal_result_over_http(self):
        class Service:
            def external_send_stream(self, request, on_delta):
                self.request = request
                on_delta('první '); on_delta('část')
                return {'thread': {'messages': []}, 'state': 'succeeded'}

        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            server.chat_service = Service()
            response = driver.request(server, path='/v1/external/send-stream',
                                      body=b'{"run_id":"test-run"}')
        head, body = response.split(b'\r\n\r\n', 1)
        self.assertIn(b' 200 ', head)
        events = [json.loads(line) for line in body.splitlines()]
        self.assertEqual(events, [
            {'type': 'delta', 'delta': 'první '},
            {'type': 'delta', 'delta': 'část'},
            {'type': 'result', 'result': {
                'thread': {'messages': []}, 'state': 'succeeded'}}])
        self.assertEqual(server.chat_service.request, {'run_id': 'test-run'})

    def test_prompt_switches_to_chat_only_when_submitted(self):
        input_handler = JS.split("draft.addEventListener('input',()=>{", 1)[1].split('});', 1)[0]
        submit_handler = JS.split("document.querySelector('#chat-composer').addEventListener('submit',async event=>{", 1)[1].split('});', 1)[0]
        self.assertNotIn('selectMainTab', input_handler)
        self.assertIn('selectMainTab(mainTabs[1])', submit_handler)

    def test_gamepad_demo_ui_and_backend_are_exposed(self):
        from spikes.desktop_ui import HTML, JS
        self.assertIn('id="gamepad-scan"', HTML)
        self.assertIn('/v1/gamepad/status', JS)
        self.assertIn('Gamepad demo', HTML)
        self.assertIn('id="gamepad-list"', HTML)

    def test_presentation_ui_and_backend_are_exposed(self):
        from spikes.desktop_ui import ASSETS, CSS, HTML, JS, presentation_public_payload
        from types import SimpleNamespace
        from spikes.desktop_ui import presentation_deck
        deck = presentation_deck()
        self.assertIn('id="presentation-start"', HTML)
        self.assertIn('id="presentation-slide"', HTML)
        self.assertIn('/v1/presentation/status', JS)
        self.assertIn('Promítání prezentace', HTML)
        self.assertIn('presentation-mode', JS)
        self.assertIn('id="presentation-prev"', HTML)
        self.assertIn('id="presentation-next"', HTML)
        self.assertIn('id="presentation-fullscreen"', HTML)
        self.assertIn('requestFullscreen()', JS)
        self.assertIn("event.key==='ArrowRight'", JS)
        self.assertIn('id="presenter-view"', HTML)
        self.assertIn('id="presenter-screen"', HTML)
        self.assertNotIn('id="presenter-ratio"', HTML)
        self.assertIn('id="presenter-backups"', HTML)
        self.assertIn('presenterBackupsData=[]', JS)
        self.assertIn("result.backups", JS)
        self.assertIn('Otevřít presenter', HTML)
        self.assertIn('id="presenter-notes"', HTML)
        self.assertIn('id="presenter-next-preview"', HTML)
        self.assertIn('id="presenter-deck-list"', HTML)
        self.assertIn('id="presenter-private-preview"', HTML)
        self.assertIn('id="presenter-show-private"', HTML)
        self.assertIn('id="presenter-exposure"', HTML)
        self.assertIn('id="presenter-blackout"', HTML)
        self.assertIn('id="presenter-question"', HTML)
        self.assertIn('id="presenter-gamepad-status"', HTML)
        self.assertIn('id="presenter-tab-content"', HTML)
        self.assertIn('class="presenter-next-selector"', HTML)
        self.assertIn('id="presenter-slide-list"', HTML)
        self.assertIn('id="presenter-backup-list"', HTML)
        self.assertIn('id="presenter-question-list"', HTML)
        self.assertIn('class="presenter-slide-widget"', HTML)
        self.assertIn('min-height:48px', CSS)
        self.assertIn('presenter-next-selector h3', CSS)
        self.assertIn('setPresenterNextSelection', JS)
        self.assertIn("setPresenterNextSelection(backup,'backup')", JS)
        self.assertIn('#presenter-tab-status,#presenter-backup-status{display:none}', CSS)
        self.assertIn("document.querySelector('#presenter-backup-list').hidden", JS)
        self.assertIn('.presenter-selection-preview{flex:0 0 auto', CSS)
        self.assertIn("pad.axes[2]", JS)
        self.assertIn("pad.axes[3]", JS)
        self.assertIn('selectPresenterTab', JS)
        self.assertIn('movePresenterItem', JS)
        self.assertIn('presenter-gamepad-selected', CSS)
        self.assertIn('id="presenter-meeting-time"', HTML)
        self.assertIn('id="presenter-branch-time"', HTML)
        self.assertIn('id="presenter-backup-search"', HTML)
        self.assertIn('id="presenter-outline"', HTML)
        self.assertIn('id="presenter-alert"', HTML)
        self.assertIn('id="presenter-return"', HTML)
        self.assertEqual(HTML.count('id="presenter-notes"'), 1)
        self.assertIn('presenterBackupSearch.addEventListener', JS)
        self.assertIn('presenterMeetingStarted', JS)
        self.assertIn('renderPrivateSelection(backup', JS)
        self.assertIn('presenterShowPrivate.addEventListener', JS)
        self.assertNotIn('renderPresenterContent(presenterScreen,backup)', JS)
        self.assertEqual(len(deck['slides']), 5)
        self.assertEqual(len(deck['backups']), 10)
        self.assertTrue(all(slide.get('notes') for slide in deck['slides']))
        self.assertEqual([sum(item['after_slide'] == index for item in deck['backups']) for index in range(5)], [2] * 5)
        self.assertIn('grid-template-columns:15% 25% minmax(0,1fr)', CSS)
        self.assertIn('.presenter-speaker{width:100%;align-self:stretch;display:flex;flex-direction:column}', CSS)
        self.assertIn('#presenter-view{height:100%;min-height:0;display:flex;flex-direction:column', CSS)
        self.assertIn('.presenter-header{font-size:1.5em;min-height:52px', CSS)
        self.assertIn('class="presenter-header-main"', HTML)
        self.assertIn('body.presenter-active>aside{display:none}', CSS)
        self.assertIn("document.body.classList.add('presenter-active')", JS)
        self.assertIn("document.body.classList.remove('presenter-active')", JS)
        self.assertIn('height:100%', CSS)
        self.assertIn('aspect-ratio:16/9', CSS)
        self.assertIn('max-width:420px', CSS)
        self.assertLess(HTML.index('id="presenter-screen"'), HTML.index('id="presenter-notes"'))
        self.assertGreaterEqual(CSS.count('font-size:1.5em'), 2)
        self.assertIn('/presentation-screen', ASSETS)
        self.assertIn('/v1/presentation/control', JS)
        public_server = SimpleNamespace()
        self.assertFalse(presentation_public_payload(public_server)['visible'])
        public_payload = presentation_public_payload(public_server, {'action': 'show', 'slide': 0})
        self.assertTrue(public_payload['visible'])
        ratio_payload = presentation_public_payload(public_server, {'action': 'display-ratio', 'ratio': '4:3'})
        self.assertEqual(ratio_payload['ratio'], '4:3')
        self.assertIn('display-ratio', ASSETS['/presentation-screen'][1])
        self.assertNotIn('notes', public_payload['content'])
        self.assertNotIn('backups', public_payload)

    def test_chat_ui_uses_authenticated_api_and_explicit_message_selection(self):
        self.assertIn("projectRequest('/v1/chat/status',{})", JS)
        self.assertIn("projectRequest('/v1/chat/configure',binding)", JS)
        self.assertIn('id="external-backend-form"', HTML)
        self.assertIn('type="password"', HTML)
        self.assertIn('href="https://platform.openai.com/api-keys"', HTML)
        self.assertIn("projectRequest('/v1/external/status',{})", JS)
        self.assertIn("projectRequest('/v1/external/configure',binding)", JS)
        self.assertIn('id="external-load-models"', HTML)
        self.assertIn('id="external-models"', HTML)
        self.assertIn("projectRequest('/v1/external/models',{})", JS)
        self.assertIn('id="external-preview-button"', HTML)
        self.assertIn('id="external-propose-button"', HTML)
        self.assertIn('id="external-proposal-messages"', HTML)
        self.assertIn('id="external-privacy-confirm"', HTML)
        self.assertIn("projectRequest('/v1/external/propose',request,210000)", JS)
        self.assertIn("fetch('/v1/external/send-stream'", JS)
        self.assertIn("event.type==='delta'", JS)
        self.assertIn("projectRequest('/v1/external/request',{run_id:turn.run_id})", JS)
        self.assertIn('Zobrazit odeslaný request', JS)
        self.assertIn('Ollama nevrátila platný návrh externího volání',
                      Path('spikes/desktop_ui.py').read_text())
        self.assertIn('Externí LLM odpověď nebylo možné bezpečně přijmout',
                      Path('spikes/desktop_ui.py').read_text())
        self.assertIn("'/v1/tasks/'", Path('spikes/desktop_ui.py').read_text())
        self.assertIn('error.status=response.status', JS)
        self.assertIn('if(error.status===422)pendingChatRequest=null', JS)
        self.assertIn('Ollama vrátila neplatný formát výsledku úlohy',
                      Path('spikes/desktop_ui.py').read_text())
        self.assertIn("projectRequest('/v1/external/preview',request)", JS)
        self.assertIn("projectRequest('/v1/external/confirm'", JS)
        self.assertIn("projectRequest('/v1/external/cancel'", JS)
        self.assertIn('preview_sha256:preview.preview_sha256', JS)
        self.assertIn("fields.secret.value=''", JS)
        self.assertIn("administration.hidden=selected.id==='settings-backend-tab'", JS)
        self.assertIn("const reloaded=await loadBackendBinding()", JS)
        self.assertIn("Poslední potvrzené nastavení bylo znovu načteno.", JS)
        self.assertIn("projectRequest('/v1/tasks/route',pendingChatRequest,210000)", JS)
        self.assertIn("projectRequest('/v1/tasks/list',{project_id:activeProject.id})", JS)
        self.assertIn("projectRequest('/v1/tasks/artifact'", JS)
        self.assertIn("projectRequest('/v1/tasks/external/preview'", JS)
        self.assertIn("projectRequest('/v1/tasks/external/confirm'", JS)
        self.assertIn("projectRequest('/v1/tasks/external/cancel'", JS)
        self.assertIn("typeof projection.external_answer==='string'", JS)
        self.assertIn('answer.textContent=projection.external_answer', JS)
        self.assertIn('id="task-artifact-list"', HTML)
        self.assertIn('id="advanced-external"', HTML)
        self.assertIn("body.textContent=outcome.content", JS)
        self.assertNotIn('innerHTML=outcome', JS)
        self.assertIn("selected_message_ids:selectedMessages.map", JS)
        self.assertIn("activeThread?.thread_id===threadId ? activeThread.messages : []", JS)
        self.assertIn("querySelectorAll('#task-artifact-list input:checked')", JS)
        self.assertIn("activeThread=null;activeTaskThreadId=null;taskOutcomes=[];pendingChatRequest=null", JS)
        self.assertIn("querySelector('#chat-new-thread').addEventListener", JS)
        self.assertIn("++chatSelectionRevision;pendingChatRequest=null;activeTaskThreadId=crypto.randomUUID()", JS)
        self.assertIn('if(selectionRevision!==chatSelectionRevision)return', JS)
        self.assertIn("project_id:failed.project_id,thread_id:failed.thread_id", JS)
        self.assertNotIn("}catch(error){await loadChat();chatOperationStatus.textContent=error.message;}", JS)
        self.assertIn("projectRequest('/v1/chat/assign'", JS)
        self.assertIn("projectRequest('/v1/chat/snapshot'", JS)
        self.assertIn("projectRequest('/v1/chat/output'", JS)
        self.assertIn('id="chat-mode"', HTML)
        self.assertIn('id="chat-run-adapter"', HTML)
        self.assertIn('id="chat-run-model"', HTML)
        self.assertIn('id="backend-metrics" hidden', HTML)
        self.assertIn('id="backend-metrics-indicator" hidden', HTML)
        self.assertIn("projectRequest('/v1/backend-metrics/status',{})", JS)
        self.assertIn("projectRequest('/v1/backend-metrics/configure'", JS)
        self.assertIn("projectRequest('/v1/backend-metrics/refresh'", JS)
        self.assertIn("projectRequest('/v1/chat/orchestration'", JS)
        self.assertIn("mode==='brainstorming' && adapter==='openai-responses'", JS)
        self.assertIn("mode==='brainstorming' && adapter==='ollama'", JS)
        self.assertIn("projectRequest('/v1/chat/send',pendingChatRequest,210000)", JS)
        self.assertIn('selected_artifact_ids:[]', JS)
        self.assertIn('run_choice:runChoice', JS)

    def test_chat_progress_stays_with_prompt(self):
        from spikes.desktop_ui import HTML
        composer = HTML.split('<form id="chat-composer">', 1)[1].split('</form>', 1)[0]
        self.assertIn('id="chat-operation-status"', composer)
        self.assertIn("chatOperationStatus.textContent='Odesílám…'", JS)
        self.assertIn("chatOperationStatus.textContent='Model přemýšlí…'", JS)

    def test_node_settings_are_global_and_backend_form_is_not_duplicated(self):
        from spikes.desktop_ui import HTML
        from spikes.desktop_management import ASSETS
        desktop_html = ASSETS['/'][1]
        self.assertIn('id="backend-metrics"', desktop_html)
        self.assertNotIn('id="backend-metrics" hidden', desktop_html)
        self.assertNotIn('id="backend-metrics-indicator" hidden', desktop_html)
        self.assertIn('#backend-metrics-indicator{position:fixed', ASSETS['/app.css'][1])
        self.assertEqual(HTML.count('id="chat-backend-form"'), 1)
        self.assertIn('id="settings-view"', HTML)
        self.assertIn('id="open-settings"', HTML)
        self.assertIn('id="chat-open-settings"', HTML)
        self.assertNotIn('id="chat-backend-settings"', HTML)
        self.assertIn("settingsReturn={project:!!activeProject,tabId:", JS)
        self.assertIn("document.querySelector('#project-home').hidden=true", JS)
        self.assertIn("const tab=document.getElementById(destination.tabId)", JS)
        self.assertIn("await loadBackendBinding()", JS)
        self.assertIn("projectRequest('/v1/chat/configure',binding)", JS)
        self.assertIn('id="settings-users-tab"', desktop_html)
        self.assertIn('id="settings-federation-tab"', desktop_html)
        self.assertNotIn('id="settings-users-tab" type="button" data-desktop="true" role="tab" aria-selected="false" aria-controls="admin-users-panel" tabindex="-1" hidden', desktop_html)
        settings = desktop_html.split('id="settings-view"', 1)[1].split('id="project-view"', 1)[0]
        self.assertIn('id="administration" class="settings-card"', settings)
        self.assertNotIn('<dialog', settings)
        self.assertNotIn('id="administration-open"', settings)

    def test_summary_ui_uses_explicit_selection_preview_and_confirmation(self):
        from spikes.desktop_ui import HTML
        self.assertIn('id="summary-tab"', HTML)
        self.assertIn('id="summary-artifact-list"', HTML)
        self.assertIn("projectRequest('/v1/summary/preview',pendingSummaryRequest,210000)", JS)
        self.assertIn("projectRequest('/v1/summary/publish',pendingSummaryPublish)", JS)
        self.assertIn("selection={kind:'artifacts',artifact_ids:ids}", JS)
        self.assertIn("selection={kind:'messages'", JS)
        self.assertIn("item.textContent=heading?heading[2]:line", JS)
        self.assertNotIn('summaryPreviewElement.innerHTML', JS)

    def test_extraction_ui_uses_closed_schema_safe_preview_and_confirmation(self):
        from spikes.desktop_ui import HTML
        self.assertIn('id="extraction-tab"', HTML)
        self.assertIn('value="facts|facts-v1"', HTML)
        self.assertIn('value="action-items|action-items-v1"', HTML)
        self.assertIn('id="extraction-kind"', HTML)
        self.assertIn("projectRequest('/v1/extraction/preview',pendingExtractionRequest,210000)", JS)
        self.assertIn("projectRequest('/v1/extraction/publish',pendingExtractionPublish)", JS)
        self.assertIn("extractionPreviewElement.textContent=JSON.stringify", JS)
        self.assertIn("selection={kind:'messages'", JS)
        self.assertNotIn('extractionPreviewElement.innerHTML', JS)
        self.assertIn("result.format==='json'", JS)

    def test_metadata_ui_uses_safe_diff_and_explicit_field_confirmation(self):
        from spikes.desktop_ui import HTML
        self.assertIn('id="metadata-tab"', HTML)
        self.assertIn('id="metadata-artifact"', HTML)
        self.assertIn("projectRequest('/v1/metadata-suggestions/preview',pendingMetadataRequest,210000)", JS)
        self.assertIn("projectRequest('/v1/metadata-suggestions/publish',pendingMetadataPublish)", JS)
        self.assertIn("description.checked=false", JS)
        self.assertIn("querySelectorAll('#metadata-tag-list input:checked')", JS)
        self.assertIn("textContent='Původní: '", JS)
        self.assertNotIn('metadata-diff.innerHTML', JS)

    def test_credentials_are_restricted_to_exact_api_and_initiator(self):
        origin = 'http://127.0.0.1:1234'
        self.assertEqual(request_policy(origin + '/', '', 'GET', origin), 'allow')
        self.assertEqual(request_policy(origin + '/app.js', origin, 'GET', origin), 'allow')
        self.assertEqual(request_policy(origin + '/v1/counter', origin + '/', 'POST', origin), 'authenticate')
        for url, initiator, method in [
            (origin + '/v1/counter', '', 'POST'),
            (origin + '/v1/counter', 'http://evil.example', 'POST'),
            (origin + '/v1/counter', origin, 'GET'),
            (origin + '/v1/counter?x=1', origin, 'POST'),
            ('http://127.0.0.1:1235/v1/counter', origin, 'POST'),
            ('http://user@127.0.0.1:1234/v1/counter', origin, 'POST'),
            ('https://evil.example/', origin, 'GET'),
            (origin + '/#create-main-todo', origin, 'GET'),
            (origin + '/native/main-todo', origin, 'POST'),
            ('file:///etc/passwd', origin, 'GET'),
            ('data:text/html,test', origin, 'GET'),
        ]:
            with self.subTest(url=url, initiator=initiator):
                self.assertEqual(request_policy(url, initiator, method, origin), 'block')

    def test_provider_key_onboarding_uses_only_exact_system_browser_url(self):
        approved = 'https://platform.openai.com/api-keys'
        self.assertEqual(provider_key_url(approved), approved)
        for url in ('https://platform.openai.com/api-keys?next=evil',
                    'https://platform.openai.com.evil.example/api-keys',
                    'https://evil.example/', 'http://platform.openai.com/api-keys'):
            with self.subTest(url=url):
                self.assertIsNone(provider_key_url(url))

    def test_assets_do_not_bootstrap_token_and_api_still_requires_auth(self):
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            for path in ('/', '/app.js', '/app.css'):
                response = driver.request(server, method='GET', path=path, headers={'Authorization': None})
                self.assertTrue(response.startswith(b'HTTP/1.0 200'))
                self.assertIn(b"frame-ancestors 'none'", response)
                self.assertNotIn(server.token.encode(), response)
                self.assertNotIn(b'Access-Control-Allow-Origin', response)
            driver.rejected(server, headers={'Authorization': None})
            driver.rejected(server, method='GET', path='/', headers={'Host': 'evil.example'})
            for path in ('/../requirements.txt', '/?token=x', '/favicon.ico'):
                driver.rejected(server, method='GET', path=path)
            endpoint = server.server_address
        with self.assertRaises(OSError):
            socket.create_connection(endpoint, timeout=1)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Set M0_DESKTOP_TEST=1 for real Qt/WebEngine smoke')
    def test_real_webengine_click_close_and_restart(self):
        for _ in range(2):
            result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--smoke'],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                    text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('authenticated fetch, value=1', result.stdout)
            self.assertIn('backend stopped', result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_renderer_crash_exits_with_failure(self):
        result = subprocess.run([sys.executable, '-m', 'spikes.desktop', '--smoke', '--smoke-crash'],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=25)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn('backend stopped', result.stdout)
