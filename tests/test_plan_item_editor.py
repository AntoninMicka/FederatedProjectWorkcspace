# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import shutil
import subprocess
import unittest
from uuid import uuid4

from spikes.metadata import ValidationError
from spikes.plan_item_editor import PlanItems, item_span
from spikes.projects import Projects
from tests import test_artifact_actions as artifact_tests


BODY = '''<!-- fpw-plan-profile: software-development/v1 -->
# Roadmapa — zachovat komentáře a formát
```md
- [ ] [TASK-01] Pouze příklad, nikoli definice
```
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - [ ] [BATCH-01] Dávka
    - type: batch
    <!-- vlastní neznámý komentář -->
    - [ ] [TASK-01] První
      - type: task
      - Popis s háčky
      - [ ] Podmínka

    - [ ] [TASK-02] Druhý
      - type: task
      - depends_on: TASK-01

# Konec — mimo položky
'''


class PlanItemTests(unittest.TestCase):
    def setUp(self):
        artifact_tests.ArtifactActionTests.setUp(self)
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Roadmapa', body=BODY.replace('\n', '\r\n'), new=False), str(uuid4()))['commit_id']
        self.editor = PlanItems(self.node)

    def opened(self, task='TASK-01'):
        return self.editor.open(self.project, self.artifact, task, self.head)

    def request(self, model=None, **changes):
        model = model or self.opened()
        return {k: model[k] for k in ('project_id', 'artifact_id', 'task_id', 'expected_head', 'fragment_sha256', 'body')} | changes

    def test_only_own_block_is_loaded_and_only_its_bytes_are_saved(self):
        model = self.opened(); self.assertNotIn('TASK-02', model['body'])
        self.assertNotIn('Pouze příklad', model['body']); self.assertNotIn('# Konec', model['body'])
        batch = self.opened('BATCH-01')
        self.assertNotIn('TASK-01', batch['body']); self.assertIn('neznámý komentář', batch['body'])
        git = Projects(self.node).repository(self.project); before = git.snapshot(self.head)
        request = self.request(model, body=model['body'].replace('První', 'Upravený').replace('[ ] Podmínka', '[x] Podmínka'))
        operation = str(uuid4()); result = self.editor.save(request, operation)
        self.assertEqual(result, self.editor.save(request, operation))
        after = git.snapshot(result['commit_id']); path = f'artifacts/{self.artifact}/content.md'
        self.assertEqual({path}, {p for p in before if before[p] != after[p]})
        self.assertEqual(before[path].replace(model['body'].encode(), request['body'].encode(), 1), after[path])
        with self.assertRaises(ValidationError): self.editor.save(request | {'body': request['body']+'\n'}, operation)

    def test_invalid_scope_ids_dependencies_hierarchy_and_stale_revision_do_not_write(self):
        model = self.opened(); before = Projects(self.node).repository(self.project).snapshot(self.head)
        for changes in [dict(fragment_sha256='0'*64), dict(expected_head='0'*40),
                        dict(body=model['body'].replace('TASK-01', 'TASK-99')),
                        dict(body=model['body']+'    - [ ] [TASK-03] Injected\r\n      - type: task\r\n'),
                        dict(body=model['body']+'      - depends_on: TASK-02\r\n'),
                        dict(body=model['body'].replace('type: task', 'type: batch')),
                        dict(body=model['body']+'# Unrelated heading\r\n'),
                        dict(body=model['body'].rstrip()), dict(body='\0')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.editor.save(self.request(model, **changes), str(uuid4()))
        git = Projects(self.node).repository(self.project)
        self.assertEqual(self.head, git.head()); self.assertEqual(before, git.snapshot(self.head))
        with self.assertRaises(ValueError): self.opened('TASK-99')
        with self.assertRaises(ValueError): self.editor.open(self.project, str(uuid4()), 'TASK-01', self.head)

    def test_writer_recovery_at_prepare_files_commit_and_index_replays_exactly_once(self):
        for stage in ('prepared', 'files-applied', 'ref-updated', 'indexed', 'completed'):
            model = self.opened(); request = self.request(model, body=model['body'].replace('První', stage))
            # Each iteration must have a real change.
            request['body'] = request['body'].replace('type: task', 'type: task\r\n      - '+stage)
            operation = str(uuid4())
            def stop(current):
                if current == stage: raise RuntimeError('power loss')
            with self.subTest(stage=stage), self.assertRaises(RuntimeError):
                self.editor.save(request, operation, checkpoint=stop)
            result = self.editor.save(request, operation)
            self.assertEqual(result, self.editor.save(request, operation))
            git = Projects(self.node).repository(self.project)
            self.assertEqual('1', git.run('rev-list', '--count', self.head+'..'+result['commit_id']).stdout.strip())
            self.head = result['commit_id']
            self.assertEqual(request['body'], self.opened()['body'])
            self.assertEqual(self.head, Projects(self.node).open(self.project)['commit_id'])

    def test_item_in_referenced_definition_document_preserves_main_roadmap(self):
        external = str(uuid4())
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=external,
            base_head=self.head, title='Definitions', new=True,
            body='<!-- fpw-plan-document: definitions/v1 -->\n- [ ] [TASK-EXT] External\n  - type: task\n'), str(uuid4()))['commit_id']
        root = ('<!-- fpw-plan-profile: software-development/v1 -->\n'
                '- [ ] [MILESTONE-01] Milník\n  - type: milestone\n'
                f'  - [ ] [BATCH-01] [Dávka](artifacts/{external}/content.md)\n    - type: batch\n')
        self.head = self.actions.save(dict(project_id=self.project, artifact_id=self.artifact,
            base_head=self.head, title='Roadmapa', new=False, body=root), str(uuid4()))['commit_id']
        git = Projects(self.node).repository(self.project); before = git.snapshot(self.head)
        model = self.editor.open(self.project, external, 'TASK-EXT', self.head)
        self.assertEqual('BATCH-01', model['parent_id'])
        result = self.editor.save(self.request(model, body=model['body'].replace('External', 'Edited')), str(uuid4()))
        after = git.snapshot(result['commit_id'])
        self.assertEqual({f'artifacts/{external}/content.md'}, {p for p in before if before[p] != after[p]})

    def test_frontmatter_bytes_and_neighboring_text_are_preserved(self):
        import yaml
        git = Projects(self.node).repository(self.project); files = git.snapshot(self.head)
        sidecar = f'artifacts/{self.artifact}/metadata.json'; path = f'artifacts/{self.artifact}/content.md'
        metadata = json.loads(files[sidecar])
        metadata.pop('file')
        prefix = ('---\n# Preserve YAML comment and ordering\n'+yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False)+'---\n').encode()
        changes = {sidecar: None, path: prefix+files[path]}
        workspace = self.editor.projects.workspace(self.project)
        self.head = workspace.transact(str(uuid4()), {'fixture':'frontmatter'},
            lambda ws: (changes, 'Fixture', 'fixture@local.invalid', 'Frontmatter fixture'), expected_head=self.head)['commit_id']
        model = self.opened(); body = model['body'].replace('První', 'Edited')
        result = self.editor.save(self.request(model, body=body), str(uuid4()))
        self.assertEqual(changes[path].replace(model['body'].encode(), body.encode(), 1), git.snapshot(result['commit_id'])[path])

    def test_authenticated_http_open_save_rejects_filesystem_fields(self):
        from spikes.desktop_ui import DesktopHandler
        from spikes.local_api import running_api
        from tests.test_local_api import LocalAPITests
        driver = LocalAPITests()
        request = dict(project_id=self.project, artifact_id=self.artifact, task_id='TASK-01', expected_head=self.head)
        with running_api('http', handler=DesktopHandler, projects=Projects(self.node)) as server:
            path = '/v1/artifacts/editor/plan-item/open'
            response = driver.request(server, path=path, body=json.dumps(request).encode())
            self.assertTrue(response.startswith(b'HTTP/1.0 200'), response)
            model = json.loads(response.split(b'\r\n\r\n', 1)[1])
            self.assertNotIn('TASK-02', model['body'])
            driver.rejected(server, path=path, body=json.dumps(request).encode(), headers={'Authorization': None})
            driver.rejected(server, path=path, body=json.dumps(request | {'path': '/etc/passwd'}).encode())
            save = dict(operation_id=str(uuid4()), item=self.request(model, body=model['body'].replace('První', 'HTTP')))
            response = driver.request(server, path='/v1/artifacts/editor/plan-item/save', body=json.dumps(save).encode())
            self.assertTrue(response.startswith(b'HTTP/1.0 200'), response)

    def test_network_privacy_rejects_open_and_save_before_writing(self):
        self.head = self.artifacts.save(dict(project_id=self.project, artifact_id=str(uuid4()),
            base_head=self.head, title='Private', body='Local data', new=True),
            str(uuid4()), privacy='local-only')['commit_id']
        model = self.opened(); network = PlanItems(self.node, network=True)
        with self.assertRaisesRegex(ValueError, 'local-only'):
            network.open(self.project, self.artifact, 'TASK-01', self.head)
        with self.assertRaisesRegex(ValueError, 'local-only'):
            network.save(self.request(model, body=model['body'].replace('První', 'Denied')), str(uuid4()))
        self.assertEqual(self.head, Projects(self.node).repository(self.project).head())


