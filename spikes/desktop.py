# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Linux Qt/WebEngine shell around the existing local API; registered project reads."""
import argparse
import json
import os
from pathlib import Path
import signal
import stat
import sys
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from spikes.desktop_management import ASSETS, DesktopManagementHandler as DesktopHandler
from spikes.administration import Administration
from spikes.local_api import running_api
from spikes.projects import Projects
from spikes.project_creation import CreationConflict, ProjectCreation, default_node_path
from spikes.project_creation_actions import ProjectCreationActions
from spikes.project_deletion import ProjectDeletion
from spikes.project_deletion_actions import ProjectDeletionActions
from spikes.project_repair import ProjectRepairActions
from spikes.notebooklm_import_actions import NotebookLMImportActions
from spikes.chat_service import ChatService
from spikes.summary_service import SummaryService
from spikes.extraction_service import ExtractionService
from spikes.metadata_suggestion_service import MetadataSuggestionService
from spikes.media_service import MediaService
from spikes.role_workflow_service import RoleWorkflowService
from spikes.publication_cms import PublicationCms
from spikes.google_drive_import import GoogleDriveImport
from spikes.replication_control import ReplicationScheduler
from spikes.user_profile import UserProfile
from spikes.gamepad_settings import GamepadSettings
from spikes.journal import sync_dir


PROVIDER_KEY_URLS = frozenset({'https://platform.openai.com/api-keys'})
NATIVE_ACTIONS = frozenset({'register-project-location', 'relocate-project-location',
                            'recover-project-operation',
                            'unregister-missing-project', 'choose-project-location',
                            'choose-notebooklm-archive',
                            'choose-notebooklm-target', 'choose-presentation-pdf',
                            'export-presentation-pdf', 'presenter-displays-identify',
                            'presenter-displays-apply', 'presenter-displays-cancel',
                            'federation-network-open', 'federation-network-run',
                            'federation-deployment-open', 'federation-deployment-start'})


def presentation_pdf_paths(target, nonce):
    """Resolve a user-picked PDF and its same-directory, one-operation temporary file."""
    if str(UUID(nonce)) != nonce:
        raise ValueError('Invalid PDF export nonce')
    target = Path(target).absolute()
    if target.suffix.lower() != '.pdf':
        target = target.with_suffix('.pdf')
    if (not target.parent.is_dir() or target.parent.is_symlink() or target.exists() and target.is_dir()
            or '\0' in str(target) or len(target.name.encode()) > 240):
        raise ValueError('Invalid PDF export target')
    return target, target.parent / ('.' + target.name + '.' + nonce + '.part')


def presentation_pdf_js_request(value):
    """Decode the explicit JSON bridge used because Qt does not portably map JS objects."""
    if not isinstance(value, str) or not 0 < len(value) <= 512:
        raise ValueError('Invalid PDF export request')
    try:
        request = json.loads(value)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Invalid PDF export request') from exc
    if (not isinstance(request, dict) or set(request) != {'nonce', 'preview_sha256'}
            or not isinstance(request['nonce'], str)
            or not isinstance(request['preview_sha256'], str)
            or len(request['preview_sha256']) != 64
            or any(character not in '0123456789abcdef' for character in request['preview_sha256'])):
        raise ValueError('Invalid PDF export request')
    try:
        if str(UUID(request['nonce'])) != request['nonce']:
            raise ValueError('Invalid PDF export request')
    except (ValueError, AttributeError) as exc:
        raise ValueError('Invalid PDF export request') from exc
    return request


def publish_presentation_pdf(temporary, target):
    """Durably replace the target only after WebEngine completed the whole PDF."""
    temporary, target = Path(temporary), Path(target)
    if not temporary.is_file() or temporary.is_symlink() or temporary.stat().st_size == 0:
        raise OSError('PDF renderer nevytvořil platný dočasný soubor.')
    with temporary.open('rb') as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, target)
    sync_dir(target.parent)


def provider_key_url(url):
    """Return an exact approved provider onboarding URL, never an arbitrary URL."""
    return url if url in PROVIDER_KEY_URLS else None


def google_authorization_url(url, origin):
    """Allow only the bounded OAuth/One Picker URL produced by the backend."""
    parsed = urlsplit(url)
    if (parsed.scheme, parsed.netloc, parsed.path, parsed.fragment) != (
            'https', 'accounts.google.com', '/o/oauth2/v2/auth', ''):
        return None
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
        required = {'client_id', 'scope', 'redirect_uri', 'response_type', 'access_type',
                    'prompt', 'trigger_onepick', 'allow_multiple', 'allow_folder_selection',
                    'state', 'code_challenge', 'code_challenge_method',
                    'include_granted_scopes'}
        if set(query) != required or any(len(values) != 1 for values in query.values()):
            return None
        if (query['scope'] != ['https://www.googleapis.com/auth/drive.file']
                or query['response_type'] != ['code'] or query['access_type'] != ['offline']
                or query['prompt'] != ['consent'] or query['trigger_onepick'] != ['true']
                or query['allow_multiple'] != ['true']
                or query['allow_folder_selection'] != ['true']
                or query['code_challenge_method'] != ['S256']
                or query['include_granted_scopes'] != ['false']):
            return None
        callback = urlsplit(query['redirect_uri'][0])
        if (callback.scheme, callback.netloc, callback.path) != (
                'http', urlsplit(origin).netloc, '/'):
            return None
        return url
    except (ValueError, AttributeError):
        return None


def native_action_request(url, origin):
    """Return an allowlisted one-shot action and its strictly bounded payload."""
    parsed, expected = urlsplit(url), urlsplit(origin)
    if (parsed.scheme, parsed.netloc, parsed.path, parsed.query) != (
            expected.scheme, expected.netloc, '/', '') or parsed.username or parsed.password:
        return None
    action, separator, query = parsed.fragment.partition('?')
    if not separator or action not in NATIVE_ACTIONS:
        return None
    try:
        fields = parse_qs(query, strict_parsing=True)
        if action == 'choose-notebooklm-target':
            expected_fields = {'nonce', 'operation_id'}
        elif action in {'relocate-project-location', 'unregister-missing-project'}:
            expected_fields = {'nonce', 'project_id'}
        elif action in {'presenter-displays-identify', 'presenter-displays-apply'}:
            expected_fields = {'nonce', 'token', 'speaker', 'audience'}
        else:
            expected_fields = {'nonce'}
        if set(fields) != expected_fields or any(len(values) != 1 for values in fields.values()):
            return None
        nonce = fields['nonce'][0]
        if str(UUID(nonce)) != nonce:
            return None
        request = {'action': action, 'nonce': nonce}
        if action == 'choose-notebooklm-target':
            operation_id = fields['operation_id'][0]
            if str(UUID(operation_id)) != operation_id:
                return None
            request['operation_id'] = operation_id
        elif action in {'relocate-project-location', 'unregister-missing-project'}:
            project_id = fields['project_id'][0]
            if str(UUID(project_id)) != project_id:
                return None
            request['project_id'] = project_id
        elif action in {'presenter-displays-identify', 'presenter-displays-apply'}:
            token = fields['token'][0]
            if str(UUID(token)) != token:
                return None
            speaker, audience = int(fields['speaker'][0]), int(fields['audience'][0])
            if not 0 <= speaker <= 63 or not -1 <= audience <= 63:
                return None
            request.update(token=token, speaker=speaker, audience=audience)
        return request
    except (ValueError, AttributeError, KeyError):
        return None


