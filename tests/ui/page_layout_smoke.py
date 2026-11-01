# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Exercise shared page chrome in Qt with isolated domain transport."""
import json
import os

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.desktop_ui import HTML, CSS, JS
from spikes.presentation_documents import new_deck, layout_presets, encode_deck

app = QApplication([])
view = QWebEngineView()
view.resize(int(os.environ.get('WORKSPACE_LAYOUT_WIDTH','1440')), 980)
test = r'''
window.layoutTest={done:false};
(async()=>{
 const check=(value,message)=>{if(!value)throw Error(message);};
 const tick=()=>new Promise(resolve=>setTimeout(resolve,30));
 const visible=node=>node&&!node.hidden&&node.getBoundingClientRect().height>0;
 for(const dialog of document.querySelectorAll('dialog')){
  check(!dialog.classList.contains('workspace-page'),'Dialog was mounted as a page: '+dialog.id);
  check(!dialog.open&&getComputedStyle(dialog).display==='none','Closed dialog is visible: '+dialog.id);
 }
 const exportDialog=document.querySelector('#presentation-print-dialog');
 check(exportDialog.querySelector('form>h2')?.textContent==='Export prezentace do PDF','Export form was rearranged');
 mountWorkspacePage(exportDialog);
 check(!exportDialog.classList.contains('workspace-page'),'Page factory accepted a dialog');
 exportDialog.showModal();check(exportDialog.matches(':modal')&&getComputedStyle(exportDialog).display!=='none','Export dialog cannot open modally');
 exportDialog.close();check(getComputedStyle(exportDialog).display==='none','Export dialog stays visible after closing');
 const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aV1kAAAAASUVORK5CYII=';
 const body='# Shared document\n\nThe original file content stays unchanged.\n';
 const records={doc:{id:'doc',kind:'document',title:'Shared document'},image:{id:'image',kind:'source',title:'Image'},pdf:{id:'pdf',kind:'source',title:'PDF'},deck:{id:'deck',kind:'document',title:'Slides'},json:{id:'json',kind:'document',title:'JSON'}};
 let writes=0;
 projectRequest=async(path,request)=>{
  if(path==='/v1/artifacts/preview'){
   const record=records[request.artifact_id];check(record,'Unknown artifact');
   const format=(record.id==='doc'||record.id==='deck'||record.body!==undefined)?'markdown':record.id==='json'?'json':record.id==='pdf'?'pdf':'image';
   return {format,metadata:{title:record.title,kind:record.kind,file:record.id==='pdf'?'file.pdf':record.id==='deck'?'presentation.md':'content.md'},text:record.id==='deck'?ENCODED_PRESENTATION:(record.body??body),image:png,pages:1};
  }
  if(path==='/v1/presentations/open')return {commit_id:activeProject.head,layout_presets:PRESETS,documents:[{id:'deck',title:'Slides',deck:DECK}]};
  if(path==='/v1/artifacts/editor/open')return {document:{title:'Shared document',body,metadata:{file:'content.md'}}};
  if(path==='/v1/projects/delete/trash'||path==='/v1/projects')return {projects:[]};
  if(path==='/v1/artifacts/editor/save'){writes++;records[request.document.artifact_id]={id:request.document.artifact_id,kind:'document',title:request.document.title,body:request.document.body};return {commit_id:'saved-head'};}
  if(path==='/v1/projects/open')return {commit_id:activeProject.head,artifacts:Object.values(records),main_todo:null,history:null,plan:null};
  throw Error('Unexpected transport '+path);
 };
 artifactRawWidget.configure=async()=>{};artifactRawWidget.validate=async()=>({valid:true});loadChat=async()=>{};loadBackendBinding=async()=>{};
 activeProject={id:'project',head:'head',title:'Demo project',mainTodoId:'todo'};syncSidebarProjectAvailability();document.querySelector('#project-title').textContent='Demo project';renderSidebarArtifacts(Object.values(records));
 const transport=projectRequest,projectBeforeFailure=activeProject;
 projectRequest=async()=>{throw Error('Failed to fetch');};
 await navigateSidebarTab(document.querySelector('#presentations-tab'));
 check(activeProject===projectBeforeFailure,'Output loading failure closed the project');
 check(sidebarPresentationStatus.textContent==='Failed to fetch'&&outputsOverviewStatus.textContent==='Failed to fetch','Output sidebar incorrectly asks to open a project after a transport failure');
 projectRequest=transport;
 check(document.querySelector('#main-tabs').closest('#sidebar-page-tools'),'Technical tabs still occupy page header');
 check(document.querySelector('#prompt-widget').parentElement.tagName==='MAIN','Chat is confined to a single page');
 await navigateSidebarTab(document.querySelector('#artifacts-tab'));
 check(!document.querySelector('#artifact-overview').hidden&&document.querySelectorAll('#artifact-overview-list li').length===5,'Missing section file list');
 await openPreview('doc');await tick();
 const preview=document.querySelector('#preview-panel'),layout=workspacePageLayouts.get(preview);
 check(layout.header.querySelector('#preview-title').textContent==='Shared document','Wrong file title');
 check(layout.row.querySelector('#preview-edit')&&!document.querySelector('#preview-edit').hidden,'Writable document has no Edit action');
 check(layout.row.getBoundingClientRect().top>=layout.titleNode.getBoundingClientRect().bottom,'Actions are above title');check(layout.body.tabIndex===0&&layout.body.getAttribute('aria-labelledby')===layout.titleNode.id,'Scrollable content has no keyboard entry or title');
 check(previewContent.querySelector('h1').hidden&&previewContent.querySelector('h1').dataset.duplicatePageTitle==='true','Duplicate document title remains visible');
 check(previewContent.textContent.includes('original file content'),'Viewer changed source content');
 check(previewStatus.textContent==='','Redundant saved/read-only label remains');
 check(document.querySelector('#project-view>.project-header').hidden,'Technical project banner remains');
 check(!promptForm.hidden&&document.querySelector('#prompt-widget').dataset.chatMode==='full','Viewer chat default ignored');
 document.querySelector('#preview-edit').click();await tick();
 check(!artifactEditorView.hidden,'Edit did not open editor');
 const editorLayout=workspacePageLayouts.get(artifactEditorForm);
 check(editorLayout.row.contains(artifactEditorForm.querySelector('button[type=submit]'))&&editorLayout.row.contains(document.querySelector('#artifact-editor-close')),'Editor actions remain below content');
 check(document.querySelector('.task-plan-mode').hidden,'Unsupported WYSIWYG offered for generic Markdown');
 check(artifactEditorForm.elements.body.value===body,'Edit lost exact original bytes');check(document.activeElement===artifactEditorForm.elements.body,'Editor focus: '+JSON.stringify({active:document.activeElement?.id||document.activeElement?.tagName,rect:artifactEditorForm.elements.body.getBoundingClientRect().toJSON()}));check(editorLayout.body.firstElementChild===artifactEditorStatus,'Save feedback remains below editor content');
 check(promptForm.hidden,'Editor did not default to hidden chat');
 artifactEditorForm.elements.body.value=body+'Draft';artifactEditorForm.elements.body.dispatchEvent(new Event('input',{bubbles:true}));
 document.querySelector('#artifact-editor-close').click();await tick();document.querySelector('[data-leave-choice=cancel]').click();await tick();check(!artifactEditorView.hidden,'Cancelled editor exit lost draft');
 document.querySelector('#artifact-editor-close').click();await tick();document.querySelector('[data-leave-choice=discard]').click();await tick();check(artifactEditorView.hidden&&selectedArtifact==='doc','Editor close did not return to viewer');
 check(writes===0,'Discard wrote data');
 layout.closeButton.click();await tick();check(!document.querySelector('#artifact-overview').hidden,'Viewer close did not return to section list');
 await openPreview('json');await tick();check(document.querySelector('#preview-edit').hidden,'Unsupported JSON editor offered');
 await openPreview('image');await tick();check(previewContent.querySelector('img')&&document.querySelector('#preview-edit').hidden,'Image did not open read-only');
 await openPreview('pdf');await tick();check(!document.querySelector('#pdf-controls').hidden&&layout.row.contains(document.querySelector('#pdf-controls'))&&document.querySelector('#preview-edit').hidden,'PDF controls or read-only mode missing');
 activeProject.readOnly=true;await openPreview('doc');check(document.querySelector('#preview-edit').hidden,'Read-only project exposed editing');activeProject.readOnly=false;
 await openNewArtifactEditor({todo:true});await tick();check(!document.querySelector('.task-plan-mode').hidden&&editorLayout.row.contains(document.querySelector('.task-plan-mode')),'Structured/raw switches not in header');
 await closeArtifactEditor();
 await openPreview('deck');await tick();check(previewContent.querySelector('[data-presentation-slide]')&&!document.querySelector('#preview-edit').hidden&&document.querySelector('#text-preview-controls').hidden,'Stored Markdown presentation did not open in validated slide viewer');
 presentationEditorView={commit_id:activeProject.head,layout_presets:PRESETS,documents:[{id:'deck',title:'Slides',deck:DECK}]};
 await openPresentationEditor('deck');await tick();
 const deckLayout=workspacePageLayouts.get(document.querySelector('#presentation-panel'));
 check(deckLayout.row.contains(presentationEditorSave)&&deckLayout.row.contains(document.querySelector('#presentation-editor-mode-raw'))&&deckLayout.row.contains(document.querySelector('#presentation-editor-mode-special')),'Presentation save/mode actions not in header');
 deckLayout.closeButton.click();await tick();check(selectedArtifact==='deck'&&!preview.hidden&&previewContent.querySelector('[data-presentation-slide]'),'Presentation editor close did not show slide viewer');
 layout.closeButton.click();await tick();check(document.querySelector('#outputs-overview-panel').hidden===false,'Output viewer close did not return to outputs');
 await openPreview('doc');await tick();
 const widget=document.querySelector('#prompt-widget');draft.value='Keep chat draft';
 preview.dataset.chatDefault='hidden';syncPageLayout();check(widget.hidden&&promptForm.hidden,'Hidden chat contract ignored');
 preview.dataset.chatDefault='compact';syncPageLayout();check(widget.dataset.chatMode==='compact'&&widget.dataset.compactPending==='true'&&!promptForm.hidden,'Compact contract not reserved');
 preview.dataset.chatDefault='full';syncPageLayout();check(!widget.hidden&&draft.value==='Keep chat draft','Chat mode switch lost draft');
 check(writes===0,'Read-only operations changed project');check(document.documentElement.scrollWidth<=innerWidth,'Layout overflows viewport');if(innerWidth<=640){check(layout.header.getBoundingClientRect().top>=document.querySelector('#mobile-sidebar-toggle').getBoundingClientRect().bottom,'Mobile navigation overlaps page title');check(document.querySelector('main').getBoundingClientRect().bottom<=innerHeight+1&&widget.getBoundingClientRect().bottom<=innerHeight+1&&getComputedStyle(document.documentElement).overflowY==='hidden','Page frame exceeds viewport');}


 selectMainTab(document.querySelector('#tools-main-tab'));juliaModelDetail.hidden=false;juliaEditor.hidden=true;syncPageLayout();juliaDeleteDialog.showModal();check(getComputedStyle(juliaDeleteDialog).display!=='none','Model viewer hides modal dialogs');juliaDeleteDialog.close();
 juliaModelDetail.hidden=true;juliaEditor.hidden=false;syncPageLayout();juliaDeleteDialog.showModal();check(getComputedStyle(juliaDeleteDialog).display!=='none','Model editor hides modal dialogs');juliaDeleteDialog.close();juliaEditor.hidden=true;
 await openNewArtifactEditor();const createdId=artifactEditorItem.id;artifactEditorForm.elements.title.value='Created file';artifactEditorForm.elements.body.value='# Created file\n\nSaved draft';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));
 const closing=closeArtifactEditor();await tick();document.querySelector('[data-leave-choice=save]').click();await closing;await tick();
 check(selectedArtifact===createdId&&artifactEditorView.hidden&&!document.querySelector('#preview-edit').hidden&&writes===1,'Saving a new file on editor close did not show editable viewer');
 layout.closeButton.click();await tick();check(document.querySelector('#artifact-overview-list').textContent.includes('Created file'),'Section list did not refresh after save');
 const read=projectRequest;workspaceArtifactProjectionHead='unknown';projectRequest=async(path,request)=>path==='/v1/projects/open'?{commit_id:'different-head',artifacts:[]} : await read(path,request);
 await showArtifactOverview();check(!document.querySelector('#artifact-overview-list').children.length&&document.querySelector('#artifact-overview-status').textContent.includes('Projekt se změnil'),'Stale snapshot shown as current list');
 projectRequest=read;await showArtifactOverview();check(document.querySelector('#artifact-overview-list').textContent.includes('Created file')&&!document.querySelector('#artifact-overview-status').textContent,'List did not recover after successful refresh');
 await closeProject();await tick();const homeLayout=workspacePageLayouts.get(document.querySelector('#project-home'));check(visible(homeLayout.header),'Section home has no common header');check(document.querySelector('#dashboard-tasks').getBoundingClientRect().height<=homeLayout.body.getBoundingClientRect().height+1,'Dashboard tile exceeds available page content');
 layoutTest={done:true,ok:true};
})().catch(error=>{layoutTest={done:true,ok:false,error:error.message};});
'''.replace('DECK', json.dumps(new_deck())).replace('PRESETS', json.dumps(layout_presets())).replace('ENCODED_PRESENTATION',json.dumps(encode_deck(new_deck())))

def loaded(ok):
    if not ok:
        app.exit(2)
        return
    view.page().runJavaScript(test)
    QTimer.singleShot(100, poll)

def checked(raw):
    if not raw:
        QTimer.singleShot(100, poll)
        return
    result = json.loads(raw)
    if not result.get('done'):
        QTimer.singleShot(100, poll)
        return
    print(json.dumps(result), flush=True)
    app.exit(0 if result.get('ok') else 1)

def poll():
    view.page().runJavaScript('JSON.stringify(window.layoutTest)', 0, checked)

prefix = "document.body.dataset.runtime='desktop';window.workspaceAutoStart=false;window.fetch=async()=>{throw Error('test-offline')};window.requestAnimationFrame=()=>0;"
html = HTML.replace('<link rel="stylesheet" href="/app.css">', '<style>' + CSS + '</style>').replace(
    '<script src="/app.js"></script>', '<script>' + prefix + JS.replace('</script', '<\\/script') + '</script>')
view.loadFinished.connect(loaded)
view.setHtml(html, QUrl('http://127.0.0.1/'))
view.show()
QTimer.singleShot(30000, lambda: app.exit(3))
raise SystemExit(app.exec())
