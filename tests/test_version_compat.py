# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""AUDIT-B3: upgrade regressions N -> N+1 under the version compatibility contract.

docs/version-compatibility.md: an unknown newer version is a typed visible
error (K1), behaviour never falls back to an older version (K2), the failure
scope is the validation unit (K3, ADR 0085), cross-process state is typed (K6)
and the extension/backend protocol is declared (K7, ADR 0060). No test here
accepts a silent disable as correct behaviour.
"""
from contextlib import closing
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from uuid import uuid4

from spikes import bridge_protocol
from spikes.action_autonomy import parse_plan
from spikes.administration import Administration
from spikes.artifacts import Artifacts, main_todo_id
from spikes.federation_catalog import validate_catalog
from spikes.federation_sync import validate_exchange
from spikes.local_api import Handler, running_api
from spikes.metadata import UnsupportedVersion, ValidationError, peer_unsupported_version
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from tests import test_action_autonomy as autonomy_fixture  # module import: no test re-run

GIT_ENV = {'GIT_AUTHOR_NAME': 'n', 'GIT_AUTHOR_EMAIL': 'n@x', 'GIT_COMMITTER_NAME': 'n',
           'GIT_COMMITTER_EMAIL': 'n@x', 'PATH': '/usr/bin:/bin'}


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, env=GIT_ENV,
                          capture_output=True, text=True).stdout.strip()


class ArtifactMetadataUpgradeTests(unittest.TestCase):
    """Fixture R3: one artifact with metadata N+1 committed by a newer node."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        base = Path(tmp.name); self.node = base / 'node.json'; self.root = base / 'project'
        self.pid = ProjectCreation(self.node).create('Upgrade', str(self.root), str(uuid4()))['id']
        self.artifacts = Artifacts(self.node); self.aid = main_todo_id(self.pid)
        head = Projects(self.node).repository(self.pid).head()
        self.artifacts.save(dict(project_id=self.pid, artifact_id=self.aid, base_head=head,
                                 title='Roadmap', body='- [ ] Task\n', new=True), str(uuid4()))
        self.path = self.root / 'artifacts' / self.aid / 'metadata.json'
        self.supported = json.loads(self.path.read_text())

    def commit_version(self, version):
        self.path.write_text(json.dumps(dict(self.supported, schema_version=version), indent=2) + '\n')
        git(self.root, 'commit', '-qam', f'metadata v{version}')
        return git(self.root, 'rev-parse', 'HEAD')

    def journal_state(self):
        ws = Projects(self.node).workspace(self.pid)
        with ws.journal.lock(shared=True), ws.journal.connect() as db:
            return (db.execute('SELECT count(*) FROM pending').fetchone(),
                    db.execute('SELECT * FROM operations').fetchall())

    def test_newer_artifact_metadata_is_typed_and_names_the_artifact(self):
        journal = self.journal_state()
        newer = self.commit_version(5)
        for name, call in (('artifacts.open', lambda: self.artifacts.open(self.pid)),
                           ('projects.open', lambda: Projects(self.node).open(self.pid))):
            with self.subTest(reader=name), self.assertRaises(UnsupportedVersion) as caught:
                call()
            error = caught.exception
            self.assertEqual((error.kind, error.subject, error.found, error.supported, error.update),
                             ('artifact-metadata', self.aid, 5, (1, 4), 'this-node'))
            self.assertIn(self.aid, str(error)); self.assertIn('Aktualizujte', str(error))
        # Fail-closed leaves Git, the journal and the stale index untouched.
        self.assertEqual(git(self.root, 'rev-parse', 'HEAD'), newer)
        self.assertEqual(git(self.root, 'status', '--porcelain'), '')
        self.assertEqual(self.journal_state(), journal)

    def test_project_opens_again_once_the_version_is_supported(self):
        self.commit_version(5)
        with self.assertRaises(UnsupportedVersion):
            self.artifacts.open(self.pid)
        current = self.commit_version(self.supported['schema_version'])
        self.assertEqual(self.artifacts.open(self.pid)['commit_id'], current)

    def test_older_or_missing_version_is_invalid_data_without_update_advice(self):
        for version in (0, None, '4'):
            with self.subTest(version=version):
                self.commit_version(version)
                with self.assertRaises(UnsupportedVersion) as caught:
                    self.artifacts.open(self.pid)
                self.assertIsNone(caught.exception.update)
                self.assertNotIn('Aktualizujte', str(caught.exception))

    def test_generic_http_rejection_keeps_the_typed_version_error(self):
        self.commit_version(5)
        artifacts, pid = self.artifacts, self.pid

        class OpenHandler(Handler):
            post_paths = Handler.post_paths | {'/v1/test/open'}

            def dispatch(self, request):
                try:
                    return self.reply(200, artifacts.open(pid))
                except ValueError:  # the generic mapping of many routes
                    return self.reply(422, {'error': 'Projekt nelze otevřít.'})

        with running_api('http', handler=OpenHandler) as server:
            status, _, body = http(server, '/v1/test/open', b'{}')
        self.assertEqual(status, 422)
        self.assertEqual((body['code'], body['kind'], body['subject'], body['found'],
                          body['supported'], body['update']),
                         ('unsupported_version', 'artifact-metadata', self.aid, 5, [1, 4], 'this-node'))
        self.assertIn(self.aid, body['error'])


