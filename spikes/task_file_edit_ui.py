# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Selected-file proposals use the shared editor and one exact diff confirmation."""

FILE_EDIT_HTML = '''<dialog id="task-file-edit-dialog" aria-labelledby="task-file-edit-heading">
<h2 id="task-file-edit-heading">Uložit změny vybraného dokumentu</h2>
<p id="task-file-edit-target"></p><pre id="task-file-edit-diff"></pre>
<label class="confirm"><input id="task-file-edit-approved" type="checkbox"> Souhlasím s uvedenými změnami a uložením do tohoto dokumentu.</label>
<div class="form-actions"><button type="button" data-file-edit-choice="save" disabled>Potvrdit a uložit</button><button type="button" class="secondary-button" data-file-edit-choice="cancel">Zrušit</button></div>
</dialog>'''

FILE_EDIT_CSS = '''
#task-file-edit-dialog{width:min(900px,90vw);max-height:85vh;box-sizing:border-box;border:1px solid #bfcdc9;border-radius:14px;padding:20px;color:#213746}
#task-file-edit-dialog pre{max-height:48vh;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;padding:12px;background:#f3f7f8}
#task-file-edit-dialog .confirm{display:flex;align-items:center;gap:8px}
#task-file-edit-dialog .form-actions{margin-top:12px}
'''

