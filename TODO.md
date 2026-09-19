<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-UX-SETTINGS-01: Centralizovaná stránka nastavení

Milník UX/M2; jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-UX-SETTINGS-01 — Centralizovaná stránka nastavení

- Stav: [x] [completed]; lokálně PoC validated 2026-09-19, čeká commit/push/PR a merge do `develop`.
- Původ: uživatelský požadavek 2026-09-18 přesunout průběžně rostoucí nastavení z pracovních panelů na společnou stránku.
- Skutečná větev: `feature/f-ux-settings-01-central-settings`, založená z `develop` (`e5b5d9d`); jediný budoucí PR do `develop`.
- Výstup: stránka nastavení uzlu dostupná i bez otevřeného projektu; současný Ollama binding se přesune z chatu do sekce lokálního AI backendu, chat nabídne jen stav a odkaz a existující správa uživatelů a federace se otevře ze stejné stránky místo samostatného plovoucího vstupu.
- Mimo rozsah: nový konfigurační formát, synchronizace nastavení, credentials/vault, automatická změna routeru, další backendy a projektová nastavení.
- Recovery: ukládání dál používá validaci a atomické nahrazení `OllamaBindings`; neplatný požadavek ponechá poslední platnou konfiguraci a UI nesmí tvrdit úspěch.
- Akceptace: přístup bez projektu i z chatu; jediný editační formulář; zachování hodnot a bezpečnostních hranic; chybové stavy bez ztráty platné konfigurace; testy API/UI a aktualizovaný návod.

- [x] [completed] **F-UX-SETTINGS-01-A — Informační architektura, hranice stavu a reuse review (designed, 2026-09-19).** ADR 0025 vymezuje samostatnou stránku uzlových nastavení, návratový kontext, jediný Ollama formulář, oddělení node-local stavu od projektu a credentials a zachování stávající serverové validace/atomického zápisu. Reuse review adaptuje existující DOM, autentizované API, `ChatService` a `OllamaBindings`; nová persistence ani knihovna nejsou potřeba.
- [x] [completed] **F-UX-SETTINGS-01-B — Stránka nastavení a přesun uzlových vstupů (implemented, 2026-09-19).** Globální navigace otevírá nastavení bez projektu i z pracovního panelu. Rovnoběžné záložky **AI backend**, **Uživatelé** a **Federace** vykreslují obsah přímo v hlavní ploše bez dialogu či podokna; jediný Ollama formulář používá stávající autentizované API. Desktopový lokální admin kontrakt i webové RBAC zůstávají zachovány. Návrat obnoví původní home/projektový pohled a aktivní pracovní záložku a znovu načte serverový binding. Cílená desktop/API/HTTPS/RBAC sada: 20 testů prošlo a 3 skutečné Qt/WebEngine testy byly podmíněně přeskočeny.
- [x] [completed] **F-UX-SETTINGS-01-C — Regresní ověření a dokumentace (PoC validated, 2026-09-19).** Neplatná rekonfigurace zachová poslední potvrzený binding a UI jej po chybě znovu načte; statický UI kontrakt ověřuje jediný formulář, přímé záložky bez dialogu, návratový kontext, bezpečné DOM a webové role. Návod popisuje AI backend, uživatele, federaci i node-local/credential hranice. Cílená sada: 26 testů OK, 3 podmíněné Qt/WebEngine skipy. Kompletní sada: 284 testů OK, 22 podmíněných skipů. Skutečný průchod nové stránky v Qt/WebEngine zůstává neověřený.