class AutonomyPlanUpgradeTests(unittest.TestCase):
    """Fixture R4: plan v4 never runs as plan v1."""
    def setUp(self):
        self.helper = autonomy_fixture.ActionAutonomyTests('setUp'); self.helper.setUp()
        self.addCleanup(self.helper.doCleanups)

    def test_parse_plan_v4_is_typed_before_field_checks(self):
        h = self.helper
        step = h.step('analysis.read-only', {'selection_sha256': '1' * 64})
        for name, plan in (('base fields', dict(h.plan([step]), schema_version=4)),
                           ('v3 fields', dict(h.dynamic_plan([step]), schema_version=4))):
            with self.subTest(plan=name), self.assertRaises(UnsupportedVersion) as caught:
                parse_plan(plan, h.registry)
            self.assertEqual((caught.exception.kind, caught.exception.found,
                              caught.exception.supported), ('autonomy-plan', 4, (1, 3)))

    def test_stored_v4_workflow_is_an_explicit_error_not_v1_logic(self):
        h = self.helper; queue = h.queue()
        plan = h.plan([h.step('analysis.read-only', {'selection_sha256': '1' * 64})], mode='manual')
        h.prepare_and_activate(queue, plan)
        with closing(sqlite3.connect(queue.path)) as db:  # written by a newer node, then downgraded
            db.execute('UPDATE workflows SET plan_json=? WHERE workflow_id=?',
                       (json.dumps(dict(plan, schema_version=4)).encode(), h.workflow_id))
            db.commit()
        for name, call in (('get', lambda: queue.get(h.workflow_id, h.node_id, h.user_id)),
                           ('advance', lambda: h.advance(queue))):
            with self.subTest(call=name), self.assertRaises(UnsupportedVersion):
                call()

    def test_known_versions_keep_their_capabilities(self):
        h = self.helper; queue = h.queue()
        plan = h.dynamic_plan([h.step('analysis.read-only', {'selection_sha256': '1' * 64})])
        view = queue.prepare(plan, h.node_id, h.user_id)
        self.assertEqual(view['plan_capabilities'], ['countdown', 'policy', 'revisions'])
        self.assertEqual(view['countdown_seconds'], 3); self.assertIsNotNone(view['policy'])


