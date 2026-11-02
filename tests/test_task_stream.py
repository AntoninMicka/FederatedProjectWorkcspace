# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import socket
import threading
import time
import unittest
from uuid import uuid4

from spikes.task_stream import RunDeadline, registered, decide
from spikes.ollama_backend import OllamaAdapter, OllamaRuns, UnknownRun
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from tests import test_task_file_edit as fixtures
from tests import test_local_api as local_api
from tests.fixtures import ENTITY


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.events=[]
        self.control=RunDeadline(self.events.append, soft=10, clock=lambda:self.now)
        self.control.started=0
        self.addCleanup(self.control.close)

    def test_soft_is_advisory_and_default_hard_is_twice_soft(self):
        for current in [0,10,19.999]:
            self.now=current; self.control.tick()
            self.assertIsNone(self.control.reason)
        self.assertEqual(20,self.events[-1]['hard_seconds'])
        self.now=20;self.control.tick()
        self.assertEqual('hard-timeout',self.control.reason)
        with self.assertRaises(ValueError):self.control.extend()

    def test_extension_is_absolute_ten_times_not_sliding_or_repeatable(self):
        self.now=19;self.control.extend()
        self.now=99;self.control.extend();self.control.tick()
        self.assertIsNone(self.control.reason)
        self.assertEqual(100,self.control.snapshot()['hard_seconds'])
        self.now=100;self.control.tick()
        self.assertEqual('hard-timeout',self.control.reason)

    def test_valid_completion_ends_deadline_and_rejects_late_extension(self):
        self.now=19;self.control.complete()
        self.now=1000;self.control.tick();self.control.stop()
        self.assertIsNone(self.control.reason)
        self.assertTrue(self.control.finished)
        with self.assertRaises(ValueError):self.control.extend()

    def test_cancel_interrupts_attached_socket_and_stays_stopped(self):
        local,remote=socket.socketpair();self.addCleanup(local.close);self.addCleanup(remote.close)
        self.control.attach(local);self.control.stop()
        self.assertEqual(b'',remote.recv(1))
        self.control.stop('hard-timeout');self.assertEqual('user-stopped',self.control.reason)
        with self.assertRaises(ValueError):self.control.check()
        with self.assertRaises(ValueError):self.control.extend()


