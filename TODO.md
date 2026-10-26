<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — COMP-02

Aktivní feature dávka: **Lokální Julia runner a publikace výsledků**. Původní
akceptace byla před PR znovu otevřena kvůli chybějícímu bezpečnému onboardingu;
větev zůstává `feature/comp-02-julia-runner` a cílem je jediný PR do `develop`.

- [x] [completed] **COMP-02-A až COMP-02-E — runner, izolace, publikace,
  regrese a fyzická ARM64 akceptace (PoC validated).** Dosavadní implementace
  a důkazy zůstávají platné; konsolidovaná evidence je dočasně ve WORK_LOG.
- [ ] [in progress] **COMP-02-F — bezpečný onboarding runtime
  (implemented).** Doplnit jediný `setup` příkaz, který bez projektových
  argumentů ověří podporovanou verzi/platformu a známý checksum archivu,
  prakticky prověří bubblewrap namespaces, vytvoří owned mode-0700 depot/state
  a immutable binding bez přepisu. Výsledek musí rozlišit neověřený podpis,
  být idempotentní pro stejný binding a dát konkrétní další krok.

## Crash hranice doplnění

Kontroly runtime, archivu a bubblewrap předcházejí persistentním změnám.
Vytvořené privátní adresáře jsou bezpečně opakovatelné; binding vzniká jen
novým mode-0600 souborem a existující odlišný obsah se nepřepisuje. Pád před
bindingem může zanechat pouze prázdný depot/state, které retry bezpečně převezme.
