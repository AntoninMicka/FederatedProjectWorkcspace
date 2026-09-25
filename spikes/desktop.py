# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Linux Qt/WebEngine shell around the existing local API; registered project reads."""
import argparse
import json
import os
import signal
import sys
from urllib.parse import urlsplit
from uuid import uuid4

from spikes.desktop_management import ASSETS, DesktopManagementHandler as DesktopHandler
from spikes.administration import Administration
from spikes.local_api import running_api
from spikes.projects import Projects
from spikes.project_creation import ProjectCreation, default_node_path
from spikes.chat_service import ChatService
from spikes.summary_service import SummaryService
from spikes.extraction_service import ExtractionService
from spikes.metadata_suggestion_service import MetadataSuggestionService


PROVIDER_KEY_URLS = frozenset({'https://platform.openai.com/api-keys'})


def provider_key_url(url):
    """Return an exact approved provider onboarding URL, never an arbitrary URL."""
    return url if url in PROVIDER_KEY_URLS else None


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
        from PySide6.QtCore import Qt, QTimer, QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import (QApplication, QMessageBox, QMainWindow, QPushButton,
                                       QFileDialog, QInputDialog)
        from spikes.desktop_editor import EditorDialog
        from spikes.desktop_displays import PresenterDisplays
        from spikes.artifacts import Artifacts
        from spikes.desktop_creation import CreationController
        from spikes.desktop_deployment import DeploymentDialog
        from spikes.desktop_network import NetworkDialog
        from spikes.desktop_transfer import TransferDialog
        from spikes.desktop_import import ImportDialog
        from spikes.network_backend import NetworkBackend
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
            requested = url.toString()
            external = provider_key_url(requested)
            if main_frame and external:
                QDesktopServices.openUrl(QUrl(external))
                return False
            return main_frame and requested in {server.origin + '/', server.origin + '/presentation-screen'}

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
            displays.stop()
            super().closeEvent(event)

    app = QApplication([sys.argv[0]])
    app.setApplicationName('Projektový workspace')
    node_path = args.node or default_node_path()
    with running_api('http', handler=DesktopHandler, projects=Projects(node_path)) as server:
        server.administration = Administration(node_path, deployment='desktop')
        server.chat_service = ChatService(node_path, server.projects)
        server.summary_service = SummaryService(node_path, server.projects,
            state_dir=server.chat_service.state_dir,
            chat_state_dir=server.chat_service.state_dir)
        server.extraction_service = ExtractionService(node_path, server.projects,
            state_dir=server.chat_service.state_dir,
            chat_state_dir=server.chat_service.state_dir)
        server.metadata_suggestion_service = MetadataSuggestionService(node_path, server.projects,
            state_dir=server.chat_service.state_dir,
            chat_state_dir=server.chat_service.state_dir)
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
        public_view = View()
        public_page = Page(profile, public_view)
        public_view.setPage(public_page)
        public_window = QMainWindow()
        public_window.setCentralWidget(public_view)
        public_window.setWindowTitle('Veřejné promítání · Projektový workspace')
        displays = PresenterDisplays(app, window, public_window)
        public_view.setUrl(QUrl(server.origin + '/presentation-screen'))
        network_backend = NetworkBackend(node_path)
        if not args.smoke:
            try:
                network_config = network_backend.load()
                if network_config:
                    network_backend.start(network_config)
            except Exception as exc:
                QMessageBox.warning(window, 'Síťový backend se nespustil', str(exc))
        app.aboutToQuit.connect(network_backend.stop)
        app.aboutToQuit.connect(public_window.close)
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
                QMessageBox.warning(window, 'Operace projektu nebyla dokončena', message)
        controller = CreationController(window, ProjectCreation(node_path), created, creation_failed)
        project_toolbar = controller.toolbar
        register_button = QPushButton('Načíst projekt z umístění…')
        def register_project():
            if controller.busy:
                return
            folder = QFileDialog.getExistingDirectory(window, 'Vyberte kořen existujícího projektu',
                                                       str(controller.service.default_projects_root()))
            if folder:
                controller.start(lambda: controller.service.register(folder, str(uuid4())))
        register_button.clicked.connect(register_project)
        project_toolbar.addWidget(register_button)
        relocate_button = QPushButton('Opravit umístění projektu…')
        def relocate_project():
            if controller.busy:
                return
            rows = server.projects.catalog()
            if not rows:
                QMessageBox.information(window, 'Umístění projektu', 'Uzel nemá žádný registrovaný projekt.')
                return
            labels = [row['title'] + ' — ' + row['id'] for row in rows]
            label, accepted = QInputDialog.getItem(window, 'Umístění projektu',
                                                   'Registrovaný projekt', labels, 0, False)
            if not accepted:
                return
            project_id = rows[labels.index(label)]['id']
            if controller.service.registration_root_missing(project_id):
                choice = QMessageBox(window)
                choice.setWindowTitle('Chybějící projekt')
                choice.setTextFormat(Qt.TextFormat.PlainText)
                choice.setText('Původní umístění tohoto projektu na disku neexistuje.\n\n'
                               'Můžete vybrat nové umístění stejného projektu, nebo odebrat pouze jeho '
                               'registraci ze seznamu. Lokální stav a případná data jinde se nemažou.')
                repair = choice.addButton('Vybrat nové umístění', QMessageBox.ButtonRole.AcceptRole)
                remove = choice.addButton('Odebrat pouze ze seznamu', QMessageBox.ButtonRole.DestructiveRole)
                choice.addButton(QMessageBox.StandardButton.Cancel)
                choice.exec()
                if choice.clickedButton() is remove:
                    controller.start(lambda: controller.service.unregister_missing(project_id, str(uuid4())))
                    return
                if choice.clickedButton() is not repair:
                    return
            folder = QFileDialog.getExistingDirectory(window, 'Vyberte nové umístění stejného projektu',
                                                       str(controller.service.default_projects_root()))
            if folder:
                controller.start(lambda: controller.service.relocate(project_id, folder, str(uuid4())))
        relocate_button.clicked.connect(relocate_project)
        project_toolbar.addWidget(relocate_button)
        editor_toolbar = window.addToolBar('Dokumenty')
        deploy_button = QPushButton('Nasadit LXC uzel…')
        def deploy_node():
            if controller.busy:
                return
            dialog = DeploymentDialog(node_path, window, local_endpoint=network_backend.endpoint)
            dialog.exec()
            if dialog.worker:
                dialog.worker.wait()
            dialog.deleteLater()
        deploy_button.clicked.connect(deploy_node)
        editor_toolbar.addWidget(deploy_button)
        network_button = QPushButton('Síť a test spojení…')
        def network_settings():
            if controller.busy:
                return
            dialog = NetworkDialog(network_backend, window)
            dialog.exec()
            if dialog.worker:
                dialog.worker.wait()
            dialog.deleteLater()
        network_button.clicked.connect(network_settings)
        editor_toolbar.addWidget(network_button)
        transfer_button = QPushButton('Přenést veřejný projekt…')
        def transfer_project():
            if controller.busy:
                return
            dialog = TransferDialog(node_path, window)
            dialog.exec()
            if dialog.worker:
                dialog.worker.wait()
            dialog.deleteLater()
        transfer_button.clicked.connect(transfer_project)
        editor_toolbar.addWidget(transfer_button)
        import_button = QPushButton('Importovat zdroj…')
        import_open = False
        def import_source():
            nonlocal import_open
            if controller.busy or import_open:
                return
            import_open = True
            def selected(project_id):
                nonlocal import_open
                try:
                    if view.closing:
                        return
                    if not project_id:
                        QMessageBox.information(window, 'Import zdroje', 'Nejprve otevřete projekt.')
                        return
                    dialog = ImportDialog(node_path, project_id, window)
                    dialog.saved.connect(lambda id_: page.runJavaScript('loadProjects(' + json.dumps(id_) + ')'))
                    dialog.exec()
                    if dialog.worker:
                        dialog.worker.wait()
                    dialog.deleteLater()
                finally:
                    import_open = False
            page.runJavaScript('activeProject?.id || null', 0, selected)
        import_button.clicked.connect(import_source)
        editor_toolbar.addWidget(import_button)
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
            actions = {
                '/#presenter-open': displays.open,
                '/#presenter-displays': displays.configure,
                '/#presenter-close': displays.stop,
            }
            action = actions.get(url.toString().removeprefix(server.origin))
            if action and url.toString().startswith(server.origin + '/'):
                page.runJavaScript("history.replaceState(null, '', '/');")
                action()
                return
            # A same-document fragment never loads a route or exposes an HTTP writer.
            if url.toString() == server.origin + '/#create-main-todo':
                page.runJavaScript("history.replaceState(null, '', '/');")
                edit_selected(True)
        page.urlChanged.connect(native_action)
        def project_loaded(ok):
            creation_result['loaded'] = ok
            if ok and creation_result['receipt']:
                page.runJavaScript('loadProjects(' + json.dumps(creation_result['receipt']['id']) + ')')
        view.loadStarted.connect(displays.stop)
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
                       document.querySelector('#project-home select, #sidebar-projects select') ||
                       card.querySelector('.project-name').textContent!==expected.title)return null;
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
                  if(document.querySelector('#preview-panel').hidden || !document.querySelector('#chat-panel').hidden ||
                     document.querySelector('#chat-submit').disabled)return null;
                  if(!window.promptSubmitChecked){
                    const before=document.querySelector('#count').textContent;
                    draft.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
                    if(document.querySelector('#chat-panel').hidden ||
                       draft.value!=='Local draft' ||
                       document.querySelector('#count').textContent!==before)return null;
                    window.promptSubmitChecked=true;
                  }
                  if(!window.chatModesChecked){
                    const mode=document.querySelector('#chat-mode'),adapter=document.querySelector('#chat-run-adapter');
                    const artifacts=document.querySelector('#task-artifacts');
                    if(mode.value!=='orchestration' || !adapter.disabled || artifacts.hidden)return null;
                    mode.value='brainstorming';mode.dispatchEvent(new Event('change',{bubbles:true}));
                    if(adapter.disabled || !artifacts.hidden)return null;
                    mode.value='orchestration';mode.dispatchEvent(new Event('change',{bubbles:true}));
                    if(!adapter.disabled || artifacts.hidden)return null;
                    window.chatModesChecked=true;
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
                    if(expected.preview.metadata.import){
                      const details=document.querySelector('#preview-metadata').textContent;
                      for(const value of [expected.preview.metadata.import.imported_at,
                                          expected.preview.metadata.import.imported_by,
                                          expected.preview.metadata.import.content_sha256,
                                          expected.preview.metadata.import.importer.name,
                                          expected.preview.metadata.import.source_created_at].filter(Boolean)){
                        if(!details.includes(value))return null;
                      }
                    }
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
