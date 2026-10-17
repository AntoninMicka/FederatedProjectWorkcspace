# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Render an A4 paper-review pack from the current shared UI forms."""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spikes.desktop_ui import CSS, HTML


EDITION = "2026-10-17"


def sheet(key, title, selectors=(), forms=(), *, scale=.78, source="Sdílené web/desktop UI", native_html="", notes=True):
    return {
        "key": key,
        "title": title,
        "selectors": list(selectors),
        "forms": list(forms),
        "scale": scale,
        "source": source,
        "native_html": native_html,
        "notes": notes,
    }


def native_form(intro, fields, buttons, *, notice=""):
    rows = []
    for label, kind, value in fields:
        if kind == "select":
            options = "".join(f"<option>{html.escape(item)}</option>" for item in value)
            control = f"<select>{options}</select>"
        elif kind == "check":
            control = f'<label class="native-check"><input type="checkbox"> {html.escape(value)}</label>'
        elif kind == "textarea":
            control = f"<textarea rows=5>{html.escape(value)}</textarea>"
        else:
            control = f'<input value="{html.escape(value)}">'
        rows.append(f"<label><span>{html.escape(label)}</span>{control}</label>")
    actions = "".join(f"<button type=button>{html.escape(button)}</button>" for button in buttons)
    notice_html = f'<p class="native-notice">{html.escape(notice)}</p>' if notice else ""
    return (
        f'<section class="native-form"><p>{html.escape(intro)}</p>'
        + "".join(rows)
        + notice_html
        + f'<div class="form-actions">{actions}</div><textarea rows=5 aria-label="Výstup / diagnostika"></textarea></section>'
    )


