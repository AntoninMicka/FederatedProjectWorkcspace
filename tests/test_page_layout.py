# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Shared page header, viewer-first flow and page-owned chat mode contracts."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

from spikes.page_layout import PAGE_LAYOUT_JS


class PageLayoutTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_list_refresh_rejects_stale_failed_and_foreign_project_responses(self):
        start = PAGE_LAYOUT_JS.index('async function refreshArtifactOverview(')
        function = PAGE_LAYOUT_JS[start:PAGE_LAYOUT_JS.index('\n}', start) + 2]
        script = r'''
const assert=require('node:assert/strict');
let activeProject={id:'project',head:'head'},rendered=[],response={commit_id:'head',artifacts:[{id:'doc'}]},failure=null;
const status={textContent:''},empty={hidden:false},list={replaceChildren(){this.cleared=true;}};
const document={querySelector:id=>id==='#artifact-overview-status'?status:id==='#artifact-overview-empty'?empty:list};
let projectRequest=async()=>{if(failure)throw failure;return response;};
function renderSidebarArtifacts(value){rendered.push(value);status.textContent='';}
function renderTodo(){}function renderProjectOverview(){}function renderProjectHistory(){}function renderTaskPlanSidebar(){}
'''+function+r'''
(async()=>{
 await refreshArtifactOverview();assert.deepEqual(rendered,[[{id:'doc'}]]);assert.equal(status.textContent,'');
 rendered=[];response={commit_id:'other',artifacts:[{id:'stale'}]};await refreshArtifactOverview();assert.equal(rendered.length,0);assert.match(status.textContent,/Projekt se změnil/);assert.equal(list.cleared,true);assert.equal(empty.hidden,true);
 failure=Error('offline');await refreshArtifactOverview();assert.equal(rendered.length,0);assert.equal(status.textContent,'offline');failure=null;
 let release;projectRequest=()=>new Promise(resolve=>{release=resolve;});const pending=refreshArtifactOverview();
 activeProject={id:'replacement',head:'replacement-head'};status.textContent='replacement';release({commit_id:'head',artifacts:[{id:'old'}]});await pending;assert.equal(rendered.length,0);assert.equal(status.textContent,'replacement');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_chat_modes_preserve_form_and_reject_unknown_values(self):
        start = PAGE_LAYOUT_JS.index('function setPageChatMode(')
        function = PAGE_LAYOUT_JS[start:PAGE_LAYOUT_JS.index('\n}', start) + 2]
        script = r'''
const assert=require('node:assert/strict');
const WORKSPACE_CHAT_MODES=new Set(['full','compact','hidden']);
let workspaceChatModeOverride=null;
const widget={dataset:{},hidden:false,querySelectorAll:()=>[]},promptForm={hidden:false,value:'unsent draft',contains:()=>false};
const document={querySelector:()=>widget};
'''+function+r'''
for(const mode of ['full','hidden','compact','full']){
 setPageChatMode(mode);assert.equal(widget.dataset.chatMode,mode);assert.equal(widget.hidden,false);assert.equal(promptForm.hidden,mode==='hidden');assert.equal(promptForm.value,'unsent draft');
}
assert.throws(()=>setPageChatMode('unknown'));assert.equal(widget.dataset.chatMode,'full');
setPageChatMode('compact',{user:true});setPageChatMode('hidden');assert.equal(widget.dataset.chatMode,'compact');
setPageChatMode('hidden',{user:true});setPageChatMode('full');assert.equal(promptForm.hidden,true);assert.equal(widget.hidden,false);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_shared_headers_viewers_editor_actions_and_chat_modes(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(root/'tests/ui/page_layout_smoke.py')],
                                cwd=root, env={**os.environ, 'PYTHONPATH': str(root)},
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout[-3000:] + result.stderr[-3000:])
        self.assertIn('"ok": true', result.stdout)
