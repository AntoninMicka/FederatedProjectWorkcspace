"""Linux Qt/WebEngine shell around the existing local API; no persistent state."""
import argparse
import os
import signal
import sys
from urllib.parse import urlsplit

from spikes.desktop_ui import ASSETS, DesktopHandler
from spikes.local_api import running_api


def request_policy(url, initiator, method, origin):
    """Fail closed before Qt can attach credentials or contact another origin."""
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        return 'block'
    if f'{parsed.scheme}://{parsed.netloc}' != origin:
        return 'block'
    if parsed.path in ASSETS and method == 'GET':
        return 'allow'
    if parsed.path == '/v1/counter' and method == 'POST' and initiator.rstrip('/') == origin:
        return 'authenticate'
    return 'block'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true', help='Run real WebEngine click test and exit.')
    parser.add_argument('--screenshot', help='Save the rendered window during --smoke.')
    parser.add_argument('--smoke-crash', action='store_true', help='Kill renderer during --smoke; expect exit 1.')
    args = parser.parse_args()
    if args.smoke_crash and not args.smoke:
        parser.error('--smoke-crash requires --smoke')
    if args.screenshot and not args.smoke:
        parser.error('--screenshot requires --smoke')
    try:
        from PySide6.QtCore import QTimer, QUrl
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                          QWebEngineSettings, QWebEngineUrlRequestInterceptor)
    except ImportError:
        print('Chybí PySide6 WebEngine. Instalace viz README, sekce Desktop.', file=sys.stderr)
        return 1
    if os.geteuid() == 0:
        print('Desktop spouštějte jako běžný uživatel.', file=sys.stderr)
        return 1

    class Interceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info):
            policy = request_policy(info.requestUrl().toString(), info.initiator().toString(),
                                    bytes(info.requestMethod()).decode(), server.origin)
            if policy == 'block':
                info.block(True)
            elif policy == 'authenticate':
                info.setHttpHeader(b'Authorization', ('Bearer ' + server.token).encode())

    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, main_frame):
            return main_frame and url.toString() == server.origin + '/'

        def createWindow(self, kind):
            return None

    class View(QWebEngineView):
        closing = False

        def closeEvent(self, event):
            self.closing = True
            super().closeEvent(event)

    app = QApplication([sys.argv[0]])
    app.setApplicationName('Projektový workspace')
    with running_api('http', handler=DesktopHandler) as server:
        profile = QWebEngineProfile(app)  # unnamed => off the record
        interceptor = Interceptor(profile)
        profile.setUrlRequestInterceptor(interceptor)
        profile.downloadRequested.connect(lambda download: download.cancel())
        view = View()
        page = Page(profile, view)
        view.setPage(page)
        settings = page.settings()
        for setting in ('LocalContentCanAccessFileUrls', 'LocalContentCanAccessRemoteUrls',
                        'JavascriptCanOpenWindows', 'FullScreenSupportEnabled'):
            settings.setAttribute(getattr(QWebEngineSettings.WebAttribute, setting), False)
        view.setWindowTitle('Projektový workspace · Desktop PoC')
        view.resize(1100, 760)
        page.renderProcessTerminated.connect(lambda *_: None if view.closing else app.exit(1))
        timer = QTimer()
        timer.timeout.connect(lambda: None)
        timer.start(200)  # Let Python handle SIGINT while Qt's loop is running.
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, lambda *_: app.quit())
        if args.smoke:
            deadline = QTimer()
            deadline.setSingleShot(True)
            deadline.timeout.connect(lambda: app.exit(2))
            deadline.start(15000)
            poll = QTimer()
            def checked(value):
                if value == '1' and server.counter == 1:
                    poll.stop()
                    if args.smoke_crash:
                        os.kill(page.renderProcessPid(), signal.SIGKILL)
                        return
                    print('desktop smoke: rendered UI, authenticated fetch, value=1', flush=True)
                    def finish():
                        print('desktop measure: idle', flush=True)
                        if args.screenshot and not view.grab().save(args.screenshot):
                            app.exit(4)
                            return
                        view.close()
                    QTimer.singleShot(800, finish)  # Allow Chromium to present its frame.
            poll.timeout.connect(lambda: page.runJavaScript("document.querySelector('#count')?.textContent", 0, checked))
            poll.start(100)
            def loaded(ok):
                if not ok:
                    app.exit(3)
                else:
                    print("desktop measure: ui ready", flush=True)
                    page.runJavaScript("document.querySelector('#increment').click()")
            view.loadFinished.connect(loaded)
        else:
            view.loadFinished.connect(lambda ok: None if ok else QMessageBox.warning(
                view, 'Nelze načíst rozhraní', 'Zavřete aplikaci a spusťte ji znovu.'))
        view.load(QUrl(server.origin + '/'))
        view.show()
        result = app.exec()
        view.close()
        # Destroy pages before their off-the-record profile.
        from shiboken6 import delete
        delete(view)
        delete(profile)
    if args.smoke and result == 0:
        print('desktop smoke: backend stopped', flush=True)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
