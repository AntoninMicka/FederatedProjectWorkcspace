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
from uuid import uuid4

from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.project_creation import CreationConflict, ProjectCreation
from spikes.projects import Projects
from spikes.administration import Administration, AccessDenied, identifier
from spikes.web_administration import ADMIN_HTML, ADMIN_CSS, ADMIN_JS

HTML = HTML.replace('<body>', '<body>' + ADMIN_HTML)
CSS += ADMIN_CSS
JS = JS.removesuffix('loadProjects();\n') + ADMIN_JS

LOGIN = '''<section id="login"><h1>Projektový workspace</h1>
<form id="login-form"><label>Přístupový klíč <input id="access-key" type="password" required autocomplete="off"></label>
<button>Přihlásit</button><p id="login-status" role="status"></p></form></section>'''
WEB_HTML = HTML.replace('<body>', '<body>' + LOGIN).replace(
    '<div class="node-note">', '<button id="logout">Odhlásit</button><div class="node-note">').replace(
    'Na tomto počítači', 'Na serveru').replace(
    'Nový projekt vytvoříte tlačítkem v horní liště.',
    'Projekt můžete vytvořit bez desktopové aplikace.')
WEB_HTML = WEB_HTML.replace(
    '<p class="home-help">Projekt můžete vytvořit bez desktopové aplikace.</p>',
    '<form id="create-project" aria-label="Vytvořit projekt">'
    '<label for="new-project-title">Název nového projektu</label>'
    '<div class="project-create-row"><input id="new-project-title" type="text" required minlength="1" maxlength="200" placeholder="Můj projekt">'
    '<button id="create-project-btn">Vytvořit projekt</button></div>'
    '<p id="create-project-status" role="status"> </p></form>'
    '<p class="home-help">Projekt můžete vytvořit bez desktopové aplikace.</p>')
# A separate asset preserves the desktop/native authentication contract.
WEB_JS = '''let accessKey='';
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
  projectCreateForm.hidden=!admin;document.querySelector('#administration-open').hidden=!admin;
  document.body.classList.add('authenticated');await loadProjects();
}catch(error){accessKey='';document.querySelector('#login-status').textContent='Přihlášení se nezdařilo.';}
});
const projectCreateForm=document.querySelector('#create-project');
const createStatus=document.querySelector('#create-project-status');
let creationAttempt=null;
projectCreateForm.addEventListener('submit',async(event)=>{
 event.preventDefault();
 const title=document.querySelector('#new-project-title').value.trim();
 if(!title){createStatus.textContent='Zadejte název projektu.';return;}
 createStatus.textContent='Vytvářím...';
 if(!creationAttempt || creationAttempt.title!==title)creationAttempt={title,operation_id:crypto.randomUUID()};
 document.querySelector('#create-project-btn').disabled=true;
 try{
  const response=await fetch('/v1/projects/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(creationAttempt)});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || 'Projekt se nepodařilo vytvořit.');
  createStatus.textContent=`Projekt „${result.title}“ vytvořen.`;
  document.querySelector('#new-project-title').value='';creationAttempt=null;
  await loadProjects(result.id);
 }catch(error){createStatus.textContent=error.message || 'Projekt se nepodařilo vytvořit.';}
 finally{document.querySelector('#create-project-btn').disabled=false;}
});
window.addEventListener('pagehide',()=>{accessKey='';});
window.addEventListener('pageshow',event=>{if(event.persisted)location.reload();});
document.querySelector('#logout').addEventListener('click',()=>{accessKey='';location.reload();});
''' + JS.removesuffix('loadProjects();\n').replace(
    'createTodo.hidden=!!todo;', 'createTodo.hidden=true;').replace(
    'Založte seznam a mějte úkoly projektu po ruce.', 'Projekt zatím nemá hlavní seznam úkolů.').replace(
    'První dokument vytvoříte tlačítkem Dokumenty v horní liště.', 'Dokumenty vytvoříte v desktopové aplikaci.')
WEB_CSS = CSS + '''body:not(.authenticated)>aside,body:not(.authenticated)>main{display:none}
body.authenticated>#login{display:none}#login{margin:10vh auto;padding:24px}
#login input{padding:12px;margin:12px}#create-main-todo,#todo-help{display:none!important}
.project-create-row{display:flex;gap:12px;align-items:flex-start;max-width:520px}#new-project-title{flex:1;min-width:0;padding:12px}#create-project-status{font-size:12px;min-height:14px;color:#47635f}
@media(max-width:600px){.project-create-row{flex-direction:column}#new-project-title{width:100%;box-sizing:border-box}}'''
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
    post_paths = DesktopHandler.post_paths | {'/v1/projects/create', '/v1/administration', '/v1/session'}

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

    def _default_projects_root(self):
        return Path(self.server.node).parent / 'projects'

    def _create_project(self, request):
        if not isinstance(request, dict) or not {'title'} <= set(request) <= {'title', 'operation_id'} or not isinstance(request['title'], str):
            return self.send_error(400)
        title = request['title']
        try:
            root = self._default_projects_root()
            root.mkdir(mode=0o700, exist_ok=True)
            operation_id = request.get('operation_id', str(uuid4()))
            identifier(operation_id)
            target = root / f'projekt-{operation_id}'
            creator = ProjectCreation(self.server.node)
            receipt = creator.create(title, target, operation_id)
            self.server.projects = Projects(self.server.node, network=True)
            self.reply(200, receipt)
        except (ValueError, CreationConflict, OSError, sqlite3.Error, subprocess.SubprocessError):
            self.reply(422, {'error': 'Projekt se nepodařilo vytvořit. Ověřte název a dostupnost úložiště.'})

    def dispatch(self, request):
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
        if self.path in {'/v1/projects/open', '/v1/artifacts/preview'}:
            if not isinstance(request, dict) or not self.server.administration.allowed(self.actor, request.get('project_id')):
                return self.send_error(403)
        if self.path == '/v1/projects/create':
            if not self.server.administration.is_admin(self.actor):
                return self.send_error(403)
            return self._create_project(request)
        return super().dispatch(request)

    def do_GET(self):
        if self.single('Host') != self.server.authority:
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
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
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


def make_server(bind, port, lan, cert, key, token_file, node):
    network = ipaddress.ip_network(lan)
    if network.version != 4 or network.prefixlen < 8 or not network.is_private:
        raise ValueError('Specify a private IPv4 LAN subnet')
    ipaddress.IPv4Address(bind)
    token = secret(token_file)
    creator = ProjectCreation(node)
    if creator.database.exists():
        creator.recover()
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert, key)
    server = WebServer((bind, port), WebHandler)
    server.tls, server.allowed_network = tls, network
    server.token, server.counter = token, 0
    server.projects = Projects(node, network=True)
    server.node = node
    server.administration = Administration(node)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8443)
    for option in ('lan', 'cert', 'key', 'token-file', 'node'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args()
    with make_server(args.bind, args.port, args.lan, args.cert, args.key, args.token_file, args.node) as server:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    main()
