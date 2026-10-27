# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""HTTPS LAN workspace with project creation and local user/peer administration."""
import argparse
import ipaddress
import hmac
import os
from pathlib import Path
import re
import ssl
import stat
import sqlite3
import subprocess
from urllib.parse import urlsplit

from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.local_api import BoundedHTTPServer
from spikes.chat_service import ChatService
from spikes.project_creation import ProjectCreation
from spikes.project_creation_actions import ProjectCreationActions
from spikes.project_deletion import ProjectDeletion
from spikes.project_deletion_actions import ProjectDeletionActions
from spikes.projects import Projects
from spikes.administration import Administration, AccessDenied
from spikes.metadata import MAX_FILE
from spikes.source_import import Sources
from spikes.media_service import MediaService
from spikes.notebooklm_import_actions import NotebookLMImportActions
from spikes.role_workflow_service import RoleWorkflowService
from spikes.autonomy_service import AutonomyService
from spikes.summary_service import SummaryService
from spikes.extraction_service import ExtractionService
from spikes.metadata_suggestion_service import MetadataSuggestionService
from spikes.backend_contract import BackendResponseError, BackendUnknown
from spikes.publication_cms import PublicationCms
from spikes.google_drive_import import GoogleDriveImport
from spikes.application_access import ApplicationAccess

# The shell is shared byte-for-byte. This explicit bootstrap is the only web
# variant: it provides browser authentication and enables server capabilities.
WEB_HTML = HTML
WEB_CSS = CSS
WEB_JS = '''document.body.dataset.runtime='server';window.workspaceAutoStart=false;
document.querySelector('#source-import-local-only').disabled=true;
document.querySelector('#google-drive-local-only').disabled=true;
document.querySelector('#notebooklm-local-only').disabled=true;
document.querySelector('#presentation-tab').hidden=true;
document.querySelector('#outputs-overview-tab').hidden=false;
document.querySelector('#presentation-editor').hidden=true;
document.querySelector('#open-federation-network').closest('li').hidden=true;
document.querySelector('#open-federation-deployment').closest('li').hidden=true;
let accessKey='';
const notebookImportButton=document.querySelector('#open-notebooklm-import');
const originalFetch=window.fetch.bind(window);
window.fetch=(path,options={})=>{
 const url=new URL(path,location.href);
 if(url.origin!==location.origin)throw new Error('Nepovolená adresa');
 const headers=new Headers(options.headers);headers.set('Authorization','Bearer '+accessKey);
 return originalFetch(path,{...options,headers,credentials:'omit',redirect:'error'});
};
document.querySelector('#login-form').addEventListener('submit',async event=>{
 event.preventDefault();accessKey=document.querySelector('#access-key').value;
  document.querySelector('#access-key').value='';
  try{
  const response=await fetch('/v1/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!response.ok)throw new Error();
  const sessionResponse=await fetch('/v1/session',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  if(!sessionResponse.ok)throw new Error();
  const session=await sessionResponse.json();const admin=['node-admin','federation-admin'].includes(session.node_role);
  projectCreateForm.hidden=!admin;document.querySelector('#sidebar-create-project').hidden=!admin;notebookImportButton.hidden=!admin;document.querySelector('#settings-users-tab').hidden=!admin;
  document.querySelector('[data-settings-item="settings-users-tab"]').hidden=!admin;
  document.querySelector('#settings-cms-tab').hidden=!admin;
  document.querySelector('#settings-access-tab').hidden=!admin;
  document.querySelector('[data-settings-item="settings-access-tab"]').hidden=!admin;
  document.querySelector('#settings-federation-tab').hidden=!admin;
  document.querySelector('[data-settings-item="settings-federation-tab"]').hidden=!admin;
  document.querySelector('#federation-tab').hidden=!admin;
  document.querySelector('#backend-metrics').hidden=!admin;
  document.querySelector('#backend-metrics-indicator').hidden=!admin;
  document.querySelector('#openai-resource-provider').hidden=!admin;
  document.querySelector('#resource-monitor').hidden=!admin;
  document.querySelector('#resource-runtime-policy').hidden=!admin;
  document.querySelector('#model-catalog-import').hidden=!admin;
  document.querySelector('#model-catalog-knowledge').readOnly=!admin;
  document.querySelector('#atlascloud-backend-form').hidden=!admin;
  document.body.classList.add('authenticated');await loadProjects();if(admin)await loadBackendMetrics();
}catch(error){accessKey='';document.querySelector('#login-status').textContent='Přihlášení se nezdařilo.';}
});
window.addEventListener('pagehide',()=>{accessKey='';});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
document.querySelector('#logout').addEventListener('click',()=>{accessKey='';location.reload();});
''' + JS
ASSETS = {'/': ('text/html; charset=utf-8', WEB_HTML),
          '/app.css': ('text/css; charset=utf-8', WEB_CSS),
          '/app.js': ('text/javascript; charset=utf-8', WEB_JS)}


