# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Real desktop navigation, editor return and roadmap geometry in an isolated project."""
import json
from uuid import uuid4
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.artifacts import Artifacts
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.chat_service import ChatService
from tests.test_plan_draft import PlanDraftTests

app = QApplication([])
fixture = PlanDraftTests(); fixture.setUp()
body = '<!-- fpw-plan-profile: software-development/v1 -->\n- [ ] [MILESTONE-01] Milník\n  - type: milestone\n'
for batch in range(1, 5):
    body += f'  - [ ] [BATCH-{batch:02}] Dávka dlouhého názvu '+('popis ' * 20)+'\n    - type: batch\n'
    if batch==2:body+='    - depends_on: BATCH-01\n'
    for task in range(1, 13):
        body += f'    - [ ] [TASK-{batch:02}-{task:02}] Úkol '+('dlouhý název ' * 10)+'\n      - type: task\n      - Popis úkolu.\n'
body += '  - [ ] [BATCH-05] Prázdná dávka\n    - type: batch\n'
Artifacts(fixture.node).save(dict(project_id=fixture.pid, artifact_id=fixture.aid,
    base_head=fixture.git.head(), title='Roadmapa', body=body, new=False), str(uuid4()))
try:
    with running_api('http', handler=DesktopHandler, projects=fixture.projects) as server:
        server.chat_service = ChatService(fixture.node, fixture.projects)
        profile = QWebEngineProfile(app); page = QWebEnginePage(profile, app)
        view = QWebEngineView(); view.setPage(page); view.resize(1440, 980); view.show()
        bootstrap = QWebEngineScript(); bootstrap.setInjectionPoint(QWebEngineScript.DocumentCreation)
        bootstrap.setWorldId(QWebEngineScript.MainWorld); bootstrap.setSourceCode('window.workspaceAutoStart=false;')
        page.scripts().insert(bootstrap)
        command = r'''
(async()=>{
 const check=(value,message)=>{if(!value)throw Error(message);};
 const tick=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 const nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:TOKEN};return nativeFetch(url,opts)};
 await openRegisteredProject(PID);
 await openTaskPlan({kind:'batch',id:'BATCH-01',title:'Dávka'});
 const task=()=>taskPlanProjection.nodes.find(node=>node.id==='TASK-01-01');
 showTaskPlanDetail(task());await tick();
 const graph=document.querySelector('#plan-graph');graph.scrollTop=240;graph.scrollLeft=80;
 changePlanZoom(.9);graph.scrollTop=240;
 const before=capturePlanPosition();check(before.scrolls[0].top===240,'fixture must scroll');
 await openPlanItemEditor(task());check(!artifactEditorView.hidden,'editor not open');
 await closeArtifactEditor();await tick();
 check(taskPlanSelection?.id==='BATCH-01'&&!document.querySelector('#plan-panel').hidden,'close lost selected graph');
 check(planZoom===.9&&graph.scrollTop===before.scrolls[0].top&&graph.scrollLeft===before.scrolls[0].left,'close lost scroll');
 check(document.querySelector('#plan-detail h3').textContent.includes('TASK-01-01'),'close lost detail');
 await openPlanItemEditor(task());
 artifactEditorForm.elements.body.value=artifactEditorForm.elements.body.value.replace('Popis úkolu.','Upravený popis úkolu.');
 artifactEditorForm.elements.body.dispatchEvent(new Event('input',{bubbles:true}));
 check(await savePlanItemEditor(),'save failed: '+artifactEditorStatus.textContent);await tick();
 check(taskPlanSelection?.id==='BATCH-01'&&graph.scrollTop===before.scrolls[0].top,'save lost selection or scroll');
 check(document.querySelector('#plan-detail').textContent.includes('Upravený popis'),'saved detail stale');
 // Parent navigation uses the actual openTaskPlan transport, not a stub.
 await openTaskPlan(planParentSelection(task()));
 check(taskPlanSelection?.id==='BATCH-01','task to batch');
 document.querySelector('#plan-up').click();await new Promise(resolve=>setTimeout(resolve,250));
 check(taskPlanSelection?.id==='MILESTONE-01','batch to milestone');
 document.querySelector('#plan-up').click();await new Promise(resolve=>setTimeout(resolve,250));
 check(taskPlanSelection===null&&document.querySelector('#plan-up').hidden,'milestone to root');
 check(!document.querySelector('.plan-mini-task'),'expanded tasks must not remain under cards');
 const counter=document.querySelector('[data-plan-progress="BATCH-01"]');
 check(counter?.textContent==='0/12','wrong completion counter');
 const card=counter.parentElement.querySelector('.plan-batch-card'),rect=card.getBoundingClientRect(),badge=counter.getBoundingClientRect();
 check(badge.left>=rect.left&&badge.right<=rect.right&&badge.top>=rect.top&&badge.bottom<=rect.bottom,'counter outside batch cell');
 counter.click();check(document.querySelectorAll('#plan-detail [data-plan-child]').length===12,'summary lost tasks');
 check(document.querySelectorAll('#plan-detail .plan-child-summary').length===12,'brief task descriptions missing');
 check(!document.querySelector('#plan-detail dl'),'counter opened full batch detail');
 check(taskPlanSelection===null,'counter must not replace graph');
 const summaryPosition=capturePlanPosition();await restorePlanPosition(summaryPosition);
 check(document.querySelectorAll('#plan-detail .plan-child-summary').length===12,'summary return lost mode');
 document.querySelector('#plan-detail [data-plan-child="TASK-01-01"]').click();
 check(document.querySelector('#plan-detail h3').textContent.includes('TASK-01-01'),'summary task detail');
 const batchCard=document.querySelector('[data-plan-progress="BATCH-01"]').parentElement.querySelector('.plan-batch-card');batchCard.click();
 check(document.querySelector('#plan-detail dl'),'batch card must retain full detail');
 const empty=document.querySelector('[data-plan-progress="BATCH-05"]');check(empty?.textContent==='0/0','empty batch counter');empty.click();
 check(document.querySelector('#plan-detail').textContent.includes('Dávka zatím nemá podúkoly.')&&!document.querySelector('#plan-detail [data-plan-child]'),'empty batch summary');
 // Counts use accepted completion, not filter or resolved work state.
 const children=taskPlanProjection.nodes.filter(node=>node.parent_id==='BATCH-01');
 children[0].checked=true;children[0].status='completed';children[1].status='resolved';
 renderTaskPlan();check(document.querySelector('[data-plan-progress="BATCH-01"]').textContent==='1/12','resolved must not count as accepted completion');
 document.querySelector('#plan-status-filter').value='ready';renderTaskPlan();
 const filteredCounter=document.querySelector('[data-plan-progress="BATCH-01"]');
 check(filteredCounter?.textContent==='1/12','filter changed total');filteredCounter.click();
 check(document.querySelectorAll('#plan-detail [data-plan-child]').length===12,'filter hid summary children');
 document.querySelector('#plan-status-filter').value='';renderTaskPlan();
 check(!document.querySelector('.plan-cell-flags'),'symbol indicators should be removed');
 check(!document.querySelector('#settings-roadmap-tab')&&!document.querySelector('#settings-roadmap-panel')&&!document.querySelector('[data-settings-tab="settings-roadmap-tab"]'),'alternative settings roadmap remains');
 const blocked=document.querySelector('.plan-batch-card[data-blocked="true"]');check(blocked&&getComputedStyle(blocked).backgroundColor==='rgb(237, 224, 250)','blocked needs distinct violet fill');
 check(getComputedStyle(blocked).backgroundColor!==planStatusColors.failed,'blocked must not reuse failed fill');
 check(document.querySelector('.plan-batch-card[data-critical="true"]'),'critical fixture missing');
 check(document.querySelector('.plan-batch-card[data-ready="true"]'),'ready fixture missing');
 document.querySelector('#plan-zoom-reset').click();const baseWidth=document.querySelector('.plan-batch-card').getBoundingClientRect().width;
 document.querySelector('#plan-zoom-out').click();check(planZoom===.9&&document.querySelector('#plan-zoom-reset').textContent==='90 %','zoom out control');
 check(Math.abs(document.querySelector('.plan-batch-card').getBoundingClientRect().width-baseWidth*.9)<1,'zoom did not scale cards');
 for(let i=0;i<20;i++)document.querySelector('#plan-zoom-out').click();check(planZoom===.5&&document.querySelector('#plan-zoom-out').disabled,'zoom minimum');
 for(let i=0;i<30;i++)document.querySelector('#plan-zoom-in').click();check(planZoom===2&&document.querySelector('#plan-zoom-in').disabled,'zoom maximum');
 const zoomPosition=capturePlanPosition();changePlanZoom(1);await restorePlanPosition(zoomPosition);check(planZoom===2,'return lost zoom');
 document.querySelector('#plan-zoom-reset').click();check(planZoom===1,'reset zoom');
 for(const card of document.querySelectorAll('.plan-batch-card')){
  check(!card.querySelector('.plan-status-badge'),'duplicate card status');
  check(getComputedStyle(card).overflow==='hidden','unbounded card');
  check(getComputedStyle(card).borderStyle===(card.dataset.ready==='true'?'dashed':'solid'),'readiness border incorrect');
  check(getComputedStyle(card).borderTopWidth===(card.dataset.critical==='true'?'4px':'2px'),'critical border incorrect');
  const c=card.getBoundingClientRect();for(const child of card.children){const r=child.getBoundingClientRect();check(r.right<=c.right&&r.bottom<=c.bottom,'card text box overflows');}
 }
 check(!document.querySelector('#plan-state-filter')&&document.querySelector('#plan-status-filter'),'duplicate state filters');
 await navigateSidebarTab(document.querySelector('#todo-tab'));
 check(!document.querySelector('#preview-panel').hidden&&selectedArtifact===activeProject.mainTodoId,'tasks opened project overview');
 check(document.querySelector('#todo-tab').getAttribute('aria-selected')==='true','tasks sidebar lost');
 window.planNavigationResult='ok';
})().catch(error=>{window.planNavigationResult=error.stack||error.message;});
'''.replace('TOKEN', json.dumps('Bearer '+server.token)).replace('PID', json.dumps(fixture.pid))
        started = False
        def poll():
            global started
            def received(value):
                global started
                if value=='ready' and not started:
                    started=True; page.runJavaScript(command)
                elif value and value!='ready':
                    print(value, flush=True); app.exit(0 if value=='ok' else 2)
            page.runJavaScript("window.planNavigationResult||(typeof capturePlanPosition==='function'?'ready':'')", received)
        timer=QTimer(); timer.timeout.connect(poll); timer.start(100)
        QTimer.singleShot(25000, lambda:(print('navigation timeout',flush=True),app.exit(3)))
        page.setUrl(QUrl(server.origin+'/')); result=app.exec(); view.close(); page.deleteLater(); profile.deleteLater()
        raise SystemExit(result)
finally:
    fixture.doCleanups()
