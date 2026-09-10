"""Linux Qt/WebEngine shell around the existing local API; registered project reads."""
import argparse
import json
import os
import signal
import sys
from urllib.parse import urlsplit

from spikes.desktop_ui import ASSETS, DesktopHandler
from spikes.local_api import running_api
from spikes.projects import Projects
from spikes.project_creation import ProjectCreation, default_node_path


def request_policy(url, initiator, method, origin):
    """Fail closed before Qt can attach credentials or contact another origin."""
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        return 'block'
    if f'{parsed.scheme}://{parsed.netloc}' != origin:
        return 'block'
    if parsed.path in ASSETS and method == 'GET':
        return 'allow'
    if parsed.path in DesktopHandler.post_paths and method == 'POST' and initiator.rstrip('/') == origin:
        return 'authenticate'
    return 'block'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', help='Local node.json containing authorized project registrations.')
    parser.add_argument('--smoke', action='store_true', help='Run real WebEngine click test and exit.')
    parser.add_argument('--screenshot', help='Save the rendered window during --smoke.')
    parser.add_argument('--smoke-create', metavar='NEW_DIRECTORY', help='During --smoke, create a project through the native dialog.')
    parser.add_argument('--smoke-project', help='During --smoke, open this registered ID and verify rendered rows.')
    parser.add_argument('--smoke-crash', action='store_true', help='Kill renderer during --smoke; expect exit 1.')
    args = parser.parse_args()
    if args.smoke_create and (not (args.smoke and args.node) or args.smoke_project):
        parser.error('--smoke-create requires --smoke and --node; cannot combine with --smoke-project')
    if args.smoke_project and not (args.smoke and args.node):
        parser.error('--smoke-project requires --smoke and --node')
    if args.smoke_crash and not args.smoke:
        parser.error('--smoke-crash requires --smoke')
    if args.screenshot and not args.smoke:
        parser.error('--screenshot requires --smoke')
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtWidgets import QApplication, QMessageBox, QMainWindow, QPushButton
        from spikes.desktop_editor import EditorDialog
        from spikes.artifacts import Artifacts
        from spikes.desktop_creation import CreationController
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                          QWebEngineSettings, QWebEngineUrlRequestInterceptor)
    except ImportError:
        print('Chybí PySide6 WebEngine. Instalace viz README, sekce Desktop.', file=sys.stderr)
        return 1
    if os.geteuid() == 0:
        print('Desktop spouštějte jako běžný uživatel.', file=sys.stderr)
        return 1

    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            policy = request_policy(info.requestUrl().toString(), info.initiator().toString(),
                                    bytes(info.requestMethod()).decode(), server.origin)
            if policy == 'block':
                info.block(True)
            elif policy == 'authenticate':
                info.setHttpHeader(b'Authorization', ('Bearer ' + server.token).encode())

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, main_frame):
            return main_frame and url.toString() == server.origin + '/'

        def createWindow(self, kind):
            return None

    class View(QWebEngineView):
        closing = False

        def closeEvent(self, event):
            self.closing = True
            super().closeEvent(event)

    class Window(QMainWindow):
        def closeEvent(self, event):
            if controller.busy:
                event.ignore()
                return
            view.closing = True
            super().closeEvent(event)

    app = QApplication([sys.argv[0]])
    app.setApplicationName('Projektový workspace')
    node_path = args.node or default_node_path()
    with running_api('http', handler=DesktopHandler, projects=Projects(node_path)) as server:
        profile = QWebEngineProfile(app)  # unnamed => off the record
        interceptor = Interceptor(profile)
        profile.setUrlRequestInterceptor(interceptor)
        profile.downloadRequested.connect(lambda download: download.cancel())
        view = View()
        page = Page(profile, view)
        view.setPage(page)
        settings = page.settings()
        for setting in ('LocalContentCanAccessFileUrls', 'LocalContentCanAccessRemoteUrls',
                        'JavascriptCanOpenWindows', 'FullScreenSupportEnabled'):
            settings.setAttribute(getattr(QWebEngineSettings.WebAttribute, setting), False)
        window = Window()
        window.setCentralWidget(view)
        window.setWindowTitle('Projektový workspace · Zkušební verze')
        window.resize(1100, 800)
        creation_result = {'receipt': None, 'loaded': False}
        def created(receipt):
            if receipt:
                creation_result['receipt'] = receipt
                if creation_result['loaded']:
                    page.runJavaScript('loadProjects(' + json.dumps(receipt['id']) + ')')
        def creation_failed(message):
            if args.smoke:
                print('desktop creation failed: ' + message, file=sys.stderr, flush=True)
                app.exit(5)
            else:
                QMessageBox.warning(window, 'Projekt nebyl vytvořen', message)
        controller = CreationController(window, ProjectCreation(node_path), created, creation_failed)
        editor_toolbar = window.addToolBar('Dokumenty')
        editor_open = False
        def edit_selected(todo=False):
            nonlocal editor_open
            if controller.busy or editor_open:
                return
            editor_open = True
            def selected(project_id):
                nonlocal editor_open
                if view.closing:
                    editor_open = False
                    return
                if not project_id:
                    editor_open = False
                    QMessageBox.information(window, 'Dokumenty', 'Nejprve vyberte projekt.')
                    return
                try:
                    dialog = EditorDialog(Artifacts(node_path), project_id, window, todo=todo)
                    dialog.saved.connect(lambda id_: page.runJavaScript('loadProjects(' + json.dumps(id_) + ')'))
                    dialog.exec()
                    for worker in dialog.workers:
                        worker.wait()
                    dialog.deleteLater()
                finally:
                    editor_open = False
            page.runJavaScript("activeProject?.id || null", 0, selected)
        for label, todo in [('Dokumenty…', False), ('Úkoly projektu…', True)]:
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, todo=todo: edit_selected(todo))
            editor_toolbar.addWidget(button)
        def native_action(url):
            # A same-document fragment never loads a route or exposes an HTTP writer.
            if url.toString() == server.origin + '/#create-main-todo':
                page.runJavaScript("history.replaceState(null, '', '/');")
                edit_selected(True)
        page.urlChanged.connect(native_action)
        def project_loaded(ok):
            creation_result['loaded'] = ok
            if ok and creation_result['receipt']:
                page.runJavaScript('loadProjects(' + json.dumps(creation_result['receipt']['id']) + ')')
        view.loadFinished.connect(project_loaded)
        page.renderProcessTerminated.connect(lambda *_: None if view.closing else app.exit(1))
        timer = QTimer()
        timer.timeout.connect(lambda: None)
        timer.start(200)  # Let Python handle SIGINT while Qt's loop is running.
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: app.quit())
        if args.smoke:
            deadline = QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(lambda: app.exit(2))
            deadline.start(15000)
            poll = QTimer()
            project_check = None
            if args.smoke_project:
                expected = server.projects.open(args.smoke_project)
                if expected['artifacts']:
                    expected['preview'] = server.projects.preview(args.smoke_project, expected['artifacts'][0]['id'], expected['commit_id'])
                project_check = json.dumps(expected)
            def checked(value):
                if value == '1' and server.counter == 1:
                    if args.smoke_create and (not creation_result['receipt'] or controller.busy):
                        return
                    poll.stop()
                    if args.smoke_crash:
                        os.kill(page.renderProcessPid(), signal.SIGKILL)
                        return
                    if args.smoke_create:
                        print('desktop smoke: created=' + creation_result['receipt']['id'], flush=True)
                    if project_check:
                        print('desktop smoke: project=' + args.smoke_project + ', rendered rows verified', flush=True)
                    print('desktop smoke: rendered UI, authenticated fetch, value=1', flush=True)
                    def finish():
                        print('desktop measure: idle', flush=True)
                        if args.screenshot and not window.grab().save(args.screenshot):
                            app.exit(4)
                            return
                        window.close()
                    QTimer.singleShot(800, finish)  # Allow Chromium to present its frame.
            script = "document.querySelector('#count')?.textContent"
            if project_check:
                script = """(()=>{
                  if(!document.querySelector('#project-view'))return null;
                  const expected=EXPECTED;
                  const card=[...document.querySelectorAll('.project-card')].find(e=>e.dataset.id===expected.id);
                  if(!window.projectSmokeStarted && card){
                    if(document.querySelector('#project-home').hidden || document.querySelector('#sidebar-projects').hidden ||
                       document.querySelector('select') || card.querySelector('.project-name').textContent!==expected.title)return null;
                    const compact=[...document.querySelectorAll('#sidebar-project-list button')].find(e=>e.dataset.id===expected.id);
                    if(!compact || compact.textContent!==expected.title)return null;
                    window.projectSmokeStarted=true;(window.homeReturnChecked?compact:card).click();
                  }
                  if(document.querySelector('#project-view').hidden) return null;
                  if(document.querySelector('#project-title').textContent!==expected.title ||
                     document.querySelector('#project-commit').textContent!==expected.commit_id ||
                     !document.querySelector('#project-home').hidden || !document.querySelector('#sidebar-projects').hidden)return null;
                  const artifactTab=document.querySelector('#artifacts-tab'),todoTab=document.querySelector('#todo-tab');
                  const artifactPanel=document.querySelector('#sidebar-artifacts'),todoPanel=document.querySelector('#todo-widget');
                  const sidebarList=document.querySelector('#sidebar-artifact-list');
                  if(window.sidebarReloaded && artifactTab.getAttribute('aria-selected')!=='true') return null;
                  artifactTab.click();
                  if(artifactPanel.hidden || !todoPanel.hidden || artifactTab.getAttribute('aria-selected')!=='true') return null;
                  const sideRows=[...sidebarList.querySelectorAll('li')].map(row=>({
                    id:row.querySelector('.sidebar-artifact-id').textContent,
                    title:row.querySelector('.sidebar-artifact-title').textContent}));
                  if(JSON.stringify(sideRows)!==JSON.stringify(expected.artifacts) || sidebarList.querySelector('img,script,a')) return null;
                  artifactTab.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
                  if(todoPanel.hidden || !artifactPanel.hidden || document.activeElement!==todoTab) return null;
                  todoTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
                  if(artifactPanel.hidden || document.activeElement!==artifactTab || artifactTab.tabIndex!==0 || todoTab.tabIndex!==-1) return null;
                  artifactTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
                  if(todoPanel.hidden || document.activeElement!==todoTab) return null;
                  const todo=expected.main_todo;
                  if(document.querySelector('#create-main-todo').hidden!==!!todo) return null;
                  const tree=document.querySelector('#todo-tree');
                  if(!tree || tree.querySelector('img,script,a')) return null;
                  const todoRows=[...tree.querySelectorAll('li')];
                  if(todo?.status==='ready'){
                    if(document.querySelector('#todo-title').textContent!==todo.title || todoRows.length!==todo.items.length) return null;
                    for(let i=0;i<todoRows.length;i++){
                      const row=todoRows[i], item=todo.items[i], check=row.querySelector('input');
                      if(row.querySelector('.todo-text').textContent!==item.title ||
                         Number(row.dataset.depth)!==item.depth || !check.disabled || check.checked!==item.checked) return null;
                      let depth=0;for(let parent=row.parentElement;parent!==tree;parent=parent.parentElement){
                        if(parent.tagName==='UL') depth++;
                      }
                      if(depth!==item.depth) return null;
                      check.click();if(check.checked!==item.checked) return null;
                    }
                    const branch=tree.querySelector('details');
                    if(branch){branch.querySelector('summary').click();if(branch.open) return null;
                      branch.querySelector('summary').click();if(!branch.open) return null;}
                  }else if(todoRows.length) return null;
                  todoTab.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));
                  if(artifactPanel.hidden || document.activeElement!==artifactTab) return null;
                  if(!window.sidebarReloaded){
                    window.sidebarReloaded=true;
                    clearProject();
                    if(tree.children.length || sidebarList.children.length || document.querySelector('#todo-title').textContent) return null;
                    loadProjects(expected.id);
                    return null;
                  }
                  const chatTab=document.querySelector('#chat-tab'),previewTab=document.querySelector('#preview-tab');
                  previewTab.click();
                  const draft=document.querySelector('#chat-draft');draft.value='Local draft';
                  draft.dispatchEvent(new Event('input',{bubbles:true}));
                  if(document.querySelector('#chat-panel').hidden || document.querySelector('#chat-submit').disabled)return null;
                  if(!window.promptSubmitChecked){
                    const before=document.querySelector('#count').textContent;
                    draft.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
                    if(document.querySelector('#chat-messages').lastElementChild?.textContent!=='Local draft' || draft.value ||
                       document.querySelector('#count').textContent!==before)return null;
                    window.promptSubmitChecked=true;draft.value='Local draft';draft.dispatchEvent(new Event('input'));
                  }
                  const composer=document.querySelector('#chat-composer');
                  if(composer.closest('[role=tabpanel]') || composer.getBoundingClientRect().bottom>window.innerHeight)return null;
                  chatTab.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
                  if(document.querySelector('#preview-panel').hidden || draft.value!=='Local draft' ||
                     document.activeElement!==previewTab)return null;
                  if(expected.artifacts.length){
                    if(!window.previewStarted){window.previewStarted=true;
                      document.querySelector('#sidebar-artifact-list button').click();return null;}
                    if(document.querySelector('#preview-title').textContent!==expected.artifacts[0].title ||
                       document.querySelector('#preview-details').hidden)return null;
                    const content=document.querySelector('#preview-content');
                    if(content.querySelector('script,iframe,object,a'))return null;
                    const image=content.querySelector('img');
                    if(['image','pdf'].includes(expected.preview.format) && !image)return null;
                    if(image && (!image.complete || !image.naturalWidth))return null;
                    if(expected.preview.format==='markdown' && !content.children.length && expected.preview.text)return null;
                    if(!window.previewClearChecked){
                      window.previewClearChecked=true;window.previewStarted=false;
                      clearProject();
                      if(content.children.length || draft.value || document.querySelector('#preview-title').textContent)return null;
                      loadProjects(expected.id);return null;
                    }
                  }
                  if(!window.homeReturnChecked){
                    window.homeReturnChecked=true;window.projectSmokeStarted=false;window.previewStarted=false;
                    document.querySelector('#back-projects').click();
                    if(!document.querySelector('#project-view').hidden || document.querySelector('#project-home').hidden ||
                       document.querySelector('#sidebar-projects').hidden || draft.value)return null;
                    return null;
                  }
                  return document.querySelector('#count').textContent;
                })()""".replace('EXPECTED', project_check)
            if args.smoke_create:
                script = """(()=>{
                  if(document.querySelector('#project-view').hidden ||
                     document.querySelector('#project-title').textContent!=='Nový projekt z dialogu' ||
                     !document.querySelector('#project-commit').textContent) return null;
                  return document.querySelector('#count').textContent;
                })()"""
            poll.timeout.connect(lambda: page.runJavaScript(script, 0, checked))
            poll.start(100)
            def loaded(ok):
                if not ok:
                    app.exit(3)
                else:
                    print("desktop measure: ui ready", flush=True)
                    page.runJavaScript("document.querySelector('#increment').click()")
                    if args.smoke_create:
                        controller.smoke = ('Nový projekt z dialogu', args.smoke_create)
                        QTimer.singleShot(0, controller.button.click)
            view.loadFinished.connect(loaded)
        else:
            view.loadFinished.connect(lambda ok: None if ok else QMessageBox.warning(
                view, 'Nelze načíst rozhraní', 'Zavřete aplikaci a spusťte ji znovu.'))
        view.load(QUrl(server.origin + '/'))
        window.show()
        if not args.smoke:
            QTimer.singleShot(0, controller.recover)
        result = app.exec()
        controller.wait()
        view.closing = True
        window.close()
        # Destroy pages before their off-the-record profile.
        from shiboken6 import delete
        delete(window)
        delete(profile)
    if args.smoke and result == 0:
        print('desktop smoke: backend stopped', flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
