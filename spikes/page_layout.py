# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Shared page chrome; domain viewers, editor buffers and save operations stay in place."""

PAGE_LAYOUT_CSS = r'''
html{height:100%;overflow:hidden}
main{display:flex;flex-direction:column;min-height:0;overflow:hidden}
main>div{flex:1;min-height:0;height:auto!important}
main>div.workspace-page{overflow:hidden!important}
#project-home.workspace-page>.workspace-page-header{display:flex}
main>#prompt-widget #chat-composer{max-height:48vh;padding-top:18px}
main>#prompt-widget{flex:none;max-height:48vh;min-height:0;margin-top:15px;border:1px solid #dce3e9;border-radius:14px}
#prompt-display-controls{position:absolute;right:16px;top:-15px;display:flex;gap:3px;padding:2px 4px;background:#fafffd;border:1px solid #bfcdc9;border-radius:16px;z-index:30}
#prompt-display-controls button{min-height:24px;padding:3px 10px;font-size:11px;line-height:18px;border-radius:12px;background:transparent;color:#526675}
#prompt-display-controls button[aria-pressed=true]{background:#176b60;color:white}
#prompt-display-controls button:focus-visible{outline:2px solid #176b60;outline-offset:2px}
#prompt-widget[data-chat-mode=hidden]{min-height:18px}
.prompt-surface{display:contents}
.prompt-entry{border:1px solid #bfcdc9;border-radius:10px;background:white}
.prompt-entry:focus-within{border-color:#176b60;box-shadow:0 0 0 2px #79c9ac3d}
.prompt-caption{display:flex;align-items:baseline;flex-wrap:wrap;gap:3px 10px;padding:5px 12px 0}
#chat-composer .prompt-caption label{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#526675}
#chat-composer .prompt-caption #chat-orchestration-target{margin:0;font-size:10px;overflow-wrap:anywhere}
.prompt-entry .prompt-draft-control{border:0;box-shadow:none}
.prompt-entry #chat-draft{padding-top:5px;min-height:48px}
#prompt-widget[data-chat-mode=compact] .prompt-surface{display:block;position:relative;border:1px solid #bfcdc9;border-radius:10px;background:white}
#prompt-widget[data-chat-mode=compact] .prompt-surface:focus-within{border-color:#176b60;box-shadow:0 0 0 2px #79c9ac3d}
#prompt-widget[data-chat-mode=compact] .prompt-entry{border:0;box-shadow:none;background:transparent}
#prompt-widget[data-chat-mode=compact] .prompt-draft-control{border:0;box-shadow:none;background:transparent}
#prompt-widget[data-chat-mode=compact] #chat-draft{min-height:48px;padding-right:42px}
#prompt-widget[data-chat-mode=compact] .prompt-toolbar{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin:0;padding:4px 48px 7px 8px}
#prompt-widget[data-chat-mode=compact] .prompt-control{display:flex;align-items:center;gap:3px;height:25px;border:0;border-radius:5px;background:#f3f7f8;max-width:100%}
#prompt-widget[data-chat-mode=compact] .prompt-control>span{position:static;padding-left:6px;font-size:8px;white-space:nowrap}
#prompt-widget[data-chat-mode=compact] .prompt-control>span::after{content:':' }
#prompt-widget[data-chat-mode=compact] .prompt-control select{height:25px;min-height:0;width:auto;max-width:145px;padding:1px 16px 1px 0;font-size:9px}
#prompt-widget[data-chat-mode=compact] .prompt-routing-controls,#prompt-widget[data-chat-mode=compact] .prompt-execution-controls{display:contents}
#prompt-widget[data-chat-mode=compact] .prompt-toolbar:has(#task-routing:not([hidden]))>.prompt-privacy-control{margin-left:auto}
#prompt-widget[data-chat-mode=compact] .prompt-route-arrow{font-size:12px}
#prompt-widget[data-chat-mode=compact] .prompt-input-picker>summary{flex-direction:row;align-items:center;gap:3px;min-width:0;height:25px;padding:1px 16px 1px 6px;border:0;background:#f3f7f8}
#prompt-widget[data-chat-mode=compact] .prompt-input-picker>summary span{font-size:8px}
#prompt-widget[data-chat-mode=compact] .prompt-input-picker>summary span::after{content:':' }
#prompt-widget[data-chat-mode=compact] .prompt-input-picker>summary output{font-size:9px}
#prompt-widget[data-chat-mode=compact] .prompt-input-picker>summary::after{right:5px;bottom:5px}
#prompt-widget[data-chat-mode=compact] .prompt-input-menu{bottom:35px}
#prompt-widget[data-chat-mode=compact] #chat-submit{position:absolute;right:8px;bottom:7px;min-height:26px;height:26px;width:26px;font-size:14px}
@media(max-width:640px){#prompt-display-controls{right:8px}#prompt-widget[data-chat-mode=compact] .prompt-input-menu{bottom:14px}}
#project-view{gap:0}.project-header{display:none}
#main-panel-content{padding:0;overflow:hidden}
#main-panel-content.project-overview-active{overflow:hidden}
.workspace-page{box-sizing:border-box;display:flex!important;flex-direction:column;min-height:0;height:100%;width:100%;max-width:none;margin:0;padding:0;overflow:hidden;background:white;border-radius:14px}
.workspace-page[hidden]{display:none!important}
#main-panel-content>.workspace-page{padding:0;max-width:none;margin:0;height:100%}
#artifact-editor-view>header,#artifact-editor-view>.page-heading,.project-overview-heading{display:none!important}
#project-overview-panel:has(#project-conflicts:not([hidden]))>.workspace-page-header{display:none}
.workspace-page-header{display:flex;flex:none;flex-direction:column;align-items:stretch;gap:12px;padding:20px 22px 16px;border-bottom:1px solid #dce3e9;background:white}
.workspace-page-header .workspace-page-title{font-size:26px!important;line-height:1.25;margin:0;color:#162638;overflow-wrap:anywhere}
.workspace-page-actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.workspace-page-actions:empty{display:none}
.workspace-page-actions button{margin:0;min-height:36px}
.workspace-page-actions label{margin:0!important}
.workspace-page-actions>#pdf-controls,.workspace-page-actions>#text-preview-controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.workspace-page-actions .form-actions,.workspace-page-actions .editor-mode-switch,.workspace-page-actions .task-plan-mode{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:0}
.workspace-page-body{flex:1;min-height:0;min-width:0;overflow:auto;padding:20px 22px;overscroll-behavior:contain}
#project-overview-panel>.workspace-page-body{display:flex;flex-direction:column}
#artifact-editor-view{display:flex;flex-direction:column;overflow:hidden}
#artifact-editor-view[hidden]{display:none}
#artifact-editor-form{flex:1;min-height:0;max-width:none;border:1px solid #dce3e9}
#artifact-editor-form .raw-editor-widget{width:100%;max-width:none}
#tools-panel:has(#julia-editor:not([hidden]))>.workspace-page-body,#tools-panel:has(#julia-model-detail:not([hidden]))>.workspace-page-body{display:flex;flex-direction:column;padding:0;overflow:hidden}
#tools-panel:has(#julia-editor:not([hidden]))>.workspace-page-body>:not(#julia-editor):not(dialog),#tools-panel:has(#julia-model-detail:not([hidden]))>.workspace-page-body>:not(#julia-model-detail):not(dialog){display:none}
#julia-editor.workspace-page,#julia-model-detail.workspace-page,#project-conflicts.workspace-page{height:100%;min-height:0;flex:1}
#project-overview-panel:has(#project-conflicts:not([hidden]))>.workspace-page-body{padding:0;overflow:hidden}
.workspace-page-status{position:sticky;top:0;z-index:3;margin:0 0 12px;padding:8px 0;background:white;font-size:13px;overflow-wrap:anywhere}
.workspace-page-status:empty{display:none}
.workspace-page-description{margin:0 0 14px;color:#627183;font-size:14px;line-height:1.5}
.workspace-file-properties{margin-bottom:16px;padding:10px 12px;border:1px solid #dce3e9;border-radius:8px}
.workspace-file-properties>summary{font-weight:600}
.workspace-file-list{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.workspace-file-list button{display:block;width:100%;padding:14px;text-align:left;color:#162638;background:#f3f7f8;border:1px solid #dce3e9}
.workspace-file-list small{display:block;margin-top:5px;color:#627183}
#sidebar-page-tools{margin-top:14px;min-height:0;overflow:auto}
#sidebar-page-tools>summary{font-size:12px;color:#c8d4df;padding:8px 0}
#sidebar-page-tools #main-tabs{display:grid;grid-template-columns:minmax(0,1fr);gap:5px;padding:8px 0;border:0;overflow:visible}
#sidebar-page-tools #main-tabs button{min-width:0;white-space:normal;text-align:left;padding:9px;font-size:12px}
#sidebar-plan #open-task-queue{flex:none;width:100%;margin-top:14px;padding:9px 7px;text-align:left;color:#dce8f1;background:transparent}
#sidebar-plan #open-task-queue:hover,#sidebar-plan #open-task-queue[aria-current=true]{background:#274154}
#plan-subgraphs #sidebar-plan-list{flex:none;max-height:none;overflow:visible}
#plan-subgraphs #sidebar-plan-list button{color:#213746;background:#f3f7f8}
#task-queue-panel .task-queue-list{max-height:none;overflow:visible;margin:0;padding-left:22px}
#task-queue-panel .task-queue-list li{flex-wrap:wrap}
#task-queue-panel .task-queue-list li button:first-child{flex:1;min-width:0}
#plan-panel>.workspace-page-header{padding:12px 16px 10px;gap:6px}
#plan-panel>.workspace-page-header .workspace-page-title{font-size:22px!important}
#plan-panel .roadmap-controls{padding:0;gap:8px}
#plan-panel #plan-status{margin:0 0 0 auto;font-size:12px}
#plan-panel>.workspace-page-body{display:flex;flex-direction:column;gap:6px;padding:8px 12px 12px;overflow:hidden}
#plan-panel #plan-subgraphs{flex:none;max-height:25%;overflow:auto}
#plan-panel .plan-layout{flex:1;min-height:0;min-width:0;grid-template-columns:minmax(0,1fr) minmax(240px,24%);grid-template-rows:minmax(0,1fr);gap:8px;overflow:hidden}
#plan-panel .plan-layout:has(#plan-detail[hidden]){grid-template-columns:minmax(0,1fr)}
#plan-panel #plan-graph{height:100%;min-height:0;max-height:none;min-width:0;box-sizing:border-box;overflow:auto}
#plan-panel #plan-detail{min-height:0;min-width:0;margin:0;padding:10px 12px;overflow:auto;overscroll-behavior:contain;color:#213746}
#plan-panel #plan-detail dl{grid-template-columns:minmax(90px,.7fr) minmax(0,1.6fr)}
@media(max-width:900px){
 #plan-panel .plan-layout{grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,3fr) minmax(0,2fr)}
 #plan-panel .plan-layout:has(#plan-detail[hidden]){grid-template-rows:minmax(0,1fr)}
}
#preview-status:empty,#artifact-overview-status:empty{display:none}
.workspace-page .layout-label{display:none}
.workspace-page-body .workspace-page{min-height:320px;height:auto}
.workspace-page-body:has(>#julia-editor:not([hidden]))>.workspace-page-header{display:none}
#tools-panel:has(#julia-editor:not([hidden]))>.workspace-page-header{display:none}
#tools-panel:has(#julia-model-detail:not([hidden]))>.workspace-page-header{display:none}
#tools-panel:has(#julia-editor:not([hidden])) #tools-overview-list,#tools-panel:has(#julia-model-detail:not([hidden])) #tools-overview-list{display:none}
@media(max-width:640px){
 body{display:flex;height:100vh;height:100dvh;min-height:0;overflow:hidden}
 main{width:100%;height:100%;min-height:0;padding:68px 10px 12px;overflow:hidden}
 #project-view{min-height:0}
 #workspace-panel{overflow:hidden}
 #main-panel-content,#main-panel-content.project-overview-active{padding:0;overflow:hidden}
 #project-home>.workspace-page-body{display:flex;flex-direction:column}
 #project-home #dashboard-grid{flex:1;min-height:0}
 #project-home #dashboard-tasks{height:100%;max-height:100%}
 .workspace-page-header{padding:16px 14px 12px;gap:10px}
 .workspace-page-header .workspace-page-title{font-size:23px!important}
 .workspace-page-body{padding:14px}
 .workspace-page-actions button{min-height:44px}
 main>#prompt-widget{max-height:46vh}
 main>#prompt-widget #chat-composer{max-height:46vh}
 #project-overview-panel>.workspace-page-body{display:block}
}
'''

