# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import shutil
import subprocess
import unittest
from spikes.desktop_ui import HTML
from tests.test_workspace_navigation import function


class ToolSidebarTests(unittest.TestCase):
    def test_one_tree_and_creation_menu_reuse_all_existing_editor_ids(self):
        sidebar=HTML.split('id="sidebar-tools"',1)[1].split('id="sidebar-presentations"',1)[0]
        self.assertIn('id="sidebar-tools-tree"',sidebar)
        for kind in ('julia','source','filter','pool','processing','task','legacy'):
            self.assertIn('data-tool-category="'+kind+'"',sidebar)
        for kind in ('source','filter','pool','processing','task','compose'):
            self.assertEqual(sidebar.count('data-new-monitoring-block="'+kind+'"'),1)
        for id_ in ('julia-editor-new','monitoring-new','monitoring-workflow-new','sidebar-monitoring-new'):
            self.assertEqual(HTML.count('id="'+id_+'"'),1)
            self.assertIn('id="'+id_+'"',sidebar)

    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_new_actions_preserve_leave_permission_and_project_guards(self):
        script=r'''
const assert=require('node:assert/strict');
let activeProject={id:'one',readOnly:false},blockCatalog={can_manage:true},allowed=true,opened=[],loads=0;
let blockSelectedId='old',blockTab='',changeProject=false;
async function canLeaveWorkspaceEditors(){return allowed;}
async function loadMonitoring(){loads++;blockCatalog={can_manage:true};if(changeProject)activeProject={id:'two'};}
function blockReadOnly(){return !blockCatalog.can_manage;}
const sidebarToolNewOptions={hidden:false},sidebarNewTool={setAttribute(){}};
function monitoringOpen(){opened.push('open');}function renderMonitoringBlocks(){}
async function editMonitoringBlock(kind){opened.push(kind);}
const compose={hidden:true,focus(){opened.push('focus');}};
const document={querySelector:()=>compose};
function closeMobileSidebar(){}function closeCompactSidebarMenu(){}
'''+function('createMonitoringTool')+r'''
(async()=>{
 allowed=false;await createMonitoringTool('filter');assert.deepEqual(opened,[]);
 allowed=true;activeProject.readOnly=true;await createMonitoringTool('filter');assert.deepEqual(opened,[]);
 activeProject.readOnly=false;blockCatalog.can_manage=false;await createMonitoringTool('filter');assert.deepEqual(opened,[]);
 blockCatalog.can_manage=true;await createMonitoringTool('filter');assert.deepEqual(opened,['open','filter']);assert.equal(blockSelectedId,null);assert.equal(sidebarToolNewOptions.hidden,true);
 opened=[];blockCatalog=null;changeProject=true;await createMonitoringTool('pool');assert.equal(loads,1);assert.deepEqual(opened,[]);
 changeProject=false;await createMonitoringTool('compose');assert.deepEqual(opened,['open','focus']);assert.equal(blockTab,'task');assert.equal(compose.hidden,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
