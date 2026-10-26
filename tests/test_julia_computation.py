# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import julia_runtime_binding
from scripts.julia_runtime_binding import main as runtime_binding_cli
from spikes.julia_cli import main as julia_cli
from spikes.julia_computation import (BubblewrapSandbox, DirectTestSandbox,
    JuliaExecutor, RUN_SCHEMA, _distribution_digest, validate_computation)
from spikes.metadata import ValidationError, validate_metadata, validate_snapshot
from spikes.output_execution import canonical, digest
from spikes.project_creation import ProjectCreation
from spikes.projects import Projects
from spikes.storage import Git


class JuliaComputationTests(unittest.TestCase):
    VERSION = '1.10.12'

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name); self.node = self.base / 'node.json'
        self.project = self.base / 'project'; self.project_id = str(uuid4())
        self.author = str(uuid4())
        self.ids = {name: str(uuid4()) for name in ('model', 'project', 'manifest', 'input')}
        self.raw = {
            'model': b'# model entrypoint\n',
            'project': ('name = "WorkspaceComputation"\nuuid = "' + str(uuid4()) + '"\n').encode(),
            'manifest': (f'julia_version = "{self.VERSION}"\nmanifest_format = "2.0"\n'
                         + 'project_hash = "' + 'a' * 64 + '"\n').encode(),
            'input': b'41\n',
        }
        names = {'model': 'model.jl', 'project': 'Project.toml',
                 'manifest': 'Manifest-v1.10.toml', 'input': 'input.txt'}
        files = {}
        for name, artifact_id in self.ids.items():
            filename = names[name]
            metadata = {'schema_version': 1, 'id': artifact_id, 'title': name.title(),
                'kind': 'source', 'created_at': '2026-10-26T12:00:00Z',
                'author_id': self.author,
                'privacy': 'confidential' if name == 'input' else 'project',
                'provenance': 'user', 'file': filename}
            files[f'artifacts/{artifact_id}/{filename}'] = self.raw[name]
            files[f'artifacts/{artifact_id}/metadata.json'] = (
                json.dumps(metadata, sort_keys=True) + '\n').encode()
        ProjectCreation(self.node).create('Julia project', str(self.project), str(uuid4()),
            initial_files=files, project_id=self.project_id,
            created_at='2026-10-26T12:00:00Z', request_digest='b' * 64,
            commit_message='Seed Julia project')
        self.git = Git(self.project); self.state = self.base / 'julia-state'
        self.state.mkdir(mode=0o700)
        self.runtime = self.base / 'runtime'; self.runtime.mkdir(mode=0o700)
        (self.runtime / 'bin').mkdir(mode=0o700)
        (self.runtime / 'lib' / 'julia').mkdir(parents=True, mode=0o700)
        (self.runtime / 'lib').chmod(0o700)
        self.executable = self.runtime / 'bin' / 'julia'
        self.executable.write_text('''#!/usr/bin/python3
import hashlib, json, os, pathlib, socket, sys, time
if '--version' in sys.argv:
    print('julia version 1.10.12'); sys.exit(0)
request = pathlib.Path(sys.argv[sys.argv.index('--fpw-request') + 1])
output = pathlib.Path(sys.argv[sys.argv.index('--fpw-output') + 1])
value = json.loads(request.read_text())['parameters'].get('value', 0)
if value == 998: time.sleep(5)
if value == 999: sys.exit(7)
if value == 995:
    sys.stdout.write('x' * 10000); sys.stdout.flush()
raw = ('result=' + str(value) + '\\n').encode()
if value == 994: raw = b'x' * 2048
if value == 993:
    probe = socket.socket(); probe.settimeout(0.2)
    try:
        probe.connect(('1.1.1.1', 53)); raw = b'network=open\\n'
    except OSError:
        raw = b'network=denied\\n'
    finally:
        probe.close()
if value == 996:
    os.symlink('/etc/passwd', output / 'result.txt')
    raw = (output / 'result.txt').read_bytes()
else:
    (output / 'result.txt').write_bytes(raw)
if value == 997: (output / 'undeclared.txt').write_text('undeclared')
manifest = {'schema':'fpw-julia-result-v1','outputs':[{'name':'result',
    'kind':'report','media_type':'text/plain','path':'result.txt','size':len(raw),
    'sha256':hashlib.sha256(raw).hexdigest()}]}
(output / 'fpw-julia-result-v1.json').write_text(
    json.dumps(manifest, sort_keys=True, separators=(',', ':')))
''', encoding='utf-8')
        self.executable.chmod(0o700)
        self.sysimage = self.runtime / 'lib' / 'julia' / 'sys.so'
        self.sysimage.write_bytes(b'fake-sysimage')
        self.sysimage.chmod(0o600)
        self.depot = self.base / 'depot'; self.depot.mkdir(mode=0o700)
        self.binding = {'schema': 'fpw-julia-runtime-v1',
            'binding_id': str(uuid4()), 'revision': 'test-1',
            'executable': str(self.executable), 'version': self.VERSION,
            'platform': 'linux-' + os.uname().machine.lower(),
            'executable_sha256': digest(self.executable.read_bytes()),
            'distribution_sha256': _distribution_digest(self.runtime),
            'sysimage': str(self.sysimage), 'sysimage_sha256': digest(self.sysimage.read_bytes()),
            'depot': str(self.depot), 'depot_sha256': hashlib.sha256().hexdigest()}
        self.computation = self.make_computation()
        self.node_id, self.user_id = str(uuid4()), str(uuid4())

    def blob(self, artifact, filename):
        path = f'artifacts/{self.ids[artifact]}/{filename}'
        info = self.git.run('ls-tree', self.git.head(), '--', path).stdout.strip().split('\t')[0]
        return path, info.split()[2]

    def make_computation(self):
        model_path, model_blob = self.blob('model', 'model.jl')
        input_path, input_blob = self.blob('input', 'input.txt')
        project_path, _ = self.blob('project', 'Project.toml')
        manifest_path, _ = self.blob('manifest', 'Manifest-v1.10.toml')
        return {'schema': 'fpw-julia-computation-v1', 'computation_id': str(uuid4()),
            'title': 'Add one', 'entrypoint': {'artifact_id': self.ids['model'],
                'path': model_path, 'git_blob': model_blob, 'sha256': digest(self.raw['model'])},
            'environment': {'project_path': project_path,
                'project_sha256': digest(self.raw['project']),
                'manifest_path': manifest_path,
                'manifest_sha256': digest(self.raw['manifest']),
                'julia_compat': self.VERSION},
            'inputs': [{'name': 'source', 'artifact_id': self.ids['input'],
                'path': input_path, 'git_blob': input_blob, 'sha256': digest(self.raw['input']),
                'media_type': 'text/plain', 'required': True}],
            'parameters': [{'name': 'value', 'type': 'integer', 'required': True,
                'default': None, 'constraints': {'minimum': 0, 'maximum': 1000}}],
            'outputs': [{'name': 'result', 'kind': 'report',
                'media_type': 'text/plain', 'required': True, 'max_bytes': 1024}],
            'execution_policy': {'network': 'deny', 'timeout_ms': 1000,
                'cpu_threads': 1, 'max_processes': 8, 'memory_bytes': 512 * 1024 * 1024,
                'output_bytes': 4096, 'output_files': 4,
                'stdout_bytes': 4096, 'stderr_bytes': 4096}}

    def executor(self, **changes):
        values = dict(git=self.git, state_dir=self.state,
                      runtime_binding=self.binding, sandbox=DirectTestSandbox())
        values.update(changes); return JuliaExecutor(**values)

    def prepare(self, executor=None, value=42, operation_id=None):
        executor = executor or self.executor(); operation_id = operation_id or str(uuid4())
        return executor, executor.prepare(operation_id, self.node_id, self.user_id,
            self.project_id, self.computation, {'value': value})

    def test_descriptor_is_closed_bounded_and_pins_network_and_runtime(self):
        self.assertEqual(self.computation, validate_computation(self.computation))
        cases = []
        changed = json.loads(json.dumps(self.computation)); changed['unknown'] = True; cases.append(changed)
        changed = json.loads(json.dumps(self.computation)); changed['execution_policy']['network'] = 'allow'; cases.append(changed)
        changed = json.loads(json.dumps(self.computation)); changed['environment']['julia_compat'] = '1.10'; cases.append(changed)
        changed = json.loads(json.dumps(self.computation)); changed['outputs'][0]['max_bytes'] = 99999; cases.append(changed)
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises(ValidationError):
                validate_computation(candidate)

    def test_open_prepare_and_status_never_dispatch(self):
        executor, prepared = self.prepare()
        self.assertEqual('prepared', executor.status(
            prepared['operation_id'], self.node_id, self.user_id)['freshness'])
        self.assertFalse((self.state / 'output-materializations' /
                          prepared['operation_id']).exists())

    def test_prepare_execute_restart_status_and_exact_output(self):
        executor, prepared = self.prepare()
        self.assertEqual('prepared', prepared['state'])
        self.assertEqual('confidential', prepared['preview']['privacy'])
        with self.assertRaisesRegex(ValidationError, 'confirmation differs'):
            executor.execute(prepared['operation_id'], self.node_id, self.user_id, '0' * 64)
        completed = executor.execute(prepared['operation_id'], self.node_id, self.user_id,
                                     prepared['approval_digest'])
        self.assertEqual('succeeded', completed['state'])
        self.assertEqual(b'', base64.b64decode(completed['receipt']['stderr_b64']))
        content, item, _ = self.executor().output(prepared['operation_id'], self.node_id,
                                                  self.user_id, 'result')
        self.assertEqual(b'result=42\n', content); self.assertEqual(digest(content), item['sha256'])
        self.assertEqual('current', self.executor().status(
            prepared['operation_id'], self.node_id, self.user_id)['freshness'])

    def test_same_operation_is_idempotent_and_changed_request_is_rejected(self):
        operation_id = str(uuid4()); executor, first = self.prepare(operation_id=operation_id)
        second = executor.prepare(operation_id, self.node_id, self.user_id, self.project_id,
                                  self.computation, {'value': 42})
        self.assertEqual(first['approval_digest'], second['approval_digest'])
        with self.assertRaisesRegex(ValidationError, 'different Julia run'):
            executor.prepare(operation_id, self.node_id, self.user_id, self.project_id,
                             self.computation, {'value': 43})

    def test_crash_after_publication_reconciles_without_second_process(self):
        executor, prepared = self.prepare()
        def checkpoint(stage):
            if stage == 'materialization-published':
                raise RuntimeError('simulated crash')
        with self.assertRaisesRegex(RuntimeError, 'simulated crash'):
            executor.execute(prepared['operation_id'], self.node_id, self.user_id,
                             prepared['approval_digest'], checkpoint)
        self.assertEqual('dispatching', executor.store.get(
            prepared['operation_id'], self.node_id, self.user_id)['state'])
        recovered = self.executor().reconcile(prepared['operation_id'], self.node_id, self.user_id)
        self.assertEqual('succeeded', recovered['state'])
        self.assertTrue(recovered['receipt']['recovered'])

    def test_interrupted_dispatch_without_generation_becomes_unknown(self):
        executor, prepared = self.prepare()
        def checkpoint(stage):
            if stage == 'dispatching': raise RuntimeError('crash before process')
        with self.assertRaisesRegex(RuntimeError, 'crash before process'):
            executor.execute(prepared['operation_id'], self.node_id, self.user_id,
                             prepared['approval_digest'], checkpoint)
        recovered = self.executor().reconcile(prepared['operation_id'], self.node_id, self.user_id)
        self.assertEqual('unknown', recovered['state'])

    def test_known_process_failure_and_timeout_are_terminal(self):
        executor, failed = self.prepare(value=999)
        with self.assertRaisesRegex(RuntimeError, 'exit code 7'):
            executor.execute(failed['operation_id'], self.node_id, self.user_id,
                             failed['approval_digest'])
        failed_record = executor.store.get(failed['operation_id'], self.node_id, self.user_id)
        self.assertEqual(('failed', 7),
                         (failed_record['state'], failed_record['receipt']['exit_code']))
        slow = json.loads(json.dumps(self.computation)); slow['execution_policy']['timeout_ms'] = 50
        operation_id = str(uuid4()); executor = self.executor()
        prepared = executor.prepare(operation_id, self.node_id, self.user_id,
            self.project_id, slow, {'value': 998})
        with self.assertRaises(TimeoutError):
            executor.execute(operation_id, self.node_id, self.user_id,
                             prepared['approval_digest'])
        timeout_record = executor.store.get(operation_id, self.node_id, self.user_id)
        self.assertEqual('cancelled', timeout_record['state'])
        self.assertIsNotNone(timeout_record['receipt']['exit_code'])

    def test_manual_cancel_terminates_running_process_group(self):
        slow = json.loads(json.dumps(self.computation))
        slow['execution_policy']['timeout_ms'] = 10_000
        operation_id = str(uuid4()); executor = self.executor()
        prepared = executor.prepare(operation_id, self.node_id, self.user_id,
            self.project_id, slow, {'value': 998})
        errors = []
        def run():
            try:
                executor.execute(operation_id, self.node_id, self.user_id,
                                 prepared['approval_digest'])
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=run); worker.start()
        deadline = time.monotonic() + 2
        while executor.store.get(operation_id, self.node_id, self.user_id)['state'] != 'dispatching':
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        self.assertEqual('cancel_requested', executor.cancel(
            operation_id, self.node_id, self.user_id)['state'])
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(1, len(errors)); self.assertIsInstance(errors[0], InterruptedError)
        self.assertEqual('cancelled', executor.store.get(
            operation_id, self.node_id, self.user_id)['state'])

    def test_same_run_cannot_dispatch_concurrently(self):
        slow = json.loads(json.dumps(self.computation))
        slow['execution_policy']['timeout_ms'] = 10_000
        operation_id = str(uuid4()); executor = self.executor()
        prepared = executor.prepare(operation_id, self.node_id, self.user_id,
            self.project_id, slow, {'value': 998})
        worker = threading.Thread(target=lambda: self.assertRaises(
            InterruptedError, executor.execute, operation_id, self.node_id,
            self.user_id, prepared['approval_digest']))
        worker.start()
        deadline = time.monotonic() + 2
        while executor.store.get(operation_id, self.node_id, self.user_id)['state'] != 'dispatching':
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)
        with self.assertRaisesRegex(ValidationError, 'not prepared'):
            executor.execute(operation_id, self.node_id, self.user_id,
                             prepared['approval_digest'])
        executor.cancel(operation_id, self.node_id, self.user_id); worker.join(3)
        self.assertFalse(worker.is_alive())

    def test_unsafe_and_undeclared_outputs_fail_closed(self):
        for value, message in ((994, 'Unsafe Julia output'),
                               (996, 'Unsafe Julia output'),
                               (997, 'undeclared files')):
            with self.subTest(value=value):
                executor, prepared = self.prepare(value=value)
                with self.assertRaisesRegex(ValidationError, message):
                    executor.execute(prepared['operation_id'], self.node_id,
                                     self.user_id, prepared['approval_digest'])
                self.assertEqual('failed', executor.store.get(
                    prepared['operation_id'], self.node_id, self.user_id)['state'])
        executor, prepared = self.prepare(value=995)
        with self.assertRaises((RuntimeError, ValidationError)):
            executor.execute(prepared['operation_id'], self.node_id,
                             self.user_id, prepared['approval_digest'])
        self.assertEqual('failed', executor.store.get(
            prepared['operation_id'], self.node_id, self.user_id)['state'])

    def test_unowned_input_and_changed_runtime_are_rejected_before_dispatch(self):
        changed = json.loads(json.dumps(self.computation))
        changed['inputs'][0]['artifact_id'] = str(uuid4())
        with self.assertRaisesRegex(ValidationError, 'not owned'):
            self.executor().prepare(str(uuid4()), self.node_id, self.user_id,
                self.project_id, changed, {'value': 42})
        changed_binding = dict(self.binding, revision='changed')
        executor, prepared = self.prepare()
        executor.binding = changed_binding
        with self.assertRaisesRegex(ValidationError, 'binding changed'):
            executor.execute(prepared['operation_id'], self.node_id, self.user_id,
                             prepared['approval_digest'])
        self.assertEqual('prepared', executor.store.get(
            prepared['operation_id'], self.node_id, self.user_id)['state'])

        executor, prepared = self.prepare()
        library = self.runtime / 'lib' / 'changed.so'; library.write_bytes(b'changed')
        library.chmod(0o600)
        with self.assertRaisesRegex(ValidationError, 'distribution differs'):
            executor.execute(prepared['operation_id'], self.node_id, self.user_id,
                             prepared['approval_digest'])
        self.assertEqual('prepared', executor.store.get(
            prepared['operation_id'], self.node_id, self.user_id)['state'])

    def test_head_change_makes_result_stale_and_blocks_new_dispatch(self):
        executor, prepared = self.prepare(); executor.execute(
            prepared['operation_id'], self.node_id, self.user_id, prepared['approval_digest'])
        new_id = str(uuid4()); workspace = Projects(self.node).workspace(self.project_id)
        metadata = {'schema_version': 1, 'id': new_id, 'title': 'Later', 'kind': 'document',
            'created_at': '2026-10-26T13:00:00Z', 'author_id': self.author,
            'privacy': 'project', 'provenance': 'user', 'file': 'later.md'}
        workspace.transact(str(uuid4()), {'add': new_id}, lambda ws: ({
            f'artifacts/{new_id}/later.md': b'later\n',
            f'artifacts/{new_id}/metadata.json': (json.dumps(metadata, sort_keys=True) + '\n').encode()},
            'Test author', 'test@example.invalid', 'Add later document'),
            expected_head=self.git.head())
        self.assertEqual('stale', executor.status(prepared['operation_id'],
                                                  self.node_id, self.user_id)['freshness'])
        with self.assertRaisesRegex(ValidationError, 'Project changed'):
            executor.output(prepared['operation_id'], self.node_id, self.user_id, 'result')

    def test_runtime_change_makes_completed_result_stale(self):
        executor, prepared = self.prepare(); executor.execute(
            prepared['operation_id'], self.node_id, self.user_id,
            prepared['approval_digest'])
        library = self.runtime / 'lib' / 'later.so'; library.write_bytes(b'later')
        library.chmod(0o600)
        self.assertEqual('stale', executor.status(prepared['operation_id'],
                                                  self.node_id, self.user_id)['freshness'])
        with self.assertRaisesRegex(ValidationError, 'distribution differs'):
            executor.output(prepared['operation_id'], self.node_id, self.user_id, 'result')

    def test_explicit_publication_uses_workspace_and_v4_provenance(self):
        executor, prepared = self.prepare(); executor.execute(
            prepared['operation_id'], self.node_id, self.user_id, prepared['approval_digest'])
        workspace = Projects(self.node).workspace(self.project_id); head = self.git.head()
        artifact_id = str(uuid4())
        publication_id = str(uuid4())
        receipt = executor.publish(publication_id, prepared['operation_id'], self.node_id,
            self.user_id, 'result', artifact_id, 'Computed report', 'result.txt', workspace,
            head, self.author)
        self.assertNotEqual(head, receipt['commit_id'])
        files = self.git.snapshot(self.git.head()); entities = validate_snapshot(files)
        meta = entities[artifact_id]
        self.assertEqual((4, 'snapshot', 'snapshot'),
                         (meta['schema_version'], meta['kind'], meta['provenance']))
        self.assertEqual(prepared['operation_id'], meta['computation']['operation_id'])
        self.assertEqual('confidential', meta['privacy'])
        changed = json.loads(json.dumps(meta))
        changed['computation']['runtime']['version'] = '1.10'
        with self.assertRaisesRegex(ValidationError, 'runtime identity'):
            validate_metadata(changed, sidecar=True)
        self.assertEqual(receipt, executor.publish(publication_id, prepared['operation_id'],
            self.node_id, self.user_id, 'result', artifact_id, 'Computed report',
            'result.txt', workspace, head, self.author))

    def test_bubblewrap_command_denies_network_and_exposes_only_scoped_paths(self):
        command = BubblewrapSandbox('/usr/bin/bwrap').command(
            self.binding, self.project, self.project, self.state, self.state,
            self.state / 'request.json', self.computation)
        self.assertIn('--unshare-all', command)
        self.assertNotIn('--share-net', command)
        self.assertIn('--clearenv', command)
        self.assertIn('--sysimage=/runtime/lib/julia/sys.so', command)
        self.assertNotIn(str(Path.home()), command)

    @unittest.skipUnless(os.environ.get('M0_JULIA_SANDBOX_TEST') == '1',
                         'Requires usable Linux user namespaces and bubblewrap')
    def test_physical_bubblewrap_denies_network(self):
        executor, prepared = self.prepare(
            executor=self.executor(sandbox=BubblewrapSandbox()), value=993)
        completed = executor.execute(prepared['operation_id'], self.node_id, self.user_id,
                                     prepared['approval_digest'])
        self.assertEqual('succeeded', completed['state'])
        content, _, _ = executor.output(prepared['operation_id'], self.node_id,
                                        self.user_id, 'result')
        self.assertEqual(b'network=denied\n', content)

    def test_cli_prepare_status_and_verified_output_copy(self):
        binding = self.base / 'binding.json'; computation = self.base / 'computation.json'
        parameters = self.base / 'parameters.json'
        for path, value in ((binding, self.binding), (computation, self.computation),
                            (parameters, {'value': 42})):
            path.write_text(json.dumps(value), encoding='utf-8')
        operation_id = str(uuid4())
        common = ['--project', str(self.project), '--state', str(self.state),
                  '--binding', str(binding), '--node-id', self.node_id,
                  '--user-id', self.user_id]
        with patch('spikes.julia_cli._emit') as emit:
            self.assertEqual(0, julia_cli(common + ['prepare', '--operation-id', operation_id,
                '--project-id', self.project_id, '--computation', str(computation),
                '--parameters', str(parameters)]))
            self.assertEqual('prepared', emit.call_args.args[0]['state'])
        prepared = self.executor().store.get(operation_id, self.node_id, self.user_id)
        self.executor().execute(operation_id, self.node_id, self.user_id,
                                prepared['approval_digest'])
        destination = self.base / 'copied.txt'
        with patch('spikes.julia_cli._emit') as emit:
            self.assertEqual(0, julia_cli(common + ['status', '--operation-id', operation_id]))
            self.assertEqual('current', emit.call_args.args[0]['freshness'])
            self.assertEqual(0, julia_cli(common + ['output', '--operation-id', operation_id,
                '--name', 'result', '--destination', str(destination)]))
        self.assertEqual(b'result=42\n', destination.read_bytes())
        with patch('spikes.julia_cli._emit'):
            self.assertEqual(2, julia_cli(common + ['output', '--operation-id', operation_id,
                '--name', 'result', '--destination', str(destination)]))

    def test_runtime_binding_inventory_checks_archive_and_writes_once(self):
        archive = self.base / 'julia.tar.gz'; archive.write_bytes(b'archive')
        output = self.base / 'binding-output.json'; binding_id = str(uuid4())
        arguments = ['--runtime-root', str(self.runtime), '--archive', str(archive),
            '--archive-sha256', digest(b'archive'), '--depot', str(self.depot),
            '--version', self.VERSION, '--binding-id', binding_id,
            '--revision', 'verified-test', '--output', str(output)]
        self.assertEqual(0, runtime_binding_cli(arguments))
        binding = json.loads(output.read_bytes())
        self.assertEqual((binding_id, _distribution_digest(self.runtime)),
                         (binding['binding_id'], binding['distribution_sha256']))
        self.assertEqual(2, runtime_binding_cli(arguments))
        wrong = list(arguments); wrong[wrong.index('--archive-sha256') + 1] = '0' * 64
        wrong[wrong.index('--output') + 1] = str(self.base / 'wrong.json')
        self.assertEqual(2, runtime_binding_cli(wrong))

    def test_setup_onboards_supported_runtime_without_project_arguments(self):
        archive = self.base / 'julia.tar.gz'; archive.write_bytes(b'archive')
        setup_root = self.base / 'onboarding'
        supported = {(self.VERSION, 'linux-' + os.uname().machine.lower()):
                     digest(b'archive')}
        arguments = ['setup', '--runtime', str(self.runtime), '--archive', str(archive),
                     '--root', str(setup_root)]
        with patch.object(julia_runtime_binding, 'SUPPORTED_ARCHIVES', supported), \
                patch.object(julia_runtime_binding, 'probe_bubblewrap',
                             return_value='/usr/bin/bwrap'), \
                patch('spikes.julia_cli._emit') as emit:
            self.assertEqual(0, julia_cli(arguments))
            result = emit.call_args.args[0]
            self.assertEqual(('ready', False, 'not-verified-by-setup'),
                (result['status'], result['reused'], result['archive_signature']))
            self.assertEqual('prepare-versioned-computation', result['next']['action'])
            self.assertIn(str(setup_root / 'binding.json'), result['next']['command'])
            self.assertEqual(0o700, stat.S_IMODE((setup_root / 'state').stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE((setup_root / 'depot').stat().st_mode))
            self.assertEqual(0o600, stat.S_IMODE((setup_root / 'binding.json').stat().st_mode))
            binding = json.loads((setup_root / 'binding.json').read_bytes())
            self.assertEqual(_distribution_digest(self.runtime),
                             binding['distribution_sha256'])
            binding_path = setup_root / 'binding.json'
            pending = setup_root / '.binding.json.pending'
            binding_path.rename(pending)
            self.assertEqual(0, julia_cli(arguments))
            self.assertFalse(pending.exists())
            os.link(binding_path, pending)
            self.assertEqual(0, julia_cli(arguments))
            self.assertTrue(emit.call_args.args[0]['reused'])
            self.assertFalse(pending.exists())

    def test_setup_fails_before_writes_for_changed_archive(self):
        archive = self.base / 'julia.tar.gz'; archive.write_bytes(b'archive')
        setup_root = self.base / 'onboarding'
        supported = {(self.VERSION, 'linux-' + os.uname().machine.lower()): '0' * 64}
        arguments = ['setup', '--runtime', str(self.runtime), '--archive', str(archive),
                     '--root', str(setup_root)]
        with patch.object(julia_runtime_binding, 'SUPPORTED_ARCHIVES', supported), \
                patch.object(julia_runtime_binding, 'probe_bubblewrap') as probe, \
                patch('spikes.julia_cli._emit'):
            self.assertEqual(2, julia_cli(arguments))
        self.assertFalse(setup_root.exists())
        probe.assert_not_called()

    def test_setup_never_overwrites_changed_binding(self):
        archive = self.base / 'julia.tar.gz'; archive.write_bytes(b'archive')
        setup_root = self.base / 'onboarding'
        supported = {(self.VERSION, 'linux-' + os.uname().machine.lower()):
                     digest(b'archive')}
        arguments = ['setup', '--runtime', str(self.runtime), '--archive', str(archive),
                     '--root', str(setup_root)]
        with patch.object(julia_runtime_binding, 'SUPPORTED_ARCHIVES', supported), \
                patch.object(julia_runtime_binding, 'probe_bubblewrap',
                             return_value='/usr/bin/bwrap'), \
                patch('spikes.julia_cli._emit'):
            self.assertEqual(0, julia_cli(arguments))
            binding = setup_root / 'binding.json'; binding.write_text('{}')
            self.assertEqual(2, julia_cli(arguments))
            self.assertEqual('{}', binding.read_text())

    def test_setup_archive_extracts_and_binds_with_one_argument(self):
        archive = self.base / 'julia.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            bundle.add(self.runtime, arcname='julia-1.10.12')
        setup_root = self.base / 'onboarding'
        supported = {(self.VERSION, 'linux-' + os.uname().machine.lower()):
                     digest(archive.read_bytes())}
        arguments = ['setup-archive', '--archive', str(archive), '--root', str(setup_root)]
        with patch.object(julia_runtime_binding, 'SUPPORTED_ARCHIVES', supported), \
                patch.object(julia_runtime_binding, 'probe_bubblewrap',
                             return_value='/usr/bin/bwrap'), \
                patch('spikes.julia_cli._emit') as emit:
            self.assertEqual(0, julia_cli(arguments))
            result = emit.call_args.args[0]
            runtime = setup_root / 'runtime' / 'julia-1.10.12'
            self.assertEqual(runtime, Path(result['runtime']))
            self.assertEqual(archive, Path(result['archive']))
            self.assertTrue((runtime / 'bin' / 'julia').is_file())
            self.assertTrue((setup_root / 'binding.json').is_file())
            self.assertEqual(0, julia_cli(arguments))
            self.assertTrue(emit.call_args.args[0]['reused'])
            self.assertFalse((setup_root / '.runtime-extract.pending').exists())

    def test_setup_archive_rejects_escape_before_writing(self):
        archive = self.base / 'escape.tar.gz'
        payload = self.base / 'payload'; payload.write_bytes(b'escape')
        with tarfile.open(archive, 'w:gz') as bundle:
            bundle.add(payload, arcname='../escape')
        setup_root = self.base / 'onboarding'
        supported = {(self.VERSION, 'linux-' + os.uname().machine.lower()):
                     digest(archive.read_bytes())}
        arguments = ['setup-archive', '--archive', str(archive), '--root', str(setup_root)]
        with patch.object(julia_runtime_binding, 'SUPPORTED_ARCHIVES', supported), \
                patch.object(julia_runtime_binding, 'probe_bubblewrap',
                             return_value='/usr/bin/bwrap'), \
                patch('spikes.julia_cli._emit'):
            self.assertEqual(2, julia_cli(arguments))
        self.assertFalse(setup_root.exists())

    def test_setup_archive_reports_actual_and_supported_digests(self):
        archive = self.base / 'other-version.tar.gz'; archive.write_bytes(b'other version')
        actual = digest(archive.read_bytes())
        expected = 'a' * 64
        supported = {(self.VERSION, 'linux-' + os.uname().machine.lower()): expected}
        arguments = ['setup-archive', '--archive', str(archive),
                     '--root', str(self.base / 'onboarding')]
        with patch.object(julia_runtime_binding, 'SUPPORTED_ARCHIVES', supported), \
                patch('spikes.julia_cli._emit'), \
                patch('sys.stderr') as stderr:
            self.assertEqual(2, julia_cli(arguments))
        message = ''.join(call.args[0] for call in stderr.write.call_args_list if call.args)
        self.assertIn(actual, message)
        self.assertIn(f'Julia {self.VERSION} ({expected})', message)

    def test_run_wrapper_exposes_single_archive_setup(self):
        launcher = Path(__file__).resolve().parents[1] / 'run.sh'
        help_result = subprocess.run([str(launcher), 'help'], capture_output=True,
                                     text=True, timeout=15)
        self.assertEqual(0, help_result.returncode)
        self.assertIn('julia-setup ARCHIV.tar.gz', help_result.stdout)
        missing = subprocess.run([str(launcher), 'julia-setup'], capture_output=True,
                                 text=True, timeout=15)
        self.assertEqual(2, missing.returncode)


@unittest.skipUnless(os.environ.get('M0_JULIA_RUNTIME_ROOT'),
                     'Requires a verified official Julia 1.10.12 ARM64 runtime')
class JuliaRuntimeAcceptanceTests(unittest.TestCase):
    VERSION = '1.10.12'
    ARCHIVE_SHA256 = 'cc257b21967049642bfe17de1aff7dae17477eba4f423f98cb400c002080e5a2'

    def test_real_arm64_computation_network_isolation_and_publication(self):
        runtime = Path(os.environ['M0_JULIA_RUNTIME_ROOT']).resolve(strict=True)
        archive = Path(os.environ['M0_JULIA_ARCHIVE']).resolve(strict=True)
        self.assertEqual(self.ARCHIVE_SHA256, digest(archive.read_bytes()))
        executable = runtime / 'bin/julia'; sysimage = runtime / 'lib/julia/sys.so'
        self.assertEqual('julia version ' + self.VERSION, subprocess.run(
            [str(executable), '--version'], check=True, capture_output=True,
            text=True).stdout.strip())
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        base = Path(temporary.name); prep_depot = base / 'prep-depot'
        environment = base / 'environment'; environment.mkdir(); prep_depot.mkdir()
        project_raw = b'[deps]\n'; (environment / 'Project.toml').write_bytes(project_raw)
        subprocess.run([str(executable), '--startup-file=no', '--history-file=no',
            '--project=' + str(environment), '-e', 'using Pkg; Pkg.resolve()'], check=True,
            capture_output=True, env={'HOME': str(base), 'LC_ALL': 'C',
                'JULIA_DEPOT_PATH': str(prep_depot), 'JULIA_LOAD_PATH': '@:@stdlib',
                'JULIA_PKG_OFFLINE': 'true'})
        manifest_raw = (environment / 'Manifest.toml').read_bytes()
        entry_raw = b'''using SHA, Sockets
output = ARGS[findfirst(==("--fpw-output"), ARGS) + 1]
network = try
    socket = connect(ip"1.1.1.1", 53); close(socket); "open"
catch
    "denied"
end
raw = Vector{UInt8}(codeunits("real-julia=42;network=$(network)\\n"))
write(joinpath(output, "result.txt"), raw)
hash = bytes2hex(sha256(raw))
manifest = "{\\\"outputs\\\":[{\\\"kind\\\":\\\"report\\\",\\\"media_type\\\":\\\"text/plain\\\",\\\"name\\\":\\\"result\\\",\\\"path\\\":\\\"result.txt\\\",\\\"sha256\\\":\\\"$(hash)\\\",\\\"size\\\":$(length(raw))}],\\\"schema\\\":\\\"fpw-julia-result-v1\\\"}"
write(joinpath(output, "fpw-julia-result-v1.json"), manifest)
'''
        node = base / 'node.json'; project = base / 'project'; project_id = str(uuid4())
        author = str(uuid4()); ids = {name: str(uuid4()) for name in
            ('model', 'project', 'manifest', 'input')}
        values = {'model': ('model.jl', entry_raw),
                  'project': ('Project.toml', project_raw),
                  'manifest': ('Manifest.toml', manifest_raw),
                  'input': ('input.txt', b'41\n')}
        files = {}
        for name, artifact_id in ids.items():
            filename, raw = values[name]
            metadata = {'schema_version': 1, 'id': artifact_id, 'title': name.title(),
                'kind': 'source', 'created_at': '2026-10-26T12:00:00Z',
                'author_id': author, 'privacy': 'project', 'provenance': 'user',
                'file': filename}
            files[f'artifacts/{artifact_id}/{filename}'] = raw
            files[f'artifacts/{artifact_id}/metadata.json'] = (
                json.dumps(metadata, sort_keys=True) + '\n').encode()
        ProjectCreation(node).create('Real Julia project', str(project), str(uuid4()),
            initial_files=files, project_id=project_id,
            created_at='2026-10-26T12:00:00Z', request_digest='d' * 64,
            commit_message='Seed physical Julia acceptance')
        git = Git(project)
        def reference(name):
            filename, raw = values[name]; path = f'artifacts/{ids[name]}/{filename}'
            line = git.run('ls-tree', git.head(), '--', path).stdout.strip()
            return path, line.split()[2], digest(raw)
        model_path, model_blob, model_sha = reference('model')
        project_path, _, project_sha = reference('project')
        manifest_path, _, manifest_sha = reference('manifest')
        input_path, input_blob, input_sha = reference('input')
        computation = {'schema': 'fpw-julia-computation-v1',
            'computation_id': str(uuid4()), 'title': 'Physical ARM64 calculation',
            'entrypoint': {'artifact_id': ids['model'], 'path': model_path,
                'git_blob': model_blob, 'sha256': model_sha},
            'environment': {'project_path': project_path, 'project_sha256': project_sha,
                'manifest_path': manifest_path, 'manifest_sha256': manifest_sha,
                'julia_compat': self.VERSION},
            'inputs': [{'name': 'source', 'artifact_id': ids['input'],
                'path': input_path, 'git_blob': input_blob, 'sha256': input_sha,
                'media_type': 'text/plain', 'required': True}],
            'parameters': [], 'outputs': [{'name': 'result', 'kind': 'report',
                'media_type': 'text/plain', 'required': True, 'max_bytes': 1024}],
            'execution_policy': {'network': 'deny', 'timeout_ms': 30_000,
                'cpu_threads': 1, 'max_processes': 16,
                'memory_bytes': 2 * 1024 * 1024 * 1024, 'output_bytes': 4096,
                'output_files': 4, 'stdout_bytes': 4096, 'stderr_bytes': 4096}}
        state = base / 'julia-state'; state.mkdir(mode=0o700)
        depot = base / 'offline-depot'; depot.mkdir(mode=0o700)
        binding = {'schema': 'fpw-julia-runtime-v1', 'binding_id': str(uuid4()),
            'revision': 'official-1.10.12-linux-aarch64', 'executable': str(executable),
            'version': self.VERSION, 'platform': 'linux-' + os.uname().machine.lower(),
            'executable_sha256': digest(executable.read_bytes()),
            'distribution_sha256': _distribution_digest(runtime), 'sysimage': str(sysimage),
            'sysimage_sha256': digest(sysimage.read_bytes()), 'depot': str(depot),
            'depot_sha256': hashlib.sha256().hexdigest()}
        executor = JuliaExecutor(git=git, state_dir=state, runtime_binding=binding)
        node_id, user_id, operation_id = str(uuid4()), str(uuid4()), str(uuid4())
        prepared = executor.prepare(operation_id, node_id, user_id, project_id,
                                    computation, {})
        completed = executor.execute(operation_id, node_id, user_id,
                                     prepared['approval_digest'])
        self.assertEqual('succeeded', completed['state'])
        content, _, _ = executor.output(operation_id, node_id, user_id, 'result')
        self.assertEqual(b'real-julia=42;network=denied\n', content)
        workspace = Projects(node).workspace(project_id); head = git.head()
        artifact_id = str(uuid4())
        receipt = executor.publish(str(uuid4()), operation_id, node_id, user_id,
            'result', artifact_id, 'Physical Julia result', 'result.txt', workspace,
            head, author)
        self.assertNotEqual(head, receipt['commit_id'])
        self.assertEqual(content,
            git.snapshot(git.head())[f'artifacts/{artifact_id}/result.txt'])


if __name__ == '__main__':
    unittest.main()
