# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import base64
import unittest
from uuid import uuid4
from unittest.mock import patch

from spikes.artifacts import Artifacts
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.task_queue import TaskQueue
from spikes.ide_queue import publish, load, status, read_document, digest
from tests import test_ide_bridge_panel as panel_tests


class QueuePacketTests(unittest.TestCase):
    def setUp(self):
        panel_tests.BridgePanelTests.setUp(self)
        self.head = self.save('- [ ] [TASK-01] First\n- [ ] [TASK-02] Second\n  - depends_on: TASK-01\n- [ ] [TASK-03] Third\n  - depends_on: TASK-02\n')
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
    def message(self,packet,task='TASK-01'):
        return dict(message_id=str(uuid4()),task_id=task,kind='completed',body='Implemented and inspected.',
            revision=self.record['snapshot']['revision'],repository_commit='b'*40,queue_packet_id=packet['packet_id'],
            reported_by='agent',evidence=dict(tests='Focused test suite passed',diff='commit '+('b'*40)))
    def send(self,m):return self.service.exchange(self.record,dict(session_id=self.record['session_id'],messages=[m]))
    def review(self,m,**changes):
        request=dict(project_id=self.project,session_id=self.record['session_id'],message_id=m['message_id'],
            decision='accepted',note='Human accepted evidence.',expected_head=Projects(self.node).repository(self.project).head(),operation_id=str(uuid4()))
        return self.service.review(None,request|changes)

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
