# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Chat in a real browser: runs, context, retries, threads and external models (AUDIT-B7-T1).

Replaces the chat part of the source-text assertions of
``test_chat_ui_uses_authenticated_api_and_explicit_message_selection``.
"""
from tests.browser_harness import Reply, ndjson
from tests.ui_flow_case import FakeApi, UiFlowCase, require_browser

HOSTILE = 'Odpověď <img src=x onerror=window.__pwned=1><b>tučně</b>'


class ChatActions:
    def brainstorm(self, text, answers=None, api=None):
        if not hasattr(self, 'page'):
            self.start(answers=answers or [], api=api)
            self.open_project_chat()
            self.page.fill('#chat-mode', 'brainstorming')
            self.page.wait_idle()
            self.page.fill('#chat-run-adapter', 'ollama')
            self.page.fill('#chat-run-model', 'aggregate:ollama/gemma3')
        page = self.page
        page.fill('#chat-draft', text)
        before = len(page.api.requests)
        page.evaluate("document.querySelector('#chat-composer').requestSubmit()")
        page.wait(lambda: any(item['path'].startswith('/v1/chat/send') for item in page.api.requests[before:]),
                  'the message to be sent')
        page.wait_js("!['','Odesílám…'].includes(document.querySelector('#chat-operation-status').textContent)",
                     'the run to finish')
        page.wait_idle()
        return [item for item in page.api.requests[before:] if item['path'].startswith('/v1/chat/send')]

    def messages(self):
        return self.page.evaluate("""[...document.querySelectorAll('#chat-messages > .chat-message')]
          .map(x=>[x.classList.contains('user')?'user':'assistant',x.firstChild.textContent])""")


@require_browser
class BrainstormingTests(ChatActions, UiFlowCase):
    def test_streamed_answer_is_shown_as_text_and_pinned_to_the_chosen_offer(self):
        sent = self.brainstorm('První otázka', answers=[HOSTILE])
        page = self.page
        self.assertEqual([item['path'] for item in sent], ['/v1/chat/send-stream'])
        request = sent[0]['body']
        self.assertTrue(sent[0]['authenticated'])
        choice = request['run_choice']
        self.assertEqual((choice['mode'], choice['adapter'], choice['model']), ('brainstorming', 'ollama', 'gemma3'))
        selection = page.evaluate('modelSelectionProjection')
        self.assertEqual(choice['selection_revision'], selection['revision'])
        self.assertEqual(choice['offer_id'], selection['offers'][0]['offer_id'])
        self.assertEqual(request['selected_message_ids'], [])
        self.assertEqual(request['privacy'], 'project')
        self.assertEqual(self.messages(), [['user', 'První otázka'], ['assistant', HOSTILE]])
        self.assertEqual(page.evaluate("document.querySelectorAll('#chat-messages img,#chat-messages b').length"), 0)
        self.assertIsNone(page.evaluate('window.__pwned ?? null'))
        self.assertRegex(page.text('#chat-operation-status'), r'^Odpověď je připravena · přijato 2 průběžných částí\.')
        self.assertFalse(page.evaluate("Boolean(document.querySelector('#chat-stream-status')?.checkVisibility())"),
                         'Progress disappears after the run')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), '')
        self.assert_no_page_errors()

    def test_follow_up_turn_sends_the_thread_as_explicit_context(self):
        self.brainstorm('První otázka', answers=['První odpověď', 'Druhá odpověď'])
        first = self.page.evaluate('activeThread.messages.map(m=>m.message_id)')
        sent = self.brainstorm('Navazující otázka')
        self.assertEqual(sent[0]['body']['selected_message_ids'], first)
        self.assertEqual(sent[0]['body']['thread_id'], self.page.evaluate('activeThread.thread_id'))
        self.assertEqual([text for _, text in self.messages()],
                         ['První otázka', 'První odpověď', 'Navazující otázka', 'Druhá odpověď'])

    def test_rejected_run_retries_as_a_new_run_and_unknown_outcome_keeps_its_identity(self):
        api = FakeApi()
        replies = [Reply({'error': 'Backend odmítl běh.', 'outcome': 'failed'}, status=502),
                   Reply({'error': 'Výsledek není známý.', 'outcome': 'unknown',
                          'retry': 'same-operation'}, status=503)]
        api.route('/v1/chat/send-stream', lambda body: replies.pop(0) if replies else None)
        first = self.brainstorm('Otázka', answers=['Konečně odpověď'], api=api)[0]['body']
        self.assertIn('tlačítkem Zpracovat spustíte vědomě nový běh', self.page.text('#chat-operation-status'))
        self.assertIsNone(self.page.evaluate('pendingChatRequest'))
        second = self.brainstorm('Otázka')[0]['body']
        self.assertNotEqual(second['run_id'], first['run_id'], 'A rejected run is not repeated')
        self.assertEqual(self.page.text('#chat-operation-status'), 'Výsledek není známý.')
        third = self.brainstorm('Otázka')[0]['body']
        self.assertEqual(third['run_id'], second['run_id'], 'An unknown outcome is retried as the same operation')
        self.assertEqual(self.messages()[-1], ['assistant', 'Konečně odpověď'])

    def test_streaming_can_be_turned_off_for_a_single_reply(self):
        self.start(answers=['Celá odpověď najednou'])
        page = self.page
        page.evaluate('openSettings()')
        page.wait_idle()
        page.evaluate("openBackendSettings({backend_id:'ollama',display_name:'Ollama',detail:''})")
        page.wait_js("!document.querySelector('#ollama-streaming-enabled').disabled", 'streaming toggle')
        self.assertTrue(page.evaluate("document.querySelector('#ollama-streaming-enabled').checked"))
        page.click('#ollama-streaming-enabled')
        page.wait(lambda: self.requests('/v1/chat/preferences'), 'preference request')
        page.wait_idle()
        self.assertEqual(self.requests('/v1/chat/preferences')[0]['body'], {'streaming': False})
        self.assertEqual(page.text('#ollama-streaming-state'),
                         'Streamování je vypnuto; odpověď se zobrazí až celá.')
        page.evaluate("document.querySelector('#backend-settings-dialog').close()")
        self.open_project_chat()
        page.fill('#chat-mode', 'brainstorming')
        page.wait_idle()
        page.fill('#chat-run-adapter', 'ollama')
        page.fill('#chat-run-model', 'aggregate:ollama/gemma3')
        sent = self.brainstorm('Bez streamu')
        self.assertEqual([item['path'] for item in sent], ['/v1/chat/send'])
        self.assertEqual(page.text('#chat-operation-status')[:25], 'Odpověď je připravena. Ru')


@require_browser
class ThreadTests(ChatActions, UiFlowCase):
    def thread_action(self, label):
        self.click_text(label, '#sidebar-chat-tree')

    def test_new_thread_starts_empty_for_the_open_project(self):
        self.brainstorm('Otázka', answers=['Odpověď'])
        old = self.page.evaluate('activeThread.thread_id')
        self.page.click('#chat-new-thread')
        self.page.wait_idle()
        self.assertEqual(self.messages(), [])
        self.assertIsNone(self.page.evaluate('pendingChatRequest'))
        self.assertTrue(self.page.text('#chat-backend-status').startswith(
            'Nové vlákno pro projekt Projekt v prohlížeči · backend: gemma3'))
        sent = self.brainstorm('Nové téma')
        self.assertNotEqual(sent[0]['body']['thread_id'], old)
        self.assertEqual(sent[0]['body']['selected_message_ids'], [])

    def test_project_threads_are_listed_and_restored_after_reopening(self):
        self.brainstorm('Otázka k uložení', answers=['Uložená odpověď'])
        page = self.page
        tree = page.text('#sidebar-chat-tree')
        self.assertIn('Projektová vlákna', tree)
        self.assertEqual(page.evaluate("document.querySelector('#sidebar-chat-tree').getAttribute('role')"), 'tree')
        self.assertTrue(page.evaluate("document.querySelectorAll('#sidebar-chat-tree [role=treeitem]').length>0"))
        page.navigate(page.server.origin + '/')
        page.wait_idle()
        self.open_project_chat()
        self.assertIn('Obnoveno poslední uložené vlákno projektu.', page.text('#chat-operation-status'))
        self.assertEqual([text for _, text in self.messages()], ['Otázka k uložení', 'Uložená odpověď'])

    def test_snapshot_and_output_are_saved_and_the_thread_stays_open(self):
        self.brainstorm('Otázka', answers=['Odpověď pro záznam'])
        page = self.page
        thread = page.evaluate('activeThread.thread_id')
        for label, path, saved in (('Uložit otisk', '/v1/chat/snapshot', 'Otisk byl uložen do projektu.'),
                                   ('Uložit poslední odpověď', '/v1/chat/output',
                                    'Výstup byl uložen jako editovatelný dokument.')):
            with self.subTest(record=label):
                self.thread_action(label)
                page.wait(lambda: self.requests(path), label)
                page.wait_js(f"document.querySelector('#chat-operation-status').textContent==={saved!r}",
                             'the saved message')
                page.wait_idle()
                record = self.requests(path)[0]
                self.assertEqual((record['body']['thread_id'], page.status(record)), (thread, 200))
                # AUDIT-B7-T1 fix: reopening the project used to empty the chat.
                self.assertEqual(page.evaluate('activeThread?.thread_id'), thread)
                self.assertEqual([text for _, text in self.messages()], ['Otázka', 'Odpověď pro záznam'])
                self.assertEqual(page.text('#chat-operation-status'), saved)
                self.assertIn(label, self.buttons('#sidebar-chat-tree'))
        self.assertEqual(self.requests('/v1/chat/output')[0]['body']['body'], 'Odpověď pro záznam')

    def test_archive_and_deletion_act_on_the_active_thread(self):
        self.brainstorm('Otázka', answers=['Odpověď'])
        page = self.page
        thread = page.evaluate('activeThread.thread_id')
        self.thread_action('Archivovat')
        page.wait(lambda: self.requests('/v1/chat/archive'), 'archive')
        page.wait_idle()
        self.assertEqual(self.requests('/v1/chat/archive')[0]['body']['thread_id'], thread)
        self.assertEqual(page.text('#chat-operation-status'), 'Vlákno bylo archivováno a zůstává lokálně uložené.')
        self.thread_action('Připravit smazání')
        page.wait_js("!document.querySelector('#chat-delete-preview').hidden", 'deletion preview')
        self.assertTrue(page.evaluate("document.querySelector('#chat-delete-run').disabled"))
        page.click('#chat-delete-confirm')
        page.click('#chat-delete-run')
        page.wait(lambda: self.requests('/v1/chat/delete/confirm'), 'delete')
        page.wait_idle()
        deleted = self.requests('/v1/chat/delete/confirm')[0]['body']
        self.assertEqual(deleted['thread_id'], thread)
        self.assertRegex(deleted['preview_sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(self.messages(), [])
        self.assertIn('Git historie zůstala zachovaná.', page.text('#chat-operation-status'))

    def test_cancelled_deletion_removes_nothing(self):
        self.brainstorm('Otázka', answers=['Odpověď'])
        page = self.page
        self.thread_action('Připravit smazání')
        page.wait_js("!document.querySelector('#chat-delete-preview').hidden", 'deletion preview')
        page.click('#chat-delete-confirm')
        page.click('#chat-delete-cancel')
        self.assertTrue(page.evaluate("document.querySelector('#chat-delete-preview').hidden"))
        self.assertIsNone(page.evaluate('pendingThreadDeletion'))
        self.assertEqual(self.requests('/v1/chat/delete/confirm'), [])
        self.assertEqual(len(self.messages()), 2)
        # AUDIT-B7-T1 fix: the action used to stay disabled after a preview.
        self.thread_action('Připravit smazání')
        page.wait(lambda: len(self.requests('/v1/chat/delete/preview')) == 2, 'second preview')
        page.wait_js("!document.querySelector('#chat-delete-preview').hidden", 'deletion preview again')

    def test_orchestration_answer_is_rendered_as_text(self):
        self.start(answers=[{'schema_version': 1, 'kind': 'direct-answer', 'content': HOSTILE}])
        self.open_project_chat()
        sent = self.submit_prompt('Otázka pro orchestraci')
        route = [item for item in sent if item['path'].startswith('/v1/tasks/route')][0]['body']
        self.assertEqual(route['run_choice']['mode'], 'orchestration')
        self.assertIsNone(route['run_choice']['model'], 'Orchestration uses the configured Ollama model')
        self.assertEqual(route['task_plan']['source_kinds'], ['conversation'])
        self.assertIn(HOSTILE, self.page.text('#chat-messages'))
        self.assertEqual(self.page.evaluate("document.querySelectorAll('#chat-messages img,#chat-messages b').length"), 0)


def external_api(stream):
    """Scripted OpenAI offer next to the real Ollama one."""
    api = FakeApi()
    caps = [{'name': 'generate-text', 'supported': True, 'state': 'reported'},
            {'name': 'text-output', 'supported': True, 'state': 'reported'}]
    projection = {'schema_version': 1, 'revision': 'selection-external', 'models': [],
                  'preferences': {'preferred_model_ids': []}, 'offers': [
                      {'offer_id': 'openai:gpt', 'adapter_id': 'openai-responses', 'provider_model_id': 'gpt-test',
                       'canonical_model_id': None, 'aggregation_model_id': 'openai/gpt-test',
                       'model_group_id': 'aggregate:openai/gpt-test', 'model_group_canonical_id': None,
                       'display_model_id': 'gpt-test', 'protocol': 'openai-responses-v1',
                       'availability': 'available', 'freshness': 'fresh',
                       'binding_id': '11111111-1111-4111-8111-111111111111', 'binding_revision': 'one',
                       'capabilities': caps}]}
    api.route('/v1/model-selection/status', projection)
    api.route('/v1/external/status', {'binding': {'model': 'gpt-test'}, 'capabilities': {'streaming': True},
                                      'credential': {'available': True}, 'model_catalog': None})
    api.route('/v1/external/send-stream', stream)
    api.route('/v1/external/request', {'provider_request': {'model': 'gpt-test', 'input': 'Otázka'}})
    return api


class ExternalActions:
    def open_external(self, stream):
        self.start(api=external_api(stream))
        self.open_project_chat_external()

    def open_project_chat_external(self):
        page = self.page
        page.evaluate("[...document.querySelectorAll('#sidebar-project-list button')]"
                      ".find(b=>b.textContent==='Otevřít').click()")
        page.wait_js('activeProject?.id', 'project to open')
        page.wait_idle()
        page.click('#chat-tab')
        page.wait_idle()
        page.fill('#chat-mode', 'brainstorming')
        page.wait_idle()
        page.wait_js("document.querySelector('#chat-run-adapter option[value=\"openai-responses\"]')", 'OpenAI offer')
        page.fill('#chat-run-adapter', 'openai-responses')
        page.fill('#chat-run-model', 'aggregate:openai/gpt-test')

    def send(self, text, privacy='project'):
        page = self.page
        page.fill('#chat-privacy', privacy)
        page.fill('#chat-draft', text)
        before = len(page.api.requests)
        page.evaluate("document.querySelector('#chat-composer').requestSubmit()")
        page.wait_js("!document.querySelector('#chat-operation-status').textContent.startsWith('Odesílám')",
                     'external run')
        page.wait_idle()
        return self.requests('/v1/external/send-stream', before)


@require_browser
class ExternalModelTests(ExternalActions, UiFlowCase):
    def test_local_only_text_never_goes_to_an_external_model(self):
        self.open_external(ndjson())
        self.assertEqual(self.send('Tajné', privacy='local-only'), [])
        self.assertEqual(self.page.text('#chat-operation-status'),
                         'Text jen na tomto počítači nelze odeslat externímu modelu.')

    def test_external_stream_is_shown_with_the_request_that_was_sent(self):
        thread = {'thread_id': 'th-ext', 'project_id': None, 'revision': 1, 'messages': [
            {'message_id': 'm1', 'role': 'user', 'content': 'Otázka', 'privacy': 'project',
             'created_at': '2026-11-20T10:00:00Z'},
            {'message_id': 'm2', 'role': 'assistant', 'content': 'Externí odpověď', 'privacy': 'project',
             'created_at': '2026-11-20T10:00:01Z'}],
            'turns': [{'assistant_message_id': 'm2', 'run_id': 'run-1', 'external_request_available': True}]}
        self.open_external(ndjson({'type': 'delta', 'delta': 'Externí '}, {'type': 'delta', 'delta': 'odpověď'},
                                  {'type': 'result', 'result': {'thread': thread}}))
        sent = self.send('Otázka')
        self.assertEqual(sent[0]['body']['run_choice']['adapter'], 'openai-responses')
        self.assertEqual(self.page.text('#chat-operation-status'), 'Externí odpověď byla přijata průběžně (2 částí).')
        self.click_text('Zobrazit odeslaný request')
        self.page.wait_js("document.querySelector('.external-request-record')", 'sent request')
        self.assertEqual(self.requests('/v1/external/request')[0]['body'], {'run_id': 'run-1'})
        self.assertIn('"model": "gpt-test"', self.page.text('.external-request-record'))

    def test_rejected_stream_is_kept_aside_and_not_added_to_history(self):
        self.open_external(ndjson({'type': 'delta', 'delta': 'Rozpracovaná část'},
                                  {'type': 'error', 'error': 'Poskytovatel odpověď odmítl.', 'status': 502,
                                   'outcome': 'failed'}))
        self.send('Otázka')
        page = self.page
        self.assertTrue(page.text('#chat-operation-status').startswith('Poskytovatel odpověď odmítl.'))
        notice = page.evaluate("""(()=>{const item=document.querySelector('#chat-messages [data-incomplete="true"]');
          return item?{label:item.querySelector('strong').textContent,body:item.querySelector('pre').textContent}:null;})()""")
        self.assertEqual(notice['body'], 'Rozpracovaná část')
        self.assertIn('není součástí historie', notice['label'])
        self.assertIsNone(page.evaluate('activeThread'))
        self.assertIsNone(page.evaluate('pendingChatRequest'))


@require_browser
class ManualExternalCallTests(ExternalActions, UiFlowCase):
    def scripted(self):
        api = external_api(ndjson())
        preview = {'approval_id': 'appr-1', 'preview_sha256': 'e' * 64, 'privacy': 'project',
                   'target': {'provider': 'OpenAI', 'model': 'gpt-test'}, 'messages': ['Otázka']}
        api.route('/v1/external/preview', preview)
        api.route('/v1/external/cancel', {'cancelled': True})
        api.route('/v1/external/confirm', lambda body: {'thread': {
            'thread_id': 'th-x', 'project_id': None, 'revision': 1, 'turns': [], 'messages': [
                {'message_id': 'u', 'role': 'user', 'content': 'Otázka', 'privacy': 'project',
                 'created_at': '2026-11-20T10:00:00Z'},
                {'message_id': 'a', 'role': 'assistant', 'content': 'Potvrzená odpověď', 'privacy': 'project',
                 'created_at': '2026-11-20T10:00:01Z'}]}})
        api.route('/v1/external/propose', lambda body: {
            'proposal': {'purpose': 'Ověřit fakt', 'message_ids': []},
            'source': {'available_message_ids': [body['message_id']]}})
        self.start(api=api)
        self.open_project_chat_external()
        self.page.fill('#chat-draft', 'Otázka')

    def test_manual_call_is_sent_only_after_reviewed_preview_and_privacy_confirmation(self):
        self.scripted()
        page = self.page
        page.click('#external-preview-button')
        page.wait_js("!document.querySelector('#external-preview').hidden", 'external preview')
        request = self.requests('/v1/external/preview')[0]['body']
        self.assertEqual(request['run_choice']['adapter'], 'openai-responses')
        self.assertEqual(page.text('#chat-operation-status'),
                         'Externí požadavek ještě nebyl odeslán. Zkontrolujte náhled.')
        self.assertTrue(page.evaluate("document.querySelector('#external-confirm').disabled"))
        # AUDIT-B7-T1 fix: the button stayed disabled (null currentTarget after await).
        page.wait_idle()
        self.assertFalse(page.evaluate("document.querySelector('#external-preview-button').disabled"))
        page.click('#external-cancel')
        page.wait(lambda: self.requests('/v1/external/cancel'), 'cancel')
        page.wait_idle()
        self.assertEqual(self.requests('/v1/external/cancel')[0]['body'], {'approval_id': 'appr-1'})
        self.assertEqual(page.text('#chat-operation-status'), 'Externí odeslání bylo zrušeno.')
        page.click('#external-preview-button')
        page.wait_js("!document.querySelector('#external-preview').hidden", 'external preview')
        page.click('#external-privacy-confirm')
        page.click('#external-confirm')
        page.wait(lambda: self.requests('/v1/external/confirm'), 'confirm')
        page.wait_idle()
        self.assertEqual(self.requests('/v1/external/confirm')[0]['body'], {
            'approval_id': 'appr-1', 'preview_sha256': 'e' * 64, 'approved': True, 'privacy': 'project'})
        self.assertEqual(page.text('#chat-operation-status'), 'Externí odpověď byla přijata.')
        self.assertIn('Potvrzená odpověď', page.text('#chat-messages'))
        self.assert_no_page_errors()

    def test_ollama_proposal_only_suggests_context_and_sends_nothing(self):
        self.scripted()
        page = self.page
        page.click('#external-propose-button')
        page.wait_js("!document.querySelector('#external-proposal').hidden", 'proposal')
        self.assertEqual(page.text('#external-proposal-purpose'), 'Ověřit fakt')
        self.assertEqual(page.text('#chat-operation-status'), 'Ollama pouze navrhla výběr. Zkontrolujte nebo upravte jej.')
        boxes = page.evaluate("[...document.querySelectorAll('#external-proposal-messages input')]"
                              ".map(x=>[x.checked,x.disabled])")
        self.assertEqual(boxes, [[True, True]], 'The current message is always included')
        page.click('#external-proposal-cancel')
        self.assertEqual(page.text('#chat-operation-status'), 'Návrh Ollamy byl zahozen; nic nebylo odesláno externě.')
        self.assertEqual(self.requests('/v1/external/preview'), [])
        self.assertEqual(self.requests('/v1/external/confirm'), [])
