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
from http.server import HTTPServer

from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.chat_service import ChatService
from spikes.project_creation import ProjectCreation
from spikes.project_creation_actions import ProjectCreationActions
from spikes.projects import Projects
from spikes.administration import Administration, AccessDenied
from spikes.metadata import MAX_FILE
from spikes.source_import import Sources
from spikes.media_service import MediaService
from spikes.notebooklm_import_actions import NotebookLMImportActions
from spikes.role_workflow_service import RoleWorkflowService
from spikes.summary_service import SummaryService
from spikes.extraction_service import ExtractionService
from spikes.metadata_suggestion_service import MetadataSuggestionService
from spikes.backend_contract import BackendResponseError, BackendUnknown
from spikes.publication_cms import PublicationCms

# The shell is shared byte-for-byte. This explicit bootstrap is the only web
# variant: it provides browser authentication and enables server capabilities.
WEB_HTML = HTML
WEB_CSS = CSS
WEB_JS = '''document.body.dataset.runtime='server';window.workspaceAutoStart=false;
document.querySelector('#source-import-local-only').disabled=true;
document.querySelector('#notebooklm-local-only').disabled=true;
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
  projectCreateForm.hidden=!admin;notebookImportButton.hidden=!admin;document.querySelector('#settings-users-tab').hidden=!admin;
  document.querySelector('#settings-cms-tab').hidden=!admin;
  document.querySelector('#settings-federation-tab').hidden=session.node_role!=='federation-admin';
  document.querySelector('#backend-metrics').hidden=!admin;
  document.querySelector('#backend-metrics-indicator').hidden=!admin;
  document.body.classList.add('authenticated');await loadProjects();
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
    post_paths = DesktopHandler.post_paths | {'/v1/administration', '/v1/session',
                                               '/v1/sources/import', '/v1/backend-metrics/status',
                                               '/v1/backend-metrics/configure', '/v1/backend-metrics/refresh',
                                               '/v1/notebooklm/preview', '/v1/notebooklm/plan',
                                               '/v1/notebooklm/confirm'}

    def do_POST(self):
        from spikes.federation_probe import PATH, reply_probe
        if self.path == PATH:
            return reply_probe(self)
        return super().do_POST()

    def authorized(self, auth):
        if hmac.compare_digest(auth.encode(), ('Bearer ' + self.server.token).encode()):
            self.actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
            return True
        try:
            self.actor = self.server.administration.authenticate(auth)
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
        # HTTPServer is intentionally single-threaded. Pin authority to the actual
        # local destination, never to untrusted Host/X-Forwarded-* headers.
        ip, port = self.connection.getsockname()[:2]
        self.server.authority = f'{ip}:{port}'
        self.server.origin = 'https://' + self.server.authority

    def request_authority(self):
        authority = self.single('Host')
        if authority == self.server.authority:
            return authority
        if self.server.hostname and authority == f'{self.server.hostname}:{self.server.server_port}':
            return authority
        return None

    def request_origin(self, authority):
        return 'https://' + authority

    def _can_write(self, project_id):
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
        if self.path in {'/v1/chat/configure', '/v1/chat/test'} \
                and not self.server.administration.is_admin(self.actor):
            return self.send_error(403)
        if self.path == '/v1/session':
            if request != {}:
                return self.send_error(400)
            return self.reply(200, {'user_id': self.actor['id'], 'node_role': self.actor['node_role'],
                                    'memberships': self.actor['memberships']})
        if self.path == '/v1/administration':
            try:
                result = self.server.administration.request(self.actor, request)
                result['projects'] = self.server.projects.catalog()
                return self.reply(200, result)
            except AccessDenied:
                return self.reply(403, {'error': 'Nedostatečné oprávnění nebo změněný registr. Načtěte správu znovu.'})
            except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
                return self.reply(422, {'error': 'Změnu nelze uložit. Ověřte údaje a dostupnost úložiště uzlu.'})
        if self.path.startswith('/v1/notebooklm/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            return super().dispatch(request)
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
        if self.path.startswith('/v1/publication-cms/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
        if self.path in {'/v1/projects/open', '/v1/artifacts/preview',
                         '/v1/artifacts/history/list', '/v1/artifacts/history/compare',
                         '/v1/artifacts/editor/open', '/v1/artifacts/delete/preview'}:
            if not isinstance(request, dict) or not self.server.administration.allowed(self.actor, request.get('project_id')):
                return self.send_error(403)
        if self.path == '/v1/artifacts/editor/save':
            document = request.get('document') if isinstance(request, dict) else None
            if not isinstance(document, dict) or not self._can_write(document.get('project_id')):
                return self.send_error(403)
        if self.path == '/v1/artifacts/delete/confirm':
            if not isinstance(request, dict) or not self._can_write(request.get('project_id')):
                return self.send_error(403)
        if self.path.startswith('/v1/projects/create/'):
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            return super().dispatch(request)
        if self.path == '/v1/sources/import':
            return self._import_source(request)
        return super().dispatch(request)

    def do_GET(self):
        if self.request_authority() is None:
            return self.send_error(403)
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


class WebServer(HTTPServer):
    def get_request(self):
        connection, address = super().get_request()
        try:
            peer = ipaddress.ip_address(address[0])
            if not peer.is_loopback and peer not in self.allowed_network:
                raise OSError('Client outside configured LAN')
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
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert, key)
    server = WebServer((bind, port), WebHandler)
    server.tls, server.allowed_network = tls, network
    server.hostname = hostname
    server.token, server.counter = token, 0
    server.projects = Projects(node, network=True)
    server.node = node
    server.project_creation_actions = ProjectCreationActions(
        node, projects_root=creator.configured_projects_root() or Path(node).parent / 'projects')
    server.chat_service = ChatService(node, server.projects)
    server.media_service = MediaService(node, server.projects,
        state_dir=server.chat_service.state_dir)
    server.role_workflow_service = RoleWorkflowService(node, server.projects,
        state_dir=server.chat_service.state_dir)
    server.summary_service = SummaryService(node, server.projects,
        state_dir=server.chat_service.state_dir,
        chat_state_dir=server.chat_service.state_dir)
    server.extraction_service = ExtractionService(node, server.projects,
        state_dir=server.chat_service.state_dir,
        chat_state_dir=server.chat_service.state_dir)
    server.metadata_suggestion_service = MetadataSuggestionService(node, server.projects,
        state_dir=server.chat_service.state_dir,
        chat_state_dir=server.chat_service.state_dir)
    server.publication_cms = PublicationCms(server.chat_service.state_dir)
    server.notebooklm_import_actions = NotebookLMImportActions(
        node, projects_root=creator.configured_projects_root() or Path(node).parent / 'projects')
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
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
