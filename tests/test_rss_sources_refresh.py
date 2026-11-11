# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import shutil
import subprocess
import unittest
from tests.test_workspace_navigation import function


@unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
class ReaderRefreshTests(unittest.TestCase):
    def test_visible_due_refresh_is_one_channel_and_manual_batch_stops_on_navigation(self):
        script=r'''
const assert=require('node:assert/strict');
let sourcesView={can_refresh:true,channels:[{id:'one',due:false},{id:'two',due:true},{id:'three',due:true}]};
let sourcesBusy=false,sourcesDirty=false,sourcesChannel='all',sourcesSequence=0;
const sourcesEditor={hidden:true},sourcesImportReview={hidden:true},sourcesRefresh={},sourcesStatus={};
const panel={hidden:false},document={hidden:false,getElementById:()=>panel};
let calls=[],leave=false;
async function projectRequest(path,payload){calls.push(payload);if(leave)panel.hidden=true;return sourcesView;}
function renderSources(){}
'''+function('loadSources')+'\n'+function('refreshDueSources')+r'''
(async()=>{
 document.hidden=true;await refreshDueSources();assert.equal(calls.length,0);
 document.hidden=false;panel.hidden=true;await refreshDueSources();assert.equal(calls.length,0);
 panel.hidden=false;sourcesDirty=true;await refreshDueSources();assert.equal(calls.length,0);
 sourcesDirty=false;sourcesEditor.hidden=false;await refreshDueSources();assert.equal(calls.length,0);
 sourcesEditor.hidden=true;sourcesBusy=true;await refreshDueSources();assert.equal(calls.length,0);
 sourcesBusy=false;await refreshDueSources();assert.deepEqual(calls,[{channel_id:'two',due_only:true}]);
 calls=[];leave=true;await loadSources(true);assert.equal(calls.length,1);assert.equal(calls[0].channel_id,'one');
 assert.equal(sourcesBusy,false);
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
