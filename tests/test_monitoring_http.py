# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Monitoring uses the shared authenticated HTTP/RBAC boundary."""
import json
import unittest
from uuid import uuid4
from tests import test_web_server as fixtures
from spikes.monitoring import PROFILES

class MonitoringHTTPTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.WebTests('test_dns_hostname_validation_is_fail_closed')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        code,body,_=self.f.create_project('Monitoring HTTP')
        self.assertEqual(code,200,body);self.pid=json.loads(body)['id']

    def call(self,action,body,headers=None):
        return self.f.request(path='/v1/monitoring/'+action,body=json.dumps(dict(project_id=self.pid,**body)),headers=headers)

    def test_admin_can_create_and_read_watch_editor_cannot_activate_it(self):
        code,raw,_=self.call('view',{});self.assertEqual(code,200,raw);view=json.loads(raw)
        cfg=dict(id=str(uuid4()),name='HTTP watch',goal='Evidence',active=False,privacy='project',timezone='Europe/Prague',
            start='2026-03-23',inputs=[],urls=[],access_note='',periods={'weekly':PROFILES['weekly']},presentation=False,mode='deterministic',binding=None,tags=[])
        code,raw,_=self.call('save',dict(operation_id=str(uuid4()),base_head=view['commit_id'],watch=cfg,new=True))
        self.assertEqual(code,200,raw)
        def admin(body):
            code,raw,_=self.f.request(path='/v1/administration',body=json.dumps(body));self.assertEqual(code,200,raw);return json.loads(raw)
        state=admin({'action':'list'})
        state=admin({'action':'create-user','expected_commit':state['commit_id'],'name':'Editor','node_role':'member'})
        key=state['access_key'];user=state['users'][0]
        admin({'action':'update-user','expected_commit':state['commit_id'],'user_id':user['id'],'active':True,'node_role':'member','memberships':{self.pid:'editor'}})
        headers={'Authorization':'Bearer '+key}
        code,raw,_=self.call('view',{},headers);self.assertEqual(code,200,raw);self.assertFalse(json.loads(raw)['can_manage'])
        code,_,_=self.call('run',{'watch_id':cfg['id'],'kind':'weekly'},headers);self.assertEqual(code,403)
        code,_,_=self.call('view',{}, {'Authorization':'Bearer invalid'});self.assertEqual(code,401)

    def test_independent_definitions_share_read_permissions_and_admin_write_boundary(self):
        from tests.test_monitoring_definitions import definition
        watch_id=str(uuid4())
        code,raw,_=self.call('definitions',{});self.assertEqual(code,200,raw)
        view=json.loads(raw)
        request=dict(operation_id=str(uuid4()),base_head=view['commit_id'],watch_id=watch_id,
                     previous=[],privacy='project',definition=definition())
        code,raw,_=self.call('definition-save',request);self.assertEqual(code,200,raw)
        code,raw,_=self.call('definitions',{});self.assertEqual(code,200,raw)
        self.assertEqual(json.loads(raw)['definitions'][0]['watch_id'],watch_id)
        def admin(body):
            code,raw,_=self.f.request(path='/v1/administration',body=json.dumps(body))
            self.assertEqual(code,200,raw);return json.loads(raw)
        state=admin({'action':'list'})
        state=admin({'action':'create-user','expected_commit':state['commit_id'],'name':'Definition reader','node_role':'member'})
        key=state['access_key'];user=state['users'][0]
        admin({'action':'update-user','expected_commit':state['commit_id'],'user_id':user['id'],
               'active':True,'node_role':'member','memberships':{self.pid:'reader'}})
        headers={'Authorization':'Bearer '+key}
        code,raw,_=self.call('definitions',{},headers);self.assertEqual(code,200,raw)
        self.assertFalse(json.loads(raw)['can_manage'])
        self.assertEqual(self.call('definition-save',request,headers)[0],403)
        self.assertEqual(self.call('definitions',{}, {'Authorization':'Bearer invalid'})[0],401)
