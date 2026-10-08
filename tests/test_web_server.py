# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import http.client
import io
import os
import json
from pathlib import Path
import secrets
import ssl
import subprocess
import tempfile
import threading
import tarfile
import unittest
from uuid import uuid4

from spikes.web_server import make_server, secret, WEB_HTML, WEB_CSS, WEB_JS
from spikes.projects import Projects
from tests import test_projects
from tests.fixtures import markdown, metadata, ENTITY
from spikes.source_import import Sources, request_from_bytes
from spikes.configuration import parse_node, read_config
from tests.test_notebooklm_import import valid_members


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cert, self.key = self.root/'cert.pem', self.root/'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(self.key), '-out', str(self.cert), '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=IP:127.0.0.1'],
                       check=True, capture_output=True)
        self.token = secrets.token_urlsafe(32)
        self.token_file = self.root/'token'
        self.token_file.write_text(self.token); self.token_file.chmod(0o600)
        self.server = make_server('127.0.0.1', 0, '192.168.100.0/24', self.cert, self.key,
                                  self.token_file, self.root/'node.json')
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.addCleanup(self.stop)
        self.authority = f'127.0.0.1:{self.server.server_port}'
        self.context = ssl.create_default_context(cafile=self.cert)

    def stop(self):
        self.server.shutdown(); self.thread.join(); self.server.server_close()

    def request(self, method='POST', path='/v1/projects', body='{}', headers=None):
        conn = http.client.HTTPSConnection('127.0.0.1', self.server.server_port,
                                          context=self.context, timeout=5)
        h = {'Content-Type': 'application/json', 'Authorization': 'Bearer '+self.token}
        h.update(headers or {})
        conn.request(method, path, body=body if method == 'POST' else None, headers=h)
        result = conn.getresponse()
        code, data, response_headers = result.status, result.read(), dict(result.getheaders())
        conn.close()
        return code, data, response_headers

    def notebook_archive(self):
        path = self.root / 'notebooklm.tgz'
        with tarfile.open(path, 'w:gz') as bundle:
            for member_name, raw in valid_members().items():
                info = tarfile.TarInfo(member_name); info.size = len(raw); info.mode = 0o600
                bundle.addfile(info, io.BytesIO(raw))
        return path

    def test_https_auth_origin_host_routes_and_no_token_bootstrap(self):
        self.assertEqual(self.request()[0], 200)
        for headers, code in [({'Authorization':''},401), ({'Authorization':'Bearer bad'},401),
                              ({'Origin':'https://evil.invalid'},403), ({'Host':'evil.invalid'},403),
                              ({'Sec-Fetch-Site':'cross-site'},403)]:
            self.assertEqual(self.request(headers=headers)[0], code)
        self.assertEqual(self.request(headers={'Origin':'https://'+self.authority})[0],200)
        self.assertEqual(self.request(path='/v1/projects/create', body='{}')[0], 400)
        code, data, _ = self.request(path='/v1/projects/create', body=json.dumps({'title':'Nový projekt'}))
        self.assertEqual(code, 200)
        created = json.loads(data)
        code, catalog, _ = self.request(body='{"details":true}')
        self.assertEqual(code, 200)
        self.assertIn(created['id'], [p['id'] for p in json.loads(catalog)['projects']])
        self.assertEqual(self.request(path='/v1/projects/open', body=json.dumps({'project_id':created['id']}))[0], 200)
        code, data, _ = self.request(path='/v1/workflows/status',
            body=json.dumps({'project_id': created['id']}))
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(data), {'workflows': []})
        for path in ('/', '/app.js', '/app.css'):
            code, data, headers = self.request('GET',path)
            self.assertEqual(code,200)
            self.assertNotIn(self.token.encode(),data)
            self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.request('GET','/../node.json')[0],404)
        self.assertNotIn('localStorage', WEB_JS)
        self.assertFalse(WEB_JS.endswith('loadProjects();\n'))
        self.assertIn('id="settings-users-tab"', WEB_HTML)
        self.assertIn('id="settings-cms-tab"', WEB_HTML)
        self.assertIn('id="administration" class="settings-card" hidden', WEB_HTML)
        self.assertNotIn('<dialog id="administration"', WEB_HTML)
        self.assertIn("querySelector('#settings-users-tab').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#settings-cms-tab').hidden=!admin", WEB_JS)
        self.assertIn("querySelector('#settings-federation-tab').hidden=session.node_role!=='federation-admin'", WEB_JS)
        self.assertIn("querySelector('#backend-metrics-indicator').hidden=!admin", WEB_JS)
        self.assertIn('id="workflow-tab"', WEB_HTML)
        self.assertIn('Projekt z archivu (NotebookLM notebook)', WEB_HTML)
        self.assertIn('id="notebooklm-selection"', WEB_HTML)
        self.assertIn("projectRequest('/v1/workflows/prepare'", WEB_JS)
        self.assertEqual(self.request(path='/v1/backend-metrics/status')[0], 200)

    def test_mobile_layout_has_accessible_drawer_and_bounded_priority_flows(self):
        self.assertIn('id="mobile-sidebar-toggle" type="button" aria-controls="workspace-sidebar"', WEB_HTML)
        self.assertIn('id="mobile-sidebar-backdrop" type="button" aria-label="Zavřít navigaci"', WEB_HTML)
        self.assertIn('id="workspace-sidebar" aria-label="Navigace pracovního prostoru"', WEB_HTML)
        self.assertIn("window.matchMedia('(max-width:640px)')", WEB_JS)
        self.assertIn("workspaceSidebar.inert=mobileViewport.matches&&!open", WEB_JS)
        self.assertIn("event.key==='Escape'", WEB_JS)
        self.assertIn("#sidebar-artifact-list button'))closeMobileSidebar()", WEB_JS)
        self.assertIn('@media(max-width:640px)', WEB_CSS)
        self.assertIn('max-width:calc(100vw - 48px)', WEB_CSS)
        self.assertIn('grid-template-columns:minmax(0,1fr)', WEB_CSS)
        self.assertIn('overflow-x:auto;overscroll-behavior-x:contain', WEB_CSS)
        self.assertIn('body:not(.authenticated)>#mobile-sidebar-toggle', WEB_CSS)
        self.assertIn('#notebooklm-preview{max-height:50vh;max-width:100%', WEB_CSS)

    def test_individual_keys_membership_rotation_and_revocation_over_https(self):
        from uuid import uuid4
        _, data, _ = self.request(path='/v1/projects/create', body='{"title":"Restricted"}')
        project = json.loads(data)['id']
        def admin(request):
            return self.request(path='/v1/administration', body=json.dumps(request))
        code, data, _ = admin({'action':'list'})
        self.assertEqual(code, 200)
        state = json.loads(data)
        code, data, _ = admin({'action':'create-user', 'expected_commit':state['commit_id'], 'name':'Reader', 'node_role':'member'})
        self.assertEqual(code, 200)
        state = json.loads(data); key = state['access_key']; user = state['users'][0]
        headers = {'Authorization':'Bearer '+key}
        self.assertEqual(json.loads(self.request(headers=headers)[1])['projects'], [])
        self.assertEqual(self.request(path='/v1/projects/open', body=json.dumps({'project_id':project}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/administration', body='{"action":"list"}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/backend-metrics/status', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/media/openai/configure', body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/publication-cms/status', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/external/request',
            body=json.dumps({'run_id':str(uuid4())}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/external/send-stream',
            body='{}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/projects/create', body='{"title":"Denied"}', headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/notebooklm/preview',
            body='{"archive_path":"/tmp/denied.tgz"}', headers=headers)[0], 403)
        code, data, _ = admin({'action':'update-user', 'expected_commit':state['commit_id'], 'user_id':user['id'],
                              'active':True, 'node_role':'member', 'memberships':{project:'reader'}})
        self.assertEqual(code, 200); state = json.loads(data)
        self.assertEqual(self.request(path='/v1/projects/open', body=json.dumps({'project_id':project}), headers=headers)[0], 200)
        self.assertEqual(self.request(path='/v1/media/preview', body=json.dumps({
            'project_id': project}), headers=headers)[0], 403)
        self.assertEqual(self.request(path='/v1/workflows/status', body=json.dumps({
            'project_id': project}), headers=headers)[0], 403)
        view = Projects(self.root/'node.json').open(project)
        source = request_from_bytes(project, view['commit_id'], 'reader.md', b'denied', 'Denied', '', [], 'project')
        self.assertEqual(self.request(path='/v1/sources/import', body=json.dumps({
            'operation_id': str(uuid4()), 'source': source}), headers=headers)[0], 403)
        code, data, _ = admin({'action':'rotate-key', 'expected_commit':state['commit_id'], 'user_id':user['id']})
        self.assertEqual(code, 200); state=json.loads(data)
        self.assertEqual(self.request(headers=headers)[0],401)
        headers={'Authorization':'Bearer '+state['access_key']}
        self.assertEqual(self.request(headers=headers)[0],200)
        code, _, _ = admin({'action':'update-user', 'expected_commit':state['commit_id'], 'user_id':user['id'],
                           'active':False, 'node_role':'member', 'memberships':{project:'reader'}})
        self.assertEqual(code,200)
        self.assertEqual(self.request(headers=headers)[0],401)

    def test_create_retries_have_one_receipt_and_project(self):
        from uuid import uuid4
        body=json.dumps({'title':'Retry', 'operation_id':str(uuid4())})
        first=self.request(path='/v1/projects/create',body=body)
        second=self.request(path='/v1/projects/create',body=body)
        self.assertEqual(first[0],200);self.assertEqual(second[0],200)
        self.assertEqual(json.loads(first[1]),json.loads(second[1]))
        self.assertEqual(len(json.loads(self.request()[1])['projects']),1)

    def test_admin_previews_plans_and_confirms_server_local_notebooklm_export(self):
        archive = self.notebook_archive()
        code, data, _ = self.request(path='/v1/notebooklm/preview',
                                     body=json.dumps({'archive_path': str(archive)}))
        self.assertEqual(200, code)
        preview = json.loads(data)
        operation = str(uuid4())
        request = {'archive_path': str(archive),
                   'selection_digest': preview['notebooks'][0]['selection_digest'],
                   'privacy': 'confidential', 'operation_id': operation}
        code, data, _ = self.request(path='/v1/notebooklm/plan', body=json.dumps(request))
        self.assertEqual(200, code)
        plan = json.loads(data)
        self.assertEqual('confidential', plan['privacy'])
        self.assertIn(str(self.root / 'projects'), plan['target_root'])
        body = json.dumps({'archive_path': str(archive), 'plan': plan})
        first = self.request(path='/v1/notebooklm/confirm', body=body)
        second = self.request(path='/v1/notebooklm/confirm', body=body)
        self.assertEqual(200, first[0]); self.assertEqual(first, second)
        receipt = json.loads(first[1])
        self.assertEqual(plan['project_id'], receipt['id'])
        self.assertEqual(6, len(Projects(self.root / 'node.json').open(receipt['id'])['artifacts']))

    def test_web_import_preserves_bytes_and_retries_one_operation(self):
        from uuid import uuid4
        _, data, _ = self.request(path='/v1/projects/create', body='{"title":"Web import"}')
        project = json.loads(data)
        raw = b'# Evidence\n' + b'x' * 70000
        source = request_from_bytes(project['id'], project['commit_id'], 'evidence.md', raw,
                                    'Evidence', '', ['web'], 'project')
        body = json.dumps({'operation_id': str(uuid4()), 'source': source})
        first = self.request(path='/v1/sources/import', body=body)
        second = self.request(path='/v1/sources/import', body=body)
        self.assertEqual(first[0], 200); self.assertEqual(second[0], 200)
        self.assertEqual(json.loads(first[1]), json.loads(second[1]))
        opened = Sources(self.root/'node.json').open(project['id'])
        self.assertEqual(len(opened['sources']), 1)
        project_root = Path(parse_node(read_config(self.root/'node.json'),
                                       location=self.root/'node.json')['projects'][0]['root'])
        imported = json.loads((project_root/'artifacts'/source['artifact_id']/'metadata.json').read_text())
        self.assertEqual(imported['import']['importer']['name'], 'workspace-web-import')
        self.assertEqual((project_root/'artifacts'/source['artifact_id']/'evidence.md').read_bytes(), raw)

    def test_web_import_rejects_local_only(self):
        from uuid import uuid4
        _, data, _ = self.request(path='/v1/projects/create', body='{"title":"Privacy"}')
        project = json.loads(data)
        source = request_from_bytes(project['id'], project['commit_id'], 'private.md', b'private',
                                    'Private', '', [], 'local-only')
        code, _, _ = self.request(path='/v1/sources/import', body=json.dumps({
            'operation_id': str(uuid4()), 'source': source}))
        self.assertEqual(code, 422)
        self.assertEqual(Sources(self.root/'node.json').open(project['id'])['sources'], [])

    def test_router_entry_redirects_to_live_https_and_rejects_bad_certificate(self):
        import ipaddress
        from http.server import HTTPServer
        from unittest.mock import patch, Mock
        from scripts.router_entry import EntryHandler
        entry = HTTPServer(('127.0.0.1', 0), EntryHandler)
        entry.target = ('workspace-m0', ipaddress.ip_network('127.0.0.0/8'),
                        self.server.server_port, str(self.cert))
        thread = threading.Thread(target=entry.serve_forever); thread.start()
        try:
            def info(args, **kwargs):
                return Mock(stdout='RUNNING' if args[-1]=='-sH' else '127.0.0.1')
            with patch('scripts.router_entry.subprocess.run', side_effect=info):
                for ca, expected in [(str(self.cert),302), (str(self.root/'missing-ca'),503)]:
                    entry.target = (*entry.target[:3], ca)
                    conn = http.client.HTTPConnection(*entry.server_address, timeout=10)
                    conn.request('GET','/federated-workspace/')
                    response = conn.getresponse()
                    self.assertEqual(response.status, expected)
                    self.assertEqual(response.getheader('Cache-Control'),'no-store')
                    if expected == 302:
                        self.assertEqual(response.getheader('Location'),'https://'+self.authority+'/')
                    else:
                        self.assertIsNone(response.getheader('Location'))
                    response.read(); conn.close()
        finally:
            entry.shutdown(); thread.join(); entry.server_close()

    def test_secret_permissions_symlink_and_invalid_keys(self):
        self.token_file.chmod(0o644)
        with self.assertRaises(ValueError): secret(self.token_file)
        self.token_file.chmod(0o600)
        link = self.root/'link'; link.symlink_to(self.token_file)
        with self.assertRaises(ValueError): secret(link)
        self.token_file.write_text('short')
        with self.assertRaises(ValueError): secret(self.token_file)

    def test_bad_tls_client_does_not_prevent_following_request(self):
        import socket
        with socket.create_connection(('127.0.0.1',self.server.server_port)) as sock:
            sock.sendall(b'GET / HTTP/1.0\r\n\r\n')
        self.assertEqual(self.request()[0],200)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_browser_login_catalog_and_logout(self):
        import sys
        # Accept only the ephemeral test certificate, never a production TLS policy.
        code = r"""
import json, os, sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
app=QApplication([]); view=QWebEngineView(); view.resize(1000,750)
view.page().certificateError.connect(lambda error:error.acceptCertificate())
phase=0; ticks=0
key=os.environ['WORKSPACE_SMOKE_KEY']
def result(value):
 global phase
 if phase==0 and value=='ready':
  phase=1
  view.page().runJavaScript("document.querySelector('#access-key').value="+json.dumps(key)+";document.querySelector('#login-form').requestSubmit();")
 elif phase==1 and value=='loaded':
  phase=2
  view.page().runJavaScript("document.querySelector('#logout').click();")
 elif phase==2 and value=='ready':
  print('web smoke: login, catalog and logout OK');app.exit(0)
def poll():
 global ticks
 ticks+=1
 if ticks>150: app.exit(1);return
 view.page().runJavaScript("document.querySelector('#login-form') ? (document.body.classList.contains('authenticated') ? (document.querySelector('#project-status').textContent==='Zatím nemáte žádný projekt.' && !document.querySelector('#backend-metrics-indicator').hidden?'loaded':'waiting') : 'ready') : 'waiting'",result)
timer=QTimer();timer.timeout.connect(poll);timer.start(100)
view.load(QUrl(os.environ['WORKSPACE_SMOKE_URL']));view.show()
sys.exit(app.exec())
"""
        result = subprocess.run([sys.executable, '-c', code], env=dict(os.environ,
            WORKSPACE_SMOKE_KEY=self.token, WORKSPACE_SMOKE_URL='https://'+self.authority+'/'),
            capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('web smoke: login, catalog and logout OK', result.stdout)

    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
    def test_real_mobile_browser_import_catalog_preview_and_keyboard_drawer(self):
        title = 'Český projekt s velmi dlouhým názvem ' + 'bez-mezer-' * 14
        _, data, _ = self.request(path='/v1/projects/create', body=json.dumps({'title': title}))
        project = json.loads(data)
        source = request_from_bytes(project['id'], project['commit_id'], 'mobile.md',
                                    b'# Mobilni nahled\nBezpecny text.', 'Mobilní podklad',
                                    'Dlouhý popis pro telefon', ['mobile'], 'project')
        code, _, _ = self.request(path='/v1/sources/import', body=json.dumps({
            'operation_id': str(uuid4()), 'source': source}))
        self.assertEqual(code, 200)
        archive = self.notebook_archive()
        import sys
        code = r"""
import json, os, sys
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
app=QApplication([]);view=QWebEngineView();view.resize(390,844)
view.page().certificateError.connect(lambda error:error.acceptCertificate())
phase=0;ticks=0;key=os.environ['WORKSPACE_SMOKE_KEY'];archive=os.environ['WORKSPACE_NOTEBOOK_ARCHIVE']
def run(script): view.page().runJavaScript(script)
def finish(message,code=1): print(message);app.exit(code)
def result(value):
 global phase
 if isinstance(value,str) and value.startswith('FAIL:'): finish(value);return
 if value!='ready': return
 if phase==0:
  phase=1;run("document.querySelector('#access-key').value="+json.dumps(key)+";document.querySelector('#login-form').requestSubmit();")
 elif phase==1:
  phase=2;run("document.querySelector('#notebooklm-import').open=true;document.querySelector('#notebooklm-archive').value="+json.dumps(archive)+";document.querySelector('#notebooklm-load').click();")
 elif phase==2:
  phase=3;run("document.querySelector('#notebooklm-plan').click();")
 elif phase==3:
  phase=4;run("const c=document.querySelector('#notebooklm-confirm');c.checked=true;c.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('.project-card').click();")
 elif phase==4:
  phase=5;run("document.querySelector('#mobile-sidebar-toggle').click();")
 elif phase==5:
  phase=6;run("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));")
 elif phase==6:
  phase=7;run("document.querySelector('#mobile-sidebar-toggle').click();")
 elif phase==7:
  phase=8;run("document.querySelector('#sidebar-artifact-list button').click();")
 elif phase==8:
  phase=9;run("document.querySelector('#mobile-sidebar-toggle').click();")
 elif phase==9:
  phase=10;run("document.querySelector('#logout').click();")
 elif phase==10: finish('mobile web smoke: import plan, catalog, keyboard drawer and preview OK',0)
def poll():
 global ticks
 ticks+=1
 if ticks>450: finish('mobile web smoke timeout at phase '+str(phase));return
 checks={
 0:"document.querySelector('#login-form')&&!document.body.classList.contains('authenticated')?'ready':'waiting'",
 1:"(()=>{if(!document.body.classList.contains('authenticated')||document.querySelectorAll('.project-card').length!==1)return'waiting';if(innerWidth!==390)return'FAIL: wrong viewport '+innerWidth;if(document.documentElement.scrollWidth>document.documentElement.clientWidth)return'FAIL: home overflow';const b=document.querySelector('#mobile-sidebar-toggle');if(getComputedStyle(b).display==='none'||parseFloat(getComputedStyle(b).minHeight)<44)return'FAIL: touch target';return'ready'})()",
 2:"document.querySelector('#notebooklm-selection')&&!document.querySelector('#notebooklm-selection').disabled?'ready':'waiting'",
 3:"(()=>{const row=document.querySelector('#notebooklm-confirm-row');if(row.hidden)return'waiting';if(document.documentElement.scrollWidth>document.documentElement.clientWidth)return'FAIL: import overflow';return'ready'})()",
 4:"!document.querySelector('#project-view').hidden&&document.querySelector('#sidebar-artifact-list button')?'ready':'waiting'",
 5:"(()=>{const b=document.querySelector('#mobile-sidebar-toggle'),s=document.querySelector('#workspace-sidebar');if(b.getAttribute('aria-expanded')!=='true')return'waiting';if(s.inert)return'FAIL: open drawer inert';return'ready'})()",
 6:"(()=>{const b=document.querySelector('#mobile-sidebar-toggle'),s=document.querySelector('#workspace-sidebar');if(b.getAttribute('aria-expanded')!=='false')return'waiting';if(!s.inert)return'FAIL: closed drawer focusable';if(document.activeElement!==b)return'FAIL: drawer focus not restored';return'ready'})()",
 7:"document.querySelector('#mobile-sidebar-toggle').getAttribute('aria-expanded')==='true'?'ready':'waiting'",
 8:"(()=>{if(document.querySelector('#preview-title').textContent!=='Mobilní podklad')return'waiting';if(document.documentElement.scrollWidth>document.documentElement.clientWidth)return'FAIL: preview overflow';const s=document.querySelector('#workspace-sidebar');if(!s.inert)return'FAIL: selected drawer focusable';return'ready'})()",
 9:"document.querySelector('#mobile-sidebar-toggle').getAttribute('aria-expanded')==='true'?'ready':'waiting'",
 10:"document.querySelector('#login-form')&&!document.body.classList.contains('authenticated')?'ready':'waiting'"}
 view.page().runJavaScript(checks[phase],result)
timer=QTimer();timer.timeout.connect(poll);timer.start(100)
view.load(QUrl(os.environ['WORKSPACE_SMOKE_URL']));view.show();sys.exit(app.exec())
"""
        result = subprocess.run([sys.executable, '-c', code], env=dict(
            os.environ, WORKSPACE_SMOKE_KEY=self.token,
            WORKSPACE_SMOKE_URL='https://'+self.authority+'/',
            WORKSPACE_NOTEBOOK_ARCHIVE=str(archive)), capture_output=True, text=True,
            timeout=55)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('mobile web smoke: import plan, catalog, keyboard drawer and preview OK', result.stdout)


class NetworkPrivacyTests(unittest.TestCase):
    def test_local_only_catalog_open_and_preview_with_real_git(self):
        fixture = test_projects.ProjectTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        projects = Projects(fixture.node_path, network=True)
        self.assertTrue(projects.catalog()[0]['available'])
        self.assertEqual(projects.open(ENTITY)['id'],ENTITY)
        meta = metadata(); meta['privacy']='local-only'
        (fixture.gits[0].root/'artifacts'/ENTITY/'note.md').write_bytes(markdown(meta))
        head = fixture.gits[0].commit('Local only')
        self.assertNotIn(ENTITY, str(projects.catalog()))
        self.assertNotIn(ENTITY, str(projects.list()))
        with self.assertRaises(ValueError): projects.open(ENTITY)
        with self.assertRaises(ValueError): projects.preview(ENTITY,ENTITY,head)
        # The native/local boundary retains access.
        self.assertEqual(fixture.projects.open(ENTITY)['id'],ENTITY)

class BootstrapTests(unittest.TestCase):
    def test_repeated_initialization_preserves_identity_key_and_registration(self):
        from spikes.web_bootstrap import initialize
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            initialize(root)
            before={p.name:p.read_bytes() for p in root.iterdir()}
            initialize(root)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir()})
            for p in root.iterdir(): self.assertEqual(p.stat().st_mode & 0o777,0o600)
            (root/'access-key').write_text('corrupt')
            with self.assertRaises(ValueError): initialize(root)
            self.assertEqual((root/'access-key').read_text(),'corrupt')
