<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-CHAT-01: Lokálně perzistentní živé konverzace

Milník M2; Gate M1 zůstává otevřený kvůli odložené cílové restartové akceptaci M1-07. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M2-CHAT-01 — Lokálně perzistentní živé konverzace

- Stav: [ ] [in progress]; cílová úroveň PoC validated.
- Původ: uživatelské doplnění plánu 2026-09-15; volitelný orchestrator chat a LLM run records z ADR 0008.
- Skutečná větev: `feature/f-m2-chat-01-local-threads`, založená z `develop` (`a6dfbf6`, PR #28 začleněn); jediný budoucí PR do `develop`.
- Výstup: backendově nezávislé vícekolové vlákno, lokální trvalé uložení a bezpečné navázání po restartu; samostatný chat má výchozí klasifikaci `brainstorming`.
- Mimo rozsah: projektová publikace, full/delta otisky, federovaná synchronizace vláken a automatické provádění navržených akcí.
- Závislosti: F-M2-CONTEXT-01 a F-M2-OLLAMA-01 jsou začleněné v `develop`; vlákno, backendové run records a projektový index zůstávají oddělené.
- Akceptace: po pádu je rozlišen poslední potvrzený obsah od draftu a `unknown` běhu; navázání explicitně manifestuje vybrané zprávy; změna backendu/modelu/boundary je viditelná a nevyvolá tichý fallback. Testy pokrývají restart v každém trvalém přechodu, poškozený stav, souběh a oddělení uživatelů i projektových kontextů.

- [x] [completed] **F-M2-CHAT-01-A — Thread/Message kontrakt, retence a crash boundaries (designed, 2026-09-18).** ADR 0008 odděluje autoritativní node-local vlákno, neměnné zprávy, UI draft, turn a backendový run; určuje pořadí, privacy, manifest výběr, explicitní retenci a obnovu před/po dispatchi bez duplicitního odeslání.
- [x] [completed] **F-M2-CHAT-01-B — Lokální thread store a recovery (implemented, 2026-09-18).** `ChatThreads` je samostatná node-local SQLite autorita se striktním v1 schématem, vlastnictvím node/user, neměnnými hashovanými zprávami, transakčním pořadím, turn/run vazbou, idempotentní reconciliation a explicitními terminal states. Šest cílených testů pokrývá restart, rollback před všemi třemi commity, souběh, oddělení vlastníků, limity, archivaci, unsafe/poškozený stav a neznámé schéma; celá sada prošla 237 testy (22 přeskočeno).
- [x] [completed] **F-M2-CHAT-01-C — Context/adapter napojení a desktop UI (PoC validated, 2026-09-18).** `ChatService` propojuje přesný projektový HEAD, explicitně seřazené message UUID a jejich bajty s Context Manifestem, trvalým Ollama runem a přesným bindingem bez fallbacku. Manifest nese thread ID/revizi/výběr a služba před autorizací znovu ověří nezměněné vlákno. Autentizované same-origin API a desktop načítají vlákna po restartu, konfigurují same-node nebo připnutý private-network backend a zachovávají `failed`/`unknown` bez assistant zprávy či automatického opakování. Cílených 32 testů prošlo (2 opt-in přeskočeny), celá sada prošla 244 testy (22 přeskočeno) a samostatný reálný Qt/WebEngine test otevření projektu/restartu prošel. Skutečné volání běžící Ollamy a reálný LAN TLS endpoint nebyly součástí automatického ověření.

### Recovery hranice

- Uživatelská zpráva a připravený turn se potvrdí v thread store před vytvořením backendového runu; bez run recordu nebyl dispatch zahájen.
- Run ID se k turnu připne před dispatch; po restartu se jeho durable stav načte z backendového run store. `dispatching`/`unknown` se automaticky neopakuje.
- Assistant zpráva a dokončení turnu se zapíší jednou transakcí až z durable úspěšného výsledku; opakovaná reconciliation nesmí vytvořit druhou zprávu.
