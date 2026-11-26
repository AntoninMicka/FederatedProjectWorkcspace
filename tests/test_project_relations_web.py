# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import unittest
from uuid import uuid4
from tests import test_web_server as fixtures
from spikes.artifacts import Artifacts


class RelationsWebTests(unittest.TestCase):
    setUp=fixtures.WebTests.setUp
    stop=fixtures.WebTests.stop
    request=fixtures.WebTests.request
    create_project=fixtures.WebTests.create_project

    def post(self,path,body,key=None):
        code,data,_=self.request(path=path,body=json.dumps(body),headers={'Authorization':'Bearer '+key} if key else None)
        return code,json.loads(data) if data else None

    def test_https_membership_derived_read_and_native_management_guards(self):
        a=json.loads(self.create_project('Rodič')[1])['id'];b=json.loads(self.create_project('Dítě')[1])['id']
        artifacts=Artifacts(self.root/'node.json');id_=str(uuid4());local=str(uuid4())
        for id_,body,privacy in [(id_,'Sdílené podle hierarchie','project')]:
            artifacts.save(dict(project_id=b,artifact_id=id_,base_head=artifacts.workspace(b).git.head(),
                                title=body,body=body,new=True,privacy=privacy),str(uuid4()))
        code,envelope=self.post('/v1/project-relations/proposal/preview',dict(project_id=a,source_project_id=a,
            target_project_id=b,relation_type='parent_of',reason='Dítě dodává podklady',relation_id=None))
        self.assertEqual(code,200,envelope)
        rid=envelope['preview']['record']['id'];owner=min(a,b)
        code,receipt=self.post('/v1/project-relations/confirm',dict(project_id=a,preview=envelope['preview'],sha256=envelope['sha256'],operation_id=str(uuid4())))
        self.assertEqual(code,200,receipt)
        for pid in (a,b):
            op=str(uuid4());code,envelope=self.post('/v1/project-relations/evidence/preview',dict(project_id=pid,
                owner_project_id=owner,relation_id=rid,operation_id=op,revoke=False,reason=None))
            self.assertEqual(code,200,envelope)
            code,receipt=self.post('/v1/project-relations/confirm',dict(project_id=pid,preview=envelope['preview'],sha256=envelope['sha256'],operation_id=op))
            self.assertEqual(code,200,receipt)
        artifacts.save(dict(project_id=b,artifact_id=local,base_head=artifacts.workspace(b).git.head(),
                            title='Nesmí do webu',body='Nesmí do webu',new=True,privacy='local-only'),str(uuid4()))
        code,state=self.post('/v1/administration',dict(action='list'));self.assertEqual(code,200,state)
        code,state=self.post('/v1/administration',dict(action='create-user',expected_commit=state['commit_id'],name='Editor rodiče',node_role='member'))
        uid=state['users'][0]['id'];key=state['access_key']
        self.post('/v1/administration',dict(action='update-user',expected_commit=state['commit_id'],user_id=uid,
                                           active=True,node_role='member',memberships={a:'editor'}))
        code,view=self.post('/v1/project-relations/sources',dict(project_id=a,query=''),key)
        self.assertEqual(code,200,view)
        public_id=next(r['artifact_id'] for r in view['items'] if r['source_project_id']==b)
        self.assertNotIn(local,repr(view));self.assertNotIn('Nesmí do webu',repr(view))
        code,preview=self.post('/v1/project-relations/source/view',dict(project_id=a,source_project_id=b,artifact_id=public_id),key)
        self.assertEqual(code,200,preview);self.assertIn('Sdílené podle hierarchie',preview['preview']['text'])
        self.assertEqual(self.post('/v1/projects/open',dict(project_id=b),key)[0],403)
        code,pin=self.post('/v1/project-relations/source/pin',dict(project_id=a,source_project_id=b,artifact_id=public_id),key)
        self.assertEqual(code,200,pin);self.assertEqual(pin['pin']['source']['project_id'],b)
        code,view=self.post('/v1/project-relations/overview',dict(project_id=a),key)
        self.assertEqual(code,200,view);self.assertFalse(view['can_create']);self.assertFalse(view['relations'][0]['can_edit'])
        self.assertEqual(self.post('/v1/project-relations/proposal/preview',dict(project_id=a,source_project_id=a,
            target_project_id=b,relation_type='depends_on',reason='Nepovolené',relation_id=rid),key)[0],403)
        self.assertEqual(self.post('/v1/project-relations/source/view',dict(project_id=a,source_project_id=b,artifact_id=local),key)[0],409)
