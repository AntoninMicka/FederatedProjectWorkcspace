# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Optional native comparison: set M0_LIBGIT2_PROBE to the compiled C++ probe."""
from contextlib import closing, contextmanager
import base64
import http.server
import json
from itertools import product
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
import threading
import unittest
from urllib.parse import urlsplit

from spikes.storage import Git, Index, StaleIndex
from tests.fixtures import ENTITY, registry


class Adapter:
    def __init__(self, root, native):
        self.git = Git(root)
        self.native = native

    def call(self, command, *args, check=True, auth=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'M0_AUTH_'))}
        if auth:
            env.update(M0_AUTH_USER=auth[0], M0_AUTH_PASSWORD=auth[1])
        return subprocess.run([os.environ['M0_LIBGIT2_PROBE'], command, str(self.git.root), *args],
                              env=env, capture_output=True, text=True, check=check, timeout=20)

    def commit(self, message, path, second='-', prepare=False):
        if self.native:
            return self.call('prepare' if prepare else 'commit', message, second, path).stdout.strip()
        self.git.run('add', '--', path)
        tree = self.git.run('write-tree').stdout.strip()
        parents = ['-p', self.git.head()]
        if second != '-':
            parents += ['-p', second]
        candidate = self.git.run('commit-tree', tree, *parents, '-m', message).stdout.strip()
        if not prepare:
            self.git.run('update-ref', 'HEAD', candidate)
            if second != '-':
                self.git.run('reset', '--hard', candidate)
        return candidate

    def fetch(self, source, *, auth=None, check=True):
        if self.native:
            return self.call('fetch', source, auth=auth, check=check)
        config = []
        if auth:
            encoded = base64.b64encode(':'.join(auth).encode()).decode()
            config = ['-c', f'http.extraHeader=Authorization: Basic {encoded}']
        return self.git.run(*config, 'fetch', source, '+refs/heads/main:refs/remotes/probe/main', check=check)

    def cas(self, candidate, expected, check=True):
        if self.native:
            return self.call('cas', 'refs/heads/main', candidate, expected, check=check)
        return self.git.run('update-ref', 'refs/heads/main', candidate, expected, check=check)


