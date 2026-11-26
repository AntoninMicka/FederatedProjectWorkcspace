# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import json
from pathlib import Path
import re
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.project_creation import ProjectCreation
from spikes.project_relations import ProjectRelations
from tests.ui_flow_case import UiFlowCase, require_browser


@require_browser
class ProjectRelationsBrowserTests(UiFlowCase):
    def setUp(self):
        super().setUp()
        self.child = ProjectCreation(self.node).create('Podprojekt mostu', self.node.parent/'child', str(uuid4()))['id']
        self.artifacts = Artifacts(self.node); self.source, self.linked = str(uuid4()), str(uuid4())
        for id_,title,body in [(self.linked,'Navazující podklad','Doplňující údaje v dítěti.'),
                               (self.source,'Zadání mostu',f'# Most\n\nNosnost je 12 tun.\n\n[Navazující](artifacts/{self.linked}/content.md)\n')]:
            self.artifacts.save(dict(project_id=self.child, artifact_id=id_, base_head=self.artifacts.workspace(self.child).git.head(),
                                     title=title, body=body, new=True),str(uuid4()))

    def open(self,pid):
        self.page.evaluate(f'openRegisteredProject({json.dumps(pid)})')
        self.page.wait_js(f'activeProject?.id==={json.dumps(pid)}','open project');self.page.wait_idle()

    def dialog(self):
        self.page.evaluate("navigateMainTab(document.querySelector('#project-overview-tab'))")
        self.page.wait_idle()
        self.assertTrue(self.page.visible('#open-project-relations'))
        self.page.click('#open-project-relations')
        self.page.wait_js('relationOverview?.project_id===activeProject.id&&relationCatalog?.project_id===activeProject.id','relation overview')
        self.page.wait_idle()

    def confirm_step(self):
        page=self.page
        page.wait_js("!document.querySelector('#relations-review').hidden",'native preview')
        self.assertTrue(page.evaluate("document.querySelector('#relations-confirm').disabled"))
        before=len(self.requests('/v1/project-relations/confirm'))
        page.click('#relations-approved');page.click('#relations-confirm')
        page.wait(lambda:len(self.requests('/v1/project-relations/confirm'))>before,'native confirmation')
        page.wait_js("!document.querySelector('#relations-overview').hidden&&document.querySelector('#relations-status').textContent.includes('uložen')",'saved step')
        page.wait_idle()
        self.assertEqual(self.page.status(self.requests('/v1/project-relations/confirm')[-1]),200)

    def test_create_approve_navigate_preview_and_use_source_in_cited_task(self):
        def answer(request):
            citation=re.search(r'\[project:[^\]]+\]',request['prompt']).group(0)
            return dict(schema_version=1,kind='direct-answer',content='Nosnost je 12 tun. '+citation)
        page=self.start(configure_search=False,answers=[answer])
        self.open(self.project_id);self.dialog()
        page.click('#relations-create');page.fill('#relations-other',self.child)
        page.fill('#relations-reason','Dítě dodává podklady mostu')
        page.evaluate("document.querySelector('#relations-editor').requestSubmit()")
        self.confirm_step()
        self.assertEqual(page.evaluate('relationOverview.relations[0].state'),'pending')
        self.click_text('Potvrdit za tento projekt','#relations-list');self.confirm_step()
        self.assertEqual(page.evaluate('relationOverview.relations[0].state'),'pending')
        self.click_text('Otevřít projekt','#relations-list')
        page.wait_js(f'activeProject?.id==={json.dumps(self.child)}','navigate child');page.wait_idle()
        self.dialog();self.click_text('Potvrdit za tento projekt','#relations-list');self.confirm_step()
        self.assertEqual(page.evaluate('relationOverview.relations[0].state'),'active')
        self.click_text('Otevřít projekt','#relations-list')
        page.wait_js(f'activeProject?.id==={json.dumps(self.project_id)}','return parent');page.wait_idle()
        page.fill('#chat-draft','Rozepsané zadání zůstává')
        self.dialog();page.fill('#relations-query','Zadání mostu')
        card=f'#relations-sources [data-artifact-id="{self.source}"]'
        page.click(card+' button')
        page.wait_js("document.querySelector('#relations-preview-content').textContent.includes('12 tun')",'inherited source preview')
        self.assertEqual(page.evaluate('activeProject.id'),self.project_id)
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"),'Rozepsané zadání zůstává')
        page.click('#relations-preview-content .artifact-link')
        page.wait_js("document.querySelector('#relations-preview-title').textContent==='Navazující podklad'",'source link without switching project')
        self.assertEqual(page.evaluate('activeProject.id'),self.project_id)
        page.click('#relations-preview .relations-back')
        self.click_text('Použít v zadání',card)
        page.wait_js("!document.querySelector('#relations-dialog').open&&selectedRelationInputs().length===1",'explicit shared input')
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"),'Rozepsané zadání zůstává')
        page.wait_js("document.querySelector('#chat-run-adapter option[value=\"ollama\"]')",'Ollama selector')
        page.fill('#chat-run-adapter','ollama');page.fill('#chat-run-model','aggregate:ollama/'+self.ollama.model)
        selected=page.evaluate('selectedRelationInputs()[0]')
        sent=self.submit_prompt('Jaká je nosnost mostu podle vybraného podkladu?')
        route=[r for r in sent if r['path'].startswith('/v1/tasks/route')][-1]
        self.assertEqual(page.status(route),200,page.response_json(route))
        self.assertEqual(route['body']['selected_relation_inputs'],[selected])
        try:
            page.wait_js("document.querySelector('#chat-messages').textContent.includes('Nosnost je 12 tun.')",'completed cited answer')
        except AssertionError:
            self.fail(str((page.text('#chat-operation-status'),page.response_json(route),page.exceptions)))
        self.assertIn('Nosnost je 12 tun.',page.text('#chat-messages'))
        self.assertIn(selected['pin']['source']['commit_id'],page.text('#chat-messages'))
        prompt=self.ollama.requests[-1]['prompt']
        self.assertIn(self.source,prompt);self.assertNotIn('Doplňující údaje v dítěti.',prompt)
        self.assert_no_page_errors()
        page.evaluate('openProjectRelations()');page.wait_idle()
        shot=page._call('Page.captureScreenshot',{'format':'png'},session=page._session)
        Path('/tmp/project-relations-ui-preview.png').write_bytes(base64.b64decode(shot['data']))
        self.click_text('Upravit typ / směr','#relations-list')
        page.fill('#relations-type','depends_on');page.fill('#relations-direction','incoming')
        page.fill('#relations-reason','Rodič nově poskytuje publikované výstupy')
        page.evaluate("document.querySelector('#relations-editor').requestSubmit()")
        self.confirm_step()
        self.assertEqual(page.evaluate('relationOverview.relations[0].type'),'depends_on')
        self.assertEqual(page.evaluate('relationOverview.relations[0].orientation'),'incoming')
        self.assertEqual(page.evaluate('relationOverview.relations[0].state'),'pending')
        page.evaluate("window.prompt=()=> 'Ukončení při ověření UI'")
        self.click_text('Ukončit vazbu za tento projekt','#relations-list');self.confirm_step()
        self.assertEqual(page.evaluate('relationOverview.relations[0].state'),'revoked')
        self.assert_no_page_errors()


    def test_stale_selected_source_is_rejected_before_a_provider_call(self):
        lifecycle=ProjectRelations(self.node)
        envelope=lifecycle.proposal_preview(self.project_id,self.child,'parent_of','Platná vazba')
        lifecycle.confirm(envelope['preview'],envelope['sha256'],str(uuid4()),confirm=True)
        rid=envelope['preview']['record']['id'];owner=min(self.project_id,self.child)
        for pid in (self.project_id,self.child):
            op=str(uuid4());e=lifecycle.evidence_preview(owner,rid,pid,op)
            lifecycle.confirm(e['preview'],e['sha256'],op,confirm=True)
        page=self.start(configure_search=False);self.open(self.project_id);self.dialog()
        page.fill('#relations-query','Zadání mostu');self.click_text('Použít v zadání',f'#relations-sources [data-artifact-id="{self.source}"]')
        page.wait_js('selectedRelationInputs().length===1','shared selection');page.wait_idle()
        page.fill('#chat-run-adapter','ollama');page.fill('#chat-run-model','aggregate:ollama/'+self.ollama.model)
        op=str(uuid4());e=lifecycle.evidence_preview(owner,rid,self.child,op,revoke=True,reason='Vazba odebrána')
        lifecycle.confirm(e['preview'],e['sha256'],op,confirm=True)
        before=len(self.ollama.requests);sent=self.submit_prompt('Použij starý vybraný podklad.')
        route=[r for r in sent if r['path'].startswith('/v1/tasks/route')][-1]
        events=page.response_json(route)
        if isinstance(events,dict): events=[events]
        self.assertTrue(any(e.get('type')=='error' for e in events),events)
        self.assertEqual(len(self.ollama.requests),before)
        self.assertEqual(page.evaluate("document.querySelector('#chat-draft').value"),'Použij starý vybraný podklad.')
        self.assert_no_page_errors()
