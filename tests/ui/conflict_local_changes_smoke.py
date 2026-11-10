# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Isolated WebEngine regression for local/peer conflict visibility; no live node."""
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage

from spikes.artifacts import Artifacts
from spikes.conflict_resolution import ConflictResolution
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
(workspace.git.root / path).write_text('- [SUM] HARDENING\n<img src=x onerror=alert(1)>\n')
view = ConflictResolution(node).list(project, head)

app = QApplication([])
page = QWebEnginePage()
test = r'''
window.conflictSmoke={done:false};
(async()=>{
 const check=(value,message)=>{if(!value)throw Error(message);};
 const view=VIEW;let calls=[];
 activeProject={id:'PROJECT',head:'HEAD'};
 projectRequest=async(path)=>{calls.push(path);if(path==='/v1/projects/conflicts/list')return view;throw Error('Unexpected write '+path);};
 await loadProjectConflictSummary();
 check(!projectConflictOpen.hidden,'Local-only conflict action is hidden');
 await openProjectConflicts();
 const section=document.querySelector('#project-conflicts-local-changes');
 check(!projectConflicts.hidden&&!section.hidden,'Local conflict section hidden');
 const details=section.querySelector('details');check(details,'Missing file comparison');details.open=true;
 check(details.textContent.includes('+- [SUM] HARDENING'),'Missing exact local diff');
 check(!details.querySelector('img'),'Local content interpreted as HTML');
 check(projectConflictWorkspace.hidden,'Local edit fabricated an incoming history');
 check(!await saveConflictEditor(),'Local edit allowed merge publication');
 check(calls.every(path=>path.endsWith('/list')),'Read-only inspection wrote data');
 // A concurrent history preview must not enable publication over local edits.
 projectConflictPreview={files:[]};projectConflictConfirm.checked=true;updateConflictCompletion();
 check(projectConflictConfirm.disabled&&projectConflictPublish.disabled,'Local edits did not block merge controls');
 projectConflictPreview=null;resetProjectConflicts();
 view.local_changes=[];view.sync_conflicts=[{peer_id:'omnia-peer'}];
 await loadProjectConflictSummary();check(!projectConflictOpen.hidden,'Peer-only conflict action hidden');
 await openProjectConflicts();check(!document.querySelector('#project-conflicts-sync').hidden,'Peer conflict hidden');
 check(document.querySelector('#project-conflicts-sync-peers').textContent.includes('omnia-peer'),'Peer identity missing');
 resetProjectConflicts();view.sync_conflicts=[];await loadProjectConflictSummary();
 check(projectConflictOpen.hidden,'Clean project still marked conflicted');
 projectRequest=async()=>{throw Error('Unavailable');};await loadProjectConflictSummary();
 check(!projectConflictOpen.hidden&&projectConflictOpen.textContent.includes('není dostupný'),'Failed read claimed no conflicts');
 window.conflictSmoke={done:true,ok:true};
})().catch(error=>{window.conflictSmoke={done:true,ok:false,error:error.stack};});
'''.replace('VIEW', json.dumps(view)).replace('PROJECT', project).replace('HEAD', head)


def result(raw):
    value = json.loads(raw) if raw else {}
    if not value.get('done'):
        QTimer.singleShot(100, poll)
        return
    print(json.dumps(value), flush=True)
    app.exit(0 if value.get('ok') else 1)


def poll():
    page.runJavaScript('JSON.stringify(window.conflictSmoke)', 0, result)


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
