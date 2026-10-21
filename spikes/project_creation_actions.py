# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared preview/confirm adapter for recoverable project creation."""
import hashlib
import hmac
import json
from pathlib import Path
from uuid import uuid4

from spikes.administration import identifier
from spikes.project_creation import ProjectCreation, check


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


class ProjectCreationActions:
    """Bind the shared UI to one configured root or an exact native capability."""

    def __init__(self, node_path, *, projects_root=None, desktop_locations=False):
        self.creator = ProjectCreation(node_path)
        self.projects_root = Path(projects_root) if projects_root is not None else None
        self.desktop_locations = desktop_locations
        self._locations = {}
        self._previews = {}

    def register_location(self, root, operation_id):
        """Mint an in-process capability for one picker-selected target and operation."""
        check(self.desktop_locations, 'Vlastní umístění je dostupné pouze v desktopu.')
        identifier(operation_id)
        root = Path(root)
        check(root.is_absolute() and root == root.resolve(),
              'Vybrané umístění musí být absolutní a nesmí vést přes symlink.')
        token = str(uuid4())
        self._locations[token] = (operation_id, root)
        return {'location_capability': token, 'location_label': str(root),
                'operation_id': operation_id}

    def _target(self, operation_id, capability):
        identifier(operation_id)
        if capability is not None:
            check(self.desktop_locations and isinstance(capability, str),
                  'Neplatná capability umístění projektu.')
            selected = self._locations.get(capability)
            check(selected is not None and selected[0] == operation_id,
                  'Capability umístění nepatří této operaci nebo vypršela.')
            return selected[1]
        parent = self.projects_root or self.creator.default_projects_root()
        return parent / ('projekt-' + operation_id)

    def preview(self, request):
        check(isinstance(request, dict) and set(request) == {
            'title', 'operation_id', 'location_capability', 'remember_parent'},
            'Neplatný požadavek na náhled vytvoření projektu.')
        title, operation_id = request['title'], request['operation_id']
        capability, remember = request['location_capability'], request['remember_parent']
        check(isinstance(title, str) and bool(title.strip()) and len(title) <= 200
              and not any(ord(char) < 32 for char in title),
              'Zadejte název projektu (nejvýše 200 znaků).')
        check(isinstance(remember, bool), 'Neplatná volba výchozího umístění.')
        check(not remember or capability is not None,
              'Výchozí umístění lze změnit pouze systémovým výběrem adresáře.')
        target = self._target(operation_id, capability)
        intent = {'title': title, 'operation_id': operation_id,
                  'root': str(target), 'remember_parent': remember}
        plan = {'title': title, 'operation_id': operation_id,
                'location_capability': capability, 'remember_parent': remember,
                'target_label': str(target), 'preview_sha256': _digest(intent)}
        self._previews[operation_id] = dict(plan)
        return plan

    def confirm(self, plan):
        check(isinstance(plan, dict) and set(plan) == {
            'title', 'operation_id', 'location_capability', 'remember_parent',
            'target_label', 'preview_sha256'},
            'Neplatný plán vytvoření projektu.')
        issued = self._previews.get(plan.get('operation_id'))
        check(issued is not None and issued == plan,
              'Náhled vytvoření nebyl vydán tímto backendem nebo se změnil.')
        target = self._target(plan['operation_id'], plan['location_capability'])
        intent = {'title': plan['title'], 'operation_id': plan['operation_id'],
                  'root': str(target), 'remember_parent': plan['remember_parent']}
        expected = _digest(intent)
        check(isinstance(plan['preview_sha256'], str)
              and hmac.compare_digest(plan['preview_sha256'], expected)
              and plan['target_label'] == str(target),
              'Náhled vytvoření se změnil; připravte jej znovu.')
        if plan['location_capability'] is None:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return self.creator.create(plan['title'], target, plan['operation_id'],
                                   remember_parent=plan['remember_parent'])
