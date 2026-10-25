# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
from pathlib import Path
from types import SimpleNamespace
import subprocess
import tempfile
import unittest

from spikes.node_telemetry import NodeTelemetry, OllamaRuntimePolicy


class NodeTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proc = self.root / 'proc'; (self.proc / 'net').mkdir(parents=True)
        (self.proc / 'meminfo').write_text(
            'MemTotal:       1000 kB\nMemAvailable:    250 kB\n')
        (self.proc / 'stat').write_text('cpu  100 0 50 850 0 0 0 0\n')
        (self.proc / 'net/dev').write_text(
            'Inter-| Receive | Transmit\n face |bytes packets |bytes packets\n'
            '  lo: 100 0 0 0 0 0 0 0 100 0 0 0 0 0 0 0\n'
            'eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n')
        self.times = iter((10.0, 12.0))

    @staticmethod
    def runner(args, **_kwargs):
        query = args[1]
        if query == '--query-gpu=utilization.gpu':
            output = '40\n20\n'
        elif query == '--query-gpu=memory.used,memory.total':
            output = '1024, 4096\n512, 2048\n'
        else:
            output = '40, 1024, 4096\n20, 512, 2048\n'
        return subprocess.CompletedProcess([], 0, output, '')

    def test_live_metrics_require_deltas_and_never_turn_unknown_into_zero(self):
        telemetry = NodeTelemetry(self.root, proc_root=self.proc,
                                  clock=lambda: next(self.times), runner=self.runner)
        first = telemetry.snapshot()
        self.assertEqual(first['metrics']['cpu']['reason'], 'awaiting-second-sample')
        self.assertEqual(first['metrics']['net']['reason'], 'awaiting-second-sample')
        self.assertEqual(first['metrics']['ram']['value'], 75.0)
        self.assertEqual(first['metrics']['gpu']['value'], 40.0)
        self.assertEqual(first['metrics']['vram']['value'], 25.0)
        (self.proc / 'stat').write_text('cpu  130 0 70 900 0 0 0 0\n')
        (self.proc / 'net/dev').write_text(
            'Inter-| Receive | Transmit\n face |bytes packets |bytes packets\n'
            'eth0: 3000 0 0 0 0 0 0 0 4000 0 0 0 0 0 0 0\n')
        second = telemetry.snapshot()
        self.assertEqual(second['metrics']['cpu']['status'], 'available')
        self.assertEqual(second['metrics']['cpu']['value'], 50.0)
        self.assertEqual(second['metrics']['net']['value'], 2000.0)

    def test_missing_nvidia_tool_is_explicitly_unknown(self):
        def missing(*_args, **_kwargs):
            raise FileNotFoundError('nvidia-smi')
        result = NodeTelemetry(self.root, proc_root=self.proc,
                               clock=lambda: 1.0, runner=missing).snapshot()
        self.assertEqual(result['metrics']['gpu'], {
            'status': 'unknown', 'reason': 'unavailable', 'source': 'nvidia-smi'})
        self.assertEqual(result['metrics']['vram']['status'], 'unknown')

    def test_activity_and_capacity_groups_read_only_their_metric_class(self):
        calls = []
        def runner(args, **kwargs):
            calls.append(args[1])
            return self.runner(args, **kwargs)
        telemetry = NodeTelemetry(self.root, proc_root=self.proc,
                                  clock=lambda: 1.0, runner=runner)
        activity = telemetry.snapshot('activity')
        capacity = telemetry.snapshot('capacity')
        self.assertEqual(set(activity['metrics']), {'cpu', 'gpu', 'net'})
        self.assertEqual(set(capacity['metrics']), {'ram', 'vram', 'disk'})
        self.assertEqual(calls, ['--query-gpu=utilization.gpu',
                                 '--query-gpu=memory.used,memory.total'])


class OllamaRuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.root.chmod(0o700)
        self.binding = SimpleNamespace(binding_id='binding-one', revision='revision-one')

    def test_policy_is_atomic_restart_safe_and_scoped_to_binding_revision(self):
        store = OllamaRuntimePolicy(self.root)
        self.assertEqual(store.load(self.binding)['expected_processor'], 'unspecified')
        saved = store.save(self.binding, 'gpu')
        self.assertEqual((saved['revision'], saved['expected_processor']), (1, 'gpu'))
        self.assertEqual(OllamaRuntimePolicy(self.root).load(self.binding), saved)
        run_model = SimpleNamespace(binding_id='binding-one',
            revision='revision-one.run-model-0123456789abcdef')
        self.assertEqual(OllamaRuntimePolicy(self.root).load(run_model), saved)
        changed = SimpleNamespace(binding_id='binding-one', revision='revision-two')
        self.assertEqual(OllamaRuntimePolicy(self.root).load(changed), {
            'schema_version': 1, 'revision': 0, 'binding_id': 'binding-one',
            'binding_revision': 'revision-two', 'expected_processor': 'unspecified'})

    def test_unsafe_policy_file_is_rejected(self):
        store = OllamaRuntimePolicy(self.root); store.save(self.binding, 'cpu')
        store.path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'Unsafe'):
            store.load(self.binding)