SHEETS = [
    sheet("login", "Přihlášení", ("#login",), ("login-form",), scale=.92),
    sheet("project", "Projekt — vytvoření a bezpečná akce", ("#create-project", "#project-delete-panel"),
          ("create-project",), scale=.82),
    sheet("notebooklm", "Import celého projektu z NotebookLM", ("#notebooklm-import",), scale=.72),
    sheet("ollama", "Nastavení — lokální AI backend", ("#chat-backend-form",), ("chat-backend-form",), scale=.9),
    sheet("search-config", "Nastavení — řízené webové hledání", ("#search-backend-form",),
          ("search-backend-form",), scale=.9),
    sheet("drive-config", "Nastavení — Google Drive OAuth", ("#google-drive-config-form",),
          ("google-drive-config-form",), scale=.9),
    sheet("comfy", "Nastavení — ComfyUI", ("#comfy-backend-form",), ("comfy-backend-form",), scale=.68),
    sheet("openai", "Nastavení — OpenAI text, obrázky a náklady",
          ("#external-backend-form", "#openai-image-form", "#backend-metrics"),
          ("external-backend-form", "openai-image-form", "backend-metrics-form"), scale=.67),
    sheet("cms", "Publikační CMS — obsah webů", ("#settings-cms-panel",),
          ("cms-deployment-form",), scale=.56),
    sheet("users", "Správa uzlu — lokální účty", ("#admin-users-panel",),
          ("admin-user-create",), scale=.78),
    sheet("federation", "Správa uzlu — federace a mapování účtů", ("#admin-federation",),
          ("admin-peer-create", "admin-mapping-create", "admin-mapping-import"), scale=.56),
    sheet("drive-import", "Import zdroje — Google Drive", ("#google-drive-import",), scale=.6),
    sheet("source-import", "Import zdroje — místní soubor", ("#source-import-form",),
          ("source-import-form",), scale=.86),
    sheet("history", "Historie dokumentu", (".history-form",), scale=.8),
    sheet("document", "Dokument — editor a odstranění", ("#artifact-editor-form", "#artifact-delete-preview"),
          ("artifact-editor-form",), scale=.64),
    sheet("task", "Chat — zadání úkolu a explicitní routování", ("#chat-composer",),
          ("chat-composer",), scale=.68),
    sheet("chat-confirm", "Chat — odstranění a externí předání",
          ("#chat-delete-preview", "#external-proposal", "#external-preview"), scale=.68),
    sheet("public-source", "Veřejný internet — hledání a načtení zdroje",
          ("#search-preview", "#public-source-preview"), scale=.72),
    sheet("summary", "Lokální souhrn", ("#summary-panel",), scale=.68),
    sheet("workflow", "Creator → opponent → publikace", ("#workflow-panel",), scale=.54),
    sheet("extraction", "Strukturovaná extrakce", ("#extraction-panel",), scale=.67),
    sheet("image", "Generování obrázku", ("#image-panel",), scale=.7),
    sheet("presentation", "Editor prezentace", ("#presentation-panel",), scale=.48, notes=False),
    sheet("presentation-pdf", "Export prezentace do PDF", ("#presentation-print-dialog",), scale=.82),
    sheet("metadata", "Návrh popisu a štítků", ("#metadata-panel",), scale=.72),
    sheet("gamepad", "Presenter — nastavení gamepadu", (".presenter-gamepad-settings",), scale=.78),
    sheet(
        "native-profile", "Nativní dialog — uživatelský profil", source="PySide6 desktop",
        native_html=native_form(
            "Údaje se zobrazí na závěrečném slidu textově a v QR kódu; zůstávají v lokálním profilu.",
            (("Jméno", "text", ""), ("E-mail", "text", ""), ("Telefon", "text", ""), ("Web", "text", "")),
            ("Uložit profil",))),
    sheet(
        "native-deploy", "Nativní dialog — nasazení LXC uzlu", source="PySide6 desktop", scale=.75,
        native_html=native_form(
            "Jedno SSH spojení; cílový kontejner a operace se vždy potvrzují samostatně.",
            (("Zapamatovaný uzel", "select", ("Nový / ručně zadaný uzel", "workspace-m0 — host")),
             ("SSH router", "text", "root@192.168.100.1"), ("Kontejner", "text", "workspace-m0"),
             ("Privátní LAN", "text", "192.168.100.0/24"),
             ("Adresa desktopového uzlu", "text", "https://192.168.100.2:8443"),
             ("Operace", "select", ("První instalace a propojení", "Aktualizovat pouze aplikaci",
                                      "Obnovit přerušené nasazení", "Resetovat stav", "Aktualizovat adresu"))),
            ("Zobrazit souhrn a spustit",), notice="Výstup / průběh vzdálené operace")),
    sheet(
        "native-network", "Nativní dialog — síťový backend a spojení", source="PySide6 desktop", scale=.68,
        native_html=native_form(
            "Nastavení opt-in HTTPS backendu desktopu a diagnostika spojení s protějším uzlem.",
            (("Backend", "check", "Povolit HTTPS backend při běhu desktopu"),
             ("Naslouchací IPv4", "text", "192.168.100.2"), ("Port", "text", "8443"),
             ("Povolená LAN klientů", "text", "192.168.100.0/24"), ("TLS certifikát", "text", ""),
             ("TLS soukromý klíč", "text", ""), ("Veřejná CA", "text", ""),
             ("Nové TLS", "check", "Vytvořit lokální CA a TLS certifikát pro zvolenou IP"),
             ("Protější uzel", "select", ("workspace-m0 — https://…",)),
             ("CA protějšího uzlu", "text", "")),
            ("Použít a uložit nastavení", "Ověřit HTTPS a identitu", "Ověřit oba směry"),
            notice="Firewall ani projektová synchronizace se tímto dialogem automaticky nemění.")),
    sheet(
        "native-transfer", "Nativní dialog — přenos veřejného projektu do LXC", source="PySide6 desktop", scale=.8,
        native_html=native_form(
            "Přenos celé veřejné Git historie bez credentials, lokálního indexu a journalu.",
            (("Projekt desktopu", "select", ("Veřejný projekt",)),
             ("Cílový LXC uzel", "select", ("workspace-m0 — https://…",)),
             ("Důvěryhodná veřejná CA LXC", "text", "")),
            ("Potvrdit a přenést",), notice="Cíl musí být nový projekt; neveřejná historie přenos zastaví.")),
    sheet(
        "native-displays", "Nativní dialog — displeje a role prezentace", source="PySide6 desktop", scale=.86,
        native_html=native_form(
            "Přiřazení displeje řečníkovi a divákům; ostatní displeje zůstanou nepoužité.",
            (("Řečník — ovládání a poznámky", "select", ("1 · displej · 1920 × 1080",)),
             ("Diváci — schválený slide", "select", ("Bez promítání", "2 · displej · 1920 × 1080"))),
            ("Identifikovat displeje", "Použít role", "Zrušit"))),
]


