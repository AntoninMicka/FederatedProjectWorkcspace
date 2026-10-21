# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from spikes.desktop_deployment import FederationDeployment
except ModuleNotFoundError as exc:
    if exc.name != 'PySide6':
        raise
    FederationDeployment = None


class SignalStub:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class WorkerStub:
    instances = []

    def __init__(self, node, values, parent):
        self.node, self.values, self.parent = node, values, parent
        self.progress, self.done = SignalStub(), SignalStub()
        self.started = False
        self.instances.append(self)

    def isRunning(self):
        return self.started

    def start(self):
        self.started = True

    def wait(self):
        self.started = False
        return True


@unittest.skipIf(FederationDeployment is None, 'PySide6 is unavailable')
class FederationDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.node = Path(self.temp.name) / 'node.json'
        self.targets = [{'node_id': '685839ef-540e-4e92-af57-d699d75e230d',
                         'container': 'workspace-m0', 'endpoint': 'https://192.0.2.2:8443',
                         'host': 'root@192.0.2.1', 'fingerprint': 'a' * 64,
                         'lan': '192.0.2.0/24',
                         'desktop_endpoint': 'https://192.0.2.10:8443'}]
        self.configurations, self.progress, self.finished = [], [], []
        self.patches = [
            patch('spikes.desktop_deployment.DeploymentTargets.load', return_value=self.targets),
            patch('spikes.desktop_deployment.address_candidates', return_value=[
                'https://192.168.100.2:8443']),
        ]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        self.controller = FederationDeployment(
            self.node, endpoint_callback=lambda: 'https://192.168.100.3:8443',
            configuration_callback=self.configurations.append,
            progress_callback=self.progress.append,
            finished_callback=lambda success, message: self.finished.append((success, message)))

    def request(self, **changes):
        value = {'token': self.controller.token, 'target': 0, 'host': 'root@192.0.2.1',
                 'container': 'workspace-m0', 'lan': '192.0.2.0/24',
                 'endpoint': 'https://192.168.100.3:8443', 'mode': 'update',
                 'confirmed': True}
        value.update(changes)
        return value

    def test_open_exposes_bounded_targets_modes_and_current_endpoint(self):
        self.controller.open(); value = self.configurations[-1]
        self.assertEqual('https://192.168.100.3:8443', value['endpoint'])
        self.assertEqual(5, len(value['modes']))
        self.assertEqual('workspace-m0', value['targets'][0]['container'])
        self.assertNotIn('node_id', value['targets'][0])
        self.assertNotIn('fingerprint', value['targets'][0])

    def test_start_requires_current_token_confirmation_and_unchanged_targets(self):
        self.controller.open()
        for changes in ({'token': 'stale'}, {'confirmed': False}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'aktuálnímu formuláři'):
                self.controller.start(self.request(**changes))
        with patch('spikes.desktop_deployment.DeploymentTargets.load', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'se změnil'):
                self.controller.start(self.request())

    def test_selected_target_cannot_silently_change_identity_coordinates(self):
        self.controller.open()
        with self.assertRaisesRegex(ValueError, 'ruční zadání'):
            self.controller.start(self.request(host='root@192.0.2.99'))

    def test_install_requires_endpoint_and_address_requires_remembered_target(self):
        self.controller.open()
        with self.assertRaisesRegex(ValueError, 'HTTPS endpoint'):
            self.controller.start(self.request(mode='install', endpoint=''))
        with self.assertRaisesRegex(ValueError, 'zapamatovaný'):
            self.controller.start(self.request(mode='address', target=-1))

    def test_confirmed_request_starts_only_native_worker(self):
        self.controller.open(); WorkerStub.instances.clear()
        with patch('spikes.desktop_deployment.DeploymentWorker', WorkerStub):
            self.controller.start(self.request())
        worker = WorkerStub.instances[-1]
        self.assertEqual(('root@192.0.2.1', 'workspace-m0', '192.0.2.0/24',
                          'https://192.168.100.3:8443', 'update'), worker.values)
        self.assertTrue(worker.started)
        self.assertIn('SSH', self.progress[-1])


if __name__ == '__main__':
    unittest.main()