def native_action_name(url, origin):
    """Return only the action name for navigation policy checks."""
    request = native_action_request(url, origin)
    return request['action'] if request else None


def repairable_target_mode(path):
    """Return an unsafe mode only for an owned, empty, non-symlink directory."""
    path = Path(path)
    try:
        info = path.lstat()
        if (path.absolute() != path.resolve() or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid() or any(path.iterdir())):
            return None
        mode = stat.S_IMODE(info.st_mode)
        return mode if mode & 0o022 else None
    except OSError:
        return None


def notebooklm_target_error(exc):
    """Translate only known target validation failures without leaking internals."""
    return {
        'Directory must not be writable by other users':
            'Cílová složka má příliš otevřená práva. Nastavte jí práva 0700 a vyberte ji znovu.',
        'Existující cílová složka musí být prázdná.':
            'Cílová složka musí být prázdná.',
        'Expected owned directory':
            'Cílová složka musí patřit uživateli, pod kterým běží aplikace.',
    }.get(str(exc), 'Vybranou složku nelze použít. Zvolte existující prázdnou složku bez symlinků.')


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
    parser.add_argument('--smoke-create', metavar='NEW_DIRECTORY', help='During --smoke, create a project through the shared form and native location capability.')
    parser.add_argument('--smoke-project', help='During --smoke, open this registered ID and verify rendered rows.')
    parser.add_argument('--smoke-repair', help='During --smoke, repair the missing index of this registered project through the shared UI.')
    parser.add_argument('--smoke-crash', action='store_true', help='Kill renderer during --smoke; expect exit 1.')
    args = parser.parse_args()
    smoke_targets = sum(bool(value) for value in
                        (args.smoke_create, args.smoke_project, args.smoke_repair))
    if smoke_targets > 1:
        parser.error('--smoke-create, --smoke-project and --smoke-repair cannot be combined')
    if args.smoke_create and not (args.smoke and args.node):
        parser.error('--smoke-create requires --smoke and --node')
    if args.smoke_project and not (args.smoke and args.node):
        parser.error('--smoke-project requires --smoke and --node')
    if args.smoke_repair and not (args.smoke and args.node):
        parser.error('--smoke-repair requires --smoke and --node')
    if args.smoke_crash and not args.smoke:
        parser.error('--smoke-crash requires --smoke')
    if args.screenshot and not args.smoke:
        parser.error('--screenshot requires --smoke')
    try:
        from PySide6.QtCore import Qt, QTimer, QUrl, QMarginsF, QSizeF
        from PySide6.QtGui import QDesktopServices, QPageLayout, QPageSize
        from PySide6.QtWidgets import (QApplication, QMessageBox, QMainWindow,
                                       QFileDialog)
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                          QWebEngineSettings, QWebEngineUrlRequestInterceptor)
    except ImportError:
        print('Chybí PySide6 WebEngine. Instalace viz README, sekce Desktop.', file=sys.stderr)
        return 1
    try:
        from spikes.desktop_displays import PresenterDisplays
        from spikes.presentation_documents import PresentationDocuments
        from spikes.presentation_sessions import PresentationSessions
        from spikes.desktop_creation import CreationController
        from spikes.desktop_deployment import FederationDeployment
        from spikes.desktop_network import FederationNetwork
        from spikes.network_backend import NetworkBackend
    except ImportError as exc:
        print('Nelze načíst interní modul desktopu: ' + str(exc), file=sys.stderr)
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
            external = provider_key_url(requested) or google_authorization_url(requested, server.origin)
            if main_frame and external:
                QDesktopServices.openUrl(QUrl(external))
                return False
            return main_frame and (
                requested in {server.origin + '/', server.origin + '/presentation-screen'}
                or native_action_name(requested, server.origin) is not None)

        def createWindow(self, kind):
            return None

    class View(QWebEngineView):
        closing = False

        def closeEvent(self, event):
            self.closing = True
            super().closeEvent(event)

    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.native_operation_guards = []

        def closeEvent(self, event):
            if controller.busy or any(guard() for guard in self.native_operation_guards):
                event.ignore()
                return
            view.closing = True
            displays.stop()
            super().closeEvent(event)

    app = QApplication([sys.argv[0]])
    app.setApplicationName('Projektový workspace')
    node_path = args.node or default_node_path()
    try:
        ProjectDeletion(node_path).recover()
    except Exception as exc:
        QMessageBox.warning(None, 'Odstranění projektu nebylo dokončeno', str(exc))
    with running_api('http', handler=DesktopHandler, projects=Projects(node_path)) as server:
        server.administration = Administration(node_path, deployment='desktop')
        server.user_profile = UserProfile(node_path)
        server.gamepad_settings = GamepadSettings(node_path)
        server.presentation_documents = PresentationDocuments(node_path)
        server.presentation_sessions = PresentationSessions(node_path)
        try:
            server.presentation_sessions.recover()
        except Exception as exc:
            QMessageBox.warning(None, 'Obnova záznamu prezentace nebyla dokončena', str(exc))
        server.chat_service = ChatService(node_path, server.projects)
        server.media_service = MediaService(node_path, server.projects,
            state_dir=server.chat_service.state_dir)
        server.role_workflow_service = RoleWorkflowService(node_path, server.projects,
            state_dir=server.chat_service.state_dir)
        server.summary_service = SummaryService(node_path, server.projects,
            state_dir=server.chat_service.state_dir,
            chat_state_dir=server.chat_service.state_dir)
        server.extraction_service = ExtractionService(node_path, server.projects,
            state_dir=server.chat_service.state_dir,
            chat_state_dir=server.chat_service.state_dir)
        server.metadata_suggestion_service = MetadataSuggestionService(node_path, server.projects,
            state_dir=server.chat_service.state_dir,
            chat_state_dir=server.chat_service.state_dir)
        server.publication_cms = PublicationCms(server.chat_service.state_dir)
        server.project_creation_actions = ProjectCreationActions(
            node_path, desktop_locations=True)
        server.project_deletion_actions = ProjectDeletionActions(node_path)
        server.project_repair_actions = ProjectRepairActions(node_path)
        if args.smoke_repair:
            # Exercise the real unavailable-project menu without letting the
            # dashboard opener eagerly rebuild this deliberately missing index.
            catalog = server.projects.catalog

            def repair_smoke_catalog():
                rows = catalog()
                return [dict(item, available=False, location_missing=False)
                        if item['id'] == args.smoke_repair else item
                        for item in rows]

            server.projects.catalog = repair_smoke_catalog
        server.notebooklm_import_actions = NotebookLMImportActions(
            node_path, desktop_capabilities=True)
        server.google_drive_import = GoogleDriveImport(node_path)
        profile = QWebEngineProfile(app)  # unnamed => off the record
        interceptor = Interceptor(profile)
        profile.setUrlRequestInterceptor(interceptor)
        presentation_pdf_targets = {}
        presentation_pdf_jobs = {}
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
        displays = PresenterDisplays(
            app, window, public_window,
            configuration_callback=lambda result: page.runJavaScript(
                'showPresenterDisplayConfiguration(' + json.dumps(result) + ')'),
            closed_callback=lambda: page.runJavaScript(
                "typeof closePresenterDisplayConfiguration==='function'&&"
                'closePresenterDisplayConfiguration()'),
            error_callback=lambda message: page.runJavaScript(
                'setPresenterDisplayNativeError(' + json.dumps(message) + ')'))
        public_view.setUrl(QUrl(server.origin + '/presentation-screen'))
        network_backend = NetworkBackend(node_path)
        if not args.smoke:
            try:
                network_config = network_backend.load()
                if network_config:
                    network_backend.start(network_config)
            except Exception as exc:
                QMessageBox.warning(window, 'Síťový backend se nespustil', str(exc))
        federation_network = FederationNetwork(
            network_backend, parent=window,
            configuration_callback=lambda result: page.runJavaScript(
                'showFederationNetworkConfiguration(' + json.dumps(result) + ')'),
            progress_callback=lambda message: page.runJavaScript(
                'setFederationNetworkProgress(' + json.dumps(message) + ')'),
            finished_callback=lambda success, message: page.runJavaScript(
                'finishFederationNetwork(' + json.dumps(bool(success)) + ',' +
                json.dumps(message) + ')'))
        federation_deployment = FederationDeployment(
            node_path, parent=window, endpoint_callback=lambda: network_backend.endpoint,
            configuration_callback=lambda result: page.runJavaScript(
                'showFederationDeploymentConfiguration(' + json.dumps(result) + ')'),
            progress_callback=lambda message: page.runJavaScript(
                'setFederationDeploymentProgress(' + json.dumps(message) + ')'),
            finished_callback=lambda success, message: page.runJavaScript(
                'finishFederationDeployment(' + json.dumps(bool(success)) + ',' +
                json.dumps(message) + ')'))
        window.native_operation_guards.extend([
            lambda: bool(federation_network.worker and federation_network.worker.isRunning()),
            lambda: bool(federation_deployment.worker and federation_deployment.worker.isRunning()),
        ])
        app.aboutToQuit.connect(network_backend.stop)
        app.aboutToQuit.connect(public_window.close)
        creation_result = {'receipt': None, 'loaded': False}
        creation_status_state = {'message': '', 'can_retry': False}
        def creation_status_changed(message, can_retry):
            creation_status_state.update(message=message, can_retry=bool(can_retry))
            if creation_result['loaded']:
                page.runJavaScript('setNativeProjectOperationStatus(' + json.dumps(message) + ',' +
                                   json.dumps(bool(can_retry)) + ')')
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
        controller = CreationController(window, ProjectCreation(node_path), created, creation_failed,
                                        creation_status_changed)
        def register_project():
            if controller.busy:
                return
            folder = QFileDialog.getExistingDirectory(window, 'Vyberte kořen existujícího projektu',
                                                       str(controller.service.default_projects_root()))
            if folder:
                controller.start(lambda: controller.service.register(folder, str(uuid4())))
            else:
                page.runJavaScript("document.querySelector('#sidebar-project-status').textContent=" +
                                   json.dumps('Výběr projektu byl zrušen.'))
        def relocate_project(project_id):
            if controller.busy:
                return
            try:
                location_missing = controller.service.registration_root_missing(project_id)
            except ValueError:
                page.runJavaScript("document.querySelector('#sidebar-project-status').textContent=" +
                                   json.dumps('Registrace projektu už není dostupná. Obnovte seznam.'))
                return
            if not location_missing:
                page.runJavaScript("document.querySelector('#sidebar-project-status').textContent=" +
                                   json.dumps('Projekt už nemá chybějící umístění. Obnovte seznam.'))
                return
            folder = QFileDialog.getExistingDirectory(window, 'Vyberte nové umístění stejného projektu',
                                                       str(controller.service.default_projects_root()))
            if folder:
                controller.start(lambda: controller.service.relocate(project_id, folder, str(uuid4())))
            else:
                page.runJavaScript("document.querySelector('#sidebar-project-status').textContent=" +
                                   json.dumps('Oprava umístění byla zrušena.'))
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
            request = native_action_request(url.toString(), server.origin)
            if request is None:
                return
            action = request['action']
            page.runJavaScript("history.replaceState(null, '', '/');")
            if action == 'register-project-location':
                register_project()
            elif action == 'recover-project-operation':
                controller.recover()
            elif action == 'relocate-project-location':
                relocate_project(request['project_id'])
            elif action == 'unregister-missing-project':
                if not controller.busy:
                    controller.start(lambda: controller.service.unregister_missing(
                        request['project_id'], str(uuid4())))
            elif action == 'choose-project-location':
                def choose_project_location(request):
                    if not isinstance(request, dict) or set(request) != {'title', 'operation_id'}:
                        return
                    folder = QFileDialog.getExistingDirectory(
                        window, 'Existující prázdná složka projektu',
                        str(controller.service.default_projects_root()))
                    if folder:
                        result = server.project_creation_actions.register_location(
                            folder, request['operation_id'])
                        page.runJavaScript('setProjectCreationLocation(' + json.dumps(result) + ')')
                page.runJavaScript('projectCreationPickerRequest()', 0, choose_project_location)
            elif action == 'choose-notebooklm-archive':
                archive, _ = QFileDialog.getOpenFileName(
                    window, 'Google Takeout TGZ', '', 'TGZ (*.tgz *.tar.gz)')
                if archive:
                    try:
                        result = server.notebooklm_import_actions.register_archive(archive)
                        page.runJavaScript('setNotebookLMArchive(' + json.dumps(result) + ')')
                    except (ValueError, OSError):
                        page.runJavaScript('setNotebookLMNativeError(' + json.dumps(
                            'Vybraný archiv nelze použít. Zvolte existující běžný TGZ soubor.') + ')')
            elif action == 'choose-notebooklm-target':
                folder = QFileDialog.getExistingDirectory(
                    window, 'Existující prázdná cílová složka projektu',
                    str(controller.service.default_projects_root()))
                if folder:
                    try:
                        unsafe_mode = repairable_target_mode(folder)
                        if unsafe_mode is not None:
                            answer = QMessageBox.question(
                                window, 'Soukromí cílové složky',
                                'Vybraná prázdná složka je zapisovatelná dalšími uživateli '
                                f'(práva {unsafe_mode:04o}).\n\nNastavit bezpečná práva 0700 a použít ji?',
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                QMessageBox.StandardButton.No)
                            if answer != QMessageBox.StandardButton.Yes:
                                raise CreationConflict('Directory must not be writable by other users')
                            os.chmod(folder, 0o700)
                        result = server.notebooklm_import_actions.register_target(
                            folder, request['operation_id'])
                        page.runJavaScript('setNotebookLMTarget(' + json.dumps(result) + ')')
                    except (ValueError, OSError) as exc:
                        page.runJavaScript('setNotebookLMNativeError(' + json.dumps(
                            notebooklm_target_error(exc)) + ')')
            elif action == 'choose-presentation-pdf':
                def choose_presentation_pdf(raw_plan):
                    try:
                        plan = presentation_pdf_js_request(raw_plan)
                    except ValueError:
                        page.runJavaScript("setPresentationPdfNativeError('Nativní výběr cíle nepřevzal platný plán exportu.')")
                        return
                    if plan['nonce'] != request['nonce']:
                        page.runJavaScript("setPresentationPdfNativeError('Výběr cíle neodpovídá aktuálnímu exportu.')")
                        return
                    filename, _ = QFileDialog.getSaveFileName(
                        window, 'Export prezentace do PDF', '', 'PDF (*.pdf)')
                    if filename:
                        try:
                            target, temporary = presentation_pdf_paths(filename, request['nonce'])
                            presentation_pdf_targets[request['nonce']] = (
                                target, temporary, plan['preview_sha256'])
                            result = {'nonce': request['nonce'], 'path': str(target),
                                      'exists': target.exists()}
                            page.runJavaScript('setPresentationPdfTarget(' + json.dumps(result) + ')')
                        except (ValueError, OSError) as exc:
                            page.runJavaScript('presentationPdfExportFinished(' + json.dumps({
                                'nonce': request['nonce'], 'success': False, 'error': str(exc)}) + ')')
                page.runJavaScript('JSON.stringify(presentationPdfTargetRequest())', 0,
                                   choose_presentation_pdf)
            elif action in {'presenter-displays-identify', 'presenter-displays-apply'}:
                try:
                    method = (displays.identify_selection if action == 'presenter-displays-identify'
                              else displays.apply_selection)
                    method(request['token'], request['speaker'], request['audience'])
                except ValueError as exc:
                    page.runJavaScript('setPresenterDisplayNativeError(' + json.dumps(str(exc)) + ')')
                    displays.configure()
            elif action == 'presenter-displays-cancel':
                displays.cancel_configuration()
            elif action == 'federation-network-open':
                try:
                    federation_network.open()
                except (ValueError, OSError) as exc:
                    page.runJavaScript('setFederationNetworkError(' + json.dumps(str(exc)) + ')')
            elif action == 'federation-network-run':
                def run_federation_network(raw_request):
                    try:
                        payload = json.loads(raw_request) if isinstance(raw_request, str) else None
                        federation_network.run(payload)
                    except (ValueError, OSError, json.JSONDecodeError) as exc:
                        page.runJavaScript('setFederationNetworkError(' + json.dumps(str(exc)) + ')')
                page.runJavaScript('JSON.stringify(federationNetworkRequest())', 0,
                                   run_federation_network)
            elif action == 'federation-deployment-open':
                try:
                    federation_deployment.open()
                except (ValueError, OSError) as exc:
                    page.runJavaScript('setFederationDeploymentError(' + json.dumps(str(exc)) + ')')
            elif action == 'federation-deployment-start':
                def start_federation_deployment(raw_request):
                    try:
                        payload = json.loads(raw_request) if isinstance(raw_request, str) else None
                        federation_deployment.start(payload)
                    except (ValueError, OSError, json.JSONDecodeError) as exc:
                        page.runJavaScript('setFederationDeploymentError(' + json.dumps(str(exc)) + ')')
                page.runJavaScript('JSON.stringify(federationDeploymentRequest())', 0,
                                   start_federation_deployment)
            elif action == 'export-presentation-pdf':
                selected = presentation_pdf_targets.get(request['nonce'])
                if selected is None:
                    page.runJavaScript("setPresentationPdfNativeError('Cíl PDF už není pro tento export dostupný. Vyberte jej znovu.')")
                    return
                def export_pdf(raw_approval):
                    try:
                        approval = presentation_pdf_js_request(raw_approval)
                    except ValueError:
                        page.runJavaScript("setPresentationPdfNativeError('Nativní export nepřevzal platné potvrzení.')")
                        return
                    if (approval['nonce'] != request['nonce']
                            or approval['preview_sha256'] != selected[2]):
                        page.runJavaScript("setPresentationPdfNativeError('Potvrzení neodpovídá aktuálnímu exportu.')")
                        return
                    target, temporary, _ = selected
                    try:
                        if temporary.exists():
                            raise OSError('Dočasný soubor této exportní operace již existuje.')
                        layout = QPageLayout(
                            QPageSize(QSizeF(16, 9), QPageSize.Unit.Inch, '16:9'),
                            # Custom size is already 16 x 9; Qt "Landscape" would rotate it.
                            QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0),
                            QPageLayout.Unit.Inch)
                        presentation_pdf_jobs[str(temporary)] = (request['nonce'], target)
                        QTimer.singleShot(0, lambda: page.printToPdf(str(temporary), layout))
                    except (ValueError, OSError) as exc:
                        page.runJavaScript('presentationPdfExportFinished(' + json.dumps({
                            'nonce': request['nonce'], 'success': False, 'error': str(exc)}) + ')')
                page.runJavaScript('JSON.stringify(presentationPdfExportRequest())', 0, export_pdf)
        page.urlChanged.connect(native_action)

        def presentation_pdf_finished(filename, success):
            job = presentation_pdf_jobs.pop(filename, None)
            if job is None:
                return
            nonce, target = job
            temporary = Path(filename)
            try:
                if not success:
                    raise OSError('WebEngine nedokončil vytvoření PDF.')
                publish_presentation_pdf(temporary, target)
                presentation_pdf_targets.pop(nonce, None)
                result = {'nonce': nonce, 'success': True}
            except OSError as exc:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
                result = {'nonce': nonce, 'success': False, 'error': str(exc)}
            page.runJavaScript('presentationPdfExportFinished(' + json.dumps(result) + ')')
        page.pdfPrintingFinished.connect(presentation_pdf_finished)
        def project_loaded(ok):
            creation_result['loaded'] = ok
            if ok:
                creation_status_changed(creation_status_state['message'],
                                        creation_status_state['can_retry'])
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
            def smoke_timeout():
                print('desktop smoke controller: counter=' + str(server.counter) +
                      ', busy=' + str(controller.busy) +
                      ', receipt=' + str(bool(creation_result['receipt'])), flush=True)
                page.runJavaScript("""JSON.stringify({
                  projectSmokeStarted:Boolean(window.projectSmokeStarted),
                  sidebarStage:window.smokeSidebarStage || null,
                  sidebarReloaded:Boolean(window.sidebarReloaded),
                  promptSubmitChecked:Boolean(window.promptSubmitChecked),
                  chatModesChecked:Boolean(window.chatModesChecked),
                  workflowPanelChecked:Boolean(window.workflowPanelChecked),
                  imagePanelChecked:Boolean(window.imagePanelChecked),
                  previewStarted:Boolean(window.previewStarted),
                  previewClearChecked:Boolean(window.previewClearChecked),
                  homeReturnChecked:Boolean(window.homeReturnChecked),
                  repairSmokeOpened:Boolean(window.repairSmokeOpened),
                  repairSmokePreviewed:Boolean(window.repairSmokePreviewed),
                  repairSmokeConfirmed:Boolean(window.repairSmokeConfirmed),
                  repairViewHidden:document.querySelector('#project-repair-view')?.hidden,
                  repairState:document.querySelector('#project-repair-state')?.textContent || null,
                  repairStatus:document.querySelector('#project-repair-status')?.textContent || null,
                  repairPlanHidden:document.querySelector('#project-repair-plan')?.hidden,
                  repairFindings:document.querySelector('#project-repair-findings')?.textContent || null,
                  selectedSidebar:document.querySelector('#sidebar-tabs [aria-selected="true"]')?.id || null,
                  artifactsHidden:document.querySelector('#sidebar-artifacts')?.hidden,
                  todoHidden:document.querySelector('#todo-widget')?.hidden,
                  artifactCount:document.querySelectorAll('#sidebar-artifact-list li').length,
                  artifactRows:[...document.querySelectorAll('#sidebar-artifact-list li')].map(row=>({id:row.querySelector('.sidebar-artifact-id')?.textContent,title:row.querySelector('.sidebar-artifact-title')?.textContent})),
                  expectedArtifacts:window.smokeExpectedArtifacts || null,
                  chatMode:document.querySelector('#chat-mode')?.value || null,
                  chatAdapterDisabled:document.querySelector('#chat-run-adapter')?.disabled,
                  taskArtifactsHidden:document.querySelector('#task-artifacts')?.hidden,
                  composerBottom:document.querySelector('#chat-composer')?.getBoundingClientRect().bottom,
                  viewportHeight:window.innerHeight,
                  previewTitle:document.querySelector('#preview-title')?.textContent || null,
                  expectedPreviewTitle:window.smokeExpectedArtifacts?.[0]?.title || null,
                  previewTitleMatches:document.querySelector('#preview-title')?.textContent===window.smokeExpectedArtifacts?.[0]?.title,
                  previewDetailsHidden:document.querySelector('#preview-details')?.hidden,
                  projectHidden:document.querySelector('#project-view')?.hidden,
                  projectCreateHidden:document.querySelector('#project-create-view')?.hidden,
                  projectTitle:document.querySelector('#project-title')?.textContent || null,
                  projectCommit:Boolean(document.querySelector('#project-commit')?.textContent),
                  imageTabHidden:document.querySelector('#image-tab')?.hidden,
                  imageTabSelected:document.querySelector('#image-tab')?.getAttribute('aria-selected'),
                  imagePanelHidden:document.querySelector('#image-panel')?.hidden,
                  imagePrompt:Boolean(document.querySelector('#image-prompt')),
                  imageRequestHidden:document.querySelector('#image-request-preview')?.hidden,
                  imageResultHidden:document.querySelector('#image-result')?.hidden,
                  imageDispatchDisabled:document.querySelector('#image-dispatch')?.disabled,
                  count:document.querySelector('#count')?.textContent || null
                })""", lambda value: (print('desktop smoke timeout: ' + str(value), flush=True), app.exit(2)))
            deadline.timeout.connect(smoke_timeout)
            deadline.start(15000)
            poll = QTimer()
            project_check = None
            if args.smoke_project:
                expected = server.projects.open(args.smoke_project)
                if expected['artifacts']:
                    expected['preview'] = server.projects.preview(args.smoke_project, expected['artifacts'][0]['id'], expected['commit_id'])
                project_check = json.dumps(expected)
            repair_check = None
            if args.smoke_repair:
                item = next((item for item in server.projects.catalog()
                             if item['id'] == args.smoke_repair), None)
                if item is None:
                    parser.error('--smoke-repair requires a registered project')
                repair_check = json.dumps(dict(item, available=False,
                                               location_missing=False))
            def checked(value):
                if value == '1' and server.counter == 1:
                    if args.smoke_create and not creation_result['receipt'] and not controller.busy:
                        created_projects = [item for item in server.projects.catalog()
                                            if item['title'] == 'Nový projekt ze společného formuláře']
                        if len(created_projects) == 1:
                            creation_result['receipt'] = created_projects[0]
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
                    if repair_check:
                        print('desktop smoke: project=' + args.smoke_repair + ', repair UI verified', flush=True)
                    print('desktop smoke: rendered UI, authenticated fetch, value=1', flush=True)
                    def finish():
                        print('desktop measure: idle', flush=True)
                        if args.screenshot and not window.grab().save(args.screenshot):
                            app.exit(4)
                            return
                        window.close()
                    QTimer.singleShot(800, finish)  # Allow Chromium to present its frame.
            script = """(()=>{
              if(typeof startChatProgress!=='function')return null;
              document.querySelector('#project-home').hidden=true;
              document.querySelector('#project-view').hidden=false;
              const chatTab=document.querySelector('#chat-tab');chatTab.click();
              if(!window.smokeChatProgress)window.smokeChatProgress=startChatProgress('Ollama testuje živý stav…');
              const progress=document.querySelector('#chat-stream-status');
              const progressRect=progress.getBoundingClientRect();
              const viewportRect=document.querySelector('#main-panel-content').getBoundingClientRect();
              const stream=document.querySelector('#chat-stream');
              if(!window.smokeLongStreamStarted){
                if(progress.hidden || getComputedStyle(progress).display==='none' ||
                   !document.querySelector('#chat-panel').contains(progress) ||
                   !document.querySelector('#chat-stream-progress-text').textContent.includes('Ollama testuje živý stav') ||
                   progressRect.width<=0 || progressRect.height<=0 ||
                   progressRect.bottom<=viewportRect.top || progressRect.top>=viewportRect.bottom)return null;
                stream.hidden=false;stream.textContent=Array.from({length:300},(_,i)=>`Dlouhý řádek ${i}\\n`).join('');
                keepChatStreamVisible();window.smokeLongStreamStarted=true;return null;
              }
              const owner=chatScrollOwner();
              if(!window.smokeManualScrollStarted){
                if(owner.scrollHeight-owner.scrollTop-owner.clientHeight>2)return null;
                owner.scrollTop=0;updateChatAutoFollow();stream.textContent+='Přírůstek mimo pohled\\n';
                keepChatStreamVisible();window.smokeManualScrollStarted=true;return null;
              }
              if(!window.smokeResumeStarted){
                if(owner.scrollTop!==0 || streamAutoFollow)return null;
                owner.scrollTop=owner.scrollHeight;updateChatAutoFollow();
                stream.textContent+='Přírůstek po návratu na konec\\n';keepChatStreamVisible();
                window.smokeResumeStarted=true;return null;
              }
              if(!streamAutoFollow || owner.scrollHeight-owner.scrollTop-owner.clientHeight>2)return null;
              window.smokeChatProgress.stop();window.smokeChatProgress=null;
              stream.hidden=true;stream.textContent='';
              return document.querySelector('#count')?.textContent;
            })()"""
            if project_check:
                script = """(()=>{
                  if(!document.querySelector('#project-view') || typeof sidebarItemMenu!=='function')return null;
                  const expected=EXPECTED;
                  window.smokeExpectedArtifacts=expected.artifacts;
                  const card=[...document.querySelectorAll('.project-card')].find(e=>e.dataset.id===expected.id);
                  if(!window.projectSmokeStarted && card){
                    const registerProject=document.querySelector('#sidebar-register-project');
                    const importOptions=document.querySelector('#sidebar-project-import-options');
                    const importProject=document.querySelector('#sidebar-import-project');
                    const federationTab=document.querySelector('#federation-tab');
                    const federationItem=document.querySelector('#open-federation-sharing');
                    const federationNetworkItem=document.querySelector('#open-federation-network');
                    const federationDeploymentItem=document.querySelector('#open-federation-deployment');
                    const projectsTab=document.querySelector('#projects-tab');
                    const sidebar=document.querySelector('#workspace-sidebar');
                    const layoutToggle=document.querySelector('#sidebar-layout-toggle');
                    if(!window.sidebarCompactSmokeStarted){
                      if(!layoutToggle)return null;
                      if(sidebar.classList.contains('sidebar-compact')){layoutToggle.click();return null;}
                      if(sidebar.getBoundingClientRect().width<200)return null;
                      window.sidebarCompactSmokeStarted=true;layoutToggle.click();return null;
                    }
                    if(!window.sidebarCompactMenuOpened){
                      if(!sidebar.classList.contains('sidebar-compact') || sidebar.getBoundingClientRect().width>=100 ||
                         sidebar.classList.contains('sidebar-menu-open'))return null;
                      window.sidebarCompactMenuOpened=true;projectsTab.click();return null;
                    }
                    if(!window.sidebarCompactSmokeChecked){
                      const panel=document.querySelector('#sidebar-projects');
                      if(!sidebar.classList.contains('sidebar-menu-open') || panel.hidden ||
                         panel.getClientRects().length===0)return null;
                      window.sidebarCompactSmokeChecked=true;layoutToggle.click();return null;
                    }
                    if(!window.projectImportSmokeOpened){
                      if(sidebar.classList.contains('sidebar-compact') || sidebar.getBoundingClientRect().width<200 ||
                         !registerProject || registerProject.hidden || !importOptions.hidden ||
                         document.querySelectorAll('.sidebar-project-primary-actions .project-action-icon').length!==3)return null;
                      window.projectImportSmokeOpened=true;importProject.click();return null;
                    }
                    if(!window.projectImportSmokeChecked){
                      if(importOptions.hidden || registerProject.getClientRects().length===0)return null;
                      window.projectImportSmokeChecked=true;importProject.click();return null;
                    }
                    if(!window.federationSharingSmokeOpened){
                      if(!importOptions.hidden || federationTab.hidden || !federationItem || !federationNetworkItem || !federationDeploymentItem || [...document.querySelectorAll('#sidebar-tabs [role="tab"]')].at(-1)!==federationTab)return null;
                      window.federationSharingSmokeOpened=true;federationTab.click();federationItem.click();return null;
                    }
                    if(!window.federationSharingSmokeChecked){
                      const matrix=document.querySelector('#admin-project-shares');
                      if(document.querySelector('#federation-view').hidden || !matrix || matrix.rows.length<1 ||
                         document.querySelector('#federation-sharing-status').textContent.includes('Načítám'))return null;
                      window.federationSharingSmokeChecked=true;federationNetworkItem.click();return null;
                    }
                    if(!window.federationNetworkSmokeChecked){
                      const form=document.querySelector('#federation-network-form');
                      if(document.querySelector('#federation-network-view').hidden ||
                         form.elements.port.value!=='8443' ||
                         document.querySelector('#federation-network-status').textContent.includes('Načítám'))return null;
                      window.federationNetworkSmokeChecked=true;federationDeploymentItem.click();return null;
                    }
                    if(!window.federationDeploymentSmokeChecked){
                      const form=document.querySelector('#federation-deployment-form');
                      if(document.querySelector('#federation-deployment-view').hidden ||
                         form.elements.container.value!=='workspace-m0' ||
                         form.elements.mode.options.length!==5 ||
                         document.querySelector('#federation-deployment-status').textContent.includes('Načítám'))return null;
                      window.federationDeploymentSmokeChecked=true;projectsTab.click();return null;
                    }
                    const settingsTab=document.querySelector('#settings-sidebar-tab');
                    const monitor=document.querySelector('#resource-monitor-open');
                    const monitorDialog=document.querySelector('#resource-monitor-dialog');
                    if(settingsTab.disabled || !monitor || !monitorDialog)return null;
                    const profileMenuItem=document.querySelector('[data-settings-item="settings-profile-tab"]');
                    const profileMenuButton=document.querySelector('[data-settings-tab="settings-profile-tab"]');
                    if(!window.profileSmokeOpened){
                      if(profileMenuItem.hidden || !profileMenuButton)return null;
                      window.profileSmokeOpened=true;profileMenuButton.click();return null;
                    }
                    const profileStatus=document.querySelector('#user-profile-status');
                    const profileForm=document.querySelector('#user-profile-form');
                    if(!window.profileSmokeSubmitted){
                      if(document.querySelector('#settings-view').hidden || document.querySelector('#settings-profile-panel').hidden ||
                         document.querySelector('#settings-profile-tab').hidden || profileMenuItem.hidden ||
                         !profileStatus.textContent.includes('načtený'))return null;
                      profileForm.elements.name.value='Desktop Smoke';profileForm.elements.email.value='smoke@example.invalid';
                      profileForm.elements.phone.value='+420 000 000 000';profileForm.elements.web.value='https://example.invalid';
                      window.profileSmokeSubmitted=true;profileForm.requestSubmit();return null;
                    }
                    if(!window.profileSmokeSaved){
                      if(!profileStatus.textContent.includes('uložen pouze'))return null;
                      window.profileSmokeSaved=true;closeSettings();return null;
                    }
                    const displayButton=document.querySelector('#presenter-fullscreen');
                    const displayDialog=document.querySelector('#presenter-display-dialog');
                    const displayForm=document.querySelector('#presenter-display-form');
                    if(!window.presenterDisplaySmokeOpened){
                      if(displayButton.hidden)return null;
                      window.presenterDisplaySmokeOpened=true;location.hash='presenter-open';return null;
                    }
                    if(!window.presenterDisplaySmokeCancelled){
                      if(!displayDialog.open || displayForm.elements.speaker.options.length<1 ||
                         displayForm.elements.audience.options.length<2)return null;
                      window.presenterDisplaySmokeCancelled=true;document.querySelector('#presenter-display-cancel').click();return null;
                    }
                    if(displayDialog.open)return null;
                    monitor.click();if(!monitorDialog.open)return null;monitorDialog.close();
                    if(document.querySelector('#project-home').hidden || document.querySelector('#sidebar-projects').hidden ||
                       document.querySelector('#sidebar-projects select') ||
                       card.querySelector('.project-name').textContent!==expected.title)return null;
                    const compact=[...document.querySelectorAll('#sidebar-project-list button')].find(e=>e.dataset.id===expected.id);
                    const compactMenu=compact?.closest('li')?.querySelector('.sidebar-item-menu-items');
                    if(!compact || compact.textContent!==expected.title ||
                       compactMenu?.querySelector('button')?.textContent!=='Otevřít')return null;
                    window.projectSmokeStarted=true;(window.homeReturnChecked?compact:card).click();
                  }
                  if(document.querySelector('#project-view').hidden) return null;
                  if(document.querySelector('#project-title').textContent!==expected.title ||
                     document.querySelector('#project-description').textContent!==expected.description ||
                     document.querySelector('#project-commit').textContent!==expected.commit_id ||
                     !document.querySelector('#project-home').hidden || !document.querySelector('#sidebar-projects').hidden)return null;
                  const overviewTab=document.querySelector('#project-overview-tab');
                  const overviewPanel=document.querySelector('#project-overview-panel');
                  const promptForm=document.querySelector('#chat-composer');
                  const openTodo=expected.main_todo?.status==='ready' ? expected.main_todo.items.filter(item=>!item.checked) : [];
                  const overviewTasks=[...document.querySelectorAll('#project-overview-task-list .dashboard-task-row span')].map(item=>item.textContent);
                  if(!window.projectOverviewChecked){
                    const descriptionRect=document.querySelector('.project-overview-description').getBoundingClientRect();
                    const historyRect=document.querySelector('.project-overview-history').getBoundingClientRect();
                    const tasksRect=document.querySelector('.project-overview-tasks').getBoundingClientRect();
                    const mainPanelContent=document.querySelector('#main-panel-content');
                    const historyList=document.querySelector('#project-overview-history-list');
                    const taskList=document.querySelector('#project-overview-task-list');
                    const modeControl=document.querySelector('label[for="chat-mode"]');
                    const modeControlRect=modeControl.getBoundingClientRect();
                    const modeLabelRect=modeControl.querySelector('span').getBoundingClientRect();
                    const historySubjects=[...document.querySelectorAll('#project-overview-history-list .project-history-row strong')].map(item=>item.textContent);
                    if(overviewPanel.hidden || overviewTab.getAttribute('aria-selected')!=='true' || promptForm.hidden ||
                       document.querySelector('#prompt-widget-toggle') ||
                       !mainPanelContent.classList.contains('project-overview-active') ||
                       getComputedStyle(mainPanelContent).overflowY!=='hidden' ||
                       getComputedStyle(historyList).overflowY!=='auto' ||
                       getComputedStyle(taskList).overflowY!=='auto' ||
                       modeControlRect.height!==44 || modeLabelRect.top<modeControlRect.top ||
                       modeLabelRect.bottom>modeControlRect.bottom ||
                       descriptionRect.width<historyRect.width*1.8 ||
                       descriptionRect.bottom>historyRect.top ||
                       Math.abs(historyRect.top-tasksRect.top)>2 ||
                       JSON.stringify(historySubjects)!==JSON.stringify(expected.history.entries.map(item=>item.subject||'Commit bez názvu')) ||
                       JSON.stringify(overviewTasks)!==JSON.stringify(openTodo.map(item=>item.title)))return null;
                    window.projectOverviewChecked=true;
                  }
                  const projectsTab=document.querySelector('#projects-tab'),chatsTab=document.querySelector('#chats-tab');
                  const artifactTab=document.querySelector('#artifacts-tab'),todoTab=document.querySelector('#todo-tab');
                  const artifactPanel=document.querySelector('#sidebar-artifacts'),todoPanel=document.querySelector('#todo-widget');
                  const sidebarList=document.querySelector('#sidebar-artifact-list');
                  window.smokeSidebarStage='opened';
                  artifactTab.click();
                  if(artifactPanel.hidden || !todoPanel.hidden || artifactTab.getAttribute('aria-selected')!=='true') return null;
                  const sideRows=[...sidebarList.querySelectorAll('li')].map(row=>({
                    id:row.querySelector('.sidebar-artifact-id').textContent,
                    title:row.querySelector('.sidebar-item-title').textContent}));
                  const expectedRows=expected.artifacts.map(({id,title})=>({id,title}));
                  if(JSON.stringify(sideRows)!==JSON.stringify(expectedRows) || sidebarList.querySelector('img,script,a') ||
                     [...sidebarList.querySelectorAll(':scope > li')].some(row=>row.querySelector('.sidebar-item-menu-items button')?.textContent!=='Zobrazit')) return null;
                  window.smokeSidebarStage='rows';
                  artifactTab.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
                  if(document.querySelector('#sidebar-projects').hidden || !artifactPanel.hidden || document.activeElement!==projectsTab) return null;
                  window.smokeSidebarStage='home';
                  projectsTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
                  if(document.querySelector('#sidebar-chats').hidden || document.activeElement!==chatsTab) return null;
                  window.smokeSidebarStage='chats';
                  chatsTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
                  if(todoPanel.hidden || document.activeElement!==todoTab) return null;
                  window.smokeSidebarStage='todo';
                  todoTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
                  if(artifactPanel.hidden || document.activeElement!==artifactTab || artifactTab.tabIndex!==0 || todoTab.tabIndex!==-1) return null;
                  window.smokeSidebarStage='artifact-right';
                  artifactTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
                  if(todoPanel.hidden || document.activeElement!==todoTab) return null;
                  window.smokeSidebarStage='todo-back';
                  const todo=expected.main_todo;
                  const todoAction=document.querySelector('#create-main-todo');
                  if(todoAction.hidden || todoAction.textContent!==(todo?'Upravit seznam úkolů':'Vytvořit seznam úkolů')) return null;
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
                  window.smokeSidebarStage='todo-content';
                  todoTab.dispatchEvent(new KeyboardEvent('keydown',{key:'End',bubbles:true}));
                  const federationTab=document.querySelector('#federation-tab');
                  if(document.querySelector('#sidebar-federation').hidden || document.activeElement!==federationTab) return null;
                  federationTab.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true}));
                  if(document.querySelector('#sidebar-settings').hidden || document.activeElement!==document.querySelector('#settings-sidebar-tab')) return null;
                  window.smokeSidebarStage='end';
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
                    const routing=document.querySelector('#task-routing');
                    const action=document.querySelector('#task-action'),publicSource=document.querySelector('#task-source-public');
                    const inputs=document.querySelector('#task-inputs'),output=document.querySelector('#task-output-kind');
                    const currentPromptSource=document.querySelector('#task-source-current-prompt');
                    const conversationSource=document.querySelector('#task-source-conversation-label');
                    if(mode.value!=='orchestration' || adapter.disabled || routing.hidden ||
                       action.value!=='answer' || publicSource.checked || !currentPromptSource.hidden ||
                       document.querySelector('#task-input-count').textContent!=='1')return null;
                    output.value='document';
                    action.value='search';action.dispatchEvent(new Event('change',{bubbles:true}));
                    const routingWarning=document.querySelector('#chat-orchestration-target');
                    if(!publicSource.checked || currentPromptSource.hidden || !conversationSource.hidden ||
                       output.value!=='conversation' || !output.disabled ||
                       (!routingWarning.hidden && !routingWarning.textContent.includes('nastavte SearXNG')))return null;
                    action.value='answer';action.dispatchEvent(new Event('change',{bubbles:true}));
                    if(!currentPromptSource.hidden || conversationSource.hidden || output.disabled || output.value!=='document')return null;
                    inputs.querySelector('summary').click();inputs.dispatchEvent(new Event('toggle'));
                    if(!inputs.open || !promptForm.classList.contains('inputs-open'))return null;
                    inputs.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));
                    inputs.dispatchEvent(new Event('toggle'));
                    if(inputs.open || promptForm.classList.contains('inputs-open'))return null;
                    mode.value='brainstorming';mode.dispatchEvent(new Event('change',{bubbles:true}));
                    if(adapter.disabled || !routing.hidden)return null;
                    mode.value='orchestration';mode.dispatchEvent(new Event('change',{bubbles:true}));
                    if(adapter.disabled || routing.hidden)return null;
                    window.chatModesChecked=true;
                  }
                  if(!window.workflowPanelChecked){
                    const workflowTab=document.querySelector('#workflow-tab');workflowTab.click();
                    const workflowPanel=document.querySelector('#workflow-panel');
                    if(workflowPanel.hidden || workflowTab.getAttribute('aria-selected')!=='true' ||
                       !promptForm.hidden ||
                       !document.querySelector('#workflow-purpose') ||
                       !document.querySelector('#workflow-creator-artifacts') ||
                       !document.querySelector('#workflow-opponent-artifacts') ||
                       !document.querySelector('#workflow-creator-preview').hidden ||
                       !document.querySelector('#workflow-opponent-preview').hidden ||
                       !document.querySelector('#workflow-publish').hidden)return null;
                    window.workflowPanelChecked=true;chatTab.click();
                    if(document.querySelector('#chat-panel').hidden)return null;
                  }
                  if(!window.imagePanelChecked){
                    const imageTab=document.querySelector('#image-tab');imageTab.click();
                    const imagePanel=document.querySelector('#image-panel');
                    if(imagePanel.hidden || imageTab.getAttribute('aria-selected')!=='true' ||
                       !promptForm.hidden ||
                       !document.querySelector('#image-prompt') ||
                       !document.querySelector('#image-request-preview').hidden ||
                       !document.querySelector('#image-result').hidden ||
                       !document.querySelector('#image-dispatch').disabled)return null;
                    window.imagePanelChecked=true;chatTab.click();
                    if(document.querySelector('#chat-panel').hidden)return null;
                  }
                  const composer=document.querySelector('#chat-composer');
                  window.smokeSidebarStage='composer';
                  if(composer.closest('[role=tabpanel]') || !composer.offsetParent || composer.getBoundingClientRect().width<=0)return null;
                  chatTab.dispatchEvent(new KeyboardEvent('keydown',{key:'Home',bubbles:true}));
                  if(overviewPanel.hidden || draft.value!=='Local draft' || promptForm.hidden ||
                     document.activeElement!==overviewTab)return null;
                  window.smokeSidebarStage='main-home';
                  if(expected.artifacts.length){
                    if(!window.previewStarted){window.previewStarted=true;
                      document.querySelector('#sidebar-artifact-list button').click();return null;}
                    if(document.querySelector('#preview-title').textContent!==expected.artifacts[0].title ||
                       document.querySelector('#preview-details').hidden ||
                       document.querySelector('#task-source-current-file').hidden ||
                       !document.querySelector('#task-source-current-file-title').textContent.includes(expected.artifacts[0].title))return null;
                    const currentFileInput=document.querySelector('#task-source-current-file-input');
                    if(!currentFileInput.checked)currentFileInput.click();
                    if(!currentFileInput.checked || document.querySelector('#task-input-count').textContent!=='2')return null;
                    window.smokeSidebarStage='preview-basic';
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
                    window.smokeSidebarStage='preview-metadata';
                    const content=document.querySelector('#preview-content');
                    if(content.querySelector('script,iframe,object,a'))return null;
                    const image=content.querySelector('img');
                    if(['image','pdf'].includes(expected.preview.format) && !image)return null;
                    if(image && (!image.complete || !image.naturalWidth))return null;
                    if(expected.preview.format==='markdown' && !content.children.length && expected.preview.text)return null;
                    if(expected.preview.format==='json' &&
                       content.querySelector('pre')?.textContent!==expected.preview.text)return null;
                    window.smokeSidebarStage='preview-content';
                    if(!window.previewClearChecked){
                      window.previewClearChecked=true;window.previewStarted=false;
                      clearProject();
                      if(content.children.length || draft.value || document.querySelector('#preview-title').textContent)return null;
                      loadProjects(expected.id);return null;
                    }
                  }
                  if(!window.homeReturnChecked){
                    window.homeReturnChecked=true;window.projectSmokeStarted=false;window.previewStarted=false;
                    document.querySelector('#projects-tab').click();
                    if(!document.querySelector('#project-view').hidden || document.querySelector('#project-home').hidden ||
                       document.querySelector('#sidebar-projects').hidden || draft.value)return null;
                    return null;
                  }
                  return document.querySelector('#count').textContent;
                })()""".replace('EXPECTED', project_check)
            if repair_check:
                script = """(()=>{
                  const expected=EXPECTED;
                  if(typeof renderProjectCatalog!=='function' || typeof openProjectRepair!=='function')return null;
                  if(!window.repairSmokeOpened){
                    renderProjectCatalog([expected]);
                    const row=[...document.querySelectorAll('#sidebar-project-list > li')]
                      .find(item=>item.querySelector('.sidebar-list-main')?.dataset.id===expected.id);
                    const repair=[...(row?.querySelectorAll('.sidebar-project-menu button')||[])]
                      .find(button=>button.textContent==='Zkontrolovat projekt…');
                    if(!repair)return null;
                    window.repairSmokeOpened=true;repair.click();return null;
                  }
                  const view=document.querySelector('#project-repair-view');
                  const state=document.querySelector('#project-repair-state');
                  const status=document.querySelector('#project-repair-status');
                  const preview=document.querySelector('#project-repair-preview');
                  if(view.hidden)return null;
                  if(!window.repairSmokePreviewed){
                    if(state.textContent!=='Bezpečně opravitelné' || preview.hidden ||
                       !document.querySelector('#project-repair-findings').textContent.includes('index-missing'))return null;
                    window.repairSmokePreviewed=true;preview.click();return null;
                  }
                  const plan=document.querySelector('#project-repair-plan');
                  const check=document.querySelector('#project-repair-confirm-check');
                  const confirm=document.querySelector('#project-repair-confirm');
                  if(!window.repairSmokeConfirmed){
                    if(plan.hidden || !document.querySelector('#project-repair-details').textContent.includes('Vrstva: index'))return null;
                    check.click();if(!check.checked || confirm.disabled)return null;
                    window.repairSmokeConfirmed=true;confirm.click();return null;
                  }
                  if(state.textContent!=='V pořádku' || !status.textContent.startsWith('Oprava dokončena.') ||
                     !plan.hidden || document.querySelector('#project-repair-findings').textContent.includes('index-missing'))return null;
                  return document.querySelector('#count').textContent;
                })()""".replace('EXPECTED', repair_check)
            if args.smoke_create:
                script = """(()=>{
                  const required=['project-view','project-title','project-commit','image-tab','image-panel',
                    'image-prompt','image-request-preview','image-result','image-dispatch'];
                  const missing=required.filter(id=>!document.getElementById(id));
                  if(missing.length)return null;
                  if(document.querySelector('#project-view').hidden ||
                     document.querySelector('#project-title').textContent!=='Nový projekt ze společného formuláře' ||
                     !document.querySelector('#project-commit').textContent ||
                     !document.querySelector('#project-create-view').hidden) return null;
                  const imageTab=document.querySelector('#image-tab');imageTab.click();
                  if(document.querySelector('#image-panel').hidden ||
                     imageTab.getAttribute('aria-selected')!=='true' ||
                     !document.querySelector('#image-prompt') ||
                     !document.querySelector('#image-request-preview').hidden ||
                     !document.querySelector('#image-result').hidden ||
                     !document.querySelector('#image-dispatch').disabled)return null;
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
                        operation = str(uuid4())
                        location = server.project_creation_actions.register_location(
                            args.smoke_create, operation)
                        bootstrap = """(()=>{
                          const title='Nový projekt ze společného formuláře';
                          document.querySelector('#sidebar-create-project').click();
                          if(document.querySelector('#project-create-view').hidden ||
                             !document.querySelector('#project-home').hidden)throw new Error('Samostatná stránka vytvoření se neotevřela.');
                          document.querySelector('#new-project-title').value=title;
                          projectCreationAttempt={title,operation_id:OPERATION};
                          setProjectCreationLocation(LOCATION);
                          document.querySelector('#create-project').requestSubmit();
                          const confirm=setInterval(()=>{
                            if(!projectCreationPlan)return;
                            clearInterval(confirm);
                            document.querySelector('#project-create-confirm-check').click();
                            document.querySelector('#project-create-confirm').click();
                          },50);
                        })()""".replace('OPERATION', json.dumps(operation)).replace(
                            'LOCATION', json.dumps(location))
                        page.runJavaScript(bootstrap)
            view.loadFinished.connect(loaded)
        else:
            view.loadFinished.connect(lambda ok: None if ok else QMessageBox.warning(
                view, 'Nelze načíst rozhraní', 'Zavřete aplikaci a spusťte ji znovu.'))
        view.load(QUrl(server.origin + '/'))
        window.show()
        if not args.smoke:
            QTimer.singleShot(0, controller.recover)
        replication_scheduler = ReplicationScheduler(
            node_path, deployment='desktop')
        from spikes.federation_catalog import CatalogScheduler
        from spikes.federation_sync import ContentSyncScheduler
        catalog_scheduler = CatalogScheduler(
            node_path, deployment='desktop')
        content_scheduler = ContentSyncScheduler(
            node_path, deployment='desktop')
        replication_scheduler.start()
        catalog_scheduler.start()
        content_scheduler.start()
        result = app.exec()
        content_scheduler.stop()
        catalog_scheduler.stop()
        replication_scheduler.stop()
        controller.wait()
        federation_network.wait()
        federation_deployment.wait()
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
