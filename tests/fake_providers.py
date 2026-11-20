# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Loopback HTTP fakes of Ollama and SearXNG for behavioural UI tests (AUDIT-B7-T1).

The real adapters talk HTTP to these servers, so a browser test covers the
whole path from the UI through the API, the service and the adapter.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


class _Server:
    def __init__(self, handler):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.server.fake = self
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def endpoint(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, value, status=200):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class FakeOllama(_Server):
    """``answers``: queue of JSON values (or callables(request) -> value); each
    becomes the text of one /api/generate reply, JSON-encoded unless a str."""

    def __init__(self, model='gemma3', answers=()):
        self.model, self.answers, self.requests = model, list(answers), []
        super().__init__(_OllamaHandler)

    def next_text(self, request):
        value = self.answers.pop(0) if self.answers else {
            'schema_version': 1, 'kind': 'direct-answer', 'content': 'Odpověď modelu.'}
        value = value(request) if callable(value) else value
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class _OllamaHandler(_Handler):
    def do_GET(self):
        fake = self.server.fake
        if self.path == '/api/tags':
            return self.send_json({'models': [{'name': fake.model}]})
        if self.path == '/api/ps':
            return self.send_json({'models': []})
        self.send_json({'error': 'not found'}, 404)

    def do_POST(self):
        fake = self.server.fake
        length = int(self.headers.get('Content-Length') or 0)
        request = json.loads(self.rfile.read(length) or b'{}')
        if self.path != '/api/generate':
            return self.send_json({'error': 'not found'}, 404)
        fake.requests.append(request)
        text = fake.next_text(request)
        created = '2026-11-20T12:00:00.000000Z'
        if not request.get('stream'):
            return self.send_json({'model': fake.model, 'created_at': created,
                                   'response': text, 'done': True})
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.end_headers()
        middle = max(1, len(text) // 2)
        for chunk, done in ((text[:middle], False), (text[middle:], False), ('', True)):
            frame = {'model': fake.model, 'created_at': created, 'response': chunk, 'done': done}
            if done:
                frame['done_reason'] = 'stop'
            self.wfile.write(json.dumps(frame, ensure_ascii=False).encode() + b'\n')
            self.wfile.flush()


class FakeSearXNG(_Server):
    """``results``: list of {'title','url','content'} returned for every query."""

    def __init__(self, results=()):
        self.results, self.queries = list(results), []
        super().__init__(_SearchHandler)


class _SearchHandler(_Handler):
    def do_GET(self):
        fake = self.server.fake
        parsed = urlsplit(self.path)
        if parsed.path != '/search':
            return self.send_json({'error': 'not found'}, 404)
        fake.queries.append(parse_qs(parsed.query).get('q', [''])[0])
        self.send_json({'results': fake.results})