@unittest.skipUnless(os.environ.get('M0_LIBGIT2_PROBE'), 'Native probe not configured; see spikes/libgit2/README.md')
class GitComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.path = f'registries/decisions/{ENTITY}.json'
        self.assertTrue(Path(os.environ['M0_LIBGIT2_PROBE']).is_file())

    def adapter(self, native, name):
        root = self.base / name
        root.mkdir()
        adapter = Adapter(root, native)
        adapter.git.run('init', '--initial-branch=main')
        adapter.git.run('commit', '--allow-empty', '-m', 'Initialize comparison')
        return adapter

    def write(self, adapter, title):
        path = adapter.git.root / self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(registry(title))

    def test_commit_branch_clone_conflict_abort_and_resolution(self):
        for native in (False, True):
            with self.subTest(native=native):
                local = self.adapter(native, f'local-{native}')
                self.write(local, 'Shared base')
                local.commit('Base', self.path)
                if native:
                    local.call('branch', 'topic')
                else:
                    local.git.run('branch', 'topic')
                self.assertEqual(local.git.run('rev-parse', 'topic').stdout.strip(), local.git.head())
                peer = Adapter(self.base / f'peer-{native}', native)
                if native:
                    peer.call('clone', str(local.git.root))
                else:
                    local.git.run('clone', '--no-hardlinks', str(local.git.root), str(peer.git.root))
                self.write(local, 'Desktop edit')
                left = local.commit('Desktop offline', self.path)
                self.write(peer, 'Server edit')
                right = peer.commit('Server offline', self.path)
                local.fetch(str(peer.git.root))
                self.assertEqual(local.git.run('rev-parse', 'refs/remotes/probe/main').stdout.strip(), right)
                for attempt in range(2):
                    if native:
                        result = local.call('merge', right, check=False)
                        self.assertEqual(result.returncode, 3, result.stderr)
                    else:
                        result = local.git.run('merge', '--no-edit', right, check=False)
                        self.assertEqual(result.returncode, 1, result.stderr)
                    for stage, title in [(1, 'Shared base'), (2, 'Desktop edit'), (3, 'Server edit')]:
                        raw = local.git.run('show', f':{stage}:{self.path}').stdout
                        self.assertEqual(json.loads(raw)['title'], title)
                    self.assertEqual(local.git.head(), left)
                    if attempt == 0:
                        if native:
                            local.call('abort')
                        else:
                            local.git.run('merge', '--abort')
                        self.assertEqual(local.git.run('status', '--porcelain').stdout, '')
                        self.assertEqual(local.git.head(), left)
                self.write(local, 'Human resolution')
                merged = local.commit('Resolve', self.path, second=right)
                self.assertEqual(local.git.run('show', '-s', '--format=%P', merged).stdout.split(), [left, right])
                db = Index(self.base / f'{native}.sqlite')
                db.rebuild(local.git)
                self.assertEqual(db.read(local.git), [(ENTITY, 'Human resolution')])
                self.assertEqual(local.git.run('status', '--porcelain').stdout, '')

    def test_candidate_cas_and_restart_before_index_without_duplicate_commit(self):
        for native, phase in product((False, True), ('before', 'after')):
            with self.subTest(native=native, phase=phase):
                adapter = self.adapter(native, f'recovery-{native}-{phase}')
                db = Index(self.base / f'index-{native}-{phase}.sqlite')
                db.rebuild(adapter.git)
                base = adapter.git.head()
                self.write(adapter, 'Candidate')
                candidate = adapter.commit('Prepared', self.path, prepare=True)
                self.assertEqual(adapter.git.head(), base)
                # Test driver persists candidate before killing its publisher process.
                record = self.base / f'operation-{native}-{phase}.json'
                record.write_text(json.dumps(dict(candidate=candidate, base=base)))
                script = '''
import json, os, sys
from pathlib import Path
from tests.test_git_comparison import Adapter
r = json.loads(Path(sys.argv[3]).read_text())
a = Adapter(Path(sys.argv[1]), sys.argv[2] == 'True')
if sys.argv[4] == 'after':
    a.cas(r['candidate'], r['base'])
os._exit(73)
'''
                result = subprocess.run([sys.executable, '-c', script, str(adapter.git.root), str(native), str(record), phase],
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 73, result.stderr)
                reopened = Adapter(adapter.git.root, native)
                if phase == 'before':
                    self.assertEqual(reopened.git.head(), base)
                    reopened.cas(candidate, base)
                self.assertEqual(reopened.git.head(), candidate)
                with self.assertRaises(StaleIndex):
                    db.read(reopened.git)
                db.rebuild(reopened.git)
                self.assertEqual(db.read(reopened.git), [(ENTITY, 'Candidate')])
                self.assertNotEqual(reopened.cas(candidate, base, check=False).returncode, 0)
                self.assertEqual(reopened.git.head(), candidate)
                self.assertEqual(reopened.git.run('rev-list', '--count', 'HEAD').stdout.strip(), '2')
                # An actually different intervening head must be retained as well.
                self.write(reopened, 'Foreign')
                foreign = reopened.commit('Foreign', self.path)
                self.assertNotEqual(reopened.cas(candidate, base, check=False).returncode, 0)
                self.assertEqual(reopened.git.head(), foreign)

    def test_semantically_invalid_commit_does_not_replace_index(self):
        for native in (False, True):
            adapter = self.adapter(native, f'invalid-{native}')
            self.write(adapter, 'Valid')
            old = adapter.commit('Valid', self.path)
            db = Index(self.base / f'invalid-{native}.sqlite')
            db.rebuild(adapter.git)
            (adapter.git.root / self.path).write_text('{"invalid":true}')
            adapter.commit('Invalid projection', self.path)
            with self.assertRaises(ValueError):
                db.rebuild(adapter.git)
            with self.assertRaises(StaleIndex):
                db.read(adapter.git)
            with closing(sqlite3.connect(db.path)) as connection:
                self.assertEqual(connection.execute('SELECT commit_id FROM state').fetchone()[0], old)
                self.assertEqual(connection.execute('SELECT id, title FROM entities').fetchall(), [(ENTITY, 'Valid')])
            self.assertNotEqual(adapter.git.head(), old)

    @unittest.skipUnless(os.environ.get('M0_GIT_HTTP') == '1', 'Loopback HTTP comparison explicitly enabled')
    def test_http_authentication_success_missing_and_wrong_credentials(self):
        server_repo = self.adapter(False, 'server')
        self.write(server_repo, 'Remote document')
        commit = server_repo.commit('Remote', self.path)
        with smart_http(self.base) as url:
            for native in (False, True):
                client = self.adapter(native, f'client-{native}')
                for auth in (None, ('test-user', 'wrong')):
                    result = client.fetch(url + '/server', auth=auth, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('test-password', result.stderr)
                    self.assertNotEqual(client.git.run('rev-parse', '--verify', 'refs/remotes/probe/main', check=False).returncode, 0)
                client.fetch(url + '/server', auth=('test-user', 'test-password'))
                self.assertEqual(client.git.run('rev-parse', 'refs/remotes/probe/main').stdout.strip(), commit)
                self.assertEqual(client.git.snapshot(commit)[self.path], registry('Remote document'))


@contextmanager
def smart_http(root):
    backend = Path(subprocess.run(['git', '--exec-path'], capture_output=True, text=True, check=True).stdout.strip()) / 'git-http-backend'
    expected = 'Basic ' + base64.b64encode(b'test-user:test-password').decode()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_git(self):
            if self.headers.get('Authorization') != expected:
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="M0"')
                self.end_headers()
                return
            path = urlsplit(self.path)
            env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
            env.update(GIT_PROJECT_ROOT=str(root), GIT_HTTP_EXPORT_ALL='1', PATH_INFO=path.path,
                       QUERY_STRING=path.query, REQUEST_METHOD=self.command,
                       CONTENT_TYPE=self.headers.get('Content-Type', ''), REMOTE_USER='test-user')
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            result = subprocess.run([str(backend)], env=env, input=body, capture_output=True, timeout=15)
            headers, payload = result.stdout.split(b'\r\n\r\n', 1)
            self.send_response(200)
            for line in headers.decode().split('\r\n'):
                name, value = line.split(':', 1)
                self.send_header(name, value.strip())
            self.end_headers()
            self.wfile.write(payload)

        do_GET = handle_git
        do_POST = handle_git

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
