# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Headless Chromium harness for behavioural UI tests (AUDIT-B7-T1).

Standard library only: Chromium is driven over the DevTools protocol on
``--remote-debugging-pipe``. The page and its assets come from a real desktop
``running_api`` server, so headers and the Content Security Policy are the
real ones. Every ``/v1/*`` request is paused and judged by the real desktop
``request_policy``, which decides whether the native token is attached, just
as the Qt interceptor does. A request then either goes to the real desktop
backend (``node=``: services wired by ``attach_desktop_services``) or gets a
scripted reply from ``FakeApi`` for states that are hard to reach, such as
errors. Tests assert on the requests the UI actually sends and on the DOM it
renders, instead of on the source text of the UI.

Browser discovery: ``FPW_BROWSER`` or the first of google-chrome, chromium,
chromium-browser on PATH. Without a browser the tests are skipped, unless
``FPW_REQUIRE_BROWSER=1`` (set in CI), which turns a missing browser into a
failure instead of a silent skip.
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from contextlib import ExitStack
from urllib.parse import urlsplit

BROWSERS = ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser')


def find_browser():
    explicit = os.environ.get('FPW_BROWSER')
    if explicit:
        return explicit
    for name in BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def require_browser(test_case):
    """Class decorator: skip without a browser, fail if CI requires one."""
    browser = find_browser()
    if browser or os.environ.get('FPW_REQUIRE_BROWSER') == '1':
        return test_case
    return unittest.skip('Headless Chromium is unavailable (set FPW_BROWSER)')(test_case)


class BrowserError(AssertionError):
    pass


class FakeApi:
    """Scripted /v1/* responses and a record of every request the page sent."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []

    def route(self, path, response):
        """``response``: a JSON value, a Reply, or a callable(body) returning one;
        a callable that returns None passes the request to the real backend."""
        self.routes[path] = response

    def answer(self, path, body):
        handler = self.routes.get(path)
        if handler is None:
            return None
        value = handler(body) if callable(handler) else handler
        if value is None and callable(handler):
            return None  # a callable may pass this request on to the real backend
        return value if isinstance(value, Reply) else Reply(value)

    def sent(self, path):
        return [item for item in self.requests if item['path'] == path]


class Reply:
    def __init__(self, payload, *, status=200, content_type='application/json', raw=None):
        self.status, self.content_type = status, content_type
        self.raw = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode()


def ndjson(*events):
    """Streaming endpoint reply: newline-delimited JSON events."""
    raw = b''.join(json.dumps(event, ensure_ascii=False).encode() + b'\n' for event in events)
    return Reply(None, content_type='application/x-ndjson', raw=raw)


class _Pipe:
    def __init__(self, browser, profile, extra_flags=()):
        commands_read, self._commands = os.pipe()
        self._events, events_write = os.pipe()

        def child():
            os.dup2(commands_read, 3)
            os.dup2(events_write, 4)
        flags = ['--headless=new', '--remote-debugging-pipe', '--no-first-run',
                 '--no-default-browser-check', '--disable-extensions', '--disable-gpu',
                 '--disable-background-networking', '--window-size=1280,900',
                 '--user-data-dir=' + profile]
        flags.extend(extra_flags)
        if os.environ.get('CI') == 'true':
            # Ubuntu 24.04 runners restrict the user namespaces Chrome's sandbox
            # needs. The pages are local test fixtures, not untrusted content.
            flags.append('--no-sandbox')
        self.process = subprocess.Popen(
            [browser, *flags, 'about:blank'],
            pass_fds=(3, 4), preexec_fn=child,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(commands_read)
        os.close(events_write)
        self._buffer = b''
        self._next_id = 0

    def send(self, method, params=None, session=None):
        self._next_id += 1
        message = {'id': self._next_id, 'method': method, 'params': params or {}}
        if session:
            message['sessionId'] = session
        os.write(self._commands, json.dumps(message).encode() + b'\0')
        return self._next_id

    def read(self):
        while b'\0' not in self._buffer:
            chunk = os.read(self._events, 1 << 16)
            if not chunk:
                raise BrowserError('Chromium closed the DevTools pipe')
            self._buffer += chunk
        raw, self._buffer = self._buffer.split(b'\0', 1)
        return json.loads(raw)

    def close(self):
        try:
            self.send('Browser.close')
        except OSError:
            pass
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for fd in (self._commands, self._events):
            try:
                os.close(fd)
            except OSError:
                pass


class BrowserPage:
    """One headless page on the desktop UI; use as a context manager."""

    def __init__(self, api=None, *, node=None, chat_service=None, web=False, timeout=20):
        """``node``: a node.json path for the real backend; without it every
        unscripted /v1 request gets 404, so the page runs on scripted data only.

        ``web=True`` serves the web variant instead: the real ``make_server``
        over TLS on loopback with a generated local CA. The page itself sends
        the access key (``self.access_key``), so nothing is injected; every
        request goes to the real server and is only recorded."""
        self.api = api or FakeApi()
        self.node, self.chat_service, self.web = node, chat_service, web
        self.timeout = timeout
        self.console = []
        self.exceptions = []
        self.inflight = set()      # network request ids not finished yet
        self._statuses = {}        # network request id -> HTTP status
        self._last_activity = time.monotonic()
        self.dialogs = []          # (type, message) of every alert/confirm/prompt
        self.dialog_answers = []   # queued answers; True (accept) when empty

    def __enter__(self):
        browser = find_browser()
        if not browser:
            raise BrowserError('FPW_REQUIRE_BROWSER=1 but no Chromium was found')
        from spikes.desktop import request_policy
        from spikes.desktop_management import DesktopManagementHandler
        from spikes.local_api import running_api
        self._policy = request_policy
        self._stack = ExitStack()
        try:
            if self.web:
                self._start_web()
            projects = None
            if self.node is not None and not self.web:
                from spikes.administration import Administration
                from spikes.project_creation import ProjectCreation
                from spikes.projects import Projects
                ProjectCreation(self.node).initialize_node()
                administration = Administration(self.node, deployment='desktop')
                administration.bootstrap()
                projects = Projects(self.node)
            if not self.web:
                self.server = self._stack.enter_context(
                    running_api('http', handler=DesktopManagementHandler, projects=projects))
            if self.node is not None and not self.web:
                from spikes.desktop import attach_desktop_services
                chat = self.chat_service(self.node, projects) if self.chat_service else None
                attach_desktop_services(self.server, self.node, administration,
                                        chat_service=chat, monitoring=False)
            profile = self._stack.enter_context(tempfile.TemporaryDirectory(prefix='fpw-browser-'))
            # Only the web variant serves the generated loopback test CA.
            self._pipe = _Pipe(browser, profile, ['--ignore-certificate-errors'] if self.web else ())
            self._stack.callback(self._pipe.close)
            target = self._call('Target.createTarget', {'url': 'about:blank'})['targetId']
            self._session = self._call('Target.attachToTarget',
                                       {'targetId': target, 'flatten': True})['sessionId']
            for method, params in (('Runtime.enable', {}), ('Page.enable', {}), ('Network.enable', {}),
                                   ('Fetch.enable', {'patterns': [{'urlPattern': '*'}]})):
                self._call(method, params, session=self._session)
            # Native desktop actions are requested through location.hash; record
            # them as Qt would see them.
            self._call('Page.addScriptToEvaluateOnNewDocument', {'source':
                "window.__nativeActions=[];addEventListener('hashchange',()=>"
                "window.__nativeActions.push(location.hash.slice(1)));"}, session=self._session)
            self.navigate(self.server.origin + '/')
        except BaseException:
            self._stack.close()
            raise
        return self

    def _start_web(self):
        import secrets
        import threading
        from spikes.network_backend import NetworkBackend
        from spikes.web_server import make_server
        tls = NetworkBackend(self.node).generate('127.0.0.1', 8443, '192.168.100.0/24')
        token = self.node.parent / 'web-access-key'
        self.access_key = secrets.token_urlsafe(32)
        token.write_text(self.access_key)
        token.chmod(0o600)
        server = make_server('127.0.0.1', 0, '192.168.100.0/24', tls['cert'], tls['key'], token, self.node)
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        thread.start()

        def stop():
            server.shutdown()
            server.monitoring.close()
            server.server_close()
            thread.join(5)
        self._stack.callback(stop)
        server.origin = f'https://127.0.0.1:{server.server_port}'
        self.server = server

    def __exit__(self, *exc):
        self._stack.close()

    # -- DevTools plumbing -------------------------------------------------
    def _call(self, method, params=None, *, session=None, deadline=None):
        ident = self._pipe.send(method, params, session)
        deadline = deadline or time.monotonic() + self.timeout
        while True:
            if time.monotonic() > deadline:
                raise BrowserError(f'DevTools call timed out: {method}')
            message = self._pipe.read()
            if message.get('id') == ident:
                if 'error' in message:
                    raise BrowserError(f"{method}: {message['error']}")
                return message.get('result', {})
            self._event(message)

    def _event(self, message):
        method, params = message.get('method'), message.get('params', {})
        if method == 'Fetch.requestPaused':
            self._paused(params)
        elif method == 'Runtime.consoleAPICalled':
            self.console.append(' '.join(str(arg.get('value', arg.get('description', '')))
                                         for arg in params.get('args', [])))
        elif method == 'Runtime.exceptionThrown':
            details = params.get('exceptionDetails', {})
            self.exceptions.append(details.get('exception', {}).get('description')
                                   or details.get('text'))
        elif method == 'Network.requestWillBeSent':
            self.inflight.add(params['requestId'])
            self._last_activity = time.monotonic()
        elif method == 'Network.responseReceived':
            self._statuses[params['requestId']] = params['response']['status']
        elif method in ('Network.loadingFinished', 'Network.loadingFailed'):
            self.inflight.discard(params['requestId'])
            self._last_activity = time.monotonic()
        elif method == 'Page.loadEventFired':
            self._loaded = True
        elif method == 'Page.javascriptDialogOpening':
            # A native dialog blocks the page; answer it like the user would.
            self.dialogs.append((params.get('type'), params.get('message')))
            accept = self.dialog_answers.pop(0) if self.dialog_answers else True
            self._pipe.send('Page.handleJavaScriptDialog', {'accept': bool(accept)}, self._session)

    def _paused(self, params):
        request, ident = params['request'], params['requestId']
        url, method = request['url'], request['method']
        path = urlsplit(url).path
        if self.web:
            # The web page authenticates itself; record and pass everything on.
            if path.startswith('/v1/'):
                body = request.get('postData')
                try:
                    parsed = json.loads(body) if body else None
                except ValueError:
                    parsed = body
                self.api.requests.append({
                    'path': path, 'method': method, 'body': parsed,
                    'network_id': params.get('networkId'),
                    'authenticated': {name.lower(): value for name, value in request['headers'].items()}
                    .get('authorization') == 'Bearer ' + self.access_key})
            elif urlsplit(url).query or method != 'GET':
                self.api.requests.append({'path': path, 'method': method, 'navigation': url})
            self._pipe.send('Fetch.continueRequest', {'requestId': ident}, self._session)
            return
        initiator = self.server.origin + '/' if url.startswith(self.server.origin) else ''
        policy = self._policy(url, initiator, method, self.server.origin)
        if policy == 'allow' or (policy == 'block' and url.startswith(self.server.origin)
                                 and method == 'GET' and not path.startswith('/v1/')):
            # Static assets come from the real server with its real headers.
            self._pipe.send('Fetch.continueRequest', {'requestId': ident}, self._session)
            return
        if not path.startswith('/v1/'):
            self.api.requests.append({'path': path, 'method': method, 'blocked': True})
            self._pipe.send('Fetch.failRequest', {'requestId': ident, 'errorReason': 'BlockedByClient'},
                            self._session)
            return
        body = request.get('postData')
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            parsed = body
        self.api.requests.append({'path': path, 'method': method, 'body': parsed,
                                  'authenticated': policy == 'authenticate',
                                  'network_id': params.get('networkId')})
        if policy != 'authenticate':
            reply = Reply({'error': 'Request policy blocked ' + path}, status=403)
        else:
            reply = self.api.answer(path, parsed)
            if reply is None and self.node is not None:
                # The real backend, with the token the Qt interceptor would add.
                headers = [{'name': name, 'value': value} for name, value in request['headers'].items()
                           if name.lower() != 'authorization']
                headers.append({'name': 'Authorization', 'value': 'Bearer ' + self.server.token})
                self._pipe.send('Fetch.continueRequest', {'requestId': ident, 'headers': headers},
                                self._session)
                return
            if reply is None:
                reply = Reply({'error': 'Not scripted in the test: ' + path}, status=404)
        self._pipe.send('Fetch.fulfillRequest', {
            'requestId': ident, 'responseCode': reply.status,
            'responseHeaders': [{'name': 'Content-Type', 'value': reply.content_type}],
            'body': base64.b64encode(reply.raw).decode()}, self._session)

    # -- Test API ------------------------------------------------------------
    def navigate(self, url):
        self._loaded = False
        self._call('Page.navigate', {'url': url}, session=self._session)
        self.wait(lambda: self._loaded, 'page load')
        self.settle()

    def evaluate(self, expression, *, await_promise=True):
        result = self._call('Runtime.evaluate', {
            'expression': expression, 'awaitPromise': await_promise,
            'returnByValue': True, 'userGesture': True}, session=self._session)
        if 'exceptionDetails' in result:
            details = result['exceptionDetails']
            raise BrowserError(details.get('exception', {}).get('description') or details.get('text'))
        return result['result'].get('value')

    def wait(self, condition, what, timeout=None):
        """Process browser events until a Python condition holds."""
        deadline = time.monotonic() + (timeout or self.timeout)
        while not condition():
            if time.monotonic() > deadline:
                raise BrowserError('Timed out waiting for ' + what)
            self._call('Runtime.evaluate', {'expression': '0'}, session=self._session)
            time.sleep(0.02)

    def wait_js(self, expression, what=None, timeout=None):
        """Wait until a page expression is truthy in JavaScript."""
        deadline = time.monotonic() + (timeout or self.timeout)
        while True:
            # Boolean() on the page: a DOM node would serialize as an empty {}.
            if self.evaluate(f'Boolean({expression})'):
                return True
            if time.monotonic() > deadline:
                raise BrowserError('Timed out waiting for ' + (what or expression))
            time.sleep(0.05)

    def native_actions(self):
        """[(action, {field: value})] requested from the native shell so far."""
        from urllib.parse import parse_qsl
        result = []
        for value in self.evaluate('window.__nativeActions') or []:
            action, _, query = value.partition('?')
            result.append((action, dict(parse_qsl(query))))
        return result

    def wait_idle(self, quiet=0.4, timeout=None):
        """Wait until no request has been in flight for ``quiet`` seconds."""
        # Count the quiet time from this call at the earliest, so a request that
        # an action is about to start is not missed.
        start = time.monotonic()
        self.wait(lambda: not self.inflight and
                  time.monotonic() - max(self._last_activity, start) >= quiet,
                  'the page network to become idle', timeout)

    def status(self, record):
        """HTTP status of a recorded /v1 request, once its response arrived."""
        return self._statuses.get(record.get('network_id'))

    def response_json(self, record):
        """Body of a finished recorded request, parsed as JSON (or NDJSON lines)."""
        result = self._call('Network.getResponseBody', {'requestId': record['network_id']},
                            session=self._session)
        raw = base64.b64decode(result['body']) if result.get('base64Encoded') else result['body'].encode()
        lines = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
        return lines[0] if len(lines) == 1 else lines

    def settle(self, seconds=0.2):
        """Let pending timers and fetches finish."""
        self.evaluate(f'new Promise(resolve=>setTimeout(resolve,{int(seconds * 1000)}))')

    def click(self, selector):
        self.evaluate(f'document.querySelector({json.dumps(selector)}).click()')

    def fill(self, selector, value):
        self.evaluate(f'''(()=>{{const el=document.querySelector({json.dumps(selector)});
          el.value={json.dumps(value)};el.dispatchEvent(new Event('input',{{bubbles:true}}));
          el.dispatchEvent(new Event('change',{{bubbles:true}}));}})()''')

    def text(self, selector):
        return self.evaluate(f'document.querySelector({json.dumps(selector)})?.textContent ?? null')

    def visible(self, selector):
        return self.evaluate(f'Boolean(document.querySelector({json.dumps(selector)})?.checkVisibility())')
