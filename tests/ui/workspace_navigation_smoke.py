# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Isolated Qt shell regression; transport is stubbed, no backend is contacted."""
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage
from spikes.desktop_ui import HTML,CSS,JS
from spikes.presentation_documents import layout_presets
app=QApplication([])
class Page(QWebEnginePage):
 def javaScriptConsoleMessage(self,level,message,line,source):
  if 'test-offline' not in message: print('JS',line,message[:400],flush=True)
page=Page()
test=r'''
window.navigationTest={done:false};
(async()=>{
 const check=(value,message)=>{if(!value)throw Error(message);};
 const tick=()=>new Promise(resolve=>setTimeout(resolve,10));
 loadChat=async()=>{};loadBackendBinding=async()=>{};
 projectRequest=async(path)=>{if(path==='/v1/projects')return {projects:[]};if(path==='/v1/projects/trash')return {projects:[]};throw Error('Unexpected '+path);};
 artifactRawWidget.configure=async()=>{};artifactRawWidget.validate=async()=>({valid:true});
 const seed=()=>{activeProject={id:'project',head:'head',mainTodoId:'todo',title:'Project'};syncSidebarProjectAvailability();};seed();
 const pages=[projectCreateView,projectTrashView,projectRepairView,sourceImportView,notebookImportView,historyView,settingsView,document.querySelector('#federation-view'),federationNetworkView,federationDeploymentView];
 for(const page of pages){showWorkspacePage(page);await navigateSidebarTab(document.querySelector('#chats-tab'));check(!projectView.hidden&&page.hidden,'Cannot leave '+page.id);check(!editorLeaveDialog.open,'Prompt on ordinary '+page.id);}
 await openNewArtifactEditor();check(!artifactEditorDirty,'New untouched document dirty');await navigateSidebarTab(document.querySelector('#chats-tab'));check(!editorLeaveDialog.open&&!projectView.hidden,'Clean document failed');
 await openNewArtifactEditor();artifactEditorForm.elements.title.value='Title';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));
 let nav=navigateSidebarTab(document.querySelector('#chats-tab'));await tick();check(editorLeaveDialog.open,'Missing dirty dialog');document.querySelector('[data-leave-choice="cancel"]').click();check(!await nav&&!artifactEditorView.hidden,'Cancel lost document');
 artifactEditorForm.elements.title.value='';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));check(!artifactEditorDirty,'Reverted document dirty');await navigateSidebarTab(document.querySelector('#chats-tab'));check(!editorLeaveDialog.open,'Reverted document prompted');
 await openNewArtifactEditor();artifactEditorForm.elements.title.value='Title';artifactEditorForm.elements.body.value='Text';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));
 let writes=0,fail=true,operations=[];projectRequest=async(path,body)=>{if(path==='/v1/artifacts/editor/save'){operations.push(body.operation_id);writes++;if(fail)throw Error('save failed');return {commit_id:'new-head'};}throw Error('Unexpected '+path);};
 nav=navigateSidebarTab(document.querySelector('#chats-tab'));await tick();document.querySelector('[data-leave-choice="save"]').click();check(!await nav&&!artifactEditorView.hidden&&artifactEditorDirty,'Save failure left editor');check(artifactEditorForm.elements.body.value==='Text','Save failure lost body');
 const operation=artifactEditorAttempt.operation_id;fail=false;
 nav=navigateSidebarTab(document.querySelector('#chats-tab'));await tick();document.querySelector('[data-leave-choice="save"]').click();check(await nav&&!projectView.hidden&&writes===2,'Save did not navigate');check(activeProject.head==='new-head','Save did not update HEAD');check(operations.length===2&&operations.every(id=>id===operation),'Retry changed operation ID');
 await openNewArtifactEditor();artifactEditorForm.elements.title.value='Discard';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));nav=navigateSidebarTab(document.querySelector('#chats-tab'));await tick();document.querySelector('[data-leave-choice="discard"]').click();check(await nav&&!artifactEditorDirty&&writes===2,'Discard wrote document');
 // Pending editor exit ignores a second navigation rather than racing dialogs.
 await openNewArtifactEditor();artifactEditorForm.elements.title.value='Race';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));nav=navigateSidebarTab(document.querySelector('#chats-tab'));await tick();check(!await navigateSidebarTab(document.querySelector('#tools-tab')),'Second navigation raced');document.querySelector('[data-leave-choice="cancel"]').click();await nav;
 artifactEditorDirty=false;artifactEditorView.hidden=true;
 // Julia and presentation drafts use the same save/discard guard.
 juliaEditor.hidden=false;juliaEditorDirty=true;juliaEditorModel={};nav=navigateMainTab(document.querySelector('#preview-tab'));await tick();check(editorLeaveDialog.open,'Julia not guarded');document.querySelector('[data-leave-choice="discard"]').click();check(await nav&&!juliaEditorDirty,'Julia discard failed');
 presentationEditorDirty=true;nav=navigateMainTab(document.querySelector('#chat-tab'));await tick();check(editorLeaveDialog.open,'Presentation not guarded');document.querySelector('[data-leave-choice="discard"]').click();check(await nav&&!presentationEditorDirty,'Presentation discard failed');
 projectConflictDrafts.set('a',{choice:'manual',text:'changed'});nav=navigateMainTab(document.querySelector('#preview-tab'));await tick();check(editorLeaveDialog.open,'Conflict not guarded');document.querySelector('[data-leave-choice="discard"]').click();check(await nav&&!conflictDraftChanged(),'Conflict discard failed');

 // Real save callbacks for Julia and presentation, including invalid Julia JSON.
 juliaSourceRawWidget.configure=async options=>{juliaEditor.elements.julia_code.value=options.content;};
 showWorkspacePage(projectView);selectMainTab(document.querySelector('#tools-main-tab'));
 await fillJuliaEditor({title:'Julia',privacy:'project',parameters:[],outputs:[],project_toml:'[deps]',manifest_toml:'manifest_format = "2.0"',execution_policy:{},julia_code:'println(1)',base_head:activeProject.head,new:true,artifact_ids:{}});
 check(!juliaEditorDirty,'Untouched Julia prompted');juliaEditor.elements.title.value='Julia changed';juliaEditor.dispatchEvent(new Event('input',{bubbles:true}));
 projectRequest=async(path)=>{check(path==='/v1/julia/editor/save','Unexpected Julia request');return {commit_id:'julia-head'};};
 juliaEditor.elements.parameters.value='invalid';nav=navigateMainTab(document.querySelector('#preview-tab'));await tick();document.querySelector('[data-leave-choice="save"]').click();check(!await nav&&!juliaEditor.hidden&&juliaEditorDirty,'Invalid Julia JSON left editor');
 juliaEditor.elements.parameters.value='[]';nav=navigateMainTab(document.querySelector('#preview-tab'));await tick();document.querySelector('[data-leave-choice="save"]').click();check(await nav&&activeProject.head==='julia-head'&&!juliaEditorDirty,'Julia save failed');
 showWorkspacePage(projectView);selectMainTab(presentationTab);presentationEditorView={commit_id:activeProject.head,documents:[],layout_presets:LAYOUT_PRESETS};await createPresentationDocument(false);check(!presentationEditorDirty,'Untouched presentation prompted');
 const originalTitle=presentationEditorDeck.title;presentationEditorDeck.title='Changed';presentationEditorChanged(false);check(presentationEditorDirty,'Presentation change not dirty');presentationEditorDeck.title=originalTitle;presentationEditorChanged(false);check(!presentationEditorDirty,'Reverted presentation prompted');presentationEditorDeck.title='Saved title';presentationEditorChanged(false);
 projectRequest=async(path)=>{check(path==='/v1/presentations/save','Unexpected presentation request');return {commit_id:'presentation-head'};};
 nav=navigateMainTab(document.querySelector('#preview-tab'));await tick();document.querySelector('[data-leave-choice="save"]').click();check(await nav&&activeProject.head==='presentation-head'&&!presentationEditorDirty,'Presentation save failed');check(presentationEditorView.documents[0].deck.title==='Saved title','Saved presentation cache stale');
 // Sidebar click and keyboard handlers perform navigation as well.
 document.querySelector('#chats-tab').click();await tick();check(document.querySelector('#chat-tab').getAttribute('aria-selected')==='true','Sidebar click did not route');
 document.querySelector('#chats-tab').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));await tick();check(document.querySelector('#todo-tab').getAttribute('aria-selected')==='true','Sidebar keyboard did not route');

 // Leaving a running native tool neither cancels it nor starts it again on return.
 federationNetworkRunning=true;federationDeploymentRunning=true;
 const networkConfig={token:'keep-network'},deploymentConfig={token:'keep-deployment'};federationNetworkConfiguration=networkConfig;federationDeploymentConfiguration=deploymentConfig;
 showWorkspacePage(federationNetworkView);await navigateSidebarTab(document.querySelector('#chats-tab'));check(federationNetworkView.hidden&&federationNetworkRunning,'Running network blocked navigation');await openFederationNetwork();check(!federationNetworkView.hidden&&federationNetworkConfiguration===networkConfig,'Network return reset running state');
 await navigateSidebarTab(document.querySelector('#chats-tab'));await openFederationDeployment();check(!federationDeploymentView.hidden&&federationDeploymentConfiguration===deploymentConfig,'Deployment return reset running state');federationNetworkRunning=false;federationDeploymentRunning=false;
 projectRequest=async(path)=>{if(path==='/v1/presentation/status')return {saved:false};throw Error('test-offline');};
 await openPresenter();check(!presenterView.hidden&&getComputedStyle(document.querySelector('body>aside')).display!=='none','Presenter hides navigation');await navigateSidebarTab(document.querySelector('#chats-tab'));check(presenterView.hidden&&!document.body.classList.contains('presenter-active'),'Presenter did not allow navigation');

 // Section defaults never close the current project, including Projects itself.
 seed();const retained=activeProject;
 projectRequest=async(path)=>{if(path==='/v1/projects'||path==='/v1/projects/delete/trash')return {projects:[]};throw Error('test-offline');};
 const defaults={'projects-tab':'project-overview-tab','chats-tab':'chat-tab','todo-tab':'project-overview-tab','plan-tab':'plan-main-tab','artifacts-tab':'preview-tab','tools-tab':'tools-main-tab','presentations-tab':'outputs-overview-tab'};
 for(const [section,destination] of Object.entries(defaults)){showWorkspacePage(historyView);await navigateSidebarTab(document.getElementById(section));check(activeProject===retained,'Section closed project: '+section);check(!projectView.hidden&&document.getElementById(destination).getAttribute('aria-selected')==='true','Wrong section default: '+section);}
 check(document.querySelector('#sidebar-close-project').disabled===false,'Close project not enabled');
 const actions=[...document.querySelectorAll('.sidebar-project-primary-actions>button')].map(button=>button.id);check(actions.join(',')==='sidebar-create-project,sidebar-import-project,sidebar-close-project,sidebar-project-trash','Wrong project action order');
 await loadProjects();check(activeProject===retained&&!projectView.hidden,'Catalog refresh closed project');
 await openProjectTrashView();check(activeProject===retained,'Trash closed project');await navigateSidebarTab(document.querySelector('#projects-tab'));check(!projectView.hidden,'Trash return lost project landing');
 await openNotebookLMImport();check(activeProject===retained,'Notebook import closed project');
 await openProjectRepair({id:'other',title:'Other project'});check(activeProject===retained,'Repair closed current project');
 document.querySelector('#sidebar-create-project').click();await tick();check(activeProject===retained&&!projectCreateView.hidden,'Create project closed current project');
 await openNewArtifactEditor();artifactEditorForm.elements.title.value='Keep draft';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));
 let closing=closeProject();await tick();document.querySelector('[data-leave-choice=cancel]').click();check(!await closing&&activeProject===retained&&!artifactEditorView.hidden,'Cancelled close lost project or draft');
 document.querySelector('#sidebar-close-project').click();await tick();document.querySelector('[data-leave-choice=discard]').click();await tick();check(activeProject===null&&!document.querySelector('#project-home').hidden&&document.querySelector('#sidebar-close-project').disabled,'Explicit close failed');
 await navigateSidebarTab(document.querySelector('#projects-tab'));check(!document.querySelector('#project-home').hidden,'Projects without open project did not show home');
 seed();await openNewArtifactEditor();artifactEditorForm.elements.title.value='Save on close';artifactEditorForm.elements.body.value='Saved before close';artifactEditorForm.dispatchEvent(new Event('input',{bubbles:true}));
 let closeWrites=0;projectRequest=async(path)=>{if(path==='/v1/artifacts/editor/save'){closeWrites++;return {commit_id:'close-head'};}if(path==='/v1/projects'||path==='/v1/projects/delete/trash')return {projects:[]};throw Error('test-offline');};
 closing=closeProject();await tick();document.querySelector('[data-leave-choice=save]').click();check(await closing&&activeProject===null&&closeWrites===1,'Save and close failed');
 // Explicitly opening another project replaces the former one and lands on its overview.
 seed();loadJuliaWorkspace=async()=>{};loadRoadmapReview=async()=>{};loadProjectConflictSummary=async()=>{};
 projectRequest=async(path,body)=>{check(path==='/v1/projects/open'&&body.project_id==='other','Unexpected replacement request');return {title:'Other',description:'',commit_id:'other-head',main_todo_id:'other-todo',main_todo:null,history:null,plan:null,artifacts:[]};};
 await openRegisteredProject('other');check(activeProject?.id==='other'&&!projectView.hidden&&document.querySelector('#projects-tab').getAttribute('aria-selected')==='true'&&document.querySelector('#project-overview-tab').getAttribute('aria-selected')==='true','Opening another project did not replace context');

 // Completion of a confirmed removal must not close another project opened meanwhile.
 let finishRemoval;projectRequest=async(path)=>{if(path==='/v1/projects/delete/confirm')return await new Promise(resolve=>{finishRemoval=resolve;});if(path==='/v1/projects'||path==='/v1/projects/delete/trash')return {projects:[]};throw Error('test-offline');};
 projectDeletePlan={project_id:'other'};projectDeleteKind='delete';projectDeleteCheck.checked=true;projectDeleteConfirm.disabled=false;projectDeleteConfirm.click();await tick();seed();const replacement=activeProject;finishRemoval({});await tick();check(activeProject===replacement,'Old removal closed replacement project');
 projectRequest=async(path)=>{if(path==='/v1/projects/delete/confirm')return {};if(path==='/v1/projects'||path==='/v1/projects/delete/trash')return {projects:[]};throw Error('test-offline');};projectDeletePlan={project_id:activeProject.id};projectDeleteCheck.checked=true;projectDeleteConfirm.disabled=false;projectDeleteConfirm.click();await tick();check(activeProject===null,'Removing current project did not close it');
 navigationTest={done:true,ok:true,pages:pages.length};
})().catch(error=>{navigationTest={done:true,ok:false,error:error.stack.split("\n").map(line=>line.slice(0,180)).join("\n")};});
'''
test=test.replace("LAYOUT_PRESETS",json.dumps(layout_presets()))
def loaded(ok):
 if not ok:app.exit(2);return
 page.runJavaScript(test)
 QTimer.singleShot(100,poll)
def result(raw):
 if not raw:QTimer.singleShot(100,poll);return
 d=json.loads(raw)
 if not d.get('done'):QTimer.singleShot(100,poll);return
 print(json.dumps(d),flush=True);app.exit(0 if d.get('ok') else 1)
def poll():page.runJavaScript('JSON.stringify(window.navigationTest)',0,result)
page.loadFinished.connect(loaded)
# Avoid any runtime backend effects; navigation tests replace only read/write transport.
prefix="window.fetch=async()=>{throw Error('test-offline')};window.requestAnimationFrame=()=>0;"
html=HTML.replace('<link rel="stylesheet" href="/app.css">','<style>'+CSS+'</style>').replace('<script src="/app.js"></script>','<script>'+prefix+JS.replace('</script','<\\/script')+'</script>')
page.setHtml(html,QUrl("http://127.0.0.1/"))
QTimer.singleShot(30000,lambda:app.exit(3))
raise SystemExit(app.exec())
