# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
#
"""Static same-origin UI; project data arrives through authenticated reads."""
import json
import copy
import sqlite3
import subprocess
from pathlib import Path

from spikes.local_api import Handler
from spikes.presentation_visual import SLIDE_JS
from spikes.presentation_documents import public_content
from spikes.ollama_backend import OllamaResponseError, UnknownRun
from spikes.openai_backend import OpenAIResponseError, OpenAIUnknownRun
from spikes.projects import Projects
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation


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
            content['body'] = source.get('body', '')
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
    server.presentation_public_state = state
    if not state['visible'] or state['blackout']:
        return {'visible': False, 'blackout': True}
    return {'visible': True, 'blackout': False, 'slide': state['slide'], 'ratio': state.get('ratio', '16:9'), 'content': state['content']}


def presentation_status(server):
    result = copy.deepcopy(getattr(server, 'presentation_selected_deck', None) or presentation_deck())
    state = getattr(server, 'presentation_public_state', {})
    result['ratio'] = state.get('ratio', '16:9')
    return result


HTML = '''<!doctype html><html lang="cs"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projektový workspace</title><link rel="stylesheet" href="/app.css">
<body><aside><div class="brand">◈ &nbsp; WORKSPACE</div>
<div id="sidebar-projects"><h2>Projekty</h2><ul id="sidebar-project-list"></ul>
<p id="sidebar-project-status" role="status">Načítám projekty…</p></div>
<div id="sidebar-project-tools" hidden>
<div id="sidebar-tabs" role="tablist" aria-label="Obsah levého panelu">
<button id="todo-tab" role="tab" aria-controls="todo-widget" aria-selected="true">Úkoly</button>
<button id="artifacts-tab" role="tab" aria-controls="sidebar-artifacts" aria-selected="false" tabindex="-1">Podklady</button></div>
<div id="todo-widget" role="tabpanel" aria-labelledby="todo-tab" tabindex="0"><h2>Hlavní seznam úkolů</h2>
<p id="todo-status" role="status">Otevřete projekt.</p><div id="todo-title"></div>
<button id="create-main-todo" hidden>Vytvořit seznam úkolů</button>
<ul id="todo-tree" aria-label="Úkoly projektu"></ul><small id="todo-help" hidden>Úkoly upravíte v editoru.</small></div>
<div id="sidebar-artifacts" role="tabpanel" aria-labelledby="artifacts-tab" tabindex="0" hidden>
<h2>Podklady</h2><p id="sidebar-artifact-status" role="status"></p>
<ul id="sidebar-artifact-list" aria-label="Podklady projektu"></ul></div></div>
<button id="open-settings" class="global-nav" type="button">Nastavení</button>
<div class="node-note">Na tomto počítači<br>Zkušební verze</div></aside>
<main><div id="project-home">
<header><span class="badge">Pracovní prostor</span><span>Vaše projekty, zdroje a rozhodnutí</span></header>
<div class="home-heading"><div class="eyebrow">VAŠE PRÁCE NA JEDNOM MÍSTĚ</div>
<h1>Projekty</h1><p>Vyberte projekt a pokračujte tam, kde jste skončili.</p></div>
<p id="project-status" role="status" aria-live="polite">Načítám projekty…</p>
<div id="project-cards" aria-label="Seznam projektů"></div>
<p class="home-help">Nový projekt vytvoříte tlačítkem v horní liště.</p>
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
<div id="settings-view" hidden>
<header><span class="badge">Nastavení uzlu</span><span>Platí pro tento počítač</span></header>
<div class="settings-heading"><div class="eyebrow">LOKÁLNÍ KONFIGURACE</div>
<h1>Nastavení</h1><p>Tato nastavení se neukládají do projektu ani nesynchronizují.</p></div>
<div id="settings-tabs" role="tablist" aria-label="Sekce nastavení">
<button id="settings-backend-tab" type="button" role="tab" aria-selected="true" aria-controls="settings-backend-panel">AI backend</button>
<button id="settings-users-tab" type="button" role="tab" aria-selected="false" aria-controls="admin-users-panel" tabindex="-1" hidden>Uživatelé</button>
<button id="settings-federation-tab" type="button" role="tab" aria-selected="false" aria-controls="admin-federation" tabindex="-1" hidden>Federace</button></div>
<section id="settings-backend-panel" class="settings-card" role="tabpanel" aria-labelledby="settings-backend-tab">
<h2 id="settings-backend-title">Lokální AI backend</h2>
<p id="settings-backend-status" role="status" aria-live="polite">Načítám stav lokálního backendu…</p>
<form id="chat-backend-form"><label>Hranice <select name="boundary"><option value="same-node">Stejný počítač</option><option value="private-network">Privátní síť</option></select></label>
<label>Endpoint <input name="endpoint" value="http://127.0.0.1:11434" required></label>
<label>Model <input name="model" placeholder="gemma3" required></label>
<label>ID cíle <input name="target_id" value="local-process" required></label>
<label>SHA-256 certifikátu pro LAN <input name="tls_cert_sha256" pattern="[0-9a-f]{64}"></label>
<button type="submit">Uložit backend</button></form>
<small>Privátní síť vyžaduje číselnou HTTPS adresu a připnutý certifikát. Tajné klíče se zde nezobrazují.</small>
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
<section id="backend-metrics" hidden><hr><h2>Spotřeba a náklady OpenAI</h2>
<p id="backend-metrics-status" role="status">Účetní přehled zatím nebyl načten.</p>
<form id="backend-metrics-form"><label>OpenAI Admin API klíč
<input name="secret" type="password" autocomplete="new-password" maxlength="4096"></label>
<button type="submit">Uložit administrátorský klíč</button>
<button id="backend-metrics-refresh" type="button">Načíst posledních 30 dní</button></form>
<pre id="backend-metrics-report" hidden></pre></section>
</section>
<div id="administration-host"></div>
<button id="settings-back" class="back-button" type="button">← Zpět</button>
</div>
<div id="project-view" hidden>
<header class="project-header"><div><span class="eyebrow">OTEVŘENÝ PROJEKT</span><h1 id="project-title"></h1></div>
<details><summary>Uložená verze</summary><code id="project-commit"></code></details></header>
<section id="workspace-panel" aria-label="Pracovní prostor">
<div id="main-tabs" role="tablist" aria-label="Hlavní panel">
<button id="preview-tab" role="tab" aria-controls="preview-panel" aria-selected="true">Náhled</button>
<button id="chat-tab" role="tab" aria-controls="chat-panel" aria-selected="false" tabindex="-1">Chat</button>
<button id="summary-tab" role="tab" aria-controls="summary-panel" aria-selected="false" tabindex="-1">Souhrn</button>
<button id="extraction-tab" role="tab" aria-controls="extraction-panel" aria-selected="false" tabindex="-1">Extrakce</button>
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
<button id="chat-open-settings" class="secondary-button" type="button">Otevřít nastavení backendu</button>
<button id="chat-new-thread" type="button">Nové vlákno</button>
<span id="chat-record-actions" hidden><button id="chat-save-snapshot" type="button">Uložit otisk</button>
<button id="chat-save-output" type="button">Uložit poslední odpověď</button></span>
<div id="chat-messages" role="log" aria-label="Vaše zadání"></div></div>
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
<div id="chat-stream" class="chat-message assistant" aria-live="polite" hidden></div>
<section id="external-preview" hidden aria-label="Náhled externího odeslání">
<h3>Co bude odesláno externímu provideru</h3>
<pre id="external-preview-content"></pre>
<label><input id="external-privacy-confirm" type="checkbox"> Potvrzuji odeslání zobrazených dat a uvedené úrovně soukromí.</label>
<button id="external-confirm" type="button" disabled>Odeslat do OpenAI</button>
<button id="external-cancel" class="secondary-button" type="button">Zrušit</button>
</section>
<small>Enter odešle, Shift+Enter vloží nový řádek · historie zůstává lokálně na tomto uzlu</small></form>
</section>
<button id="back-projects" class="back-button">← Zpět na seznam projektů</button>
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
<aside class="presenter-speaker" aria-label="Soukromý kokpit"><div class="presenter-panel-head"><h2>Soukromý kokpit</h2><p id="presenter-counter">Slide 0 z 0</p></div><section class="presenter-browser"><div class="presenter-tab-row"><div class="presenter-tabs" role="tablist"><button id="presenter-slide-tab" type="button" role="tab" aria-selected="true">K slidu</button><button id="presenter-backup-tab" type="button" role="tab" aria-selected="false">Backupy</button><button id="presenter-question-tab" type="button" role="tab" aria-selected="false">Otázky</button></div><label class="presenter-search" for="presenter-backup-search"><span>Hledat</span><input id="presenter-backup-search" type="search" placeholder="Hledat…"></label></div><p id="presenter-gamepad-status" class="presenter-gamepad-status">Gamepad: čekám.</p><p id="presenter-tab-status">K slide · otázky a doplňky</p>
<div id="presenter-tab-content"><section id="presenter-slide-list"><h3>Současný slide</h3><div id="presenter-preview"></div><h3>Další podle plánu</h3><button id="presenter-planned-slide" class="presenter-backup" type="button" disabled></button><h3>Backupy k aktuálnímu slidu</h3><p id="presenter-slide-backup-status" role="status"></p><ul id="presenter-slide-backups"></ul></section><section id="presenter-backup-list" hidden><p id="presenter-backup-status">Backupy se zobrazí po spuštění.</p><ul id="presenter-backups"></ul></section><section id="presenter-question-list" hidden><h3>Otázky / doplňky</h3><button id="presenter-question" type="button">Doplňující otázka</button><p id="presenter-question-status">Žádná aktivní odbočka.</p></section></div>
</section><section class="presenter-next-selector"><h3 id="presenter-next-title">Další slide podle plánu</h3><div class="presenter-slide-widget"><div class="presenter-slide-preview" id="presenter-private-preview"></div><section class="presenter-notes"><h2>Poznámky k vybranému slidu</h2><p id="presenter-next-notes"></p></section></div><p id="presenter-private-status">Soukromé procházení nemění expozici.</p><button id="presenter-next-preview" type="button">Zobrazit další slide</button><button id="presenter-show-private" type="button" hidden disabled>Zobrazit publiku</button></section></aside>
</div>
<footer class="presenter-footer"><button id="presenter-return" type="button">Návrat na původní slide</button><span>Otázky: <strong id="presenter-question-count">0</strong></span><span>Odložené: <strong>0</strong></span><span id="presenter-blackout-state">Veřejný výstup aktivní</span></footer>
</div>
</main><script src="/app.js"></script></body></html>'''
CSS = '''*{box-sizing:border-box}[hidden]{display:none!important}
body{margin:0;background:#f4f7fa;color:#162638;font:15px system-ui;display:flex;height:100vh;overflow:hidden}
aside{width:238px;flex-shrink:0;background:#142638;color:#c8d4df;padding:28px 20px;display:flex;flex-direction:column;overflow:auto}
.brand{font-weight:750;letter-spacing:2px;color:white;margin-bottom:32px}.global-nav{margin-top:auto;background:#176b60;text-align:left}.node-note{font-size:11px;line-height:1.8;padding-top:18px;color:#9eb5c7}
main{flex:1;min-width:0;padding:26px 32px;overflow:auto}header{display:flex;justify-content:space-between;gap:16px;align-items:center;color:#627183;font-size:12px}
.badge{color:#1c6556;background:#e0efe9;border-radius:20px;padding:8px 13px}.eyebrow{font-size:11px;color:#31796e;font-weight:750;letter-spacing:2px}
h1{font-size:32px;margin:12px 0}h2{font-size:21px}p{line-height:1.6;color:#627183}button,textarea,input{font:inherit}
button{border:0;border-radius:8px;background:#176b60;color:white;font-weight:600;padding:12px 18px;cursor:pointer}
button:hover{background:#12564d}button:disabled{opacity:.5;cursor:default}button:focus-visible,textarea:focus-visible,summary:focus-visible{outline:3px solid #59b6aa;outline-offset:3px}
summary{cursor:pointer}code,li,dd,h1,h2,button{overflow-wrap:anywhere}small{font-size:11px;color:#627183}
#gamepad-list{list-style:none;padding-left:0;margin:12px 0 0;display:flex;flex-direction:column;gap:8px}
#gamepad-list li{background:#edf7f4;border:1px solid #d2e5e0;border-radius:8px;padding:8px 12px;color:#1f3a41}
.home-heading,.settings-heading{margin-top:44px}.home-heading h1{font-size:38px}.home-help{font-size:13px;margin-top:24px}
.settings-card{max-width:720px;background:white;border:1px solid #dce3e9;border-radius:16px;padding:22px 26px;margin:24px 0}.settings-card label{display:block;margin:12px 0}.settings-card input,.settings-card select{padding:9px;max-width:100%}.settings-card input{width:100%}.settings-card small{display:block;margin-top:16px}
.provider-link{color:#176b60;font-weight:600}
#backend-metrics-indicator{position:fixed;right:14px;bottom:10px;z-index:20;
 background:#142638e8;color:#dce8f1;border:1px solid #496072;border-radius:12px;
 padding:6px 10px;font-size:11px;box-shadow:0 3px 12px #14263830;max-width:60vw;
 white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#settings-tabs{display:flex;gap:8px;flex-wrap:wrap;margin:22px 0 8px}#settings-tabs button[aria-selected="false"]{background:#e8eef2;color:#304657}
#project-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:18px;margin-top:24px}
.project-card{background:white;color:#162638;border:1px solid #dce5eb;border-radius:16px;padding:24px;text-align:left;min-height:190px;display:flex;flex-direction:column;gap:14px;box-shadow:0 5px 20px #18364808}
.project-card:hover{background:#fafffd;border-color:#4b9e8c;box-shadow:0 8px 24px #18364812}
.project-card .project-name{font-size:21px;line-height:1.4}.project-card .project-description{font-size:13px;color:#627183;font-weight:400;line-height:1.6}
.project-card .project-id{font-size:11px;color:#82909d;font-weight:400;margin-top:auto}.project-card .project-action{color:#176b60;font-size:13px}
.diagnostics{margin-top:32px;color:#627183;font-size:12px}.diagnostics button{margin:14px 12px 0 0}.diagnostics output{font-size:20px}
aside h2{font-size:16px;color:white}aside p{font-size:12px;color:#aabecf}aside small{color:#aabecf}
#sidebar-project-list,#sidebar-artifact-list,#todo-tree{list-style:none;padding:0;margin:14px 0}
#sidebar-project-list button,#sidebar-artifact-list button{display:block;text-align:left;width:100%;background:transparent;color:#dce8f1;padding:10px 8px;font-size:13px}
#sidebar-project-list button:hover,#sidebar-artifact-list button:hover{background:#274154}
#sidebar-artifact-list button[aria-current="true"]{background:#274154;border-left:3px solid #79c9ac}
.sidebar-artifact-id{display:block;font-size:10px;color:#8faabc;margin:0 8px 10px}.sidebar-artifact-title{font-size:13px}
#sidebar-tabs{display:flex;gap:4px;flex-wrap:wrap;margin-bottom:18px}#sidebar-tabs button{font-size:12px;padding:8px 6px;border:1px solid #496072;background:transparent;color:#c8d4df}
#sidebar-tabs button[aria-selected="true"]{background:#274154;color:white;border-color:#79c9ac}
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
#external-preview,#external-proposal{margin-top:12px;border:1px solid #d6b36a;background:#fffaf0;border-radius:10px;padding:12px}#external-preview pre{white-space:pre-wrap;max-height:260px;overflow:auto}#external-proposal-messages label{display:block;margin:7px 0}
#task-artifacts,#advanced-external{margin:8px 0;color:#456276;font-size:12px}#task-artifacts fieldset{border:1px solid #dce3e9;margin:8px 0;padding:8px 12px;max-height:130px;overflow:auto}#task-artifact-list label{display:block;font-weight:400;margin:5px 0}.task-outcome{border:1px solid #dce3e9;border-radius:12px;margin:14px 0;padding:14px 18px;background:#fffaf0}.task-outcome.terminal{background:#f4f7fa}.task-outcome pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:none}.task-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.task-actions button{padding:8px 12px}.artifact-link{color:#176b60;background:transparent;padding:0;text-align:left}.artifact-link:hover{background:transparent;text-decoration:underline}
.prompt-row{display:flex;gap:10px;margin:8px 0}.prompt-row textarea{resize:vertical;min-height:64px;max-height:150px;flex:1;min-width:0;border:1px solid #bfcdc9;border-radius:8px;padding:10px;background:white}
.prompt-row button{align-self:flex-end}.chat-message{padding:14px 18px;background:#edf5f2;border-radius:12px;margin:14px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.chat-message.assistant{background:#eef1fa}.chat-message small{display:block;margin-top:6px}.secondary-button{background:#e8eef2;color:#304657;margin:0 8px 12px 0}.secondary-button:hover{background:#dce6eb}#chat-privacy{padding:7px;max-width:100%}#chat-operation-status{font-size:12px;min-height:20px;margin:2px 0;color:#315f58}#chat-record-actions button{padding:8px 12px;margin-left:6px;font-size:12px}
#summary-panel label,#extraction-panel label{display:block;margin:10px 0 5px}#summary-panel textarea,#summary-panel input,#summary-panel select,#extraction-panel textarea,#extraction-panel input,#extraction-panel select{padding:9px;max-width:100%}#summary-focus,#extraction-focus{width:100%;resize:vertical}#summary-artifacts,#extraction-panel fieldset{margin:14px 0;border:1px solid #dce3e9}#summary-artifact-list label,#extraction-artifact-list label{font-weight:400}#summary-status,#extraction-status{font-size:12px;min-height:20px;color:#315f58}#summary-preview,#extraction-preview{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#summary-preview:empty,#extraction-preview:empty{display:none}#summary-preview p{white-space:pre-wrap;margin:6px 0}#extraction-preview{white-space:pre-wrap;overflow:auto}#summary-publish-controls,#extraction-publish-controls{border-top:1px solid #dce3e9;padding-top:12px}
#metadata-panel label{display:block;margin:10px 0 5px}#metadata-panel select{padding:9px;max-width:100%;margin-bottom:10px}#metadata-status{font-size:12px;min-height:20px;color:#315f58}#metadata-diff{background:#f5f7fb;border-radius:12px;padding:12px 18px;margin:12px 0}#metadata-diff p,#metadata-diff span{white-space:pre-wrap}#metadata-diff fieldset{margin:14px 0;border:1px solid #dce3e9}#metadata-tag-list label{font-weight:400}
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
document.querySelector('#presentation-editor').addEventListener('click',()=>{location.hash='presentation-editor';});
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
 const entries=slides.map((slide,mainIndex)=>({slide,mainIndex,kind:'main'}));
 let position=0,pending=null,preferred=null;
 function removePending(){
  const index=entries.indexOf(pending);
  if(index>position)entries.splice(index,1);
  pending=null;
 }
 return {
  entries,
  get position(){return position;},
  get current(){return entries[position];},
  get next(){return preferred || entries[position+1];},
  get planned(){return entries.slice(position+1).find(entry=>entry.kind==='main');},
  chooseBackup(slide){
   if(!entries[position] || !slide)return;
   removePending();preferred=null;
   if(entries[position+1]?.slide===slide){preferred=entries[position+1];return;}
   pending={slide,mainIndex:entries[position].mainIndex,kind:'backup'};
   entries.splice(position+1,0,pending);preferred=pending;
  },
  choosePlanned(){removePending();preferred=this.planned || null;},
  chooseEntry(entry){if(entries.includes(entry))preferred=entry;},
  target(delta){return delta<0?entries[position-1]:this.next;},
  commit(entry){
   const index=entries.indexOf(entry);if(index<0)return;
   position=index;preferred=null;if(entry===pending)pending=null;
  }
 };
}
let presenterSequence=createPresenterSequence([]);
let presenterNavigating=false;
function createPresenterGamepadInput(){
 let identity=null,armed={left:false,x:false,y:false};
 return (pad,active)=>{
  if(!active || !pad){identity=null;armed={left:false,x:false,y:false};return [];}
  const key=`${pad.index}:${pad.id}`;
  if(identity!==key){identity=key;armed={left:false,x:false,y:false};}
  const actions=[];
  for(const [name,value,negative,positive] of [
   ['left',pad.axes[0] ?? 0,'previous','next'],
   ['x',pad.axes[2] ?? 0,'tabPrevious','tabNext'],
   ['y',pad.axes[3] ?? 0,'itemPrevious','itemNext']
  ]){
   if(Math.abs(value)<0.35)armed[name]=true;
   else if(Math.abs(value)>0.65 && armed[name]){armed[name]=false;actions.push(value>0?positive:negative);}
  }
  return actions;
 };
}
const readPresenterGamepad=createPresenterGamepadInput();
function renderPresenterContent(target,slide){renderSlideVisual(target,slide);}
function renderPresenterWidget(preview,notes,slide){
 renderPresenterContent(preview,slide);
 notes.textContent=slide?.notes || (slide ? 'Tento slide nemá poznámky.' : 'Žádné poznámky.');
}
let presenterSelectedBackup=null;
function refreshPresenterNext(){
 const next=presenterSequence.next;
 setPresenterNextSelection(next?.slide,next?.kind || 'main');
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
 const slide=entry?.slide;
 renderPresenterWidget(presenterScreen,presenterNotes,slide);renderPresenterContent(presenterPreview,slide);
 presenterOutline.textContent=slide ? `Cíl: ${slide.title}. Veřejně potvrzený obsah zůstává oddělený od soukromé přípravy.` : 'Osnova se zobrazí po spuštění.';
 refreshPresenterNext();
 renderPresenterBackups();
 presenterCounter.textContent=`Pozice ${presenterSequence.position+1} z ${presenterSequence.entries.length}`;
 presenterPrevButton.disabled=presenterSequence.position===0 || presenterNavigating;presenterNextButton.disabled=!presenterSequence.next || presenterNavigating;
 presenterStatus.textContent=slide?`Promítám: ${slide.title}.`:'Prezentace je prázdná.';
 presenterReturnAnchor.textContent=`Návrat: slide ${String(presenterIndex+1).padStart(2,'0')} · hlavní linie`;
 renderPresenterDeck();
}
function renderPresenterDeck(){
 presenterDeckList.replaceChildren();
 presenterSequence.entries.forEach((entry,index)=>{
  const item=document.createElement('li');const button=document.createElement('button');button.type='button';
  button.textContent=`${String(index+1).padStart(2,'0')} ${entry.kind==='backup'?'Backup · ':''}${entry.slide.title}`;
  item.setAttribute('aria-current',String(index===presenterSequence.position));
  item.classList.toggle('presenter-live',index===presenterSequence.position);
  item.classList.toggle('presenter-visited',index<presenterSequence.position);
  button.addEventListener('click',()=>{if(presenterNavigating)return;presenterSequence.chooseEntry(entry);refreshPresenterNext();});
  item.append(button);presenterDeckList.append(item);
 });
}
function choosePresenterBackup(backup){
 if(presenterNavigating)return;
 presenterSequence.chooseBackup(backup);
 presenterSelectedBackup=backup;
 renderPrivateSelection(backup,`Backup zařazen do dočasného pořadí za aktuální slide. Zatím nepromítnuto.`);
 setPresenterNextSelection(backup,'backup');
 refreshPresenterNext();renderPresenterDeck();
}
async function showPresenterEntry(entry){
 if(presenterNavigating || !entry)return;
 let failure=null;
 presenterNavigating=true;presenterPrevButton.disabled=true;presenterNextButton.disabled=true;presenterNextPreview.disabled=true;
 try{
  await presentationControl(entry.slide.id?{action:'show',slide:entry.mainIndex,slide_id:entry.slide.id,deck_revision:entry.slide.deck_revision}:{action:'show',slide:entry.mainIndex,content:{title:entry.slide.title,body:entry.slide.body}});
  presenterSequence.commit(entry);presenterPrivateSelection=null;
  presenterBlackout=false;presenterView.classList.remove('presenter-blackout');
  presenterBlackoutButton.textContent='Zatemnit';presenterBlackoutState.textContent='Veřejný výstup aktivní';
  presenterLiveState.textContent='ŽIVĚ';
  if(entry.kind==='backup'){presenterExposureValue+=1;presenterExposure.textContent=`Expozice ${presenterExposureValue} · +1`;}
  presenterPrivateStatus.textContent='Dočasné pořadí zůstává zachované pro listování tam i zpět.';
 }catch(error){
  failure=error.message;
  presenterPrivateStatus.textContent='Zobrazení nebylo potvrzeno. Pozice zůstala zachovaná; ověřte veřejný výstup.';
 }finally{
  presenterNavigating=false;renderPresenterSlide();if(failure)presenterStatus.textContent=failure;
 }
}
function movePresenter(delta){return showPresenterEntry(presenterSequence.target(delta));}
function returnPresenterMain(){
 return showPresenterEntry(presenterSequence.entries.find(entry=>entry.kind==='main' && entry.mainIndex===presenterIndex));
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
function closePresenter(){location.hash='presenter-close';document.body.classList.remove('presenter-active');presenterView.hidden=true;if(activeProject){projectView.hidden=false;document.querySelector('#sidebar-project-tools').hidden=false;}else{document.querySelector('#project-home').hidden=false;document.querySelector('#sidebar-projects').hidden=false;}}
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
function pollPresenterGamepad(){
 const pad=Array.from(navigator.getGamepads?.() || []).find(item=>item);
 const active=!presenterView.hidden && !document.hidden && document.hasFocus();
 const actions=readPresenterGamepad(pad,active);
 presenterGamepadStatus.textContent=pad?`Gamepad: ${pad.id.slice(0,32)} · levý: předchozí/další · pravý: výběr`:'Gamepad: čekám na připojení.';
 // A navigation gesture uses the selection visible before this frame.
 if(actions.includes('previous'))movePresenter(-1);
 else if(actions.includes('next'))movePresenter(1);
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
addEventListener('gamepadconnected',()=>{presenterGamepadStatus.textContent='Gamepad: připojen.';updatePresenterItem();});
addEventListener('blur',()=>readPresenterGamepad(null,false));
addEventListener('gamepaddisconnected',()=>{readPresenterGamepad(null,false);presenterGamepadStatus.textContent='Gamepad: odpojen.';});
requestAnimationFrame(pollPresenterGamepad);
selectPresenterTab(0);
"""
JS += """
const projectCards=document.querySelector('#project-cards');
const sidebarProjects=document.querySelector('#sidebar-project-list');
const projectStatus=document.querySelector('#project-status');
const projectView=document.querySelector('#project-view');
const settingsView=document.querySelector('#settings-view');
const todoTree=document.querySelector('#todo-tree');
const todoStatus=document.querySelector('#todo-status');
const sidebarArtifacts=document.querySelector('#sidebar-artifact-list');
const sidebarArtifactStatus=document.querySelector('#sidebar-artifact-status');
const sidebarTabs=[...document.querySelectorAll('#sidebar-tabs [role="tab"]')];
function selectSidebarTab(selected){
 for(const tab of sidebarTabs){
  const active=tab===selected;
  tab.setAttribute('aria-selected',String(active));tab.tabIndex=active ? 0 : -1;
  document.getElementById(tab.getAttribute('aria-controls')).hidden=!active;
 }
}
for(const [index,tab] of sidebarTabs.entries()){
 tab.addEventListener('click',()=>selectSidebarTab(tab));
 tab.addEventListener('keydown',event=>{
  const next={ArrowRight:(index+1)%2,ArrowLeft:(index+1)%2,Home:0,End:1}[event.key];
  if(next===undefined) return;
  event.preventDefault();selectSidebarTab(sidebarTabs[next]);sidebarTabs[next].focus();
 });
}
let currentArtifacts=[];
function renderSidebarArtifacts(items){
 currentArtifacts=items;
 sidebarArtifacts.replaceChildren();
 sidebarArtifactStatus.textContent=items.length ? `Počet položek: ${items.length}` : 'Zatím tu nejsou žádné podklady.';
 for(const item of items){
  const row=document.createElement('li');
  const title=document.createElement('button');title.className='sidebar-artifact-title';title.textContent=item.title;
  title.dataset.id=item.id;title.setAttribute('aria-current','false');
  title.addEventListener('click',()=>openPreview(item.id));
  const id=document.createElement('small');id.className='sidebar-artifact-id';id.textContent=item.id;
 row.append(title,id);sidebarArtifacts.append(row);
 }
 renderSummarySources();
 renderExtractionSources();
 renderMetadataSources();
 renderTaskArtifactSources();
}
let viewRequest=0;
const createTodo=document.querySelector('#create-main-todo');
createTodo.addEventListener('click',()=>{
 if(activeProject && !createTodo.hidden)location.hash='create-main-todo';
});
function renderTodo(todo){
 createTodo.hidden=!!todo;
 document.querySelector('#todo-help').hidden=!todo;
 todoTree.replaceChildren();
 document.querySelector('#todo-title').textContent=todo?.title || '';
 if(!todo){todoStatus.textContent='Založte seznam a mějte úkoly projektu po ruce.';return;}
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
 clearPreview();activeProject=null;document.querySelector('#chat-draft').value='';
 currentArtifacts=[];clearSummary();clearExtraction();clearMetadata();
 activeThread=null;activeTaskThreadId=null;taskOutcomes=[];pendingChatRequest=null;
 document.querySelector('#chat-submit').disabled=true;document.querySelector('#chat-messages').replaceChildren();
 document.querySelector('#chat-backend-status').textContent='Otevřete projekt.';
 document.querySelector('#chat-operation-status').textContent='';document.querySelector('#chat-record-actions').hidden=true;
 document.querySelector('#project-home').hidden=false;
 settingsView.hidden=true;
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
  error.status=response.status;throw error;}
 return result;
}
let catalogRequest=0;
async function openRegisteredProject(projectId){
 ++catalogRequest;
 clearProject();const request=viewRequest;
 projectStatus.textContent='Otevírám projekt…';
 try{
  const result=await projectRequest('/v1/projects/open',{project_id:projectId});
  if(request!==viewRequest)return;
  activeProject={id:projectId,head:result.commit_id};
  renderTodo(result.main_todo);renderSidebarArtifacts(result.artifacts);
  document.querySelector('#project-title').textContent=result.title;
  document.querySelector('#project-commit').textContent=result.commit_id;
  projectView.hidden=false;document.querySelector('#project-home').hidden=true;
  document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=false;
  await loadChat();
  selectSidebarTab(sidebarTabs[1]);
  document.querySelector('#preview-status').textContent=result.artifacts.length ?
   'Vyberte podklad ze seznamu vlevo.' : 'Zatím tu nejsou žádné podklady. První dokument vytvoříte tlačítkem Dokumenty v horní liště.';
 }catch(error){if(request===viewRequest)projectStatus.textContent=error.message;}
}
function renderProjectCatalog(items){
 projectCards.replaceChildren();sidebarProjects.replaceChildren();
 for(const item of items){
  const card=document.createElement('button');card.type='button';card.className='project-card';card.dataset.id=item.id;
  const name=document.createElement('span');name.className='project-name';name.textContent=item.title;
  const description=document.createElement('span');description.className='project-description';
  description.textContent=item.available ? (item.description.slice(0,240) || 'Prostor pro zdroje, poznámky a rozhodnutí.') : 'Projekt nelze načíst. Ověřte jeho umístění a konfiguraci.';
  const id=document.createElement('span');id.className='project-id';id.textContent=item.id;
  const action=document.createElement('span');action.className='project-action';action.textContent=item.available?'Otevřít projekt →':'Zkusit otevřít →';
  card.append(name,description,id,action);card.addEventListener('click',()=>openRegisteredProject(item.id));projectCards.append(card);
  const row=document.createElement('li');const compact=document.createElement('button');compact.type='button';compact.dataset.id=item.id;
  compact.textContent=item.title;compact.title=item.id;compact.addEventListener('click',()=>openRegisteredProject(item.id));row.append(compact);sidebarProjects.append(row);
 }
 document.querySelector('#sidebar-project-status').textContent=items.length ? `Počet projektů: ${items.length}` : 'Zatím bez projektů.';
}
async function loadProjects(selectedId=null){
 const request=++catalogRequest;
 clearProject();projectCards.replaceChildren();sidebarProjects.replaceChildren();
 projectStatus.textContent='Načítám projekty…';document.querySelector('#sidebar-project-status').textContent='Načítám projekty…';
 try{
  const result=await projectRequest('/v1/projects',{details:true});
  if(request!==catalogRequest)return;
  renderProjectCatalog(result.projects);
  projectStatus.textContent=result.projects.length ? 'Vyberte projekt.' : 'Zatím nemáte žádný projekt.';
  if(selectedId && result.projects.some(p=>p.id===selectedId))await openRegisteredProject(selectedId);
 }catch(error){if(request===catalogRequest){projectStatus.textContent=error.message;document.querySelector('#sidebar-project-status').textContent='Seznam není dostupný.';}}
}
document.querySelector('#back-projects').addEventListener('click',()=>loadProjects());

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
for(const [index,tab] of mainTabs.entries()){
 tab.addEventListener('click',()=>selectMainTab(tab));
 tab.addEventListener('keydown',event=>{
  const next={ArrowRight:(index+1)%mainTabs.length,
   ArrowLeft:(index+mainTabs.length-1)%mainTabs.length,Home:0,End:mainTabs.length-1}[event.key];
  if(next===undefined)return;
  event.preventDefault();selectMainTab(mainTabs[next]);mainTabs[next].focus();
 });
}
let settingsReturn=null;
const settingsTabs=[...document.querySelectorAll('#settings-tabs [role="tab"]')];
function selectSettingsTab(selected){
 for(const tab of settingsTabs){
  const active=tab===selected;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
  const panel=document.getElementById(tab.getAttribute('aria-controls'));if(panel)panel.hidden=!active;
 }
 const administration=document.getElementById('administration');if(administration)administration.hidden=selected.id==='settings-backend-tab';
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
 const activeTab=mainTabs.find(tab=>tab.getAttribute('aria-selected')==='true');
 settingsReturn={project:!!activeProject,tabId:activeTab?.id || 'preview-tab'};
 document.querySelector('#project-home').hidden=true;projectView.hidden=true;settingsView.hidden=false;
 document.querySelector('#sidebar-projects').hidden=true;document.querySelector('#sidebar-project-tools').hidden=true;
 selectSettingsTab(document.querySelector('#settings-backend-tab'));
 document.querySelector('#settings-backend-status').textContent='Načítám stav lokálního backendu…';
 await loadBackendBinding();
}
async function closeSettings(){
 const destination=settingsReturn;settingsReturn=null;settingsView.hidden=true;
 document.dispatchEvent(new Event('settingsclosed'));
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
 let fence=null,code=null;
 for(const line of text.split('\\n')){
  const marker=line.match(/^\\s*(`{3,}|~{3,})(.*)$/);
  if(marker && (!fence || (marker[1][0]===fence[0] && marker[1].length>=fence.length && !marker[2].trim()))){
   if(fence){fence=null;code=null;}else{fence=marker[1];code=document.createElement('pre');previewContent.append(code);}
   continue;
  }
  if(fence){code.textContent+=line+'\\n';continue;}
  const heading=line.match(/^(#{1,6})\\s+(.*)$/);
  const element=document.createElement(heading?'h'+heading[1].length:'p');
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
document.querySelector('#pdf-show').addEventListener('click',()=>{
 const input=document.querySelector('#pdf-page');
 if(input.reportValidity() && selectedArtifact)openPreview(selectedArtifact,Number(input.value));
});
const draft=document.querySelector('#chat-draft');
const chatStatus=document.querySelector('#chat-backend-status');
const settingsBackendStatus=document.querySelector('#settings-backend-status');
const settingsExternalStatus=document.querySelector('#settings-external-status');
const backendMetricsStatus=document.querySelector('#backend-metrics-status');
const backendMetricsIndicator=document.querySelector('#backend-metrics-indicator');
const chatMessages=document.querySelector('#chat-messages');
const chatForm=document.querySelector('#chat-backend-form');
const chatOperationStatus=document.querySelector('#chat-operation-status');
const chatStream=document.querySelector('#chat-stream');
const chatRunUsage=document.querySelector('#chat-run-usage');
let activeThread=null,chatBinding=null,externalBinding=null,externalStreaming=false,pendingChatRequest=null,pendingExternalPreview=null,pendingExternalProposal=null;
let activeTaskThreadId=null,taskOutcomes=[],chatSelectionRevision=0;
async function externalStreamRequest(request,onDelta){
 const response=await fetch('/v1/external/send-stream',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
 if(!response.ok)throw Object.assign(new Error('Streamovaný požadavek byl odmítnut.'),{status:response.status});
 const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result=null;
 while(true){const part=await reader.read();buffer+=decoder.decode(part.value || new Uint8Array(),{stream:!part.done});
  let newline;while((newline=buffer.indexOf('\\n'))>=0){const line=buffer.slice(0,newline);buffer=buffer.slice(newline+1);
   if(!line)continue;const event=JSON.parse(line);
   if(event.type==='delta' && typeof event.delta==='string')onDelta(event.delta);
   else if(event.type==='result')result=event.result;
   else if(event.type==='error')throw Object.assign(new Error(event.error),{status:event.status});
   else throw new Error('Neplatná událost streamu.');}
  if(part.done)break;}
 if(buffer || !result)throw new Error('Stream skončil bez finální odpovědi.');return result;
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
 document.querySelector('#chat-record-actions').hidden=!(thread?.messages?.length);
}
function renderRunUsage(report){
 if(!report || report.status!=='available'){chatRunUsage.hidden=true;return;}
 chatRunUsage.textContent='Spotřeba běhu: '+report.metrics
  .map(item=>`${item.name} ${item.value} ${item.unit}`).join(' · ');
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
function taskButton(label,handler,secondary=false){
 const button=document.createElement('button');button.type='button';button.textContent=label;
 if(secondary)button.className='secondary-button';button.addEventListener('click',handler);return button;
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
   outcome.kind==='artifact-link'?'Vytvořený artefakt':'Externí volání';card.append(heading);
  if(outcome.kind==='artifact-draft'){
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
document.querySelector('#chat-new-thread').addEventListener('click',()=>{
 ++chatSelectionRevision;pendingChatRequest=null;activeTaskThreadId=crypto.randomUUID();
 taskOutcomes=[];renderChat(null);draft.value='';
 chatOperationStatus.textContent='';
 document.querySelector('#chat-submit').disabled=true;
 chatStatus.textContent=chatBinding ? `Nové vlákno · backend: ${chatBinding.model}` :
  'Nové vlákno · nejprve nastavte backend.';
 draft.focus();
});
function fillBinding(binding){
 chatBinding=binding;const fields=chatForm.elements;
 if(binding){fields.boundary.value=binding.boundary;fields.endpoint.value=binding.endpoint;
  fields.model.value=binding.model;fields.target_id.value=binding.target_id;
  fields.tls_cert_sha256.value=binding.tls_cert_sha256 || '';
  chatStatus.textContent=`Backend: ${binding.model} · ${binding.boundary}`;
  settingsBackendStatus.textContent=`Nastaven backend ${binding.model} · ${binding.boundary}.`;
 }else{
  chatStatus.textContent='Backend zatím není nastaven.';
  settingsBackendStatus.textContent='Backend zatím není nastaven.';
 }
 refreshChatModeControls();
}
async function loadBackendBinding(){
 try{const result=await projectRequest('/v1/chat/status',{});fillBinding(result.binding);
  const external=await projectRequest('/v1/external/status',{});
  externalBinding=external.binding;
  externalStreaming=external.capabilities?.streaming===true;
  refreshChatModeControls();
  fillExternalModels(external.model_catalog);
  settingsExternalStatus.textContent=external.binding ?
   `Nastaven externí backend ${external.binding.model}; klíč ${external.credential?.available?'je uložen':'chybí'}.` :
   'Externí backend zatím není nastaven.';
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
 if(mode==='orchestration'){
  adapter.value='ollama';adapter.disabled=true;model.value=chatBinding?.model || '';model.disabled=true;
  artifacts.hidden=false;
 }else{
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
   activeTaskThreadId=activeThread.thread_id;taskOutcomes=[];renderChat(activeThread);
  }catch(error){event.currentTarget.value='brainstorming';chatOperationStatus.textContent=error.message;}
 }else{activeThread=null;activeTaskThreadId=crypto.randomUUID();taskOutcomes=[];renderChat(null);}
 refreshChatModeControls();
});
async function loadChat(){
 const selectionRevision=chatSelectionRevision;
 try{
  const result=await projectRequest('/v1/chat/status',{});fillBinding(result.binding);
  const active=[...result.threads].reverse().filter(item=>item.status==='active');
  const tasks=activeProject ? await projectRequest('/v1/tasks/list',{project_id:activeProject.id}) : {outcomes:[]};
  if(selectionRevision!==chatSelectionRevision)return;
  activeThread=active.find(item=>item.project_id===activeProject?.id) ||
               active.find(item=>item.project_id===null) || null;
  if(activeThread){document.querySelector('#chat-mode').value=activeThread.classification;
   document.querySelector('#chat-run-adapter').value='ollama';
   document.querySelector('#chat-run-model').value=chatBinding?.model || '';refreshChatModeControls();}
  activeTaskThreadId=tasks.outcomes.at(-1)?.thread_id || activeThread?.thread_id || null;
  taskOutcomes=tasks.outcomes.filter(item=>item.thread_id===activeTaskThreadId);
  renderChat(activeThread);
 }catch(error){if(selectionRevision===chatSelectionRevision){chatStatus.textContent=error.message;renderChat(null);}}
}
chatForm.addEventListener('submit',async event=>{
 event.preventDefault();const fields=chatForm.elements;
 const boundary=fields.boundary.value;
 const binding={schema_version:1,binding_id:chatBinding?.binding_id || crypto.randomUUID(),
  revision:crypto.randomUUID(),adapter:'ollama',boundary,endpoint:fields.endpoint.value.trim(),
  model:fields.model.value.trim(),target_id:boundary==='same-node'?'local-process':fields.target_id.value.trim()};
 if(boundary==='private-network')binding.tls_cert_sha256=fields.tls_cert_sha256.value.trim();
 settingsBackendStatus.textContent='Ukládám backend…';
 try{const result=await projectRequest('/v1/chat/configure',binding);fillBinding(result.binding);
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
 const disabled=!activeProject || !draft.value.trim();
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
    activeThread=result.thread;renderChat(result.thread);renderRunUsage(result.usage_report);draft.value='';
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
 selectMainTab(mainTabs[1]);
 if(!chatBinding){chatOperationStatus.textContent='Nejprve uložte nastavení backendu.';return;}
 const mode=document.querySelector('#chat-mode').value;
 const adapter=document.querySelector('#chat-run-adapter').value;
 const model=document.querySelector('#chat-run-model').value.trim();
 if(!model){chatOperationStatus.textContent='Vyberte model běhu.';return;}
 const runChoice={mode,adapter,model:mode==='orchestration'?null:model};
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
  chatStream.textContent='';chatStream.hidden=!externalStreaming;
  try{const result=externalStreaming ?
   await externalStreamRequest(pendingChatRequest,delta=>{chatStream.textContent+=delta;}) :
   await projectRequest('/v1/external/send',pendingChatRequest,210000);
   activeThread=result.thread;activeTaskThreadId=result.thread.thread_id;
   renderChat(result.thread);renderRunUsage(result.usage_report);pendingChatRequest=null;
   chatStream.hidden=true;draft.value='';draft.focus();chatOperationStatus.textContent='Externí odpověď byla přijata.';
  }catch(error){
   if([409,422,502].includes(error.status))pendingChatRequest=null;
   chatOperationStatus.textContent=error.message;
  }finally{chatStream.hidden=true;submit.disabled=!activeProject || !draft.value.trim();}
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
  chatOperationStatus.textContent='Odesílám…';
  const thinking=setTimeout(()=>{chatOperationStatus.textContent='Model přemýšlí…';},250);
  try{
   const result=await projectRequest('/v1/chat/send',pendingChatRequest,210000);
   activeThread=result.thread;activeTaskThreadId=result.thread.thread_id;
   renderChat(result.thread);renderRunUsage(result.usage_report);pendingChatRequest=null;draft.value='';draft.focus();
   chatOperationStatus.textContent='Odpověď je připravena.';
  }catch(error){
   if(error.status===422)pendingChatRequest=null;
   chatOperationStatus.textContent=error.message+(error.status===422 ?
    ' Zadání můžete po opravě zopakovat jako nový běh.' : '');
  }finally{clearTimeout(thinking);submit.disabled=!activeProject || !draft.value.trim();
   document.querySelector('#main-panel-content').scrollTop=document.querySelector('#main-panel-content').scrollHeight;}
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
 const thinking=setTimeout(()=>{chatOperationStatus.textContent='Model přemýšlí…';},250);
 try{
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
  if(error.status===422)pendingChatRequest=null;
  chatOperationStatus.textContent=error.message+(error.status===422 ?
   ' Zadání můžete po opravě zopakovat jako nový běh.' : '');
 }
 finally{clearTimeout(thinking);submit.disabled=!activeProject || !draft.value.trim();
  document.querySelector('#main-panel-content').scrollTop=document.querySelector('#main-panel-content').scrollHeight;}
});
async function assignActiveThread(){
 if(!activeProject || !activeThread)throw new Error('Nejprve vytvořte chatové vlákno.');
 if(activeThread.project_id===activeProject.id)return activeThread;
 const assigned=await projectRequest('/v1/chat/assign',{project_id:activeProject.id,
  thread_id:activeThread.thread_id,expected_revision:activeThread.revision});
 renderChat(assigned);return assigned;
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
document.querySelector('#chat-save-snapshot').addEventListener('click',event=>runChatRecord(event.currentTarget,'snapshot'));
document.querySelector('#chat-save-output').addEventListener('click',event=>runChatRecord(event.currentTarget,'output'));
draft.addEventListener('keydown',event=>{
 if(event.key==='Enter' && !event.shiftKey && !event.isComposing){event.preventDefault();document.querySelector('#chat-composer').requestSubmit();}
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
 }catch(error){summaryStatus.textContent=error.message;}
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
 }catch(error){extractionStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
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
 }catch(error){metadataStatus.textContent=error.message;}finally{event.currentTarget.disabled=false;}
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
loadProjects();
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
          '/app.js': ('text/javascript; charset=utf-8', JS)}


class DesktopHandler(Handler):
    assets = ASSETS
    max_body = 64 * 1024
    post_paths = Handler.post_paths | {'/v1/projects', '/v1/projects/open',
        '/v1/artifacts/preview', '/v1/chat/status', '/v1/chat/configure', '/v1/chat/send',
        '/v1/chat/orchestration', '/v1/gamepad/status', '/v1/presentation/status',
        '/v1/presentation/control', '/v1/presentation/public',
        '/v1/external/status', '/v1/external/configure', '/v1/external/models',
        '/v1/external/propose', '/v1/external/send', '/v1/external/send-stream', '/v1/external/request',
        '/v1/external/preview', '/v1/external/confirm',
        '/v1/external/cancel',
        '/v1/tasks/route', '/v1/tasks/list', '/v1/tasks/cancel',
        '/v1/tasks/artifact', '/v1/tasks/external/preview',
        '/v1/tasks/external/confirm', '/v1/tasks/external/cancel',
        '/v1/chat/assign', '/v1/chat/snapshot', '/v1/chat/output',
        '/v1/summary/status', '/v1/summary/preview', '/v1/summary/publish',
        '/v1/extraction/status', '/v1/extraction/preview', '/v1/extraction/publish',
        '/v1/metadata-suggestions/status', '/v1/metadata-suggestions/preview',
        '/v1/metadata-suggestions/publish'}

    def dispatch(self, request):
        if self.path == '/v1/counter':
            return super().dispatch(request)
        if self.path == '/v1/gamepad/status' and (request == {} or isinstance(request, dict)):
            return self.reply(200, scan_gamepads())
        if self.path == '/v1/presentation/status' and (request == {} or isinstance(request, dict)):
            return self.reply(200, presentation_status(self.server))
        if self.path == '/v1/presentation/control' and isinstance(request, dict):
            try:
                return self.reply(200, presentation_public_payload(self.server, request))
            except ValueError as exc:
                return self.reply(409, {'error': str(exc)})
        if self.path == '/v1/presentation/public' and request == {}:
            return self.reply(200, presentation_public_payload(self.server))
        projects = self.server.projects or Projects()
        try:
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
            if self.path == '/v1/tasks/external/preview' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_external_preview(request))
            if self.path == '/v1/tasks/external/confirm' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_external_confirm(request))
            if self.path == '/v1/tasks/external/cancel' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.task_external_cancel(request))
            if self.path == '/v1/chat/configure' and isinstance(request, dict):
                return self.reply(200, self.server.chat_service.configure(request))
            if (self.path == '/v1/chat/orchestration' and isinstance(request, dict)
                    and set(request) == {'source_thread_id', 'thread_id', 'created_at'}):
                return self.reply(200, self.server.chat_service.start_orchestration(**request))
            if self.path == '/v1/chat/send' and isinstance(request, dict) and set(request) in ({
                    'project_id', 'expected_head', 'thread_id', 'turn_id', 'message_id',
                    'run_id', 'manifest_id', 'assistant_message_id', 'selected_message_ids',
                    'content', 'privacy', 'created_at'}, {
                    'project_id', 'expected_head', 'thread_id', 'turn_id', 'message_id',
                    'run_id', 'manifest_id', 'assistant_message_id', 'selected_message_ids',
                    'content', 'privacy', 'created_at', 'run_choice'}):
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
            if (self.path == '/v1/projects/open' and isinstance(request, dict)
                    and set(request) == {'project_id'} and isinstance(request['project_id'], str)):
                return self.reply(200, projects.open(request['project_id']))
            if (self.path == '/v1/artifacts/preview' and isinstance(request, dict)
                    and set(request) == {'project_id', 'artifact_id', 'expected_head', 'page'}):
                return self.reply(200, projects.preview(**request))
            return self.send_error(400)
        except UnknownRun:
            return self.reply(409, {'error': 'Výsledek běhu není známý. Vlákno bylo zachováno; '
                                   'zkontrolujte stav před novým odesláním.'})
        except OpenAIUnknownRun:
            return self.reply(409, {'error': 'Výsledek externího běhu není známý. Požadavek '
                                   'automaticky neopakujte; stav byl zachován.'})
        except OllamaResponseError:
            return self.reply(502, {'error': 'Lokální LLM požadavek selhal. Vlákno a stav běhu byly zachovány.'})
        except OpenAIResponseError:
            if self.path == '/v1/external/models':
                return self.reply(502, {'error': 'Seznam modelů externího provideru nelze načíst. '
                                       'Uložené nastavení nebylo změněno.'})
            return self.reply(502, {'error': 'Externí LLM odpověď nebylo možné bezpečně přijmout. '
                                   'Běh byl ukončen bez automatického opakování.'})
        except PendingOperation:
            return self.reply(409, {'error': 'Projekt má nedokončenou operaci. Nejprve proveďte obnovu.'})
        except StaleIndex:
            return self.reply(409, {'error': 'Projekt se během čtení změnil. Zkuste jej znovu otevřít.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            if self.path == '/v1/external/propose':
                return self.reply(422, {'error': 'Ollama nevrátila platný návrh externího volání. '
                                       'Zkuste návrh vytvořit znovu nebo použijte ruční externí náhled.'})
            if self.path == '/v1/tasks/route':
                return self.reply(422, {'error': 'Ollama vrátila neplatný formát výsledku úlohy. '
                                       'Projekt ani předchozí vlákno nebyly změněny.'})
            if self.path.startswith(('/v1/chat/', '/v1/external/', '/v1/tasks/', '/v1/summary/', '/v1/extraction/',
                                     '/v1/metadata-suggestions/')):
                return self.reply(422, {'error': 'Chat požadavek nelze provést. Ověřte backend, '
                                       'projekt, výběr kontextu a lokální stav.'})
            # Do not forward paths, Git stderr or configuration payloads to the renderer.
            return self.reply(422, {'error': 'Projekt nelze otevřít: ověřte konfiguraci, registraci, '
                                   'práva lokálního stavu a platnost Git dat/indexu.'})

    def do_GET(self):
        if self.single('Host') != self.server.authority:
            return self.send_error(403)
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
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
