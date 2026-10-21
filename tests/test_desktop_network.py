# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

try:
    from spikes.desktop_network import FederationNetwork
except ModuleNotFoundError as exc:
    if exc.name != 'PySide6':
        raise
    FederationNetwork = None


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

    def complete(self):
        try:
            success, message = True, self.action()
        except Exception as exc:
            success, message = False, 'Operace selhala: ' + str(exc)
        self.started = False
        self.done.callback(success, message)


class BackendStub:
    def __init__(self, node):
        self.node = node
        self.config = None
        self.endpoint = ''
        self.generated = []
        self.configured = []

    def validate(self, config):
        if config['port'] < 1024:
            raise ValueError('bad port')

    def generate(self, bind, port, lan):
        self.generated.append((bind, port, lan))
        return dict(bind=bind, port=port, lan=lan, cert='/new/tls.crt', key='/new/tls.key',
                    ca='/new/ca.pem', enabled=True)

    def configure(self, config):
        self.config = dict(config)
        self.configured.append(dict(config))
        self.endpoint = f"https://{config['bind']}:{config['port']}" if config['enabled'] else ''


@unittest.skipIf(FederationNetwork is None, 'PySide6 is unavailable')
class FederationNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.node = Path(self.temp.name) / 'node.json'
        self.backend = BackendStub(self.node)
        self.targets = [{'node_id': '685839ef-540e-4e92-af57-d699d75e230d',
                         'container': 'workspace-m0', 'endpoint': 'https://192.0.2.2:8443',
                         'host': 'root@192.0.2.1', 'fingerprint': 'a' * 64,
                         'lan': '192.0.2.0/24', 'desktop_endpoint': ''}]
        self.configurations, self.progress, self.finished = [], [], []
        self.patches = [
            patch('spikes.desktop_network.DeploymentTargets.load', return_value=self.targets),
            patch('spikes.desktop_network.address_candidates', return_value=[
                'https://192.168.100.2:8443']),
        ]
        for item in self.patches:
            item.start(); self.addCleanup(item.stop)
        self.controller = FederationNetwork(
            self.backend, configuration_callback=self.configurations.append,
            progress_callback=self.progress.append,
            finished_callback=lambda success, message: self.finished.append((success, message)))

    def configure_request(self, **changes):
        config = dict(bind='192.168.100.2', port=8443, lan='192.168.100.0/24',
                      cert='', key='', ca='', enabled=True)
        config.update(changes.pop('config', {}))
        request = {'token': self.controller.token, 'action': 'configure',
                   'config': config, 'generate': True}
        request.update(changes)
        return request

    def diagnostic_request(self, action='check', **changes):
        request = {'token': self.controller.token, 'action': action,
                   'target': 0, 'ca': '/tmp/public-ca.pem'}
        if action == 'check-bilateral':
            request['confirmed'] = True
        request.update(changes)
        return request

    def test_open_exposes_bounded_configuration_without_peer_pin(self):
        self.controller.open()
        value = self.configurations[-1]
        self.assertEqual(['192.168.100.2'], value['addresses'])
        self.assertEqual(8443, value['config']['port'])
        self.assertEqual('workspace-m0', value['targets'][0]['container'])
        self.assertNotIn('fingerprint', value['targets'][0])
        with self.assertRaisesRegex(ValueError, 'aktuálnímu formuláři'):
            self.controller.run(self.configure_request(token='stale'))

    def test_configure_generates_tls_and_refreshes_configuration(self):
        self.controller.open(); WorkerStub.instances.clear()
        with patch('spikes.desktop_network.NetworkWorker', WorkerStub):
            self.controller.run(self.configure_request())
            WorkerStub.instances[-1].complete()
        self.assertEqual([('192.168.100.2', 8443, '192.168.100.0/24')], self.backend.generated)
        self.assertEqual('/new/ca.pem', self.backend.configured[-1]['ca'])
        self.assertTrue(self.finished[-1][0])
        self.assertEqual('/new/ca.pem', self.configurations[-1]['config']['ca'])

    def test_diagnostics_reject_stale_targets_and_require_bilateral_confirmation(self):
        self.controller.open()
        with self.assertRaisesRegex(ValueError, 'diagnostiky'):
            self.controller.run(self.diagnostic_request('check-bilateral', confirmed=False))
        with patch('spikes.desktop_network.DeploymentTargets.load', return_value=[]):
            with self.assertRaisesRegex(ValueError, 'se změnil'):
                self.controller.run(self.diagnostic_request())

    def test_check_revalidates_approved_peer_before_probe(self):
        self.controller.open(); WorkerStub.instances.clear()
        administration = Mock()
        administration.request.return_value = {'peers': [{
            'id': self.targets[0]['node_id'], 'trust': 'approved',
            'fingerprint': self.targets[0]['fingerprint'], 'endpoint': self.targets[0]['endpoint']}]}
        with patch('spikes.desktop_network.NetworkWorker', WorkerStub), \
             patch('spikes.desktop_network.Administration', return_value=administration), \
             patch('spikes.desktop_network.check_peer', return_value='Spojení ověřeno') as probe:
            self.controller.run(self.diagnostic_request())
            WorkerStub.instances[-1].complete()
        probe.assert_called_once()
        self.assertEqual((True, 'Spojení ověřeno'), self.finished[-1])

    def test_bilateral_check_requires_active_backend(self):
        self.controller.open()
        with self.assertRaisesRegex(ValueError, 'zapněte'):
            self.controller.run(self.diagnostic_request('check-bilateral'))


if __name__ == '__main__':
    unittest.main()
