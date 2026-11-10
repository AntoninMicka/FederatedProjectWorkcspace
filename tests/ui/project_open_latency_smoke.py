# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Project landing must not wait for hidden feature requests; isolated WebEngine."""
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage

from spikes.artifacts import Artifacts
from spikes.desktop_ui import HTML, CSS, JS
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects

temporary = tempfile.TemporaryDirectory()
root = Path(temporary.name)
node = root / 'node.json'
project = ProjectCreation(node).create('Conflict smoke', root / 'project', str(uuid4()))['id']
workspace = Projects(node).workspace(project)
artifact = str(uuid4())
head = Artifacts(node).save(dict(project_id=project, artifact_id=artifact,
    base_head=workspace.git.head(), title='Roadmap', body='- [ ] HARDENING\n', new=True),
    str(uuid4()))['commit_id']
path = next(p for p in workspace.git.snapshot(head) if p.endswith('.md'))
view = Projects(node).open(project)

app = QApplication([])
page = QWebEnginePage()
test = r"""
window.projectOpenSmoke={done:false};
(async()=>{
 const check=(value,message)=>{if(!value)throw Error(message);};
 const view=VIEW,loads=[];let requests=[];
 loadMonitoring=async()=>{loads.push('monitoring');};
 loadJuliaWorkspace=async()=>{loads.push('julia');};
 loadRoadmapReview=async()=>{loads.push('roadmap');};
 loadChat=async()=>{loads.push('chat');};
 const catalog=Array.from({length:12},(_,i)=>({id:crypto.randomUUID(),title:'Startup '+i,available:true}));
 let dashboardActive=0,dashboardPeak=0;
 projectRequest=async(path,body)=>{
  requests.push(path);
  if(path==='/v1/projects')return {projects:catalog};
  check(path==='/v1/projects/open'&&body.scope==='dashboard','Startup loaded hidden/full feature '+path);
  dashboardActive++;dashboardPeak=Math.max(dashboardPeak,dashboardActive);
  await new Promise(resolve=>setTimeout(resolve,5));dashboardActive--;
  return {main_todo:null};
 };
 await loadProjects();
 check(dashboardPeak===1&&requests.length===13,'Startup background reads were unbounded');
 check(loads.length===0,'Startup loaded hidden chat/tools');
 requests=[];
 projectRequest=async(path,body)=>{requests.push(path);check(path==='/v1/projects/open','Hidden feature requested '+path);return view;};
 await openRegisteredProject('PROJECT');
 check(activeProject?.id==='PROJECT'&&!projectView.hidden,'Project did not open');
 check(document.getElementById('project-overview-tab').getAttribute('aria-selected')==='true','Project landing not shown');
 check(loads.length===0,'Project opening loaded hidden features');
 check(requests.length===1,'Opening required extra HTTP requests: '+JSON.stringify(requests));
 const retained=activeProject;let fail;
 projectRequest=async()=>await new Promise((resolve,reject)=>{fail=reject;});
 const switching=openRegisteredProject('unavailable');await new Promise(resolve=>setTimeout(resolve,10));
 check(activeProject===retained,'Switch cleared current project before successful response');
 fail(Error('Server busy'));await switching;
 check(activeProject===retained,'Failed switch lost current project');
 check(!projectStatus.classList.contains('visually-hidden')&&projectStatus.textContent.includes('Server busy'),'Switch failure hidden');
 projectRequest=async(path)=>{requests.push(path);check(path==='/v1/projects/open','Unexpected '+path);return view;};
 await navigateSidebarTab(document.getElementById('tools-tab'));
 check(loads.join(',')==='julia,roadmap,monitoring','Tools were not loaded on demand');
 loads.length=0;await navigateSidebarTab(document.getElementById('chats-tab'));
 check(loads.join(',')==='chat','Chat not loaded on demand');
 loads.length=0;await navigateMainTab(document.getElementById('monitoring-tab'));
 check(loads.join(',')==='monitoring','Monitoring not loaded on demand');
 check(Number.isFinite(window.workspaceLastProjectOpen.total_ms),'Missing end-to-end UI timing');
 window.projectOpenSmoke={done:true,ok:true};
})().catch(error=>{window.projectOpenSmoke={done:true,ok:false,error:error.stack};});
""".replace("VIEW", json.dumps(view)).replace("PROJECT", project)


def result(raw):
    value = json.loads(raw) if raw else {}
    if not value.get('done'):
        QTimer.singleShot(100, poll)
        return
    print(json.dumps(value), flush=True)
    app.exit(0 if value.get('ok') else 1)


def poll():
    page.runJavaScript('JSON.stringify(window.projectOpenSmoke)', 0, result)


def loaded(ok):
    if not ok:
        app.exit(2)
        return
    page.runJavaScript(test)
    QTimer.singleShot(100, poll)


page.loadFinished.connect(loaded)
prefix = "window.fetch=async()=>{throw Error('test-offline')};window.requestAnimationFrame=()=>0;"
html = HTML.replace('<link rel="stylesheet" href="/app.css">', '<style>' + CSS + '</style>').replace(
    '<script src="/app.js"></script>', '<script>' + prefix + JS.replace('</script', '<\\/script') + '</script>')
page.setHtml(html, QUrl('http://127.0.0.1/'))
QTimer.singleShot(30000, lambda: app.exit(3))
code = app.exec()
temporary.cleanup()
raise SystemExit(code)
