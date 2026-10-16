# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Opt-in real audience layout, authenticated projection and QR rendering."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires real Qt/WebEngine')
class ClosingWebEngineTests(unittest.TestCase):
    def test_closing_center_contacts_and_qr_at_both_display_ratios(self):
        script = r'''
import json, os
from types import SimpleNamespace
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInterceptor
from spikes.desktop import request_policy
from spikes.desktop_management import DesktopManagementHandler
from spikes.local_api import running_api
from tests.test_local_api import LocalAPITests
from tests.test_user_profile import PROFILE
app=QApplication([])
with running_api('http', handler=DesktopManagementHandler) as server:
    server.user_profile=SimpleNamespace(load=lambda: dict(PROFILE))
    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            policy=request_policy(info.requestUrl().toString(), info.initiator().toString(), bytes(info.requestMethod()).decode(), server.origin)
            if policy=='block': info.block(True)
            elif policy=='authenticate': info.setHttpHeader(b'Authorization', ('Bearer '+server.token).encode())
    profile=QWebEngineProfile(app); interceptor=Interceptor(profile); profile.setUrlRequestInterceptor(interceptor)
    view=QWebEngineView(); page=QWebEnginePage(profile,view);view.setPage(page)
    view.resize(1280,720);view.show()
    driver=LocalAPITests()
    def request(path, body):
        response=driver.request(server,path=path,body=json.dumps(body).encode())
        assert response.startswith(b'HTTP/1.0 200'), response[:200]
        return json.loads(response.split(b'\r\n\r\n',1)[1])
    session=request('/v1/presentation/status',{'action':'start'})
    final=session['slides'][-1]
    assert final['closing']
    request('/v1/presentation/control',dict(action='show',slide=len(session['slides'])-1,slide_id=final['id'],deck_revision=final['deck_revision']))
    state={'ratio':0}
    def received(raw):
        if not raw:return
        data=json.loads(raw)
        if not data or not data['ready'] or state['ratio']==-1:return
        try:
            box,title,qr=data['box'],data['titleBox'],data['qrBox']
            assert data['title']=='Prostor pro Vaše dotazy'
            assert data['contacts']=='\n'.join(PROFILE.values())
            assert abs(title['x']+title['w']/2-(box['x']+box['w']/2))<2
            assert abs(title['y']+title['h']/2-(box['y']+box['h']/2))<2
            assert qr['x']>box['x']+box['w']/2
            assert qr['y']>title['y']+title['h']
            assert qr['x']+qr['w']<=box['x']+box['w']
            assert qr['y']+qr['h']<=box['y']+box['h']
            if state['ratio']==0:
                if abs(box['w']/box['h']-16/9)>.02:return
                state['ratio']=-1
                def capture_and_resize():
                    shot=os.environ.get('FPW_CLOSING_SCREENSHOT')
                    if shot:view.grab().save(shot)
                    state['ratio']=1;view.resize(960,720)
                    request('/v1/presentation/control',dict(action='display-ratio',ratio='4:3'))
                QTimer.singleShot(350,capture_and_resize)
            elif abs(box['w']/box['h']-4/3)<.02:
                print('closing: center, contacts and decoded image verified at 16:9 and 4:3',flush=True)
                app.exit(0)
        except Exception:
            import traceback;traceback.print_exc();app.exit(4)
    poll=QTimer()
    poll.timeout.connect(lambda:page.runJavaScript(r"""(()=>{
const box=document.querySelector('#screen'),title=box?.querySelector('h1'),qr=box?.querySelector('img');
if(!qr || !title)return '';
const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};};
return JSON.stringify({ready:qr.complete&&qr.naturalWidth>0,title:title.textContent,
contacts:qr.previousElementSibling.textContent,box:rect(box),titleBox:rect(title),qrBox:rect(qr)});
})()""",0,received))
    page.loadFinished.connect(lambda ok: None if ok else app.exit(3))
    page.setUrl(QUrl(server.origin+'/presentation-screen'));poll.start(100)
    QTimer.singleShot(15000,lambda:app.exit(2))
    code=app.exec();poll.stop();raise SystemExit(code)
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('verified at 16:9 and 4:3', result.stdout)
