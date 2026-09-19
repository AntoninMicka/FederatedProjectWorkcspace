<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-UX-SETTINGS-01: Centralizovaná stránka nastavení

Milník UX/M2; jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-UX-SETTINGS-01 — Centralizovaná stránka nastavení

- Stav: [ ] [in progress]; návrhový kontrakt dokončen 2026-09-19.
- Původ: uživatelský požadavek 2026-09-18 přesunout průběžně rostoucí nastavení z pracovních panelů na společnou stránku.
- Skutečná větev: `feature/f-ux-settings-01-central-settings`, založená z `develop` (`e5b5d9d`); jediný budoucí PR do `develop`.
- Výstup: stránka nastavení uzlu dostupná i bez otevřeného projektu; současný Ollama binding se přesune z chatu do sekce lokálního AI backendu a chat nabídne jen stav a odkaz do nastavení.
- Mimo rozsah: nový konfigurační formát, synchronizace nastavení, credentials/vault, automatická změna routeru, další backendy a projektová nastavení.
- Recovery: ukládání dál používá validaci a atomické nahrazení `OllamaBindings`; neplatný požadavek ponechá poslední platnou konfiguraci a UI nesmí tvrdit úspěch.
- Akceptace: přístup bez projektu i z chatu; jediný editační formulář; zachování hodnot a bezpečnostních hranic; chybové stavy bez ztráty platné konfigurace; testy API/UI a aktualizovaný návod.

- [x] [completed] **F-UX-SETTINGS-01-A — Informační architektura, hranice stavu a reuse review (designed, 2026-09-19).** ADR 0025 vymezuje samostatnou stránku uzlových nastavení, návratový kontext, jediný Ollama formulář, oddělení node-local stavu od projektu a credentials a zachování stávající serverové validace/atomického zápisu. Reuse review adaptuje existující DOM, autentizované API, `ChatService` a `OllamaBindings`; nová persistence ani knihovna nejsou potřeba.
- [ ] [in progress] **F-UX-SETTINGS-01-B — Stránka nastavení a přesun Ollama formuláře (cílová úroveň: implemented).** Doplnit navigaci dostupnou bez projektu, přesunout formulář bez duplikace a v chatu zachovat stav backendu a odkaz s návratem do původního kontextu.
- [ ] [planned] **F-UX-SETTINGS-01-C — Regresní ověření a dokumentace (cílová úroveň: PoC validated).** Ověřit načtení/uložení, chybný vstup, zachování platného bindingu, navigaci bez projektu i z projektu, bezpečné DOM vykreslení a aktualizovat uživatelský návod; spustit úplnou sadu.
