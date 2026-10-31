# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import json
import unittest
import subprocess
import shutil
from uuid import uuid4

from spikes.artifacts import Artifacts
from spikes.ide_bridge import IdeBridge
from spikes.ide_bridge_panel import panel, read_document
from spikes.projects import Projects
from tests import test_ide_bridge as bridge_tests
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler


class BridgePanelTests(unittest.TestCase):
    save = bridge_tests.IdeBridgeTests.save
    create = bridge_tests.IdeBridgeTests.create
    message = bridge_tests.IdeBridgeTests.message

    def setUp(self):
        bridge_tests.IdeBridgeTests.setUp(self)

    def session(self):
        self.created,parent=bridge_tests.IdeBridgeTests.parent(self)
        repository=str(self.root/'project')
        mapping=self.service.configure_mapping(None,bridge_tests.IdeBridgeTests.mapping(self,parent,
            repository=repository,editor_workspace=repository,export_documents=True))
        self.service.connection_exchange(parent,dict(connection_id=parent['connection_id'],action='bind',
            session_id=mapping['session_id'],repository=repository,editor_workspace=repository))
        with self.service.database() as db:
            self.record=json.loads(db.execute('SELECT record FROM sessions WHERE id=?',(mapping['session_id'],)).fetchone()[0])
        self.created['revision']=self.record['snapshot']['revision']
        return self.record

    def send(self, **changes):
        record = self.session()
        message = self.message(self.created) | changes
        self.service.exchange(record, dict(session_id=record['session_id'], messages=[message]))
        return message

    def review(self, message, **changes):
        return dict(project_id=self.project, session_id=self.record['session_id'],
                    message_id=message['message_id'], decision='accepted', note='Reviewed evidence.',
                    expected_head=self.head, operation_id=str(uuid4()), **changes)

    def test_panel_and_exact_document_bytes_never_modify_project(self):
        record = self.session(); value = panel(self.service, record)
        self.assertEqual(value['revision'], self.created['revision'])
        self.assertTrue(any(row['artifact_id'] == self.artifact for row in value['documents']))
        result = read_document(self.service, record, self.artifact)
        self.assertEqual(base64.b64decode(result['content_base64']), self.body.encode())
        self.assertEqual(Projects(self.node).open(self.project)['commit_id'], self.head)
        with self.assertRaises(ValueError):
            read_document(self.service, record, str(uuid4()))

    def test_old_credentials_cannot_grant_themselves_document_export(self):
        created,parent=bridge_tests.IdeBridgeTests.parent(self)
        repo=str(self.root/'project')
        request=bridge_tests.IdeBridgeTests.mapping(self,parent,repository=repo,editor_workspace=repo)
        mapping=self.service.configure_mapping(None,request)
        def bind(session):
            self.service.connection_exchange(parent,dict(connection_id=parent['connection_id'],action='bind',
                session_id=session,repository=repo,editor_workspace=repo))
        def call(action,session,**payload):
            return self.service.connection_exchange(parent,dict(connection_id=parent['connection_id'],action=action,
                request={'session_id':session,**payload}))
        bind(mapping['session_id'])
        self.assertEqual(call('panel',mapping['session_id'])['documents'],[])
        with self.assertRaisesRegex(ValueError,'not enabled'):
            call('document',mapping['session_id'],artifact_id=self.artifact)
        updated=request|{'expected_mapping':mapping['session_id'],'export_documents':True}
        with self.assertRaisesRegex(ValueError,'human'):
            self.service.connection_exchange(parent,dict(connection_id=parent['connection_id'],action='map',mapping=updated))
        allowed=self.service.configure_mapping(None,updated);bind(allowed['session_id'])
        self.assertTrue(call('panel',allowed['session_id'])['documents'])
        with self.assertRaises(ValueError):call('panel',mapping['session_id'])
        self.assertEqual(self.head,Projects(self.node).open(self.project)['commit_id'])

    def test_rules_explicit_scope_privacy_and_revoke_fail_closed(self):
        identifier = str(uuid4())
        value = {'schema': 'fpw-agent-rules-v1', 'scope': {'kind': 'directory', 'path': 'src'}, 'body': 'Focused tests.'}
        self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=identifier,
            base_head=self.head, title='Agent rules', body=json.dumps(value), new=True,
            metadata={'tags': ['agent-rules']}), str(uuid4()))['commit_id']
        folder = self.root/'project'/'artifacts'/identifier
        (folder/'content.md').rename(folder/'rules.json')
        meta = json.loads((folder/'metadata.json').read_text()); meta['file'] = 'rules.json'
        (folder/'metadata.json').write_text(json.dumps(meta))
        self.head = Projects(self.node).repository(self.project).commit('Typed rule fixture')
        record = self.session()
        rules = next(v for v in panel(self.service, record)['documents'] if v['artifact_id'] == identifier)
        self.assertEqual(rules['scope'], {'kind': 'directory', 'path': 'src'})
        self.service.revoke(self.project, record['session_id'])
        with self.assertRaisesRegex(ValueError, 'revoked'):
            panel(self.service, record)
        record = self.session()
        folder = self.root/'project'/'artifacts'/self.artifact
        meta = json.loads((folder/'metadata.json').read_text()); meta['privacy'] = 'local-only'
        (folder/'metadata.json').write_text(json.dumps(meta))
        self.head = Projects(self.node).repository(self.project).commit('Local-only fixture')
        with self.assertRaisesRegex(ValueError, 'local-only'):
            panel(self.service, record)

    def test_review_rejects_viewer_and_wrong_project_without_mutation(self):
        message=self.send();before=self.head;request=self.review(message)
        with self.assertRaisesRegex(ValueError,'access revoked'):
            self.service.review({'id':str(uuid4()),'node_role':'viewer','memberships':{}},request)
        with self.assertRaises(ValueError):
            self.service.review(None,request|{'project_id':str(uuid4())})
        self.assertEqual(Projects(self.node).open(self.project)['commit_id'],before)

    def test_frontmatter_completion_preserves_metadata_and_exact_body(self):
        import yaml
        folder=self.root/'project'/'artifacts'/self.artifact
        meta=json.loads((folder/'metadata.json').read_text());meta.pop('file')
        (folder/'metadata.json').unlink()
        (folder/'content.md').write_text('---\n'+yaml.safe_dump(meta,sort_keys=True)+'---\n'+self.body)
        self.head=Projects(self.node).repository(self.project).commit('Frontmatter fixture')
        message=self.send();request=self.review(message)
        before=Projects(self.node).repository(self.project).snapshot(self.head)
        self.service.review(None,request)
        view=Projects(self.node).open(self.project)
        after=Projects(self.node).repository(self.project).snapshot(view['commit_id'])
        for p,raw in before.items():
            if b'[TASK-01]' in raw:
                self.assertEqual(after[p],raw.replace(b'- [ ] [TASK-01]',b'- [x] [TASK-01]',1))
            else:self.assertEqual(after[p],raw)

    def test_project_message_and_partial_progress_are_not_automatic_completion(self):
        message = self.send(task_id=None, kind='message')
        self.assertIsNone(panel(self.service, self.record)['messages'][0]['message']['task_id'])
        outcome = self.service.review(None, self.review(message))
        self.assertEqual(outcome['state'], 'completed')
        self.assertEqual(Projects(self.node).open(self.project)['commit_id'], self.head)
        self.assertEqual(panel(self.service, self.record)['messages'][0]['review'], outcome)

    def test_review_task_completion_replays_without_second_commit(self):
        message = self.send(); request = self.review(message)
        first = self.service.review(None, request)
        second = IdeBridge(self.node).review(None, request)
        self.assertEqual(first, second)
        view = Projects(self.node).open(self.project)
        self.assertTrue(next(t for t in view['plan']['nodes'] if t['id'] == 'TASK-01')['checked'])
        self.assertEqual(Projects(self.node).repository(self.project).run(
            'rev-list', '--count', self.head+'..HEAD').stdout.strip(), '1')
        with self.assertRaisesRegex(ValueError, 'another decision'):
            self.service.review(None, request | {'decision': 'rejected'})

    def test_stale_proposal_never_changes_a_newer_task(self):
        message = self.send()
        self.head = self.save(self.body+'- [ ] [TASK-03] New revision\n')
        with self.assertRaisesRegex(ValueError, 'Stale proposal'):
            self.service.review(None, self.review(message))
        self.assertFalse(next(t for t in Projects(self.node).open(self.project)['plan']['nodes']
                              if t['id'] == 'TASK-01')['checked'])

    def test_prepared_review_without_native_effect_becomes_terminal_stale(self):
        message = self.send(); request = self.review(message)
        with self.assertRaisesRegex(RuntimeError, 'before native'):
            self.service.review(None, request, checkpoint=lambda stage:
                (_ for _ in ()).throw(RuntimeError('before native')) if stage=='intent-prepared' else None)
        self.head = self.save(self.body+'- [ ] [TASK-03] New work\n')
        result = self.service.review(None, request)
        self.assertEqual(result['outcome'], 'stale'); self.assertEqual(result['state'], 'completed')
        self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])
        self.assertEqual(result, self.service.review(None, request))

    def test_review_crashes_resume_same_operation_at_each_store_boundary(self):
        for boundary in ('intent-prepared', 'prepared', 'ref-updated', 'indexed', 'before-outcome', 'outcome-published'):
            with self.subTest(boundary=boundary):
                self.head = self.save(self.body+'\nBoundary '+boundary+'\n')
                message = self.send(); request = self.review(message)
                with self.assertRaisesRegex(RuntimeError, 'power loss'):
                    self.service.review(None, request, checkpoint=lambda stage:
                        (_ for _ in ()).throw(RuntimeError('power loss')) if stage == boundary else None)
                status = self.service.status(self.project)
                self.assertTrue(any(entry['review'] for session in status['sessions'] for entry in session['messages']))
                self.assertIn(self.project, [p['project_id'] for p in self.service.connections_status(None)['projects']])
                result = IdeBridge(self.node).review(None, request)
                self.assertEqual(result['state'], 'completed')
                self.assertEqual(Projects(self.node).repository(self.project).run(
                    'rev-list', '--count', self.head+'..HEAD').stdout.strip(), '1')
                self.head = result['result']['commit_id']

    def test_checklist_partial_and_completion_use_exact_indices_and_preserve_fences(self):
        self.body = '- [ ] [TASK-01] Feature\n  - type: task\n  - [ ] First\n```text\n  - [ ] Example\n```\n  - [ ] Second\n'
        self.head = self.save(self.body)
        message = self.send(kind='progress', checklist=[{'index': 0, 'checked': True}])
        result = self.service.review(None, self.review(message))
        self.head = result['result']['commit_id']
        task = Projects(self.node).open(self.project)['plan']['nodes'][0]
        self.assertFalse(task['checked']); self.assertEqual([r['checked'] for r in task['checklist']], [True, False])
        message = self.send(kind='completed', checklist=[{'index': 1, 'checked': True}])
        self.service.review(None, self.review(message))
        task = Projects(self.node).open(self.project)['plan']['nodes'][0]
        self.assertTrue(task['checked']); self.assertTrue(all(r['checked'] for r in task['checklist']))
        raw = Projects(self.node).repository(self.project).snapshot(
            Projects(self.node).open(self.project)['commit_id'])
        self.assertTrue(any(b'  - [ ] Example' in v for v in raw.values()))
        self.head = Projects(self.node).open(self.project)['commit_id']
        message = self.send(kind='progress', checklist=[{'index':0,'checked':False}])
        self.service.review(None,self.review(message))
        self.assertFalse(Projects(self.node).open(self.project)['plan']['nodes'][0]['checked'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for sidebar host')
    def test_sidebar_real_http_documents_rules_handoff_messages_review_and_revocation(self):
        from spikes.project_creation import ProjectCreation
        from spikes.markdown_documents import main_todo_id
        document_id, rule_id = str(uuid4()), str(uuid4())
        body = '<script>untrusted document</script>\n'
        for identifier, title, text, tags in [(document_id,'Reference',body,[]),
                                             (rule_id,'Workspace rules','Use focused tests.\n',['agent-rules'])]:
            self.head = Artifacts(self.node).save(dict(project_id=self.project, artifact_id=identifier,
                base_head=self.head, title=title, body=text, new=True, metadata={'tags': tags}),str(uuid4()))['commit_id']
        self.body = f'- [ ] [TASK-01] Unsafe <script> title\n  - Podklad: [Reference](artifacts/{document_id}/content.md)\n'
        self.head = self.save(self.body)
        repository = self.root/'project'
        (repository/'AGENTS.md').write_text('Local agent instructions.\n')
        (repository/' space').mkdir()
        (repository/' space'/'AGENTS.md').write_text('Nested rules.\n')
        (repository/'linked.txt').symlink_to(self.root/'outside.txt')
        (self.root/'outside.txt').write_text('Outside repository')
        self.head = Projects(self.node).repository(self.project).commit('Local agent fixtures')
        other = ProjectCreation(self.node).create('Other', str(self.root/'other'), str(uuid4()))['id']
        other_head = Projects(self.node).open(other)['commit_id']
        other_head = Artifacts(self.node).save(dict(project_id=other,artifact_id=main_todo_id(other),
            base_head=other_head,title='Tasks',body='- [ ] [OTHER-01] Other task\n',new=True),str(uuid4()))['commit_id']
        created, parent = bridge_tests.IdeBridgeTests.parent(self)
        mappings = {}
        for identifier, head, repo in [(self.project,self.head,repository),(other,other_head,self.root/'other')]:
            mapping = self.service.configure_mapping(None,dict(connection_id=parent['connection_id'],project_id=identifier,
                enabled=True,expected_head=head,repository=str(repo),editor_workspace=str(repo),instructions='Focused tests.',
                expected_mapping=None))
            self.service.connection_exchange(parent,dict(connection_id=parent['connection_id'],action='bind',
                session_id=mapping['session_id'],repository=str(repo),editor_workspace=str(repo)))
            mappings[mapping['session_id']] = dict(repository=str(repo),editor_workspace=str(repo))
        with running_api('http',handler=DesktopHandler,projects=Projects(self.node)) as server:
            fixture = self.root/'sidebar.json'; fixture.write_text(json.dumps(dict(pairing=created['pairing']|{'endpoint':server.origin},
                mappings=mappings,project_id=self.project,other_project=other,head=self.head,repository=str(repository),
                document_id=document_id,document_body=body,storage=str(self.root/'sidebar-storage'),admin_token=server.token)))
            fixture.chmod(0o600)
            result = subprocess.run(['node','tests/ide_sidebar_host.cjs',str(fixture)],capture_output=True,text=True,timeout=90)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(json.loads(result.stdout)['revocation'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for human review UI')
    def test_human_review_ui_safe_text_and_exact_resume_intent(self):
        from spikes.desktop_ui import JS
        function='async function showIdeBridgeMessages(projectId){'+JS.split('async function showIdeBridgeMessages(projectId){',1)[1].split('\nfunction renderIdeBridgeProjects()',1)[0]
        harness=r'''
const assert=require('node:assert/strict');
class Element{constructor(tag){this.tag=tag;this.children=[];this.textContent='';}append(...items){this.children.push(...items);}replaceChildren(){this.children=[];}addEventListener(_name,fn){this.click=fn;}set innerHTML(_value){throw Error('unsafe HTML');}}
const target=new Element('root'),document={querySelector:()=>target,createElement:tag=>new Element(tag)},crypto={randomUUID:()=> 'operation'};
let prompts=0,requests=[],data={current_head:'a'.repeat(40),sessions:[{session_id:'session',connection_id:'parent',commit_id:'a'.repeat(40),messages:[{message:{message_id:'message',task_id:'TASK-01',kind:'progress',body:'<img onerror=bad>',repository_commit:'b'.repeat(40),checklist:[{index:0,checked:true}]},task_preview:{checklist:[{text:'Verified condition'}]},receipt:{status:'received'}}]}]};
const window={prompt:()=>{prompts++;return 'Reviewed';},confirm:text=>{assert.match(text,/Verified condition/);return true;}};
async function projectRequest(route,body){if(route.endsWith('/status'))return data;requests.push(body);return {};}
'''
        checks=r'''
(async()=>{
 await showIdeBridgeMessages('project');
 const article=target.children[0];assert.match(article.children[0].textContent,/<img onerror=bad>/);
 await article.children.find(e=>e.tag==='button').click();assert.equal(prompts,1);
 assert.equal(requests[0].expected_head,data.current_head);assert.equal(requests[0].decision,'accepted');
 const intent={project_id:'project',session_id:'session',message_id:'message',decision:'accepted',note:'original',expected_head:'a'.repeat(40),operation_id:'durable-operation'};
 data.sessions[0].messages[0].review={state:'prepared',request:intent};
 await showIdeBridgeMessages('project');await target.children[0].children.find(e=>e.tag==='button').click();
 assert.equal(prompts,1);assert.deepEqual(requests.at(-1),intent);
 delete data.sessions[0].messages[0].review;data.current_head='c'.repeat(40);
 await showIdeBridgeMessages('project');assert.equal(target.children[0].children.find(e=>e.tag==='button').disabled,true);
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result=subprocess.run(['node','-e',harness+function+checks],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