PRINT_CSS = r"""
@page { size: A4 portrait; margin: 8mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: white !important; color: #162638; visibility: visible !important;
  height: auto !important; min-height: 0 !important; overflow: visible !important; }
body { display: block !important; font: 8.4pt/1.28 system-ui, sans-serif; }
#source-ui { display: none !important; }
#print-root { display: block !important; }
.cover, .sheet { break-after: page; page-break-after: always; }
.cover { min-height: 270mm; padding: 10mm 8mm; }
.cover h1 { font-size: 26pt; margin: 0 0 5mm; color: #176b60; }
.cover h2 { font-size: 12pt; margin-top: 8mm; }
.cover ol { columns: 2; column-gap: 10mm; padding-left: 6mm; }
.cover li { break-inside: avoid; margin: 0 0 2mm; }
.sheet { min-height: 270mm; position: relative; padding: 0; }
.sheet-header { display: flex; justify-content: space-between; gap: 8mm; align-items: baseline;
  border-bottom: .5mm solid #176b60; padding-bottom: 2mm; margin-bottom: 3mm; }
.sheet-header h1 { font-size: 14pt; line-height: 1.15; margin: 0; color: #176b60; }
.sheet-header p { margin: 0; color: #526675; white-space: nowrap; }
.sheet-body { display: block !important; transform-origin: top left; width: 100%; color: #162638; }
.sheet-body [hidden] { display: block !important; }
.sheet-body dialog { display: block !important; position: static !important; inset: auto !important; width: auto !important;
  max-width: 100% !important; margin: 0 !important; border: 1px solid #d6b36a; }
.sheet-body details > * { display: block !important; }
.sheet-body, .sheet-body * { max-width: 100% !important; min-height: 0 !important; overflow: visible !important; }
.sheet-body section, .sheet-body form, .sheet-body div { height: auto !important; }
.sheet-body main, .sheet-body aside { width: auto !important; position: static !important; }
.sheet-body iframe { display: block; height: 35mm; border: 1px dashed #8faabc; }
.sheet-body input, .sheet-body select, .sheet-body textarea { border: 1px solid #8faabc !important; background: white !important;
  color: #162638 !important; min-height: 7mm; }
.sheet-body textarea { resize: none; }
.sheet-body button { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
.sheet-body pre:empty::after, .sheet-body output:empty::after, .placeholder::after { content: "prostor pro dynamický obsah";
  display: block; min-height: 12mm; color: #82909d; border: 1px dashed #a9b8c3; padding: 2mm; }
.sheet-body ul:empty::after, .sheet-body ol:empty::after, .sheet-body tbody:empty::after { content: "dynamický seznam";
  display: block; min-height: 9mm; color: #82909d; border: 1px dashed #a9b8c3; padding: 2mm; }
.annotation { break-inside: avoid; margin-top: 4mm; min-height: 28mm; border: .35mm solid #9cafb8;
  background-image: radial-gradient(#b9c7cd .35mm, transparent .35mm); background-size: 5mm 5mm; }
.annotation strong { display: inline-block; background: white; padding: 1.5mm 2mm; color: #526675; }
.native-form { max-width: 178mm; padding: 5mm; border: 1px solid #dce3e9; border-radius: 3mm; }
.native-form > label { display: grid; grid-template-columns: 58mm 1fr; gap: 4mm; align-items: center; margin: 3mm 0; }
.native-form > label > span { font-weight: 650; }
.native-form input, .native-form select, .native-form textarea { width: 100%; padding: 2mm; }
.native-form .native-check { display: flex; align-items: center; gap: 2mm; }
.native-notice { padding: 3mm; border-left: 1mm solid #d6b36a; background: #fffaf0; }
@media print {
  body > #print-root { display: block !important; }
  body > script, body > template { display: none !important; }
  #presentation-print-view { display: none !important; }
}
"""


def form_ids(source=HTML):
    return set(re.findall(r'<form\b[^>]*\bid="([^"]+)"', source))


def covered_form_ids():
    return {form_id for item in SHEETS for form_id in item["forms"]}


def validate_inventory(source=HTML):
    missing = sorted(form_ids(source) - covered_form_ids())
    extra = sorted(covered_form_ids() - form_ids(source))
    if missing or extra:
        raise ValueError(f"Form inventory mismatch; missing={missing}, extra={extra}")
    for item in SHEETS:
        if not item["selectors"] and not item["native_html"]:
            raise ValueError(f"Empty sheet definition: {item['key']}")
        for selector in item["selectors"]:
            token = selector[1:]
            if selector.startswith("#") and f'id="{token}"' not in source:
                raise ValueError(f"Missing selector {selector} for {item['key']}")
            if selector.startswith(".") and not re.search(r'class="[^"]*\b' + re.escape(token) + r'\b', source):
                raise ValueError(f"Missing selector {selector} for {item['key']}")


def source_body(source=HTML):
    match = re.search(r'<body[^>]*>(.*)</body>', source, re.S)
    if not match:
        raise ValueError("Shared UI HTML has no body")
    return re.sub(r'<script\b[^>]*>.*?</script>', '', match.group(1), flags=re.S)


