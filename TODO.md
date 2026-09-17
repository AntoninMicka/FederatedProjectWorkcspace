<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-CONTEXT-01: Bezpečný Context Builder

Milník M2; Gate M1 zůstává otevřený kvůli odložené cílové restartové akceptaci M1-07. Tato dávka je na ní implementačně nezávislá. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M2-CONTEXT-01 — Bezpečný Context Builder

- Stav: [x] [completed]; lokálně PoC validated 2026-09-17, PR dosud není vytvořen ani sloučen.
- Původ: Context Builder část M2 a kontrakt [ADR 0008](docs/adr/0008-context-and-publication-contracts.md).
- Skutečná větev: `feature/f-m2-context-01-manifest`, založená z `develop` (`7d985c4`); jediný budoucí PR do `develop`.
- Výstup: explicitní výběr projektových a neměnných ad-hoc vstupů, Context Manifest přesných bajtů a revalidace identity, HEAD, privacy, oprávnění, bindingu a cíle bezprostředně před předáním backendu.
- Mimo rozsah: Ollama či jiný backend adapter, skutečné síťové odeslání, automatické souhrny, billing, role orchestrace a publikace výsledku.
- Závislosti: implementované projektové čtení/validace M1 a návrhový kontrakt ADR 0008. Odložený reboot M1-07 nemění Context Builder; Gate M1 se touto výjimkou neuzavírá.
- Akceptace: exact bytes/digests, deterministické pořadí a limity; změna HEAD, identity/session, oprávnění, policy, bindingu nebo cíle mezi přípravou a autorizací se odmítne; `local-only` neopustí `same-node`; chybějící povinný vstup a implicitní fallback se odmítnou; volitelné vynechání je viditelné; testy chybových cest a dokumentace.

- [x] [completed] **F-M2-CONTEXT-01-A — Striktní kontrakt manifestu a builder (implemented, 2026-09-17).** Verzovaný omezený kontrakt fixuje explicitně zvolené projektové a ad-hoc bajty, SHA-256, velikost, privacy, commit, autoritu, policy a přesný binding/cíl v kanonickém manifestu a payloadu.
- [x] [completed] **F-M2-CONTEXT-01-B — Autorizační revalidace a dispatch handoff (implemented, 2026-09-17).** `prepare` a `authorize_for_dispatch` jsou oddělené; druhá fáze pod společným writer lockem kontroluje session/uživatele/uzel, HEAD, čtecí práva, policy, binding/cíl, privacy a přesné bajty. Výstup je pouze backendově neutrální handoff, nikoli síťové odeslání.
- [x] [completed] **F-M2-CONTEXT-01-C — Chybové scénáře, dokumentace a závěrečné ověření (PoC validated lokálně, 2026-09-17).** Cílené 4 testy prošly. Celá sada mimo socketový sandbox: 220 testů OK, 22 podmíněných skipů. První běh uvnitř sandboxu měl 20 očekávaných `PermissionError` chyb při vytvoření HTTP/HTTPS/Unix socketu; nejde o aplikační regresi. ADR 0008 a reuse evidence jsou aktualizované.

### Recovery hranice

- Builder je v této dávce read-only. Připravený manifest a snapshot jsou neměnný lokální objekt; samotný hash bez bajtů není dostačující.
- `prepare` nesmí nic odeslat. `authorize_for_dispatch` znovu ověří aktuální stav a vrátí pouze krátkodobý autorizovaný handoff přesně stejných bajtů.
- Skutečný backend adapter, trvalý run record, stav `dispatching/unknown` a placený síťový účinek patří do navazující dávky; nesmí být předstírány tímto PoC.
