<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-SUMMARY-01: Lokální projektové souhrny

Milník M2; Gate M1 zůstává otevřený kvůli odložené cílové restartové akceptaci M1-07. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M2-SUMMARY-01 — Lokální projektové souhrny

- Stav: [ ] [in progress]; cílová úroveň PoC validated.
- Původ: roadmapa M2 „Summarizer“, sekce 8 a bezpečný Context Builder/LLM kontrakt ADR 0008.
- Skutečná větev: `feature/f-m2-summary-01-local-summaries`, založená z `develop` (`db4917e`, F-M2-CHAT-02 začleněn PR #30); jediný budoucí PR do `develop`.
- Výstup: uživatelem vyžádaný lokální souhrn explicitně vybraných projektových artefaktů nebo zpráv, nejprve jako náhled a teprve po potvrzení jako verzovaný Markdown dokument s přesnou provenance a privacy.
- Mimo rozsah: automatické přepisování zdrojů, background summarizace, externí provider, embeddings/RAG, extractor, auto-description, tagging a obecný multi-role workflow.
- Závislosti: F-M2-CONTEXT-01, F-M2-OLLAMA-01, F-M2-CHAT-01 a F-M2-CHAT-02 jsou začleněné PR #26, #27, #29 a #30; publikace použije standardní Workspace/Journal/Git/index lifecycle.
- Akceptace: explicitní výběr a Context Manifest vážou přesné vstupy/HEAD/privacy/cíl; preview nic nezapisuje; potvrzená publikace zachová source/message/run/manifest provenance a nejpřísnější privacy; stale HEAD, nepovolený nebo změněný vstup, local-only mimo same-node, unknown běh, retry a pád před/po CAS selžou či se obnoví bez duplicitní externí akce nebo artefaktu.

- [x] [completed] **F-M2-SUMMARY-01-A — Kontrakt souhrnu a reuse review (designed, 2026-09-18).** ADR 0008 definuje `fpw-summary-request-v1`, výhradní artifact nebo thread/message selection, roli `summarizer-v1`, limity, node-local task/preview journal, oddělený durable Ollama run, explicitní publish potvrzení, `fpw-summary-v1`, nejpřísnější privacy a recovery přes task journal + Workspace. Reuse review adaptuje ContextBuilder, Ollama lifecycle, SQLite vzor ChatThreads a Markdown/Workspace publikaci; odmítá skrytou volbu zdrojů, RAG, vektorovou DB, message queue i nedoložený externí backendový kód.
- [ ] [planned] **F-M2-SUMMARY-01-B — Lokální summarizer a bezpečný náhled (cílová úroveň: implemented).** Implementovat backendově neutrální přípravu role `summarizer`, autorizovaný same-node Ollama dispatch a node-local durable run/preview bez automatického zápisu do projektu.
- [ ] [planned] **F-M2-SUMMARY-01-C — Potvrzená publikace, desktop UI a akceptace (cílová úroveň: PoC validated).** Přidat výběr vstupů, preview a explicitní uložení Markdown souhrnu přes expected HEAD/Journal/CAS/index; ověřit restart, stale/unknown, privacy, idempotentní retry, recovery a bezpečné vykreslení.

### Povinné recovery hranice

- LLM dispatch a projektová publikace jsou dvě oddělené operace: neurčitý síťový výsledek se automaticky neopakuje a samotný preview/run nic necommitne.
- Před publikací se znovu ověří projektový HEAD, autorita, přesné vstupy a privacy; journal vlastní přesné výsledné bajty před CAS.
- Po posunu refu recovery pouze dokončí index a receipt; nevytváří další LLM běh, artefakt ani commit.
