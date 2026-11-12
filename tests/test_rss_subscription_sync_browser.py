# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class ReaderSyncBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_opt_in_signed_sync_conflict_review_and_no_article_fetch(self):
        script=r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from tests import test_federation_catalog as fixtures
from tests.test_rss_subscription_sync import channel
from spikes import rss_subscription_state as state,rss_subscription_sync as sync
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.rss_sources import RSSSources
app=QApplication([])
f=fixtures.FederationCatalogTests('test_signed_exchange_stores_only_remote_project_identity_and_title');f.setUp()
try:
 a,b=f.nodes
 for node,c in ((a,channel()),(b,channel('Remote','https://example.org/remote','remote'))):
  s=state.store(node);rev,_=s.load();s.save(rev,[c])
 state.configure(b,f.node_ids[0],True)
 sync.exchange=lambda node,peer,envelope,ca=None:sync.receive(f.services[1],envelope)
 with running_api('http',handler=DesktopHandler,projects=Projects(a)) as server:
  server.administration=f.services[0]
  server.rss_sources=RSSSources(node=a,fetcher=lambda u:(_ for _ in ()).throw(AssertionError('No article fetch during sync')))
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConfirm(self,url,text):return True
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print(message,line,flush=True)
  page=Page(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1200,850);view.show()
  phase=0;busy=False
  commands={
   1:'window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};navigateSidebarTab(document.querySelector("#sources-sidebar-tab"))',
   2:"document.querySelector('#sources-reader-sync').open=true;document.querySelector('#sources-reader-sync-peers input').click()",
   3:"document.querySelector('#sources-reader-sync-peers button').click()",
   4:"loadSources()",
   5:"[...document.querySelectorAll('#sources-reader-sync-conflicts button')].find(b=>b.textContent.includes('Desktop choice')).click()",
   6:"document.querySelector('#sources-reader-sync-peers button').click()",
  }
  checks={
   0:"typeof loadSources==='function'",
   1:"sourcesView?.channels.length===1&&!!sourcesView.reader_sync&&!document.querySelector('#sources-reader-sync').hidden",
   2:"!sourcesSaving&&sourcesView.reader_sync.peers.some(p=>p.enabled)",
   3:"!sourcesSaving&&sourcesView.channels.length===2&&sourcesView.channels.some(c=>c.name==='Remote')",
   4:"!sourcesSaving&&sourcesView.reader_sync.conflicts.length===1&&document.querySelectorAll('#sources-reader-sync-conflicts button').length===2",
   5:"!sourcesSaving&&sourcesView.reader_sync.conflicts.length===0&&sourcesView.channels.some(c=>c.name==='Desktop choice')",
   6:"!sourcesSaving&&sourcesView.reader_sync.conflicts.length===0&&window.innerWidth<500&&document.documentElement.scrollWidth<=window.innerWidth+1",
  }
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==4:
    for node,name in ((a,'Desktop choice'),(b,'Remote choice')):
     s=state.store(node);rev,channels=s.load()
     for c in channels:
      if c['url']=='https://example.org/rss':c['name']=name
     s.save(rev,channels)
    sync.synchronize(a,f.node_ids[1],deployment='web')
   if phase==5:view.grab().save('/tmp/fpw-rss-reader-conflict.png');view.resize(390,850)
   if phase==7:
    assert not state.view(b)['conflicts']
    assert any(c['name']=='Desktop choice' for c in state.store(b).load()[1])
    assert not server.rss_sources.view()['entries']
    print('reader sync browser OK',flush=True);app.exit(0);return
   page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(200)
  page.setUrl(QUrl(server.origin+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript("document.querySelector('#sources-status')?.textContent",lambda value:(print(value,flush=True),app.exit(2)))
  QTimer.singleShot(30000,timeout);code=app.exec()
  from shiboken6 import delete
  view.close();delete(view);delete(page);delete(profile);raise SystemExit(code)
finally:f.doCleanups()
'''
        r=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=45)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('reader sync browser OK',r.stdout)
