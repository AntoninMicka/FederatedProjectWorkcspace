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
    for task in range(1, 13):
        body += f'    - [ ] [TASK-{batch:02}-{task:02}] Úkol '+('dlouhý název ' * 10)+'\n      - type: task\n      - Popis úkolu.\n'
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
 const before=capturePlanPosition();check(before.scrolls[0].top===240,'fixture must scroll');
 await openPlanItemEditor(task());check(!artifactEditorView.hidden,'editor not open');
 await closeArtifactEditor();await tick();
 check(taskPlanSelection?.id==='BATCH-01'&&!document.querySelector('#plan-panel').hidden,'close lost selected graph');
 check(graph.scrollTop===before.scrolls[0].top&&graph.scrollLeft===before.scrolls[0].left,'close lost scroll');
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
 check(document.querySelectorAll('.plan-mini-task').length===48,'overview missing child level');
 const mini=document.querySelector('.plan-mini-task');mini.click();
 check(document.querySelector('#plan-detail h3').textContent.includes('TASK-01-01'),'mini task detail');
 check(taskPlanSelection===null,'mini click must not replace graph');
 for(const card of document.querySelectorAll('.plan-batch-card')){
  check(!card.querySelector('.plan-status-badge'),'duplicate card status');
  check(getComputedStyle(card).overflow==='hidden','unbounded card');
  check(getComputedStyle(card).borderStyle==='solid','competing readiness border');
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
