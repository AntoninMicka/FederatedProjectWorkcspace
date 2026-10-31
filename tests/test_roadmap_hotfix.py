# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import shutil
import os
from pathlib import Path
import subprocess
import sys
import unittest

from spikes.desktop_ui import JS


class RoadmapHotfixTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_full_conflict_layout_keeps_confirmation_above_prompt(self):
        result = subprocess.run([sys.executable, '-m', 'tests.roadmap_layout_smoke'],
                                cwd=Path(__file__).resolve().parent.parent,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
    def test_project_links_open_nested_documents_and_keep_unsafe_text_inert(self):
        helper = JS[JS.index('function appendProjectArtifactLinks('):JS.index('const projectConflicts=')]
        detail = JS[JS.index('function showTaskPlanDetail('):JS.index('function renderProfiledTaskRoadmap(')]
        script = r'''
const assert=require('node:assert/strict');
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.listeners={};this.classList={add(){}};this.textContent='';}
 append(...items){this.children.push(...items);}
 replaceChildren(){this.children=[];}
 addEventListener(name,fn){this.listeners[name]=fn;}
}
const previewContent=new Element('preview'),detail=new Element('detail'),opened=[];
const document={createElement:tag=>new Element(tag),createTextNode:text=>({textContent:text}),querySelector:()=>detail};
const openPreview=id=>opened.push(id),addConflictLineClasses=()=>{};
const buttons=el=>[...(el.tag==='button'?[el]:[]),...el.children?.flatMap(buttons)||[]];
''' + helper + detail + r'''
const id='12345678-1234-1234-1234-123456789abc';
const link='[Podklad](artifacts/'+id+'/content.md)';
showTaskPlanDetail({id:'DEV-02',title:'Task',description:link,depends_on:[],source:{artifact_id:id}});
assert.equal(buttons(detail).length,2);
buttons(detail)[0].listeners.click();buttons(detail)[1].listeners.click();
assert.deepEqual(opened,[id,id]);
renderMarkdown('- '+link,previewContent);
assert.equal(buttons(previewContent).length,1);buttons(previewContent)[0].listeners.click();
assert.equal(opened.length,3);
for(const value of ['[x](javascript:alert(1))','[x](https://example.com)', '<img src=x onerror=alert(1)>',
 '[x](../../secret)','[x](artifacts/not-an-id/content.md)']){
 const target=new Element('p');appendProjectArtifactLinks(target,value);
 assert.equal(buttons(target).length,0);assert.equal(target.children.map(x=>x.textContent).join(''),value);
}
previewContent.replaceChildren();renderMarkdown('```\n'+link+'\n```',previewContent);
assert.equal(buttons(previewContent).length,0);
const conflict=new Element('conflict');renderMarkdown(link,conflict);
assert.equal(buttons(conflict).length,0);
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
