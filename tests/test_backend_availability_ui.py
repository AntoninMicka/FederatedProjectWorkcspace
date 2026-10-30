# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Execute the actual monitor JS with delayed fetch and binding changes."""
import json
import shutil
import subprocess
import unittest

from spikes.desktop_ui import JS


class AvailabilityUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_pending_unavailable_stale_and_changed_binding(self):
        render = JS[JS.index('function renderLocalProviderAvailability('):
                    JS.index('async function probeBackendAvailability(')]
        probe = JS[JS.index('async function probeBackendAvailability('):
                   JS.index('function scheduleBackendStateRefresh(')]
        script = r'''
const assert=require('node:assert/strict');
let chatBinding={revision:'one'},backendProbeRunning=false,backendAvailabilityPoll=null;
let latestOllamaRuntime=null,ollamaAvailability=null,availabilityBindingKey=null;
const localProviderIndicator={classList:{remove(){},toggle(){}},textContent:''};
const localProviderAvailability={textContent:''};
const document={hidden:false,querySelector(){return {hidden:false}}};
let timers=[],calls=[];
function setTimeout(fn,delay){timers.push({fn,delay});return timers.length;}
function clearTimeout(){}
let nextResult;
async function projectRequest(path,binding,timeout){calls.push({path,binding,timeout});return await nextResult;}
function runtimeEvidenceText(){return '';}
''' + render + probe + r'''
(async()=>{
 renderLocalProviderAvailability(chatBinding);
 nextResult={status:'unknown',available:null,checking:true,stale:true,checked_at:null,retry_after_ms:1000};
 await probeBackendAvailability();
 assert.equal(calls[0].path,'/v1/chat/availability');
 assert.match(localProviderIndicator.textContent,/ověřuji/);
 assert.doesNotMatch(localProviderIndicator.textContent,/nedostupná/);
 assert.equal(timers.at(-1).delay,1000);
 nextResult={status:'available',available:true,model_available:true,checking:true,stale:true,checked_at:'2026-10-30T12:00:00Z',retry_after_ms:1000};
 await probeBackendAvailability();
 assert.match(localProviderAvailability.textContent,/2026-10-30T12:00:00Z/);
 assert.match(localProviderAvailability.textContent,/čeká na obnovení/);
 nextResult={status:'unavailable',available:false,checking:false,stale:false,checked_at:'now',retry_after_ms:null};
 await probeBackendAvailability();
 assert.match(localProviderIndicator.textContent,/nedostupná/);
 let resolve;
 nextResult=new Promise(r=>resolve=r);
 const pending=probeBackendAvailability();
 const count=calls.length;
 await probeBackendAvailability();
 assert.equal(calls.length,count);
 chatBinding={revision:'two'};
 renderLocalProviderAvailability(chatBinding);
 assert.equal(ollamaAvailability,null);
 resolve({available:true,model_available:true,checked_at:'old binding'});
 await pending;
 assert.equal(ollamaAvailability,null);
 assert.doesNotMatch(localProviderAvailability.textContent,/old binding/);
 nextResult=Promise.reject(new Error('503'));
 await probeBackendAvailability();
 assert.equal(ollamaAvailability.available,null);
 assert.doesNotMatch(localProviderIndicator.textContent,/nedostupná/);
 document.hidden=true;
 await probeBackendAvailability();
 assert.equal(calls.length,count+1);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-'], input=script, text=True,
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
