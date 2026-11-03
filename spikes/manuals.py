# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Explicit public documentation allowlist, shared by the UI and packages."""
from pathlib import Path

MANUAL_GROUPS = (
    ('Začínáme', (
        ('project-opening', 'Projekty a dokumenty'),
        ('desktop-navigation', 'Navigace a neuložené změny'),
        ('document-patterns-and-task-authoring', 'Vzory dokumentů a úkolů'),
    )),
    ('Plánování a spolupráce', (
        ('task-planning', 'Plánování úkolů'),
        ('roadmap-visualization', 'Roadmapa a graf'),
        ('roadmap-dependencies', 'Závislosti úkolů'),
        ('task-queue', 'Fronta úloh'),
        ('ide-workspace-sidebar', 'Workspace v IDE'),
        ('ide-queue-handoff', 'Předání úloh do IDE'),
        ('project-chat-sync', 'Sdílení chatů'),
    )),
    ('Zdroje a AI', (
        ('native-source-import', 'Import souborů'),
        ('google-drive-import', 'Import z Google Drive'),
        ('public-sources-research', 'Výzkum veřejných zdrojů'),
        ('web-search-providers', 'Webové vyhledávání'),
        ('ai-file-edit', 'Úpravy dokumentu pomocí AI'),
        ('ollama-lan', 'Připojení Ollama'),
    )),
    ('Nástroje a výstupy', (
        ('julia-runner', 'Výpočty v Julia'),
        ('gamepad-demo-presenter', 'Prezentace a gamepad'),
        ('page-layout', 'Rozvržení stránky'),
    )),
    ('Správa a nasazení', (
        ('administration', 'Administrace'),
        ('desktop-network', 'Síť a připojení'),
        ('desktop-lxc-deployment', 'Nasazení desktopu a LXC'),
        ('git-project-transfer', 'Přenos projektu přes Git'),
    )),
)


def manual_paths():
    return tuple('docs/' + key + '.md' for _, items in MANUAL_GROUPS for key, _ in items)


def manual_catalog(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    groups = []
    for title, items in MANUAL_GROUPS:
        manuals = []
        for key, label in items:
            path = root / 'docs' / (key + '.md')
            try:
                text = path.read_text(encoding='utf-8')
            except (OSError, UnicodeError):
                text = None
            manuals.append(dict(id=key, title=label, text=text))
        groups.append(dict(title=title, manuals=manuals))
    return groups
