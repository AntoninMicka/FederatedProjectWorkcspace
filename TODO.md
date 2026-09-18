<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-UI-01: Přepnutí do chatu až při odeslání

Milník M1; malá samostatná UI feature po začlenění F-M2-OLLAMA-01. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-UI-01 — Přepnutí do chatu až při odeslání

- Stav: [ ] [in progress]; implementace a lokální PoC ověření dokončeny 2026-09-18, dávka čeká na commit a PR.
- Původ: uživatelský požadavek 2026-09-18 změnit automatické přepnutí při psaní.
- Skutečná větev: `feature/f-m1-ui-01-prompt-submit-tab`, založená z `develop` (`d1fc6f4`, PR #27 začleněn); jediný budoucí PR do `develop`.
- Výstup: editace promptu zachová aktivní náhled nebo chat; do chatu přepne až platné odeslání Enterem nebo tlačítkem.
- Mimo rozsah: perzistentní chat, volání LLM/backendu, změna lifecycle draftu a klávesové konvence Shift+Enter.
- Akceptace: psaní v náhledu nepřepne záložku, neprázdný prompt povolí odeslání, Enter/tlačítko přepne do chatu a vloží zprávu, Shift+Enter pouze vloží řádek; dokumentace a testy odpovídají chování.

- [x] [completed] **F-M1-UI-01-A — Oddělit editaci a odeslání promptu (implemented, 2026-09-18).** `input` pouze aktualizuje dostupnost tlačítka; změnu hlavní záložky provede až validní `submit`.
- [x] [completed] **F-M1-UI-01-B — Regresní ověření a dokumentace (PoC validated, 2026-09-18).** Unit kontrakt a skutečný Qt/WebEngine smoke ověřují zachování náhledu při psaní a přepnutí až po Enteru; cílených 5 testů prošlo. Celá sada prošla 231 testy (22 přeskočeno); uživatelský návod a ADR 0019 odpovídají změněnému chování.

### Hranice

- Zpráva i draft zůstávají pouze v paměti stránky; tato dávka nepřidává persistentní operaci ani nové recovery hranice.
- F-M2-CHAT-01 zůstává následující samostatnou feature dávkou.
