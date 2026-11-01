# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Shared navigation and editor-exit behavior; Qt shell smoke is opt-in."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from spikes.desktop_ui import JS


def function(name):
    start = JS.index('function ' + name + '(')
    if JS[max(0, start - 6):start] == 'async ':
        start -= 6
    return JS[start:JS.index('\n}', start) + 2]


class WorkspaceNavigationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_sidebar_routes_hide_standalone_pages_only_after_allowed_exit(self):
        script = r'''
const assert=require('node:assert/strict');
const ids=['project-home','project-view','settings-view','history-view','source-import-view','project-create-view','project-trash-view','project-repair-view','notebooklm-import-view','federation-view','federation-network-view','federation-deployment-view'];
const pages=ids.map(id=>({id,hidden:true})),byId=new Map(pages.map(page=>[page.id,page]));
const document={querySelectorAll:()=>pages,querySelector:id=>byId.get(id.slice(1)),getElementById:id=>({id}),dispatchEvent:()=>{}};
const projectView=byId.get('project-view'),settingsView=byId.get('settings-view');
let activeProject={id:'project'},userProfileLoaded=true,allowed=true,selected=null,main=null,loads=0;
async function canLeaveWorkspaceEditors(){return allowed;}
function selectSidebarTab(tab){selected=tab.id;}
function selectMainTab(tab){main=tab.id;}
function closeMobileSidebar(){}function closeCompactSidebarMenu(){}
async function loadChat(){loads++;}
async function loadProjects(){showWorkspacePage(byId.get('project-home'));}
async function openSettings(){showWorkspacePage(settingsView);}
async function openFederationSharing(){showWorkspacePage(byId.get('federation-view'));}
async function openOutputsOverview(){showWorkspacePage(projectView);}
function openTaskPlan(){}let taskPlanSelection=null;
'''
        script += '\n' + function('showWorkspacePage') + '\n' + function('navigateSidebarTab')
        script += r'''
(async()=>{
 for(const page of pages){
  showWorkspacePage(page);allowed=false;
  assert.equal(await navigateSidebarTab({id:'chats-tab'}),false);
  assert.equal(page.hidden,false);assert.equal(pages.filter(p=>!p.hidden).length,1);
  allowed=true;assert.equal(await navigateSidebarTab({id:'chats-tab'}),true);
  assert.equal(projectView.hidden,false);assert.equal(pages.filter(p=>!p.hidden).length,1);
  assert.equal(selected,'chats-tab');assert.equal(main,'chat-tab');
 }
 assert.equal(loads,pages.length);
 const before=selected;assert.equal(await navigateSidebarTab({id:'tools-tab',disabled:true}),false);assert.equal(selected,before);
 await navigateSidebarTab({id:'settings-sidebar-tab'});assert.equal(settingsView.hidden,false);
 await navigateSidebarTab({id:'federation-tab'});assert.equal(byId.get('federation-view').hidden,false);
 await navigateSidebarTab({id:'projects-tab'});assert.equal(byId.get('project-home').hidden,false);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_editor_exit_cancel_save_failure_discard_escape_and_clean_buffers(self):
        script = r'''
const assert=require('node:assert/strict');
const handlers=new Map();
const editorLeaveDialog={open:false,addEventListener:(type,fn)=>handlers.set(type,fn),removeEventListener:type=>handlers.delete(type),showModal(){this.open=true;},close(){this.open=false;}};
const document={querySelector:()=>({textContent:''})};
let editorLeavePending=false;
let artifactEditorView={hidden:false},artifactEditorDirty=false,artifactEditorAttempt=null,artifactEditorItem={id:'doc'};
let juliaEditor={hidden:false},juliaEditorDirty=false,juliaEditorAttempt=null,juliaEditorModel={};
let presentationEditorDirty=false,presentationEditorAttempt=null,presentationEditorView={},presentationEditorDeck={},presentationEditorWorkspace={hidden:false},presentationRawPanel={hidden:true};
let conflicts=false,projectConflictOperation=null;
let projectConflictDrafts=new Map();
function closeConflictDialog(){conflicts=false;}
function conflictDraftChanged(){return conflicts;}
function resetProjectConflicts(){conflicts=false;projectConflictOperation=null;}
let writes=0,saveOK=true;
async function saveArtifactEditor(navigate){assert.equal(navigate,false);writes++;if(!saveOK)return false;artifactEditorDirty=false;artifactEditorAttempt=null;return true;}
async function saveJuliaEditor(navigate){assert.equal(navigate,false);writes++;if(!saveOK)return false;juliaEditorDirty=false;return true;}
async function savePresentationEditor(navigate){assert.equal(navigate,false);writes++;if(!saveOK)return false;presentationEditorDirty=false;return true;}
async function saveConflictEditor(navigate){assert.equal(navigate,false);writes++;if(!saveOK)return false;resetProjectConflicts();return true;}
const choose=choice=>handlers.get('click')({target:{closest:()=>({dataset:{leaveChoice:choice}})}});
'''
        for name in ('resolveEditorLeave', 'canLeaveArtifactEditor', 'canLeaveJuliaEditor',
                     'canLeavePresentationEditor', 'canLeaveConflictEditor'):
            script += '\n' + function(name)
        script += r'''
(async()=>{
 for(const guard of [canLeaveArtifactEditor,canLeaveJuliaEditor,canLeavePresentationEditor,canLeaveConflictEditor]){
  assert.equal(await guard(),true);assert.equal(editorLeaveDialog.open,false);
 }
 const editors=[
  [canLeaveArtifactEditor,()=>{artifactEditorView.hidden=false;artifactEditorDirty=true;}],
  [canLeaveJuliaEditor,()=>{juliaEditor.hidden=false;juliaEditorDirty=true;}],
  [canLeavePresentationEditor,()=>{presentationEditorDirty=true;}],
  [canLeaveConflictEditor,()=>{conflicts=true;}]
 ];
 for(const [guard,dirty] of editors){
  dirty();let pending=guard();assert.equal(editorLeaveDialog.open,true);choose('cancel');assert.equal(await pending,false);
  saveOK=false;pending=guard();choose('save');assert.equal(await pending,false);assert.equal(editorLeaveDialog.open,false);
  saveOK=true;pending=guard();choose('save');assert.equal(await pending,true);assert.equal(await guard(),true);
  dirty();pending=guard();assert.equal(await guard(),false);let prevented=false;handlers.get('cancel')({preventDefault(){prevented=true;}});assert.equal(await pending,false);assert.equal(prevented,true);
  const count=writes;pending=guard();choose('discard');assert.equal(await pending,true);assert.equal(writes,count);assert.equal(await guard(),true);
 }
 assert.equal(writes,8);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_shell_leaves_standalone_pages_and_preserves_unsaved_editors(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root / 'tests/ui/workspace_navigation_smoke.py')],
                                cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-3000:])
        self.assertIn('"ok": true', result.stdout)
