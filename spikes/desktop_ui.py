# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Static same-origin UI; project data arrives through authenticated reads."""
import json
import copy
import re
import sqlite3
import subprocess
from urllib.parse import parse_qs, urlsplit
from pathlib import Path

from spikes.artifact_history import ArtifactHistory
from spikes.conflict_resolution import ConflictResolution
from spikes.artifact_actions import ArtifactActions
from spikes.local_api import Handler
from spikes.backend_contract import BackendResponseError, BackendUnknown
from spikes.metadata import MAX_FILE, ValidationError
from spikes.presentation_visual import SLIDE_JS
from spikes.presentation_documents import public_content
from spikes.presentation_closing import closing_slide
from spikes.ollama_backend import OllamaResponseError, UnknownRun
from spikes.openai_backend import OpenAIResponseError, OpenAIUnknownRun
from spikes.publication_cloudflare import CloudflareUnavailable, CloudflareUnknown
from spikes.public_source import (PublicSourceError, PublicSourceRejected,
                                  PublicSourceUnknown, PublicSourceUnsupported)
from spikes.projects import Projects
from spikes.project_creation import ProjectCreation
from spikes.source_import import Sources
from spikes.google_drive_import import GoogleDriveImport, DriveAccessError, GOOGLE_ISSUER, SCOPE
from spikes.gamepad_settings import DEFAULT_GAMEPAD_SETTINGS
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation
from spikes.web_search import SearchResponseError, SearchUnknown
from spikes.web_administration import (ADMIN_HTML, ADMIN_SHARING_HTML,
                                       ADMIN_CSS, ADMIN_JS)


CHAT_VALIDATION_ERRORS = {
    'Private-network orchestration requires explicit Ollama binding selection': (
        'Orchestrace přes privátní síť vyžaduje explicitně vybraný aktuální backend. '
        'Obnovte stav a spusťte nový běh.'),
    'Selected orchestration binding changed': (
        'Vybraný orchestrační backend se změnil. Zkontrolujte nový cíl a spusťte nový běh.'),
    'local-only requires same-node execution': (
        'Obsah „Jen na tomto počítači“ nelze odeslat Ollamě v privátní síti. Zvolte '
        'jinou úroveň soukromí nebo backend na stejném uzlu.'),
    'Project changed before chat dispatch': (
        'Projekt se od otevření změnil. Znovu jej otevřete a požadavek spusťte jako nový běh.'),
    'Project changed before routed task': (
        'Projekt se od otevření změnil. Znovu jej otevřete a požadavek spusťte jako nový běh.'),
    'Project changed during context preparation': (
        'Projekt se během přípravy kontextu změnil. Znovu jej otevřete a spusťte nový běh.'),
    'Project changed after context preparation': (
        'Projekt se během přípravy kontextu změnil. Znovu jej otevřete a spusťte nový běh.'),
    'Project changed during dispatch authorization': (
        'Projekt se během přípravy kontextu změnil. Znovu jej otevřete a spusťte nový běh.'),
    'Chat mode cannot change inside an existing thread': (
        'Režim nelze změnit uvnitř existujícího vlákna. Založte nové vlákno.'),
    'Chat thread changed during context preparation': (
        'Vlákno se během přípravy změnilo. Načtěte jeho aktuální stav a spusťte nový běh.'),
    'Selected chat message is unavailable': (
        'Vybraná zpráva už není v aktuálním vlákně dostupná. Obnovte výběr kontextu.'),
    'Selected chat thread is unavailable': (
        'Vybrané vlákno už není dostupné. Založte nové vlákno nebo obnovte výběr kontextu.'),
    'Selected messages must use thread order': (
        'Vybrané zprávy nejsou v aktuálním pořadí vlákna. Obnovte výběr kontextu.'),
}
AUTONOMY_VALIDATION_ERRORS = {
    'Autonomy time budget is exhausted': (
        'Časový limit automatického workflow je vyčerpán. Potvrďte nabízenou '
        'revizi rozpočtu, nebo workflow ukončete.'),
}


def scan_gamepads():
    """Return a safe, Linux-specific list of likely joystick/gamepad devices."""
    base = Path('/dev/input')
    if not base.exists():
        return {'available': False, 'devices': [], 'message': 'Linux /dev/input není dostupné.'}
    matches = []
    for entry in sorted(base.iterdir(), key=lambda p: p.name):
        if not entry.name.startswith('event'):
            continue
        path = str(entry)
        name = entry.name
        labels = [name]
        try:
            result = subprocess.run(
                ['udevadm', 'info', '--query=property', '--name=' + path],
                capture_output=True, text=True, check=False, timeout=2)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            result = None
        if result and result.returncode == 0:
            for line in result.stdout.splitlines():
                if '=' not in line:
                    continue
                key, value = line.split('=', 1)
                if key in {'ID_INPUT_JOYSTICK', 'ID_INPUT_GAMEPAD', 'ID_INPUT_KEYBOARD', 'DEVNAME'}:
                    labels.append(f'{key}={value}')
                    if key in {'ID_INPUT_JOYSTICK', 'ID_INPUT_GAMEPAD'} and value in {'1', 'true', 'True'}:
                        matches.append(path)
        if any(token in ' '.join(labels).lower() for token in ('gamepad', 'joystick', 'controller', 'pad')):
            matches.append(path)
    devices = []
    seen = set()
    for path in sorted(set(matches)):
        device_name = path.rsplit('/', 1)[-1]
        if path in seen:
            continue
        seen.add(path)
        devices.append({'path': path, 'name': device_name})
    return {
        'available': bool(devices),
        'devices': devices,
        'message': 'Nalezeno gamepad/joystick zařízení.' if devices else 'Nebyl nalezen žádný gamepad/joystick.'
    }


def presentation_deck():
    """Return a small presenter deck for desktop projection demo."""
    return {
        'active': True,
        'slides': [
            {'title': 'Úvod', 'body': 'Demo: desktopová prezentace a promítání.', 'notes': 'Přivítejte publikum a řekněte, že ukazujeme celý presenter workflow.'},
            {'title': 'Problém', 'body': 'Potřebujeme jasnou, bezpečnou prezentaci bez rizika ztráty kontextu.', 'notes': 'Zdůrazněte rozdíl mezi tím, co vidí publikum, a tím, co potřebuje řečník.'},
            {'title': 'Řešení', 'body': 'Presenter odděluje audience screen, speaker notes, další slide a backupy.', 'notes': 'Tady ukažte, že backup je připravený, ale automaticky nenaruší hlavní linii.'},
            {'title': 'Výhody', 'body': 'Snadná navigace, rychlá iterace a bezpečné odbočky pro otázky publika.', 'notes': 'Předveďte šipky, náhled dalšího slidu a otevření backupu.'},
            {'title': 'Další krok', 'body': 'Napojit deck na projektové artefakty, notes a verzovaný export.', 'notes': 'Uzavřete demo a pojmenujte, co už je funkční a co bude následovat.'},
        ],
        'backups': [
            {'title': 'Úvod: kontext', 'body': 'Presenter je součástí desktopového workspace, ne samostatný export.', 'after_slide': 0},
            {'title': 'Úvod: cíl', 'body': 'Dnes ověřujeme tok od přípravy decku až po promítání.', 'after_slide': 0},
            {'title': 'Problém: publikum', 'body': 'Publikum nemá vidět poznámky, backupy ani rozhodovací scénář.', 'after_slide': 1},
            {'title': 'Problém: řečník', 'body': 'Řečník potřebuje navigaci a připravenou odpověď na časté otázky.', 'after_slide': 1},
            {'title': 'Řešení: API', 'body': 'Deck se načítá přes lokální same-origin endpoint desktopu.', 'after_slide': 2},
            {'title': 'Řešení: stav', 'body': 'Aktuální pozice zůstává oddělená od obsahu backupu.', 'after_slide': 2},
            {'title': 'Výhody: fullscreen', 'body': 'Audience screen lze přepnout do celé obrazovky bez speaker panelu.', 'after_slide': 3},
            {'title': 'Výhody: otázky', 'body': 'Backupy slouží jako řízené odbočky při dotazech publika.', 'after_slide': 3},
            {'title': 'Další krok: data', 'body': 'Slides mohou být odvozené z verzovaných projektových artefaktů.', 'after_slide': 4},
            {'title': 'Další krok: export', 'body': 'Bezpečný export musí vyloučit notes a nepoužité backupy.', 'after_slide': 4},
        ],
        'current_slide': 0,
        'message': 'Prezentace je připravena k promítání.'
    }


def presentation_public_payload(server, request=None):
    """Return only the currently approved public presentation content."""
    deck = getattr(server, 'presentation_selected_deck', None) or presentation_deck()
    session = getattr(server, 'presentation_session_deck', None)
    if session is not None and session.get('revision') == deck.get('revision'):
        deck = session
    state = getattr(server, 'presentation_public_state',
                    {'visible': False, 'blackout': True, 'slide': 0, 'content': None, 'ratio': '16:9'})
    if request and request.get('action') == 'show':
        index = request.get('slide', state['slide'])
        if not isinstance(index, int) or not 0 <= index < len(deck['slides']):
            index = 0
        if 'slide_id' in request:
            if request.get('deck_revision') != deck.get('revision'):
                raise ValueError('Prezentace se změnila. Znovu otevřete presenter.')
            source = next((s for s in deck['slides'] + deck['backups'] if s.get('id') == request['slide_id']), None)
            if source is None:
                raise ValueError('Slide v této prezentaci neexistuje.')
            content = public_content(source)
            rows = request.get('rows', len(content['bullets']))
            if type(rows) is not int or not 0 <= rows <= len(content['bullets']):
                raise ValueError('Neplatný počet zobrazených řádků.')
            content['bullets'] = content['bullets'][:rows]
            content['body'] = '\n'.join(content['bullets'])
        else:
            content = request.get('content')
        if not isinstance(content, dict):
            source = deck['slides'][index]
            content = {'title': source['title'], 'body': source['body']}
        ratio = request.get('ratio', state.get('ratio', '16:9'))
        if ratio not in {'16:9', '4:3'}:
            ratio = '16:9'
        state = {'visible': True, 'blackout': False, 'slide': index, 'ratio': ratio,
                 'content': (content if 'slide_id' in request else {'title': str(content.get('title', '')), 'body': str(content.get('body', ''))})}
    elif request and request.get('action') == 'display-ratio' and request.get('ratio') in {'16:9', '4:3'}:
        state = dict(state, ratio=request['ratio'])
    elif request and request.get('action') == 'ratio' and request.get('ratio') in {'16:9', '4:3'}:
        state = dict(state, ratio=request['ratio'])
    elif request and request.get('action') == 'blackout':
        state = dict(state, blackout=True)
    elif request and request.get('action') == 'reveal':
        state = dict(state, blackout=False, visible=True)
    if request and request.get('action') == 'show' and 'slide_id' in request:
        sessions = getattr(server, 'presentation_sessions', None)
        session_id = getattr(server, 'presentation_session_id', None)
        if sessions is not None and session_id is not None:
            sessions.record(session_id, request['slide_id'], state['ratio'], state['content'])
    server.presentation_public_state = state
    if not state['visible'] or state['blackout']:
        return {'visible': False, 'blackout': True}
    return {'visible': True, 'blackout': False, 'slide': state['slide'], 'ratio': state.get('ratio', '16:9'), 'content': state['content']}


def presentation_status(server, *, start=False):
    result = copy.deepcopy(getattr(server, 'presentation_selected_deck', None) or presentation_deck())
    if start:
        profile = getattr(server, 'user_profile', None)
        result['slides'].append(closing_slide(profile.load() if profile else None, result.get('revision')))
        server.presentation_session_deck = copy.deepcopy(result)
        revision = result.get('revision', '')
        match = re.fullmatch(r'([0-9a-f]{40,64}):([0-9a-f-]{36})', revision)
        sessions = getattr(server, 'presentation_sessions', None)
        project_id = result.get('source_project_id')
        artifact_id = result.get('source_artifact_id')
        if sessions is not None and match and project_id and artifact_id:
            server.presentation_session_id = sessions.start(
                project_id, artifact_id, revision, result.get('title', 'Prezentace'))
    state = getattr(server, 'presentation_public_state', {})
    result['ratio'] = state.get('ratio', '16:9')
    return result


def finish_presentation_session(server):
    session_id = getattr(server, 'presentation_session_id', None)
    sessions = getattr(server, 'presentation_sessions', None)
    if session_id is None or sessions is None:
        return {'saved': False}
    artifact_id = sessions.finish(session_id)
    server.presentation_session_id = None
    return {'saved': True, 'artifact_id': artifact_id}


HTML = '''<!doctype html><html lang="cs"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projektový workspace</title><link rel="stylesheet" href="/app.css">
<body data-runtime="pending"><section id="login"><h1>Projektový workspace</h1>
<form id="login-form"><label>Přístupový klíč <input id="access-key" type="password" required autocomplete="off"></label>
<button>Přihlásit</button><p id="login-status" role="status"></p></form></section>
<button id="mobile-sidebar-toggle" type="button" aria-controls="workspace-sidebar" aria-expanded="false">Navigace</button>
<button id="mobile-sidebar-backdrop" type="button" aria-label="Zavřít navigaci" hidden></button>
<aside id="workspace-sidebar" aria-label="Navigace pracovního prostoru"><div class="brand"><span class="brand-mark">◈</span><span class="brand-name">WORKSPACE</span></div>
<div id="sidebar-project-tools">
<div id="sidebar-tabs" role="tablist" aria-label="Obsah levého panelu">
<button id="projects-tab" role="tab" aria-label="Projekty" aria-controls="sidebar-projects" aria-selected="true"><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6.5h7l2 2h9v10H3z"/></svg><span class="sidebar-tab-label" role="tooltip">Projekty</span></button>
<button id="chats-tab" role="tab" aria-label="Chaty" aria-controls="sidebar-chats" aria-selected="false" tabindex="-1"><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/></svg><span class="sidebar-tab-label" role="tooltip">Chaty</span></button>
<button id="todo-tab" role="tab" aria-label="Úkoly" aria-controls="todo-widget" aria-selected="false" aria-disabled="true" disabled tabindex="-1"><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 5h14v15H5zM8 9l2 2 4-4M8 15h7"/></svg><span class="sidebar-tab-label" role="tooltip">Úkoly</span></button>
<button id="artifacts-tab" role="tab" aria-label="Podklady" aria-controls="sidebar-artifacts" aria-selected="false" aria-disabled="true" disabled tabindex="-1"><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6zM15 3v5h4M9 12h7M9 16h7"/></svg><span class="sidebar-tab-label" role="tooltip">Podklady</span></button>
<button id="tools-tab" role="tab" aria-label="Nástroje" aria-controls="sidebar-tools" aria-selected="false" aria-disabled="true" disabled tabindex="-1"><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 6a4 4 0 0 0-5 5L3 17l4 4 6-6a4 4 0 0 0 5-5l-3 3-4-4z"/></svg><span class="sidebar-tab-label" role="tooltip">Nástroje</span></button>
<button id="presentations-tab" role="tab" aria-label="Výstupy" aria-controls="sidebar-presentations" aria-selected="false" aria-disabled="true" disabled tabindex="-1"><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 19V9h4v10M10 19V4h4v15M16 19v-7h4v7"/></svg><span class="sidebar-tab-label" role="tooltip">Výstupy</span></button>
<button id="settings-sidebar-tab" role="tab" aria-label="Nastavení" aria-controls="sidebar-settings" aria-selected="false" tabindex="-1"><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/></svg><span class="sidebar-tab-label" role="tooltip">Nastavení</span></button>
<button id="federation-tab" role="tab" aria-label="Federace" aria-controls="sidebar-federation" aria-selected="false" tabindex="-1" hidden><svg class="sidebar-tab-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="6" cy="12" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="m8.7 10.7 6.6-3.4M8.7 13.3l6.6 3.4"/></svg><span class="sidebar-tab-label" role="tooltip">Federace</span></button></div>
<div id="sidebar-projects" role="tabpanel" aria-labelledby="projects-tab" tabindex="0">
<h2>Projekty</h2><div class="sidebar-project-primary-actions">
<button id="sidebar-create-project" type="button" aria-label="Nový projekt"><svg class="project-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h6l2 2h8v10H4zM12 12v5M9.5 14.5h5"/></svg><span class="project-action-label" role="tooltip">Nový projekt</span></button>
<button id="sidebar-import-project" type="button" aria-label="Importovat projekt" aria-expanded="false" aria-controls="sidebar-project-import-options"><svg class="project-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h6l2 2h8v10H4zM12 3v10M8.5 9.5 12 13l3.5-3.5"/></svg><span class="project-action-label" role="tooltip">Importovat projekt</span></button>
<button id="sidebar-project-trash" type="button" aria-label="Koš projektů"><svg class="project-action-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"/></svg><span class="project-action-label" role="tooltip">Koš projektů</span></button></div>
<div id="sidebar-project-import-options" hidden><button id="sidebar-register-project" type="button" hidden>Projekt z umístění</button><button id="open-notebooklm-import" type="button" hidden>NotebookLM</button></div>
<p id="sidebar-project-status" role="status">Načítám projekty…</p><button id="sidebar-project-recover" type="button" hidden>Dokončit přerušenou operaci</button><ul id="sidebar-project-list"></ul></div>
<div id="sidebar-chats" role="tabpanel" aria-labelledby="chats-tab" tabindex="0" hidden>
<h2>Chaty</h2><p id="sidebar-chat-status" role="status">Načítám uložená vlákna…</p>
<div class="sidebar-chat-primary-actions"><button id="chat-new-thread" type="button" disabled>Nové vlákno</button></div>
<ul id="sidebar-chat-tree" role="tree" aria-label="Uložené chaty"></ul></div>
<div id="todo-widget" role="tabpanel" aria-labelledby="todo-tab" tabindex="0" hidden><h2>Hlavní seznam úkolů</h2>
<p id="todo-status" role="status">Otevřete projekt.</p><div id="todo-title"></div>
<button id="create-main-todo" hidden>Vytvořit seznam úkolů</button>
<ul id="todo-tree" aria-label="Úkoly projektu"></ul><small id="todo-help" hidden>Úkoly upravíte v editoru.</small></div>
<div id="sidebar-artifacts" role="tabpanel" aria-labelledby="artifacts-tab" tabindex="0" hidden>
<h2>Podklady</h2><div class="sidebar-artifact-primary-actions"><button id="new-document" type="button">Nový dokument</button>
<button id="open-source-import" type="button">Importovat zdroj</button></div>
<p id="sidebar-artifact-status" role="status"></p>
<ul id="sidebar-artifact-list" aria-label="Podklady projektu"></ul></div>
<div id="sidebar-tools" role="tabpanel" aria-labelledby="tools-tab" tabindex="0" hidden>
<h2>Nástroje</h2><p>Výpočetní a simulační skripty projektu.</p>
<p id="sidebar-tools-status" role="status">Katalog nástrojů je zatím prázdný. Spouštění skriptů bude doplněno samostatnou schopností.</p>
<ul id="sidebar-tool-list" aria-label="Nástroje projektu"></ul></div>
<div id="sidebar-presentations" role="tabpanel" aria-labelledby="presentations-tab" tabindex="0" hidden>
<h2>Výstupy</h2><h3>Prezentace</h3><p id="sidebar-presentation-status" role="status">Otevřete projekt.</p>
<ul id="sidebar-presentation-list" aria-label="Prezentace ve výstupech projektu"></ul></div>
<div id="sidebar-settings" role="tabpanel" aria-labelledby="settings-sidebar-tab" tabindex="0" hidden>
<h2>Nastavení</h2><p>Jednotlivá nastavení tohoto uzlu.</p>
<ul id="sidebar-settings-list" aria-label="Seznam nastavení">
<li class="sidebar-list-row" data-settings-item="settings-backend-tab"><button class="sidebar-list-main" type="button" data-settings-tab="settings-backend-tab">AI backend</button><details class="sidebar-item-menu"><summary aria-label="Akce nastavení AI backend">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button type="button" role="menuitem" data-settings-menu-tab="settings-backend-tab">Otevřít</button></div></details></li>
<li class="sidebar-list-row" data-settings-item="settings-cms-tab"><button class="sidebar-list-main" type="button" data-settings-tab="settings-cms-tab">Weby</button><details class="sidebar-item-menu"><summary aria-label="Akce nastavení Weby">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button type="button" role="menuitem" data-settings-menu-tab="settings-cms-tab">Otevřít</button></div></details></li>
<li class="sidebar-list-row" data-settings-item="settings-access-tab" hidden><button class="sidebar-list-main" type="button" data-settings-tab="settings-access-tab">Dostupnost aplikace</button><details class="sidebar-item-menu"><summary aria-label="Akce nastavení dostupnosti aplikace">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button type="button" role="menuitem" data-settings-menu-tab="settings-access-tab">Otevřít</button></div></details></li>
<li class="sidebar-list-row" data-settings-item="settings-profile-tab" hidden><button class="sidebar-list-main" type="button" data-settings-tab="settings-profile-tab">Profil</button><details class="sidebar-item-menu"><summary aria-label="Akce nastavení Profil">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button type="button" role="menuitem" data-settings-menu-tab="settings-profile-tab">Otevřít</button></div></details></li>
<li class="sidebar-list-row" data-settings-item="settings-users-tab" hidden><button class="sidebar-list-main" type="button" data-settings-tab="settings-users-tab">Uživatelé</button><details class="sidebar-item-menu"><summary aria-label="Akce nastavení Uživatelé">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button type="button" role="menuitem" data-settings-menu-tab="settings-users-tab">Otevřít</button></div></details></li>
<li class="sidebar-list-row" data-settings-item="settings-federation-tab"><button class="sidebar-list-main" type="button" data-settings-tab="settings-federation-tab">Federace</button><details class="sidebar-item-menu"><summary aria-label="Akce nastavení Federace">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button type="button" role="menuitem" data-settings-menu-tab="settings-federation-tab">Otevřít</button></div></details></li>
</ul></div>
<div id="sidebar-federation" role="tabpanel" aria-labelledby="federation-tab" tabindex="0" hidden>
<h2>Federace</h2><p>Sdílení projektů a nástroje federačního uzlu.</p>
<ul id="sidebar-federation-list" aria-label="Nástroje federace"><li class="sidebar-list-row">
<button id="open-federation-sharing" class="sidebar-list-main" type="button">Sdílení projektů</button>
<details class="sidebar-item-menu"><summary aria-label="Akce sdílení projektů">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button id="open-federation-sharing-menu" type="button" role="menuitem">Otevřít</button></div></details>
</li><li class="sidebar-list-row">
<button id="open-federation-network" class="sidebar-list-main" type="button">Síťový backend a spojení</button>
<details class="sidebar-item-menu"><summary aria-label="Akce síťového backendu a spojení">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button id="open-federation-network-menu" type="button" role="menuitem">Otevřít</button></div></details>
</li><li class="sidebar-list-row">
<button id="open-federation-deployment" class="sidebar-list-main" type="button">Nasadit LXC uzel</button>
<details class="sidebar-item-menu"><summary aria-label="Akce nasazení LXC uzlu">⋮</summary><div class="sidebar-item-menu-items" role="menu"><button id="open-federation-deployment-menu" type="button" role="menuitem">Otevřít</button></div></details>
</li></ul></div></div>
<section id="resource-monitor" aria-label="Přehled zdrojů uzlu">
<button id="resource-monitor-open" type="button" aria-haspopup="dialog" aria-controls="resource-monitor-dialog">
<svg class="sidebar-utility-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 17V7M9 17v-4M14 17V4M19 17v-7"/></svg>
<span class="resource-monitor-heading">Zdroje <small>detail</small></span>
<span id="backend-metrics-indicator" hidden>OpenAI · nenačteno</span>
<span id="local-provider-indicator">Lokální AI · neověřeno</span>
<span class="resource-mini-row"><span>CPU</span><progress max="100" value="0" aria-label="CPU – placeholder bez telemetrie"></progress><output>—</output></span>
<span class="resource-mini-row"><span>GPU</span><progress max="100" value="0" aria-label="GPU – placeholder bez telemetrie"></progress><output>—</output></span>
<span class="resource-mini-row"><span>RAM</span><progress max="100" value="0" aria-label="RAM – placeholder bez telemetrie"></progress><output>—</output></span>
<span class="resource-mini-row"><span>VRAM</span><progress max="100" value="0" aria-label="VRAM – placeholder bez telemetrie"></progress><output>—</output></span>
<span class="resource-mini-row"><span>DISK</span><progress max="100" value="0" aria-label="Disk – placeholder bez telemetrie"></progress><output>—</output></span>
<span class="resource-mini-row"><span>NET</span><progress max="100" value="0" aria-label="Síť – placeholder bez telemetrie"></progress><output>—</output></span>
</button></section>
<button id="logout" type="button"><svg class="sidebar-utility-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 5H5v14h5M14 8l4 4-4 4M8 12h10"/></svg><span>Odhlásit</span></button>
<button id="sidebar-layout-toggle" type="button" aria-pressed="false" aria-label="Sbalit hlavní panel"><svg class="sidebar-utility-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="m15 6-6 6 6 6"/></svg><span class="sidebar-layout-label">Sbalit panel</span></button></aside>
<dialog id="resource-monitor-dialog" aria-labelledby="resource-monitor-title">
<div class="resource-dialog-heading"><div><div class="eyebrow">TELEMETRIE UZLU</div><h2 id="resource-monitor-title">Spotřeba a dostupnost zdrojů</h2></div><button id="resource-monitor-close" type="button" class="secondary-button" aria-label="Zavřít přehled zdrojů">Zavřít</button></div>
<section><h3>Poskytovatelé</h3><div id="resource-provider-list">
<article id="openai-resource-provider" hidden><strong>OpenAI</strong><p id="resource-openai-detail">Účetní přehled zatím nebyl načten.</p></article>
<article><strong>Lokální AI</strong><p id="local-provider-availability">Dostupnost není ověřena.</p><small>U lokálních providerů se zde sleduje pouze dostupnost, nikoli tokeny ani náklady.</small></article>
</div></section>
<section><h3>Systémové monitory</h3><p class="resource-placeholder-note">CPU, GPU, RAM, VRAM, DISK a NET jsou zatím pouze připravená místa. Aplikace dosud systémovou telemetrii nesbírá.</p>
<div id="system-monitor-detail"></div></section>
</dialog>
<dialog id="project-registration-remove-dialog" aria-labelledby="project-registration-remove-title">
<form method="dialog"><h2 id="project-registration-remove-title">Odebrat nedostupnou registraci</h2>
<p>Odebere se pouze registrace z tohoto uzlu. Lokální stav projektu a případná data v jiném umístění zůstanou zachované.</p>
<p>Projekt: <code id="project-registration-remove-id"></code></p>
<div class="form-actions"><button value="cancel" class="secondary-button">Zrušit</button><button id="project-registration-remove-confirm" type="button" class="danger">Odebrat registraci</button></div>
</form></dialog>
<main><div id="project-home">
<header><span class="badge">Pracovní prostor</span></header>
<div class="home-heading"><h1>Přehled</h1></div>
<p id="project-status" class="visually-hidden" role="status" aria-live="polite">Načítám přehled…</p>
<div id="dashboard-grid" aria-label="Přehled pracovního prostoru">
<section id="dashboard-calendar" class="dashboard-tile dashboard-placeholder" tabindex="0" aria-label="Kalendář, integrace připravena jako placeholder">
<span class="dashboard-kicker">Dnes</span><strong id="dashboard-date">—</strong>
<p>Kalendář zatím není propojený s externí aplikací.</p></section>
<section id="dashboard-tasks" class="dashboard-tile dashboard-tasks"><span class="dashboard-kicker">Všechny projekty</span>
<h2>Úkoly</h2><p id="dashboard-task-status" role="status">Načítám úkoly…</p>
<ul id="dashboard-task-list" aria-label="Nehotové úkoly ze všech projektů"></ul></section>
<section id="dashboard-mail" class="dashboard-tile dashboard-placeholder" tabindex="0" aria-label="Pošta, integrace připravena jako placeholder">
<span class="dashboard-kicker">Pošta</span><strong>Přehled zpráv</strong>
<p>Poštovní klient zatím není propojený.</p></section>
<button id="dashboard-trash" class="dashboard-tile dashboard-action" type="button"><span class="dashboard-kicker">Projekty</span>
<strong>Koš projektů</strong><span id="dashboard-trash-summary">Načítám…</span></button>
<div id="project-cards" class="dashboard-projects" aria-label="Naposledy otevřené projekty"></div>
</div>
</div>
<div id="project-trash-view" hidden>
<header><span class="badge">Projekty</span></header>
<button id="project-trash-back" type="button" class="back-button">← Zpět na přehled</button>
<section class="standalone-form project-trash-page"><h1>Koš projektů</h1>
<section id="project-delete-panel" class="creation-preview" hidden><h2 id="project-delete-title">Akce projektu</h2>
<label id="project-delete-mode-row">Režim <select id="project-delete-mode"><option value="clear-derived">Obnovit odvozený index</option><option value="unregister">Pouze odregistrovat</option><option value="trash" selected>Přesunout do obnovitelného koše</option></select></label>
<pre id="project-delete-details"></pre><p id="project-delete-blockers" role="alert"></p>
<label class="confirm"><input id="project-delete-check" type="checkbox"> Potvrzuji přesný lokální rozsah této akce.</label>
<div class="form-actions"><button id="project-delete-confirm" type="button" disabled>Provést potvrzenou akci</button>
<button id="project-delete-cancel" type="button" class="secondary-button">Zrušit</button></div>
<p id="project-delete-status" role="status"></p></section>
<div id="project-trash-list"></div><p id="project-trash-status" role="status"></p></section></div>
<div id="project-repair-view" hidden>
<header><span class="badge">Projekty</span><span>Desktopová diagnostika</span></header>
<button id="project-repair-back" type="button" class="back-button">← Zpět na projekty</button>
<section class="standalone-form project-repair-page"><div class="eyebrow">CHECK &amp; REPAIR</div>
<h1 id="project-repair-heading" tabindex="-1">Zkontrolovat projekt</h1>
<p id="project-repair-target"></p>
<p>Kontrola je pouze pro čtení. Automatická oprava nikdy nemění Git historii,
práva, identitu projektu ani obsah neznámého poškozeného stavu.</p>
<div class="form-actions"><button id="project-repair-check" type="button">Spustit novou kontrolu</button>
<button id="project-repair-location" type="button" class="secondary-button" hidden>Opravit umístění…</button></div>
<p id="project-repair-status" role="status" aria-live="polite"></p>
<section id="project-repair-report" hidden aria-labelledby="project-repair-report-title">
<h2 id="project-repair-report-title">Výsledek kontroly</h2>
<p><strong id="project-repair-state"></strong> <span id="project-repair-summary"></span></p>
<ol id="project-repair-findings" class="repair-findings"></ol>
<button id="project-repair-preview" type="button" hidden>Připravit bezpečnou opravu…</button>
</section>
<section id="project-repair-plan" class="creation-preview" hidden>
<h2>Potvrzení opravy</h2><pre id="project-repair-details"></pre>
<label class="confirm"><input id="project-repair-confirm-check" type="checkbox"> Potvrzuji přesně popsaný účinek na lokální vrstvě.</label>
<div class="form-actions"><button id="project-repair-confirm" type="button" disabled>Provést potvrzenou opravu</button>
<button id="project-repair-cancel" type="button" class="secondary-button">Zrušit náhled</button></div>
</section></section></div>
<div id="legacy-home-diagnostics" hidden aria-hidden="true">
<details class="diagnostics"><summary>Ověření spojení</summary>
<button id="increment">Ověřit spojení</button><output id="count">0</output><p id="status" role="status">Připraveno k ověření.</p></details>
<details class="diagnostics"><summary>Gamepad demo</summary>
<button id="gamepad-scan" type="button">Vyhledat gamepad</button>
<p id="gamepad-status" role="status">Stav: zatím bez skenování.</p>
<ul id="gamepad-list" aria-live="polite"></ul>
</details>
<details id="presentation-mode" class="diagnostics presentation-panel"><summary>Promítání prezentace</summary>
<button id="presentation-start" type="button">Spustit prezentaci</button>
<button id="presentation-editor" type="button">Editor prezentací…</button>
<button id="presentation-open" type="button">Otevřít presenter</button>
<button id="presentation-prev" type="button" disabled aria-label="Předchozí slide">Předchozí</button>
<button id="presentation-next" type="button" disabled aria-label="Další slide">Další</button>
<button id="presentation-fullscreen" type="button" disabled>Celá obrazovka</button>
<p id="presentation-status" role="status">Stav: prezentace není spuštěna.</p>
<div id="presentation-slide" tabindex="0" aria-live="polite">Zde se zobrazí aktuální slide.</div>
</details>
</div>
<div id="project-create-view" hidden>
<header><span class="badge">Nový projekt</span><span>Samostatný průvodce vytvořením</span></header>
<button id="project-create-back" type="button" class="back-button">← Zpět na projekty</button>
<section class="standalone-form"><div class="eyebrow">NOVÝ PRACOVNÍ PROSTOR</div><h1 id="project-create-heading" tabindex="-1">Vytvořit projekt</h1>
<p>Nejprve připravíme přesný náhled. Projekt vznikne až po vašem potvrzení názvu a cílového umístění.</p>
<form id="create-project" aria-label="Vytvořit projekt">
<label for="new-project-title">Název nového projektu</label>
<div class="project-create-row"><input id="new-project-title" type="text" required minlength="1" maxlength="200" placeholder="Můj projekt">
<button id="create-project-btn">Připravit vytvoření</button></div>
<div id="project-location-controls" hidden><button id="choose-project-location" type="button">Vybrat existující prázdnou složku…</button>
<button id="clear-project-location" type="button" class="secondary-button" hidden>Použít výchozí umístění</button>
<p id="project-location-label">Použije se výchozí místní umístění.</p>
<label id="remember-project-parent-row" hidden><input id="remember-project-parent" type="checkbox"> Používat rodiče vybrané složky jako výchozí umístění</label></div>
<section id="project-create-preview" class="creation-preview" hidden><h2>Potvrzení vytvoření</h2>
<pre id="project-create-details"></pre>
<label class="confirm"><input id="project-create-confirm-check" type="checkbox"> Potvrzuji název a přesné cílové umístění.</label>
<div class="form-actions"><button id="project-create-confirm" type="button" disabled>Vytvořit a otevřít projekt</button>
<button id="project-create-cancel" type="button" class="secondary-button">Zrušit náhled</button></div></section>
<p id="create-project-status" role="status"> </p></form></section></div>
<div id="federation-view" hidden>
<header><span class="badge">Federace</span><span>Policy sdílení projektů</span></header>
<section class="standalone-form federation-sharing-page"><div class="eyebrow">PROJEKTY × PEERY</div>
<p id="federation-sharing-status" role="status" aria-live="polite">Načítám nastavení sdílení…</p>
'''+ ADMIN_SHARING_HTML + '''
</section></div>
<div id="federation-network-view" hidden>
<header><span class="badge">Federace</span><span>Lokální nastavení desktopového uzlu</span></header>
<section class="standalone-form federation-network-page"><div class="eyebrow">SÍŤ A DŮVĚRA</div>
<h1>Síťový backend a spojení</h1>
<p>Backend sdílí identitu desktopu a vystavuje pouze podepsaný test spojení, nikoli projekty, účty ani synchronizaci. Firewall se nemění.</p>
<form id="federation-network-form">
<fieldset><legend>HTTPS backend desktopu</legend>
<label class="confirm"><input name="enabled" type="checkbox"> Povolit HTTPS backend při běhu desktopu</label>
<label>Naslouchací privátní IPv4 <input name="bind" type="text" list="federation-network-addresses" maxlength="45" required autocomplete="off"></label>
<datalist id="federation-network-addresses"></datalist>
<label>Port <input name="port" type="number" min="1024" max="65535" required></label>
<label>Povolená LAN klientů <input name="lan" type="text" maxlength="64" required autocomplete="off"></label>
<label>TLS certifikát <input name="cert" type="text" maxlength="4096" autocomplete="off"></label>
<label>TLS soukromý klíč <input name="key" type="text" maxlength="4096" autocomplete="off"></label>
<label>Veřejná CA desktopu <input name="ca" type="text" maxlength="4096" autocomplete="off"></label>
<label class="confirm"><input name="generate" type="checkbox"> Vytvořit novou lokální CA a TLS certifikát pro zvolenou IP</label>
<p class="form-warning">Nové TLS změní důvěryhodnou CA. Pokud následné spuštění nebo uložení selže, nově vytvořená nepoužitá TLS složka může zůstat na disku; předchozí listener se obnoví.</p>
<button id="federation-network-apply" type="submit">Použít a uložit nastavení</button>
</fieldset>
<fieldset><legend>Diagnostika protějšího uzlu</legend>
<label>Zapamatovaný LXC uzel <select name="target"></select></label>
<label>Důvěryhodná veřejná CA LXC <input name="peer_ca" type="text" maxlength="4096" autocomplete="off"></label>
<div class="form-actions"><button id="federation-network-check" type="button">Ověřit HTTPS a identitu</button>
<button id="federation-network-bilateral-preview" type="button" class="secondary-button">Ověřit oba směry…</button></div>
<section id="federation-network-confirmation" class="creation-preview" hidden><h2>Potvrdit obousměrný test přes SSH</h2>
<pre id="federation-network-details"></pre>
<p>Přenese se pouze veřejná CA desktopu a aktualizuje adresa již schváleného peeru. Identity, práva, soukromé klíče ani firewall se nemění. Při pozdější chybě testu mohou CA a adresa na LXC zůstat aktualizované.</p>
<label class="confirm"><input id="federation-network-confirm" type="checkbox"> Potvrzuji uvedený LXC uzel, veřejné CA a jedno SSH spojení.</label>
<div class="form-actions"><button id="federation-network-bilateral" type="button" disabled>Potvrdit a ověřit oba směry</button><button id="federation-network-cancel" type="button" class="secondary-button">Zrušit</button></div>
</section></fieldset>
<p id="federation-network-status" role="status" aria-live="polite">Otevřete nástroj ze záložky Federace.</p>
<pre id="federation-network-log" aria-label="Výsledek síťové operace"></pre>
</form></section></div>
<div id="federation-deployment-view" hidden>
<header><span class="badge">Federace</span><span>Desktopový nástroj pro vzdálený uzel</span></header>
<section class="standalone-form federation-deployment-page"><div class="eyebrow">LXC UZEL</div>
<h1>Nasadit LXC uzel</h1>
<p>Operace používá jedno SSH spojení. IP kontejneru zjistí automaticky; router musí mít Python 3 a jeho SSH host key musí být předem důvěryhodný v <code>known_hosts</code>. Heslo se neukládá.</p>
<form id="federation-deployment-form">
<label>Zapamatovaný uzel <select name="target"><option value="-1">Nový / ručně zadaný uzel</option></select></label>
<label>SSH router <input name="host" type="text" maxlength="255" required autocomplete="off" placeholder="root@192.168.100.1"></label>
<label>Kontejner <input name="container" type="text" maxlength="63" required value="workspace-m0" autocomplete="off"></label>
<label>Privátní LAN <input name="lan" type="text" maxlength="64" required value="192.168.100.0/24" autocomplete="off"></label>
<label>Adresa desktopového uzlu <input name="endpoint" type="text" list="federation-deployment-endpoints" maxlength="4096" autocomplete="off" placeholder="https://192.168.100.2:8443"></label>
<datalist id="federation-deployment-endpoints"></datalist>
<label>Operace <select name="mode" required></select></label>
<p class="form-warning">První instalace vytvoří lokálního správce a schválí peery na obou uzlech. Existující účty a důvěra se nepřepisují. Projektová synchronizace se nezapíná.</p>
<p class="form-warning">Reset zahodí recovery snapshot a zastaví službu; není rollback. Po selhání instalace použijte nejprve Obnovit. Aktualizace adresy neinstaluje software, ale vyžaduje zapamatovaný uzel a ověří TLS i identitu.</p>
<button id="federation-deployment-preview" type="button" disabled>Zobrazit souhrn</button>
<section id="federation-deployment-confirmation" class="creation-preview" hidden><h2>Potvrdit vzdálené změny</h2>
<pre id="federation-deployment-details"></pre>
<p>Instalace nebo aktualizace restartuje pouze webovou službu. První instalace navíc vytvoří správce a oboustrannou důvěru. Změna adresy upraví schválený desktopový peer bez instalace softwaru.</p>
<label class="confirm"><input id="federation-deployment-confirm" type="checkbox"> Potvrzuji přesný SSH cíl, kontejner, LAN, endpoint a zvolenou operaci.</label>
<div class="form-actions"><button id="federation-deployment-start" type="submit" disabled>Potvrdit a spustit</button><button id="federation-deployment-cancel" type="button" class="secondary-button">Zrušit</button></div>
</section>
<p id="federation-deployment-status" role="status" aria-live="polite">Otevřete nástroj ze záložky Federace.</p>
<pre id="federation-deployment-log" aria-label="Průběh nasazení"></pre>
</form></section></div>
<div id="notebooklm-import-view" hidden>
<header><span class="badge">Import projektu</span><span>Personal NotebookLM / Google Takeout</span></header>
<button id="notebooklm-import-back" type="button" class="back-button">← Zpět na projekty</button>
<section id="notebooklm-import" class="standalone-form"><h1>Importovat celý projekt z NotebookLM</h1>
<p class="notebooklm-server-source">Zadejte absolutní cestu k TGZ souboru uloženému na tomto uzlu. Import je dostupný pouze správci uzlu.</p>
<label class="notebooklm-server-source">Takeout TGZ na uzlu <input id="notebooklm-archive" type="text" autocomplete="off" placeholder="/srv/import/takeout.tgz"></label>
<div class="notebooklm-desktop-source"><button id="notebooklm-choose-archive" type="button">Vybrat Takeout TGZ…</button>
<p id="notebooklm-archive-label">Archiv zatím nebyl vybrán.</p></div>
<button id="notebooklm-load" type="button">Načíst bezpečný přehled</button>
<label>Projekt z archivu (NotebookLM notebook) <select id="notebooklm-selection" disabled></select></label>
<label>Soukromí <select id="notebooklm-privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option id="notebooklm-local-only" value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select></label>
<div class="notebooklm-desktop-source"><button id="notebooklm-choose-target" type="button">Vybrat prázdnou cílovou složku…</button>
<p id="notebooklm-target-label">Použije se výchozí umístění projektů.</p></div>
<p class="destination-callout"><strong>Cíl projektu:</strong> <span id="notebooklm-destination">Přesná cesta se zobrazí po přípravě plánu.</span></p>
<button id="notebooklm-plan" type="button" disabled>Připravit přesný plán</button>
<pre id="notebooklm-preview" hidden></pre>
<label id="notebooklm-confirm-row" class="confirm" hidden><input id="notebooklm-confirm" type="checkbox"> Potvrzuji vybraný projekt, cílovou cestu, privacy a uvedené limity.</label>
<button id="notebooklm-run" type="button" disabled>Vytvořit a otevřít projekt</button>
<p id="notebooklm-status" role="status"></p></section></div>
<div id="settings-view" hidden>
<header><span class="badge">Nastavení uzlu</span><span>Platí pro tento počítač</span></header>
<div class="settings-heading"><div class="eyebrow">LOKÁLNÍ KONFIGURACE</div>
<h1>Nastavení</h1><p>Tato nastavení se neukládají do projektu ani nesynchronizují.</p></div>
<div id="settings-tabs" role="tablist" aria-label="Sekce nastavení">
<button id="settings-backend-tab" type="button" role="tab" aria-selected="true" aria-controls="settings-backend-panel">AI backend</button>
<button id="settings-cms-tab" type="button" role="tab" aria-selected="false" aria-controls="settings-cms-panel" tabindex="-1" hidden>Weby</button>
<button id="settings-access-tab" type="button" role="tab" aria-selected="false" aria-controls="settings-access-panel" tabindex="-1" hidden>Dostupnost</button>
<button id="settings-profile-tab" type="button" role="tab" aria-selected="false" aria-controls="settings-profile-panel" tabindex="-1" hidden>Profil</button>
<button id="settings-users-tab" type="button" role="tab" aria-selected="false" aria-controls="admin-users-panel" tabindex="-1" hidden>Uživatelé</button>
<button id="settings-federation-tab" type="button" role="tab" aria-selected="false" aria-controls="admin-federation" tabindex="-1" hidden>Federace</button></div>
<section id="settings-backend-panel" class="settings-card" role="tabpanel" aria-labelledby="settings-backend-tab">
<h2 id="settings-backend-title">Lokální AI backend</h2>
<p id="settings-backend-status" role="status" aria-live="polite">Načítám stav lokálního backendu…</p>
<form id="chat-backend-form"><label>Hranice <select name="boundary"><option value="same-node">Stejný počítač</option><option value="private-network">Privátní síť</option></select></label>
<label>Endpoint <input name="endpoint" value="http://127.0.0.1:11434" required></label>
<label>Model <input name="model" placeholder="gemma3" required></label>
<label>ID cíle <input name="target_id" value="local-process" required></label>
<label>SHA-256 certifikátu pro LAN <input name="tls_cert_sha256" placeholder="68:34:… nebo 6834…"></label>
<label class="settings-toggle"><input id="ollama-streaming-enabled" type="checkbox" disabled> Streamovat odpovědi Ollamy v režimu Brainstorming</label>
<p id="ollama-streaming-state" role="status" aria-live="polite">Načítám stav streamování…</p>
<fieldset><legend>Výchozí jazyk odpovědi</legend>
<p>Preference se dědí v pořadí uzel → projekt → vlákno; konkrétní volba v promptu platí jen pro daný běh.</p>
<label>Úroveň <select id="response-language-scope"><option value="node">Tento uzel</option><option value="project">Aktuální projekt</option><option value="thread">Aktuální vlákno</option></select></label>
<label>BCP 47 <input id="response-language-tag" value="cs-CZ" maxlength="63" required></label>
<button id="response-language-save" type="button">Uložit jazyk</button>
<p id="response-language-state" role="status" aria-live="polite">Jazyk zatím nebyl načten.</p>
</fieldset>
<button id="chat-backend-test" type="button">Ověřit bez uložení</button>
<button type="submit">Uložit backend</button></form>
<small>Privátní síť vyžaduje číselnou HTTPS adresu, stabilní ID cíle a připnutý certifikát. Test načte pouze seznam modelů; neposílá projektová data a nastavení neukládá. Tajné klíče se zde nezobrazují.</small>
<hr><h2>Řízené webové hledání</h2>
<p id="settings-search-status" role="status" aria-live="polite">SearXNG zatím nebylo načteno.</p>
<form id="search-backend-form">
<label>Hranice <select name="boundary"><option value="same-node">Stejný počítač</option><option value="private-network">Privátní síť</option></select></label>
<label>Endpoint <input name="endpoint" value="http://127.0.0.1:8888" required></label>
<label>ID cíle <input name="target_id" value="local-process" required></label>
<label>Maximum výsledků <input name="result_limit" type="number" min="1" max="10" value="3" required></label>
<label>Timeout v sekundách <input name="timeout_seconds" type="number" min="1" max="60" value="15" required></label>
<label>SHA-256 certifikátu pro LAN <input name="tls_cert_sha256" placeholder="68:34:… nebo 6834…"></label>
<button id="search-backend-test" type="button">Ověřit veřejným testovacím dotazem</button>
<button type="submit">Uložit SearXNG</button></form>
<small>Test odešle pouze pevný veřejný dotaz „SearXNG“. Projektová data se neodesílají. Skutečný dotaz se odešle až po kontrole přesného náhledu a potvrzení; obsah „Jen na tomto počítači“ se odmítne.</small>
<hr><h2>Google Drive import</h2>
<p id="settings-google-drive-status" role="status" aria-live="polite">Připojení zatím nebylo načteno.</p>
<details class="oauth-setup-guide"><summary>Jak připravit první přihlášení</summary>
<ol><li id="google-drive-client-guide">Načítám správný typ OAuth klienta pro tuto aplikaci.</li>
<li><span id="google-drive-callback-guide">Návratová adresa:</span> <code id="google-drive-callback"></code></li>
<li>V Google Auth Platform → Audience ponechte pro osobní test stav <strong>Testing</strong> a v části <strong>Test users</strong> přidejte přesný Google účet, kterým se budete přihlašovat. Pro takový test není nutné čekat na veřejné ověření aplikace.</li>
<li>Client ID a client secret vložte níže. Uloží se jen v soukromém stavu tohoto uzlu, ne do projektu.</li></ol>
<p>Google heslo se zadává pouze na stránce Googlu; Workspace je nikdy neuvidí.</p></details>
<form id="google-drive-config-form"><label>OAuth client ID <input name="client_id" maxlength="512" autocomplete="off" required></label>
<label>OAuth client secret <input name="client_secret" type="password" minlength="8" maxlength="512" autocomplete="new-password" required></label>
<button type="submit">Uložit Google OAuth klienta</button></form>
<small>Použije se pouze per-file scope <code>drive.file</code>. OAuth klient a tokeny zůstanou v soukromém stavu uzlu mimo projektový Git; secret se po uložení vymaže a backend jej nevrací.</small>
<hr><h2>Lokální obrazový backend ComfyUI</h2>
<p id="settings-comfy-status" role="status">Načítám nastavení ComfyUI…</p>
<form id="comfy-backend-form">
<label>Hranice <select name="boundary"><option value="same-node">Stejný počítač</option><option value="private-network">Privátní síť</option></select></label>
<label>Endpoint <input name="endpoint" value="http://127.0.0.1:8188" required></label>
<label>ID cíle <input name="target_id" value="local-process" required></label>
<label>Revize workflow <input name="workflow_revision" required></label>
<label>API workflow JSON <textarea name="workflow" rows="8" required></textarea></label>
<label>Mapa parametrů JSON <textarea name="parameters" rows="5" required>{"prompt":{"node_id":"1","input":"text"},"width":{"node_id":"2","input":"width"},"height":{"node_id":"2","input":"height"},"seed":{"node_id":"3","input":"seed"}}</textarea></label>
<label>Výstupní node ID <input name="output_node_id" required></label>
<label>Timeout v sekundách <input name="timeout_seconds" type="number" min="1" max="180" value="180" required></label>
<label>SHA-256 certifikátu pro LAN <input name="tls_cert_sha256" pattern="[0-9a-f]{64}"></label>
<button type="submit">Uložit ComfyUI</button></form>
<small>Uloží se pouze verzovaný API workflow. Při generování lze měnit jen prompt, rozměry a seed; custom workflow od LLM se nespouští.</small>
<hr><h2>Externí textový backend</h2>
<p id="settings-external-status" role="status" aria-live="polite">Načítám stav externího backendu…</p>
<form id="external-backend-form">
<label>Provider <input value="OpenAI Responses API" disabled></label>
<label>Endpoint <input name="endpoint" value="https://api.openai.com/v1/responses" readonly></label>
<label>Model <input name="model" list="external-models" placeholder="gpt-5.6-luna" value="gpt-5.6-luna" required></label>
<datalist id="external-models"></datalist>
<button id="external-load-models" type="button">Načíst dostupné modely</button>
<label>Maximum výstupních tokenů <input name="max_output_tokens" type="number" min="1" max="128000" value="4096" required></label>
<label>Timeout v sekundách <input name="timeout_seconds" type="number" min="1" max="180" value="180" required></label>
<label>API klíč <input name="secret" type="password" minlength="20" maxlength="4096" autocomplete="new-password" required></label>
<p><a class="provider-link" href="https://platform.openai.com/api-keys">Vytvořit nebo spravovat klíč u OpenAI ↗</a></p>
<button type="submit">Uložit externí backend</button></form>
<small>Správa klíče se otevře v systémovém prohlížeči; workspace nevidí přihlášení ani vytvořený klíč. Klíč sem potom vložíte jednou, po odeslání se vymaže z formuláře a server jej nikdy nevrací. Externí volání bude dostupné až po samostatném náhledu a potvrzení.</small>
<hr><h2>OpenAI Images</h2>
<p id="settings-openai-image-status" role="status">Obrazový binding zatím nebyl načten.</p>
<form id="openai-image-form"><label>Model <input name="model" value="gpt-image-1" maxlength="128" required></label>
<label>Timeout v sekundách <input name="timeout_seconds" type="number" min="1" max="180" value="180" required></label>
<button type="submit">Uložit obrazový binding</button></form>
<small>Použije uložený OpenAI credential, ale samostatný Images endpoint, model a binding. Klíč se do formuláře ani odpovědi nevrací.</small>
<section id="backend-metrics" hidden><hr><h2>Spotřeba a náklady OpenAI</h2>
<p id="backend-metrics-status" role="status">Účetní přehled zatím nebyl načten.</p>
<form id="backend-metrics-form"><label>OpenAI Admin API klíč
<input name="secret" type="password" autocomplete="new-password" maxlength="4096"></label>
<button type="submit">Uložit administrátorský klíč</button>
<button id="backend-metrics-refresh" type="button">Načíst posledních 30 dní</button></form>
<pre id="backend-metrics-report" hidden></pre></section>
</section>
<section id="settings-cms-panel" class="settings-card cms-card" role="tabpanel" aria-labelledby="settings-cms-tab" hidden>
<h2>Publikační CMS</h2>
<p id="cms-status" role="status" aria-live="polite">Modul zatím nebyl načten.</p>
<h3>Dostupné moduly</h3><div id="cms-module-list"></div>
<div id="cms-module" class="module-card">
<button id="cms-enable" type="button" hidden>Povolit modul</button>
<button id="cms-disable" type="button" hidden>Zakázat modul</button></div>
<small>Workspace moduly automaticky detekuje, ale nikdy je bez výslovného povolení nespustí. Kompatibilita se řídí verzí reviewovaného manifestu, ne Git commitem. Nastavení CMS zatím platí pro celý uzel.</small>
<div id="cms-editor" hidden>
<hr><h3>Domény a povolené části</h3>
<p>Každá doména může zveřejnit vlastní kombinaci částí. Vypnutí části její rozepsaný obsah nesmaže.</p>
<div class="cms-domain-row"><label>Doména <select id="cms-hostname"></select></label>
<button id="cms-remove-domain" type="button">Odebrat doménu</button></div>
<div class="cms-domain-row"><label>Nová doména <input id="cms-new-hostname" maxlength="253" placeholder="example.cz"></label>
<button id="cms-add-domain" type="button">Přidat doménu</button></div>
<fieldset id="cms-sections"><legend>Povolené části této domény</legend>
<label><input id="cms-section-profile" type="checkbox" value="profile"> Profil <small>O mně, kontakt a odkazy</small></label>
<label><input id="cms-section-cv" type="checkbox" value="cv"> CV</label>
<label><input id="cms-section-timeline" type="checkbox" value="timeline"> Timeline</label></fieldset>
<label>Název <input id="cms-title" maxlength="128"></label>
<label>Popis <textarea id="cms-description" rows="3" maxlength="512"></textarea></label>
<label>Katalog <select id="cms-catalog-kind"><option value="sandbox">Sandbox projekty</option><option value="realized">Realizované projekty</option><option value="both">Obojí</option></select></label>
<label>Nadpis katalogu <input id="cms-catalog-title" maxlength="128"></label>
<label>Kontakty <textarea id="cms-contacts" rows="3" placeholder="Popisek | https://… nebo mailto:…"></textarea></label>
<label>Odkazy <textarea id="cms-links" rows="3" placeholder="Popisek | https://…"></textarea></label>
<label>CV <textarea id="cms-cv" rows="4" placeholder="Období | Název | Popis"></textarea></label>
<label>Timeline <textarea id="cms-timeline" rows="5" placeholder="Datum | Název | Popis | volitelné https://…"></textarea></label>
<div class="cms-actions"><button id="cms-preview-button" type="button">Vytvořit náhled</button></div>
<div id="cms-preview" hidden><h3>Přesný náhled požadavku</h3><pre id="cms-request-preview"></pre>
<iframe id="cms-preview-frame" sandbox title="Náhled statické stránky"></iframe>
<label class="confirm"><input id="cms-confirm" type="checkbox"> Potvrzuji vygenerování statických výstupů všech uvedených domén z tohoto náhledu.</label>
<button id="cms-generate-button" type="button" disabled>Vygenerovat statické weby</button></div>
<hr><h3>Cloudflare deployment</h3>
<p>Jeden portál používá jeden existující Worker pro všechny uvedené domény. Token zůstává pouze na tomto uzlu; připojení Custom Domains a DNS se tímto krokem nemění.</p>
<form id="cms-deployment-form"><input name="portal_id" type="hidden" value="main">
<input name="provider" type="hidden" value="cloudflare">
<label>Cloudflare Account ID <input name="account_id" maxlength="32" pattern="[0-9a-f]{32}" required></label>
<label>Název existujícího Workeru <input name="worker_name" maxlength="63" required></label>
<label>API token <input name="api_token" type="password" autocomplete="new-password" maxlength="4096" required></label>
<button type="submit">Uložit připojení</button>
<button id="cms-deployment-refresh" type="button">Načíst skutečný stav</button></form>
<p id="cms-deployment-status" role="status" aria-live="polite">Cloudflare zatím nebyl načten.</p>
<div id="cms-deployment-domains"></div>
<button id="cms-deployment-preview-button" type="button" hidden>Připravit plán deploymentu</button>
<section id="cms-deployment-preview" hidden><h4>Přesný plán externí změny</h4>
<pre id="cms-deployment-request-preview"></pre>
<label class="confirm"><input id="cms-deployment-confirm" type="checkbox"> Potvrzuji vytvoření nové verze existujícího Workeru a převedení 100 % provozu. Custom Domains ani DNS se nemění.</label>
<button id="cms-deployment-run" type="button" disabled>Nasadit potvrzený release</button></section>
</div>
</section>
<section id="settings-access-panel" class="settings-card" role="tabpanel" aria-labelledby="settings-access-tab" hidden>
<h2>Dostupnost aplikace</h2>
<p id="application-access-runtime">Určuje, ze kterých adres lze navázat spojení s touto aplikací. Přihlášení a HTTPS zůstávají povinné ve všech režimech.</p>
<form id="application-access-form">
<label>Rozsah dostupnosti <select name="mode">
<option value="localhost">Pouze localhost</option>
<option value="private-network">Lokální / privátní síť</option>
<option value="allowlist">Pouze povolené adresy</option>
<option value="unrestricted">Neomezeně</option>
</select></label>
<label id="application-access-allowed-row" hidden>Povolené IP adresy a sítě, jedna na řádek
<textarea name="allowed" rows="7" placeholder="192.0.2.10&#10;10.20.0.0/16&#10;2001:db8::/48"></textarea></label>
<p id="application-access-context" class="settings-note"></p>
<button id="application-access-preview-button" type="submit">Zkontrolovat změnu</button>
<p id="application-access-status" role="status" aria-live="polite"></p>
</form>
<section id="application-access-preview" hidden><h3>Přesný náhled změny</h3>
<pre id="application-access-plan"></pre>
<label class="confirm"><input id="application-access-confirm" type="checkbox"> Potvrzuji tento rozsah dostupnosti a beru na vědomí možné odpojení současného klienta.</label>
<button id="application-access-save" type="button" disabled>Uložit dostupnost</button></section>
<small>Politika se ukládá pouze na tomto uzlu. Skutečnou dosažitelnost může dále zúžit naslouchací adresa služby, firewall nebo síťová trasa.</small>
</section>
<section id="settings-profile-panel" class="settings-card" role="tabpanel" aria-labelledby="settings-profile-tab" hidden>
<h2>Uživatelský profil</h2><p>Jméno a kontakty pro závěrečný slide prezentace. Platí pro tohoto uživatele desktopu.</p>
<p>Údaje zůstávají v lokálním profilu tohoto uzlu; do projektu se neukládají ani nesynchronizují.</p>
<form id="user-profile-form">
<label>Jméno <input name="name" maxlength="100" autocomplete="name"></label>
<label>E-mail <input name="email" inputmode="email" maxlength="180" autocomplete="email"></label>
<label>Telefon <input name="phone" type="tel" maxlength="80" autocomplete="tel"></label>
<label>Web <input name="web" inputmode="url" maxlength="200" autocomplete="url"></label>
<button type="submit">Uložit profil</button>
<p id="user-profile-status" role="status" aria-live="polite"></p></form></section>
'''+ ADMIN_HTML + '''
<button id="settings-back" class="back-button" type="button">← Zpět</button>
</div>
<div id="source-import-view" hidden>
<header><span class="badge">Podklady projektu</span><span>Původní bajty a doložená metadata</span></header>
<div class="page-heading"><div class="eyebrow">IMPORT ZDROJE</div><h1 id="source-import-heading" tabindex="-1">Importovat zdroj</h1>
<p>Zdroj se uloží jako neměnný podklad. Nová verze se importuje jako nový zdroj.</p></div>
<section id="google-drive-import" class="standalone-form"><h2>Google Drive</h2>
<p>Průvodce vás provede připojením, výběrem a kontrolou. Do projektu se nic neuloží bez posledního potvrzení.</p>
<ol id="google-drive-steps" class="import-steps" aria-label="Postup importu z Google Drive">
<li data-step="1" aria-current="step"><span>1</span><strong>Připojení</strong><small>Připravenost Google OAuth</small></li>
<li data-step="2"><span>2</span><strong>Výběr</strong><small>Soubory nebo jedna složka</small></li>
<li data-step="3"><span>3</span><strong>Kontrola</strong><small>Formát, revize a privacy</small></li>
<li data-step="4"><span>4</span><strong>Import</strong><small>Jediné potvrzené uložení</small></li></ol>
<section id="google-drive-connect-step" class="wizard-callout"><h3>1. Připravte připojení</h3>
<p id="google-drive-connect-copy">Ověřuji, zda je Google Drive na tomto uzlu připravený.</p>
<button id="google-drive-open-settings" class="secondary-button" type="button" hidden>Nastavit připojení</button></section>
<section id="google-drive-select-step"><h3>2. Vyberte, co chcete přidat</h3>
<div class="google-login-guide"><h4>Jak přihlášení proběhne</h4><ol>
<li>V systémovém prohlížeči nebo nové kartě se otevře přihlášení přímo u Googlu.</li>
<li>Vyberete účet a povolíte přístup jen k souborům, které zvolíte pro tuto aplikaci.</li>
<li>Vyberete jednotlivé soubory nebo jednu složku a vrátíte se sem ke kontrole.</li></ol>
<p><strong>Google heslo zadáváte jen Googlu.</strong> Workspace je neuvidí, do Drive nic nezapisuje a bez závěrečného potvrzení nezmění ani projekt.</p></div>
<label>Soukromí <select id="google-drive-privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option id="google-drive-local-only" value="local-only">Pouze lokální</option><option value="public">Veřejné</option></select></label>
<button id="google-drive-select" type="button">Přihlásit se ke Googlu a vybrat…</button>
<button id="google-drive-recover" class="secondary-button" type="button" hidden>Pokračovat v potvrzeném importu</button>
<p id="google-drive-status" role="status" aria-live="polite">Načítám stav připojení…</p></section>
<section id="google-drive-preview" hidden><h3>3. Zkontrolujte vybrané položky</h3>
<p id="google-drive-summary" class="wizard-summary"></p><ul id="google-drive-files" class="wizard-file-list"></ul>
<details><summary>Technické podrobnosti a provenance</summary><pre id="google-drive-plan"></pre></details>
<h3>4. Potvrďte import</h3>
<label class="confirm"><input id="google-drive-confirm-check" type="checkbox"> Potvrzuji cílový projekt, privacy, soubory, případné PDF exporty a uvedené limity.</label>
<button id="google-drive-run" type="button" disabled>Importovat potvrzený výběr</button></section></section>
<h2 class="import-divider">Soubor z tohoto zařízení</h2>
<form id="source-import-form" class="standalone-form"><label>Soubor <input name="file" type="file" accept=".md,.png,.jpg,.jpeg,.pdf" required></label>
<label>Název <input name="title" maxlength="200" required></label>
<label>Popis <textarea name="description" rows="3"></textarea></label>
<label>Štítky, jeden na řádek <textarea name="tags" rows="2"></textarea></label>
<label>Doložený čas vzniku zdroje (UTC) <input name="source_created_at" maxlength="27" placeholder="např. 2024-05-10T14:30:00Z"></label>
<label>Navazuje na předchozí zdroj <select name="supersedes" id="source-import-supersedes"><option value="">Samostatný zdroj</option></select></label>
<label>Soukromí <select name="privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option id="source-import-local-only" value="local-only">Pouze lokální</option><option value="public">Veřejné</option></select></label>
<p>Markdown, PNG, JPEG a PDF do 16 MiB. Čas importu se uloží automaticky; čas vzniku vyplňte jen tehdy, když jej zdroj dokládá.</p>
<label class="confirm"><input name="confirmed" type="checkbox" required> Potvrzuji import původních bajtů, zvolená metadata a soukromí.</label>
<div class="form-actions"><button type="submit">Importovat původní bajty</button><button id="source-import-back" class="secondary-button" type="button">Zpět do projektu</button></div>
<p id="source-import-status" role="status" aria-live="polite"></p></form>
</div>
<div id="history-view" hidden>
<header><span class="badge">Historie artefaktu</span><span>Uložené Git verze · pouze pro čtení</span></header>
<div class="page-heading"><div class="eyebrow">HISTORIE DOKUMENTU</div><h1 id="history-title">Historie</h1>
<p>Porovnání čte pouze verze dosažitelné z otevřeného HEAD a nemění projekt ani rozepsanou práci.</p></div>
<section class="standalone-form history-form" aria-label="Historie dokumentu">
<p id="history-status" role="status" aria-live="polite"></p>
<div class="history-choices"><label>Starší / výchozí verze <select id="history-older"></select></label>
<label>Zobrazená verze <select id="history-newer"></select></label></div>
<div class="form-actions"><button id="history-compare" type="button">Zobrazit a porovnat</button>
<button id="history-close" class="secondary-button" type="button">Zavřít historii</button></div>
<h2>Obsah zobrazené verze</h2><pre id="history-body"></pre>
<details><summary>Technické údaje</summary><pre id="history-metadata"></pre></details>
<details><summary>Rozdíl uložených souborů</summary><pre id="history-diff"></pre></details>
<details><summary>Záznam uložení</summary><pre id="history-info"></pre></details>
</section></div>
<div id="artifact-editor-view" hidden>
<header><span class="badge">Dokument</span><span id="artifact-editor-mode">Uložený Markdown</span></header>
<div class="page-heading"><div class="eyebrow" id="artifact-editor-eyebrow">UPRAVIT DOKUMENT</div><h1 id="artifact-editor-heading">Dokument</h1></div>
<form id="artifact-editor-form" class="standalone-form"><label>Název <input name="title" maxlength="200" required></label>
<label>Název souboru (.md) <input name="filename" maxlength="200" required></label>
<label>Popis <textarea name="description" rows="3"></textarea></label>
<label>Štítky, jeden na řádek <textarea name="tags" rows="3"></textarea></label>
<label>Obsah <textarea name="body" rows="18" maxlength="1048576" required></textarea></label>
<div class="form-actions"><button type="submit">Uložit</button><button id="artifact-editor-close" class="secondary-button" type="button">Zavřít editor</button></div>
<p id="artifact-editor-status" role="status" aria-live="polite"></p></form>
<section id="artifact-delete-preview" class="standalone-form deletion-preview" hidden><h2>Připravit smazání</h2>
<pre id="artifact-delete-details"></pre><label class="confirm"><input id="artifact-delete-confirm" type="checkbox"> Potvrzuji odstranění dokumentu z aktuální verze projektu. Git historie zůstane zachovaná.</label>
<div class="form-actions"><button id="artifact-delete-run" type="button" disabled>Odstranit dokument</button><button id="artifact-delete-cancel" class="secondary-button" type="button">Zrušit</button></div></section>
</div>
<div id="project-view" hidden>
<header class="project-header"><span class="eyebrow">OTEVŘENÝ PROJEKT</span>
<details><summary>Uložená verze</summary><code id="project-commit"></code></details></header>
<p id="project-read-only" class="read-only-notice" role="status" hidden>Tento projekt je read-only replika. Obsah lze číst, ale místní editory ani publikační akce jej nemohou měnit.</p>
<section id="workspace-panel" aria-label="Pracovní prostor">
<div id="main-tabs" role="tablist" aria-label="Hlavní panel">
<button id="project-overview-tab" role="tab" aria-controls="project-overview-panel" aria-selected="true" data-prompt-default="visible">Projekt</button>
<button id="preview-tab" role="tab" aria-controls="preview-panel" aria-selected="false" data-prompt-default="visible" tabindex="-1">Náhled</button>
<button id="chat-tab" role="tab" aria-controls="chat-panel" aria-selected="false" data-prompt-default="visible" tabindex="-1">Chat</button>
<button id="workflow-tab" role="tab" aria-controls="workflow-panel" aria-selected="false" data-prompt-default="hidden" tabindex="-1">Creator → opponent</button>
<button id="summary-tab" role="tab" aria-controls="summary-panel" aria-selected="false" data-prompt-default="hidden" tabindex="-1">Souhrn</button>
<button id="extraction-tab" role="tab" aria-controls="extraction-panel" aria-selected="false" data-prompt-default="hidden" tabindex="-1">Extrakce</button>
<button id="image-tab" role="tab" aria-controls="image-panel" aria-selected="false" data-prompt-default="hidden" tabindex="-1">Obrázek</button>
<button id="outputs-overview-tab" role="tab" aria-controls="outputs-overview-panel" aria-selected="false" data-prompt-default="hidden" tabindex="-1" hidden>Výstupy</button>
<button id="presentation-tab" role="tab" aria-controls="presentation-panel" aria-selected="false" data-prompt-default="hidden" tabindex="-1">Prezentace</button>
<button id="metadata-tab" role="tab" aria-controls="metadata-panel" aria-selected="false" data-prompt-default="hidden" tabindex="-1">Metadata</button></div>
<div id="main-panel-content">
<div id="project-overview-panel" role="tabpanel" aria-labelledby="project-overview-tab">
<header class="project-overview-heading"><span class="dashboard-kicker">Projekt</span><h1 id="project-title"></h1></header>
<div class="project-overview-grid">
<section class="dashboard-tile project-overview-history"><span class="dashboard-kicker">Poslední aktivita</span>
<h2>Historie změn</h2><p id="project-overview-history-status" role="status">Načítám historii…</p>
<ol id="project-overview-history-list" aria-label="Poslední změny projektu"></ol>
<button id="project-conflicts-open" type="button" class="conflict-button" hidden>Vyřešit konflikt</button></section>
<section class="project-overview-description" aria-label="Stručný popis projektu"><p id="project-description"></p></section>
<section class="dashboard-tile dashboard-tasks project-overview-tasks"><span class="dashboard-kicker">Hlavní seznam</span>
<h2>Úkoly</h2><p id="project-overview-task-status" role="status">Načítám úkoly…</p>
<ul id="project-overview-task-list" aria-label="Nehotové úkoly projektu"></ul>
<button id="project-overview-edit-todo" type="button" class="secondary-button">Upravit seznam úkolů</button></section></div>
<section id="project-conflicts" hidden aria-labelledby="project-conflicts-title">
<button id="project-conflicts-back" type="button" class="back-button">← Zpět na projekt</button>
<span class="dashboard-kicker">FEDEROVANÁ HISTORIE</span><h2 id="project-conflicts-title">Vyřešit konflikt</h2>
<p>Výsledek je zatím pouze místní návrh. Projekt se změní až po kontrole a výslovném potvrzení.</p>
<p id="project-conflicts-status" role="status" aria-live="polite"></p>
<div class="conflict-toolbar"><label>Protější historie <select id="project-conflicts-select"></select></label></div>
<div id="project-conflicts-workspace" hidden>
<h3>Konfliktní soubory</h3><p id="project-conflicts-files-summary"></p>
<ul id="project-conflicts-files" class="conflict-file-list" aria-label="Soubory v konfliktu"></ul>
<p id="project-conflicts-unresolved" role="status"></p>
<label class="confirm"><input id="project-conflicts-confirm" type="checkbox"> Zkontroloval(a) jsem všechny výsledné soubory a potvrzuji vytvoření dvourodičového merge commitu.</label>
<button id="project-conflicts-publish" type="button" disabled>Vytvořit merge commit</button>
</div>
<dialog id="project-conflicts-dialog" class="conflict-dialog" aria-labelledby="project-conflicts-dialog-title">
<div class="conflict-dialog-shell"><header class="conflict-dialog-header"><div><span class="dashboard-kicker">ŘEŠENÍ SOUBORU</span><h2 id="project-conflicts-dialog-title"></h2></div><button id="project-conflicts-dialog-close" type="button" class="secondary-button" aria-label="Zavřít řešitel konfliktu">Zavřít</button></header>
<div class="conflict-toolbar">
<div role="tablist" aria-label="Zobrazení konfliktu"><button id="project-conflicts-raw" type="button" aria-selected="true">Raw</button><button id="project-conflicts-rendered" type="button" class="secondary-button" aria-selected="false">Náhled</button></div></div>
<div id="project-conflicts-raw-panel" class="conflict-grid">
<section class="conflict-pane conflict-local"><header><h3>Lokální verze</h3><span id="project-conflicts-local-summary" class="conflict-summary"></span></header><div class="conflict-code" data-conflict-diff="ours"></div></section>
<section class="conflict-pane conflict-result"><header><h3>Výsledek</h3><span id="project-conflicts-result-summary" class="conflict-summary"></span></header><label class="visually-hidden" for="project-conflicts-result">Výsledný obsah souboru</label><div class="conflict-editor-stack"><pre id="project-conflicts-result-highlight" aria-hidden="true"></pre><textarea id="project-conflicts-result" rows="20" wrap="off" spellcheck="false"></textarea></div></section>
<section class="conflict-pane conflict-remote"><header><h3>Vzdálená verze</h3><span id="project-conflicts-remote-summary" class="conflict-summary"></span></header><div class="conflict-code" data-conflict-diff="theirs"></div></section></div>
<div id="project-conflicts-rendered-panel" class="conflict-grid conflict-rendered" hidden>
<section class="conflict-pane conflict-local"><header><h3>Lokální verze</h3></header><div data-conflict-preview="ours"></div></section>
<section class="conflict-pane conflict-result"><header><h3>Výsledek</h3></header><div data-conflict-preview="result"></div></section>
<section class="conflict-pane conflict-remote"><header><h3>Vzdálená verze</h3></header><div data-conflict-preview="theirs"></div></section></div>
<div class="conflict-legend" aria-label="Legenda rozdílů"><span class="diff-local">Rozdíl vůči lokální verzi</span><span class="diff-remote">Rozdíl vůči vzdálené verzi</span><span class="diff-both">Rozdíl vůči oběma verzím</span></div>
<div class="form-actions"><button id="project-conflicts-use-ours" type="button">Použít lokální</button>
<button id="project-conflicts-use-theirs" type="button">Použít vzdálenou</button>
<button id="project-conflicts-use-both" type="button">Použít obě</button>
<button id="project-conflicts-delete" type="button" class="secondary-button">Výsledný soubor smazat</button></div>
</div></dialog></section></div>
<div id="preview-panel" role="tabpanel" aria-labelledby="preview-tab" hidden>
<p id="preview-status" role="status">Vyberte podklad ze seznamu vlevo.</p>
<h2 id="preview-title"></h2><div id="preview-content"></div>
<div id="pdf-controls" hidden><label for="pdf-page">Stránka PDF (1–100)</label>
<input id="pdf-page" type="number" min="1" max="100" value="1"><button id="pdf-show">Zobrazit stránku</button></div>
<details id="preview-details" hidden><summary>Podrobnosti</summary><dl id="preview-metadata"></dl></details></div>
<div id="chat-panel" role="tabpanel" aria-labelledby="chat-tab" hidden><h2>Chat</h2>
<p id="chat-backend-status" role="status">Načítám stav lokálního backendu…</p>
<section id="chat-delete-preview" class="deletion-preview" hidden aria-label="Náhled smazání vlákna">
<h3>Co bude odstraněno z tohoto uzlu</h3><pre id="chat-delete-details"></pre>
<label class="confirm"><input id="chat-delete-confirm" type="checkbox"> Rozumím, že lokální stav bude odstraněn, ale publikované Git artefakty zůstanou zachované.</label>
<button id="chat-delete-run" type="button" disabled>Odstranit lokální vlákno</button>
<button id="chat-delete-cancel" class="secondary-button" type="button">Zrušit</button></section>
<div id="chat-messages" role="log" aria-label="Vaše zadání"></div>
<div id="chat-stream-status" class="chat-message assistant chat-live-progress" role="status" aria-live="polite" hidden>
<span class="chat-progress-spinner" aria-hidden="true"></span><span id="chat-stream-progress-text"></span></div>
<div id="chat-stream" class="chat-message assistant" aria-live="off" hidden></div>
<button id="search-recovery" class="secondary-button" type="button" hidden>Nastavit SearXNG</button>
<section id="search-preview" hidden aria-label="Náhled webového hledání">
<h3>Přesný webový dotaz před odesláním</h3><pre id="search-preview-content"></pre>
<label class="confirm"><input id="search-confirm-check" type="checkbox"> Potvrzuji odeslání zobrazeného dotazu na uvedený SearXNG endpoint.</label>
<button id="search-confirm" type="button" disabled>Vyhledat a zpracovat přes Ollamu</button>
<button id="search-cancel" class="secondary-button" type="button">Zrušit</button>
</section>
<section id="public-source-preview" hidden aria-label="Náhled načtení veřejného zdroje">
<h3>Přesný plán načtení veřejného zdroje</h3><pre id="public-source-preview-content"></pre>
<label class="confirm"><input id="public-source-confirm-check" type="checkbox"> Potvrzuji oba zobrazené GET účinky, cílovou URL, privacy a limity.</label>
<button id="public-source-confirm" type="button" disabled>Načíst vybranou stránku</button>
<button id="public-source-cancel" class="secondary-button" type="button">Zrušit</button>
<div id="public-source-result" hidden><h3>Čitelný inertní výtah veřejného zdroje</h3>
<div class="public-source-view-tabs" role="group" aria-label="Zobrazení veřejného zdroje">
<button type="button" data-source-view="structured" aria-pressed="true">Strukturovaný výtah</button>
<button type="button" class="secondary-button" data-source-view="text" aria-pressed="false">Původní bounded text</button></div>
<div class="public-source-structured" role="document"></div><pre class="public-source-text" hidden></pre><small></small></div>
</section></div>
<p id="chat-run-usage" hidden></p>
<div id="summary-panel" role="tabpanel" aria-labelledby="summary-tab" hidden><h2>Lokální souhrn</h2>
<p>Vyberte projektové podklady, nebo zprávy aktuálního chatu. Náhled se do projektu uloží až po potvrzení.</p>
<label>Zdroj <select id="summary-kind"><option value="artifacts">Vybrané podklady</option>
<option value="messages">Aktuální chat</option></select></label>
<fieldset id="summary-artifacts"><legend>Podklady</legend><div id="summary-artifact-list"></div></fieldset>
<label for="summary-focus">Zaměření (volitelné)</label>
<textarea id="summary-focus" rows="2" maxlength="16384"></textarea>
<label for="summary-focus-privacy">Soukromí zaměření</label><select id="summary-focus-privacy">
<option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option>
<option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<button id="summary-generate" type="button">Vytvořit náhled</button>
<p id="summary-status" role="status" aria-live="polite"></p>
<div id="summary-preview" aria-label="Náhled souhrnu"></div>
<div id="summary-publish-controls" hidden><label for="summary-title">Název dokumentu</label>
<input id="summary-title" maxlength="200" value="Souhrn projektu">
<button id="summary-publish" type="button">Uložit do projektu</button></div></div>
<div id="workflow-panel" role="tabpanel" aria-labelledby="workflow-tab" hidden><h2>Creator → opponent</h2>
<p>Každý krok má vlastní přesný požadavek a potvrzení. Opponent nedostane historii creatoru, pouze jeho uložený výstup a zde vybrané podklady.</p>
<label for="workflow-purpose">Účel</label><textarea id="workflow-purpose" rows="3" maxlength="16384"></textarea>
<label for="workflow-privacy">Soukromí účelu</label><select id="workflow-privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<label for="workflow-creator-model">Creator model</label><input id="workflow-creator-model" maxlength="128">
<fieldset><legend>Podklady creatoru</legend><div id="workflow-creator-artifacts"></div></fieldset>
<label for="workflow-opponent-model">Opponent model</label><input id="workflow-opponent-model" maxlength="128">
<fieldset><legend>Dodatečné podklady opponenta</legend><div id="workflow-opponent-artifacts"></div></fieldset>
<button id="workflow-prepare" type="button">Připravit creator požadavek</button>
<p id="workflow-status" role="status" aria-live="polite"></p>
<details id="autonomy-queue"><summary>Řízená fronta</summary>
<p>Automatický režim je vždy opt-in. Vytvoření lokálního dokumentu čeká na samostatné potvrzení přesného výstupu.</p>
<details class="autonomy-plan-editor"><summary>Načíst nebo upravit návrh plánu</summary>
<p>Vložte celý návrh JSON. Kontrola jej pouze připraví; nic nespustí ani neuloží do projektu.</p>
<label>Návrh plánu (JSON)<textarea id="autonomy-plan-json" rows="8" spellcheck="false"></textarea></label>
<div class="form-actions"><button id="autonomy-plan-example" class="secondary-button" type="button">Vložit statický read-only příklad</button><button id="autonomy-plan-dynamic-example" class="secondary-button" type="button">Vložit dynamický read-only příklad</button><button id="autonomy-plan-check" type="button">Zkontrolovat návrh</button></div></details>
<div class="form-actions"><button id="autonomy-refresh" class="secondary-button" type="button">Obnovit</button><button id="autonomy-global-pause" class="secondary-button" type="button">Pozastavit vše</button></div>
<p id="autonomy-status" role="status" aria-live="polite">Otevřením načtete frontu tohoto projektu.</p><div id="autonomy-list"></div></details>
<section id="workflow-creator-preview" hidden><h3>Creator — přesný požadavek</h3><pre></pre>
<label class="confirm"><input id="workflow-creator-confirm" type="checkbox"> Potvrzuji creator vstupy, model, privacy a přesný request.</label>
<button id="workflow-creator-dispatch" type="button" disabled>Spustit creatora</button></section>
<section id="workflow-creator-result" hidden><h3>Materializovaný creator výstup</h3><pre></pre>
<button id="workflow-opponent-prepare" type="button">Připravit opponent handoff</button></section>
<section id="workflow-opponent-preview" hidden><h3>Opponent — přesný handoff</h3><pre></pre>
<label class="confirm"><input id="workflow-opponent-confirm" type="checkbox"> Potvrzuji předaný creator výstup, podklady, model a privacy.</label>
<button id="workflow-opponent-dispatch" type="button" disabled>Spustit opponenta</button></section>
<section id="workflow-opponent-result" hidden><h3>Materializovaná oponentura</h3><pre></pre></section>
<section id="workflow-publish" hidden><h3>Uložit vybraný výsledek</h3>
<label for="workflow-publish-step">Výsledek</label><select id="workflow-publish-step"></select>
<label for="workflow-title">Název dokumentu</label><input id="workflow-title" maxlength="200" value="Oponentura návrhu">
<button id="workflow-publish-button" type="button">Uložit do projektu</button></section></div>
<div id="extraction-panel" role="tabpanel" aria-labelledby="extraction-tab" hidden><h2>Strukturovaná extrakce</h2>
<p>Vyberte podklady a uzavřené schéma. Náhled se uloží až po potvrzení.</p>
<label>Schéma <select id="extraction-schema"><option value="facts|facts-v1">Fakta</option>
<option value="action-items|action-items-v1">Akční položky</option></select></label>
<label>Zdroj <select id="extraction-kind"><option value="artifacts">Vybrané podklady</option>
<option value="messages">Aktuální chat</option></select></label>
<fieldset id="extraction-artifacts"><legend>Podklady</legend><div id="extraction-artifact-list"></div></fieldset>
<label for="extraction-focus">Zaměření (volitelné)</label><textarea id="extraction-focus" rows="2" maxlength="16384"></textarea>
<label for="extraction-focus-privacy">Soukromí zaměření</label><select id="extraction-focus-privacy">
<option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option>
<option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<button id="extraction-generate" type="button">Vytvořit náhled</button>
<p id="extraction-status" role="status" aria-live="polite"></p>
<pre id="extraction-preview" aria-label="Náhled extrakce"></pre>
<div id="extraction-publish-controls" hidden><label for="extraction-title">Název zdroje</label>
<input id="extraction-title" maxlength="200" value="Strukturovaná extrakce">
<button id="extraction-publish" type="button">Uložit do projektu</button></div></div>
<div id="image-panel" role="tabpanel" aria-labelledby="image-tab" hidden><h2>Generování obrázku</h2>
<p>Nejdřív zkontrolujete přesný požadavek. Provider se zavolá až po samostatném potvrzení a výsledek se uloží do projektu až dalším krokem.</p>
<label for="image-adapter">Backend</label><select id="image-adapter"><option value="comfyui">ComfyUI</option><option value="openai-images">OpenAI Images</option></select>
<label for="image-prompt">Prompt</label><textarea id="image-prompt" rows="5" maxlength="32768"></textarea>
<label for="image-size">Rozměr</label><select id="image-size"><option value="1024x1024">1024 × 1024</option><option value="1536x1024">1536 × 1024</option><option value="1024x1536">1024 × 1536</option></select>
<label for="image-quality">Kvalita</label><select id="image-quality"><option value="auto">Auto</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select>
<label for="image-seed">Seed pro ComfyUI</label><input id="image-seed" type="number" min="0" step="1" value="0">
<label for="image-privacy">Soukromí</label><select id="image-privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<button id="image-preview-button" type="button">Připravit přesný požadavek</button>
<p id="image-status" role="status" aria-live="polite"></p>
<section id="image-request-preview" hidden><h3>Požadavek před odesláním</h3><pre id="image-request-json"></pre>
<label class="confirm"><input id="image-confirm" type="checkbox"> Potvrzuji tento prompt, backend, parametry a privacy.</label>
<button id="image-dispatch" type="button" disabled>Vygenerovat obrázek</button></section>
<section id="image-result" hidden><h3>Validovaný výsledek</h3><img id="image-result-preview" alt="Náhled vygenerovaného obrázku">
<pre id="image-result-metadata"></pre><label for="image-title">Název artefaktu</label>
<input id="image-title" maxlength="200" value="Vygenerovaný obrázek">
<button id="image-publish" type="button">Uložit do projektu</button></section></div>
<div id="outputs-overview-panel" role="tabpanel" aria-labelledby="outputs-overview-tab" hidden>
<header class="outputs-overview-heading"><span class="dashboard-kicker">VERZOVANÉ DEFINICE</span><h2>Výstupy projektu</h2>
<p>Web zobrazuje přesně uložené definice výstupů aktuálního commitu. Úpravy, spuštění presenteru a lokální export zůstávají v desktopové aplikaci.</p></header>
<p id="outputs-overview-status" role="status" aria-live="polite">Otevřete kategorii Výstupy.</p>
<div class="outputs-overview-grid"><ul id="outputs-overview-list" aria-label="Definice výstupů projektu"></ul>
<section id="outputs-overview-detail" class="outputs-overview-detail" aria-labelledby="outputs-overview-detail-title" hidden>
<span class="dashboard-kicker">DEFINICE</span><h3 id="outputs-overview-detail-title"></h3><dl id="outputs-overview-properties"></dl>
</section></div></div>
<div id="presentation-panel" role="tabpanel" aria-labelledby="presentation-tab" hidden>
<div class="presentation-editor-head"><div><h2>Prezentace</h2><p>Editor, náhled i spuštění používají stejný deck otevřeného projektu.</p></div>
<div class="form-actions"><label>Uložená prezentace <select id="presentation-editor-documents"></select></label><button id="presentation-editor-new" type="button">Nová</button><button id="presentation-editor-reload" class="secondary-button" type="button">Znovu načíst</button></div></div>
<div id="presentation-editor-workspace" class="presentation-editor-workspace" hidden>
<section class="presentation-editor-slides"><label>Název prezentace <input id="presentation-deck-title" maxlength="200"></label><h3>Slidy</h3><ol id="presentation-slide-list"></ol>
<div class="form-actions"><button id="presentation-add-main" type="button">+ Hlavní</button><button id="presentation-add-backup" type="button">+ Backup</button><button id="presentation-delete-slide" class="danger-button" type="button">Odstranit</button></div>
<details class="presentation-template-manager"><summary>Šablony layoutu</summary><label>Upravit šablonu <select id="presentation-template-select"></select></label>
<div class="form-actions"><button id="presentation-template-copy" type="button">Nová kopie</button><button id="presentation-template-reset" class="secondary-button" type="button">Výchozí vzhled</button><button id="presentation-template-delete" class="danger-button" type="button">Odstranit</button></div>
<label>Název šablony <input id="presentation-template-name" maxlength="80"></label><label>Typ rozložení <select id="presentation-template-preset"><option value="title">Titulní</option><option value="title-content">Nadpis a obsah</option><option value="two-column">Dva sloupce</option><option value="visual">Obrázek / graf</option><option value="closing">Závěrečný</option></select></label>
<label>Zarovnání nadpisu <select id="presentation-template-title-align"><option value="left">Vlevo</option><option value="center">Na střed</option><option value="right">Vpravo</option></select></label><label>Zarovnání obsahu <select id="presentation-template-content-align"><option value="left">Vlevo</option><option value="center">Na střed</option><option value="right">Vpravo</option></select></label>
<label>Hustota <select id="presentation-template-density"><option value="compact">Kompaktní</option><option value="normal">Běžná</option><option value="spacious">Vzdušná</option></select></label><div class="presentation-template-colors"><label>Pozadí <input id="presentation-template-background" type="color"></label><label>Text <input id="presentation-template-foreground" type="color"></label><label>Akcent <input id="presentation-template-accent" type="color"></label></div></details></section>
<section class="presentation-editor-fields"><h3 id="presentation-slide-kind">Hlavní slide</h3><label>Layout <select id="presentation-slide-layout"></select></label><label id="presentation-column-break-label" hidden>Levý sloupec – počet odrážek <input id="presentation-column-break" type="number" min="0" max="12" value="0"><small>0 rozdělí odrážky automaticky.</small></label><label>Nadpis <input id="presentation-slide-title" maxlength="200"></label>
<label>Odrážky, jedna na řádek <textarea id="presentation-slide-bullets" rows="7" maxlength="6012"></textarea></label><label>Soukromé poznámky <textarea id="presentation-slide-notes" rows="4" maxlength="10000"></textarea></label>
<div class="presentation-editor-options"><label><input id="presentation-slide-repeat" type="checkbox"> Povolit opakované promítnutí</label><label>Zobrazení <select id="presentation-slide-reveal"><option value="all">Vše najednou</option><option value="step">Postupně</option></select></label>
<label>Pozadí <input id="presentation-slide-background" type="color"></label><label>Text <input id="presentation-slide-foreground" type="color"></label></div>
<label>Tapeta PNG <input id="presentation-slide-wallpaper" type="file" accept="image/png"></label><button id="presentation-clear-wallpaper" class="secondary-button" type="button">Odebrat tapetu</button>
<fieldset><legend>Zařazení a vazby</legend><div class="form-actions"><button id="presentation-slide-up" class="secondary-button" type="button">↑ Dříve</button><button id="presentation-slide-down" class="secondary-button" type="button">↓ Později</button></div><div id="presentation-backup-links"></div></fieldset></section>
<section class="presentation-editor-preview"><h3>Náhled slidu</h3><div id="presentation-editor-preview" class="presenter-slide-preview"></div><p>Náhled nepřenáší soukromé poznámky do veřejného okna.</p></section></div>
<section id="presentation-session-section" class="presentation-session-section"><div><h3>Uskutečněné relace</h3><p>Každý záznam obsahuje jen skutečně potvrzené veřejné výstupy.</p></div><ul id="presentation-session-list"></ul><p id="presentation-session-status" role="status"></p></section>
<div class="presentation-editor-footer"><p id="presentation-editor-status" role="status" aria-live="polite">Otevřete editor.</p><div class="form-actions"><button id="presentation-editor-print" class="secondary-button" type="button" disabled>Vytisknout prezentaci</button><button id="presentation-editor-save" type="button" disabled>Uložit do projektu</button><button id="presentation-editor-use" type="button" disabled>Spustit uloženou prezentaci</button><button id="presentation-editor-presenter" class="secondary-button" type="button">Otevřít presenter</button></div></div></div>
<dialog id="presentation-print-dialog"><form method="dialog"><h2>Export prezentace do PDF</h2><pre id="presentation-print-details"></pre><p id="presentation-print-warning"></p><p id="presentation-print-target">Cíl PDF zatím není vybraný.</p><button id="presentation-print-choose" type="button">Vybrat cílový PDF soubor</button><label class="confirm"><input id="presentation-print-confirm" type="checkbox" disabled> Potvrzuji uvedený režim, zdrojovou revizi, pořadí stran, cíl a případné přepsání.</label><div class="form-actions"><button id="presentation-print-run" type="button" disabled>Vytvořit PDF</button><button value="cancel" class="secondary-button">Zrušit</button></div></form></dialog>
<div id="presentation-print-view" aria-hidden="true"></div>
<div id="metadata-panel" role="tabpanel" aria-labelledby="metadata-tab" hidden><h2>Návrh popisu a štítků</h2>
<p>Vyberte jeden artefakt. Návrh projekt nezmění, dokud nepotvrdíte konkrétní pole.</p>
<label for="metadata-artifact">Artefakt</label><select id="metadata-artifact"></select>
<button id="metadata-generate" type="button">Navrhnout metadata</button>
<p id="metadata-status" role="status" aria-live="polite"></p>
<div id="metadata-diff" hidden><section><h3>Popis</h3><p id="metadata-description-before"></p>
<label><input id="metadata-apply-description" type="checkbox"><span id="metadata-description-after"></span></label></section>
<fieldset><legend>Navržené nové štítky</legend><div id="metadata-tag-list"></div></fieldset>
<button id="metadata-publish" type="button">Použít vybrané změny</button></div></div></div>
<section id="prompt-widget" aria-label="Prompt"><form id="chat-composer">
<label class="prompt-draft-control" for="chat-draft"><span>Zadání</span>
<textarea id="chat-draft" rows="2" maxlength="16000" placeholder="Co chcete zpracovat?"></textarea></label>
<div class="prompt-toolbar">
<label class="prompt-control" for="chat-mode"><span>Režim</span><select id="chat-mode"><option value="orchestration">Úkol</option><option value="brainstorming">Volná konverzace</option></select></label>
<div id="task-routing" class="prompt-routing-controls">
<details id="task-inputs" class="prompt-input-picker"><summary><span>Vstupy</span><output id="task-input-count">1</output></summary>
<div class="prompt-input-menu"><fieldset><legend>Vybrané zdroje</legend>
<label id="task-source-current-prompt" hidden><input type="checkbox" checked disabled> Aktuální zadání (povinné pro vyhledávání)</label>
<label id="task-source-current-file" hidden><input id="task-source-current-file-input" type="checkbox"> <span id="task-source-current-file-title">Aktuální soubor</span></label>
<label id="task-source-conversation-label"><input id="task-source-conversation" type="checkbox" checked> Aktuální konverzace</label>
<label id="task-source-artifacts-label"><input id="task-source-artifacts" type="checkbox"> Podklady projektu</label>
<details id="task-artifacts" hidden><summary>Vybrat konkrétní podklady</summary><fieldset><legend>Explicitně předat lokálnímu modelu</legend><div id="task-artifact-list"></div></fieldset></details>
<label id="task-source-public-label"><input id="task-source-public" type="checkbox"> Veřejný web / načtené zdroje</label>
<fieldset id="task-public-sources" hidden><legend>Již načtené veřejné zdroje</legend><div id="task-public-source-list"></div></fieldset>
</fieldset></div></details>
<label class="prompt-control" for="task-action"><span>Akce</span><select id="task-action"><option value="answer">Odpovědět</option><option value="search">Vyhledat na webu</option></select></label>
<span class="prompt-route-arrow" aria-hidden="true">→</span>
<label class="prompt-control" for="task-output-kind"><span>Výsledek</span><select id="task-output-kind"><option value="conversation">Konverzace</option><option value="document">Dokument</option><option value="presentation">Prezentace</option></select></label>
</div>
<label class="prompt-control prompt-privacy-control" for="chat-privacy"><span>Soukromí</span><select id="chat-privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select></label>
<label class="prompt-control" for="chat-response-language"><span>Jazyk</span><select id="chat-response-language"><option value="">Výchozí · cs-CZ</option><option value="cs-CZ">Čeština · cs-CZ</option><option value="en-US">English · en-US</option><option value="de-DE">Deutsch · de-DE</option><option value="sk-SK">Slovenčina · sk-SK</option></select></label>
<div class="prompt-execution-controls" aria-label="Cíl běhu">
<label class="prompt-control" for="chat-run-adapter"><span>Backend</span><select id="chat-run-adapter"><option value="ollama">Lokální Ollama</option><option value="openai-responses">OpenAI</option></select></label>
<label class="prompt-control" for="chat-run-model"><span>Model</span><input id="chat-run-model" maxlength="128" list="external-models"></label>
</div>
<button id="chat-submit" type="submit" aria-label="Zpracovat zadání" title="Zpracovat zadání (Enter) · nový řádek (Shift+Enter)" disabled>↑</button>
</div>
<p id="chat-orchestration-target" role="status" aria-live="polite"></p>
<details id="advanced-external" hidden aria-hidden="true"><summary>Pokročilé ruční externí volání</summary>
<button id="external-propose-button" type="button" disabled>Navrhnout přes Ollamu</button>
<button id="external-preview-button" type="button" disabled>Připravit pro OpenAI</button>
<section id="external-proposal" hidden aria-label="Návrh externího volání">
<h3>Návrh Ollamy</h3><p id="external-proposal-purpose"></p>
<fieldset><legend>Zprávy navržené k odeslání</legend><div id="external-proposal-messages"></div></fieldset>
<button id="external-proposal-use" type="button">Připravit upravený externí náhled</button>
<button id="external-proposal-cancel" class="secondary-button" type="button">Zahodit návrh</button>
</section></details>
<p id="chat-operation-status" role="status" aria-live="polite"></p>
<section id="external-preview" hidden aria-label="Náhled externího odeslání">
<h3>Co bude odesláno externímu provideru</h3>
<pre id="external-preview-content"></pre>
<label><input id="external-privacy-confirm" type="checkbox"> Potvrzuji odeslání zobrazených dat a uvedené úrovně soukromí.</label>
<button id="external-confirm" type="button" disabled>Odeslat do OpenAI</button>
<button id="external-cancel" class="secondary-button" type="button">Zrušit</button>
</section>
</form></section>
</section>
</div>
<div id="presenter-view" hidden>
<header class="presenter-header"><div class="presenter-header-main"><span class="badge">Presenter · NÁCVIK</span><h1>Disclosure cockpit</h1><p>Demo workspace · Ukázková schůzka · Interní demo · r1</p></div>
<div class="presenter-header-state"><strong id="presenter-live-state">NEAKTIVNÍ</strong><span>Schůzka <b id="presenter-meeting-time">00:00</b></span><span>Odbočka <b id="presenter-branch-time">00:00</b></span><span id="presenter-exposure">Expozice 0 · +0</span><button id="presenter-back" class="back-button" type="button">← Zpět do workspace</button></div></header>
<p id="presenter-status" role="status">Presenter není spuštěný.</p>
<div class="presenter-layout">
<nav class="presenter-deck" aria-label="Pořadí prezentace"><h2>Pořadí prezentace</h2><ol id="presenter-deck-list"></ol><p id="presenter-return-anchor">Návrat: hlavní slide 01</p></nav>
<section class="presenter-audience" aria-label="Náhled veřejného výstupu"><div class="presenter-kicker">ZMENŠENÝ NÁHLED VEŘEJNÉHO VÝSTUPU</div>
<div class="presenter-slide-preview" id="presenter-screen" tabindex="0" aria-live="polite"><p>Spusťte prezentaci.</p></div>
<section class="presenter-notes"><h2>Poznámky k promítanému obsahu</h2><p id="presenter-notes">Poznámky se zobrazí po spuštění.</p><details><summary>Stručná osnova</summary><p id="presenter-outline">Osnova se zobrazí po spuštění.</p></details><p class="presenter-alert" id="presenter-alert">Interní upozornění: soukromý výběr není promítnutý.</p></section>
<div class="presenter-controls"><button id="presenter-prev" type="button" disabled>Předchozí</button><button id="presenter-next" type="button" disabled>Další</button><button id="presenter-fullscreen" type="button" hidden disabled>Displeje a role…</button><button id="presenter-blackout" type="button">Zatemnit</button></div></section>
<aside class="presenter-speaker" aria-label="Soukromý kokpit"><div class="presenter-panel-head"><h2>Soukromý kokpit</h2><p id="presenter-counter">Slide 0 z 0</p></div><section class="presenter-browser"><div class="presenter-tab-row"><div class="presenter-tabs" role="tablist"><button id="presenter-slide-tab" type="button" role="tab" aria-selected="true">K slidu</button><button id="presenter-backup-tab" type="button" role="tab" aria-selected="false">Backupy</button><button id="presenter-question-tab" type="button" role="tab" aria-selected="false">Otázky</button></div><label class="presenter-search" for="presenter-backup-search"><span>Hledat</span><input id="presenter-backup-search" type="search" placeholder="Hledat…"></label></div><p id="presenter-gamepad-status" class="presenter-gamepad-status">Gamepad: čekám.</p>
<details id="presenter-gamepad-settings" class="presenter-gamepad-settings"><summary>Nastavení gamepadu</summary>
<div class="presenter-gamepad-grid"><label class="presenter-gamepad-wide"><input id="presenter-gamepad-enabled" type="checkbox"> Používat gamepad</label>
<label class="presenter-gamepad-wide">Zařízení <select id="presenter-gamepad-device"><option value="">První připojené</option></select></label>
<label>Předchozí / další <input id="presenter-gamepad-history-axis" type="number" min="0" max="31"></label><label><input id="presenter-gamepad-history-invert" type="checkbox"> Obrátit osu</label>
<label>Výběr hlavního slidu <input id="presenter-gamepad-main-axis" type="number" min="0" max="31"></label><label><input id="presenter-gamepad-main-invert" type="checkbox"> Obrátit osu</label>
<label>Přepínání záložek <input id="presenter-gamepad-tabs-axis" type="number" min="0" max="31"></label><label><input id="presenter-gamepad-tabs-invert" type="checkbox"> Obrátit osu</label>
<label>Výběr položky <input id="presenter-gamepad-items-axis" type="number" min="0" max="31"></label><label><input id="presenter-gamepad-items-invert" type="checkbox"> Obrátit osu</label>
<label>Potvrzovací tlačítko <input id="presenter-gamepad-confirm-button" type="number" min="0" max="63"></label><span></span>
<label>Neutrální práh <input id="presenter-gamepad-neutral" type="number" min="0.05" max="0.8" step="0.05"></label><label>Aktivační práh <input id="presenter-gamepad-activation" type="number" min="0.1" max="1" step="0.05"></label></div>
<div class="presenter-gamepad-actions"><button id="presenter-gamepad-refresh" type="button" class="secondary-button">Obnovit zařízení</button><button id="presenter-gamepad-apply" type="button">Použít nyní</button><button id="presenter-gamepad-save" type="button">Uložit na tomto uzlu</button></div>
<p id="presenter-gamepad-settings-status" role="status">Načítám místní nastavení. Použití nyní nic neukládá.</p><output id="presenter-gamepad-live">Živý vstup: čekám na zařízení.</output></details>
<p id="presenter-tab-status">K slide · otázky a doplňky</p>
<div id="presenter-tab-content"><section id="presenter-slide-list"><h3>Současný slide</h3><div id="presenter-preview"></div><h3>Další podle plánu</h3><button id="presenter-planned-slide" class="presenter-backup" type="button" disabled></button><h3>Backupy k aktuálnímu slidu</h3><p id="presenter-slide-backup-status" role="status"></p><ul id="presenter-slide-backups"></ul></section><section id="presenter-backup-list" hidden><p id="presenter-backup-status">Backupy se zobrazí po spuštění.</p><ul id="presenter-backups"></ul></section><section id="presenter-question-list" hidden><h3>Otázky / doplňky</h3><button id="presenter-question" type="button">Doplňující otázka</button><p id="presenter-question-status">Žádná aktivní odbočka.</p></section></div>
</section><section class="presenter-next-selector"><h3 id="presenter-next-title">Další slide podle plánu</h3><div class="presenter-slide-widget"><div class="presenter-slide-preview" id="presenter-private-preview"></div><section class="presenter-notes"><h2>Poznámky k vybranému slidu</h2><p id="presenter-next-notes"></p></section></div><p id="presenter-private-status">Soukromé procházení nemění expozici.</p><button id="presenter-next-preview" type="button">Zobrazit další slide</button><button id="presenter-show-private" type="button" hidden disabled>Zobrazit publiku</button></section></aside>
</div>
<footer class="presenter-footer"><button id="presenter-return" type="button">Návrat na původní slide</button><span>Otázky: <strong id="presenter-question-count">0</strong></span><span>Odložené: <strong>0</strong></span><span id="presenter-blackout-state">Veřejný výstup aktivní</span></footer>
<dialog id="presenter-display-dialog" aria-labelledby="presenter-display-title"><form id="presenter-display-form" method="dialog">
<h2 id="presenter-display-title">Displeje a role prezentace</h2>
<p>Přiřaďte displej řečníkovi a divákům. Ostatní displeje zůstanou nepoužité. Na jednom displeji ponechte veřejný výstup vypnutý.</p>
<label>Řečník — ovládání a poznámky <select name="speaker" required></select></label>
<label>Diváci — schválený slide <select name="audience" required></select></label>
<p id="presenter-display-status" role="status" aria-live="polite"></p>
<div class="form-actions"><button id="presenter-display-identify" type="button" class="secondary-button">Identifikovat displeje</button><button id="presenter-display-cancel" type="button" class="secondary-button">Zrušit</button><button id="presenter-display-apply" type="submit">Použít role</button></div>
</form></dialog>
</div>
</main><script src="/app.js"></script></body></html>'''
CSS = '''*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:#f4f7fa;color:#162638;font:15px system-ui;display:flex;height:100vh;overflow:hidden}
#mobile-sidebar-toggle,#mobile-sidebar-backdrop{display:none}
aside{position:relative;width:292px;height:100vh;min-height:0;box-sizing:border-box;flex-shrink:0;background:#142638;color:#c8d4df;padding:22px 14px;display:flex;flex-direction:column;overflow:hidden}
.brand{display:flex;align-items:center;gap:10px;flex:none;font-weight:750;letter-spacing:2px;color:white;margin-bottom:18px}.brand-mark{font-size:17px}.brand-name{white-space:nowrap}
main{flex:1;min-width:0;padding:26px 32px;overflow:auto}header{display:flex;justify-content:space-between;gap:16px;align-items:center;color:#627183;font-size:12px}
.badge{color:#1c6556;background:#e0efe9;border-radius:20px;padding:8px 13px}.eyebrow{font-size:11px;color:#31796e;font-weight:750;letter-spacing:2px}
h1{font-size:32px;margin:12px 0}h2{font-size:21px}p{line-height:1.6;color:#627183}button,textarea,input{font:inherit}
button{border:0;border-radius:8px;background:#176b60;color:white;font-weight:600;padding:12px 18px;cursor:pointer}
button:hover{background:#12564d}button:disabled{opacity:.5;cursor:default}button:focus-visible,textarea:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #59b6aa;outline-offset:3px}
summary{cursor:pointer}code,li,dd,h1,h2,button{overflow-wrap:anywhere}small{font-size:11px;color:#627183}
#gamepad-list{list-style:none;padding-left:0;margin:12px 0 0;display:flex;flex-direction:column;gap:8px}
#gamepad-list li{background:#edf7f4;border:1px solid #d2e5e0;border-radius:8px;padding:8px 12px;color:#1f3a41}
.home-heading,.settings-heading{margin-top:28px}.home-heading h1{font-size:38px}
.settings-card{max-width:720px;background:white;border:1px solid #dce3e9;border-radius:16px;padding:22px 26px;margin:24px 0}.settings-card label{display:block;margin:12px 0}.settings-card input,.settings-card select,.settings-card textarea{padding:9px;max-width:100%}.settings-card input,.settings-card textarea{width:100%}.settings-card textarea{resize:vertical}.settings-card small{display:block;margin-top:16px}
.settings-card .settings-toggle{display:flex;align-items:center;gap:9px}.settings-card .settings-toggle input{width:auto}
.cms-card{max-width:900px}.cms-actions,.cms-domain-row{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:18px 0}.cms-domain-row label{flex:1}.cms-domain-row input,.cms-domain-row select{width:100%}#cms-sections{display:flex;gap:18px;flex-wrap:wrap;margin:18px 0;border:1px solid #dce3e9;border-radius:10px;padding:12px}#cms-sections label{margin:0}#cms-sections input{width:auto}#cms-sections small{display:block;color:#61706d;margin-left:22px}#cms-preview{border-top:1px solid #dce3e9;margin-top:20px;padding-top:14px}#cms-request-preview{white-space:pre-wrap;max-height:260px;overflow:auto;background:#f5f7fb;padding:12px;border-radius:8px}#cms-preview-frame{width:100%;min-height:520px;border:1px solid #bfcdc9;border-radius:10px;background:white}.confirm{padding:12px;background:#fffaf0;border:1px solid #d6b36a;border-radius:8px}.confirm input{width:auto}
.provider-link{color:#176b60;font-weight:600}
.search-sources li{margin:12px 0}.search-sources strong,.search-sources code,.search-sources small{display:block}.search-sources code{margin:4px 0;color:#245c73;white-space:normal}
#public-source-preview pre,#public-source-result pre{max-height:360px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
.public-source-view-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.public-source-view-tabs button{padding:8px 12px}.public-source-structured{max-height:min(58vh,620px);overflow:auto;border:1px solid #dce3e9;border-radius:10px;background:#fff;padding:16px}.public-source-structured h4,.public-source-structured h5,.public-source-structured h6{margin:18px 0 8px;color:#18384a}.public-source-structured>h4:first-child{margin-top:0}.public-source-block{margin:10px 0;overflow-wrap:anywhere}.public-source-block>small{display:block;margin-bottom:4px;color:#657d89}.public-source-block blockquote{margin:8px 0;border-left:3px solid #8db6c8;padding-left:12px}.public-source-block pre{background:#f4f7fa;padding:10px;border-radius:7px}.public-source-list-item{display:grid;grid-template-columns:2rem minmax(0,1fr);gap:4px}.public-source-list-marker{text-align:right;color:#456276}.public-source-table-wrap{overflow:auto;margin:12px 0}.public-source-table{border-collapse:collapse;min-width:min(100%,520px);background:#fff}.public-source-table caption{text-align:left;font-weight:700;margin-bottom:6px}.public-source-table th,.public-source-table td{border:1px solid #bfcdc9;padding:7px 9px;text-align:left;vertical-align:top}.public-source-table th{background:#edf5f3}
.search-budget{font-size:12px;color:#456276}.search-round{border-left:3px solid #8db6c8;margin:12px 0;padding:4px 0 4px 12px}.search-round h4{margin:0 0 4px}.search-round>small,.search-evaluation small{display:block;color:#456276;overflow-wrap:anywhere}.search-evaluation{background:#f4f7fa;border-radius:8px;margin-top:8px;padding:10px}.search-evaluation p{margin:6px 0}.search-autonomy-controls{border:1px solid #bfcdc9;border-radius:9px;padding:10px}.search-autonomy-controls label{margin-right:10px}.search-autonomy{width:100%;border:1px solid #bfcdc9;border-left:5px solid #c69224;border-radius:10px;background:#f8fbfc;padding:12px}.search-autonomy[data-state="countdown"]{border-left-color:#2d8a62}.search-autonomy h4{margin:0 0 8px}.search-autonomy-facts{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 10px;margin:8px 0}.search-autonomy-facts dt{font-weight:700}.search-autonomy-facts dd{margin:0;overflow-wrap:anywhere}.search-autonomy progress{width:100%;accent-color:#176b60}.search-autonomy .task-actions input{min-width:min(28rem,100%);flex:1}.search-next-query{width:100%;display:grid;gap:7px}.research-phases{display:grid;gap:6px;padding:0;list-style:none}.research-phase{border-left:4px solid #8aa1ad;background:#fff;border-radius:7px;padding:7px 9px}.research-phase[data-state="completed"]{border-left-color:#2d8a62}.research-phase[data-state="queued"],.research-phase[data-state="countdown"],.research-phase[data-state="awaiting-approval"]{border-left-color:#c69224}.research-phase[data-state="failed"],.research-phase[data-state="unknown"]{border-left-color:#b74435}.research-phase small{display:block;color:#526575;overflow-wrap:anywhere}.research-revision,.research-draft{border:1px solid #d6b36a;border-radius:8px;background:#fffaf0;padding:10px;margin-top:10px}.research-revision code{display:block;overflow-wrap:anywhere}.research-draft pre{max-height:360px;overflow:auto;white-space:pre-wrap;background:#fff;padding:10px;border-radius:7px}
#resource-monitor{flex:none;margin-top:10px;border-top:1px solid #365066;padding-top:9px}
#resource-monitor-open{display:block;width:100%;padding:8px 9px;border:1px solid #365066;background:#0f2030;color:#dce8f1;text-align:left}
#resource-monitor-open:hover{background:#1c3549}#resource-monitor-open>*{pointer-events:none}
.sidebar-utility-icon{display:none;width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
#sidebar-layout-toggle,#logout{flex:none;width:100%;margin-top:8px;padding:9px}#sidebar-layout-toggle{display:flex;align-items:center;justify-content:center;gap:8px;background:#20384b}#sidebar-layout-toggle:hover{background:#29485f}#sidebar-layout-toggle .sidebar-utility-icon{display:block;width:18px;height:18px}
#sidebar-project-recover{margin:0 0 8px;padding:8px;font-size:11px;background:#8a642c}
.resource-monitor-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;font-size:11px;text-transform:uppercase;letter-spacing:.08em}.resource-monitor-heading small{font-size:9px;text-transform:none;letter-spacing:0;color:#8faabc}
#backend-metrics-indicator,#local-provider-indicator{display:block;margin-bottom:4px;color:#9fcfc2;font-size:9px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}#local-provider-indicator{color:#aabecf}
.resource-mini-row{display:grid;grid-template-columns:32px minmax(0,1fr) 12px;gap:5px;align-items:center;margin:2px 0;font-size:8px;color:#9eb5c7}.resource-mini-row progress{width:100%;height:5px;accent-color:#79c9ac}.resource-mini-row output{text-align:right;color:#7891a3}
#resource-monitor-dialog{width:min(760px,calc(100vw - 32px));max-height:calc(100vh - 32px);padding:22px;border:1px solid #9babb7;border-radius:16px;color:#162638;background:#f8fbfd;box-shadow:0 18px 60px #07131f66;overflow:auto}
#project-registration-remove-dialog{width:min(560px,calc(100vw - 32px));padding:22px;border:1px solid #9babb7;border-radius:16px;color:#162638;background:#f8fbfd;box-shadow:0 18px 60px #07131f66}#project-registration-remove-dialog::backdrop{background:#07131fa8}#project-registration-remove-dialog h2{margin-top:0}#project-registration-remove-dialog code{overflow-wrap:anywhere}
#project-registration-remove-confirm{background:#8b3030}
#resource-monitor-dialog::backdrop{background:#07131fa8}.resource-dialog-heading{display:flex;justify-content:space-between;align-items:flex-start;gap:18px}.resource-dialog-heading h2{margin:5px 0 12px}.resource-dialog-heading button{flex:none}
#resource-monitor-dialog>section{margin-top:16px;padding:15px;border:1px solid #dce5eb;border-radius:12px;background:white}#resource-monitor-dialog h3{margin:0 0 12px}
#resource-provider-list{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}#resource-provider-list article{padding:12px;border:1px solid #dce5eb;border-radius:10px}#resource-provider-list p{margin:5px 0;font-size:12px}
.resource-placeholder-note{margin:0;color:#6e7d8a}#system-monitor-detail{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}.resource-detail-row{display:grid;grid-template-columns:48px minmax(0,1fr) 92px;gap:8px;align-items:center;padding:8px;border-radius:8px;background:#f3f6f8;font-size:12px}.resource-detail-row progress{width:100%;accent-color:#79c9ac}.resource-detail-row output{text-align:right;color:#73818e}
#settings-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 8px}#settings-tabs button[aria-selected="false"]{background:#e8eef2;color:#304657}
.visually-hidden{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
#dashboard-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-template-rows:repeat(2,minmax(230px,1fr));gap:16px;min-height:min(640px,calc(100vh - 150px))}
#project-cards{display:contents}.dashboard-tile,.project-card{min-width:0;min-height:0;border:1px solid #dce5eb;border-radius:16px;padding:20px;background:white;color:#162638;box-shadow:0 5px 20px #18364808;text-align:left;overflow:auto}
button.dashboard-tile,button.project-card{display:flex;flex-direction:column;align-items:flex-start;gap:12px}
button.dashboard-tile:hover,button.project-card:hover{background:#fafffd;border-color:#4b9e8c;box-shadow:0 8px 24px #18364812}
.dashboard-kicker{display:block;color:#31796e;font-size:11px;font-weight:750;letter-spacing:.09em;text-transform:uppercase}.dashboard-tile>strong,.project-card .project-name{display:block;font-size:21px;line-height:1.3}.dashboard-tile p{font-size:13px;margin:8px 0}.dashboard-placeholder{background:#f8fafb}.dashboard-placeholder>strong{font-size:24px}.dashboard-action #dashboard-trash-summary{margin-top:auto;color:#627183;font-size:12px;font-weight:500}
.dashboard-tasks{display:flex;flex-direction:column}.dashboard-tasks h2{margin:6px 0 0}.dashboard-tasks>p{margin:0}.dashboard-tasks ul{list-style:none;padding:0;margin:8px 0 0;overflow:auto;min-height:0}.dashboard-task-row{border-top:1px solid #e2e8ec}.dashboard-task-row button{width:100%;padding:10px 4px;background:transparent;color:#162638;text-align:left}.dashboard-task-row button:hover{background:#edf7f4}.dashboard-task-row span,.dashboard-task-row small{display:block}.dashboard-task-row small{margin-top:3px}.project-card .project-meta{margin-top:auto;color:#627183;font-size:12px;font-weight:500}.project-card-unavailable{opacity:.68}
.trash-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid #dce5eb}.trash-row code{overflow-wrap:anywhere}.trash-row .danger{background:#8b3030}#project-delete-blockers{color:#8b3030;white-space:pre-wrap}#project-trash-list{margin-top:8px}.project-trash-page{margin-top:18px}
.diagnostics{margin-top:32px;color:#627183;font-size:12px}.diagnostics button{margin:14px 12px 0 0}.diagnostics output{font-size:20px}
aside h2{font-size:16px;color:white}aside p{font-size:12px;color:#aabecf}aside small{color:#aabecf}
#sidebar-project-list,#sidebar-artifact-list,#sidebar-chat-tree,#sidebar-chat-tree ul,#sidebar-presentation-list,#sidebar-tool-list,#sidebar-settings-list,#sidebar-federation-list,#todo-tree{list-style:none;padding:0;margin:14px 0}
#sidebar-project-list button,#sidebar-artifact-list button,#sidebar-chats button,#sidebar-federation-list button{display:block;text-align:left;width:100%;background:transparent;color:#dce8f1;padding:10px 8px;font-size:13px}
#sidebar-project-list button:hover,#sidebar-artifact-list button:hover,#sidebar-chats button:hover,#sidebar-federation-list button:hover{background:#274154}
.sidebar-list-row{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start}.sidebar-list-main{min-width:0}.sidebar-list-main[aria-current="true"]{background:#274154!important;border-left:3px solid #79c9ac}.sidebar-item-id{display:block;font-size:10px;color:#8faabc;margin-top:4px;overflow-wrap:anywhere}
.sidebar-artifact-row{position:relative}.sidebar-artifact-title{font-size:13px}
#sidebar-chats button[aria-current="true"]{background:#274154;border-left:3px solid #79c9ac}
.sidebar-chat-meta{display:block;font-size:10px;color:#8faabc;margin-top:4px;overflow-wrap:anywhere}
.sidebar-project-primary-actions,.sidebar-chat-primary-actions,.sidebar-artifact-primary-actions{display:grid;grid-template-columns:1fr 1fr;gap:6px}.sidebar-project-primary-actions{grid-template-columns:repeat(3,minmax(0,1fr));overflow:visible}.sidebar-project-primary-actions button,.sidebar-chat-primary-actions button,.sidebar-artifact-primary-actions button{padding:8px 6px;font-size:11px}.sidebar-project-primary-actions button{position:relative;display:grid;place-items:center;min-height:38px}.project-action-icon{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.project-action-label{position:absolute;z-index:60;left:50%;top:calc(100% + 6px);padding:7px 9px;border:1px solid #496072;border-radius:7px;background:#07131f;color:#f4f8fb;font-size:12px;line-height:1;white-space:nowrap;box-shadow:0 5px 16px #07131f66;opacity:0;visibility:hidden;pointer-events:none;transform:translate(-50%,-4px);transition:opacity .12s ease,transform .12s ease,visibility .12s ease}.sidebar-project-primary-actions button:first-child .project-action-label{left:0;transform:translateY(-4px)}.sidebar-project-primary-actions button:last-child .project-action-label{left:auto;right:0;transform:translateY(-4px)}.sidebar-project-primary-actions button:hover .project-action-label,.sidebar-project-primary-actions button:focus-visible .project-action-label{opacity:1;visibility:visible;transform:translate(-50%,0)}.sidebar-project-primary-actions button:first-child:hover .project-action-label,.sidebar-project-primary-actions button:first-child:focus-visible .project-action-label,.sidebar-project-primary-actions button:last-child:hover .project-action-label,.sidebar-project-primary-actions button:last-child:focus-visible .project-action-label{transform:translateY(0)}
#sidebar-project-import-options{margin-top:6px}#sidebar-project-import-options button{width:100%;padding:8px 6px;font-size:11px}
.sidebar-chat-branch{margin-top:12px}.sidebar-chat-branch-toggle{display:flex!important;align-items:center;gap:7px;color:#a9bdca!important;font-size:11px!important;text-transform:uppercase;letter-spacing:.06em}
.sidebar-chat-branch-toggle::before{content:'▾';font-size:10px}.sidebar-chat-branch[aria-expanded="false"]>.sidebar-chat-branch-toggle::before{content:'▸'}
.sidebar-chat-branch[aria-expanded="false"]>[role="group"]{display:none}.sidebar-chat-branch>[role="group"]{margin:2px 0 8px}
.sidebar-chat-row{position:relative}.sidebar-chat-row>.sidebar-chat-open{min-width:0}
.sidebar-presentation-row{position:relative;border-bottom:1px solid #274154}.sidebar-presentation-row .sidebar-list-main strong,.sidebar-presentation-row .sidebar-list-main small{display:block;overflow-wrap:anywhere}.sidebar-presentation-row .sidebar-list-main small{margin-top:4px;color:#8faabc;font-size:10px}
.sidebar-item-menu{position:relative;margin-top:4px}.sidebar-item-menu>summary{display:block;list-style:none;cursor:pointer;color:#dce8f1;padding:8px;border-radius:8px;font-weight:700}.sidebar-item-menu>summary::-webkit-details-marker{display:none}.sidebar-item-menu>summary:hover,.sidebar-item-menu[open]>summary{background:#274154}.sidebar-item-menu-items{position:absolute;z-index:30;right:0;top:100%;width:205px;padding:6px;background:#f8fbfd;border:1px solid #8faabc;border-radius:10px;box-shadow:0 8px 22px #07131f55}.sidebar-item-menu-items button{display:block!important;width:100%!important;padding:9px 10px!important;text-align:left!important;background:transparent!important;color:#20384b!important;font-size:12px!important}.sidebar-item-menu-items button:hover{background:#dfecea!important}.sidebar-item-menu-items button:disabled{display:block!important;opacity:.48;cursor:not-allowed}
#sidebar-tabs{grid-column:1;grid-row:1;display:flex;flex-direction:column;align-items:stretch;gap:6px;margin:0;padding-right:8px;border-right:1px solid #365066;overflow:visible;z-index:10}
#sidebar-tabs button{position:relative;width:42px;min-height:42px;padding:8px;display:grid;place-items:center;border:1px solid transparent;background:transparent;color:#c8d4df}
.sidebar-tab-icon{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.sidebar-tab-label{position:absolute;z-index:50;left:calc(100% + 9px);top:50%;padding:7px 9px;border:1px solid #496072;border-radius:7px;background:#07131f;color:#f4f8fb;font-size:12px;line-height:1;white-space:nowrap;box-shadow:0 5px 16px #07131f66;opacity:0;visibility:hidden;pointer-events:none;transform:translate(-4px,-50%);transition:opacity .12s ease,transform .12s ease,visibility .12s ease}
#sidebar-tabs button:hover .sidebar-tab-label,#sidebar-tabs button:focus-visible .sidebar-tab-label{opacity:1;visibility:visible;transform:translate(0,-50%)}
#sidebar-tabs button[aria-selected="true"]{background:#274154;color:white;border-color:#79c9ac}
#sidebar-tabs button:disabled{opacity:.42}#sidebar-tabs button:disabled:hover{background:transparent}
#sidebar-project-tools{flex:1;min-height:0;display:grid;grid-template-columns:51px minmax(0,1fr);column-gap:10px;overflow:hidden}
#sidebar-project-tools>[role="tabpanel"]:not([hidden]){grid-column:2;grid-row:1;min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden}
#sidebar-project-list,#todo-tree,#sidebar-artifact-list,#sidebar-chat-tree,#sidebar-presentation-list,#sidebar-tool-list,#sidebar-settings-list,#sidebar-federation-list{min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin}
#sidebar-project-list,#todo-tree,#sidebar-artifact-list,#sidebar-presentation-list,#sidebar-tool-list,#sidebar-settings-list,#sidebar-federation-list{flex:1}
#sidebar-settings-list{flex:1}
#sidebar-project-tools>#sidebar-chats:not([hidden]){display:grid;grid-template-rows:auto auto auto minmax(0,1fr)}
#sidebar-settings-list button{display:block;width:100%;padding:10px 8px;text-align:left;background:transparent;color:#dce8f1;font-size:13px}#sidebar-settings-list button:hover{background:#274154}#sidebar-settings-list li[hidden]{display:none}
#sidebar-tools h2,#sidebar-presentations h2,#sidebar-settings h2,#sidebar-federation h2{margin-bottom:4px}#sidebar-presentations h3{font-size:13px;color:#dce8f1;margin:8px 0 0}
#todo-title{font-size:13px;font-weight:600;overflow-wrap:anywhere}#todo-tree ul{padding-left:14px;list-style:none;border-left:1px solid #496072;margin-left:4px}
#todo-tree li{font-size:13px;margin:8px 0}.todo-label{display:inline-flex;gap:7px;align-items:baseline;max-width:100%;padding:7px 5px;border-radius:7px;cursor:pointer}.todo-label:hover,.todo-label:focus-visible{background:#274154;outline:none}.todo-label input{flex-shrink:0;accent-color:#79c9ac}.todo-text{overflow-wrap:anywhere;min-width:0}
.todo-done>.todo-label .todo-text,.todo-done>details>summary .todo-text{color:#a9c5b7;text-decoration:line-through}
#project-view{height:100%;display:flex;flex-direction:column;gap:16px}.project-header{flex-shrink:0;min-height:28px}.project-header .eyebrow{align-self:center}
.project-header details{max-width:280px}.project-header code{font-size:10px}
.read-only-notice{margin:0;padding:10px 14px;border:1px solid #c9a951;border-radius:8px;background:#fff7dd;color:#604b11}
#workspace-panel{min-height:0;flex:1;display:flex;flex-direction:column;background:white;border:1px solid #dce3e9;border-radius:16px;overflow:hidden}
#main-tabs{display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid #dce3e9;padding:16px;flex-shrink:0}
#main-tabs button[aria-selected="false"]{background:#e8eef2;color:#304657}
#main-panel-content{overflow:auto;padding:0 22px 20px;flex:1;min-height:0}#main-panel-content.project-overview-active{overflow:hidden}
#project-overview-panel{box-sizing:border-box;display:flex;flex-direction:column;width:100%;height:100%;max-width:1180px;margin:0 auto;padding:22px 0}.project-overview-heading{display:block;flex:none;padding:8px 2px 18px}.project-overview-heading h1{font-size:38px;margin:8px 0}.project-overview-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;align-items:stretch;flex:1;min-height:0}.project-overview-history{display:flex;flex-direction:column;grid-column:span 1;min-height:0;overflow:hidden}.project-overview-history ol{flex:1;min-height:0;list-style:none;margin:0;padding:0;overflow:auto;overscroll-behavior:contain}.project-history-row{padding:10px 0;border-top:1px solid #dce3e9}.project-history-row:first-child{border-top:0}.project-history-row strong,.project-history-row small{display:block;overflow-wrap:anywhere}.project-history-row small{margin-top:4px;color:#526675}.project-overview-description{grid-column:span 2;min-width:0;padding:20px 12px}.project-overview-description p{margin:0;white-space:pre-wrap;font-size:17px;line-height:1.75}.project-overview-description p:empty::after{content:'Projekt zatím nemá stručný popis.';color:#84909b;font-style:italic}
.project-overview-tasks{grid-column:span 1;width:100%;max-height:none;min-height:0;overflow:hidden}.project-overview-tasks ul{flex:1;min-height:0;max-height:none;overscroll-behavior:contain}.project-overview-tasks>.secondary-button{align-self:flex-start;margin-top:8px}
.conflict-button{margin-top:10px;background:#a33b32}.conflict-button:hover{background:#842f28}#project-conflicts{width:100%;max-width:1800px;margin:0 auto;padding:10px 0 30px}.conflict-toolbar{display:flex;gap:12px;align-items:end;justify-content:space-between;flex-wrap:wrap;margin:14px 0}.conflict-toolbar label{flex:1;min-width:260px}.conflict-toolbar select{display:block;width:100%;padding:9px}.conflict-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;align-items:stretch}.conflict-pane{min-width:0;border:1px solid #dce3e9;border-radius:10px;background:#fff;overflow:hidden}.conflict-pane>header{display:flex;align-items:baseline;justify-content:space-between;gap:8px;min-height:30px;padding:10px 12px;border-bottom:1px solid #dce3e9;background:#f5f8fa}.conflict-pane h3{margin:0;font-size:15px}.conflict-result{border-color:#77a99e;box-shadow:0 0 0 1px #77a99e}.conflict-result>header{background:#e8f4f0}.conflict-summary{font-size:11px;font-weight:600;color:#526675;text-align:right}.conflict-code,.conflict-editor-stack{height:440px;min-height:260px;overflow:auto;background:#fff}.conflict-code pre,.conflict-editor-stack pre,.conflict-editor-stack textarea{box-sizing:border-box;margin:0;padding:12px;width:100%;min-width:100%;min-height:100%;border:0;font:13px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;tab-size:4;white-space:pre}.conflict-code pre{overflow:visible}.conflict-editor-stack{display:grid;position:relative}.conflict-editor-stack pre,.conflict-editor-stack textarea{grid-area:1/1;overflow:auto}.conflict-editor-stack pre{pointer-events:none;color:transparent;background:#fff}.conflict-editor-stack textarea{position:relative;resize:none;outline:0;background:transparent;color:#213746}.conflict-editor-stack textarea:focus{box-shadow:inset 0 0 0 2px #176b60}.conflict-line{display:block;min-height:1.55em;padding:0 3px}.diff-local{background:#dceeff;border-left:4px solid #2674a8}.diff-remote{background:#fff0cf;border-left:4px solid #c17b16}.diff-both{background:linear-gradient(90deg,#dceeff 0 50%,#fff0cf 50%);border-left:4px solid #7c5ba7}.conflict-legend{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0;font-size:12px}.conflict-legend span{display:inline-block;padding:5px 8px;border-radius:5px}.conflict-rendered [data-conflict-preview]{padding:12px;font-weight:400;overflow-wrap:anywhere;max-height:440px;overflow:auto}.conflict-rendered pre{white-space:pre-wrap}.conflict-rendered p{white-space:pre-wrap}.conflict-rendered .diff-local,.conflict-rendered .diff-remote,.conflict-rendered .diff-both{padding-left:8px}.conflict-missing{color:#6b7780;font-style:italic}#project-conflicts-unresolved{font-weight:700;color:#9b4f30}
.conflict-code{overflow:auto}.conflict-editor-stack{overflow:hidden}
.conflict-file-list{display:grid;gap:8px;margin:12px 0;padding:0;list-style:none}.conflict-file-list button{display:flex;align-items:center;justify-content:space-between;gap:12px;width:100%;padding:12px 14px;text-align:left;background:#f5f8fa;color:#213746;border:1px solid #dce3e9}.conflict-file-list button:hover,.conflict-file-list button:focus-visible{background:#e8f4f0;border-color:#77a99e}.conflict-file-path{min-width:0;overflow-wrap:anywhere;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}.conflict-file-status{flex:none;padding:4px 7px;border-radius:999px;font-size:11px;font-weight:700}.conflict-file-status.unresolved{background:#fde2dc;color:#8c2e26}.conflict-file-status.resolved{background:#dff2e9;color:#176b60}.conflict-file-status.automatic{background:#e8eef2;color:#456276}.conflict-dialog{box-sizing:border-box;width:min(1760px,calc(100vw - 32px));max-width:none;max-height:92vh;margin:auto;padding:0;border:1px solid #77a99e;border-radius:14px;background:#f8fafb;box-shadow:0 18px 60px #14263855}.conflict-dialog::backdrop{background:#14263899}.conflict-dialog-shell{box-sizing:border-box;max-height:92vh;padding:18px;overflow:auto}.conflict-dialog-header{display:flex;align-items:start;justify-content:space-between;gap:16px}.conflict-dialog-header h2{margin:4px 0 0;overflow-wrap:anywhere}.conflict-dialog-header button{flex:none}
#preview-status{font-size:12px}#preview-content img{max-width:100%;height:auto}#preview-content pre{white-space:pre-wrap;background:#eff3f6;padding:16px}
#preview-content p{white-space:pre-wrap;margin:6px 0}#preview-content h1{font-size:28px}#preview-title{font-size:20px}
#preview-metadata{overflow-wrap:anywhere}#preview-metadata dt{font-weight:600;margin-top:10px}#preview-metadata dd{margin:4px 0;white-space:pre-wrap}
#pdf-controls{margin:16px 0}#pdf-page{width:75px;margin:0 12px;padding:10px}
#prompt-widget{position:relative;z-index:20;flex-shrink:0;border-top:1px solid #dce3e9;background:#fafffd}#chat-composer{max-height:52vh;overflow:auto;padding:12px 20px 14px}#chat-composer.inputs-open{overflow:visible}#chat-composer label{font-weight:600;font-size:12px}.visually-hidden{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}
.prompt-draft-control{position:relative;display:block;box-sizing:border-box;border:1px solid #bfcdc9;border-radius:10px;background:#fff;color:#526675}.prompt-draft-control>span{position:absolute;z-index:1;top:5px;left:12px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;pointer-events:none}.prompt-draft-control:focus-within,.prompt-control:focus-within{border-color:#176b60;box-shadow:0 0 0 2px #79c9ac3d}#chat-draft{display:block;box-sizing:border-box;width:100%;min-height:68px;max-height:180px;resize:vertical;border:0;border-radius:10px;outline:0;padding:23px 12px 8px;background:transparent}
.prompt-toolbar{display:flex;align-items:end;gap:8px;margin:9px 0 5px;min-width:0}.prompt-control{position:relative;display:block;box-sizing:border-box;height:44px;min-width:0;border:1px solid #bfcdc9;border-radius:8px;background:#fff;color:#526675}.prompt-control>span{position:absolute;z-index:1;top:4px;left:9px;font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;pointer-events:none}.prompt-control select,.prompt-control input{box-sizing:border-box;height:42px;min-width:0;max-width:180px;margin:0;padding:17px 28px 3px 9px;border:0;border-radius:8px;outline:0;background:transparent;color:#213746}.prompt-routing-controls,.prompt-execution-controls{display:flex;align-items:end;gap:8px;min-width:0}.prompt-routing-controls{flex:1}.prompt-execution-controls{margin-left:auto}.prompt-route-arrow{align-self:center;color:#688194;font-size:18px}.prompt-input-picker{position:relative;flex:0 0 auto}.prompt-input-picker>summary{display:flex;flex-direction:column;justify-content:center;box-sizing:border-box;height:44px;min-width:108px;padding:5px 28px 5px 10px;border:1px solid #bfcdc9;border-radius:8px;background:#fff;color:#213746;cursor:pointer;list-style:none}.prompt-input-picker>summary::-webkit-details-marker{display:none}.prompt-input-picker>summary::after{content:'▾';position:absolute;right:10px;bottom:11px;color:#688194}.prompt-input-picker[open]>summary{border-color:#176b60;box-shadow:0 0 0 2px #79c9ac3d}.prompt-input-picker>summary span{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:#526675}.prompt-input-picker>summary output{font-size:13px;font-weight:600}.prompt-input-menu{position:absolute;z-index:25;left:0;bottom:50px;width:min(390px,calc(100vw - 48px));max-height:min(360px,45vh);overflow:auto;border:1px solid #bfcdc9;border-radius:10px;padding:10px 12px;background:#fff;box-shadow:0 10px 28px #14263835}.prompt-input-menu fieldset{margin:0;padding:0;border:0}.prompt-input-menu fieldset>legend{font-weight:700;margin-bottom:8px}.prompt-input-menu label{display:block!important;margin:7px 0!important;font-weight:400!important}.prompt-input-menu #task-artifacts{margin:5px 0 9px 22px}.prompt-input-menu #task-artifacts summary{cursor:pointer;font-weight:600}.prompt-input-menu #task-artifacts fieldset,.prompt-input-menu #task-public-sources{max-height:160px;overflow:auto;margin:7px 0;padding:7px 10px;border-left:2px solid #dce3e9}.prompt-privacy-control select{max-width:155px}.prompt-execution-controls .prompt-control:first-child select{max-width:165px}.prompt-execution-controls .prompt-control:last-child input{max-width:150px;padding-right:9px}#chat-submit{flex:0 0 44px;width:44px;height:44px;min-height:44px;padding:0;border-radius:50%;font-size:22px;line-height:1}#chat-submit:disabled{opacity:.48;cursor:not-allowed}#chat-orchestration-target{margin:5px 0 0;color:#9b4f30;font-size:12px}#chat-orchestration-target:empty{display:none}
#external-preview,#external-proposal,#search-preview,.deletion-preview{margin-top:12px;border:1px solid #d6b36a;background:#fffaf0;border-radius:10px;padding:12px}#external-preview pre,#search-preview pre,.deletion-preview pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto}#external-proposal-messages label{display:block;margin:7px 0}
#advanced-external{margin:8px 0;color:#456276;font-size:12px}.task-outcome{border:1px solid #dce3e9;border-radius:12px;margin:14px 0;padding:14px 18px;background:#fffaf0}.task-outcome.terminal{background:#f4f7fa}.task-outcome pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:none}.task-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.task-actions button{padding:8px 12px}.artifact-link{color:#176b60;background:transparent;padding:0;text-align:left}.artifact-link:hover{background:transparent;text-decoration:underline}
.chat-message{padding:14px 18px;background:#edf5f2;border-radius:12px;margin:14px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.chat-message.assistant{background:#eef1fa}.chat-message small{display:block;margin-top:6px}.secondary-button{background:#e8eef2;color:#304657;margin:0 8px 12px 0}.secondary-button:hover{background:#dce6eb}#chat-privacy{padding:17px 28px 3px 9px;max-width:100%}#chat-operation-status{font-size:12px;margin:5px 0 0;color:#315f58}#chat-operation-status:empty{display:none}
#chat-stream-status.chat-live-progress{display:flex;align-items:center;gap:10px;min-height:52px;color:#304657;font-weight:600}
.chat-progress-spinner{width:12px;height:12px;flex:0 0 auto;border:3px solid #afc3d8;border-top-color:#526ca4;border-radius:50%;animation:chat-stream-spin .8s linear infinite}
@keyframes chat-stream-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.chat-progress-spinner{animation:none;border-top-color:#afc3d8;background:#526ca4}}
#summary-panel label,#extraction-panel label{display:block;margin:10px 0 5px}#summary-panel textarea,#summary-panel input,#summary-panel select,#extraction-panel textarea,#extraction-panel input,#extraction-panel select{padding:9px;max-width:100%}#summary-focus,#extraction-focus{width:100%;resize:vertical}#summary-artifacts,#extraction-panel fieldset{margin:14px 0;border:1px solid #dce3e9}#summary-artifact-list label,#extraction-artifact-list label{font-weight:400}#summary-status,#extraction-status{font-size:12px;min-height:20px;color:#315f58}#summary-preview,#extraction-preview{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#summary-preview:empty,#extraction-preview:empty{display:none}#summary-preview p{white-space:pre-wrap;margin:6px 0}#extraction-preview{white-space:pre-wrap;overflow:auto}#summary-publish-controls,#extraction-publish-controls{border-top:1px solid #dce3e9;padding-top:12px}
#workflow-panel label{display:block;margin:10px 0 5px}#workflow-panel textarea,#workflow-panel input,#workflow-panel select{padding:9px;max-width:100%}#workflow-purpose{width:100%;resize:vertical}#workflow-panel fieldset{margin:14px 0;border:1px solid #dce3e9}#workflow-panel fieldset label{font-weight:400}#workflow-status{font-size:12px;min-height:20px;color:#315f58}#workflow-panel section{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#workflow-panel pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}#workflow-publish{border-top:1px solid #dce3e9}
#autonomy-queue{margin:16px 0;border:1px solid #bfcdc9;border-radius:12px;padding:12px;background:#f8fbfc}#autonomy-queue>summary{font-weight:700;color:#176b60}.autonomy-plan-editor{margin:10px 0}.autonomy-plan-editor textarea,.autonomy-revision-editor textarea{width:100%;font-family:monospace;font-size:12px}#autonomy-list{display:grid;gap:10px;margin-top:12px}.autonomy-card{border:1px solid #dce3e9;border-left:5px solid #8aa1ad;border-radius:10px;padding:12px;background:#fff}.autonomy-card[data-state="completed"]{border-left-color:#2d8a62}.autonomy-card[data-state="paused"],.autonomy-card[data-state="awaiting-approval"],.autonomy-card[data-state="proposed"]{border-left-color:#c69224}.autonomy-card[data-state="failed"],.autonomy-card[data-state="unknown"]{border-left-color:#b74435}.autonomy-card h3{margin:0 0 5px}.autonomy-card progress{width:100%;accent-color:#176b60}.autonomy-card ol{padding-left:22px}.autonomy-card li{margin:5px 0}.autonomy-card details pre{max-height:220px;font-size:11px}.autonomy-card .form-actions{display:flex;gap:7px;flex-wrap:wrap}.autonomy-card .danger-button{background:#9b3f35}.autonomy-revision{margin:10px 0;padding:10px;border:1px solid #dfbd72;border-radius:8px;background:#fff8e8}.autonomy-revision p{margin:4px 0}.autonomy-revision-history{font-size:13px;color:#526575}
#metadata-panel label{display:block;margin:10px 0 5px}#metadata-panel select{padding:9px;max-width:100%;margin-bottom:10px}#metadata-status{font-size:12px;min-height:20px;color:#315f58}#metadata-diff{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#metadata-diff p,#metadata-diff span{white-space:pre-wrap}#metadata-diff fieldset{margin:14px 0;border:1px solid #dce3e9}#metadata-tag-list label{font-weight:400}
#image-panel label{display:block;margin:10px 0 5px}#image-panel textarea,#image-panel input,#image-panel select{padding:9px;max-width:100%}#image-prompt{width:100%;box-sizing:border-box;resize:vertical}#image-status{font-size:12px;min-height:20px;color:#315f58}#image-request-preview,#image-result{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#image-request-json,#image-result-metadata{white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto}#image-result-preview{display:block;max-width:100%;max-height:520px;margin:12px auto}#image-result-preview:not([src]){display:none}
#presentation-panel{min-height:100%}.presentation-editor-head,.presentation-editor-footer{display:flex;justify-content:space-between;align-items:end;gap:16px;flex-wrap:wrap}.presentation-editor-head h2{margin-bottom:0}.presentation-editor-head p{margin-top:4px}.presentation-editor-head label{display:flex;align-items:center;gap:8px}.presentation-editor-head select{padding:8px;max-width:300px}.presentation-editor-workspace{display:grid;grid-template-columns:minmax(220px,26%) minmax(300px,1fr) minmax(260px,34%);gap:14px;margin-top:14px}.presentation-editor-workspace>section{background:#fff;border:1px solid #dce3e9;border-radius:12px;padding:14px;min-width:0}.presentation-editor-workspace label{display:block;margin:8px 0}.presentation-editor-workspace input[type="text"],.presentation-editor-workspace input[type="number"],.presentation-editor-workspace textarea,.presentation-editor-workspace select{width:100%;padding:8px}.presentation-editor-options{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px}.presentation-editor-options label:first-child{grid-column:1/-1}.presentation-editor-options input[type="color"]{width:64px;height:36px;padding:2px}.presentation-editor-slides ol{list-style:none;padding:0;max-height:420px;overflow:auto}.presentation-editor-slides li button{display:block;width:100%;text-align:left;background:#edf2f5;color:#304657;margin:5px 0;padding:9px}.presentation-editor-slides li button[aria-current="true"]{background:#176b60;color:#fff}.presentation-editor-slides li.backup button{border-left:4px solid #d6b36a}.presentation-template-manager{margin-top:14px;border-top:1px solid #dce3e9;padding-top:10px}.presentation-template-manager summary{font-weight:700}.presentation-template-manager .form-actions{display:grid;grid-template-columns:1fr 1fr}.presentation-template-manager .form-actions button:last-child{grid-column:1/-1}.presentation-template-colors{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.presentation-template-colors input[type="color"]{width:100%;height:36px;padding:2px}.presentation-editor-fields fieldset{margin-top:12px;border:1px solid #dce3e9}.presentation-editor-fields #presentation-backup-links label{font-weight:400}.presentation-editor-preview #presentation-editor-preview{width:100%;aspect-ratio:16/9;background:#10222f;color:#f6faf8;overflow:hidden}.presentation-session-section{margin-top:16px;padding:14px;background:#fff;border:1px solid #dce3e9;border-radius:12px}.presentation-session-section ul{list-style:none;padding:0}.presentation-session-section li{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid #dce3e9}.presentation-session-section small{display:block;color:#526675}.presentation-editor-footer{margin-top:12px;border-top:1px solid #dce3e9}.presentation-editor-footer>p{flex:1}.danger-button{background:#9b3f3f}.danger-button:hover{background:#7d3030}#presentation-print-view{display:none}
.outputs-overview-heading{max-width:760px}.outputs-overview-heading h2{margin:4px 0}.outputs-overview-grid{display:grid;grid-template-columns:minmax(240px,38%) minmax(280px,1fr);gap:16px;margin-top:14px}.outputs-overview-grid>ul{list-style:none;margin:0;padding:0}.outputs-overview-grid>ul button{display:block;width:100%;margin:0 0 8px;padding:12px;text-align:left;background:#edf2f5;color:#213746}.outputs-overview-grid>ul button[aria-current="true"]{background:#176b60;color:#fff}.outputs-overview-grid>ul small{display:block;margin-top:4px;overflow-wrap:anywhere}.outputs-overview-detail{border:1px solid #dce3e9;border-radius:12px;padding:16px;background:#fff}.outputs-overview-detail dl{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:8px 14px}.outputs-overview-detail dt{font-weight:700}.outputs-overview-detail dd{margin:0;overflow-wrap:anywhere}
@media print{body>*{display:none!important}#presentation-print-view{display:block!important}#presentation-print-view .print-slide{display:block;break-after:page;width:16in;height:9in;page-break-after:always}#presentation-print-view .print-slide:last-child{break-after:auto;page-break-after:auto}@page{size:16in 9in;margin:0}}
.back-button{align-self:flex-start;background:transparent;color:#456276;padding:8px 0;font-size:13px;flex-shrink:0}.back-button:hover{background:transparent;color:#176b60}
.federation-transfer-page,.federation-network-page,.federation-deployment-page{max-width:860px}.federation-transfer-page form>label,.federation-network-page fieldset>label,.federation-deployment-page form>label{display:block;margin:14px 0;font-weight:650}.federation-transfer-page select,.federation-transfer-page input,.federation-network-page select,.federation-network-page input:not([type="checkbox"]),.federation-deployment-page select,.federation-deployment-page input:not([type="checkbox"]){display:block;width:100%;margin-top:6px;padding:9px}.federation-transfer-page pre,.federation-network-page pre,.federation-deployment-page pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f6f8;border-radius:8px;padding:12px}.federation-network-page fieldset{margin:18px 0;border:1px solid #dce3e9;border-radius:10px;padding:14px}.federation-network-page legend{font-weight:700}.federation-network-page .form-warning,.federation-deployment-page .form-warning{color:#7a4b28}#federation-transfer-log:empty,#federation-network-log:empty,#federation-deployment-log:empty{display:none}
@media(max-width:1100px) and (min-width:641px){#dashboard-grid{grid-template-columns:repeat(2,minmax(0,1fr));grid-template-rows:none;grid-auto-rows:minmax(210px,auto)}}
@media(max-width:1250px) and (min-width:641px){.project-overview-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.project-overview-description{grid-column:1/-1;grid-row:1}.project-overview-history{grid-column:1;grid-row:2}.project-overview-tasks{grid-column:2;grid-row:2}}
@media(max-width:1180px) and (min-width:641px){.prompt-toolbar{flex-wrap:wrap}.prompt-routing-controls{order:3;flex-basis:100%}.prompt-execution-controls{margin-left:0}}
@media(max-width:780px){aside{width:268px;padding:22px 12px}main{padding:18px}.project-header details{max-width:140px}}
@media(min-width:641px){
 aside.sidebar-compact{width:70px;padding:14px 9px;overflow:visible}
 aside.sidebar-compact .brand{justify-content:center;height:30px;margin-bottom:10px}aside.sidebar-compact .brand-name{display:none}
 aside.sidebar-compact #sidebar-project-tools{display:block;overflow:visible}aside.sidebar-compact #sidebar-tabs{height:100%;padding:0;border-right:0;overflow-y:auto;overflow-x:visible;scrollbar-width:none}
 aside.sidebar-compact #sidebar-tabs::-webkit-scrollbar{display:none}
 aside.sidebar-compact #sidebar-project-tools>[role="tabpanel"]:not([hidden]){position:absolute;z-index:70;left:calc(100% + 8px);top:12px;bottom:12px;width:292px;min-width:0;padding:18px 14px;border:1px solid #496072;border-radius:12px;background:#142638;box-shadow:0 12px 32px #07131f66;overflow:hidden}
 aside.sidebar-compact:not(.sidebar-menu-open) #sidebar-project-tools>[role="tabpanel"]:not([hidden]){display:none}
 aside.sidebar-compact.sidebar-menu-open #sidebar-project-tools>[role="tabpanel"]:not([hidden]){display:flex}
 aside.sidebar-compact.sidebar-menu-open #sidebar-project-tools>#sidebar-chats:not([hidden]){display:grid}
 aside.sidebar-compact #resource-monitor{margin-top:8px;padding-top:8px}aside.sidebar-compact #resource-monitor-open{display:grid;place-items:center;width:42px;height:42px;padding:8px}
 aside.sidebar-compact #resource-monitor-open>:not(.sidebar-utility-icon){display:none}aside.sidebar-compact #resource-monitor-open>.sidebar-utility-icon{display:block}
 aside.sidebar-compact #logout,aside.sidebar-compact #sidebar-layout-toggle{position:relative;display:grid;place-items:center;width:42px;height:42px;padding:8px;font-size:0}
 body[data-runtime="desktop"] aside.sidebar-compact #logout{display:none}
 aside.sidebar-compact #logout .sidebar-utility-icon{display:block}
 aside.sidebar-compact #sidebar-layout-toggle .sidebar-utility-icon{transform:rotate(180deg)}
 aside.sidebar-compact .sidebar-layout-label{position:absolute;z-index:90;left:calc(100% + 9px);top:50%;padding:7px 9px;border:1px solid #496072;border-radius:7px;background:#07131f;color:#f4f8fb;font-size:12px;line-height:1;white-space:nowrap;box-shadow:0 5px 16px #07131f66;opacity:0;visibility:hidden;pointer-events:none;transform:translate(-4px,-50%);transition:opacity .12s ease,transform .12s ease,visibility .12s ease}
 aside.sidebar-compact #sidebar-layout-toggle:hover .sidebar-layout-label,aside.sidebar-compact #sidebar-layout-toggle:focus-visible .sidebar-layout-label{opacity:1;visibility:visible;transform:translate(0,-50%)}
}
@media(max-width:640px){
 body{display:block;height:auto;min-height:100vh;min-height:100dvh;overflow:auto}
 #mobile-sidebar-toggle{display:block;position:fixed;z-index:60;top:10px;left:10px;min-height:44px;padding:10px 14px;box-shadow:0 3px 14px #14263835}
 #mobile-sidebar-backdrop{display:block;position:fixed;z-index:45;inset:0;width:100%;height:100%;border:0;border-radius:0;background:#07131fa8;padding:0}
 #mobile-sidebar-backdrop:hover{background:#07131fa8}
 aside{position:fixed;z-index:50;inset:0 auto 0 0;width:min(88vw,360px);height:100vh;height:100dvh;max-width:calc(100vw - 48px);padding:68px 18px 24px;transform:translateX(-105%);transition:transform .18s ease;box-shadow:8px 0 24px #07131f45}
 body.mobile-sidebar-open aside{transform:translateX(0)}
 main{width:100%;min-height:100vh;min-height:100dvh;padding:68px 14px 24px;overflow:visible}
 header,.project-header{align-items:flex-start;flex-direction:column}.project-header details{max-width:100%}
 .home-heading,.settings-heading{margin-top:20px}.home-heading h1,h1{font-size:30px}
 #project-home>header,#project-home>.home-heading{display:none}#dashboard-grid{display:block;min-height:0}.dashboard-tile,.project-card{display:none!important}#dashboard-tasks{display:flex!important;height:calc(100vh - 36px);padding:16px}
 #project-view{height:auto;min-height:calc(100vh - 92px);min-height:calc(100dvh - 92px)}
 #workspace-panel{min-width:0;overflow:visible}#main-panel-content,#main-panel-content.project-overview-active{overflow:visible;padding:0 14px 18px}
 #project-overview-panel{display:block;height:auto;padding:16px 0}.project-overview-heading h1{font-size:30px}.project-overview-grid{display:grid;grid-template-columns:1fr}.project-overview-description{grid-column:1;grid-row:1;padding:12px 2px}.project-overview-history{display:flex!important;grid-column:1;grid-row:2;min-height:180px;overflow:visible}.project-overview-history ol{flex:none;overflow:visible;overscroll-behavior:auto}.project-overview-tasks{display:flex!important;grid-column:1;grid-row:3;min-height:260px;overflow:visible}.project-overview-tasks ul{flex:none;overflow:visible;overscroll-behavior:auto}#chat-composer{max-height:none;padding:12px 14px 14px}
 #main-tabs,#settings-tabs{flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-x:contain;scroll-snap-type:x proximity;padding:12px;scrollbar-width:thin}
 #main-tabs button,#settings-tabs button{flex:0 0 auto;min-height:44px;scroll-snap-align:start}
 .settings-card,#workflow-panel section,#image-request-preview,#image-result,#metadata-diff{max-width:100%;padding:16px 14px;border-radius:12px}
 button{min-height:44px}input,select,textarea{font-size:16px;max-width:100%}fieldset{min-width:0}
 .prompt-toolbar{display:grid;grid-template-columns:1fr 1fr auto;align-items:end}.prompt-toolbar>.prompt-control:first-child{grid-column:1}.prompt-routing-controls{display:contents}.prompt-input-picker{grid-column:2}.prompt-routing-controls>.prompt-control{grid-column:1}.prompt-route-arrow{display:none}.prompt-routing-controls>.prompt-control:last-child{grid-column:2}.prompt-privacy-control{grid-column:1}.prompt-execution-controls{display:contents}.prompt-execution-controls>.prompt-control:first-child{grid-column:1}.prompt-execution-controls>.prompt-control:last-child{grid-column:2}.prompt-control select,.prompt-control input,.prompt-privacy-control select,.prompt-execution-controls .prompt-control:first-child select,.prompt-execution-controls .prompt-control:last-child input{width:100%;max-width:none}.prompt-input-picker>summary{width:100%}#chat-submit{grid-column:3;grid-row:3/span 2;align-self:end;width:44px;height:44px;min-height:44px}.prompt-input-menu{position:fixed;z-index:70;left:14px;right:14px;bottom:14px;width:auto;max-height:70vh}.cms-domain-row{align-items:stretch}.cms-domain-row button{width:100%}
 .confirm{display:flex!important;align-items:flex-start;gap:10px;overflow-wrap:anywhere}.confirm input{flex:0 0 auto;margin-top:4px}
 pre,code,output,[role="status"],[role="alert"]{max-width:100%;overflow-wrap:anywhere;word-break:break-word}
 #preview-content pre,#workflow-panel pre,#image-request-json,#image-result-metadata,#external-preview pre,#cms-request-preview{white-space:pre-wrap;overflow-x:auto}
 #pdf-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}#pdf-page{margin:0}
 #system-monitor-detail{grid-template-columns:1fr}
 #sidebar-layout-toggle{display:none}
}
@media(max-width:640px) and (prefers-reduced-motion:reduce){aside{transition:none}}
@media(max-width:1000px){.presentation-editor-workspace{grid-template-columns:1fr 1fr}.presentation-editor-preview{grid-column:1/-1}}
@media(max-width:700px){.presentation-editor-workspace,.outputs-overview-grid{grid-template-columns:1fr}.presentation-editor-preview{grid-column:auto}.presentation-editor-head label{display:block}.presentation-editor-head select{max-width:100%;width:100%}.outputs-overview-detail dl{grid-template-columns:1fr}.outputs-overview-detail dd{margin-bottom:6px}}
@media(max-width:1000px){.conflict-grid{grid-template-columns:1fr}.conflict-code,.conflict-editor-stack{height:300px}.conflict-toolbar{align-items:stretch}.conflict-toolbar button{width:100%}}
'''
CSS += ADMIN_CSS + '''
body[data-runtime="pending"]{visibility:hidden}
body[data-runtime="desktop"]>#login,body[data-runtime="desktop"] #logout{display:none!important}
body[data-runtime="desktop"] .notebooklm-server-source,
body[data-runtime="server"] .notebooklm-desktop-source{display:none!important}
body[data-runtime="server"]:not(.authenticated)>aside,
body[data-runtime="server"]:not(.authenticated)>main,
body[data-runtime="server"]:not(.authenticated)>#mobile-sidebar-toggle,
body[data-runtime="server"]:not(.authenticated)>#mobile-sidebar-backdrop{display:none}
body.authenticated>#login{display:none}#login{margin:10vh auto;padding:24px}
#login input{padding:12px;margin:12px}.project-create-row{display:flex;gap:12px;align-items:flex-start;max-width:520px}
#new-project-title{flex:1;min-width:0;padding:12px}#create-project-status{font-size:12px;min-height:14px;color:#47635f}
#create-project{max-width:760px}#project-location-controls{margin-top:12px}#project-location-label{font-size:12px;color:#47635f;overflow-wrap:anywhere}.creation-preview{margin-top:14px;border:1px solid #d6b36a;background:#fffaf0;border-radius:10px;padding:12px}.creation-preview h2{margin-top:0;font-size:17px}.creation-preview pre{white-space:pre-wrap;overflow-wrap:anywhere}
#project-create-view,#project-trash-view,#project-repair-view,#source-import-view,#notebooklm-import-view,#history-view,#artifact-editor-view,#federation-view{height:100%;overflow:auto}.standalone-form{max-width:820px;padding:20px;background:white;border:1px solid #dce3e9;border-radius:12px}
.repair-findings{display:grid;gap:10px;padding-left:24px}.repair-finding{padding:12px;border:1px solid #dce3e9;border-radius:10px}.repair-finding strong,.repair-finding span,.repair-finding code{display:block}.repair-finding code{margin-top:5px;color:#526878;font-size:12px}
#google-drive-import{margin-bottom:20px}.import-steps{list-style:none;padding:0;margin:18px 0 22px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.import-steps li{min-width:0;padding:10px;border:1px solid #dce3e9;border-radius:10px;background:#f5f7f9;color:#5b6b7b}.import-steps li>span{display:inline-grid;place-items:center;width:25px;height:25px;margin-right:6px;border-radius:50%;background:#dce3e9;font-weight:750}.import-steps strong,.import-steps small{display:block}.import-steps small{margin:5px 0 0 31px;line-height:1.3}.import-steps li.current{border-color:#16796b;background:#edf8f6;color:#174f48}.import-steps li.current>span,.import-steps li.done>span{background:#16796b;color:white}.import-steps li.done{color:#315f58}.wizard-callout,.wizard-summary{padding:12px 14px;border-left:4px solid #16796b;background:#edf8f6;border-radius:6px}.wizard-callout h3{margin-top:0}.google-login-guide{margin:12px 0;padding:12px 16px;background:#f5f7f9;border-radius:8px}.google-login-guide h4{margin:0}.google-login-guide ol{padding-left:22px}.google-login-guide li{margin:6px 0}.oauth-setup-guide{margin:12px 0;padding:10px 12px;background:#f5f7f9;border-radius:8px}.oauth-setup-guide code{overflow-wrap:anywhere}.wizard-file-list{padding:0;list-style:none}.wizard-file-list li{margin:8px 0;padding:11px 13px;border:1px solid #dce3e9;border-radius:9px;background:#fff}.wizard-file-list strong,.wizard-file-list small{display:block}.wizard-file-list small{margin-top:4px;color:#526a78}#google-drive-plan{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;background:#f5f7f9;padding:12px;border-radius:8px}.import-divider{max-width:820px;margin-top:22px}
.standalone-form label,#notebooklm-import label{display:block;margin:9px 0}.standalone-form .confirm{display:flex;gap:8px;align-items:flex-start}
.standalone-form input,.standalone-form textarea,.standalone-form select,#notebooklm-import input,#notebooklm-import select{max-width:100%;padding:8px}
.standalone-form textarea{width:100%}.form-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}#notebooklm-archive{width:min(680px,100%)}
.history-form{max-width:1100px}.history-choices{display:grid;grid-template-columns:1fr 1fr;gap:14px}.history-form pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto;background:#f5f7f9;padding:12px;border-radius:8px}.history-form details{margin-top:14px}
#notebooklm-import{margin:16px 0}
.destination-callout{padding:10px 12px;border-left:4px solid #16796b;background:#edf8f6;overflow-wrap:anywhere}
#notebooklm-preview{white-space:pre-wrap;max-height:320px;overflow:auto}
@media(max-width:600px){
 #login{margin:5vh 12px;padding:18px}#login input{display:block;width:100%;margin:8px 0 14px}
 .project-create-row{flex-direction:column}.project-create-row button,#new-project-title{width:100%}
 .standalone-form,#notebooklm-import{padding:14px 12px;overflow-wrap:anywhere}
 .standalone-form input,.standalone-form textarea,.standalone-form select,#notebooklm-import input,#notebooklm-import select{width:100%}
 #notebooklm-import button,.standalone-form button{width:100%;margin-top:6px}
 .import-steps{grid-template-columns:1fr 1fr}.import-steps small{margin-left:0}
 #notebooklm-preview{max-height:50vh;max-width:100%;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere}
}'''
PRESENTER_CSS = '''
.presentation-panel #presentation-slide{margin-top:12px;padding:28px 24px;min-height:150px;background:#162638;color:#f6faf8;border-radius:10px}
.presentation-panel #presentation-slide h3{font-size:28px;color:#79c9ac;margin:0 0 14px}.presentation-panel #presentation-slide p{font-size:18px;line-height:1.5;margin:0}
.presentation-panel #presentation-slide:fullscreen{display:flex;flex-direction:column;justify-content:center;padding:8vw;background:#10222f;border-radius:0}
.presentation-panel #presentation-slide:fullscreen h3{font-size:clamp(32px,6vw,80px)}.presentation-panel #presentation-slide:fullscreen p{font-size:clamp(20px,3vw,42px)}
.presenter-header{font-size:1.5em;min-height:52px;border:1px solid #dce3e9;background:#fff;border-radius:10px;padding:6px 12px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:center}.presenter-header-main{display:flex;align-items:center;gap:10px;min-width:0;white-space:nowrap}.presenter-header-main h1{font-size:24px;color:#162638;margin:0;flex:none}.presenter-header-main p{font-size:12px;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.presenter-header-state{display:flex;gap:10px;align-items:center;flex-wrap:nowrap;justify-content:flex-end;white-space:nowrap}.presenter-header-state strong{color:#176b60;font-size:12px}.presenter-header-state span{font-size:12px;color:#627183}#presenter-view{height:100%;min-height:0;display:flex;flex-direction:column;gap:8px}.presenter-layout{display:grid;grid-template-columns:15% 25% minmax(0,1fr);gap:14px;min-height:0;flex:1}.presenter-layout>nav,.presenter-layout>section,.presenter-layout>aside{min-width:0;min-height:0}body.presenter-active>aside{display:none}body.presenter-active main{padding-left:22px;padding-right:22px}
.presenter-header + #presenter-status{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.presenter-deck,.presenter-speaker{background:#fff;border:1px solid #dce3e9;border-radius:12px;padding:10px;overflow:auto;height:100%}.presenter-speaker{width:100%;align-self:stretch;display:flex;flex-direction:column}.presenter-panel-head{display:flex;align-items:baseline;justify-content:space-between;gap:8px}.presenter-panel-head h2{font-size:16px;margin:0}.presenter-panel-head p{font-size:11px;margin:0}.presenter-tab-row{display:flex;align-items:center;gap:6px;margin:4px 0}.presenter-next-selector{flex:0 0 auto;border-bottom:1px solid #dce3e9;padding:4px 0 8px}.presenter-next-selector h3{font-size:12px;margin:0 0 4px}.presenter-next-selector #presenter-next-preview{width:100%;text-align:left;background:#f4f7fa;color:#304657;border:1px solid #dce3e9;padding:8px;border-radius:8px}.presenter-next-selector #presenter-next-preview h2{font-size:14px;color:#176b60;margin:0 0 4px}.presenter-next-selector #presenter-next-preview p{font-size:12px;margin:0}.presenter-tab-content{flex:1;min-height:0;overflow:auto}.presenter-selection-preview{flex:0 0 auto;border-top:1px solid #dce3e9;margin-top:6px;padding-top:6px}.presenter-deck h2{margin-top:0;font-size:16px}.presenter-deck ol{padding-left:24px;margin:0}.presenter-deck li{padding:9px 6px;color:#456276;cursor:pointer;border-radius:6px}.presenter-deck li:hover,.presenter-deck li[aria-current="true"]{background:#e0efe9;color:#176b60}.presenter-deck li.presenter-live{font-weight:700;border-left:3px solid #176b60}.presenter-deck li.presenter-visited{color:#82909d}.presenter-deck button{background:transparent;color:inherit;padding:0;text-align:left;font-weight:inherit;width:100%}.presenter-return-anchor{border-top:1px solid #dce3e9;padding-top:14px;font-size:12px}
.presenter-audience{background:#10222f;border-radius:14px;padding:16px;display:flex;flex-direction:column;min-width:0;min-height:0;overflow:hidden}.presenter-kicker{font-size:11px;letter-spacing:1.6px;color:#79c9ac}.presenter-audience #presenter-screen{width:100%;max-width:420px;aspect-ratio:16/9;height:auto;min-height:0;flex:0 0 auto;display:flex;flex-direction:column;justify-content:center;align-self:center;padding:5%;color:#f6faf8;outline:none;border:1px solid #496072}.presenter-audience #presenter-screen:fullscreen{background:#10222f;max-width:none}
.presenter-audience #presenter-screen h2{font-size:clamp(14px,1.8vw,30px);color:#79c9ac;margin:0 0 8px}.presenter-audience #presenter-screen p{font-size:clamp(10px,1.2vw,20px);line-height:1.35;margin:0}.presenter-controls{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.presenter-speaker{background:#fff;border:1px solid #dce3e9;border-radius:12px;padding:18px;overflow:auto}.presenter-speaker h2{margin-top:0}.presenter-speaker h3{border-top:1px solid #dce3e9;padding-top:18px}.presenter-speaker #presenter-preview,.presenter-speaker #presenter-next-preview{background:#f4f7fa;padding:14px;border-radius:8px}.presenter-speaker #presenter-preview h2,.presenter-speaker #presenter-next-preview h2{font-size:17px;border:0;padding:0;margin:0 0 8px;color:#176b60}.presenter-speaker #presenter-preview p,.presenter-speaker #presenter-next-preview p{margin:0;white-space:pre-wrap;font-size:13px}.presenter-speaker #presenter-notes{background:#fffaf0;border-left:3px solid #d6b36a;padding:10px 12px;white-space:pre-wrap}.presenter-speaker ul{list-style:none;padding:0}.presenter-backup{width:100%;text-align:left;background:#fffaf0;border:1px solid #d6b36a;color:#304657;margin:6px 0;padding:10px}.presenter-backup:hover{background:#fff3d8}.presenter-backup strong,.presenter-backup span{display:block}.presenter-backup span{font-size:12px;margin-top:4px;color:#627183}
.presenter-notes{flex:1;min-height:0;overflow:auto;background:#fffaf0;border-top:1px solid #d6b36a;padding:10px 18px}.presenter-notes h2{font-size:13px;margin:0}.presenter-notes p{margin:4px 0;font-size:13px}.presenter-tabs{display:flex;gap:4px;flex-wrap:wrap}.presenter-tabs button{font-size:11px;padding:8px;background:#e8eef2;color:#304657}.presenter-tabs button[aria-selected="true"]{background:#176b60;color:#fff}#presenter-private-preview{background:#f4f7fa;padding:12px;border-radius:8px}#presenter-private-preview h2{font-size:16px;color:#176b60}#presenter-private-preview p{font-size:12px;margin:5px 0}.presenter-private-status{font-size:11px}.presenter-footer{font-size:1.5em;display:flex;gap:16px;align-items:center;flex-wrap:wrap;border:1px solid #dce3e9;background:#fff;border-radius:10px;padding:10px 14px;color:#627183}.presenter-footer button{padding:9px 12px}.presenter-blackout #presenter-screen{background:#05090c}.presenter-blackout #presenter-screen>*{visibility:hidden}
.presenter-notes{background:#fffaf0;border-top:1px solid #d6b36a;padding:8px 12px}.presenter-notes h2{font-size:13px;margin:0}.presenter-notes p{margin:3px 0;font-size:13px}.presenter-alert{border-left:3px solid #c48226;padding-left:10px}.presenter-tabs{display:flex;gap:3px;flex:0 0 auto}.presenter-tabs button{font-size:11px;padding:7px 9px;background:#e8eef2;color:#304657}.presenter-tabs button[aria-selected="true"]{background:#176b60;color:#fff}.presenter-search{display:flex;align-items:center;gap:4px;min-width:110px;margin:0;font-size:11px;color:#627183}.presenter-search input{width:100px;padding:6px;margin:0;border:1px solid #bfcdc9;border-radius:7px}#presenter-tab-status,#presenter-backup-status{display:none}.presenter-private-preview{background:#f4f7fa;padding:8px;border-radius:8px}.presenter-private-preview h2{font-size:16px;color:#176b60}.presenter-private-preview p{font-size:12px;margin:4px 0}.presenter-private-status{font-size:11px}.presenter-footer{display:flex;gap:16px;align-items:center;flex-wrap:wrap;border-top:1px solid #dce3e9;padding:10px 0;font-size:12px;color:#627183}.presenter-footer button{padding:9px 12px}.presenter-blackout #presenter-screen{background:#05090c}.presenter-blackout #presenter-screen>*{visibility:hidden}
.presenter-gamepad-status{font-size:11px!important;color:#627183;margin:4px 0!important}.presenter-gamepad-selected{outline:3px solid #59b6aa!important;outline-offset:2px}
.presenter-gamepad-settings{font-size:11px;color:#456276;border:1px solid #dce3e9;border-radius:8px;padding:6px 8px;margin:4px 0}.presenter-gamepad-settings summary{cursor:pointer;font-weight:700;color:#176b60}.presenter-gamepad-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;margin-top:8px}.presenter-gamepad-grid label{display:flex;align-items:center;justify-content:space-between;gap:6px}.presenter-gamepad-grid input[type="number"]{width:64px;padding:4px}.presenter-gamepad-grid select{min-width:0;max-width:230px;padding:4px}.presenter-gamepad-wide{grid-column:1/-1}.presenter-gamepad-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.presenter-gamepad-actions button{font-size:11px;padding:7px 9px}.presenter-gamepad-settings p{font-size:11px;margin:6px 0!important}.presenter-gamepad-settings output{display:block;overflow-wrap:anywhere;color:#627183}
#presenter-display-dialog{width:min(620px,calc(100vw - 32px));padding:0;border:1px solid #9babb7;border-radius:16px;color:#162638;background:#f8fbfd;box-shadow:0 18px 60px #07131f66}#presenter-display-dialog::backdrop{background:#07131fa8}#presenter-display-form{padding:22px}#presenter-display-form h2{margin-top:0}#presenter-display-form label{display:block;margin:14px 0;font-weight:650}#presenter-display-form select{display:block;width:100%;margin-top:6px;padding:9px}#presenter-display-status{min-height:24px;color:#8b3030}#presenter-display-form .form-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.presenter-next-selector h3{border-top:0!important;padding-top:0!important;margin:0 0 4px!important}.presenter-next-selector #presenter-next-preview{display:block;min-height:48px;line-height:1.25;cursor:pointer}
.presenter-speaker{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);grid-template-rows:auto minmax(0,1fr);gap:12px;overflow:hidden}
.presenter-panel-head{grid-column:1/-1}
.presenter-speaker{color:#162638}.presenter-speaker h2{color:#162638}.presenter-speaker p{color:#627183}
.presenter-browser{min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden}
.presenter-browser .presenter-tab-row{flex-wrap:wrap;flex-shrink:0}
.presenter-next-selector{min-width:0;min-height:0;display:flex;flex-direction:column;overflow:hidden;border:0;border-left:1px solid #dce3e9;padding:0 0 0 12px}
.presenter-next-selector>h3,.presenter-next-selector>p,.presenter-next-selector>button{flex-shrink:0}
.presenter-slide-widget{display:flex;flex:1;flex-direction:column;min-height:0;background:#10222f}
.presenter-slide-widget .presenter-slide-preview{flex-shrink:0}
.presenter-slide-widget .presenter-notes{flex:1;min-height:0}
.presenter-audience #presenter-screen,.presenter-speaker #presenter-private-preview{width:100%;max-width:420px;aspect-ratio:16/9;align-self:center;display:flex;flex-direction:column;justify-content:center;background:#10222f;color:#f6faf8;padding:5%;border:1px solid #496072;border-radius:0;overflow:auto}.presenter-audience #presenter-screen h2,.presenter-speaker #presenter-private-preview h2{font-size:clamp(14px,1.8vw,30px);color:#79c9ac;margin:0 0 8px}.presenter-audience #presenter-screen p,.presenter-speaker #presenter-private-preview p{font-size:clamp(10px,1.2vw,20px);color:#c8d4df;line-height:1.35;margin:0;white-space:pre-wrap}.presenter-notes p{white-space:pre-wrap}#presenter-tab-content{flex:1;min-height:0;overflow:auto}
.back-button{align-self:flex-start;background:transparent;color:#456276;padding:8px 0;font-size:13px;flex-shrink:0}.back-button:hover{background:transparent;color:#176b60}
@media(max-width:1100px){.presenter-layout{grid-template-columns:15% 25% minmax(0,1fr)}}
@media(max-width:780px){aside{width:268px;padding:22px 12px}main{padding:18px}#project-cards{grid-template-columns:1fr}.presenter-layout{grid-template-columns:1fr;min-height:auto}.presenter-deck{max-height:190px}.presenter-audience{min-height:460px}.presenter-speaker{min-height:560px}}
'''
CSS += PRESENTER_CSS
JS = SLIDE_JS + '''const button=document.querySelector('#increment');
button.addEventListener('click',async()=>{
 button.disabled=true;
 const status=document.querySelector('#status');
 status.textContent='Ověřuji spojení…';
 try {
  const response=await fetch('/v1/counter',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({action:'increment'}),signal:AbortSignal.timeout(4000)});
  if(!response.ok) throw new Error('request rejected');
  const result=await response.json();
  document.querySelector('#count').textContent=result.value;
  status.textContent='Spojení funguje.';
 }catch(error){status.textContent='Spojení se nezdařilo. Zavřete a znovu spusťte aplikaci.';}
 finally{button.disabled=false;}
});'''
JS += """
const gamepadScanButton=document.querySelector('#gamepad-scan');
const gamepadStatus=document.querySelector('#gamepad-status');
const gamepadList=document.querySelector('#gamepad-list');
gamepadScanButton.addEventListener('click',async()=>{
 gamepadScanButton.disabled=true;
 gamepadStatus.textContent='Skenuji vstupní zařízení…';
 gamepadList.replaceChildren();
 try{
  const response=await fetch('/v1/gamepad/status',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({action:'scan'}),signal:AbortSignal.timeout(4000)});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || 'Gamepad není dostupný.');
  gamepadStatus.textContent=result.message || 'Gamepad demo hotovo.';
  if(!result.devices || !result.devices.length){
   const item=document.createElement('li');item.textContent='Žádné joystick/gamepad zařízení nebylo detekováno.';gamepadList.append(item);return;
  }
  for(const device of result.devices){
   const item=document.createElement('li');item.textContent=`${device.name} — ${device.path}`;gamepadList.append(item);
  }
 }catch(error){
  gamepadStatus.textContent=error.message || 'Gamepad demo nebylo možné spustit.';
  const item=document.createElement('li');item.textContent='Demo vyžaduje Linux /dev/input a dostupné udev metadata.';gamepadList.append(item);
 }finally{gamepadScanButton.disabled=false;}
});"""
JS += """
const presentationStartButton=document.querySelector('#presentation-start');
const presentationPrevButton=document.querySelector('#presentation-prev');
const presentationNextButton=document.querySelector('#presentation-next');
const presentationFullscreenButton=document.querySelector('#presentation-fullscreen');
const presentationStatus=document.querySelector('#presentation-status');
const presentationSlide=document.querySelector('#presentation-slide');
const presentationMode=document.querySelector('#presentation-mode');
let presentationSlides=[];
let presentationIndex=0;
function renderPresentationSlide(slide){
 renderSlideVisual(presentationSlide,slide,'h3');
 presentationPrevButton.disabled=presentationIndex===0;
 presentationNextButton.disabled=presentationIndex>=presentationSlides.length-1;
 presentationStatus.textContent=`Promítám slide ${presentationIndex+1} z ${presentationSlides.length}.`;
}
presentationStartButton.addEventListener('click',async()=>{
 presentationStartButton.disabled=true;
 presentationStatus.textContent='Načítám prezentaci…';
 try{
  const response=await fetch('/v1/presentation/status',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({action:'start'}),signal:AbortSignal.timeout(4000)});
  const result=await response.json();
  if(!response.ok) throw new Error(result.error || 'Prezentaci nebylo možné připravit.');
    presentationSlides=Array.isArray(result.slides) ? result.slides : [];
    presentationIndex=Math.min(result.current_slide ?? 0,Math.max(0,presentationSlides.length-1));
    presentationPrevButton.disabled=false;presentationNextButton.disabled=false;
    presentationFullscreenButton.disabled=!presentationSlides.length;
    presentationStartButton.textContent='Restartovat prezentaci';
    renderPresentationSlide(presentationSlides[presentationIndex]);
 }catch(error){
  presentationStatus.textContent=error.message || 'Prezentace nebylo možné spustit.';
  presentationSlide.textContent='Demo promítání vyžaduje běžící desktop app a validní prezentaci.';
 }finally{presentationStartButton.disabled=false;}
});
function movePresentation(offset){
 if(!presentationSlides.length)return;
 presentationIndex=Math.max(0,Math.min(presentationSlides.length-1,presentationIndex+offset));
 renderPresentationSlide(presentationSlides[presentationIndex]);
}
presentationPrevButton.addEventListener('click',()=>movePresentation(-1));
presentationNextButton.addEventListener('click',()=>movePresentation(1));
presentationFullscreenButton.addEventListener('click',async()=>{
 try{await presentationSlide.requestFullscreen();presentationSlide.focus();}
 catch(error){presentationStatus.textContent='Celou obrazovku se nepodařilo spustit.';}
});
presentationMode.addEventListener('keydown',event=>{
 if(event.key==='ArrowLeft'){event.preventDefault();movePresentation(-1);}
 if(event.key==='ArrowRight'){event.preventDefault();movePresentation(1);}
});
const presentationOpenButton=document.querySelector('#presentation-open');
document.querySelector('#presentation-editor').addEventListener('click',()=>openPresentationEditor());
const presenterView=document.querySelector('#presenter-view');
const presenterScreen=document.querySelector('#presenter-screen');
const presenterPreview=document.querySelector('#presenter-preview');
const presenterNotes=document.querySelector('#presenter-notes');
const presenterNextPreview=document.querySelector('#presenter-next-preview');
const presenterOutline=document.querySelector('#presenter-outline');
const presenterMeetingTime=document.querySelector('#presenter-meeting-time');
const presenterBranchTime=document.querySelector('#presenter-branch-time');
const presenterBackupSearch=document.querySelector('#presenter-backup-search');
const presenterTabStatus=document.querySelector('#presenter-tab-status');
const presenterGamepadStatus=document.querySelector('#presenter-gamepad-status');
const presenterGamepadEnabled=document.querySelector('#presenter-gamepad-enabled');
const presenterGamepadDevice=document.querySelector('#presenter-gamepad-device');
const presenterGamepadSettingsStatus=document.querySelector('#presenter-gamepad-settings-status');
const presenterGamepadLive=document.querySelector('#presenter-gamepad-live');
const presenterDeckList=document.querySelector('#presenter-deck-list');
const presenterPrivatePreview=document.querySelector('#presenter-private-preview');
const presenterPrivateStatus=document.querySelector('#presenter-private-status');
const presenterShowPrivate=document.querySelector('#presenter-show-private');
const presenterExposure=document.querySelector('#presenter-exposure');
const presenterLiveState=document.querySelector('#presenter-live-state');
const presenterReturnAnchor=document.querySelector('#presenter-return-anchor');
const presenterBlackoutButton=document.querySelector('#presenter-blackout');
const presenterBlackoutState=document.querySelector('#presenter-blackout-state');
const presenterQuestionButton=document.querySelector('#presenter-question');
const presenterQuestionStatus=document.querySelector('#presenter-question-status');
const presenterQuestionCount=document.querySelector('#presenter-question-count');
const presenterStatus=document.querySelector('#presenter-status');
const presenterCounter=document.querySelector('#presenter-counter');
const presenterBackups=document.querySelector('#presenter-backups');
const presenterBackupStatus=document.querySelector('#presenter-backup-status');
const presenterPrevButton=document.querySelector('#presenter-prev');
const presenterNextButton=document.querySelector('#presenter-next');
const presenterFullscreenButton=document.querySelector('#presenter-fullscreen');
const presenterDisplayDialog=document.querySelector('#presenter-display-dialog');
const presenterDisplayForm=document.querySelector('#presenter-display-form');
const presenterDisplayStatus=document.querySelector('#presenter-display-status');
let presenterDisplayConfiguration=null;
let presenterSlides=[];
let presenterBackupsData=[];
let presenterIndex=0;
let presenterPrivateSelection=null;
let presenterNextSelection=null;
let presenterNextSelectionKind='main';
let presenterExposureValue=0;
let presenterBlackout=false;
let presenterMeetingStarted=0;
let presenterBranchStarted=0;
async function presentationControl(payload){
 const response=await fetch('/v1/presentation/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:AbortSignal.timeout(4000)});
 if(!response.ok)throw new Error('Veřejné okno nepřijalo změnu.');
 return response.json();
}
function applyPresenterRatio(ratio){for(const preview of [presenterScreen,presenterPrivatePreview])preview.style.aspectRatio=ratio==='4:3'?'4 / 3':'16 / 9';}
function formatPresenterTime(value){const seconds=Math.max(0,Math.floor(value/1000));return `${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`;}
setInterval(()=>{if(!presenterMeetingStarted)return;presenterMeetingTime.textContent=formatPresenterTime(Date.now()-presenterMeetingStarted);presenterBranchTime.textContent=presenterBranchStarted?formatPresenterTime(Date.now()-presenterBranchStarted):'00:00';},1000);
function createPresenterSequence(slides){
 const entries=slides.map((slide,mainIndex)=>({slide,mainIndex,kind:slide.closing?'closing':'main',visited:false}));
 const shown=new Map();
 let position=0,frontier=-1,preferred=null;
 const key=slide=>slide?.id || slide;
 const count=slide=>shown.get(key(slide)) || 0;
 const remaining=slide=>slide.reveal==='step' && count(slide)<(slide.bullets?.length || 0);
 const available=slide=>!shown.has(key(slide)) || slide.repeat===true || remaining(slide);
 const unfinished=()=>entries.some(e=>e.kind==='main' && (!shown.has(key(e.slide)) || remaining(e.slide)));
 return {
  entries, available, count,
  get position(){return position;},
  get current(){return entries[position];},
  get previous(){return entries.slice(0,position).reverse().find(e=>e.visited);},
  get returnEntry(){return this.current?.returnPending?this.current.returnTo:undefined;},
  get next(){return preferred || this.returnEntry || this.planned;},
  get planned(){
   if(this.current?.visited && remaining(this.current.slide))return this.current;
   return entries.slice(frontier+1).find(e=>e.kind==='main' && available(e.slide)) ||
    entries.find(e=>e.kind==='main' && remaining(e.slide)) ||
    (!unfinished()?entries.find(e=>e.kind==='closing' && available(e.slide)):undefined);
  },
  get choices(){
   const seen=new Set();
   return entries.map(e=>key(e.slide)===key(this.current?.slide)?this.current:e).filter(e=>{
    if(e.kind!=='main' || !available(e.slide) || (e===this.current && !remaining(e.slide)) || seen.has(key(e.slide)))return false;
    seen.add(key(e.slide));return true;
   });
  },
  canShow(entry,backward=false){return Boolean(entry && (backward?entry===this.previous:
   (entry===this.returnEntry || (available(entry.slide) && (entry.kind!=='closing' || !unfinished())))));},
  rows(entry){return entry.slide.reveal==='step'?Math.min(count(entry.slide)+1,entry.slide.bullets?.length || 0):entry.slide.bullets?.length || 0;},
  visual(entry, upcoming=false){
   if(!entry)return undefined;
   const slide=entry.slide;
   if(slide.reveal!=='step')return slide;
   const bullets=(slide.bullets || []).slice(0,upcoming?this.rows(entry):count(slide));
   return {...slide,bullets,body:bullets.join('\\n')};
  },
  chooseBackup(slide){
   if(!this.current || !slide || !available(slide))return false;
   preferred=key(slide)===key(this.current.slide)?this.current:{slide,mainIndex:this.current.mainIndex,kind:'backup',returnTo:this.current,returnPending:true,visited:false};
   return true;
  },
  choosePlanned(){preferred=this.planned || null;},
  chooseEntry(entry){
   if(!entries.includes(entry) || !this.canShow(entry))return;
   if(entry.kind==='backup' && entry!==this.returnEntry)this.chooseBackup(entry.slide);
   else preferred=entry;
  },
  chooseMain(delta){
   const choices=this.choices;if(!choices.length)return;
   const index=choices.indexOf(this.next);
   preferred=choices[(index<0?(delta>0?0:choices.length-1):(index+delta+choices.length)%choices.length)];
  },
  target(delta){return delta<0?this.previous:this.next;},
  commit(entry,backward=false){
   if(!this.canShow(entry,backward))return;
   const rows=this.rows(entry),returning=entry===this.returnEntry;
   if(backward){position=entries.indexOf(entry);}
   else if(entry===this.current && position===frontier){/* Reveal another row in place. */}
   else {
    const index=entries.indexOf(entry);
    if(entry.visited)entry={...entry,returnPending:returning && entry.returnPending};
    else if(index>=0)entries.splice(index,1);
    entries.splice(frontier+1,0,entry);position=++frontier;
   }
   entry.visited=true;preferred=null;shown.set(key(entry.slide),Math.max(1,rows));
  }
 };
}
let presenterSequence=createPresenterSequence([]);
let presenterNavigating=false;
function defaultPresenterGamepadSettings(){return """ + json.dumps(DEFAULT_GAMEPAD_SETTINGS, ensure_ascii=False, separators=(',', ':')) + """;}
let presenterGamepadSettings=defaultPresenterGamepadSettings();
function createPresenterGamepadInput(){
 let identity=null,armed={left:false,leftY:false,x:false,y:false,confirm:false};
 return (pad,active,settings=defaultPresenterGamepadSettings())=>{
  if(!active || !pad){identity=null;armed={left:false,leftY:false,x:false,y:false,confirm:false};return [];}
  const key=`${pad.index}:${pad.id}`;
  if(identity!==key){identity=key;armed={left:false,leftY:false,x:false,y:false,confirm:false};}
  const actions=[];
  for(const [name,value,negative,positive] of [
   ['left',(pad.axes[settings.history_axis] ?? 0)*(settings.history_invert?-1:1),'previous','next'],
   ['leftY',(pad.axes[settings.main_axis] ?? 0)*(settings.main_invert?-1:1),'mainPrevious','mainNext'],
   ['x',(pad.axes[settings.tabs_axis] ?? 0)*(settings.tabs_invert?-1:1),'tabPrevious','tabNext'],
   ['y',(pad.axes[settings.items_axis] ?? 0)*(settings.items_invert?-1:1),'itemPrevious','itemNext'],
   ['confirm',pad.buttons?.[settings.confirm_button]?.pressed?1:0,'confirm','confirm']
  ]){
   if(Math.abs(value)<settings.neutral_threshold)armed[name]=true;
   else if(Math.abs(value)>settings.activation_threshold && armed[name]){armed[name]=false;actions.push(value>0?positive:negative);}
  }
  return actions;
 };
}
const readPresenterGamepad=createPresenterGamepadInput();
const gamepadFieldIds={history_axis:'history-axis',history_invert:'history-invert',main_axis:'main-axis',main_invert:'main-invert',tabs_axis:'tabs-axis',tabs_invert:'tabs-invert',items_axis:'items-axis',items_invert:'items-invert',confirm_button:'confirm-button',neutral_threshold:'neutral',activation_threshold:'activation'};
function refreshPresenterGamepadDevices(){
 const selected=presenterGamepadDevice.value || presenterGamepadSettings.device_id;
 const pads=Array.from(navigator.getGamepads?.() || []).filter(Boolean);
 presenterGamepadDevice.replaceChildren(new Option('První připojené',''));
 for(const pad of pads)presenterGamepadDevice.append(new Option(`${pad.index}: ${pad.id}`,pad.id));
 if(selected && !pads.some(pad=>pad.id===selected))presenterGamepadDevice.append(new Option(`${selected} (nyní nepřipojený)`,selected));
 presenterGamepadDevice.value=selected;
}
function fillPresenterGamepadForm(settings){
 presenterGamepadEnabled.checked=settings.enabled;presenterGamepadDevice.value=settings.device_id;
 for(const [key,suffix] of Object.entries(gamepadFieldIds)){
  const field=document.querySelector(`#presenter-gamepad-${suffix}`);
  if(typeof settings[key]==='boolean')field.checked=settings[key];else field.value=String(settings[key]);
 }
 refreshPresenterGamepadDevices();
}
function readPresenterGamepadForm(){
 const settings={...presenterGamepadSettings,enabled:presenterGamepadEnabled.checked,device_id:presenterGamepadDevice.value};
 for(const [key,suffix] of Object.entries(gamepadFieldIds)){
  const field=document.querySelector(`#presenter-gamepad-${suffix}`);
  settings[key]=field.type==='checkbox'?field.checked:Number(field.value);
 }
 if(!Number.isInteger(settings.history_axis)||!Number.isInteger(settings.main_axis)||!Number.isInteger(settings.tabs_axis)||!Number.isInteger(settings.items_axis)||!Number.isInteger(settings.confirm_button))throw new Error('Osy a tlačítko musí být celá čísla.');
 if(settings.neutral_threshold<0.05 || settings.neutral_threshold>0.8 || settings.activation_threshold<=settings.neutral_threshold || settings.activation_threshold>1)throw new Error('Aktivační práh musí být větší než neutrální práh.');
 return settings;
}
function applyPresenterGamepadSettings(settings,message){
 presenterGamepadSettings=settings;readPresenterGamepad(null,false,settings);fillPresenterGamepadForm(settings);presenterGamepadSettingsStatus.textContent=message;
}
async function loadPresenterGamepadSettings(){
 try{
  const response=await fetch('/v1/gamepad/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'load'}),signal:AbortSignal.timeout(4000)});
  const result=await response.json();if(!response.ok)throw new Error(result.error || 'Nastavení nelze načíst.');
  applyPresenterGamepadSettings(result.settings,result.saved?'Načteno uložené nastavení tohoto uzlu.':'Používá se výchozí nastavení; dosud nevznikl žádný konfigurační soubor.');
 }catch(error){fillPresenterGamepadForm(presenterGamepadSettings);presenterGamepadSettingsStatus.textContent=error.message || 'Nastavení nelze načíst.';}
}
function renderPresenterContent(target,slide){renderSlideVisual(target,slide);}
function renderPresenterWidget(preview,notes,slide){
 renderPresenterContent(preview,slide);
 notes.textContent=slide?.notes || (slide ? 'Tento slide nemá poznámky.' : 'Žádné poznámky.');
}
let presenterSelectedBackup=null;
function refreshPresenterNext(){
 const next=presenterSequence.next;
 setPresenterNextSelection(presenterSequence.visual(next,true),next?.kind || 'main');
 const planned=presenterSequence.planned;
 const button=document.querySelector('#presenter-planned-slide');
 button.disabled=!planned || presenterNavigating;
 button.textContent=planned?planned.slide.title:'Konec hlavní prezentace';
 button.setAttribute('aria-pressed',String(Boolean(planned && next===planned)));
 presenterNextButton.disabled=!next || presenterNavigating;
}
function setPresenterNextSelection(slide,kind='main'){
 presenterNextSelection=slide;presenterNextSelectionKind=kind;renderPresenterWidget(presenterPrivatePreview,document.querySelector('#presenter-next-notes'),slide);document.querySelector('#presenter-next-title').textContent=kind==='backup'?'Vybraný backup':'Další slide podle plánu';presenterNextPreview.textContent=kind==='backup'?'Zobrazit backup publiku':'Zobrazit další slide';presenterNextPreview.disabled=!slide;presenterNextPreview.dataset.kind=kind;
}
function renderPresenterSlide(){
 const entry=presenterSequence.current;
 presenterIndex=entry?.mainIndex ?? 0;
 const slide=presenterSequence.visual(entry);
 renderPresenterWidget(presenterScreen,presenterNotes,slide);renderPresenterContent(presenterPreview,slide);
 presenterOutline.textContent=slide ? `Cíl: ${slide.title}. Veřejně potvrzený obsah zůstává oddělený od soukromé přípravy.` : 'Osnova se zobrazí po spuštění.';
 refreshPresenterNext();
 renderPresenterBackups();
 presenterCounter.textContent=`Pozice ${presenterSequence.position+1} z ${presenterSequence.entries.length}`;
 presenterPrevButton.disabled=!presenterSequence.target(-1) || presenterNavigating;presenterNextButton.disabled=!presenterSequence.next || presenterNavigating;
 presenterStatus.textContent=slide?`Promítám: ${slide.title}.`:'Prezentace je prázdná.';
 presenterReturnAnchor.disabled=!presenterSequence.returnEntry;
 document.querySelector('#presenter-return').disabled=!presenterSequence.returnEntry;
 presenterReturnAnchor.textContent=presenterSequence.returnEntry?`Návrat: ${presenterSequence.returnEntry.slide.title}`:'Návrat není dostupný';
 renderPresenterDeck();
}
function renderPresenterDeck(){
 presenterDeckList.replaceChildren();
 presenterSequence.entries.forEach((entry,index)=>{
  // Keep the full route visible; consumed entries are history, not new choices.
  const item=document.createElement('li');const button=document.createElement('button');button.type='button';
  button.textContent=`${String(index+1).padStart(2,'0')} ${entry.kind==='backup'?'Backup · ':''}${entry.slide.title}`;
  item.setAttribute('aria-current',String(index===presenterSequence.position));
  item.classList.toggle('presenter-live',index===presenterSequence.position);
  item.classList.toggle('presenter-visited',entry.visited);
  button.disabled=presenterNavigating || !presenterSequence.canShow(entry);
  button.addEventListener('click',()=>{if(presenterNavigating)return;presenterSequence.chooseEntry(entry);refreshPresenterNext();});
  item.append(button);presenterDeckList.append(item);
 });
}
function choosePresenterBackup(backup){
 if(presenterNavigating)return;
 if(!presenterSequence.chooseBackup(backup))return;
 presenterSelectedBackup=backup;
 renderPrivateSelection(backup,`Backup zařazen do dočasného pořadí za aktuální slide. Zatím nepromítnuto.`);
 setPresenterNextSelection(backup,'backup');
 refreshPresenterNext();renderPresenterDeck();
}
async function showPresenterEntry(entry,backward=false){
 if(presenterNavigating || !presenterSequence.canShow(entry,backward))return;
 let failure=null;
 presenterNavigating=true;presenterPrevButton.disabled=true;presenterNextButton.disabled=true;presenterNextPreview.disabled=true;
 try{
  await presentationControl(entry.slide.id?{action:'show',slide:entry.mainIndex,slide_id:entry.slide.id,deck_revision:entry.slide.deck_revision,rows:presenterSequence.rows(entry)}:{action:'show',slide:entry.mainIndex,content:{title:entry.slide.title,body:entry.slide.body}});
  presenterSequence.commit(entry,backward);presenterPrivateSelection=null;
  presenterBlackout=false;presenterView.classList.remove('presenter-blackout');
  presenterBlackoutButton.textContent='Zatemnit';presenterBlackoutState.textContent='Veřejný výstup aktivní';
  presenterLiveState.textContent='ŽIVĚ';
  if(entry.kind==='backup'){presenterExposureValue+=1;presenterExposure.textContent=`Expozice ${presenterExposureValue} · +1`;}
  presenterPrivateStatus.textContent='Výstup potvrzen. Nabídka zohledňuje promítnuté slidy a odhalené řádky.';
 }catch(error){
  failure=error.message;
  presenterPrivateStatus.textContent='Zobrazení nebylo potvrzeno. Pozice zůstala zachovaná; ověřte veřejný výstup.';
 }finally{
  presenterNavigating=false;renderPresenterSlide();if(failure)presenterStatus.textContent=failure;
 }
}
function movePresenter(delta){return showPresenterEntry(presenterSequence.target(delta),delta<0);}
function returnPresenterMain(){
 return showPresenterEntry(presenterSequence.returnEntry);
}
function renderPrivateSelection(slide,status){
 presenterPrivateSelection=slide;presenterPrivateStatus.textContent=status;presenterShowPrivate.disabled=!slide;
 if(slide){setPresenterNextSelection(slide,'private');if(!presenterBranchStarted)presenterBranchStarted=Date.now();}
 else refreshPresenterNext();
}
function createPresenterBackupItem(backup){
 const item=document.createElement('li');const button=document.createElement('button');button.type='button';button.className='presenter-backup';
 const title=document.createElement('strong');title.textContent=backup.title;
 const body=document.createElement('span');body.textContent=backup.body;
 button.append(title,body);
 button.addEventListener('click',()=>choosePresenterBackup(backup));
 item.append(button);return item;
}
function renderPresenterBackups(){
 presenterBackups.replaceChildren();
 const slideBackups=document.querySelector('#presenter-slide-backups');
 const slideStatus=document.querySelector('#presenter-slide-backup-status');
 slideBackups.replaceChildren();
 presenterBackupStatus.textContent=presenterBackupsData.length ? 'Volitelné odbočky pro dotazy publika.' : 'Tento deck nemá backupy.';
 const filter=(presenterBackupSearch.value || '').trim().toLowerCase();
 let assigned=0,visible=0;
 for(const backup of presenterBackupsData){
  if(!presenterSequence.available(backup))continue;
  const linked=Boolean(presenterSlides[presenterIndex]) && (backup.after_slide===presenterIndex || (Array.isArray(backup.after_slides) && backup.after_slides.includes(presenterIndex)));
  if(linked)assigned++;
  if(filter && !`${backup.title} ${backup.body}`.toLowerCase().includes(filter))continue;
  presenterBackups.append(createPresenterBackupItem(backup));
  if(linked){slideBackups.append(createPresenterBackupItem(backup));visible++;}
 }
 slideStatus.textContent=!assigned?'K tomuto slidu nejsou přiřazené žádné backupy.':!visible?'Hledání neodpovídá žádný přiřazený backup.':`Přiřazené backupy: ${visible} z ${assigned}.`;
}
async function loadPresenter(){
 presenterStatus.textContent='Načítám presenter…';
 try{
  const result=await projectRequest('/v1/presentation/status',{action:'start'});
  presenterSlides=Array.isArray(result.slides)?result.slides:[];presenterBackupsData=Array.isArray(result.backups)?result.backups:[];presenterIndex=0;presenterSequence=createPresenterSequence(presenterSlides);presenterSelectedBackup=null;presenterPrivateSelection=null;selectPresenterTab(0);
  presenterPrevButton.disabled=!presenterSlides.length;presenterNextButton.disabled=!presenterSlides.length;presenterFullscreenButton.disabled=!presenterSlides.length;
    presenterExposureValue=0;presenterBlackout=false;presenterMeetingStarted=Date.now();presenterBranchStarted=0;presenterLiveState.textContent='NÁCVIK';presenterExposure.textContent='Expozice 0 · +0';
    applyPresenterRatio(result.ratio);renderPresenterSlide();renderPrivateSelection(null,'Soukromé procházení nemění veřejný výstup.');await showPresenterEntry(presenterSequence.current);
 }catch(error){presenterStatus.textContent=error.message || 'Presenter nebylo možné spustit.';}
}
function openPresenter(){
 location.hash='presenter-open';
 document.body.classList.add('presenter-active');document.querySelector('#project-home').hidden=true;projectView.hidden=true;settingsView.hidden=true;presenterView.hidden=false;
 document.querySelector('#sidebar-project-tools').hidden=true;loadPresenter();
}
async function closePresenter(){
 let saved=false;
 try{const result=await projectRequest('/v1/presentation/status',{action:'end'},120000);saved=result.saved;}
 catch(error){presenterStatus.textContent=`Záznam relace nelze uzavřít: ${error.message}`;return;}
 location.hash='presenter-close';document.body.classList.remove('presenter-active');presenterView.hidden=true;
 document.querySelector('#sidebar-project-tools').hidden=false;
 if(activeProject){const projectId=activeProject.id;projectView.hidden=false;if(saved){await openRegisteredProject(projectId);await loadPresentationEditor(presentationEditorArtifact,false);sidebarPresentationStatus.textContent='Relace byla uložena do projektu.';}}
 else{document.querySelector('#project-home').hidden=false;selectSidebarTab(document.querySelector('#projects-tab'));}
}
presentationOpenButton.addEventListener('click',openPresenter);
document.querySelector('#presenter-back').addEventListener('click',closePresenter);
presenterPrevButton.addEventListener('click',()=>movePresenter(-1));
presenterNextButton.addEventListener('click',()=>movePresenter(1));
presenterFullscreenButton.addEventListener('click',()=>{location.hash='presenter-displays';});
function presenterDisplaySelection(){return presenterDisplayConfiguration?{
 token:presenterDisplayConfiguration.token,
 speaker:Number(presenterDisplayForm.elements.speaker.value),
 audience:Number(presenterDisplayForm.elements.audience.value)}:null;}
function validatePresenterDisplaySelection(){
 const selection=presenterDisplaySelection();
 const same=selection&&selection.speaker===selection.audience;
 document.querySelector('#presenter-display-apply').disabled=!selection||same;
 presenterDisplayStatus.textContent=same?'Řečník a diváci musí mít různé displeje.':'';
}
function showPresenterDisplayConfiguration(configuration){
 if(!configuration||typeof configuration.token!=='string'||!Array.isArray(configuration.screens)||!configuration.screens.length)return;
 presenterDisplayConfiguration=configuration;
 const speaker=presenterDisplayForm.elements.speaker,audience=presenterDisplayForm.elements.audience;
 speaker.replaceChildren();audience.replaceChildren();
 const disabled=document.createElement('option');disabled.value='-1';disabled.textContent='Bez promítání';audience.append(disabled);
 for(const screen of configuration.screens){
  const left=document.createElement('option'),right=document.createElement('option');
  left.value=right.value=String(screen.index);left.textContent=right.textContent=screen.label;speaker.append(left);audience.append(right);
 }
 speaker.value=String(configuration.speaker);audience.value=String(configuration.audience);
 presenterDisplayStatus.textContent='Veřejný výstup zůstává skrytý do potvrzení rolí.';
 validatePresenterDisplaySelection();if(!presenterDisplayDialog.open)presenterDisplayDialog.showModal();
}
function closePresenterDisplayConfiguration(){
 presenterDisplayConfiguration=null;if(presenterDisplayDialog.open)presenterDisplayDialog.close();
}
function setPresenterDisplayNativeError(message){
 presenterDisplayStatus.textContent=message||'Nastavení displejů se nepodařilo použít.';
 document.querySelector('#presenter-display-apply').disabled=false;
}
function requestPresenterDisplayAction(action){
 const selection=presenterDisplaySelection();if(!selection)return;
 requestNativeAction(action,selection);
}
presenterDisplayForm.elements.speaker.addEventListener('change',validatePresenterDisplaySelection);
presenterDisplayForm.elements.audience.addEventListener('change',validatePresenterDisplaySelection);
document.querySelector('#presenter-display-identify').addEventListener('click',()=>requestPresenterDisplayAction('presenter-displays-identify'));
document.querySelector('#presenter-display-cancel').addEventListener('click',()=>requestNativeAction('presenter-displays-cancel'));
presenterDisplayDialog.addEventListener('cancel',event=>{event.preventDefault();requestNativeAction('presenter-displays-cancel');});
presenterDisplayForm.addEventListener('submit',event=>{event.preventDefault();validatePresenterDisplaySelection();
 if(document.querySelector('#presenter-display-apply').disabled)return;
 document.querySelector('#presenter-display-apply').disabled=true;presenterDisplayStatus.textContent='Přesouvám okna na potvrzené displeje…';
 requestPresenterDisplayAction('presenter-displays-apply');
});
presenterView.addEventListener('keydown',event=>{
 if(event.repeat || event.target.closest('input,textarea,[contenteditable="true"],[role="tablist"]'))return;
 if(event.key==='ArrowLeft'){event.preventDefault();movePresenter(-1);}
 if(event.key==='ArrowRight'){event.preventDefault();movePresenter(1);}
});
presenterShowPrivate.addEventListener('click',()=>movePresenter(1));
presenterReturnAnchor.addEventListener('click',returnPresenterMain);
document.querySelector('#presenter-return').addEventListener('click',returnPresenterMain);
document.querySelector('#presenter-planned-slide').addEventListener('click',()=>{
 if(presenterNavigating)return;
 presenterSequence.choosePlanned();presenterPrivateSelection=null;refreshPresenterNext();renderPresenterDeck();
 presenterPrivateStatus.textContent='Vybrán plánovaný slide. Zatím nepromítnuto.';
});
presenterBlackoutButton.addEventListener('click',async()=>{presenterBlackout=!presenterBlackout;presenterView.classList.toggle('presenter-blackout',presenterBlackout);presenterBlackoutButton.textContent=presenterBlackout?'Zobrazit veřejný výstup':'Zatemnit';presenterBlackoutState.textContent=presenterBlackout?'Veřejný výstup zatemněn':'Veřejný výstup aktivní';try{await presentationControl({action:presenterBlackout?'blackout':'reveal'});}catch(error){presenterStatus.textContent=error.message;}});
presenterQuestionButton.addEventListener('click',()=>{if(!presenterBranchStarted)presenterBranchStarted=Date.now();presenterQuestionCount.textContent=String(Number(presenterQuestionCount.textContent)+1);presenterQuestionStatus.textContent=`Odbočka uložena: slide ${presenterIndex+1}. Veřejný výstup zůstává beze změny.`;});
presenterNextPreview.addEventListener('click',()=>movePresenter(1));
presenterBackupSearch.addEventListener('input',renderPresenterBackups);
const presenterTabs=[...document.querySelectorAll('.presenter-tabs [role="tab"]')];
let presenterTabIndex=0,presenterItemIndex=0;
function presenterItems(){
 if(presenterTabIndex===0)return [document.querySelector('#presenter-planned-slide'),...document.querySelector('#presenter-slide-backups').querySelectorAll('button')].filter(button=>!button.disabled);
 if(presenterTabIndex===1)return [...presenterBackups.querySelectorAll('button')];
 if(presenterTabIndex===2)return [presenterQuestionButton];
 return [];
}
function updatePresenterItem(select=false){
 const items=presenterItems();if(!items.length)return;presenterItemIndex=Math.max(0,Math.min(items.length-1,presenterItemIndex));
 for(const [index,item] of items.entries()){item.classList.toggle('presenter-gamepad-selected',index===presenterItemIndex);item.setAttribute('aria-current',index===presenterItemIndex?'true':'false');}
 items[presenterItemIndex].focus({preventScroll:true});
 if(select && presenterTabIndex!==2)items[presenterItemIndex].click();
 presenterGamepadStatus.textContent=`Gamepad: ${presenterTabs[presenterTabIndex].textContent} · ${presenterItemIndex+1}/${items.length}`;
}
function selectPresenterTab(index){presenterTabIndex=(index+presenterTabs.length)%presenterTabs.length;presenterItemIndex=0;for(const [tabIndex,tab] of presenterTabs.entries())tab.setAttribute('aria-selected',String(tabIndex===presenterTabIndex));document.querySelector('#presenter-slide-list').hidden=presenterTabIndex!==0;document.querySelector('#presenter-backup-list').hidden=presenterTabIndex!==1;document.querySelector('#presenter-question-list').hidden=presenterTabIndex!==2;presenterTabStatus.textContent=presenterTabIndex===0?'K tomuto slidu · veřejný a následující slide':presenterTabIndex===1?'Všechny backupy · soukromá knihovna':'Otázky a odpovědi · strom odboček';refreshPresenterNext();updatePresenterItem();}
for(const [index,tab] of presenterTabs.entries())tab.addEventListener('click',()=>selectPresenterTab(index));
function movePresenterItem(delta){const items=presenterItems();if(!items.length)return;presenterItemIndex=(presenterItemIndex+delta+items.length)%items.length;updatePresenterItem(true);}
document.querySelector('#presenter-gamepad-refresh').addEventListener('click',()=>{refreshPresenterGamepadDevices();presenterGamepadSettingsStatus.textContent='Seznam zařízení byl obnoven.';});
document.querySelector('#presenter-gamepad-apply').addEventListener('click',()=>{
 try{applyPresenterGamepadSettings(readPresenterGamepadForm(),'Nastavení je použito pro tento běh; na disk se nic nezapsalo.');}
 catch(error){presenterGamepadSettingsStatus.textContent=error.message;}
});
document.querySelector('#presenter-gamepad-save').addEventListener('click',async()=>{
 const button=document.querySelector('#presenter-gamepad-save');button.disabled=true;
 try{
  const settings=readPresenterGamepadForm();
  const response=await fetch('/v1/gamepad/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save',settings}),signal:AbortSignal.timeout(4000)});
  const result=await response.json();if(!response.ok)throw new Error(result.error || 'Nastavení nelze uložit.');
  applyPresenterGamepadSettings(result.settings,'Nastavení bylo uloženo pouze na tomto uzlu.');
 }catch(error){presenterGamepadSettingsStatus.textContent=error.message || 'Nastavení nelze uložit.';}
 finally{button.disabled=false;}
});
function pollPresenterGamepad(){
 const pads=Array.from(navigator.getGamepads?.() || []).filter(Boolean);
 const pad=presenterGamepadSettings.device_id?pads.find(item=>item.id===presenterGamepadSettings.device_id):pads[0];
 const active=presenterGamepadSettings.enabled && !presenterView.hidden && !document.hidden && document.hasFocus();
 const actions=readPresenterGamepad(pad,active,presenterGamepadSettings);
 presenterGamepadStatus.textContent=!presenterGamepadSettings.enabled?'Gamepad: vypnutý v nastavení.':pad?`Gamepad: ${pad.id.slice(0,32)} · mapování lze změnit níže`:'Gamepad: čekám na vybrané zařízení.';
 presenterGamepadLive.textContent=pad?`Živý vstup: osy ${pad.axes.map(value=>Number(value).toFixed(2)).join(', ')} · stisknutá tlačítka ${pad.buttons.map((button,index)=>button.pressed?index:null).filter(index=>index!==null).join(', ') || 'žádná'}`:'Živý vstup: čekám na zařízení.';
 // Horizontal navigation projects the choice visible before this frame.
 if(actions.includes('previous'))movePresenter(-1);
 else if(actions.includes('next') || actions.includes('confirm'))movePresenter(1);
 else if(!presenterNavigating && (actions.includes('mainPrevious') || actions.includes('mainNext'))){
  presenterSequence.chooseMain(actions.includes('mainNext')?1:-1);refreshPresenterNext();renderPresenterDeck();
 }
 else if(!presenterNavigating){
  for(const action of actions){
   if(action==='tabPrevious')selectPresenterTab(presenterTabIndex-1);
   if(action==='tabNext')selectPresenterTab(presenterTabIndex+1);
   if(action==='itemPrevious')movePresenterItem(-1);
   if(action==='itemNext')movePresenterItem(1);
  }
 }
 requestAnimationFrame(pollPresenterGamepad);
}
addEventListener('gamepadconnected',()=>{refreshPresenterGamepadDevices();presenterGamepadStatus.textContent='Gamepad: připojen.';updatePresenterItem();});
addEventListener('blur',()=>readPresenterGamepad(null,false));
addEventListener('gamepaddisconnected',()=>{readPresenterGamepad(null,false);refreshPresenterGamepadDevices();presenterGamepadStatus.textContent='Gamepad: odpojen.';});
loadPresenterGamepadSettings();
requestAnimationFrame(pollPresenterGamepad);
selectPresenterTab(0);
"""
JS += """
const projectCards=document.querySelector('#project-cards');
const sidebarProjects=document.querySelector('#sidebar-project-list');
const projectStatus=document.querySelector('#project-status');
const projectView=document.querySelector('#project-view');
const settingsView=document.querySelector('#settings-view');
const projectCreateView=document.querySelector('#project-create-view');
const projectTrashView=document.querySelector('#project-trash-view');
const projectRepairView=document.querySelector('#project-repair-view');
const sourceImportView=document.querySelector('#source-import-view');
const notebookImportView=document.querySelector('#notebooklm-import-view');
const historyView=document.querySelector('#history-view');
const artifactEditorView=document.querySelector('#artifact-editor-view');
const todoTree=document.querySelector('#todo-tree');
const todoStatus=document.querySelector('#todo-status');
const sidebarArtifacts=document.querySelector('#sidebar-artifact-list');
const sidebarArtifactStatus=document.querySelector('#sidebar-artifact-status');
const workspaceSidebar=document.querySelector('#workspace-sidebar');
const mobileSidebarToggle=document.querySelector('#mobile-sidebar-toggle');
const mobileSidebarBackdrop=document.querySelector('#mobile-sidebar-backdrop');
const sidebarLayoutToggle=document.querySelector('#sidebar-layout-toggle');
const mobileViewport=window.matchMedia('(max-width:640px)');
let mobileSidebarReturnFocus=null;
function compactSidebarActive(){return workspaceSidebar.classList.contains('sidebar-compact')&&!mobileViewport.matches;}
function closeCompactSidebarMenu(){
 if(!compactSidebarActive()||!workspaceSidebar.classList.contains('sidebar-menu-open'))return;
 workspaceSidebar.classList.remove('sidebar-menu-open');syncCompactSidebar();
}
function syncCompactSidebar(){
 const compact=workspaceSidebar.classList.contains('sidebar-compact');
 const menuOpen=compactSidebarActive()&&workspaceSidebar.classList.contains('sidebar-menu-open');
 sidebarLayoutToggle.setAttribute('aria-pressed',String(compact));
 sidebarLayoutToggle.setAttribute('aria-label',compact?'Rozbalit hlavní panel':'Sbalit hlavní panel');
 sidebarLayoutToggle.querySelector('.sidebar-layout-label').textContent=compact?'Rozbalit panel':'Sbalit panel';
 for(const tab of document.querySelectorAll('#sidebar-tabs [role="tab"]')){
  if(compact)tab.setAttribute('aria-expanded',String(menuOpen&&tab.getAttribute('aria-selected')==='true'));
  else tab.removeAttribute('aria-expanded');
 }
}
function setCompactSidebar(compact){
 workspaceSidebar.classList.toggle('sidebar-compact',compact);workspaceSidebar.classList.remove('sidebar-menu-open');
 syncCompactSidebar();
}
sidebarLayoutToggle.addEventListener('click',()=>setCompactSidebar(!workspaceSidebar.classList.contains('sidebar-compact')));
function syncMobileSidebar(){
 const open=document.body.classList.contains('mobile-sidebar-open')&&mobileViewport.matches;
 mobileSidebarToggle.setAttribute('aria-expanded',String(open));mobileSidebarBackdrop.hidden=!open;
 workspaceSidebar.inert=mobileViewport.matches&&!open;
}
function openMobileSidebar(){
 if(!mobileViewport.matches)return;mobileSidebarReturnFocus=mobileSidebarToggle;
 document.body.classList.add('mobile-sidebar-open');syncMobileSidebar();
 const target=[...workspaceSidebar.querySelectorAll('button:not([hidden]),[href],input:not([hidden]),select:not([hidden]),textarea:not([hidden])')].find(item=>item.offsetParent!==null);
 if(target)target.focus();
}
function closeMobileSidebar(restoreFocus=true){
 document.body.classList.remove('mobile-sidebar-open');syncMobileSidebar();
 if(restoreFocus&&mobileSidebarReturnFocus instanceof HTMLElement)mobileSidebarReturnFocus.focus();
 mobileSidebarReturnFocus=null;
}
mobileSidebarToggle.addEventListener('click',()=>document.body.classList.contains('mobile-sidebar-open')?closeMobileSidebar():openMobileSidebar());
mobileSidebarBackdrop.addEventListener('click',()=>closeMobileSidebar());
document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if(document.body.classList.contains('mobile-sidebar-open')){event.preventDefault();closeMobileSidebar();return;}if(compactSidebarActive()&&workspaceSidebar.classList.contains('sidebar-menu-open')){event.preventDefault();closeCompactSidebarMenu();}});
workspaceSidebar.addEventListener('click',event=>{if(event.target.closest('#open-notebooklm-import,#sidebar-create-project,#sidebar-register-project,#resource-monitor-open,#sidebar-project-trash,#new-document,#open-source-import,.sidebar-list-main,.sidebar-item-menu-items button,#chat-new-thread')){closeMobileSidebar();closeCompactSidebarMenu();}});
document.addEventListener('click',event=>{if(!workspaceSidebar.contains(event.target))closeCompactSidebarMenu();});
mobileViewport.addEventListener('change',()=>{document.body.classList.remove('mobile-sidebar-open');workspaceSidebar.classList.remove('sidebar-menu-open');syncMobileSidebar();syncCompactSidebar();});
syncMobileSidebar();
const sidebarTabs=[...document.querySelectorAll('#sidebar-tabs [role="tab"]')];
let federationNetworkRunning=false;
let federationDeploymentRunning=false;
function selectSidebarTab(selected){
 if(!selected || selected.disabled)return;
 if((federationNetworkRunning||federationDeploymentRunning)&&selected.id!=='federation-tab'){
  if(federationNetworkRunning)document.querySelector('#federation-network-status').textContent='Síťová operace právě probíhá; stránku nelze opustit.';
  if(federationDeploymentRunning)document.querySelector('#federation-deployment-status').textContent='Nasazení právě probíhá; stránku nelze opustit.';
  return;
 }
 const federationPages=[document.querySelector('#federation-view'),document.querySelector('#federation-network-view'),document.querySelector('#federation-deployment-view')];
 if(selected.id!=='federation-tab'&&federationPages.some(view=>!view.hidden)){
  for(const view of federationPages)view.hidden=true;
  if(activeProject)projectView.hidden=false;else document.querySelector('#project-home').hidden=false;
 }
 for(const tab of sidebarTabs){
  const active=tab===selected;
  tab.setAttribute('aria-selected',String(active));tab.tabIndex=active ? 0 : -1;
  document.getElementById(tab.getAttribute('aria-controls')).hidden=!active;
 }
}
for(const tab of sidebarTabs){
 tab.addEventListener('click',()=>{
  if(!compactSidebarActive()){selectSidebarTab(tab);return;}
  const close=tab.getAttribute('aria-selected')==='true'&&workspaceSidebar.classList.contains('sidebar-menu-open');
  selectSidebarTab(tab);workspaceSidebar.classList.toggle('sidebar-menu-open',!close);syncCompactSidebar();
 });
 tab.addEventListener('keydown',event=>{
  const visible=sidebarTabs.filter(item=>!item.hidden&&!item.disabled),index=visible.indexOf(tab);
  const next={ArrowRight:(index+1)%visible.length,
   ArrowLeft:(index-1+visible.length)%visible.length,
   Home:0,End:visible.length-1}[event.key];
  if(next===undefined) return;
  event.preventDefault();selectSidebarTab(visible[next]);visible[next].focus();
 });
}
let currentArtifacts=[];
function sidebarItemMenu(label,actions,legacyClass=''){
 const menu=document.createElement('details');menu.className=`sidebar-item-menu ${legacyClass}`.trim();
 const trigger=document.createElement('summary');trigger.setAttribute('aria-label',`Akce položky ${label}`);trigger.textContent='⋮';
 const items=document.createElement('div');items.className='sidebar-item-menu-items';items.setAttribute('role','menu');
 for(const action of actions){
  const button=document.createElement('button');button.type='button';button.textContent=action.label;button.disabled=Boolean(action.disabled);button.setAttribute('role','menuitem');
  button.addEventListener('click',async event=>{event.stopPropagation();menu.open=false;closeCompactSidebarMenu();await action.run(event.currentTarget);});items.append(button);
 }
 menu.append(trigger,items);return menu;
}
function renderSidebarArtifacts(items){
 currentArtifacts=items;
 sidebarArtifacts.replaceChildren();
 sidebarArtifactStatus.textContent=items.length ? `Počet položek: ${items.length}` : 'Zatím tu nejsou žádné podklady.';
 for(const item of items){
  const row=document.createElement('li');row.className='sidebar-list-row sidebar-artifact-row';
  const title=document.createElement('button'),name=document.createElement('span');title.className='sidebar-list-main sidebar-artifact-title';name.className='sidebar-item-title';name.textContent=item.title;
  title.dataset.id=item.id;title.setAttribute('aria-current','false');
  title.addEventListener('click',()=>openPreview(item.id));
  const id=document.createElement('small');id.className='sidebar-item-id sidebar-artifact-id';id.textContent=item.id;title.append(name,id);
  const actions=[{label:'Zobrazit',run:()=>openPreview(item.id)}];
  if(item.kind==='document'&&!activeProject?.readOnly)actions.push(
   {label:'Upravit / přejmenovat',run:()=>openArtifactEditor(item)},
   {label:'Připravit smazání',run:()=>openArtifactEditor(item,true)});
  actions.push(
   {label:'Zobrazit historii',run:async()=>{await openPreview(item.id);if(selectedArtifact===item.id)await openHistory();}},
   {label:'Kopírovat ID',run:async()=>{try{await navigator.clipboard.writeText(item.id);sidebarArtifactStatus.textContent='ID položky bylo zkopírováno.';}catch(error){sidebarArtifactStatus.textContent=`ID položky: ${item.id}`;}}});
  row.append(title,sidebarItemMenu(item.title,actions,'sidebar-artifact-menu'));
  sidebarArtifacts.append(row);
 }
 renderSummarySources();
 renderWorkflowSources();
 renderExtractionSources();
 renderMetadataSources();
 renderTaskArtifactSources();
}
let viewRequest=0;
const createTodo=document.querySelector('#create-main-todo');
createTodo.addEventListener('click',()=>openMainTodoEditor());
document.querySelector('#project-overview-edit-todo').addEventListener('click',()=>openMainTodoEditor());
const mobileProjectOverview=window.matchMedia('(max-width:640px)');
const mobileProjectOverviewItemLimit=5;
let projectOverviewHistory,projectOverviewTodo;
function visibleProjectOverviewItems(items){return mobileProjectOverview.matches?items.slice(0,mobileProjectOverviewItemLimit):items;}
function renderProjectHistory(history){
 projectOverviewHistory=history;
 const list=document.querySelector('#project-overview-history-list');
 const status=document.querySelector('#project-overview-history-status');
 list.replaceChildren();
 if(!history){status.textContent='Otevřete projekt.';return;}
 const visible=visibleProjectOverviewItems(history.entries);
 for(const item of visible){
  const row=document.createElement('li');row.className='project-history-row';
  const subject=document.createElement('strong');subject.textContent=item.subject||'Commit bez názvu';
  const detail=document.createElement('small');
  const parsed=new Date(item.date);const date=Number.isNaN(parsed.getTime()) ? item.date :
   new Intl.DateTimeFormat('cs-CZ',{dateStyle:'medium',timeStyle:'short'}).format(parsed);
  detail.textContent=`${date} · ${item.author} · ${item.commit_id.slice(0,8)}`;
  row.append(subject,detail);list.append(row);
 }
 status.textContent=history.entries.length ? `${history.entries.length} posledních změn` : 'Projekt zatím nemá historii změn.';
 if(visible.length<history.entries.length)status.textContent+=` · na telefonu zobrazeno ${visible.length}`;
 if(history.truncated)status.textContent+=' Zobrazeno posledních 20 záznamů.';
}
function renderProjectOverview(todo){
 projectOverviewTodo=todo;
 const list=document.querySelector('#project-overview-task-list');
 const status=document.querySelector('#project-overview-task-status');
 const edit=document.querySelector('#project-overview-edit-todo');
 list.replaceChildren();edit.textContent=todo ? 'Upravit seznam úkolů' : 'Vytvořit seznam úkolů';
 if(!todo){status.textContent='Projekt zatím nemá hlavní seznam úkolů.';return;}
 if(todo.status!=='ready'){status.textContent='Hlavní seznam úkolů nelze zobrazit v tomto formátu nebo velikosti.';return;}
 const open=todo.items.filter(item=>!item.checked);
 const visible=visibleProjectOverviewItems(open);
 for(const item of visible){
  const row=document.createElement('li');row.className='dashboard-task-row';
  const button=document.createElement('button');button.type='button';
  const title=document.createElement('span');title.textContent=item.title;
  const detail=document.createElement('small');detail.textContent=item.depth ? `Vnořená úroveň ${item.depth}` : 'Hlavní úroveň';
  button.append(title,detail);button.addEventListener('click',()=>openMainTodoEditor());row.append(button);list.append(row);
 }
 status.textContent=open.length ? `${open.length} nehotových · ${todo.completed} z ${todo.total} hotovo` :
  (todo.total ? 'Všechny úkoly jsou hotové.' : 'Zatím bez úkolů.');
 if(visible.length<open.length)status.textContent+=` · na telefonu zobrazeno ${visible.length}`;
 if(todo.truncated)status.textContent+=' Zobrazeno prvních 1000 položek.';
}
mobileProjectOverview.addEventListener('change',()=>{
 if(projectOverviewHistory!==undefined)renderProjectHistory(projectOverviewHistory);
 if(projectOverviewTodo!==undefined)renderProjectOverview(projectOverviewTodo);
});
function renderTodo(todo){
 createTodo.hidden=false;createTodo.textContent=todo ? 'Upravit seznam úkolů' : 'Vytvořit seznam úkolů';
 document.querySelector('#todo-help').hidden=!todo;
 todoTree.replaceChildren();
 document.querySelector('#todo-title').textContent=todo?.title || '';
 if(!todo){todoStatus.textContent='Projekt zatím nemá hlavní seznam úkolů.';return;}
 if(todo.status!=='ready'){todoStatus.textContent='Hlavní seznam úkolů nelze zobrazit v tomto formátu nebo velikosti.';return;}
 todoStatus.textContent=todo.total ? `${todo.completed} z ${todo.total} hotovo` : 'Zatím bez úkolů.';
 if(todo.truncated) todoStatus.textContent+=' Zobrazeno prvních 1000 položek.';
 const lists=[todoTree];
 for(let i=0;i<todo.items.length;i++){
  const item=todo.items[i];lists.length=item.depth+1;
  const row=document.createElement('li');row.dataset.depth=item.depth;row.className='sidebar-list-row';
  const label=document.createElement('span');label.className='todo-label sidebar-list-main';label.tabIndex=0;label.setAttribute('role','button');label.setAttribute('aria-label',`Upravit seznam úkolů: ${item.title}`);
  const check=document.createElement('input');check.type='checkbox';check.checked=item.checked;check.disabled=true;
  check.setAttribute('aria-label',item.checked ? 'Hotovo' : 'Nehotovo');
  const title=document.createElement('span');title.className='todo-text';title.textContent=item.title;
  label.append(check,title);
  label.addEventListener('click',event=>{event.stopPropagation();openMainTodoEditor();});
  label.addEventListener('keydown',event=>{if(!['Enter',' '].includes(event.key))return;event.preventDefault();event.stopPropagation();openMainTodoEditor();});
  if(item.checked) row.classList.add('todo-done');
  if(todo.items[i+1]?.depth>item.depth){
   const branch=document.createElement('details');branch.open=true;
   const summary=document.createElement('summary');summary.append(label);branch.append(summary);
   const children=document.createElement('ul');branch.append(children);row.append(branch);
   lists[item.depth+1]=children;
  }else{row.append(label);}
  row.append(sidebarItemMenu(item.title,[{label:'Upravit seznam úkolů',run:()=>openMainTodoEditor()}],'sidebar-todo-menu'));
  lists[item.depth].append(row);
 }
}
const projectSidebarTabs=['todo-tab','artifacts-tab','tools-tab','presentations-tab'];
function syncSidebarProjectAvailability(){
 const available=Boolean(activeProject);
 for(const id of projectSidebarTabs){const tab=document.getElementById(id);tab.disabled=!available;tab.setAttribute('aria-disabled',String(!available));}
 const writable=available&&!activeProject.readOnly;
 document.querySelector('#chat-new-thread').disabled=!writable;
 for(const id of ['new-document','open-source-import','create-main-todo','project-overview-edit-todo'])document.getElementById(id).disabled=!writable;
 document.querySelector('#project-read-only').hidden=!available||!activeProject.readOnly;
 if(!available && projectSidebarTabs.includes(sidebarTabs.find(tab=>tab.getAttribute('aria-selected')==='true')?.id))selectSidebarTab(document.querySelector('#projects-tab'));
}
function clearProject(){
 ++viewRequest;
 resetProjectConflicts();
 artifactEditorItem=null;artifactEditorAttempt=null;artifactEditorBaseline=null;artifactEditorDirty=false;hideArtifactDeletion();
 presentationEditorView=null;presentationEditorDeck=null;presentationEditorArtifact=null;presentationEditorSlide=null;presentationEditorNew=false;presentationEditorDirty=false;presentationEditorAttempt=null;presentationEditorWorkspace.hidden=true;presentationEditorDocuments.replaceChildren();sidebarPresentationList.replaceChildren();sidebarPresentationStatus.textContent='Otevřete projekt.';presentationEditorStatus.textContent='Otevřete projekt.';
 clearPreview();activeProject=null;document.querySelector('#chat-draft').value='';
 currentArtifacts=[];clearSummary();clearWorkflow();clearExtraction();clearImage();clearMetadata();
 activeThread=null;activeTaskThreadId=null;taskOutcomes=[];pendingChatRequest=null;
 hideSearchRecovery();
 pendingSearchPreview=null;document.querySelector('#search-preview').hidden=true;
 pendingExternalPreview=null;document.querySelector('#external-preview').hidden=true;
 knownThreads=[];pendingThreadDeletion=null;renderThreadList([]);
 document.querySelector('#chat-delete-preview').hidden=true;
 document.querySelector('#chat-submit').disabled=true;document.querySelector('#chat-messages').replaceChildren();
 document.querySelector('#chat-backend-status').textContent='Otevřete projekt.';
 document.querySelector('#chat-operation-status').textContent='';
 document.querySelector('#project-home').hidden=false;
 projectCreateView.hidden=true;
 projectTrashView.hidden=true;
 projectRepairView.hidden=true;
 projectRepairTarget=null;projectRepairReport=null;resetProjectRepairPlan();
 settingsView.hidden=true;
 sourceImportView.hidden=true;
 notebookImportView.hidden=true;
 historyView.hidden=true;
 artifactEditorView.hidden=true;
 syncSidebarProjectAvailability();selectSidebarTab(document.querySelector('#projects-tab'));
 selectMainTab(mainTabs[0]);
 sidebarArtifacts.replaceChildren();sidebarArtifactStatus.textContent='Otevřete projekt.';
 todoTree.replaceChildren();document.querySelector('#todo-title').textContent='';
 todoStatus.textContent='Otevřete projekt.';createTodo.hidden=true;document.querySelector('#todo-help').hidden=true;
 renderProjectOverview(null);renderProjectHistory(null);
 projectView.hidden=true;
 document.querySelector('#project-title').textContent='';
 document.querySelector('#project-description').textContent='';
 document.querySelector('#project-commit').textContent='';
}
async function projectRequest(path,body,timeout=60000){
 let response;
 try{response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body),signal:AbortSignal.timeout(timeout)});
 }catch(error){if(error?.name==='TimeoutError' || error?.name==='AbortError' ||
    String(error?.message || '').toLowerCase().includes('signal timed out')){
   const timeoutError=new Error('Čekání na odpověď vypršelo. Operace mohla na backendu doběhnout; obnovte stav a původní běh automaticky neopakujte.');
   timeoutError.status=408;timeoutError.outcome='unknown';throw timeoutError;
  }throw error;}
 const result=await response.json();
 if(!response.ok){const error=new Error(result.error || 'Požadavek byl odmítnut.');
  error.status=response.status;error.diagnostic=result.diagnostic;
  error.outcome=result.outcome;error.retry=result.retry;throw error;}
 return result;
}
const sourceImportForm=document.querySelector('#source-import-form');
const sourceImportStatus=document.querySelector('#source-import-status');
const googleDriveStatus=document.querySelector('#google-drive-status');
const googleDrivePreview=document.querySelector('#google-drive-preview');
const googleDrivePlanElement=document.querySelector('#google-drive-plan');
const googleDriveConnectCopy=document.querySelector('#google-drive-connect-copy');
const googleDriveFiles=document.querySelector('#google-drive-files');
let googleDriveSelection=null,googleDrivePlan=null,googleDriveOperation=null,googleDrivePoll=null;
let sourceImportAttempt=null;
function setGoogleDriveStep(current,completed=0){
 for(const item of document.querySelectorAll('#google-drive-steps li')){
  const step=Number(item.dataset.step);item.classList.toggle('done',step<=completed);item.classList.toggle('current',step===current);
  if(step===current)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');
 }
}
function bytesBase64(buffer){const bytes=new Uint8Array(buffer);let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));return btoa(binary);}
function closeSourceImport(){
 if(googleDrivePoll){clearTimeout(googleDrivePoll);googleDrivePoll=null;}
 sourceImportView.hidden=true;
 if(activeProject)projectView.hidden=false;
 else document.querySelector('#project-home').hidden=false;
}
function openSourceImport(){
 if(!activeProject||!canLeaveWorkspaceEditors())return;
 const predecessors=document.querySelector('#source-import-supersedes');predecessors.replaceChildren();
 const standalone=document.createElement('option');standalone.value='';standalone.textContent='Samostatný zdroj';predecessors.append(standalone);
 for(const item of currentArtifacts.filter(item=>item.kind==='source')){
  const option=document.createElement('option');option.value=item.id;option.textContent=`${item.title} — ${item.id}`;predecessors.append(option);
 }
 sourceImportStatus.textContent='Vyberte soubor; do potvrzení se nic neimportuje.';
 resetGoogleDrivePlan();loadGoogleDriveStatus();
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;projectView.hidden=true;sourceImportView.hidden=false;
 selectSidebarTab(document.querySelector('#artifacts-tab'));
 document.querySelector('#source-import-heading').focus();
}
function resetGoogleDrivePlan(){
 googleDrivePlan=null;googleDriveOperation=null;googleDrivePreview.hidden=true;
 document.querySelector('#google-drive-confirm-check').checked=false;
 document.querySelector('#google-drive-run').disabled=true;googleDrivePlanElement.textContent='';googleDriveFiles.replaceChildren();
 document.querySelector('#google-drive-summary').textContent='';setGoogleDriveStep(1);
}
async function loadGoogleDriveStatus(){
 try{const status=await projectRequest('/v1/google-drive/status',{});
  googleDriveConnectCopy.textContent=status.configured ?
   'Připojení aplikace je připravené. Přihlašovací údaje zadáte až přímo Googlu v dalším kroku.' :
   'Nejdřív je potřeba jednorázově uložit OAuth klienta pro tento uzel. Průvodce vás zavede přímo na správné místo v nastavení.';
  document.querySelector('#google-drive-open-settings').hidden=status.configured;
  googleDriveStatus.textContent=status.configured ?
   'Můžete se přihlásit ke Googlu a vybrat soubory. Projekt se tím ještě nezmění.' :
   'Google Drive zatím není připojený. Použijte tlačítko Nastavit připojení.';
  document.querySelector('#google-drive-select').disabled=!status.configured;
  document.querySelector('#google-drive-recover').hidden=!status.pending_import;
  setGoogleDriveStep(status.pending_import ? 4 : (status.configured ? 2 : 1),status.pending_import ? 3 : (status.configured ? 1 : 0));
  if(status.pending_import)googleDriveStatus.textContent='Na tomto uzlu čeká dříve potvrzený import. Můžete bezpečně pokračovat z lokálního stagingu.';
  const resumable=status.pending_selection;
  if(!status.pending_import && resumable && resumable.project_id===activeProject.id && resumable.expected_head===activeProject.head){
   document.querySelector('#google-drive-privacy').value=resumable.privacy;googleDriveSelection=resumable.selection_id;
   document.querySelector('#google-drive-select').disabled=true;setGoogleDriveStep(2,1);
   googleDriveStatus.textContent='Navazuji na dokončený výběr z Googlu a připravuji bezpečný náhled…';
   if(googleDrivePoll)clearTimeout(googleDrivePoll);googleDrivePoll=setTimeout(pollGoogleDrive,0);
  }
 }catch(error){googleDriveConnectCopy.textContent='Stav připojení se nepodařilo ověřit.';googleDriveStatus.textContent=error.message;document.querySelector('#google-drive-select').disabled=true;}
}
function renderGoogleDrivePlan(plan){
 const lines=[`Cíl: ${activeProject.title} (${plan.project_id})`,`Projektová verze: ${plan.expected_head}`,
  `Soukromí: ${plan.privacy}`,`Počet souborů: ${plan.file_count}`,
  `Drive zápisy: ne · průběžná synchronizace: ne`,''];
 for(const [index,item] of plan.files.entries()){
  lines.push(`${index+1}. ${item.name} → ${item.filename}`,
   `   zdrojový typ: ${item.source_mime_type}`,
   `   revize: ${item.source_revision} · vznik zdroje: ${item.source_created_at}`,
   item.export_mime_type ? `   transformace: export do ${item.export_mime_type} (limit 10 MiB)` :
    `   původní bajty: ano · deklarovaná velikost: ${item.size} B`,
   item.supersedes ? `   navazuje na: ${item.supersedes}` : '   samostatný zdroj');
 }
 if(plan.blockers.length)lines.push('',...plan.blockers.map(value=>'BLOKACE: '+value));
 document.querySelector('#google-drive-summary').textContent=`Vybráno ${plan.file_count} položek pro projekt ${activeProject.title}. Zkontrolujte zejména PDF exporty, privacy a případné blokace.`;
 googleDriveFiles.replaceChildren();
 for(const item of plan.files){
  const row=document.createElement('li'),name=document.createElement('strong'),format=document.createElement('small'),provenance=document.createElement('small');
  name.textContent=item.name;format.textContent=item.export_mime_type ?
   `Google dokument → ${item.filename} (${item.export_mime_type})` :
   `Původní soubor → ${item.filename} · ${item.source_mime_type} · ${item.size} B`;
  provenance.textContent=`Revize ${item.source_revision} · vznik zdroje ${item.source_created_at}`;
  row.append(name,format,provenance);googleDriveFiles.append(row);
 }
 googleDrivePlanElement.textContent=lines.join('\\n');googleDrivePreview.hidden=false;
 document.querySelector('#google-drive-confirm-check').checked=false;
 document.querySelector('#google-drive-run').disabled=true;
 setGoogleDriveStep(3,2);
 googleDriveStatus.textContent=plan.blockers.length ?
  'Výběr obsahuje blokující duplicitu; zvolte jiný soubor nebo revizi.' :
  'Náhled je připraven. Drive byl pouze přečten; projekt zatím nebyl změněn.';
}
async function pollGoogleDrive(){
 if(!googleDriveSelection || sourceImportView.hidden)return;
 try{const result=await projectRequest('/v1/google-drive/preview',{selection_id:googleDriveSelection});
  if(result.status==='planned'){googleDrivePlan=result.plan;renderGoogleDrivePlan(result.plan);return;}
  if(result.status==='failed')throw new Error('Přihlášení nebo výběr nebyly dokončeny. Můžete bezpečně začít znovu.');
  googleDriveStatus.textContent='Dokončete přihlášení a výběr u Googlu. Potom se náhled načte automaticky.';
 }catch(error){googleDriveStatus.textContent='Náhled Drive výběru se nepodařilo vytvořit. '+error.message;document.querySelector('#google-drive-select').disabled=false;setGoogleDriveStep(2,1);return;}
 googleDrivePoll=setTimeout(pollGoogleDrive,1000);
}
document.querySelector('#google-drive-privacy').addEventListener('change',()=>{
 googleDriveSelection=null;if(googleDrivePoll)clearTimeout(googleDrivePoll);googleDrivePoll=null;resetGoogleDrivePlan();
 googleDriveStatus.textContent='Změnili jste privacy; spusťte nový Drive výběr.';
});
document.querySelector('#google-drive-recover').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;googleDriveStatus.textContent='Obnovuji potvrzený Drive import z lokálního stagingu…';
 try{const result=await projectRequest('/v1/google-drive/recover',{},180000);
  if(!result.receipt)throw new Error('Žádný potvrzený import nečeká na obnovu.');
  await openRegisteredProject(result.receipt.project_id);
  sidebarArtifactStatus.textContent=`Drive import byl obnoven; ${result.receipt.file_count} souborů bylo publikováno v jednom commitu.`;
 }catch(error){googleDriveStatus.textContent=error.message;event.currentTarget.disabled=false;}
});
document.querySelector('#google-drive-select').addEventListener('click',async event=>{
 if(!activeProject)return;event.currentTarget.disabled=true;resetGoogleDrivePlan();setGoogleDriveStep(2,1);
 googleDriveStatus.textContent='Připravuji bezpečné přihlášení přímo u Googlu…';
 try{const result=await projectRequest('/v1/google-drive/authorize',{project_id:activeProject.id,
   expected_head:activeProject.head,privacy:document.querySelector('#google-drive-privacy').value});
  googleDriveSelection=result.selection_id;
  if(document.body.dataset.runtime==='desktop'){
   googleDriveStatus.textContent='Google se otevírá v systémovém prohlížeči. Přihlaste se, vyberte položky a vraťte se sem.';
   location.assign(result.authorization_url);
  }else{
   googleDriveStatus.textContent='Google se otevírá v nové kartě. Pokud se nic nestalo, povolte pro tento web vyskakovací okna a zkuste to znovu.';
   window.open(result.authorization_url,'_blank','noopener');
  }
  googleDrivePoll=setTimeout(pollGoogleDrive,1000);
 }catch(error){googleDriveStatus.textContent='Přihlášení se nepodařilo zahájit. '+error.message;}
 finally{event.currentTarget.disabled=false;}
});
document.querySelector('#google-drive-confirm-check').addEventListener('change',event=>{
 document.querySelector('#google-drive-run').disabled=!event.currentTarget.checked || !googleDrivePlan || googleDrivePlan.blockers.length>0;
 setGoogleDriveStep(event.currentTarget.checked ? 4 : 3,event.currentTarget.checked ? 3 : 2);
});
document.querySelector('#google-drive-run').addEventListener('click',async event=>{
 if(!googleDrivePlan || !document.querySelector('#google-drive-confirm-check').checked)return;
 if(!googleDriveOperation)googleDriveOperation=crypto.randomUUID();
 event.currentTarget.disabled=true;googleDriveStatus.textContent='Stahuji a atomicky importuji potvrzený výběr…';
 try{const result=await projectRequest('/v1/google-drive/confirm',{
   plan:googleDrivePlan,operation_id:googleDriveOperation},180000);
  const projectId=result.project_id;googleDriveSelection=null;googleDrivePlan=null;googleDriveOperation=null;
  await openRegisteredProject(projectId);sidebarArtifactStatus.textContent=`Z Google Drive bylo importováno ${result.file_count} souborů v jednom commitu.`;
 }catch(error){googleDriveStatus.textContent=error.message;event.currentTarget.disabled=false;}
});
document.querySelector('#open-source-import').addEventListener('click',openSourceImport);
document.querySelector('#source-import-back').addEventListener('click',closeSourceImport);
document.querySelector('#google-drive-open-settings').addEventListener('click',async()=>{
 await openSettings();document.querySelector('#google-drive-config-form input[name="client_id"]').focus();
});
sourceImportForm.elements.file.addEventListener('change',event=>{
 const file=event.currentTarget.files[0];if(file&&!sourceImportForm.elements.title.value)sourceImportForm.elements.title.value=file.name.replace(/\\.[^.]+$/,'');
 sourceImportAttempt=null;
});
sourceImportForm.addEventListener('input',()=>{sourceImportAttempt=null;});
sourceImportForm.addEventListener('submit',async event=>{
 event.preventDefault();const fields=new FormData(sourceImportForm);const file=fields.get('file');
 if(!activeProject || !(file instanceof File) || !file.size){sourceImportStatus.textContent='Vyberte otevřený projekt a soubor.';return;}
 if(file.size>16777216){sourceImportStatus.textContent='Soubor přesahuje limit 16 MiB.';return;}
 const button=sourceImportForm.querySelector('button[type="submit"]');button.disabled=true;sourceImportStatus.textContent='Importuji…';
 try{
  const signature=JSON.stringify([activeProject.id,activeProject.head,file.name,file.size,file.lastModified,
   fields.get('title'),fields.get('description'),fields.get('tags'),fields.get('source_created_at'),fields.get('supersedes'),fields.get('privacy')]);
  if(!sourceImportAttempt || sourceImportAttempt.signature!==signature){
   const raw=await file.arrayBuffer(),digest=await crypto.subtle.digest('SHA-256',raw);
   const source={project_id:activeProject.id,artifact_id:crypto.randomUUID(),base_head:activeProject.head,
    filename:file.name,title:String(fields.get('title')||'').trim(),description:String(fields.get('description')||''),
    tags:String(fields.get('tags')||'').split(/\\r?\\n/).map(value=>value.trim()).filter(Boolean),privacy:String(fields.get('privacy')),
    created_at:new Date().toISOString(),content:bytesBase64(raw),sha256:[...new Uint8Array(digest)].map(byte=>byte.toString(16).padStart(2,'0')).join(''),
    source_url:null,source_author:null,source_created_at:String(fields.get('source_created_at')||'').trim()||null,source_revision:null};
   const supersedes=String(fields.get('supersedes')||'');if(supersedes)source.supersedes=supersedes;
   sourceImportAttempt={signature,request:{operation_id:crypto.randomUUID(),source}};
  }
  const result=await projectRequest('/v1/sources/import',sourceImportAttempt.request,120000);
  const projectId=result.id;sourceImportAttempt=null;sourceImportForm.reset();await openRegisteredProject(projectId);
  sidebarArtifactStatus.textContent='Zdroj byl importován beze změny původních bajtů.';
 }catch(error){sourceImportStatus.textContent=error.message;}finally{button.disabled=false;}
});
const artifactEditorForm=document.querySelector('#artifact-editor-form');
const artifactEditorStatus=document.querySelector('#artifact-editor-status');
let artifactEditorItem=null,artifactEditorAttempt=null,artifactEditorBaseline=null,artifactEditorDirty=false,artifactDeletePreview=null,artifactDeleteOperation=null;
function hideArtifactDeletion(){artifactDeletePreview=null;artifactDeleteOperation=null;document.querySelector('#artifact-delete-preview').hidden=true;document.querySelector('#artifact-delete-confirm').checked=false;document.querySelector('#artifact-delete-run').disabled=true;}
function artifactEditorState(){return JSON.stringify(Object.fromEntries(new FormData(artifactEditorForm).entries()));}
function canLeaveArtifactEditor(){
 if(artifactEditorView.hidden||(!artifactEditorDirty&&!artifactEditorAttempt))return true;
 return window.confirm('Zahodit rozepsané změny dokumentu? Neuložený text zůstává pouze v tomto editoru.');
}
function canLeaveFederationTools(){
 if(federationNetworkRunning){document.querySelector('#federation-network-status').textContent='Síťová operace právě probíhá; stránku nelze opustit.';return false;}
 if(federationDeploymentRunning){document.querySelector('#federation-deployment-status').textContent='Nasazení právě probíhá; stránku nelze opustit.';return false;}
 return true;
}
function canLeaveWorkspaceEditors(){return canLeaveArtifactEditor()&&canLeavePresentationEditor()&&canLeaveFederationTools();}
function fillArtifactEditor(doc,isNew=false){
 const meta=doc.metadata||{};document.querySelector('#artifact-editor-heading').textContent=doc.title||'Nový dokument';
 document.querySelector('#artifact-editor-mode').textContent=isNew?'Nový neuložený Markdown':'Uložený Markdown';
 document.querySelector('#artifact-editor-eyebrow').textContent=isNew?'NOVÝ DOKUMENT':'UPRAVIT DOKUMENT';
 artifactEditorForm.elements.title.value=doc.title||'';artifactEditorForm.elements.filename.value=meta.file||doc.filename||'content.md';
 artifactEditorForm.elements.description.value=meta.description||'';artifactEditorForm.elements.tags.value=(meta.tags||[]).join('\\n');artifactEditorForm.elements.body.value=doc.body||'';
 artifactEditorBaseline=artifactEditorState();artifactEditorDirty=isNew;artifactEditorAttempt=null;
}
async function closeArtifactEditor(){
 if(!canLeaveWorkspaceEditors())return;
 const item=artifactEditorItem;artifactEditorView.hidden=true;hideArtifactDeletion();artifactEditorAttempt=null;artifactEditorDirty=false;artifactEditorItem=null;
 if(activeProject){projectView.hidden=false;if(item&&!item.new)await openPreview(item.id);}
}
async function openArtifactEditor(item,deleteMode=false){
 if(!activeProject||activeProject.readOnly||item.kind!=='document')return;
 if(!artifactEditorView.hidden&&!canLeaveWorkspaceEditors())return;
 await openPreview(item.id);if(selectedArtifact!==item.id)return;
 const project=activeProject;artifactEditorItem=item;artifactEditorAttempt=null;hideArtifactDeletion();
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;historyView.hidden=true;projectView.hidden=true;artifactEditorView.hidden=false;
 selectSidebarTab(document.querySelector('#artifacts-tab'));
 artifactEditorStatus.textContent='Načítám uložený dokument…';
 try{const result=await projectRequest('/v1/artifacts/editor/open',{project_id:project.id,artifact_id:item.id,expected_head:project.head});
  if(activeProject!==project||artifactEditorItem!==item)return;
  fillArtifactEditor(result.document);
  artifactEditorStatus.textContent='Uložená verze je připravena k úpravě.';
  if(deleteMode)await prepareArtifactDeletion();else artifactEditorForm.elements.title.focus();
 }catch(error){artifactEditorStatus.textContent=error.message;}
}
function openNewArtifactEditor({todo=false}={}){
 if(!activeProject||activeProject.readOnly||(!artifactEditorView.hidden&&!canLeaveWorkspaceEditors()))return;
 const id=todo?activeProject.mainTodoId:crypto.randomUUID();
 artifactEditorItem={id,kind:'document',new:true};hideArtifactDeletion();
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;historyView.hidden=true;projectView.hidden=true;artifactEditorView.hidden=false;
 selectSidebarTab(document.querySelector(todo?'#todo-tab':'#artifacts-tab'));
 fillArtifactEditor(todo?{title:'Hlavní seznam úkolů',filename:'content.md',body:'# Hlavní seznam úkolů\\n\\n- [ ] První úkol\\n'}:{title:'',filename:'content.md',body:''},true);
 artifactEditorStatus.textContent='Dokument vznikne až po uložení.';artifactEditorForm.elements.title.focus();
}
function openMainTodoEditor(){
 if(!activeProject||activeProject.readOnly)return;const item=currentArtifacts.find(candidate=>candidate.id===activeProject.mainTodoId);
 if(item)openArtifactEditor(item);else openNewArtifactEditor({todo:true});
}
document.querySelector('#new-document').addEventListener('click',()=>openNewArtifactEditor());
artifactEditorForm.addEventListener('input',()=>{artifactEditorAttempt=null;artifactEditorDirty=artifactEditorState()!==artifactEditorBaseline;});
artifactEditorForm.addEventListener('submit',async event=>{
 event.preventDefault();if(!activeProject||!artifactEditorItem)return;const fields=new FormData(artifactEditorForm),button=artifactEditorForm.querySelector('button[type="submit"]');
 const request={project_id:activeProject.id,artifact_id:artifactEditorItem.id,base_head:activeProject.head,title:String(fields.get('title')).trim(),body:String(fields.get('body')),new:Boolean(artifactEditorItem.new),filename:String(fields.get('filename')).trim(),metadata:{description:String(fields.get('description')),tags:String(fields.get('tags')).split(/\\r?\\n/).map(value=>value.trim()).filter(Boolean)}};
 const signature=JSON.stringify(request);if(!artifactEditorAttempt||artifactEditorAttempt.signature!==signature)artifactEditorAttempt={signature,operation_id:crypto.randomUUID(),document:request};
 button.disabled=true;artifactEditorStatus.textContent='Ukládám dokument…';
 try{const id=artifactEditorItem.id,projectId=activeProject.id;await projectRequest('/v1/artifacts/editor/save',{operation_id:artifactEditorAttempt.operation_id,document:artifactEditorAttempt.document},120000);artifactEditorAttempt=null;artifactEditorDirty=false;artifactEditorItem=null;await openRegisteredProject(projectId);await openPreview(id);previewStatus.textContent='Dokument byl uložen.';}
 catch(error){artifactEditorStatus.textContent=error.message;}finally{button.disabled=false;}
});
async function prepareArtifactDeletion(){
 if(!activeProject||!artifactEditorItem)return;hideArtifactDeletion();artifactEditorStatus.textContent='Připravuji přesný náhled smazání…';
 try{artifactDeletePreview=await projectRequest('/v1/artifacts/delete/preview',{project_id:activeProject.id,artifact_id:artifactEditorItem.id,expected_head:activeProject.head});
  artifactDeleteOperation=crypto.randomUUID();
  document.querySelector('#artifact-delete-details').textContent=`Dokument: ${artifactDeletePreview.title}\nID: ${artifactDeletePreview.artifact_id}\nVýchozí commit: ${artifactDeletePreview.base_head}`;
  document.querySelector('#artifact-delete-preview').hidden=false;artifactEditorStatus.textContent='Smazání čeká na výslovné potvrzení.';
 }catch(error){artifactEditorStatus.textContent=error.message;}
}
document.querySelector('#artifact-delete-confirm').addEventListener('change',event=>{document.querySelector('#artifact-delete-run').disabled=!(event.currentTarget.checked&&artifactDeletePreview);});
document.querySelector('#artifact-delete-cancel').addEventListener('click',hideArtifactDeletion);
document.querySelector('#artifact-delete-run').addEventListener('click',async event=>{
 if(!artifactDeletePreview||!document.querySelector('#artifact-delete-confirm').checked)return;event.currentTarget.disabled=true;artifactEditorStatus.textContent='Odstraňuji dokument…';
 try{const projectId=activeProject.id;await projectRequest('/v1/artifacts/delete/confirm',{project_id:projectId,artifact_id:artifactDeletePreview.artifact_id,base_head:artifactDeletePreview.base_head,preview_sha256:artifactDeletePreview.preview_sha256,operation_id:artifactDeleteOperation},120000);artifactEditorItem=null;artifactDeleteOperation=null;await openRegisteredProject(projectId);previewStatus.textContent='Dokument byl odstraněn. Git historie zůstala zachovaná.';}
 catch(error){artifactEditorStatus.textContent=error.message;event.currentTarget.disabled=false;}
});
document.querySelector('#artifact-editor-close').addEventListener('click',closeArtifactEditor);
window.addEventListener('beforeunload',event=>{if(artifactEditorDirty||artifactEditorAttempt||conflictDraftChanged()||projectConflictOperation){event.preventDefault();event.returnValue='';}});
function localRunRetryHint(error){return [409,422,502].includes(error.status) ?
 ' Vstupy zůstaly zachovány; další potvrzení vytvoří vědomě nový běh.' : '';}
let catalogRequest=0;
let recentProjectOrder=[];
const sidebarProjectRecover=document.querySelector('#sidebar-project-recover');
function setNativeProjectOperationStatus(message,canRetry=false){
 document.querySelector('#sidebar-project-status').textContent=message;
 sidebarProjectRecover.hidden=!canRetry;sidebarProjectRecover.disabled=false;
}
sidebarProjectRecover.addEventListener('click',()=>{
 sidebarProjectRecover.disabled=true;setNativeProjectOperationStatus('Obnovuji přerušenou operaci…',false);
 requestNativeAction('recover-project-operation');
});
let projectRegistrationRemoveTarget=null;
const projectRegistrationRemoveDialog=document.querySelector('#project-registration-remove-dialog');
function repairProjectLocation(item){
 document.querySelector('#sidebar-project-status').textContent='Otevírám systémový výběr nového umístění…';
 requestNativeAction('relocate-project-location',{project_id:item.id});
}
function confirmMissingProjectUnregister(item){
 projectRegistrationRemoveTarget=item;
 document.querySelector('#project-registration-remove-id').textContent=item.id;
 projectRegistrationRemoveDialog.showModal();
}
projectRegistrationRemoveDialog.addEventListener('close',()=>{projectRegistrationRemoveTarget=null;});
document.querySelector('#project-registration-remove-confirm').addEventListener('click',()=>{
 if(!projectRegistrationRemoveTarget)return;
 const projectId=projectRegistrationRemoveTarget.id;
 projectRegistrationRemoveDialog.close();
 document.querySelector('#sidebar-project-status').textContent='Odebírám potvrzenou nedostupnou registraci…';
 requestNativeAction('unregister-missing-project',{project_id:projectId});
});
let projectRepairTarget=null,projectRepairReport=null,projectRepairPlan=null,projectRepairOperation=null;
const projectRepairStatus=document.querySelector('#project-repair-status');
const projectRepairPreview=document.querySelector('#project-repair-preview');
const projectRepairConfirmCheck=document.querySelector('#project-repair-confirm-check');
const projectRepairConfirm=document.querySelector('#project-repair-confirm');
function resetProjectRepairPlan(){
 projectRepairPlan=null;projectRepairOperation=null;document.querySelector('#project-repair-plan').hidden=true;
 projectRepairConfirmCheck.checked=false;projectRepairConfirm.disabled=true;
}
function repairAction(report){
 const findings=Array.isArray(report?.findings)?report.findings:[];
 const actions=[...new Set(findings.map(item=>item.action).filter(action=>['rebuild-index','resume-operation'].includes(action)))];
 return report?.status==='repairable'&&actions.length===1&&findings.length===1?actions[0]:null;
}
function renderProjectRepairReport(report){
 projectRepairReport=report;resetProjectRepairPlan();
 document.querySelector('#project-repair-report').hidden=false;
 const stateLabels={healthy:'V pořádku',repairable:'Bezpečně opravitelné',manual:'Ruční kontrola',retry:'Zopakovat kontrolu'};
 document.querySelector('#project-repair-state').textContent=stateLabels[report.status]||report.status;
 document.querySelector('#project-repair-summary').textContent=report.summary;
 const findings=document.querySelector('#project-repair-findings');findings.replaceChildren();
 for(const finding of report.findings){
  const row=document.createElement('li');row.className='repair-finding';
  const component=document.createElement('strong');component.textContent=finding.component;
  const message=document.createElement('span');message.textContent=finding.message;
  const code=document.createElement('code');code.textContent=finding.code;
  row.append(component,message,code);findings.append(row);
 }
 if(!report.findings.length){const row=document.createElement('li');row.className='repair-finding';row.textContent='V kontrolovaném rozsahu nebyla nalezena chyba.';findings.append(row);}
 const action=repairAction(report);projectRepairPreview.hidden=!action;projectRepairPreview.dataset.action=action||'';
 const location=report.findings.some(item=>item.action==='repair-location');
 document.querySelector('#project-repair-location').hidden=!location;
 projectRepairStatus.textContent=action?'Kontrola nabízí jednu přesně vymezenou opravu. Nejprve zobrazte její náhled.':report.summary;
}
async function runProjectRepairCheck(){
 if(!projectRepairTarget)return;resetProjectRepairPlan();projectRepairPreview.hidden=true;
 document.querySelector('#project-repair-location').hidden=true;projectRepairStatus.textContent='Kontroluji registraci, filesystem, Git, projekt, journal a index pouze pro čtení…';
 try{renderProjectRepairReport(await projectRequest('/v1/projects/repair/check',{project_id:projectRepairTarget.id},120000));}
 catch(error){document.querySelector('#project-repair-report').hidden=true;projectRepairStatus.textContent=error.message;}
}
async function openProjectRepair(item){
 if(!canLeaveWorkspaceEditors())return;clearProject();projectRepairTarget=item;
 document.querySelector('#project-home').hidden=true;projectRepairView.hidden=false;selectSidebarTab(document.querySelector('#projects-tab'));
 document.querySelector('#project-repair-target').textContent=`${item.title} · ${item.id}`;
 document.querySelector('#project-repair-heading').focus();await runProjectRepairCheck();
}
document.querySelector('#project-repair-check').addEventListener('click',runProjectRepairCheck);
document.querySelector('#project-repair-back').addEventListener('click',()=>loadProjects());
document.querySelector('#project-repair-location').addEventListener('click',()=>{if(projectRepairTarget)repairProjectLocation(projectRepairTarget);});
projectRepairPreview.addEventListener('click',async()=>{
 const action=repairAction(projectRepairReport||{});if(!projectRepairTarget||!action)return;
 projectRepairOperation=crypto.randomUUID();projectRepairStatus.textContent='Připravuji přesný náhled opravy…';
 try{projectRepairPlan=await projectRequest('/v1/projects/repair/preview',{
   project_id:projectRepairTarget.id,action,operation_id:projectRepairOperation,
   check_token:projectRepairReport.check_token});
  const intent=projectRepairPlan.intent_operation_id?`Původní operace: ${projectRepairPlan.intent_operation_id}`:'Původní operace: samostatný journalový intent';
  document.querySelector('#project-repair-details').textContent=[
   `Vrstva: ${projectRepairPlan.layer}`,projectRepairPlan.effect,
   `HEAD: ${projectRepairPlan.expected_head||'—'}`,intent,
   '',...projectRepairPlan.preconditions.map(value=>'Podmínka: '+value),
   '',`Recovery: ${projectRepairPlan.recovery}`].join('\\n');
  document.querySelector('#project-repair-plan').hidden=false;projectRepairConfirmCheck.checked=false;projectRepairConfirm.disabled=true;
  projectRepairStatus.textContent='Náhled je připraven. Projekt se zatím nezměnil.';
 }catch(error){resetProjectRepairPlan();projectRepairStatus.textContent=error.message;}
});
projectRepairConfirmCheck.addEventListener('change',()=>{projectRepairConfirm.disabled=!(projectRepairConfirmCheck.checked&&projectRepairPlan);});
document.querySelector('#project-repair-cancel').addEventListener('click',()=>{resetProjectRepairPlan();projectRepairStatus.textContent='Náhled byl zrušen; projekt se nezměnil.';});
projectRepairConfirm.addEventListener('click',async()=>{
 if(!projectRepairPlan||!projectRepairConfirmCheck.checked)return;projectRepairConfirm.disabled=true;
 projectRepairStatus.textContent='Provádím potvrzenou opravu a následnou úplnou kontrolu…';
 try{const result=await projectRequest('/v1/projects/repair/confirm',{plan:projectRepairPlan},120000);
  const operation=result.receipt.operation_id;renderProjectRepairReport(result.report);
  projectRepairStatus.textContent=`Oprava dokončena. Receipt operace: ${operation}`;
 }catch(error){projectRepairStatus.textContent=error.message;projectRepairConfirm.disabled=false;}
});
function recentProjectIds(){return recentProjectOrder;}
function rememberRecentProject(projectId){
 recentProjectOrder=[projectId,...recentProjectOrder.filter(id=>id!==projectId)].slice(0,12);
}
async function openRegisteredProject(projectId){
 if(!canLeaveWorkspaceEditors())return;
 ++catalogRequest;
 clearProject();const request=viewRequest;
 projectStatus.textContent='Otevírám projekt…';
 try{
  const result=await projectRequest('/v1/projects/open',{project_id:projectId});
  if(request!==viewRequest)return;
  rememberRecentProject(projectId);
  activeProject={id:projectId,title:result.title,description:result.description,head:result.commit_id,mainTodoId:result.main_todo_id,readOnly:Boolean(result.read_only),replication:result.replication||null};
  renderTodo(result.main_todo);renderProjectOverview(result.main_todo);renderProjectHistory(result.history);renderSidebarArtifacts(result.artifacts);
  document.querySelector('#project-title').textContent=result.title;
  document.querySelector('#project-description').textContent=result.description;
  document.querySelector('#project-commit').textContent=result.commit_id;
  sourceImportView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;projectView.hidden=false;document.querySelector('#project-home').hidden=true;
  syncSidebarProjectAvailability();
  loadProjectConflictSummary();
  await loadChat();
  syncSidebarProjectAvailability();
  selectSidebarTab(document.querySelector('#artifacts-tab'));selectMainTab(document.querySelector('#project-overview-tab'));
  document.querySelector('#preview-status').textContent=result.read_only ?
   'Read-only replika: podklady lze prohlížet, změny provádějte na primárním uzlu.' : result.artifacts.length ?
   'Vyberte podklad ze seznamu vlevo.' : 'Projekt zatím nemá žádné podklady.';
 }catch(error){if(request===viewRequest)projectStatus.textContent=error.message;}
}
function renderProjectCatalog(items){
 projectCards.replaceChildren();sidebarProjects.replaceChildren();
 for(const item of items){
  const row=document.createElement('li');row.className='sidebar-list-row';
  const compact=document.createElement('button');compact.type='button';compact.className='sidebar-list-main';compact.dataset.id=item.id;
  compact.textContent=item.title;compact.title=item.id;compact.addEventListener('click',()=>openRegisteredProject(item.id));
  const actions=[
   {label:item.available?'Otevřít':'Zkusit otevřít',run:()=>openRegisteredProject(item.id)},
   {label:'Správa odstranění…',run:()=>openProjectDeletion(item)},
   {label:'Kopírovat ID',run:async()=>{try{await navigator.clipboard.writeText(item.id);document.querySelector('#sidebar-project-status').textContent='ID projektu bylo zkopírováno.';}catch(error){document.querySelector('#sidebar-project-status').textContent=`ID projektu: ${item.id}`;}}}
  ];
  if(!item.available)actions.splice(1,0,
   {label:'Zkontrolovat projekt…',run:()=>openProjectRepair(item)});
  if(item.location_missing)actions.splice(1,1,
   {label:'Opravit umístění…',run:()=>repairProjectLocation(item)},
   {label:'Odebrat nedostupnou registraci…',run:()=>confirmMissingProjectUnregister(item)});
  const menu=sidebarItemMenu(item.title,actions,'sidebar-project-menu');
  row.append(compact,menu);sidebarProjects.append(row);
 }
 const byId=new Map(items.map(item=>[item.id,item]));
 const ordered=[...recentProjectIds().map(id=>byId.get(id)).filter(Boolean),...items.filter(item=>!recentProjectIds().includes(item.id))].slice(0,4);
 for(const item of ordered){
  const card=document.createElement('button');card.type='button';card.className=`project-card${item.available?'':' project-card-unavailable'}`;card.dataset.id=item.id;
  const kicker=document.createElement('span');kicker.className='dashboard-kicker';kicker.textContent='Nedávný projekt';
  const name=document.createElement('span');name.className='project-name';name.textContent=item.title;
  const meta=document.createElement('span');meta.className='project-meta';meta.textContent=item.available?'Otevřít':'Projekt není dostupný';
  card.append(kicker,name,meta);card.addEventListener('click',()=>openRegisteredProject(item.id));projectCards.append(card);
 }
 document.querySelector('#sidebar-project-status').textContent=items.length ? `Počet projektů: ${items.length}` : 'Zatím bez projektů.';
}
async function loadDashboardTasks(items,request){
 const list=document.querySelector('#dashboard-task-list'),status=document.querySelector('#dashboard-task-status');list.replaceChildren();status.textContent='Načítám úkoly…';
 const available=items.filter(item=>item.available),results=await Promise.allSettled(available.map(item=>projectRequest('/v1/projects/open',{project_id:item.id})));
 if(request!==catalogRequest)return;
 let unavailable=0,openCount=0;
 for(let index=0;index<results.length;index++){
  const result=results[index],project=available[index];
  if(result.status!=='fulfilled'){unavailable++;continue;}
  const todo=result.value.main_todo;
  if(!todo||todo.status!=='ready'){if(todo)unavailable++;continue;}
  for(const item of todo.items.filter(item=>!item.checked)){
   openCount++;const row=document.createElement('li');row.className='dashboard-task-row';const button=document.createElement('button');button.type='button';
   const title=document.createElement('span');title.textContent=item.title;const source=document.createElement('small');source.textContent=project.title;button.append(title,source);
   button.addEventListener('click',async()=>{await openRegisteredProject(project.id);if(activeProject?.id===project.id)selectSidebarTab(document.querySelector('#todo-tab'));});row.append(button);list.append(row);
  }
 }
 status.textContent=openCount?`${openCount} nehotových úkolů${unavailable?` · ${unavailable} projektů nelze načíst`:''}`:(unavailable?'Úkoly nejsou dostupné ve všech projektech.':'Žádné nehotové úkoly.');
}
const projectDeletePanel=document.querySelector('#project-delete-panel');
const projectDeleteMode=document.querySelector('#project-delete-mode');
const projectDeleteCheck=document.querySelector('#project-delete-check');
const projectDeleteConfirm=document.querySelector('#project-delete-confirm');
let projectDeleteTarget=null,projectDeletePlan=null,projectDeleteKind=null;
function deletionDetails(plan){
 const lines=[plan.effect,`Projekt: ${plan.project_id}`,`HEAD: ${plan.head||'—'}`];
 if(plan.root)lines.push(`Repozitář: ${plan.root}`);
 if(plan.state_dir)lines.push(`Projektový stav: ${plan.state_dir}`);
 if(plan.trash_path)lines.push(`Koš: ${plan.trash_path}`);
 if(plan.dirty_worktree)lines.push('Pracovní strom obsahuje necommitnuté nebo nesledované soubory.');
 if(plan.transfers?.length)lines.push(`Nedokončené přenosy: ${plan.transfers.length}`);
 if(plan.administration)lines.push(`Účty projektu: ${plan.administration.memberships||0}; federační mapování: ${plan.administration.mappings||0}`);
 lines.push(`Node-local záznamy: ${plan.node_records?.records||0} (zůstanou zachovány)`,'Vzdálené a dříve sdílené kopie zůstanou zachovány.');
 return lines.join('\\n');
}
function showDeletionPlan(plan,kind){
 projectDeletePlan=plan;projectDeleteKind=kind;projectDeleteCheck.checked=false;
 document.querySelector('#project-delete-details').textContent=deletionDetails(plan);
 const blockers=plan.blockers||[];document.querySelector('#project-delete-blockers').textContent=blockers.join('\\n');
 projectDeleteCheck.disabled=Boolean(blockers.length);projectDeleteConfirm.disabled=true;
 projectDeleteConfirm.textContent=kind==='purge'?'Definitivně vymazat':kind==='restore'?'Obnovit projekt':'Provést potvrzenou akci';
 document.querySelector('#project-delete-status').textContent=blockers.length?'Akce je zablokovaná. Vyřešte uvedené vazby nebo operace.':'Náhled je připraven k potvrzení.';
 projectDeletePanel.hidden=false;
}
async function refreshProjectDeletion(){
 if(!projectDeleteTarget)return;projectDeletePlan=null;projectDeleteConfirm.disabled=true;
 document.querySelector('#project-delete-status').textContent='Načítám přesný náhled…';
 try{showDeletionPlan(await projectRequest('/v1/projects/delete/preview',{project_id:projectDeleteTarget.id,mode:projectDeleteMode.value}),'delete');}
 catch(error){document.querySelector('#project-delete-status').textContent=error.message;}
}
function openProjectDeletion(item){
 if(!openProjectTrashView())return;
 projectDeleteTarget=item;projectDeleteMode.value='trash';document.querySelector('#project-delete-mode-row').hidden=false;
 document.querySelector('#project-delete-title').textContent=`Akce projektu: ${item.title}`;refreshProjectDeletion();
}
projectDeleteMode.addEventListener('change',refreshProjectDeletion);
projectDeleteCheck.addEventListener('change',()=>{projectDeleteConfirm.disabled=!(projectDeleteCheck.checked&&projectDeletePlan&&!(projectDeletePlan.blockers||[]).length);});
document.querySelector('#project-delete-cancel').addEventListener('click',()=>{projectDeletePanel.hidden=true;projectDeletePlan=null;projectDeleteTarget=null;});
projectDeleteConfirm.addEventListener('click',async()=>{
 if(!projectDeletePlan||!projectDeleteCheck.checked)return;projectDeleteConfirm.disabled=true;
 const path=projectDeleteKind==='restore'?'/v1/projects/delete/restore/confirm':projectDeleteKind==='purge'?'/v1/projects/delete/purge/confirm':'/v1/projects/delete/confirm';
 try{await projectRequest(path,{preview:projectDeletePlan,operation_id:crypto.randomUUID()},120000);projectDeletePanel.hidden=true;projectDeletePlan=null;projectDeleteTarget=null;await loadProjects();}
 catch(error){document.querySelector('#project-delete-status').textContent=error.message;projectDeleteConfirm.disabled=false;}
});
async function prepareTrashAction(item,kind){
 document.querySelector('#project-delete-mode-row').hidden=true;document.querySelector('#project-delete-title').textContent=kind==='restore'?'Obnovit projekt z koše':'Definitivně vymazat projekt';
 const path=kind==='restore'?'/v1/projects/delete/restore/preview':'/v1/projects/delete/purge/preview';
 try{showDeletionPlan(await projectRequest(path,{operation_id:item.operation_id}),kind);}
 catch(error){document.querySelector('#project-trash-status').textContent=error.message;}
}
async function loadProjectTrash(){
 const list=document.querySelector('#project-trash-list');list.replaceChildren();
 try{const result=await projectRequest('/v1/projects/delete/trash',{});for(const item of result.projects){
   const row=document.createElement('div');row.className='trash-row';const label=document.createElement('code');label.textContent=`${item.project_id} · ${item.trash_path}`;
   const restore=document.createElement('button');restore.type='button';restore.textContent='Připravit obnovu';restore.addEventListener('click',()=>prepareTrashAction(item,'restore'));
   const purge=document.createElement('button');purge.type='button';purge.className='danger';purge.textContent='Připravit definitivní výmaz';purge.addEventListener('click',()=>prepareTrashAction(item,'purge'));
   row.append(label,restore,purge);list.append(row);
  }document.querySelector('#project-trash-status').textContent=result.projects.length?`Položek v koši: ${result.projects.length}`:'Koš je prázdný.';
   document.querySelector('#dashboard-trash-summary').textContent=result.projects.length?`${result.projects.length} položek`:'Koš je prázdný';
 }catch(error){document.querySelector('#project-trash-status').textContent=error.message;document.querySelector('#dashboard-trash-summary').textContent='Koš není dostupný';}
}
function openProjectTrashView(){
 if(!canLeaveWorkspaceEditors())return false;
 clearProject();document.querySelector('#project-home').hidden=true;projectTrashView.hidden=false;selectSidebarTab(document.querySelector('#projects-tab'));loadProjectTrash();
 return true;
}
async function loadProjects(selectedId=null){
 if(!canLeaveWorkspaceEditors())return;
 const request=++catalogRequest;
 clearProject();projectCards.replaceChildren();sidebarProjects.replaceChildren();
 projectStatus.textContent='Načítám projekty…';document.querySelector('#sidebar-project-status').textContent='Načítám projekty…';
 try{
  const result=await projectRequest('/v1/projects',{details:true});
  if(request!==catalogRequest)return;
  renderProjectCatalog(result.projects);
  await Promise.all([loadProjectTrash(),loadDashboardTasks(result.projects,request),loadChat()]);
  projectStatus.textContent=result.projects.length ? 'Přehled je připravený.' : 'Zatím nemáte žádný projekt.';
  if(selectedId && result.projects.some(p=>p.id===selectedId))await openRegisteredProject(selectedId);
 }catch(error){if(request===catalogRequest){projectStatus.textContent=error.message;document.querySelector('#sidebar-project-status').textContent='Seznam není dostupný.';}}
}
document.querySelector('#projects-tab').addEventListener('click',()=>loadProjects());
document.querySelector('#chats-tab').addEventListener('click',()=>{if(!activeProject)loadChat();});
document.querySelector('#sidebar-register-project').addEventListener('click',()=>{
 document.querySelector('#sidebar-project-import-options').hidden=true;
 document.querySelector('#sidebar-import-project').setAttribute('aria-expanded','false');
 document.querySelector('#sidebar-project-status').textContent='Otevírám systémový výběr projektu…';
 requestNativeAction('register-project-location');
});
document.querySelector('#sidebar-project-trash').addEventListener('click',openProjectTrashView);
document.querySelector('#dashboard-trash').addEventListener('click',openProjectTrashView);
document.querySelector('#project-trash-back').addEventListener('click',()=>loadProjects());
document.querySelector('#dashboard-date').textContent=new Intl.DateTimeFormat('cs-CZ',{weekday:'long',day:'numeric',month:'long'}).format(new Date());
document.querySelector('#sidebar-create-project').addEventListener('click',async()=>{
 if(activeProject)await loadProjects();
 document.querySelector('#project-home').hidden=true;projectView.hidden=true;settingsView.hidden=true;projectRepairView.hidden=true;
 sourceImportView.hidden=true;notebookImportView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;
 projectCreateView.hidden=false;selectSidebarTab(document.querySelector('#projects-tab'));
 resetProjectCreationPreview();document.querySelector('#project-create-heading').focus();
});
document.querySelector('#project-create-back').addEventListener('click',()=>loadProjects());
document.querySelector('#sidebar-import-project').addEventListener('click',event=>{
 const options=document.querySelector('#sidebar-project-import-options'),open=options.hidden;options.hidden=!open;event.currentTarget.setAttribute('aria-expanded',String(open));
});

const projectCreateForm=document.querySelector('#create-project');
const createStatus=document.querySelector('#create-project-status');
const projectCreatePreview=document.querySelector('#project-create-preview');
let projectCreationAttempt=null,projectCreationPlan=null,projectCreationLocation=null;
function resetProjectCreationPreview(message=''){
 projectCreationPlan=null;projectCreatePreview.hidden=true;
 document.querySelector('#project-create-confirm-check').checked=false;
 document.querySelector('#project-create-confirm').disabled=true;
 if(message)createStatus.textContent=message;
}
function creationAttempt(title){
 if(!projectCreationAttempt||projectCreationAttempt.title!==title){
  projectCreationAttempt={title,operation_id:crypto.randomUUID()};projectCreationLocation=null;
  document.querySelector('#project-location-label').textContent='Použije se výchozí místní umístění.';
  document.querySelector('#clear-project-location').hidden=true;
  document.querySelector('#remember-project-parent-row').hidden=true;
 }
 return projectCreationAttempt;
}
window.projectCreationPickerRequest=()=>{
 const title=document.querySelector('#new-project-title').value.trim();
 if(!title){createStatus.textContent='Nejprve zadejte název projektu.';return null;}
 const attempt=creationAttempt(title);resetProjectCreationPreview('Vyberte existující prázdnou cílovou složku.');
 return {title:attempt.title,operation_id:attempt.operation_id};
};
window.setProjectCreationLocation=result=>{
 if(!result||!projectCreationAttempt||result.operation_id!==projectCreationAttempt.operation_id)return;
 projectCreationLocation=result;document.querySelector('#project-location-label').textContent=`Vybrané umístění: ${result.location_label}`;
 document.querySelector('#clear-project-location').hidden=false;
 document.querySelector('#remember-project-parent-row').hidden=false;
 resetProjectCreationPreview('Umístění bylo vybráno. Připravte přesný náhled.');
};
document.querySelector('#choose-project-location').addEventListener('click',()=>{
 if(window.projectCreationPickerRequest())requestNativeAction('choose-project-location');
});
document.querySelector('#clear-project-location').addEventListener('click',()=>{
 projectCreationLocation=null;document.querySelector('#project-location-label').textContent='Použije se výchozí místní umístění.';
 document.querySelector('#clear-project-location').hidden=true;document.querySelector('#remember-project-parent-row').hidden=true;
 document.querySelector('#remember-project-parent').checked=false;resetProjectCreationPreview('Použije se výchozí umístění uzlu.');
});
document.querySelector('#new-project-title').addEventListener('input',()=>{
 projectCreationAttempt=null;projectCreationLocation=null;resetProjectCreationPreview();
 document.querySelector('#project-location-label').textContent='Použije se výchozí místní umístění.';
 document.querySelector('#clear-project-location').hidden=true;document.querySelector('#remember-project-parent-row').hidden=true;
});
projectCreateForm.addEventListener('submit',async event=>{
 event.preventDefault();const title=document.querySelector('#new-project-title').value.trim();
 if(!title){createStatus.textContent='Zadejte název projektu.';return;}
 const attempt=creationAttempt(title),button=document.querySelector('#create-project-btn');button.disabled=true;
 createStatus.textContent='Připravuji přesný náhled…';
 try{projectCreationPlan=await projectRequest('/v1/projects/create/preview',{
   title,operation_id:attempt.operation_id,
   location_capability:projectCreationLocation?.location_capability||null,
   remember_parent:Boolean(projectCreationLocation&&document.querySelector('#remember-project-parent').checked)});
  document.querySelector('#project-create-details').textContent=`Název: ${projectCreationPlan.title}\nCíl: ${projectCreationPlan.target_label}\nID operace: ${projectCreationPlan.operation_id}`;
  document.querySelector('#project-create-confirm-check').checked=false;document.querySelector('#project-create-confirm').disabled=true;
  projectCreatePreview.hidden=false;createStatus.textContent='Náhled je připraven k potvrzení.';
 }catch(error){resetProjectCreationPreview(error.message);}finally{button.disabled=false;}
});
document.querySelector('#project-create-confirm-check').addEventListener('change',event=>{
 document.querySelector('#project-create-confirm').disabled=!(event.currentTarget.checked&&projectCreationPlan);
});
document.querySelector('#project-create-cancel').addEventListener('click',()=>resetProjectCreationPreview('Náhled byl zrušen.'));
document.querySelector('#project-create-confirm').addEventListener('click',async event=>{
 if(!projectCreationPlan||!document.querySelector('#project-create-confirm-check').checked)return;
 event.currentTarget.disabled=true;createStatus.textContent='Vytvářím projekt…';
 try{const result=await projectRequest('/v1/projects/create/confirm',{plan:projectCreationPlan},120000);
  const title=result.title;projectCreationAttempt=null;projectCreationPlan=null;projectCreationLocation=null;projectCreateForm.reset();projectCreatePreview.hidden=true;
  createStatus.textContent=`Projekt „${title}“ byl vytvořen.`;await loadProjects(result.id);
 }catch(error){createStatus.textContent=error.message;event.currentTarget.disabled=false;}
});

const notebookStatus=document.querySelector('#notebooklm-status');
const notebookSelection=document.querySelector('#notebooklm-selection');
let notebookBundle=null,notebookPlan=null,notebookAttempt=null;
let notebookArchiveCapability=null,notebookTargetCapability=null;
function requestNativeAction(action,payload={}){
 const fields=new URLSearchParams({...payload,nonce:crypto.randomUUID()});location.hash=`${action}?${fields}`;
}
const federationView=document.querySelector('#federation-view');
const federationNetworkView=document.querySelector('#federation-network-view');
const federationDeploymentView=document.querySelector('#federation-deployment-view');
const federationNetworkForm=document.querySelector('#federation-network-form');
const federationNetworkStatus=document.querySelector('#federation-network-status');
const federationNetworkLog=document.querySelector('#federation-network-log');
const federationNetworkConfirmation=document.querySelector('#federation-network-confirmation');
let federationNetworkConfiguration=null;
function resetFederationNetworkConfirmation(message=''){
 federationNetworkConfirmation.hidden=true;document.querySelector('#federation-network-confirm').checked=false;
 document.querySelector('#federation-network-bilateral').disabled=true;
 if(message)federationNetworkStatus.textContent=message;
}
function federationNetworkConfigureRequest(){
 if(!federationNetworkConfiguration)return null;
 return {token:federationNetworkConfiguration.token,action:'configure',config:{
  enabled:federationNetworkForm.elements.enabled.checked,
  bind:federationNetworkForm.elements.bind.value.trim(),
  port:Number(federationNetworkForm.elements.port.value),
  lan:federationNetworkForm.elements.lan.value.trim(),cert:federationNetworkForm.elements.cert.value.trim(),
  key:federationNetworkForm.elements.key.value.trim(),ca:federationNetworkForm.elements.ca.value.trim()},
  generate:federationNetworkForm.elements.generate.checked};
}
function federationNetworkDiagnosticRequest(action){
 if(!federationNetworkConfiguration)return null;
 const request={token:federationNetworkConfiguration.token,action,
  target:Number(federationNetworkForm.elements.target.value),ca:federationNetworkForm.elements.peer_ca.value.trim()};
 if(action==='check-bilateral')request.confirmed=document.querySelector('#federation-network-confirm').checked;
 return request;
}
function federationNetworkRequest(){
 const action=federationNetworkForm.dataset.action;
 return action==='configure'?federationNetworkConfigureRequest():federationNetworkDiagnosticRequest(action);
}
function setFederationNetworkLocked(locked){
 for(const field of federationNetworkForm.querySelectorAll('input,select,button'))field.disabled=locked;
}
function showFederationNetworkConfiguration(configuration){
 if(!configuration||typeof configuration.token!=='string'||!configuration.config||!Array.isArray(configuration.addresses)||!Array.isArray(configuration.targets)){
  setFederationNetworkError('Nativní vrstva neposkytla platné síťové nastavení.');return;
 }
 federationNetworkConfiguration=configuration;federationNetworkRunning=false;setFederationNetworkLocked(false);
 const config=configuration.config;
 for(const key of ['bind','port','lan','cert','key','ca'])federationNetworkForm.elements[key].value=config[key]??'';
 federationNetworkForm.elements.enabled.checked=Boolean(config.enabled);
 federationNetworkForm.elements.generate.checked=Boolean(configuration.generate);
 const addresses=document.querySelector('#federation-network-addresses');addresses.replaceChildren();
 for(const value of configuration.addresses)addresses.append(new Option(value,value));
 const targets=federationNetworkForm.elements.target;targets.replaceChildren();
 for(const item of configuration.targets)targets.append(new Option(item.label,item.index));
 federationNetworkForm.elements.peer_ca.value=configuration.targets[0]?.ca||'';
 document.querySelector('#federation-network-check').disabled=!configuration.targets.length;
 document.querySelector('#federation-network-bilateral-preview').disabled=!configuration.targets.length||!configuration.endpoint;
 resetFederationNetworkConfirmation(configuration.endpoint?`Aktivní backend: ${configuration.endpoint}`:'Aktivní backend: vypnutý');
}
function setFederationNetworkProgress(message){
 federationNetworkRunning=true;setFederationNetworkLocked(true);federationNetworkStatus.textContent=message;
}
function setFederationNetworkError(message){
 federationNetworkRunning=false;setFederationNetworkLocked(false);federationNetworkStatus.textContent=message||'Síťovou operaci nelze provést.';
}
function finishFederationNetwork(success,message){
 federationNetworkRunning=false;setFederationNetworkLocked(false);
 federationNetworkStatus.textContent=success?'Síťová operace byla dokončena.':'Síťová operace nebyla dokončena.';
 federationNetworkLog.textContent=message;
 if(federationNetworkConfiguration){
  const available=federationNetworkConfiguration.targets.length>0;
  document.querySelector('#federation-network-check').disabled=!available;
  document.querySelector('#federation-network-bilateral-preview').disabled=!available||!federationNetworkConfiguration.endpoint;
 }
}
function runFederationNetwork(request,message){
 if(!request)return;federationNetworkForm.dataset.action=request.action;
 federationNetworkRunning=true;setFederationNetworkLocked(true);federationNetworkStatus.textContent=message;
 requestNativeAction('federation-network-run');
}
function openFederationNetwork(){
 if(!canLeaveWorkspaceEditors())return;
 document.querySelector('#project-home').hidden=true;projectCreateView.hidden=true;projectTrashView.hidden=true;projectRepairView.hidden=true;
 projectView.hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;notebookImportView.hidden=true;
 historyView.hidden=true;artifactEditorView.hidden=true;federationView.hidden=true;federationDeploymentView.hidden=true;federationNetworkView.hidden=false;
 selectSidebarTab(document.querySelector('#federation-tab'));federationNetworkConfiguration=null;
 federationNetworkLog.textContent='';resetFederationNetworkConfirmation('Načítám lokální síťové nastavení…');
 requestNativeAction('federation-network-open');
}
document.querySelector('#open-federation-network').addEventListener('click',openFederationNetwork);
document.querySelector('#open-federation-network-menu').addEventListener('click',event=>{event.currentTarget.closest('details').open=false;openFederationNetwork();});
federationNetworkForm.addEventListener('submit',event=>{
 event.preventDefault();runFederationNetwork(federationNetworkConfigureRequest(),'Předávám nastavení nativní vrstvě…');
});
federationNetworkForm.elements.target.addEventListener('change',event=>{
 const target=federationNetworkConfiguration?.targets.find(item=>item.index===Number(event.currentTarget.value));
 federationNetworkForm.elements.peer_ca.value=target?.ca||'';resetFederationNetworkConfirmation('Výběr uzlu se změnil.');
});
federationNetworkForm.elements.peer_ca.addEventListener('input',()=>resetFederationNetworkConfirmation('Veřejná CA protějšího uzlu se změnila.'));
document.querySelector('#federation-network-check').addEventListener('click',()=>{
 const request=federationNetworkDiagnosticRequest('check');
 if(!request?.ca){federationNetworkStatus.textContent='Vyberte LXC uzel a jeho důvěryhodnou veřejnou CA.';return;}
 runFederationNetwork(request,'Předávám diagnostiku nativní vrstvě…');
});
document.querySelector('#federation-network-bilateral-preview').addEventListener('click',()=>{
 const request=federationNetworkDiagnosticRequest('check-bilateral');
 if(!request?.ca){federationNetworkStatus.textContent='Vyberte LXC uzel a jeho důvěryhodnou veřejnou CA.';return;}
 const target=federationNetworkConfiguration.targets.find(item=>item.index===request.target);
 document.querySelector('#federation-network-details').textContent=`Router: ${target.host}\nKontejner: ${target.container}\nDesktop: ${federationNetworkConfiguration.endpoint}\nVeřejná CA LXC: ${request.ca}`;
 federationNetworkConfirmation.hidden=false;federationNetworkStatus.textContent='Zkontrolujte přesný rozsah a potvrďte obousměrný test.';
});
document.querySelector('#federation-network-confirm').addEventListener('change',event=>{document.querySelector('#federation-network-bilateral').disabled=!event.currentTarget.checked;});
document.querySelector('#federation-network-cancel').addEventListener('click',()=>resetFederationNetworkConfirmation('Potvrzení bylo zrušeno.'));
document.querySelector('#federation-network-bilateral').addEventListener('click',()=>{
 const request=federationNetworkDiagnosticRequest('check-bilateral');if(!request?.confirmed)return;
 runFederationNetwork(request,'Předávám potvrzený obousměrný test nativní vrstvě…');
});
const federationDeploymentForm=document.querySelector('#federation-deployment-form');
const federationDeploymentStatus=document.querySelector('#federation-deployment-status');
const federationDeploymentLog=document.querySelector('#federation-deployment-log');
const federationDeploymentConfirmation=document.querySelector('#federation-deployment-confirmation');
let federationDeploymentConfiguration=null;
function resetFederationDeploymentConfirmation(message=''){
 federationDeploymentConfirmation.hidden=true;document.querySelector('#federation-deployment-confirm').checked=false;
 document.querySelector('#federation-deployment-start').disabled=true;
 if(message)federationDeploymentStatus.textContent=message;
}
function federationDeploymentRequest(){
 if(!federationDeploymentConfiguration)return null;
 return {token:federationDeploymentConfiguration.token,
  target:Number(federationDeploymentForm.elements.target.value),
  host:federationDeploymentForm.elements.host.value.trim(),
  container:federationDeploymentForm.elements.container.value.trim(),
  lan:federationDeploymentForm.elements.lan.value.trim(),
  endpoint:federationDeploymentForm.elements.endpoint.value.trim(),
  mode:federationDeploymentForm.elements.mode.value,
  confirmed:document.querySelector('#federation-deployment-confirm').checked};
}
function setFederationDeploymentLocked(locked){
 for(const field of federationDeploymentForm.querySelectorAll('input,select,button'))field.disabled=locked;
}
function showFederationDeploymentConfiguration(configuration){
 if(!configuration||typeof configuration.token!=='string'||!Array.isArray(configuration.targets)||!Array.isArray(configuration.modes)||!Array.isArray(configuration.endpoints)){
  setFederationDeploymentError('Nativní vrstva neposkytla platné nastavení nasazení.');return;
 }
 federationDeploymentConfiguration=configuration;federationDeploymentRunning=false;setFederationDeploymentLocked(false);
 const targets=federationDeploymentForm.elements.target;targets.replaceChildren(new Option('Nový / ručně zadaný uzel',-1));
 for(const item of configuration.targets)targets.append(new Option(item.label,item.index));
 const modes=federationDeploymentForm.elements.mode;modes.replaceChildren();
 for(const item of configuration.modes)modes.append(new Option(item.label,item.value));
 const endpoints=document.querySelector('#federation-deployment-endpoints');endpoints.replaceChildren();
 for(const value of configuration.endpoints)endpoints.append(new Option(value,value));
 if(configuration.endpoint)federationDeploymentForm.elements.endpoint.value=configuration.endpoint;
 document.querySelector('#federation-deployment-preview').disabled=false;
 resetFederationDeploymentConfirmation('Vyberte nebo zadejte cílový uzel a připravte souhrn.');
}
function setFederationDeploymentProgress(message){
 federationDeploymentRunning=true;setFederationDeploymentLocked(true);
 federationDeploymentStatus.textContent='Vzdálená operace probíhá…';
 federationDeploymentLog.textContent+=(federationDeploymentLog.textContent?'\\n':'')+message;
}
function setFederationDeploymentError(message){
 federationDeploymentRunning=false;setFederationDeploymentLocked(false);
 resetFederationDeploymentConfirmation(message||'Nasazení nelze připravit nebo spustit.');
 if(federationDeploymentConfiguration)document.querySelector('#federation-deployment-preview').disabled=false;
}
function finishFederationDeployment(success,message){
 federationDeploymentRunning=false;setFederationDeploymentLocked(false);
 if(message)federationDeploymentLog.textContent+=(federationDeploymentLog.textContent?'\\n':'')+message;
 resetFederationDeploymentConfirmation(success?'Vzdálená operace byla dokončena. Připravte nový souhrn pro případné opakování.':'Vzdálená operace nebyla dokončena. Zkontrolujte průběh a připravte nový souhrn.');
 if(federationDeploymentConfiguration)document.querySelector('#federation-deployment-preview').disabled=false;
}
function openFederationDeployment(){
 if(!canLeaveWorkspaceEditors())return;
 document.querySelector('#project-home').hidden=true;projectCreateView.hidden=true;projectTrashView.hidden=true;projectRepairView.hidden=true;
 projectView.hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;notebookImportView.hidden=true;
 historyView.hidden=true;artifactEditorView.hidden=true;federationView.hidden=true;federationNetworkView.hidden=true;federationDeploymentView.hidden=false;
 selectSidebarTab(document.querySelector('#federation-tab'));federationDeploymentConfiguration=null;
 federationDeploymentLog.textContent='';resetFederationDeploymentConfirmation('Načítám cílové uzly a lokální endpoint…');
 requestNativeAction('federation-deployment-open');
}
document.querySelector('#open-federation-deployment').addEventListener('click',openFederationDeployment);
document.querySelector('#open-federation-deployment-menu').addEventListener('click',event=>{event.currentTarget.closest('details').open=false;openFederationDeployment();});
federationDeploymentForm.elements.target.addEventListener('change',event=>{
 const target=federationDeploymentConfiguration?.targets.find(item=>item.index===Number(event.currentTarget.value));
 if(target){
  federationDeploymentForm.elements.host.value=target.host;federationDeploymentForm.elements.container.value=target.container;
  federationDeploymentForm.elements.lan.value=target.lan;
  federationDeploymentForm.elements.endpoint.value=federationDeploymentConfiguration.endpoint||target.desktop_endpoint;
  federationDeploymentForm.elements.mode.value='update';
  federationDeploymentLog.textContent+=(federationDeploymentLog.textContent?'\\n':'')+`Zapamatovaná adresa kontejneru: ${target.endpoint}`;
 }
 resetFederationDeploymentConfirmation('Výběr cílového uzlu se změnil.');
});
for(const field of federationDeploymentForm.querySelectorAll('input[name],select[name="mode"]'))field.addEventListener('input',()=>resetFederationDeploymentConfirmation('Nastavení se změnilo; připravte nový souhrn.'));
document.querySelector('#federation-deployment-preview').addEventListener('click',()=>{
 const request=federationDeploymentRequest();
 if(!request||!request.host||!request.container||!request.lan){federationDeploymentStatus.textContent='Vyplňte SSH cíl, kontejner a privátní LAN.';return;}
 if(request.mode==='install'&&!request.endpoint){federationDeploymentStatus.textContent='První instalace vyžaduje skutečný HTTPS endpoint desktopového backendu.';return;}
 if(request.mode==='address'&&request.target<0){federationDeploymentStatus.textContent='Aktualizace adresy vyžaduje zapamatovaný cílový uzel.';return;}
 const mode=federationDeploymentConfiguration.modes.find(item=>item.value===request.mode);
 document.querySelector('#federation-deployment-details').textContent=`SSH cíl: ${request.host}\\nKontejner: ${request.container}\\nLAN: ${request.lan}\\nDesktopový endpoint: ${request.endpoint||'nepoužije se'}\\nOperace: ${mode?.label||request.mode}`;
 federationDeploymentConfirmation.hidden=false;federationDeploymentStatus.textContent='Zkontrolujte přesný rozsah vzdálených změn a potvrďte operaci.';
});
document.querySelector('#federation-deployment-confirm').addEventListener('change',event=>{document.querySelector('#federation-deployment-start').disabled=!event.currentTarget.checked;});
document.querySelector('#federation-deployment-cancel').addEventListener('click',()=>resetFederationDeploymentConfirmation('Souhrn byl zrušen.'));
federationDeploymentForm.addEventListener('submit',event=>{
 event.preventDefault();const request=federationDeploymentRequest();if(!request?.confirmed)return;
 federationDeploymentRunning=true;setFederationDeploymentLocked(true);
 federationDeploymentStatus.textContent='Předávám potvrzené nasazení nativní vrstvě…';requestNativeAction('federation-deployment-start');
});
function openNotebookLMImport(){
 if(!canLeaveWorkspaceEditors())return;
 clearProject();
 document.querySelector('#project-home').hidden=true;projectView.hidden=true;settingsView.hidden=true;
 sourceImportView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;notebookImportView.hidden=false;
 selectSidebarTab(document.querySelector('#projects-tab'));
 notebookStatus.textContent=notebookArchiveCapability?'Pokračujte načtením nebo výběrem projektu.':'Vyberte export Google Takeout.';
}
function closeNotebookLMImport(){notebookImportView.hidden=true;document.querySelector('#project-home').hidden=false;selectSidebarTab(document.querySelector('#projects-tab'));}
document.querySelector('#open-notebooklm-import').addEventListener('click',openNotebookLMImport);
document.querySelector('#notebooklm-import-back').addEventListener('click',closeNotebookLMImport);
function notebookArchiveRequest(){
 return {archive_path:document.body.dataset.runtime==='server' ? document.querySelector('#notebooklm-archive').value.trim() : null,
  archive_capability:notebookArchiveCapability?.archive_capability||null};
}
function resetNotebookPlan(message=''){
 notebookPlan=null;document.querySelector('#notebooklm-preview').hidden=true;
 document.querySelector('#notebooklm-confirm-row').hidden=true;document.querySelector('#notebooklm-confirm').checked=false;
 document.querySelector('#notebooklm-run').disabled=true;
 if(message)notebookStatus.textContent=message;
}
function resetNotebookArchive(message=''){
 notebookBundle=null;notebookAttempt=null;notebookTargetCapability=null;
 notebookSelection.replaceChildren();notebookSelection.disabled=true;
 document.querySelector('#notebooklm-plan').disabled=true;
 document.querySelector('#notebooklm-target-label').textContent='Použije se výchozí umístění projektů.';
 document.querySelector('#notebooklm-destination').textContent='Přesná cesta se zobrazí po přípravě plánu.';
 resetNotebookPlan(message);
}
window.setNotebookLMArchive=result=>{
 if(!result?.archive_capability)return;
 notebookArchiveCapability=result;
 document.querySelector('#notebooklm-archive-label').textContent=`Vybraný archiv: ${result.archive_label}`;
 resetNotebookArchive('Archiv byl vybrán. Načtěte bezpečný přehled.');
};
window.notebookLMTargetPickerRequest=()=>{
 if(!notebookBundle){notebookStatus.textContent='Nejprve načtěte bezpečný přehled archivu.';return null;}
 if(!notebookAttempt)notebookAttempt={operation_id:crypto.randomUUID()};
 return {operation_id:notebookAttempt.operation_id};
};
window.setNotebookLMTarget=result=>{
 if(!result||!notebookAttempt||result.operation_id!==notebookAttempt.operation_id)return;
 notebookTargetCapability=result;
 document.querySelector('#notebooklm-target-label').textContent=`Vybrané umístění: ${result.target_label}`;
 document.querySelector('#notebooklm-destination').textContent=result.target_label;
 resetNotebookPlan('Cílové umístění bylo vybráno. Připravte přesný plán.');
};
window.setNotebookLMNativeError=message=>{notebookStatus.textContent=message||'Nativní výběr se nezdařil.';};
document.querySelector('#notebooklm-choose-archive').addEventListener('click',()=>{
 requestNativeAction('choose-notebooklm-archive');
});
document.querySelector('#notebooklm-choose-target').addEventListener('click',()=>{
 const request=window.notebookLMTargetPickerRequest();
 if(request)requestNativeAction('choose-notebooklm-target',request);
});
document.querySelector('#notebooklm-archive').addEventListener('input',()=>resetNotebookArchive());
notebookSelection.addEventListener('change',()=>resetNotebookPlan('Výběr se změnil. Připravte nový plán.'));
document.querySelector('#notebooklm-privacy').addEventListener('change',()=>resetNotebookPlan('Privacy se změnila. Připravte nový plán.'));
document.querySelector('#notebooklm-load').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;notebookStatus.textContent='Kontroluji archiv…';resetNotebookPlan();
 try{notebookBundle=await projectRequest('/v1/notebooklm/preview',notebookArchiveRequest(),120000);
  notebookSelection.replaceChildren(...notebookBundle.notebooks.map(item=>{
   const option=document.createElement('option');option.value=item.selection_digest;
   option.textContent=`${item.title} · ${item.sources.length} zdrojů · ${item.artifacts.length} výstupů · ${item.chats.length} chatů`;
   option.disabled=!item.importable;return option;}));
  notebookAttempt=null;notebookTargetCapability=null;
  notebookSelection.disabled=false;document.querySelector('#notebooklm-plan').disabled=false;
  notebookStatus.textContent=`Nalezeno ${notebookBundle.notebooks.length} projektů NotebookLM. Vyberte právě jeden.`;
 }catch(error){resetNotebookArchive(error.message);}finally{event.currentTarget.disabled=false;}
});
document.querySelector('#notebooklm-plan').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;
 try{notebookStatus.textContent='Připravuji plán…';
  if(!notebookAttempt)notebookAttempt={operation_id:crypto.randomUUID()};
  notebookPlan=await projectRequest('/v1/notebooklm/plan',{...notebookArchiveRequest(),
   selection_digest:notebookSelection.value,privacy:document.querySelector('#notebooklm-privacy').value,
   operation_id:notebookAttempt.operation_id,target_capability:notebookTargetCapability?.target_capability||null},120000);
  document.querySelector('#notebooklm-destination').textContent=notebookPlan.target_root;
  const summary={edice:'Personal NotebookLM / Google Takeout',vybrany_projekt:notebookPlan.title,
   cil:notebookPlan.target_root,privacy:notebookPlan.privacy,polozky:notebookPlan.artifacts.length,
   existujici_shodne_importy:notebookPlan.existing_imports,
   varovani:notebookPlan.warnings,digest:notebookPlan.request_digest};
  const output=document.querySelector('#notebooklm-preview');output.textContent=JSON.stringify(summary,null,2);output.hidden=false;
  document.querySelector('#notebooklm-confirm-row').hidden=false;document.querySelector('#notebooklm-confirm').checked=false;
  document.querySelector('#notebooklm-run').disabled=true;notebookStatus.textContent='Plán je připraven k potvrzení.';
 }catch(error){resetNotebookPlan(error.message);}finally{event.currentTarget.disabled=false;}
});
document.querySelector('#notebooklm-confirm').addEventListener('change',event=>{
 document.querySelector('#notebooklm-run').disabled=!(event.currentTarget.checked&&notebookPlan);});
document.querySelector('#notebooklm-run').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;notebookStatus.textContent='Importuji projekt…';
 try{const result=await projectRequest('/v1/notebooklm/confirm',{
   ...notebookArchiveRequest(),plan:notebookPlan},180000);
  notebookStatus.textContent='Projekt byl vytvořen jedním počátečním commitem.';
  notebookPlan=null;await loadProjects(result.id);
 }catch(error){notebookStatus.textContent=error.message;event.currentTarget.disabled=false;}
});

"""

JS += """
let activeProject=null, selectedArtifact=null, previewRequest=0;
const previewStatus=document.querySelector('#preview-status');
const previewContent=document.querySelector('#preview-content');
const mainTabs=[...document.querySelectorAll('#main-tabs [role="tab"]')];
const promptForm=document.querySelector('#chat-composer');
function setPromptVisible(visible){promptForm.hidden=!visible;}
function selectMainTab(tab){
 for(const item of mainTabs){
  const active=item===tab;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;
  document.getElementById(item.getAttribute('aria-controls')).hidden=!active;
 }
 document.querySelector('#main-panel-content').classList.toggle('project-overview-active',tab.id==='project-overview-tab');
 setPromptVisible(tab.dataset.promptDefault!=='hidden');
}
for(const tab of mainTabs){
 tab.addEventListener('click',()=>selectMainTab(tab));
 tab.addEventListener('keydown',event=>{
  const visible=mainTabs.filter(item=>!item.hidden),index=visible.indexOf(tab);
  const next={ArrowRight:(index+1)%visible.length,
   ArrowLeft:(index+visible.length-1)%visible.length,Home:0,End:visible.length-1}[event.key];
  if(next===undefined)return;
  event.preventDefault();selectMainTab(visible[next]);visible[next].focus();
 });
}
const presentationTab=document.querySelector('#presentation-tab');
const outputsOverviewTab=document.querySelector('#outputs-overview-tab');
const outputsOverviewList=document.querySelector('#outputs-overview-list');
const outputsOverviewStatus=document.querySelector('#outputs-overview-status');
const presentationEditorDocuments=document.querySelector('#presentation-editor-documents');
const sidebarPresentationList=document.querySelector('#sidebar-presentation-list');
const sidebarPresentationStatus=document.querySelector('#sidebar-presentation-status');
const presentationEditorWorkspace=document.querySelector('#presentation-editor-workspace');
const presentationEditorStatus=document.querySelector('#presentation-editor-status');
const presentationEditorSave=document.querySelector('#presentation-editor-save');
const presentationEditorUse=document.querySelector('#presentation-editor-use');
const presentationEditorPrint=document.querySelector('#presentation-editor-print');
const presentationSessionList=document.querySelector('#presentation-session-list');
const presentationSessionStatus=document.querySelector('#presentation-session-status');
let presentationEditorView=null,presentationEditorDeck=null,presentationEditorArtifact=null,presentationEditorSlide=null;
let presentationEditorNew=false,presentationEditorDirty=false,presentationEditorAttempt=null,presentationEditorLoading=false;
let presentationPrintPlan=null,presentationPrintTarget=null;
function presentationNewSlide(kind='main',layout='content'){
 const template=presentationEditorDeck?.templates?.find(item=>item.id===layout)||presentationEditorView?.layout_presets?.find(item=>item.id===layout)||{background:'#102b36',foreground:'#ffffff'};
 return {id:crypto.randomUUID(),kind,title:'Nový slide',bullets:[],notes:'',background:template.background,foreground:template.foreground,wallpaper:'',next:null,backups:[],repeat:false,reveal:'all',layout,column_break:0};
}
function presentationNewDeck(){const templates=structuredClone(presentationEditorView.layout_presets),template=templates.find(item=>item.id==='content')||templates[0],slide=presentationNewSlide('main',template.id);slide.background=template.background;slide.foreground=template.foreground;return {version:1,title:'Nová prezentace',templates,slides:[slide]};}
function presentationMainOrder(){
 const main=new Map(presentationEditorDeck.slides.filter(slide=>slide.kind==='main').map(slide=>[slide.id,slide]));
 const targets=new Set([...main.values()].map(slide=>slide.next).filter(Boolean));let current=[...main.keys()].find(id=>!targets.has(id)),order=[];
 while(current&&main.has(current)&&!order.includes(current)){order.push(current);current=main.get(current).next;}
 return order;
}
function presentationRelink(order){const byId=new Map(presentationEditorDeck.slides.map(slide=>[slide.id,slide]));for(const [index,id] of order.entries())byId.get(id).next=order[index+1]||null;}
function presentationCurrentSlide(){return presentationEditorDeck?.slides.find(slide=>slide.id===presentationEditorSlide);}
function presentationCurrentTemplate(){const selected=document.querySelector('#presentation-template-select')?.value||presentationCurrentSlide()?.layout;return presentationEditorDeck?.templates.find(item=>item.id===selected);}
function presentationVisualSlide(slide){if(!slide)return slide;return {...slide,layout:structuredClone(presentationEditorDeck.templates.find(item=>item.id===slide.layout)||{})};}
function canLeavePresentationEditor(){
 if(!presentationEditorDirty&&!presentationEditorAttempt)return true;
 return window.confirm(presentationEditorAttempt?'Výsledek uložení není ověřený. Zahodit rozepsanou relaci editoru?':'Zahodit neuložené změny prezentace?');
}
function updatePresentationEditorEnabled(){
 const frozen=Boolean(presentationEditorAttempt),ready=Boolean(presentationEditorDeck);
 for(const control of presentationEditorWorkspace.querySelectorAll('input,textarea,select,button'))control.disabled=frozen||!ready;
 presentationEditorDocuments.disabled=frozen;document.querySelector('#presentation-editor-new').disabled=frozen;
 presentationEditorSave.disabled=!ready||(!presentationEditorDirty&&!presentationEditorAttempt);
 presentationEditorSave.textContent=presentationEditorAttempt?'Opakovat stejné uložení':'Uložit do projektu';
 presentationEditorUse.disabled=!ready||presentationEditorDirty||presentationEditorNew||Boolean(presentationEditorAttempt);
 presentationEditorPrint.disabled=!ready||presentationEditorDirty||presentationEditorNew||Boolean(presentationEditorAttempt);
 document.querySelector('#presentation-clear-wallpaper').disabled=frozen||!ready||!presentationCurrentSlide()?.wallpaper;
}
function presentationEditorChanged(rerender=true){
 if(presentationEditorLoading||!presentationEditorDeck)return;presentationEditorDirty=true;presentationEditorAttempt=null;
 if(rerender)renderPresentationEditor();else{renderSlideVisual(document.querySelector('#presentation-editor-preview'),presentationVisualSlide(presentationCurrentSlide()));const selected=document.querySelector('#presentation-slide-list button[aria-current="true"]');if(selected)selected.textContent=(presentationCurrentSlide().kind==='backup'?'Backup · ':'')+presentationCurrentSlide().title;updatePresentationEditorEnabled();}
}
function renderPresentationTemplateForm(preferred=null){
 const manager=document.querySelector('#presentation-template-select'),layout=document.querySelector('#presentation-slide-layout'),current=presentationCurrentSlide();manager.replaceChildren();layout.replaceChildren();
 for(const template of presentationEditorDeck.templates){manager.append(new Option(template.name,template.id));layout.append(new Option(template.name,template.id));}
 layout.value=current.layout;manager.value=presentationEditorDeck.templates.some(item=>item.id===preferred)?preferred:current.layout;
 const template=presentationCurrentTemplate(),slideTemplate=presentationEditorDeck.templates.find(item=>item.id===current.layout);document.querySelector('#presentation-template-name').value=template.name;document.querySelector('#presentation-template-preset').value=template.preset;document.querySelector('#presentation-template-title-align').value=template.title_align;document.querySelector('#presentation-template-content-align').value=template.content_align;document.querySelector('#presentation-template-density').value=template.density;document.querySelector('#presentation-template-background').value=template.background;document.querySelector('#presentation-template-foreground').value=template.foreground;document.querySelector('#presentation-template-accent').value=template.accent;
 document.querySelector('#presentation-template-delete').disabled=presentationEditorDeck.templates.length===1;document.querySelector('#presentation-column-break-label').hidden=slideTemplate.preset!=='two-column';document.querySelector('#presentation-column-break').value=current.column_break||0;
}
function renderPresentationEditor(){
 const slide=presentationCurrentSlide();presentationEditorLoading=true;presentationEditorWorkspace.hidden=!slide;
 if(!slide){presentationEditorLoading=false;updatePresentationEditorEnabled();return;}
 document.querySelector('#presentation-deck-title').value=presentationEditorDeck.title;
 const list=document.querySelector('#presentation-slide-list');list.replaceChildren();const order=presentationMainOrder(),byId=new Map(presentationEditorDeck.slides.map(item=>[item.id,item]));
 for(const id of [...order,...presentationEditorDeck.slides.filter(item=>item.kind==='backup').map(item=>item.id)]){
  const item=byId.get(id),row=document.createElement('li'),button=document.createElement('button');row.className=item.kind;button.type='button';button.textContent=(item.kind==='backup'?'Backup · ':'')+item.title;button.setAttribute('aria-current',String(id===slide.id));button.addEventListener('click',()=>{presentationEditorSlide=id;renderPresentationEditor();});row.append(button);list.append(row);
 }
 document.querySelector('#presentation-slide-kind').textContent=slide.kind==='backup'?'Backup slide':'Hlavní slide';
 renderPresentationTemplateForm();
 document.querySelector('#presentation-slide-title').value=slide.title;document.querySelector('#presentation-slide-bullets').value=slide.bullets.join('\\n');document.querySelector('#presentation-slide-notes').value=slide.notes;
 document.querySelector('#presentation-slide-repeat').checked=Boolean(slide.repeat);document.querySelector('#presentation-slide-reveal').value=slide.reveal||'all';document.querySelector('#presentation-slide-background').value=slide.background;document.querySelector('#presentation-slide-foreground').value=slide.foreground;
 const links=document.querySelector('#presentation-backup-links');links.replaceChildren();
 const candidates=presentationEditorDeck.slides.filter(item=>item.kind!==slide.kind);
 for(const other of candidates){const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=slide.kind==='main'?slide.backups.includes(other.id):other.backups.includes(slide.id);check.addEventListener('change',()=>{const source=slide.kind==='main'?slide:other,target=slide.kind==='main'?other:slide;source.backups=check.checked?[...new Set([...source.backups,target.id])]:source.backups.filter(id=>id!==target.id);presentationEditorChanged();});label.append(check,document.createTextNode(' '+other.title));links.append(label);}
 if(!candidates.length)links.textContent=slide.kind==='main'?'Zatím nejsou vytvořené žádné backupy.':'Zatím nejsou dostupné hlavní slidy.';
 renderSlideVisual(document.querySelector('#presentation-editor-preview'),presentationVisualSlide(slide));
 const position=order.indexOf(slide.id);document.querySelector('#presentation-slide-up').disabled=slide.kind!=='main'||position<=0;document.querySelector('#presentation-slide-down').disabled=slide.kind!=='main'||position<0||position===order.length-1;
 presentationEditorLoading=false;updatePresentationEditorEnabled();renderPresentationSessions();
}
function presentationSessionsForDeck(){return (presentationEditorView?.sessions||[]).filter(row=>row.session?.source_artifact_id===presentationEditorArtifact);}
function renderPresentationSessions(){
 presentationSessionList.replaceChildren();const rows=presentationSessionsForDeck();
 for(const row of rows){const item=document.createElement('li'),description=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('small'),actions=document.createElement('div'),print=document.createElement('button'),remove=document.createElement('button'),session=row.session;
  title.textContent=new Date(session.started_at).toLocaleString('cs-CZ');detail.textContent=`${session.outcome==='completed'?'Dokončená':'Přerušená'} · ${session.pages.length} stran · ${session.source_revision.slice(0,12)}`;description.append(title,detail);actions.className='form-actions';print.type='button';print.textContent='Vytisknout';print.disabled=!session.pages.length;remove.type='button';remove.className='danger-button';remove.textContent='Smazat';print.addEventListener('click',()=>preparePresentationPrint(row.id));remove.addEventListener('click',()=>deletePresentationSession(row));actions.append(print,remove);item.append(description,actions);presentationSessionList.append(item);
 }
 presentationSessionStatus.textContent=rows.length?`Počet zaznamenaných relací: ${rows.length}.`:'Tato prezentace zatím nemá zaznamenanou relaci.';
}
async function deletePresentationSession(row){
 if(!activeProject||!window.confirm(`Smazat záznam relace z ${new Date(row.session.started_at).toLocaleString('cs-CZ')}? Git historie zůstane zachovaná.`))return;
 try{const preview=await projectRequest('/v1/artifacts/delete/preview',{project_id:activeProject.id,artifact_id:row.id,expected_head:presentationEditorView.commit_id});
  if(!window.confirm(`Potvrďte odstranění záznamu „${preview.title}“ z commitu ${preview.base_head.slice(0,12)}.`))return;
  await projectRequest('/v1/artifacts/delete/confirm',{project_id:activeProject.id,artifact_id:row.id,base_head:preview.base_head,preview_sha256:preview.preview_sha256,operation_id:crypto.randomUUID()},120000);const projectId=activeProject.id,deckId=presentationEditorArtifact;await openRegisteredProject(projectId);await openPresentationEditor(deckId);presentationSessionStatus.textContent='Záznam relace byl odstraněn; Git historie zůstala zachovaná.';
 }catch(error){presentationSessionStatus.textContent=error.message;}
}
async function preparePresentationPrint(sessionArtifactId=null){
 if(!activeProject||!presentationEditorArtifact)return;
 try{const request={project_id:activeProject.id,artifact_id:presentationEditorArtifact,expected_head:presentationEditorView.commit_id};if(sessionArtifactId)request.session_artifact_id=sessionArtifactId;
  presentationPrintPlan=await projectRequest('/v1/presentations/export/preview',request);presentationPrintPlan.nonce=crypto.randomUUID();presentationPrintTarget=null;const count=presentationPrintPlan.pages.length,mode=presentationPrintPlan.mode==='canonical'?'Kanonická prezentace':'Uskutečněná relace';
  document.querySelector('#presentation-print-details').textContent=`Režim: ${mode}\nPrezentace: ${presentationPrintPlan.title}\nZdrojová revize: ${presentationPrintPlan.source_revision}\nPočet stran: ${count}\nPořadí: ${presentationPrintPlan.pages.map((page,index)=>`${index+1}. ${page.title}`).join(' | ')||'žádné strany'}`;
  document.querySelector('#presentation-print-warning').textContent=count?'Soukromé poznámky a nepromítnutý obsah nejsou součástí exportu.':'Prázdnou relaci nelze vytisknout.';document.querySelector('#presentation-print-target').textContent='Cíl PDF zatím není vybraný.';document.querySelector('#presentation-print-confirm').checked=false;document.querySelector('#presentation-print-confirm').disabled=true;document.querySelector('#presentation-print-run').disabled=true;document.querySelector('#presentation-print-choose').disabled=!count;document.querySelector('#presentation-print-dialog').showModal();
 }catch(error){presentationEditorStatus.textContent=error.message;}
}
function renderPresentationPrint(){const target=document.querySelector('#presentation-print-view');document.body.append(target);target.replaceChildren();for(const page of presentationPrintPlan.pages){const slide=document.createElement('section');slide.className='print-slide presenter-slide-preview';renderSlideVisual(slide,page);target.append(slide);}}
presentationEditorPrint.addEventListener('click',()=>preparePresentationPrint());
document.querySelector('#presentation-print-choose').addEventListener('click',()=>{if(presentationPrintPlan?.pages.length)location.hash=`choose-presentation-pdf?nonce=${presentationPrintPlan.nonce}`;});
function presentationPdfTargetRequest(){return presentationPrintPlan?.pages.length?{nonce:presentationPrintPlan.nonce,preview_sha256:presentationPrintPlan.preview_sha256}:null;}
function setPresentationPdfTarget(result){if(!presentationPrintPlan||result?.nonce!==presentationPrintPlan.nonce)return;presentationPrintTarget=result;document.querySelector('#presentation-print-target').textContent=`Cíl: ${result.path}${result.exists?' — existující soubor bude atomicky přepsán':' — nový soubor'}`;document.querySelector('#presentation-print-confirm').checked=false;document.querySelector('#presentation-print-confirm').disabled=false;document.querySelector('#presentation-print-run').disabled=true;}
function setPresentationPdfNativeError(message){document.querySelector('#presentation-print-warning').textContent=message||'Nativní export se nezdařil.';document.querySelector('#presentation-print-run').disabled=true;}
function presentationPdfExportRequest(){if(!presentationPrintPlan||!presentationPrintTarget||!document.querySelector('#presentation-print-confirm').checked)return null;return {nonce:presentationPrintPlan.nonce,preview_sha256:presentationPrintPlan.preview_sha256};}
function presentationPdfExportFinished(result){if(!presentationPrintPlan||result?.nonce!==presentationPrintPlan.nonce)return;if(result.success){document.querySelector('#presentation-print-dialog').close();presentationEditorStatus.textContent=`PDF bylo atomicky uloženo: ${presentationPrintTarget.path}`;presentationPrintPlan=null;presentationPrintTarget=null;}else{document.querySelector('#presentation-print-warning').textContent=result.error||'PDF se nepodařilo vytvořit.';document.querySelector('#presentation-print-run').disabled=false;}}
document.querySelector('#presentation-print-confirm').addEventListener('change',event=>{document.querySelector('#presentation-print-run').disabled=!(event.currentTarget.checked&&presentationPrintTarget&&presentationPrintPlan?.pages.length);});
document.querySelector('#presentation-print-run').addEventListener('click',()=>{if(!presentationPrintTarget||!presentationPrintPlan?.pages.length||!document.querySelector('#presentation-print-confirm').checked)return;renderPresentationPrint();document.querySelector('#presentation-print-run').disabled=true;location.hash=`export-presentation-pdf?nonce=${presentationPrintPlan.nonce}`;});
function installPresentationDocument(document){
 presentationEditorDeck=structuredClone(document.deck);presentationEditorArtifact=document.id;presentationEditorSlide=presentationEditorDeck.slides[0].id;presentationEditorNew=false;presentationEditorDirty=false;presentationEditorAttempt=null;renderPresentationEditor();
}
function renderOutputsOverview(preferred=null){
 outputsOverviewList.replaceChildren();
 const documents=presentationEditorView?.documents||[];
 const selected=documents.find(item=>item.id===preferred)||documents[0];
 for(const doc of documents){
  const item=document.createElement('li'),button=document.createElement('button'),title=document.createElement('strong'),detail=document.createElement('small');
  button.type='button';button.dataset.id=doc.id;button.setAttribute('aria-current',String(doc===selected));
  title.textContent=doc.title+(doc.error?' — neplatná':'');detail.textContent=`Prezentace · ${doc.id}`;
  button.append(title,detail);button.addEventListener('click',()=>renderOutputsOverview(doc.id));item.append(button);outputsOverviewList.append(item);
 }
 const panel=document.querySelector('#outputs-overview-detail'),properties=document.querySelector('#outputs-overview-properties');properties.replaceChildren();
 if(!selected){panel.hidden=true;outputsOverviewStatus.textContent='Projekt zatím nemá žádnou uloženou definici výstupu.';return;}
 outputsOverviewStatus.textContent=`Počet definic výstupů: ${documents.length} · commit ${presentationEditorView.commit_id.slice(0,12)}`;
 panel.hidden=false;document.querySelector('#outputs-overview-detail-title').textContent=selected.title;
 const values=[['Typ','Prezentace'],['Artefakt',selected.id],['Stav',selected.error?'Neplatná definice':'Validní definice'],['Hlavní slidy',String(selected.deck?.slides?.filter(slide=>slide.kind==='main').length||0)],['Záložní slidy',String(selected.deck?.slides?.filter(slide=>slide.kind==='backup').length||0)],['Revize projektu',presentationEditorView.commit_id]];
 for(const [name,value] of values){const term=document.createElement('dt'),description=document.createElement('dd');term.textContent=name;description.textContent=value;properties.append(term,description);}
}
async function openOutputsOverview(preferred=null){
 if(!activeProject){projectStatus.textContent='Nejprve otevřete projekt, do kterého výstupy patří.';return;}
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;notebookImportView.hidden=true;historyView.hidden=true;projectView.hidden=false;
 selectSidebarTab(document.querySelector('#presentations-tab'));selectMainTab(outputsOverviewTab);outputsOverviewTab.focus();
 if(!presentationEditorView||presentationEditorView.commit_id!==activeProject.head){
  outputsOverviewStatus.textContent='Načítám definice výstupů…';
  try{presentationEditorView=await projectRequest('/v1/outputs/definitions',{project_id:activeProject.id,expected_head:activeProject.head});renderPresentationDocuments(null,false);renderOutputsOverview(preferred);}
  catch(error){outputsOverviewList.replaceChildren();document.querySelector('#outputs-overview-detail').hidden=true;outputsOverviewStatus.textContent=error.message;}
 }else renderOutputsOverview(preferred);
}
function renderSidebarPresentations(){
 sidebarPresentationList.replaceChildren();
 for(const doc of presentationEditorView.documents){
  const item=document.createElement('li'),main=document.createElement('button'),title=document.createElement('strong'),identity=document.createElement('small');
  item.className='sidebar-list-row sidebar-presentation-row';main.type='button';main.className='sidebar-list-main';title.textContent=doc.title+(doc.error?' — neplatná':'');identity.textContent=doc.id;main.disabled=Boolean(doc.error);
  const web=document.body.dataset.runtime==='server';
  main.addEventListener('click',()=>web?openOutputsOverview(doc.id):openPresentationEditor(doc.id));main.append(title,identity);
  const actions=web?[{label:'Zobrazit',run:()=>openOutputsOverview(doc.id)}]:[
   {label:'Upravit',run:()=>openPresentationEditor(doc.id),disabled:Boolean(doc.error)},
   {label:'Spustit',run:()=>usePresentationDocument(doc),disabled:Boolean(doc.error)}];
  const menu=sidebarItemMenu(doc.title,actions,'sidebar-presentation-menu');
  item.append(main,menu);sidebarPresentationList.append(item);
 }
 sidebarPresentationStatus.textContent=presentationEditorView.documents.length?`Počet prezentací: ${presentationEditorView.documents.length}`:'Zatím tu nejsou žádné uložené prezentace.';
}
function renderPresentationDocuments(preferred=null,openEditor=true){
 presentationEditorDocuments.replaceChildren();
 for(const doc of presentationEditorView.documents){const option=new Option(doc.title+(doc.error?' — neplatná':''),doc.id);option.disabled=Boolean(doc.error);presentationEditorDocuments.append(option);}
 renderSidebarPresentations();if(!openEditor)return;
 const document=presentationEditorView.documents.find(doc=>doc.id===(preferred||presentationEditorArtifact)&&doc.deck)||presentationEditorView.documents.find(doc=>doc.deck);
 if(document){presentationEditorDocuments.value=document.id;installPresentationDocument(document);}else{presentationEditorDocuments.append(new Option('Nová neuložená prezentace',''));createPresentationDocument(false);}
}
async function loadPresentationEditor(preferred=null,openEditor=true){
 if(!activeProject)return;sidebarPresentationStatus.textContent='Načítám prezentace projektu…';presentationEditorStatus.textContent='Načítám prezentace projektu…';
 try{presentationEditorView=await projectRequest('/v1/presentations/open',{project_id:activeProject.id,expected_head:activeProject.head});renderPresentationDocuments(preferred,openEditor);presentationEditorStatus.textContent=presentationEditorView.documents.length?'Editor používá aktuální uloženou verzi projektu.':'Nová prezentace vznikne až po kliknutí na Uložit do projektu.';}
 catch(error){sidebarPresentationStatus.textContent=error.message;presentationEditorStatus.textContent=error.message;presentationEditorDeck=null;presentationEditorWorkspace.hidden=true;updatePresentationEditorEnabled();}
}
async function openPresentationEditor(preferred=null){
 if(!activeProject){projectStatus.textContent='Nejprve otevřete projekt, do kterého prezentace patří.';return;}
 if(!artifactEditorView.hidden){if(!canLeaveArtifactEditor())return;artifactEditorView.hidden=true;artifactEditorItem=null;artifactEditorAttempt=null;artifactEditorDirty=false;}
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;notebookImportView.hidden=true;historyView.hidden=true;projectView.hidden=false;selectSidebarTab(document.querySelector('#presentations-tab'));
 selectMainTab(presentationTab);presentationTab.focus();if(!presentationEditorView||presentationEditorView.commit_id!==activeProject.head)await loadPresentationEditor(preferred,true);else if(preferred){const document=presentationEditorView.documents.find(item=>item.id===preferred&&item.deck);if(document){if(!canLeavePresentationEditor())return;presentationEditorDocuments.value=document.id;installPresentationDocument(document);}}
}
function createPresentationDocument(confirmDiscard=true){
 if(confirmDiscard&&!canLeavePresentationEditor())return;presentationEditorDeck=presentationNewDeck();presentationEditorArtifact=crypto.randomUUID();presentationEditorSlide=presentationEditorDeck.slides[0].id;presentationEditorNew=true;presentationEditorDirty=true;presentationEditorAttempt=null;presentationEditorDocuments.value='';renderPresentationEditor();presentationEditorStatus.textContent='Koncept je pouze v editoru. Soubor vznikne až po uložení.';
}
presentationTab.addEventListener('click',()=>{if(!presentationEditorView||presentationEditorView.commit_id!==activeProject?.head)loadPresentationEditor();else if(!presentationEditorDeck)renderPresentationDocuments();});
document.querySelector('#presentations-tab').addEventListener('click',()=>{if(document.body.dataset.runtime==='server'){openOutputsOverview();return;}if(!presentationEditorView||presentationEditorView.commit_id!==activeProject?.head)loadPresentationEditor(null,false);else renderSidebarPresentations();});
presentationEditorDocuments.addEventListener('change',()=>{const document=presentationEditorView?.documents.find(item=>item.id===presentationEditorDocuments.value&&item.deck);if(document){if(canLeavePresentationEditor())installPresentationDocument(document);else presentationEditorDocuments.value=presentationEditorArtifact;}});
document.querySelector('#presentation-editor-new').addEventListener('click',()=>createPresentationDocument());
document.querySelector('#presentation-editor-reload').addEventListener('click',()=>{if(canLeavePresentationEditor()){presentationEditorView=null;loadPresentationEditor();}});
for(const id of ['presentation-deck-title','presentation-slide-title','presentation-slide-bullets','presentation-slide-notes','presentation-slide-repeat','presentation-slide-reveal','presentation-slide-background','presentation-slide-foreground'])document.querySelector('#'+id).addEventListener('input',()=>{
 if(presentationEditorLoading)return;const slide=presentationCurrentSlide();presentationEditorDeck.title=document.querySelector('#presentation-deck-title').value;slide.title=document.querySelector('#presentation-slide-title').value;slide.bullets=document.querySelector('#presentation-slide-bullets').value.split(/\\r?\\n/).filter(line=>line.trim());slide.column_break=Math.min(slide.column_break||0,slide.bullets.length);slide.notes=document.querySelector('#presentation-slide-notes').value;slide.repeat=document.querySelector('#presentation-slide-repeat').checked;slide.reveal=document.querySelector('#presentation-slide-reveal').value;slide.background=document.querySelector('#presentation-slide-background').value;slide.foreground=document.querySelector('#presentation-slide-foreground').value;presentationEditorChanged(false);
});
document.querySelector('#presentation-slide-layout').addEventListener('change',event=>{if(presentationEditorLoading)return;const slide=presentationCurrentSlide(),template=presentationEditorDeck.templates.find(item=>item.id===event.currentTarget.value);slide.layout=template.id;slide.background=template.background;slide.foreground=template.foreground;slide.column_break=0;presentationEditorChanged();});
document.querySelector('#presentation-column-break').addEventListener('input',event=>{if(presentationEditorLoading)return;const slide=presentationCurrentSlide();slide.column_break=Math.max(0,Math.min(slide.bullets.length,Number(event.currentTarget.value)||0));presentationEditorChanged(false);});
document.querySelector('#presentation-template-select').addEventListener('change',event=>renderPresentationTemplateForm(event.currentTarget.value));
const presentationTemplateFields={'presentation-template-name':'name','presentation-template-preset':'preset','presentation-template-title-align':'title_align','presentation-template-content-align':'content_align','presentation-template-density':'density','presentation-template-background':'background','presentation-template-foreground':'foreground','presentation-template-accent':'accent'};
for(const [id,key] of Object.entries(presentationTemplateFields))document.querySelector('#'+id).addEventListener('input',event=>{
 if(presentationEditorLoading)return;const template=presentationCurrentTemplate(),previous=template[key];template[key]=event.currentTarget.value;template.revision=Math.min(1000000,template.revision+1);
 if(key==='background'||key==='foreground'){for(const slide of presentationEditorDeck.slides)if(slide.layout===template.id&&slide[key]===previous)slide[key]=template[key];document.querySelector('#presentation-slide-'+key).value=presentationCurrentSlide()[key];}
 const option=document.querySelector(`#presentation-template-select option[value="${template.id}"]`),layoutOption=document.querySelector(`#presentation-slide-layout option[value="${template.id}"]`);if(key==='name'){option.textContent=template.name;layoutOption.textContent=template.name;}
 if(template.id===presentationCurrentSlide().layout)document.querySelector('#presentation-column-break-label').hidden=template.preset!=='two-column';presentationEditorChanged(false);
});
document.querySelector('#presentation-template-copy').addEventListener('click',()=>{if(presentationEditorDeck.templates.length>=20){presentationEditorStatus.textContent='Limit je 20 šablon.';return;}const source=presentationCurrentTemplate(),copy={...structuredClone(source),id:crypto.randomUUID(),revision:1,name:`Kopie – ${source.name}`};presentationEditorDeck.templates.push(copy);presentationCurrentSlide().layout=copy.id;presentationEditorChanged();renderPresentationTemplateForm(copy.id);});
document.querySelector('#presentation-template-reset').addEventListener('click',()=>{const template=presentationCurrentTemplate(),preset=presentationEditorView.layout_presets.find(item=>item.preset===template.preset)||presentationEditorView.layout_presets[0],identity={id:template.id,name:template.name,revision:Math.min(1000000,template.revision+1)};Object.assign(template,structuredClone(preset),identity);presentationEditorChanged();renderPresentationTemplateForm(template.id);});
document.querySelector('#presentation-template-delete').addEventListener('click',()=>{const template=presentationCurrentTemplate();if(presentationEditorDeck.templates.length===1)return;const fallback=presentationEditorDeck.templates.find(item=>item.id!==template.id);presentationEditorDeck.templates=presentationEditorDeck.templates.filter(item=>item.id!==template.id);for(const slide of presentationEditorDeck.slides)if(slide.layout===template.id){slide.layout=fallback.id;slide.background=fallback.background;slide.foreground=fallback.foreground;slide.column_break=0;}presentationEditorChanged();renderPresentationTemplateForm(fallback.id);});
function addPresentationSlide(kind){if(presentationEditorDeck.slides.length>=100){presentationEditorStatus.textContent='Limit je 100 slidů.';return;}const current=presentationCurrentSlide(),slide=presentationNewSlide(kind,current.layout),order=presentationMainOrder();presentationEditorDeck.slides.push(slide);if(kind==='main')presentationRelink([...order,slide.id]);else if(current.kind==='main')current.backups.push(slide.id);presentationEditorSlide=slide.id;presentationEditorChanged();}
document.querySelector('#presentation-add-main').addEventListener('click',()=>addPresentationSlide('main'));document.querySelector('#presentation-add-backup').addEventListener('click',()=>addPresentationSlide('backup'));
document.querySelector('#presentation-delete-slide').addEventListener('click',()=>{const slide=presentationCurrentSlide(),order=presentationMainOrder();if(slide.kind==='main'&&order.length===1){presentationEditorStatus.textContent='Poslední hlavní slide nelze odstranit.';return;}presentationEditorDeck.slides=presentationEditorDeck.slides.filter(item=>item.id!==slide.id);presentationRelink(order.filter(id=>id!==slide.id));for(const item of presentationEditorDeck.slides)item.backups=item.backups.filter(id=>id!==slide.id);presentationEditorSlide=presentationEditorDeck.slides[0].id;presentationEditorChanged();});
function movePresentationSlide(delta){const order=presentationMainOrder(),index=order.indexOf(presentationEditorSlide);if(index<0||index+delta<0||index+delta>=order.length)return;[order[index],order[index+delta]]=[order[index+delta],order[index]];presentationRelink(order);presentationEditorChanged();}
document.querySelector('#presentation-slide-up').addEventListener('click',()=>movePresentationSlide(-1));document.querySelector('#presentation-slide-down').addEventListener('click',()=>movePresentationSlide(1));
document.querySelector('#presentation-clear-wallpaper').addEventListener('click',()=>{presentationCurrentSlide().wallpaper='';presentationEditorChanged();});
document.querySelector('#presentation-slide-wallpaper').addEventListener('change',async event=>{const file=event.currentTarget.files[0];event.currentTarget.value='';if(!file)return;if(file.type!=='image/png'||file.size>190000){presentationEditorStatus.textContent='Vyberte PNG do 190 KiB.';return;}const value=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(reader.error);reader.readAsDataURL(file);});if(String(value).length>262144){presentationEditorStatus.textContent='Zakódovaná tapeta překračuje limit 256 KiB.';return;}presentationCurrentSlide().wallpaper=String(value);presentationEditorChanged();});
presentationEditorSave.addEventListener('click',async()=>{
 if(!activeProject||!presentationEditorDeck)return;if(!presentationEditorAttempt){const document={project_id:activeProject.id,artifact_id:presentationEditorArtifact,base_head:presentationEditorView.commit_id,new:presentationEditorNew,deck:structuredClone(presentationEditorDeck)};presentationEditorAttempt={operation_id:crypto.randomUUID(),document};}
 updatePresentationEditorEnabled();presentationEditorStatus.textContent='Ukládám potvrzenou podobu prezentace do projektu…';
 try{const result=await projectRequest('/v1/presentations/save',presentationEditorAttempt,120000),id=presentationEditorArtifact,projectId=activeProject.id;presentationEditorAttempt=null;presentationEditorDirty=false;presentationEditorNew=false;await openRegisteredProject(projectId);await openPresentationEditor(id);presentationEditorStatus.textContent=`Prezentace byla uložena do projektu (${result.commit_id.slice(0,12)}).`;}
 catch(error){if([400,409,422].includes(error.status))presentationEditorAttempt=null;presentationEditorStatus.textContent=error.message+(presentationEditorAttempt?' Opakujte stejné uložení nebo znovu načtěte projekt.':'');updatePresentationEditorEnabled();}
});
async function usePresentationDocument(document){try{presentationEditorUse.disabled=true;await projectRequest('/v1/presentations/use',{project_id:activeProject.id,artifact_id:document.id,expected_head:presentationEditorView.commit_id});sidebarPresentationStatus.textContent=`Prezentace „${document.title}“ je připravena v presenteru.`;presentationEditorStatus.textContent='Uložená prezentace je připravena v presenteru.';openPresenter();}catch(error){sidebarPresentationStatus.textContent=error.message;presentationEditorStatus.textContent=error.message;}finally{updatePresentationEditorEnabled();}}
presentationEditorUse.addEventListener('click',()=>usePresentationDocument({id:presentationEditorArtifact,title:presentationEditorDeck.title}));
document.querySelector('#presentation-editor-presenter').addEventListener('click',openPresenter);
const applicationAccessForm=document.querySelector('#application-access-form');
const applicationAccessAllowedRow=document.querySelector('#application-access-allowed-row');
const applicationAccessStatus=document.querySelector('#application-access-status');
const applicationAccessPreview=document.querySelector('#application-access-preview');
const applicationAccessConfirm=document.querySelector('#application-access-confirm');
const applicationAccessSave=document.querySelector('#application-access-save');
let applicationAccessPlan=null;
const applicationAccessLabels={localhost:'Pouze localhost','private-network':'Lokální / privátní síť',allowlist:'Pouze povolené adresy',unrestricted:'Neomezeně'};
function invalidateApplicationAccess(){applicationAccessPlan=null;applicationAccessPreview.hidden=true;applicationAccessConfirm.checked=false;applicationAccessSave.disabled=true;applicationAccessAllowedRow.hidden=applicationAccessForm.elements.mode.value!=='allowlist';}
function fillApplicationAccess(result){
 const settings=result.settings;applicationAccessForm.elements.mode.value=settings.mode;applicationAccessForm.elements.allowed.value=settings.allowed.join('\\n');invalidateApplicationAccess();
 document.querySelector('#application-access-context').textContent=result.runtime==='desktop'
  ? 'Desktopová aplikace je pevně dostupná pouze na tomto počítači.'
  : `Privátní síť: ${result.private_network} · tento klient: ${result.client_address}`;
 applicationAccessStatus.textContent=`Aktuální režim: ${applicationAccessLabels[settings.mode]}.`;
}
async function loadApplicationAccess(){
 if(document.body.dataset.runtime==='desktop'){
  fillApplicationAccess({runtime:'desktop',settings:{mode:'localhost',allowed:[]}});
  for(const control of applicationAccessForm.elements)control.disabled=true;
  document.querySelector('#application-access-runtime').textContent='Desktopová aplikace nepovoluje vzdálený přístup; tato volba je pouze informativní.';return;
 }
 applicationAccessStatus.textContent='Načítám aktuální rozsah dostupnosti…';
 try{fillApplicationAccess(await projectRequest('/v1/application-access',{action:'status'}));}
 catch(error){applicationAccessStatus.textContent=error.message;}
}
applicationAccessForm.elements.mode.addEventListener('change',invalidateApplicationAccess);
applicationAccessForm.elements.allowed.addEventListener('input',invalidateApplicationAccess);
applicationAccessForm.addEventListener('submit',async event=>{event.preventDefault();if(document.body.dataset.runtime==='desktop')return;
 const settings={mode:applicationAccessForm.elements.mode.value,allowed:applicationAccessForm.elements.allowed.value.split(/\\r?\\n/).map(value=>value.trim()).filter(Boolean)};
 applicationAccessStatus.textContent='Kontroluji přesný rozsah…';
 try{const result=await projectRequest('/v1/application-access',{action:'preview',settings});applicationAccessPlan=result.plan;
  const disconnect=result.plan.current_client_allowed?'Současný klient zůstane povolen.':'POZOR: současný klient bude po uložení odmítnut.';
  document.querySelector('#application-access-plan').textContent=[`Režim: ${applicationAccessLabels[result.plan.settings.mode]}`,`Povolené adresy: ${result.plan.settings.allowed.join(', ') || '—'}`,`Klient: ${result.plan.client_address}`,disconnect].join('\\n');
  applicationAccessPreview.hidden=false;applicationAccessConfirm.checked=false;applicationAccessSave.disabled=true;applicationAccessStatus.textContent='Náhled je připraven. Zkontrolujte jej a potvrďte.';
 }catch(error){invalidateApplicationAccess();applicationAccessStatus.textContent=error.message;}
});
applicationAccessConfirm.addEventListener('change',()=>{applicationAccessSave.disabled=!applicationAccessPlan||!applicationAccessConfirm.checked;});
applicationAccessSave.addEventListener('click',async()=>{if(!applicationAccessPlan||!applicationAccessConfirm.checked)return;applicationAccessSave.disabled=true;applicationAccessStatus.textContent='Ukládám potvrzenou politiku na tomto uzlu…';
 try{const result=await projectRequest('/v1/application-access',{action:'confirm',plan:applicationAccessPlan,confirmed_disconnect:!applicationAccessPlan.current_client_allowed});fillApplicationAccess(result);applicationAccessStatus.textContent=`Uloženo: ${applicationAccessLabels[result.settings.mode]}.`;}
 catch(error){applicationAccessStatus.textContent=error.message;applicationAccessSave.disabled=false;}
});
let settingsReturn=null;
const settingsTabs=[...document.querySelectorAll('#settings-tabs [role="tab"]')];
function selectSettingsTab(selected){
 for(const tab of settingsTabs){
  const active=tab===selected;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
  const panel=document.getElementById(tab.getAttribute('aria-controls'));if(panel)panel.hidden=!active;
 }
 const administration=document.getElementById('administration');if(administration)administration.hidden=!['settings-users-tab','settings-federation-tab'].includes(selected.id);
 if(selected.id==='settings-cms-tab')loadCmsStatus();
 if(selected.id==='settings-access-tab')loadApplicationAccess();
 if(selected.id==='settings-profile-tab')loadUserProfile();
}
for(const [index,tab] of settingsTabs.entries()){
 tab.addEventListener('click',()=>selectSettingsTab(tab));
 tab.addEventListener('keydown',event=>{
  const visible=settingsTabs.filter(item=>!item.hidden);const current=visible.indexOf(tab);
  const next={ArrowRight:(current+1)%visible.length,ArrowLeft:(current+visible.length-1)%visible.length,Home:0,End:visible.length-1}[event.key];
  if(next===undefined)return;event.preventDefault();visible[next].click();visible[next].focus();
 });
}
function syncSidebarSettingsList(){
 for(const item of document.querySelectorAll('#sidebar-settings-list [data-settings-item]'))item.hidden=document.getElementById(item.dataset.settingsItem).hidden;
}
async function openSettings(settingsTabId='settings-backend-tab'){
 if(!canLeaveWorkspaceEditors())return;
 const activeTab=mainTabs.find(tab=>tab.getAttribute('aria-selected')==='true');
 settingsReturn={project:!!activeProject,tabId:activeTab?.id || 'preview-tab',sourceImport:!sourceImportView.hidden,trash:!projectTrashView.hidden};
 document.querySelector('#project-home').hidden=true;projectCreateView.hidden=true;projectTrashView.hidden=true;projectRepairView.hidden=true;projectView.hidden=true;sourceImportView.hidden=true;notebookImportView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;settingsView.hidden=false;
 selectSidebarTab(document.querySelector('#settings-sidebar-tab'));syncSidebarSettingsList();
 const requested=document.getElementById(settingsTabId),selected=requested&&!requested.hidden?requested:document.querySelector('#settings-backend-tab');selectSettingsTab(selected);
 if(selected.id==='settings-users-tab'||selected.id==='settings-federation-tab'){
  await openAdministration(selected.id==='settings-users-tab'?'users':'federation');return;
 }
 document.querySelector('#settings-backend-status').textContent='Načítám stav lokálního backendu…';
 await loadBackendBinding();
}
async function closeSettings(){
 const destination=settingsReturn;settingsReturn=null;settingsView.hidden=true;userProfileLoaded=false;
 document.dispatchEvent(new Event('settingsclosed'));
 if(destination?.trash){openProjectTrashView();return;}
 if(destination?.sourceImport && activeProject){openSourceImport();return;}
 if(destination?.project && activeProject){
  projectView.hidden=false;
  const tab=document.getElementById(destination.tabId);if(tab)selectMainTab(tab);
  await loadBackendBinding();
 }else{
  document.querySelector('#project-home').hidden=false;selectSidebarTab(document.querySelector('#projects-tab'));
 }
}
for(const button of document.querySelectorAll('#sidebar-settings-list [data-settings-tab]'))button.addEventListener('click',()=>openSettings(button.dataset.settingsTab));
for(const button of document.querySelectorAll('#sidebar-settings-list [data-settings-menu-tab]'))button.addEventListener('click',event=>{event.currentTarget.closest('details').open=false;openSettings(button.dataset.settingsMenuTab);});
document.querySelector('#settings-back').addEventListener('click',closeSettings);
const cmsStatus=document.querySelector('#cms-status');
const cmsEditor=document.querySelector('#cms-editor');
const cmsHostname=document.querySelector('#cms-hostname');
let cmsConfig=null,cmsPreview=null,cmsGenerationAttempt=null,cmsActiveHostname=null,cmsDeploymentPreview=null,cmsDeploymentAttempt=null;
function cmsRows(value,fields){return (value || []).map(item=>fields.map(field=>item[field] || '').join(' | ')).join('\\n');}
function parseCmsRows(value,fields){return value.split(/\\r?\\n/).map(line=>line.trim()).filter(Boolean).map(line=>{
 const parts=line.split('|').map(item=>item.trim()),minimum=fields.at(-1)==='url' && fields.length>2 ? fields.length-1 : fields.length;
 if(parts.length<minimum || parts.length>fields.length)throw new Error('Řádek CMS nemá očekávaný počet částí oddělených znakem |.');
 const item={};for(let index=0;index<fields.length;index++)if(parts[index])item[fields[index]]=parts[index];return item;
});}
function selectedCmsSite(hostname=cmsHostname.value){return cmsConfig?.sites.find(item=>item.hostname===hostname);}
function invalidateCmsPreview(){cmsPreview=null;cmsGenerationAttempt=null;document.querySelector('#cms-preview').hidden=true;document.querySelector('#cms-confirm').checked=false;document.querySelector('#cms-generate-button').disabled=true;}
function saveCmsSiteForm(hostname=cmsHostname.value){const site=selectedCmsSite(hostname);if(!site)return;
 site.title=document.querySelector('#cms-title').value.trim();site.description=document.querySelector('#cms-description').value.trim();
 site.catalog.kind=document.querySelector('#cms-catalog-kind').value;site.catalog.title=document.querySelector('#cms-catalog-title').value.trim();
 site.sections=['profile','cv','timeline'].filter(section=>document.querySelector('#cms-section-'+section).checked);
 if(!site.sections.length)throw new Error('Povolte pro doménu alespoň jednu část.');
 site.contacts=parseCmsRows(document.querySelector('#cms-contacts').value,['label','url']);
 site.links=parseCmsRows(document.querySelector('#cms-links').value,['label','url']);
 site.cv=parseCmsRows(document.querySelector('#cms-cv').value,['period','title','description']);
 site.timeline=parseCmsRows(document.querySelector('#cms-timeline').value,['date','title','description','url']);
}
function renderCmsSite(){const site=selectedCmsSite();if(!site)return;
 for(const section of ['profile','cv','timeline'])document.querySelector('#cms-section-'+section).checked=site.sections.includes(section);
 document.querySelector('#cms-title').value=site.title;document.querySelector('#cms-description').value=site.description;
 document.querySelector('#cms-catalog-kind').value=site.catalog.kind;document.querySelector('#cms-catalog-title').value=site.catalog.title;
 document.querySelector('#cms-contacts').value=cmsRows(site.contacts,['label','url']);
 document.querySelector('#cms-links').value=cmsRows(site.links,['label','url']);
 document.querySelector('#cms-cv').value=cmsRows(site.cv,['period','title','description']);
 document.querySelector('#cms-timeline').value=cmsRows(site.timeline,['date','title','description','url']);cmsActiveHostname=site.hostname;
 document.querySelector('#cms-remove-domain').disabled=cmsConfig.sites.length===1;invalidateCmsPreview();
}
function fillCmsStatus(result){cmsStatus.textContent=result.message;cmsEditor.hidden=!result.compatible;
 const moduleList=document.querySelector('#cms-module-list');moduleList.replaceChildren();for(const item of result.modules || []){const row=document.createElement('p'),name=document.createElement('strong'),detail=document.createElement('span');name.textContent=item.display_name;detail.textContent=` · ${item.module_version} · ${item.compatible ? 'kompatibilní' : item.message}`;row.append(name,detail);moduleList.append(row);}if(!result.modules?.length)moduleList.textContent='Nebyl nalezen žádný modul s validním manifestem.';
 const module=result.modules?.find(item=>item.module_id==='cz.proofofidea.publication-experiment-registry'),enabled=Boolean(module?.enabled);
 document.querySelector('#cms-enable').hidden=!module || enabled || !module.compatible;document.querySelector('#cms-disable').hidden=!enabled;
 if(!result.compatible || !result.config){cmsConfig=null;return;}cmsConfig=structuredClone(result.config);cmsHostname.replaceChildren();
 for(const site of cmsConfig.sites){const option=document.createElement('option');option.value=site.hostname;option.textContent=site.hostname;cmsHostname.append(option);}renderCmsSite();
}
const cmsDeploymentStatus=document.querySelector('#cms-deployment-status');
function fillCmsDeploymentStatus(result){cmsDeploymentStatus.textContent=result.message+(result.state ? ` Stav: ${result.state}.` : '');
 const form=document.querySelector('#cms-deployment-form');if(result.binding){form.elements.account_id.value=result.binding.account_id;form.elements.worker_name.value=result.binding.worker_name;}
 const domains=document.querySelector('#cms-deployment-domains');domains.replaceChildren();for(const item of result.domains || []){const row=document.createElement('p');row.textContent=`${item.hostname} · obsah: ${item.content} · Custom Domain: ${item.custom_domain}`;domains.append(row);}
 document.querySelector('#cms-deployment-preview-button').hidden=!result.configured || !['partial','current','outdated'].includes(result.state);
 cmsDeploymentPreview=null;cmsDeploymentAttempt=null;document.querySelector('#cms-deployment-preview').hidden=true;document.querySelector('#cms-deployment-confirm').checked=false;document.querySelector('#cms-deployment-run').disabled=true;
}
async function loadCmsDeploymentStatus(){try{fillCmsDeploymentStatus(await projectRequest('/v1/publication-cms/deployment/status',{}));}catch(error){cmsDeploymentStatus.textContent=error.message;}}
async function loadCmsStatus(){try{const result=await projectRequest('/v1/publication-cms/status',{});fillCmsStatus(result);if(result.compatible)await loadCmsDeploymentStatus();}catch(error){cmsStatus.textContent=error.message;cmsEditor.hidden=true;}}
async function setCmsEnabled(enabled){cmsStatus.textContent=enabled ? 'Ověřuji verzi manifestu a povoluji modul…' : 'Zakazuji modul…';
 try{fillCmsStatus(await projectRequest('/v1/publication-cms/configure',{module_id:'cz.proofofidea.publication-experiment-registry',enabled}));}
 catch(error){cmsStatus.textContent=error.message;cmsEditor.hidden=true;}}
document.querySelector('#cms-enable').addEventListener('click',()=>setCmsEnabled(true));
document.querySelector('#cms-disable').addEventListener('click',()=>setCmsEnabled(false));
cmsHostname.addEventListener('change',()=>{if(cmsActiveHostname)saveCmsSiteForm(cmsActiveHostname);renderCmsSite();});
for(const id of ['cms-title','cms-description','cms-catalog-kind','cms-catalog-title','cms-contacts','cms-links','cms-cv','cms-timeline'])document.querySelector('#'+id).addEventListener('input',invalidateCmsPreview);
for(const section of ['profile','cv','timeline'])document.querySelector('#cms-section-'+section).addEventListener('change',event=>{
 if(!['profile','cv','timeline'].some(name=>document.querySelector('#cms-section-'+name).checked)){event.currentTarget.checked=true;cmsStatus.textContent='Každá doména musí mít povolenou alespoň jednu část.';return;}invalidateCmsPreview();
});
document.querySelector('#cms-add-domain').addEventListener('click',()=>{if(cmsActiveHostname)saveCmsSiteForm(cmsActiveHostname);
 const input=document.querySelector('#cms-new-hostname'),hostname=input.value.trim().toLowerCase();
 if(!/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(hostname)){cmsStatus.textContent='Zadejte platnou doménu bez protokolu a cesty.';return;}
 if(selectedCmsSite(hostname)){cmsStatus.textContent='Tato doména už v seznamu je.';return;}
 const site={hostname,presentation:'standard',sections:['profile'],title:hostname,description:'',catalog:{kind:'realized',title:'Projekty'},contacts:[],links:[],cv:[],timeline:[]};
 cmsConfig.sites.push(site);const option=document.createElement('option');option.value=hostname;option.textContent=hostname;cmsHostname.append(option);cmsHostname.value=hostname;input.value='';renderCmsSite();cmsStatus.textContent='Doména byla přidána do rozepsané konfigurace. Změnu potvrďte až po kontrole náhledu.';
});
document.querySelector('#cms-remove-domain').addEventListener('click',()=>{if(cmsConfig.sites.length<=1)return;const hostname=cmsHostname.value,index=cmsConfig.sites.findIndex(site=>site.hostname===hostname);if(index<0)return;
 cmsConfig.sites.splice(index,1);cmsHostname.options[index].remove();cmsHostname.selectedIndex=Math.min(index,cmsHostname.options.length-1);renderCmsSite();cmsStatus.textContent='Doména byla odebrána z rozepsané konfigurace. Výstup se změní až po potvrzeném generování.';
});
document.querySelector('#cms-preview-button').addEventListener('click',async event=>{event.currentTarget.disabled=true;
 try{saveCmsSiteForm();const request={config:structuredClone(cmsConfig),hostname:cmsHostname.value};cmsStatus.textContent='Generuji izolovaný náhled…';
  const result=await projectRequest('/v1/publication-cms/preview',request,60000);cmsPreview={request,result};cmsGenerationAttempt=null;
  document.querySelector('#cms-request-preview').textContent=JSON.stringify({module_version:result.module_version,hostname:result.hostname,preview_sha256:result.preview_sha256,config:request.config},null,2);
  document.querySelector('#cms-preview-frame').srcdoc=result.html;document.querySelector('#cms-preview').hidden=false;
  document.querySelector('#cms-confirm').checked=false;document.querySelector('#cms-generate-button').disabled=true;cmsStatus.textContent='Náhled je připraven. Výstup ještě nebyl změněn.';
 }catch(error){cmsStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}});
document.querySelector('#cms-confirm').addEventListener('change',event=>{document.querySelector('#cms-generate-button').disabled=!event.currentTarget.checked || !cmsPreview;});
document.querySelector('#cms-generate-button').addEventListener('click',async event=>{if(!cmsPreview || !document.querySelector('#cms-confirm').checked)return;
 event.currentTarget.disabled=true;cmsStatus.textContent='Generuji potvrzené statické weby…';
 if(!cmsGenerationAttempt)cmsGenerationAttempt={operation_id:crypto.randomUUID(),preview_sha256:cmsPreview.result.preview_sha256,approved:true,config:cmsPreview.request.config};
 try{const result=await projectRequest('/v1/publication-cms/generate',cmsGenerationAttempt,60000);cmsStatus.textContent=`Vygenerováno ${result.generated_hostnames.length} webů · modul ${result.module_version} · ${result.output}.`;cmsGenerationAttempt=null;}
 catch(error){cmsStatus.textContent=error.message;event.currentTarget.disabled=false;}});
document.querySelector('#cms-deployment-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget;
 try{const request=Object.fromEntries(new FormData(form));cmsDeploymentStatus.textContent='Ukládám node-local Cloudflare připojení…';
  const result=await projectRequest('/v1/publication-cms/deployment/configure',request);form.elements.api_token.value='';cmsDeploymentStatus.textContent=result.message;await loadCmsDeploymentStatus();
 }catch(error){cmsDeploymentStatus.textContent=error.message;}});
document.querySelector('#cms-deployment-refresh').addEventListener('click',loadCmsDeploymentStatus);
document.querySelector('#cms-deployment-preview-button').addEventListener('click',async event=>{event.currentTarget.disabled=true;
 try{cmsDeploymentStatus.textContent='Načítám provider stav a připravuji přesný plán…';cmsDeploymentPreview=await projectRequest('/v1/publication-cms/deployment/preview',{});cmsDeploymentAttempt=null;
  document.querySelector('#cms-deployment-request-preview').textContent=JSON.stringify(cmsDeploymentPreview,null,2);document.querySelector('#cms-deployment-preview').hidden=false;
  document.querySelector('#cms-deployment-confirm').checked=false;document.querySelector('#cms-deployment-run').disabled=true;cmsDeploymentStatus.textContent='Plán je připraven. Cloudflare ještě nebyl změněn.';
 }catch(error){cmsDeploymentStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}});
document.querySelector('#cms-deployment-confirm').addEventListener('change',event=>{document.querySelector('#cms-deployment-run').disabled=!event.currentTarget.checked || !cmsDeploymentPreview;});
document.querySelector('#cms-deployment-run').addEventListener('click',async event=>{if(!cmsDeploymentPreview || !document.querySelector('#cms-deployment-confirm').checked)return;
 event.currentTarget.disabled=true;if(!cmsDeploymentAttempt)cmsDeploymentAttempt={operation_id:crypto.randomUUID(),preview_sha256:cmsDeploymentPreview.preview_sha256,approved:true};
 try{cmsDeploymentStatus.textContent='Nahrávám potvrzený release do Cloudflare…';const result=await projectRequest('/v1/publication-cms/deployment/confirm',cmsDeploymentAttempt,120000);cmsDeploymentAttempt=null;cmsDeploymentStatus.textContent=`Deployment ${result.deployment_id} dokončen pro ${result.hostnames.length} domén.`;await loadCmsDeploymentStatus();
 }catch(error){cmsDeploymentStatus.textContent=error.message;}});
const userProfileForm=document.querySelector('#user-profile-form');
const userProfileStatus=document.querySelector('#user-profile-status');
let userProfileLoaded=false;
async function loadUserProfile(){
 if(userProfileLoaded)return;
 userProfileStatus.textContent='Načítám lokální profil…';
 try{const result=await projectRequest('/v1/user-profile',{action:'load'});
  for(const [key,value] of Object.entries(result.profile))userProfileForm.elements[key].value=value;
  userProfileLoaded=true;userProfileStatus.textContent='Profil je načtený z tohoto počítače.';
 }catch(error){userProfileStatus.textContent=error.message;}
}
userProfileForm.addEventListener('submit',async event=>{
 event.preventDefault();const submit=userProfileForm.querySelector('button[type="submit"]');submit.disabled=true;
 const profile=Object.fromEntries(new FormData(userProfileForm));userProfileStatus.textContent='Ukládám lokální profil…';
 try{const result=await projectRequest('/v1/user-profile',{action:'save',profile});
  for(const [key,value] of Object.entries(result.profile))userProfileForm.elements[key].value=value;
  userProfileLoaded=true;userProfileStatus.textContent='Profil byl uložen pouze na tomto počítači.';
 }catch(error){userProfileStatus.textContent=error.message;
 }finally{submit.disabled=false;}
});
function clearPreview(){
 ++previewRequest;selectedArtifact=null;previewContent.replaceChildren();
 refreshCurrentFileSource();
 for(const button of sidebarArtifacts.querySelectorAll('button'))button.setAttribute('aria-current','false');
 document.querySelector('#preview-title').textContent='';
 document.querySelector('#preview-metadata').replaceChildren();
 document.querySelector('#preview-details').hidden=true;
 document.querySelector('#pdf-controls').hidden=true;
 previewStatus.textContent='Vyberte podklad ze seznamu.';
}
function addConflictLineClasses(element,lineClasses,index){for(const name of lineClasses?.get(index)||[])element.classList.add(name);}
function renderMarkdown(text,target=previewContent,lineClasses=null){
 // Deliberately small Markdown subset; all source text uses textContent, never HTML.
 let fence=null,code=null,list=null,lineIndex=0;
 for(const line of text.split('\\n')){
  const marker=line.match(/^\\s*(`{3,}|~{3,})(.*)$/);
  if(marker && (!fence || (marker[1][0]===fence[0] && marker[1].length>=fence.length && !marker[2].trim()))){
   list=null;
   if(fence){fence=null;code=null;}else{fence=marker[1];code=document.createElement('pre');addConflictLineClasses(code,lineClasses,lineIndex);target.append(code);}
   lineIndex++;
   continue;
  }
  if(fence){code.textContent+=line+'\\n';addConflictLineClasses(code,lineClasses,lineIndex);lineIndex++;continue;}
  const heading=line.match(/^(#{1,6})\\s+(.*)$/);
  const bullet=line.match(/^\\s*[-*+]\\s+(.*)$/);
  if(bullet){if(!list){list=document.createElement('ul');target.append(list);}
   const item=document.createElement('li');item.textContent=bullet[1];addConflictLineClasses(item,lineClasses,lineIndex);list.append(item);lineIndex++;continue;}
  list=null;const element=document.createElement(heading?'h'+heading[1].length:'p');
  element.textContent=heading?heading[2]:line;addConflictLineClasses(element,lineClasses,lineIndex);target.append(element);lineIndex++;
 }
}
const projectConflicts=document.querySelector('#project-conflicts');
const projectConflictGrid=document.querySelector('.project-overview-grid');
const projectConflictHeading=document.querySelector('.project-overview-heading');
const projectConflictOpen=document.querySelector('#project-conflicts-open');
const projectConflictStatus=document.querySelector('#project-conflicts-status');
const projectConflictSelect=document.querySelector('#project-conflicts-select');
const projectConflictWorkspace=document.querySelector('#project-conflicts-workspace');
const projectConflictFiles=document.querySelector('#project-conflicts-files');
const projectConflictDialog=document.querySelector('#project-conflicts-dialog');
const projectConflictResult=document.querySelector('#project-conflicts-result');
const projectConflictConfirm=document.querySelector('#project-conflicts-confirm');
const projectConflictPublish=document.querySelector('#project-conflicts-publish');
let projectConflictRows=[],projectConflictPreview=null,projectConflictDrafts=new Map(),projectConflictOperation=null,projectConflictRequest=0,projectConflictPath=null;
function closeConflictDialog(){if(!projectConflictDialog.open)return;if(projectConflictDialog.close)projectConflictDialog.close();else projectConflictDialog.removeAttribute('open');}
function resetProjectConflicts(){
 ++projectConflictRequest;projectConflictRows=[];projectConflictPreview=null;projectConflictDrafts=new Map();projectConflictOperation=null;projectConflictPath=null;closeConflictDialog();
 projectConflictSelect.replaceChildren();projectConflictFiles.replaceChildren();projectConflictWorkspace.hidden=true;projectConflicts.hidden=true;
 projectConflictGrid.hidden=false;projectConflictHeading.hidden=false;projectConflictOpen.hidden=true;projectConflictConfirm.checked=false;projectConflictPublish.disabled=true;
}
function conflictDraftChanged(){return [...projectConflictDrafts.values()].some(item=>item.choice && item.choice!=='auto');}
function closeProjectConflicts(){
 if(conflictDraftChanged()&&!window.confirm('Zahodit rozepsané řešení konfliktu? Projekt zatím nebyl změněn.'))return;
 closeConflictDialog();projectConflicts.hidden=true;projectConflictGrid.hidden=false;projectConflictHeading.hidden=false;projectConflictPreview=null;projectConflictDrafts=new Map();projectConflictOperation=null;projectConflictPath=null;
}
async function loadProjectConflictSummary(){
 if(!activeProject)return;const project=activeProject,request=++projectConflictRequest;projectConflictOpen.hidden=true;
 try{const result=await projectRequest('/v1/projects/conflicts/list',{project_id:project.id,expected_head:project.head});
  if(request!==projectConflictRequest||activeProject!==project)return;
  projectConflictRows=result.conflicts||[];projectConflictOpen.hidden=!projectConflictRows.length;
  projectConflictOpen.textContent=projectConflictRows.length===1?'Vyřešit konflikt':'Vyřešit konflikty ('+projectConflictRows.length+')';
 }catch(error){if(request===projectConflictRequest)projectConflictOpen.hidden=true;}
}
async function openProjectConflicts(){
 if(!activeProject)return;projectConflictGrid.hidden=true;projectConflictHeading.hidden=true;projectConflicts.hidden=false;projectConflictWorkspace.hidden=true;
 projectConflictStatus.textContent='Načítám zachované protější historie…';projectConflictSelect.replaceChildren();
 const project=activeProject,request=++projectConflictRequest;
 try{const result=await projectRequest('/v1/projects/conflicts/list',{project_id:project.id,expected_head:project.head});
  if(request!==projectConflictRequest||activeProject!==project)return;
  projectConflictRows=result.conflicts||[];
  for(const row of projectConflictRows){const option=document.createElement('option');option.value=row.ref;option.textContent=`${row.branch} · ${row.head.slice(0,10)} · ${row.author} · ${row.subject}`;projectConflictSelect.append(option);}
  projectConflictStatus.textContent=projectConflictRows.length?'Načítám seznam konfliktních souborů…':'Projekt nemá nevyřešenou divergenci.';
  if(projectConflictRows.length)await loadConflictPreview();
 }catch(error){if(request===projectConflictRequest)projectConflictStatus.textContent=error.message;}
}
function selectedConflictFile(){return projectConflictPreview?.files.find(item=>item.path===projectConflictPath);}
function changedLineIndexes(left,right){
 const a=left.split('\\n'),b=right.split('\\n'),leftChanged=new Set(),rightChanged=new Set();
 if(left===right)return {left:leftChanged,right:rightChanged};
 const markMiddle=()=>{let start=0,endA=a.length-1,endB=b.length-1;while(start<=endA&&start<=endB&&a[start]===b[start])start++;while(endA>=start&&endB>=start&&a[endA]===b[endB]){endA--;endB--;}for(let i=start;i<=endA;i++)leftChanged.add(i);for(let i=start;i<=endB;i++)rightChanged.add(i);};
 if((a.length+1)*(b.length+1)>250000){markMiddle();return {left:leftChanged,right:rightChanged};}
 const table=Array.from({length:a.length+1},()=>new Uint32Array(b.length+1));
 for(let i=a.length-1;i>=0;i--)for(let j=b.length-1;j>=0;j--)table[i][j]=a[i]===b[j]?table[i+1][j+1]+1:Math.max(table[i+1][j],table[i][j+1]);
 let i=0,j=0;while(i<a.length&&j<b.length){if(a[i]===b[j]){i++;j++;}else if(table[i+1][j]>=table[i][j+1])leftChanged.add(i++);else rightChanged.add(j++);}while(i<a.length)leftChanged.add(i++);while(j<b.length)rightChanged.add(j++);
 return {left:leftChanged,right:rightChanged};
}
function conflictDiffState(item,draft){
 const resultExists=!draft?.deleted,result=resultExists&&draft?.text!==null?draft?.text:null;
 const local=item.ours_exists&&item.ours!==null&&result!==null?changedLineIndexes(item.ours,result):null;
 const remote=item.theirs_exists&&item.theirs!==null&&result!==null?changedLineIndexes(item.theirs,result):null;
 return {resultExists,result,local,remote};
}
function resultLineClasses(state){
 const classes=new Map(),count=state.result===null?0:state.result.split('\\n').length;
 for(let index=0;index<count;index++){const local=state.local?.right.has(index),remote=state.remote?.right.has(index);if(local||remote)classes.set(index,[local&&remote?'diff-both':local?'diff-local':'diff-remote']);}
 return classes;
}
function sideLineClasses(diff,name){const classes=new Map();if(diff)for(const index of diff.left)classes.set(index,[name]);return classes;}
function renderConflictLines(target,value,exists,lineClasses){
 target.replaceChildren();if(!exists||value===null){const note=document.createElement('p');note.className='conflict-missing';note.textContent=exists?'Binární nebo nepodporovaný obsah · použijte volbu celého souboru.':'Soubor v této verzi neexistuje.';target.append(note);return;}
 const pre=document.createElement('pre');for(const [index,line] of value.split('\\n').entries()){const row=document.createElement('span');row.className='conflict-line';addConflictLineClasses(row,lineClasses,index);row.textContent=line||' ';pre.append(row);}target.append(pre);
}
function conflictDifferenceSummary(diff,unavailable){return unavailable?'Porovnání není dostupné':`${diff?.left.size||0} odlišných řádků`;}
function renderConflictDiffs(){
 const item=selectedConflictFile();if(!item)return;const draft=projectConflictDrafts.get(item.path),state=conflictDiffState(item,draft);
 const localTarget=document.querySelector('[data-conflict-diff="ours"]'),remoteTarget=document.querySelector('[data-conflict-diff="theirs"]');
 renderConflictLines(localTarget,item.ours,item.ours_exists,sideLineClasses(state.local,'diff-local'));renderConflictLines(remoteTarget,item.theirs,item.theirs_exists,sideLineClasses(state.remote,'diff-remote'));
 document.querySelector('#project-conflicts-local-summary').textContent=conflictDifferenceSummary(state.local,!item.ours_exists||item.ours===null||state.result===null);
 document.querySelector('#project-conflicts-remote-summary').textContent=conflictDifferenceSummary(state.remote,!item.theirs_exists||item.theirs===null||state.result===null);
 const resultClasses=resultLineClasses(state),highlight=document.querySelector('#project-conflicts-result-highlight');highlight.replaceChildren();
 if(state.result!==null)for(const [index,line] of state.result.split('\\n').entries()){const row=document.createElement('span');row.className='conflict-line';addConflictLineClasses(row,resultClasses,index);row.textContent=line||' ';highlight.append(row);}
 const localCount=state.local?.right.size||0,remoteCount=state.remote?.right.size||0;document.querySelector('#project-conflicts-result-summary').textContent=!state.resultExists?'Výsledný soubor bude odstraněn':state.result===null?'Binární obsah · volba celého souboru':`${localCount} vůči lokální · ${remoteCount} vůči vzdálené`;
 highlight.scrollTop=projectConflictResult.scrollTop;highlight.scrollLeft=projectConflictResult.scrollLeft;
}
function renderConflictPreviews(){
 const item=selectedConflictFile();if(!item)return;const draft=projectConflictDrafts.get(item.path),state=conflictDiffState(item,draft),resultClasses=resultLineClasses(state);
 for(const target of document.querySelectorAll('[data-conflict-preview]')){
  target.replaceChildren();const key=target.dataset.conflictPreview,value=key==='result'?(draft?.deleted?null:draft?.text):item[key];
  const exists=key==='result'?!draft?.deleted:item[key+'_exists'];
  if(!exists||value===null){const note=document.createElement('p');note.className='conflict-missing';note.textContent=exists?'Binární nebo nepodporovaný obsah · použijte volbu celého souboru.':'Soubor v této verzi neexistuje.';target.append(note);}
  else{const classes=key==='ours'?sideLineClasses(state.local,'diff-local'):key==='theirs'?sideLineClasses(state.remote,'diff-remote'):resultClasses;if(item.path.toLowerCase().endsWith('.md'))renderMarkdown(value,target,classes);else renderConflictLines(target,value,exists,classes);}
 }
}
function renderConflictFileList(){
 projectConflictFiles.replaceChildren();if(!projectConflictPreview)return;let conflicts=0,automatic=0;
 for(const item of projectConflictPreview.files){
  const draft=projectConflictDrafts.get(item.path),state=item.conflict?(draft?.choice?'resolved':'unresolved'):draft?.choice==='auto'?'automatic':'resolved';if(item.conflict)conflicts++;else automatic++;
  const row=document.createElement('li'),button=document.createElement('button'),path=document.createElement('span'),status=document.createElement('span');button.type='button';path.className='conflict-file-path';path.textContent=item.path;status.className='conflict-file-status '+state;status.textContent=state==='automatic'?'Automaticky':state==='resolved'?'Vyřešeno':'Nevyřešeno';button.append(path,status);button.addEventListener('click',()=>openConflictDialog(item.path));row.append(button);projectConflictFiles.append(row);
 }
 document.querySelector('#project-conflicts-files-summary').textContent=`${conflicts} konfliktních · ${automatic} automaticky sloučených souborů. Kliknutím otevřete porovnání.`;
}
function openConflictDialog(path){
 if(!projectConflictPreview?.files.some(item=>item.path===path))return;projectConflictPath=path;document.querySelector('#project-conflicts-dialog-title').textContent=path;renderConflictFile();
 if(projectConflictDialog.showModal)projectConflictDialog.showModal();else projectConflictDialog.setAttribute('open','');
}
function updateConflictCompletion(){
 if(!projectConflictPreview)return;let unresolved=0;
 for(const item of projectConflictPreview.files){const draft=projectConflictDrafts.get(item.path);if(item.conflict&&!draft?.choice)unresolved++;}
 document.querySelector('#project-conflicts-unresolved').textContent=unresolved?`Zbývá vyřešit ${unresolved} konfliktních souborů.`:'Všechny konfliktní soubory mají explicitní výsledek.';
 projectConflictConfirm.disabled=Boolean(unresolved)||activeProject?.readOnly;projectConflictPublish.disabled=Boolean(unresolved)||!projectConflictConfirm.checked||activeProject?.readOnly;
 renderConflictFileList();
}
function renderConflictFile(){
 const item=selectedConflictFile();if(!item)return;const draft=projectConflictDrafts.get(item.path);
 projectConflictResult.value=draft?.deleted?'':draft?.text??'';projectConflictResult.readOnly=!item.editable;projectConflictResult.placeholder=draft?.deleted?'Výsledný soubor bude odstraněn.':!item.editable?'Binární nebo nepodporovaný obsah · použijte volbu celého souboru.':'';
 document.querySelector('#project-conflicts-use-both').disabled=!item.editable||item.ours===null||item.theirs===null;
 renderConflictDiffs();renderConflictPreviews();updateConflictCompletion();
}
async function loadConflictPreview(){
 if(!activeProject||!projectConflictSelect.value)return;const project=activeProject,request=++projectConflictRequest;
 closeConflictDialog();projectConflictPath=null;projectConflictStatus.textContent='Sestavuji izolované 3-way porovnání…';projectConflictWorkspace.hidden=true;
 try{const result=await projectRequest('/v1/projects/conflicts/preview',{project_id:project.id,expected_head:project.head,incoming_ref:projectConflictSelect.value},120000);
  if(request!==projectConflictRequest||activeProject!==project)return;
  projectConflictPreview=result;projectConflictDrafts=new Map();projectConflictOperation=null;
  for(const item of result.files)projectConflictDrafts.set(item.path,{choice:item.conflict?null:'auto',text:item.result,deleted:!item.result_exists});
  projectConflictConfirm.checked=false;projectConflictWorkspace.hidden=false;updateConflictCompletion();projectConflictStatus.textContent='Vyberte soubor ze seznamu. Návrh je pouze v prohlížeči; Git ani projekt nebyly změněny.';
 }catch(error){if(request===projectConflictRequest)projectConflictStatus.textContent=error.message;}
}
function chooseConflict(choice){
 const item=selectedConflictFile();if(!item)return;const draft=projectConflictDrafts.get(item.path);draft.choice=choice;draft.deleted=choice==='delete';
 if(choice==='ours'){draft.text=item.ours;draft.deleted=!item.ours_exists;}else if(choice==='theirs'){draft.text=item.theirs;draft.deleted=!item.theirs_exists;}else if(choice==='both'){draft.text=(item.ours||'')+((item.ours&&!item.ours.endsWith('\\n'))?'\\n':'')+(item.theirs||'');draft.deleted=false;}else if(choice==='delete')draft.text='';
 projectConflictOperation=null;projectConflictConfirm.checked=false;renderConflictFile();
}
projectConflictOpen.addEventListener('click',openProjectConflicts);document.querySelector('#project-conflicts-back').addEventListener('click',closeProjectConflicts);projectConflictSelect.addEventListener('change',loadConflictPreview);document.querySelector('#project-conflicts-dialog-close').addEventListener('click',closeConflictDialog);
document.querySelector('#project-conflicts-use-ours').addEventListener('click',()=>chooseConflict('ours'));document.querySelector('#project-conflicts-use-theirs').addEventListener('click',()=>chooseConflict('theirs'));document.querySelector('#project-conflicts-use-both').addEventListener('click',()=>chooseConflict('both'));document.querySelector('#project-conflicts-delete').addEventListener('click',()=>chooseConflict('delete'));
projectConflictResult.addEventListener('input',()=>{const item=selectedConflictFile();if(!item||!item.editable)return;const draft=projectConflictDrafts.get(item.path);draft.choice='manual';draft.text=projectConflictResult.value;draft.deleted=false;projectConflictOperation=null;projectConflictConfirm.checked=false;renderConflictDiffs();renderConflictPreviews();updateConflictCompletion();});
projectConflictResult.addEventListener('scroll',()=>{const highlight=document.querySelector('#project-conflicts-result-highlight');highlight.scrollTop=projectConflictResult.scrollTop;highlight.scrollLeft=projectConflictResult.scrollLeft;});
for(const [buttonId,panelId,otherId] of [['project-conflicts-raw','project-conflicts-raw-panel','project-conflicts-rendered-panel'],['project-conflicts-rendered','project-conflicts-rendered-panel','project-conflicts-raw-panel']])document.getElementById(buttonId).addEventListener('click',event=>{document.getElementById(panelId).hidden=false;document.getElementById(otherId).hidden=true;for(const button of event.currentTarget.parentElement.querySelectorAll('button')){const active=button===event.currentTarget;button.setAttribute('aria-selected',String(active));button.classList.toggle('secondary-button',!active);}renderConflictPreviews();});
projectConflictConfirm.addEventListener('change',()=>updateConflictCompletion());
projectConflictPublish.addEventListener('click',async()=>{
 if(!activeProject||!projectConflictPreview||!projectConflictConfirm.checked)return;projectConflictPublish.disabled=true;projectConflictStatus.textContent='Validuji celý projekt a vytvářím potvrzený merge commit…';
 if(!projectConflictOperation)projectConflictOperation=crypto.randomUUID();
 const resolution={project_id:projectConflictPreview.project_id,expected_head:projectConflictPreview.expected_head,incoming_ref:projectConflictPreview.incoming_ref,incoming_head:projectConflictPreview.incoming_head,base:projectConflictPreview.base,preview_sha256:projectConflictPreview.preview_sha256,resolutions:projectConflictPreview.files.map(item=>{const draft=projectConflictDrafts.get(item.path);const row={path:item.path,choice:draft.choice};if(draft.choice==='manual')row.text=draft.text;return row;})};
 try{await projectRequest('/v1/projects/conflicts/confirm',{operation_id:projectConflictOperation,resolution},120000);projectConflictOperation=null;await openRegisteredProject(activeProject.id);}
 catch(error){projectConflictStatus.textContent=error.message;projectConflictPublish.disabled=false;}
});
async function openPreview(id,page=1){
 if(!activeProject)return;
 const project=activeProject;
 clearPreview();selectedArtifact=id;refreshCurrentFileSource();
 for(const button of sidebarArtifacts.querySelectorAll('button'))button.setAttribute('aria-current',String(button.dataset.id===id));
 const request=previewRequest;
 selectMainTab(document.querySelector('#preview-tab'));previewStatus.textContent='Načítám náhled…';
 try{
  const result=await projectRequest('/v1/artifacts/preview',{
   project_id:project.id,artifact_id:id,expected_head:project.head,page});
  if(request!==previewRequest || activeProject!==project)return;
  document.querySelector('#preview-title').textContent=result.metadata.title;
  const metadata=document.querySelector('#preview-metadata');
  for(const [key,value] of Object.entries(result.metadata)){
   const entries=key==='import' ? [
    ['imported_at',value.imported_at],['imported_by',value.imported_by],['content_sha256',value.content_sha256],
    ['source_author',value.source_author],['source_created_at',value.source_created_at],
    ['source_revision',value.source_revision],['importer_name',value.importer?.name],
    ['importer_version',value.importer?.version]
   ].filter(([,item])=>item!==undefined) : [[key,value]];
   for(const [entryKey,entryValue] of entries){
    const term=document.createElement('dt');term.textContent=({title:'Název',description:'Popis',tags:'Štítky',id:'Identifikátor',kind:'Typ',file:'Soubor',created_at:'Vytvořeno v projektu',author_id:'Autor',privacy:'Soukromí',provenance:'Původ',schema_version:'Verze formátu',relations:'Vztahy',source_url:'Odkaz na zdroj',imported_at:'Importováno do projektu',imported_by:'Importoval',content_sha256:'SHA-256 původních bajtů',source_author:'Autor zdroje',source_created_at:'Doložený čas vzniku zdroje',source_revision:'Revize zdroje',importer_name:'Importér',importer_version:'Verze importéru'})[entryKey] || entryKey;
    const detail=document.createElement('dd');detail.textContent=Array.isArray(entryValue) && entryValue.every(item=>typeof item==='string') ? entryValue.join(', ') : typeof entryValue==='string'?entryValue:JSON.stringify(entryValue);
    const labels={privacy:{public:'Veřejné',project:'V rámci projektu',confidential:'Důvěrné','local-only':'Jen na tomto počítači'},
     provenance:{user:'Vytvořeno uživatelem',external:'Převzato ze zdroje','llm-generated':'Vytvořeno AI','llm-transformed':'Upraveno AI',snapshot:'Snímek stavu'},
     kind:{document:'Dokument',source:'Zdroj'}};
    if(labels[entryKey] && Object.hasOwn(labels[entryKey],entryValue))detail.textContent=labels[entryKey][entryValue];
    metadata.append(term,detail);
   }
  }
  document.querySelector('#preview-details').hidden=false;
  if(result.format==='markdown')renderMarkdown(result.text);
  else if(result.format==='json'){
   const pre=document.createElement('pre');pre.textContent=result.text;previewContent.append(pre);
  }
  else if(result.format==='image' || result.format==='pdf'){
   const image=document.createElement('img');image.alt=result.metadata.title;
   image.addEventListener('error',()=>{if(request===previewRequest)previewStatus.textContent='Obrázek se nepodařilo zobrazit.';});
   image.src=result.image;previewContent.append(image);
  }
  // Keep page selection available after an invalid/missing PDF page.
  const isPdf=result.format==='pdf' || result.metadata.file?.toLowerCase().endsWith('.pdf');
  document.querySelector('#pdf-controls').hidden=!isPdf;
  document.querySelector('#pdf-page').value=page;
  previewStatus.textContent=result.message || (result.format==='pdf'?'Stránka '+page+' · uložená verze':'Uložená verze · pouze pro čtení');
 }catch(error){if(request===previewRequest){previewStatus.textContent=error.message;}}
}
const historyStatus=document.querySelector('#history-status');
const historyOlder=document.querySelector('#history-older');
const historyNewer=document.querySelector('#history-newer');
const historyCompare=document.querySelector('#history-compare');
let historyVersions=[],historyRequest=0;
function clearHistoryResult(){
 for(const id of ['history-body','history-metadata','history-diff','history-info'])document.getElementById(id).textContent='';
}
function closeHistory(){
 ++historyRequest;historyView.hidden=true;
 if(activeProject)projectView.hidden=false;
 else{document.querySelector('#project-home').hidden=false;selectSidebarTab(document.querySelector('#projects-tab'));}
}
async function openHistory(){
 if(!activeProject||!selectedArtifact)return;
 const project=activeProject,artifactId=selectedArtifact,request=++historyRequest;
 historyVersions=[];historyOlder.replaceChildren();historyNewer.replaceChildren();clearHistoryResult();
 document.querySelector('#history-title').textContent=`Historie · ${document.querySelector('#preview-title').textContent||artifactId}`;
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;projectView.hidden=true;historyView.hidden=false;
 selectSidebarTab(document.querySelector('#artifacts-tab'));
 historyCompare.disabled=true;historyStatus.textContent='Načítám historii…';
 try{
  const result=await projectRequest('/v1/artifacts/history/list',{project_id:project.id,artifact_id:artifactId,expected_head:project.head});
  if(request!==historyRequest||activeProject!==project||selectedArtifact!==artifactId)return;
  historyVersions=result.versions;
  for(const [index,row] of historyVersions.entries()){
   const summary=(row.message.split(/\\r?\\n/,1)[0]||'(bez zprávy)').slice(0,100);
   const suffix=!row.available?' · neplatná/nepodporovaná verze':row.deleted?' · smazáno':'';
   const label=`${row.commit_id.slice(0,10)} · ${row.date} · ${row.author} · ${summary}${suffix}`;
   for(const select of [historyOlder,historyNewer]){const option=document.createElement('option');option.value=String(index);option.textContent=label;option.disabled=!row.available;select.append(option);}
  }
  historyNewer.value='0';historyOlder.value=String(Math.min(1,historyVersions.length-1));
  historyCompare.disabled=!historyVersions.some(row=>row.available);
  historyStatus.textContent=(historyVersions.length?'Vyberte verze a zobrazte porovnání.':'Dokument nemá dostupnou historii.')+(result.truncated?' Zobrazeno nejnovějších 100 záznamů.':'');
 }catch(error){if(request===historyRequest){historyStatus.textContent=error.message;}}
}
for(const select of [historyOlder,historyNewer])select.addEventListener('change',clearHistoryResult);
historyCompare.addEventListener('click',async()=>{
 const project=activeProject,artifactId=selectedArtifact;
 const older=historyVersions[Number(historyOlder.value)],newer=historyVersions[Number(historyNewer.value)];
 if(!project||!artifactId||!older?.available||!newer?.available)return;
 const request=++historyRequest;clearHistoryResult();historyCompare.disabled=true;historyStatus.textContent='Načítám uložené verze…';
 try{
  const result=await projectRequest('/v1/artifacts/history/compare',{project_id:project.id,artifact_id:artifactId,expected_head:project.head,older:older.commit_id,newer:newer.commit_id});
  if(request!==historyRequest||activeProject!==project||selectedArtifact!==artifactId)return;
  document.querySelector('#history-body').textContent=result.after?result.after.body:'Dokument v této verzi neexistuje.';
  document.querySelector('#history-metadata').textContent=result.after?JSON.stringify(result.after.metadata,null,2):'';
  document.querySelector('#history-diff').textContent=result.diff||'Vybrané verze nemají rozdíly v souborech dokumentu.';
  document.querySelector('#history-info').textContent=`${newer.commit_id}\n${newer.date}\n${newer.author} <${newer.email}>\n\n${newer.message}`;
  historyStatus.textContent='Uložená verze · pouze pro čtení.';
 }catch(error){if(request===historyRequest)historyStatus.textContent=error.message;}
 finally{if(request===historyRequest)historyCompare.disabled=false;}
});
document.querySelector('#history-close').addEventListener('click',closeHistory);
document.querySelector('#pdf-show').addEventListener('click',()=>{
 const input=document.querySelector('#pdf-page');
 if(input.reportValidity() && selectedArtifact)openPreview(selectedArtifact,Number(input.value));
});
const draft=document.querySelector('#chat-draft');
const chatStatus=document.querySelector('#chat-backend-status');
const settingsBackendStatus=document.querySelector('#settings-backend-status');
const settingsSearchStatus=document.querySelector('#settings-search-status');
const settingsGoogleDriveStatus=document.querySelector('#settings-google-drive-status');
const googleDriveDesktop=document.body.dataset.runtime==='desktop';
document.querySelector('#google-drive-client-guide').textContent=googleDriveDesktop ?
 'V Google Cloud zapněte Google Drive API a vytvořte OAuth klienta typu Desktop app. Nepoužívejte klienta typu Web application.' :
 'V Google Cloud zapněte Google Drive API a vytvořte OAuth klienta typu Web application.';
document.querySelector('#google-drive-callback-guide').textContent=googleDriveDesktop ?
 'Desktop používá automatickou loopback adresu; v klientovi ji ručně neregistrujte:' :
 'Do Authorized redirect URIs vložte přesně:';
document.querySelector('#google-drive-callback').textContent=googleDriveDesktop ?
 location.origin+'/' : location.origin+'/oauth/google-drive/callback';
const settingsExternalStatus=document.querySelector('#settings-external-status');
const backendMetricsStatus=document.querySelector('#backend-metrics-status');
const backendMetricsIndicator=document.querySelector('#backend-metrics-indicator');
const resourceOpenAIDetail=document.querySelector('#resource-openai-detail');
const localProviderAvailability=document.querySelector('#local-provider-availability');
const localProviderIndicator=document.querySelector('#local-provider-indicator');
const resourceMonitorDialog=document.querySelector('#resource-monitor-dialog');
for(const name of ['CPU','GPU','RAM','VRAM','DISK','NET']){
 const row=document.createElement('div');row.className='resource-detail-row';
 const label=document.createElement('strong');label.textContent=name;
 const progress=document.createElement('progress');progress.max=100;progress.value=0;
 progress.setAttribute('aria-label',`${name} – placeholder bez telemetrie`);
 const value=document.createElement('output');value.textContent='bez telemetrie';
 row.append(label,progress,value);document.querySelector('#system-monitor-detail').append(row);
}
document.querySelector('#resource-monitor-open').addEventListener('click',()=>resourceMonitorDialog.showModal());
document.querySelector('#resource-monitor-close').addEventListener('click',()=>resourceMonitorDialog.close());
resourceMonitorDialog.addEventListener('click',event=>{
 const bounds=resourceMonitorDialog.getBoundingClientRect();
 if(event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom)resourceMonitorDialog.close();
});
function renderLocalProviderAvailability(binding){
 localProviderIndicator.textContent=binding ? `Lokální AI · ${binding.model} · neověřeno` : 'Lokální AI · nenastaveno';
 localProviderAvailability.textContent=binding ?
  `Nakonfigurováno: ${binding.model}. Dostupnost zatím nebyla ověřena.` :
  'Lokální provider není nakonfigurován; dostupnost není ověřena.';
}
const mainPanelContent=document.querySelector('#main-panel-content');
const chatMessages=document.querySelector('#chat-messages');
const chatForm=document.querySelector('#chat-backend-form');
const searchForm=document.querySelector('#search-backend-form');
const chatOperationStatus=document.querySelector('#chat-operation-status');
const searchRecovery=document.querySelector('#search-recovery');
const chatStream=document.querySelector('#chat-stream');
const chatStreamStatus=document.querySelector('#chat-stream-status');
const chatStreamProgressText=document.querySelector('#chat-stream-progress-text');
const chatRunUsage=document.querySelector('#chat-run-usage');
const ollamaStreamingToggle=document.querySelector('#ollama-streaming-enabled');
const ollamaStreamingState=document.querySelector('#ollama-streaming-state');
const responseLanguageState=document.querySelector('#response-language-state');
let activeThread=null,knownThreads=[],pendingThreadDeletion=null,chatBinding=null,searchBinding=null,externalBinding=null,ollamaStreaming=false,ollamaStreamingSupported=false,externalStreaming=false,pendingChatRequest=null,pendingExternalPreview=null,pendingExternalProposal=null,pendingSearchPreview=null,pendingPublicSourcePreview=null,searchRecoveryBinding=null;
let activeTaskThreadId=null,taskOutcomes=[],chatSelectionRevision=0;
const presentationApprovalAttempts=new Map();
let streamScrollPending=false,streamAutoFollow=false,chatProgressSequence=0,chatProgressActive=false;
function chatScrollOwner(){
 return getComputedStyle(mainPanelContent).overflowY==='visible' ?
  document.scrollingElement : mainPanelContent;
}
function chatScrollNearBottom(){const owner=chatScrollOwner();
 return owner.scrollHeight-owner.scrollTop-owner.clientHeight<=80;}
function updateChatAutoFollow(){
 if(!chatStream.hidden || !chatStreamStatus.hidden)streamAutoFollow=chatScrollNearBottom();
}
mainPanelContent.addEventListener('scroll',updateChatAutoFollow,{passive:true});
window.addEventListener('scroll',updateChatAutoFollow,{passive:true});
function keepChatStreamVisible(){
 if(!streamAutoFollow || streamScrollPending)return;streamScrollPending=true;
 requestAnimationFrame(()=>{streamScrollPending=false;if(!streamAutoFollow)return;
  const owner=chatScrollOwner();owner.scrollTop=owner.scrollHeight;});
}
function finishChatAutoFollow(){
 const follow=streamAutoFollow;streamAutoFollow=false;
 if(follow)requestAnimationFrame(()=>{const owner=chatScrollOwner();owner.scrollTop=owner.scrollHeight;});
}
function startChatProgress(initialState){
 const sequence=++chatProgressSequence;let state=initialState,started=Date.now();
 chatProgressActive=true;streamAutoFollow=true;chatStreamStatus.hidden=false;
 chatMessages.setAttribute('aria-busy','true');
 chatMessages.append(chatStreamStatus);
 const render=()=>{const seconds=Math.floor((Date.now()-started)/1000);
  chatStreamProgressText.textContent=`${state} · ${seconds} s`;keepChatStreamVisible();};
 const timer=setInterval(render,1000);render();
 return {set(nextState){if(sequence!==chatProgressSequence)return;state=nextState;render();},stop(){clearInterval(timer);
  if(sequence!==chatProgressSequence)return;chatProgressActive=false;
  chatMessages.removeAttribute('aria-busy');chatStreamStatus.hidden=true;
  chatStreamProgressText.textContent='';chatStreamStatus.remove();}};
}
function appendChatOperationNotice(error){
 if(error?.status!==408)return;
 const notice=document.createElement('div');notice.className='chat-message assistant';
 notice.textContent=error.message;const detail=document.createElement('small');
 detail.textContent='Výsledek operace není z pohledu UI potvrzený.';
 notice.append(detail);chatMessages.append(notice);
}
async function withChatProgress(initialState,action){
 const progress=startChatProgress(initialState);
 try{await waitForVisiblePaint();return await action(progress);}
 catch(error){appendChatOperationNotice(error);throw error;}
 finally{progress.stop();}
}
function waitForVisiblePaint(){
 return new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
}
function threadWritable(){return !activeThread || (activeThread.status==='active' &&
 (activeThread.project_id===null || activeThread.project_id===activeProject?.id));}
async function streamRequest(path,request,onDelta,onStatus=()=>{}){
 const response=await fetch(path,{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
 if(!response.ok)throw Object.assign(new Error('Streamovaný požadavek byl odmítnut.'),{status:response.status});
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result=null;
 while(true){const part=await reader.read();buffer+=decoder.decode(part.value || new Uint8Array(),{stream:!part.done});
  let newline;while((newline=buffer.indexOf('\\n'))>=0){const line=buffer.slice(0,newline);buffer=buffer.slice(newline+1);
   if(!line)continue;const event=JSON.parse(line);
   if(event.type==='delta' && typeof event.delta==='string')onDelta(event.delta);
   else if(event.type==='status' && typeof event.status==='string')onStatus(event.status);
   else if(event.type==='result')result=event.result;
   else if(event.type==='error')throw Object.assign(new Error(event.error),{status:event.status});
   else throw new Error('Neplatná událost streamu.');}
  if(part.done)break;}
 if(buffer || !result)throw new Error('Stream skončil bez finální odpovědi.');return result;
}
async function externalStreamRequest(request,onDelta){
 return streamRequest('/v1/external/send-stream',request,onDelta);
}
function fillExternalModels(catalog){
 const list=document.querySelector('#external-models');list.replaceChildren();
 for(const model of catalog?.models || []){const option=document.createElement('option');option.value=model;list.append(option);}
}
function buildChatTimeline(thread,projections){
 const messages=thread?.messages || [],messageIds=new Set(messages.map(item=>item.message_id));
 const tasksByPrompt=new Map(),entries=[];
 for(const projection of projections){
  const messageId=projection.prompt?.message_id;
  if(messageIds.has(messageId)){
   if(!tasksByPrompt.has(messageId))tasksByPrompt.set(messageId,[]);
   tasksByPrompt.get(messageId).push(projection);
  }else entries.push({kind:'task',created_at:projection.created_at,
   stable_id:projection.task_id,value:projection});
  for(const source of projection.public_sources || [])if(source.state==='succeeded'){
   entries.push({kind:'public-source',
    created_at:source.result?.fetched_at || projection.created_at,
    stable_id:source.run_id,value:{task_id:projection.task_id,source}});
  }
 }
 for(const [index,item] of messages.entries())entries.push({kind:'message',
  created_at:item.created_at,stable_id:String(index).padStart(12,'0'),value:item,
  tasks:tasksByPrompt.get(item.message_id) || []});
 entries.sort((left,right)=>{
  const byTime=Date.parse(left.created_at)-Date.parse(right.created_at);
  if(byTime)return byTime;
  if(left.kind!==right.kind)return left.kind==='message'?-1:1;
  return left.stable_id.localeCompare(right.stable_id);
 });
 return entries;
}
function renderThreadMessage(item,thread){
  const message=document.createElement('div');message.className='chat-message '+item.role;
  message.textContent=item.content;
  const turn=(thread?.turns || []).find(value=>value.assistant_message_id===item.message_id);
  const languageDetail=turn?.response_language ?
   ` · požadovaný jazyk ${turn.response_language} · shoda ${turn.language_compliance==='unverified'?'neověřena':turn.language_compliance}`:'';
  const detail=document.createElement('small');detail.textContent=`${item.role==='user'?'Vy':'Asistent'} · ${item.privacy}${languageDetail}`;
  message.append(detail);
  if(turn?.external_request_available){
   const requestButton=document.createElement('button');requestButton.type='button';
   requestButton.className='secondary-button';requestButton.textContent='Zobrazit odeslaný request';
   requestButton.addEventListener('click',async()=>{
    requestButton.disabled=true;
    try{const record=await projectRequest('/v1/external/request',{run_id:turn.run_id});
     let pre=message.querySelector('.external-request-record');
     if(!pre){pre=document.createElement('pre');pre.className='external-request-record';message.append(pre);}
     pre.textContent=JSON.stringify(record.provider_request,null,2);
    }catch(error){chatOperationStatus.textContent=error.message;}
    finally{requestButton.disabled=false;}
   });
   message.append(requestButton);
  }
 return message;
}
function renderChat(thread){
 activeThread=thread || null;chatMessages.replaceChildren();
 if(responseLanguagePolicy)applyResponseLanguageStatus({response_language_policy:responseLanguagePolicy});
 for(const entry of buildChatTimeline(thread,taskOutcomes)){
  if(entry.kind==='task'){renderTaskOutcome(entry.value,true);continue;}
  if(entry.kind==='public-source'){renderPublicSourceTimelineEntry(entry.value);continue;}
  chatMessages.append(renderThreadMessage(entry.value,thread));
  for(const projection of entry.tasks)renderTaskOutcome(projection,false);
 }
 if(chatProgressActive)chatMessages.append(chatStreamStatus);
 draft.placeholder=activeSearchContinuation()?
  'Zpřesněte další kolo hledání…':'Co chcete v projektu zpracovat?';
 const composerDisabled=!activeProject || !draft.value.trim() || !threadWritable();
 document.querySelector('#chat-submit').disabled=composerDisabled;
 document.querySelector('#external-propose-button').disabled=composerDisabled;
 document.querySelector('#external-preview-button').disabled=composerDisabled;
}
function renderThreadList(threads){
 knownThreads=threads;
 const tree=document.querySelector('#sidebar-chat-tree');tree.replaceChildren();
 const assigned=activeProject ? threads.filter(thread=>thread.project_id===activeProject.id) : [];
 const unassigned=threads.filter(thread=>thread.project_id===null);
 function branch(label,branchThreads){
  if(!branchThreads.length)return;
  const root=document.createElement('li');root.className='sidebar-chat-branch';root.setAttribute('role','treeitem');root.setAttribute('aria-expanded','true');
  const toggle=document.createElement('button');toggle.type='button';toggle.className='sidebar-chat-branch-toggle';toggle.textContent=`${label} (${branchThreads.length})`;
  const group=document.createElement('ul');group.setAttribute('role','group');
  toggle.addEventListener('click',()=>{const expanded=root.getAttribute('aria-expanded')==='true';root.setAttribute('aria-expanded',String(!expanded));});
  root.append(toggle,group);tree.append(root);
  for(const thread of branchThreads){
  const row=document.createElement('li'),button=document.createElement('button');button.type='button';row.setAttribute('role','treeitem');
  row.className='sidebar-list-row sidebar-chat-row';button.className='sidebar-list-main sidebar-chat-open';
  button.dataset.threadId=thread.thread_id;
  button.setAttribute('aria-current',String(activeThread?.thread_id===thread.thread_id));
  button.textContent=`${thread.classification} · ${thread.status}`;
  const meta=document.createElement('small');meta.className='sidebar-chat-meta';
  const project=thread.project_id===activeProject?.id?'tento projekt':'jiný projekt';
  meta.textContent=`${thread.messages.length} zpráv${thread.project_id===null?'':` · ${project}`}`;
  button.append(meta);button.addEventListener('click',()=>openStoredThread(thread.thread_id));
  const menu=document.createElement('details');menu.className='sidebar-item-menu sidebar-chat-menu';
  const trigger=document.createElement('summary');trigger.setAttribute('aria-label',`Akce chatu ${thread.classification}`);trigger.textContent='⋮';
  const items=document.createElement('div');items.className='sidebar-item-menu-items sidebar-chat-menu-items';items.setAttribute('role','menu');
  function action(label,callback,disabled=false){
   const item=document.createElement('button');item.type='button';item.textContent=label;item.disabled=disabled;item.setAttribute('role','menuitem');
   item.addEventListener('click',async event=>{event.stopPropagation();menu.open=false;
    if(activeThread?.thread_id!==thread.thread_id)await openStoredThread(thread.thread_id);
    if(activeThread?.thread_id===thread.thread_id)await callback(event.currentTarget);});
   items.append(item);
  }
  action('Zobrazit',async()=>{},!activeProject);
  if(thread.project_id===null)action('Zařadit do tohoto projektu',async control=>{
   control.disabled=true;chatOperationStatus.textContent='Zařazuji vlákno do otevřeného projektu…';
   try{await assignActiveThread();chatOperationStatus.textContent='Vlákno bylo zařazeno do otevřeného projektu.';}
   catch(error){control.disabled=false;chatOperationStatus.textContent=error.message;}
  },!activeProject||thread.status==='archived');
  action('Archivovat',archiveActiveThread,!activeProject||thread.status==='archived');
  action('Připravit smazání',prepareActiveThreadDeletion,!activeProject);
  action('Uložit otisk',button=>runChatRecord(button,'snapshot'),!activeProject||!thread.messages.length);
  action('Uložit poslední odpověď',button=>runChatRecord(button,'output'),!activeProject||!thread.messages.length);
  menu.append(trigger,items);row.append(button,menu);group.append(row);
  }
 }
 branch('Zařazené',assigned);branch('Nezařazené',unassigned);
 const assignedCount=assigned.length,unassignedCount=unassigned.length;
 document.querySelector('#sidebar-chat-status').textContent=assignedCount||unassignedCount?
  `${assignedCount} zařazených · ${unassignedCount} nezařazených`:
  (activeProject?'Tento projekt nemá žádná přiřazená ani dostupná nezařazená vlákna.':'Zatím tu nejsou žádná nezařazená vlákna.');
}
function rememberThread(thread){
 const index=knownThreads.findIndex(item=>item.thread_id===thread.thread_id);
 if(index<0)knownThreads.unshift(thread);else knownThreads[index]=thread;
 renderThreadList(knownThreads);return thread;
}
function renderRunUsage(report,delivery=null){
 if(!report || report.status!=='available'){chatRunUsage.hidden=true;return;}
 chatRunUsage.textContent='Spotřeba běhu: '+report.metrics
  .map(item=>`${item.name} ${item.value} ${item.unit}`).join(' · ');
 if(delivery){chatRunUsage.textContent+=delivery.enabled ?
  ` · stream ${delivery.deltas} částí · první text ${delivery.firstDeltaMs===null?'nepřišel':(delivery.firstDeltaMs/1000).toFixed(1)+' s'} · UI celkem ${(delivery.totalMs/1000).toFixed(1)} s` :
  ' · stream nebyl v UI zapnutý';}
 chatRunUsage.hidden=false;
}
function renderTaskArtifactSources(){
 const list=document.querySelector('#task-artifact-list');if(!list)return;list.replaceChildren();
 for(const item of currentArtifacts){
  const label=document.createElement('label'),check=document.createElement('input');
  check.type='checkbox';check.value=item.id;
  label.append(check,document.createTextNode(` ${item.title}`));list.append(label);
 }
 if(!currentArtifacts.length)list.textContent='Projekt zatím nemá podklady.';
 updatePromptInputSummary();
}
function availablePublicSources(){
 const values=[];
 for(const projection of taskOutcomes){for(const source of projection.public_sources || []){
  if(source.state==='succeeded' && !values.some(item=>item.run_id===source.run_id))values.push(source);
 }}return values;
}
function renderTaskPublicSources(){
 const list=document.querySelector('#task-public-source-list');if(!list)return;
 const selected=new Set([...list.querySelectorAll('input:checked')].map(item=>item.value));
 list.replaceChildren();const sources=availablePublicSources();
 for(const source of sources){const label=document.createElement('label'),check=document.createElement('input');
  check.type='checkbox';check.value=source.run_id;check.checked=selected.has(source.run_id);
  label.append(check,document.createTextNode(` ${source.title} · ${source.url}`));list.append(label);}
 if(!sources.length)list.textContent='Zatím není načtený žádný veřejný zdroj. Zadejte dotaz; nejprve vznikne kontrolované webové hledání.';
 updatePromptInputSummary();
}
function refreshCurrentFileSource(){
 const label=document.querySelector('#task-source-current-file');
 const input=document.querySelector('#task-source-current-file-input');
 const title=document.querySelector('#task-source-current-file-title');
 if(!label||!input||!title)return;
 const item=currentArtifacts.find(value=>value.id===selectedArtifact);
 const searching=document.querySelector('#task-action')?.value==='search';
 const external=document.querySelector('#chat-run-adapter')?.value==='openai-responses';
 label.hidden=!item||searching;input.disabled=!item||external;
 if(!item||external)input.checked=false;
 input.value=item?.id || '';title.textContent=item?`Aktuální soubor: ${item.title}`:'Aktuální soubor';
 updatePromptInputSummary();
}
function updatePromptInputSummary(){
 const searching=document.querySelector('#task-action')?.value==='search';
 const conversation=document.querySelector('#task-source-conversation')?.checked;
 const artifacts=document.querySelector('#task-source-artifacts')?.checked;
 const publicWeb=document.querySelector('#task-source-public')?.checked;
 const artifactIds=new Set(artifacts?[...document.querySelectorAll('#task-artifact-list input:checked')].map(item=>item.value):[]);
 if(document.querySelector('#task-source-current-file-input')?.checked&&selectedArtifact)artifactIds.add(selectedArtifact);
 const artifactCount=artifactIds.size;
 const publicCount=publicWeb?document.querySelectorAll('#task-public-source-list input:checked').length:0;
 const count=searching?1:(conversation?1:0)+artifactCount+publicCount;
 const countOutput=document.querySelector('#task-input-count');
 if(countOutput)countOutput.textContent=String(count);
}
function replaceTaskProjection(projection){
 const index=taskOutcomes.findIndex(item=>item.task_id===projection.task_id);
 if(index<0)taskOutcomes.push(projection);else taskOutcomes[index]=projection;
 activeTaskThreadId=projection.thread_id;renderTaskPublicSources();renderChat(activeThread);
}
function activeSearchContinuation(){
 const projection=taskOutcomes.at(-1),round=projection?.search_workflow?.rounds?.at(-1);
 return projection?.temporary && projection.outcome?.kind==='web-search' && round?.evaluation ?
  {projection,round}:null;
}
function taskButton(label,handler,secondary=false){
 const button=document.createElement('button');button.type='button';button.textContent=label;
 if(secondary)button.className='secondary-button';button.addEventListener('click',handler);return button;
}
function searchAutonomyWorkflow(taskId){
 const matching=(autonomyQueue?.workflows || []).filter(workflow=>workflow.steps?.some(step=>
  step.action?.id==='search.iterative-query' && step.input?.request?.task_id===taskId));
 return matching.find(workflow=>!autonomyTerminal.has(workflow.state)) || matching.at(-1);
}
function currentSearchAutonomyStep(workflow){
 return workflow?.steps?.find(step=>!['completed','failed','unknown','cancelled'].includes(step.state)) ||
  workflow?.steps?.at(-1) || null;
}
async function refreshActiveTaskOutcomes(){
 if(!activeProject || !activeTaskThreadId)return;
 const tasks=await projectRequest('/v1/tasks/list',{
  project_id:activeProject.id,thread_id:activeTaskThreadId});
 taskOutcomes=tasks.outcomes;renderTaskPublicSources();renderChat(activeThread);
}
async function prepareAutomaticSearch(projection,query,parentSearchId,countdownSeconds){
 const request={workflow_id:crypto.randomUUID(),task_id:projection.task_id,
  mode:'automatic',countdown_seconds:countdownSeconds};
 if(query!==null)Object.assign(request,{query,parent_search_id:parentSearchId});
 chatOperationStatus.textContent='Připravuji přesný automatický plán bez odeslání…';
 try{await projectRequest('/v1/autonomy/search/prepare',request);await loadAutonomyQueue(false);
  renderChat(activeThread);chatOperationStatus.textContent=
   'Automatický plán je připravený. Zkontrolujte dotaz, cíl, privacy a budget a výslovně jej aktivujte.';
 }catch(error){chatOperationStatus.textContent=error.message;offerSearchRecovery(error);}
}
const researchProfileLabels={
 'quick-search-v1':'Rychlé hledání',
 'read-and-verify-v1':'Načíst a ověřit',
 'deep-research-v1':'Hloubkový výzkum'
};
const researchPhaseLabels={
 'search.iterative-query':'Vyhledání zdrojů',
 'source.fetch-public':'Načtení zdroje',
 'research.verify-evidence':'Ověření zdrojů a vazeb',
 'research.select-relevant':'Výběr relevantních zdrojů',
 'research.analyze':'Analýza',
 'research.compose-report':'Sestavení návrhu zprávy',
 'research.plan-next':'Rozhodnutí o dalším kroku'
};
const pendingResearchPreparations=new Set();
function researchActivityLabel(step){
 const action=step?.action?.id;
 if(action==='search.iterative-query')return 'Vyhledávám a vyhodnocuji zdroje…';
 if(action==='source.fetch-public')return 'Načítám a bezpečně zpracovávám zdroj…';
 if(action==='research.verify-evidence')return 'Ověřuji původ a vazby zdrojů…';
 if(action==='research.select-relevant')return 'Model vybírá relevantní zdroje…';
 if(action==='research.analyze')return 'Model analyzuje vybrané zdroje…';
 if(action==='research.compose-report')return 'Model sestavuje návrh zprávy…';
 if(action==='research.plan-next')return 'Model přemýšlí o dalším kroku…';
 return 'Provádím další krok workflow…';
}
async function prepareResearch(projection,mode,countdownSeconds,profileId){
 if(pendingResearchPreparations.has(projection.task_id)){
  chatOperationStatus.textContent='Příprava výzkumného plánu už probíhá; nevytvářím druhou frontu.';return;
 }
 pendingResearchPreparations.add(projection.task_id);
 chatOperationStatus.textContent='Připravuji kontrolovatelný výzkumný plán bez odeslání…';
 try{await withChatProgress('Připravuji kontrolovatelný výzkumný plán…',async()=>{
   await projectRequest('/v1/autonomy/research/prepare',{
    workflow_id:crypto.randomUUID(),task_id:projection.task_id,mode,
    countdown_seconds:countdownSeconds,profile_id:profileId,profile_version:'1.0'});
   await loadAutonomyQueue(false);renderChat(activeThread);
  });chatOperationStatus.textContent=
   'Výzkumný plán je připravený. Před spuštěním zkontrolujte profil, cíl, privacy a limity.';
 }catch(error){chatOperationStatus.textContent=error.message;offerSearchRecovery(error);}
 finally{pendingResearchPreparations.delete(projection.task_id);}
}
function renderResearchPreparation(container,projection,query,parentSearchId){
 const controls=document.createElement('fieldset');controls.className='search-autonomy-controls';
 const legend=document.createElement('legend');legend.textContent='Další práce se zdroji';
 const profileLabel=document.createElement('label');profileLabel.textContent='Profil ';
 const profile=document.createElement('select');
 profile.append(new Option('Jednorázové hledání',''),
  new Option('Rychlé hledání','quick-search-v1'),
  new Option('Načíst a ověřit','read-and-verify-v1'),
  new Option('Hloubkový výzkum','deep-research-v1'));profileLabel.append(profile);
 const modeLabel=document.createElement('label');modeLabel.textContent=' Režim ';
 const mode=document.createElement('select');
 mode.append(new Option('Ruční kontrola','manual'),new Option('Automaticky s odpočtem','automatic'));
 modeLabel.append(mode);
 const countdownLabel=document.createElement('label');countdownLabel.textContent=' Odpočet ';
 const countdown=document.createElement('select');
 for(const seconds of [3,4,5])countdown.append(new Option(`${seconds} s`,String(seconds)));
 countdown.value='5';countdown.disabled=true;countdownLabel.append(countdown);
 const run=taskButton('Připravit ruční kontrolu',async()=>{
  if(profile.value)await prepareResearch(projection,mode.value,Number(countdown.value),profile.value);
  else if(mode.value==='manual')await prepareTaskSearch(projection,query,parentSearchId);
  else await prepareAutomaticSearch(projection,query,parentSearchId,Number(countdown.value));
 });
 const update=()=>{const automatic=mode.value==='automatic';countdown.disabled=!automatic;
  run.textContent=profile.value ? `Připravit: ${researchProfileLabels[profile.value]}` :
   automatic?'Připravit automatiku':'Připravit ruční kontrolu';};
 mode.addEventListener('change',update);profile.addEventListener('change',update);
 controls.append(legend,profileLabel,modeLabel,countdownLabel,run);container.append(controls);
}
function openResearchDraftEditor(draft){
 if(!canLeaveWorkspaceEditors())return;
 openNewArtifactEditor();
 fillArtifactEditor({title:'Výzkumná zpráva',filename:'research-report.md',
  body:draft.markdown,metadata:{description:'Návrh sestavený z ověřených zdrojů.',
   tags:['research']}},true);
 artifactEditorStatus.textContent='Neuložený návrh. Projekt se změní až po stisknutí Uložit.';
}
function renderSearchAutonomy(container,projection,query,parentSearchId){
 const workflow=searchAutonomyWorkflow(projection.task_id);
 if(!workflow){
  renderResearchPreparation(container,projection,query,parentSearchId);return;
 }
 const research=workflow.policy?.research || null;
 const step=currentSearchAutonomyStep(workflow),preview=step?.input?.preview || {};
 const panel=document.createElement('section');panel.className='search-autonomy';panel.dataset.state=workflow.state;
 const title=document.createElement('h4');title.textContent=
  `${workflow.mode==='automatic'?'Automatický':'Ruční'} ${research ?
   researchProfileLabels[research.profile_id] || research.profile_id : 'přenos dotazu'} · ${workflow.state}`;
 const facts=document.createElement('dl');facts.className='search-autonomy-facts';
 const fact=(name,value)=>{const term=document.createElement('dt');term.textContent=name;
  const detail=document.createElement('dd');detail.textContent=String(value ?? '—');facts.append(term,detail);};
 fact('Dotaz',preview.query || research?.goal);fact('Účel',preview.purpose || research?.goal);
 if(research)fact('Profil',`${researchProfileLabels[research.profile_id] || research.profile_id} · ${research.profile_version}`);
 fact('Cíl',preview.binding ? `${preview.binding.endpoint || preview.binding.adapter || 'SearXNG'} · ${preview.binding.target_id || '—'}` : '—');
 fact('Privacy',step?.privacy);fact('Kolo',preview.round_index);
 fact('Limit',`${workflow.spent_cost}/${workflow.budget.max_cost_units} cost · nejvýše ${workflow.budget.max_steps} kroků · ${workflow.budget.max_seconds} s`);
 fact('Zbývá',`${workflow.remaining_cost} cost · ${workflow.remaining_steps} kroků · ${workflow.remaining_seconds} s`);
 if(workflow.state==='countdown'&&step?.not_before){const term=document.createElement('dt');term.textContent='Odeslání za';
  const detail=document.createElement('dd'),count=document.createElement('strong');count.className='search-autonomy-countdown';
  count.dataset.notBefore=step.not_before;detail.append(count);facts.append(term,detail);}
 const progress=document.createElement('progress');progress.max=Math.max(1,workflow.budget.max_cost_units);
 progress.value=workflow.spent_cost;progress.setAttribute('aria-label','Využitý rozpočet automatického hledání');
 const actions=document.createElement('div');actions.className='task-actions';
 const attach=()=>projectRequest('/v1/autonomy/attach',{workflow_id:workflow.workflow_id});
 if(workflow.state==='proposed')actions.append(taskButton('Aktivovat plán',async()=>{
  if(!confirm(`Aktivovat ${workflow.mode==='automatic'?'automatický':'ruční'} plán?\n\nProfil: ${researchProfileLabels[research?.profile_id] || 'jednorázové hledání'}\nCíl: ${research?.goal || preview.purpose}\nPrivacy: ${step.privacy}\nLimit: ${workflow.budget.max_steps} kroků / ${workflow.budget.max_cost_units} cost / ${workflow.budget.max_seconds} s\nOdpočet: ${workflow.countdown_seconds} s`))return;
  await attach();await autonomyRequest('/v1/autonomy/activate',{
   workflow_id:workflow.workflow_id,activation_digest:workflow.activation_digest});renderChat(activeThread);
 }));
 if(['queued','running'].includes(workflow.state)&&workflow.mode==='manual')actions.append(taskButton('Provést další krok',async()=>{
  await withChatProgress(researchActivityLabel(step),async()=>{await attach();
   await autonomyRequest('/v1/autonomy/advance',{workflow_id:workflow.workflow_id});
   await refreshActiveTaskOutcomes();renderChat(activeThread);});
 }));
 for(const awaiting of workflow.steps.filter(item=>item.state==='awaiting-approval'))actions.append(taskButton('Schválit přesný krok',async()=>{
  if(!confirm(`Potvrdit pouze tento krok?\n\n${researchPhaseLabels[awaiting.action.id] || awaiting.action.id}\n${JSON.stringify(awaiting.input,null,2)}`))return;
  await attach();await autonomyRequest('/v1/autonomy/approve',{workflow_id:workflow.workflow_id,step_id:awaiting.step_id});renderChat(activeThread);
 }));
 if(workflow.state==='countdown')actions.append(taskButton('Odeslat nyní',async()=>{
  if(!confirm(`Odeslat nyní přesně zobrazený dotaz?\n\n${preview.query}`))return;
  await withChatProgress(researchActivityLabel(step),async()=>{
   await autonomyRequest('/v1/autonomy/send-now',{workflow_id:workflow.workflow_id,
    step_id:step.step_id,dispatch_digest:step.dispatch_digest});
   await refreshActiveTaskOutcomes();renderChat(activeThread);});
 }));
 if(['queued','countdown'].includes(workflow.state))actions.append(taskButton('Pozastavit',async()=>{
  await autonomyRequest('/v1/autonomy/pause',{workflow_id:workflow.workflow_id});renderChat(activeThread);
 },true));
 if(workflow.state==='paused')actions.append(taskButton('Pokračovat',async()=>{
  await attach();await autonomyRequest('/v1/autonomy/resume',{workflow_id:workflow.workflow_id});renderChat(activeThread);
 }));
 const editable=step && ['queued','countdown','awaiting-approval'].includes(step.state) &&
  step.input?.request?.parent_search_id;
 if(editable){const edit=document.createElement('input');edit.value=preview.query || '';
  edit.maxLength=4096;edit.setAttribute('aria-label','Upravený webový dotaz');
  actions.append(edit,taskButton('Uložit úpravu',async()=>{
   await autonomyRequest('/v1/autonomy/search/edit',{
    workflow_id:workflow.workflow_id,query:edit.value});renderChat(activeThread);
  },true));}
 if(!autonomyTerminal.has(workflow.state))actions.append(taskButton('Zrušit',async()=>{
  if(!confirm('Zrušit automatické hledání a dosud neodeslané dotazy?'))return;
  await autonomyRequest('/v1/autonomy/cancel',{workflow_id:workflow.workflow_id});
  await refreshActiveTaskOutcomes();renderChat(activeThread);
 },true));
 const phases=document.createElement('ol');phases.className='research-phases';
 for(const item of workflow.steps){const row=document.createElement('li');row.className='research-phase';row.dataset.state=item.state;
  const label=document.createElement('strong');label.textContent=`${researchPhaseLabels[item.action.id] || item.action.id} · ${item.state}`;
  const detail=document.createElement('small');const result=item.result || {};
  const provenance=[`privacy ${item.privacy}`,`cost ${item.cost_units}`];
  if(result.run_id)provenance.push(`run ${result.run_id}`);
  if(result.final_url)provenance.push(result.final_url);
  if(result.source_run_id)provenance.push(`source ${result.source_run_id}`);
  if(result.evidence?.sources)provenance.push(`${result.evidence.sources.length} zdrojů · ${result.evidence.relations.length} vazeb`);
  if(result.selection?.selected_source_run_ids)provenance.push(`${result.selection.selected_source_run_ids.length} vybraných zdrojů`);
  if(result.claims)provenance.push(`${result.claims.length} závěrů`);
  if(result.proposal_sha256)provenance.push(`návrh ${result.proposal_sha256}`);
  if(result.draft_sha256)provenance.push(`draft ${result.draft_sha256}`);
  if(result.reason)provenance.push(result.reason);
  if(item.error)provenance.push(`Chyba: ${item.error}`);
  detail.textContent=provenance.join(' · ');row.append(label,detail);phases.append(row);}
 const revisionPanels=document.createElement('div');
 for(const pending of (workflow.revision_proposals || []).filter(item=>item.state==='pending')){
  const proposal=pending.proposal,box=document.createElement('section');box.className='research-revision';
  const heading=document.createElement('strong');heading.textContent=`Čekající revize: ${proposal.kind}`;
  const reason=document.createElement('p');reason.textContent=`Důvod: ${proposal.reason}`;
  const impact=document.createElement('p');impact.textContent=`Limit: ${JSON.stringify(workflow.budget)} → ${JSON.stringify(proposal.budget)}${proposal.step?` · nový krok ${researchPhaseLabels[proposal.step.action.id] || proposal.step.action.id}`:' · ukončení'}`;
  const exact=document.createElement('code');exact.textContent=`digest ${pending.approval_digest}`;
  const approve=taskButton('Potvrdit přesnou revizi',async()=>{if(!confirm(`Potvrdit změnu plánu?\n${reason.textContent}\n${impact.textContent}\n${exact.textContent}`))return;
   await attach();await autonomyRequest('/v1/autonomy/revision/confirm',{workflow_id:workflow.workflow_id,proposal_id:pending.proposal_id,approval_digest:pending.approval_digest});renderChat(activeThread);});
  box.append(heading,reason,impact,exact,approve);revisionPanels.append(box);
 }
 const drafts=document.createElement('div');
 for(const report of workflow.steps.filter(item=>item.action.id==='research.compose-report'&&item.state==='completed')){
  const box=document.createElement('section');box.className='research-draft';
  const heading=document.createElement('strong');heading.textContent='Návrh výzkumné zprávy';
  const note=document.createElement('p');note.textContent='Pouhé zobrazení ani otevření v editoru projekt nemění.';
  const show=taskButton('Zobrazit návrh zprávy',async()=>{const draft=await projectRequest('/v1/autonomy/research/draft',{workflow_id:workflow.workflow_id,step_id:report.step_id});
   let pre=box.querySelector('pre');if(!pre){pre=document.createElement('pre');box.append(pre);}pre.textContent=draft.markdown;
   let provenance=box.querySelector('small');if(!provenance){provenance=document.createElement('small');box.append(provenance);}provenance.textContent=`run ${draft.run_id} · zdroje ${draft.selected_source_run_ids.join(', ')} · citace ${draft.citations.length}`;
   if(!box.querySelector('[data-open-research-draft]')){const open=taskButton('Otevřít jako neuložený dokument',()=>openResearchDraftEditor(draft));open.dataset.openResearchDraft='true';box.append(open);}
  });box.append(heading,note,show);drafts.append(box);
 }
 panel.append(title,facts,progress,phases,revisionPanels,drafts,actions);
 if((workflow.plan_revisions || []).length>1){const history=document.createElement('details');
  const view=autonomyWorkflowView(workflow);history.open=view.planReasonsOpen;
  history.addEventListener('toggle',()=>{view.planReasonsOpen=history.open;});
  const summary=document.createElement('summary');summary.textContent='Důvody změn plánu';
  const list=document.createElement('ol');for(const revision of workflow.plan_revisions.slice(1)){
   const row=document.createElement('li');row.textContent=`r${revision.revision} · ${revision.kind} · ${revision.reason}`;list.append(row);}
  history.append(summary,list);panel.append(history);}
 if(workflow.revisions?.length){const history=document.createElement('details');
  const view=autonomyWorkflowView(workflow);history.open=view.searchRevisionsOpen;
  history.addEventListener('toggle',()=>{view.searchRevisionsOpen=history.open;});
  const summary=document.createElement('summary');summary.textContent=`Zrušené verze dotazu (${workflow.revisions.length})`;
  const pre=document.createElement('pre');pre.textContent=JSON.stringify(workflow.revisions,null,2);
  history.append(summary,pre);panel.append(history);}
 container.append(panel);if(autonomyTerminal.has(workflow.state))renderResearchPreparation(container,projection,query,parentSearchId);updateAutonomyCountdownLabels();
}
function taskPlanSummary(plan){
 if(!plan)return '';
 const sources={conversation:'konverzace',artifacts:'interní artefakty','public-web':'veřejné zdroje'};
 const outputs={conversation:'konverzace',document:'dokument',presentation:'prezentace'};
 const execution={'local-ollama':'lokální Ollama','external-openai':'externí OpenAI'};
 return `Zdroje: ${plan.source_kinds.map(value=>sources[value] || value).join(', ')} · výstup: ${outputs[plan.output_kind] || plan.output_kind} · provedení: ${execution[plan.execution] || plan.execution}`;
}
function renderSearchWorkflow(container,workflow,projection=null){
 if(!workflow)return;
 const budget=document.createElement('p');budget.className='search-budget';
 const used=workflow.budget_used || {},limits=workflow.budget || {};
 budget.textContent=`Rozpočet: kola ${used.rounds_used || 0}/${limits.max_rounds || 0} · dotazy ${used.queries_used || 0}/${limits.max_queries || 0} · výsledky ${used.results_used || 0}/${limits.max_results || 0} · čas ${used.elapsed_seconds || 0}/${limits.max_seconds || 0} s`;
 container.append(budget);
 const rounds=document.createElement('div');rounds.className='search-rounds';
 for(const item of workflow.rounds || []){
  const round=document.createElement('section');round.className='search-round';
  const title=document.createElement('h4');title.textContent=`Kolo ${item.round_index}: ${item.query}`;round.append(title);
  const provenance=document.createElement('small');
  provenance.textContent=`search ${item.search_id} · run ${item.run_id} · manifest ${item.manifest_id}`;round.append(provenance);
  const sources=document.createElement('ol');sources.className='search-sources';
  for(const source of item.sources || []){const row=document.createElement('li'),name=document.createElement('strong');
   name.textContent=source.title;const url=document.createElement('code');url.textContent=source.url;
   const snippet=document.createElement('small');snippet.textContent=source.snippet;
   const sourceId=document.createElement('small');sourceId.textContent=source.source_id;
   row.append(name,url,snippet,sourceId);
   if(projection && typeof source.url==='string' && source.url.startsWith('https://')){
    const existing=(projection.public_sources || []).filter(
      value=>value.source_id===source.source_id).at(-1);
    if(existing?.state==='succeeded')row.append(taskButton('Zobrazit načtený text',
      ()=>showPublicSource(projection.task_id,existing.run_id),true));
    else {if(existing){const state=document.createElement('small');
      state.textContent=`Reader: ${existing.state}${existing.error_code?' · '+existing.error_code:''}`;row.append(state);}
     row.append(taskButton(existing?'Připravit nové načtení':'Načíst stránku',
      ()=>preparePublicSource(projection,item.search_id,source),true));}
   }
   sources.append(row);}round.append(sources);
  if(item.evaluation){const evaluation=document.createElement('div');evaluation.className='search-evaluation';
   const assessment=document.createElement('strong');assessment.textContent=`Hodnocení modelu: ${item.evaluation.assessment}`;
   const answer=document.createElement('p');answer.textContent=item.evaluation.answer;
   const rationale=document.createElement('small');rationale.textContent=item.evaluation.rationale;
   evaluation.append(assessment,answer,rationale);
   for(const limitation of item.evaluation.limitations || []){const note=document.createElement('small');note.textContent=`Omezení: ${limitation}`;evaluation.append(note);}
   round.append(evaluation);}
  rounds.append(round);
 }
 container.append(rounds);
}
function renderTaskOutcome(projection,showPrompt=true){
  if(showPrompt){const prompt=document.createElement('div');prompt.className='chat-message user';
   prompt.textContent=projection.prompt.content;
   const promptDetail=document.createElement('small');promptDetail.textContent=`Vy · ${projection.prompt.privacy}`;
   prompt.append(promptDetail);chatMessages.append(prompt);}
  if(projection.state==='cancelled')return;
  const outcome=projection.outcome;if(!outcome)return;
  if(outcome.kind==='direct-answer'){
   const answer=document.createElement('div');answer.className='chat-message assistant';answer.textContent=outcome.content;
   const detail=document.createElement('small');detail.textContent=`Asistent · ${projection.privacy}`;
   answer.append(detail);if(projection.task_plan){const plan=document.createElement('small');
    plan.textContent=taskPlanSummary(projection.task_plan);answer.append(plan);}chatMessages.append(answer);return;
  }
  const card=document.createElement('section');card.className='task-outcome'+(projection.temporary?'':' terminal');
  const heading=document.createElement('h3');
  heading.textContent=outcome.kind==='artifact-draft'?'Návrh artefaktu':
   outcome.kind==='presentation-draft'?'Návrh prezentace':
   outcome.kind==='presentation-link'?'Uložená prezentace':
   outcome.kind==='artifact-link'?'Vytvořený artefakt':
   outcome.kind==='web-search'?'Návrh webového hledání':
   outcome.kind==='web-search-answer'?'Odpověď z řízeného hledání':'Externí volání';card.append(heading);
  if(projection.task_plan){const plan=document.createElement('small');plan.textContent=taskPlanSummary(projection.task_plan);card.append(plan);}
  if(outcome.kind==='presentation-draft'){
   const approval=projection.presentation_approval;
   const title=document.createElement('strong');title.textContent=outcome.deck.title;card.append(title);
   const mode=document.createElement('p');mode.textContent=outcome.operation==='create'?
    'Nová prezentace — zatím pouze náhled.':'Aktualizace existující prezentace — zatím pouze náhled.';card.append(mode);
   const slides=document.createElement('ol');slides.className='presentation-proposal-slides';
   for(const slide of outcome.deck.slides.filter(item=>item.kind==='main')){
    const item=document.createElement('li');const name=document.createElement('strong');name.textContent=slide.title;
    const detail=document.createElement('small');detail.textContent=`Layout: ${slide.layout} · ${slide.bullets.length} odrážek`;
    item.append(name,detail);slides.append(item);
   }
   card.append(slides);
   const digest=document.createElement('small');digest.textContent=
    `Výchozí revize ${outcome.base_revision.slice(0,12)} · digest návrhu ${outcome.deck_sha256.slice(0,12)}`;card.append(digest);
   if(approval){const diff=document.createElement('details'),summary=document.createElement('summary');
    summary.textContent=approval.operation==='create'?
     `Přesný náhled vytvoření · ${approval.changes.length} slidů`:
     `Přesný diff aktualizace · ${approval.changes.length} změněných slidů`;
    diff.append(summary);const titles=document.createElement('p');titles.textContent=
     approval.title_before===null?`Nový název: ${approval.title_after}`:
     `Název: ${approval.title_before} → ${approval.title_after}`;diff.append(titles);
    for(const change of approval.changes){const item=document.createElement('pre');item.textContent=
      JSON.stringify({akce:change.action,před:change.before,po:change.after},null,2);diff.append(item);}
    const approvalDigest=document.createElement('small');approvalDigest.textContent=
     `Digest schválení ${approval.approval_digest}`;diff.append(approvalDigest);card.append(diff);}
   const warning=document.createElement('small');warning.textContent=
    'Návrh není uložený. Potvrzení vytvoří jeden projektový commit; změněná revize nebo digest se odmítne.';card.append(warning);
   const actions=document.createElement('div');actions.className='task-actions';
   if(approval)actions.append(taskButton(outcome.operation==='create'?'Schválit a vytvořit':'Schválit aktualizaci',async event=>{
    event.currentTarget.disabled=true;chatOperationStatus.textContent='Ukládám přesně schválenou prezentaci…';
    let attempt=presentationApprovalAttempts.get(projection.task_id);
    if(!attempt){attempt={artifact_id:outcome.operation==='update'?outcome.target_artifact_id:crypto.randomUUID(),operation_id:crypto.randomUUID()};presentationApprovalAttempts.set(projection.task_id,attempt);}
    try{const projectId=activeProject.id,result=await projectRequest('/v1/tasks/presentation/confirm',{
      task_id:projection.task_id,artifact_id:attempt.artifact_id,operation_id:attempt.operation_id,
      approval_digest:approval.approval_digest,base_revision:approval.base_revision,
      deck_sha256:approval.deck_sha256,approved:true},120000);
     presentationApprovalAttempts.delete(projection.task_id);replaceTaskProjection(result);
     await openRegisteredProject(projectId);await openPresentationEditor(attempt.artifact_id);
     chatOperationStatus.textContent='Prezentace byla uložena do projektu a otevřena v editoru.';
    }catch(error){chatOperationStatus.textContent=error.message;event.currentTarget.disabled=false;}
   }));
   actions.append(taskButton('Zahodit',()=>cancelTaskProjection(projection.task_id),true));card.append(actions);
  }else if(outcome.kind==='presentation-link'){
   const title=document.createElement('strong');title.textContent=outcome.title;card.append(title);
   const detail=document.createElement('small');detail.textContent=
    `${outcome.operation==='create'?'Vytvořeno':'Aktualizováno'} v revizi ${outcome.project_commit.slice(0,12)} · digest ${outcome.deck_sha256.slice(0,12)}`;card.append(detail);
   const actions=document.createElement('div');actions.className='task-actions';
   actions.append(taskButton('Otevřít prezentaci',()=>openPresentationEditor(outcome.artifact_id)));card.append(actions);
  }else if(outcome.kind==='artifact-draft'){
   const title=document.createElement('strong');title.textContent=outcome.title;card.append(title);
   const body=document.createElement('pre');body.textContent=outcome.content;card.append(body);
   const actions=document.createElement('div');actions.className='task-actions';
   actions.append(taskButton('Uložit do projektu',async event=>{
    event.currentTarget.disabled=true;chatOperationStatus.textContent='Ukládám potvrzený artefakt…';
    try{const projectId=activeProject.id;await projectRequest('/v1/tasks/artifact',{
      task_id:projection.task_id,artifact_id:crypto.randomUUID(),operation_id:crypto.randomUUID()});
     await openRegisteredProject(projectId);selectMainTab(document.querySelector('#chat-tab'));
     chatOperationStatus.textContent='Artefakt byl uložen a návrh nahrazen odkazem.';
    }catch(error){chatOperationStatus.textContent=error.message;event.currentTarget.disabled=false;}
   }),taskButton('Zahodit',()=>cancelTaskProjection(projection.task_id),true));card.append(actions);
  }else if(outcome.kind==='external-request'){
   const purpose=document.createElement('p');purpose.textContent=outcome.purpose;card.append(purpose);
   const query=document.createElement('pre');query.textContent=outcome.query;card.append(query);
   const actions=document.createElement('div');actions.className='task-actions';
   actions.append(taskButton('Zkontrolovat externí odeslání',()=>prepareTaskExternal(projection)),
                  taskButton('Zahodit',()=>cancelTaskProjection(projection.task_id),true));card.append(actions);
  }else if(outcome.kind==='web-search'){
   const purpose=document.createElement('p');purpose.textContent=outcome.purpose;card.append(purpose);
   const query=document.createElement('pre');query.textContent=outcome.query;card.append(query);
   renderSearchWorkflow(card,projection.search_workflow,projection);
   const actions=document.createElement('div');actions.className='task-actions';
   const workflow=projection.search_workflow,latest=workflow?.rounds?.at(-1);
   if(!workflow || !latest?.evaluation){
    renderSearchAutonomy(actions,projection,null,null);
   }else{
   const activeAutomatic=searchAutonomyWorkflow(projection.task_id);
   if(activeAutomatic){renderSearchAutonomy(actions,projection,
    activeAutomatic.steps.at(-1)?.input?.preview?.query || null,latest.search_id);}
   else for(const nextQuery of workflow.next_queries || []){
     const option=document.createElement('div');option.className='search-next-query';
     const label=document.createElement('strong');label.textContent=`Navržený další dotaz: ${nextQuery}`;
     option.append(label);renderSearchAutonomy(option,projection,nextQuery,latest.search_id);
     actions.append(option);
    }
    if(!(workflow.next_queries || []).length){const hint=document.createElement('small');
     hint.textContent='Výsledek není konečný. Zpřesnění dalšího kola napište do pole dole.';
     actions.append(hint);}
   }
   actions.append(taskButton('Zahodit',()=>cancelTaskProjection(projection.task_id),true));card.append(actions);
  }else if(outcome.kind==='web-search-answer'){
   const answer=document.createElement('div');answer.className='chat-message assistant';
   answer.textContent=outcome.content;card.append(answer);
   renderSearchWorkflow(card,{rounds:outcome.rounds,budget:outcome.budget,
    budget_used:outcome.budget_used},projection);
   const caveat=document.createElement('small');caveat.textContent=
    `Finálnost je hodnocení modelu, nikoli záruka správnosti · důvod ukončení: ${outcome.completion_reason}`;card.append(caveat);
   const detail=document.createElement('small');detail.textContent=
    `SearXNG · ${outcome.sources?.length || 0} unikátních zdrojů · ${outcome.model}`;card.append(detail);
  }else if(outcome.kind==='artifact-link'){
   const link=document.createElement('button');link.type='button';link.className='artifact-link';
   link.textContent=`${outcome.title} → ${outcome.artifact_id}`;
   link.addEventListener('click',()=>openPreview(outcome.artifact_id));card.append(link);
  }else{
   const detail=document.createElement('small');detail.textContent=
    `Externista byl zavolán · stav ${outcome.state} · run ${outcome.run_id}`;card.append(detail);
  }
  chatMessages.append(card);
  if(outcome.kind==='external-call' && typeof projection.external_answer==='string'){
   const answer=document.createElement('div');answer.className='chat-message assistant';
   answer.textContent=projection.external_answer;
   const detail=document.createElement('small');detail.textContent=`Externí asistent · ${projection.privacy}`;
   answer.append(detail);chatMessages.append(answer);
  }
}
async function cancelTaskProjection(taskId){
 try{replaceTaskProjection(await projectRequest('/v1/tasks/cancel',{task_id:taskId}));
  chatOperationStatus.textContent='Návrh byl zahozen.';
 }catch(error){chatOperationStatus.textContent=error.message;}
}
function hideSearchRecovery(){searchRecoveryBinding=null;searchRecovery.hidden=true;searchRecovery.disabled=false;}
function offerSearchRecovery(error,binding=null){
 if(error.retry!=='configure-search'){hideSearchRecovery();return;}
 searchRecoveryBinding=binding;searchRecovery.textContent=binding ?
  'Obnovit SearXNG z tohoto náhledu' : 'Otevřít nastavení SearXNG';
 searchRecovery.hidden=false;searchRecovery.disabled=false;
}
searchRecovery.addEventListener('click',async()=>{
 if(!searchRecoveryBinding){await openSettings();searchForm.elements.endpoint.focus();return;}
 searchRecovery.disabled=true;chatOperationStatus.textContent='Obnovuji přesné nastavení SearXNG z kontrolovaného náhledu…';
 try{const result=await projectRequest('/v1/search/configure',searchRecoveryBinding);
  fillSearchBinding(result.binding);hideSearchRecovery();
  document.querySelector('#search-confirm').disabled=!document.querySelector('#search-confirm-check').checked;
  chatOperationStatus.textContent='Nastavení SearXNG bylo obnoveno. Dotaz můžete potvrdit znovu.';
 }catch(error){chatOperationStatus.textContent=error.message;searchRecovery.disabled=false;}
});
async function prepareTaskExternal(projection){
 chatOperationStatus.textContent='Připravuji přesný externí náhled…';
 const request={task_id:projection.task_id,approval_id:crypto.randomUUID(),turn_id:crypto.randomUUID(),
  run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),assistant_message_id:crypto.randomUUID()};
 try{const preview=projection.external_preview ||
   await projectRequest('/v1/tasks/external/preview',request);
  pendingExternalPreview={task:true,taskId:projection.task_id,request,preview};
  document.querySelector('#external-preview-content').textContent=JSON.stringify(preview,null,2);
  document.querySelector('#external-preview').hidden=false;
  document.querySelector('#external-privacy-confirm').checked=false;
  document.querySelector('#external-confirm').disabled=true;
  chatOperationStatus.textContent='Externí požadavek je jen náhled. Zkontrolujte jej a potvrďte.';
 }catch(error){chatOperationStatus.textContent=error.message;}
}
async function prepareTaskSearch(projection,query=null,parentSearchId=null){
 hideSearchRecovery();
 chatOperationStatus.textContent='Připravuji přesný náhled webového dotazu…';
 const request={task_id:projection.task_id,search_id:crypto.randomUUID(),
  synthesis_run_id:crypto.randomUUID(),synthesis_manifest_id:crypto.randomUUID()};
 if(query!==null){request.query=query;request.parent_search_id=parentSearchId;}
 try{const preview=(query===null && projection.search_preview) ||
   await projectRequest('/v1/tasks/search/preview',request);
  pendingSearchPreview={projection,preview};
  document.querySelector('#search-preview-content').textContent=JSON.stringify(preview,null,2);
  document.querySelector('#search-preview').hidden=false;
  document.querySelector('#search-confirm-check').checked=false;
  document.querySelector('#search-confirm').disabled=true;
  chatOperationStatus.textContent=preview.state==='unknown'?
   'Výsledek předchozího hledání není známý; automatické opakování je zakázané.' :
   'Zkontrolujte přesný dotaz, privacy a endpoint a potom jej potvrďte.';
  return true;
 }catch(error){chatOperationStatus.textContent=error.message;offerSearchRecovery(error);return false;}
}
document.querySelector('#search-confirm-check').addEventListener('change',event=>{
 document.querySelector('#search-confirm').disabled=!event.currentTarget.checked || !pendingSearchPreview;
});
document.querySelector('#search-cancel').addEventListener('click',()=>{
 hideSearchRecovery();
 pendingSearchPreview=null;document.querySelector('#search-preview').hidden=true;
 document.querySelector('#search-confirm-check').checked=false;
});
document.querySelector('#search-confirm').addEventListener('click',async event=>{
 if(!pendingSearchPreview)return;event.currentTarget.disabled=true;
 chatOperationStatus.textContent='SearXNG hledá a Ollama zpracovává bounded výsledky…';
 const preview=pendingSearchPreview.preview;
 try{const projection=await withChatProgress('Vyhledávám a model vyhodnocuje výsledky…',()=>
   projectRequest('/v1/tasks/search/confirm',{
    task_id:preview.task_id,search_id:preview.search_id,
    preview_sha256:preview.preview_sha256,approved:true},210000));
  replaceTaskProjection(projection);pendingSearchPreview=null;
  document.querySelector('#search-preview').hidden=true;
  chatOperationStatus.textContent=projection.temporary ?
   (projection.search_workflow?.next_queries?.length ?
    'Kolo je vyhodnocené. Navržený další dotaz se odešle až po vaší kontrole a potvrzení.' :
    'Kolo není konečné. Napište do pole dole vlastní zpřesnění; před odesláním jej zkontrolujete.') :
   'Řízené hledání a syntéza jsou dokončené.';
 }catch(error){chatOperationStatus.textContent=error.message;
  offerSearchRecovery(error,preview.binding);event.currentTarget.disabled=false;}
});
async function preparePublicSource(projection,searchId,source){
 const request={task_id:projection.task_id,search_id:searchId,
  source_id:source.source_id,run_id:crypto.randomUUID()};
 chatOperationStatus.textContent='Připravuji přesný plán načtení vybraného zdroje…';
 try{const preview=await projectRequest('/v1/tasks/public-source/preview',request);
  pendingPublicSourcePreview={request,preview};
  document.querySelector('#public-source-preview-content').textContent=JSON.stringify(preview,null,2);
  document.querySelector('#public-source-preview').hidden=false;
  document.querySelector('#public-source-result').hidden=true;
  document.querySelector('#public-source-confirm-check').checked=false;
  document.querySelector('#public-source-confirm').disabled=true;
  chatOperationStatus.textContent='Zkontrolujte robots preflight, cílovou URL, privacy a limity.';
 }catch(error){chatOperationStatus.textContent=error.message;}
}
function displayPublicSourceResult(fetched){
 const panel=document.querySelector('#public-source-preview');panel.hidden=false;
 const result=document.querySelector('#public-source-result');
 populatePublicSourceResult(result,fetched);
}
function populatePublicSourceResult(result,fetched){
 const structured=result.querySelector('.public-source-structured');
 const original=result.querySelector('.public-source-text');original.textContent=fetched.text;
 renderPublicSourceProjection(structured,fetched.projection);
 const hasStructured=Boolean(fetched.projection?.blocks?.length);
 result.querySelector('[data-source-view="structured"]').hidden=!hasStructured;
 selectPublicSourceView(result,hasStructured?'structured':'text');
 result.querySelector('small').textContent=
  `run ${fetched.run_id} · text SHA-256 ${fetched.result.text_sha256} · ${fetched.result.text_length} znaků${fetched.result.projection?' · '+fetched.result.projection.block_count+' bloků · projekce '+fetched.result.projection.sha256:''} · do projektu nebylo nic zapsáno`;
 result.hidden=false;
}
function createPublicSourceResultView(){
 const result=document.createElement('div');result.className='public-source-inline-result';result.hidden=true;
 const tabs=document.createElement('div');tabs.className='public-source-view-tabs';tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Zobrazení veřejného zdroje');
 const structuredButton=document.createElement('button');structuredButton.type='button';structuredButton.dataset.sourceView='structured';structuredButton.textContent='Strukturovaný výtah';
 const textButton=document.createElement('button');textButton.type='button';textButton.dataset.sourceView='text';textButton.className='secondary-button';textButton.textContent='Původní bounded text';
 const structured=document.createElement('div');structured.className='public-source-structured';structured.setAttribute('role','document');
 const original=document.createElement('pre');original.className='public-source-text';original.hidden=true;
 const detail=document.createElement('small');tabs.append(structuredButton,textButton);result.append(tabs,structured,original,detail);
 result.addEventListener('click',event=>{const button=event.target.closest('[data-source-view]');if(button)selectPublicSourceView(result,button.dataset.sourceView);});
 return result;
}
function renderPublicSourceTimelineEntry(entry){
 const source=entry.source,card=document.createElement('section');card.className='task-outcome terminal public-source-timeline-entry';
 const heading=document.createElement('h3');heading.textContent='Načtená veřejná stránka';
 const title=document.createElement('strong');title.textContent=source.title;
 const url=document.createElement('code');url.textContent=source.url;
 const projection=source.result?.projection;
 const detail=document.createElement('small');detail.textContent=
  `${source.result?.fetched_at || 'čas neuveden'} · run ${source.run_id}${projection?' · '+projection.block_count+' bloků':''}`;
 const actions=document.createElement('div');actions.className='task-actions';
 const button=document.createElement('button');button.type='button';button.textContent='Zobrazit uložený výtah';
 let view=null;
 button.addEventListener('click',async()=>{
  if(view){view.hidden=!view.hidden;button.textContent=view.hidden?'Zobrazit uložený výtah':'Skrýt uložený výtah';return;}
  button.disabled=true;
  try{const fetched=await projectRequest('/v1/tasks/public-source/result',{
    task_id:entry.task_id,run_id:source.run_id});
   view=createPublicSourceResultView();populatePublicSourceResult(view,fetched);card.append(view);
   button.textContent='Skrýt uložený výtah';
  }catch(error){chatOperationStatus.textContent=error.message;}
  finally{button.disabled=false;}
 });
 actions.append(button);card.append(heading,title,url,detail,actions);chatMessages.append(card);
}
function selectPublicSourceView(result,view){
 const structured=result.querySelector('.public-source-structured');
 const original=result.querySelector('.public-source-text');
 structured.hidden=view!=='structured';original.hidden=view!=='text';
 for(const button of result.querySelectorAll('[data-source-view]')){
  const active=button.dataset.sourceView===view;button.setAttribute('aria-pressed',String(active));
  button.classList.toggle('secondary-button',!active);
 }
}
function renderPublicSourceProjection(container,projection){
 container.replaceChildren();if(!projection?.blocks?.length)return;
 if(projection.title){const title=document.createElement('h4');title.textContent=projection.title;container.append(title);}
 let previousPath='';
 for(const block of projection.blocks){
  if(!block || typeof block.type!=='string' || typeof block.anchor!=='string')continue;
  const wrapper=document.createElement('section');wrapper.className='public-source-block';wrapper.dataset.anchor=block.anchor;
  const path=Array.isArray(block.heading_path)?block.heading_path.join(' › '):'';
  if(path && block.type!=='heading' && path!==previousPath){const breadcrumb=document.createElement('small');breadcrumb.textContent=path;wrapper.append(breadcrumb);}
  previousPath=path;
  if(block.type==='heading'){
   const heading=document.createElement(block.level<=2?'h4':block.level<=4?'h5':'h6');heading.textContent=block.text;wrapper.append(heading);
  }else if(block.type==='table' && Array.isArray(block.rows)){
   const scroll=document.createElement('div');scroll.className='public-source-table-wrap';const table=document.createElement('table');table.className='public-source-table';
   if(block.caption){const caption=document.createElement('caption');caption.textContent=block.caption;table.append(caption);}
   const body=document.createElement('tbody'),headers=new Set(block.header_rows || []);
   block.rows.forEach((row,rowIndex)=>{const tr=document.createElement('tr');for(const value of row){const cell=document.createElement(headers.has(rowIndex)?'th':'td');cell.textContent=value;tr.append(cell);}body.append(tr);});
   table.append(body);scroll.append(table);wrapper.append(scroll);
  }else if(block.type==='list-item'){
   wrapper.classList.add('public-source-list-item');wrapper.style.paddingLeft=`${Math.min(Math.max(Number(block.depth)||1,1),16)-1}rem`;
   const marker=document.createElement('span');marker.className='public-source-list-marker';marker.textContent=block.ordered?'1.':'•';const text=document.createElement('span');text.textContent=block.text;wrapper.append(marker,text);
  }else if(block.type==='blockquote'){
   const quote=document.createElement('blockquote');quote.textContent=block.text;wrapper.append(quote);
  }else if(block.type==='pre'){
   const pre=document.createElement('pre');pre.textContent=block.text;wrapper.append(pre);
  }else{
   const text=document.createElement(block.type==='definition-term'?'strong':'p');text.textContent=block.text;wrapper.append(text);
  }
  container.append(wrapper);
 }
}
document.querySelector('#public-source-result').addEventListener('click',event=>{
 const button=event.target.closest('[data-source-view]');if(button)selectPublicSourceView(event.currentTarget,button.dataset.sourceView);
});
async function showPublicSource(taskId,runId){
 chatOperationStatus.textContent='Načítám ověřenou lokální projekci veřejného zdroje…';
 try{const fetched=await projectRequest('/v1/tasks/public-source/result',{
   task_id:taskId,run_id:runId});displayPublicSourceResult(fetched);
  chatOperationStatus.textContent='Zobrazuji durable inertní text; síť nebyla znovu použita.';
 }catch(error){chatOperationStatus.textContent=error.message;}
}
document.querySelector('#public-source-confirm-check').addEventListener('change',event=>{
 document.querySelector('#public-source-confirm').disabled=
  !event.currentTarget.checked || !pendingPublicSourcePreview;
});
document.querySelector('#public-source-cancel').addEventListener('click',()=>{
 pendingPublicSourcePreview=null;document.querySelector('#public-source-preview').hidden=true;
 document.querySelector('#public-source-confirm-check').checked=false;
});
document.querySelector('#public-source-confirm').addEventListener('click',async event=>{
 if(!pendingPublicSourcePreview)return;event.currentTarget.disabled=true;
 const {request,preview}=pendingPublicSourcePreview;
 chatOperationStatus.textContent='Ověřuji robots.txt a načítám jednu bounded statickou stránku…';
 try{const fetched=await withChatProgress('Načítám a bezpečně zpracovávám zdroj…',()=>
   projectRequest('/v1/tasks/public-source/confirm',{
    ...request,preview_sha256:preview.preview_sha256,approved:true},65000));
  displayPublicSourceResult(fetched);
  const owner=taskOutcomes.find(item=>item.task_id===fetched.task_id);
  if(owner){const refreshed=await projectRequest('/v1/tasks/list',{
    project_id:owner.project_id,thread_id:owner.thread_id});
   for(const projection of refreshed.outcomes)replaceTaskProjection(projection);}
  pendingPublicSourcePreview=null;
  document.querySelector('#public-source-confirm-check').checked=false;
  chatOperationStatus.textContent='Veřejný zdroj byl načten jako inertní nedůvěryhodný text.';
 }catch(error){chatOperationStatus.textContent=error.message;event.currentTarget.disabled=false;}
});
document.querySelector('#chat-new-thread').addEventListener('click',()=>{
 if(!activeProject){document.querySelector('#sidebar-chat-status').textContent='Pro nové vlákno nejprve vyberte projekt.';return;}
 hideSearchRecovery();
 ++chatSelectionRevision;pendingChatRequest=null;activeTaskThreadId=crypto.randomUUID();
 taskOutcomes=[];renderTaskPublicSources();renderChat(null);renderThreadList(knownThreads);draft.value='';
 chatOperationStatus.textContent='';
 document.querySelector('#chat-submit').disabled=true;
 chatStatus.textContent=chatBinding ? `Nové vlákno pro projekt ${activeProject.title} · backend: ${chatBindingLabel(chatBinding)}` :
  `Nové vlákno pro projekt ${activeProject.title} · nejprve nastavte backend.`;
 draft.focus();
});
async function openStoredThread(threadId){
 if(!activeProject){document.querySelector('#sidebar-chat-status').textContent='Pro otevření vlákna nejprve vyberte projekt.';return;}
 ++chatSelectionRevision;pendingChatRequest=null;pendingThreadDeletion=null;
 document.querySelector('#chat-delete-preview').hidden=true;
 const thread=knownThreads.find(item=>item.thread_id===threadId);
 if(!thread){chatOperationStatus.textContent='Vyberte uložené vlákno.';return;}
 activeTaskThreadId=thread.thread_id;activeThread=thread;
 document.querySelector('#chat-mode').value=thread.classification;refreshChatModeControls();
 selectMainTab(document.querySelector('#chat-tab'));renderThreadList(knownThreads);
 try{const tasks=thread.project_id ? await projectRequest('/v1/tasks/list',{
   project_id:thread.project_id,thread_id:thread.thread_id}) : {outcomes:[]};
  taskOutcomes=tasks.outcomes;await loadAutonomyQueue(false);
  renderTaskPublicSources();renderChat(thread);
  chatOperationStatus.textContent=`Navázáno na ${thread.status==='archived'?'archivované':'aktivní'} uložené vlákno.`;
 }catch(error){chatOperationStatus.textContent=error.message;}
}
async function archiveActiveThread(button){
 if(!activeThread)return;if(button)button.disabled=true;
 try{const archived=await projectRequest('/v1/chat/archive',{
   thread_id:activeThread.thread_id,expected_revision:activeThread.revision});
  activeThread=archived;const index=knownThreads.findIndex(item=>item.thread_id===archived.thread_id);
  if(index>=0)knownThreads[index]=archived;renderThreadList(knownThreads);renderChat(archived);
  chatOperationStatus.textContent='Vlákno bylo archivováno a zůstává lokálně uložené.';
 }catch(error){chatOperationStatus.textContent=error.message;if(button)button.disabled=false;}
}
async function prepareActiveThreadDeletion(button){
 if(!activeThread)return;if(button)button.disabled=true;chatOperationStatus.textContent='Připravuji přesný rozsah smazání…';
 try{const preview=await projectRequest('/v1/chat/delete/preview',{thread_id:activeThread.thread_id});
  pendingThreadDeletion={preview,operation_id:crypto.randomUUID()};
  document.querySelector('#chat-delete-details').textContent=JSON.stringify({
   lokální_záznamy:preview.counts,blokace:preview.blockers,
   zachované_Git_artefakty:preview.published_artifacts},null,2);
  document.querySelector('#chat-delete-preview').hidden=false;
  document.querySelector('#chat-delete-confirm').checked=false;
  document.querySelector('#chat-delete-run').disabled=true;
  chatOperationStatus.textContent=preview.blockers.length?
   'Smazání blokuje aktivní nebo neznámý účinek.':'Zkontrolujte rozsah a potvrďte smazání.';
 }catch(error){chatOperationStatus.textContent=error.message;if(button)button.disabled=false;}
}
document.querySelector('#chat-delete-confirm').addEventListener('change',event=>{
 document.querySelector('#chat-delete-run').disabled=!event.currentTarget.checked ||
  !pendingThreadDeletion || pendingThreadDeletion.preview.blockers.length>0;
});
document.querySelector('#chat-delete-cancel').addEventListener('click',()=>{
 pendingThreadDeletion=null;document.querySelector('#chat-delete-preview').hidden=true;
});
document.querySelector('#chat-delete-run').addEventListener('click',async event=>{
 if(!pendingThreadDeletion)return;event.currentTarget.disabled=true;
 const {preview,operation_id}=pendingThreadDeletion;
 try{await projectRequest('/v1/chat/delete/confirm',{thread_id:preview.thread_id,operation_id,
   expected_revision:preview.expected_revision,preview_sha256:preview.preview_sha256});
  knownThreads=knownThreads.filter(item=>item.thread_id!==preview.thread_id);
  pendingThreadDeletion=null;activeTaskThreadId=null;taskOutcomes=[];
  document.querySelector('#chat-delete-preview').hidden=true;renderThreadList(knownThreads);renderChat(null);
  chatOperationStatus.textContent='Lokální vlákno a jeho podporovaný navázaný stav byly odstraněny. Git historie zůstala zachovaná.';
 }catch(error){chatOperationStatus.textContent=error.message;event.currentTarget.disabled=false;}
});
function chatBindingLabel(binding){
 const boundary=binding.boundary==='private-network'?'Privátní síť':'Stejný počítač';
 return `${binding.model} · ${boundary} · ${binding.endpoint}`;
}
function fillBinding(binding,draft=null,draftState=null){
 chatBinding=binding;const fields=chatForm.elements,candidate=draft || binding;
 renderLocalProviderAvailability(binding);
 if(candidate){fields.boundary.value=candidate.boundary;fields.endpoint.value=candidate.endpoint;
  fields.model.value=candidate.model;fields.target_id.value=candidate.target_id;
  fields.tls_cert_sha256.value=candidate.tls_cert_sha256 || '';
 }
 if(binding){
  chatStatus.textContent=`Backend: ${chatBindingLabel(binding)}`;
  settingsBackendStatus.textContent=draftState && draftState!=='confirmed' ?
   `Aktivní je ${chatBindingLabel(binding)}; formulář obsahuje ${draftState==='invalid'?'neplatný':'nepotvrzený'} uložený koncept.` :
   `Nastaven backend ${chatBindingLabel(binding)}.`;
  if(!document.querySelector('#workflow-creator-model').value)document.querySelector('#workflow-creator-model').value=binding.model;
  if(!document.querySelector('#workflow-opponent-model').value)document.querySelector('#workflow-opponent-model').value=binding.model;
 }else{
  chatStatus.textContent='Backend zatím není nastaven.';
  settingsBackendStatus.textContent=draft ? 'Formulář obsahuje uložený nepotvrzený koncept.' :
   'Backend zatím není nastaven.';
 }
 refreshChatModeControls();
}
function fillSearchBinding(binding){
 searchBinding=binding;const fields=searchForm.elements;
 if(binding){fields.boundary.value=binding.boundary;fields.endpoint.value=binding.endpoint;
  fields.target_id.value=binding.target_id;fields.result_limit.value=binding.result_limit;
  fields.timeout_seconds.value=binding.timeout_seconds;
  fields.tls_cert_sha256.value=binding.tls_cert_sha256 || '';
  settingsSearchStatus.textContent=`SearXNG ${binding.boundary==='same-node'?'na tomto počítači':'v privátní síti'} · ${binding.endpoint} · nejvýše ${binding.result_limit} výsledků.`;
 }else settingsSearchStatus.textContent='SearXNG zatím není nastaveno.';
}
function applyOllamaStreamingStatus(result){
 ollamaStreamingSupported=result.capabilities?.streaming===true;
 const enabled=result.preferences?.streaming!==false;
 ollamaStreaming=ollamaStreamingSupported&&enabled;
 ollamaStreamingToggle.checked=ollamaStreaming;
 ollamaStreamingToggle.disabled=!ollamaStreamingSupported;
 ollamaStreamingState.textContent=!ollamaStreamingSupported ?
  'Streamování tento backend nepodporuje.' :
  (ollamaStreaming?'Streamování je zapnuto.':'Streamování je vypnuto; odpověď se zobrazí až celá.');
}
let responseLanguagePolicy=null;
function applyResponseLanguageStatus(result){
 const policy=result.response_language_policy;
 if(!policy)return;
 responseLanguagePolicy=policy;
 const select=document.querySelector('#chat-response-language');
 const inherited=activeThread?.response_language || policy.projects?.[activeProject?.id] || policy.node_default;
 select.options[0].textContent=`Výchozí · ${inherited}`;
 select.title='Prázdná volba dědí jazyk vlákna, projektu a uzlu. Konkrétní volba platí pro tento běh.';
 const settingsTag=document.querySelector('#response-language-tag');
 if(document.activeElement!==settingsTag)settingsTag.value=inherited;
 responseLanguageState.textContent=`Účinný jazyk: ${inherited}. Shoda výstupu se automaticky negarantuje ani skrytě neopravuje.`;
}
async function loadBackendBinding(){
 try{const result=await projectRequest('/v1/chat/status',{});
  fillBinding(result.binding,result.binding_draft,result.binding_draft_state);
  fillSearchBinding(result.search_binding);
  applyOllamaStreamingStatus(result);
  applyResponseLanguageStatus(result);
  const external=await projectRequest('/v1/external/status',{});
  externalBinding=external.binding;
  externalStreaming=external.capabilities?.streaming===true;
  refreshChatModeControls();
  fillExternalModels(external.model_catalog);
  settingsExternalStatus.textContent=external.binding ?
   `Nastaven externí backend ${external.binding.model}; klíč ${external.credential?.available?'je uložen':'chybí'}.` :
   'Externí backend zatím není nastaven.';
  const media=await projectRequest('/v1/media/status',{}),comfy=media.bindings?.comfyui;
  document.querySelector('#settings-comfy-status').textContent=comfy ?
   `ComfyUI ${comfy.workflow_revision} · ${comfy.boundary} · ${comfy.endpoint}` :
   'ComfyUI zatím není nastaveno.';
  const openaiImage=media.bindings?.['openai-images'];
  document.querySelector('#settings-openai-image-status').textContent=openaiImage ?
   `OpenAI Images ${openaiImage.model} · ${openaiImage.revision}` :
   'OpenAI Images zatím není nastaveno.';
  const drive=await projectRequest('/v1/google-drive/status',{});
  settingsGoogleDriveStatus.textContent=drive.configured ?
   `OAuth klient je uložen · scope drive.file · konfigurace ${drive.credential_revision} · ${drive.client_id_hint}.` :
   'Google OAuth klient zatím není nastaven.';
  if(!document.querySelector('#backend-metrics').hidden)await loadBackendMetrics();
  return true;}
 catch(error){settingsBackendStatus.textContent=error.message;return false;}
}
function renderBackendMetrics(result){
 const report=document.querySelector('#backend-metrics-report');
 if(!result?.report){backendMetricsStatus.textContent=result?.credential?.available ?
  'Administrátorský klíč je uložen; přehled zatím nebyl načten.' :
  'Administrátorský klíč není uložen.';report.hidden=true;
  backendMetricsIndicator.textContent='OpenAI · nenačteno';
  resourceOpenAIDetail.textContent=result?.credential?.available ?
   'Administrátorský klíč je uložen; spotřeba zatím nebyla načtena.' :
   'Účetní přehled není nakonfigurován.';return;}
 const metricStates={unauthorized:'Administrátorský klíč byl odmítnut (HTTP 401).',
  forbidden:'Klíč nemá oprávnění k účetnímu přehledu (HTTP 403).',
  'rate-limited':'OpenAI dočasně omezilo načítání přehledu (HTTP 429).',
  unavailable:'Účetní přehled je dočasně nedostupný.'};
 backendMetricsStatus.textContent=result.report.status==='available' ?
  `Přehled aktualizován ${result.report.fetched_at}.` : result.report.status==='stale' ?
  `Zobrazuji poslední platný přehled; obnova selhala: ${metricStates[result.report.refresh_error] || result.report.refresh_error}.` :
  (metricStates[result.report.status] || `Přehled má stav ${result.report.status}.`);
 report.textContent=JSON.stringify(result.report,null,2);report.hidden=false;
 const metrics=(result.report.reports || []).flatMap(item=>item.metrics || []);
 const tokens=metrics.filter(item=>item.unit==='tokens').reduce((sum,item)=>sum+item.value,0);
 const costs=metrics.filter(item=>item.name==='cost')
  .map(item=>`${item.value} ${String(item.currency || '').toUpperCase()}`);
 const parts=[...costs,tokens ? `${tokens} tokenů` : ''].filter(Boolean);
 backendMetricsIndicator.textContent=`OpenAI · ${result.report.status}`+(parts.length ? ` · ${parts.join(' · ')}` : '');
 backendMetricsIndicator.title=`Poslední načtení: ${result.report.fetched_at}`;
 resourceOpenAIDetail.textContent=`Stav: ${result.report.status}. `+
  (parts.length ? parts.join(' · ') : 'Přehled neobsahuje agregovanou spotřebu.')+
  ` Poslední načtení: ${result.report.fetched_at}.`;
}
async function loadBackendMetrics(){
 try{renderBackendMetrics(await projectRequest('/v1/backend-metrics/status',{}));}
 catch(error){backendMetricsStatus.textContent=error.message;}
}
document.querySelector('#backend-metrics-form').addEventListener('submit',async event=>{
 event.preventDefault();const secret=event.currentTarget.elements.secret;
 try{backendMetricsStatus.textContent='Ukládám administrátorský klíč…';
  const result=await projectRequest('/v1/backend-metrics/configure',{secret:secret.value});
  secret.value='';renderBackendMetrics(result);
 }catch(error){secret.value='';backendMetricsStatus.textContent=error.message;}
});
function stableJson(value){if(Array.isArray(value))return '['+value.map(stableJson).join(',')+']';
 if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+stableJson(value[key])).join(',')+'}';
 return JSON.stringify(value);}
document.querySelector('#comfy-backend-form').addEventListener('submit',async event=>{
 event.preventDefault();const fields=event.currentTarget.elements,status=document.querySelector('#settings-comfy-status');
 try{const workflow=JSON.parse(fields.workflow.value),parameters=JSON.parse(fields.parameters.value);
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(stableJson(workflow)));
  const boundary=fields.boundary.value,binding={schema_version:1,binding_id:crypto.randomUUID(),
   revision:crypto.randomUUID(),adapter:'comfyui',boundary,endpoint:fields.endpoint.value.trim(),
   target_id:boundary==='same-node'?'local-process':fields.target_id.value.trim(),
   workflow_revision:fields.workflow_revision.value.trim(),workflow_sha256:[...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join(''),
   workflow,parameters,output_node_id:fields.output_node_id.value.trim(),timeout_seconds:Number(fields.timeout_seconds.value)};
  if(boundary==='private-network')binding.tls_cert_sha256=fields.tls_cert_sha256.value.trim();
  status.textContent='Ukládám ComfyUI…';const result=await projectRequest('/v1/media/comfyui/configure',binding);
  status.textContent=`ComfyUI ${result.binding.workflow_revision} bylo uloženo.`;
 }catch(error){status.textContent=error.message;}
});
document.querySelector('#openai-image-form').addEventListener('submit',async event=>{
 event.preventDefault();const fields=event.currentTarget.elements;
 const status=document.querySelector('#settings-openai-image-status');
 try{status.textContent='Ukládám OpenAI Images binding…';
  const result=await projectRequest('/v1/media/openai/configure',{
   model:fields.model.value.trim(),timeout_seconds:Number(fields.timeout_seconds.value)});
  status.textContent=`OpenAI Images ${result.binding.model} bylo uloženo.`;
 }catch(error){status.textContent=error.message;}
});
document.querySelector('#backend-metrics-refresh').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;backendMetricsStatus.textContent='Načítám účetní přehled…';
 const end=Math.floor(Date.now()/1000),start=end-30*86400;
 try{const report=await projectRequest('/v1/backend-metrics/refresh',{start_time:start,end_time:end},210000);
  renderBackendMetrics({credential:{available:true},report});
 }catch(error){backendMetricsStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
function refreshChatModeControls(){
 const mode=document.querySelector('#chat-mode').value;
 const adapter=document.querySelector('#chat-run-adapter');
 const model=document.querySelector('#chat-run-model');
 const artifacts=document.querySelector('#task-artifacts');
 const action=document.querySelector('#task-action');
 const output=document.querySelector('#task-output-kind');
 const ollamaOption=adapter.querySelector('option[value="ollama"]');
 const target=document.querySelector('#chat-orchestration-target');
 const routing=document.querySelector('#task-routing');
 const artifactSource=document.querySelector('#task-source-artifacts');
 const publicSource=document.querySelector('#task-source-public');
 const publicSources=document.querySelector('#task-public-sources');
 const currentPromptSource=document.querySelector('#task-source-current-prompt');
 const conversationSource=document.querySelector('#task-source-conversation-label');
 const artifactSourceLabel=document.querySelector('#task-source-artifacts-label');
 const publicSourceLabel=document.querySelector('#task-source-public-label');
 const lan=chatBinding?.boundary==='private-network';
 ollamaOption.textContent=lan?'Ollama v privátní síti':'Ollama na tomto uzlu';
 if(mode==='orchestration'){
  adapter.disabled=false;routing.hidden=false;
  const external=adapter.value==='openai-responses';
  model.value=external ? (externalBinding?.model || model.value) : (chatBinding?.model || '');
  model.disabled=!external;
  artifactSource.disabled=external;
  if(external){artifactSource.checked=false;for(const input of document.querySelectorAll('#task-artifact-list input'))input.checked=false;}
  action.value=publicSource.checked?'search':'answer';
  const searching=action.value==='search';
  refreshCurrentFileSource();
  currentPromptSource.hidden=!searching;
  conversationSource.hidden=searching;artifactSourceLabel.hidden=searching;publicSourceLabel.hidden=searching;
  artifacts.hidden=searching||!artifactSource.checked;publicSources.hidden=true;publicSource.disabled=searching;
  if(searching){
   if(!output.disabled)output.dataset.beforeSearch=output.value;
   output.value='conversation';output.disabled=true;
  }else{
   output.disabled=false;
   if(output.dataset.beforeSearch){output.value=output.dataset.beforeSearch;delete output.dataset.beforeSearch;}
  }
  const warnings=[];
  if(publicSource.checked&&!searchBinding)warnings.push('Pro vyhledávání nejprve nastavte SearXNG.');
  if(external&&!externalBinding)warnings.push('Externí úkol vyžaduje nejprve nastavit OpenAI backend.');
  if(!external&&!chatBinding)warnings.push('Lokální úkol vyžaduje nejprve nastavit Ollama backend.');
  target.textContent=warnings.join(' ');target.hidden=!warnings.length;
 }else{
  target.hidden=true;target.textContent='';
  adapter.disabled=false;model.disabled=false;routing.hidden=true;artifacts.hidden=true;
  currentPromptSource.hidden=true;conversationSource.hidden=false;artifactSourceLabel.hidden=false;publicSourceLabel.hidden=false;
  publicSource.disabled=false;output.disabled=false;
  if(output.dataset.beforeSearch){output.value=output.dataset.beforeSearch;delete output.dataset.beforeSearch;}
  for(const input of document.querySelectorAll('#task-artifact-list input'))input.checked=false;
  if(!model.value)model.value=adapter.value==='openai-responses' ? (externalBinding?.model || '') : (chatBinding?.model || '');
 }
 updatePromptInputSummary();
}
document.querySelector('#chat-run-adapter').addEventListener('change',event=>{
 document.querySelector('#chat-run-model').value=event.currentTarget.value==='openai-responses' ?
  (externalBinding?.model || '') : (chatBinding?.model || '');
 refreshChatModeControls();
});
document.querySelector('#task-action').addEventListener('change',event=>{
 document.querySelector('#task-source-public').checked=event.currentTarget.value==='search';
 renderTaskPublicSources();refreshChatModeControls();
});
document.querySelector('#task-source-conversation').addEventListener('change',updatePromptInputSummary);
document.querySelector('#task-source-current-file-input').addEventListener('change',updatePromptInputSummary);
document.querySelector('#task-source-artifacts').addEventListener('change',refreshChatModeControls);
document.querySelector('#task-source-public').addEventListener('change',()=>{
 renderTaskPublicSources();refreshChatModeControls();
});
document.querySelector('#task-artifact-list').addEventListener('change',updatePromptInputSummary);
document.querySelector('#task-public-source-list').addEventListener('change',updatePromptInputSummary);
const taskInputs=document.querySelector('#task-inputs');
taskInputs.addEventListener('toggle',()=>promptForm.classList.toggle('inputs-open',taskInputs.open));
taskInputs.addEventListener('keydown',event=>{
 if(event.key==='Escape'&&taskInputs.open){event.preventDefault();taskInputs.open=false;taskInputs.querySelector('summary').focus();}
});
document.querySelector('#chat-mode').addEventListener('change',async event=>{
 pendingChatRequest=null;const mode=event.currentTarget.value;
 if(mode==='orchestration' && activeThread?.classification==='brainstorming'){
  try{activeThread=await projectRequest('/v1/chat/orchestration',{
    source_thread_id:activeThread.thread_id,thread_id:crypto.randomUUID(),created_at:new Date().toISOString()});
   activeTaskThreadId=activeThread.thread_id;taskOutcomes=[];renderTaskPublicSources();renderChat(activeThread);rememberThread(activeThread);
  }catch(error){event.currentTarget.value='brainstorming';chatOperationStatus.textContent=error.message;}
 }else{activeThread=null;activeTaskThreadId=crypto.randomUUID();taskOutcomes=[];renderTaskPublicSources();renderChat(null);renderThreadList(knownThreads);}
 refreshChatModeControls();
});
async function loadChat(){
 const selectionRevision=chatSelectionRevision;
 const projectId=activeProject?.id || null;
 try{
  const [result,external,tasks]=await Promise.all([
   projectRequest('/v1/chat/status',{}),projectRequest('/v1/external/status',{}),
   projectId?projectRequest('/v1/tasks/list',{project_id:projectId}):Promise.resolve({outcomes:[]})]);
  fillBinding(result.binding,result.binding_draft,result.binding_draft_state);
  fillSearchBinding(result.search_binding);
  applyOllamaStreamingStatus(result);
  externalBinding=external.binding;
  externalStreaming=external.capabilities?.streaming===true;
  fillExternalModels(external.model_catalog);
  if(selectionRevision!==chatSelectionRevision)return;
  if(projectId!==(activeProject?.id || null))return;
  const ordered=[...result.threads].reverse();
  const projectThreads=projectId?ordered.filter(thread=>thread.project_id===projectId):[];
  const restored=projectThreads.find(thread=>thread.status==='active') || projectThreads[0] || null;
  activeThread=restored;activeTaskThreadId=restored?.thread_id || null;
  taskOutcomes=restored?tasks.outcomes.filter(item=>item.thread_id===restored.thread_id):[];
  renderThreadList(ordered);renderTaskPublicSources();renderChat(restored);
  if(restored){document.querySelector('#chat-mode').value=restored.classification;refreshChatModeControls();}
  const queueLoaded=!projectId || await loadAutonomyQueue(false);
  if(queueLoaded)chatOperationStatus.textContent=restored?
   'Obnoveno poslední uložené vlákno projektu. Rozpracovaná automatika po restartu zůstává bezpečně pozastavená.':'';
 }catch(error){if(selectionRevision===chatSelectionRevision){chatStatus.textContent=error.message;renderChat(null);}}
}
function backendCandidate(){
 const fields=chatForm.elements;
 const boundary=fields.boundary.value;
 const binding={schema_version:1,binding_id:chatBinding?.binding_id || crypto.randomUUID(),
  revision:crypto.randomUUID(),adapter:'ollama',boundary,endpoint:fields.endpoint.value.trim(),
  model:fields.model.value.trim(),target_id:boundary==='same-node'?'local-process':fields.target_id.value.trim()};
 if(boundary==='private-network')binding.tls_cert_sha256=normalizeFingerprint(fields.tls_cert_sha256.value);
 return binding;
}
function normalizeFingerprint(value){return value.trim()
 .replace(/^sha256\\s*fingerprint\\s*=\\s*/i,'').replaceAll(':','').toLowerCase();}
function searchCandidate(){
 const fields=searchForm.elements,boundary=fields.boundary.value;
 const binding={schema_version:1,binding_id:searchBinding?.binding_id || crypto.randomUUID(),
  revision:crypto.randomUUID(),adapter:'searxng',boundary,
  endpoint:fields.endpoint.value.trim(),target_id:boundary==='same-node'?'local-process':fields.target_id.value.trim(),
  result_limit:Number(fields.result_limit.value),timeout_seconds:Number(fields.timeout_seconds.value)};
 if(boundary==='private-network')binding.tls_cert_sha256=normalizeFingerprint(fields.tls_cert_sha256.value);
 return binding;
}
document.querySelector('#search-backend-test').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;settingsSearchStatus.textContent='Odesílám pevný testovací dotaz „SearXNG“…';
 try{const result=await projectRequest('/v1/search/test',searchCandidate(),65000);
  settingsSearchStatus.textContent=`SearXNG je dostupné; test vrátil ${result.result_count} bounded výsledků. Uložené nastavení nebylo změněno.`;}
 catch(error){settingsSearchStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
searchForm.addEventListener('submit',async event=>{
 event.preventDefault();settingsSearchStatus.textContent='Ukládám SearXNG binding…';
 try{const result=await projectRequest('/v1/search/configure',searchCandidate());
  fillSearchBinding(result.binding);hideSearchRecovery();
  settingsSearchStatus.textContent=`SearXNG ${result.binding.endpoint} bylo uloženo.`;}
 catch(error){settingsSearchStatus.textContent=error.message;}
});
document.querySelector('#google-drive-config-form').addEventListener('submit',async event=>{
 event.preventDefault();const fields=event.currentTarget.elements;
 settingsGoogleDriveStatus.textContent='Ukládám Google OAuth klienta pouze na tomto uzlu…';
 try{const result=await projectRequest('/v1/google-drive/configure',{
   client_id:fields.client_id.value.trim(),client_secret:fields.client_secret.value});
  fields.client_secret.value='';settingsGoogleDriveStatus.textContent=
   `OAuth klient je uložen · scope drive.file · konfigurace ${result.credential_revision} · ${result.client_id_hint}.`;
 }catch(error){fields.client_secret.value='';settingsGoogleDriveStatus.textContent=error.message;}
});
document.querySelector('#chat-backend-test').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;settingsBackendStatus.textContent='Ověřuji endpoint bez odeslání projektových dat…';
 try{const result=await projectRequest('/v1/chat/test',backendCandidate(),15000);
  localProviderIndicator.textContent=result.model_available ? 'Lokální AI · dostupná' : 'Lokální AI · dostupná, model chybí';
  localProviderAvailability.textContent=result.model_available ?
   `Dostupný · model ${result.model} je připraven.` :
   `Dostupný · model ${result.model} není nainstalován.`;
  settingsBackendStatus.textContent=result.model_available ?
   `Ollama je dostupná a model ${result.model} je připraven.` :
   `Ollama je dostupná, ale model ${result.model} není mezi ${result.model_count} dostupnými modely.`;
 }catch(error){localProviderIndicator.textContent='Lokální AI · nedostupná';localProviderAvailability.textContent='Nedostupný · poslední ověření selhalo.';settingsBackendStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
ollamaStreamingToggle.addEventListener('change',async event=>{
 const requested=event.currentTarget.checked;event.currentTarget.disabled=true;
 ollamaStreamingState.textContent='Ukládám nastavení streamování…';
 try{const result=await projectRequest('/v1/chat/preferences',{streaming:requested});
  applyOllamaStreamingStatus(result);
 }catch(error){event.currentTarget.checked=ollamaStreaming;
  event.currentTarget.disabled=!ollamaStreamingSupported;
  ollamaStreamingState.textContent=error.message;}
});
document.querySelector('#response-language-save').addEventListener('click',async event=>{
 const scope=document.querySelector('#response-language-scope').value;
 const request={scope,tag:document.querySelector('#response-language-tag').value.trim()};
 if(scope==='project'){
  if(!activeProject){responseLanguageState.textContent='Nejprve otevřete projekt.';return;}
  request.project_id=activeProject.id;
 }
 if(scope==='thread'){
  if(!activeThread){responseLanguageState.textContent='Nejprve otevřete vlákno.';return;}
  request.thread_id=activeThread.thread_id;request.expected_revision=activeThread.revision;
 }
 event.currentTarget.disabled=true;responseLanguageState.textContent='Ukládám jazykovou preferenci…';
 try{const result=await projectRequest('/v1/chat/response-language',request);
  if(result.thread){activeThread=result.thread;rememberThread(result.thread);renderChat(result.thread);}
  applyResponseLanguageStatus({response_language_policy:result.policy});
  responseLanguageState.textContent=`Uloženo ${result.tag} pro úroveň ${scope}. Model může požadavek nedodržet; výstup se nepřekládá.`;
 }catch(error){responseLanguageState.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
chatForm.addEventListener('submit',async event=>{
 event.preventDefault();const binding=backendCandidate();
 settingsBackendStatus.textContent='Ukládám backend…';
 try{const result=await projectRequest('/v1/chat/configure',binding);
  fillBinding(result.binding,result.binding_draft,result.binding_draft_state);
  settingsBackendStatus.textContent=`Backend ${result.binding.model} byl uložen.`;}
 catch(error){
  const message=error.message;const reloaded=await loadBackendBinding();
  settingsBackendStatus.textContent=reloaded ? message+' Poslední potvrzené nastavení bylo znovu načteno.' :
   message+' Aktuální stav nelze potvrdit; zkuste nastavení znovu otevřít.';
 }
});
document.querySelector('#external-backend-form').addEventListener('submit',async event=>{
 event.preventDefault();const form=event.currentTarget,fields=form.elements;
 const binding={schema_version:1,binding_id:crypto.randomUUID(),revision:crypto.randomUUID(),
  adapter:'openai-responses',boundary:'external-provider',endpoint:fields.endpoint.value,
  model:fields.model.value.trim(),target_id:'api.openai.com',
  max_output_tokens:Number(fields.max_output_tokens.value),
  timeout_seconds:Number(fields.timeout_seconds.value),secret:fields.secret.value};
 settingsExternalStatus.textContent='Ukládám externí backend…';
 try{const result=await projectRequest('/v1/external/configure',binding);
  fields.secret.value='';settingsExternalStatus.textContent=
   `Externí backend ${result.binding.model} byl uložen; klíč server nevrátil.`;}
 catch(error){fields.secret.value='';settingsExternalStatus.textContent=error.message;}
});
document.querySelector('#external-load-models').addEventListener('click',async event=>{
 event.currentTarget.disabled=true;settingsExternalStatus.textContent='Načítám dostupné modely…';
 try{const result=await projectRequest('/v1/external/models',{});
  fillExternalModels(result);
  settingsExternalStatus.textContent=`Načteno ${result.models.length} kandidátů pro textový Responses backend · ${result.fetched_at}. Ruční ID zůstává povoleno.`;
 }catch(error){settingsExternalStatus.textContent=error.message+' Uložené nastavení nebylo změněno.';}
 finally{event.currentTarget.disabled=false;}
});
draft.addEventListener('input',()=>{
 const disabled=!activeProject || !draft.value.trim() || !threadWritable();
 document.querySelector('#chat-submit').disabled=disabled;
 document.querySelector('#external-propose-button').disabled=disabled;
 document.querySelector('#external-preview-button').disabled=disabled;
});
async function showExternalPreview(request){
 chatOperationStatus.textContent='Připravuji přesný externí náhled…';
 try{const preview=await projectRequest('/v1/external/preview',request);
  pendingExternalPreview={request,preview};
  document.querySelector('#external-preview-content').textContent=JSON.stringify(preview,null,2);
  document.querySelector('#external-preview').hidden=false;
  document.querySelector('#external-privacy-confirm').checked=false;
  document.querySelector('#external-confirm').disabled=true;
  chatOperationStatus.textContent='Externí požadavek ještě nebyl odeslán. Zkontrolujte náhled.';
 }catch(error){chatOperationStatus.textContent=error.message;}
}
document.querySelector('#external-preview-button').addEventListener('click',async event=>{
 if(!activeProject || !draft.value.trim())return;selectMainTab(document.querySelector('#chat-tab'));
 const request={approval_id:crypto.randomUUID(),project_id:activeProject.id,
  expected_head:activeProject.head,thread_id:activeThread?.thread_id || crypto.randomUUID(),
  turn_id:crypto.randomUUID(),message_id:crypto.randomUUID(),run_id:crypto.randomUUID(),
  manifest_id:crypto.randomUUID(),assistant_message_id:crypto.randomUUID(),
  selected_message_ids:(activeThread?.messages || []).map(item=>item.message_id),
  content:draft.value,privacy:document.querySelector('#chat-privacy').value,
  created_at:new Date().toISOString()};
 event.currentTarget.disabled=true;await showExternalPreview(request);
 event.currentTarget.disabled=!activeProject || !draft.value.trim();
});
document.querySelector('#external-propose-button').addEventListener('click',async event=>{
 if(!activeProject || !draft.value.trim())return;selectMainTab(document.querySelector('#chat-tab'));
 const request={proposal_id:crypto.randomUUID(),project_id:activeProject.id,
  expected_head:activeProject.head,thread_id:activeThread?.thread_id || crypto.randomUUID(),
  message_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
  selected_message_ids:(activeThread?.messages || []).map(item=>item.message_id),
  content:draft.value,privacy:document.querySelector('#chat-privacy').value,
  created_at:new Date().toISOString()};
 event.currentTarget.disabled=true;chatOperationStatus.textContent='Ollama připravuje návrh externího volání…';
 try{const result=await projectRequest('/v1/external/propose',request,210000);
  pendingExternalProposal={request,result};
  document.querySelector('#external-proposal-purpose').textContent=result.proposal.purpose;
  const list=document.querySelector('#external-proposal-messages');list.replaceChildren();
  for(const messageId of result.source.available_message_ids){
   const prior=(activeThread?.messages || []).find(item=>item.message_id===messageId);
   const label=document.createElement('label'),check=document.createElement('input');
   check.type='checkbox';check.value=messageId;
   check.checked=result.proposal.message_ids.includes(messageId);
   if(messageId===request.message_id){check.checked=true;check.disabled=true;}
   label.append(check,document.createTextNode(' '+(prior?.content || request.content)));list.append(label);
  }
  document.querySelector('#external-proposal').hidden=false;
  chatOperationStatus.textContent='Ollama pouze navrhla výběr. Zkontrolujte nebo upravte jej.';
 }catch(error){chatOperationStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=!activeProject || !draft.value.trim();}
});
document.querySelector('#external-proposal-use').addEventListener('click',async()=>{
 if(!pendingExternalProposal)return;
 const {request}=pendingExternalProposal;
 const selected=[...document.querySelectorAll('#external-proposal-messages input:checked')]
  .map(item=>item.value).filter(value=>value!==request.message_id);
 const external={approval_id:crypto.randomUUID(),project_id:request.project_id,
  expected_head:request.expected_head,thread_id:request.thread_id,
  turn_id:crypto.randomUUID(),message_id:request.message_id,run_id:crypto.randomUUID(),
  manifest_id:crypto.randomUUID(),assistant_message_id:crypto.randomUUID(),
  selected_message_ids:selected,content:request.content,privacy:request.privacy,
  created_at:request.created_at};
 document.querySelector('#external-proposal').hidden=true;await showExternalPreview(external);
});
document.querySelector('#external-proposal-cancel').addEventListener('click',()=>{
 pendingExternalProposal=null;document.querySelector('#external-proposal').hidden=true;
 chatOperationStatus.textContent='Návrh Ollamy byl zahozen; nic nebylo odesláno externě.';
});
document.querySelector('#external-privacy-confirm').addEventListener('change',event=>{
 document.querySelector('#external-confirm').disabled=!event.currentTarget.checked;
});
document.querySelector('#external-cancel').addEventListener('click',async()=>{
 if(!pendingExternalPreview)return;
 try{if(pendingExternalPreview.task){
    const result=await projectRequest('/v1/tasks/external/cancel',{
     task_id:pendingExternalPreview.taskId,
     approval_id:pendingExternalPreview.preview.approval_id});
    replaceTaskProjection(result.projection);
   }else await projectRequest('/v1/external/cancel',
    {approval_id:pendingExternalPreview.preview.approval_id});
  pendingExternalPreview=null;document.querySelector('#external-preview').hidden=true;
  chatOperationStatus.textContent='Externí odeslání bylo zrušeno.';
 }catch(error){chatOperationStatus.textContent=error.message;}
});
document.querySelector('#external-confirm').addEventListener('click',async event=>{
 if(!pendingExternalPreview)return;event.currentTarget.disabled=true;
 chatOperationStatus.textContent='Odesílám potvrzený požadavek do OpenAI…';
 const preview=pendingExternalPreview.preview;
 try{if(pendingExternalPreview.task){
    const projection=await projectRequest('/v1/tasks/external/confirm',{
     task_id:pendingExternalPreview.taskId,approval_id:preview.approval_id,
     preview_sha256:preview.preview_sha256,approved:true,privacy:preview.privacy},210000);
    replaceTaskProjection(projection);
   }else{
    const result=await projectRequest('/v1/external/confirm',
     {approval_id:preview.approval_id,preview_sha256:preview.preview_sha256,
      approved:true,privacy:preview.privacy},210000);
    activeThread=result.thread;renderChat(result.thread);rememberThread(result.thread);renderRunUsage(result.usage_report);draft.value='';
   }
  pendingExternalPreview=null;
  document.querySelector('#external-preview').hidden=true;
  document.querySelector('#chat-submit').disabled=true;
  document.querySelector('#external-propose-button').disabled=true;
  document.querySelector('#external-preview-button').disabled=true;
  chatOperationStatus.textContent='Externí odpověď byla přijata.';
 }catch(error){chatOperationStatus.textContent=error.message;}
});
document.querySelector('#chat-composer').addEventListener('submit',async event=>{
 event.preventDefault();if(!activeProject || !draft.value.trim())return;
 if(!threadWritable()){
  chatOperationStatus.textContent='Archivované vlákno nebo vlákno jiného projektu je pouze pro čtení.';return;
 }
 selectMainTab(document.querySelector('#chat-tab'));
 const mode=document.querySelector('#chat-mode').value;
 const adapter=document.querySelector('#chat-run-adapter').value;
 if(adapter==='ollama' && !chatBinding){chatOperationStatus.textContent='Nejprve uložte nastavení Ollama backendu.';return;}
 if(adapter==='openai-responses' && !externalBinding){chatOperationStatus.textContent='Nejprve uložte nastavení OpenAI backendu.';return;}
 const model=document.querySelector('#chat-run-model').value.trim();
 if(!model){chatOperationStatus.textContent='Vyberte model běhu.';return;}
 const runChoice={mode,adapter,model:mode==='orchestration' && adapter==='ollama'?null:model};
 const responseLanguage=document.querySelector('#chat-response-language').value || null;
 if(mode==='orchestration'){
  if(adapter==='ollama'){
   runChoice.binding_id=chatBinding.binding_id;runChoice.binding_revision=chatBinding.revision;
  }
 }
 const searchContinuation=activeSearchContinuation();
 if(mode==='orchestration' && searchContinuation){
  const submit=document.querySelector('#chat-submit');submit.disabled=true;
  const prepared=await prepareTaskSearch(searchContinuation.projection,draft.value.trim(),
                                         searchContinuation.round.search_id);
  if(prepared){draft.value='';draft.focus();}
  submit.disabled=!activeProject || !draft.value.trim();return;
 }
 if(adapter==='ollama' && chatBinding.boundary==='private-network'){
  if(document.querySelector('#chat-privacy').value==='local-only'){
   chatOperationStatus.textContent='Obsah Jen na tomto počítači nelze odeslat Ollamě v privátní síti.';return;}
 }
 if(mode==='orchestration' && adapter==='openai-responses'
    && document.querySelector('#chat-privacy').value==='local-only'){
  chatOperationStatus.textContent='Text jen na tomto počítači nelze odeslat externímu modelu.';return;
 }
 if(mode==='brainstorming' && adapter==='openai-responses'){
  if(document.querySelector('#chat-privacy').value==='local-only'){
   chatOperationStatus.textContent='Text jen na tomto počítači nelze odeslat externímu modelu.';return;}
  if(!pendingChatRequest)pendingChatRequest={approval_id:crypto.randomUUID(),project_id:activeProject.id,
   expected_head:activeProject.head,thread_id:activeThread?.thread_id || activeTaskThreadId || crypto.randomUUID(),
   turn_id:crypto.randomUUID(),message_id:crypto.randomUUID(),run_id:crypto.randomUUID(),
   manifest_id:crypto.randomUUID(),assistant_message_id:crypto.randomUUID(),
   selected_message_ids:(activeThread?.messages || []).map(item=>item.message_id),
   selected_artifact_ids:[],content:draft.value.trim(),
   privacy:document.querySelector('#chat-privacy').value,created_at:new Date().toISOString(),
   run_choice:runChoice,response_language:responseLanguage};
 const submit=document.querySelector('#chat-submit');submit.disabled=true;
  chatOperationStatus.textContent='Odesílám do OpenAI…';
  chatStream.textContent='';delete chatStream.dataset.progress;chatStream.hidden=!externalStreaming;
  const liveProgress=externalStreaming ? startChatProgress('Připojuji se k OpenAI…') :
   startChatProgress('Model přemýšlí…');
  let receivedDeltas=0,firstDeltaMs=null,streamStarted=performance.now();
  try{await waitForVisiblePaint();
   const result=externalStreaming ?
   await externalStreamRequest(pendingChatRequest,delta=>{receivedDeltas+=1;
    if(firstDeltaMs===null)firstDeltaMs=performance.now()-streamStarted;
    liveProgress.set('OpenAI generuje odpověď…');chatStream.textContent+=delta;keepChatStreamVisible();}) :
   await projectRequest('/v1/external/send',pendingChatRequest,210000);
   activeThread=result.thread;activeTaskThreadId=result.thread.thread_id;
   renderChat(result.thread);rememberThread(result.thread);renderRunUsage(result.usage_report,
    {enabled:externalStreaming,deltas:receivedDeltas,firstDeltaMs,totalMs:performance.now()-streamStarted});pendingChatRequest=null;
   chatStream.hidden=true;draft.value='';draft.focus();chatOperationStatus.textContent=externalStreaming ?
    `Externí odpověď byla přijata průběžně (${receivedDeltas} částí).` : 'Externí odpověď byla přijata.';
  }catch(error){
   appendChatOperationNotice(error);
   if([409,422,502].includes(error.status))pendingChatRequest=null;
   chatOperationStatus.textContent=error.message;
  }finally{liveProgress.stop();chatStream.hidden=true;
   finishChatAutoFollow();submit.disabled=!activeProject || !draft.value.trim();}
  return;
 }
 if(mode==='brainstorming' && adapter==='ollama'){
  if(!pendingChatRequest){
   pendingChatRequest={project_id:activeProject.id,expected_head:activeProject.head,
    thread_id:activeThread?.thread_id || activeTaskThreadId || crypto.randomUUID(),
    turn_id:crypto.randomUUID(),message_id:crypto.randomUUID(),run_id:crypto.randomUUID(),
    manifest_id:crypto.randomUUID(),assistant_message_id:crypto.randomUUID(),
    selected_message_ids:(activeThread?.messages || []).map(item=>item.message_id),
    content:draft.value.trim(),privacy:document.querySelector('#chat-privacy').value,
    created_at:new Date().toISOString(),run_choice:runChoice,
    response_language:responseLanguage};
  }
  const submit=document.querySelector('#chat-submit');submit.disabled=true;
  chatOperationStatus.textContent='Odesílám…';chatStream.textContent='';
  chatStream.hidden=!ollamaStreaming;
  const streamStates={preparing:'Připravuji kontext…',connecting:'Připojuji se k Ollamě…',
   'waiting-first-token':'Čekám na první část odpovědi…',thinking:'Ollama přemýšlí…',
   generating:'Ollama generuje odpověď…',
   completed:'Generování je dokončeno.'};
  const liveProgress=startChatProgress(ollamaStreaming?streamStates.preparing:'Model přemýšlí…');
  let receivedDeltas=0,firstDeltaMs=null,streamStarted=performance.now();
  const thinking=setTimeout(()=>{chatOperationStatus.textContent='Model přemýšlí…';liveProgress.set('Model přemýšlí…');},250);
  try{
   await waitForVisiblePaint();
   const result=ollamaStreaming ? await streamRequest('/v1/chat/send-stream',pendingChatRequest,
    delta=>{receivedDeltas+=1;if(firstDeltaMs===null)firstDeltaMs=performance.now()-streamStarted;
     chatStream.textContent+=delta;keepChatStreamVisible();},status=>{
     liveProgress.set(streamStates[status] || 'Probíhá lokální AI běh…');}) :
    await projectRequest('/v1/chat/send',pendingChatRequest,210000);
   activeThread=result.thread;activeTaskThreadId=result.thread.thread_id;
   renderChat(result.thread);rememberThread(result.thread);renderRunUsage(result.usage_report,
    {enabled:ollamaStreaming,deltas:receivedDeltas,firstDeltaMs,totalMs:performance.now()-streamStarted});pendingChatRequest=null;draft.value='';draft.focus();
   chatOperationStatus.textContent=ollamaStreaming ?
    `Odpověď je připravena · přijato ${receivedDeltas} průběžných částí.` : 'Odpověď je připravena.';
  }catch(error){
   appendChatOperationNotice(error);
   if([409,422,502].includes(error.status))pendingChatRequest=null;
   chatStream.textContent='';
   chatOperationStatus.textContent=error.message+([409,422,502].includes(error.status) ?
    ' Zadání a výběr zůstaly zachovány; tlačítkem Zpracovat spustíte vědomě nový běh.' : '');
  }finally{clearTimeout(thinking);liveProgress.stop();
   submit.disabled=!activeProject || !draft.value.trim();chatStream.hidden=true;
   finishChatAutoFollow();}
  return;
 }
 if(!pendingChatRequest){
 const threadId=activeTaskThreadId || activeThread?.thread_id || crypto.randomUUID();
 const selectedMessages=activeThread?.thread_id===threadId ? activeThread.messages : [];
  const searching=document.querySelector('#task-action').value==='search';
  const useConversation=!searching&&document.querySelector('#task-source-conversation').checked;
  const useCurrentFile=!searching&&document.querySelector('#task-source-current-file-input').checked&&selectedArtifact;
  const includeSelectedArtifacts=!searching&&document.querySelector('#task-source-artifacts').checked;
  const usePublic=searching||document.querySelector('#task-source-public').checked;
  const selectedArtifactIds=[...document.querySelectorAll('#task-artifact-list input:checked')].map(item=>item.value);
  const artifactIds=includeSelectedArtifacts ? selectedArtifactIds : [];
  if(useCurrentFile)artifactIds.push(selectedArtifact);
  const uniqueArtifactIds=[...new Set(artifactIds)],useArtifacts=uniqueArtifactIds.length>0;
  const publicRunIds=usePublic&&!searching ? [...document.querySelectorAll('#task-public-source-list input:checked')]
   .map(item=>item.value) : [];
  const sourceKinds=[];if(useConversation)sourceKinds.push('conversation');
  if(useArtifacts)sourceKinds.push('artifacts');if(usePublic)sourceKinds.push('public-web');
  if(!sourceKinds.length){chatOperationStatus.textContent='Vyberte alespoň jeden zdroj úkolu.';return;}
  if(includeSelectedArtifacts && !selectedArtifactIds.length){chatOperationStatus.textContent='Vyberte alespoň jeden interní artefakt.';return;}
  const searchQuery=searching?draft.value.trim():null;
  if(usePublic && !publicRunIds.length && !searchQuery){
   chatOperationStatus.textContent='Zadejte zadání pro kontrolované hledání na webu.';return;
  }
  pendingChatRequest={task_id:crypto.randomUUID(),
  project_id:activeProject.id,expected_head:activeProject.head,
  thread_id:threadId,
  message_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
  selected_message_ids:useConversation?selectedMessages.map(item=>item.message_id):[],
  selected_artifact_ids:uniqueArtifactIds,
  content:draft.value.trim(),privacy:document.querySelector('#chat-privacy').value,
  created_at:new Date().toISOString(),run_choice:runChoice,
  response_language:responseLanguage,
  task_plan:{schema_version:1,source_kinds:sourceKinds,
   output_kind:document.querySelector('#task-output-kind').value,
   execution:adapter==='ollama'?'local-ollama':'external-openai',
   search_query:searchQuery,public_source_run_ids:publicRunIds}};}
 const submit=document.querySelector('#chat-submit');submit.disabled=true;chatOperationStatus.textContent='Odesílám…';
 const liveProgress=startChatProgress(adapter==='ollama'?
  'Ollama zpracovává explicitní úkol…':'Připravuji explicitní externí náhled…');
 const thinking=setTimeout(()=>{chatOperationStatus.textContent='Model přemýšlí…';
  liveProgress.set(pendingChatRequest?.task_plan?.search_query ?
   'Vyhledávám a model vyhodnocuje výsledky…':'Model přemýšlí…');},250);
 try{
  await waitForVisiblePaint();
  const result=await projectRequest('/v1/tasks/route',pendingChatRequest,210000);
  replaceTaskProjection(result.projection);pendingChatRequest=null;draft.value='';draft.focus();
  chatOperationStatus.textContent=result.projection.temporary ?
   'Návrh je připraven ke kontrole.' : 'Odpověď je připravena.';
 }catch(error){
  appendChatOperationNotice(error);
  const failed=pendingChatRequest;
  try{
   const recovered=await projectRequest('/v1/tasks/list',{
    project_id:failed.project_id,thread_id:failed.thread_id});
   const projection=recovered.outcomes.find(item=>item.task_id===failed.task_id);
   if(projection){replaceTaskProjection(projection);pendingChatRequest=null;}
  }catch(_recoveryError){}
  if([409,422,502].includes(error.status))pendingChatRequest=null;
  chatOperationStatus.textContent=error.message+([409,422,502].includes(error.status) ?
   ' Zadání a výběr zůstaly zachovány; tlačítkem Zpracovat spustíte vědomě nový běh.' : '');
 }
 finally{clearTimeout(thinking);liveProgress.stop();submit.disabled=!activeProject || !draft.value.trim();
  finishChatAutoFollow();}
});
async function assignActiveThread(){
 if(!activeProject || !activeThread)throw new Error('Nejprve vytvořte chatové vlákno.');
 if(activeThread.project_id===activeProject.id)return activeThread;
 const assigned=await projectRequest('/v1/chat/assign',{project_id:activeProject.id,
  thread_id:activeThread.thread_id,expected_revision:activeThread.revision});
 renderChat(assigned);rememberThread(assigned);return assigned;
}
async function runChatRecord(button,action){
 button.disabled=true;chatOperationStatus.textContent='Připravuji projektový záznam…';
 try{
  const thread=await assignActiveThread();
  if(action==='snapshot'){
   await projectRequest('/v1/chat/snapshot',{operation_id:crypto.randomUUID(),project_id:activeProject.id,
    thread_id:thread.thread_id,expected_thread_revision:thread.revision,expected_head:activeProject.head,
    snapshot_id:crypto.randomUUID(),mode:'full',title:'Záznam brainstormingu',created_at:new Date().toISOString(),
    base_snapshot_id:null,base_snapshot_sha256:null});
  }else{
   const answer=[...thread.messages].reverse().find(item=>item.role==='assistant');
   if(!answer)throw new Error('Vlákno zatím nemá odpověď asistenta.');
   await projectRequest('/v1/chat/output',{operation_id:crypto.randomUUID(),project_id:activeProject.id,
    thread_id:thread.thread_id,expected_thread_revision:thread.revision,expected_head:activeProject.head,
    artifact_id:crypto.randomUUID(),title:'Výstup z brainstormingu',body:answer.content,
    created_at:new Date().toISOString(),message_ids:[answer.message_id],snapshot_id:null,snapshot_sha256:null});
  }
  chatOperationStatus.textContent=action==='snapshot'?'Otisk byl uložen do projektu.':'Výstup byl uložen jako editovatelný dokument.';
  await openRegisteredProject(activeProject.id);selectMainTab(document.querySelector('#chat-tab'));
 }catch(error){chatOperationStatus.textContent=error.message;}
 finally{button.disabled=false;}
}
draft.addEventListener('keydown',event=>{
 if(event.key==='Enter' && !event.shiftKey && !event.isComposing){event.preventDefault();document.querySelector('#chat-composer').requestSubmit();}
});
let roleWorkflow=null,pendingWorkflowRequest=null,pendingWorkflowPublish=null;
const workflowStatus=document.querySelector('#workflow-status');
const autonomyPanel=document.querySelector('#autonomy-queue');
const autonomyStatus=document.querySelector('#autonomy-status');
const autonomyList=document.querySelector('#autonomy-list');
let autonomyQueue={global_paused:false,workflows:[]},autonomyHeartbeatBusy=false;
const autonomyTimers=new Map();
const autonomyNoStepAttempts=new Map();
const autonomyViewState=new Map();
const autonomyTerminal=new Set(['completed','failed','unknown','cancelled']);
function autonomyWorkflowView(workflow){
 let view=autonomyViewState.get(workflow.workflow_id);
 if(!view){view={planRevision:workflow.plan_revision,detailOpen:false,
  revisionOpen:false,planReasonsOpen:false,searchRevisionsOpen:false,draft:null};
  autonomyViewState.set(workflow.workflow_id,view);}
 if(view.planRevision!==workflow.plan_revision)Object.assign(view,{
  planRevision:workflow.plan_revision,revisionOpen:false,draft:null});
 return view;
}
function isSearchAutonomy(workflow){
 return workflow.steps?.some(step=>step.action?.id==='search.iterative-query');
}
function autonomyWorkflowVisible(workflow){
 if(!activeProject || document.visibilityState!=='visible')return false;
 if(isSearchAutonomy(workflow)){
  const taskId=workflow.steps?.[0]?.input?.request?.task_id;
  return document.querySelector('#chat-tab').getAttribute('aria-selected')==='true' &&
   taskOutcomes.some(item=>item.task_id===taskId);
 }
 return autonomyPanel.open &&
  document.querySelector('#workflow-tab').getAttribute('aria-selected')==='true';
}
function updateAutonomyCountdownLabels(){
 for(const label of document.querySelectorAll('.search-autonomy-countdown[data-not-before]')){
  const remaining=Math.max(0,new Date(label.dataset.notBefore).getTime()-Date.now());
  label.textContent=`${Math.ceil(remaining/1000)} s`;
 }
}
function autonomyButton(label,action,className='secondary-button'){
 const button=document.createElement('button');button.type='button';button.className=className;
 button.textContent=label;button.addEventListener('click',async()=>{button.disabled=true;try{await action();}catch(error){autonomyStatus.textContent=error.message;}finally{button.disabled=false;}});return button;
}
function dynamicRevisionDraft(workflow,kind){
 const lastRevision=workflow.plan_revisions?.at(-1),source=[...workflow.steps].reverse().find(item=>item.state==='completed');
 const proposal={schema_version:1,proposal_id:crypto.randomUUID(),workflow_id:workflow.workflow_id,
  base_revision:workflow.plan_revision,base_plan_digest:lastRevision?.plan_digest,kind,
  reason:kind==='finish'?'Cíl workflow je splněn.':kind==='repeat'?'Zopakovat dokončený krok s novou identitou.':'Pokračovat dalším kompatibilním krokem.',
  step:null,repeat_of:null,budget:{...workflow.budget}};
 if(kind!=='finish'){
  if(!source)throw new Error('Revize kroku vyžaduje alespoň jeden dokončený krok.');
  proposal.budget.max_steps=Math.max(proposal.budget.max_steps,workflow.steps.length+1);
  proposal.budget.max_cost_units=Math.max(proposal.budget.max_cost_units,workflow.spent_cost+source.cost_units);
  const activated=Date.parse(workflow.activated_at||''),elapsedSeconds=Number.isFinite(activated)?Math.max(0,Math.ceil((Date.now()-activated)/1000)):0;
  proposal.budget.max_seconds=Math.min(86400,Math.max(proposal.budget.max_seconds+300,elapsedSeconds+300));
  proposal.step={step_id:crypto.randomUUID(),action:{...source.action},privacy:source.privacy,
   cost_units:source.cost_units,depends_on:[source.step_id],input:structuredClone(source.input)};
  if(kind==='repeat')proposal.repeat_of=source.step_id;
 }
 return proposal;
}
async function autonomyRequest(path,payload={}){
 const result=await projectRequest(path,payload,210000);if(activeProject)await loadAutonomyQueue(false);return result;
}
function autonomyNoStepFingerprint(workflow){
 return JSON.stringify([workflow.plan_revision,workflow.state,
  workflow.steps.map(item=>[item.step_id,item.state]),
  (workflow.revision_proposals||[]).map(item=>[item.proposal_id,item.state])]);
}
function scheduleAutomaticWorkflow(workflow){
 if(workflow.mode!=='automatic'||autonomyQueue.global_paused||!autonomyWorkflowVisible(workflow))return;
 if(workflow.revision_proposals?.some(item=>item.state==='pending'))return;
 const step=workflow.steps.find(item=>!['completed','failed','unknown','cancelled'].includes(item.state));
 let delay=null;
 const settled=workflow.steps.every(item=>['completed','failed','cancelled'].includes(item.state));
 const noStepRecovery=workflow.state==='queued'&&!step&&settled;
 const noStepFingerprint=noStepRecovery?autonomyNoStepFingerprint(workflow):null;
 if(noStepFingerprint&&autonomyNoStepAttempts.get(workflow.workflow_id)===noStepFingerprint)return;
 if(noStepRecovery)delay=350;
 if(workflow.state==='queued'&&step?.state==='queued'&&step.automatable&&step.confirmation==='none')delay=350;
 if(workflow.state==='countdown'&&step?.state==='countdown'&&step.not_before){delay=Math.max(50,new Date(step.not_before).getTime()-Date.now()+50);autonomyStatus.textContent=`${step.action.id}: automatický krok čeká ${Math.max(0,Math.ceil(delay/1000))} s; lze jej pozastavit nebo zrušit.`;}
 if(delay===null)return;
 autonomyTimers.set(workflow.workflow_id,setTimeout(async()=>{autonomyTimers.delete(workflow.workflow_id);if(!autonomyWorkflowVisible(workflow))return;if(noStepFingerprint)autonomyNoStepAttempts.set(workflow.workflow_id,noStepFingerprint);try{await withChatProgress(step?researchActivityLabel(step):'Doplňuji další krok výzkumu…',async()=>{await projectRequest('/v1/autonomy/attach',{workflow_id:workflow.workflow_id});await autonomyRequest('/v1/autonomy/advance',{workflow_id:workflow.workflow_id});if(isSearchAutonomy(workflow))await refreshActiveTaskOutcomes();renderChat(activeThread);});}catch(error){autonomyStatus.textContent=error.message;chatOperationStatus.textContent=error.message;}},delay));
}
function renderAutonomyQueue(){
 if(document.activeElement?.matches('.autonomy-revision-editor textarea'))return;
 for(const timer of autonomyTimers.values())clearTimeout(timer);autonomyTimers.clear();
 autonomyList.replaceChildren();const rows=autonomyQueue.workflows||[];
 const visibleIds=new Set(rows.map(item=>item.workflow_id));
 for(const workflowId of autonomyViewState.keys())if(!visibleIds.has(workflowId))autonomyViewState.delete(workflowId);
 for(const workflowId of autonomyNoStepAttempts.keys())if(!visibleIds.has(workflowId))autonomyNoStepAttempts.delete(workflowId);
 document.querySelector('#autonomy-global-pause').textContent=autonomyQueue.global_paused?'Zrušit globální pauzu':'Pozastavit vše';
 if(!rows.length){const empty=document.createElement('p');empty.textContent='Pro tento projekt není připravená žádná řízená fronta.';autonomyList.append(empty);return;}
 for(const workflow of rows){const card=document.createElement('article');card.className='autonomy-card';card.dataset.state=workflow.state;
  const view=autonomyWorkflowView(workflow);
  const heading=document.createElement('h3');heading.textContent=`${workflow.mode==='automatic'?'Automatická':'Ruční'} fronta · ${workflow.state}`;
  const meta=document.createElement('p');meta.textContent=`${workflow.workflow_id} · revize ${workflow.plan_revision} · náklady ${workflow.spent_cost}/${workflow.budget.max_cost_units} · zbývá ${workflow.remaining_cost} cost / ${workflow.remaining_steps} kroků / ${workflow.remaining_seconds} s`;
  const progress=document.createElement('progress');progress.max=Math.max(1,workflow.budget.max_cost_units);progress.value=workflow.spent_cost;progress.setAttribute('aria-label','Využitý budget');
  const steps=document.createElement('ol');
  for(const step of workflow.steps){const item=document.createElement('li');item.textContent=`${step.action.id} · ${step.state} · privacy ${step.privacy} · cost ${step.cost_units}`;steps.append(item);}
  const detail=document.createElement('details');detail.open=view.detailOpen;detail.addEventListener('toggle',()=>{view.detailOpen=detail.open;});const summary=document.createElement('summary');summary.textContent='Přesný plán a mezivýsledky';const pre=document.createElement('pre');pre.textContent=JSON.stringify(workflow.steps,null,2);detail.append(summary,pre);
  const revisions=document.createElement('div');revisions.className='autonomy-revision-history';
  revisions.textContent=`Historie plánu: ${(workflow.plan_revisions||[]).map(item=>`r${item.revision} ${item.kind}: ${item.reason}`).join(' · ')}`;
  const revisionPanels=document.createElement('div');
  for(const pending of (workflow.revision_proposals||[]).filter(item=>item.state==='pending')){
   const proposal=pending.proposal,box=document.createElement('section');box.className='autonomy-revision';
   const title=document.createElement('strong');title.textContent=`Čekající revize: ${proposal.kind}`;
   const reason=document.createElement('p');reason.textContent=`Důvod: ${proposal.reason}`;
   const impact=document.createElement('p');impact.textContent=`Dopad limitu: ${JSON.stringify(workflow.budget)} → ${JSON.stringify(proposal.budget)}${proposal.step?` · nový krok ${proposal.step.action.id}`:' · bez nového kroku'}`;
   const exact=document.createElement('code');exact.textContent=`digest ${pending.approval_digest}`;
   const confirmRevision=autonomyButton('Potvrdit přesnou revizi',async()=>{if(!confirm(`Potvrdit změnu plánu?\n${reason.textContent}\n${impact.textContent}\n${exact.textContent}`))return;await projectRequest('/v1/autonomy/attach',{workflow_id:workflow.workflow_id});await autonomyRequest('/v1/autonomy/revision/confirm',{workflow_id:workflow.workflow_id,proposal_id:pending.proposal_id,approval_digest:pending.approval_digest});});
   box.append(title,reason,impact,exact,confirmRevision);revisionPanels.append(box);
  }
  const revisionReady=workflow.plan_schema_version===3&&!autonomyTerminal.has(workflow.state)&&
   !(workflow.revision_proposals||[]).some(item=>item.state==='pending')&&
   workflow.steps.some(item=>item.state==='completed')&&workflow.steps.every(item=>['completed','cancelled'].includes(item.state));
  if(revisionReady){
   const editor=document.createElement('details');editor.className='autonomy-revision-editor';
   editor.open=view.revisionOpen;editor.addEventListener('toggle',()=>{view.revisionOpen=editor.open;});
   const editorSummary=document.createElement('summary');editorSummary.textContent='Navrhnout přesnou změnu plánu';
   const textarea=document.createElement('textarea');textarea.rows=8;textarea.spellcheck=false;
   const fill=kind=>{textarea.value=JSON.stringify(dynamicRevisionDraft(workflow,kind),null,2);view.draft=textarea.value;};
   if(view.draft===null)fill('finish');else textarea.value=view.draft;
   textarea.addEventListener('input',()=>{view.draft=textarea.value;});
   const templates=document.createElement('div');templates.className='form-actions';
   templates.append(autonomyButton('Přidat navazující krok',()=>fill('append')),
    autonomyButton('Zopakovat poslední krok',()=>fill('repeat')),
    autonomyButton('Ukončit plán',()=>fill('finish')));
   const submit=autonomyButton('Zkontrolovat a navrhnout revizi',async()=>{const proposal=JSON.parse(textarea.value);if(proposal.workflow_id!==workflow.workflow_id)throw new Error('Revize patří do jiné fronty.');await autonomyRequest('/v1/autonomy/revision/propose',proposal);});
   editor.append(editorSummary,templates,textarea,submit);revisionPanels.append(editor);
  }
  const actions=document.createElement('div');actions.className='form-actions';
  const attach=()=>projectRequest('/v1/autonomy/attach',{workflow_id:workflow.workflow_id});
  if(workflow.state==='proposed')actions.append(autonomyButton('Aktivovat plán',async()=>{if(!confirm(`Aktivovat ${workflow.mode==='automatic'?'automatický':'ruční'} režim s budgetem ${JSON.stringify(workflow.budget)}?`))return;await attach();await autonomyRequest('/v1/autonomy/activate',{workflow_id:workflow.workflow_id,activation_digest:workflow.activation_digest});}));
  if(['queued','running'].includes(workflow.state)){actions.append(autonomyButton('Provést další krok',async()=>{await attach();await autonomyRequest('/v1/autonomy/advance',{workflow_id:workflow.workflow_id});}));actions.append(autonomyButton('Pozastavit',()=>autonomyRequest('/v1/autonomy/pause',{workflow_id:workflow.workflow_id})));}
  if(workflow.state==='countdown')actions.append(autonomyButton('Pozastavit odpočet',()=>autonomyRequest('/v1/autonomy/pause',{workflow_id:workflow.workflow_id})));
  if(workflow.state==='paused')actions.append(autonomyButton('Pokračovat',async()=>{await attach();await autonomyRequest('/v1/autonomy/resume',{workflow_id:workflow.workflow_id});}));
  for(const step of workflow.steps.filter(item=>item.state==='awaiting-approval'))actions.append(autonomyButton(step.action.id==='artifact.create-local'?'Schválit přesný lokální výstup':'Schválit krok',async()=>{if(!confirm(`Potvrdit pouze tento krok?\n${JSON.stringify(step.input,null,2)}`))return;await attach();await autonomyRequest('/v1/autonomy/approve',{workflow_id:workflow.workflow_id,step_id:step.step_id});}));
  if(!autonomyTerminal.has(workflow.state))actions.append(autonomyButton('Zrušit frontu',async()=>{if(confirm('Opravdu zrušit dosud neprovedené kroky této fronty?'))await autonomyRequest('/v1/autonomy/cancel',{workflow_id:workflow.workflow_id});},'danger-button'));
  card.append(heading,meta,progress,steps,revisions,revisionPanels,detail,actions);autonomyList.append(card);scheduleAutomaticWorkflow(workflow);
 }
}
async function loadAutonomyQueue(showStatus=true){
 if(!activeProject){autonomyQueue={global_paused:false,workflows:[]};renderAutonomyQueue();return;}
 if(showStatus)autonomyStatus.textContent='Načítám řízenou frontu…';
 try{autonomyQueue=await projectRequest('/v1/autonomy/status',{project_id:activeProject.id});renderAutonomyQueue();if(document.querySelector('#chat-tab').getAttribute('aria-selected')==='true')renderChat(activeThread);const incompatible=autonomyQueue.incompatible_workflows?.length || 0;autonomyStatus.textContent=incompatible?`Fronty: ${autonomyQueue.workflows.length}. ${incompatible} starší terminální záznamy nelze zobrazit s aktuálním katalogem; v journalu zůstávají zachované.`:`Fronty: ${autonomyQueue.workflows.length}. Bez živého UI se další krok nespustí.`;return true;}
 catch(error){autonomyStatus.textContent=error.message;if(document.querySelector('#chat-tab').getAttribute('aria-selected')==='true')chatOperationStatus.textContent=`Frontu automatizace nelze načíst: ${error.message}`;return false;}
}
async function refreshAutonomyLease(){
 if(autonomyHeartbeatBusy)return;autonomyHeartbeatBusy=true;
 try{let anyVisible=false;for(const workflow of autonomyQueue.workflows||[])if(!autonomyTerminal.has(workflow.state)){const visible=autonomyWorkflowVisible(workflow);anyVisible ||= visible;const path=visible?'/v1/autonomy/attach':'/v1/autonomy/detach';await projectRequest(path,{workflow_id:workflow.workflow_id});}if(anyVisible)await loadAutonomyQueue(false);}catch(error){autonomyStatus.textContent=error.message;}finally{autonomyHeartbeatBusy=false;}
}
autonomyPanel.addEventListener('toggle',()=>{if(autonomyPanel.open){loadAutonomyQueue().then(refreshAutonomyLease);}else refreshAutonomyLease();});
document.querySelector('#autonomy-refresh').addEventListener('click',()=>loadAutonomyQueue());
document.querySelector('#autonomy-plan-example').addEventListener('click',async()=>{
 if(!activeProject){autonomyStatus.textContent='Nejprve otevřete projekt.';return;}
 const seed=new TextEncoder().encode(`${activeProject.id}\n${activeProject.head}`);const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',seed)),byte=>byte.toString(16).padStart(2,'0')).join('');
 document.querySelector('#autonomy-plan-json').value=JSON.stringify({schema_version:1,workflow_id:crypto.randomUUID(),project_id:activeProject.id,expected_head:activeProject.head,mode:'automatic',privacy:'project',budget:{max_steps:1,max_cost_units:1,max_seconds:300},steps:[{step_id:crypto.randomUUID(),action:{id:'analysis.read-only',version:'1.0'},privacy:'project',cost_units:1,depends_on:[],input:{selection_sha256:hash}}]},null,2);
 autonomyStatus.textContent='Příklad je pouze vložený v editoru. Tlačítkem Zkontrolovat návrh jej připravíte bez spuštění.';
});
document.querySelector('#autonomy-plan-dynamic-example').addEventListener('click',async()=>{
 if(!activeProject){autonomyStatus.textContent='Nejprve otevřete projekt.';return;}
 const seed=new TextEncoder().encode(`${activeProject.id}\n${activeProject.head}`);const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',seed)),byte=>byte.toString(16).padStart(2,'0')).join('');
 document.querySelector('#autonomy-plan-json').value=JSON.stringify({schema_version:3,workflow_id:crypto.randomUUID(),project_id:activeProject.id,expected_head:activeProject.head,mode:'manual',privacy:'project',countdown_seconds:3,policy:{actions:[{id:'analysis.read-only',version:'1.0'}],permissions:['project-read'],execution_boundaries:['local-node']},budget:{max_steps:1,max_cost_units:1,max_seconds:300},steps:[{step_id:crypto.randomUUID(),action:{id:'analysis.read-only',version:'1.0'},privacy:'project',cost_units:1,depends_on:[],input:{selection_sha256:hash}}]},null,2);
 autonomyStatus.textContent='Dynamický read-only příklad je jen v editoru. Kontrola připraví revizi 1 bez spuštění.';
});
document.querySelector('#autonomy-plan-check').addEventListener('click',async()=>{
 const button=document.querySelector('#autonomy-plan-check');button.disabled=true;
 try{if(!activeProject)throw new Error('Nejprve otevřete projekt.');const plan=JSON.parse(document.querySelector('#autonomy-plan-json').value);if(plan.project_id!==activeProject.id)throw new Error('Návrh patří do jiného projektu.');const exists=(autonomyQueue.workflows||[]).some(item=>item.workflow_id===plan.workflow_id);await autonomyRequest(exists?'/v1/autonomy/replace':'/v1/autonomy/prepare',plan);autonomyStatus.textContent='Návrh prošel kontrolou. Před spuštěním zkontrolujte přesný plán, režim a budget.';}catch(error){autonomyStatus.textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector('#autonomy-global-pause').addEventListener('click',()=>autonomyRequest(autonomyQueue.global_paused?'/v1/autonomy/resume-all':'/v1/autonomy/pause-all'));
document.querySelector('#workflow-tab').addEventListener('click',()=>{if(autonomyPanel.open)loadAutonomyQueue().then(refreshAutonomyLease);});
document.querySelector('#chat-tab').addEventListener('click',()=>loadAutonomyQueue(false).then(refreshAutonomyLease));
document.addEventListener('visibilitychange',refreshAutonomyLease);setInterval(refreshAutonomyLease,5000);setInterval(updateAutonomyCountdownLabels,250);
function resetWorkflowProjection(message=''){
 roleWorkflow=null;pendingWorkflowRequest=null;pendingWorkflowPublish=null;
 for(const id of ['workflow-creator-preview','workflow-creator-result','workflow-opponent-preview',
                  'workflow-opponent-result','workflow-publish'])document.querySelector('#'+id).hidden=true;
 document.querySelector('#workflow-creator-confirm').checked=false;
 document.querySelector('#workflow-creator-dispatch').disabled=true;
 document.querySelector('#workflow-opponent-confirm').checked=false;
 document.querySelector('#workflow-opponent-dispatch').disabled=true;
 document.querySelector('#workflow-publish-step').replaceChildren();
 workflowStatus.textContent=message;
}
function clearWorkflow(){resetWorkflowProjection();}
function invalidateWorkflow(){if(roleWorkflow || pendingWorkflowRequest)resetWorkflowProjection('Vstupy se změnily. Připravte nové workflow s novými ID.');}
function renderWorkflowSources(){
 for(const [id,required] of [['workflow-creator-artifacts',true],['workflow-opponent-artifacts',false]]){
  const list=document.querySelector('#'+id);if(!list)return;list.replaceChildren();
  for(const item of currentArtifacts){const label=document.createElement('label');
   const input=document.createElement('input');input.type='checkbox';input.value=item.id;
   input.addEventListener('change',invalidateWorkflow);label.append(input,document.createTextNode(' '+item.title));list.append(label);}
  if(!currentArtifacts.length){const empty=document.createElement('p');empty.textContent=required?'Creator vyžaduje alespoň jeden podklad.':'Žádné dodatečné podklady.';list.append(empty);}
 }
}
async function workflowTarget(model){
 if(!chatBinding)throw new Error('Nejprve nastavte lokální Ollama backend.');
 const target=structuredClone(chatBinding);model=model.trim();if(!model)throw new Error('Zadejte oba modely.');
 if(model!==target.model){const raw=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(model));
  const suffix=[...new Uint8Array(raw)].map(value=>value.toString(16).padStart(2,'0')).join('').slice(0,16);
  target.revision=target.revision+'.run-model-'+suffix;target.model=model;}
 return target;
}
function workflowStep(ordinal){return roleWorkflow?.steps?.find(step=>step.ordinal===ordinal);}
function renderWorkflow(){
 if(!roleWorkflow)return;const creator=workflowStep(1),opponent=workflowStep(2);
 if(creator?.preview){const section=document.querySelector('#workflow-creator-preview');section.hidden=creator.state!=='prepared';
  section.querySelector('pre').textContent=JSON.stringify(creator.preview,null,2)+'\\n\\nProvider request:\\n'+JSON.stringify(creator.provider_request,null,2);}
 if(creator?.response){const section=document.querySelector('#workflow-creator-result');section.hidden=false;
  section.querySelector('pre').textContent=creator.response;}
 if(opponent?.preview){const section=document.querySelector('#workflow-opponent-preview');section.hidden=opponent.state!=='prepared';
  section.querySelector('pre').textContent=JSON.stringify(opponent.preview,null,2)+'\\n\\nProvider request:\\n'+JSON.stringify(opponent.provider_request,null,2);}
 if(opponent?.response){const section=document.querySelector('#workflow-opponent-result');section.hidden=false;
  section.querySelector('pre').textContent=opponent.response;}
 const options=document.querySelector('#workflow-publish-step');options.replaceChildren();
 for(const [step,label] of [[creator,'Creator výstup'],[opponent,'Oponentura']])if(step?.state==='succeeded'){
  const option=document.createElement('option');option.value=step.step_id;option.textContent=label;options.append(option);}
 document.querySelector('#workflow-publish').hidden=!options.options.length;
}
for(const id of ['workflow-purpose','workflow-privacy','workflow-creator-model','workflow-opponent-model'])
 document.querySelector('#'+id).addEventListener('input',invalidateWorkflow);
document.querySelector('#workflow-creator-confirm').addEventListener('change',event=>{
 document.querySelector('#workflow-creator-dispatch').disabled=!event.currentTarget.checked;});
document.querySelector('#workflow-opponent-confirm').addEventListener('change',event=>{
 document.querySelector('#workflow-opponent-dispatch').disabled=!event.currentTarget.checked;});
document.querySelector('#workflow-title').addEventListener('input',()=>{pendingWorkflowPublish=null;});
document.querySelector('#workflow-publish-step').addEventListener('change',()=>{pendingWorkflowPublish=null;});
document.querySelector('#workflow-prepare').addEventListener('click',async event=>{
 if(!activeProject || !chatBinding){workflowStatus.textContent='Nejprve otevřete projekt a nastavte lokální backend.';return;}
 const purpose=document.querySelector('#workflow-purpose').value.trim();
 const creatorIds=[...document.querySelectorAll('#workflow-creator-artifacts input:checked')].map(item=>item.value);
 const opponentIds=[...document.querySelectorAll('#workflow-opponent-artifacts input:checked')].map(item=>item.value);
 if(!purpose || !creatorIds.length){workflowStatus.textContent='Zadejte účel a vyberte alespoň jeden creator podklad.';return;}
 event.currentTarget.disabled=true;workflowStatus.textContent='Připravuji přesný creator požadavek…';
 try{const creatorTarget=await workflowTarget(document.querySelector('#workflow-creator-model').value);
  const opponentTarget=await workflowTarget(document.querySelector('#workflow-opponent-model').value);
  pendingWorkflowRequest={schema:'fpw-role-workflow-v1',workflow_id:crypto.randomUUID(),
   project_id:activeProject.id,expected_head:activeProject.head,
   purpose:{input_id:crypto.randomUUID(),content:purpose,privacy:document.querySelector('#workflow-privacy').value},
   creator:{step_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
    role_id:'creator',role_revision:'creator-v1',target:creatorTarget,artifact_ids:creatorIds},
   opponent:{step_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
    role_id:'opponent',role_revision:'opponent-v1',target:opponentTarget,artifact_ids:opponentIds}};
  roleWorkflow=await projectRequest('/v1/workflows/prepare',pendingWorkflowRequest);
  pendingWorkflowRequest=null;renderWorkflow();workflowStatus.textContent='Creator požadavek je připraven k samostatnému potvrzení.';
 }catch(error){workflowStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
document.querySelector('#workflow-creator-dispatch').addEventListener('click',async event=>{
 const step=workflowStep(1);if(!roleWorkflow || !step)return;event.currentTarget.disabled=true;
 workflowStatus.textContent='Spouštím potvrzený creator krok…';
 try{roleWorkflow=await projectRequest('/v1/workflows/creator/dispatch',{workflow_id:roleWorkflow.workflow_id,
   project_id:activeProject.id,approval_digest:step.approval_digest},210000);
  document.querySelector('#workflow-creator-preview').hidden=true;renderWorkflow();workflowStatus.textContent='Creator výstup je durable uložen. Připravte samostatný opponent handoff.';
 }catch(error){
  if([409,422,502].includes(error.status))resetWorkflowProjection();
  workflowStatus.textContent=error.message+localRunRetryHint(error);
 }
});
document.querySelector('#workflow-opponent-prepare').addEventListener('click',async event=>{
 if(!roleWorkflow)return;event.currentTarget.disabled=true;workflowStatus.textContent='Připravuji přesný opponent handoff…';
 try{roleWorkflow=await projectRequest('/v1/workflows/opponent/prepare',{workflow_id:roleWorkflow.workflow_id,
   project_id:activeProject.id});renderWorkflow();workflowStatus.textContent='Opponent handoff je připraven k novému potvrzení.';
 }catch(error){workflowStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
document.querySelector('#workflow-opponent-dispatch').addEventListener('click',async event=>{
 const step=workflowStep(2);if(!roleWorkflow || !step)return;event.currentTarget.disabled=true;
 workflowStatus.textContent='Spouštím potvrzený opponent krok…';
 try{roleWorkflow=await projectRequest('/v1/workflows/opponent/dispatch',{workflow_id:roleWorkflow.workflow_id,
   project_id:activeProject.id,approval_digest:step.approval_digest},210000);
  document.querySelector('#workflow-opponent-preview').hidden=true;renderWorkflow();workflowStatus.textContent='Oponentura je durable uložená.';
 }catch(error){
  if([409,422,502].includes(error.status))resetWorkflowProjection();
  workflowStatus.textContent=error.message+localRunRetryHint(error);
 }
});
document.querySelector('#workflow-publish-button').addEventListener('click',async event=>{
 if(!roleWorkflow || !activeProject)return;const stepId=document.querySelector('#workflow-publish-step').value;
 const step=roleWorkflow.steps.find(item=>item.step_id===stepId);const title=document.querySelector('#workflow-title').value.trim();
 if(!step || !title){workflowStatus.textContent='Vyberte výsledek a zadejte název.';return;}
 if(!pendingWorkflowPublish)pendingWorkflowPublish={workflow_id:roleWorkflow.workflow_id,step_id:step.step_id,
  result_sha256:step.response_sha256,project_id:activeProject.id,expected_head:activeProject.head,
  artifact_id:crypto.randomUUID(),title,created_at:new Date().toISOString(),operation_id:crypto.randomUUID()};
 event.currentTarget.disabled=true;workflowStatus.textContent='Ukládám vybraný workflow výstup do projektu…';
 try{await projectRequest('/v1/workflows/publish',pendingWorkflowPublish,120000);const projectId=activeProject.id;
  await openRegisteredProject(projectId);workflowStatus.textContent='Workflow výstup byl uložen do projektu.';
 }catch(error){workflowStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
let summaryPreview=null,pendingSummaryRequest=null,pendingSummaryPublish=null;
const summaryStatus=document.querySelector('#summary-status');
const summaryPreviewElement=document.querySelector('#summary-preview');
function clearSummary(){
 summaryPreview=null;pendingSummaryRequest=null;pendingSummaryPublish=null;
 if(summaryPreviewElement)summaryPreviewElement.replaceChildren();
 const controls=document.querySelector('#summary-publish-controls');if(controls)controls.hidden=true;
 if(summaryStatus)summaryStatus.textContent='';
}
function renderSummarySources(){
 const list=document.querySelector('#summary-artifact-list');if(!list)return;list.replaceChildren();
 for(const item of currentArtifacts){
  const label=document.createElement('label');const input=document.createElement('input');
  input.type='checkbox';input.value=item.id;label.append(input,document.createTextNode(' '+item.title));list.append(label);
 }
}
function renderSummary(text){
 summaryPreviewElement.replaceChildren();
 for(const line of text.split('\\n')){
  const heading=line.match(/^(#{1,6})\\s+(.*)$/);
  const item=document.createElement(heading?'h'+heading[1].length:'p');
  item.textContent=heading?heading[2]:line;summaryPreviewElement.append(item);
 }
}
document.querySelector('#summary-kind').addEventListener('change',event=>{
 document.querySelector('#summary-artifacts').hidden=event.target.value!=='artifacts';
 pendingSummaryRequest=null;summaryPreview=null;summaryPreviewElement.replaceChildren();
 document.querySelector('#summary-publish-controls').hidden=true;
});
document.querySelector('#summary-generate').addEventListener('click',async event=>{
 if(!activeProject || !chatBinding){summaryStatus.textContent='Nejprve otevřete projekt a nastavte lokální backend.';return;}
 const kind=document.querySelector('#summary-kind').value;
 try{
  let selection;
  if(kind==='artifacts'){
   const ids=[...document.querySelectorAll('#summary-artifact-list input:checked')].map(item=>item.value);
   if(!ids.length)throw new Error('Vyberte alespoň jeden podklad.');
   selection={kind:'artifacts',artifact_ids:ids};
  }else{
   const thread=await assignActiveThread();
   if(!thread.messages.length)throw new Error('Aktuální chat nemá zprávy.');
   selection={kind:'messages',thread_id:thread.thread_id,thread_revision:thread.revision,
    message_ids:thread.messages.map(item=>item.message_id)};
  }
  if(!pendingSummaryRequest){
   const focusText=document.querySelector('#summary-focus').value.trim();
   pendingSummaryRequest={schema:'fpw-summary-request-v1',task_id:crypto.randomUUID(),
    run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),project_id:activeProject.id,
    expected_head:activeProject.head,role_id:'summarizer',role_revision:'summarizer-v1',
    target:chatBinding,selection,focus:focusText?{input_id:crypto.randomUUID(),content:focusText,
     privacy:document.querySelector('#summary-focus-privacy').value}:null};
  }
  event.currentTarget.disabled=true;summaryStatus.textContent='Připravuji souhrn…';
  const result=await projectRequest('/v1/summary/preview',pendingSummaryRequest,210000);
  summaryPreview=result;pendingSummaryRequest=null;pendingSummaryPublish=null;renderSummary(result.response);
  document.querySelector('#summary-publish-controls').hidden=false;
  summaryStatus.textContent=`Náhled je připraven · soukromí: ${result.privacy}.`;
 }catch(error){
  if([409,422,502].includes(error.status))pendingSummaryRequest=null;
  summaryStatus.textContent=error.message+localRunRetryHint(error);
 }
 finally{event.currentTarget.disabled=false;}
});
document.querySelector('#summary-publish').addEventListener('click',async event=>{
 if(!summaryPreview || !activeProject)return;
 try{
  const title=document.querySelector('#summary-title').value.trim();
  if(!title)throw new Error('Zadejte název souhrnu.');
  if(!pendingSummaryPublish)pendingSummaryPublish={task_id:summaryPreview.task_id,
   preview_sha256:summaryPreview.response_sha256,project_id:activeProject.id,
   expected_head:activeProject.head,artifact_id:crypto.randomUUID(),title,
   created_at:new Date().toISOString(),operation_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;summaryStatus.textContent='Ukládám souhrn do projektu…';
  await projectRequest('/v1/summary/publish',pendingSummaryPublish);
  const projectId=activeProject.id;summaryStatus.textContent='Souhrn byl uložen do projektu.';
  await openRegisteredProject(projectId);
 }catch(error){summaryStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
let extractionPreview=null,pendingExtractionRequest=null,pendingExtractionPublish=null;
const extractionStatus=document.querySelector('#extraction-status');
const extractionPreviewElement=document.querySelector('#extraction-preview');
function clearExtraction(){
 extractionPreview=null;pendingExtractionRequest=null;pendingExtractionPublish=null;
 if(extractionPreviewElement)extractionPreviewElement.textContent='';
 const controls=document.querySelector('#extraction-publish-controls');if(controls)controls.hidden=true;
 if(extractionStatus)extractionStatus.textContent='';
}
function renderExtractionSources(){
 const list=document.querySelector('#extraction-artifact-list');if(!list)return;list.replaceChildren();
 for(const item of currentArtifacts){const label=document.createElement('label');const input=document.createElement('input');
  input.type='checkbox';input.value=item.id;label.append(input,document.createTextNode(' '+item.title));list.append(label);}
}
document.querySelector('#extraction-kind').addEventListener('change',event=>{
 document.querySelector('#extraction-artifacts').hidden=event.target.value!=='artifacts';clearExtraction();
});
document.querySelector('#extraction-generate').addEventListener('click',async event=>{
 if(!activeProject || !chatBinding){extractionStatus.textContent='Nejprve otevřete projekt a nastavte lokální backend.';return;}
 try{
  const kind=document.querySelector('#extraction-kind').value;let selection;
  if(kind==='artifacts'){
   const ids=[...document.querySelectorAll('#extraction-artifact-list input:checked')].map(item=>item.value);
   if(!ids.length)throw new Error('Vyberte alespoň jeden podklad.');
   selection={kind:'artifacts',artifact_ids:ids};
  }else{const thread=await assignActiveThread();if(!thread.messages.length)throw new Error('Aktuální chat nemá zprávy.');
   selection={kind:'messages',thread_id:thread.thread_id,thread_revision:thread.revision,
    message_ids:thread.messages.map(item=>item.message_id)};}
  const [schemaId,schemaRevision]=document.querySelector('#extraction-schema').value.split('|');
  const focusText=document.querySelector('#extraction-focus').value.trim();
  if(!pendingExtractionRequest)pendingExtractionRequest={schema:'fpw-extraction-request-v1',task_id:crypto.randomUUID(),
   run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),project_id:activeProject.id,expected_head:activeProject.head,
   role_id:'extractor',role_revision:'extractor-v1',target:chatBinding,schema_id:schemaId,
   schema_revision:schemaRevision,selection,focus:focusText?
   {input_id:crypto.randomUUID(),content:focusText,privacy:document.querySelector('#extraction-focus-privacy').value}:null};
  event.currentTarget.disabled=true;extractionStatus.textContent='Připravuji extrakci…';
  const result=await projectRequest('/v1/extraction/preview',pendingExtractionRequest,210000);
  extractionPreview=result;pendingExtractionRequest=null;pendingExtractionPublish=null;
  extractionPreviewElement.textContent=JSON.stringify(JSON.parse(result.response),null,2);
  document.querySelector('#extraction-publish-controls').hidden=false;
  extractionStatus.textContent=`Náhled je připraven · soukromí: ${result.privacy}.`;
 }catch(error){
  if([409,422,502].includes(error.status))pendingExtractionRequest=null;
  extractionStatus.textContent=error.message+localRunRetryHint(error);
 }finally{event.currentTarget.disabled=false;}
});
document.querySelector('#extraction-publish').addEventListener('click',async event=>{
 if(!extractionPreview || !activeProject)return;
 try{const title=document.querySelector('#extraction-title').value.trim();if(!title)throw new Error('Zadejte název extrakce.');
  if(!pendingExtractionPublish)pendingExtractionPublish={task_id:extractionPreview.task_id,
   preview_sha256:extractionPreview.response_sha256,project_id:activeProject.id,expected_head:activeProject.head,
   artifact_id:crypto.randomUUID(),title,created_at:new Date().toISOString(),operation_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;extractionStatus.textContent='Ukládám extrakci do projektu…';
  await projectRequest('/v1/extraction/publish',pendingExtractionPublish);const projectId=activeProject.id;
  extractionStatus.textContent='Extrakce byla uložena do projektu.';await openRegisteredProject(projectId);
 }catch(error){extractionStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
let metadataPreview=null,pendingMetadataRequest=null,pendingMetadataPublish=null;
const metadataStatus=document.querySelector('#metadata-status');
function clearMetadata(){
 metadataPreview=null;pendingMetadataRequest=null;pendingMetadataPublish=null;
 const diff=document.querySelector('#metadata-diff');if(diff)diff.hidden=true;
 if(metadataStatus)metadataStatus.textContent='';
}
function renderMetadataSources(){
 const select=document.querySelector('#metadata-artifact');if(!select)return;select.replaceChildren();
 const empty=document.createElement('option');empty.value='';empty.textContent='Vyberte artefakt';select.append(empty);
 for(const item of currentArtifacts){const option=document.createElement('option');option.value=item.id;
  option.textContent=item.title;select.append(option);}
}
document.querySelector('#metadata-artifact').addEventListener('change',clearMetadata);
document.querySelector('#metadata-generate').addEventListener('click',async event=>{
 if(!activeProject || !chatBinding){metadataStatus.textContent='Nejprve otevřete projekt a nastavte lokální backend.';return;}
 const artifactId=document.querySelector('#metadata-artifact').value;
 if(!artifactId){metadataStatus.textContent='Vyberte jeden artefakt.';return;}
 try{
  if(!pendingMetadataRequest)pendingMetadataRequest={schema:'fpw-metadata-suggestion-request-v1',
   task_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
   project_id:activeProject.id,expected_head:activeProject.head,role_id:'metadata-advisor',
   role_revision:'metadata-advisor-v1',target:chatBinding,
   selection:{kind:'artifacts',artifact_ids:[artifactId]},focus:null,metadata_input_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;metadataStatus.textContent='Připravuji návrh metadat…';
  const result=await projectRequest('/v1/metadata-suggestions/preview',pendingMetadataRequest,210000);
  metadataPreview=result;pendingMetadataRequest=null;pendingMetadataPublish=null;
  document.querySelector('#metadata-description-before').textContent='Původní: '+(result.diff.description.before || 'bez popisu');
  const description=document.querySelector('#metadata-apply-description');
  description.checked=false;description.disabled=!result.diff.description.changed;
  document.querySelector('#metadata-description-after').textContent=result.diff.description.after===null?
   'Model nenavrhl nový popis.':'Navržený: '+result.diff.description.after;
  const tags=document.querySelector('#metadata-tag-list');tags.replaceChildren();
  for(const tag of result.diff.tags.suggested_additions){const label=document.createElement('label');
   const input=document.createElement('input');input.type='checkbox';input.value=tag;
   label.append(input,document.createTextNode(' '+tag));tags.append(label);}
  if(!result.diff.tags.suggested_additions.length)tags.textContent='Model nenavrhl žádný nový štítek.';
  document.querySelector('#metadata-diff').hidden=false;
  metadataStatus.textContent=`Návrh je připraven · soukromí: ${result.privacy}.`;
 }catch(error){
  if([409,422,502].includes(error.status))pendingMetadataRequest=null;
  metadataStatus.textContent=error.message+localRunRetryHint(error);
 }finally{event.currentTarget.disabled=false;}
});
document.querySelector('#metadata-publish').addEventListener('click',async event=>{
 if(!metadataPreview || !activeProject)return;
 try{const applyDescription=document.querySelector('#metadata-apply-description').checked;
  const tags=[...document.querySelectorAll('#metadata-tag-list input:checked')].map(item=>item.value);
  if(!applyDescription && !tags.length)throw new Error('Vyberte alespoň jednu změnu.');
  if(!pendingMetadataPublish)pendingMetadataPublish={task_id:metadataPreview.task_id,
   preview_sha256:metadataPreview.response_sha256,project_id:activeProject.id,
   expected_head:activeProject.head,artifact_id:document.querySelector('#metadata-artifact').value,
   apply_description:applyDescription,tags,operation_id:crypto.randomUUID()};
  event.currentTarget.disabled=true;metadataStatus.textContent='Ukládám potvrzená metadata…';
  await projectRequest('/v1/metadata-suggestions/publish',pendingMetadataPublish);
  const projectId=activeProject.id;metadataStatus.textContent='Vybraná metadata byla uložena.';
  await openRegisteredProject(projectId);
 }catch(error){metadataStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
});
let imageApproval=null,imageResult=null,pendingImageRequest=null,pendingImagePublish=null;
const imageStatus=document.querySelector('#image-status');
function clearImage(){
 imageApproval=null;imageResult=null;pendingImageRequest=null;pendingImagePublish=null;
 const request=document.querySelector('#image-request-preview'),result=document.querySelector('#image-result');
 if(request)request.hidden=true;if(result)result.hidden=true;
 const preview=document.querySelector('#image-result-preview');if(preview)preview.removeAttribute('src');
 const confirm=document.querySelector('#image-confirm');if(confirm)confirm.checked=false;
 const dispatch=document.querySelector('#image-dispatch');if(dispatch)dispatch.disabled=true;
 if(imageStatus)imageStatus.textContent='';
}
function refreshImageAdapter(){
 const comfy=document.querySelector('#image-adapter').value==='comfyui';
 const quality=document.querySelector('#image-quality'),seed=document.querySelector('#image-seed');
 if(comfy)quality.value='auto';quality.disabled=comfy;seed.disabled=!comfy;
}
document.querySelector('#image-adapter').addEventListener('change',()=>{clearImage();refreshImageAdapter();});
for(const id of ['image-prompt','image-size','image-quality','image-seed','image-privacy']){
 document.querySelector('#'+id).addEventListener('input',clearImage);
}
document.querySelector('#image-preview-button').addEventListener('click',async event=>{
 if(!activeProject){imageStatus.textContent='Nejprve otevřete projekt.';return;}
 const adapter=document.querySelector('#image-adapter').value;
 const prompt=document.querySelector('#image-prompt').value;
 if(!prompt.trim()){imageStatus.textContent='Vyplňte prompt.';return;}
 if(!pendingImageRequest)pendingImageRequest={schema:'fpw-image-request-v1',
  approval_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
  project_id:activeProject.id,expected_head:activeProject.head,adapter,prompt,
  size:document.querySelector('#image-size').value,
  quality:adapter==='comfyui'?'auto':document.querySelector('#image-quality').value,
  seed:adapter==='comfyui'?Number(document.querySelector('#image-seed').value):null,
  privacy:document.querySelector('#image-privacy').value};
 event.currentTarget.disabled=true;imageStatus.textContent='Připravuji požadavek bez volání provideru…';
 try{imageApproval=await projectRequest('/v1/media/preview',pendingImageRequest);
  document.querySelector('#image-request-json').textContent=JSON.stringify(imageApproval,null,2);
  document.querySelector('#image-request-preview').hidden=false;
  document.querySelector('#image-confirm').checked=false;document.querySelector('#image-dispatch').disabled=true;
  imageStatus.textContent='Požadavek je připraven. Provider ještě nebyl zavolán.';
 }catch(error){pendingImageRequest=null;imageStatus.textContent=error.message;}
 finally{event.currentTarget.disabled=false;}
});
document.querySelector('#image-confirm').addEventListener('change',event=>{
 document.querySelector('#image-dispatch').disabled=!event.currentTarget.checked || !imageApproval;
});
document.querySelector('#image-dispatch').addEventListener('click',async event=>{
 if(!imageApproval || !document.querySelector('#image-confirm').checked || !activeProject)return;
 event.currentTarget.disabled=true;imageStatus.textContent='Odesílám potvrzený požadavek…';
 try{imageResult=await projectRequest('/v1/media/confirm',{
   approval_id:imageApproval.approval_id,project_id:activeProject.id,
   preview_sha256:imageApproval.preview_sha256,approved:true,privacy:imageApproval.privacy},210000);
  pendingImagePublish=null;const preview=document.querySelector('#image-result-preview');
  if(imageResult.image_base64)preview.src='data:image/png;base64,'+imageResult.image_base64;
  else preview.removeAttribute('src');
  document.querySelector('#image-result-metadata').textContent=JSON.stringify({
   image_sha256:imageResult.image_sha256,metadata:imageResult.metadata,
   preview_available:imageResult.preview_available},null,2);
  document.querySelector('#image-result').hidden=false;
  imageStatus.textContent=imageResult.preview_available ?
   'PNG byl validován. Uložení do projektu vyžaduje další potvrzenou akci.' :
   'PNG byl validován, ale překročil 4 MiB limit UI náhledu. Původní bajty lze uložit do projektu.';
 }catch(error){imageStatus.textContent=error.message;}
});
document.querySelector('#image-publish').addEventListener('click',async event=>{
 if(!imageResult || !activeProject)return;
 const title=document.querySelector('#image-title').value.trim();
 if(!title){imageStatus.textContent='Vyplňte název artefaktu.';return;}
 if(!pendingImagePublish)pendingImagePublish={approval_id:imageResult.approval_id,
  result_sha256:imageResult.result_sha256,project_id:activeProject.id,
  expected_head:activeProject.head,artifact_id:crypto.randomUUID(),title,
  created_at:new Date().toISOString(),operation_id:crypto.randomUUID(),privacy:imageResult.privacy};
 event.currentTarget.disabled=true;imageStatus.textContent='Ukládám původní validovaný PNG do projektu…';
 try{const projectId=activeProject.id;
  await projectRequest('/v1/media/publish',pendingImagePublish,120000);
  imageStatus.textContent='Obrázek byl uložen do projektu.';await openRegisteredProject(projectId);
 }catch(error){imageStatus.textContent=error.message;event.currentTarget.disabled=false;}
});
refreshImageAdapter();
if(window.workspaceAutoStart!==false){loadProjects();if(!backendMetricsIndicator.hidden)loadBackendMetrics();}
"""
JS += ADMIN_JS
DESKTOP_BOOTSTRAP = """document.body.dataset.runtime='desktop';
document.querySelector('#settings-profile-tab').hidden=false;
document.querySelector('[data-settings-item="settings-profile-tab"]').hidden=false;
document.querySelector('#settings-access-tab').hidden=false;
document.querySelector('[data-settings-item="settings-access-tab"]').hidden=false;
document.querySelector('#presenter-fullscreen').hidden=false;
document.querySelector('#federation-tab').hidden=false;
"""
PUBLIC_CSS = '''html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#05090c;color:#f6faf8;font:clamp(18px,2.5vw,42px) system-ui}body{display:flex;align-items:center;justify-content:center}.screen{width:86vw;aspect-ratio:16/9;display:flex;flex-direction:column;justify-content:center}.screen h1{font-size:clamp(30px,6vw,96px);color:#79c9ac;margin:0 0 3vh}.screen p{line-height:1.4;margin:0}.neutral{font-size:clamp(16px,2vw,30px);color:#94a9b5;text-align:center}'''
PUBLIC_JS = SLIDE_JS + '''
const screen=document.querySelector('#screen');
function render(result){renderSlideVisual(screen,result.visible?result.content:null,'h1');if(!result.visible){screen.replaceChildren();const empty=document.createElement('p');empty.className='neutral';empty.textContent='Veřejné okno čeká na schválený slide.';screen.append(empty);return;}screen.style.aspectRatio=result.ratio==='4:3'?'4 / 3':'16 / 9';}
async function poll(){try{const response=await fetch('/v1/presentation/public',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});if(response.ok)render(await response.json());}catch(error){}}
async function reportDisplayRatio(){const ratio=innerWidth/innerHeight>=1.55?'16:9':'4:3';try{await fetch('/v1/presentation/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'display-ratio',ratio})});}catch(error){}}
reportDisplayRatio();addEventListener('resize',reportDisplayRatio);poll();setInterval(poll,300);
'''
PUBLIC_HTML = '''<!doctype html><html lang="cs"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Veřejné promítání</title>
<link rel="stylesheet" href="/presentation-screen.css">
<main id="screen" class="screen"><p class="neutral">Veřejné okno čeká na schválený slide.</p></main><script src="/presentation-screen.js"></script></html>'''
ASSETS = {'/presentation-screen.css': ('text/css; charset=utf-8', PUBLIC_CSS),
          '/presentation-screen.js': ('text/javascript; charset=utf-8', PUBLIC_JS),
          '/': ('text/html; charset=utf-8', HTML), '/presentation-screen': ('text/html; charset=utf-8', PUBLIC_HTML), '/app.css': ('text/css; charset=utf-8', CSS),
          '/app.js': ('text/javascript; charset=utf-8', DESKTOP_BOOTSTRAP + JS)}


class DesktopHandler(Handler):
    assets = ASSETS
    google_drive_callback_path = '/'
    max_body = 4 * ((MAX_FILE + 2) // 3) + 128 * 1024
    post_paths = Handler.post_paths | {'/v1/projects', '/v1/projects/open',
        '/v1/projects/create/preview', '/v1/projects/create/confirm',
        '/v1/projects/repair/check', '/v1/projects/repair/preview',
        '/v1/projects/repair/confirm', '/v1/projects/repair/receipt',
        '/v1/projects/delete/preview', '/v1/projects/delete/confirm',
        '/v1/projects/delete/trash', '/v1/projects/delete/restore/preview',
        '/v1/projects/delete/restore/confirm', '/v1/projects/delete/purge/preview',
        '/v1/projects/delete/purge/confirm',
        '/v1/notebooklm/preview', '/v1/notebooklm/plan', '/v1/notebooklm/confirm',
        '/v1/artifacts/preview', '/v1/artifacts/history/list', '/v1/artifacts/history/compare',
        '/v1/projects/conflicts/list', '/v1/projects/conflicts/preview',
        '/v1/projects/conflicts/confirm',
        '/v1/artifacts/editor/open', '/v1/artifacts/editor/save',
        '/v1/artifacts/delete/preview', '/v1/artifacts/delete/confirm',
        '/v1/sources/import', '/v1/google-drive/status', '/v1/google-drive/configure',
        '/v1/google-drive/authorize', '/v1/google-drive/preview',
        '/v1/google-drive/confirm', '/v1/google-drive/recover',
        '/v1/chat/status', '/v1/chat/configure',
        '/v1/chat/preferences', '/v1/chat/response-language', '/v1/chat/test',
        '/v1/search/status', '/v1/search/configure', '/v1/search/test',
        '/v1/chat/send', '/v1/chat/send-stream',
        '/v1/chat/orchestration', '/v1/chat/archive', '/v1/chat/delete/preview',
        '/v1/chat/delete/confirm',
        '/v1/gamepad/status', '/v1/presentation/status',
        '/v1/gamepad/settings', '/v1/user-profile',
        '/v1/presentations/open', '/v1/presentations/save', '/v1/presentations/use',
        '/v1/presentations/export/preview',
        '/v1/presentation/control', '/v1/presentation/public',
        '/v1/external/status', '/v1/external/configure', '/v1/external/models',
        '/v1/external/propose', '/v1/external/send', '/v1/external/send-stream', '/v1/external/request',
        '/v1/external/preview', '/v1/external/confirm',
        '/v1/external/cancel',
        '/v1/tasks/route', '/v1/tasks/list', '/v1/tasks/cancel',
        '/v1/tasks/artifact', '/v1/tasks/presentation/confirm',
        '/v1/tasks/external/preview',
        '/v1/tasks/external/confirm', '/v1/tasks/external/cancel',
        '/v1/tasks/search/preview', '/v1/tasks/search/confirm',
        '/v1/tasks/public-source/preview', '/v1/tasks/public-source/confirm',
        '/v1/tasks/public-source/result',
        '/v1/chat/assign', '/v1/chat/snapshot', '/v1/chat/output',
        '/v1/workflows/status', '/v1/workflows/prepare',
        '/v1/workflows/creator/dispatch', '/v1/workflows/opponent/prepare',
        '/v1/workflows/opponent/dispatch', '/v1/workflows/publish',
        '/v1/autonomy/status', '/v1/autonomy/prepare', '/v1/autonomy/replace',
        '/v1/autonomy/search/prepare', '/v1/autonomy/search/edit',
        '/v1/autonomy/send-now',
        '/v1/autonomy/revision/propose', '/v1/autonomy/revision/confirm',
        '/v1/autonomy/research/prepare', '/v1/autonomy/research/draft',
        '/v1/autonomy/attach',
        '/v1/autonomy/detach', '/v1/autonomy/activate', '/v1/autonomy/approve',
        '/v1/autonomy/pause', '/v1/autonomy/resume', '/v1/autonomy/cancel',
        '/v1/autonomy/advance', '/v1/autonomy/pause-all',
        '/v1/autonomy/resume-all',
        '/v1/summary/status', '/v1/summary/preview', '/v1/summary/publish',
        '/v1/extraction/status', '/v1/extraction/preview', '/v1/extraction/publish',
        '/v1/metadata-suggestions/status', '/v1/metadata-suggestions/preview',
        '/v1/metadata-suggestions/publish', '/v1/media/status',
        '/v1/media/comfyui/configure', '/v1/media/openai/configure',
        '/v1/media/preview', '/v1/media/confirm', '/v1/media/publish',
        '/v1/publication-cms/status', '/v1/publication-cms/configure',
        '/v1/publication-cms/preview', '/v1/publication-cms/generate',
        '/v1/publication-cms/deployment/configure', '/v1/publication-cms/deployment/status',
        '/v1/publication-cms/deployment/preview', '/v1/publication-cms/deployment/confirm'}

    def dispatch(self, request):
        if self.path == '/v1/counter':
            return super().dispatch(request)
        if self.path == '/v1/user-profile' and isinstance(request, dict):
            service = getattr(self.server, 'user_profile', None)
            if service is None:
                return self.reply(503, {'error': 'Uživatelský profil je dostupný jen v desktopu.'})
            try:
                if request == {'action': 'load'}:
                    return self.reply(200, {'profile': service.load()})
                if request.keys() == {'action', 'profile'} and request['action'] == 'save':
                    return self.reply(200, {'profile': service.save(request['profile'])})
                return self.send_error(400)
            except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
                return self.reply(422, {'error': str(exc)})
        if self.path == '/v1/gamepad/status' and (request == {} or isinstance(request, dict)):
            return self.reply(200, scan_gamepads())
        if self.path == '/v1/gamepad/settings' and isinstance(request, dict):
            service = getattr(self.server, 'gamepad_settings', None)
            if service is None:
                return self.reply(503, {'error': 'Nastavení gamepadu je dostupné jen v desktopu.'})
            try:
                if request == {'action': 'load'}:
                    return self.reply(200, {'settings': service.load(), 'saved': service.path.exists()})
                if request.keys() == {'action', 'settings'} and request['action'] == 'save':
                    return self.reply(200, {'settings': service.save(request['settings']), 'saved': True})
                return self.send_error(400)
            except (ValueError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
                return self.reply(422, {'error': str(exc)})
        if self.path.startswith('/v1/presentations/') and isinstance(request, dict):
            service = getattr(self.server, 'presentation_documents', None)
            if service is None:
                return self.reply(503, {'error': 'Editor prezentací je dostupný jen v desktopu.'})
            try:
                if self.path == '/v1/presentations/open' and request.keys() == {'project_id', 'expected_head'}:
                    result = service.open(request['project_id'])
                    if result['commit_id'] != request['expected_head']:
                        return self.reply(409, {'error': 'Projekt se od otevření změnil. Načtěte jej znovu.'})
                    return self.reply(200, result)
                if self.path == '/v1/presentations/save' and request.keys() == {'operation_id', 'document'}:
                    service.save(request['document'], request['operation_id'])
                    return self.reply(200, service.open(request['document']['project_id']))
                if self.path == '/v1/presentations/use' and request.keys() == {'project_id', 'artifact_id', 'expected_head'}:
                    deck = service.select(request['project_id'], request['artifact_id'], request['expected_head'])
                    self.server.presentation_selected_deck = deck
                    return self.reply(200, {'deck': deck})
                if (self.path == '/v1/presentations/export/preview'
                        and request.keys() in ({'project_id', 'artifact_id', 'expected_head'},
                                               {'project_id', 'artifact_id', 'expected_head',
                                                'session_artifact_id'})):
                    session_id = request.get('session_artifact_id')
                    return self.reply(200, service.export_preview(
                        request['project_id'], request['artifact_id'], request['expected_head'],
                        session_artifact_id=session_id))
                return self.send_error(400)
            except (ValueError, TypeError, KeyError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
                return self.reply(422, {'error': str(exc)})
        if self.path == '/v1/presentation/status' and (request == {} or isinstance(request, dict)):
            try:
                if request.get('action') == 'end':
                    return self.reply(200, finish_presentation_session(self.server))
                return self.reply(200, presentation_status(self.server, start=request.get('action') == 'start'))
            except (ValueError, OSError, sqlite3.Error, ImportError) as exc:
                return self.reply(422, {'error': str(exc) or 'Prezentaci nelze připravit.'})
        if self.path == '/v1/presentation/control' and isinstance(request, dict):
            try:
                return self.reply(200, presentation_public_payload(self.server, request))
            except (ValueError, OSError, sqlite3.Error) as exc:
                return self.reply(409, {'error': str(exc)})
        if self.path == '/v1/presentation/public' and request == {}:
            return self.reply(200, presentation_public_payload(self.server))
        projects = self.server.projects or Projects()
        try:
            if self.path.startswith('/v1/google-drive/'):
                service = self.server.google_drive_import
                node = getattr(projects, 'node_path', None)
                if node is None:
                    return self.send_error(400)
                actor = getattr(self, 'actor', {}) or {}
                actor_id = actor.get('id') or ProjectCreation(node).author_id()
                if self.path == '/v1/google-drive/status' and request == {}:
                    return self.reply(200, service.status(actor_id))
                if (self.path == '/v1/google-drive/configure' and isinstance(request, dict)
                        and set(request) == {'client_id', 'client_secret'}):
                    return self.reply(200, service.configure(
                        request['client_id'], request['client_secret']))
                if (self.path == '/v1/google-drive/authorize' and isinstance(request, dict)
                        and set(request) == {'project_id', 'expected_head', 'privacy'}):
                    redirect = self.request_origin(self.request_authority()) \
                        + self.google_drive_callback_path
                    return self.reply(200, service.authorize(actor_id, request, redirect))
                if (self.path == '/v1/google-drive/preview' and isinstance(request, dict)
                        and set(request) == {'selection_id'}):
                    return self.reply(200, service.preview(actor_id, request['selection_id']))
                if (self.path == '/v1/google-drive/confirm' and isinstance(request, dict)
                        and set(request) == {'plan', 'operation_id'}):
                    result = service.confirm(actor_id, request['plan'], request['operation_id'])
                    return self.reply(200, result)
                if self.path == '/v1/google-drive/recover' and request == {}:
                    result = service.recover(actor_id)
                    return self.reply(200, {'receipt': result})
                return self.send_error(400)
            if (self.path == '/v1/workflows/status' and isinstance(request, dict)
                    and set(request) == {'project_id'}):
                result = self.server.role_workflow_service.status()
                result['workflows'] = [item for item in result['workflows']
                                       if item['project_id'] == request['project_id']]
                return self.reply(200, result)
            if self.path == '/v1/workflows/prepare' and isinstance(request, dict):
                return self.reply(200, self.server.role_workflow_service.prepare(request))
            if (self.path == '/v1/workflows/creator/dispatch' and isinstance(request, dict)
                    and set(request) == {'workflow_id', 'project_id', 'approval_digest'}):
                owned = self.server.role_workflow_service.get(request['workflow_id'])
                if owned['project_id'] != request['project_id']: return self.send_error(400)
                result = self.server.role_workflow_service.dispatch_creator(
                    request['workflow_id'], request['approval_digest'])
                return self.reply(200, result)
            if (self.path == '/v1/workflows/opponent/prepare' and isinstance(request, dict)
                    and set(request) == {'workflow_id', 'project_id'}):
                owned = self.server.role_workflow_service.get(request['workflow_id'])
                if owned['project_id'] != request['project_id']: return self.send_error(400)
                result = self.server.role_workflow_service.prepare_opponent(
                    request['workflow_id'])
                return self.reply(200, result)
            if (self.path == '/v1/workflows/opponent/dispatch' and isinstance(request, dict)
                    and set(request) == {'workflow_id', 'project_id', 'approval_digest'}):
                owned = self.server.role_workflow_service.get(request['workflow_id'])
                if owned['project_id'] != request['project_id']: return self.send_error(400)
                result = self.server.role_workflow_service.dispatch_opponent(
                    request['workflow_id'], request['approval_digest'])
                return self.reply(200, result)
            if self.path == '/v1/workflows/publish' and isinstance(request, dict):
                return self.reply(200, self.server.role_workflow_service.publish(request))
            if self.path.startswith('/v1/autonomy/') and isinstance(request, dict):
                service = getattr(self.server, 'autonomy_service', None)
                if service is None:
                    return self.reply(503, {'error': 'Řízená autonomie není dostupná.'})
                if (self.path == '/v1/autonomy/status'
                        and set(request) in ({}, {'project_id'})):
                    return self.reply(200, service.list(request.get('project_id')))
                if self.path == '/v1/autonomy/prepare':
                    return self.reply(200, service.prepare(request))
                if self.path == '/v1/autonomy/replace':
                    return self.reply(200, service.replace(request))
                if self.path == '/v1/autonomy/search/prepare':
                    return self.reply(200, service.prepare_search(request))
                if self.path == '/v1/autonomy/research/prepare':
                    return self.reply(200, service.prepare_research(request))
                if (self.path == '/v1/autonomy/research/draft'
                        and set(request) == {'workflow_id', 'step_id'}):
                    return self.reply(200, service.research_draft(
                        request['workflow_id'], request['step_id']))
                if (self.path == '/v1/autonomy/search/edit'
                        and set(request) == {'workflow_id', 'query'}):
                    return self.reply(200, service.edit_search(
                        request['workflow_id'], request['query']))
                if (self.path == '/v1/autonomy/send-now'
                        and set(request) == {
                            'workflow_id', 'step_id', 'dispatch_digest'}):
                    return self.reply(200, service.send_now(
                        request['workflow_id'], request['step_id'],
                        request['dispatch_digest']))
                if (self.path == '/v1/autonomy/activate'
                        and set(request) == {'workflow_id', 'activation_digest'}):
                    return self.reply(200, service.activate(
                        request['workflow_id'], request['activation_digest']))
                if (self.path == '/v1/autonomy/approve'
                        and set(request) == {'workflow_id', 'step_id'}):
                    return self.reply(200, service.approve(
                        request['workflow_id'], request['step_id']))
                if self.path == '/v1/autonomy/revision/propose':
                    return self.reply(200, service.propose_revision(request))
                if (self.path == '/v1/autonomy/revision/confirm'
                        and set(request) == {
                            'workflow_id', 'proposal_id', 'approval_digest'}):
                    return self.reply(200, service.confirm_revision(
                        request['workflow_id'], request['proposal_id'],
                        request['approval_digest']))
                operations = {'/v1/autonomy/attach': 'attach',
                    '/v1/autonomy/detach': 'detach',
                    '/v1/autonomy/pause': 'pause',
                    '/v1/autonomy/resume': 'resume',
                    '/v1/autonomy/cancel': 'cancel',
                    '/v1/autonomy/advance': 'advance'}
                if self.path in operations and set(request) == {'workflow_id'}:
                    return self.reply(200, getattr(service, operations[self.path])(
                        request['workflow_id']))
                if self.path == '/v1/autonomy/pause-all' and request == {}:
                    return self.reply(200, service.pause_all())
                if self.path == '/v1/autonomy/resume-all' and request == {}:
                    return self.reply(200, service.resume_all())
                return self.send_error(400)
            if self.path == '/v1/media/status' and request == {}:
                return self.reply(200, self.server.media_service.status())
            if self.path == '/v1/media/comfyui/configure' and isinstance(request, dict):
                return self.reply(200, self.server.media_service.configure_comfy(request))
            if self.path == '/v1/media/openai/configure' and isinstance(request, dict):
                return self.reply(200, self.server.media_service.configure_openai(request))
            if self.path == '/v1/media/preview' and isinstance(request, dict):
                return self.reply(200, self.server.media_service.preview(request))
            if self.path == '/v1/media/confirm' and isinstance(request, dict):
                return self.reply(200, self.server.media_service.confirm(request))
            if self.path == '/v1/media/publish' and isinstance(request, dict):
                return self.reply(200, self.server.media_service.publish(request))
            if self.path == '/v1/publication-cms/status' and request == {}:
                return self.reply(200, self.server.publication_cms.status())
            if self.path == '/v1/publication-cms/configure' and isinstance(request, dict):
                return self.reply(200, self.server.publication_cms.configure(request))
            if self.path == '/v1/publication-cms/preview' and isinstance(request, dict):
                return self.reply(200, self.server.publication_cms.preview(request))
            if self.path == '/v1/publication-cms/generate' and isinstance(request, dict):
                return self.reply(200, self.server.publication_cms.generate(request))
            if self.path == '/v1/publication-cms/deployment/configure' and isinstance(request, dict):
                return self.reply(200, self.server.publication_cms.deployment_configure(request))
            if self.path == '/v1/publication-cms/deployment/status' and request == {}:
                return self.reply(200, self.server.publication_cms.deployment_status())
            if self.path == '/v1/publication-cms/deployment/preview' and request == {}:
                return self.reply(200, self.server.publication_cms.deployment_preview(request))
            if self.path == '/v1/publication-cms/deployment/confirm' and isinstance(request, dict):
                return self.reply(200, self.server.publication_cms.deployment_confirm(request))
            if self.path == '/v1/metadata-suggestions/status' and request == {}:
                return self.reply(200, self.server.metadata_suggestion_service.status())
            if self.path == '/v1/metadata-suggestions/preview' and isinstance(request, dict):
                return self.reply(200, self.server.metadata_suggestion_service.preview(request))
            if self.path == '/v1/metadata-suggestions/publish' and isinstance(request, dict):
                return self.reply(200, self.server.metadata_suggestion_service.publish(request))
            if self.path == '/v1/extraction/status' and request == {}:
                return self.reply(200, self.server.extraction_service.status())
            if self.path == '/v1/extraction/preview' and isinstance(request, dict):
                return self.reply(200, self.server.extraction_service.preview(request))
            if self.path == '/v1/extraction/publish' and isinstance(request, dict):
                return self.reply(200, self.server.extraction_service.publish(request))
            if self.path == '/v1/summary/status' and request == {}:
                return self.reply(200, self.server.summary_service.status())
            if self.path == '/v1/summary/preview' and isinstance(request, dict):
                return self.reply(200, self.server.summary_service.preview(request))
            if self.path == '/v1/summary/publish' and isinstance(request, dict):
                return self.reply(200, self.server.summary_service.publish(request))
            if self.path == '/v1/chat/status' and request == {}:
                return self.reply(200, self.server.chat_service.status())
            if self.path == '/v1/search/status' and request == {}:
                return self.reply(200, self.server.chat_service.search_status())
            if self.path == '/v1/search/configure' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure_search(request))
            if self.path == '/v1/search/test' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.test_search(request))
            if self.path == '/v1/external/status' and request == {}:
                return self.reply(200, self.server.chat_service.external_status())
            if self.path == '/v1/external/configure' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure_external(request))
            if self.path == '/v1/external/models' and request == {}:
                return self.reply(200, self.server.chat_service.external_models())
            if self.path == '/v1/external/propose' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.external_propose(request))
            if self.path == '/v1/external/send' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.external_send(request))
            if self.path == '/v1/external/send-stream' and isinstance(request, dict):
                self.close_connection = True
                self.send_response_only(200)
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Connection', 'close')
                self.end_headers()
                def emit(value):
                    self.wfile.write(json.dumps(value, ensure_ascii=False,
                        separators=(',', ':')).encode() + b'\n'); self.wfile.flush()
                def emit_error(status, message):
                    try: emit({'type': 'error', 'status': status, 'error': message})
                    except OSError: pass
                try:
                    result = self.server.chat_service.external_send_stream(
                        request, lambda delta: emit({'type': 'delta', 'delta': delta}))
                    emit({'type': 'result', 'result': result})
                except OpenAIUnknownRun:
                    emit_error(409, 'Výsledek externího běhu není známý; požadavek automaticky neopakujte.')
                except OpenAIResponseError:
                    emit_error(502, 'Externí LLM odpověď nebylo možné bezpečně přijmout.')
                except (ValueError, OSError, sqlite3.Error):
                    emit_error(422, 'Streamovaný chat požadavek nelze provést.')
                return
            if self.path == '/v1/external/request' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.external_request(request))
            if self.path == '/v1/external/preview' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.external_preview(request))
            if self.path == '/v1/external/confirm' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.external_confirm(request))
            if self.path == '/v1/external/cancel' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.external_cancel(request))
            if self.path == '/v1/tasks/route' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_route(request))
            if (self.path == '/v1/tasks/list' and isinstance(request, dict)
                    and set(request) in ({'project_id'}, {'project_id', 'thread_id'})):
                return self.reply(200, {'outcomes': self.server.chat_service.task_outcomes(
                    project_id=request['project_id'], thread_id=request.get('thread_id'))})
            if self.path == '/v1/tasks/cancel' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_cancel(request))
            if self.path == '/v1/tasks/artifact' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_publish_artifact(request))
            if (self.path == '/v1/tasks/presentation/confirm'
                    and isinstance(request, dict)):
                return self.reply(200,
                    self.server.chat_service.task_confirm_presentation(request))
            if self.path == '/v1/tasks/external/preview' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_external_preview(request))
            if self.path == '/v1/tasks/external/confirm' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_external_confirm(request))
            if self.path == '/v1/tasks/external/cancel' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_external_cancel(request))
            if self.path == '/v1/tasks/search/preview' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_search_preview(request))
            if self.path == '/v1/tasks/search/confirm' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_search_confirm(request))
            if self.path == '/v1/tasks/public-source/preview' and isinstance(request, dict):
                return self.reply(200,
                    self.server.chat_service.task_public_source_preview(request))
            if self.path == '/v1/tasks/public-source/confirm' and isinstance(request, dict):
                return self.reply(200,
                    self.server.chat_service.task_public_source_confirm(request))
            if self.path == '/v1/tasks/public-source/result' and isinstance(request, dict):
                return self.reply(200,
                    self.server.chat_service.task_public_source_result(request))
            if self.path == '/v1/chat/configure' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure(request))
            if self.path == '/v1/chat/preferences' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure_preferences(request))
            if self.path == '/v1/chat/response-language' and isinstance(request, dict):
                return self.reply(200,
                    self.server.chat_service.configure_response_language(request))
            if self.path == '/v1/chat/test' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.test_binding(request))
            if (self.path == '/v1/chat/orchestration' and isinstance(request, dict)
                    and set(request) == {'source_thread_id', 'thread_id', 'created_at'}):
                return self.reply(200, self.server.chat_service.start_orchestration(**request))
            if (self.path == '/v1/chat/archive' and isinstance(request, dict)
                    and set(request) == {'thread_id', 'expected_revision'}):
                return self.reply(200, self.server.chat_service.archive_thread(**request))
            if (self.path == '/v1/chat/delete/preview' and isinstance(request, dict)
                    and set(request) == {'thread_id'}):
                return self.reply(200, self.server.chat_service.delete_thread_preview(**request))
            if (self.path == '/v1/chat/delete/confirm' and isinstance(request, dict)
                    and set(request) == {'thread_id', 'operation_id', 'expected_revision',
                                         'preview_sha256'}):
                return self.reply(200, self.server.chat_service.delete_thread(**request))
            chat_send_required = {
                'project_id', 'expected_head', 'thread_id', 'turn_id', 'message_id',
                'run_id', 'manifest_id', 'assistant_message_id', 'selected_message_ids',
                'content', 'privacy', 'created_at'}
            chat_send_optional = {'run_choice', 'response_language'}
            if (self.path == '/v1/chat/send-stream' and isinstance(request, dict)
                    and chat_send_required <= set(request)
                    and set(request) <= chat_send_required | chat_send_optional):
                self.close_connection = True
                self.send_response_only(200)
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Connection', 'close')
                self.end_headers()
                def emit(value):
                    self.wfile.write(json.dumps(value, ensure_ascii=False,
                        separators=(',', ':')).encode() + b'\n'); self.wfile.flush()
                def emit_error(status, message):
                    try: emit({'type': 'error', 'status': status, 'error': message})
                    except OSError: pass
                try:
                    result = self.server.chat_service.send_stream(
                        request, lambda delta: emit({'type': 'delta', 'delta': delta}),
                        lambda status: emit({'type': 'status', 'status': status}))
                    emit({'type': 'result', 'result': result})
                except UnknownRun:
                    emit_error(409, 'Výsledek lokálního LLM běhu není známý; '
                               'původní run automaticky neopakujte.')
                except OllamaResponseError:
                    emit_error(502, 'Ollama stream nevrátil bezpečně použitelný výsledek.')
                except (ValueError, OSError, sqlite3.Error):
                    emit_error(422, 'Streamovaný chat požadavek nelze provést.')
                return
            if self.path == '/v1/chat/send' and isinstance(request, dict) \
                    and chat_send_required <= set(request) \
                    and set(request) <= chat_send_required | chat_send_optional:
                return self.reply(200, self.server.chat_service.send(**request))
            if self.path == '/v1/chat/assign' and isinstance(request, dict) and set(request) == {
                    'project_id', 'thread_id', 'expected_revision'}:
                return self.reply(200, self.server.chat_service.assign(**request))
            if self.path in {'/v1/chat/snapshot', '/v1/chat/output'} and isinstance(request, dict):
                payload = dict(request); operation_id = payload.pop('operation_id', None)
                if self.path == '/v1/chat/snapshot':
                    return self.reply(200, self.server.chat_service.publish_snapshot(payload, operation_id))
                return self.reply(200, self.server.chat_service.publish_output(payload, operation_id))
            if self.path == '/v1/projects' and request == {}:
                return self.reply(200, {'projects': projects.list()})
            if self.path == '/v1/projects' and isinstance(request, dict) and set(request) == {'details'} and request['details'] is True:
                return self.reply(200, {'projects': projects.catalog()})
            if self.path.startswith('/v1/projects/repair/'):
                service = getattr(self.server, 'project_repair_actions', None)
                if service is None:
                    return self.reply(503, {'error': 'Kontrola projektu je dostupná jen v desktopu.'})
                if (self.path == '/v1/projects/repair/check' and isinstance(request, dict)
                        and set(request) == {'project_id'}):
                    return self.reply(200, service.diagnostics.check(request['project_id']))
                if (self.path == '/v1/projects/repair/preview' and isinstance(request, dict)
                        and set(request) == {'project_id', 'action', 'operation_id',
                                             'check_token'}):
                    return self.reply(200, service.preview(request))
                if (self.path == '/v1/projects/repair/confirm' and isinstance(request, dict)
                        and set(request) == {'plan'}):
                    return self.reply(200, service.confirm(request['plan']))
                if (self.path == '/v1/projects/repair/receipt' and isinstance(request, dict)
                        and set(request) == {'project_id', 'operation_id'}):
                    return self.reply(200, {'receipt': service.receipt(
                        request['project_id'], request['operation_id'])})
                return self.send_error(400)
            if self.path == '/v1/projects/create/preview' and isinstance(request, dict):
                return self.reply(200, self.server.project_creation_actions.preview(request))
            if (self.path == '/v1/projects/create/confirm' and isinstance(request, dict)
                    and set(request) == {'plan'}):
                receipt = self.server.project_creation_actions.confirm(request['plan'])
                self.server.projects = Projects(projects.node_path,
                    network=getattr(projects, 'network', False))
                return self.reply(200, receipt)
            if self.path == '/v1/projects/delete/preview':
                return self.reply(200, self.server.project_deletion_actions.preview(request))
            if self.path == '/v1/projects/delete/confirm':
                receipt = self.server.project_deletion_actions.confirm(request)
                self.server.projects = Projects(projects.node_path,
                    network=getattr(projects, 'network', False))
                return self.reply(200, receipt)
            if self.path == '/v1/projects/delete/trash' and request == {}:
                return self.reply(200, self.server.project_deletion_actions.trash())
            if self.path == '/v1/projects/delete/restore/preview':
                return self.reply(200, self.server.project_deletion_actions.restore_preview(request))
            if self.path == '/v1/projects/delete/restore/confirm':
                receipt = self.server.project_deletion_actions.restore_confirm(request)
                self.server.projects = Projects(projects.node_path,
                    network=getattr(projects, 'network', False))
                return self.reply(200, receipt)
            if self.path == '/v1/projects/delete/purge/preview':
                return self.reply(200, self.server.project_deletion_actions.purge_preview(request))
            if self.path == '/v1/projects/delete/purge/confirm':
                return self.reply(200, self.server.project_deletion_actions.purge_confirm(request))
            if self.path == '/v1/notebooklm/preview':
                return self.reply(200, self.server.notebooklm_import_actions.preview(request))
            if self.path == '/v1/notebooklm/plan':
                return self.reply(200, self.server.notebooklm_import_actions.plan(request))
            if self.path == '/v1/notebooklm/confirm':
                node = getattr(projects, 'node_path', None)
                if node is None:
                    return self.send_error(400)
                actor = getattr(self, 'actor', {}) or {}
                author = actor.get('id') or ProjectCreation(node).author_id()
                receipt = self.server.notebooklm_import_actions.confirm(
                    request, author_id=author)
                self.server.projects = Projects(node,
                    network=getattr(projects, 'network', False))
                return self.reply(200, receipt)
            if (self.path == '/v1/sources/import' and isinstance(request, dict)
                    and set(request) == {'operation_id', 'source'}
                    and isinstance(request['source'], dict)):
                node = getattr(projects, 'node_path', None)
                if node is None:
                    return self.send_error(400)
                receipt = Sources(node).import_source(request['source'], request['operation_id'])
                return self.reply(200, {'id': request['source'].get('project_id'),
                                        'commit_id': receipt['commit_id']})
            if (self.path == '/v1/projects/open' and isinstance(request, dict)
                    and set(request) == {'project_id'} and isinstance(request['project_id'], str)):
                return self.reply(200, projects.open(request['project_id']))
            if self.path.startswith('/v1/projects/conflicts/'):
                node = getattr(projects, 'node_path', None)
                if node is None:
                    return self.send_error(400)
                conflicts = ConflictResolution(
                    node, network=getattr(projects, 'network', False))
                if (self.path == '/v1/projects/conflicts/list'
                        and isinstance(request, dict)
                        and set(request) == {'project_id', 'expected_head'}):
                    return self.reply(200, conflicts.list(**request))
                if (self.path == '/v1/projects/conflicts/preview'
                        and isinstance(request, dict)
                        and set(request) == {
                            'project_id', 'expected_head', 'incoming_ref'}):
                    return self.reply(200, conflicts.preview(**request))
                if (self.path == '/v1/projects/conflicts/confirm'
                        and isinstance(request, dict)
                        and set(request) == {'operation_id', 'resolution'}
                        and isinstance(request['resolution'], dict)):
                    return self.reply(200, conflicts.confirm(
                        request['resolution'], request['operation_id']))
                return self.send_error(400)
            if (self.path == '/v1/artifacts/preview' and isinstance(request, dict)
                    and set(request) == {'project_id', 'artifact_id', 'expected_head', 'page'}):
                return self.reply(200, projects.preview(**request))
            if (self.path == '/v1/artifacts/history/list' and isinstance(request, dict)
                    and set(request) == {'project_id', 'artifact_id', 'expected_head'}):
                node = getattr(projects, 'node_path', None)
                if node is None:
                    return self.send_error(400)
                history = ArtifactHistory(node, network=getattr(projects, 'network', False))
                return self.reply(200, history.list(**request))
            if (self.path == '/v1/artifacts/history/compare' and isinstance(request, dict)
                    and set(request) == {'project_id', 'artifact_id', 'expected_head', 'older', 'newer'}):
                node = getattr(projects, 'node_path', None)
                if node is None:
                    return self.send_error(400)
                history = ArtifactHistory(node, network=getattr(projects, 'network', False))
                return self.reply(200, history.compare(**request))
            if self.path.startswith(('/v1/artifacts/editor/', '/v1/artifacts/delete/')):
                node = getattr(projects, 'node_path', None)
                if node is None:
                    return self.send_error(400)
                actions = ArtifactActions(node, network=getattr(projects, 'network', False))
                if (self.path == '/v1/artifacts/editor/open' and isinstance(request, dict)
                        and set(request) == {'project_id', 'artifact_id', 'expected_head'}):
                    return self.reply(200, actions.open(**request))
                if (self.path == '/v1/artifacts/editor/save' and isinstance(request, dict)
                        and set(request) == {'operation_id', 'document'}
                        and isinstance(request['document'], dict)):
                    return self.reply(200, actions.save(request['document'], request['operation_id']))
                if (self.path == '/v1/artifacts/delete/preview' and isinstance(request, dict)
                        and set(request) == {'project_id', 'artifact_id', 'expected_head'}):
                    return self.reply(200, actions.deletion_preview(**request))
                if (self.path == '/v1/artifacts/delete/confirm' and isinstance(request, dict)
                        and set(request) == {'project_id', 'artifact_id', 'base_head',
                                             'preview_sha256', 'operation_id'}):
                    return self.reply(200, actions.delete(**request))
                return self.send_error(400)
            return self.send_error(400)
        except UnknownRun as exc:
            return self.reply(409, {'error': 'Výsledek lokálního LLM běhu není známý. Původní '
                                   'run se nesmí opakovat; zadání lze vědomě odeslat jako nový běh.',
                                   'diagnostic': exc.code, 'outcome': 'unknown',
                                   'retry': 'new-run'})
        except OpenAIUnknownRun:
            return self.reply(409, {'error': 'Výsledek externího běhu není známý. Požadavek '
                                   'automaticky neopakujte; stav byl zachován.'})
        except BackendUnknown:
            message = ('Výsledek workflow kroku není známý. Požadavek automaticky '
                       'neopakujte; pro nový pokus vytvořte nové workflow.'
                       if self.path.startswith('/v1/workflows/') else
                       'Výsledek obrazového běhu není známý. Požadavek automaticky '
                       'neopakujte; pro nový pokus použijte nové ID.')
            return self.reply(409, {'error': message})
        except CloudflareUnknown:
            return self.reply(409, {'error': 'Výsledek Cloudflare deploymentu není známý. '
                                   'Požadavek automaticky neopakujte; načtěte skutečný stav provideru.'})
        except CloudflareUnavailable:
            return self.reply(502, {'error': 'Cloudflare stav nyní nelze bezpečně načíst. '
                                   'Nebyla zahájena nová potvrzená změna.'})
        except SearchUnknown as exc:
            return self.reply(409, {'error': 'Výsledek webového hledání není známý. Původní '
                                   'search ID se nesmí automaticky opakovat; připravte nový dotaz.',
                                   'diagnostic': exc.code, 'outcome': 'unknown',
                                   'retry': 'new-search'})
        except SearchResponseError as exc:
            messages = {'not-configured': ('SearXNG není nakonfigurován. Otevřete Nastavení → '
                                           'AI backend → Řízené webové hledání.'),
                'unavailable': 'SearXNG endpoint není dostupný.',
                'connect-timeout': 'Vypršel čas při spojování se SearXNG.',
                'tls-failed': 'TLS spojení se SearXNG se nepodařilo ověřit.',
                'tls-pin-mismatch': 'Certifikát SearXNG neodpovídá uloženému otisku.',
                'redirect-forbidden': 'SearXNG vrátilo zakázané přesměrování.',
                'invalid-json': 'SearXNG nevrátilo platný JSON.',
                'response-invalid': 'SearXNG vrátilo neplatné nebo nebezpečné výsledky.',
                'response-too-large': 'Odpověď SearXNG překročila bezpečný limit.',
                'overloaded': 'SearXNG je přetížené.'}
            return self.reply(422 if exc.code == 'not-configured' else 502,
                              {'error': messages.get(exc.code,
                                   'Webové hledání bezpečně selhalo.'),
                                   'diagnostic': exc.code, 'outcome': 'failed',
                                   'retry': ('configure-search' if exc.code == 'not-configured'
                                             else 'new-search')})
        except PublicSourceUnknown as exc:
            return self.reply(409, {'error': 'Výsledek načtení veřejného zdroje není známý. '
                                   'Původní run se nesmí automaticky opakovat.',
                                   'diagnostic': exc.code, 'outcome': 'unknown',
                                   'retry': 'new-fetch'})
        except (PublicSourceUnsupported, PublicSourceRejected, PublicSourceError) as exc:
            state = getattr(exc, 'state', 'failed')
            messages = {'robots-disallowed': 'robots.txt načtení této stránky zakazuje.',
                'robots-unavailable': 'robots.txt nyní neumožňuje bezpečně rozhodnout.',
                'redirect-requires-approval': ('Zdroj přesměrovává jinam. Nový cíl vyžaduje '
                                               'samostatný náhled a potvrzení.'),
                'authentication-required': 'Zdroj vyžaduje přihlášení, které reader nepodporuje.',
                'unsupported-mime': 'Zdroj není podporovaný statický HTML nebo text.',
                'unsupported-charset': 'Zdroj nepoužívá podporované UTF-8 kódování.',
                'no-static-text': ('Stránka bez JavaScriptu neobsahuje podporovaný statický '
                                   'text. Reader JavaScript nespouští.'),
                'overloaded': 'Zdroj je přetížený; automatické opakování nebylo provedeno.'}
            return self.reply(422 if state in {'unsupported', 'rejected'} else 502,
                {'error': messages.get(exc.code, 'Veřejný zdroj nelze bezpečně načíst.'),
                 'diagnostic': exc.code, 'outcome': state, 'retry': 'new-fetch'})
        except DriveAccessError:
            return self.reply(502, {'error': 'Google Drive není dostupný nebo byl přístup odvolán. '
                                   'Projekt nebyl změněn.'})
        except OllamaResponseError as exc:
            messages = {
                'unavailable': 'Ollama endpoint není dostupný.',
                'connect-timeout': 'Vypršel čas při navazování spojení s Ollamou.',
                'tls-failed': 'TLS spojení s LAN Ollamou se nepodařilo ověřit.',
                'tls-pin-mismatch': 'Certifikát LAN Ollamy neodpovídá uloženému SHA-256 otisku.',
                'model-unavailable': 'Požadovaný model není na Ollama serveru dostupný.',
                'api-incompatible': 'Endpoint neposkytuje podporované Ollama API.',
                'overloaded': 'Ollama je přetížená a požadavek odmítla.',
                'redirect-forbidden': 'Ollama endpoint vrátil zakázané přesměrování.',
                'invalid-json': 'Ollama nevrátila platný JSON.',
                'invalid-envelope': 'Ollama vrátila neplatný formát odpovědi.',
                'response-too-large': 'Odpověď Ollamy překročila bezpečný limit.',
                'access-denied': 'Ollama proxy požadavek odmítla.',
                'healthcheck-unavailable': 'Test spojení s Ollamou byl přerušen.'}
            return self.reply(502, {'error': messages.get(exc.code,
                                   'Lokální LLM požadavek selhal.'),
                                   'diagnostic': exc.code, 'outcome': 'failed',
                                   'retry': 'new-run'})
        except OpenAIResponseError:
            if self.path == '/v1/external/models':
                return self.reply(502, {'error': 'Seznam modelů externího provideru nelze načíst. '
                                       'Uložené nastavení nebylo změněno.'})
            return self.reply(502, {'error': 'Externí LLM odpověď nebylo možné bezpečně přijmout. '
                                   'Běh byl ukončen bez automatického opakování.'})
        except BackendResponseError:
            return self.reply(502, {'error': 'Obrazový backend nevrátil bezpečně použitelný PNG '
                                   'výsledek. Běh byl ukončen bez automatického opakování.'})
        except PendingOperation:
            return self.reply(409, {'error': 'Projekt má nedokončenou operaci. Nejprve proveďte obnovu.'})
        except StaleIndex:
            return self.reply(409, {'error': 'Projekt se během čtení změnil. Zkuste jej znovu otevřít.'})
        except BlockingIOError:
            return self.reply(409, {'error': 'Projekt právě používá jiná zapisující operace. '
                                   'Po jejím dokončení spusťte novou kontrolu.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
            if (isinstance(exc, ValidationError)
                    and self.path == '/v1/tasks/search/confirm'
                    and str(exc) in {
                        'Ollama returned an invalid iterative search evaluation',
                        'Ollama cited an unavailable search source',
                        'Ollama returned invalid search limitations',
                        'Ollama returned invalid follow-up search queries',
                        'Ollama returned duplicate follow-up search queries',
                        'Final search evaluation cannot request another query'}):
                return self.reply(422, {'error':
                    'Ollama vrátila neplatné hodnocení výsledků hledání. '
                    'Uložené výsledky nebyly změněny ani automaticky zopakovány. '
                    'Zahoďte tento návrh a spusťte nové hledání.'})
            if isinstance(exc, ValidationError) and self.path in {
                    '/v1/chat/send', '/v1/chat/send-stream', '/v1/tasks/route'}:
                if (self.path == '/v1/tasks/route'
                        and str(exc) == 'Ollama returned invalid presentation proposal'):
                    return self.reply(422, {'error':
                        'Ollama vytvořila návrh prezentace, ale ten nesplnil povinný formát '
                        'nebo povolené vazby na zdroje a layouty. '
                        'Projekt ani předchozí vlákno nebyly změněny.'})
                message = CHAT_VALIDATION_ERRORS.get(str(exc))
                if message is not None:
                    return self.reply(422, {'error': message})
            if isinstance(exc, ValidationError) and self.path.startswith(
                    '/v1/autonomy/'):
                message = AUTONOMY_VALIDATION_ERRORS.get(str(exc))
                if message is not None:
                    return self.reply(422, {'error': message})
            if self.path == '/v1/external/propose':
                return self.reply(422, {'error': 'Ollama nevrátila platný návrh externího volání. '
                                       'Zkuste návrh vytvořit znovu nebo použijte ruční externí náhled.'})
            if self.path == '/v1/tasks/route':
                return self.reply(422, {'error': 'Ollama vrátila neplatný formát výsledku úlohy. '
                                       'Projekt ani předchozí vlákno nebyly změněny.'})
            if self.path == '/v1/tasks/presentation/confirm':
                return self.reply(422, {'error':
                    'Potvrzení prezentace nelze dokončit: návrh, schválení nebo projektová revize '
                    'se změnily. Načtěte aktuální stav; pokud návrh zůstane dostupný, opakování '
                    'stejného tlačítka zachová identitu operace.'})
            if self.path.startswith(('/v1/publication-cms/', '/v1/chat/', '/v1/search/', '/v1/external/', '/v1/tasks/', '/v1/workflows/', '/v1/autonomy/', '/v1/summary/', '/v1/extraction/', '/v1/media/',
                                     '/v1/metadata-suggestions/')):
                message = ('Publikační CMS požadavek nelze provést. Ověřte přítomnost, povolení a verzi '
                           'modulu, konfiguraci a lokální recovery stav.' if self.path.startswith('/v1/publication-cms/') else
                           'Chat požadavek nelze provést. Ověřte backend, projekt, výběr kontextu a lokální stav.')
                return self.reply(422, {'error': message})
            if self.path == '/v1/sources/import':
                return self.reply(422, {'error': 'Zdroj nelze importovat. Ověřte typ, velikost, metadata a aktuální verzi projektu.'})
            if self.path.startswith('/v1/google-drive/'):
                return self.reply(422, {'error': 'Google Drive import nelze provést. Obnovte výběr '
                                       'a ověřte konfiguraci, privacy, limity a aktuální projekt.'})
            if self.path.startswith('/v1/projects/create/'):
                return self.reply(422, {'error': 'Projekt nelze vytvořit. Obnovte náhled a ověřte název, umístění a dostupnost úložiště.'})
            if self.path.startswith('/v1/projects/delete/'):
                return self.reply(422, {'error': 'Akci projektu nelze provést. Obnovte náhled a ověřte blokující operace, vazby a lokální stav.'})
            if self.path.startswith('/v1/projects/repair/'):
                return self.reply(422, {'error': 'Kontrolu nebo opravu nelze dokončit. '
                                       'Načtěte nový stav a ověřte přesně uvedenou ruční příčinu.'})
            if self.path.startswith('/v1/notebooklm/'):
                message = {
                    'Directory must not be writable by other users':
                        'Cílová složka má příliš otevřená práva. Nastavte jí práva 0700 a obnovte plán.',
                    'Existující cílová složka musí být prázdná.':
                        'Cílová složka už není prázdná. Vyberte jinou složku a obnovte plán.',
                    'Cílový lokální stav již existuje.':
                        'Pro tento cíl už existuje lokální stav. Zvolte jinou prázdnou složku.',
                }.get(str(exc))
                if message:
                    return self.reply(422, {'error': message})
                return self.reply(422, {'error': 'Import NotebookLM nelze provést. Obnovte náhled a ověřte archiv, výběr, privacy a cílové úložiště.'})
            if self.path.startswith('/v1/artifacts/history/'):
                return self.reply(422, {'error': 'Historii nelze zobrazit. Ověřte dokument, oprávnění a aktuální verzi projektu.'})
            if self.path.startswith(('/v1/artifacts/editor/', '/v1/artifacts/delete/')):
                return self.reply(422, {'error': 'Akci dokumentu nelze provést. Ověřte aktuální verzi, metadata, vztahy a recovery stav projektu.'})
            # Do not forward paths, Git stderr or configuration payloads to the renderer.
            return self.reply(422, {'error': 'Projekt nelze otevřít: ověřte konfiguraci, registraci, '
                                   'práva lokálního stavu a platnost Git dat/indexu.'})

    def do_GET(self):
        authority = self.request_authority()
        if authority is None:
            return self.send_error(403)
        parsed = urlsplit(self.path)
        query = None
        if parsed.path == self.google_drive_callback_path and parsed.query:
            try:
                query = parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
            except ValueError:
                pass
        if query is not None and 'state' in query:
            try:
                allowed = {'state', 'code', 'picked_file_ids', 'scope', 'iss', 'error'}
                if not set(query) <= allowed or any(len(values) != 1 for values in query.values()) \
                        or 'state' not in query or ('scope' in query and query['scope'] != [SCOPE]) \
                        or ('iss' in query and query['iss'] != [GOOGLE_ISSUER]):
                    raise ValueError('Neplatná OAuth callback odpověď.')
                self.server.google_drive_import.callback(
                    query['state'][0], query.get('code', [''])[0],
                    query.get('picked_file_ids', [''])[0], query.get('error', [None])[0])
                title = 'Výběr Google Drive byl přijat'
                body = 'Vraťte se do pracovního prostoru; náhled importu se načte automaticky.'
            except (ValueError, OSError, sqlite3.Error, DriveAccessError):
                title = 'Výběr Google Drive se nepodařilo přijmout'
                body = 'Vraťte se do pracovního prostoru a spusťte nový výběr.'
            data = ('<!doctype html><html lang="cs"><meta charset="utf-8"><title>' + title
                    + '</title><body><h1>' + title + '</h1><p>' + body
                    + '</p><p>Toto okno můžete zavřít.</p></body></html>').encode()
            self.close_connection = True
            self.send_response_only(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")
            self.send_header('Connection', 'close')
            self.end_headers(); self.wfile.write(data)
            return
        if self.path not in self.assets:
            return self.send_error(404)
        kind, content = self.assets[self.path]
        data = content.encode()
        self.close_connection = True
        self.send_response_only(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src data:; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
