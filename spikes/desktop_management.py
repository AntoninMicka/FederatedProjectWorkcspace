# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native single-OS-user administration, using the existing process token."""
import sqlite3
import os
import subprocess

from spikes.desktop_ui import ASSETS as BASE_ASSETS, DesktopHandler, HTML, CSS, JS
from spikes.administration import AccessDenied
from spikes.web_administration import ADMIN_HTML, ADMIN_CSS, ADMIN_JS
from spikes.project_creation import ProjectCreation

ASSETS = {**BASE_ASSETS, '/': ('text/html; charset=utf-8', HTML.replace(
              'id="backend-metrics" hidden', 'id="backend-metrics"').replace(
              'id="backend-metrics-indicator" hidden', 'id="backend-metrics-indicator"').replace(
              '<div id="administration-host"></div>', ADMIN_HTML).replace(
              'id="settings-users-tab" type="button"', 'id="settings-users-tab" type="button" data-desktop="true"').replace(
              'id="settings-federation-tab" type="button"', 'id="settings-federation-tab" type="button" data-desktop="true"').replace(
              ' tabindex="-1" hidden>Uživatelé', ' tabindex="-1">Uživatelé').replace(
              ' tabindex="-1" hidden>Federace', ' tabindex="-1">Federace')),
          '/app.css': ('text/css; charset=utf-8', CSS + ADMIN_CSS),
          '/app.js': ('text/javascript; charset=utf-8', JS + ADMIN_JS)}


class DesktopManagementHandler(DesktopHandler):
    assets = ASSETS
    post_paths = DesktopHandler.post_paths | {'/v1/administration',
        '/v1/backend-metrics/status', '/v1/backend-metrics/configure',
        '/v1/backend-metrics/refresh'}

    def dispatch(self, request):
        if self.path.startswith('/v1/backend-metrics/'):
            try:
                if self.path == '/v1/backend-metrics/status' and request == {}:
                    return self.reply(200, self.server.chat_service.account_metrics_status())
                if self.path == '/v1/backend-metrics/configure' and isinstance(request, dict):
                    return self.reply(200, self.server.chat_service.configure_account_metrics(request))
                if self.path == '/v1/backend-metrics/refresh' and isinstance(request, dict):
                    return self.reply(200, self.server.chat_service.refresh_account_metrics(request))
                return self.send_error(400)
            except (ValueError, OSError, sqlite3.Error):
                return self.reply(422, {'error': 'Účetní přehled nelze načíst nebo uložit. '
                                       'Ověřte administrátorský klíč a lokální stav.'})
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
