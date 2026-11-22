# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
from uuid import uuid4
from tests.ui_flow_case import UiFlowCase, require_browser


@require_browser
class ChatAttemptBrowserTests(UiFlowCase):
    def test_privacy_conflict_explicit_target_only_recovery_and_reviewed_roadmap_save(self):
        self.privacy_roadmap_flow()

    def test_explicit_privacy_override_keeps_inputs_and_saves_only_after_review(self):
        self.privacy_roadmap_flow(override=True)

    def privacy_roadmap_flow(self, *, override=False):
        from spikes.artifacts import Artifacts
        from spikes.projects import Projects
        from spikes.markdown_documents import main_todo_id
        from spikes.metadata import validate_snapshot
        git = Projects(self.node).repository(self.project_id)
        target = main_todo_id(self.project_id)
        original = ('<!-- fpw-plan-profile: software-development/v1 -->\n'
            '- [ ] [MILESTONE-DEV] Vývoj\n  - type: milestone\n'
            '  - [ ] [EXISTING-BATCH] Původní dávka\n    - type: batch\n')
        Artifacts(self.node).save(dict(project_id=self.project_id, artifact_id=target,
            new=True, base_head=git.head(), title='Hlavní seznam úkolů', body=original), str(uuid4()))
        secret = str(uuid4())
        Artifacts(self.node).save(dict(project_id=self.project_id, artifact_id=secret,
            new=True, base_head=git.head(), title='Důvěrný podklad', body='PRIVATE CONTEXT'),
            str(uuid4()), privacy='confidential')
        addition = ('  - [ ] [AGENT-BATCH] Správa uzlu\n    - type: batch\n'
            '    - [ ] [AGENT-DESIGN] Navrhnout agenta\n      - type: task\n'
            '    - [ ] [AGENT-IMPL] Implementovat agenta\n      - type: task\n')
        from spikes.roadmap_additions import OUTPUT
        proposal = dict(kind=OUTPUT, additions=[dict(parent_id='MILESTONE-DEV', batch_id='AGENT-BATCH',
            batch_title='Správa uzlu', batch_description='', tasks=[
                dict(id='AGENT-DESIGN',title='Navrhnout agenta',description='',depends_on=[]),
                dict(id='AGENT-IMPL',title='Implementovat agenta',description='',depends_on=[])])])
        page = self.start(answers=[proposal])
        self.open_project_chat(); page.fill('#task-output-kind', 'file-edit')
        page.fill('#task-edit-target', target); page.fill('#task-edit-format', 'blocks')
        page.wait_js('taskFileEditScopeKey!==null', 'Markdown scope loaded')
        page.evaluate("document.querySelector('#task-source-artifacts').checked=true;"
            "document.querySelectorAll('#task-artifact-list input').forEach(i=>i.checked=true)")
        prompt = 'doplň seznam úkolů o úkoly pro návrh a implementaci sw agenta pro správu sw a nastavení uzlu sítě'
        before = git.head(); self.submit_prompt(prompt)
        page.wait_js("!document.querySelector('#chat-edit-privacy').hidden", 'specific privacy conflict')
        self.assertIn('Důvěrné', page.text('#chat-edit-privacy'))
        self.assertEqual(self.ollama.requests, []); self.assertEqual(before, git.head())
        page.fill('#chat-privacy', 'confidential')
        self.submit_prompt(prompt)
        page.wait_js("!document.querySelector('#chat-edit-privacy').hidden", 'private prompt refusal')
        self.assertTrue(page.evaluate("document.querySelector('#chat-edit-target-only').disabled"))
        self.assertEqual(self.ollama.requests, [])
        page.fill('#chat-privacy', 'project')
        self.submit_prompt(prompt)
        page.wait_js("!document.querySelector('#chat-edit-privacy').hidden", 'source-only refusal again')
        if override:
            page.dialog_answers.append(False)
            page.click('#chat-edit-override'); page.wait_idle()
            self.assertEqual(self.ollama.requests, [])
            page.evaluate("document.querySelector('#task-source-conversation').checked=false")
            page.click('#chat-edit-override'); page.wait_idle()
            self.assertEqual(self.ollama.requests, [])
            self.assertIn('Vstupy se změnily', page.text('#chat-operation-status'))
            page.evaluate("document.querySelector('#task-source-conversation').checked=true")
            self.submit_prompt(prompt)
            page.wait_js("!document.querySelector('#chat-edit-privacy').hidden", 'fresh privacy review')
            page.click('#chat-edit-override'); page.wait_idle()
        else:
            page.click('#chat-edit-target-only'); page.wait_idle()
        if not override:
            self.assertEqual(self.ollama.requests, [])
            self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"), prompt)
            self.assertEqual(page.evaluate("document.querySelector('#chat-privacy').value"), 'project')
            self.assertFalse(page.evaluate("document.querySelector('#task-source-conversation').checked"))
            self.assertEqual(page.evaluate("[...document.querySelectorAll('#task-artifact-list input:checked')].map(i=>i.value)"), [target])
            self.submit_prompt(prompt)
        self.assertEqual(len(self.ollama.requests), 1, page.text('#chat-operation-status'))
        self.assertEqual('PRIVATE CONTEXT' in self.ollama.requests[0]['prompt'], override)
        self.assertIn('Zkontrolovat úpravy ve společném editoru', self.buttons(),
            page.text('#chat-operation-status'))
        self.click_text('Zkontrolovat úpravy ve společném editoru')
        page.wait_js('artifactEditorTaskEdit!==null', 'review editor')
        page.evaluate("document.querySelector('#artifact-editor-form').requestSubmit()")
        page.wait_js("document.querySelector('#task-file-edit-dialog').open", 'explicit save approval')
        self.assertEqual(before, git.head())
        if override:self.assertIn('Výslovná výjimka',page.text('#task-file-edit-target'))
        page.click('#task-file-edit-approved'); page.click('[data-file-edit-choice=save]')
        page.wait(lambda:git.head()!=before, 'native reviewed save'); page.wait_idle()
        files = git.snapshot(git.head())
        self.assertEqual(files[f'artifacts/{target}/content.md'].decode(), original.replace('  - type: milestone\n','  - type: milestone\n'+addition))
        self.assertEqual(validate_snapshot(files)[target]['privacy'], 'project')
        self.assertEqual(files[f'artifacts/{secret}/content.md'].decode(), 'PRIVATE CONTEXT')
        self.assert_no_page_errors()

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
