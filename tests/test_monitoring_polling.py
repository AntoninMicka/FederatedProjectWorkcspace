# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Exercise actual monitoring refresh functions with bounded async transport."""
import shutil
import subprocess
import unittest

from spikes.monitoring_ui import JS


@unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
class MonitoringPollingTests(unittest.TestCase):
    def test_hidden_dirty_overlapping_and_stale_project_refreshes(self):
        code = JS[JS.index('let monitoringLoadSequence='):JS.index('function renderMonitoring()')]
        harness = r'''
let activeProject={id:'one',head:'old'},monitoringView=null,monitoringDirty=false,monitoringAttempt=null;
let panelVisible=false,calls=[],blocks=0,rendered=0;
let blockEdit=null,blockProposal=null,blockComposeRun=null,blockSaving=null;
const document={hidden:false,querySelector:()=>({getClientRects:()=>panelVisible?[{}]:[]})},monitoringStatus={};
const monitoringRequest=()=>new Promise((resolve,reject)=>calls.push({resolve,reject}));
const renderMonitoring=()=>rendered++,loadMonitoringBlocks=async()=>{blocks++;};
const check=(value,message)=>{if(!value)throw Error(message);};
'''
        checks = r'''
(async()=>{
 await refreshVisibleMonitoring();check(calls.length===0,'Hidden panel polled');
 panelVisible=true;document.hidden=true;await refreshVisibleMonitoring();check(!calls.length,'Hidden tab polled');
 document.hidden=false;monitoringDirty=true;await refreshVisibleMonitoring();check(!calls.length,'Dirty editor polled');
 monitoringDirty=false;monitoringAttempt={};await refreshVisibleMonitoring();check(!calls.length,'Pending write polled');monitoringAttempt=null;
 for(const set of [v=>blockEdit=v,v=>blockProposal=v,v=>blockComposeRun=v,v=>blockSaving=v]){
 set({});await refreshVisibleMonitoring();check(!calls.length,'Composable editor overwritten');set(null);
 }
 await refreshMonitoringAfterSync({detail:{projectId:'other',status:{state:'idle'}}});
 await refreshMonitoringAfterSync({detail:{projectId:'one',status:{state:'busy'}}});
 check(!calls.length,'Unrelated or incomplete sync loaded monitoring');
 const first=refreshMonitoringAfterSync({detail:{projectId:'one',status:{state:'idle'}}}),overlap=refreshVisibleMonitoring();
 check(calls.length===1,'Overlapping refresh duplicated HTTP request');calls[0].resolve({commit_id:'new'});
 await Promise.all([first,overlap]);check(activeProject.head==='new'&&blocks===1&&rendered===1,'Refresh result lost');
 const old=loadMonitoring();activeProject={id:'two',head:'two-old'};const current=loadMonitoring();
 calls[1].resolve({commit_id:'wrong'});await old;check(activeProject.head==='two-old','Old project response published');
 calls[2].resolve({commit_id:'two-new'});await current;check(activeProject.head==='two-new','New project response lost');
 const failed=loadMonitoring();calls[3].reject(Error('Unavailable'));await failed;check(monitoringStatus.textContent==='Unavailable','Failure hidden');
 const retry=loadMonitoring();check(calls.length===5,'Failure left refresh stuck');calls[4].resolve({commit_id:'recovered'});await retry;
 // A read after an explicit save must not join an older pre-save response.
 const stale=loadMonitoring(),afterSave=loadMonitoring();check(calls.length===7,'Explicit refresh after save was coalesced');
 calls[5].resolve({commit_id:'pre-save'});await stale;check(activeProject.head==='recovered','Pre-save read replaced current head');
 calls[6].resolve({commit_id:'post-save'});await afterSave;check(activeProject.head==='post-save','Post-save refresh lost');
 console.log('monitoring refresh behavior OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', harness + code + checks], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('monitoring refresh behavior OK', result.stdout)