class SpanTests(unittest.TestCase):
    def test_fenced_examples_and_child_nodes_do_not_change_physical_offsets(self):
        start, end = item_span(BODY, 'TASK-01')
        self.assertTrue(BODY[start:end].startswith('    - [ ] [TASK-01] První\n'))
        self.assertTrue(BODY[end:].startswith('\n    - [ ] [TASK-02]'))
        with self.assertRaises(ValueError): item_span(BODY, 'UNKNOWN-01')

    @unittest.skipUnless(shutil.which('node'), 'Node required for editor controls')
    def test_scoped_editor_preserves_dirty_guard_draft_and_operation_on_lost_reply(self):
        from spikes.desktop_ui import JS
        fill = JS[JS.index('function fillArtifactEditor('):JS.index('async function closeArtifactEditor(')]
        controls = JS[JS.index('async function openPlanItemEditor('):JS.index('async function openNewArtifactEditor(')]
        harness = r'''
const assert=require('node:assert/strict');
const field=()=>({value:'',disabled:false,readOnly:false,label:{hidden:false},closest(){return this.label;},focus(){}});
const elements=new Map(),button={disabled:false};
const document={querySelector(id){if(!elements.has(id))elements.set(id,{textContent:''});return elements.get(id);}};
const artifactEditorForm={elements:Object.fromEntries(['body','title','filename','description','tags'].map(n=>[n,field()])),querySelector:()=>button};
let activeProject={id:'p',head:'h',mainTodoId:'main',readOnly:false},artifactEditorItem=null,artifactEditorAttempt=null,artifactEditorBaseline=null,artifactEditorDirty=false;
let allow=false,failed=true,calls=[],filled=[],artifactEditorView={hidden:true},taskPlanProjection={nodes:[]};
const artifactEditorStatus={textContent:''},artifactRawWidget={configure:()=>Promise.resolve()};
const crypto={randomUUID:()=>String(calls.length)};
function resetTaskFileEditEditor(){}function artifactEditorState(){return artifactEditorForm.elements.body.value;}function configureTaskPlanEditor(){}
function hideArtifactDeletion(){}function showWorkspacePage(v){v.hidden=false;}async function canLeaveWorkspaceEditors(){return allow;}
const model={project_id:'p',artifact_id:'a',task_id:'TASK-01',expected_head:'h',fragment_sha256:'digest',body:'one item',title:'Title'};
async function projectRequest(path,request){calls.push({path,request});if(path.endsWith('/open'))return model;if(failed)throw Error('unknown');return {project_id:'p',commit_id:'new'};}
'''
        checks = r'''
(async()=>{
const task={id:'TASK-01',source:{artifact_id:'a'}};
await openPlanItemEditor(task);assert.equal(calls.length,0,'dirty guard cancellation');
allow=true;await openPlanItemEditor(task);assert.equal(calls.length,1);assert.equal(artifactEditorForm.elements.body.value,'one item');
assert.equal(artifactEditorForm.elements.title.disabled,true);assert.equal(artifactEditorForm.elements.title.label.hidden,true);
artifactEditorForm.elements.body.value='draft';artifactEditorDirty=true;
assert.equal(await savePlanItemEditor(false),false);const attempt=artifactEditorAttempt;
assert.equal(artifactEditorForm.elements.body.value,'draft');assert(artifactEditorDirty);assert.equal(button.disabled,false);assert.equal(artifactEditorForm.elements.body.readOnly,false);
assert.equal(await savePlanItemEditor(false),false);assert.equal(artifactEditorAttempt,attempt);assert.equal(calls.at(-1).request.operation_id,attempt.operation_id);
failed=false;assert.equal(await savePlanItemEditor(false),true);assert.equal(activeProject.head,'new');assert.equal(artifactEditorDirty,false);
fillArtifactEditor({title:'Whole document',body:'content'});assert.equal(artifactEditorForm.elements.title.disabled,false);assert.equal(artifactEditorForm.elements.title.label.hidden,false);
})().catch(error=>{console.error(error);process.exit(1);});
'''
        result = subprocess.run(['node', '-e', harness+fill+controls+checks], capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)
