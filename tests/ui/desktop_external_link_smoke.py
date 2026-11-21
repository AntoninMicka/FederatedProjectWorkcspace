# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Click an HTTP link in the actual desktop Page; replace the OS browser with a spy."""
import ast
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QTimer,QUrl,Qt,QPointF,QEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QMouseEvent
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from spikes.desktop import external_link_url,provider_key_url,google_authorization_url,native_action_name
from http.server import HTTPServer,BaseHTTPRequestHandler
from threading import Thread
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  raw=b'<a style="display:block;width:200px;height:60px" href="https://example.com/" target="_blank" rel="noopener noreferrer">External</a>'
  self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
http=HTTPServer(('127.0.0.1',0),Handler);Thread(target=http.serve_forever,daemon=True).start()
origin='http://127.0.0.1:'+str(http.server_port)
app=QApplication([]);opened=[]
module=ast.parse(Path('spikes/desktop.py').read_text());node=next(n for n in ast.walk(module) if isinstance(n,ast.ClassDef) and n.name=='Page')
ns=dict(QWebEnginePage=QWebEnginePage,QDesktopServices=SimpleNamespace(openUrl=lambda url:opened.append(url.toString())),QUrl=QUrl,external_link_url=external_link_url,provider_key_url=provider_key_url,google_authorization_url=google_authorization_url,native_action_name=native_action_name,server=SimpleNamespace(origin=origin))
exec(compile(ast.Module(body=[node],type_ignores=[]),'production Page','exec'),ns)
profile=QWebEngineProfile(app);page=ns['Page'](profile,app);view=QWebEngineView();view.setPage(page);view.resize(600,400);view.show()
def click():
 widget=view.focusProxy()
 for kind,buttons in [(QEvent.Type.MouseButtonPress,Qt.MouseButton.LeftButton),(QEvent.Type.MouseButtonRelease,Qt.MouseButton.NoButton)]:
  app.sendEvent(widget,QMouseEvent(kind,QPointF(55,30),QPointF(55,30),Qt.MouseButton.LeftButton,buttons,Qt.KeyboardModifier.NoModifier))
 QTimer.singleShot(500,done)
def done():
 print('desktop external link browser OK' if opened==['https://example.com/'] else repr(opened),flush=True);app.exit(0 if opened==['https://example.com/'] else 2)
page.loadFinished.connect(lambda ok:QTimer.singleShot(300,click))
page.setUrl(QUrl(origin+'/'))
QTimer.singleShot(5000,lambda:app.exit(3));result=app.exec();view.close();http.shutdown();http.server_close();raise SystemExit(result)
