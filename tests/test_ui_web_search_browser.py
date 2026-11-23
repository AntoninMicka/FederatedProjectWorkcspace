# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Web search, public sources and research timeline in a real browser (AUDIT-B7-T1).

Replaces the source-text assertions of
``test_web_search_ui_requires_exact_preview_and_renders_sources_as_text``.
"""
import json

from tests.browser_harness import Reply
from tests.ui_flow_case import FakeApi, UiFlowCase, final_evaluation, require_browser, search_request

HOSTILE_RESULT = {'title': '<b>Titulek</b>', 'url': 'https://example.org/med',
                  'content': '<img src=x onerror=window.__pwned=1>Úryvek o mědi'}


@require_browser
class WebSearchFlowTests(UiFlowCase):
    def prepare_search(self, *, answers=None, api=None):
        self.start(answers=answers or [search_request(), final_evaluation()],
                   results=[HOSTILE_RESULT], api=api)
        self.open_project_chat()
        sent = self.submit_prompt('Jaká je cena mědi?', action='search')
        self.assert_prompt_status('Návrh je připraven ke kontrole.', sent)
        before = len(self.page.api.requests)
        self.click_text('Připravit ruční kontrolu')
        self.page.wait_js("!document.querySelector('#search-preview').hidden", 'search preview')
        return before

    def test_query_leaves_only_after_reviewing_the_exact_preview(self):
        before = self.prepare_search()
        page = self.page
        preview = self.requests('/v1/tasks/search/preview', before)
        self.assertEqual(len(preview), 1)
        self.assertTrue(preview[0]['authenticated'])
        self.assertEqual(set(preview[0]['body']),
                         {'task_id', 'search_id', 'synthesis_run_id', 'synthesis_manifest_id'})
        # The approval replaces the composer inside the prompt widget.
        self.assertEqual(page.text('#search-preview-query'), 'cena mědi LME')
        self.assertIn('soukromí: project · kolo 1', page.text('#search-preview-summary'))
        self.assertTrue(page.evaluate("Boolean(document.querySelector('#search-preview').closest('#prompt-widget'))"))
        self.assertTrue(page.evaluate("Boolean(document.querySelector('#search-recovery').closest('#chat-panel'))"))
        self.assertFalse(page.visible('#chat-composer'))
        self.assertEqual(self.searx.queries, [], 'Nothing may be searched before confirmation')
        self.assertTrue(page.evaluate("document.querySelector('#search-confirm').disabled"))
        page.click('#search-confirm-check')
        self.assertFalse(page.evaluate("document.querySelector('#search-confirm').disabled"))
        page.click('#search-confirm')
        page.wait_js("document.querySelector('#search-preview').hidden", 'confirmation to finish')
        confirm = self.requests('/v1/tasks/search/confirm', before)
        self.assertEqual(len(confirm), 1)
        self.assertEqual(confirm[0]['body']['approved'], True)
        self.assertEqual(confirm[0]['body']['search_id'], preview[0]['body']['search_id'])
        self.assertRegex(confirm[0]['body']['preview_sha256'], '^[0-9a-f]{64}$')
        self.assertEqual(self.searx.queries, ['cena mědi LME'])
        self.assertTrue(page.visible('#chat-composer'))
        self.assertEqual(page.text('#chat-operation-status'), 'Řízené hledání a syntéza jsou dokončené.')

        # Untrusted results stay inert text: no markup, image or link is created.
        messages = page.text('#chat-messages')
        for text in ('<b>Titulek</b>', 'https://example.org/med', '<img src=x onerror=window.__pwned=1>Úryvek o mědi',
                     'Měď stojí 9 USD.', 'finálnost je hodnocení modelu'):
            self.assertIn(text, messages)
        self.assertEqual(page.evaluate("document.querySelectorAll('#chat-messages img,#chat-messages b').length"), 0)
        self.assertEqual(page.evaluate("document.querySelectorAll('#chat-messages a[href]').length"), 0)
        self.assertIsNone(page.evaluate('window.__pwned ?? null'))
        # Timeline: prompt, proposal, search round and final answer in order.
        kinds = page.evaluate("""[...document.querySelectorAll('#chat-messages > *')].map(x=>
          x.matches('.chat-message.user')?'message':x.matches('.timeline-record.task-outcome')?'round':
          x.matches('.task-outcome')?'task':x.matches('.chat-message.assistant')?'answer':x.className)""")
        self.assertEqual(kinds, ['message', 'task', 'round', 'answer'])
        self.assert_no_page_errors()

    def test_cancel_returns_the_composer_without_searching(self):
        self.prepare_search()
        self.page.click('#search-confirm-check')
        self.page.click('#search-cancel')
        self.assertTrue(self.page.evaluate("document.querySelector('#search-preview').hidden"))
        self.assertTrue(self.page.visible('#chat-composer'))
        self.assertFalse(self.page.evaluate("document.querySelector('#search-confirm-check').checked"))
        self.assertEqual(self.requests('/v1/tasks/search/confirm'), [])
        self.assertEqual(self.searx.queries, [])

    def test_unfinished_round_asks_the_user_to_refine_the_next_query(self):
        unfinished = final_evaluation(assessment='intermediate', answer='Zatím nevím.',
                                      limitations=['Chybí zdroj LME.'])
        self.prepare_search(answers=[search_request(), unfinished])
        page = self.page
        page.click('#search-confirm-check')
        page.click('#search-confirm')
        page.wait_js("document.querySelector('#search-preview').hidden", 'confirmation to finish')
        self.assertEqual(page.text('#chat-operation-status'),
                         'Kolo není konečné. Napište do pole dole vlastní zpřesnění; '
                         'před odesláním jej zkontrolujete.')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').placeholder"),
                         'Zpřesněte další kolo hledání…')
        self.assertIn('Výsledek není konečný. Zpřesnění dalšího kola napište do pole dole.',
                      page.text('#chat-messages'))
        first = self.requests('/v1/tasks/search/confirm')[0]['body']['search_id']
        before = len(page.api.requests)
        page.fill('#chat-draft', 'cena mědi LME listopad 2026')
        page.evaluate("document.querySelector('#chat-composer').requestSubmit()")
        page.wait_js("!document.querySelector('#search-preview').hidden", 'second preview')
        second = self.requests('/v1/tasks/search/preview', before)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]['body']['query'], 'cena mědi LME listopad 2026')
        self.assertEqual(second[0]['body']['parent_search_id'], first)
        self.assertEqual(page.text('#search-preview-query'), 'cena mědi LME listopad 2026')
        self.assertIn('kolo 2', page.text('#search-preview-summary'))
        self.assertEqual(self.searx.queries, ['cena mědi LME'], 'The refinement is only previewed')

    def test_missing_configuration_offers_recovery_from_the_reviewed_preview(self):
        api = FakeApi()
        api.route('/v1/tasks/search/confirm', Reply({
            'error': 'SearXNG není nakonfigurován.', 'diagnostic': 'not-configured',
            'outcome': 'failed', 'retry': 'configure-search'}, status=422))
        self.prepare_search(api=api)
        page = self.page
        reviewed = page.evaluate('pendingSearchPreview.preview.binding')
        self.assertTrue(page.evaluate("document.querySelector('#search-recovery').hidden"))
        page.click('#search-confirm-check')
        page.click('#search-confirm')
        page.wait_js("!document.querySelector('#search-recovery').hidden", 'recovery offer')
        self.assertEqual(page.text('#search-recovery'), 'Obnovit SearXNG z tohoto náhledu')
        self.assertEqual(page.text('#search-preview-status'), 'SearXNG není nakonfigurován.')
        before = len(page.api.requests)
        page.click('#search-recovery')
        page.wait_js("document.querySelector('#search-recovery').hidden", 'recovery to finish')
        configure = self.requests('/v1/search/configure', before)
        self.assertEqual([item['body'] for item in configure], [reviewed])
        self.assertEqual(page.text('#chat-operation-status'),
                         'Nastavení SearXNG bylo obnoveno. Dotaz můžete potvrdit znovu.')
        self.assertFalse(page.evaluate("document.querySelector('#search-confirm').disabled"))

    def test_preview_failure_without_binding_opens_search_settings(self):
        api = FakeApi()
        api.route('/v1/tasks/search/preview', Reply({
            'error': 'SearXNG není nakonfigurován.', 'retry': 'configure-search'}, status=422))
        self.start(answers=[search_request()], api=api)
        self.open_project_chat()
        self.submit_prompt('Jaká je cena mědi?', action='search')
        self.click_text('Připravit ruční kontrolu')
        page = self.page
        page.wait_js("!document.querySelector('#search-recovery').hidden", 'recovery offer')
        self.assertEqual(page.text('#search-recovery'), 'Otevřít nastavení SearXNG')
        page.click('#search-recovery')
        page.wait_js("!document.querySelector('#settings-view').hidden", 'settings')
        self.assertEqual(self.requests('/v1/search/configure'), [])

    def test_search_settings_are_tested_and_saved_as_entered(self):
        self.start(configure_search=False)
        page = self.page
        page.evaluate('openSettings()')
        page.wait_js("!document.querySelector('#settings-view').hidden", 'settings')
        page.evaluate("openBackendSettings({backend_id:'searxng',display_name:'SearXNG',detail:''})")
        page.fill('#search-backend-form [name=endpoint]', self.searx.endpoint)
        page.fill('#search-backend-form [name=result_limit]', '2')
        before = len(page.api.requests)
        page.click('#search-backend-test')
        page.wait(lambda: self.requests('/v1/search/test', before), 'search test request')
        page.settle(0.5)
        tested = self.requests('/v1/search/test', before)[0]['body']
        self.assertEqual((tested['endpoint'], tested['result_limit'], tested['adapter']),
                         (self.searx.endpoint, 2, 'searxng'))
        self.assertEqual(self.searx.queries, ['SearXNG'], 'The test sends only the fixed public query')
        page.evaluate("document.querySelector('#search-backend-form').requestSubmit()")
        page.wait(lambda: self.requests('/v1/search/configure', before), 'search configure request')
        page.settle(0.5)
        saved = page.evaluate("projectRequest('/v1/chat/status',{}).then(r=>r.search_binding)")
        self.assertEqual((saved['endpoint'], saved['result_limit']), (self.searx.endpoint, 2))


@require_browser
class PublicSourceFlowTests(UiFlowCase):
    def test_page_is_fetched_only_after_approval_and_shown_as_inert_text(self):
        api = FakeApi()
        preview = {'preview_sha256': 'a' * 64, 'url': 'https://example.org/med', 'robots': 'allowed'}
        result = {'task_id': None, 'run_id': None, 'text': '<script>window.__pwned=1</script>Původní text',
                  'projection': {'title': 'Ceny kovů', 'blocks': [
                      {'type': 'heading', 'level': 2, 'text': 'Měď', 'anchor': 'h-med', 'heading_path': ['Měď']},
                      {'type': 'table', 'anchor': 't-1', 'heading_path': ['Měď'], 'caption': 'Ceník',
                       'header_rows': [0], 'rows': [['Kov', 'Cena'], ['<b>Měď</b>', '9 USD']]},
                      {'type': 'list-item', 'anchor': 'l-1', 'heading_path': ['Měď'], 'depth': 2,
                       'ordered': False, 'text': 'Bod seznamu'}]},
                  'result': {'text_sha256': 'b' * 64, 'text_length': 24,
                             'projection': {'block_count': 3, 'sha256': 'c' * 64}}}

        def confirm(body):
            return dict(result, task_id=body['task_id'], run_id=body['run_id'])
        api.route('/v1/tasks/public-source/preview', preview)
        api.route('/v1/tasks/public-source/confirm', confirm)
        self.start(answers=[search_request(), final_evaluation()], results=[HOSTILE_RESULT], api=api)
        self.open_project_chat()
        sent = self.submit_prompt('Jaká je cena mědi?', action='search')
        self.assert_prompt_status('Návrh je připraven ke kontrole.', sent)
        self.click_text('Připravit ruční kontrolu')
        page = self.page
        page.wait_js("!document.querySelector('#search-preview').hidden", 'search preview')
        page.click('#search-confirm-check')
        page.click('#search-confirm')
        page.wait_js("document.querySelector('#search-preview').hidden", 'search to finish')
        before = len(page.api.requests)
        self.click_text('Načíst stránku')
        page.wait_js("!document.querySelector('#public-source-preview').hidden", 'source preview')
        planned = self.requests('/v1/tasks/public-source/preview', before)[0]['body']
        self.assertEqual(set(planned), {'task_id', 'search_id', 'source_id', 'run_id'})
        self.assertIn('"robots": "allowed"', page.text('#public-source-preview-content'))
        self.assertTrue(page.evaluate("document.querySelector('#public-source-confirm').disabled"))
        page.click('#public-source-confirm-check')
        page.click('#public-source-confirm')
        page.wait_js("!document.querySelector('#public-source-result').hidden", 'source result')
        page.wait_js("document.querySelector('#chat-operation-status').textContent === "
                     "'Veřejný zdroj byl načten jako inertní nedůvěryhodný text.'",
                     'source projection refresh to finish')
        confirmed = self.requests('/v1/tasks/public-source/confirm', before)[0]['body']
        self.assertEqual((confirmed['approved'], confirmed['preview_sha256'], confirmed['run_id']),
                         (True, 'a' * 64, planned['run_id']))
        view = '#public-source-result'
        self.assertEqual(page.evaluate(f"""[...document.querySelectorAll('{view} .public-source-block')]
          .map(x=>x.dataset.anchor)"""), ['h-med', 't-1', 'l-1'])
        self.assertEqual(page.evaluate(f"""[...document.querySelectorAll('{view} table tr')]
          .map(r=>[...r.children].map(c=>c.tagName+':'+c.textContent))"""),
                         [['TH:Kov', 'TH:Cena'], ['TD:<b>Měď</b>', 'TD:9 USD']])
        self.assertEqual(page.evaluate(f"document.querySelectorAll('{view} b,{view} script').length"), 0)
        self.assertIn('do projektu nebylo nic zapsáno', page.text(f'{view} small'))
        self.assertTrue(page.visible(f'{view} .public-source-structured'))
        page.click(f'{view} [data-source-view="text"]')
        self.assertTrue(page.visible(f'{view} .public-source-text'))
        self.assertEqual(page.text(f'{view} .public-source-text'), result['text'])
        self.assertIsNone(page.evaluate('window.__pwned ?? null'))
        self.assertEqual(page.text('#chat-operation-status'),
                         'Veřejný zdroj byl načten jako inertní nedůvěryhodný text.')


@require_browser
class ResearchAutomationTests(UiFlowCase):
    def prepare_automatic(self):
        self.start(answers=[search_request(), final_evaluation()], results=[HOSTILE_RESULT])
        self.open_project_chat()
        self.submit_prompt('Jaká je cena mědi?', action='search')
        page = self.page
        modes = page.evaluate("""[...document.querySelectorAll('#chat-messages .task-outcome select')]
          .map(s=>[...s.options].map(o=>o.textContent))""")
        self.assertIn(['Ruční kontrola', 'Automaticky s odpočtem'], modes)
        page.evaluate("""(()=>{const mode=[...document.querySelectorAll('#chat-messages .task-outcome select')]
          .find(s=>[...s.options].some(o=>o.value==='automatic'));mode.value='automatic';
          mode.dispatchEvent(new Event('change',{bubbles:true}));})()""")
        self.click_text('Připravit automatiku')
        page.wait_js("[...document.querySelectorAll('#chat-messages button')].some(b=>b.textContent==='Aktivovat plán')",
                     'plan to be ready')

    def test_automatic_plan_needs_explicit_activation_and_send_now(self):
        self.prepare_automatic()
        page = self.page
        prepared = self.requests('/v1/autonomy/search/prepare')[0]['body']
        self.assertEqual((prepared['mode'], prepared['countdown_seconds']), ('automatic', 5))
        control = page.text('#chat-messages .timeline-control')
        for fact in ('Dotaz', 'cena mědi LME', 'Aktuální fáze', 'Limit', 'Privacy'):
            self.assertIn(fact, control)
        self.assertEqual(page.text('#chat-operation-status'), 'Automatický plán je připravený. '
                         'Zkontrolujte dotaz, cíl, privacy a budget a výslovně jej aktivujte.')
        # Declining the native confirmation activates nothing.
        page.dialog_answers.append(False)
        self.click_text('Aktivovat plán')
        page.settle(0.5)
        self.assertEqual(self.requests('/v1/autonomy/activate'), [])
        self.assertIn('Privacy: project', page.dialogs[-1][1])
        self.assertIn('Limit: 3 kroků / 3 cost / 300 s', page.dialogs[-1][1])
        self.click_text('Aktivovat plán')
        page.wait_js("[...document.querySelectorAll('#chat-messages button')].some(b=>b.textContent==='Odeslat nyní')",
                     'countdown')
        activated = self.requests('/v1/autonomy/activate')
        self.assertEqual(len(activated), 1)
        self.assertRegex(activated[0]['body']['activation_digest'], '^[0-9a-f]{64}$')
        self.assertEqual(self.searx.queries, [], 'The countdown has not elapsed yet')
        self.click_text('Odeslat nyní')
        page.wait(lambda: self.searx.queries, 'the search to be sent')
        self.assertEqual(len(self.requests('/v1/autonomy/send-now')), 1)
        self.assertEqual(self.searx.queries, ['cena mědi LME'])


@require_browser
class TimelineTests(UiFlowCase):
    """Ordering and representation rules of the chat timeline on scripted data."""

    def test_entries_are_ordered_by_time_then_kind_and_rounds_hide_their_steps(self):
        self.start(configure_search=False)
        entries = self.page.evaluate("""(()=>{
          const t=s=>'2026-11-20T10:00:0'+s+'Z';
          const thread={messages:[{message_id:'m1',created_at:t(1),role:'user',content:'otázka',privacy:'project'}]};
          const projection={task_id:'task-1',created_at:t(2),prompt:{message_id:'m1'},
            outcome:{kind:'web-search-answer'},
            search_workflow:{rounds:[{search_id:'s1',searched_at:t(3)}]},
            search:{search_id:'s1',searched_at:t(3)},
            public_sources:[{state:'succeeded',run_id:'r1',result:{fetched_at:t(4)}},
                            {state:'failed',run_id:'r2'}]};
          const orphan={task_id:'task-2',created_at:t(2)};
          const workflow={workflow_id:'w1',created_at:t(1),updated_at:t(8),
            steps:[{step_id:'st-round',state:'completed',action:{id:'search.iterative-query'},
                    input:{request:{task_id:'task-1',search_id:'s1'}},finished_at:t(3)},
                   {step_id:'st-fetch',state:'completed',action:{id:'source.fetch-public'},
                    result:{run_id:'r1'},finished_at:t(4)},
                   {step_id:'st-plan',state:'failed',action:{id:'research.plan-next'},finished_at:t(5)},
                   {step_id:'st-open',state:'queued',action:{id:'research.plan-next'}}],
            plan_revisions:[{revision:0},{revision:1,applied_at:t(6)}],
            revisions:[{ordinal:1,revision:1,cancelled_at:t(7)}]};
          return buildChatTimeline(thread,[projection,orphan],[workflow]).map(e=>e.kind+':'+e.stable_id);
        })()""")
        self.assertEqual(entries, [
            'message:000000000000',
            'task:task-2',
            'search-round:s1',
            # The answer takes the time of the last round, so it precedes a
            # source fetched later.
            'search-answer:task-1:answer',
            'public-source:r1',
            'research-step:st-plan',
            'research-revision:w1:revision:1',
            'research-edit:w1:edit:1:1',
            'research-control:w1:control'])

    def test_prompt_tasks_render_directly_under_their_message(self):
        self.start(configure_search=False)
        self.open_project_chat()
        order = self.page.evaluate("""(()=>{
          // Created after the second message, yet shown under the prompt it answers.
          taskOutcomes=[{task_id:'task-1',created_at:'2026-11-20T10:00:20Z',prompt:{message_id:'m1'},
            outcome:{kind:'direct-answer',content:'Odpověď'},state:'succeeded',privacy:'project'}];
          renderChat({thread_id:'t1',messages:[
            {message_id:'m1',created_at:'2026-11-20T10:00:00Z',role:'user',content:'První',privacy:'project'},
            {message_id:'m2',created_at:'2026-11-20T10:00:09Z',role:'user',content:'Druhá',privacy:'project'}]});
          return [...document.querySelectorAll('#chat-messages > *')].map(x=>x.firstChild.textContent);
        })()""")
        self.assertEqual(order, ['První', 'Odpověď', 'Druhá'])


@require_browser
class ResearchRecordTests(UiFlowCase):
    def test_planning_step_explains_decision_target_and_finish_reason(self):
        self.start(configure_search=False)
        card = self.page.evaluate("""(()=>{
          chatMessages.replaceChildren();
          renderResearchStepTimelineEntry({workflow:{workflow_id:'w1'},step:{step_id:'s1',state:'completed',
            privacy:'project',cost_units:1,elapsed_seconds:1.5,action:{id:'research.plan-next'},
            result:{decision:'finish',target_action:'research.compose-report',finish_reason:'goal-met'}}});
          const card=chatMessages.lastElementChild;
          return {heading:card.querySelector('h3').textContent,detail:card.querySelector('small').textContent,
                  state:card.dataset.state};
        })()""")
        self.assertEqual(card['heading'], 'Rozhodnutí o dalším kroku')
        self.assertEqual(card['state'], 'completed')
        self.assertEqual(card['detail'], 'completed · project · cost 1 · 1.500 s běhu · '
                         'rozhodnutí ukončit workflow (finish) · '
                         'cílová akce Sestavení návrhu zprávy · důvod ukončení goal-met')

    def test_workflow_without_next_step_is_advanced_once_per_state(self):
        api = FakeApi()
        workflow = {'workflow_id': 'w-recover', 'mode': 'automatic', 'state': 'queued', 'plan_revision': 2,
                    'steps': [{'step_id': 'st-1', 'state': 'completed',
                               'action': {'id': 'search.iterative-query'},
                               'input': {'request': {'task_id': 'task-recover'}}}],
                    'revision_proposals': []}
        api.route('/v1/autonomy/attach', {'attached': True})
        api.route('/v1/autonomy/advance', workflow)
        api.route('/v1/tasks/list', {'outcomes': []})
        self.start(configure_search=False, api=api)
        self.open_project_chat()
        # From now on the queue lists the workflow, as the backend would.
        api.route('/v1/autonomy/status', {'global_paused': False, 'workflows': [workflow]})
        page = self.page
        page.evaluate(f"""(()=>{{const workflow={json.dumps(workflow)};
          taskOutcomes=[{{task_id:'task-recover'}}];autonomyQueue={{global_paused:false,workflows:[workflow]}};
          scheduleAutomaticWorkflow(workflow);}})()""")
        page.wait(lambda: self.requests('/v1/autonomy/advance'), 'recovery advance')
        # The advance reloads the queue, which re-renders it and clears timers.
        page.wait_idle()
        page.evaluate(f"scheduleAutomaticWorkflow({json.dumps(workflow)})")
        page.settle(0.8)
        page.wait_idle()
        advanced = self.requests('/v1/autonomy/advance')
        self.assertEqual([item['body'] for item in advanced], [{'workflow_id': 'w-recover'}],
                         'The same settled state is recovered only once')
        changed = dict(workflow, plan_revision=3)
        page.evaluate(f"scheduleAutomaticWorkflow({json.dumps(changed)})")
        page.wait(lambda: len(self.requests('/v1/autonomy/advance')) == 2, 'advance after a new state')
