# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from uuid import uuid4
from tests.ui_flow_case import UiFlowCase, require_browser


@require_browser
class ChatAttemptBrowserTests(UiFlowCase):
    def test_long_multiline_task_reaches_model_and_publishes_reviewed_document(self):
        from spikes.projects import Projects
        body = '# Postup\n\n1. Zpracovat podklady.\n2. Zkontrolovat výsledek.\n'
        page = self.start(answers=[dict(schema_version=1, kind='artifact-draft',
            artifact_kind='document', title='Postup', content=body)])
        self.open_project_chat();page.fill('#task-output-kind','document')
        prompt = ('Podklady a podmínky: zachovej češtinu, sestav postup, uveď kontrolu a nejasnosti.\n'*400).strip()
        self.submit_prompt(prompt)
        self.assertEqual(len(self.ollama.requests),1)
        self.assertIn(prompt,self.ollama.requests[0]['prompt'])
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"),'')
        self.assertTrue(page.evaluate("document.querySelector('#chat-failed-inputs').hidden"))
        self.click_text('Uložit do projektu','#chat-messages')
        page.wait(lambda:self.requests('/v1/tasks/artifact'),'confirmed document publication');page.wait_idle()
        aid=self.requests('/v1/tasks/artifact')[0]['body']['artifact_id']
        git=Projects(self.node).repository(self.project_id)
        self.assertEqual(git.snapshot(git.head())['artifacts/'+aid+'/content.md'].decode(),body)
        self.assertEqual(len(self.ollama.requests),1)
        self.assert_no_page_errors()

    def test_long_failed_submission_survives_new_backend_and_profile_without_repeating_model(self):
        page = self.start(answers=[{}]); self.open_project_chat()
        prompt = ('Navrhni složitý postup s podklady, podmínkami a kontrolou výsledků.\n' * 400).strip()
        self.assertGreater(len(prompt), 16000)
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').maxLength"), -1)
        page.fill('#chat-privacy', 'confidential')
        self.submit_prompt(prompt)
        page.wait_js("!document.querySelector('#chat-failed-inputs').hidden", 'saved failed input')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), prompt)
        self.assertIn('Model nevrátil', page.text('#chat-failed-inputs'))
        first = self.requests('/v1/tasks/route-stream')
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]['body']['content'], prompt)
        old_origin = page.server.origin
        page.__exit__(None, None, None)
        page = self.start(); self.open_project_chat()
        self.assertNotEqual(page.server.origin, old_origin)
        page.wait_js("!document.querySelector('#chat-failed-inputs').hidden", 'failed input after restart')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), '')
        page.click('#chat-failed-inputs summary')
        self.assertTrue(page.visible('#chat-failed-inputs button'))
        page.click('#chat-failed-inputs button')
        page.wait_js("document.querySelector('#chat-draft').value.length>16000", 'explicit prompt restore')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), prompt)
        self.assertEqual(self.requests('/v1/tasks/route-stream'), [])
        self.assertEqual(page.evaluate("document.querySelector('#chat-privacy').value"), 'confidential')
        self.assertIn('Zpracování nebylo spuštěno', page.text('#chat-operation-status'))
        page.click('#chat-failed-inputs button:nth-of-type(2)')
        page.wait_js("document.querySelector('#chat-failed-inputs').hidden", 'remove stored prompt')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), prompt)
        self.assertEqual(self.requests('/v1/tasks/route-stream'), [])
        self.assert_no_page_errors()

    def test_successful_old_response_preserves_new_text_typed_during_run(self):
        page = self.start(); self.open_project_chat()
        page.evaluate("streamRequest=async(path,request)=>{window.submitted=request;return new Promise(resolve=>window.releaseRun=resolve)}")
        page.fill('#chat-draft', 'Original submitted text')
        page.evaluate("document.querySelector('#chat-composer').requestSubmit()")
        page.wait_js('window.releaseRun', 'pending model result')
        page.fill('#chat-draft', 'NEXT text typed while the model works')
        page.evaluate("""(()=>{const r=window.submitted;window.releaseRun({projection:{task_id:r.task_id,
          project_id:r.project_id,thread_id:r.thread_id,privacy:r.privacy,created_at:r.created_at,
          state:'completed',temporary:false,prompt:{message_id:r.message_id,content:r.content,privacy:r.privacy},
          outcome:{schema_version:1,kind:'direct-answer',content:'Completed answer'}}});})()""")
        page.wait_js("document.querySelector('#chat-operation-status').textContent==='Odpověď je připravena.'", 'old run complete')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), 'NEXT text typed while the model works')
        self.assert_no_page_errors()

    def test_current_file_control_is_disabled_for_every_external_backend(self):
        page = self.start(); self.open_project_chat()
        aid = str(uuid4())
        page.evaluate('currentArtifacts=[{id:'+json.dumps(aid)+',title:"Selected document"}];selectedArtifact='+json.dumps(aid))
        for adapter in ['ollama','openai-responses','atlascloud-text','anthropic-messages','gemini-generate','xai-responses']:
            with self.subTest(adapter=adapter):
                state = page.evaluate("""(()=>{const select=document.querySelector('#chat-run-adapter');
                  const option=document.createElement('option');option.value="""+json.dumps(adapter)+""";
                  select.append(option);select.value=option.value;
                  const input=document.querySelector('#task-source-current-file-input');input.checked=true;
                  refreshCurrentFileSource();return {disabled:input.disabled,checked:input.checked};})()""")
                self.assertEqual(state, dict(disabled=adapter!='ollama',checked=adapter=='ollama'))

    def test_oversized_unicode_input_stays_intact_without_dispatch(self):
        page = self.start(); self.open_project_chat()
        prompt = 'ě' * 530000  # Character count fits; UTF-8 byte count exceeds 1 MiB.
        page.fill('#chat-draft', prompt)
        page.evaluate("document.querySelector('#chat-composer').requestSubmit()")
        page.wait_js("document.querySelector('#chat-operation-status').textContent.includes('1 MiB')", 'byte limit')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), prompt)
        self.assertEqual(self.requests('/v1/tasks/route-stream'), [])
        self.assertEqual(self.ollama.requests, [])
