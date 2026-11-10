# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import subprocess
import json
import os
import sys
import unittest

from spikes.http_ui_admission import HTTP_UI_ADMISSION_JS


class UIAdmissionTests(unittest.TestCase):
    def test_project_client_preserves_admission_and_uncertain_response_outcomes(self):
        from spikes.desktop_ui import JS
        start=JS.index('async function projectRequest(')
        request=JS[start:JS.index('\n}',start)+2]
        start=JS.index('async function streamRequest(')
        request+='\n'+JS[start:JS.index('\n}',start)+2]
        script=r'''
const assert=require('node:assert/strict');
global.scheduleBackendStateRefresh=()=>{};
'''+request+r'''
(async()=>{
 const before=Object.assign(new Error('not sent'),{name:'TimeoutError',phase:'admission',outcome:'not-started',status:503});
 global.fetch=async()=>{throw before;};
 await assert.rejects(projectRequest('/v1/chat/send',{}),e=>e===before&&e.outcome==='not-started');
 global.fetch=async()=>({status:200,json:async()=>{throw new SyntaxError('incomplete body');}});
 await assert.rejects(projectRequest('/v1/chat/send',{}),{outcome:'unknown',status:408,retry:'same-operation'});
 global.fetch=async()=>({ok:false,status:503,json:async()=>({error:'busy',outcome:'not-started',retry:'same-operation'})});
 await assert.rejects(projectRequest('/v1/chat/send',{}),{outcome:'not-started',status:503});
 global.fetch=async()=>new Response('{"type":"error","status":503,"error":"busy","outcome":"unknown","retry":"same-operation"}\n');
 await assert.rejects(streamRequest('/v1/chat/send-stream',{},()=>{}),{status:503,outcome:'unknown',retry:'same-operation'});
 global.fetch=async()=>new Response('{"type":"status","status":"working"}\n');
 await assert.rejects(streamRequest('/v1/chat/send-stream',{},()=>{}),{status:408,outcome:'unknown',retry:'same-operation'});
 console.log('client outcomes OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('client outcomes OK',result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires real Qt/WebEngine')
    def test_real_webengine_expired_origin_lock_wait_never_reaches_backend(self):
        script=r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from spikes.http_ui_admission import HTTP_UI_ADMISSION_JS
from spikes.local_api import Handler,running_api
writes=[]
class Fixture(Handler):
 post_paths={'/v1/write','/v1/diagnostics/status'}
 def _do_GET(self):
  self.reply(200,{'ready':True})
 def dispatch(self,request):
  if self.path=='/v1/write':writes.append(request['operation_id'])
  self.reply(200,{'ok':True})
app=QApplication([])
with running_api('http',handler=Fixture) as server:
 profile=QWebEngineProfile(app);pages=[QWebEnginePage(profile,app) for _ in range(2)]
 loaded=set();phase=0;checking=False
 options=json.dumps({'method':'POST','headers':{'Content-Type':'application/json','Authorization':'Bearer '+server.token},'body':'{"operation_id":"fixed-review-id"}'})
 def install(i,ok):
  if not ok:return app.exit(3)
  pages[i].runJavaScript(HTTP_UI_ADMISSION_JS+';true',0,lambda value:loaded.add(i))
 for i,page in enumerate(pages):
  page.loadFinished.connect(lambda ok,i=i:install(i,ok));page.setUrl(QUrl(server.origin+'/'))
 def received(raw):
  global phase,checking
  checking=False;value=json.loads(raw) if raw else {}
  if phase==1 and value.get('held'):
   phase=2
   pages[1].runJavaScript("fetch('/v1/write',"+options+").then(()=>window.expired={unexpected:true}).catch(e=>window.expired={name:e.name,outcome:e.outcome,phase:e.phase});fetch('/v1/diagnostics/status',"+options+").then(r=>window.diagnostic=r.status);")
  elif phase==2 and value.get('expired'):
   assert value['expired']=={'name':'TimeoutError','outcome':'not-started','phase':'admission'},value
   assert value.get('diagnostic')==200 and writes==[],(value,writes)
   phase=3;pages[0].runJavaScript('releaseHeld()')
   pages[1].runJavaScript("fetch('/v1/write',"+options+").then(r=>r.json()).then(v=>window.retried=v);")
  elif phase==3 and value.get('retried'):
   assert writes==['fixed-review-id'],writes
   print('real origin-lock timeout, independent diagnostic and exact retry OK',flush=True);app.exit(0)
 def poll():
  global phase,checking
  if len(loaded)!=2 or checking:return
  if phase==0:
   phase=1;pages[0].runJavaScript("navigator.locks.request('fpw-http-application',async()=>{window.held=true;await new Promise(resolve=>window.releaseHeld=resolve);});")
  checking=True
  page=pages[0] if phase==1 else pages[1]
  page.runJavaScript('JSON.stringify({held:window.held,expired:window.expired,diagnostic:window.diagnostic,retried:window.retried})',0,received)
 timer=QTimer();timer.timeout.connect(poll);timer.start(30)
 QTimer.singleShot(12000,lambda:app.exit(2));code=app.exec()
 for page in pages:page.deleteLater()
 app.processEvents();profile.deleteLater();app.processEvents()
 raise SystemExit(code)
'''
        result=subprocess.run([sys.executable,'-c',script],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('exact retry OK',result.stdout)

    def run_deadline_case(self, transport, checks):
        harness = r'''
const assert=require('node:assert/strict');
global.window=globalThis;global.location={href:'http://localhost/',origin:'http://localhost'};
let stamp=0,sequence=0;const timers=new Map(),calls=[];
global.performance={now:()=>stamp};
global.setTimeout=(fn,ms)=>{const id=++sequence;timers.set(id,{fn,at:stamp+ms});return id;};
global.clearTimeout=id=>timers.delete(id);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const advance=async ms=>{stamp+=ms;for(const [id,timer] of [...timers])if(timer.at<=stamp){timers.delete(id);timer.fn();}await tick();};
const post=(path,options={})=>fetch(path,{method:'POST',...options});
'''
        script = harness + transport + HTTP_UI_ADMISSION_JS + '\n(async()=>{' + checks + r'''
console.log('deadline checks OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node','-e',script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('deadline checks OK', result.stdout)

    def test_expired_and_cancelled_fifo_entries_never_send_or_retain_capacity(self):
        self.run_deadline_case(r'''
const controls=new Map();
global.fetch=async(path,options)=>{calls.push([path,options]);return new Response(new ReadableStream({start(c){controls.set(path,c);}}));};
''', r'''
const first=await post('/v1/held');
for(let round=0;round<4;round++){
 const waiting=Array.from({length:63},(_,i)=>post('/v1/expired-'+round+'-'+i).catch(e=>e));
 await assert.rejects(post('/v1/full'),{name:'QuotaExceededError',outcome:'not-started'});
 let inspected=0;const body={toString(){inspected++;return '{}';}};
 await assert.rejects(post('/v1/projects/open',{body}),{name:'QuotaExceededError',outcome:'not-started'});
 assert.equal(inspected,0,'Full queue decoded a rejected body');
 await advance(5001);
 for(const error of await Promise.all(waiting))assert.equal(error.outcome,'not-started');
 assert.equal(calls.length,1);assert.equal(timers.size,0);
}
const controller=new AbortController();
const cancelled=post('/v1/cancelled',{signal:controller.signal}).catch(e=>e);
controller.abort('explicit caller reason');const error=await cancelled;
assert.equal(error.outcome,'not-started');assert.equal(error.cause,'explicit caller reason');
const expiredLate=post('/v1/delayed-timer').catch(e=>e);stamp+=5001;
controls.get('/v1/held').close();await first.text();
assert.equal((await expiredLate).outcome,'not-started','Throttled timer permitted late dispatch');
const body='{"operation_id":"fixed-original-operation"}',sent=await post('/v1/retry',{body});
assert.deepEqual(calls.map(v=>v[0]),['/v1/held','/v1/retry']);assert.equal(calls[1][1].body,body);
controls.get('/v1/retry').close();await sent.text();await tick();assert.equal(timers.size,0);
''')

    def test_web_lock_wait_has_same_deadline_and_no_late_dispatch(self):
        self.run_deadline_case(r'''
let parked;
Object.defineProperty(globalThis,'navigator',{configurable:true,value:{locks:{request(name,options,callback){return new Promise((resolve,reject)=>{
 parked={name,callback};options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});
});}}}});
global.fetch=async(path,options)=>{calls.push(path);return new Response('{}');};
''', r'''
const waiting=post('/v1/waiting').catch(e=>e);await tick();
assert.equal(parked.name,'fpw-http-application');await advance(5001);
const error=await waiting;assert.equal(error.name,'TimeoutError');assert.equal(error.phase,'admission');
assert.equal(error.outcome,'not-started');assert.equal(error.dispatched,false);
await assert.rejects(parked.callback());assert.equal(calls.length,0);
navigator.locks.request=()=>{throw new DOMException('denied','SecurityError');};
await assert.rejects(post('/v1/denied'),{name:'SecurityError',outcome:'not-started'});
navigator.locks.request=async(name,options,callback)=>callback();
const response=await post('/v1/after');await response.text();await tick();
assert.deepEqual(calls,['/v1/after']);assert.equal(timers.size,0);
''')

    def test_abort_after_send_is_unknown_and_does_not_release_owner_early(self):
        self.run_deadline_case(r'''
