# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from spikes.artifact_actions import ArtifactActions
from spikes.artifacts import Artifacts
from spikes.markdown_documents import main_todo_id
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git

BODY='''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-01] Milník
  - type: milestone
  - Popis milníku.
  - [ ] [BATCH-01] Dávka
    - type: batch
    - Popis dávky.
    - [ ] [TASK-01] První úkol
      - type: task
      - Popis prvního úkolu.
'''
PARTIAL=BODY+'''    - [ ] [TASK-02] Druhý, právě dopisovaný úkol
      - Rozsah:
        - Rozepsaný text bez hotových metadat.
'''

class PlanDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.node=self.root/'node.json';self.project_root=self.root/'project'
        self.pid=ProjectCreation(self.node).create('Draft plan',self.project_root,str(uuid4()))['id']
        self.aid=main_todo_id(self.pid);self.projects=Projects(self.node);self.git=Git(self.project_root)
        Artifacts(self.node).save(dict(project_id=self.pid,artifact_id=self.aid,base_head=self.git.head(),
            title='Roadmapa',body=BODY,new=True),str(uuid4()))
        self.head=self.git.head();self.path=self.project_root/'artifacts'/self.aid/'content.md'
        self.before=self.projects.open(self.pid)

    def test_incremental_external_edit_is_visible_without_commit_or_acceptance(self):
        self.path.write_text(PARTIAL)
        view=self.projects.open(self.pid)
        self.assertEqual(view['commit_id'],self.head)
        self.assertEqual(view['plan'],self.before['plan'])
        draft=view['plan_draft'];self.assertEqual(draft['status'],'draft');self.assertFalse(draft['draft_valid'])
        self.assertEqual(draft['text'],PARTIAL)
        self.assertEqual(len(draft['outline']),4)
        batch=next(row for row in draft['outline'] if row['id']=='BATCH-01')
        tasks=[r for r in draft['outline'] if r['parent_key']==batch['key']]
        self.assertEqual([r['id'] for r in tasks],['TASK-01','TASK-02'])
        self.assertNotIn('Druhý',batch['description_markdown'])
        # Even a complete draft remains unaccepted and outside the execution graph.
        self.path.write_text(PARTIAL+'      - type: task\n')
        draft=self.projects.open(self.pid)['plan_draft']
        self.assertTrue(draft['draft_valid']);self.assertEqual(draft['status'],'draft');self.assertEqual(draft['nodes'],[])
        self.assertEqual(self.git.head(),self.head);self.assertTrue(self.git.run('status','--porcelain').stdout)

    def test_frozen_preview_and_default_editor_keep_commit_bytes_explicit_editor_reads_draft(self):
        self.path.write_text(PARTIAL);actions=ArtifactActions(self.node)
        self.assertEqual(self.projects.preview(self.pid,self.aid,self.head)['text'],BODY)
        self.assertEqual(actions.open(self.pid,self.aid,self.head)['document']['body'],BODY)
        draft=actions.open(self.pid,self.aid,self.head,include_working_draft=True)['document']
        self.assertEqual(draft['body'],PARTIAL);self.assertTrue(draft['working_draft'])
        self.assertEqual(self.path.read_text(),PARTIAL);self.assertEqual(self.git.head(),self.head)

    def test_network_never_reads_or_discloses_local_working_draft(self):
        self.path.write_text(PARTIAL+'      - private-draft-sentinel\n')
        view=Projects(self.node,network=True).open(self.pid)
        self.assertNotIn('plan_draft',view);self.assertNotIn('private-draft-sentinel',json.dumps(view))
        result=ArtifactActions(self.node,network=True).open(self.pid,self.aid,self.head,include_working_draft=True)
        self.assertEqual(result['document']['body'],BODY)

    def test_missing_unsafe_or_oversized_draft_is_explicit_and_never_silently_current(self):
        secret=self.root/'private';secret.write_text('private-sentinel')
        self.path.unlink();self.path.symlink_to(secret)
        view=self.projects.open(self.pid)
        self.assertNotIn('plan_draft',view);self.assertIn('plan_draft_error',view)
        self.assertNotIn('private-sentinel',json.dumps(view))
        self.path.unlink();self.path.write_bytes(b'x'*(1024*1024+1))
        view=self.projects.open(self.pid);self.assertIn('plan_draft_error',view)
        self.assertEqual(self.git.head(),self.head)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_real_ui_reads_partial_disk_plan_preview_and_editor_without_commit(self):
        script=r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineScript
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from spikes.projects import Projects
from spikes.chat_service import ChatService
from tests.test_plan_draft import PlanDraftTests,PARTIAL
app=QApplication([]);fixture=PlanDraftTests();fixture.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=fixture.projects) as server:
  server.chat_service=ChatService(fixture.node,fixture.projects)
  profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app)
  bootstrap=QWebEngineScript();bootstrap.setInjectionPoint(QWebEngineScript.DocumentCreation);bootstrap.setWorldId(QWebEngineScript.MainWorld);bootstrap.setSourceCode('window.workspaceAutoStart=false;');page.scripts().insert(bootstrap)
  phase=0;busy=False
  commands={1:'window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};openRegisteredProject('+json.dumps(fixture.pid)+').then(()=>window.openDone=true)',2:'openTaskPlan()',3:'openPreview('+json.dumps(fixture.aid)+')',4:'openArtifactEditor({id:'+json.dumps(fixture.aid)+',kind:"document"})',5:'openTaskPlan().then(()=>openArtifactEditor({id:'+json.dumps(fixture.aid)+',kind:"document"}))'}
  checks={0:"typeof openTaskPlan==='function'",1:"window.openDone===true",2:"taskPlanProjection?.status==='ready'&&!taskPlanProjection.nodes.some(n=>n.id==='TASK-02')&&!document.querySelector('#plan-source-controls')",3:"document.querySelector('#preview-content').textContent.includes('Druhý, právě dopisovaný úkol')&&document.querySelector('#preview-status').textContent.includes('Pracovní soubor')",4:"artifactEditorForm.elements.body.value===PARTIAL&&artifactEditorForm.elements.body.readOnly&&artifactEditorForm.querySelector('button[type=submit]').disabled&&document.querySelectorAll('#task-plan-blocks [data-plan-outline]').length===4",5:"artifactEditorForm.elements.body.value.includes('TASK-03')&&document.querySelectorAll('#task-plan-blocks [data-plan-outline]').length===5"}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==2:fixture.path.write_text(PARTIAL)
   if phase==5:fixture.path.write_text(PARTIAL+'    - [ ] [TASK-03] Další ručně dopsaný úkol\n')
   if phase==6:
    assert fixture.git.head()==fixture.head
    print('working plan browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase].replace('PARTIAL',json.dumps(PARTIAL))+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(150);page.setUrl(QUrl(server.origin+'/'))
  QTimer.singleShot(20000,lambda:(print('timeout phase',phase,flush=True),app.exit(2)))
  result=app.exec();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:fixture.doCleanups()
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('working plan browser OK',result.stdout)
