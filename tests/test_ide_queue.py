# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import base64
from pathlib import Path
import subprocess
import unittest
from uuid import uuid4
from unittest.mock import patch

from spikes.artifacts import Artifacts
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_queue import TaskQueue
from spikes.ide_queue import (build_hierarchy, digest, hierarchy_problems, load, publish,
                              read_document, refresh, status)
from tests import test_ide_bridge_panel as panel_tests


class QueuePacketTests(unittest.TestCase):
    def setUp(self):
        panel_tests.BridgePanelTests.setUp(self)
        self.body = '- [ ] [TASK-01] First\n- [ ] [TASK-02] Second\n  - depends_on: TASK-01\n- [ ] [TASK-03] Third\n  - depends_on: TASK-02\n'
        self.head = self.save(self.body)
        self.record = panel_tests.BridgePanelTests.session(self)
        self.owner = ProjectCreation(self.node).author_id(); self.queue = TaskQueue(self.node)
        for task in ['TASK-01','TASK-02','TASK-03']: self.act('add',task)
        self.request = dict(project_id=self.project,session_id=self.record['session_id'],expected_head=self.head,
                            queue_revision=self.qstatus()['revision'],repository_commit='a'*40)

    save = panel_tests.BridgePanelTests.save
    def qstatus(self): return self.queue.execute(dict(project_id=self.project,action='status'),self.owner)
    def act(self,action,task=None,**extra):
        view=self.qstatus();request=dict(project_id=self.project,action=action,revision=view['revision'],expected_head=view['expected_head'])
        if task:request['task_id']=task
        return self.queue.execute(request|extra,self.owner)
    def packet(self):
        result=publish(self.service,None,self.request);return load(self.service,self.record['session_id'],result['packet_id'])
    def http_publish(self, request):
        import urllib.request, urllib.error
        from spikes.local_api import running_api
        from spikes.desktop_ui import DesktopHandler
        with running_api('http',handler=DesktopHandler,projects=Projects(self.node)) as server:
            call=urllib.request.Request(server.origin+'/v1/ide-queue/publish',
                data=json.dumps(request).encode(),headers={
                    'Authorization':'Bearer '+server.token,'Content-Type':'application/json'})
            try:
                with urllib.request.urlopen(call,timeout=20) as response:
                    return response.status,json.load(response)
            except urllib.error.HTTPError as error:
                with error:
                    return error.code,json.load(error)

    def test_plan_scope_http_avoids_full_open_and_omits_history_and_artifact_catalog(self):
        import urllib.request
        from spikes.local_api import running_api
        from spikes.desktop_ui import DesktopHandler
        with running_api('http',handler=DesktopHandler,projects=Projects(self.node)) as server:
            call=urllib.request.Request(server.origin+'/v1/projects/open',
                data=json.dumps(dict(project_id=self.project,scope='plan')).encode(),headers={
                    'Authorization':'Bearer '+server.token,'Content-Type':'application/json'})
            with patch.object(Projects,'open',side_effect=AssertionError('full project reload')):
                with urllib.request.urlopen(call,timeout=20) as response:
                    result=json.load(response)
        self.assertEqual(result['commit_id'],self.head)
        self.assertEqual(result['plan']['status'],'ready')
        self.assertNotIn('history',result);self.assertNotIn('artifacts',result)

    def test_http_publish_refreshes_existing_bound_mapping_without_reconfiguration(self):
        self.head=self.save(self.body+'- [ ] [TASK-04] New unrelated task\n')
        request=self.request|dict(expected_head=self.head,queue_revision=self.qstatus()['revision'])
        code,result=self.http_publish(request)
        self.assertEqual(code,200,result)
        packet=load(self.service,self.record['session_id'],result['packet_id'])
        self.assertEqual(packet['manifest']['project_head'],self.head)
        self.assertEqual(packet['manifest']['session_id'],self.record['session_id'])
        self.assertEqual(Projects(self.node).repository(self.project).head(),self.head)

    def test_http_publish_never_refreshes_over_pending_human_review(self):
        packet=self.packet();self.send(self.message(packet))
        self.head=self.save(self.body+'- [ ] [TASK-04] New unrelated task\n')
        request=self.request|dict(expected_head=self.head,queue_revision=self.qstatus()['revision'])
        code,result=self.http_publish(request)
        self.assertEqual(code,422,result)
        self.assertIn('human review',result['error'])
        self.assertEqual(load(self.service,self.record['session_id'])['packet_id'],packet['packet_id'])
        self.assertEqual(Projects(self.node).repository(self.project).head(),self.head)
    def message(self,packet,task='TASK-01'):
        return dict(message_id=str(uuid4()),task_id=task,kind='completed',body='Implemented and inspected.',
            revision=self.record['snapshot']['revision'],repository_commit='b'*40,queue_packet_id=packet['packet_id'],
            reported_by='agent',evidence=dict(tests='Focused test suite passed',diff='commit '+('b'*40)))
    def send(self,m):return self.service.exchange(self.record,dict(session_id=self.record['session_id'],messages=[m]))
    def review(self,m,**changes):
        request=dict(project_id=self.project,session_id=self.record['session_id'],message_id=m['message_id'],
            decision='accepted',note='Human accepted evidence.',expected_head=Projects(self.node).repository(self.project).head(),operation_id=str(uuid4()))
        return self.service.review(None,request|changes)

    def test_start_gate_allows_resolved_and_one_running_but_never_completion(self):
        for first, second, allowed in [('resolved', 'resolved', True),
                                       ('resolved', 'in progress', True),
                                       ('in progress', 'in progress', False),
                                       ('resolved', 'planned', False),
                                       ('failed', 'resolved', False)]:
            with self.subTest(first=first, second=second):
                self.body = (f'- [ ] [TASK-01] A\n  - status: {first}\n'
                             f'- [ ] [TASK-02] B\n  - status: {second}\n'
                             '- [ ] [TASK-03] C\n  - depends_on: TASK-01, TASK-02\n')
                self.head = Projects(self.node).repository(self.project).head()
                self.head = self.save(self.body)
                self.record = panel_tests.BridgePanelTests.session(self)
                self.act('revalidate')
                self.request.update(session_id=self.record['session_id'], expected_head=self.head,
                                    queue_revision=self.qstatus()['revision'])
                packet = self.packet()
                item = status(self.service, self.record)['items'][2]
                self.assertEqual(allowed, item['startable'])
                self.assertFalse(item['eligible'])
                message = self.message(packet, 'TASK-03') | {'kind': 'progress'}
                message.pop('evidence')
                if allowed:
                    self.assertEqual('automatic-start', self.send(message)['receipts'][0]['acceptance'])
                    self.assertEqual('in progress', status(self.service, self.record)['items'][2]['status'])
                else:
                    with self.assertRaises(ValueError): self.send(message)
                with self.assertRaises(ValueError): self.send(self.message(packet, 'TASK-03'))

    def test_progress_then_completion_uses_same_packet_without_false_acceptance(self):
        packet = self.packet()
        progress = self.message(packet) | dict(kind='progress', body='Work started')
        progress.pop('evidence')
        with self.assertRaises(ValueError): self.send(progress | {'queue_packet_id': '0'*64})
        self.send(progress)  # accepted automatically, no human review
        first = status(self.service, self.record)['items'][0]
        self.assertFalse(first['agent_confirmed'])
        self.assertFalse(first['user_confirmed'])
        value = status(self.service, self.record)
        self.assertTrue(value['current'])
        self.assertEqual('in progress', value['items'][0]['status'])
        self.assertFalse(value['items'][0]['user_confirmed'])
        self.assertFalse(value['items'][1]['eligible'])
        self.assertTrue(self.qstatus()['valid'])
        self.assertFalse(self.qstatus()['items'][0]['agent_confirmed'])
        completed = self.message(packet)
        self.send(completed); self.review(completed)
        value = status(self.service, self.record)
        self.assertTrue(value['current'])
        self.assertTrue(value['items'][0]['user_confirmed'])
        self.assertTrue(value['items'][1]['eligible'])

    def test_manual_user_start_is_accepted_automatically_without_completion_request(self):
        packet = self.packet()
        # Same shape as the extension's queue.manualStart.
        start = dict(message_id=str(uuid4()), task_id='TASK-01', kind='progress', body='Zahájeno ručně z IDE.',
                     revision=self.record['snapshot']['revision'], repository_commit='b'*40,
                     queue_packet_id=packet['packet_id'], reported_by='user')
        with self.assertRaises(ValueError): self.send(start | dict(message_id=str(uuid4()), evidence=dict(tests='x', diff='y')))
        with self.assertRaises(ValueError): self.send(start | dict(message_id=str(uuid4()), task_id='TASK-02', body='Blocked start'))
        receipt = self.send(start)['receipts'][0]
        self.assertEqual(('received', 'automatic-start'), (receipt['status'], receipt['acceptance']))
        self.assertNotEqual(self.head, Projects(self.node).repository(self.project).head())
        with self.assertRaisesRegex(ValueError, 'another decision'): self.review(start)
        item = status(self.service, self.record)['items'][0]
        self.assertEqual('in progress', item['status'])
        self.assertFalse(item['user_requested']); self.assertFalse(item['user_confirmed']); self.assertTrue(item['eligible'])
        request = start | dict(message_id=str(uuid4()), kind='completed', body='Hotovo', checklist=None)
        request.pop('checklist')
        self.send(request)
        self.assertTrue(status(self.service, self.record)['items'][0]['user_requested'])

    def test_chain_agent_then_human_then_following_and_receipt_flags(self):
        packet=self.packet(); self.assertEqual(packet,self.packet()); old=packet.copy()
        self.assertEqual([True,False,False],[i['eligible'] for i in status(self.service,self.record)['items']])
        with self.assertRaises(ValueError):self.send(self.message(packet,'TASK-02'))
        m=self.message(packet);first=self.send(m);self.assertEqual(first['receipts'],self.send(m)['receipts'])
        self.assertEqual(self.head,Projects(self.node).repository(self.project).head())
        self.assertFalse(status(self.service,self.record)['items'][1]['eligible'])
        self.assertTrue(self.qstatus()['items'][0]['agent_confirmed']);self.assertFalse(self.qstatus()['items'][0]['user_confirmed'])
        r=self.review(m);head=r['result']['commit_id'];self.assertNotEqual(self.head,head)
        self.assertEqual(r,self.service.review(None,r['request']))
        self.assertTrue(self.qstatus()['valid']);self.assertTrue(self.qstatus()['items'][0]['user_confirmed'])
        self.assertTrue(status(self.service,self.record)['items'][1]['eligible'])
        second=self.message(packet,'TASK-02');self.send(second);self.review(second)
        third=self.message(packet,'TASK-03');self.send(third);self.review(third)
        self.assertTrue(all(i['user_confirmed'] for i in status(self.service,self.record)['items']))
        self.assertEqual(old,load(self.service,self.record['session_id']))

    def manual(self,packet,task='TASK-01',**changes):
        value=self.message(packet,task);value.pop('evidence');value['reported_by']='user'
        return value|changes

    def test_manual_request_is_distinct_and_never_accepts_by_itself(self):
        packet=self.packet()
        with self.assertRaises(ValueError):self.send(self.manual(packet,evidence=dict(tests='x',diff='y')))
        with self.assertRaises(ValueError):self.send(self.manual(packet,reported_by='robot'))
        with self.assertRaises(ValueError):self.send(self.manual(packet,'TASK-02'))
        m=self.manual(packet);self.send(m)
        item=status(self.service,self.record)['items'][0]
        self.assertTrue(item['user_requested']);self.assertFalse(item['agent_confirmed']);self.assertFalse(item['user_confirmed'])
        self.assertEqual(self.head,Projects(self.node).repository(self.project).head())
        self.assertFalse(self.qstatus()['items'][0]['user_confirmed'])
        self.assertTrue(self.qstatus()['items'][0]['user_requested'])
        rejected=self.review(m,decision='rejected',note='Not done.')
        self.assertEqual('rejected',rejected['outcome'])
        self.assertEqual(self.head,Projects(self.node).repository(self.project).head())
        self.assertFalse(status(self.service,self.record)['items'][0]['user_confirmed'])
        again=self.manual(packet);self.send(again);accepted=self.review(again)
        self.assertNotEqual(self.head,accepted['result']['commit_id'])
        self.assertTrue(status(self.service,self.record)['items'][0]['user_confirmed'])

    def test_queue_lists_completion_reports_under_their_item(self):
        packet=self.packet();self.assertEqual([],self.qstatus()['items'][0]['reports'])
        m=self.message(packet);self.send(m)
        items=self.qstatus()['items'];report=items[0]['reports'][0]
        self.assertEqual((m['message_id'],'agent',None,None),(report['message_id'],report['reported_by'],report['outcome'],report['note']))
        self.assertEqual(m['body'],report['body']);self.assertEqual([],items[1]['reports'])
        self.review(m,decision='rejected',note='Chybí důkaz.')
        report=self.qstatus()['items'][0]['reports'][0]
        self.assertEqual(('rejected','Chybí důkaz.'),(report['outcome'],report['note']))
        again=self.manual(packet);self.send(again)
        self.assertEqual(['user','agent'],[r['reported_by'] for r in self.qstatus()['items'][0]['reports']])

    def test_queue_report_acceptability_follows_the_review_rules(self):
        packet=self.packet();m=self.message(packet);self.send(m)
        report=self.qstatus()['items'][0]['reports'][0]
        self.assertTrue(report['acceptable']);self.assertEqual(self.record['session_id'],report['session_id'])
        self.assertEqual(m['evidence'],report['evidence']);self.assertIsNone(report['review_request'])
        self.act('set-flag','TASK-03',flag='held',value=True)
        self.assertFalse(self.qstatus()['items'][0]['reports'][0]['acceptable'],'superseded generation')
        with self.assertRaises(ValueError):self.review(m)
        self.act('set-flag','TASK-03',flag='held',value=False)

    def test_accepting_from_queue_completes_only_that_task(self):
        packet=self.packet();m=self.message(packet);self.send(m)
        report=self.qstatus()['items'][0]['reports'][0]
        result=self.review(m,session_id=report['session_id'],message_id=report['message_id'])
        self.assertEqual('accepted',result['outcome'])
        items=self.qstatus()['items']
        self.assertTrue(items[0]['user_confirmed']);self.assertFalse(items[1]['user_confirmed'])
        self.assertEqual('accepted',items[0]['reports'][0]['outcome']);self.assertFalse(items[0]['reports'][0]['acceptable'])

    def test_batch_row_lists_reports_of_its_linked_tasks(self):
        packet=self.batch_queue();m=self.message(packet,'BATCH-01-A');self.send(m)
        report=self.qstatus()['items'][0]['reports'][0]
        self.assertEqual('BATCH-01-A',report['task_id']);self.assertTrue(report['acceptable'])

    def test_queue_review_button_logic(self):
        import shutil
        from spikes.desktop_ui import JS
        if not shutil.which('node'):self.skipTest('Node required')
        start=JS.index('async function reviewQueueReport(');end=JS.index('async function loadTaskQueue(){')
        install=JS[JS.index('function installTaskPlanViews('):JS.index('function renderTaskPlanSidebar(')]
        harness=r"""
const assert=require('node:assert/strict');
const crypto={randomUUID:()=>'op'};let confirmed=true,noted='',calls=[],fail=false,loaded=0,plans=0;
const window={prompt:()=>noted,confirm:()=>confirmed};
let taskQueueBusy=false,taskQueueView={expected_head:'h1'},taskQueueMessage='';let activeProject={id:'p',head:'h1',readOnly:false};
const queueIsCurrent=()=>true,renderTaskQueue=()=>{},renderTaskPlanSidebar=()=>{plans++;},loadTaskQueue=async()=>{loaded++;};
async function projectRequest(path,body){if(path==='/v1/projects/open')return {commit_id:'h2',plan:{}};calls.push(body);if(fail)throw Error('stale');return body.decision==='rejected'?{result:null}:{result:{commit_id:'h2'}};}
"""
        checks=r"""
(async()=>{
 const report={task_id:'T',body:'b',session_id:'s',message_id:'m',review_request:null};
 confirmed=false;await reviewQueueReport(report,'accepted');assert.equal(calls.length,0,'cancel sends nothing');
 noted=null;confirmed=true;await reviewQueueReport(report,'accepted');assert.equal(calls.length,0,'dismissed note sends nothing');
 noted='ok';await reviewQueueReport(report,'accepted');
 assert.deepEqual(calls[0],{project_id:'p',session_id:'s',message_id:'m',decision:'accepted',note:'ok',expected_head:'h1',operation_id:'op'});
 assert.equal(activeProject.head,'h2');assert.equal(plans,1);assert.equal(loaded,0);
 calls.length=0;await reviewQueueReport(report,'rejected');assert.equal(calls[0].decision,'rejected');assert.equal(plans,1,'rejection keeps the plan');assert.equal(loaded,1);
 const prepared={...report,review_request:{operation_id:'original'}};calls.length=0;window.prompt=()=>{throw Error('no prompt');};
 await reviewQueueReport(prepared,'resume');assert.deepEqual(calls[0],{operation_id:'original'});
 fail=true;await reviewQueueReport(prepared,'resume');assert.equal(taskQueueView,null);assert.match(taskQueueMessage,/stale/);assert.equal(taskQueueBusy,false);
})().catch(error=>{console.error(error);process.exit(1);});
"""
        result=subprocess.run(['node','-e',harness+install+JS[start:end]+checks],capture_output=True,text=True)
        self.assertEqual(0,result.returncode,result.stderr)

    def test_manual_request_from_stale_packet_is_refused(self):
        packet=self.packet()
        self.act('set-flag','TASK-03',flag='held',value=True)
        with self.assertRaises(ValueError):self.send(self.manual(packet))

    def test_held_flag_is_audited_guarded_and_blocks_only_the_handoff(self):
        before=self.qstatus()
        result=self.act('set-flag','TASK-01',flag='held',value=True)
        self.assertEqual(before['revision']+1,result['revision'])
        self.assertTrue(result['items'][0]['held']);self.assertEqual(['held'],result['editable_flags'])
        audit=result['flag_audit'][-1]
        self.assertEqual(('TASK-01','held',False,True,self.owner,result['revision']),
            (audit['task_id'],audit['flag'],audit['old'],audit['new'],audit['actor_id'],audit['revision']))
        self.assertEqual(result['revision'],self.act('set-flag','TASK-01',flag='held',value=True)['revision'],'no-op')
        for flag in ('user_confirmed','agent_confirmed','eligible','user_requested'):
            with self.subTest(flag=flag),self.assertRaisesRegex(ValueError,'nelze'):
                self.act('set-flag','TASK-01',flag=flag,value=True)
        with self.assertRaises(ValueError):self.act('set-flag','TASK-01',flag='held',value='yes')
        with self.assertRaises(ValueError):self.act('set-flag','MISSING-01',flag='held',value=True)
        with self.assertRaisesRegex(ValueError,'změnila'):
            self.queue.execute(dict(project_id=self.project,action='set-flag',task_id='TASK-01',flag='held',value=False,
                revision=before['revision'],expected_head=before['expected_head']),self.owner)
        self.assertEqual(self.head,Projects(self.node).repository(self.project).head())
        self.request['queue_revision']=self.qstatus()['revision'];packet=self.packet()
        self.assertEqual(['TASK-01'],packet['manifest']['held_task_ids'])
        item=status(self.service,self.record)['items'][0]
        self.assertTrue(item['held']);self.assertFalse(item['eligible']);self.assertFalse(item['startable'])
        self.assertIn('Pozastaveno uživatelem',item['blocked_by'])
        with self.assertRaises(ValueError):self.send(self.message(packet))
        view=self.act('set-flag','TASK-01',flag='held',value=False)
        self.assertFalse(view['items'][0]['held'])
        self.assertEqual([False,True],[e['old'] for e in view['flag_audit'][-2:]])

    def test_queue_file_without_flag_fields_still_loads(self):
        view=self.qstatus();path=next(self.queue.root.glob('*.json'))
        data=json.loads(path.read_text());data.pop('held_task_ids');data.pop('flag_audit')
        path.write_text(json.dumps(data));path.chmod(0o600)
        self.assertEqual(view['task_ids'],self.qstatus()['task_ids'])
        self.assertTrue(self.act('set-flag','TASK-01',flag='held',value=True)['items'][0]['held'])

    def batch_queue(self):
        body=('- [ ] [BATCH-01] Feature\n  - type: batch\n'
              '  - [ ] [BATCH-01-A] First\n  - [ ] [BATCH-01-B] Second\n    - depends_on: BATCH-01-A\n'
              '- [ ] [TASK-09] Other\n')
        for task in ['TASK-03','TASK-02','TASK-01']:
            self.act('remove',task,preview_sha256=self.act('remove-preview',task)['preview_sha256'])
        self.head=self.save(body)
        self.record=panel_tests.BridgePanelTests.session(self)
        self.act('revalidate');self.act('add','BATCH-01')
        self.request=dict(project_id=self.project,session_id=self.record['session_id'],expected_head=self.head,
                          queue_revision=self.qstatus()['revision'],repository_commit='a'*40)
        return self.packet()

    def test_batch_is_one_feature_with_linked_tasks_not_a_flat_list(self):
        packet=self.batch_queue();manifest=packet['manifest']
        self.assertEqual(['BATCH-01'],[t['id'] for t in manifest['tasks']])
        self.assertEqual(['BATCH-01-A','BATCH-01-B'],[t['id'] for t in manifest['linked_tasks']])
        self.assertEqual(['BATCH-01-A','BATCH-01-B'],manifest['hierarchy']['BATCH-01']['children'])
        value=status(self.service,self.record);batch=value['items'][0]
        self.assertTrue(batch['startable']);self.assertFalse(batch['eligible'])
        self.assertEqual(['BATCH-01-A','BATCH-01-B'],batch['open_children'])
        linked={i['id']:i for i in value['linked_items']}
        self.assertEqual('BATCH-01',linked['BATCH-01-A']['parent_id'])
        self.assertTrue(linked['BATCH-01-A']['eligible']);self.assertFalse(linked['BATCH-01-B']['eligible'])
        self.assertEqual([],value['hierarchy_problems'])
        with self.assertRaises(ValueError):self.send(self.message(packet,'BATCH-01'))
        with self.assertRaises(ValueError):self.send(self.message(packet,'TASK-09'))
        a=self.message(packet,'BATCH-01-A');self.send(a);self.review(a)
        value=status(self.service,self.record)
        self.assertTrue(value['linked_items'][0]['user_confirmed']);self.assertTrue(value['linked_items'][1]['eligible'])
        b=self.message(packet,'BATCH-01-B');self.send(b);self.review(b)
        value=status(self.service,self.record);self.assertTrue(value['items'][0]['eligible'])
        done=self.message(packet,'BATCH-01');self.send(done);self.review(done)
        self.assertTrue(status(self.service,self.record)['items'][0]['user_confirmed'])

    def test_hierarchy_problems_repeats_and_cycles(self):
        node=lambda i,p=None:dict(id=i,parent_id=p,type='batch' if p is None else 'task')
        nodes={i:node(i,p) for i,p in (('B',None),('A','B'),('C','B'))}
        hierarchy,linked,problems=build_hierarchy(['B','A'],nodes)
        self.assertEqual(['C'],linked,'a queued child is not linked twice');self.assertEqual([],problems)
        self.assertEqual(['A','C'],hierarchy['B']['children'])
        cycle={'X':node('X','Y'),'Y':node('Y','X')}
        _,_,problems=build_hierarchy(['X'],cycle)
        self.assertTrue(problems and problems[0].startswith('Hierarchy cycle'))
        manifest=dict(tasks=[dict(id='B')],linked_tasks=[dict(id='A')],hierarchy=dict(B=dict(children=['A','GONE'])))
        self.assertEqual(['B: chybí odkaz na GONE'],hierarchy_problems(manifest,{'B':{}, 'A':{}}))
        self.assertEqual(['B: A již není v roadmapě','B: chybí odkaz na GONE'],hierarchy_problems(manifest,{'B':{}}))

    def test_plain_queue_packet_keeps_its_original_shape(self):
        manifest=self.packet()['manifest']
        for key in ('hierarchy','linked_tasks','held_task_ids'):self.assertNotIn(key,manifest)

    def test_plugin_flags_scope_and_manual_request(self):
        import shutil
        if not shutil.which('node'):self.skipTest('Node required')
        script="""
const assert=require('node:assert/strict'),q=require('./extensions/workspace-bridge/queue.js');
const names=(e,o)=>q.flags(e,o).map(f=>f.name);
assert(q.flags({status:'failed',eligible:true}).some(f=>f.label==='Selhalo'));
assert(q.flags({status:'completed',status_mode:'sum',eligible:true},{stale:true}).some(f=>f.label==='SUM · Dokončeno (poslední známý stav)'));
const base={eligible:true,startable:true,agent_confirmed:false,user_requested:false,user_confirmed:false};
assert.deepEqual(names(base),['ready']);
assert(q.flags({...base,eligible:false,open_children:[]}).some(f=>f.name==='ready'&&f.label.includes('dokončení čeká')));
assert.deepEqual(names({...base,agent_confirmed:true,user_requested:true}),['ready','agent','requested']);
assert.deepEqual(names({...base,user_confirmed:true}),['accepted']);
assert.deepEqual(names({...base,eligible:false,startable:false}),['waiting']);
assert.deepEqual(names({...base,held:true,eligible:false}),['held']);
assert.deepEqual(names({agent_confirmed:true}),['unknown','agent']);
assert.deepEqual(names(base,{blockers:['x']}),['blocked']);
const stale=q.flags({...base,user_confirmed:true,agent_confirmed:true},{stale:true}).map(f=>f.label);
assert.equal(stale[0],'Neaktuální');assert.ok(!stale.includes('Přijato uživatelem'));
assert.ok(stale.includes('Agent hlásí splnění (poslední známý stav)'));
assert.deepEqual(names({...base,eligible:false,open_children:['A']}),['feature']);
const packet=(hierarchy,linked)=>({packet_id:'p',blockers:[],hierarchy_problems:[],items:[{id:'B',eligible:false,startable:true}],linked_items:linked,manifest:{revision:'r',hierarchy,tasks:[{id:'B',checklist:[]}],linked_tasks:linked.map(l=>({id:l.id,checklist:[{checked:true},{checked:false}]}))}});
let s=q.scope(packet({B:{children:['A','GONE','A']}},[{id:'A',eligible:true,parent_id:'B'}]),'B');
assert.deepEqual(s.rows.map(r=>[r.id,r.repeated]),[['A',false],['GONE',false],['A',true]]);
assert.deepEqual(s.problems,['Chybí odkaz: GONE']);
assert.equal(q.scope(packet({},[{id:'A',parent_id:'B'}]),'A').parent,'B');
assert.deepEqual(q.scope(packet({},[{id:'A',parent_id:'B'}]),'A').problems,['Nesouhlasí nadřazený odkaz: A']);
assert.deepEqual(q.scope(packet({},[{id:'A',parent_id:'GONE'}]),'A').problems,['Chybí nadřazený odkaz: GONE']);
assert.deepEqual(q.scope(packet({B:{children:['A']}},[{id:'A',parent_id:'B'}]),'A').problems,[]);
s=q.scope(packet({B:{children:['A']},A:{children:['B']}},[{id:'A'}]),'B');assert.ok(s.problems.some(p=>p.startsWith('Cyklus')));
const value=packet({B:{children:['A']}},[{id:'A',eligible:true}]);
const m=q.manualRequest(value,'A','done','c'.repeat(40),'id');
assert.equal(m.reported_by,'user');assert.equal(m.queue_packet_id,'p');assert.equal(m.evidence,undefined);
assert.deepEqual(m.checklist,[{index:1,checked:true}]);
assert.throws(()=>q.manualRequest(value,'B','x','c','id'),/ruční žádost/);
assert.throws(()=>q.manualRequest({...value,blockers:['stale']},'A','x','c','id'),/ruční žádost/);
assert.throws(()=>q.manualRequest({...value,linked_items:[{id:'A',eligible:true,user_requested:true}]},'A','x','c','id'),/už čeká/);
const startValue=packet({B:{children:['A']}},[{id:'A',eligible:true,startable:true,status:'planned'}]);
const st=q.manualStart(startValue,'A','start','c'.repeat(40),'id');
assert.deepEqual(st,{message_id:'id',task_id:'A',kind:'progress',body:'start',revision:'r',repository_commit:'c'.repeat(40),queue_packet_id:'p',reported_by:'user'});
assert.ok(q.startable(startValue,'A'));assert.ok(q.startable(startValue,'B'),'batch starts before its tasks are accepted');
const withA=extra=>({...startValue,linked_items:[{id:'A',startable:true,...extra}]});
assert.throws(()=>q.manualStart(withA({status_mode:'sum'}),'A','x','c','id'),/SUM/);
assert.throws(()=>q.manualStart(withA({status:'in progress'}),'A','x','c','id'),/Probíhá/);
assert.throws(()=>q.manualStart(withA({startable:false}),'A','x','c','id'),/zahájení nelze/);
assert.throws(()=>q.manualStart(withA({user_confirmed:true}),'A','x','c','id'),/zahájení nelze/);
assert.throws(()=>q.manualStart({...startValue,blockers:['stale']},'A','x','c','id'),/zahájení nelze/);
assert.throws(()=>q.manualStart(startValue,'GONE','x','c','id'),/zahájení nelze/);
assert.ok(!q.startable(null,'A'));
"""
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,cwd=str(Path(__file__).parent.parent))
        self.assertEqual(0,result.returncode,result.stderr)

    def test_cross_message_identity_and_evidence_are_fail_closed(self):
        p=self.packet();m=self.message(p)
        for changes in [dict(queue_packet_id='f'*64),dict(reported_by='user'),dict(evidence={}),dict(task_id='TASK-02')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.send(m|changes)
        naked={k:v for k,v in m.items() if k not in {'queue_packet_id','reported_by','evidence'}}
        with self.assertRaises(ValueError):self.send(naked)
        self.send(m)
        with self.assertRaises(ValueError):self.send(m|{'body':'Changed after receipt'})
        with self.assertRaises(ValueError):self.review(m,expected_head='c'*40)

    def test_external_commit_and_changed_queue_do_not_rebase_silently(self):
        p=self.packet();m=self.message(p);self.send(m)
        preview=self.act('remove-preview','TASK-03');self.act('remove','TASK-03',preview_sha256=preview['preview_sha256'])
        self.assertTrue(status(self.service,self.record)['blockers'])
        with self.assertRaises(ValueError):self.review(m)
        self.assertEqual(self.head,Projects(self.node).repository(self.project).head())
        self.head=self.save(self.body+'\nExternal edit.\n')
        self.assertFalse(status(self.service,self.record)['current'])

    def test_repair_retains_original_packet_and_new_packet_has_complete_selection(self):
        original=self.packet()
        self.head=self.save(self.body.replace('depends_on: TASK-01','depends_on: TASK-01, TASK-04')+
                            '- [ ] [TASK-04] New prerequisite\n')
        self.assertFalse(self.qstatus()['valid'])
        preview=self.act('repair-preview')
        repaired=self.act('repair',preview_sha256=preview['preview_sha256'])
        self.assertEqual(repaired['task_ids'],['TASK-01','TASK-04','TASK-02','TASK-03'])
        self.assertEqual(original,load(self.service,self.record['session_id'],original['packet_id']))
        self.assertTrue(status(self.service,self.record,original)['blockers'])
        self.request.update(expected_head=self.head,queue_revision=repaired['revision'])
        self.assertIsNone(self.poll()['queue_refresh_error'])
        replacement=load(self.service,self.record['session_id'])
        self.assertNotEqual(original['packet_id'],replacement['packet_id'])
        self.assertEqual(repaired['task_ids'],[t['id'] for t in replacement['manifest']['tasks']])

    def test_reordered_queue_refreshes_packet_without_mutating_history_or_acceptance(self):
        original = self.packet(); message = self.message(original); self.send(message)
        accepted = self.review(message); self.poll(); self.poll()
        pinned = load(self.service, self.record['session_id']); before = self.qstatus()
        moved = self.act('move', 'TASK-01', target_index=2)
        self.assertEqual(['TASK-02', 'TASK-03', 'TASK-01'], moved['task_ids'])
        self.assertEqual(before['revision']+1, moved['revision'])
        self.assertTrue(next(i for i in moved['items'] if i['id']=='TASK-01')['user_confirmed'])
        self.assertEqual(accepted['result']['commit_id'], Projects(self.node).repository(self.project).head())
        self.assertEqual(pinned, load(self.service, self.record['session_id'], pinned['packet_id']))
        self.assertTrue(status(self.service, self.record, pinned)['blockers'])
        self.poll(); self.poll()
        refreshed = load(self.service, self.record['session_id'])
        self.assertNotEqual(pinned['packet_id'], refreshed['packet_id'])
        self.assertEqual(moved['task_ids'], [item['id'] for item in refreshed['manifest']['tasks']])
        self.assertEqual(moved['revision'], refreshed['manifest']['queue_revision'])
        self.assertIn('TASK-01', refreshed['manifest']['accepted_task_ids'])
        self.assertEqual(original, load(self.service, self.record['session_id'], original['packet_id']))

    def test_export_scope_and_wrong_owner_are_not_silently_expanded(self):
        with self.service.database() as db:
            record=dict(self.record,export_documents=False)
            db.execute('UPDATE sessions SET record=? WHERE id=?',(json.dumps(record),record['session_id']))
        with self.assertRaises(ValueError):self.packet()
        with self.assertRaises(ValueError):publish(self.service,dict(id=str(uuid4()),node_role='member',memberships={}),self.request)

    def test_recursive_documents_cycle_exact_bytes_and_missing_blocker(self):
        a,b=str(uuid4()),str(uuid4());docs=Artifacts(self.node)
        head=self.head
        for id_,body in [(a,'A [B](artifacts/'+b+'/content.md)'),(b,'B [A](artifacts/'+a+'/content.md)')]:
            head=docs.save(dict(project_id=self.project,artifact_id=id_,base_head=head,title=id_,body=body,new=True),str(uuid4()))['commit_id']
        self.head=head
        self.head=self.save('- [ ] [TASK-01] First\n  - [A](artifacts/'+a+'/content.md)\n- [ ] [TASK-02] Second\n  - depends_on: TASK-01\n- [ ] [TASK-03] Third\n  - depends_on: TASK-02\n')
        # Explicitly remap and revalidate to the new snapshot, preserving old mapping history.
        self.record=panel_tests.BridgePanelTests.session(self);self.act('revalidate');self.request.update(session_id=self.record['session_id'],expected_head=self.head,queue_revision=self.qstatus()['revision'])
        p=self.packet();self.assertEqual([],p['manifest']['blockers']);ids=[d['artifact_id'] for d in p['manifest']['documents']]
        self.assertEqual(1,ids.count(a));self.assertEqual(1,ids.count(b))
        doc=read_document(self.service,self.record,p['packet_id'],a)
        self.assertEqual('A [B](artifacts/'+b+'/content.md)',base64.b64decode(doc['content_base64']).decode())
        with self.assertRaises(ValueError):read_document(self.service,self.record,p['packet_id'],str(uuid4()))
        with patch('spikes.ide_queue.MAX_DOCUMENTS',1):
            incomplete=self.packet();self.assertTrue(incomplete['manifest']['blockers'])
            with self.assertRaises(ValueError):self.send(self.message(incomplete))

    def test_native_review_crashes_recover_at_intent_commit_and_outcome(self):
        p=self.packet()
        for task,stage in zip(['TASK-01','TASK-02','TASK-03'],['intent-prepared','before-outcome','outcome-published']):
            with self.subTest(stage=stage):
                m=self.message(p,task);self.send(m);head=Projects(self.node).repository(self.project).head()
                request=dict(project_id=self.project,session_id=self.record['session_id'],message_id=m['message_id'],decision='accepted',note='',expected_head=head,operation_id=str(uuid4()))
                def stop(point):
                    if point==stage:raise RuntimeError('lost outcome at '+stage)
                with self.assertRaises(RuntimeError):self.service.review(None,request,checkpoint=stop)
                interrupted=Projects(self.node).repository(self.project).head()
                if stage=='intent-prepared':self.assertEqual(head,interrupted)
                else:self.assertNotEqual(head,interrupted)
                r=self.service.review(None,request)
                if stage!='intent-prepared':self.assertEqual(interrupted,r['result']['commit_id'])
                self.assertTrue(status(self.service,self.record)['current'])
                self.assertEqual(r,self.service.review(None,request))

    def test_packet_insert_lost_reply_is_replayed_without_new_packet(self):
        def stop(stage):
            if stage=='queue-packet-published':raise RuntimeError('lost publication reply')
        with self.assertRaises(RuntimeError):publish(self.service,None,self.request,checkpoint=stop)
        p=load(self.service,self.record['session_id']);self.assertEqual(p,self.packet())

    def poll(self):
        with self.service.database() as db:
            self.record = json.loads(db.execute('SELECT record FROM sessions WHERE id=?', (self.record['session_id'],)).fetchone()[0])
        return self.service.exchange(self.record, dict(session_id=self.record['session_id'], messages=[]))

    def test_idle_poll_publishes_initial_queue_and_refreshes_selection_without_plan_write(self):
        first = self.poll(); packet = load(self.service, self.record['session_id'])
        self.assertTrue(first['has_queue']); self.assertIsNone(first['queue_refresh_error'])
        self.assertIsNone(packet['manifest']['repository_commit'])
        preview = self.act('remove-preview', 'TASK-03')
        self.act('remove', 'TASK-03', preview_sha256=preview['preview_sha256'])
        self.assertIsNone(self.poll()['queue_refresh_error'])
        updated = load(self.service, self.record['session_id'])
        self.assertNotEqual(packet['packet_id'], updated['packet_id'])
        self.assertEqual(['TASK-01', 'TASK-02'], [t['id'] for t in updated['manifest']['tasks']])
        self.assertEqual(packet, load(self.service, self.record['session_id'], packet['packet_id']))
        self.assertEqual(self.head, Projects(self.node).repository(self.project).head())
        with self.service.database() as db:
            count = db.execute('SELECT count(*) FROM queue_packets').fetchone()[0]
        self.poll()
        with self.service.database() as db:
            self.assertEqual(count, db.execute('SELECT count(*) FROM queue_packets').fetchone()[0])

    def test_task_and_document_edits_refresh_snapshot_atomically_and_keep_receipt_replay(self):
        old = self.packet()
        message = self.message(old) | dict(kind='message')
        message = {k:v for k,v in message.items() if k not in {'queue_packet_id','reported_by','evidence'}}
        receipt = self.send(message)['receipts']
        self.head = self.save(self.body.replace('First', 'Updated task'))
        result = self.poll()
        self.assertIsNone(result['queue_refresh_error']); self.assertFalse(result['stale'])
        self.assertEqual(self.head, result['snapshot']['commit_id'])
        new = load(self.service, self.record['session_id'])
        self.assertEqual('Updated task', new['manifest']['tasks'][0]['title'])
        self.assertNotEqual(old['packet_id'], new['packet_id'])
        self.poll()  # Load the new mapping record for the replay.
        with self.assertRaises(ValueError):
            self.send(self.message(old) | dict(revision=old['manifest']['revision']))
        self.assertEqual(receipt, self.send(message)['receipts'])
        with self.assertRaises(ValueError): self.send(message | dict(body='Changed bytes'))
        # A content-only commit must refresh even when the task text stays the same.
        self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=str(uuid4()),
            base_head=self.head, title='Unrelated document', body='Document content', new=True), str(uuid4()))['commit_id']
        result = self.poll()
        self.assertEqual(self.head, result['snapshot']['commit_id'])

    def test_refresh_preserves_review_and_verified_acceptance_across_generations(self):
        packet = self.packet(); message = self.message(packet); self.send(message)
        self.head = self.save(self.body.replace('Third', 'Changed third'))
        self.assertIn('human review', self.poll()['queue_refresh_error'])
        self.assertEqual(packet, load(self.service, self.record['session_id']))
        self.review(message, decision='rejected')
        self.assertIsNone(self.poll()['queue_refresh_error'])
        self.poll(); current = load(self.service, self.record['session_id'])
        report = self.message(current); self.send(report); self.review(report)
        # Change the queue after human acceptance; TASK-01 remains accepted in the new packet.
        preview = self.act('remove-preview', 'TASK-03')
        self.act('remove', 'TASK-03', preview_sha256=preview['preview_sha256'])
        self.assertIsNone(self.poll()['queue_refresh_error']); self.poll()
        value = status(self.service, self.record)
        self.assertTrue(value['items'][0]['user_confirmed'])
        self.assertTrue(value['items'][1]['eligible'])

    def test_human_acceptance_is_reflected_by_next_idle_poll_without_stale_snapshot(self):
        packet = self.packet(); message = self.message(packet); self.send(message)
        accepted = self.review(message)
        result = self.poll()
        self.assertFalse(result['stale']); self.assertIsNone(result['queue_refresh_error'])
        self.assertEqual(accepted['result']['commit_id'], result['snapshot']['commit_id'])
        self.poll(); value = status(self.service, self.record)
        self.assertTrue(value['items'][0]['user_confirmed'])
        self.assertTrue(value['items'][1]['eligible'])
        self.assertNotEqual(packet['packet_id'], value['packet_id'])

    def test_refresh_crash_before_insert_and_after_commit_replays_one_generation(self):
        packet = self.packet(); self.head = self.save(self.body.replace('First', 'Changed'))
        def before(stage):
            if stage == 'queue-packet-before-insert': raise RuntimeError('before insert')
        with self.assertRaises(RuntimeError): refresh(self.service, self.record, checkpoint=before)
        self.assertEqual(packet, load(self.service, self.record['session_id']))
        with self.service.database() as db:
            self.assertEqual(self.record, json.loads(db.execute('SELECT record FROM sessions WHERE id=?', (self.record['session_id'],)).fetchone()[0]))
        def inside(stage):
            if stage == 'queue-snapshot-updated': raise RuntimeError('uncommitted snapshot')
        with self.assertRaises(RuntimeError): refresh(self.service, self.record, checkpoint=inside)
        with self.service.database() as db:
            self.assertEqual(self.record, json.loads(db.execute('SELECT record FROM sessions WHERE id=?', (self.record['session_id'],)).fetchone()[0]))
        self.assertEqual(packet, load(self.service, self.record['session_id']))
        def after(stage):
            if stage == 'queue-packet-published': raise RuntimeError('lost reply')
        with self.assertRaises(RuntimeError): refresh(self.service, self.record, checkpoint=after)
        committed = load(self.service, self.record['session_id'])
        self.assertNotEqual(packet['packet_id'], committed['packet_id'])
        self.poll(); self.assertEqual(committed, load(self.service, self.record['session_id']))

    def test_invalid_selection_and_disabled_export_stay_blocked(self):
        packet = self.packet()
        self.head = self.save('- [ ] [TASK-01] First\n')
        self.assertIsNotNone(self.poll()['queue_refresh_error'])
        self.assertEqual(packet, load(self.service, self.record['session_id']))
        with self.service.database() as db:
            record = dict(self.record, export_documents=False)
            db.execute('UPDATE sessions SET record=? WHERE id=?', (json.dumps(record), record['session_id']))
        self.assertIsNone(self.poll()['queue_refresh_error'])
        self.assertEqual(packet, load(self.service, self.record['session_id']))

    def test_scoped_document_refresh_exports_new_bytes_without_repeated_incomplete_packets(self):
        identifier = str(uuid4())
        self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=identifier,
            base_head=self.head, title='Context', body='Original context', new=True), str(uuid4()))['commit_id']
        self.head = self.save(self.body.replace('First\n', 'First\n  - [Context](artifacts/'+identifier+'/content.md)\n'))
        self.assertIsNone(self.poll()['queue_refresh_error']); self.poll()
        original = load(self.service, self.record['session_id'])
        self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=identifier,
            base_head=self.head, title='Context', body='Changed context', new=False), str(uuid4()))['commit_id']
        self.assertIsNone(self.poll()['queue_refresh_error']); self.poll()
        current = load(self.service, self.record['session_id'])
        self.assertEqual(original['manifest']['tasks'], current['manifest']['tasks'])
        self.assertNotEqual(original['packet_id'], current['packet_id'])
        exported = read_document(self.service, self.record, current['packet_id'], identifier)
        self.assertEqual(b'Changed context', base64.b64decode(exported['content_base64']))
        # An unsupported link produces one blocked generation, not a new packet every poll.
        self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=identifier,
            base_head=self.head, title='Context', body='[Missing](artifacts/'+str(uuid4())+'/content.md)', new=False), str(uuid4()))['commit_id']
        self.poll(); blocked = load(self.service, self.record['session_id'])
        self.assertTrue(blocked['manifest']['blockers'])
        self.assertIsNotNone(self.poll()['queue_refresh_error'])
        self.assertEqual(blocked, load(self.service, self.record['session_id']))

    def test_source_commit_can_be_discovered_by_ide_but_invalid_values_fail(self):
        self.request['repository_commit'] = None
        self.assertIsNone(self.packet()['manifest']['repository_commit'])
        for invalid in ['', 'HEAD', 123, False]:
            with self.subTest(commit=invalid):
                self.request['repository_commit'] = invalid
                with self.assertRaises(ValueError): publish(self.service, None, self.request)

    def test_real_node_http_queue_handoff_agent_report_and_human_receipts(self):
        import shutil, subprocess
        if not shutil.which('node'):self.skipTest('Node required')
        from spikes.local_api import running_api
        from spikes.desktop_ui import DesktopHandler
        self.request['repository_commit']=self.head
        with running_api('http',handler=DesktopHandler,projects=Projects(self.node)) as server:
            fixture=self.root/'queue-host.json';fixture.write_text(json.dumps(dict(
                record=self.record,publication=self.request,pairing=self.created['pairing']|{'endpoint':server.origin},storage=str(self.root/'queue-storage'),admin_token=server.token)))
            result=subprocess.run(['node','tests/ide_queue_host.cjs',str(fixture)],capture_output=True,text=True,timeout=60)
            self.assertEqual(0,result.returncode,result.stdout+result.stderr)

    def test_node_cache_links_and_fallback_protect_canonical_bytes(self):
        import shutil, subprocess
        if not shutil.which('node'):self.skipTest('Node required')
        result=subprocess.run(['node','tests/ide_queue_cache.cjs'],capture_output=True,text=True,timeout=20)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)

    def test_revoked_mapping_blocks_packet_and_review_without_project_write(self):
        packet=self.packet();message=self.message(packet);self.send(message)
        self.service.revoke(self.project,self.record['session_id'])
        with self.assertRaises(ValueError):read_document(self.service,self.record,packet['packet_id'],self.artifact)
        with self.assertRaises(ValueError):self.review(message)
        self.assertEqual(self.head,Projects(self.node).repository(self.project).head())

    def test_publication_identity_is_stable_across_process_hash_seeds(self):
        import os, subprocess, sys
        preview=self.act('remove-preview','TASK-01');self.act('remove','TASK-01',preview_sha256=preview['preview_sha256'])
        a,b=str(uuid4()),str(uuid4());head=self.head
        for id_,body in [(a,'<!-- fpw-plan-document: definitions/v1 -->\n- [ ] [TASK-01] First\n  - type: task\n'),(b,'<!-- fpw-plan-document: definitions/v1 -->\n- [ ] [TASK-02] Second\n  - type: task\n  - depends_on: TASK-01\n')]:
            head=Artifacts(self.node).save(dict(project_id=self.project,artifact_id=id_,base_head=head,title=id_,body=body,new=True),str(uuid4()))['commit_id']
        self.head=head
        self.head=self.save('<!-- fpw-plan-profile: software-development/v1 -->\n- [ ] [MILESTONE-01] Milestone\n  - type: milestone\n  - [ ] [BATCH-01] [One](artifacts/'+a+'/content.md)\n    - type: batch\n  - [ ] [BATCH-02] [Two](artifacts/'+b+'/content.md)\n    - type: batch\n')
        self.assertEqual('ready',Projects(self.node).open(self.project)['plan']['status'],Projects(self.node).open(self.project)['plan'])
        self.record=panel_tests.BridgePanelTests.session(self);self.act('revalidate')
        self.act('add','TASK-01');self.act('add','TASK-02')
        self.request.update(session_id=self.record['session_id'],expected_head=self.head,queue_revision=self.qstatus()['revision'])
        script='import sys,json;from spikes.ide_queue import publish;from spikes.ide_bridge import IdeBridge;print(publish(IdeBridge(sys.argv[1]),None,json.loads(sys.argv[2]))["packet_id"])'
        identities=[]
        for seed in ['1','42']:
            result=subprocess.run([sys.executable,'-c',script,str(self.node),json.dumps(self.request)],env=dict(os.environ,PYTHONHASHSEED=seed),capture_output=True,text=True,timeout=30)
            self.assertEqual(0,result.returncode,result.stderr);identities.append(result.stdout.strip())
        self.assertEqual(identities[0],identities[1])