FILE_EDIT_JS = r'''
let taskFileEditScopeKey=null,taskFileEditScopeLoading=null;
async function loadTaskFileEditScope(){
 const select=document.querySelector('#task-edit-scope'),target=selectedTaskFileEditTarget();
 if(!target||!activeProject)return;
 const key=activeProject.id+':'+activeProject.head+':'+target;
 if(taskFileEditScopeKey===key||taskFileEditScopeLoading===key)return;
 taskFileEditScopeLoading=key;taskFileEditScopeKey=null;select.disabled=true;select.replaceChildren(new Option('Načítám rozsah…',''));
 try{
  const result=await projectRequest('/v1/artifacts/editor/open',{project_id:activeProject.id,artifact_id:target,expected_head:activeProject.head});
  if(taskFileEditScopeLoading!==key||!activeProject||key!==activeProject.id+':'+activeProject.head+':'+selectedTaskFileEditTarget())return;
  if(result.markdown_scope_error)throw new Error(result.markdown_scope_error);
  select.replaceChildren(new Option('Celý dokument',''));
  for(const heading of result.markdown_outline??[])select.append(new Option('  '.repeat(heading.level-1)+heading.title+' ('+heading.block_id+')',JSON.stringify(heading.block_ids??[heading.block_id])));
  taskFileEditScopeKey=key;select.disabled=false;
 }catch(error){if(taskFileEditScopeLoading===key){select.replaceChildren(new Option('Rozsah nelze načíst',''));chatOperationStatus.textContent=error.message;}}
 finally{if(taskFileEditScopeLoading===key)taskFileEditScopeLoading=null;}
}
function selectedTaskFileEditTarget(){
 return document.querySelector('#chat-mode').value==='orchestration'&&document.querySelector('#task-output-kind').value==='file-edit'?document.querySelector('#task-edit-target').value:null;
}
function renderTaskFileEditTargets(){
 const control=document.querySelector('#task-edit-target-control'),select=document.querySelector('#task-edit-target');
 if(!control||!select)return;
 const previous=select.value,items=currentArtifacts.filter(item=>item.kind==='document');
 select.replaceChildren(new Option('Vyberte Markdown dokument',''));
 for(const item of items)select.append(new Option(item.title,item.id));
 select.value=items.some(item=>item.id===previous)?previous:items.some(item=>item.id===selectedArtifact)?selectedArtifact:'';
 control.hidden=document.querySelector('#chat-mode').value!=='orchestration'||document.querySelector('#task-output-kind').value!=='file-edit';
 document.querySelector('#task-edit-format-control').hidden=control.hidden;
 document.querySelector('#task-edit-scope-control').hidden=control.hidden||document.querySelector('#task-edit-format').value!=='blocks';
 if(!control.hidden&&document.querySelector('#task-edit-format').value==='blocks')loadTaskFileEditScope();
 document.querySelector('#task-edit-format').disabled=!activeProject||Boolean(activeProject.readOnly);
 select.disabled=!activeProject||Boolean(activeProject.readOnly);
}
document.querySelector('#task-output-kind').addEventListener('change',()=>{pendingChatRequest=null;refreshChatModeControls();});
document.querySelector('#task-edit-format').addEventListener('change',()=>{pendingChatRequest=null;renderTaskFileEditTargets();});
document.querySelector('#task-edit-scope').addEventListener('change',()=>{pendingChatRequest=null;});
document.querySelector('#task-edit-target').addEventListener('change',()=>{pendingChatRequest=null;loadTaskFileEditScope();updatePromptInputSummary();});

function resetTaskFileEditEditor(){
 artifactEditorTaskEdit=null;
 for(const name of ['title','filename','description','tags'])artifactEditorForm.elements[name].disabled=false;
 artifactRawWidget.setDisabled(false);
}
async function openTaskFileEditEditor(projection){
 if(!activeProject||activeProject.id!==projection.project_id||activeProject.readOnly||!await canLeaveWorkspaceEditors())return;
 const project=activeProject;
 try{
  const proposed=projection.file_edit_approval?.body??projection.outcome.content;
  const preview=await projectRequest('/v1/tasks/file-edit/preview',{project_id:project.id,task_id:projection.task_id,...(proposed===undefined?{}:{body:proposed})});
  if(activeProject!==project)return;
  artifactEditorItem={id:preview.confirmation.artifact_id,title:preview.title,kind:'document'};
  showWorkspacePage(artifactEditorView);selectSidebarTab(document.querySelector('#artifacts-tab'));hideArtifactDeletion();
  fillArtifactEditor(preview.document,false,{rawOnly:true});
  artifactEditorForm.elements.body.value=preview.body;artifactEditorForm.elements.body.dispatchEvent(new Event('input',{bubbles:true}));
  artifactEditorTaskEdit={task_id:projection.task_id,project,confirmation:preview.pending_confirmation?preview.confirmation:null};
  artifactEditorDirty=true;
  for(const name of ['title','filename','description','tags'])artifactEditorForm.elements[name].disabled=true;
  if(preview.pending_confirmation){artifactRawWidget.setDisabled(true);artifactEditorAttempt={file_edit:true,request:preview.confirmation};}
  artifactEditorStatus.textContent=preview.pending_confirmation?'Dokončete původní potvrzené uložení; návrh je připnutý.':'Návrh úpravy vstupu. Uložit nejprve zobrazí porovnání a vyžádá potvrzení.';
  closeMobileSidebar();closeCompactSidebarMenu();artifactEditorForm.elements.body.focus();syncPageLayout();
 }catch(error){chatOperationStatus.textContent=error.message;}
}
async function askTaskFileEditApproval(preview){
 const dialog=document.querySelector('#task-file-edit-dialog'),check=document.querySelector('#task-file-edit-approved'),save=dialog.querySelector('[data-file-edit-choice=save]');
 document.querySelector('#task-file-edit-target').textContent=`${preview.title} · ${preview.confirmation.artifact_id} · revize ${preview.confirmation.base_head.slice(0,12)}. Původ změn bude zaznamenán jako transformace pomocí LLM.`;
 document.querySelector('#task-file-edit-diff').textContent=preview.diff||'Obsah se nemění; potvrzení zaznamená původ transformace.';
 check.checked=false;save.disabled=true;
 return new Promise(resolve=>{
  const finish=value=>{dialog.removeEventListener('click',click);dialog.removeEventListener('cancel',cancel);check.removeEventListener('change',change);dialog.close();resolve(value);};
  const change=()=>{save.disabled=!check.checked;};
  const click=event=>{const button=event.target.closest('[data-file-edit-choice]');if(button&&(button.dataset.fileEditChoice!=='save'||check.checked))finish(button.dataset.fileEditChoice==='save');};
  const cancel=event=>{event.preventDefault();finish(false);};
  dialog.addEventListener('click',click);dialog.addEventListener('cancel',cancel);check.addEventListener('change',change);dialog.showModal();
 });
}
async function saveTaskFileEditEditor(navigate=true){
 const context=artifactEditorTaskEdit,project=activeProject,button=artifactEditorForm.querySelector('button[type=submit]');
 if(!context||context.project!==project||project.readOnly)return false;
 button.disabled=true;
 try{
  if(!context.confirmation){
   if(!await artifactRawWidget.validate())return false;
   const preview=await projectRequest('/v1/tasks/file-edit/preview',{project_id:project.id,task_id:context.task_id,body:artifactEditorForm.elements.body.value});
   if(activeProject!==project||artifactEditorTaskEdit!==context)return false;
   if(!await askTaskFileEditApproval(preview)){artifactEditorStatus.textContent='Uložení zrušeno; návrh zůstává v editoru.';return false;}
   context.confirmation={...preview.confirmation,operation_id:crypto.randomUUID()};
   artifactEditorAttempt={file_edit:true,request:context.confirmation};artifactRawWidget.setDisabled(true);
  }
  artifactEditorStatus.textContent='Ukládám potvrzenou úpravu vstupu…';
  const result=await projectRequest('/v1/tasks/file-edit/confirm',context.confirmation,120000);
  if(activeProject!==project||artifactEditorTaskEdit!==context)return true;
  const id=context.confirmation.artifact_id;activeProject.head=result.outcome.project_commit;replaceTaskProjection(result);
  artifactEditorAttempt=null;artifactEditorDirty=false;artifactEditorItem=null;artifactEditorView.hidden=true;resetTaskFileEditEditor();
  if(navigate){await openRegisteredProject(project.id);await openPreview(id);previewStatus.textContent='Potvrzené změny byly uloženy do původního dokumentu.';}
  return true;
 }catch(error){artifactEditorStatus.textContent=error.message+' Při neznámém výsledku opakujte původní potvrzené uložení nebo obnovte stav úlohy.';return false;}
 finally{button.disabled=false;}
}
'''
