# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os,sys,json
os.environ['QT_QPA_PLATFORM']='offscreen'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS']='--no-sandbox --disable-gpu'
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QTimer
from spikes.desktop_ui import HTML,CSS
app=QApplication([]);view=QWebEngineView();view.resize(1545,863);reports=[]
setup="""(()=>{
document.querySelector('#login').hidden=true;
document.querySelector('aside').hidden=false;
for(const el of document.querySelectorAll('main>section,main>div'))el.hidden=true;
document.querySelector('#project-view').hidden=false;
for(const el of document.querySelectorAll('#main-panel-content>[role=tabpanel]'))el.hidden=el.id!=='project-overview-panel';
document.querySelector('#main-panel-content').classList.add('project-overview-active');
document.querySelector('.project-overview-heading').hidden=true;
document.querySelector('.project-overview-grid').hidden=true;
document.querySelector('#project-conflicts').hidden=false;
document.querySelector('#project-conflicts-workspace').hidden=false;
document.querySelector('#prompt-widget').hidden=false;
document.querySelector('#project-conflicts-unresolved').textContent='Zbývá vyřešit 1 konfliktních souborů.';document.querySelector('#project-conflicts-status').textContent='Vyberte soubor ze seznamu. Návrh je pouze v prohlížeči; Git ani projekt nebyly změněny.';
document.querySelector('#project-conflicts-files-summary').textContent='1 konfliktních · 701 automaticky sloučených souborů. Kliknutím otevřete porovnání.';
const list=document.querySelector('#project-conflicts-files');
for(let i=0;i<702;i++){const li=document.createElement('li'),b=document.createElement('button');b.textContent='artifacts/12345678-1234-1234-1234-123456789abc/content.md';li.append(b);list.append(li);}
return true;})()"""
check="""(()=>{const list=document.querySelector('#project-conflicts-files'),publish=document.querySelector('#project-conflicts-publish'),prompt=document.querySelector('#prompt-widget');let before=publish.getBoundingClientRect().top;list.scrollTop=900;return JSON.stringify({width:innerWidth,height:innerHeight,listHeight:list.clientHeight,scrollHeight:list.scrollHeight,scroll:list.scrollTop,publishBottom:publish.getBoundingClientRect().bottom,promptTop:prompt.getBoundingClientRect().top,footerStayed:publish.getBoundingClientRect().top===before,rows:[...document.querySelector('#project-conflicts').children].map(e=>[e.tagName,e.id,e.getBoundingClientRect().height]),workspaceRows:[...document.querySelector('#project-conflicts-workspace').children].map(e=>[e.tagName,e.id,e.getBoundingClientRect().height]),panel:document.querySelector('#main-panel-content').clientHeight});})()"""
def sample():view.page().runJavaScript(check,done)
def done(raw):
    d=json.loads(raw);reports.append(d);print(json.dumps(d),flush=True)
    if len(reports)==1:
        view.resize(1326,678);QTimer.singleShot(300,sample)
    else:
        app.quit()
def loaded(ok):
    assert ok
    view.page().runJavaScript(setup,lambda _:QTimer.singleShot(300,sample))
view.loadFinished.connect(loaded)
view.setHtml(HTML.replace('<script src="/app.js"></script>','').replace('<body ', '<style>'+CSS+'</style><body ',1));view.show()
QTimer.singleShot(20000,app.quit);app.exec()
assert len(reports)==2
for d in reports:
    assert d['listHeight']>=32 and d['scrollHeight']>d['listHeight'] and d['scroll']==900 and d['footerStayed'] and d['publishBottom']<=d['promptTop'],d
