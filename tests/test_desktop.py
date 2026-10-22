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
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from uuid import uuid4

from spikes.desktop import (google_authorization_url, native_action_name, native_action_request, notebooklm_target_error,
                            presentation_pdf_js_request, presentation_pdf_paths, provider_key_url,
                            publish_presentation_pdf,
                            repairable_target_mode, request_policy)
from spikes.desktop_ui import CSS, DESKTOP_BOOTSTRAP, DesktopHandler, HTML, JS
from spikes.presentation_visual import SLIDE_JS
from spikes.local_api import running_api
from spikes.metadata import ValidationError
from spikes.ollama_backend import OllamaResponseError, UnknownRun
from spikes.web_search import SearchResponseError
from spikes.gamepad_settings import DEFAULT_GAMEPAD_SETTINGS, GamepadSettings
from spikes.presentation_documents import PresentationDocuments
from spikes.public_source import PublicSourceRejected, PublicSourceUnknown
from spikes.project_creation import ProjectCreation
from tests import test_local_api


class DesktopTests(unittest.TestCase):
    def test_web_search_ui_requires_exact_preview_and_renders_sources_as_text(self):
        composer = HTML.split('<form id="chat-composer">', 1)[1].split('</form>', 1)[0]
        chat_panel = HTML.split('<div id="chat-panel"', 1)[1].split(
            '<div id="summary-panel"', 1)[0]
        self.assertIn('id="search-backend-form"', HTML)
        self.assertIn('id="search-preview"', HTML)
        self.assertIn('id="search-recovery"', HTML)
        self.assertNotIn('id="search-preview"', composer)
        self.assertNotIn('id="search-recovery"', composer)
        self.assertIn('id="search-preview"', chat_panel)
        self.assertIn('id="search-recovery"', chat_panel)
        self.assertIn('#search-preview pre', CSS)
        self.assertIn('id="search-confirm-check"', HTML)
        self.assertIn("projectRequest('/v1/search/test',searchCandidate(),65000)", JS)
        self.assertIn("projectRequest('/v1/search/configure',searchCandidate())", JS)
        self.assertIn("projectRequest('/v1/search/configure',searchRecoveryBinding)", JS)
        self.assertIn("offerSearchRecovery(error,preview.binding)", JS)
        self.assertIn("projectRequest('/v1/tasks/search/preview',request)", JS)
        self.assertIn("projectRequest('/v1/tasks/search/confirm'", JS)
        self.assertIn("outcome.kind==='web-search-answer'", JS)
        self.assertIn('url.textContent=source.url', JS)
        self.assertIn('snippet.textContent=source.snippet', JS)
        self.assertNotIn('.href=source.url', JS)
        self.assertIn('renderSearchWorkflow(card,projection.search_workflow,projection)', JS)
        self.assertIn('Zkontrolovat další dotaz:', JS)
        self.assertIn("projection.outcome?.kind==='web-search'", JS)
        self.assertIn("'Zpřesněte další kolo hledání…'", JS)
        self.assertIn('Výsledek není konečný. Zpřesnění dalšího kola napište do pole dole.', JS)
        self.assertIn('prepareTaskSearch(searchContinuation.projection,draft.value.trim()', JS)
        self.assertIn('Kolo není konečné. Napište do pole dole vlastní zpřesnění', JS)
        self.assertIn('Finálnost je hodnocení modelu', JS)
        self.assertIn('query===null && projection.search_preview', JS)
        self.assertIn('id="public-source-preview"', HTML)
        self.assertIn("existing?'Připravit nové načtení':'Načíst stránku'", JS)
        self.assertIn("projectRequest('/v1/tasks/public-source/preview',request)", JS)
        self.assertIn("projectRequest('/v1/tasks/public-source/confirm'", JS)
        self.assertIn("projectRequest('/v1/tasks/public-source/result'", JS)
        self.assertIn("result.querySelector('pre').textContent=fetched.text", JS)
        self.assertIn('do projektu nebylo nic zapsáno', JS)
        self.assertTrue({'/v1/search/status', '/v1/search/configure', '/v1/search/test',
                         '/v1/tasks/search/preview', '/v1/tasks/search/confirm',
                         '/v1/tasks/public-source/preview',
                         '/v1/tasks/public-source/confirm',
                         '/v1/tasks/public-source/result'}
                        <= DesktopHandler.post_paths)

    def test_public_source_diagnostics_distinguish_rejected_and_unknown(self):
        driver = test_local_api.LocalAPITests()
        cases = ((PublicSourceRejected('robots', code='robots-disallowed'), 422,
                  'rejected', 'robots.txt'),
                 (PublicSourceUnknown('lost', code='response-unknown'), 409,
                  'unknown', 'automaticky opakovat'))
        for error, status, outcome, message in cases:
            class Service:
                def task_public_source_confirm(self, _request):
                    raise error
            with self.subTest(outcome=outcome), running_api(
                    'http', handler=DesktopHandler) as server:
                server.chat_service = Service()
                response = driver.request(server, path='/v1/tasks/public-source/confirm',
                                          body=b'{}')
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(f' {status} '.encode(), head)
            payload = json.loads(body)
            self.assertEqual(payload['outcome'], outcome)
            self.assertIn(message, payload['error'])

    def test_presentation_task_has_exact_diff_and_separate_confirmation(self):
        self.assertIn("outcome.kind==='presentation-draft'?'Návrh prezentace'", JS)
        branch = JS.split("if(outcome.kind==='presentation-draft'){", 1)[1].split(
            "}else if(outcome.kind==='presentation-link')", 1)[0]
        self.assertIn("taskButton('Zahodit'", branch)
        self.assertIn('Návrh není uložený.', branch)
        self.assertIn('projection.presentation_approval', branch)
        self.assertIn("projectRequest('/v1/tasks/presentation/confirm'", branch)
        self.assertIn("'Schválit a vytvořit'", branch)
        self.assertIn('approval.approval_digest', branch)
        self.assertIn('JSON.stringify({akce:change.action,před:change.before,po:change.after}', branch)
        self.assertNotIn('/v1/presentations/save', branch)
        self.assertTrue({'/v1/tasks/presentation/confirm'} <= DesktopHandler.post_paths)

    def test_project_removal_ui_has_separate_preview_restore_and_purge_approvals(self):
        self.assertIn('id="project-delete-panel"', HTML)
        self.assertIn('id="project-trash-list"', HTML)
        self.assertIn('id="project-trash-view" hidden', HTML)
        self.assertIn('id="sidebar-project-trash"', HTML)
        self.assertIn('id="dashboard-trash"', HTML)
        self.assertIn("if(!openProjectTrashView())return", JS)
        for path in ('/v1/projects/delete/preview', '/v1/projects/delete/confirm',
                     '/v1/projects/delete/restore/preview',
                     '/v1/projects/delete/restore/confirm',
                     '/v1/projects/delete/purge/preview',
                     '/v1/projects/delete/purge/confirm'):
            self.assertIn(path, JS)
        self.assertIn('Vzdálené a dříve sdílené kopie zůstanou zachovány.', JS)
        self.assertIn('projectDeleteCheck.checked=false', JS)
        self.assertNotIn("scrollIntoView({block:'nearest'})", JS)

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

    def test_missing_search_binding_has_actionable_diagnostic(self):
        class Service:
            def task_search_preview(self, _request):
                raise SearchResponseError('missing', code='not-configured')
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            server.chat_service = Service()
            response = driver.request(server, path='/v1/tasks/search/preview', body=b'{}')
        head, body = response.split(b'\r\n\r\n', 1)
        self.assertIn(b' 422 ', head)
        payload = json.loads(body)
        self.assertEqual(payload['diagnostic'], 'not-configured')
        self.assertEqual(payload['retry'], 'configure-search')
        self.assertIn('Nastavení', payload['error'])

    def test_invalid_search_evaluation_has_actionable_diagnostic(self):
        class Service:
            def task_search_confirm(self, _request):
                raise ValidationError(
                    'Ollama returned an invalid iterative search evaluation')
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            server.chat_service = Service()
            response = driver.request(server, path='/v1/tasks/search/confirm', body=b'{}')
        head, body = response.split(b'\r\n\r\n', 1)
        self.assertIn(b' 422 ', head)
        message = json.loads(body)['error']
        self.assertIn('neplatné hodnocení výsledků hledání', message)
        self.assertIn('Zahoďte tento návrh', message)

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
        self.assertIn("requestNativeAction('choose-notebooklm-target',request)", JS)
        self.assertIn('setNotebookLMNativeError', JS)
        self.assertNotIn("page.runJavaScript('notebookLMTargetPickerRequest()'", desktop)
        self.assertIn('id="notebooklm-destination"', HTML)
        self.assertIn("notebookPlan.target_root", JS)
        self.assertIn("projectRequest('/v1/notebooklm/preview'", JS)
        self.assertIn("projectRequest('/v1/notebooklm/plan'", JS)
        self.assertIn("projectRequest('/v1/notebooklm/confirm'", JS)
        self.assertIn('archive_capability:notebookArchiveCapability', JS)

    def test_presentation_editor_is_integrated_in_shared_workspace(self):
        desktop = Path('spikes/desktop.py').read_text()
        self.assertNotIn("QPushButton('Prezentace…')", desktop)
        self.assertNotIn('PresentationEditorDialog', desktop)
        self.assertIn('id="presentation-tab"', HTML)
        self.assertIn('id="presentations-tab"', HTML)
        self.assertIn('id="sidebar-presentation-list"', HTML)
        self.assertIn('aria-label="Prezentace ve výstupech projektu"', HTML)
        self.assertIn('renderSidebarPresentations', JS)
        self.assertIn("{label:'Upravit',run:()=>openPresentationEditor(doc.id)", JS)
        self.assertIn("{label:'Spustit',run:()=>usePresentationDocument(doc)", JS)
        self.assertIn("loadPresentationEditor(null,false)", JS)
        self.assertIn("renderSidebarPresentations();if(!openEditor)return", JS)
        self.assertIn('id="presentation-editor-workspace"', HTML)
        self.assertIn('id="presentation-editor-save"', HTML)
        self.assertIn("projectRequest('/v1/presentations/open'", JS)
        self.assertIn("projectRequest('/v1/presentations/save'", JS)
        self.assertIn("projectRequest('/v1/presentations/use'", JS)
        self.assertIn('id="presentation-template-select"', HTML)
        self.assertIn('id="presentation-template-copy"', HTML)
        self.assertIn('id="presentation-slide-layout"', HTML)
        self.assertIn("['title','title-content','two-column','visual','closing']", SLIDE_JS)
        self.assertIn("gridTemplateColumns:'1fr 1fr'", SLIDE_JS)
        self.assertIn('presentationVisualSlide', JS)
        self.assertIn('id="presentation-session-list"', HTML)
        self.assertIn("projectRequest('/v1/presentations/export/preview'", JS)
        self.assertIn('setPresentationPdfTarget', JS)
        self.assertIn('setPresentationPdfNativeError', JS)
        self.assertIn("JSON.stringify(presentationPdfTargetRequest())", desktop)
        self.assertIn("JSON.stringify(presentationPdfExportRequest())", desktop)
        self.assertIn("location.hash=`export-presentation-pdf?nonce=", JS)
        self.assertNotIn("location.hash='presentation-editor'", JS)
        self.assertIn('id="presenter-display-form"', HTML)
        self.assertIn("requestPresenterDisplayAction('presenter-displays-identify')", JS)
        self.assertIn("requestPresenterDisplayAction('presenter-displays-apply')", JS)
        self.assertIn("requestNativeAction('presenter-displays-cancel')", JS)
        self.assertIn('showPresenterDisplayConfiguration', JS)
        self.assertIn("typeof closePresenterDisplayConfiguration==='function'", desktop)

    def test_presentation_pdf_publication_is_same_directory_and_atomic(self):
        nonce = '5d81c0bc-b5b4-4ca9-bf9f-f4d77f98f181'
        with tempfile.TemporaryDirectory() as directory:
            target, temporary = presentation_pdf_paths(Path(directory) / 'deck', nonce)
            self.assertEqual(target.name, 'deck.pdf')
            self.assertEqual(temporary.parent, target.parent)
            target.write_bytes(b'old complete pdf')
            temporary.write_bytes(b'new complete pdf')
            publish_presentation_pdf(temporary, target)
            self.assertEqual(target.read_bytes(), b'new complete pdf')
            self.assertFalse(temporary.exists())
            temporary.write_bytes(b'')
            with self.assertRaises(OSError):
                publish_presentation_pdf(temporary, target)
            self.assertEqual(target.read_bytes(), b'new complete pdf')

    def test_presentation_pdf_javascript_bridge_is_explicit_and_bounded(self):
        nonce = '5d81c0bc-b5b4-4ca9-bf9f-f4d77f98f181'
        digest = 'a' * 64
        self.assertEqual(presentation_pdf_js_request(json.dumps({
            'nonce': nonce, 'preview_sha256': digest})),
            {'nonce': nonce, 'preview_sha256': digest})
        for invalid in ('', '{}', 'null', json.dumps({'nonce': nonce,
                        'preview_sha256': 'not-a-digest'}), json.dumps({
                            'nonce': nonce, 'preview_sha256': digest, 'extra': True})):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                presentation_pdf_js_request(invalid)

    def test_native_picker_actions_require_fresh_exact_local_capability_url(self):
        origin = 'http://127.0.0.1:4711'
        nonce = '5d81c0bc-b5b4-4ca9-bf9f-f4d77f98f181'
        operation = 'fbd03ac3-0bcf-443b-b54e-8f66b969d229'
        target_url = (f'{origin}/#choose-notebooklm-target?'
                      f'operation_id={operation}&nonce={nonce}')
        self.assertEqual(native_action_name(target_url, origin),
            'choose-notebooklm-target')
        self.assertEqual(native_action_request(target_url, origin),
                         {'action': 'choose-notebooklm-target', 'nonce': nonce,
                          'operation_id': operation})
        for action in ('register-project-location', 'recover-project-operation',
                       'choose-notebooklm-archive',
                       'choose-project-location',
                       'federation-transfer-open', 'federation-transfer-start',
                       'federation-network-open', 'federation-network-run',
                       'federation-deployment-open', 'federation-deployment-start'):
            with self.subTest(action=action):
                self.assertEqual(native_action_request(
                    f'{origin}/#{action}?nonce={nonce}', origin),
                    {'action': action, 'nonce': nonce})
        for action in ('relocate-project-location', 'unregister-missing-project'):
            with self.subTest(action=action):
                self.assertEqual(native_action_request(
                    f'{origin}/#{action}?project_id={operation}&nonce={nonce}', origin),
                    {'action': action, 'nonce': nonce, 'project_id': operation})
                self.assertIsNone(native_action_request(
                    f'{origin}/#{action}?project_id=bad&nonce={nonce}', origin))
        for action in ('choose-presentation-pdf', 'export-presentation-pdf'):
                self.assertEqual(native_action_request(
                    f'{origin}/#{action}?nonce={nonce}', origin),
                    {'action': action, 'nonce': nonce})
        token = '7461d65e-cc6c-4daa-8a88-1fe272eddf3d'
        for action in ('presenter-displays-identify', 'presenter-displays-apply'):
            url = (f'{origin}/#{action}?token={token}&speaker=0&audience=-1&nonce={nonce}')
            self.assertEqual(native_action_request(url, origin), {
                'action': action, 'nonce': nonce, 'token': token, 'speaker': 0, 'audience': -1})
            self.assertIsNone(native_action_request(url.replace('speaker=0', 'speaker=64'), origin))
            self.assertIsNone(native_action_request(url.replace(f'token={token}', 'token=bad'), origin))
        self.assertEqual(native_action_request(
            f'{origin}/#presenter-displays-cancel?nonce={nonce}', origin),
            {'action': 'presenter-displays-cancel', 'nonce': nonce})
        for url in (f'{origin}/#choose-notebooklm-target?nonce={nonce}',
                    f'{origin}/#choose-notebooklm-target?operation_id=invalid&nonce={nonce}',
                    f'{origin}/#choose-notebooklm-target?operation_id={operation}&nonce=invalid',
                    f'{origin}/other#choose-notebooklm-target?operation_id={operation}&nonce={nonce}',
                    f'{origin}/?x=1#choose-notebooklm-target?operation_id={operation}&nonce={nonce}',
                    f'http://localhost:4711/#choose-notebooklm-target?operation_id={operation}&nonce={nonce}',
                    f'{origin}/#unknown?nonce={nonce}'):
            with self.subTest(url=url):
                self.assertIsNone(native_action_name(url, origin))

    def test_notebooklm_target_permission_repair_is_narrow_and_errors_are_actionable(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'target'; target.mkdir(mode=0o700); target.chmod(0o775)
            self.assertEqual(repairable_target_mode(target), 0o775)
            (target / 'keep').write_text('x')
            self.assertIsNone(repairable_target_mode(target))
        self.assertIn('0700', notebooklm_target_error(
            ValueError('Directory must not be writable by other users')))
        self.assertIn('prázdná', notebooklm_target_error(
            ValueError('Existující cílová složka musí být prázdná.')))

    def test_presenter_next_preview_follows_tab_and_includes_notes(self):
        import shutil
        if not shutil.which('node'):
            self.skipTest('Node.js is required for presenter behavior validation')
        start = JS.index('function renderPresenterContent(')
        end = JS.index('function renderPresenterSlide()', start)
        harness = """
const assert=require('node:assert/strict');
const element=()=>({textContent:'',style:{},children:[],replaceChildren(){this.children=[];},append(...items){this.children.push(...items);},setAttribute(){},dataset:{}});
const elements={};
const document={createElement:element,querySelector(id){return elements[id]??=element();}};
const presenterPrivatePreview=element(),presenterNextPreview=element(),presenterNextButton=element();
let presenterNextSelection=null,presenterNextSelectionKind='main',presenterTabIndex=0,presenterIndex=0;
const presenterSlides=[{title:'Current'}, {title:'Next',body:'Main body',notes:'Main notes'}];
"""
        model = JS[JS.index('function createPresenterSequence('):
                   JS.index('function renderPresenterContent(')]
        checks = """
presenterSequence=createPresenterSequence(presenterSlides);
presenterSequence.commit(presenterSequence.current);
refreshPresenterNext();
assert.equal(presenterNextSelection,presenterSlides[1]);
assert.equal(elements['#presenter-next-notes'].textContent,'Main notes');
presenterSelectedBackup={title:'Backup',body:'Backup body',notes:'Backup notes'};
presenterSequence.chooseBackup(presenterSelectedBackup);refreshPresenterNext();
assert.equal(presenterNextSelectionKind,'backup');
assert.equal(presenterPrivatePreview.children[0].children[0].textContent,'Backup');
assert.equal(elements['#presenter-next-notes'].textContent,'Backup notes');
presenterTabIndex=0;refreshPresenterNext();
assert.equal(presenterNextSelection,presenterSelectedBackup);
presenterSequence.choosePlanned();refreshPresenterNext();
assert.equal(presenterNextSelection,presenterSlides[1]);
presenterSequence.commit(presenterSequence.next);refreshPresenterNext();
assert.equal(presenterNextPreview.disabled,true);
assert.equal(elements['#presenter-next-notes'].textContent,'Žádné poznámky.');
renderPresenterWidget(element(),elements['#presenter-next-notes'],{title:'No notes'});
assert.equal(elements['#presenter-next-notes'].textContent,'Tento slide nemá poznámky.');
"""
        subprocess.run(['node', '-e', harness + SLIDE_JS + model + JS[start:end] + checks], check=True)

    def test_layout_renderer_keeps_fixed_zones_and_two_columns(self):
        import shutil
        if not shutil.which('node'):
            self.skipTest('Node.js is required for layout renderer validation')
        harness = r"""
const assert=require('node:assert/strict');
const element=tag=>({tag,textContent:'',className:'',style:{},children:[],replaceChildren(){this.children=[];},append(...items){this.children.push(...items);}});
const document={createElement:element};
const target=element('div');
const slide={title:'Bezpečný layout',bullets:['Levá 1','Levá 2','Pravá 1'],background:'#112233',foreground:'#ffffff',wallpaper:'',column_break:2,layout:{preset:'two-column',title_align:'left',content_align:'left',density:'normal',background:'#102b36',foreground:'#ffffff',accent:'#79c9ac'}};
"""
        checks = r"""
renderSlideVisual(target,slide);
assert.equal(target.children.length,2);
assert.equal(target.children[0].style.top,'8%');
assert.equal(target.children[1].style.top,'30%');
const columns=target.children[1].children[0];
assert.equal(columns.style.gridTemplateColumns,'1fr 1fr');
assert.equal(columns.children[0].children.length,2);
assert.equal(columns.children[1].children.length,1);
assert.equal(target.children[0].children[0].textContent,'Bezpečný layout');
slide.layout.preset='title';renderSlideVisual(target,slide);
assert.equal(target.children[0].style.top,'24%');
assert.equal(target.children[1].style.top,'62%');
slide.layout.preset='visual';slide.wallpaper='data:image/png;base64,AA==';renderSlideVisual(target,slide);
assert.equal(target.style.backgroundImage,'none');
assert.equal(target.children[0].style.top,'6%');
assert.equal(target.children[1].style.top,'82%');
assert.equal(target.children[2].tag,'img');
assert.equal(target.children[2].style.objectFit,'contain');
"""
        subprocess.run(['node', '-e', harness + SLIDE_JS + checks], check=True)

    def test_presenter_only_lists_explicitly_assigned_backups(self):
        import shutil
        if not shutil.which('node'):
            self.skipTest('Node.js is required for presenter behavior validation')
        start = JS.index('function createPresenterBackupItem(')
        end = JS.index('async function loadPresenter()', start)
        harness = """
const assert=require('node:assert/strict');
const element=()=>({textContent:'',children:[],events:{},replaceChildren(){this.children=[];},append(...items){this.children.push(...items);},addEventListener(name,fn){this.events[name]=fn;}});
const elements={};
const document={createElement:element,querySelector(id){return elements[id]??=element();}};
const presenterBackups=element(),presenterBackupStatus=element(),presenterBackupSearch={value:''};
const presenterSlides=[{title:'First'},{title:'Second'},{title:'No backups'}];
let presenterIndex=0,presenterSelectedBackup=null,selected=null;
function renderPrivateSelection(backup){selected=backup;}
function choosePresenterBackup(backup){presenterSelectedBackup=backup;selected=backup;}
const presenterBackupsData=[
 {title:'First backup',body:'A',after_slide:0},
 {title:'Second backup',body:'B',after_slide:1},
 {title:'Unassigned',body:'C'},
 {title:'Null assignment',body:'D',after_slide:null},
 {title:'Invalid string',body:'E',after_slide:'0'}
];
"""
        checks = """
const linked=document.querySelector('#presenter-slide-backups');
renderPresenterBackups();
assert.equal(linked.children.length,1);
assert.equal(presenterBackups.children.length,5);
assert.equal(selected,null);
linked.children[0].children[0].events.click();
assert.equal(selected,presenterBackupsData[0]);
assert.equal(presenterSelectedBackup,selected);
presenterIndex=1;renderPresenterBackups();
assert.equal(linked.children.length,1);
assert.equal(linked.children[0].children[0].children[0].textContent,'Second backup');
presenterBackupSearch.value='First';renderPresenterBackups();
assert.equal(linked.children.length,0);
assert.equal(presenterBackups.children.length,1);
assert.match(elements['#presenter-slide-backup-status'].textContent,/Hledání/);
presenterBackupSearch.value='';presenterIndex=2;renderPresenterBackups();
assert.equal(linked.children.length,0);
assert.match(elements['#presenter-slide-backup-status'].textContent,/nejsou přiřazené/);
presenterIndex=0;renderPresenterBackups();
assert.equal(linked.children.length,1);
"""
        model = JS[JS.index('function createPresenterSequence('):JS.index('function renderPresenterContent(')]
        checks += '''
presenterSequence.chooseBackup(presenterBackupsData[0]);presenterSequence.commit(presenterSequence.next);
renderPresenterBackups();assert.equal(linked.children.length,0);assert.equal(presenterBackups.children.length,4);
'''
        subprocess.run(['node', '-e', harness + model + 'presenterSequence=createPresenterSequence(presenterSlides);' + JS[start:end] + checks], check=True)
        slide_renderer = JS[JS.index('function renderPresenterSlide()'):
                            JS.index('function renderPresenterDeck()')]
        self.assertIn('renderPresenterBackups();', slide_renderer)

    def test_stream_endpoint_emits_delta_and_terminal_result_over_http(self):
        class Service:
            def external_send_stream(self, request, on_delta):
                self.request = request
                on_delta('první '); on_delta('část')
                return {'thread': {'messages': []}, 'state': 'succeeded'}

            def send_stream(self, request, on_delta, on_status):
                self.chat_request = request
                on_status('preparing'); on_delta('lokální '); on_delta('část')
                on_status('completed')
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
        with running_api('http', handler=DesktopHandler) as server:
            server.chat_service = Service()
            request = {'project_id': 'project', 'expected_head': 'head',
                'thread_id': 'thread', 'turn_id': 'turn', 'message_id': 'message',
                'run_id': 'run', 'manifest_id': 'manifest',
                'assistant_message_id': 'assistant', 'selected_message_ids': [],
                'content': 'text', 'privacy': 'project', 'created_at': 'now'}
            response = driver.request(server, path='/v1/chat/send-stream',
                                      body=json.dumps(request).encode())
        head, body = response.split(b'\r\n\r\n', 1)
        self.assertIn(b' 200 ', head)
        events = [json.loads(line) for line in body.splitlines()]
        self.assertEqual([event['type'] for event in events],
                         ['status', 'delta', 'delta', 'status', 'result'])
        self.assertEqual(events[0]['status'], 'preparing')
        self.assertEqual(server.chat_service.chat_request, request)

    def test_chat_stream_flushes_delta_before_terminal_result(self):
        release = threading.Event(); terminal = threading.Event()
        class Service:
            def send_stream(self, _request, on_delta, on_status):
                on_status('preparing'); on_delta('průběžně')
                if not release.wait(2):
                    raise RuntimeError('test client did not observe the delta')
                terminal.set()
                return {'thread': {'messages': []}, 'state': 'succeeded'}

        request = {'project_id': 'project', 'expected_head': 'head',
            'thread_id': 'thread', 'turn_id': 'turn', 'message_id': 'message',
            'run_id': 'run', 'manifest_id': 'manifest',
            'assistant_message_id': 'assistant', 'selected_message_ids': [],
            'content': 'text', 'privacy': 'project', 'created_at': 'now'}
        body = json.dumps(request).encode()
        try:
            with running_api('http', handler=DesktopHandler) as server:
                server.chat_service = Service()
                client = socket.create_connection(server.server_address, timeout=2)
                self.addCleanup(client.close)
                client.sendall((
                    f'POST /v1/chat/send-stream HTTP/1.0\r\nHost: {server.authority}\r\n'
                    f'Authorization: Bearer {server.token}\r\nContent-Type: application/json\r\n'
                    f'Content-Length: {len(body)}\r\n\r\n').encode() + body)
                response = client.makefile('rb')
                self.assertIn(b' 200 ', response.readline())
                while response.readline() != b'\r\n':
                    pass
                self.assertEqual(json.loads(response.readline()),
                                 {'type': 'status', 'status': 'preparing'})
                self.assertEqual(json.loads(response.readline()),
                                 {'type': 'delta', 'delta': 'průběžně'})
                self.assertFalse(terminal.is_set())
                release.set()
                self.assertEqual(json.loads(response.readline())['type'], 'result')
                self.assertTrue(terminal.is_set())
        finally:
            release.set()

    def test_prompt_switches_to_chat_only_when_submitted(self):
        input_handler = JS.split("draft.addEventListener('input',()=>{", 1)[1].split('});', 1)[0]
        submit_handler = JS.split("document.querySelector('#chat-composer').addEventListener('submit',async event=>{", 1)[1].split('});', 1)[0]
        self.assertNotIn('selectMainTab', input_handler)
        self.assertIn("selectMainTab(document.querySelector('#chat-tab'))", submit_handler)

    def test_project_overview_and_prompt_widget_define_central_layout(self):
        overview = HTML.split('<div id="project-overview-panel"', 1)[1].split(
            '<div id="preview-panel"', 1)[0]
        self.assertIn('id="project-title"', overview)
        self.assertIn('id="project-description"', overview)
        self.assertIn('class="project-overview-grid"', overview)
        self.assertIn('class="dashboard-tile project-overview-history"', overview)
        self.assertIn('id="project-overview-history-list"', overview)
        self.assertIn('class="project-overview-description" aria-label="Stručný popis projektu"', overview)
        self.assertIn('id="project-overview-task-list"', overview)
        self.assertIn('id="project-overview-edit-todo"', overview)
        self.assertIn('class="dashboard-tile dashboard-tasks project-overview-tasks"', overview)
        self.assertIn('function renderProjectOverview(todo)', JS)
        self.assertIn('function renderProjectHistory(history)', JS)
        self.assertIn('subject.textContent=item.subject', JS)
        self.assertIn('todo.items.filter(item=>!item.checked)', JS)
        self.assertIn("classList.toggle('project-overview-active',tab.id==='project-overview-tab')", JS)
        self.assertIn("const mobileProjectOverviewItemLimit=5", JS)
        self.assertIn("mobileProjectOverview.matches?items.slice(0,mobileProjectOverviewItemLimit):items", JS)
        self.assertIn("na telefonu zobrazeno ${visible.length}", JS)
        self.assertIn('renderTodo(result.main_todo);renderProjectOverview(result.main_todo);renderProjectHistory(result.history)', JS)
        self.assertIn("document.querySelector('#project-description').textContent=result.description", JS)
        self.assertIn('id="prompt-widget"', HTML)
        self.assertNotIn('id="prompt-widget-toggle"', HTML)
        self.assertIn("setPromptVisible(tab.dataset.promptDefault!=='hidden')", JS)
        self.assertNotIn('promptToggle', JS)
        self.assertIn('id="project-overview-tab" role="tab" aria-controls="project-overview-panel" aria-selected="true" data-prompt-default="visible"', HTML)
        self.assertIn('id="chat-tab" role="tab" aria-controls="chat-panel" aria-selected="false" data-prompt-default="visible"', HTML)
        self.assertIn('id="presentation-tab" role="tab" aria-controls="presentation-panel" aria-selected="false" data-prompt-default="hidden"', HTML)
        self.assertIn('#prompt-widget{position:relative;z-index:20;flex-shrink:0', CSS)
        self.assertIn('#main-panel-content.project-overview-active{overflow:hidden}', CSS)
        self.assertIn('#project-overview-panel{box-sizing:border-box;display:flex;flex-direction:column;width:100%;height:100%', CSS)
        self.assertIn('.project-overview-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))', CSS)
        self.assertIn('align-items:stretch;flex:1;min-height:0', CSS)
        self.assertIn('.project-overview-history{display:flex;flex-direction:column', CSS)
        self.assertIn('.project-overview-history ol{flex:1;min-height:0', CSS)
        self.assertIn('.project-overview-tasks ul{flex:1;min-height:0;max-height:none', CSS)
        self.assertIn('.project-overview-description{grid-column:span 2', CSS)
        self.assertIn('@media(max-width:1250px) and (min-width:641px){.project-overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}', CSS)
        self.assertIn('.project-overview-description{grid-column:1/-1;grid-row:1}', CSS)
        self.assertIn('.project-overview-grid{display:grid;grid-template-columns:1fr}', CSS)
        self.assertIn('#main-panel-content,#main-panel-content.project-overview-active{overflow:visible', CSS)
        self.assertIn('#project-overview-panel{display:block;height:auto', CSS)
        self.assertIn('.project-overview-history{display:flex!important;grid-column:1;grid-row:2;min-height:180px;overflow:visible}', CSS)
        self.assertIn('.project-overview-history ol{flex:none;overflow:visible', CSS)
        self.assertIn('.project-overview-tasks{display:flex!important;grid-column:1;grid-row:3;min-height:260px;overflow:visible}', CSS)
        self.assertIn('.project-overview-tasks ul{flex:none;overflow:visible', CSS)

    def test_gamepad_demo_ui_and_backend_are_exposed(self):
        from spikes.desktop_ui import HTML, JS
        self.assertIn('id="gamepad-scan"', HTML)
        self.assertIn('/v1/gamepad/status', JS)
        self.assertIn('Gamepad demo', HTML)
        self.assertIn('id="gamepad-list"', HTML)
        self.assertIn('id="legacy-home-diagnostics" hidden aria-hidden="true"', HTML)

    def test_gamepad_settings_endpoint_loads_without_write_and_saves_explicitly(self):
        driver = test_local_api.LocalAPITests()
        with tempfile.TemporaryDirectory() as directory, running_api(
                'http', handler=DesktopHandler) as server:
            server.gamepad_settings = GamepadSettings(Path(directory) / 'node.json')
            response = driver.request(server, path='/v1/gamepad/settings',
                                      body=b'{"action":"load"}')
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            self.assertEqual(json.loads(body), {'settings': DEFAULT_GAMEPAD_SETTINGS,
                                                'saved': False})
            self.assertFalse(server.gamepad_settings.path.exists())
            changed = dict(DEFAULT_GAMEPAD_SETTINGS, history_axis=4)
            response = driver.request(server, path='/v1/gamepad/settings', body=json.dumps(
                {'action': 'save', 'settings': changed}).encode())
            head, body = response.split(b'\r\n\r\n', 1)
            self.assertIn(b' 200 ', head)
            self.assertEqual(json.loads(body), {'settings': changed, 'saved': True})
            self.assertEqual(server.gamepad_settings.load(), changed)

    def test_integrated_presentation_editor_api_saves_and_selects_exact_revision(self):
        from tests.test_presentation_documents import sample
        driver = test_local_api.LocalAPITests()
        with tempfile.TemporaryDirectory() as directory:
            node = Path(directory) / 'node.json'
            project = ProjectCreation(node).create(
                'Presentation API', str(Path(directory) / 'project'), str(uuid4()))['id']
            service = PresentationDocuments(node); head = service.open(project)['commit_id']
            with running_api('http', handler=DesktopHandler) as server:
                server.presentation_documents = service
                response = driver.request(server, path='/v1/presentations/open', body=json.dumps(
                    {'project_id': project, 'expected_head': head}).encode())
                self.assertIn(b' 200 ', response.split(b'\r\n\r\n', 1)[0])
                artifact = str(uuid4())
                request = {'operation_id': str(uuid4()), 'document': {'project_id': project,
                    'artifact_id': artifact, 'base_head': head, 'new': True, 'deck': sample()}}
                response = driver.request(server, path='/v1/presentations/save',
                                          body=json.dumps(request).encode())
                head_bytes, body = response.split(b'\r\n\r\n', 1)
                self.assertIn(b' 200 ', head_bytes); saved = json.loads(body)
                response = driver.request(server, path='/v1/presentations/use', body=json.dumps({
                    'project_id': project, 'artifact_id': artifact,
                    'expected_head': saved['commit_id']}).encode())
                head_bytes, body = response.split(b'\r\n\r\n', 1)
                self.assertIn(b' 200 ', head_bytes)
                self.assertEqual(json.loads(body)['deck'], server.presentation_selected_deck)
                stale = driver.request(server, path='/v1/presentations/use', body=json.dumps({
                    'project_id': project, 'artifact_id': artifact, 'expected_head': head}).encode())
                self.assertIn(b' 422 ', stale.split(b'\r\n\r\n', 1)[0])

    def test_presentation_ui_and_backend_are_exposed(self):
        from spikes.desktop_ui import ASSETS, CSS, HTML, JS, presentation_public_payload
        from types import SimpleNamespace
        from spikes.desktop_ui import presentation_deck
        deck = presentation_deck()
        self.assertIn('id="presentation-start"', HTML)
        self.assertIn('id="presentation-tab"', HTML)
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
        self.assertIn('id="presenter-gamepad-settings"', HTML)
        self.assertIn('id="presenter-gamepad-device"', HTML)
        self.assertIn('id="presenter-gamepad-apply"', HTML)
        self.assertIn('id="presenter-gamepad-save"', HTML)
        self.assertIn('Uložit na tomto uzlu', HTML)
        self.assertIn('/v1/gamepad/settings', JS)
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
        self.assertIn("pad.axes[settings.tabs_axis]", JS)
        self.assertIn("pad.axes[settings.items_axis]", JS)
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
        self.assertIn('display-ratio', ASSETS['/presentation-screen.js'][1])
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
        self.assertIn("streamRequest('/v1/external/send-stream'", JS)
        self.assertIn("streamRequest('/v1/chat/send-stream'", JS)
        self.assertIn("event.type==='delta'", JS)
        self.assertIn("event.type==='status'", JS)
        self.assertIn("thinking:'Ollama přemýšlí…'", JS)
        self.assertIn('keepChatStreamVisible()', JS)
        self.assertIn('startChatProgress', JS)
        self.assertIn('await waitForVisiblePaint()', JS)
        self.assertIn("'Ollama zpracovává explicitní úkol…'", JS)
        self.assertIn("startChatProgress('Připojuji se k OpenAI…')", JS)
        self.assertIn('Externí odpověď byla přijata průběžně (${receivedDeltas} částí).', JS)
        self.assertIn('přijato ${receivedDeltas} průběžných částí.', JS)
        self.assertIn('stream ${delivery.deltas} částí', JS)
        self.assertIn("delivery.firstDeltaMs===null?'nepřišel'", JS)
        self.assertIn("' · stream nebyl v UI zapnutý'", JS)
        self.assertIn('.chat-progress-spinner', CSS)
        self.assertIn('id="chat-stream-status" class="chat-message assistant chat-live-progress" role="status" aria-live="polite"', HTML)
        self.assertIn('id="chat-stream-progress-text"', HTML)
        self.assertIn('id="chat-stream" class="chat-message assistant" aria-live="off"', HTML)
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
        self.assertIn('id="ollama-streaming-enabled" type="checkbox"', HTML)
        self.assertIn('id="ollama-streaming-state" role="status"', HTML)
        self.assertIn("projectRequest('/v1/chat/preferences',{streaming:requested})", JS)
        self.assertIn("'Streamování je zapnuto.'", JS)
        self.assertIn("'Streamování je vypnuto; odpověď se zobrazí až celá.'", JS)
        self.assertIn('binding_draft_state', JS)
        self.assertIn('normalizeFingerprint', JS)
        ollama_form = HTML.split('id="chat-backend-form"', 1)[1].split('</form>', 1)[0]
        self.assertNotIn('pattern="[0-9a-f]{64}"', ollama_form)
        self.assertIn('Zadání a výběr zůstaly zachovány', JS)
        self.assertIn('Ollama vrátila neplatný formát výsledku úlohy',
                      Path('spikes/desktop_ui.py').read_text())
        self.assertIn('Ollama vytvořila návrh prezentace, ale ten nesplnil povinný formát',
                      Path('spikes/desktop_ui.py').read_text())
        self.assertIn("projectRequest('/v1/external/preview',request)", JS)
        self.assertIn("projectRequest('/v1/external/confirm'", JS)
        self.assertIn("projectRequest('/v1/external/cancel'", JS)
        self.assertIn('preview_sha256:preview.preview_sha256', JS)
        self.assertIn("fields.secret.value=''", JS)
        self.assertIn("administration.hidden=!['settings-users-tab','settings-federation-tab'].includes(selected.id)", JS)
        self.assertIn('id="user-profile-form"', HTML)
        self.assertIn("projectRequest('/v1/user-profile',{action:'load'})", JS)
        self.assertIn("projectRequest('/v1/user-profile',{action:'save',profile})", JS)
        self.assertIn("document.querySelector('#settings-profile-tab').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn("document.querySelector('[data-settings-item=\"settings-profile-tab\"]').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn("document.querySelector('#settings-access-tab').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn("document.querySelector('[data-settings-item=\"settings-access-tab\"]').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn("runtime==='desktop'", JS)
        self.assertIn("settings:{mode:'localhost',allowed:[]}", JS)
        self.assertNotIn('user-profile-open', HTML)
        self.assertIn("const reloaded=await loadBackendBinding()", JS)
        self.assertIn("Poslední potvrzené nastavení bylo znovu načteno.", JS)
        self.assertIn("projectRequest('/v1/tasks/route',pendingChatRequest,210000)", JS)
        self.assertIn("projectRequest('/v1/tasks/list',{", JS)
        self.assertIn("project_id:thread.project_id,thread_id:thread.thread_id", JS)
        self.assertIn("projectRequest('/v1/chat/delete/preview'", JS)
        self.assertIn("projectRequest('/v1/chat/delete/confirm'", JS)
        self.assertTrue({'/v1/chat/archive', '/v1/chat/preferences', '/v1/chat/delete/preview',
                         '/v1/chat/delete/confirm', '/v1/sources/import',
                         '/v1/user-profile'} <= DesktopHandler.post_paths)
        self.assertNotIn('id="chat-thread-list"', HTML)
        self.assertIn('id="chats-tab"', HTML)
        self.assertNotIn('id="back-projects"', HTML)
        sidebar_tabs = HTML.split('id="sidebar-tabs"', 1)[1].split('</div>', 1)[0]
        labels = ['Projekty', 'Chaty', 'Úkoly', 'Podklady', 'Nástroje', 'Výstupy', 'Nastavení', 'Federace']
        self.assertEqual([label for _, label in sorted(
            (sidebar_tabs.index(f'aria-label="{label}"'), label) for label in labels)], labels)
        self.assertEqual(sidebar_tabs.count('class="sidebar-tab-icon"'), len(labels))
        self.assertEqual(sidebar_tabs.count('class="sidebar-tab-label" role="tooltip"'), len(labels))
        self.assertIn('id="projects-tab"', sidebar_tabs)
        self.assertNotIn('disabled', sidebar_tabs.split('id="projects-tab"', 1)[1].split('</button>', 1)[0])
        self.assertNotIn('disabled', sidebar_tabs.split('id="chats-tab"', 1)[1].split('</button>', 1)[0])
        self.assertNotIn('disabled', sidebar_tabs.split('id="settings-sidebar-tab"', 1)[1].split('</button>', 1)[0])
        self.assertIn('hidden', sidebar_tabs.split('id="federation-tab"', 1)[1].split('</button>', 1)[0])
        self.assertNotIn('disabled', sidebar_tabs.split('id="federation-tab"', 1)[1].split('</button>', 1)[0])
        for tab in ('todo-tab', 'artifacts-tab', 'tools-tab', 'presentations-tab'):
            self.assertIn('disabled', sidebar_tabs.split(f'id="{tab}"', 1)[1].split('</button>', 1)[0])
        self.assertIn('id="sidebar-layout-toggle" type="button" aria-pressed="false"', HTML)
        self.assertIn('aria-label="Sbalit hlavní panel"', HTML)
        self.assertNotIn('Na tomto uzlu', HTML)
        self.assertNotIn('Zkušební verze', HTML)
        self.assertNotIn('localStorage', JS)
        self.assertIn("workspaceSidebar.classList.toggle('sidebar-menu-open',!close)", JS)
        self.assertIn("event.key!=='Escape'", JS)
        self.assertIn('aside.sidebar-compact{width:70px', CSS)
        self.assertIn('aside.sidebar-compact.sidebar-menu-open #sidebar-project-tools>', CSS)
        projects = HTML.split('id="sidebar-projects"', 1)[1].split('id="sidebar-chats"', 1)[0]
        self.assertLess(projects.index('id="sidebar-create-project"'),
                        projects.index('id="sidebar-project-list"'))
        self.assertLess(projects.index('id="sidebar-import-project"'),
                        projects.index('id="sidebar-project-trash"'))
        self.assertLess(projects.index('id="sidebar-project-trash"'),
                        projects.index('id="sidebar-register-project"'))
        self.assertLess(projects.index('id="sidebar-register-project"'),
                        projects.index('id="sidebar-project-list"'))
        self.assertEqual(projects.count('class="project-action-icon"'), 3)
        self.assertEqual(projects.count('class="project-action-label" role="tooltip"'), 3)
        for label in ('Nový projekt', 'Importovat projekt', 'Koš projektů'):
            self.assertIn(f'aria-label="{label}"', projects)
            self.assertIn(f'role="tooltip">{label}</span>', projects)
        register = projects.split('id="sidebar-register-project"', 1)[1].split('</button>', 1)[0]
        self.assertIn('hidden', register)
        self.assertIn('>Projekt z umístění', register)
        self.assertIn("requestNativeAction('register-project-location')", JS)
        self.assertIn('.sidebar-project-primary-actions{grid-template-columns:repeat(3,minmax(0,1fr))', CSS)
        self.assertNotIn('body[data-runtime="desktop"] .sidebar-project-primary-actions', CSS)
        self.assertIn('.sidebar-project-primary-actions button:hover .project-action-label', CSS)
        self.assertIn('.sidebar-project-primary-actions button:focus-visible .project-action-label', CSS)
        self.assertIn('id="open-notebooklm-import"', projects)
        self.assertIn('id="sidebar-tools"', HTML)
        self.assertIn('Katalog nástrojů je zatím prázdný', HTML)
        self.assertIn('id="sidebar-federation"', HTML)
        self.assertIn('id="open-federation-transfer"', HTML)
        self.assertIn('id="open-federation-network"', HTML)
        self.assertIn('id="open-federation-deployment"', HTML)
        self.assertEqual(HTML.count('Přenos veřejného projektu do LXC'), 2)
        self.assertIn('id="federation-transfer-form"', HTML)
        self.assertIn('plnohodnotnou správou federace projektů', HTML)
        self.assertIn("requestNativeAction('federation-transfer-open')", JS)
        self.assertIn("requestNativeAction('federation-transfer-start')", JS)
        self.assertIn('id="federation-network-form"', HTML)
        self.assertIn('Při pozdější chybě testu mohou CA a adresa na LXC zůstat aktualizované.', HTML)
        self.assertIn("requestNativeAction('federation-network-open')", JS)
        self.assertIn("requestNativeAction('federation-network-run')", JS)
        self.assertIn('id="federation-deployment-form"', HTML)
        self.assertIn('Reset zahodí recovery snapshot', HTML)
        self.assertIn("requestNativeAction('federation-deployment-open')", JS)
        self.assertIn("requestNativeAction('federation-deployment-start')", JS)
        self.assertIn('JSON.stringify(federationTransferRequest())', Path('spikes/desktop.py').read_text())
        self.assertIn('JSON.stringify(federationNetworkRequest())', Path('spikes/desktop.py').read_text())
        self.assertIn('JSON.stringify(federationDeploymentRequest())', Path('spikes/desktop.py').read_text())
        self.assertNotIn('QDialog', Path('spikes/desktop_transfer.py').read_text())
        self.assertNotIn('QDialog', Path('spikes/desktop_network.py').read_text())
        self.assertNotIn('QDialog', Path('spikes/desktop_deployment.py').read_text())
        self.assertIn('<h2>Výstupy</h2><h3>Prezentace</h3>', HTML)
        self.assertIn('#sidebar-settings-list{flex:1}', CSS)
        self.assertIn('id="sidebar-chat-tree" role="tree"', HTML)
        sidebar_chats = HTML.split('id="sidebar-chats"', 1)[1].split('</div></div>', 1)[0]
        self.assertLess(sidebar_chats.index('id="chat-new-thread"'),
                        sidebar_chats.index('id="sidebar-chat-tree"'))
        self.assertNotIn('id="chat-open-settings"', sidebar_chats)
        self.assertIn("branch('Zařazené',assigned);branch('Nezařazené',unassigned)", JS)
        self.assertIn("const assigned=activeProject ? threads.filter(thread=>thread.project_id===activeProject.id) : []", JS)
        self.assertIn("const unassigned=threads.filter(thread=>thread.project_id===null)", JS)
        self.assertNotIn("const assigned=threads.filter(thread=>thread.project_id!==null)", JS)
        self.assertIn("if(!branchThreads.length)return", JS)
        self.assertIn("root.setAttribute('role','treeitem')", JS)
        self.assertNotIn('id="chat-archive-thread"', HTML)
        self.assertNotIn('id="chat-delete-thread"', HTML)
        self.assertNotIn('id="chat-record-actions"', HTML)
        self.assertNotIn("querySelector('#chat-record-actions')", JS)
        self.assertIn("action('Archivovat',archiveActiveThread", JS)
        self.assertIn("action('Zobrazit',async()=>{},!activeProject)", JS)
        self.assertIn("action('Zařadit do tohoto projektu'", JS)
        self.assertIn('await assignActiveThread()', JS)
        self.assertIn("action('Připravit smazání',prepareActiveThreadDeletion,!activeProject)", JS)
        self.assertIn("action('Uložit otisk',button=>runChatRecord(button,'snapshot')", JS)
        self.assertIn("action('Uložit poslední odpověď',button=>runChatRecord(button,'output')", JS)
        self.assertIn("trigger.setAttribute('aria-label',`Akce chatu", JS)
        self.assertIn('.sidebar-item-menu-items{position:absolute', CSS)
        self.assertIn("openStoredThread(thread.thread_id)", JS)
        self.assertIn("function rememberThread(thread)", JS)
        self.assertIn("renderChat(assigned);rememberThread(assigned)", JS)
        self.assertIn("const visible=sidebarTabs.filter(item=>!item.hidden&&!item.disabled)", JS)
        self.assertIn("const projectSidebarTabs=['todo-tab','artifacts-tab','tools-tab','presentations-tab']", JS)
        self.assertIn("async function openSettings(settingsTabId='settings-backend-tab'){\n if(!canLeaveWorkspaceEditors())return;", JS)
        self.assertIn("document.querySelector('#chat-new-thread').disabled=!writable", JS)
        self.assertIn("End:visible.length-1", JS)
        self.assertIn("selectMainTab(document.querySelector('#chat-tab'))", JS)
        self.assertIn('grid-template-columns:51px minmax(0,1fr)', CSS)
        self.assertIn('.sidebar-tab-icon{width:22px;height:22px', CSS)
        self.assertIn('#sidebar-tabs button:hover .sidebar-tab-label,#sidebar-tabs button:focus-visible .sidebar-tab-label', CSS)
        self.assertIn('#sidebar-project-tools>[role="tabpanel"]:not([hidden])', CSS)
        self.assertIn('#sidebar-project-list,#todo-tree,#sidebar-artifact-list,#sidebar-chat-tree', CSS)
        self.assertIn('overflow-y:auto;overscroll-behavior:contain', CSS)
        project_home = HTML.split('<main><div id="project-home">', 1)[1].split(
            '<div id="project-trash-view"', 1)[0]
        self.assertNotIn('id="create-project"', project_home)
        self.assertIn('id="dashboard-grid"', project_home)
        self.assertIn('id="dashboard-calendar"', project_home)
        self.assertIn('id="dashboard-tasks"', project_home)
        self.assertIn('id="dashboard-mail"', project_home)
        self.assertIn('id="dashboard-trash"', project_home)
        self.assertNotIn('Gamepad demo', project_home)
        self.assertNotIn('Promítání prezentace', project_home)
        self.assertNotIn('VAŠE PRÁCE NA JEDNOM MÍSTĚ', project_home)
        self.assertNotIn('Vaše projekty, zdroje a rozhodnutí', project_home)
        self.assertIn('grid-template-columns:repeat(4,minmax(0,1fr))', CSS)
        self.assertNotIn('.dashboard-tasks{grid-row:span', CSS)
        self.assertIn('#dashboard-tasks{display:flex!important', CSS)
        self.assertIn("projectRequest('/v1/projects/open',{project_id:item.id})", JS)
        self.assertIn('recentProjectOrder=[projectId,...recentProjectOrder.filter', JS)
        self.assertIn('<div id="project-create-view" hidden>', HTML)
        self.assertIn('id="project-create-back"', HTML)
        self.assertIn("projectCreateView.hidden=false", JS)
        self.assertIn("projectCreateView.hidden=true", JS)
        self.assertIn('id="resource-monitor-open" type="button" aria-haspopup="dialog"', HTML)
        self.assertIn('id="resource-monitor-dialog" aria-labelledby="resource-monitor-title"', HTML)
        self.assertEqual(HTML.count('class="resource-mini-row"'), 6)
        self.assertIn("for(const name of ['CPU','GPU','RAM','VRAM','DISK','NET'])", JS)
        self.assertIn("resourceMonitorDialog.showModal()", JS)
        self.assertIn('U lokálních providerů se zde sleduje pouze dostupnost', HTML)
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
        self.assertIn("if(item.kind==='document'&&!activeProject?.readOnly)actions.push(", JS)
        self.assertIn("{label:'Zobrazit',run:()=>openPreview(item.id)}", JS)
        self.assertIn("await openPreview(item.id);if(selectedArtifact===item.id)await openHistory()", JS)
        self.assertIn('sidebar-item-menu-items', CSS)
        self.assertIn("{label:'Upravit / přejmenovat'", JS)
        self.assertIn("{label:'Připravit smazání'", JS)
        self.assertIn("{label:'Kopírovat ID'", JS)
        self.assertIn("function sidebarItemMenu(label,actions,legacyClass='')", JS)
        self.assertIn("{label:item.available?'Otevřít':'Zkusit otevřít'", JS)
        self.assertIn('data-settings-menu-tab="settings-backend-tab">Otevřít', HTML)
        self.assertIn('id="artifact-editor-view" hidden', HTML)
        self.assertIn('id="new-document"', HTML)
        self.assertIn("projectRequest('/v1/artifacts/editor/open'", JS)
        self.assertIn("projectRequest('/v1/artifacts/editor/save',{operation_id:artifactEditorAttempt.operation_id,document:artifactEditorAttempt.document}", JS)
        self.assertIn('new:Boolean(artifactEditorItem.new)', JS)
        self.assertIn('function openMainTodoEditor()', JS)
        self.assertIn("label.setAttribute('role','button')", JS)
        self.assertIn("{label:'Upravit seznam úkolů',run:()=>openMainTodoEditor()}", JS)
        self.assertNotIn("'/#create-main-todo'", Path('spikes/desktop.py').read_text())
        self.assertIn("projectRequest('/v1/artifacts/delete/preview'", JS)
        self.assertIn("projectRequest('/v1/artifacts/delete/confirm'", JS)
        self.assertIn('operation_id:artifactDeleteOperation', JS)
        self.assertIn("document.querySelector('#history-body').textContent", JS)
        self.assertNotIn('innerHTML=result.after', JS)
        self.assertTrue({'/v1/artifacts/history/list', '/v1/artifacts/history/compare'} <= DesktopHandler.post_paths)
        self.assertIn('id="chat-delete-preview"', HTML)
        self.assertIn("projectRequest('/v1/tasks/artifact'", JS)
        self.assertIn("projectRequest('/v1/tasks/presentation/confirm'", JS)
        self.assertIn("projectRequest('/v1/tasks/external/preview'", JS)
        self.assertIn("projectRequest('/v1/tasks/external/confirm'", JS)
        self.assertIn("projectRequest('/v1/tasks/external/cancel'", JS)
        self.assertIn("typeof projection.external_answer==='string'", JS)
        self.assertIn('answer.textContent=projection.external_answer', JS)
        self.assertIn('id="task-artifact-list"', HTML)
        self.assertIn('id="advanced-external"', HTML)
        self.assertIn("body.textContent=outcome.content", JS)
        self.assertNotIn('innerHTML=outcome', JS)
        self.assertIn("selected_message_ids:useConversation?selectedMessages.map", JS)
        self.assertIn("activeThread?.thread_id===threadId ? activeThread.messages : []", JS)
        self.assertIn("querySelectorAll('#task-artifact-list input:checked')", JS)
        self.assertIn("activeThread=null;activeTaskThreadId=null;taskOutcomes=[];pendingChatRequest=null", JS)
        self.assertIn("querySelector('#chat-new-thread').addEventListener", JS)
        self.assertIn('Nové vlákno pro projekt ${activeProject.title}', JS)
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
        chat_panel = HTML.split('<div id="chat-panel"', 1)[1].split('<div id="summary-panel"', 1)[0]
        self.assertIn('id="chat-operation-status"', composer)
        self.assertNotIn('id="chat-stream-status"', composer)
        self.assertIn('id="chat-stream-status"', chat_panel)
        self.assertIn('id="chat-stream"', chat_panel)
        self.assertGreater(chat_panel.index('id="chat-stream-status"'),
                           chat_panel.index('id="chat-messages"'))
        self.assertIn("chatOperationStatus.textContent='Odesílám…'", JS)
        self.assertIn("chatOperationStatus.textContent='Model přemýšlí…'", JS)
        self.assertIn("mainPanelContent.addEventListener('scroll',updateChatAutoFollow", JS)
        self.assertIn("window.addEventListener('scroll',updateChatAutoFollow", JS)
        self.assertIn('owner.scrollTop=owner.scrollHeight', JS)
        self.assertIn('if(!streamAutoFollow || streamScrollPending)return', JS)
        self.assertNotIn("scrollIntoView({block:'nearest'})", JS)

    def test_project_chat_load_enables_streaming_without_opening_settings(self):
        load_chat = JS.split('async function loadChat(){', 1)[1].split('\n}', 1)[0]
        self.assertIn("projectRequest('/v1/chat/status',{})", load_chat)
        self.assertIn("projectRequest('/v1/external/status',{})", load_chat)
        self.assertIn('applyOllamaStreamingStatus(result)', load_chat)
        self.assertIn('externalStreaming=external.capabilities?.streaming===true', load_chat)
        self.assertLess(load_chat.index('applyOllamaStreamingStatus(result)'),
                        load_chat.index('if(selectionRevision!==chatSelectionRevision)return'))
        status = JS.split('function applyOllamaStreamingStatus(result){', 1)[1].split('\n}', 1)[0]
        self.assertIn('ollamaStreamingSupported=result.capabilities?.streaming===true', status)
        self.assertIn('const enabled=result.preferences?.streaming!==false', status)
        self.assertIn('ollamaStreaming=ollamaStreamingSupported&&enabled', status)

    def test_orchestration_only_shows_actionable_configuration_warnings(self):
        self.assertIn('id="chat-orchestration-target"', HTML)
        self.assertIn("lan?'Ollama v privátní síti':'Ollama na tomto uzlu'", JS)
        controls = JS.split('function refreshChatModeControls(){', 1)[1].split('\n}', 1)[0]
        self.assertIn("warnings.push('Pro vyhledávání nejprve nastavte SearXNG.')", controls)
        self.assertIn("warnings.push('Externí úkol vyžaduje nejprve nastavit OpenAI backend.')", controls)
        self.assertIn("warnings.push('Lokální úkol vyžaduje nejprve nastavit Ollama backend.')", controls)
        self.assertIn("target.hidden=!warnings.length", controls)
        self.assertNotIn('chatBinding.endpoint', controls)
        for control in ('task-source-conversation', 'task-source-artifacts',
                        'task-source-public', 'task-source-current-prompt',
                        'task-source-current-file', 'task-source-current-file-input', 'task-output-kind',
                        'task-public-source-list'):
            self.assertIn('id="' + control + '"', HTML)
        self.assertIn("currentArtifacts.find(value=>value.id===selectedArtifact)", JS)
        self.assertIn("title.textContent=item?`Aktuální soubor: ${item.title}`", JS)
        self.assertIn("if(useCurrentFile)artifactIds.push(selectedArtifact)", JS)
        self.assertIn("selected_artifact_ids:uniqueArtifactIds", JS)
        self.assertIn('task_plan:{schema_version:1,source_kinds:sourceKinds', JS)
        self.assertIn("execution:adapter==='ollama'?'local-ollama':'external-openai'", JS)
        self.assertIn('External task execution cannot include project artifacts',
                      Path('spikes/task_plan.py').read_text())

    def test_prompt_widget_separates_inputs_action_output_privacy_and_target(self):
        composer = HTML.split('<form id="chat-composer">', 1)[1].split('</form>', 1)[0]
        for control in ('task-inputs', 'task-input-count', 'task-action',
                        'task-output-kind', 'chat-privacy', 'chat-response-language',
                        'chat-run-adapter',
                        'chat-run-model'):
            self.assertIn('id="' + control + '"', composer)
        self.assertIn('<option value="answer">Odpovědět</option>', composer)
        self.assertIn('<option value="search">Vyhledat na webu</option>', composer)
        self.assertNotIn('Výpočet', composer)
        self.assertNotIn('Julia', composer)
        self.assertIn('aria-label="Zpracovat zadání"', composer)
        self.assertIn('title="Zpracovat zadání (Enter) · nový řádek (Shift+Enter)"', composer)
        self.assertIn('<label class="prompt-draft-control" for="chat-draft"><span>Zadání</span>', composer)
        for label in ('Režim', 'Akce', 'Výsledek', 'Soukromí', 'Jazyk',
                      'Backend', 'Model'):
            self.assertIn('<span>' + label + '</span>', composer)
        self.assertIn('<option value="cs-CZ">Čeština · cs-CZ</option>', composer)
        self.assertIn('response_language:responseLanguage', JS)
        self.assertIn("turn.language_compliance==='unverified'?'neověřena'", JS)
        self.assertIn('id="task-source-current-prompt" hidden', composer)
        self.assertIn('Aktuální zadání (povinné pro vyhledávání)', composer)
        self.assertIn('id="task-source-current-file" hidden', composer)
        self.assertIn('id="task-source-current-file-input" type="checkbox"', composer)
        self.assertNotIn('id="task-search-editor"', composer)
        self.assertNotIn('id="task-search-query"', composer)
        self.assertIn('id="advanced-external" hidden aria-hidden="true"', composer)
        self.assertNotIn('id="task-selection-summary"', composer)
        self.assertNotIn('id="task-routing-note"', composer)
        self.assertNotIn('historie zůstává lokálně na tomto uzlu', composer)
        self.assertNotIn('Vyberte uložené vlákno k vědomému navázání', JS)
        self.assertIn("document.querySelector('#task-source-public').checked=event.currentTarget.value==='search'", JS)
        self.assertIn("action.value=publicSource.checked?'search':'answer'", JS)
        self.assertIn("const searchQuery=searching?draft.value.trim():null", JS)
        self.assertIn("output.value='conversation';output.disabled=true", JS)
        self.assertIn("currentPromptSource.hidden=!searching", JS)
        self.assertIn('function updatePromptInputSummary()', JS)
        self.assertIn("promptForm.classList.toggle('inputs-open',taskInputs.open)", JS)
        self.assertIn("event.key==='Escape'&&taskInputs.open", JS)
        self.assertIn('.prompt-toolbar{display:flex', CSS)
        self.assertIn('.prompt-control>span{position:absolute', CSS)
        self.assertIn('.prompt-draft-control>span{position:absolute', CSS)
        self.assertIn('#chat-composer.inputs-open{overflow:visible}', CSS)
        self.assertNotIn('.prompt-search-editor', CSS)
        self.assertIn('#chat-operation-status:empty{display:none}', CSS)
        self.assertIn('@media(max-width:640px)', CSS)

    def test_node_settings_are_global_and_backend_form_is_not_duplicated(self):
        from spikes.desktop_ui import HTML
        from spikes.desktop_management import ASSETS, DESKTOP_BOOTSTRAP
        desktop_html = ASSETS['/'][1]
        self.assertIn('id="backend-metrics"', desktop_html)
        self.assertEqual(desktop_html, HTML)
        self.assertEqual(ASSETS['/app.css'][1], CSS)
        self.assertEqual(ASSETS['/app.js'][1], DESKTOP_BOOTSTRAP + JS)
        self.assertIn("'backend-metrics','backend-metrics-indicator','openai-resource-provider'", DESKTOP_BOOTSTRAP)
        self.assertNotIn("'settings-users-tab'", DESKTOP_BOOTSTRAP)
        self.assertIn("document.querySelector('[data-settings-item=\"settings-profile-tab\"]').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn("document.querySelector('[data-settings-item=\"settings-access-tab\"]').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn("'openai-resource-provider','presenter-fullscreen'", DESKTOP_BOOTSTRAP)
        self.assertIn("'federation-tab'", DESKTOP_BOOTSTRAP)
        self.assertIn("getElementById('project-location-controls').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn("getElementById('sidebar-register-project').hidden=false", DESKTOP_BOOTSTRAP)
        self.assertIn('id="project-create-preview"', HTML)
        self.assertIn("requestNativeAction('choose-project-location')", JS)
        desktop_source = Path('spikes/desktop.py').read_text()
        self.assertNotIn('QInputDialog', desktop_source)
        self.assertNotIn("QPushButton('Načíst projekt z umístění…')", desktop_source)
        self.assertNotIn("QPushButton('Opravit umístění projektu…')", desktop_source)
        self.assertIn("requestNativeAction('relocate-project-location'", JS)
        self.assertIn("requestNativeAction('unregister-missing-project'", JS)
        self.assertIn('if(item.location_missing)actions.splice', JS)
        self.assertIn("label:'Opravit umístění…'", JS)
        self.assertIn("label:'Odebrat nedostupnou registraci…'", JS)
        self.assertIn('id="project-registration-remove-dialog"', HTML)
        creation_source = Path('spikes/desktop_creation.py').read_text()
        self.assertNotIn('CreationDialog', creation_source)
        self.assertNotIn('addToolBar', creation_source)
        self.assertNotIn('QLabel', creation_source)
        self.assertNotIn('QPushButton', creation_source)
        self.assertIn('status_changed', creation_source)
        self.assertIn('id="sidebar-project-recover"', HTML)
        self.assertIn("requestNativeAction('recover-project-operation')", JS)
        self.assertIn('#resource-monitor{flex:none', ASSETS['/app.css'][1])
        self.assertIn('#resource-monitor-dialog{width:min(760px', ASSETS['/app.css'][1])
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
        self.assertNotIn('id="open-settings"', HTML)
        self.assertNotIn('id="chat-open-settings"', HTML)
        self.assertIn('id="sidebar-settings-list" aria-label="Seznam nastavení"', HTML)
        self.assertIn('data-settings-tab="settings-backend-tab"', HTML)
        self.assertIn("openSettings(button.dataset.settingsTab)", JS)
        self.assertIn("await openAdministration(selected.id==='settings-users-tab'?'users':'federation')", JS)
        self.assertNotIn('id="chat-backend-settings"', HTML)
        self.assertIn("settingsReturn={project:!!activeProject,tabId:", JS)
        self.assertIn("document.querySelector('#project-home').hidden=true", JS)
        self.assertIn("const tab=document.getElementById(destination.tabId)", JS)
        self.assertIn("await loadBackendBinding()", JS)
        self.assertIn("projectRequest('/v1/chat/configure',binding)", JS)
        self.assertIn('id="settings-users-tab"', desktop_html)
        self.assertIn('id="settings-federation-tab"', desktop_html)
        self.assertNotIn('id="settings-cms-tab" type="button" data-desktop="true" role="tab" aria-selected="false" aria-controls="settings-cms-panel" tabindex="-1" hidden', desktop_html)
        self.assertIn('data-settings-item="settings-users-tab" hidden', desktop_html)
        self.assertIn('id="settings-users-tab" type="button" role="tab" aria-selected="false" aria-controls="admin-users-panel" tabindex="-1" hidden', desktop_html)
        settings = desktop_html.split('id="settings-view"', 1)[1].split('id="project-view"', 1)[0]
        self.assertIn('id="administration" class="settings-card"', settings)
        self.assertIn('<dialog id="admin-peer-editor"', settings)
        self.assertIn('<dialog id="admin-peer-enroll-dialog"', settings)
        self.assertNotIn('<dialog id="administration"', settings)
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

    def test_google_picker_uses_exact_system_browser_oauth_contract(self):
        origin = 'http://127.0.0.1:4321'
        query = {'client_id': 'client.apps.googleusercontent.com',
                 'scope': 'https://www.googleapis.com/auth/drive.file',
                 'redirect_uri': origin + '/',
                 'response_type': 'code', 'access_type': 'offline', 'prompt': 'consent',
                 'trigger_onepick': 'true', 'allow_multiple': 'true',
                 'allow_folder_selection': 'true', 'state': 'state',
                 'code_challenge': 'challenge', 'code_challenge_method': 'S256',
                 'include_granted_scopes': 'false'}
        approved = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(query)
        self.assertEqual(google_authorization_url(approved, origin), approved)
        for changed in (approved.replace('accounts.google.com', 'accounts.google.com.evil.test'),
                        approved.replace('drive.file', 'drive.readonly'),
                        approved.replace('127.0.0.1%3A4321', '127.0.0.1%3A9999'),
                        approved.replace('%2F&response_type', '%2Foauth%2Fgoogle-drive%2Fcallback&response_type')):
            self.assertIsNone(google_authorization_url(changed, origin))
        self.assertEqual(DesktopHandler.google_drive_callback_path, '/')
        self.assertIn('id="google-drive-preview"', HTML)
        self.assertIn('id="google-drive-steps"', HTML)
        self.assertIn('id="google-drive-open-settings"', HTML)
        self.assertIn('id="google-drive-callback"', HTML)
        self.assertIn('Google heslo zadáváte jen Googlu.', HTML)
        self.assertIn('Google Auth Platform → Audience', HTML)
        self.assertIn('<strong>Test users</strong>', HTML)
        self.assertIn("setGoogleDriveStep(3,2)", JS)
        self.assertIn("googleDriveFiles.replaceChildren()", JS)
        self.assertNotIn('googleDriveFiles.innerHTML', JS)
        self.assertIn("projectRequest('/v1/google-drive/confirm'", JS)
        self.assertIn("projectRequest('/v1/google-drive/recover'", JS)
        self.assertIn('status.pending_selection', JS)
        self.assertIn('Navazuji na dokončený výběr', JS)

    def test_desktop_google_callback_returns_to_loopback_root(self):
        calls = []

        class Drive:
            @staticmethod
            def callback(*args):
                calls.append(args)
                return {'status': 'selected'}

        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopHandler) as server:
            server.google_drive_import = Drive()
            query = urlencode({'state': 's' * 32, 'code': 'code',
                               'picked_file_ids': 'file-id',
                               'iss': 'https://accounts.google.com',
                               'scope': 'https://www.googleapis.com/auth/drive.file'})
            response = driver.request(server, method='GET', path='/?' + query)
            rejected = driver.request(server, method='GET', path='/?' + urlencode({
                'state': 's' * 32, 'code': 'code', 'picked_file_ids': 'file-id',
                'iss': 'https://accounts.google.com.evil.test'}))
        self.assertTrue(response.startswith(b'HTTP/1.0 200'), response[:80])
        self.assertIn('Vraťte se'.encode(), response)
        self.assertTrue(rejected.startswith(b'HTTP/1.0 200'), rejected[:80])
        self.assertIn('nepodařilo přijmout'.encode(), rejected)
        self.assertEqual(calls, [('s' * 32, 'code', 'file-id', None)])

    def test_management_serves_audience_page_and_authenticates_slide_polling(self):
        from spikes.desktop_management import DesktopManagementHandler
        from spikes.desktop_ui import PUBLIC_HTML
        driver = test_local_api.LocalAPITests()
        with running_api('http', handler=DesktopManagementHandler) as server:
            self.assertEqual(request_policy(server.origin + '/presentation-screen',
                                            '', 'GET', server.origin), 'allow')
            response = driver.request(server, method='GET', path='/presentation-screen',
                                      headers={'Authorization': None})
            self.assertTrue(response.startswith(b'HTTP/1.0 200'), response[:100])
            self.assertEqual(response.split(b'\r\n\r\n', 1)[1], PUBLIC_HTML.encode())
            self.assertNotIn(server.token.encode(), response)
            self.assertNotIn('<script>', PUBLIC_HTML)
            self.assertNotIn('<style>', PUBLIC_HTML)
            for path in ('/presentation-screen.css', '/presentation-screen.js'):
                self.assertIn(path, PUBLIC_HTML)
                self.assertEqual(request_policy(server.origin + path, server.origin,
                                                'GET', server.origin), 'allow')
                asset = driver.request(server, method='GET', path=path,
                                       headers={'Authorization': None})
                self.assertTrue(asset.startswith(b'HTTP/1.0 200'), asset[:100])
                self.assertNotIn(server.token.encode(), asset)
            self.assertEqual(request_policy(server.origin + '/v1/presentation/public',
                                            server.origin, 'POST', server.origin), 'authenticate')
            driver.rejected(server, path='/v1/presentation/public', body=b'{}',
                            headers={'Authorization': None})
            shown = driver.request(server, path='/v1/presentation/control', body=json.dumps({
                'action': 'show', 'slide': 0,
                'content': {'title': 'Audience regression', 'body': 'Approved content'},
            }).encode())
            self.assertTrue(shown.startswith(b'HTTP/1.0 200'), shown[:100])
            public = driver.request(server, path='/v1/presentation/public', body=b'{}')
            payload = json.loads(public.split(b'\r\n\r\n', 1)[1])
            self.assertTrue(payload['visible'])
            self.assertEqual(payload['content']['title'], 'Audience regression')

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_webengine_audience_renders_approved_slide(self):
        script = r'''
import json
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from spikes.desktop import request_policy
from spikes.desktop_management import DesktopManagementHandler
from spikes.local_api import running_api
from tests.test_local_api import LocalAPITests
from tests.test_presentation_documents import sample
from spikes.presentation_documents import project_deck
app = QApplication([])
with running_api('http', handler=DesktopManagementHandler) as server:
    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            policy = request_policy(info.requestUrl().toString(), info.initiator().toString(),
                                    bytes(info.requestMethod()).decode(), server.origin)
            if policy == 'block':
                info.block(True)
            elif policy == 'authenticate':
                info.setHttpHeader(b'Authorization', ('Bearer ' + server.token).encode())
    profile = QWebEngineProfile(app)
    interceptor = Interceptor(profile)
    profile.setUrlRequestInterceptor(interceptor)
    page = QWebEnginePage(profile, app)
    state = {'phase': 0}
    driver = LocalAPITests()
    def received(value):
        if not value:
            return
        text, color, foreground, image_ready, bullets = json.loads(value)
        if state['phase'] == 0 and 'čeká na schválený slide' in text:
            response = driver.request(server, path='/v1/presentation/control', body=json.dumps({
                'action': 'show', 'slide': 0,
                'content': {'title': 'Audience smoke', 'body': 'Approved slide rendered'},
            }).encode())
            assert response.startswith(b'HTTP/1.0 200')
            state['phase'] = 1
        elif state['phase'] == 1 and 'Approved slide rendered' in text and color == 'rgb(5, 9, 12)':
            deck = sample()
            deck['slides'][0]['foreground'] = '#aabbcc'
            server.presentation_selected_deck = project_deck(deck, 'saved-revision')
            response = driver.request(server, path='/v1/presentation/control', body=json.dumps({
                'action': 'show', 'slide': 0, 'slide_id': deck['slides'][0]['id'],
                'deck_revision': 'saved-revision',
            }).encode())
            assert response.startswith(b'HTTP/1.0 200')
            state['phase'] = 2
        elif state['phase'] == 2 and bullets == ['First point', '<b>Plain text</b>'] and image_ready and foreground == 'rgb(170, 187, 204)':
            assert 'Private' not in text
            print('audience: page, stylesheet, authenticated polling and approved slide verified', flush=True)
            print('editor: saved slide, literal bullets, foreground and decoded wallpaper verified', flush=True)
            app.exit(0)
    poll = QTimer()
    poll.timeout.connect(lambda: page.runJavaScript(
        """(()=>{const target=document.querySelector('#screen');if(!target)return '';
const style=getComputedStyle(target);
if(style.backgroundImage.startsWith('url("data:') && !window.wallpaperProbe){
 window.wallpaperProbe=new Image();window.wallpaperProbe.src=style.backgroundImage.slice(5,-2);
}
return JSON.stringify([target.textContent,getComputedStyle(document.body).backgroundColor,style.color,
 Boolean(window.wallpaperProbe?.naturalWidth),[...target.querySelectorAll('li')].map(li=>li.textContent)]);
})()""",
        0, received))
    poll.start(100)
    page.loadFinished.connect(lambda ok: None if ok else app.exit(3))
    page.setUrl(QUrl(server.origin + '/presentation-screen'))
    QTimer.singleShot(10000, lambda: app.exit(2))
    code = app.exec()
    poll.stop()
    raise SystemExit(code)
'''
        result = subprocess.run([sys.executable, '-c', script],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('approved slide verified', result.stdout)
        self.assertIn('decoded wallpaper verified', result.stdout)

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
