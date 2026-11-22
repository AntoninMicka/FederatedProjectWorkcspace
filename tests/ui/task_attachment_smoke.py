# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Attach an existing output with explicit confirmation and inspect the task text."""
import json
import sys
from uuid import uuid4
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.artifacts import Artifacts
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.chat_service import ChatService
from tests import test_task_queue as fixtures

app=QApplication([]);fixture=fixtures.TaskQueueTests();fixture.setUp()
try:
 doc=str(uuid4())
 Artifacts(fixture.node).save(dict(project_id=fixture.pid,artifact_id=doc,base_head=fixture.head,title='Inventory',body='# Original\n',new=True),str(uuid4()))
 if '--cross-project' in sys.argv or '--offer-flow' in sys.argv:
  from spikes.project_creation import ProjectCreation
  from spikes.cross_references import CrossReferences
  from spikes.reporting_schema import digest,encoded
  source=ProjectCreation(fixture.node).create('Foreign project',fixture.root/'foreign',str(uuid4()))['id']
  refs=CrossReferences(fixture.node);source_git=refs.artifacts.workspace(source).git;sibling=str(uuid4());foreign=str(uuid4())
  for aid,title,body in [(sibling,'Sibling','Sibling in source project\n'),(foreign,'Foreign output','# Original foreign\n[Sibling](artifacts/'+sibling+'/content.md)\n[Web](https://example.com/)\n')]:
   refs.artifacts.save(dict(project_id=source,artifact_id=aid,base_head=source_git.head(),title=title,body=body,new=True),str(uuid4()))
  share=str(uuid4());proposal=refs.share_preview(source,share,foreign,[fixture.pid],'Task output')
  refs.share_write(proposal,str(uuid4()),digest(encoded(proposal)),confirm=True)
  doc=str(uuid4());proposal=refs.preview(fixture.pid,doc,refs.source_pin(source,foreign),'Inventory',share_id=share,reason_text='Task evidence')
  if '--offer-flow' not in sys.argv:refs.write(proposal,str(uuid4()),digest(encoded(proposal)),confirm=True)
 with running_api('http',handler=DesktopHandler,projects=Projects(fixture.node)) as server:
  server.chat_service=ChatService(fixture.node,server.projects)
  profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1400,900);view.show()
  phase=0;busy=False
  commands={
   1:'window.originalFetch=fetch;window.fetch=(url,opts={})=>originalFetch(url,{...opts,headers:{...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'}});openRegisteredProject('+json.dumps(fixture.pid)+').then(()=>window.opened=true)',
   2:"openTaskPlan().then(()=>{showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='TASK-A'));document.querySelector('[data-task-work-start=\"TASK-A\"]').click()})",
   3:"[...document.querySelectorAll('#task-record-editor button')].find(b=>b.textContent==='Připojit existující soubor / artefakt').click()",
   4:'document.querySelector("#task-attachment-artifact").value='+json.dumps(doc)+';document.querySelector("#task-attachment-artifact").dispatchEvent(new Event("change"));document.querySelector("#task-attachment-comment").value="Existing inventory attached";document.querySelector("#task-attachment-comment").dispatchEvent(new Event("input"));window.attachmentChosen=true;',
   5:"[...document.querySelectorAll('#task-attachment-form button')].find(b=>b.textContent==='Potvrdit a připojit').click()",
   6:"[...document.querySelectorAll('#task-record-list button')].find(b=>b.textContent==='Původní verze').click()",
   7:"openPlanItemEditor(taskPlanProjection.nodes.find(n=>n.id==='TASK-A')).then(()=>window.taskOpened=true)",
  }
  checks={
   0:"typeof loadTaskAttachment==='function'&&document.body.dataset.runtime==='desktop'",
   1:'window.opened&&activeProject',
   2:"!taskWorkBusy&&taskWorkView?.active_session_id",
   3:"document.querySelector('#task-attachment-artifact')?.options.length>0",
   4:"window.attachmentChosen&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records.length===0",
   5:"!taskWorkBusy&&document.querySelector('#task-record-list').textContent.includes('Existing inventory attached')&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records.length===1&&!taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).current_task.checked",
   6:"document.querySelector('#task-record-preview').textContent.includes('Original')",
   7:"window.taskOpened&&!artifactEditorView.hidden&&artifactEditorForm.elements.body.value.includes('Existing inventory attached')&&artifactEditorForm.elements.body.value.includes('Inventory')&&!artifactEditorForm.elements.body.value.includes('# Original')",
  }
  if '--cross-project' in sys.argv:
   commands[7]="document.querySelector('#task-record-preview .artifact-link').click()"
   checks[6]+="&&document.querySelector('#task-record-preview a')?.href==='https://example.com/'"
   checks[7]="activeProject?.id==="+json.dumps(source)+"&&selectedArtifact==="+json.dumps(sibling)+"&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).project_id==="+json.dumps(fixture.pid)
  if '--offer-flow' in sys.argv:
   saved_checks=dict(checks)
   commands[3]="[...document.querySelectorAll('#task-record-editor button')].find(b=>b.textContent==='Připojit odkaz z jiného projektu').click()"
   checks[3]="!!document.querySelector('#sharing-body input[name=sharing-offer]')"
   commands[4]="document.querySelector('#sharing-body input[name=sharing-offer]').click();document.querySelector('#sharing-title').value='Inventory';document.querySelector('#sharing-reason').value='Task evidence';document.querySelector('#sharing-primary').click()"
   checks[4]="!document.querySelector('#sharing-confirm').hidden"
   commands[5]="document.querySelector('#sharing-approved').click();document.querySelector('#sharing-confirm').click()"
   checks[5]="!document.querySelector('#sharing-dialog').open&&!!document.querySelector('#task-attachment-artifact')&&taskAttachmentDrafts.get(selectedTaskWorkSession().work_session_id)?.items.some(item=>item.source_project_id==="+json.dumps(source)+")"
   commands[6]="document.querySelector('#task-attachment-artifact').value=taskAttachmentDrafts.get(selectedTaskWorkSession().work_session_id).items.find(item=>item.source_project_id==="+json.dumps(source)+").id;document.querySelector('#task-attachment-artifact').dispatchEvent(new Event('change'));document.querySelector('#task-attachment-comment').value='Existing inventory attached';document.querySelector('#task-attachment-comment').dispatchEvent(new Event('input'));window.attachmentChosen=true;"
   checks[6]="window.attachmentChosen&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).task_records.length===0"
   commands[7]="[...document.querySelectorAll('#task-attachment-form button')].find(b=>b.textContent==='Potvrdit a připojit').click()";checks[7]=saved_checks[5]
   commands[8]="[...document.querySelectorAll('#task-record-list button')].find(b=>b.textContent==='Původní verze').click()";checks[8]=saved_checks[6]
   commands[9]="document.querySelector('#task-record-preview .artifact-link').click()"
   checks[9]="activeProject?.id==="+json.dumps(source)+"&&selectedArtifact==="+json.dumps(sibling)+"&&taskWorkView.sessions.find(s=>s.work_session_id===taskWorkView.active_session_id).project_id==="+json.dumps(fixture.pid)
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==(10 if '--offer-flow' in sys.argv else 8):print('existing task attachment browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if not busy:busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150)
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("JSON.stringify({status:document.querySelector('#task-work-status').textContent,editor:document.querySelector('#artifact-editor-status')?.textContent,view:taskWorkView})",lambda v:(print(v,flush=True),app.exit(2)))
  QTimer.singleShot(45000,timeout);page.setUrl(QUrl(server.origin+'/'));result=app.exec();view.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
