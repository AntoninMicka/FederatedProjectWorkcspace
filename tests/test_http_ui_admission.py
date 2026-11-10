# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import subprocess
import json
import os
import sys
import unittest

from spikes.http_ui_admission import HTTP_UI_ADMISSION_JS


class UIAdmissionTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1',
                         'Requires real Qt/WebEngine')
    def test_real_webengine_two_pages_use_origin_wide_admission(self):
        script = r'''
import json,threading,time
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from spikes.http_ui_admission import HTTP_UI_ADMISSION_JS
from spikes.local_api import Handler,running_api
entered=threading.Event();finished=threading.Event();catalog_during=[]
class Fixture(Handler):
 reserve_ui_worker=True
 post_paths={'/v1/chat/test','/v1/chat/send','/v1/projects'}
 def _do_GET(self):
  raw=b'<!doctype html><title>Admission fixture</title>'
  self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def dispatch(self,request):
  if self.path=='/v1/chat/test':
   entered.set();time.sleep(1.2);finished.set()
  elif self.path=='/v1/projects':catalog_during.append(not finished.is_set())
  self.reply(200,{'ok':True})
app=QApplication([])
with running_api('http',handler=Fixture) as server:
 profile=QWebEngineProfile(app)
 pages=[QWebEnginePage(profile,app) for _ in range(2)]
 loaded=set();started=False;checking=False
 options=json.dumps({'method':'POST','headers':{'Content-Type':'application/json','Authorization':'Bearer '+server.token},'body':'{}'})
 def onload(index,ok):
  if not ok:return app.exit(3)
  def installed(value):loaded.add(index)
  pages[index].runJavaScript(HTTP_UI_ADMISSION_JS+';window.results=[];Boolean(navigator.locks?.request)',0,lambda value:installed(value) if value else app.exit(4))
 for index,page in enumerate(pages):
  page.loadFinished.connect(lambda ok,index=index:onload(index,ok));page.setUrl(QUrl(server.origin+'/'))
 def start_other():
  if not entered.is_set():return QTimer.singleShot(10,start_other)
  pages[1].runJavaScript("for(const path of ['/v1/chat/send','/v1/projects'])fetch(path,"+options+").then(r=>results.push([path,r.status])).catch(()=>results.push(['error',0]));")
 def inspect():
  global started,checking
  if len(loaded)==2 and not started:
   started=True
   pages[0].runJavaScript("fetch('/v1/chat/test',"+options+").then(r=>results.push(['slow',r.status]));")
   start_other()
  if not started or checking:return
  checking=True
  def first(raw):
   a=json.loads(raw)
   def second(raw):
    global checking
    checking=False;b=json.loads(raw)
    if len(a)!=1 or len(b)!=2:return
    if a!=[['slow',200]] or sorted(b)!=[['/v1/chat/send',200],['/v1/projects',200]] or catalog_during!=[True]:
     print('ownership failure',a,b,catalog_during,flush=True);return app.exit(5)
    print('real two-page Web Locks admission verified',flush=True);app.exit(0)
   pages[1].runJavaScript('JSON.stringify(results)',0,second)
  pages[0].runJavaScript('JSON.stringify(results)',0,first)
 timer=QTimer();timer.timeout.connect(inspect);timer.start(20)
 QTimer.singleShot(15000,lambda:app.exit(2))
 code=app.exec()
 for page in pages:page.deleteLater()
 app.processEvents()
 profile.deleteLater();app.processEvents()
 raise SystemExit(code)
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('real two-page Web Locks admission verified', result.stdout)

    def test_two_pages_share_locks_until_eof_and_keep_domains_independent(self):
        harness = r'''
const assert=require('node:assert/strict'),vm=require('node:vm');
const queues=new Map(),controls=new Map(),calls=[];
const locks={request(name,options,callback){
 const previous=queues.get(name)||Promise.resolve();
 const result=previous.then(()=>{
  if(options.signal?.aborted)throw options.signal.reason;
  return callback();
 });
 queues.set(name,result.catch(()=>{}));return result;
}};
function page(id){
 const scope={URL,DOMException,Promise,location:{href:'http://localhost/',origin:'http://localhost'},
  navigator:{locks},fetch:async(path)=>{
   calls.push(id+path);
   return new Response(new ReadableStream({start(controller){controls.set(id+path,controller);}}));
  }};
 scope.window=scope;vm.runInNewContext(__POLICY__,scope);return scope;
}
const a=page('a'),b=page('b'),post=(p,path)=>p.fetch(path,{method:'POST'});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function end(id,path){controls.get(id+path).close();}
(async()=>{
 const first=await post(a,'/v1/chat/test');
 const second=post(b,'/v1/chat/send');
 await tick();assert(!calls.includes('b/v1/chat/send'));
 // Polling on another page and peer reception do not join the application
 // lock. All response bodies still retain their own domain until EOF.
 const catalog=await post(b,'/v1/projects');
 const presenter=await post(b,'/v1/presentation/public');
 const sync=await post(a,'/v1/federation/content-sync');
 const control=post(a,'/v1/presentation/control');
 await tick();assert(!calls.includes('a/v1/presentation/control'));
 end('b','/v1/presentation/public');await presenter.text();
 const controlled=await control;
 assert(!calls.includes('b/v1/chat/send'));
 end('a','/v1/chat/test');await first.text();
 const sent=await second;
 end('b','/v1/chat/send');end('b','/v1/projects');
 end('a','/v1/presentation/control');end('a','/v1/federation/content-sync');
 await Promise.all([sent.text(),catalog.text(),controlled.text(),sync.text()]);
 console.log('two-page ownership verified');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('__POLICY__', json.dumps(HTTP_UI_ADMISSION_JS))
        result = subprocess.run(['node', '-e', harness], capture_output=True,
                                text=True, check=True, timeout=15)
        self.assertIn('two-page ownership verified', result.stdout)

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
 const opening=post('/v1/projects/open');
 await new Promise(resolve=>setTimeout(resolve,25));
 assert(!calls.includes('/v1/projects/open'));
 end('/v1/a');await first.text();
 const second=await b;assert(!calls.includes('/v1/cancelled'));
 end('/v1/b');await second.text();
 const opened=await opening;end('/v1/projects/open');await opened.text();
 await new Promise(resolve=>setTimeout(resolve,25));
 assert(opened.fpwAdmissionTiming.queue_ms>=20,'Project timing omitted browser queue');
 assert(opened.fpwAdmissionTiming.headers_ms>=0);
 assert(opened.fpwAdmissionTiming.drain_ms>=0);
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
