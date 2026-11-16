# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Real WebEngine and native API: restore, keep, and a lost confirmation reply."""
import json
import tempfile
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage

from spikes.artifacts import Artifacts
from spikes.desktop_ui import HTML, CSS, JS, DesktopHandler
from spikes.local_api import running_api
from spikes.http_ui_admission import HTTP_UI_ADMISSION_JS
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects

temporary = tempfile.TemporaryDirectory()
root = Path(temporary.name); node = root / 'node.json'
identities = []
for number in range(2):
    pid = ProjectCreation(node).create('Resolution ' + str(number), root / str(number), str(uuid4()))['id']
    ws = Projects(node).workspace(pid); aid = str(uuid4())
    head = Artifacts(node).save(dict(project_id=pid, artifact_id=aid, base_head=ws.git.head(),
        title='Roadmap', body='Saved\n', new=True), str(uuid4()))['commit_id']
    path = f'artifacts/{aid}/content.md'; (ws.git.root / path).write_text('Reviewed working edit\n')
    identities.append(dict(id=pid, head=head, path=path))

app = QApplication([]); page = QWebEnginePage()
# Simulate simultaneous ownership by a long application operation and inbound
# sync. Real project HTTP/UI operations must still complete independently.
with running_api('http', handler=DesktopHandler, projects=Projects(node)) as server, server.application_lane, server.content_sync_lane:
    config = dict(origin=server.origin, token=server.token, projects=identities)
    script = r'''
window.localResolutionSmoke={done:false};
(async()=>{
 const config=CONFIG,check=(value,message)=>{if(!value)throw Error(message);};
 let lost=false,confirmations=[];
 projectRequest=async(path,body)=>{
  const response=await window.fetch(config.origin+path,{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+config.token},body:JSON.stringify(body)});
  const value=await response.json();if(!response.ok){const error=Error(value.error||String(response.status));error.status=response.status;throw error;}
  if(path.endsWith('/local-confirm')){
   confirmations.push(body.operation_id);
   if(body.preview.choice==='keep'&&!lost){lost=true;throw Error('Synthetic lost reply');}
  }
  return value;
 };
 // The actual local preview must do no write, and confirmation is gated.
 const first=config.projects[0];await openRegisteredProject(first.id);await openProjectConflicts();
 let item=projectLocalChanges.find(row=>row.path===first.path);check(item?.can_resolve,'Missing restore action');
 await reviewLocalProjectChange(item,'restore');check(localConflictDialog.open,'Restore preview did not open');
 check(document.querySelector('#local-conflict-confirm').disabled,'Restore not gated');
 check(!await confirmLocalProjectChange(),'Unconfirmed restore ran');
 check(confirmations.length===0,'Preview caused a write');
 const approve=()=>{const box=document.querySelector('#local-conflict-approved');box.checked=true;box.dispatchEvent(new Event('change'));};
 approve();check(await confirmLocalProjectChange(),'Restore failed');
 check(activeProject.head===first.head,'Restore created a Git commit');
 check(projectConflictOpen.hidden,'Restored working file still marked dirty');
 // Keep uses the exact native commit; a missing response reuses the same ID.
 const second=config.projects[1];await openRegisteredProject(second.id);await openProjectConflicts();
 item=projectLocalChanges.find(row=>row.path===second.path);await reviewLocalProjectChange(item,'keep');approve();
 check(!await confirmLocalProjectChange(),'Lost reply reported success');
 check(projectLocalAttempt&&localConflictDialog.open,'Lost reply lost original decision');
 const operation=projectLocalAttempt.operation_id;
 check(await confirmLocalProjectChange(),'Exact retry failed');
 check(confirmations.length===3&&confirmations[1]===operation&&confirmations[2]===operation,'Retry changed operation ID');
 check(activeProject.head!==second.head,'Keep did not publish a commit');
 const view=await projectRequest('/v1/projects/open',{project_id:second.id});
 check(view.history.entries.length===3,'Lost reply duplicated the commit');
 check(!view.conflict_summary.local_changes,'Committed working file still dirty');
 window.localResolutionSmoke={done:true,ok:true};
})().catch(error=>{window.localResolutionSmoke={done:true,ok:false,error:error.stack};});
'''.replace('CONFIG', json.dumps(config))

    def poll():
        page.runJavaScript('JSON.stringify(window.localResolutionSmoke)', 0, result)

    def result(raw):
        value = json.loads(raw) if raw else {}
        if not value.get('done'):
            QTimer.singleShot(100, poll)
            return
        print(json.dumps(value), flush=True); app.exit(0 if value.get('ok') else 1)

    def loaded(ok):
        if not ok:
            app.exit(2); return
        page.runJavaScript('window.fetch=window.nativeFetch;' + HTTP_UI_ADMISSION_JS + script)
        QTimer.singleShot(100, poll)

    page.loadFinished.connect(loaded)
    prefix = "window.workspaceAutoStart=false;window.nativeFetch=window.fetch;window.fetch=async()=>{throw Error('test-offline')};window.requestAnimationFrame=()=>0;"
    html = HTML.replace('<link rel="stylesheet" href="/app.css">', '<style>' + CSS + '</style>').replace(
        '<script src="/app.js"></script>', '<script>' + prefix + JS.replace('</script', '<\\/script') + '</script>')
    page.setHtml(html, QUrl(server.origin + '/'))
    QTimer.singleShot(45000, lambda: app.exit(3))
    code = app.exec()
temporary.cleanup()
raise SystemExit(code)
