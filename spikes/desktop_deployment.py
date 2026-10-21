# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native LXC deployment controller behind the shared federation page."""
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, Signal

from spikes.deployment_targets import DeploymentTargets, address_candidates
from spikes.lxc_deployment import deploy


MODES = (
    ('První instalace a propojení', 'install'),
    ('Aktualizovat pouze aplikaci', 'update'),
    ('Obnovit přerušené nasazení', 'recover'),
    ('Resetovat stav — bez rollbacku', 'reset'),
    ('Aktualizovat adresu kontejneru', 'address'),
)


class DeploymentWorker(QThread):
    progress = Signal(str)
    done = Signal(bool, str)

    def __init__(self, node, values, parent):
        super().__init__(parent)
        self.node, self.values = node, values

    def run(self):
        try:
            store = DeploymentTargets(self.node)
            remembered = next((target for target in store.load()
                               if (target['host'], target['container']) == self.values[:2]), None)
            result = deploy(self.node, *self.values, self.progress.emit, remembered=remembered)
            warning = ''
            if result:
                try:
                    store.remember(result)
                    self.progress.emit('Cílový uzel byl zapamatován lokálně; credentials se neukládají.')
                except Exception as exc:
                    warning = 'Vzdálená operace proběhla, ale uložení lokálních preferencí selhalo: ' + str(exc)
                    self.progress.emit(warning)
            self.done.emit(True, warning or 'Operace dokončena.')
        except Exception as exc:
            self.done.emit(False, str(exc))


class FederationDeployment(QObject):
    """Validate a one-shot web form and retain all SSH work in native code."""

    def __init__(self, node, *, endpoint_callback=None, configuration_callback=None,
                 progress_callback=None, finished_callback=None, parent=None):
        super().__init__(parent)
        self.node = node
        self.endpoint_callback = endpoint_callback or (lambda: '')
        self.configuration_callback = configuration_callback or (lambda _configuration: None)
        self.progress_callback = progress_callback or (lambda _message: None)
        self.finished_callback = finished_callback or (lambda _success, _message: None)
        self.worker = None
        self.token = None
        self.targets = []

    def open(self):
        if self.worker and self.worker.isRunning():
            self.progress_callback('Nasazení právě probíhá; stránku nelze opustit.')
            return
        self.targets = DeploymentTargets(self.node).load()
        self.token = str(uuid4())
        endpoints = []
        active = self.endpoint_callback()
        if active:
            endpoints.append(active)
        for candidate in address_candidates():
            if candidate not in endpoints:
                endpoints.append(candidate)
        self.configuration_callback({
            'token': self.token,
            'endpoint': active,
            'endpoints': endpoints,
            'modes': [{'label': label, 'value': value} for label, value in MODES],
            'targets': [{
                'index': index,
                'label': target['container'] + ' — ' + target['host'] + ' — ' + target['endpoint'],
                'host': target['host'], 'container': target['container'], 'lan': target['lan'],
                'desktop_endpoint': target['desktop_endpoint'], 'endpoint': target['endpoint'],
            } for index, target in enumerate(self.targets)],
        })

    @staticmethod
    def _text(value, maximum):
        return isinstance(value, str) and 0 < len(value) <= maximum and '\0' not in value

    def start(self, request):
        if self.worker and self.worker.isRunning():
            return
        fields = {'token', 'target', 'host', 'container', 'lan', 'endpoint', 'mode', 'confirmed'}
        if (not isinstance(request, dict) or set(request) != fields
                or request.get('token') != self.token or request.get('confirmed') is not True
                or not isinstance(request.get('target'), int)
                or isinstance(request.get('target'), bool)
                or not -1 <= request['target'] < len(self.targets)
                or not self._text(request.get('host'), 255)
                or not self._text(request.get('container'), 63)
                or not self._text(request.get('lan'), 64)
                or not isinstance(request.get('endpoint'), str)
                or len(request['endpoint']) > 4096 or '\0' in request['endpoint']
                or request.get('mode') not in {value for _label, value in MODES}):
            raise ValueError('Výběr nasazení už neodpovídá aktuálnímu formuláři.')
        current = DeploymentTargets(self.node).load()
        if current != self.targets:
            raise ValueError('Seznam cílových uzlů se změnil; načtěte stránku znovu.')
        if request['target'] >= 0:
            selected = self.targets[request['target']]
            if (request['host'], request['container']) != (selected['host'], selected['container']):
                raise ValueError('Zapamatovaný uzel se ve formuláři změnil; zvolte ruční zadání nebo jej načtěte znovu.')
        if request['mode'] == 'install' and not request['endpoint']:
            raise ValueError('První instalace vyžaduje skutečný HTTPS endpoint desktopového backendu.')
        if request['mode'] == 'address' and request['target'] < 0:
            raise ValueError('Aktualizace adresy vyžaduje zapamatovaný cílový uzel.')
        values = (request['host'], request['container'], request['lan'],
                  request['endpoint'], request['mode'])
        self.progress_callback('Navazuji jedno potvrzené SSH spojení a spouštím vzdálenou operaci…')
        self.worker = DeploymentWorker(self.node, values, self)
        self.worker.progress.connect(self.progress_callback)
        self.worker.done.connect(self._finished)
        self.worker.start()

    def _finished(self, success, message):
        if success:
            if self.worker and self.worker.isRunning():
                self.worker.wait()
            self.open()
        self.finished_callback(success, message)

    def wait(self):
        if self.worker:
            self.worker.wait()
