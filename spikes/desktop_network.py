# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native network controller behind the shared federation settings page."""
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal

from spikes.administration import Administration
from spikes.deployment_targets import DeploymentTargets, address_candidates
from spikes.federation_probe import check_peer
from spikes.lxc_setup import ACTOR


class NetworkWorker(QThread):
    done = Signal(bool, str)

    def __init__(self, action, parent):
        super().__init__(parent)
        self.action = action

    def run(self):
        try:
            self.done.emit(True, self.action())
        except Exception as exc:
            self.done.emit(False, 'Operace selhala: ' + str(exc))


class FederationNetwork(QObject):
    """Expose bounded configuration while keeping TLS, SSH and probes native."""

    def __init__(self, backend, *, configuration_callback=None, progress_callback=None,
                 finished_callback=None, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.configuration_callback = configuration_callback or (lambda _configuration: None)
        self.progress_callback = progress_callback or (lambda _message: None)
        self.finished_callback = finished_callback or (lambda _success, _message: None)
        self.worker = None
        self.token = None
        self.targets = []
        self.current_action = None

    def open(self):
        if self.worker and self.worker.isRunning():
            self.progress_callback('Síťová operace právě probíhá; stránku nelze opustit.')
            return
        self.targets = DeploymentTargets(self.backend.node).load()
        self.token = str(uuid4())
        candidates = []
        for endpoint in address_candidates():
            hostname = urlsplit(endpoint).hostname
            if hostname and hostname not in candidates:
                candidates.append(hostname)
        config = self.backend.config or {
            'bind': candidates[0] if candidates else '', 'port': 8443,
            'lan': '192.168.100.0/24', 'cert': '', 'key': '', 'ca': '', 'enabled': False,
        }
        root = (Path(self.backend.node).absolute().parent /
                ('.' + Path(self.backend.node).name + '.network'))
        targets = []
        for index, target in enumerate(self.targets):
            ca = root / (target['node_id'] + '-ca.pem')
            targets.append({
                'index': index,
                'label': target['container'] + ' — ' + target['endpoint'],
                'container': target['container'],
                'host': target['host'],
                'endpoint': target['endpoint'],
                'ca': str(ca) if ca.is_file() else '',
            })
        self.configuration_callback({
            'token': self.token,
            'config': dict(config),
            'generate': not bool(self.backend.config),
            'endpoint': self.backend.endpoint,
            'addresses': candidates,
            'targets': targets,
        })

    def _base_request(self, request, fields):
        if (not isinstance(request, dict) or set(request) != fields
                or request.get('token') != self.token):
            raise ValueError('Síťová operace už neodpovídá aktuálnímu formuláři.')

    @staticmethod
    def _bounded_text(value, *, required=False):
        return (isinstance(value, str) and '\0' not in value and len(value) <= 4096
                and (not required or bool(value)))

    def _target(self, request, *, bilateral=False):
        fields = {'token', 'action', 'target', 'ca'}
        if bilateral:
            fields.add('confirmed')
        self._base_request(request, fields)
        if (request['action'] != ('check-bilateral' if bilateral else 'check')
                or not isinstance(request.get('target'), int)
                or isinstance(request.get('target'), bool)
                or not 0 <= request['target'] < len(self.targets)
                or not self._bounded_text(request.get('ca'), required=True)
                or bilateral and request.get('confirmed') is not True):
            raise ValueError('Výběr síťové diagnostiky už neodpovídá aktuálnímu formuláři.')
        current = DeploymentTargets(self.backend.node).load()
        if current != self.targets:
            raise ValueError('Seznam federačních uzlů se změnil; načtěte stránku znovu.')
        return self.targets[request['target']]

    def run(self, request):
        if self.worker and self.worker.isRunning():
            return
        if not isinstance(request, dict):
            raise ValueError('Síťová operace už neodpovídá aktuálnímu formuláři.')
        action = request.get('action')
        if action == 'configure':
            self._configure(request)
        elif action == 'check':
            target = self._target(request)
            self._start('check', 'Ověřuji HTTPS a připnutou identitu protějšího uzlu…',
                        lambda: self._check(target, request['ca']))
        elif action == 'check-bilateral':
            target = self._target(request, bilateral=True)
            if not self.backend.endpoint:
                raise ValueError('Nejdříve zapněte desktopový HTTPS backend.')
            from spikes.peer_diagnostics import check_both
            self._start('check-bilateral', 'Ověřuji oba směry přes jedno SSH spojení…',
                        lambda: check_both(self.backend, target, request['ca']))
        else:
            raise ValueError('Neznámá síťová operace.')

    def _configure(self, request):
        self._base_request(request, {'token', 'action', 'config', 'generate'})
        config = request.get('config')
        if (request.get('action') != 'configure' or type(request.get('generate')) is not bool
                or not isinstance(config, dict)
                or set(config) != {'bind', 'port', 'lan', 'cert', 'key', 'ca', 'enabled'}
                or type(config.get('enabled')) is not bool
                or type(config.get('port')) is not int
                or any(not self._bounded_text(config.get(key), required=key in {'bind', 'lan'})
                       for key in ('bind', 'lan', 'cert', 'key', 'ca'))):
            raise ValueError('Nastavení backendu neodpovídá aktuálnímu formuláři.')
        self.backend.validate(config)
        generate = request['generate'] and config['enabled']

        def configure():
            candidate = (self.backend.generate(config['bind'], config['port'], config['lan'])
                         if generate else config)
            self.backend.configure(candidate)
            return ('Backend: ' + (self.backend.endpoint or 'vypnutý') + '\nVeřejná CA: ' +
                    candidate['ca'] + '\nPři změně adresy upravte také evidenci '
                    'desktopového peeru na LXC. Test neprovádí synchronizaci.')

        self._start('configure', 'Ukládám lokální konfiguraci síťového backendu…', configure)

    def _check(self, target, ca):
        view = Administration(self.backend.node, deployment='desktop').request(
            ACTOR, {'action': 'list'})
        peer = next((item for item in view['peers'] if item['id'] == target['node_id']), None)
        if (not peer or peer['trust'] != 'approved'
                or peer['fingerprint'] != target['fingerprint']):
            raise ValueError('Uzel není schválený s původním pinem. Nejdříve vyřešte jeho důvěru ve správě.')
        return check_peer(peer['endpoint'], ca, peer['id'], peer['fingerprint'])

    def _start(self, action, message, operation):
        self.current_action = action
        self.progress_callback(message)
        self.worker = NetworkWorker(operation, self)
        self.worker.done.connect(self._finished)
        self.worker.start()

    def _finished(self, success, message):
        action = self.current_action
        self.current_action = None
        if success and action == 'configure':
            if self.worker and self.worker.isRunning():
                self.worker.wait()
            self.open()
        self.finished_callback(success, message)

    def wait(self):
        if self.worker:
            self.worker.wait()
