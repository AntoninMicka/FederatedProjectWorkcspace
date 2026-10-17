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
from spikes.projects import Projects
from spikes.project_creation import ProjectCreation
from spikes.source_import import Sources
from spikes.google_drive_import import GoogleDriveImport, DriveAccessError, GOOGLE_ISSUER, SCOPE
from spikes.gamepad_settings import DEFAULT_GAMEPAD_SETTINGS
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation
from spikes.web_search import SearchResponseError, SearchUnknown
from spikes.web_administration import ADMIN_HTML, ADMIN_CSS, ADMIN_JS


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
<aside id="workspace-sidebar" aria-label="Navigace pracovního prostoru"><div class="brand">◈ &nbsp; WORKSPACE</div>
<div id="sidebar-projects"><h2>Projekty</h2><ul id="sidebar-project-list"></ul>
<p id="sidebar-project-status" role="status">Načítám projekty…</p></div>
<button id="open-notebooklm-import" class="global-nav" type="button" hidden>Importovat NotebookLM</button>
<div id="sidebar-project-tools" hidden>
<button id="back-projects" class="sidebar-back" type="button">← Seznam projektů</button>
<div id="sidebar-tabs" role="tablist" aria-label="Obsah levého panelu">
<button id="todo-tab" role="tab" aria-controls="todo-widget" aria-selected="true">Úkoly</button>
<button id="artifacts-tab" role="tab" aria-controls="sidebar-artifacts" aria-selected="false" tabindex="-1">Podklady</button>
<button id="chats-tab" role="tab" aria-controls="sidebar-chats" aria-selected="false" tabindex="-1">Chaty</button>
<button id="presentations-tab" role="tab" aria-controls="sidebar-presentations" aria-selected="false" tabindex="-1">Prezentace</button></div>
<div id="todo-widget" role="tabpanel" aria-labelledby="todo-tab" tabindex="0"><h2>Hlavní seznam úkolů</h2>
<p id="todo-status" role="status">Otevřete projekt.</p><div id="todo-title"></div>
<button id="create-main-todo" hidden>Vytvořit seznam úkolů</button>
<ul id="todo-tree" aria-label="Úkoly projektu"></ul><small id="todo-help" hidden>Úkoly upravíte v editoru.</small></div>
<div id="sidebar-artifacts" role="tabpanel" aria-labelledby="artifacts-tab" tabindex="0" hidden>
<h2>Podklady</h2><div class="sidebar-artifact-primary-actions"><button id="new-document" type="button">Nový dokument</button>
<button id="open-source-import" type="button">Importovat zdroj</button></div>
<p id="sidebar-artifact-status" role="status"></p>
<ul id="sidebar-artifact-list" aria-label="Podklady projektu"></ul></div>
<div id="sidebar-chats" role="tabpanel" aria-labelledby="chats-tab" tabindex="0" hidden>
<h2>Chaty</h2><p id="sidebar-chat-status" role="status">Otevřete projekt.</p>
<div class="sidebar-chat-primary-actions"><button id="chat-new-thread" type="button">Nové vlákno</button>
<button id="chat-open-settings" type="button">Nastavení backendu</button></div>
<ul id="sidebar-chat-tree" role="tree" aria-label="Uložené chaty"></ul></div>
<div id="sidebar-presentations" role="tabpanel" aria-labelledby="presentations-tab" tabindex="0" hidden>
<h2>Prezentace</h2><p id="sidebar-presentation-status" role="status">Otevřete projekt.</p>
<ul id="sidebar-presentation-list" aria-label="Hotové prezentace projektu"></ul></div></div>
<button id="open-settings" class="global-nav" type="button">Nastavení</button>
<button id="logout" type="button">Odhlásit</button><div class="node-note">Na tomto uzlu<br>Zkušební verze</div></aside>
<main><div id="project-home">
<header><span class="badge">Pracovní prostor</span><span>Vaše projekty, zdroje a rozhodnutí</span></header>
<div class="home-heading"><div class="eyebrow">VAŠE PRÁCE NA JEDNOM MÍSTĚ</div>
<h1>Projekty</h1><p>Vyberte projekt a pokračujte tam, kde jste skončili.</p></div>
<p id="project-status" role="status" aria-live="polite">Načítám projekty…</p>
<div id="project-cards" aria-label="Seznam projektů"></div>
<section id="project-delete-panel" class="creation-preview" hidden><h2 id="project-delete-title">Akce projektu</h2>
<label id="project-delete-mode-row">Režim <select id="project-delete-mode"><option value="clear-derived">Obnovit odvozený index</option><option value="unregister">Pouze odregistrovat</option><option value="trash" selected>Přesunout do obnovitelného koše</option></select></label>
<pre id="project-delete-details"></pre><p id="project-delete-blockers" role="alert"></p>
<label class="confirm"><input id="project-delete-check" type="checkbox"> Potvrzuji přesný lokální rozsah této akce.</label>
<div class="form-actions"><button id="project-delete-confirm" type="button" disabled>Provést potvrzenou akci</button>
<button id="project-delete-cancel" type="button" class="secondary-button">Zrušit</button></div>
<p id="project-delete-status" role="status"></p></section>
<details id="project-trash"><summary>Obnovitelný koš projektů</summary><div id="project-trash-list"></div>
<p id="project-trash-status" role="status"></p></details>
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
<p id="create-project-status" role="status"> </p></form>
<p class="home-help">Dostupné akce určuje tento uzel a vaše oprávnění.</p>
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
<section id="settings-profile-panel" class="settings-card" role="tabpanel" aria-labelledby="settings-profile-tab" hidden>
<h2>Uživatelský profil</h2><p>Jméno a kontakty pro závěrečný slide prezentace. Platí pro tohoto uživatele desktopu.</p>
<button id="user-profile-open" type="button">Upravit profil…</button></section>
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
<header class="project-header"><div><span class="eyebrow">OTEVŘENÝ PROJEKT</span><h1 id="project-title"></h1></div>
<details><summary>Uložená verze</summary><code id="project-commit"></code></details></header>
<section id="workspace-panel" aria-label="Pracovní prostor">
<div id="main-tabs" role="tablist" aria-label="Hlavní panel">
<button id="preview-tab" role="tab" aria-controls="preview-panel" aria-selected="true">Náhled</button>
<button id="chat-tab" role="tab" aria-controls="chat-panel" aria-selected="false" tabindex="-1">Chat</button>
<button id="workflow-tab" role="tab" aria-controls="workflow-panel" aria-selected="false" tabindex="-1">Creator → opponent</button>
<button id="summary-tab" role="tab" aria-controls="summary-panel" aria-selected="false" tabindex="-1">Souhrn</button>
<button id="extraction-tab" role="tab" aria-controls="extraction-panel" aria-selected="false" tabindex="-1">Extrakce</button>
<button id="image-tab" role="tab" aria-controls="image-panel" aria-selected="false" tabindex="-1">Obrázek</button>
<button id="presentation-tab" role="tab" aria-controls="presentation-panel" aria-selected="false" tabindex="-1">Prezentace</button>
<button id="metadata-tab" role="tab" aria-controls="metadata-panel" aria-selected="false" tabindex="-1">Metadata</button></div>
<div id="main-panel-content">
<div id="preview-panel" role="tabpanel" aria-labelledby="preview-tab">
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
<form id="chat-composer"><label for="chat-draft">Zadání úkolu</label>
<label for="chat-mode">Režim</label><select id="chat-mode"><option value="orchestration">Orchestrace</option><option value="brainstorming">Brainstorming</option></select>
<label for="chat-run-adapter">Backend</label><select id="chat-run-adapter"><option value="ollama">Lokální Ollama</option><option value="openai-responses">OpenAI</option></select>
<label for="chat-run-model">Model běhu</label><input id="chat-run-model" maxlength="128" list="external-models">
<p id="chat-orchestration-target" role="status" aria-live="polite"></p>
<label for="chat-privacy">Soukromí</label><select id="chat-privacy"><option value="project">V rámci projektu</option><option value="confidential">Důvěrné</option><option value="local-only">Jen na tomto počítači</option><option value="public">Veřejné</option></select>
<details id="task-artifacts"><summary>Doplňující podklady</summary>
<fieldset><legend>Explicitně předat lokálnímu modelu</legend><div id="task-artifact-list"></div></fieldset></details>
<div class="prompt-row"><textarea id="chat-draft" rows="2" maxlength="16000" placeholder="Co chcete v projektu zpracovat?"></textarea>
<button id="chat-submit" type="submit" disabled>Zpracovat</button></div>
<details id="advanced-external"><summary>Pokročilé ruční externí volání</summary>
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
<small>Enter odešle, Shift+Enter vloží nový řádek · historie zůstává lokálně na tomto uzlu</small></form>
</section>
</div><output id="backend-metrics-indicator" hidden aria-live="polite">OpenAI přehled: nenačten</output>
<div id="presenter-view" hidden>
<header class="presenter-header"><div class="presenter-header-main"><span class="badge">Presenter · NÁCVIK</span><h1>Disclosure cockpit</h1><p>Demo workspace · Ukázková schůzka · Interní demo · r1</p></div>
<div class="presenter-header-state"><strong id="presenter-live-state">NEAKTIVNÍ</strong><span>Schůzka <b id="presenter-meeting-time">00:00</b></span><span>Odbočka <b id="presenter-branch-time">00:00</b></span><span id="presenter-exposure">Expozice 0 · +0</span><button id="presenter-back" class="back-button" type="button">← Zpět do workspace</button></div></header>
<p id="presenter-status" role="status">Presenter není spuštěný.</p>
<div class="presenter-layout">
<nav class="presenter-deck" aria-label="Pořadí prezentace"><h2>Pořadí prezentace</h2><ol id="presenter-deck-list"></ol><p id="presenter-return-anchor">Návrat: hlavní slide 01</p></nav>
<section class="presenter-audience" aria-label="Náhled veřejného výstupu"><div class="presenter-kicker">ZMENŠENÝ NÁHLED VEŘEJNÉHO VÝSTUPU</div>
<div class="presenter-slide-preview" id="presenter-screen" tabindex="0" aria-live="polite"><p>Spusťte prezentaci.</p></div>
<section class="presenter-notes"><h2>Poznámky k promítanému obsahu</h2><p id="presenter-notes">Poznámky se zobrazí po spuštění.</p><details><summary>Stručná osnova</summary><p id="presenter-outline">Osnova se zobrazí po spuštění.</p></details><p class="presenter-alert" id="presenter-alert">Interní upozornění: soukromý výběr není promítnutý.</p></section>
<div class="presenter-controls"><button id="presenter-prev" type="button" disabled>Předchozí</button><button id="presenter-next" type="button" disabled>Další</button><button id="presenter-fullscreen" type="button" disabled>Celá obrazovka</button><button id="presenter-blackout" type="button">Zatemnit</button></div></section>
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
</div>
</main><script src="/app.js"></script></body></html>'''
CSS = '''*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:#f4f7fa;color:#162638;font:15px system-ui;display:flex;height:100vh;overflow:hidden}
#mobile-sidebar-toggle,#mobile-sidebar-backdrop{display:none}
aside{width:238px;height:100vh;min-height:0;box-sizing:border-box;flex-shrink:0;background:#142638;color:#c8d4df;padding:28px 20px;display:flex;flex-direction:column;overflow:hidden}
.brand{flex:none;font-weight:750;letter-spacing:2px;color:white;margin-bottom:24px}.global-nav{flex:none;margin-top:auto;background:#176b60;text-align:left}.node-note{flex:none;font-size:11px;line-height:1.8;padding-top:18px;color:#9eb5c7}
main{flex:1;min-width:0;padding:26px 32px;overflow:auto}header{display:flex;justify-content:space-between;gap:16px;align-items:center;color:#627183;font-size:12px}
.badge{color:#1c6556;background:#e0efe9;border-radius:20px;padding:8px 13px}.eyebrow{font-size:11px;color:#31796e;font-weight:750;letter-spacing:2px}
h1{font-size:32px;margin:12px 0}h2{font-size:21px}p{line-height:1.6;color:#627183}button,textarea,input{font:inherit}
button{border:0;border-radius:8px;background:#176b60;color:white;font-weight:600;padding:12px 18px;cursor:pointer}
button:hover{background:#12564d}button:disabled{opacity:.5;cursor:default}button:focus-visible,textarea:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #59b6aa;outline-offset:3px}
summary{cursor:pointer}code,li,dd,h1,h2,button{overflow-wrap:anywhere}small{font-size:11px;color:#627183}
#gamepad-list{list-style:none;padding-left:0;margin:12px 0 0;display:flex;flex-direction:column;gap:8px}
#gamepad-list li{background:#edf7f4;border:1px solid #d2e5e0;border-radius:8px;padding:8px 12px;color:#1f3a41}
.home-heading,.settings-heading{margin-top:44px}.home-heading h1{font-size:38px}.home-help{font-size:13px;margin-top:24px}
.settings-card{max-width:720px;background:white;border:1px solid #dce3e9;border-radius:16px;padding:22px 26px;margin:24px 0}.settings-card label{display:block;margin:12px 0}.settings-card input,.settings-card select,.settings-card textarea{padding:9px;max-width:100%}.settings-card input,.settings-card textarea{width:100%}.settings-card textarea{resize:vertical}.settings-card small{display:block;margin-top:16px}
.settings-card .settings-toggle{display:flex;align-items:center;gap:9px}.settings-card .settings-toggle input{width:auto}
.cms-card{max-width:900px}.cms-actions,.cms-domain-row{display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:18px 0}.cms-domain-row label{flex:1}.cms-domain-row input,.cms-domain-row select{width:100%}#cms-sections{display:flex;gap:18px;flex-wrap:wrap;margin:18px 0;border:1px solid #dce3e9;border-radius:10px;padding:12px}#cms-sections label{margin:0}#cms-sections input{width:auto}#cms-sections small{display:block;color:#61706d;margin-left:22px}#cms-preview{border-top:1px solid #dce3e9;margin-top:20px;padding-top:14px}#cms-request-preview{white-space:pre-wrap;max-height:260px;overflow:auto;background:#f5f7fb;padding:12px;border-radius:8px}#cms-preview-frame{width:100%;min-height:520px;border:1px solid #bfcdc9;border-radius:10px;background:white}.confirm{padding:12px;background:#fffaf0;border:1px solid #d6b36a;border-radius:8px}.confirm input{width:auto}
.provider-link{color:#176b60;font-weight:600}
.search-sources li{margin:12px 0}.search-sources strong,.search-sources code,.search-sources small{display:block}.search-sources code{margin:4px 0;color:#245c73;white-space:normal}
.search-budget{font-size:12px;color:#456276}.search-round{border-left:3px solid #8db6c8;margin:12px 0;padding:4px 0 4px 12px}.search-round h4{margin:0 0 4px}.search-round>small,.search-evaluation small{display:block;color:#456276;overflow-wrap:anywhere}.search-evaluation{background:#f4f7fa;border-radius:8px;margin-top:8px;padding:10px}.search-evaluation p{margin:6px 0}
#backend-metrics-indicator{position:fixed;right:14px;bottom:10px;z-index:20;
 background:#142638e8;color:#dce8f1;border:1px solid #496072;border-radius:12px;
 padding:6px 10px;font-size:11px;box-shadow:0 3px 12px #14263830;max-width:60vw;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#settings-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 8px}#settings-tabs button[aria-selected="false"]{background:#e8eef2;color:#304657}
#project-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px;margin-top:24px}.project-card-wrap{display:grid;gap:6px;min-width:0}.project-remove{justify-self:end;background:transparent;color:#8b3030;padding:7px 9px;font-size:12px}.project-remove:hover{background:#fff1f1}.trash-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 0;border-bottom:1px solid #dce5eb}.trash-row code{overflow-wrap:anywhere}.trash-row .danger{background:#8b3030}#project-delete-blockers{color:#8b3030;white-space:pre-wrap}#project-trash{margin:18px 0}#project-trash-list{margin-top:8px}
.project-card{background:white;color:#162638;border:1px solid #dce5eb;border-radius:16px;padding:24px;text-align:left;min-height:190px;display:flex;flex-direction:column;gap:14px;box-shadow:0 5px 20px #18364808}
.project-card:hover{background:#fafffd;border-color:#4b9e8c;box-shadow:0 8px 24px #18364812}
.project-card .project-name{font-size:21px;line-height:1.4}.project-card .project-description{font-size:13px;color:#627183;font-weight:400;line-height:1.6}
.project-card .project-id{font-size:11px;color:#82909d;font-weight:400;margin-top:auto}.project-card .project-action{color:#176b60;font-size:13px}
.diagnostics{margin-top:32px;color:#627183;font-size:12px}.diagnostics button{margin:14px 12px 0 0}.diagnostics output{font-size:20px}
aside h2{font-size:16px;color:white}aside p{font-size:12px;color:#aabecf}aside small{color:#aabecf}
#sidebar-project-list,#sidebar-artifact-list,#sidebar-chat-tree,#sidebar-chat-tree ul,#sidebar-presentation-list,#todo-tree{list-style:none;padding:0;margin:14px 0}
#sidebar-project-list button,#sidebar-artifact-list button,#sidebar-chats button{display:block;text-align:left;width:100%;background:transparent;color:#dce8f1;padding:10px 8px;font-size:13px}
#sidebar-project-list button:hover,#sidebar-artifact-list button:hover,#sidebar-chats button:hover{background:#274154}
#sidebar-artifact-list button[aria-current="true"]{background:#274154;border-left:3px solid #79c9ac}
.sidebar-artifact-row{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start}.sidebar-artifact-main{min-width:0}.sidebar-artifact-id{display:block;font-size:10px;color:#8faabc;margin:0 8px 10px;overflow-wrap:anywhere}.sidebar-artifact-title{font-size:13px}
#sidebar-chats button[aria-current="true"]{background:#274154;border-left:3px solid #79c9ac}
.sidebar-chat-meta{display:block;font-size:10px;color:#8faabc;margin-top:4px;overflow-wrap:anywhere}
.sidebar-chat-primary-actions,.sidebar-artifact-primary-actions{display:grid;grid-template-columns:1fr 1fr;gap:6px}.sidebar-chat-primary-actions button,.sidebar-artifact-primary-actions button{padding:8px 6px;font-size:11px}
.sidebar-chat-branch{margin-top:12px}.sidebar-chat-branch-toggle{display:flex!important;align-items:center;gap:7px;color:#a9bdca!important;font-size:11px!important;text-transform:uppercase;letter-spacing:.06em}
.sidebar-chat-branch-toggle::before{content:'▾';font-size:10px}.sidebar-chat-branch[aria-expanded="false"]>.sidebar-chat-branch-toggle::before{content:'▸'}
.sidebar-chat-branch[aria-expanded="false"]>[role="group"]{display:none}.sidebar-chat-branch>[role="group"]{margin:2px 0 8px}
.sidebar-chat-row{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:start}
.sidebar-chat-row>.sidebar-chat-open{min-width:0}.sidebar-chat-menu{position:relative;margin-top:4px}
.sidebar-chat-menu>summary{display:block;list-style:none;cursor:pointer;color:#dce8f1;padding:8px;border-radius:8px;font-weight:700}
.sidebar-chat-menu>summary::-webkit-details-marker{display:none}.sidebar-chat-menu>summary:hover,.sidebar-chat-menu[open]>summary{background:#274154}
.sidebar-chat-menu-items{position:absolute;z-index:30;right:0;top:100%;width:190px;padding:6px;background:#f8fbfd;border:1px solid #8faabc;border-radius:10px;box-shadow:0 8px 22px #07131f55}
#sidebar-chats .sidebar-chat-menu-items button{display:block;width:100%;padding:9px 10px;text-align:left;background:transparent;color:#20384b;font-size:12px}
#sidebar-chats .sidebar-chat-menu-items button:hover{background:#dfecea}.sidebar-chat-menu-items button:disabled{display:none}
.sidebar-presentation-row{padding:10px 8px;border-bottom:1px solid #274154}.sidebar-presentation-row strong,.sidebar-presentation-row small{display:block;overflow-wrap:anywhere}.sidebar-presentation-row small{margin-top:4px;color:#8faabc;font-size:10px}.sidebar-presentation-actions{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}#sidebar-presentations .sidebar-presentation-actions button{padding:7px 5px;font-size:11px;text-align:center;background:#274154}#sidebar-presentations .sidebar-presentation-actions button:hover{background:#36566d}#sidebar-presentations .sidebar-presentation-actions button:disabled{opacity:.55}
.sidebar-artifact-menu{position:relative;margin-top:4px}.sidebar-artifact-menu>summary{display:block;list-style:none;cursor:pointer;color:#dce8f1;padding:8px;border-radius:8px;font-weight:700}.sidebar-artifact-menu>summary::-webkit-details-marker{display:none}.sidebar-artifact-menu>summary:hover,.sidebar-artifact-menu[open]>summary{background:#274154}.sidebar-artifact-menu-items{position:absolute;z-index:30;right:0;top:100%;width:190px;padding:6px;background:#f8fbfd;border:1px solid #8faabc;border-radius:10px;box-shadow:0 8px 22px #07131f55}#sidebar-artifacts .sidebar-artifact-menu-items button{display:block;width:100%;padding:9px 10px;text-align:left;background:transparent;color:#20384b;font-size:12px}#sidebar-artifacts .sidebar-artifact-menu-items button:hover{background:#dfecea}
#sidebar-tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:18px}#sidebar-tabs button{font-size:12px;padding:8px 6px;border:1px solid #496072;background:transparent;color:#c8d4df}
#sidebar-tabs button[aria-selected="true"]{background:#274154;color:white;border-color:#79c9ac}
#sidebar-projects:not([hidden]),#sidebar-project-tools:not([hidden]){flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}
#sidebar-project-tools>[role="tabpanel"]:not([hidden]){flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}
#sidebar-tabs,.sidebar-back{flex:none}.sidebar-back{background:transparent;color:#dce8f1;text-align:left;padding:8px;margin:0 0 14px}.sidebar-back:hover{background:#274154}
#sidebar-project-list,#todo-tree,#sidebar-artifact-list,#sidebar-chat-tree,#sidebar-presentation-list{min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin}
#sidebar-project-list,#todo-tree,#sidebar-artifact-list,#sidebar-presentation-list{flex:1}
#sidebar-project-tools>#sidebar-chats:not([hidden]){display:grid;grid-template-rows:auto auto auto minmax(0,1fr)}
#todo-title{font-size:13px;font-weight:600;overflow-wrap:anywhere}#todo-tree ul{padding-left:14px;list-style:none;border-left:1px solid #496072;margin-left:4px}
#todo-tree li{font-size:13px;margin:8px 0}.todo-label{display:inline-flex;gap:7px;align-items:baseline;max-width:100%}.todo-label input{flex-shrink:0;accent-color:#79c9ac}.todo-text{overflow-wrap:anywhere;min-width:0}
.todo-done>.todo-label .todo-text,.todo-done>details>summary .todo-text{color:#a9c5b7;text-decoration:line-through}
#project-view{height:100%;display:flex;flex-direction:column;gap:16px}.project-header{flex-shrink:0}.project-header h1{font-size:25px;color:#162638;margin:6px 0}
.project-header details{max-width:280px}.project-header code{font-size:10px}
#workspace-panel{min-height:0;flex:1;display:flex;flex-direction:column;background:white;border:1px solid #dce3e9;border-radius:16px;overflow:hidden}
#main-tabs{display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid #dce3e9;padding:16px;flex-shrink:0}
#main-tabs button[aria-selected="false"]{background:#e8eef2;color:#304657}
#main-panel-content{overflow:auto;padding:0 22px 20px;flex:1;min-height:0}
#preview-status{font-size:12px}#preview-content img{max-width:100%;height:auto}#preview-content pre{white-space:pre-wrap;background:#eff3f6;padding:16px}
#preview-content p{white-space:pre-wrap;margin:6px 0}#preview-content h1{font-size:28px}#preview-title{font-size:20px}
#preview-metadata{overflow-wrap:anywhere}#preview-metadata dt{font-weight:600;margin-top:10px}#preview-metadata dd{margin:4px 0;white-space:pre-wrap}
#pdf-controls{margin:16px 0}#pdf-page{width:75px;margin:0 12px;padding:10px}
#chat-composer{flex-shrink:0;border-top:1px solid #dce3e9;background:#fafffd;padding:14px 20px}#chat-composer label{font-weight:600;font-size:12px}
#external-preview,#external-proposal,#search-preview,.deletion-preview{margin-top:12px;border:1px solid #d6b36a;background:#fffaf0;border-radius:10px;padding:12px}#external-preview pre,#search-preview pre,.deletion-preview pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:260px;overflow:auto}#external-proposal-messages label{display:block;margin:7px 0}
#task-artifacts,#advanced-external{margin:8px 0;color:#456276;font-size:12px}#task-artifacts fieldset{border:1px solid #dce3e9;margin:8px 0;padding:8px 12px;max-height:130px;overflow:auto}#task-artifact-list label{display:block;font-weight:400;margin:5px 0}.task-outcome{border:1px solid #dce3e9;border-radius:12px;margin:14px 0;padding:14px 18px;background:#fffaf0}.task-outcome.terminal{background:#f4f7fa}.task-outcome pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:none}.task-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.task-actions button{padding:8px 12px}.artifact-link{color:#176b60;background:transparent;padding:0;text-align:left}.artifact-link:hover{background:transparent;text-decoration:underline}
.prompt-row{display:flex;gap:10px;margin:8px 0}.prompt-row textarea{resize:vertical;min-height:64px;max-height:150px;flex:1;min-width:0;border:1px solid #bfcdc9;border-radius:8px;padding:10px;background:white}
.prompt-row button{align-self:flex-end}.chat-message{padding:14px 18px;background:#edf5f2;border-radius:12px;margin:14px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.chat-message.assistant{background:#eef1fa}.chat-message small{display:block;margin-top:6px}.secondary-button{background:#e8eef2;color:#304657;margin:0 8px 12px 0}.secondary-button:hover{background:#dce6eb}#chat-privacy{padding:7px;max-width:100%}#chat-operation-status{font-size:12px;min-height:20px;margin:2px 0;color:#315f58}
#chat-stream-status.chat-live-progress{display:flex;align-items:center;gap:10px;min-height:52px;color:#304657;font-weight:600}
.chat-progress-spinner{width:12px;height:12px;flex:0 0 auto;border:3px solid #afc3d8;border-top-color:#526ca4;border-radius:50%;animation:chat-stream-spin .8s linear infinite}
@keyframes chat-stream-spin{to{transform:rotate(360deg)}}
@media(prefers-reduced-motion:reduce){.chat-progress-spinner{animation:none;border-top-color:#afc3d8;background:#526ca4}}
#summary-panel label,#extraction-panel label{display:block;margin:10px 0 5px}#summary-panel textarea,#summary-panel input,#summary-panel select,#extraction-panel textarea,#extraction-panel input,#extraction-panel select{padding:9px;max-width:100%}#summary-focus,#extraction-focus{width:100%;resize:vertical}#summary-artifacts,#extraction-panel fieldset{margin:14px 0;border:1px solid #dce3e9}#summary-artifact-list label,#extraction-artifact-list label{font-weight:400}#summary-status,#extraction-status{font-size:12px;min-height:20px;color:#315f58}#summary-preview,#extraction-preview{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#summary-preview:empty,#extraction-preview:empty{display:none}#summary-preview p{white-space:pre-wrap;margin:6px 0}#extraction-preview{white-space:pre-wrap;overflow:auto}#summary-publish-controls,#extraction-publish-controls{border-top:1px solid #dce3e9;padding-top:12px}
#workflow-panel label{display:block;margin:10px 0 5px}#workflow-panel textarea,#workflow-panel input,#workflow-panel select{padding:9px;max-width:100%}#workflow-purpose{width:100%;resize:vertical}#workflow-panel fieldset{margin:14px 0;border:1px solid #dce3e9}#workflow-panel fieldset label{font-weight:400}#workflow-status{font-size:12px;min-height:20px;color:#315f58}#workflow-panel section{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#workflow-panel pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:360px;overflow:auto}#workflow-publish{border-top:1px solid #dce3e9}
#metadata-panel label{display:block;margin:10px 0 5px}#metadata-panel select{padding:9px;max-width:100%;margin-bottom:10px}#metadata-status{font-size:12px;min-height:20px;color:#315f58}#metadata-diff{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#metadata-diff p,#metadata-diff span{white-space:pre-wrap}#metadata-diff fieldset{margin:14px 0;border:1px solid #dce3e9}#metadata-tag-list label{font-weight:400}
#image-panel label{display:block;margin:10px 0 5px}#image-panel textarea,#image-panel input,#image-panel select{padding:9px;max-width:100%}#image-prompt{width:100%;box-sizing:border-box;resize:vertical}#image-status{font-size:12px;min-height:20px;color:#315f58}#image-request-preview,#image-result{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#image-request-json,#image-result-metadata{white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto}#image-result-preview{display:block;max-width:100%;max-height:520px;margin:12px auto}#image-result-preview:not([src]){display:none}
#presentation-panel{min-height:100%}.presentation-editor-head,.presentation-editor-footer{display:flex;justify-content:space-between;align-items:end;gap:16px;flex-wrap:wrap}.presentation-editor-head h2{margin-bottom:0}.presentation-editor-head p{margin-top:4px}.presentation-editor-head label{display:flex;align-items:center;gap:8px}.presentation-editor-head select{padding:8px;max-width:300px}.presentation-editor-workspace{display:grid;grid-template-columns:minmax(220px,26%) minmax(300px,1fr) minmax(260px,34%);gap:14px;margin-top:14px}.presentation-editor-workspace>section{background:#fff;border:1px solid #dce3e9;border-radius:12px;padding:14px;min-width:0}.presentation-editor-workspace label{display:block;margin:8px 0}.presentation-editor-workspace input[type="text"],.presentation-editor-workspace input[type="number"],.presentation-editor-workspace textarea,.presentation-editor-workspace select{width:100%;padding:8px}.presentation-editor-options{display:grid;grid-template-columns:1fr 1fr;gap:4px 12px}.presentation-editor-options label:first-child{grid-column:1/-1}.presentation-editor-options input[type="color"]{width:64px;height:36px;padding:2px}.presentation-editor-slides ol{list-style:none;padding:0;max-height:420px;overflow:auto}.presentation-editor-slides li button{display:block;width:100%;text-align:left;background:#edf2f5;color:#304657;margin:5px 0;padding:9px}.presentation-editor-slides li button[aria-current="true"]{background:#176b60;color:#fff}.presentation-editor-slides li.backup button{border-left:4px solid #d6b36a}.presentation-template-manager{margin-top:14px;border-top:1px solid #dce3e9;padding-top:10px}.presentation-template-manager summary{font-weight:700}.presentation-template-manager .form-actions{display:grid;grid-template-columns:1fr 1fr}.presentation-template-manager .form-actions button:last-child{grid-column:1/-1}.presentation-template-colors{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.presentation-template-colors input[type="color"]{width:100%;height:36px;padding:2px}.presentation-editor-fields fieldset{margin-top:12px;border:1px solid #dce3e9}.presentation-editor-fields #presentation-backup-links label{font-weight:400}.presentation-editor-preview #presentation-editor-preview{width:100%;aspect-ratio:16/9;background:#10222f;color:#f6faf8;overflow:hidden}.presentation-session-section{margin-top:16px;padding:14px;background:#fff;border:1px solid #dce3e9;border-radius:12px}.presentation-session-section ul{list-style:none;padding:0}.presentation-session-section li{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid #dce3e9}.presentation-session-section small{display:block;color:#526675}.presentation-editor-footer{margin-top:12px;border-top:1px solid #dce3e9}.presentation-editor-footer>p{flex:1}.danger-button{background:#9b3f3f}.danger-button:hover{background:#7d3030}#presentation-print-view{display:none}
@media print{body>*{display:none!important}#presentation-print-view{display:block!important}#presentation-print-view .print-slide{display:block;break-after:page;width:16in;height:9in;page-break-after:always}#presentation-print-view .print-slide:last-child{break-after:auto;page-break-after:auto}@page{size:16in 9in;margin:0}}
.back-button{align-self:flex-start;background:transparent;color:#456276;padding:8px 0;font-size:13px;flex-shrink:0}.back-button:hover{background:transparent;color:#176b60}
@media(max-width:780px){aside{width:185px;padding:22px 12px}main{padding:18px}#project-cards{grid-template-columns:1fr}.prompt-row{flex-direction:column}.project-header details{max-width:140px}}
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
 #project-cards{grid-template-columns:minmax(0,1fr);gap:12px}.project-card{min-width:0;min-height:0;padding:18px}
 #project-view{height:auto;min-height:calc(100vh - 92px);min-height:calc(100dvh - 92px)}
 #workspace-panel{min-width:0;overflow:visible}#main-panel-content{overflow:visible;padding:0 14px 18px}
 #main-tabs,#settings-tabs{flex-wrap:nowrap;overflow-x:auto;overscroll-behavior-x:contain;scroll-snap-type:x proximity;padding:12px;scrollbar-width:thin}
 #main-tabs button,#settings-tabs button{flex:0 0 auto;min-height:44px;scroll-snap-align:start}
 .settings-card,#workflow-panel section,#image-request-preview,#image-result,#metadata-diff{max-width:100%;padding:16px 14px;border-radius:12px}
 button{min-height:44px}input,select,textarea{font-size:16px;max-width:100%}fieldset{min-width:0}
 .prompt-row,.cms-domain-row{align-items:stretch}.prompt-row button,.cms-domain-row button{width:100%}
 .confirm{display:flex!important;align-items:flex-start;gap:10px;overflow-wrap:anywhere}.confirm input{flex:0 0 auto;margin-top:4px}
 pre,code,output,[role="status"],[role="alert"]{max-width:100%;overflow-wrap:anywhere;word-break:break-word}
 #preview-content pre,#workflow-panel pre,#image-request-json,#image-result-metadata,#external-preview pre,#cms-request-preview{white-space:pre-wrap;overflow-x:auto}
 #pdf-controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}#pdf-page{margin:0}
 #backend-metrics-indicator{right:8px;bottom:8px;max-width:calc(100vw - 16px)}
}
@media(max-width:640px) and (prefers-reduced-motion:reduce){aside{transition:none}}
@media(max-width:1000px){.presentation-editor-workspace{grid-template-columns:1fr 1fr}.presentation-editor-preview{grid-column:1/-1}}
@media(max-width:700px){.presentation-editor-workspace{grid-template-columns:1fr}.presentation-editor-preview{grid-column:auto}.presentation-editor-head label{display:block}.presentation-editor-head select{max-width:100%;width:100%}}
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
#source-import-view,#notebooklm-import-view,#history-view,#artifact-editor-view{height:100%;overflow:auto}.standalone-form{max-width:820px;padding:20px;background:white;border:1px solid #dce3e9;border-radius:12px}
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
@media(max-width:780px){aside{width:185px;padding:22px 12px}main{padding:18px}#project-cards{grid-template-columns:1fr}.prompt-row{flex-direction:column}.presenter-layout{grid-template-columns:1fr;min-height:auto}.presenter-deck{max-height:190px}.presenter-audience{min-height:460px}.presenter-speaker{min-height:560px}}
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
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=true;loadPresenter();
}
async function closePresenter(){
 let saved=false;
 try{const result=await projectRequest('/v1/presentation/status',{action:'end'},120000);saved=result.saved;}
 catch(error){presenterStatus.textContent=`Záznam relace nelze uzavřít: ${error.message}`;return;}
 location.hash='presenter-close';document.body.classList.remove('presenter-active');presenterView.hidden=true;
 if(activeProject){const projectId=activeProject.id;projectView.hidden=false;document.querySelector('#sidebar-project-tools').hidden=false;if(saved){await openRegisteredProject(projectId);await loadPresentationEditor(presentationEditorArtifact,false);sidebarPresentationStatus.textContent='Relace byla uložena do projektu.';}}
 else{document.querySelector('#project-home').hidden=false;document.querySelector('#sidebar-projects').hidden=false;}
}
presentationOpenButton.addEventListener('click',openPresenter);
document.querySelector('#presenter-back').addEventListener('click',closePresenter);
presenterPrevButton.addEventListener('click',()=>movePresenter(-1));
presenterNextButton.addEventListener('click',()=>movePresenter(1));
presenterFullscreenButton.textContent='Displeje a role…';
presenterFullscreenButton.addEventListener('click',()=>{location.hash='presenter-displays';});
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
const mobileViewport=window.matchMedia('(max-width:640px)');
let mobileSidebarReturnFocus=null;
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
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('mobile-sidebar-open')){event.preventDefault();closeMobileSidebar();}});
workspaceSidebar.addEventListener('click',event=>{if(event.target.closest('#back-projects,#open-notebooklm-import,#open-settings,#new-document,#open-source-import,#sidebar-project-list button,.sidebar-artifact-title,.sidebar-artifact-menu-items button,.sidebar-chat-open,.sidebar-chat-menu-items button,.sidebar-presentation-actions button,#chat-new-thread,#chat-open-settings'))closeMobileSidebar();});
mobileViewport.addEventListener('change',()=>{document.body.classList.remove('mobile-sidebar-open');syncMobileSidebar();});
syncMobileSidebar();
const sidebarTabs=[...document.querySelectorAll('#sidebar-tabs [role="tab"]')];
function selectSidebarTab(selected){
 for(const tab of sidebarTabs){
  const active=tab===selected;
  tab.setAttribute('aria-selected',String(active));tab.tabIndex=active ? 0 : -1;
  document.getElementById(tab.getAttribute('aria-controls')).hidden=!active;
 }
}
for(const tab of sidebarTabs){
 tab.addEventListener('click',()=>selectSidebarTab(tab));
 tab.addEventListener('keydown',event=>{
  const visible=sidebarTabs.filter(item=>!item.hidden),index=visible.indexOf(tab);
  const next={ArrowRight:(index+1)%visible.length,
   ArrowLeft:(index-1+visible.length)%visible.length,
   Home:0,End:visible.length-1}[event.key];
  if(next===undefined) return;
  event.preventDefault();selectSidebarTab(visible[next]);visible[next].focus();
 });
}
let currentArtifacts=[];
function renderSidebarArtifacts(items){
 currentArtifacts=items;
 sidebarArtifacts.replaceChildren();
 sidebarArtifactStatus.textContent=items.length ? `Počet položek: ${items.length}` : 'Zatím tu nejsou žádné podklady.';
 for(const item of items){
  const row=document.createElement('li');row.className='sidebar-artifact-row';
  const main=document.createElement('div');main.className='sidebar-artifact-main';
  const title=document.createElement('button');title.className='sidebar-artifact-title';title.textContent=item.title;
  title.dataset.id=item.id;title.setAttribute('aria-current','false');
  title.addEventListener('click',()=>openPreview(item.id));
  const id=document.createElement('small');id.className='sidebar-artifact-id';id.textContent=item.id;
  main.append(title,id);row.append(main);
  if(item.kind==='document'){
   const menu=document.createElement('details');menu.className='sidebar-artifact-menu';
   const trigger=document.createElement('summary');trigger.setAttribute('aria-label',`Akce dokumentu ${item.title}`);trigger.textContent='⋮';
   const actions=document.createElement('div');actions.className='sidebar-artifact-menu-items';actions.setAttribute('role','menu');
   function action(label,callback){const button=document.createElement('button');button.type='button';button.textContent=label;button.setAttribute('role','menuitem');button.addEventListener('click',async event=>{event.stopPropagation();menu.open=false;await callback();});actions.append(button);}
   action('Upravit / přejmenovat',()=>openArtifactEditor(item));
   const history=document.createElement('button');history.type='button';history.textContent='Zobrazit historii';history.setAttribute('role','menuitem');
   history.addEventListener('click',async event=>{event.stopPropagation();menu.open=false;await openPreview(item.id);if(selectedArtifact===item.id)await openHistory();});
   actions.append(history);
   action('Připravit smazání',()=>openArtifactEditor(item,true));
   action('Kopírovat ID',async()=>{try{await navigator.clipboard.writeText(item.id);sidebarArtifactStatus.textContent='ID dokumentu bylo zkopírováno.';}catch(error){sidebarArtifactStatus.textContent=`ID dokumentu: ${item.id}`;}});
   menu.append(trigger,actions);row.append(menu);
  }
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
  const row=document.createElement('li');row.dataset.depth=item.depth;
  const label=document.createElement('span');label.className='todo-label';
  const check=document.createElement('input');check.type='checkbox';check.checked=item.checked;check.disabled=true;
  check.setAttribute('aria-label',item.checked ? 'Hotovo' : 'Nehotovo');
  const title=document.createElement('span');title.className='todo-text';title.textContent=item.title;
  label.append(check,title);
  if(item.checked) row.classList.add('todo-done');
  if(todo.items[i+1]?.depth>item.depth){
   const branch=document.createElement('details');branch.open=true;
   const summary=document.createElement('summary');summary.append(label);branch.append(summary);
   const children=document.createElement('ul');branch.append(children);row.append(branch);
   lists[item.depth+1]=children;
  }else{row.append(label);}
  lists[item.depth].append(row);
 }
}
function clearProject(){
 ++viewRequest;
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
 settingsView.hidden=true;
 sourceImportView.hidden=true;
 notebookImportView.hidden=true;
 historyView.hidden=true;
 artifactEditorView.hidden=true;
 document.querySelector('#sidebar-projects').hidden=false;document.querySelector('#sidebar-project-tools').hidden=true;
 selectMainTab(mainTabs[0]);
 sidebarArtifacts.replaceChildren();sidebarArtifactStatus.textContent='Otevřete projekt.';
 todoTree.replaceChildren();document.querySelector('#todo-title').textContent='';
 todoStatus.textContent='Otevřete projekt.';createTodo.hidden=true;document.querySelector('#todo-help').hidden=true;
 projectView.hidden=true;
 document.querySelector('#project-title').textContent='';
 document.querySelector('#project-commit').textContent='';
}
async function projectRequest(path,body,timeout=60000){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify(body),signal:AbortSignal.timeout(timeout)});
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
 if(activeProject){projectView.hidden=false;document.querySelector('#sidebar-project-tools').hidden=false;}
 else{document.querySelector('#project-home').hidden=false;document.querySelector('#sidebar-projects').hidden=false;}
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
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
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
function canLeaveWorkspaceEditors(){return canLeaveArtifactEditor()&&canLeavePresentationEditor();}
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
 if(activeProject){projectView.hidden=false;document.querySelector('#sidebar-project-tools').hidden=false;if(item&&!item.new)await openPreview(item.id);}
}
async function openArtifactEditor(item,deleteMode=false){
 if(!activeProject||item.kind!=='document')return;
 if(!artifactEditorView.hidden&&!canLeaveWorkspaceEditors())return;
 await openPreview(item.id);if(selectedArtifact!==item.id)return;
 const project=activeProject;artifactEditorItem=item;artifactEditorAttempt=null;hideArtifactDeletion();
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;historyView.hidden=true;projectView.hidden=true;artifactEditorView.hidden=false;
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
 artifactEditorStatus.textContent='Načítám uložený dokument…';
 try{const result=await projectRequest('/v1/artifacts/editor/open',{project_id:project.id,artifact_id:item.id,expected_head:project.head});
  if(activeProject!==project||artifactEditorItem!==item)return;
  fillArtifactEditor(result.document);
  artifactEditorStatus.textContent='Uložená verze je připravena k úpravě.';
  if(deleteMode)await prepareArtifactDeletion();else artifactEditorForm.elements.title.focus();
 }catch(error){artifactEditorStatus.textContent=error.message;}
}
function openNewArtifactEditor({todo=false}={}){
 if(!activeProject||(!artifactEditorView.hidden&&!canLeaveWorkspaceEditors()))return;
 const id=todo?activeProject.mainTodoId:crypto.randomUUID();
 artifactEditorItem={id,kind:'document',new:true};hideArtifactDeletion();
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;historyView.hidden=true;projectView.hidden=true;artifactEditorView.hidden=false;
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
 fillArtifactEditor(todo?{title:'Hlavní seznam úkolů',filename:'content.md',body:'# Hlavní seznam úkolů\\n\\n- [ ] První úkol\\n'}:{title:'',filename:'content.md',body:''},true);
 artifactEditorStatus.textContent='Dokument vznikne až po uložení.';artifactEditorForm.elements.title.focus();
}
function openMainTodoEditor(){
 if(!activeProject)return;const item=currentArtifacts.find(candidate=>candidate.id===activeProject.mainTodoId);
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
window.addEventListener('beforeunload',event=>{if(artifactEditorDirty||artifactEditorAttempt){event.preventDefault();event.returnValue='';}});
function localRunRetryHint(error){return [409,422,502].includes(error.status) ?
 ' Vstupy zůstaly zachovány; další potvrzení vytvoří vědomě nový běh.' : '';}
let catalogRequest=0;
async function openRegisteredProject(projectId){
 if(!canLeaveWorkspaceEditors())return;
 ++catalogRequest;
 clearProject();const request=viewRequest;
 projectStatus.textContent='Otevírám projekt…';
 try{
  const result=await projectRequest('/v1/projects/open',{project_id:projectId});
  if(request!==viewRequest)return;
  activeProject={id:projectId,head:result.commit_id,mainTodoId:result.main_todo_id};
  renderTodo(result.main_todo);renderSidebarArtifacts(result.artifacts);
  document.querySelector('#project-title').textContent=result.title;
  document.querySelector('#project-commit').textContent=result.commit_id;
  sourceImportView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;projectView.hidden=false;document.querySelector('#project-home').hidden=true;
  document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
  await loadChat();
  selectSidebarTab(document.querySelector('#artifacts-tab'));
  document.querySelector('#preview-status').textContent=result.artifacts.length ?
   'Vyberte podklad ze seznamu vlevo.' : 'Projekt zatím nemá žádné podklady.';
 }catch(error){if(request===viewRequest)projectStatus.textContent=error.message;}
}
function renderProjectCatalog(items){
 projectCards.replaceChildren();sidebarProjects.replaceChildren();
 for(const item of items){
  const wrap=document.createElement('div');wrap.className='project-card-wrap';
  const card=document.createElement('button');card.type='button';card.className='project-card';card.dataset.id=item.id;
  const name=document.createElement('span');name.className='project-name';name.textContent=item.title;
  const description=document.createElement('span');description.className='project-description';
  description.textContent=item.available ? (item.description.slice(0,240) || 'Prostor pro zdroje, poznámky a rozhodnutí.') : 'Projekt nelze načíst. Ověřte jeho umístění a konfiguraci.';
  const id=document.createElement('span');id.className='project-id';id.textContent=item.id;
  const action=document.createElement('span');action.className='project-action';action.textContent=item.available?'Otevřít projekt →':'Zkusit otevřít →';
  card.append(name,description,id,action);card.addEventListener('click',()=>openRegisteredProject(item.id));
  const remove=document.createElement('button');remove.type='button';remove.className='project-remove';remove.textContent='Správa odstranění…';
  remove.addEventListener('click',()=>openProjectDeletion(item));wrap.append(card,remove);projectCards.append(wrap);
  const row=document.createElement('li');const compact=document.createElement('button');compact.type='button';compact.dataset.id=item.id;
  compact.textContent=item.title;compact.title=item.id;compact.addEventListener('click',()=>openRegisteredProject(item.id));row.append(compact);sidebarProjects.append(row);
 }
 document.querySelector('#sidebar-project-status').textContent=items.length ? `Počet projektů: ${items.length}` : 'Zatím bez projektů.';
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
 }catch(error){document.querySelector('#project-trash-status').textContent=error.message;}
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
  await loadProjectTrash();
  projectStatus.textContent=result.projects.length ? 'Vyberte projekt.' : 'Zatím nemáte žádný projekt.';
  if(selectedId && result.projects.some(p=>p.id===selectedId))await openRegisteredProject(selectedId);
 }catch(error){if(request===catalogRequest){projectStatus.textContent=error.message;document.querySelector('#sidebar-project-status').textContent='Seznam není dostupný.';}}
}
document.querySelector('#back-projects').addEventListener('click',()=>loadProjects());

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
function openNotebookLMImport(){
 if(!canLeaveWorkspaceEditors())return;
 clearProject();
 document.querySelector('#project-home').hidden=true;projectView.hidden=true;settingsView.hidden=true;
 sourceImportView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;notebookImportView.hidden=false;
 document.querySelector('#sidebar-projects').hidden=false;document.querySelector('#sidebar-project-tools').hidden=true;
 notebookStatus.textContent=notebookArchiveCapability?'Pokračujte načtením nebo výběrem projektu.':'Vyberte export Google Takeout.';
}
function closeNotebookLMImport(){notebookImportView.hidden=true;document.querySelector('#project-home').hidden=false;document.querySelector('#sidebar-projects').hidden=false;}
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
function selectMainTab(tab){
 for(const item of mainTabs){
  const active=item===tab;item.setAttribute('aria-selected',String(active));item.tabIndex=active?0:-1;
  document.getElementById(item.getAttribute('aria-controls')).hidden=!active;
 }
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
function renderSidebarPresentations(){
 sidebarPresentationList.replaceChildren();
 for(const doc of presentationEditorView.documents){
  const item=document.createElement('li'),title=document.createElement('strong'),identity=document.createElement('small'),actions=document.createElement('div'),edit=document.createElement('button'),start=document.createElement('button');
  item.className='sidebar-presentation-row';title.textContent=doc.title+(doc.error?' — neplatná':'');identity.textContent=doc.id;actions.className='sidebar-presentation-actions';edit.type='button';edit.textContent='Upravit';start.type='button';start.textContent='Spustit';edit.disabled=Boolean(doc.error);start.disabled=Boolean(doc.error);
  edit.addEventListener('click',()=>openPresentationEditor(doc.id));start.addEventListener('click',()=>usePresentationDocument(doc));actions.append(edit,start);item.append(title,identity,actions);sidebarPresentationList.append(item);
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
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;notebookImportView.hidden=true;historyView.hidden=true;projectView.hidden=false;document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
 selectMainTab(presentationTab);presentationTab.focus();if(!presentationEditorView||presentationEditorView.commit_id!==activeProject.head)await loadPresentationEditor(preferred,true);else if(preferred){const document=presentationEditorView.documents.find(item=>item.id===preferred&&item.deck);if(document){if(!canLeavePresentationEditor())return;presentationEditorDocuments.value=document.id;installPresentationDocument(document);}}
}
function createPresentationDocument(confirmDiscard=true){
 if(confirmDiscard&&!canLeavePresentationEditor())return;presentationEditorDeck=presentationNewDeck();presentationEditorArtifact=crypto.randomUUID();presentationEditorSlide=presentationEditorDeck.slides[0].id;presentationEditorNew=true;presentationEditorDirty=true;presentationEditorAttempt=null;presentationEditorDocuments.value='';renderPresentationEditor();presentationEditorStatus.textContent='Koncept je pouze v editoru. Soubor vznikne až po uložení.';
}
presentationTab.addEventListener('click',()=>{if(!presentationEditorView||presentationEditorView.commit_id!==activeProject?.head)loadPresentationEditor();else if(!presentationEditorDeck)renderPresentationDocuments();});
document.querySelector('#presentations-tab').addEventListener('click',()=>{if(!presentationEditorView||presentationEditorView.commit_id!==activeProject?.head)loadPresentationEditor(null,false);else renderSidebarPresentations();});
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
let settingsReturn=null;
const settingsTabs=[...document.querySelectorAll('#settings-tabs [role="tab"]')];
function selectSettingsTab(selected){
 for(const tab of settingsTabs){
  const active=tab===selected;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
  const panel=document.getElementById(tab.getAttribute('aria-controls'));if(panel)panel.hidden=!active;
 }
 const administration=document.getElementById('administration');if(administration)administration.hidden=!['settings-users-tab','settings-federation-tab'].includes(selected.id);
 if(selected.id==='settings-cms-tab')loadCmsStatus();
}
for(const [index,tab] of settingsTabs.entries()){
 tab.addEventListener('click',()=>selectSettingsTab(tab));
 tab.addEventListener('keydown',event=>{
  const visible=settingsTabs.filter(item=>!item.hidden);const current=visible.indexOf(tab);
  const next={ArrowRight:(current+1)%visible.length,ArrowLeft:(current+visible.length-1)%visible.length,Home:0,End:visible.length-1}[event.key];
  if(next===undefined)return;event.preventDefault();visible[next].click();visible[next].focus();
 });
}
async function openSettings(){
 if(!canLeaveWorkspaceEditors())return;
 const activeTab=mainTabs.find(tab=>tab.getAttribute('aria-selected')==='true');
 settingsReturn={project:!!activeProject,tabId:activeTab?.id || 'preview-tab',sourceImport:!sourceImportView.hidden};
 document.querySelector('#project-home').hidden=true;projectView.hidden=true;sourceImportView.hidden=true;notebookImportView.hidden=true;historyView.hidden=true;artifactEditorView.hidden=true;settingsView.hidden=false;
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=true;
 selectSettingsTab(document.querySelector('#settings-backend-tab'));
 document.querySelector('#settings-backend-status').textContent='Načítám stav lokálního backendu…';
 await loadBackendBinding();
}
async function closeSettings(){
 const destination=settingsReturn;settingsReturn=null;settingsView.hidden=true;
 document.dispatchEvent(new Event('settingsclosed'));
 if(destination?.sourceImport && activeProject){openSourceImport();return;}
 if(destination?.project && activeProject){
  projectView.hidden=false;document.querySelector('#sidebar-project-tools').hidden=false;
  const tab=document.getElementById(destination.tabId);if(tab)selectMainTab(tab);
  await loadBackendBinding();
 }else{
  document.querySelector('#project-home').hidden=false;document.querySelector('#sidebar-projects').hidden=false;
 }
}
document.querySelector('#open-settings').addEventListener('click',openSettings);
document.querySelector('#chat-open-settings').addEventListener('click',openSettings);
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
document.querySelector('#user-profile-open').addEventListener('click',()=>{location.hash='user-profile';});
function clearPreview(){
 ++previewRequest;selectedArtifact=null;previewContent.replaceChildren();
 for(const button of sidebarArtifacts.querySelectorAll('button'))button.setAttribute('aria-current','false');
 document.querySelector('#preview-title').textContent='';
 document.querySelector('#preview-metadata').replaceChildren();
 document.querySelector('#preview-details').hidden=true;
 document.querySelector('#pdf-controls').hidden=true;
 previewStatus.textContent='Vyberte podklad ze seznamu.';
}
function renderMarkdown(text){
 // Deliberately small Markdown subset; all source text uses textContent, never HTML.
 let fence=null,code=null,list=null;
 for(const line of text.split('\\n')){
  const marker=line.match(/^\\s*(`{3,}|~{3,})(.*)$/);
  if(marker && (!fence || (marker[1][0]===fence[0] && marker[1].length>=fence.length && !marker[2].trim()))){
   list=null;
   if(fence){fence=null;code=null;}else{fence=marker[1];code=document.createElement('pre');previewContent.append(code);}
   continue;
  }
  if(fence){code.textContent+=line+'\\n';continue;}
  const heading=line.match(/^(#{1,6})\\s+(.*)$/);
  const bullet=line.match(/^\\s*[-*+]\\s+(.*)$/);
  if(bullet){if(!list){list=document.createElement('ul');previewContent.append(list);}
   const item=document.createElement('li');item.textContent=bullet[1];list.append(item);continue;}
  list=null;const element=document.createElement(heading?'h'+heading[1].length:'p');
  element.textContent=heading?heading[2]:line;previewContent.append(element);
 }
}
async function openPreview(id,page=1){
 if(!activeProject)return;
 const project=activeProject;
 clearPreview();selectedArtifact=id;
 for(const button of sidebarArtifacts.querySelectorAll('button'))button.setAttribute('aria-current',String(button.dataset.id===id));
 const request=previewRequest;
 selectMainTab(mainTabs[0]);previewStatus.textContent='Načítám náhled…';
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
 if(activeProject){projectView.hidden=false;document.querySelector('#sidebar-project-tools').hidden=false;}
 else{document.querySelector('#project-home').hidden=false;document.querySelector('#sidebar-projects').hidden=false;}
}
async function openHistory(){
 if(!activeProject||!selectedArtifact)return;
 const project=activeProject,artifactId=selectedArtifact,request=++historyRequest;
 historyVersions=[];historyOlder.replaceChildren();historyNewer.replaceChildren();clearHistoryResult();
 document.querySelector('#history-title').textContent=`Historie · ${document.querySelector('#preview-title').textContent||artifactId}`;
 document.querySelector('#project-home').hidden=true;settingsView.hidden=true;sourceImportView.hidden=true;projectView.hidden=true;historyView.hidden=false;
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
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
let activeThread=null,knownThreads=[],pendingThreadDeletion=null,chatBinding=null,searchBinding=null,externalBinding=null,ollamaStreaming=false,ollamaStreamingSupported=false,externalStreaming=false,pendingChatRequest=null,pendingExternalPreview=null,pendingExternalProposal=null,pendingSearchPreview=null,searchRecoveryBinding=null;
let activeTaskThreadId=null,taskOutcomes=[],chatSelectionRevision=0;
const presentationApprovalAttempts=new Map();
let streamScrollPending=false,streamAutoFollow=false;
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
 let state=initialState,started=Date.now();streamAutoFollow=true;chatStreamStatus.hidden=false;
 const render=()=>{const seconds=Math.floor((Date.now()-started)/1000);
  chatStreamProgressText.textContent=`${state} · ${seconds} s`;keepChatStreamVisible();};
 const timer=setInterval(render,1000);render();
 return {set(nextState){state=nextState;render();},stop(){clearInterval(timer);
  chatStreamStatus.hidden=true;chatStreamProgressText.textContent='';}};
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
function renderChat(thread){
 activeThread=thread || null;chatMessages.replaceChildren();
 for(const item of thread?.messages || []){
  const message=document.createElement('div');message.className='chat-message '+item.role;
  message.textContent=item.content;
  const detail=document.createElement('small');detail.textContent=`${item.role==='user'?'Vy':'Asistent'} · ${item.privacy}`;
  message.append(detail);chatMessages.append(message);
  const turn=(thread?.turns || []).find(value=>value.assistant_message_id===item.message_id);
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
 }
 renderTaskOutcomes();
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
 const assigned=threads.filter(thread=>thread.project_id!==null);
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
  row.className='sidebar-chat-row';button.className='sidebar-chat-open';
  button.dataset.threadId=thread.thread_id;
  button.setAttribute('aria-current',String(activeThread?.thread_id===thread.thread_id));
  button.textContent=`${thread.classification} · ${thread.status}`;
  const meta=document.createElement('small');meta.className='sidebar-chat-meta';
  const project=thread.project_id===activeProject?.id?'tento projekt':'jiný projekt';
  meta.textContent=`${thread.messages.length} zpráv${thread.project_id===null?'':` · ${project}`}`;
  button.append(meta);button.addEventListener('click',()=>openStoredThread(thread.thread_id));
  const menu=document.createElement('details');menu.className='sidebar-chat-menu';
  const trigger=document.createElement('summary');trigger.setAttribute('aria-label',`Akce chatu ${thread.classification}`);trigger.textContent='⋮';
  const items=document.createElement('div');items.className='sidebar-chat-menu-items';items.setAttribute('role','menu');
  function action(label,callback,disabled=false){
   const item=document.createElement('button');item.type='button';item.textContent=label;item.disabled=disabled;item.setAttribute('role','menuitem');
   item.addEventListener('click',async event=>{event.stopPropagation();menu.open=false;
    if(activeThread?.thread_id!==thread.thread_id)await openStoredThread(thread.thread_id);
    if(activeThread?.thread_id===thread.thread_id)await callback(event.currentTarget);});
   items.append(item);
  }
  if(thread.project_id===null)action('Zařadit do tohoto projektu',async control=>{
   control.disabled=true;chatOperationStatus.textContent='Zařazuji vlákno do otevřeného projektu…';
   try{await assignActiveThread();chatOperationStatus.textContent='Vlákno bylo zařazeno do otevřeného projektu.';}
   catch(error){control.disabled=false;chatOperationStatus.textContent=error.message;}
  },thread.status==='archived');
  action('Archivovat',archiveActiveThread,thread.status==='archived');
  action('Připravit smazání',prepareActiveThreadDeletion);
  action('Uložit otisk',button=>runChatRecord(button,'snapshot'),!thread.messages.length);
  action('Uložit poslední odpověď',button=>runChatRecord(button,'output'),!thread.messages.length);
  menu.append(trigger,items);row.append(button,menu);group.append(row);
  }
 }
 branch('Zařazené',assigned);branch('Nezařazené',unassigned);
 const assignedCount=assigned.length,unassignedCount=unassigned.length;
 document.querySelector('#sidebar-chat-status').textContent=threads.length?
  `${assignedCount} zařazených · ${unassignedCount} nezařazených`:'Zatím tu nejsou žádné uložené chaty.';
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
}
function replaceTaskProjection(projection){
 const index=taskOutcomes.findIndex(item=>item.task_id===projection.task_id);
 if(index<0)taskOutcomes.push(projection);else taskOutcomes[index]=projection;
 activeTaskThreadId=projection.thread_id;renderChat(activeThread);
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
function renderSearchWorkflow(container,workflow){
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
   row.append(name,url,snippet,sourceId);sources.append(row);}round.append(sources);
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
function renderTaskOutcomes(){
 for(const projection of taskOutcomes){
  const prompt=document.createElement('div');prompt.className='chat-message user';
  prompt.textContent=projection.prompt.content;
  const promptDetail=document.createElement('small');promptDetail.textContent=`Vy · ${projection.prompt.privacy}`;
  prompt.append(promptDetail);chatMessages.append(prompt);
  if(projection.state==='cancelled')continue;
  const outcome=projection.outcome;if(!outcome)continue;
  if(outcome.kind==='direct-answer'){
   const answer=document.createElement('div');answer.className='chat-message assistant';answer.textContent=outcome.content;
   const detail=document.createElement('small');detail.textContent=`Asistent · ${projection.privacy}`;
   answer.append(detail);chatMessages.append(answer);continue;
  }
  const card=document.createElement('section');card.className='task-outcome'+(projection.temporary?'':' terminal');
  const heading=document.createElement('h3');
  heading.textContent=outcome.kind==='artifact-draft'?'Návrh artefaktu':
   outcome.kind==='presentation-draft'?'Návrh prezentace':
   outcome.kind==='presentation-link'?'Uložená prezentace':
   outcome.kind==='artifact-link'?'Vytvořený artefakt':
   outcome.kind==='web-search'?'Návrh webového hledání':
   outcome.kind==='web-search-answer'?'Odpověď z řízeného hledání':'Externí volání';card.append(heading);
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
     await openRegisteredProject(projectId);selectMainTab(mainTabs[1]);
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
   renderSearchWorkflow(card,projection.search_workflow);
   const actions=document.createElement('div');actions.className='task-actions';
   const workflow=projection.search_workflow,latest=workflow?.rounds?.at(-1);
   if(!workflow || !latest?.evaluation){
    actions.append(taskButton('Zkontrolovat webový dotaz',()=>prepareTaskSearch(projection)));
   }else{
   for(const nextQuery of workflow.next_queries || []){
     actions.append(taskButton(`Zkontrolovat další dotaz: ${nextQuery}`,
      ()=>prepareTaskSearch(projection,nextQuery,latest.search_id)));
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
    budget_used:outcome.budget_used});
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
 try{const projection=await projectRequest('/v1/tasks/search/confirm',{
   task_id:preview.task_id,search_id:preview.search_id,
   preview_sha256:preview.preview_sha256,approved:true},210000);
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
document.querySelector('#chat-new-thread').addEventListener('click',()=>{
 hideSearchRecovery();
 ++chatSelectionRevision;pendingChatRequest=null;activeTaskThreadId=crypto.randomUUID();
 taskOutcomes=[];renderChat(null);renderThreadList(knownThreads);draft.value='';
 chatOperationStatus.textContent='';
 document.querySelector('#chat-submit').disabled=true;
 chatStatus.textContent=chatBinding ? `Nové vlákno pro projekt ${activeProject.title} · backend: ${chatBindingLabel(chatBinding)}` :
  `Nové vlákno pro projekt ${activeProject.title} · nejprve nastavte backend.`;
 draft.focus();
});
async function openStoredThread(threadId){
 ++chatSelectionRevision;pendingChatRequest=null;pendingThreadDeletion=null;
 document.querySelector('#chat-delete-preview').hidden=true;
 const thread=knownThreads.find(item=>item.thread_id===threadId);
 if(!thread){chatOperationStatus.textContent='Vyberte uložené vlákno.';return;}
 activeTaskThreadId=thread.thread_id;activeThread=thread;
 document.querySelector('#chat-mode').value=thread.classification;refreshChatModeControls();
 selectMainTab(document.querySelector('#chat-tab'));renderThreadList(knownThreads);
 try{const tasks=thread.project_id ? await projectRequest('/v1/tasks/list',{
   project_id:thread.project_id,thread_id:thread.thread_id}) : {outcomes:[]};
  taskOutcomes=tasks.outcomes;renderChat(thread);
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
async function loadBackendBinding(){
 try{const result=await projectRequest('/v1/chat/status',{});
  fillBinding(result.binding,result.binding_draft,result.binding_draft_state);
  fillSearchBinding(result.search_binding);
  applyOllamaStreamingStatus(result);
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
  backendMetricsIndicator.textContent='OpenAI přehled: nenačten';return;}
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
 const ollamaOption=adapter.querySelector('option[value="ollama"]');
 const target=document.querySelector('#chat-orchestration-target');
 const lan=chatBinding?.boundary==='private-network';
 ollamaOption.textContent=lan?'Ollama v privátní síti':'Ollama na tomto uzlu';
 if(mode==='orchestration'){
  adapter.value='ollama';adapter.disabled=true;model.value=chatBinding?.model || '';model.disabled=true;
  target.hidden=false;target.textContent=chatBinding ?
   `Orchestrace použije ${chatBinding.model} · ${lan?'privátní síť':'tento uzel'} · ${chatBinding.endpoint}` :
   'Orchestrace vyžaduje nejprve nastavit Ollama backend.';
  artifacts.hidden=false;
 }else{
  target.hidden=true;target.textContent='';
  adapter.disabled=false;model.disabled=false;artifacts.hidden=true;
  for(const input of document.querySelectorAll('#task-artifact-list input'))input.checked=false;
  if(!model.value)model.value=adapter.value==='openai-responses' ? (externalBinding?.model || '') : (chatBinding?.model || '');
 }
}
document.querySelector('#chat-run-adapter').addEventListener('change',event=>{
 document.querySelector('#chat-run-model').value=event.currentTarget.value==='openai-responses' ?
  (externalBinding?.model || '') : (chatBinding?.model || '');
});
document.querySelector('#chat-mode').addEventListener('change',async event=>{
 pendingChatRequest=null;const mode=event.currentTarget.value;
 if(mode==='orchestration' && activeThread?.classification==='brainstorming'){
  try{activeThread=await projectRequest('/v1/chat/orchestration',{
    source_thread_id:activeThread.thread_id,thread_id:crypto.randomUUID(),created_at:new Date().toISOString()});
   activeTaskThreadId=activeThread.thread_id;taskOutcomes=[];renderChat(activeThread);rememberThread(activeThread);
  }catch(error){event.currentTarget.value='brainstorming';chatOperationStatus.textContent=error.message;}
 }else{activeThread=null;activeTaskThreadId=crypto.randomUUID();taskOutcomes=[];renderChat(null);renderThreadList(knownThreads);}
 refreshChatModeControls();
});
async function loadChat(){
 const selectionRevision=chatSelectionRevision;
 try{
  const [result,external]=await Promise.all([
   projectRequest('/v1/chat/status',{}),projectRequest('/v1/external/status',{})]);
  fillBinding(result.binding,result.binding_draft,result.binding_draft_state);
  fillSearchBinding(result.search_binding);
  applyOllamaStreamingStatus(result);
  externalBinding=external.binding;
  externalStreaming=external.capabilities?.streaming===true;
  fillExternalModels(external.model_catalog);
  if(selectionRevision!==chatSelectionRevision)return;
  activeThread=null;activeTaskThreadId=null;taskOutcomes=[];renderChat(null);
  renderThreadList([...result.threads].reverse());
  chatOperationStatus.textContent=result.threads.length?
   'Vyberte uložené vlákno k vědomému navázání, nebo založte nové.':'Založte nové vlákno.';
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
  settingsBackendStatus.textContent=result.model_available ?
   `Ollama je dostupná a model ${result.model} je připraven.` :
   `Ollama je dostupná, ale model ${result.model} není mezi ${result.model_count} dostupnými modely.`;
 }catch(error){settingsBackendStatus.textContent=error.message;}
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
 if(!activeProject || !draft.value.trim())return;selectMainTab(mainTabs[1]);
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
 if(!activeProject || !draft.value.trim())return;selectMainTab(mainTabs[1]);
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
 selectMainTab(mainTabs[1]);
 if(!chatBinding){chatOperationStatus.textContent='Nejprve uložte nastavení backendu.';return;}
 const mode=document.querySelector('#chat-mode').value;
 const adapter=document.querySelector('#chat-run-adapter').value;
 const model=document.querySelector('#chat-run-model').value.trim();
 if(!model){chatOperationStatus.textContent='Vyberte model běhu.';return;}
 const runChoice={mode,adapter,model:mode==='orchestration'?null:model};
 if(mode==='orchestration'){
  runChoice.binding_id=chatBinding.binding_id;runChoice.binding_revision=chatBinding.revision;
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
   run_choice:runChoice};
 const submit=document.querySelector('#chat-submit');submit.disabled=true;
  chatOperationStatus.textContent='Odesílám do OpenAI…';
  chatStream.textContent='';delete chatStream.dataset.progress;chatStream.hidden=!externalStreaming;
  const liveProgress=externalStreaming?startChatProgress('Připojuji se k OpenAI…'):null;
  let receivedDeltas=0,firstDeltaMs=null,streamStarted=performance.now();
  try{if(liveProgress)await waitForVisiblePaint();
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
   if([409,422,502].includes(error.status))pendingChatRequest=null;
   chatOperationStatus.textContent=error.message;
  }finally{if(liveProgress)liveProgress.stop();chatStream.hidden=true;
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
    created_at:new Date().toISOString(),run_choice:runChoice};
  }
  const submit=document.querySelector('#chat-submit');submit.disabled=true;
  chatOperationStatus.textContent='Odesílám…';chatStream.textContent='';
  chatStream.hidden=!ollamaStreaming;
  const streamStates={preparing:'Připravuji kontext…',connecting:'Připojuji se k Ollamě…',
   'waiting-first-token':'Čekám na první část odpovědi…',thinking:'Ollama přemýšlí…',
   generating:'Ollama generuje odpověď…',
   completed:'Generování je dokončeno.'};
  const liveProgress=ollamaStreaming?startChatProgress(streamStates.preparing):null;
  let receivedDeltas=0,firstDeltaMs=null,streamStarted=performance.now();
  const thinking=setTimeout(()=>{chatOperationStatus.textContent='Model přemýšlí…';},250);
  try{
   if(liveProgress)await waitForVisiblePaint();
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
   if([409,422,502].includes(error.status))pendingChatRequest=null;
   chatStream.textContent='';
   chatOperationStatus.textContent=error.message+([409,422,502].includes(error.status) ?
    ' Zadání a výběr zůstaly zachovány; tlačítkem Zpracovat spustíte vědomě nový běh.' : '');
  }finally{clearTimeout(thinking);if(liveProgress)liveProgress.stop();
   submit.disabled=!activeProject || !draft.value.trim();chatStream.hidden=true;
   finishChatAutoFollow();}
  return;
 }
 if(!pendingChatRequest){
  const threadId=activeTaskThreadId || activeThread?.thread_id || crypto.randomUUID();
  const selectedMessages=activeThread?.thread_id===threadId ? activeThread.messages : [];
  pendingChatRequest={task_id:crypto.randomUUID(),
  project_id:activeProject.id,expected_head:activeProject.head,
  thread_id:threadId,
  message_id:crypto.randomUUID(),run_id:crypto.randomUUID(),manifest_id:crypto.randomUUID(),
  selected_message_ids:selectedMessages.map(item=>item.message_id),
  selected_artifact_ids:[...document.querySelectorAll('#task-artifact-list input:checked')]
   .map(item=>item.value),
  content:draft.value.trim(),privacy:document.querySelector('#chat-privacy').value,
  created_at:new Date().toISOString(),run_choice:runChoice};}
 const submit=document.querySelector('#chat-submit');submit.disabled=true;chatOperationStatus.textContent='Odesílám…';
 const liveProgress=startChatProgress('Ollama zpracovává orchestraci…');
 const thinking=setTimeout(()=>{chatOperationStatus.textContent='Model přemýšlí…';},250);
 try{
  await waitForVisiblePaint();
  const result=await projectRequest('/v1/tasks/route',pendingChatRequest,210000);
  replaceTaskProjection(result.projection);pendingChatRequest=null;draft.value='';draft.focus();
  chatOperationStatus.textContent=result.projection.temporary ?
   'Návrh je připraven ke kontrole.' : 'Odpověď je připravena.';
 }catch(error){
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
  await openRegisteredProject(activeProject.id);selectMainTab(mainTabs[1]);
 }catch(error){chatOperationStatus.textContent=error.message;}
 finally{button.disabled=false;}
}
draft.addEventListener('keydown',event=>{
 if(event.key==='Enter' && !event.shiftKey && !event.isComposing){event.preventDefault();document.querySelector('#chat-composer').requestSubmit();}
});
let roleWorkflow=null,pendingWorkflowRequest=null,pendingWorkflowPublish=null;
const workflowStatus=document.querySelector('#workflow-status');
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
if(window.workspaceAutoStart!==false)loadProjects();
"""
JS += ADMIN_JS
DESKTOP_BOOTSTRAP = "document.body.dataset.runtime='desktop';\n"
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
        '/v1/projects/delete/preview', '/v1/projects/delete/confirm',
        '/v1/projects/delete/trash', '/v1/projects/delete/restore/preview',
        '/v1/projects/delete/restore/confirm', '/v1/projects/delete/purge/preview',
        '/v1/projects/delete/purge/confirm',
        '/v1/notebooklm/preview', '/v1/notebooklm/plan', '/v1/notebooklm/confirm',
        '/v1/artifacts/preview', '/v1/artifacts/history/list', '/v1/artifacts/history/compare',
        '/v1/artifacts/editor/open', '/v1/artifacts/editor/save',
        '/v1/artifacts/delete/preview', '/v1/artifacts/delete/confirm',
        '/v1/sources/import', '/v1/google-drive/status', '/v1/google-drive/configure',
        '/v1/google-drive/authorize', '/v1/google-drive/preview',
        '/v1/google-drive/confirm', '/v1/google-drive/recover',
        '/v1/chat/status', '/v1/chat/configure',
        '/v1/chat/preferences', '/v1/chat/test',
        '/v1/search/status', '/v1/search/configure', '/v1/search/test',
        '/v1/chat/send', '/v1/chat/send-stream',
        '/v1/chat/orchestration', '/v1/chat/archive', '/v1/chat/delete/preview',
        '/v1/chat/delete/confirm',
        '/v1/gamepad/status', '/v1/presentation/status',
        '/v1/gamepad/settings',
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
        '/v1/chat/assign', '/v1/chat/snapshot', '/v1/chat/output',
        '/v1/workflows/status', '/v1/workflows/prepare',
        '/v1/workflows/creator/dispatch', '/v1/workflows/opponent/prepare',
        '/v1/workflows/opponent/dispatch', '/v1/workflows/publish',
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
            if self.path == '/v1/chat/configure' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure(request))
            if self.path == '/v1/chat/preferences' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure_preferences(request))
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
            chat_send_fields = ({
                    'project_id', 'expected_head', 'thread_id', 'turn_id', 'message_id',
                    'run_id', 'manifest_id', 'assistant_message_id', 'selected_message_ids',
                    'content', 'privacy', 'created_at'}, {
                    'project_id', 'expected_head', 'thread_id', 'turn_id', 'message_id',
                    'run_id', 'manifest_id', 'assistant_message_id', 'selected_message_ids',
                    'content', 'privacy', 'created_at', 'run_choice'})
            if (self.path == '/v1/chat/send-stream' and isinstance(request, dict)
                    and set(request) in chat_send_fields):
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
                    and set(request) in chat_send_fields:
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
            if self.path.startswith(('/v1/publication-cms/', '/v1/chat/', '/v1/search/', '/v1/external/', '/v1/tasks/', '/v1/workflows/', '/v1/summary/', '/v1/extraction/', '/v1/media/',
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
