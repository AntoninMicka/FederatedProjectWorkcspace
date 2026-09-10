"""Real sidebar action uses the native editor; cancel never creates a TODO."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from spikes.project_creation import ProjectCreation
from spikes.projects import Projects


class SidebarEditorTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_create_cancel_save_and_sidebar_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            node = Path(tmp) / 'node.json'
            project = ProjectCreation(node).create('Úkoly projektu', str(Path(tmp) / 'project'), str(uuid4()))
            script = r"""
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from spikes import desktop_ui, desktop
from spikes.desktop_editor import EditorDialog
from spikes.projects import Projects
node, project_id = sys.argv[1:]
original_exec = EditorDialog.exec
opened = []
def editor_exec(dialog):
    opened.append(dialog.project_id)
    assert dialog.project_id == project_id
    timer = QTimer(dialog)
    def ready():
        if dialog.busy or dialog.current is None: return
        timer.stop()
        assert dialog.current['id'] == dialog.view['main_todo_id']
        assert dialog.current['new']
        assert Projects(node).open(project_id)['main_todo'] is None
        if len(opened) == 1:
            # Exercise the real discard confirmation for the unsaved proposal.
            QTimer.singleShot(0, lambda: QApplication.activeModalWidget().button(
                QMessageBox.StandardButton.Discard).click())
            dialog.reject()
        else:
            dialog.body.setPlainText('# Úkoly\n\n- [ ] Domluvit schůzku\n')
            dialog.saved.connect(lambda *_: QTimer.singleShot(0, dialog.accept))
            dialog.save_button.click()
    timer.timeout.connect(ready); timer.start(30)
    result = original_exec(dialog)
    if len(opened) == 1:
        dialog.parent().centralWidget().page().runJavaScript('window.todoCancelled=true')
    return result
EditorDialog.exec = editor_exec
kind, js = desktop_ui.ASSETS['/app.js']
# The regular shell smoke clicks increment immediately; hold that until this flow passes.
js += r'''
let step=0;
document.querySelector('#increment').addEventListener('click',event=>{
 if(step!==3){event.stopImmediatePropagation();event.preventDefault();}
},true);
const todoSmoke=setInterval(()=>{
 const create=document.querySelector('#create-main-todo');
 if(step===0){const card=document.querySelector('.project-card');if(card){step=1;card.click();}return;}
 if(!activeProject)return;
 document.querySelector('#todo-tab').click();
 if(step===1 && !create.hidden){step=2;create.click();return;}
 if(step===2 && !create.hidden && window.todoCancelled){
  // The native modal has returned after cancellation.
  if(!window.retryAfterCancel){window.retryAfterCancel=true;create.click();}
  return;
 }
 if(step===2 && create.hidden && document.querySelector('#todo-tree').textContent.includes('Domluvit schůzku')){
  step=3;clearInterval(todoSmoke);document.querySelector('#increment').click();
 }
},100);
'''
desktop_ui.ASSETS['/app.js'] = (kind, js)
sys.argv = ['desktop', '--node', node, '--smoke']
result = desktop.main()
assert opened == [project_id, project_id], opened
assert result == 0, result
"""
            result = subprocess.run([sys.executable, '-c', script, str(node), project['id']],
                                    capture_output=True, text=True, timeout=25)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            view = Projects(node).open(project['id'])
            self.assertEqual(len(view['artifacts']), 1)
            self.assertEqual(view['main_todo']['items'][0]['title'], 'Domluvit schůzku')
