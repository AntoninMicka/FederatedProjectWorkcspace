# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Thread
import unittest

from spikes.metadata import ValidationError
from spikes.module_manifest import (canonical_manifest, fetch_and_verify_module,
                                    parse_module_manifest, read_module_manifest,
                                    verify_module_api)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'modules' / 'publication-experiment-registry.module.json'


class ModuleManifestTests(unittest.TestCase):
    def setUp(self):
        self.value = read_module_manifest(MANIFEST)

    def test_reviewed_manifest_is_valid_and_contains_no_binding(self):
        self.assertEqual(self.value['schema_version'], 1)
        self.assertNotIn('url', json.dumps(self.value).lower())
        self.assertNotIn('credential', json.dumps(self.value).lower())
        self.assertEqual(parse_module_manifest(canonical_manifest(self.value)), self.value)

    def test_manifest_rejects_unknown_missing_duplicate_and_unsafe_contracts(self):
        cases = []
        cases.append(dict(self.value, endpoint='http://127.0.0.1:1'))
        missing = deepcopy(self.value); del missing['module_id']; cases.append(missing)
        duplicate = deepcopy(self.value); duplicate['capabilities'].append(deepcopy(duplicate['capabilities'][0])); cases.append(duplicate)
        external = deepcopy(self.value); external['capabilities'][0]['side_effect'] = 'external'; cases.append(external)
        secret = deepcopy(self.value); secret['capabilities'][0]['permissions'] = ['credential:secret']; cases.append(secret)
        foreign = deepcopy(self.value); foreign['capabilities'][0]['input_schema'] = 'module://cz.example.other/schemas/input.json'; cases.append(foreign)
        dependency = deepcopy(self.value); dependency['dependencies'] = ['bad dependency']; cases.append(dependency)
        for value in cases:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                parse_module_manifest(canonical_manifest(value))

    def test_api_contract_must_match_exactly(self):
        self.assertEqual(verify_module_api(self.value, canonical_manifest(self.value)), self.value)
        for field, changed in [('module_version', '0.4.0'), ('module_id', 'cz.example.other')]:
            value = deepcopy(self.value); value[field] = changed
            with self.subTest(field=field), self.assertRaises(ValidationError):
                verify_module_api(self.value, canonical_manifest(value))
        value = deepcopy(self.value); value['capabilities'][0]['limits']['max_items'] = 999
        with self.assertRaises(ValidationError):
            verify_module_api(self.value, canonical_manifest(value))

    def test_live_same_node_check_and_fail_closed_errors(self):
        payload = canonical_manifest(self.value)

        class Handler(BaseHTTPRequestHandler):
            response = payload
            content_type = 'application/json'
            status = 200

            def do_GET(self):
                self.send_response(self.status)
                self.send_header('Content-Type', self.content_type)
                if 300 <= self.status < 400:
                    self.send_header('Location', '/redirected')
                self.send_header('Content-Length', str(len(self.response)))
                self.end_headers()
                self.wfile.write(self.response)

            def log_message(self, *_):
                pass

        try:
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        except PermissionError:
            self.skipTest('sandbox does not permit loopback sockets')
        thread = Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        self.assertEqual(fetch_and_verify_module(MANIFEST, base), self.value)
        for url in ('https://127.0.0.1:443', 'http://example.com:80', base + '/nested',
                    'http://user:secret@127.0.0.1:1234'):
            with self.subTest(url=url), self.assertRaises(ValidationError):
                fetch_and_verify_module(MANIFEST, url)
        Handler.response = canonical_manifest(dict(self.value, module_version='0.4.0'))
        with self.assertRaises(ValidationError):
            fetch_and_verify_module(MANIFEST, base)
        Handler.response = payload; Handler.content_type = 'text/plain'
        with self.assertRaises(ValidationError):
            fetch_and_verify_module(MANIFEST, base)
        Handler.content_type = 'application/json'; Handler.status = 302
        with self.assertRaises(ValidationError):
            fetch_and_verify_module(MANIFEST, base)
        Handler.status = 200
        server.shutdown(); thread.join(timeout=5); server.server_close()
        with self.assertRaises(ValidationError):
            fetch_and_verify_module(MANIFEST, base)

    def test_cli_is_read_only_and_does_not_leak_invalid_content(self):
        result = subprocess.run([sys.executable, '-m', 'spikes.check_module', str(MANIFEST)],
                                cwd=ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        with tempfile.TemporaryDirectory(prefix='module manifest ') as temp:
            broken = Path(temp) / 'module.json'
            broken.write_text('{"credential":"TOP_SECRET", broken')
            result = subprocess.run([sys.executable, '-m', 'spikes.check_module', str(broken)],
                                    cwd=ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn('TOP_SECRET', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
