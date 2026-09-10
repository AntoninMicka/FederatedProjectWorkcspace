# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Single-user HTTPS read-only LAN viewer. No Qt, cookies or project writers."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import ssl
import stat
from http.server import HTTPServer

from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.projects import Projects

LOGIN = '''<section id="login"><h1>Projektový workspace</h1>
<form id="login-form"><label>Přístupový klíč <input id="access-key" type="password" required autocomplete="off"></label>
<button>Přihlásit</button><p id="login-status" role="status"></p></form></section>'''
WEB_HTML = HTML.replace('<body>', '<body>' + LOGIN).replace(
    '<div class="node-note">', '<button id="logout">Odhlásit</button><div class="node-note">').replace(
    'Na tomto počítači', 'Na serveru').replace(
    'Nový projekt vytvoříte tlačítkem v horní liště.',
    'Webový náhled umožňuje čtení projektů. Úpravy provádějte v desktopové aplikaci.')
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
  document.body.classList.add('authenticated');await loadProjects();
 }catch(error){accessKey='';document.querySelector('#login-status').textContent='Přihlášení se nezdařilo.';}
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
#login input{padding:12px;margin:12px}#create-main-todo,#todo-help{display:none!important}'''
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
    def setup(self):
        super().setup()
        # HTTPServer is intentionally single-threaded. Pin authority to the actual
        # local destination, never to untrusted Host/X-Forwarded-* headers.
        ip, port = self.connection.getsockname()[:2]
        self.server.authority = f'{ip}:{port}'
        self.server.origin = 'https://' + self.server.authority

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
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(cert, key)
    server = WebServer((bind, port), WebHandler)
    server.tls, server.allowed_network = tls, network
    server.token, server.counter = token, 0
    server.projects = Projects(node, network=True)
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