let deliver,body;
global.fetch=async(path,options)=>{calls.push([path,options]);
 if(calls.length===1)return new Promise(resolve=>{deliver=resolve;});
 return new Response('{}');
};
''', r'''
const controller=new AbortController(),original='{"operation_id":"original-id"}';
const sent=post('/v1/sent',{signal:controller.signal,body:original}).catch(e=>e);await tick();
assert.equal(calls.length,1);controller.abort();const error=await sent;
assert.equal(error.outcome,'unknown');assert.equal(error.dispatched,true);
const waiting=post('/v1/must-not-overlap').catch(e=>e);await advance(5001);
assert.equal((await waiting).outcome,'not-started');assert.equal(calls.length,1);
deliver(new Response(new ReadableStream({start(c){body=c;}})));await tick();
const after=post('/v1/after');await tick();assert.equal(calls.length,1,'Headers released uncertain owner');
body.close();const response=await after;await response.text();await tick();
assert.deepEqual(calls.map(v=>v[0]),['/v1/sent','/v1/after']);assert.equal(calls[0][1].body,original);
assert.equal(timers.size,0);
''')

    def test_stream_queue_does_not_hold_settings_and_preserves_provider_order(self):
        script = r'''
const assert=require('node:assert/strict');
global.window=globalThis;global.location={href:'http://localhost/',origin:'http://localhost'};
const sent=[],controllers=new Map();
global.fetch=async(path,options)=>{const body=JSON.parse(options.body),key=path+':'+(body.action||'');sent.push(key);return new Response(new ReadableStream({start(c){controllers.set(key,c);}}));};
'''+HTTP_UI_ADMISSION_JS+r'''
(async()=>{
 const post=(path,body={})=>fetch(path,{method:'POST',body:JSON.stringify(body)});
 const stream=await post('/v1/chat/send-stream');
 const mutation=post('/v1/administration',{action:'create-user'});
 const recovery=post('/v1/chat/status');
 const settings=await post('/v1/administration',{action:'list'});
 const independent=await post('/v1/user-profile',{action:'load'});
 const control=await post('/v1/tasks/run-control',{action:'stop'});
 assert(!sent.includes('/v1/administration:create-user'),'Mutation bypassed active stream');
 assert(!sent.includes('/v1/chat/status:'),'Recovery bypassed active stream');
 for(const key of ['/v1/administration:list','/v1/user-profile:load','/v1/tasks/run-control:stop'])assert(sent.includes(key),'Independent request held behind stream: '+key);
 const end=key=>{const c=controllers.get(key);c.enqueue(new TextEncoder().encode('{}'));c.close();};
 end('/v1/chat/send-stream:');await stream.text();
 const changed=await mutation;assert(!sent.includes('/v1/chat/status:'));end('/v1/administration:create-user');await changed.text();
 const recovered=await recovery;end('/v1/chat/status:');await recovered.text();
 end('/v1/administration:list');end('/v1/user-profile:load');end('/v1/tasks/run-control:stop');
 await Promise.all([settings.text(),independent.text(),control.text()]);console.log('provider ordering OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('provider ordering OK', result.stdout)

    def test_julia_queue_is_independent_and_retains_ownership_until_eof(self):
        script = r'''
const assert=require('node:assert/strict');
global.window=globalThis;global.location={href:'http://localhost/',origin:'http://localhost'};
const sent=[],controllers=new Map();
global.fetch=async(path)=>{sent.push(path);return new Response(new ReadableStream({start(c){controllers.set(path,c);}}));};
'''+HTTP_UI_ADMISSION_JS+r'''
(async()=>{
 const post=path=>fetch(path,{method:'POST',body:'{}'});
 const julia=await post('/v1/julia/definitions');
 const cancel=post('/v1/julia/cancel');
 const reconcile=post('/v1/julia/reconcile');
 const application=await post('/v1/counter');
 const provider=await post('/v1/chat/status');
 assert(!sent.includes('/v1/julia/cancel'));
 assert(!sent.includes('/v1/julia/reconcile'));
 const end=path=>{const c=controllers.get(path);c.enqueue(new TextEncoder().encode('{}'));c.close();};
 end('/v1/julia/definitions');await julia.text();
 const cancelled=await cancel;assert(!sent.includes('/v1/julia/reconcile'));
 end('/v1/julia/cancel');await cancelled.text();
 const reconciled=await reconcile;end('/v1/julia/reconcile');await reconciled.text();
 end('/v1/counter');end('/v1/chat/status');await Promise.all([application.text(),provider.text()]);
 console.log('Julia domain EOF ownership OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('Julia domain EOF ownership OK', result.stdout)

    def test_monitoring_and_public_rss_have_independent_fifo_eof_owners(self):
        script = r'''
const assert=require('node:assert/strict');
global.window=globalThis;global.location={href:'http://localhost/',origin:'http://localhost'};
const sent=[],controllers=new Map();
global.fetch=async(path)=>{sent.push(path);return new Response(new ReadableStream({start(c){controllers.set(path,c);}}));};
'''+HTTP_UI_ADMISSION_JS+r'''
(async()=>{
 const post=path=>fetch(path,{method:'POST',body:JSON.stringify({project_id:'11111111-1111-4111-8111-111111111111'})});
 const monitoring=await post('/v1/monitoring/block-process');
 const status=post('/v1/monitoring/view');
 const publish=post('/v1/monitoring/block-publish');
 const rss=await post('/v1/rss-sources/refresh');
 const rssView=post('/v1/rss-sources/view');
 const others=[];
 for(const path of ['/v1/counter','/v1/projects/open','/v1/chat/status','/v1/julia/status'])others.push([path,await post(path)]);
 for(const path of ['/v1/monitoring/view','/v1/monitoring/block-publish','/v1/rss-sources/view'])assert(!sent.includes(path),'Owner bypassed: '+path);
 const end=path=>{const c=controllers.get(path);c.enqueue(new TextEncoder().encode('{}'));c.close();};
 end('/v1/monitoring/block-process');await monitoring.text();
 const viewed=await status;assert(!sent.includes('/v1/monitoring/block-publish'));
 end('/v1/monitoring/view');await viewed.text();
 const published=await publish;end('/v1/monitoring/block-publish');await published.text();
 assert(!sent.includes('/v1/rss-sources/view'));
 end('/v1/rss-sources/refresh');await rss.text();
 const refreshed=await rssView;end('/v1/rss-sources/view');await refreshed.text();
 for(const [path,response] of others){end(path);await response.text();}
 console.log('monitoring and public RSS domains OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('monitoring and public RSS domains OK', result.stdout)

    def test_project_queues_share_nested_scope_and_bound_total_waiters(self):
        script = r'''
const assert=require('node:assert/strict');
global.window=globalThis;global.location={href:'http://localhost/',origin:'http://localhost'};
const sent=[],controllers=[];
global.fetch=async(path,options)=>{sent.push([path,JSON.parse(options.body)]);return new Response(new ReadableStream({start(c){controllers.push(c);}}));};
'''+HTTP_UI_ADMISSION_JS+r'''
(async()=>{
 const a='11111111-1111-4111-8111-111111111111',b='22222222-2222-4222-8222-222222222222';
 const post=(path,body)=>fetch(path,{method:'POST',body:JSON.stringify(body)});
 const save=await post('/v1/artifacts/editor/save',{document:{project_id:a}});
 const waiting=post('/v1/projects/open',{project_id:a});
 const other=await post('/v1/projects/open',{project_id:b});
 assert.equal(sent.length,2,'Independent project was serialized or same-project read bypassed its writer');
 assert.equal(sent[1][1].project_id,b);
 controllers[0].enqueue(new TextEncoder().encode('{}'));controllers[0].close();await save.text();
 const opened=await waiting;assert.equal(sent.length,3);
 for(const c of controllers.slice(1)){c.enqueue(new TextEncoder().encode('{}'));c.close();}
 await opened.text();await other.text();await new Promise(r=>setTimeout(r,20));
 const promises=[];
 for(let i=0;i<64;i++)promises.push(post('/v1/projects/open',{project_id:i.toString(16).padStart(8,'0')+'-3333-4333-8333-333333333333'}));
 await assert.rejects(post('/v1/projects/open',{project_id:a}),{name:'QuotaExceededError'});
 await Promise.all(promises);
 for(const c of controllers.slice(3)){c.enqueue(new TextEncoder().encode('{}'));c.close();}
 console.log('project queue ownership OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('project queue ownership OK', result.stdout)

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
entered=threading.Event();finished=threading.Event();catalog_during=[];admin_during=[]
class Fixture(Handler):
 reserve_ui_worker=True
 post_paths={'/v1/chat/test','/v1/chat/send','/v1/projects','/v1/administration'}
 def _do_GET(self):
  raw=b'<!doctype html><title>Admission fixture</title>'
  self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def dispatch(self,request):
  if self.path=='/v1/chat/test':
   entered.set();time.sleep(1.2);finished.set()
  elif self.path=='/v1/projects':catalog_during.append(not finished.is_set())
  elif self.path=='/v1/administration':admin_during.append(not finished.is_set())
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
  pages[1].runJavaScript("fetch('/v1/administration',{..."+options+",body:JSON.stringify({action:'list'})}).then(r=>results.push(['/v1/administration',r.status]));")
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
    if len(a)!=1 or len(b)!=3:return
    if a!=[['slow',200]] or sorted(b)!=[['/v1/administration',200],['/v1/chat/send',200],['/v1/projects',200]] or catalog_during!=[True] or admin_during!=[True]:
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
 const scope={URL,DOMException,Promise,AbortController,setTimeout,clearTimeout,location:{href:'http://localhost/',origin:'http://localhost'},
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
 const projectRead=await post('/v1/artifacts/preview');
 const opening=post('/v1/projects/open');
 await new Promise(resolve=>setTimeout(resolve,25));
 assert(!calls.includes('/v1/projects/open'));
 end('/v1/a');await first.text();
 const second=await b;assert(!calls.includes('/v1/cancelled'));
 end('/v1/b');await second.text();
 end('/v1/artifacts/preview');await projectRead.text();
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