def secret(path):
    path = Path(path)
    if path.absolute() != path.resolve():
        raise ValueError('Secret path must not contain symlinks')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise ValueError('Secret must be owned by service user with mode 0600')
        value = handle.read(256).decode('ascii').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', value):
        raise ValueError('Expected a random access key (at least 32 random bytes)')
    return value


class WebHandler(DesktopHandler):
    max_body = 4 * ((MAX_FILE + 2) // 3) + 128 * 1024
    google_drive_callback_path = '/oauth/google-drive/callback'
    post_paths = DesktopHandler.post_paths | {'/v1/administration', '/v1/session',
                                               '/v1/federation/enroll',
                                               '/v1/federation/catalog/reconcile',
                                               '/v1/federation/content/reconcile',
                                               '/v1/federation/content/cancel',
                                               '/v1/federation/content/start-all',
                                               '/v1/federation/content/settings',
                                               '/v1/replications/status', '/v1/replications/sync',
                                               '/v1/outputs/definitions',
                                               '/v1/application-access',
                                               '/v1/sources/import', '/v1/backend-metrics/status',
                                               '/v1/backend-metrics/configure', '/v1/backend-metrics/refresh',
                                               '/v1/notebooklm/preview', '/v1/notebooklm/plan',
                                               '/v1/notebooklm/confirm'}

    def _do_POST(self):
        from spikes.federation_probe import PATH, reply_probe
        if self.path == PATH:
            return reply_probe(self)
        from spikes.federation_catalog import PATH as CATALOG_PATH, reply as reply_catalog
        if self.path == CATALOG_PATH:
            return reply_catalog(self)
        from spikes.project_replication import PATH as REPLICATION_PATH, reply
        if self.path == REPLICATION_PATH:
            return reply(self)
        from spikes.federation_sync import PATH as SYNC_PATH, reply as reply_sync
        if self.path == SYNC_PATH:
            return reply_sync(self)
        return super()._do_POST()

    def authorized(self, auth):
        if hmac.compare_digest(auth.encode(), ('Bearer ' + self.server.token).encode()):
            self.actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
            return True
        try:
            operation = (self.server.administration.authenticate_readonly
                         if self.path == '/v1/node-telemetry/status'
                         else self.server.administration.authenticate)
            self.actor = operation(auth)
            return self.actor is not None
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            self.actor = None
            return False

    def reply(self, code, payload):
        if code == 200 and self.path == '/v1/projects' and isinstance(payload, dict) and 'projects' in payload:
            payload = dict(payload, projects=[p for p in payload['projects']
                if self.server.administration.allowed(self.actor, p['id'])])
        return super().reply(code, payload)

    def setup(self):
        super().setup()
        # Pin authority to this connection, never to shared mutable server state
        # or untrusted Host/X-Forwarded-* headers.
        ip, port = self.connection.getsockname()[:2]
        self.local_authority = f'{ip}:{port}'

    def request_authority(self):
        authority = self.single('Host')
        if authority == self.local_authority:
            return authority
        if self.server.hostname and authority == f'{self.server.hostname}:{self.server.server_port}':
            return authority
        return None

    def request_origin(self, authority):
        return 'https://' + authority

    def _can_write(self, project_id):
        try:
            self.server.administration.assert_project_writable(project_id)
        except (AccessDenied, ValueError, OSError, subprocess.SubprocessError):
            return False
        if self.server.administration.is_admin(self.actor):
            return True
        return bool(self.actor and self.actor.get('memberships', {}).get(project_id) in {'editor', 'project-admin'})

    def _import_source(self, request):
        try:
            if not isinstance(request, dict) or set(request) != {'operation_id', 'source'}:
                return self.send_error(400)
            source = request['source']
            if not isinstance(source, dict) or not self._can_write(source.get('project_id')):
                return self.send_error(403)
            if source.get('privacy') not in {'public', 'project', 'confidential'}:
                return self.reply(422, {'error': 'Webový import nepovoluje local-only obsah.'})
            author = self.actor.get('id') or ProjectCreation(self.server.node).author_id()
            receipt = Sources(self.server.node).import_source(source, request['operation_id'],
                author_id=author, importer_name='workspace-web-import')
            self.reply(200, {'id': source['project_id'], 'commit_id': receipt['commit_id']})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            self.reply(422, {'error': 'Zdroj nelze importovat. Ověřte typ, velikost, metadata a aktuální verzi projektu.'})

    def dispatch(self, request):
        if self.path.startswith('/v1/projects/repair/'):
            return self.send_error(404)
        if self.path.startswith('/v1/julia/'):
            if not isinstance(request, dict):
                return self.send_error(400)
            if self.path in {'/v1/julia/publish', '/v1/julia/editor/save'} \
                    and request.get('privacy') == 'local-only':
                return self.reply(422, {'error': 'Webová operace nepovoluje local-only obsah.'})
            project_id = request.get('project_id')
            read_only = {'/v1/julia/definitions', '/v1/julia/status',
                         '/v1/julia/output', '/v1/julia/editor/open'}
            allowed = (self.server.administration.allowed(self.actor, project_id)
                       if self.path in read_only else self._can_write(project_id))
            if not allowed:
                return self.send_error(403)
            return super().dispatch(request)
        if self.path.startswith('/v1/autonomy/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            project_id = request.get('project_id') if isinstance(request, dict) else None
            if project_id is not None and not self._can_write(project_id):
                return self.send_error(403)
            service = self.server.autonomy_service
            try:
                if self.path == '/v1/autonomy/status' and isinstance(request, dict) \
                        and set(request) <= {'project_id'}:
                    return self.reply(200, service.list(
                        request.get('project_id'), allow_local_only=False))
                if self.path in {'/v1/autonomy/prepare', '/v1/autonomy/replace'} \
                        and isinstance(request, dict):
                    operation = service.prepare if self.path.endswith('/prepare') else service.replace
                    return self.reply(200, operation(request, allow_local_only=False))
                if self.path == '/v1/autonomy/pause-all' and request == {}:
                    service.pause_all()
                    return self.reply(200, service.list(allow_local_only=False))
                if self.path == '/v1/autonomy/resume-all' and request == {}:
                    service.resume_all()
                    return self.reply(200, service.list(allow_local_only=False))
                workflow_id = request.get('workflow_id') if isinstance(request, dict) else None
                if workflow_id is not None:
                    service.get(workflow_id, allow_local_only=False)
            except (ValueError, OSError, sqlite3.Error) as exc:
                return self.reply(422, {'error': str(exc)})
            return super().dispatch(request)
        if (self.path in {'/v1/node-telemetry/status',
                          '/v1/node-telemetry/configure'}
                and not self.server.administration.is_admin(self.actor)):
            return self.send_error(403)
        if self.path == '/v1/application-access':
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            try:
                if request == {'action': 'status'}:
                    return self.reply(200, self.server.application_access.status(self.client_address[0]))
                if isinstance(request, dict) and set(request) == {'action', 'settings'} \
                        and request['action'] == 'preview':
                    return self.reply(200, {'plan': self.server.application_access.preview(
                        request['settings'], self.client_address[0])})
                if isinstance(request, dict) \
                        and set(request) == {'action', 'plan', 'confirmed_disconnect'} \
                        and request['action'] == 'confirm':
                    return self.reply(200, self.server.application_access.confirm(
                        request['plan'], self.client_address[0], request['confirmed_disconnect']))
                return self.send_error(400)
            except (ValueError, OSError, sqlite3.Error) as exc:
                return self.reply(422, {'error': str(exc)})
        if self.path == '/v1/google-drive/configure':
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
        if self.path == '/v1/google-drive/authorize':
            if (not isinstance(request, dict) or not self._can_write(request.get('project_id'))
                    or request.get('privacy') == 'local-only'):
                return self.send_error(403)
        if self.path == '/v1/google-drive/confirm':
            plan = request.get('plan') if isinstance(request, dict) else None
            if (not isinstance(plan, dict) or not self._can_write(plan.get('project_id'))
                    or plan.get('privacy') == 'local-only'):
                return self.send_error(403)
        if self.path == '/v1/google-drive/preview':
            selection_id = request.get('selection_id') if isinstance(request, dict) else None
            if not isinstance(selection_id, str):
                return self.send_error(403)
            actor_id = self.actor.get('id') or ProjectCreation(self.server.node).author_id()
            selected = self.server.google_drive_import.selection(actor_id, selection_id)
            if (not selected or not self._can_write(selected['project_id'])
                    or selected['privacy'] == 'local-only'):
                return self.send_error(403)
        if self.path == '/v1/google-drive/recover':
            actor_id = self.actor.get('id') or ProjectCreation(self.server.node).author_id()
            pending = self.server.google_drive_import.pending(actor_id)
            if (not pending or not self._can_write(pending['project_id'])
                    or pending['privacy'] == 'local-only'):
                return self.send_error(403)
        if self.path in {'/v1/chat/configure', '/v1/chat/test', '/v1/chat/models',
                         '/v1/search/configure', '/v1/search/test',
                         '/v1/model-catalog/import', '/v1/atlascloud/models',
                         '/v1/atlascloud/configure',
                         '/v1/atlascloud/remove', '/v1/backend-catalog/reset',
                         '/v1/model-selection/preferences'} \
                and not self.server.administration.is_admin(self.actor):
            return self.send_error(403)
        if self.path == '/v1/session':
            if request != {}:
                return self.send_error(400)
            return self.reply(200, {'user_id': self.actor['id'], 'node_role': self.actor['node_role'],
                                    'memberships': self.actor['memberships']})
        if self.path == '/v1/federation/enroll':
            try:
                from spikes.federation_enrollment import accept_on_server
                return self.reply(200, accept_on_server(
                    self.server.administration, self.actor, request))
            except AccessDenied:
                return self.reply(403, {'error': 'Přihlášení klientského uzlu není povoleno.'})
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return self.reply(422, {'error': 'Identitu klientského uzlu nelze ověřit nebo uložit.'})
        if self.path == '/v1/administration':
            try:
                result = self.server.administration.request(self.actor, request)
                result['projects'] = self.server.projects.catalog()
                from spikes.replication_control import ReplicationControl
                result['replication_statuses'] = ReplicationControl(
                    self.server.node, deployment='web').statuses(
                        result['replications'], result['node_id'])
                from spikes.federation_catalog import CatalogControl
                result.update(CatalogControl(
                    self.server.node, deployment='web').view())
                from spikes.federation_sync import ContentSyncControl
                result['content_sync_statuses'] = ContentSyncControl(
                    self.server.node, deployment='web').statuses()
                result['content_sync_settings'] = ContentSyncControl(
                    self.server.node, deployment='web').settings()
                return self.reply(200, result)
            except AccessDenied:
                return self.reply(403, {'error': 'Nedostatečné oprávnění nebo změněný registr. Načtěte správu znovu.'})
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return self.reply(422, {'error': 'Změnu nelze uložit. Ověřte údaje a dostupnost úložiště uzlu.'})
        if self.path == '/v1/federation/catalog/reconcile':
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            if not isinstance(request, dict) or set(request) != {'peer_id'}:
                return self.send_error(400)
            try:
                from spikes.federation_catalog import CatalogControl
                control = CatalogControl(self.server.node, deployment='web')
                control.synchronize(request['peer_id'])
                return self.reply(200, control.view())
            except AccessDenied:
                return self.send_error(403)
            except Exception:
                return self.reply(409, {'error': 'Katalog projektů se nepodařilo přenést; bezpečný stav je uložen pro opakování.'})
        if self.path in {'/v1/federation/content/reconcile',
                         '/v1/federation/content/cancel',
                         '/v1/federation/content/start-all',
                         '/v1/federation/content/settings'}:
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            try:
                from spikes.federation_sync import ContentSyncControl
                control = ContentSyncControl(self.server.node, deployment='web')
                if self.path.endswith('/start-all'):
                    if request != {}: return self.send_error(400)
                    return self.reply(200, {
                        'batch': control.start_all(),
                        'content_sync_settings': control.settings(),
                        'content_sync_statuses': control.statuses()})
                if self.path.endswith('/settings'):
                    if (not isinstance(request, dict) or set(request) != {
                            'automatic_enabled', 'expected_revision'}):
                        return self.send_error(400)
                    settings = control.configure(**request)
                    return self.reply(200, {
                        'content_sync_settings': settings,
                        'content_sync_statuses': control.statuses()})
                if (not isinstance(request, dict)
                        or set(request) != {'peer_id', 'project_id'}):
                    return self.send_error(400)
                changed = (control.cancel(request['peer_id'], request['project_id'])
                           if self.path.endswith('/cancel') else
                           control.start(request['peer_id'], request['project_id']))
                return self.reply(200, {'changed': changed,
                                        'content_sync_statuses': control.statuses()})
            except AccessDenied:
                return self.send_error(403)
            except Exception:
                return self.reply(409, {'error': 'Obsah projektu se nepodařilo synchronizovat; bezpečný stav je uložen pro opakování.'})
        if self.path in {'/v1/replications/status', '/v1/replications/sync'}:
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            try:
                from spikes.replication_control import ReplicationControl
                control = ReplicationControl(self.server.node, deployment='web')
                state = self.server.administration.request(self.actor, {'action': 'list'})
                if self.path == '/v1/replications/sync':
                    if (not isinstance(request, dict)
                            or set(request) != {'replication_id'}):
                        return self.send_error(400)
                    control.synchronize(request['replication_id'])
                    state = self.server.administration.request(self.actor, {'action': 'list'})
                return self.reply(200, {'statuses': control.statuses(
                    state['replications'], state['node_id'])})
            except AccessDenied:
                return self.send_error(403)
            except Exception:
                return self.reply(409, {'error': 'Synchronizaci se nepodařilo dokončit; '
                                               'aktuální stav je uložen pro bezpečné opakování.'})
        if self.path.startswith('/v1/notebooklm/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            return super().dispatch(request)
        if self.path == '/v1/outputs/definitions':
            if (not isinstance(request, dict)
                    or set(request) != {'project_id', 'expected_head'}
                    or not self.server.administration.allowed(
                        self.actor, request.get('project_id'))):
                return self.send_error(403)
            try:
                from spikes.presentation_documents import PresentationDocuments
                result = PresentationDocuments(self.server.node).open(request['project_id'])
                if result['commit_id'] != request['expected_head']:
                    raise ValueError('Project changed before output projection')
                return self.reply(200, result)
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return self.reply(409, {'error': 'Definice výstupů nelze načíst z potvrzené verze projektu.'})
        if self.path.startswith('/v1/backend-metrics/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            try:
                if self.path == '/v1/backend-metrics/status' and request == {}:
                    return self.reply(200, self.server.chat_service.account_metrics_status())
                if self.path == '/v1/backend-metrics/configure' and isinstance(request, dict):
                    return self.reply(200, self.server.chat_service.configure_account_metrics(request))
                if self.path == '/v1/backend-metrics/refresh' and isinstance(request, dict):
                    return self.reply(200, self.server.chat_service.refresh_account_metrics(request))
                return self.send_error(400)
            except (ValueError, OSError, sqlite3.Error):
                return self.reply(422, {'error': 'Účetní přehled nelze načíst nebo uložit. '
                                       'Ověřte administrátorský klíč a lokální stav.'})
        if self.path in {'/v1/media/comfyui/configure', '/v1/media/openai/configure'}:
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
        if self.path == '/v1/media/status':
            if request != {}: return self.send_error(400)
            return self.reply(200, self.server.media_service.status(owner_id=self.actor['id']))
        if self.path in {'/v1/media/preview', '/v1/media/confirm', '/v1/media/publish'}:
            if not isinstance(request, dict) or not self._can_write(request.get('project_id')):
                return self.send_error(403)
            try:
                if self.path == '/v1/media/preview':
                    result = self.server.media_service.preview(request, owner_id=self.actor['id'])
                elif self.path == '/v1/media/confirm':
                    result = self.server.media_service.confirm(request, owner_id=self.actor['id'])
                else:
                    result = self.server.media_service.publish(request, owner_id=self.actor['id'])
                return self.reply(200, result)
            except BackendUnknown:
                return self.reply(409, {'error': 'Výsledek obrazového běhu není známý; '
                                       'požadavek automaticky neopakujte.'})
            except BackendResponseError:
                return self.reply(502, {'error': 'Obrazový backend nevrátil platný PNG výsledek.'})
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return self.reply(422, {'error': 'Obrazový požadavek nelze provést. Ověřte '
                                       'projekt, oprávnění, backend a lokální stav.'})
        if self.path.startswith('/v1/workflows/'):
            if not isinstance(request, dict): return self.send_error(400)
            project_id = request.get('project_id')
            if not self._can_write(project_id): return self.send_error(403)
            owner_id = self.actor.get('id')
            try:
                if self.path == '/v1/workflows/status' and set(request) == {'project_id'}:
                    result = self.server.role_workflow_service.status(
                        owner_id=owner_id, allow_local_only=False)
                    result['workflows'] = [item for item in result['workflows']
                                           if item['project_id'] == project_id]
                elif self.path == '/v1/workflows/prepare':
                    result = self.server.role_workflow_service.prepare(
                        request, owner_id=owner_id, allow_local_only=False)
                elif (self.path in {'/v1/workflows/creator/dispatch',
                                    '/v1/workflows/opponent/dispatch'}
                      and set(request) == {'workflow_id', 'project_id', 'approval_digest'}):
                    owned = self.server.role_workflow_service.get(
                        request['workflow_id'], owner_id=owner_id, allow_local_only=False)
                    if owned['project_id'] != project_id: return self.send_error(403)
                    method = (self.server.role_workflow_service.dispatch_creator
                              if self.path.endswith('/creator/dispatch') else
                              self.server.role_workflow_service.dispatch_opponent)
                    result = method(request['workflow_id'], request['approval_digest'],
                        owner_id=owner_id, allow_local_only=False)
                elif (self.path == '/v1/workflows/opponent/prepare'
                      and set(request) == {'workflow_id', 'project_id'}):
                    owned = self.server.role_workflow_service.get(
                        request['workflow_id'], owner_id=owner_id, allow_local_only=False)
                    if owned['project_id'] != project_id: return self.send_error(403)
                    result = self.server.role_workflow_service.prepare_opponent(
                        request['workflow_id'], owner_id=owner_id, allow_local_only=False)
                elif self.path == '/v1/workflows/publish':
                    result = self.server.role_workflow_service.publish(
                        request, owner_id=owner_id, allow_local_only=False)
                else:
                    return self.send_error(400)
                return self.reply(200, result)
            except BackendUnknown:
                return self.reply(409, {'error': 'Výsledek workflow kroku není známý; '
                                       'požadavek automaticky neopakujte.'})
            except BackendResponseError:
                return self.reply(502, {'error': 'Workflow backend nevrátil platný výsledek.'})
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return self.reply(422, {'error': 'Workflow požadavek nelze provést. Ověřte '
                                       'projekt, oprávnění, backend, privacy a lokální stav.'})
        if self.path in {'/v1/external/send', '/v1/external/send-stream',
                         '/v1/external/request'}:
            # The current chat store is bound to the desktop/node identity. Do not
            # expose that history through a different web account identity.
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
        if self.path.startswith('/v1/tasks/search/'):
            # Search task state currently uses the same node-local identity as
            # desktop chat history. Do not let another web account confirm or
            # inspect that identity's prepared disclosure.
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
        if self.path in {'/v1/chat/send', '/v1/chat/send-stream'}:
            if not isinstance(request, dict) or not self._can_write(request.get('project_id')):
                return self.send_error(403)
        if self.path in {'/v1/chat/assign', '/v1/chat/snapshot', '/v1/chat/output'}:
            if not isinstance(request, dict) or not self._can_write(request.get('project_id')):
                return self.send_error(403)
        if self.path.startswith('/v1/publication-cms/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
        if self.path in {'/v1/projects/open', '/v1/artifacts/preview',
                         '/v1/artifacts/history/list', '/v1/artifacts/history/compare',
                         '/v1/projects/conflicts/list', '/v1/projects/conflicts/preview',
                         '/v1/artifacts/editor/open', '/v1/artifacts/delete/preview'}:
            if not isinstance(request, dict) or not self.server.administration.allowed(self.actor, request.get('project_id')):
                return self.send_error(403)
        if self.path == '/v1/artifacts/editor/save':
            document = request.get('document') if isinstance(request, dict) else None
            if not isinstance(document, dict) or not self._can_write(document.get('project_id')):
                return self.send_error(403)
        if self.path == '/v1/projects/conflicts/confirm':
            resolution = request.get('resolution') if isinstance(request, dict) else None
            if (not isinstance(resolution, dict)
                    or not self._can_write(resolution.get('project_id'))):
                return self.send_error(403)
        if self.path == '/v1/artifacts/delete/confirm':
            if not isinstance(request, dict) or not self._can_write(request.get('project_id')):
                return self.send_error(403)
        if self.path.startswith('/v1/projects/create/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            return super().dispatch(request)
        if self.path.startswith('/v1/projects/delete/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            return super().dispatch(request)
        if self.path == '/v1/sources/import':
            return self._import_source(request)
        # Desktop calls retain the node-local author. Network requests bind the
        # authenticated account only for this request, including streamed chat.
        project_ids = ({item['id'] for item in self.server.projects.catalog()}
                       if self.server.administration.is_admin(self.actor) else
                       set(self.actor.get('memberships', {})))
        writable_project_ids = (project_ids if self.server.administration.is_admin(self.actor)
            else {project_id for project_id, role in
                  self.actor.get('memberships', {}).items()
                  if role in {'editor', 'project-admin'}})
        with self.server.chat_service.as_user(
                self.actor.get('id'), project_ids=project_ids,
                writable_project_ids=writable_project_ids):
            return super().dispatch(request)

    def _do_GET(self):
        if self.request_authority() is None:
            return self.send_error(403)
        if urlsplit(self.path).path == '/oauth/google-drive/callback':
            return super()._do_GET()
        if self.path not in ASSETS:
            return self.send_error(404)
        kind, content = ASSETS[self.path]
        data = content.encode()
        self.send_response_only(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src data:; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)


class WebServer(BoundedHTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        try:
            peer = ipaddress.ip_address(address[0])
            if not self.application_access.allows(peer):
                raise OSError('Client outside configured application access policy')
            connection.settimeout(2)
            return self.tls.wrap_socket(connection, server_side=True), address
        except (OSError, ValueError):
            connection.close()
            raise OSError('Connection rejected') from None


def validate_hostname(hostname):
    if hostname is None:
        return None
    if (not isinstance(hostname, str) or len(hostname) > 253
            or hostname.endswith('.') or '.' not in hostname):
        raise ValueError('Expected a DNS hostname such as workspace.example.internal')
    labels = hostname.split('.')
    if any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
           for label in labels):
        raise ValueError('Expected a DNS hostname such as workspace.example.internal')
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        return hostname.lower()
    raise ValueError('DNS hostname must not be an IP address')


def make_server(bind, port, lan, cert, key, token_file, node, *, hostname=None):
    network = ipaddress.ip_network(lan)
    if network.version != 4 or network.prefixlen < 8 or not network.is_private:
        raise ValueError('Specify a private IPv4 LAN subnet')
    ipaddress.IPv4Address(bind)
    hostname = validate_hostname(hostname)
    token = secret(token_file)
    creator = ProjectCreation(node)
    if creator.database.exists():
        creator.recover()
        ProjectDeletion(node).recover()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert, key)
    server = WebServer((bind, port), WebHandler)
    server.tls = tls
    server.hostname = hostname
    server.token, server.counter = token, 0
    server.projects = Projects(node, network=True)
    server.node = node
    server.application_access = ApplicationAccess(node, network)
    server.project_creation_actions = ProjectCreationActions(
        node, projects_root=creator.configured_projects_root() or Path(node).parent / 'projects')
    server.project_deletion_actions = ProjectDeletionActions(node)
    server.chat_service = ChatService(node, server.projects)
    server.media_service = MediaService(node, server.projects,
        state_dir=server.chat_service.state_dir)
    server.role_workflow_service = RoleWorkflowService(node, server.projects,
        state_dir=server.chat_service.state_dir)
    server.autonomy_service = AutonomyService(node, server.projects,
        state_dir=server.chat_service.state_dir, chat_service=server.chat_service,
        role_workflow_service=server.role_workflow_service)
    server.summary_service = SummaryService(node, server.projects,
        state_dir=server.chat_service.state_dir,
        chat_state_dir=server.chat_service.state_dir)
    server.extraction_service = ExtractionService(node, server.projects,
        state_dir=server.chat_service.state_dir,
        chat_state_dir=server.chat_service.state_dir)
    server.metadata_suggestion_service = MetadataSuggestionService(node, server.projects,
        state_dir=server.chat_service.state_dir,
        chat_state_dir=server.chat_service.state_dir)
    from spikes.julia_workspace import JuliaWorkspaceService
    server.julia_workspace = JuliaWorkspaceService(node, server.projects)
    server.publication_cms = PublicationCms(server.chat_service.state_dir)
    server.notebooklm_import_actions = NotebookLMImportActions(
        node, projects_root=creator.configured_projects_root() or Path(node).parent / 'projects')
    server.google_drive_import = GoogleDriveImport(node)
    server.administration = Administration(node)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8443)
    for option in ('lan', 'cert', 'key', 'token-file', 'node'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--hostname')
    args = parser.parse_args()
    with make_server(args.bind, args.port, args.lan, args.cert, args.key,
                     args.token_file, args.node, hostname=args.hostname) as server:
        from spikes.replication_control import ReplicationScheduler
        from spikes.federation_catalog import CatalogScheduler
        from spikes.federation_sync import ContentSyncScheduler
        scheduler = ReplicationScheduler(args.node, deployment='web')
        catalog_scheduler = CatalogScheduler(args.node, deployment='web')
        content_scheduler = ContentSyncScheduler(args.node, deployment='web')
        scheduler.start()
        catalog_scheduler.start()
        content_scheduler.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            content_scheduler.stop()
            catalog_scheduler.stop()
            scheduler.stop()


if __name__ == '__main__':
    main()