class FederationAndRegistryUpgradeTests(unittest.TestCase):
    def test_newer_registry_is_typed(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        admin = Administration(Path(tmp.name) / 'node.json')
        node_id = str(uuid4())
        with self.assertRaises(UnsupportedVersion) as caught:
            admin.validate({'schema_version': 7, 'node_id': node_id, 'users': [], 'peers': []}, node_id)
        self.assertEqual((caught.exception.kind, caught.exception.found,
                          caught.exception.supported), ('node-registry', 7, (1, 6)))

    def test_newer_exchange_and_catalog_are_typed_before_fields(self):
        for kind, validate, found, supported in (
                ('content-sync', validate_exchange, 4, (2, 3)),
                ('project-catalog', validate_catalog, 2, (1, 1))):
            with self.subTest(kind=kind), self.assertRaises(UnsupportedVersion) as caught:
                validate({'schema_version': found, 'future_field': True})
            self.assertEqual((caught.exception.kind, caught.exception.found,
                              caught.exception.supported, caught.exception.update),
                             (kind, found, supported, 'this-node'))

    def test_sender_reports_the_older_peer_as_the_side_to_update(self):
        peer = str(uuid4())
        refusal = UnsupportedVersion('content-sync', 4, (2, 3)).details()
        translated = peer_unsupported_version(json.dumps(refusal).encode(), subject=peer)
        self.assertEqual((translated.update, translated.subject, translated.found), ('peer', peer, 4))
        self.assertIn('protistranu', str(translated))
        for body in (b'{"error":"Content sync request rejected"}', b'not json', b'x' * 5000,
                     json.dumps(dict(refusal, supported=[3, 'x'])).encode()):
            self.assertIsNone(peer_unsupported_version(body))


def http(server, path, body, headers=()):
    fields = {'Host': server.authority, 'Authorization': 'Bearer ' + server.token,
              'Content-Type': 'application/json', 'Content-Length': str(len(body))}
    message = (f'POST {path} HTTP/1.1\r\n' + ''.join(
        f'{k}: {v}\r\n' for k, v in [*fields.items(), *headers]) + '\r\n').encode() + body
    with socket.create_connection(server.server_address, timeout=5) as client:
        client.sendall(message); client.shutdown(socket.SHUT_WR)
        chunks = []
        while data := client.recv(65536):
            chunks.append(data)
    head, _, payload = b''.join(chunks).partition(b'\r\n\r\n')
    lines = head.decode().split('\r\n')
    response_headers = dict(line.split(': ', 1) for line in lines[1:])
    return int(lines[0].split()[1]), response_headers, json.loads(payload)


class BridgeProtocolTests(unittest.TestCase):
    """Older extension x new backend and protocol mismatch, before any dispatch."""
    def setUp(self):
        self.dispatched = []
        dispatched = self.dispatched

        class BridgeHandler(Handler):
            post_paths = Handler.post_paths | {'/v1/ide-bridge/exchange',
                                               '/v1/ide-bridge/connection/exchange'}

            def dispatch(self, request):
                dispatched.append(request)
                return self.reply(200, {'ok': True})

        context = running_api('http', handler=BridgeHandler)
        self.server = context.__enter__(); self.addCleanup(context.__exit__, None, None, None)

    def call(self, protocol=None, path='/v1/ide-bridge/exchange', body=b'{"messages":[]}'):
        headers = () if protocol is None else ((bridge_protocol.HEADER, protocol),)
        return http(self.server, path, body, headers)

    def test_older_extension_without_header_is_protocol_one(self):
        status, headers, body = self.call()
        self.assertEqual((status, body), (200, {'ok': True}))
        self.assertEqual(headers[bridge_protocol.HEADER], '1-1')
        self.assertEqual(self.call('1')[0], 200)

    def test_newer_or_older_protocol_is_refused_before_dispatch_with_side(self):
        for protocol, update in (('2', 'backend'), ('0', 'extension')):
            with self.subTest(protocol=protocol):
                status, _, body = self.call(protocol)
                self.assertEqual(status, 426)
                self.assertEqual((body['code'], body['kind'], body['found'], body['supported'],
                                  body['update']),
                                 ('unsupported_version', 'ide-protocol', int(protocol), [1, 1], update))
        self.assertEqual(self.dispatched, [])

    def test_extension_update_stays_reachable_for_any_protocol(self):
        update = json.dumps({'connection_id': str(uuid4()), 'action': 'extension-update',
                             'download': False}).encode()
        for protocol in ('0', '2'):
            with self.subTest(protocol=protocol):
                status, _, _ = self.call(protocol, '/v1/ide-bridge/connection/exchange', update)
                self.assertEqual(status, 200)
        self.assertEqual(len(self.dispatched), 2)

    def test_malformed_header_is_rejected(self):
        for protocol in ('one', '1.0', '9999999'):
            with self.subTest(protocol=protocol):
                self.assertEqual(self.call(protocol)[0], 400)
        self.assertEqual(self.dispatched, [])

    def test_other_routes_ignore_the_header(self):
        status, headers, _ = http(self.server, '/v1/counter', b'{"action":"increment"}',
                                  ((bridge_protocol.HEADER, '9'),))
        self.assertEqual(status, 200); self.assertNotIn(bridge_protocol.HEADER, headers)


class TypedErrorTests(unittest.TestCase):
    def test_unsupported_version_is_a_validation_error_with_safe_subject(self):
        error = UnsupportedVersion('registry', 9, {1, 2, 3}, subject='bad subject\n<x>')
        self.assertIsInstance(error, ValidationError)
        self.assertIsNone(error.subject)
        self.assertEqual(error.details()['supported'], [1, 3])


if __name__ == '__main__':
    unittest.main()
