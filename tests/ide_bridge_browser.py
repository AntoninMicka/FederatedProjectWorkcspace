# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Real browser fixture for the IDE installation form and generated VSIX."""
import base64
import hashlib
import json
import os
import subprocess
import sys
from uuid import uuid4
from spikes.artifacts import Artifacts, main_todo_id


def run(fixture):
    code,data,_=fixture.create_project('Browser bridge smoke'); assert code==200,data
    project=json.loads(data)['id']; view=fixture.server.projects.open(project)
    head=Artifacts(fixture.root/'node.json').save(dict(project_id=project,
        artifact_id=main_todo_id(project),base_head=view['commit_id'],title='Tasks',
        body='- [ ] [TASK-01] Browser smoke\n',new=True),str(uuid4()))['commit_id']
    script=r'''
import json, os, sys
from pathlib import Path
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile,QWebEnginePage
from PySide6.QtNetwork import QSslCertificate
app=QApplication([])
try:
 from PySide6.QtWebEngineCore import QWebEngineProfileBuilder
 builder=QWebEngineProfileBuilder();builder.setAdditionalTrustedCertificates(QSslCertificate.fromPath(os.environ['BRIDGE_CA']));profile=builder.createOffTheRecordProfile(app)
except ImportError:profile=QWebEngineProfile(app)
view=QWebEngineView();page=QWebEnginePage(profile,view);view.setPage(page)
page.certificateError.connect(lambda error:error.acceptCertificate())
phase=0;ticks=0;downloaded=False
profile.downloadRequested.connect(lambda download:(download.setDownloadDirectory(os.environ['BRIDGE_DOWNLOAD']),download.setDownloadFileName('bridge.vsix'),download.accept()))
def finished(value):
 global phase
 if value!='ready':return
 phase+=1
 if phase==1:page.runJavaScript("document.querySelector('#access-key').value="+json.dumps(os.environ['BRIDGE_KEY'])+";document.querySelector('#login-form').requestSubmit();")
 elif phase==2:page.runJavaScript("document.querySelector('.project-card').click()")
 elif phase==3:page.runJavaScript("window.__bridgeNetwork=[];const originalBridgeFetch=window.fetch;window.fetch=async(...args)=>{try{const response=await originalBridgeFetch(...args);if(String(args[0]).includes('ide-bridge'))window.__bridgeNetwork.push([args[0],response.status]);return response;}catch(error){if(String(args[0]).includes('ide-bridge'))window.__bridgeNetwork.push([args[0],error.message,location.href]);throw error;}};document.querySelector('#todo-tab').click();document.querySelector('#ide-bridge-panel').open=true;document.querySelector('#ide-bridge-repository').value='https://example.invalid/source.git';document.querySelector('#ide-bridge-instructions').value='Browser smoke';document.querySelector('#ide-bridge-form').requestSubmit();")
 elif phase==4:page.runJavaScript("document.querySelector('#ide-bridge-refresh').click()")
 elif phase==5:page.runJavaScript("document.querySelector('#ide-bridge-sessions button').click()")
 elif phase==6:print('Browser bridge form, VSIX download, session list and revocation OK',flush=True);app.exit(0)
def poll():
 global ticks
 ticks+=1
 if ticks>300:
  page.runJavaScript("JSON.stringify({status:document.querySelector('#ide-bridge-status')?.textContent,sessions:document.querySelector('#ide-bridge-sessions')?.textContent,network:window.__bridgeNetwork,url:location.href})",lambda value:(print('timeout phase',phase,value,flush=True),app.exit(1)));return
 checks={0:"document.querySelector('#login-form')?'ready':'waiting'",1:"document.body.classList.contains('authenticated')&&document.querySelector('.project-card')?'ready':'waiting'",2:"!document.querySelector('#project-view').hidden?'ready':'waiting'",3:"document.querySelector('#ide-bridge-status').textContent.startsWith('Instalační balíček připraven')?'ready':'waiting'",4:"document.querySelector('#ide-bridge-sessions button')?'ready':'waiting'",5:"document.querySelector('#ide-bridge-sessions').textContent.includes('odvoláno')?'ready':'waiting'"}
 page.runJavaScript(checks[phase],finished)
timer=QTimer();timer.timeout.connect(poll);timer.start(100);view.load(QUrl(os.environ['BRIDGE_URL']));view.show();sys.exit(app.exec())
'''
    public_key = subprocess.run(['openssl', 'x509', '-in', str(fixture.cert), '-pubkey', '-noout'], check=True, capture_output=True).stdout
    der = subprocess.run(['openssl', 'pkey', '-pubin', '-outform', 'DER'], input=public_key, check=True, capture_output=True).stdout
    pin = base64.b64encode(hashlib.sha256(der).digest()).decode()
    chromium_flags = os.environ.get('QTWEBENGINE_CHROMIUM_FLAGS', '') + ' --ignore-certificate-errors-spki-list=' + pin
    result=subprocess.run([sys.executable,'-c',script],env=dict(os.environ,BRIDGE_KEY=fixture.token,BRIDGE_URL='https://'+fixture.authority+'/',BRIDGE_DOWNLOAD=str(fixture.root),BRIDGE_CA=str(fixture.cert),QTWEBENGINE_CHROMIUM_FLAGS=chromium_flags),capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
    package=fixture.root/'bridge.vsix';assert package.exists(),'download missing'
    import zipfile
    with zipfile.ZipFile(package) as archive:assert 'extension/pairing.json' in archive.namelist()
    assert fixture.server.projects.open(project)['commit_id']==head
    print(result.stdout.strip())
