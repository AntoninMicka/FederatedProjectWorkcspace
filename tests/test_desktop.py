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

from spikes.desktop import native_action_name, provider_key_url, request_policy
from spikes.desktop_ui import CSS, DesktopHandler, HTML, JS
from spikes.local_api import running_api
from spikes.metadata import ValidationError
from spikes.ollama_backend import OllamaResponseError, UnknownRun
from tests import test_local_api


class DesktopTests(unittest.TestCase):
    def test_chat_validation_returns_only_actionable_allowlisted_reason(self):
        driver = test_local_api.LocalAPITests()
        request = {key: None for key in (
            'project_id', 'expected_head', 'thread_id', 'turn_id', 'message_id',
            'run_id', 'manifest_id', 'assistant_message_id', 'selected_message_ids',
            'content', 'privacy', 'created_at', 'run_choice')}
        cases = (
            ('Private-network orchestration requires explicit Ollama binding selection',
             'Orchestrace přes privátní síť vyžaduje explicitně vybraný aktuální backend.'),
            ('Selected orchestration binding changed',
             'Vybraný orchestrační backend se změnil.'),
            ('Project changed before chat dispatch',
             'Projekt se od otevření změnil.'),
            ('private path /secret must not leak',
             'Chat požadavek nelze provést.'),
        )
        for reason, expected in cases:
            class Service:
                def send(self, **_request):
                    raise ValidationError(reason)
            with self.subTest(reason=reason), running_api(
                    'http', handler=DesktopHandler) as server:
                server.chat_service = Service()
                response = driver.request(server, path='/v1/chat/send',
                                          body=json.dumps(request).encode())
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 422 ', head)
            message = json.loads(body)['error']
            self.assertIn(expected, message)
            self.assertNotIn('/secret', message)

    def test_ollama_diagnostic_response_distinguishes_failed_and_unknown(self):
        driver = test_local_api.LocalAPITests()
        cases = ((OllamaResponseError('pin', code='tls-pin-mismatch'), 502,
                  'tls-pin-mismatch', 'failed'),
                 (UnknownRun('timeout', code='response-timeout'), 409,
                  'response-timeout', 'unknown'))
        for error, status, diagnostic, outcome in cases:
            class Service:
                def test_binding(self, request):
                    raise error
            with self.subTest(diagnostic=diagnostic), running_api(
                    'http', handler=DesktopHandler) as server:
                server.chat_service = Service()
                response = driver.request(server, path='/v1/chat/test', body=b'{}')
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(f' {status} '.encode(), head)
            payload = json.loads(body)
            self.assertEqual((payload['diagnostic'], payload['outcome'], payload['retry']),
                             (diagnostic, outcome, 'new-run'))

    def test_notebooklm_desktop_uses_shared_page_and_exact_native_capabilities(self):
        desktop = Path('spikes/desktop.py').read_text()
        self.assertNotIn('NotebookLMImportDialog', desktop)
        self.assertFalse(Path('spikes/desktop_notebooklm_import.py').exists())
        self.assertIn("'choose-notebooklm-archive'", desktop)
        self.assertIn('register_archive(archive)', desktop)
        self.assertIn('register_target(', desktop)
        self.assertIn('id="open-notebooklm-import"', HTML)
        self.assertIn('<div id="notebooklm-import-view" hidden>', HTML)
        self.assertIn('id="notebooklm-import"', HTML)
        self.assertIn("requestNativeAction('choose-notebooklm-target')", JS)
        self.assertIn('setNotebookLMNativeError', JS)
        self.assertIn("projectRequest('/v1/notebooklm/preview'", JS)
        self.assertIn("projectRequest('/v1/notebooklm/plan'", JS)
        self.assertIn("projectRequest('/v1/notebooklm/confirm'", JS)
        self.assertIn('archive_capability:notebookArchiveCapability', JS)

    def test_native_picker_actions_require_fresh_exact_local_capability_url(self):
        origin = 'http://127.0.0.1:4711'
        nonce = '5d81c0bc-b5b4-4ca9-bf9f-f4d77f98f181'
        self.assertEqual(native_action_name(
            f'{origin}/#choose-notebooklm-target&nonce={nonce}', origin),
            'choose-notebooklm-target')
        for url in (f'{origin}/#choose-notebooklm-target',
                    f'{origin}/#choose-notebooklm-target&nonce=invalid',
                    f'{origin}/other#choose-notebooklm-target&nonce={nonce}',
                    f'{origin}/?x=1#choose-notebooklm-target&nonce={nonce}',
                    f'http://localhost:4711/#choose-notebooklm-target&nonce={nonce}',
                    f'{origin}/#unknown&nonce={nonce}'):
            with self.subTest(url=url):
                self.assertIsNone(native_action_name(url, origin))

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
        self.assertIn("if([409,422,502].includes(error.status))pendingChatRequest=null", JS)
        self.assertIn("'/v1/chat/test'", JS)
        self.assertIn('Ověřit bez uložení', HTML)
        self.assertIn('binding_draft_state', JS)
        self.assertIn('normalizeFingerprint', JS)
        ollama_form = HTML.split('id="chat-backend-form"', 1)[1].split('</form>', 1)[0]
        self.assertNotIn('pattern="[0-9a-f]{64}"', ollama_form)
        self.assertIn('Zadání a výběr zůstaly zachovány', JS)
        self.assertIn('Ollama vrátila neplatný formát výsledku úlohy',
                      Path('spikes/desktop_ui.py').read_text())
        self.assertIn("projectRequest('/v1/external/preview',request)", JS)
        self.assertIn("projectRequest('/v1/external/confirm'", JS)
        self.assertIn("projectRequest('/v1/external/cancel'", JS)
        self.assertIn('preview_sha256:preview.preview_sha256', JS)
        self.assertIn("fields.secret.value=''", JS)
        self.assertIn("administration.hidden=!['settings-users-tab','settings-federation-tab'].includes(selected.id)", JS)
        self.assertIn("const reloaded=await loadBackendBinding()", JS)
        self.assertIn("Poslední potvrzené nastavení bylo znovu načteno.", JS)
        self.assertIn("projectRequest('/v1/tasks/route',pendingChatRequest,210000)", JS)
        self.assertIn("projectRequest('/v1/tasks/list',{", JS)
        self.assertIn("project_id:thread.project_id,thread_id:thread.thread_id", JS)
        self.assertIn("projectRequest('/v1/chat/delete/preview'", JS)
        self.assertIn("projectRequest('/v1/chat/delete/confirm'", JS)
        self.assertTrue({'/v1/chat/archive', '/v1/chat/delete/preview',
                         '/v1/chat/delete/confirm', '/v1/sources/import'} <= DesktopHandler.post_paths)
        self.assertNotIn('id="chat-thread-list"', HTML)
        self.assertIn('id="chats-tab"', HTML)
        self.assertIn('id="back-projects" class="sidebar-back"', HTML)
        self.assertNotIn('id="back-projects" class="back-button"', HTML)
        self.assertIn('id="sidebar-chat-tree" role="tree"', HTML)
        sidebar_chats = HTML.split('id="sidebar-chats"', 1)[1].split('</div></div>', 1)[0]
        self.assertLess(sidebar_chats.index('id="chat-new-thread"'),
                        sidebar_chats.index('id="sidebar-chat-tree"'))
        self.assertLess(sidebar_chats.index('id="chat-open-settings"'),
                        sidebar_chats.index('id="sidebar-chat-tree"'))
        self.assertIn("branch('Zařazené',assigned);branch('Nezařazené',unassigned)", JS)
        self.assertIn("if(!branchThreads.length)return", JS)
        self.assertIn("root.setAttribute('role','treeitem')", JS)
        self.assertNotIn('id="chat-archive-thread"', HTML)
        self.assertNotIn('id="chat-delete-thread"', HTML)
        self.assertNotIn('id="chat-record-actions"', HTML)
        self.assertNotIn("querySelector('#chat-record-actions')", JS)
        self.assertIn("action('Archivovat',archiveActiveThread", JS)
        self.assertIn("action('Připravit smazání',prepareActiveThreadDeletion)", JS)
        self.assertIn("action('Uložit otisk',button=>runChatRecord(button,'snapshot')", JS)
        self.assertIn("action('Uložit poslední odpověď',button=>runChatRecord(button,'output')", JS)
        self.assertIn("trigger.setAttribute('aria-label',`Akce chatu", JS)
        self.assertIn('.sidebar-chat-menu-items{position:absolute', CSS)
        self.assertIn("openStoredThread(thread.thread_id)", JS)
        self.assertIn("function rememberThread(thread)", JS)
        self.assertIn("renderChat(assigned);rememberThread(assigned)", JS)
        self.assertIn("End:sidebarTabs.length-1", JS)
        self.assertIn("selectMainTab(document.querySelector('#chat-tab'))", JS)
        self.assertIn('flex-direction:column;overflow:hidden', CSS)
        self.assertIn('#sidebar-project-tools>[role="tabpanel"]:not([hidden])', CSS)
        self.assertIn('#sidebar-project-list,#todo-tree,#sidebar-artifact-list,#sidebar-chat-tree', CSS)
        self.assertIn('overflow-y:auto;overscroll-behavior:contain', CSS)
        self.assertIn('id="open-source-import"', HTML)
        self.assertIn('id="source-import-view" hidden', HTML)
        self.assertIn('id="source-import-form"', HTML)
        self.assertLess(HTML.index('id="source-import-view"'), HTML.index('id="project-view"'))
        self.assertIn("projectRequest('/v1/sources/import',sourceImportAttempt.request,120000)", JS)
        self.assertIn('id="history-view" hidden', HTML)
        self.assertNotIn('id="preview-history"', HTML)
        self.assertIn('id="history-close"', HTML)
        self.assertIn("projectRequest('/v1/artifacts/history/list'", JS)
        self.assertIn("projectRequest('/v1/artifacts/history/compare'", JS)
        self.assertIn("if(item.kind==='document')", JS)
        self.assertIn("history.textContent='Zobrazit historii'", JS)
        self.assertIn("await openPreview(item.id);if(selectedArtifact===item.id)await openHistory()", JS)
        self.assertIn('sidebar-artifact-menu-items', CSS)
        self.assertIn("action('Upravit / přejmenovat'", JS)
        self.assertIn("action('Připravit smazání'", JS)
        self.assertIn("action('Kopírovat ID'", JS)
        self.assertIn('id="artifact-editor-view" hidden', HTML)
        self.assertIn('id="new-document"', HTML)
        self.assertIn("projectRequest('/v1/artifacts/editor/open'", JS)
        self.assertIn("projectRequest('/v1/artifacts/editor/save',{operation_id:artifactEditorAttempt.operation_id,document:artifactEditorAttempt.document}", JS)
        self.assertIn('new:Boolean(artifactEditorItem.new)', JS)
        self.assertIn('function openMainTodoEditor()', JS)
        self.assertNotIn("'/#create-main-todo'", Path('spikes/desktop.py').read_text())
        self.assertIn("projectRequest('/v1/artifacts/delete/preview'", JS)
        self.assertIn("projectRequest('/v1/artifacts/delete/confirm'", JS)
        self.assertIn('operation_id:artifactDeleteOperation', JS)
        self.assertIn("document.querySelector('#history-body').textContent", JS)
        self.assertNotIn('innerHTML=result.after', JS)
        self.assertTrue({'/v1/artifacts/history/list', '/v1/artifacts/history/compare'} <= DesktopHandler.post_paths)
        self.assertIn('id="chat-delete-preview"', HTML)
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
        self.assertIn("chatBinding.boundary==='private-network'", JS)
        self.assertIn("mode==='orchestration'", JS)
        self.assertIn('runChoice.binding_id=chatBinding.binding_id', JS)
        self.assertIn('runChoice.binding_revision=chatBinding.revision', JS)
        self.assertNotIn('Orchestrace vyžaduje Ollamu na stejném uzlu', JS)
        self.assertIn("value==='local-only'", JS)
        self.assertIn('selected_artifact_ids:[]', JS)
        self.assertIn('run_choice:runChoice', JS)

    def test_chat_progress_stays_with_prompt(self):
        from spikes.desktop_ui import HTML
        composer = HTML.split('<form id="chat-composer">', 1)[1].split('</form>', 1)[0]
        self.assertIn('id="chat-operation-status"', composer)
        self.assertIn("chatOperationStatus.textContent='Odesílám…'", JS)
        self.assertIn("chatOperationStatus.textContent='Model přemýšlí…'", JS)

    def test_orchestration_shows_the_configured_ollama_boundary(self):
        self.assertIn('id="chat-orchestration-target"', HTML)
        self.assertIn("lan?'Ollama v privátní síti':'Ollama na tomto uzlu'", JS)
        self.assertIn('Orchestrace použije ${chatBinding.model}', JS)
        self.assertIn("lan?'privátní síť':'tento uzel'", JS)
        self.assertIn('${chatBinding.endpoint}', JS)

    def test_node_settings_are_global_and_backend_form_is_not_duplicated(self):
        from spikes.desktop_ui import HTML
        from spikes.desktop_management import ASSETS, DESKTOP_BOOTSTRAP
        desktop_html = ASSETS['/'][1]
        self.assertIn('id="backend-metrics"', desktop_html)
        self.assertEqual(desktop_html, HTML)
        self.assertEqual(ASSETS['/app.css'][1], CSS)
        self.assertEqual(ASSETS['/app.js'][1], DESKTOP_BOOTSTRAP + JS)
        self.assertIn("'backend-metrics','backend-metrics-indicator'", DESKTOP_BOOTSTRAP)
        self.assertIn("getElementById('project-location-controls').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn('id="project-create-preview"', HTML)
        self.assertIn("requestNativeAction('choose-project-location')", JS)
        self.assertNotIn('CreationDialog', Path('spikes/desktop_creation.py').read_text())
        self.assertIn('#backend-metrics-indicator{position:fixed', ASSETS['/app.css'][1])
        self.assertEqual(HTML.count('id="chat-backend-form"'), 1)
        self.assertIn('id="settings-view"', HTML)
        self.assertIn('id="settings-cms-tab"', HTML)
        self.assertIn('id="cms-module"', HTML)
        self.assertIn('id="cms-enable"', HTML)
        self.assertIn('id="cms-disable"', HTML)
        self.assertIn('id="cms-add-domain"', HTML)
        self.assertIn('id="cms-remove-domain"', HTML)
        self.assertIn('id="cms-section-profile"', HTML)
        self.assertIn('id="cms-section-cv"', HTML)
        self.assertIn('id="cms-section-timeline"', HTML)
        self.assertIn("sections:['profile']", JS)
        self.assertIn("site.sections=['profile','cv','timeline'].filter", JS)
        self.assertIn('id="cms-preview-frame" sandbox', HTML)
        self.assertIn("projectRequest('/v1/publication-cms/status',{})", JS)
        self.assertIn("projectRequest('/v1/publication-cms/configure'", JS)
        self.assertIn("module_id:'cz.proofofidea.publication-experiment-registry'", JS)
        self.assertIn("projectRequest('/v1/publication-cms/preview'", JS)
        self.assertIn("projectRequest('/v1/publication-cms/generate'", JS)
        self.assertIn('id="cms-deployment-form"', HTML)
        self.assertIn('id="cms-deployment-confirm"', HTML)
        self.assertIn("projectRequest('/v1/publication-cms/deployment/status'", JS)
        self.assertIn("projectRequest('/v1/publication-cms/deployment/preview'", JS)
        self.assertIn("projectRequest('/v1/publication-cms/deployment/confirm'", JS)
        self.assertIn("form.elements.api_token.value=''", JS)
        self.assertIn('custom domain: ${item.custom_domain}', JS.lower())
        self.assertIn('preview_sha256:cmsPreview.result.preview_sha256', JS)
        self.assertIn('approved:true', JS)
        self.assertIn('srcdoc=result.html', JS)
        self.assertNotIn('innerHTML=result.html', JS)
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
        self.assertNotIn('id="settings-cms-tab" type="button" data-desktop="true" role="tab" aria-selected="false" aria-controls="settings-cms-panel" tabindex="-1" hidden', desktop_html)
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

    def test_role_workflow_ui_separates_both_approvals_and_publication(self):
        from spikes.desktop_ui import HTML
        self.assertIn('id="workflow-tab"', HTML)
        self.assertIn('id="workflow-creator-confirm"', HTML)
        self.assertIn('id="workflow-opponent-confirm"', HTML)
        self.assertIn('id="workflow-publish-step"', HTML)
        self.assertIn("projectRequest('/v1/workflows/prepare'", JS)
        self.assertIn("projectRequest('/v1/workflows/creator/dispatch'", JS)
        self.assertIn("projectRequest('/v1/workflows/opponent/prepare'", JS)
        self.assertIn("projectRequest('/v1/workflows/opponent/dispatch'", JS)
        self.assertIn("projectRequest('/v1/workflows/publish'", JS)
        self.assertIn("section.querySelector('pre').textContent", JS)
        self.assertNotIn('workflow-creator-result.innerHTML', JS)

    def test_image_ui_separates_preview_dispatch_and_project_publication(self):
        self.assertIn('id="image-tab"', HTML)
        self.assertIn('id="image-request-preview"', HTML)
        self.assertIn('id="image-confirm"', HTML)
        self.assertIn('id="image-result-preview"', HTML)
        self.assertIn("projectRequest('/v1/media/preview',pendingImageRequest)", JS)
        self.assertIn("projectRequest('/v1/media/confirm'", JS)
        self.assertIn("projectRequest('/v1/media/publish',pendingImagePublish", JS)
        self.assertIn("projectRequest('/v1/media/openai/configure'", JS)
        self.assertIn("preview.src='data:image/png;base64,'+imageResult.image_base64", JS)
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
        self.assertIn("document.createElement('ul')", JS)

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
