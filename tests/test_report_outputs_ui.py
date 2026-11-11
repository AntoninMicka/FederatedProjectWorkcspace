# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import shutil
import subprocess
import unittest
from tests.test_workspace_navigation import function


@unittest.skipUnless(shutil.which('node'),'Requires Node.js')
class ReportOutputsUITests(unittest.TestCase):
    def test_rows_are_concrete_editions_not_tasks_and_deduplicate_committed_report(self):
        script=r'''
const assert=require('node:assert/strict');
let monitoringView={outputs:[{id:'git',run_id:'done',title:'Zpráva · 2026-11-11 09:20:30 CET',built_at:'2026-11-11T08:20:30Z'}],reports:[]};
let blockCatalog={jobs:[{id:'task',intent:{kind:'task'},state:'completed',result:{children:[]}},
{id:'done',intent:{kind:'processing',block:{value:{title:'Úloha'}}},state:'review',result:{markdown:'already committed'}},
{id:'draft',intent:{kind:'processing',block:{value:{title:'Úloha'}}},state:'review',result:{markdown:'# Draft',output:{title:'Návrh · 2026-11-11 10:20:30 CET',built_at:'2026-11-11T09:20:30Z'}}}]};
'''+function('reportOutputRows')+r'''
const rows=reportOutputRows();assert.equal(rows.length,2);assert.equal(rows[0].id,'block:draft');
assert.equal(rows[0].title,'Návrh · 2026-11-11 10:20:30 CET');assert.equal(rows[1].id,'git');
assert(!rows.some(r=>r.id==='task'||r.id==='block:done'));
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_cancelled_draft_is_never_labelled_published_or_loaded_via_task(self):
        script=r"""
const assert=require('node:assert/strict');
let activeProject={id:'project'},selectedReportOutput=null,reportOutputSequence=0,monitoringView={reports:[]};
const fields={'#report-output-view':{hidden:false},'#report-output-content':{replaceChildren(){},append(){}},'#report-output-actions':{replaceChildren(){},append(){}},'#report-output-status':{},'#report-output-title':{}};
const document={querySelector:id=>fields[id]||{}};
async function canLeaveWorkspaceEditors(){return true;}
function renderReportOutputs(){}function selectSidebarTab(){}function showWorkspacePage(){}
function monitoringButton(){return {};}
function showMonitoringReport(){}function exportReportMarkdown(){}
async function monitoringRequest(){throw Error('Draft was incorrectly fetched through another resource');}
"""+function('openReportOutput')+r"""
(async()=>{
 await openReportOutput({id:'cancelled',title:'Old draft',source:'legacy-draft',state:'cancelled',markdown:'# Draft',report:{id:'run',state:'cancelled'}});
 assert.equal(fields['#report-output-status'].textContent,'Nevydaný návrh');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
