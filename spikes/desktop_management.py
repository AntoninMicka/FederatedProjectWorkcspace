# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native single-OS-user administration, using the existing process token."""
import sqlite3
import os
import subprocess

from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.administration import AccessDenied
from spikes.web_administration import ADMIN_HTML, ADMIN_CSS, ADMIN_JS
from spikes.project_creation import ProjectCreation

ASSETS = {'/': ('text/html; charset=utf-8', HTML.replace(
              '<div id="administration-host"></div>', ADMIN_HTML).replace(
              'id="settings-users-tab" type="button"', 'id="settings-users-tab" type="button" data-desktop="true"').replace(
              'id="settings-federation-tab" type="button"', 'id="settings-federation-tab" type="button" data-desktop="true"').replace(
              ' tabindex="-1" hidden>Uživatelé', ' tabindex="-1">Uživatelé').replace(
              ' tabindex="-1" hidden>Federace', ' tabindex="-1">Federace')),
          '/app.css': ('text/css; charset=utf-8', CSS + ADMIN_CSS),
          '/app.js': ('text/javascript; charset=utf-8', JS + ADMIN_JS)}


class DesktopManagementHandler(DesktopHandler):
    assets = ASSETS
    post_paths = DesktopHandler.post_paths | {'/v1/administration'}

    def dispatch(self, request):
        if self.path != '/v1/administration':
            return super().dispatch(request)
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        try:
            administration = self.server.administration
            if not os.path.lexists(administration.node) and administration.repo.exists():
                return self.reply(422, {'error': 'Chybí původní node.json. Obnovte jej ze zálohy; identitu existující federace nelze nahradit.'})
            ProjectCreation(administration.node).initialize_node()
            result = self.server.administration.request(actor, request)
            result['projects'] = self.server.projects.catalog()
            return self.reply(200, result)
        except AccessDenied:
            return self.reply(403, {'error': 'Operace není povolena nebo se změnil registr. Načtěte správu znovu.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            return self.reply(422, {'error': 'Správa není dostupná. Ověřte konfiguraci uzlu a uložené údaje.'})
