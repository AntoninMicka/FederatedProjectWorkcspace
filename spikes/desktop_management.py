# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Native single-OS-user administration, using the existing process token."""
import sqlite3
import subprocess

from spikes.desktop_ui import DesktopHandler, HTML, CSS, JS
from spikes.administration import AccessDenied
from spikes.web_administration import ADMIN_HTML, ADMIN_CSS, ADMIN_JS

ASSETS = {'/': ('text/html; charset=utf-8', HTML.replace('<body>', '<body class="desktop-management">' + ADMIN_HTML)),
          '/app.css': ('text/css; charset=utf-8', CSS + ADMIN_CSS + '\nbody.desktop-management #administration-open{display:block}'),
          '/app.js': ('text/javascript; charset=utf-8', JS + ADMIN_JS)}


class DesktopManagementHandler(DesktopHandler):
    assets = ASSETS
    post_paths = DesktopHandler.post_paths | {'/v1/administration'}

    def dispatch(self, request):
        if self.path != '/v1/administration':
            return super().dispatch(request)
        actor = {'id': None, 'node_role': 'federation-admin', 'memberships': {}}
        try:
            result = self.server.administration.request(actor, request)
            result['projects'] = self.server.projects.catalog()
            return self.reply(200, result)
        except AccessDenied:
            return self.reply(403, {'error': 'Operace není povolena nebo se změnil registr. Načtěte správu znovu.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            return self.reply(422, {'error': 'Správa není dostupná. Ověřte konfiguraci uzlu a uložené údaje.'})
