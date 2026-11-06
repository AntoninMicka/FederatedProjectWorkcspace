# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import os
from pathlib import Path
import subprocess
import sys
import unittest


class RSSSourcesBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST') == '1', 'Requires Qt/WebEngine')
    def test_main_navigation_channel_tabs_aggregation_keyboard_and_inert_titles(self):
        script = r'''
import json
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from tests import test_reporting
from tests.test_rss_sources import CHANNELS
from tests.test_rss_pilot import rss
from spikes.local_api import running_api
from spikes.desktop_ui import DesktopHandler
from spikes.projects import Projects
from spikes.rss_sources import RSSSources
app=QApplication([])
f=test_reporting.ReportingTests('test_manual_event_multiple_sources_and_read_projection');f.setUp()
try:
 with running_api('http',handler=DesktopHandler,projects=Projects(f.node)) as server:
  server.rss_sources=RSSSources(channels=CHANNELS,fetcher=lambda url:rss('&lt;img src=x onerror=alert(1)&gt;'))
  profile=QWebEngineProfile(app)
  class Page(QWebEnginePage):
   def javaScriptConsoleMessage(self,level,message,line,source):
    if 'Error' in message:print('JS:',message,line,flush=True)
  page=Page(profile,app);view=QWebEngineView();view.setPage(page);view.resize(1200,800);view.show()
  phase=0;busy=False
  commands={
   1:'window.nativeFetch=fetch;window.fetch=(url,opts={})=>{opts.headers={...opts.headers,Authorization:'+json.dumps('Bearer '+server.token)+'};return nativeFetch(url,opts)};navigateSidebarTab(document.querySelector("#sources-sidebar-tab"))',
   2:'sourcesRefresh.click()',
   3:'document.querySelector("#source-channel-one").click()',
   4:'document.activeElement.dispatchEvent(new KeyboardEvent("keydown",{key:"ArrowRight",bubbles:true}))',
   5:'document.querySelector("#source-channel-all").click()',
   6:'window.dispatchEvent(new Event("resize"))',
   7:'navigateSidebarTab(document.querySelector("#projects-tab"))'}
  checks={
   0:'typeof loadSources==="function"&&typeof navigateSidebarTab==="function"',
   1:'!document.querySelector("#sources-view").hidden&&sourcesView?.channels.length===2&&!activeProject&&document.querySelector("#sources-connector-list").textContent.includes("Nedostupné")&&document.querySelector("#sources-connector-list").textContent.includes("Nepřipojeno")',
   2:'!sourcesBusy&&sourcesFeed.querySelectorAll("article").length===2',
   3:'sourcesChannel==="one"&&sourcesFeed.querySelectorAll("article").length===1&&sourcesFeed.textContent.includes("<img src=x")&&!sourcesFeed.querySelector("img")',
   4:'sourcesChannel==="two"&&document.activeElement.id==="source-channel-two"&&sourcesFeed.querySelectorAll("article").length===1',
   5:'sourcesChannel==="all"&&sourcesFeed.querySelectorAll("article").length===2',
   6:'window.innerWidth<500&&!document.querySelector("#sources-view").hidden&&document.documentElement.scrollWidth<=window.innerWidth+1',
   7:'document.querySelector("#sources-view").hidden&&!document.querySelector("#project-home").hidden'}
  def received(value):
   global phase,busy
   busy=False
   if value!='ready':return
   phase+=1
   if phase==6:
    view.grab().save('/tmp/rss-sources-desktop.png');view.resize(390,844)
   if phase==7:view.grab().save('/tmp/rss-sources-mobile.png')
   if phase==8:print('sources browser OK',flush=True);app.exit(0);return
   print('phase',phase,flush=True);page.runJavaScript(commands[phase])
  def poll():
   global busy
   if busy:return
   busy=True;page.runJavaScript('('+checks[phase]+')?"ready":"waiting"',received)
  timer=QTimer();timer.timeout.connect(poll);timer.start(200)
  page.setUrl(QUrl('http://127.0.0.1:'+str(server.server_port)+'/'))
  def timeout():
   print('timeout phase',phase,flush=True)
   page.runJavaScript('document.querySelector("#sources-status")?.textContent',lambda x:(print(x,flush=True),app.exit(2)))
  QTimer.singleShot(30000,timeout)
  result=app.exec();view.close();page.deleteLater();profile.deleteLater();raise SystemExit(result)
finally:f.doCleanups()
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                                text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('sources browser OK', result.stdout)