PAGE_LAYOUT_JS = r'''
const workspacePageLayouts=new Map();
let workspaceArtifactProjectionHead=null;
const WORKSPACE_CHAT_MODES=new Set(['full','compact','hidden']);
let workspaceChatModeOverride=null;
function setPageChatMode(mode,{user=false}={}){
 if(!WORKSPACE_CHAT_MODES.has(mode))throw new Error('Neznámý režim chatové části.');
 if(user)workspaceChatModeOverride=mode;
 mode=workspaceChatModeOverride||mode;
 const widget=document.querySelector('#prompt-widget');
 if(widget.dataset.chatMode!==mode)widget.dataset.chatMode=mode;
 if(widget.hidden)widget.hidden=false;
 for(const button of widget.querySelectorAll('[data-chat-mode-choice]'))button.setAttribute('aria-pressed',String(button.dataset.chatModeChoice===mode));
 const hidden=mode==='hidden';
 if(hidden&&promptForm.contains(document.activeElement))widget.querySelector('[data-chat-mode-choice=hidden]')?.focus();
 if(promptForm.hidden!==hidden)promptForm.hidden=hidden;
}
function mountWorkspacePage(root,{title='',heading=null,actions=[],section='projects-tab',kind='page',chat='hidden',close=true,onClose=null,closeLabel='Zavřít'}={}){
 if(!root||root.matches('dialog')||workspacePageLayouts.has(root))return;
 const header=document.createElement('header'),row=document.createElement('div'),body=document.createElement('div');
 header.className='workspace-page-header';row.className='workspace-page-actions';row.setAttribute('aria-label','Akce stránky');body.className='workspace-page-body';
 let titleNode=heading||document.createElement('h1');
 titleNode.classList.add('workspace-page-title');if(!titleNode.id)titleNode.id=(root.id||'workspace-page-'+workspacePageLayouts.size)+'-page-title';if(!titleNode.textContent.trim())titleNode.textContent=title;
 body.tabIndex=0;body.setAttribute('role','region');body.setAttribute('aria-labelledby',titleNode.id);
 header.append(titleNode,row);
 for(const action of actions)if(action)row.append(action);
 let closeButton=null;
 if(close){closeButton=document.createElement('button');closeButton.type='button';closeButton.className='secondary-button';closeButton.dataset.pageClose='';closeButton.textContent=closeLabel;closeButton.addEventListener('click',onClose||(()=>navigateSidebarTab(document.getElementById(section))));row.prepend(closeButton);}
 for(const child of [...root.childNodes])body.append(child);
 root.classList.add('workspace-page');root.dataset.pageKind=kind;if(!root.dataset.chatDefault)root.dataset.chatDefault=chat;
 root.append(header,body);
 workspacePageLayouts.set(root,{header,row,body,titleNode,title,section,kind,closeButton});
 return workspacePageLayouts.get(root);
}
function renderArtifactOverview(current=false){
 const list=document.querySelector('#artifact-overview-list');if(!list)return;
 if(current){workspaceArtifactProjectionHead=activeProject?.head||null;document.querySelector('#artifact-overview-status').textContent='';}
 list.replaceChildren();
 for(const item of currentArtifacts){const row=document.createElement('li'),button=document.createElement('button'),title=document.createElement('strong');button.type='button';title.textContent=item.title;button.append(title);button.addEventListener('click',()=>openPreview(item.id));row.append(button);list.append(row);}
 document.querySelector('#artifact-overview-empty').hidden=Boolean(currentArtifacts.length);
}
function renderToolsOverview(){
 const list=document.querySelector('#tools-overview-list');if(!list)return;list.replaceChildren();
 for(const model of juliaCatalog){const row=document.createElement('li'),button=document.createElement('button');button.type='button';button.textContent=model.computation.title;button.addEventListener('click',()=>showJuliaModelDetail(model));row.append(button);list.append(row);}
 if(roadmapReviewRows.length||roadmapReviewError){const row=document.createElement('li'),button=document.createElement('button');button.type='button';button.textContent='Kontrola roadmapy';button.addEventListener('click',openRoadmapReview);row.append(button);list.append(row);}
}
async function openMainTodoPreview(){if(activeProject)await openPreview(activeProject.mainTodoId);}
async function showArtifactOverview(){
 if(!activeProject||!await canLeaveWorkspaceEditors())return false;
 clearPreview();renderArtifactOverview();document.querySelector('#artifact-overview').hidden=false;
 document.querySelector('#preview-title').textContent='Podklady';previewStatus.textContent='';
 showWorkspacePage(projectView);selectSidebarTab(document.querySelector('#artifacts-tab'));selectMainTab(document.querySelector('#preview-tab'));syncPageLayout();
 if(workspaceArtifactProjectionHead!==activeProject.head)await refreshArtifactOverview();
 return true;
}
async function refreshArtifactOverview(){
 const project=activeProject,head=project.head,status=document.querySelector('#artifact-overview-status');
 document.querySelector('#artifact-overview-list').replaceChildren();document.querySelector('#artifact-overview-empty').hidden=true;status.textContent='Načítám aktuální seznam…';
 try{const value=await projectRequest('/v1/projects/open',{project_id:project.id});if(activeProject!==project||project.head!==head)return;
  if(!Array.isArray(value.artifacts))throw new Error('Server neposkytl platný seznam podkladů.');
  if(value.commit_id!==head)throw new Error('Projekt se změnil. Pro aktuální obsah jej znovu otevřete.');
  renderSidebarArtifacts(value.artifacts);renderTodo(value.main_todo);renderProjectOverview(value.main_todo);renderProjectHistory(value.history);renderTaskPlanSidebar(value.plan);
 }catch(error){if(activeProject===project&&project.head===head)status.textContent=error.message;}
}
async function prepareStoredPresentationPreview(id,text){
 const project=activeProject,head=project.head;
 const front=typeof text==='string'&&text.startsWith('---\n')?text.slice(4,text.indexOf('\n---\n',4)>=0?text.indexOf('\n---\n',4):Math.min(text.length,1048576)):'';
 const candidate=typeof text==='string'&&(text.startsWith('```fpw-presentation-v1\n')||/^format:\s*["']?fpw-presentation["']?\s*$/m.test(front));
 document.querySelector('#preview-panel').dataset.presentationCandidate=String(candidate);
 if(!candidate)return null;
 if(presentationEditorView?.commit_id===head){const row=presentationEditorView.documents.find(item=>item.id===id);return row?.error||null;}
 try{const view=await projectRequest('/v1/presentations/open',{project_id:project.id,expected_head:head});
  if(activeProject!==project||project.head!==head)return null;
  if(view.commit_id!==head)return 'Projekt se změnil. Pro aktuální náhled jej znovu otevřete.';
  presentationEditorView=view;renderSidebarPresentations();return view.documents.find(item=>item.id===id)?.error||null;
 }catch(error){return 'Náhled prezentace není dostupný: '+error.message;}
}
function renderStoredPresentationPreview(id){
 if(!activeProject||!presentationEditorView||presentationEditorView.commit_id!==activeProject.head)return false;
 const deck=presentationEditorView.documents.find(item=>item.id===id)?.deck;if(!deck)return false;
 for(const slide of deck.slides){const frame=document.createElement('section');frame.dataset.presentationSlide=slide.id;frame.style.aspectRatio='16 / 9';frame.style.marginBottom='16px';frame.style.maxWidth='1000px';renderSlideVisual(frame,{...slide,layout:deck.templates.find(item=>item.id===slide.layout)});previewContent.append(frame);}
 return true;
}
function suppressDuplicatePreviewTitle(){
 const first=[...previewContent.children].find(item=>item.textContent.trim());
 if(first?.tagName==='H1'&&!first.hidden&&first.textContent.trim()===document.querySelector('#preview-title').textContent.trim()){first.hidden=true;first.dataset.duplicatePageTitle='true';}
}
function syncPageLayout(){
 if(!window.workspacePageLayoutReady)return;
 let root=[...document.querySelectorAll('main>div')].find(item=>!item.hidden);
 if(root===projectView){root=mainTabs.map(tab=>document.getElementById(tab.getAttribute('aria-controls'))).find(item=>!item.hidden);if(root?.id==='project-overview-panel'&&!projectConflicts.hidden)root=projectConflicts;if(root?.id==='tools-panel'){if(!juliaEditor.hidden)root=juliaEditor;else if(!juliaModelDetail.hidden)root=juliaModelDetail;}}
 else if(root===artifactEditorView)root=artifactEditorForm;
 const modeSwitch=document.querySelector('.task-plan-mode');if(modeSwitch&&modeSwitch.hidden!==taskPlanEditor.hidden)modeSwitch.hidden=taskPlanEditor.hidden;
 const layout=workspacePageLayouts.get(root);
 document.querySelector('#open-task-queue').setAttribute('aria-current',String(root?.id==='task-queue-panel'));
 if(root?.id==='task-queue-panel'||root?.id==='plan-panel')updateTaskPlanTreeSelection(root.id==='task-queue-panel');
 if(!layout){setPageChatMode('hidden');return;}
 if(!layout.titleNode.textContent.trim())layout.titleNode.textContent=layout.title;
 let chat=root.dataset.chatDefault||'hidden';
 if(root.id==='preview-panel'){
  const overview=!document.querySelector('#artifact-overview').hidden;
  const item=selectedPreviewMetadata?.id===selectedArtifact?selectedPreviewMetadata:currentArtifacts.find(item=>item.id===selectedArtifact);
  const deck=presentationEditorView&&activeProject&&presentationEditorView.commit_id===activeProject.head?presentationEditorView.documents.find(item=>item.id===selectedArtifact&&item.deck):null;
  const writable=Boolean(!activeProject?.readOnly&&(deck?document.body.dataset.runtime!=='server':item?.kind==='document'&&root.dataset.fileFormat==='markdown'&&root.dataset.presentationCandidate!=='true'));
  const edit=document.querySelector('#preview-edit');const hideEdit=overview||!writable;if(edit.hidden!==hideEdit)edit.hidden=hideEdit;
  edit.onclick=()=>deck?openPresentationEditor(deck.id):openArtifactEditor(item);
  if(layout.closeButton&&layout.closeButton.hidden!==overview)layout.closeButton.hidden=overview;
  root.dataset.pageKind=overview?'list':'viewer';
  for(const button of document.querySelectorAll('[data-artifact-overview-action]')){const hidden=!overview||Boolean(activeProject?.readOnly);if(button.hidden!==hidden)button.hidden=hidden;}
  suppressDuplicatePreviewTitle();
 }
 const modelEdit=document.querySelector('#julia-model-detail-edit');if(modelEdit){const model=juliaCatalog.find(item=>item.definition.path===juliaModelDetail.dataset.definitionPath);const hidden=Boolean(activeProject?.readOnly)||!model?.editable;if(modelEdit.hidden!==hidden)modelEdit.hidden=hidden;}
 if(root===juliaEditor){const title=juliaEditor.elements.title.value||'Nový Julia model';if(layout.titleNode.textContent!==title)layout.titleNode.textContent=title;}
 if(root?.id==='presentation-panel'){const title=presentationEditorDeck?.title||'Prezentace';if(layout.titleNode.textContent!==title)layout.titleNode.textContent=title;}
 if(root===settingsView){const selected=settingsTabs.find(tab=>tab.getAttribute('aria-selected')==='true');if(selected&&layout.titleNode.textContent!==selected.textContent)layout.titleNode.textContent=selected.textContent;}
 setPageChatMode(chat);
}
async function closePresentationEditorPage(){
 const id=presentationEditorArtifact;
 if(!await canLeavePresentationEditor())return false;
 if(id&&!presentationEditorNew)await openPreview(id);else await navigateSidebarTab(document.querySelector('#presentations-tab'));
 return true;
}
async function closeJuliaEditorPage(){
 const model=juliaEditorModel;
 if(!await canLeaveJuliaEditor())return false;
 juliaEditor.hidden=true;juliaEditorModel=null;juliaEditorDirty=false;juliaEditorAttempt=null;
 if(model&&!model.new&&model.definition_path)await loadJuliaWorkspace();
 const saved=model&&!model.new?juliaCatalog.find(item=>item.definition.path===model.definition_path):null;
 if(saved)await showJuliaModelDetail(saved);else await navigateSidebarTab(document.querySelector('#tools-tab'));
 syncPageLayout();return true;
}
function initializeWorkspacePageLayout(){
 const get=selector=>document.querySelector(selector);
 const take=(root,selectors)=>selectors.flatMap(selector=>[...root.querySelectorAll(selector)]);
 // Keep the existing controller/tab IDs, but put tools navigation in the sidebar.
 get('#main-tabs').setAttribute('aria-orientation','vertical');
 const tools=document.createElement('details'),summary=document.createElement('summary');tools.id='sidebar-page-tools';summary.textContent='Další nástroje';tools.append(summary,get('#main-tabs'));get('#sidebar-tools').append(tools);
 const primaryTabs=new Set(['project-overview-tab','preview-tab','chat-tab','tools-main-tab','outputs-overview-tab','plan-main-tab','task-queue-tab','presentation-tab']);
 for(const tab of mainTabs)if(primaryTabs.has(tab.id))tab.hidden=true;
 get('#settings-tabs').hidden=true;
 const prompt=get('#prompt-widget');document.querySelector('main').append(prompt);
 const displayControls=document.createElement('div');displayControls.id='prompt-display-controls';displayControls.setAttribute('role','group');displayControls.setAttribute('aria-label','Zobrazení promptu');
 for(const [mode,label] of [['full','Plný'],['compact','Kompaktní'],['hidden','Skrýt']]){const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.chatModeChoice=mode;button.setAttribute('aria-controls','chat-composer');button.addEventListener('click',()=>setPageChatMode(mode,{user:true}));displayControls.append(button);}
 prompt.prepend(displayControls);
 const surface=document.createElement('div');surface.className='prompt-surface';promptForm.prepend(surface);surface.append(get('.prompt-draft-control'),get('.prompt-toolbar'));
 const entry=document.createElement('div'),caption=document.createElement('div'),draftLabel=document.createElement('label'),draftControl=get('.prompt-draft-control'),draftTitle=draftControl.querySelector('span');
 entry.className='prompt-entry';caption.className='prompt-caption';draftTitle.id='prompt-draft-title';draftLabel.htmlFor='chat-draft';draftLabel.append(draftTitle);get('#chat-draft').setAttribute('aria-labelledby',draftTitle.id);
 caption.append(draftLabel,get('#chat-orchestration-target'));surface.prepend(entry);entry.append(caption,draftControl);
 const preview=get('#preview-panel');
 const overview=document.createElement('section'),list=document.createElement('ul'),empty=document.createElement('p');const listStatus=document.createElement('p');listStatus.id='artifact-overview-status';listStatus.setAttribute('role','status');overview.id='artifact-overview';list.id='artifact-overview-list';list.className='workspace-file-list';empty.id='artifact-overview-empty';empty.textContent='Projekt zatím nemá žádné podklady.';overview.append(listStatus,list,empty);preview.append(overview);
 const edit=document.createElement('button');edit.id='preview-edit';edit.type='button';edit.textContent='Editovat';edit.hidden=true;
 const create=document.createElement('button'),importButton=document.createElement('button');
 for(const [button,label,run] of [[create,'Nový dokument',()=>openNewArtifactEditor()],[importButton,'Importovat',openSourceImport]]){button.type='button';button.dataset.artifactOverviewAction='';button.textContent=label;button.addEventListener('click',run);}
 const previewLayout=mountWorkspacePage(preview,{onClose:()=>navigateSidebarTab(sidebarTabs.find(tab=>tab.getAttribute('aria-selected')==='true')||get('#artifacts-tab')),title:'Podklady',heading:get('#preview-title'),section:'artifacts-tab',kind:'viewer',chat:'full',actions:[edit,create,importButton,get('#text-preview-controls'),get('#pdf-controls')]});
 const artifactSave=artifactEditorForm.querySelector('button[type="submit"]');
 mountWorkspacePage(artifactEditorForm,{title:'Dokument',heading:get('#artifact-editor-heading'),section:'artifacts-tab',kind:'editor',close:false,actions:[artifactSave,get('#artifact-editor-close'),get('.task-plan-mode')]});
 const properties=document.createElement('details'),propertiesTitle=document.createElement('summary');properties.className='workspace-file-properties';propertiesTitle.textContent='Vlastnosti dokumentu';properties.append(propertiesTitle);
 for(const name of ['title','filename','description','tags'])properties.append(artifactEditorForm.elements[name].closest('label'));
 workspacePageLayouts.get(artifactEditorForm).body.prepend(properties);
 const artifactHeading=get('#artifact-editor-heading');artifactEditorForm.addEventListener('input',()=>{artifactHeading.textContent=artifactEditorForm.elements.title.value||'Nový dokument';});
 const juliaSave=juliaEditor.querySelector('button[type="submit"]');
 mountWorkspacePage(juliaEditor,{title:'Julia model',heading:juliaEditor.querySelector('h3'),section:'tools-tab',kind:'editor',close:false,actions:[juliaSave,get('#julia-editor-close')]});
 mountWorkspacePage(juliaModelDetail,{title:'Julia model',heading:get('#julia-model-detail-title'),section:'tools-tab',kind:'viewer',close:false,actions:[get('#julia-model-detail-close')]});
 mountWorkspacePage(projectConflicts,{title:'Řešení konfliktů',heading:get('#project-conflicts-title'),kind:'editor',close:false,actions:[get('#project-conflicts-back')]});get('#project-conflicts-back').textContent='Zavřít editor';
 get('#julia-model-detail-close').textContent='Zavřít';
 const modelEdit=document.createElement('button');modelEdit.type='button';modelEdit.textContent='Editovat';modelEdit.id='julia-model-detail-edit';modelEdit.addEventListener('click',()=>openJuliaEditor(false,juliaModelDetail.dataset.definitionPath));workspacePageLayouts.get(juliaModelDetail).row.append(modelEdit);
const toolsList=document.createElement('ul');toolsList.id='tools-overview-list';toolsList.className='workspace-file-list';get('#tools-panel').prepend(toolsList);
 const panelSections={'project-overview-panel':'projects-tab','plan-panel':'plan-tab','task-queue-panel':'plan-tab','preview-panel':'artifacts-tab','chat-panel':'chats-tab','tools-panel':'tools-tab','outputs-overview-panel':'presentations-tab','presentation-panel':'presentations-tab'};
 const roots=new Set(['project-overview-panel','plan-panel','chat-panel','tools-panel','outputs-overview-panel']);
 for(const panel of mainTabs.map(tab=>document.getElementById(tab.getAttribute('aria-controls'))).filter(panel=>panel?.parentElement===get('#main-panel-content'))){
  if(workspacePageLayouts.has(panel))continue;
  const tab=mainTabs.find(tab=>tab.getAttribute('aria-controls')===panel.id),heading=panel.querySelector('h1,h2');
  const actions=panel.id==='presentation-panel'?take(panel,['.presentation-editor-head>.form-actions','#presentation-editor-save','#presentation-editor-print','#presentation-editor-use','#presentation-editor-presenter']):panel.id==='project-overview-panel'?take(panel,['#project-overview-edit-todo','#project-conflicts-open']):panel.id==='task-queue-panel'?take(panel,['#task-queue-publish','#task-queue-refresh','#task-queue-revalidate']):panel.id==='plan-panel'?take(panel,['.roadmap-controls','#plan-status']):[];
  const layout=mountWorkspacePage(panel,{title:tab?.textContent||'Stránka',heading,actions,section:panelSections[panel.id]||'tools-tab',close:!roots.has(panel.id),onClose:panel.id==='presentation-panel'?closePresentationEditorPage:null,closeLabel:panel.id==='presentation-panel'?'Zavřít editor':'Zavřít',kind:panel.id==='presentation-panel'?'editor':roots.has(panel.id)||panel.id==='task-queue-panel'?'list':'page',chat:tab?.dataset.promptDefault==='visible'?'full':'hidden'});

 }
 for(const root of [...document.querySelectorAll('main>div')]){
  if(root===projectView||root===artifactEditorView||root===presenterView)continue;
  const heading=root.querySelector('h1,h2'),actions=[];
  mountWorkspacePage(root,{title:heading?.textContent||'Stránka',heading,actions,close:root.id!=='project-home',kind:root.id==='project-home'?'list':'page',section:({'settings-view':'settings-sidebar-tab','federation-view':'federation-tab','federation-network-view':'federation-tab','federation-deployment-view':'federation-tab','source-import-view':'artifacts-tab','history-view':'artifacts-tab'})[root.id]||'projects-tab'});
 }
 for(const label of document.querySelectorAll('.eyebrow,.badge,.dashboard-kicker,#artifact-editor-mode'))if(label.closest('.workspace-page')&&!label.closest('#preview-content'))label.classList.add('layout-label');
 for(const heading of document.querySelectorAll('.page-heading,.home-heading,.project-overview-heading,.outputs-overview-heading,.presentation-editor-head,.julia-editor-heading')){
  if(!heading.querySelector('h1,h2,h3,button,select')&&!heading.closest('#preview-content')){if(heading.classList.contains('page-heading'))for(const paragraph of [...heading.querySelectorAll('p')]){paragraph.classList.add('workspace-page-description');heading.before(paragraph);}heading.hidden=true;}
 }
 get('#project-view>.project-header').hidden=true;
 for(const [root,status] of [[artifactEditorForm,artifactEditorStatus],[juliaEditor,juliaEditorStatus],[get('#presentation-panel'),presentationEditorStatus]]){status.classList.add('workspace-page-status');workspacePageLayouts.get(root).body.prepend(status);}
 document.addEventListener('input',syncPageLayout);document.addEventListener('change',syncPageLayout);
 window.workspacePageLayoutReady=true;renderArtifactOverview();renderToolsOverview();syncPageLayout();
 const observer=new MutationObserver(()=>syncPageLayout());observer.observe(document.querySelector('main'),{subtree:true,attributes:true,attributeFilter:['hidden','data-chat-default']});
}
initializeWorkspacePageLayout();
'''