def render_html():
    validate_inventory()
    sheet_data = [{key: value for key, value in item.items() if key != "forms"} for item in SHEETS]
    titles = "".join(f"<li>{html.escape(item['title'])}</li>" for item in SHEETS)
    script = r"""
const definitions=__DEFINITIONS__;
const source=document.querySelector('#source-ui').content;
const root=document.querySelector('#print-root');
for(const [offset,definition] of definitions.entries()){
  const article=document.createElement('article'); article.className='sheet'; article.dataset.sheet=definition.key;
  const header=document.createElement('header'); header.className='sheet-header';
  const title=document.createElement('h1'); title.textContent=(offset+1)+'. '+definition.title;
  const origin=document.createElement('p'); origin.textContent=definition.source;
  header.append(title,origin); article.append(header);
  const content=document.createElement('div'); content.className='sheet-body'; content.style.zoom=String(definition.scale);
  if(definition.native_html){content.innerHTML=definition.native_html;}
  for(const selector of definition.selectors){
    const node=source.querySelector(selector);
    if(!node){throw new Error('Chybí tiskový selector '+selector);}
    const clone=node.cloneNode(true); clone.removeAttribute('hidden');
    clone.querySelectorAll('[hidden]').forEach(item=>item.removeAttribute('hidden'));
    clone.querySelectorAll('details').forEach(item=>item.setAttribute('open',''));
    clone.querySelectorAll('dialog').forEach(item=>item.setAttribute('open',''));
    clone.querySelectorAll('select').forEach(item=>{
      if(!item.options.length){const option=document.createElement('option'); option.textContent='Dynamický výběr'; item.append(option);}
    });
    clone.querySelectorAll('iframe').forEach(item=>item.removeAttribute('src'));
    content.append(clone);
  }
  article.append(content);
  if(definition.notes){
    const notes=document.createElement('div'); notes.className='annotation';
    notes.innerHTML='<strong>Poznámky / nový návrh</strong>'; article.append(notes);
  }
  root.append(article);
}
document.body.dataset.ready='true';
""".replace("__DEFINITIONS__", json.dumps(sheet_data, ensure_ascii=False))
    return f"""<!doctype html><html lang=cs><head><meta charset=utf-8>
<meta name=viewport content=\"width=device-width,initial-scale=1\"><title>UX facelift — formuláře A4</title>
<style>{CSS}\n{PRINT_CSS}</style></head><body>
<template id=source-ui>{source_body()}</template>
<main id=print-root><section class=cover><p>Projektový workspace · {EDITION}</p>
<h1>UX facelift — formuláře pro ruční anotaci</h1>
<p>Každý list je odvozený z aktuálního sdíleného UI nebo z používaného nativního desktopového dialogu.
Měřítko je zmenšené pro A4; dynamická data jsou označená jako prázdné pracovní plochy.</p>
<h2>Obsah — {len(SHEETS)} formulářových listů</h2><ol>{titles}</ol>
<p>Do formulářů i tečkované plochy lze kreslit přesuny, šipky, slučování a poznámky.</p></section></main>
<script>{script}</script></body></html>"""


def write_pack(html_path, pdf_path=None, chromium=None):
    html_path = Path(html_path).resolve()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_html(), encoding="utf-8")
    if pdf_path is None:
        return html_path, None
    pdf_path = Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    executable = chromium or shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
    if not executable:
        raise RuntimeError("Chromium nebyl nalezen; HTML balíček byl vytvořen.")
    command = [
        executable, "--headless", "--disable-gpu", "--no-sandbox", "--no-pdf-header-footer",
        "--run-all-compositor-stages-before-draw", "--virtual-time-budget=3000",
        f"--print-to-pdf={pdf_path}", html_path.as_uri(),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, check=False)
    if result.returncode != 0 or not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError("Chromium PDF render selhal: " + (result.stderr.strip() or result.stdout.strip()))
    return html_path, pdf_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", default=str(ROOT / "dist/ux-facelift-forms-a4.html"))
    parser.add_argument("--pdf", default=str(ROOT / "dist/ux-facelift-forms-a4.pdf"))
    parser.add_argument("--chromium")
    args = parser.parse_args()
    html_path, pdf_path = write_pack(args.html, args.pdf, args.chromium)
    print(f"HTML: {html_path}")
    print(f"PDF: {pdf_path}")
    print(f"Sheets: {len(SHEETS)}; covered HTML forms: {len(covered_form_ids())}")


if __name__ == "__main__":
    main()