class StreamTaskTests(unittest.TestCase):
    setUp=fixtures.FileEditTests.setUp
    request=fixtures.FileEditTests.request
    pin_run_choice=fixtures.FileEditTests.pin_run_choice
    route_request=fixtures.FileEditTests.route_request
    create_document=fixtures.FileEditTests.create_document
    generate=fixtures.FileEditTests.generate

    def stream_service(self, transport=None):
        service,request,calls=self.generate()
        def stream(binding,raw,delta,status,*,control):
            status('generating');delta('{"schema_version":1,')
            if transport:return transport(binding,raw,delta,status,control)
            value=dict(schema_version=1,kind='artifact-draft',artifact_kind='document',title='Selected document',content='Streamed proposal\n')
            return dict(model=binding.model,response=json.dumps(value),done=True)
        service.adapter_factory=lambda runs:OllamaAdapter(runs,stream_transport=stream)
        return service,request

    def test_streamed_edit_remains_proposal_and_never_writes_project(self):
        service,request=self.stream_service();head=self.git.head();deltas=[];events=[]
        with registered(service,request,events.append) as control:
            result=service.task_route(request,on_delta=deltas.append,on_status=lambda _:None,control=control)
        self.assertEqual(head,self.git.head());self.assertTrue(deltas)
        self.assertEqual('prepared',result['projection']['state'])
        self.assertEqual('Streamed proposal\n',result['projection']['outcome']['content'])
        self.assertFalse(service.task_stream_controls)
        self.assertTrue(OllamaRuns(self.chat_state).get(request['run_id'])['response'])

    def test_provider_frame_limit_keeps_its_diagnostic_and_never_redispatches(self):
        from spikes.ollama_backend import OllamaResponseError
        calls=[]
        def oversized(binding,raw,delta,status,control):
            calls.append(raw)
            raise OllamaResponseError('Ollama stream frame exceeds 1 MiB', code='stream-frame-too-large')
        service,request=self.stream_service(oversized);head=self.git.head()
        with running_api('http',handler=DesktopHandler) as server:
            server.chat_service=service;server.projects=service.projects
            driver=local_api.LocalAPITests()
            for _ in range(2):
                response=driver.request(server,path='/v1/tasks/route-stream',body=json.dumps(request).encode())
                events=[json.loads(line) for line in response.split(b'\r\n\r\n',1)[1].splitlines()]
                error=next(event for event in events if event['type']=='error')
                self.assertEqual('stream-frame-too-large',error['diagnostic'])
                self.assertEqual('provider-error',error['outcome'])
                self.assertIn('příliš velký rámec',error['error'])
                self.assertNotIn('Průběžný výsledek',error['error'])
        self.assertEqual(1,len(calls))
        self.assertEqual(head,self.git.head())
        self.assertEqual([],service.task_outcomes(project_id=ENTITY))
        self.assertEqual('failed',OllamaRuns(self.chat_state).get(request['run_id'])['state'])

    def test_control_is_owner_project_scoped_and_released_after_run(self):
        service,request=self.stream_service()
        payload={k:request[k] for k in ('project_id','run_id')};payload['action']='extend'
        with registered(service,request,lambda _:None) as control:
            control.start()
            with service.as_user(str(uuid4()),project_ids=[ENTITY],writable_project_ids=[ENTITY]):
                with self.assertRaises(ValueError):decide(service,payload)
            with service.as_user(service._identity()[1],project_ids=[ENTITY],writable_project_ids=[]):
                with self.assertRaises(ValueError):decide(service,payload)
            with self.assertRaises(ValueError):decide(service,payload|{'project_id':str(uuid4())})
            self.assertTrue(decide(service,payload)['extended'])
            self.assertEqual('user-stopped',decide(service,payload|{'action':'stop'})['stopped'])
        with self.assertRaises(ValueError):decide(service,payload)

    def test_hard_timeout_is_durable_unknown_and_cannot_redispatch(self):
        def blocked(binding,raw,delta,status,control):
            control.stop('hard-timeout');control.check()
        service,request=self.stream_service(blocked);head=self.git.head()
        with registered(service,request,lambda _:None) as control:
            with self.assertRaises(UnknownRun):service.task_route(request,on_delta=lambda _:None,on_status=lambda _:None,control=control)
        self.assertEqual('unknown',OllamaRuns(self.chat_state).get(request['run_id'])['state'])
        self.assertEqual('hard-timeout',OllamaRuns(self.chat_state).get(request['run_id'])['error_code'])
        with registered(service,request,lambda _:None) as control:
            with self.assertRaises(UnknownRun):service.task_route(request,on_delta=lambda _:None,on_status=lambda _:None,control=control)
        self.assertEqual(head,self.git.head())

    def test_http_stop_bypasses_busy_application_lane_and_has_terminal_stream_event(self):
        entered=threading.Event()
        def blocked(binding,raw,delta,status,control):
            entered.set()
            deadline=time.monotonic()+3
            while control.reason is None and time.monotonic()<deadline:time.sleep(.005)
            control.check()
        service,request=self.stream_service(blocked)
        driver=local_api.LocalAPITests();responses=[]
        with running_api('http',handler=DesktopHandler) as server:
            server.chat_service=service;server.projects=service.projects
            thread=threading.Thread(target=lambda:responses.append(driver.request(server,path='/v1/tasks/route-stream',body=json.dumps(request).encode())))
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                response=driver.request(server,path='/v1/tasks/run-control',body=json.dumps(dict(project_id=ENTITY,run_id=request['run_id'],action='stop')).encode())
                self.assertIn(b' 200 ',response.split(b'\r\n',1)[0])
            finally:
                thread.join(4)
            self.assertFalse(thread.is_alive())
        self.assertIn(b'"type": "delta"',responses[0])
        self.assertIn(b'"type": "error"',responses[0])
        self.assertIn(b'user-stopped',responses[0])

    def test_real_upstream_without_first_token_is_interrupted_at_hard_deadline(self):
        from dataclasses import replace
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from spikes.ollama_backend import _OllamaTransportUnknown
        from tests import test_ollama_backend
        release=threading.Event()
        class Slow(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                release.wait(3)
            def log_message(self,*args):pass
        upstream=ThreadingHTTPServer(('127.0.0.1',0),Slow)
        thread=threading.Thread(target=upstream.serve_forever,daemon=True);thread.start()
        binding=test_ollama_backend.OllamaBinding.parse(test_ollama_backend.OllamaBindingTests().binding())
        binding=replace(binding,endpoint='http://127.0.0.1:'+str(upstream.server_port))
        control=RunDeadline(lambda _:None,soft=.05)
        try:
            control.start();started=time.monotonic()
            with self.assertRaises(_OllamaTransportUnknown):
                OllamaAdapter._http_stream_transport(binding,b'{}',lambda _:None,lambda _:None,control=control)
            self.assertLess(time.monotonic()-started,1)
            self.assertEqual('hard-timeout',control.reason)
        finally:
            control.close();release.set();upstream.shutdown();upstream.server_close();thread.join()

    def test_https_deadline_decisions_require_current_writer_and_exact_owner(self):
        from tests import test_web_server
        web=test_web_server.WebTests();web.setUp()
        try:
            def post(path,payload,key=None):
                code,data,_=web.request(path=path,body=json.dumps(payload),headers={'Authorization':'Bearer '+key} if key else None)
                return code,json.loads(data) if code==200 else data
            code,raw,_=web.create_project('Isolated deadline authority');self.assertEqual(200,code)
            project=json.loads(raw)['id']
            code,state=post('/v1/administration',{'action':'list'});self.assertEqual(200,code)
            accounts=[]
            for name,role in [('Owner','editor'),('Reader','reader')]:
                code,state=post('/v1/administration',dict(action='create-user',expected_commit=state['commit_id'],name=name,node_role='member'));self.assertEqual(200,code)
                account=next(u for u in state['users'] if u['name']==name);access=state['access_key']
                code,state=post('/v1/administration',dict(action='update-user',expected_commit=state['commit_id'],user_id=account['id'],active=True,node_role='member',memberships={project:role}));self.assertEqual(200,code)
                accounts.append((account,access))
            service=web.server.chat_service;owner,access=accounts[0];run=str(uuid4());request=dict(project_id=project,run_id=run)
            with service.as_user(owner['id'],project_ids=[project],writable_project_ids=[project]), registered(service,request,lambda _:None) as control:
                control.start()
                for path in ['/v1/tasks/route-stream','/v1/tasks/run-control']:
                    self.assertEqual(403,post(path,request|{'action':'extend'},accounts[1][1])[0])
                self.assertEqual(422,post('/v1/tasks/run-control',request|{'action':'extend'})[0])
                code,result=post('/v1/tasks/run-control',request|{'action':'extend'},access)
                self.assertEqual(200,code);self.assertTrue(result['extended'])
                code,result=post('/v1/tasks/run-control',request|{'action':'stop'},access)
                self.assertEqual(200,code);self.assertEqual('user-stopped',result['stopped'])
        finally:web.doCleanups()
