# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Startup background reads cannot fan out across all project owners."""
from pathlib import Path
import os
import sys
import shutil
import subprocess
import unittest
from unittest.mock import patch
from uuid import uuid4

from spikes.desktop_management import DesktopManagementHandler
from spikes.federation_sync import ContentSyncControl, _database
from spikes.journal import snapshot
from spikes.local_api import running_api
from spikes.markdown_documents import main_todo_id
from spikes.project_creation import ProjectCreation, CreationConflict
from spikes.request_ownership import ProjectBusy
from spikes.workspace import PendingOperation
from tests import test_artifacts as artifacts
from tests import test_project_http_ownership as ownership
from tests.test_workspace_navigation import function


class DashboardProjectionTests(unittest.TestCase):
    setUp = artifacts.ArtifactTests.setUp
    request = artifacts.ArtifactTests.request
    post = ownership.ProjectHTTPOwnershipTests.post

    def test_dashboard_reads_committed_todo_without_history_graph_or_dirty_draft(self):
        request = self.request(id_=main_todo_id(self.id), body='- [ ] Committed\n')
        self.service.save(request, str(uuid4()))
        (self.root / 'artifacts' / request['artifact_id'] / 'content.md').write_text('- [x] Draft\n')
        before = snapshot(self.root); head = self.git.head()
        from spikes.storage import Git
        original = Git.run
        def no_history(git, *args, **kwargs):
            self.assertNotIn(args[0], ('rev-list', 'log'))
            return original(git, *args, **kwargs)
        with patch.object(Git, 'run', no_history), \
                patch('spikes.workspace.project_task_graph', side_effect=AssertionError('Unneeded graph')):
            result = self.service.projects.dashboard_view(self.id)
        self.assertEqual(result['main_todo']['items'][0]['title'], 'Committed')
        self.assertNotIn('history', result)
        self.assertNotIn('plan_draft', result)
        self.assertNotIn('plan', result)
        self.assertEqual(result['commit_id'], head)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.git.head(), head)

    def test_dashboard_pending_is_retained_and_native_recovery_publishes_once(self):
        request = self.request(id_=main_todo_id(self.id))
        self.service.save(request, str(uuid4()))
        before = self.git.head()
        def crash(stage):
            if stage == 'prepared': raise RuntimeError('crash')
        with self.assertRaises(RuntimeError):
            self.service.save(self.request(id_=request['artifact_id'], body='- [ ] Updated\n', new=False),
                              str(uuid4()), checkpoint=crash)
        with self.assertRaises(PendingOperation): self.service.projects.dashboard_view(self.id)
        self.assertEqual(self.git.head(), before)
        self.service.open(self.id)
        self.assertEqual(self.service.projects.dashboard_view(self.id)['main_todo']['items'][0]['title'], 'Updated')
        self.assertEqual(self.git.run('rev-list', '--count', before+'..HEAD').stdout.strip(), '1')

    def test_dashboard_http_retains_project_ownership_and_authentication(self):
        with running_api('http', handler=DesktopManagementHandler, projects=self.service.projects) as server:
            body = {'project_id': self.id, 'scope': 'dashboard'}
            with server.project_lanes.acquire(self.id, .1):
                self.assertEqual(self.post(server, '/v1/projects/open', body, token='bad')[0], 401)
                code, result, _ = self.post(server, '/v1/projects/open', body)
                self.assertEqual(code, 503, result)
                self.assertEqual(result['outcome'], 'not-started')
            code, result, _ = self.post(server, '/v1/projects/open', body)
            self.assertEqual(code, 200, result)
            self.assertIn('main_todo', result)
            self.assertNotIn('history', result)
            for scope in (None, [], {}, 'unknown'):
                self.assertEqual(self.post(server, '/v1/projects/open',
                    {'project_id': self.id, 'scope': scope})[0], 400)

    def test_sync_registry_lock_is_busy_but_semantic_creation_conflict_is_error(self):
        control = ContentSyncControl(self.node, deployment='desktop')
        peer, operation = str(uuid4()), str(uuid4())
        with _database(self.node) as db:
            db.execute('INSERT INTO outbound VALUES (?,?,?,?,?,?)',
                       (peer, self.id, operation, '{}', b'original payload', '[]'))
        creator = ProjectCreation(self.node)
        with creator._locked():
            with self.assertRaises(CreationConflict): creator.author_id()
            with patch('spikes.federation_sync.synchronize', side_effect=lambda *a, **k: creator.author_id()), \
                    self.assertRaises(ProjectBusy):
                control.synchronize(peer, self.id)
        self.assertEqual(control.statuses()[peer+':'+self.id]['state'], 'busy')
        with patch('spikes.federation_sync.synchronize', side_effect=CreationConflict('Invalid persistent state')), \
                self.assertRaises(CreationConflict):
            control.synchronize(peer, self.id)
        self.assertEqual(control.statuses()[peer+':'+self.id]['state'], 'error')
        with _database(self.node) as db:
            self.assertEqual(db.execute('SELECT operation_id,bundle FROM outbound').fetchone(),
                             (operation, b'original payload'))


@unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
class StartupAdmissionTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires actual Qt/WebEngine')
    def test_real_webengine_startup_and_foreground_project_open(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, '-m', 'tests.ui.project_open_latency_smoke'],
            cwd=root, env=dict(os.environ, QT_QPA_PLATFORM='offscreen',
                QTWEBENGINE_CHROMIUM_FLAGS='--no-sandbox --disable-gpu'),
            capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_dashboard_is_single_flight_lazy_and_yields_to_foreground_navigation(self):
        script = r'''
const assert=require('node:assert/strict');
const elements=new Map();const document={querySelector:s=>{if(!elements.has(s))elements.set(s,{hidden:false,textContent:'',replaceChildren(){},append(){}});return elements.get(s);}};
let catalogRequest=1,activeProject=null,active=0,maximum=0,calls=[],cancelAfterFirst=false,selected=null;
const items=Array.from({length:20},(_,i)=>({id:String(i),available:true,title:'Project '+i}));
async function projectRequest(path,body){
 calls.push([path,body]);
 if(path==='/v1/projects')return {projects:items};
 assert.equal(path,'/v1/projects/open');assert.equal(body.scope,'dashboard');
 active++;maximum=Math.max(maximum,active);await new Promise(resolve=>setTimeout(resolve,1));active--;
 if(cancelAfterFirst)catalogRequest++;
 return {main_todo:null};
}
async function canLeaveWorkspaceEditors(){return true;}
function clearProject(){}function showProjectLanding(){}
function renderProjectCatalog(){}function loadProjectTrash(){throw Error('Hidden trash loaded');}function loadChat(){throw Error('Hidden chat loaded');}
const projectCards={replaceChildren(){}},sidebarProjects={replaceChildren(){}},projectStatus={};
async function openRegisteredProject(id){selected=id;catalogRequest++;}
'''+function('loadDashboardTasks')+'\n'+function('loadProjects')+r'''
(async()=>{
 await loadDashboardTasks(items,catalogRequest);assert.equal(calls.length,20);assert.equal(maximum,1);
 calls=[];cancelAfterFirst=true;await loadDashboardTasks(items,catalogRequest);assert.equal(calls.length,1);
 calls=[];cancelAfterFirst=false;document.querySelector('#project-home').hidden=true;
 await loadProjects();assert.equal(calls.length,1);assert.equal(calls[0][0],'/v1/projects');
 document.querySelector('#project-home').hidden=false;calls=[];
 await loadProjects('2');assert.equal(selected,'2');assert.equal(calls.length,1);
 calls=[];await loadProjects();assert.equal(calls.length,21);assert.equal(maximum,1);
 console.log('bounded startup OK');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertIn('bounded startup OK', result.stdout)
