# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""The document preview preserves nested roadmap lists without rewriting input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from spikes.desktop_ui import JS
from spikes.task_graph import parse_main_todo
from tests import test_task_graph as graph_fixtures

ROADMAP='''<!-- fpw-plan-profile: software-development/v1 -->
- [ ] [MILESTONE-MON] Monitoring
  - type: milestone
  - [ ] [MON-08] Refaktorizace a upřesnění Monitoringu
    - status: planned
    - type: batch
    - Cíl rozšíření
      - Propojený systém sběru a zpráv.
    - Oddělit:
      - Sběr: kdy a odkud se získávají položky.
      - Výstup: kdy vzniká zpráva.

    - [ ] [MON-08-01] Datový model samostatných sledování
      - status: planned
      - type: task
      - Rozsah:
        - Každé sledování má:
          - stabilní identitu;
          - pravidla vyhodnocení.
      - Akceptace:
        - Změna definice nepřepisuje historii.

    - [ ] [MON-08-02] Konektory
      - type: task
      - RSS/Atom a uložené výstupy.
  - [ ] [MON-09] Další dávka
    - type: batch
'''

class MarkdownHierarchyTests(unittest.TestCase):
    def test_backend_keeps_child_task_out_of_batch_description(self):
        nodes,_=parse_main_todo(ROADMAP)
        self.assertEqual(nodes['MON-08-01']['parent_id'],'MON-08')
        self.assertEqual(nodes['MON-08-01']['type'],'task')
        self.assertNotIn('Rozsah:',nodes['MON-08']['description_lines'])
        self.assertIn('Rozsah:',nodes['MON-08-01']['description_lines'])

    def test_graph_projection_keeps_nested_description_and_separate_children(self):
        graph=graph_fixtures.TaskGraphTests().fixture(ROADMAP)
        self.assertEqual(graph['status'],'ready')
        nodes={node['id']:node for node in graph['nodes']}
        self.assertIn('- Cíl rozšíření\n  - Propojený systém',nodes['MON-08']['description_markdown'])
        self.assertNotIn('Datový model',nodes['MON-08']['description_markdown'])
        self.assertIn('- Rozsah:\n  - Každé sledování má:\n    - stabilní identitu;',nodes['MON-08-01']['description_markdown'])
        self.assertEqual(nodes['MON-08-01']['parent_id'],'MON-08')

    def test_renderer_preserves_ownership_blank_lines_dedent_safety_and_diff_lines(self):
        source=JS[JS.index('function addConflictLineClasses('):JS.index('const projectConflicts=')]
        script=r'''
const assert=require('node:assert/strict');
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.value='';this.classes=[];this.classList={add:name=>this.classes.push(name)};}
 append(...nodes){this.children.push(...nodes);}
 set textContent(value){this.value=value;this.children=[];}
 get textContent(){return this.value+this.children.map(c=>c.textContent).join('');}
 set innerHTML(value){throw Error('HTML injection is forbidden');}
 addEventListener(){}
}
const document={createElement:tag=>new Element(tag),createTextNode:text=>{const e=new Element('#text');e.textContent=text;return e;}};
const previewContent=new Element('main');
function openPreview(){}
'''+source+'\nconst markdown='+json.dumps(ROADMAP)+r''';
renderMarkdown(markdown,previewContent,new Map([[18,['diff-added']]]));
function all(root,tag){return root.children.flatMap(c=>[...(c.tag===tag?[c]:[]),...all(c,tag)]);}
function ownText(node){return node.value+node.children.filter(c=>c.tag!=='ul').map(c=>c.textContent).join('');}
const items=all(previewContent,'li'),find=text=>items.find(n=>ownText(n).includes(text));
const batch=find('[MON-08]'),task=find('[MON-08-01]'),other=find('[MON-09]');
const children=n=>n.children.find(c=>c.tag==='ul').children;
assert(children(batch).includes(task),'blank line must preserve the task under its batch');
assert(!children(batch).includes(other),'dedent must close the batch');
assert(children(task).includes(find('Rozsah:')),'scope belongs to the task');
assert(children(find('Každé sledování má:')).includes(find('stabilní identitu;')));
assert(find('pravidla vyhodnocení.').classes.includes('diff-added'));
assert.equal(children(batch).filter(n=>ownText(n).includes('[MON-08-')).length,2);
const target=new Element('main');renderMarkdown('- first\n\t- tab child\n\n- second\n# Heading\n- third\n```\n- literal\n```\n<script>unsafe()</script>',target);
assert.equal(target.children.filter(c=>c.tag==='ul').length,2);
assert.equal(all(target,'li').length,4);assert.equal(all(target,'pre')[0].textContent,'- literal\n');
assert.equal(all(target,'script').length,0);assert(target.textContent.includes('<script>'));
const links=new Element('main');
renderMarkdown('- [Podklad](artifacts/11111111-1111-4111-8111-111111111111/content.md)',previewContent);
assert.equal(all(previewContent,'button').length,1);
'''
        result=subprocess.run(['node','-e',script],text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_real_webengine_keeps_tasks_and_description_lists_nested(self):
        script=r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile,QWebEngineScript
from spikes.desktop_ui import DesktopHandler
from spikes.local_api import running_api
from tests.test_markdown_hierarchy import ROADMAP
from tests.test_task_graph import TaskGraphTests
app=QApplication([])
with running_api('http',handler=DesktopHandler) as server:
 profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app)
 bootstrap=QWebEngineScript();bootstrap.setInjectionPoint(QWebEngineScript.DocumentCreation);bootstrap.setWorldId(QWebEngineScript.MainWorld);bootstrap.setSourceCode('window.workspaceAutoStart=false;');page.scripts().insert(bootstrap)
 plan=TaskGraphTests().fixture(ROADMAP)
 command="""(()=>{if(typeof renderMarkdown!=='function')return 'waiting';const target=document.querySelector('#preview-content');target.replaceChildren();renderMarkdown(SOURCE,target);const items=[...target.querySelectorAll('li')],own=n=>[...n.childNodes].filter(c=>c.nodeName!=='UL').map(c=>c.textContent).join(''),find=t=>items.find(n=>own(n).includes(t)),children=n=>[...n.querySelector(':scope > ul').children];const batch=find('[MON-08]'),task=find('[MON-08-01]');if(!(children(batch).includes(task)&&children(task).includes(find('Rozsah:'))&&!children(batch).includes(find('[MON-09]'))))return 'preview failed';taskPlanProjection=PLAN;showTaskPlanDetail(taskPlanProjection.nodes.find(n=>n.id==='MON-08'));const detail=document.querySelector('#plan-detail'),description=[...detail.querySelectorAll('dt')].find(e=>e.textContent==='Popis').nextElementSibling;if(!description.querySelector('ul li ul li'))return 'description flattened';const link=detail.querySelector('[data-plan-child=MON-08-01]');if(!link||detail.querySelector('[data-plan-child=MON-09]'))return 'children mixed';link.click();if(!detail.querySelector('h3').textContent.includes('MON-08-01'))return 'child navigation failed';const scope=[...detail.querySelectorAll('dt')].find(e=>e.textContent==='Popis').nextElementSibling;if(!scope.querySelector('ul li ul li ul li'))return 'scope flattened';renderTaskPlanSidebar({status:'invalid',error:'Duplicitní ID úkolu: MON-08-01',nodes:[],subgraphs:[]});return document.querySelector('#sidebar-plan-status').textContent.includes('MON-08-01')?'ok':'hidden validation error';})()""".replace('SOURCE',json.dumps(ROADMAP)).replace('PLAN',json.dumps(plan))
 def received(value):
  if value=='waiting':return
  print('nested roadmap browser',value,flush=True);app.exit(0 if value=='ok' else 2)
 timer=QTimer();timer.timeout.connect(lambda:page.runJavaScript(command,received));timer.start(150)
 page.setUrl(QUrl(server.origin+'/'))
 QTimer.singleShot(15000,lambda:app.exit(3))
 result=app.exec();page.deleteLater();profile.deleteLater();raise SystemExit(result)
'''
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],text=True,capture_output=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('nested roadmap browser ok',result.stdout)
