# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from spikes.desktop_transfer import FederationTransfer
except ModuleNotFoundError as exc:
    if exc.name != 'PySide6':
        raise
    FederationTransfer = None


class SignalStub:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class WorkerStub:
    instances = []

    def __init__(self, action, parent):
        self.action, self.parent = action, parent
        self.done = SignalStub()
        self.started = False
        self.instances.append(self)

    def isRunning(self):
        return self.started

    def start(self):
        self.started = True

    def wait(self):
        return True


@unittest.skipIf(FederationTransfer is None, 'PySide6 is unavailable')
class FederationTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.node = Path(self.temp.name) / 'node.json'
        self.projects = [{'id': '7b3fe12c-cf35-4ad8-9bed-719c7f004c55',
                          'title': 'Veřejný projekt', 'available': True}]
        self.targets = [{'node_id': '685839ef-540e-4e92-af57-d699d75e230d',
                         'container': 'workspace-m0', 'endpoint': 'https://192.0.2.2:8443',
                         'host': 'root@192.0.2.1', 'fingerprint': 'a' * 64}]
        self.configurations, self.progress, self.finished = [], [], []
        self.patches = [
            patch('spikes.desktop_transfer.Projects.catalog', return_value=self.projects),
            patch('spikes.desktop_transfer.DeploymentTargets.load', return_value=self.targets),
        ]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        self.transfer = FederationTransfer(
            self.node, configuration_callback=self.configurations.append,
            progress_callback=self.progress.append,
            finished_callback=lambda success, message: self.finished.append((success, message)))

    def request(self, **changes):
        value = {'token': self.transfer.token, 'project': 0, 'target': 0,
                 'ca': '/tmp/public-ca.pem', 'confirmed': True}
        value.update(changes)
        return value

    def test_open_exposes_only_bounded_selection_data(self):
        self.transfer.open()
        config = self.configurations[-1]
        self.assertEqual(config['projects'][0]['title'], 'Veřejný projekt')
        self.assertEqual(config['targets'][0]['container'], 'workspace-m0')
        self.assertNotIn('fingerprint', config['targets'][0])
        self.assertTrue(config['targets'][0]['ca'].endswith(
            '.node.json.network/685839ef-540e-4e92-af57-d699d75e230d-ca.pem'))
        with self.assertRaisesRegex(ValueError, 'aktuálnímu formuláři'):
            self.transfer._selection(self.request(confirmed=False))
        with self.assertRaisesRegex(ValueError, 'aktuálnímu formuláři'):
            self.transfer._selection(self.request(token='stale'))

    def test_start_reuses_pending_operation_and_locks_retry_selection(self):
        self.transfer.open(); WorkerStub.instances.clear()
        operation = '0617d963-8bfd-42f3-aee5-ac418711d2fc'
        with patch('spikes.desktop_transfer.pending_operation', return_value=operation), \
             patch('spikes.desktop_transfer.TransferWorker', WorkerStub):
            self.transfer.start(self.request())
        self.assertEqual(self.transfer.pending, operation)
        self.assertTrue(WorkerStub.instances[-1].started)
        self.assertIn('Git bundle', self.progress[-1])
        WorkerStub.instances[-1].started = False
        with self.assertRaisesRegex(ValueError, 'stejný projekt'):
            self.transfer.start(self.request(ca='/tmp/other-ca.pem'))


if __name__ == '__main__':
    unittest.main()
