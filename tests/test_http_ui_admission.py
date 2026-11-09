# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import subprocess
import unittest

from spikes.http_ui_admission import HTTP_UI_ADMISSION_JS


class UIAdmissionTests(unittest.TestCase):
    def test_hidden_presenter_does_not_poll_and_visible_polls_do_not_overlap(self):
        from spikes.desktop_ui import PUBLIC_JS
        script = PUBLIC_JS[PUBLIC_JS.index("const screen=document.querySelector('#screen');"):]
        harness = r'''
const assert=require('node:assert/strict');
const listeners={},pending=[];let count=0,interval;
global.document={hidden:true,querySelector:()=>({}),addEventListener:(name,fn)=>listeners[name]=fn};
global.addEventListener=()=>{};global.setInterval=fn=>{interval=fn;};
global.innerWidth=1600;global.innerHeight=900;
global.fetch=()=>{count++;return new Promise(resolve=>pending.push(resolve));};
'''
        checks = r'''
(async()=>{
 assert.equal(count,0);interval();assert.equal(count,0);
 document.hidden=false;listeners.visibilitychange();assert.equal(count,2);
 interval();interval();assert.equal(count,2);
 while(pending.length)pending.shift()({ok:false});
 await new Promise(resolve=>setImmediate(resolve));
 interval();assert.equal(count,3);
 document.hidden=true;interval();assert.equal(count,3);
 while(pending.length)pending.shift()({ok:false});
 console.log('presenter checks completed');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', harness + script + checks],
                                capture_output=True, text=True, check=True, timeout=10)
        self.assertIn('presenter checks completed', result.stdout)

    def test_lanes_streaming_abort_and_failure_release_with_real_fetch_objects(self):
        harness = r'''
const assert=require('node:assert/strict');
global.window=globalThis;global.location={href:'http://localhost/',origin:'http://localhost'};
const controls=new Map(),calls=[];
global.fetch=async(path,options)=>{
 calls.push(path);
 if(path==='/v1/failure')throw new TypeError('network failure');
 return new Response(new ReadableStream({start(controller){controls.set(path,controller);}}));
};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const post=path=>fetch(path,{method:'POST'});
const end=path=>{controls.get(path).enqueue(new TextEncoder().encode('{}'));controls.get(path).close();};
'''
        checks = r'''
(async()=>{
 const a=post('/v1/a');const b=post('/v1/b');
 const first=await a; // streaming headers must return before EOF
 assert(controls.has('/v1/a'));assert(!controls.has('/v1/b'));
 const t=post('/v1/node-telemetry/status');await t;
 const t2=post('/v1/node-telemetry/status');
 const d=post('/v1/diagnostics/status');await d;
 assert.equal(calls.filter(x=>x==='/v1/node-telemetry/status').length,1);
 const abort=new AbortController();
 const cancelled=fetch('/v1/cancelled',{method:'POST',signal:abort.signal});
 abort.abort();await assert.rejects(cancelled,{name:'AbortError'});
 end('/v1/a');await first.text();
 const second=await b;assert(!calls.includes('/v1/cancelled'));
 end('/v1/b');await second.text();
 end('/v1/node-telemetry/status');await t2;
 end('/v1/node-telemetry/status');end('/v1/diagnostics/status');
 await tick();await tick();
 await assert.rejects(post('/v1/failure'),{name:'TypeError'});
 const after=await post('/v1/after');end('/v1/after');await after.text();
 assert.equal(calls.filter(x=>x==='/v1/failure').length,1); // no retry
 assert(!calls.includes('/v1/cancelled'));
 console.log('admission checks completed');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', harness + HTTP_UI_ADMISSION_JS + checks],
                       check=True, capture_output=True, text=True, timeout=15)
        self.assertIn('admission checks completed', result.stdout)
