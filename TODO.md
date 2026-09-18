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
- [x] [completed] **F-M2-SUMMARY-01-B — Lokální summarizer a bezpečný náhled (implemented, 2026-09-18).** `ContextBuilder` váže čitelnou instrukci `summarizer-v1`, přesné artifact nebo seřazené message vstupy, volitelný focus a cílový binding do manifestu/payloadu. `SummaryService` přijímá striktní `fpw-summary-request-v1`, povoluje pouze same-node Ollama a ukládá request, přesný manifest/payload, nejpřísnější privacy i bounded preview do vlastněného node-local `SummaryTasks` journalu; preview nemění projektový Git. `OllamaRuns` zůstává autoritou síťového účinku: pád po úspěšné odpovědi se obnoví bez druhého transportu a `unknown` se automaticky neopakuje. Ověření: cílená sada 22 summary/context/Ollama testů; `py_compile`; kompletní sada po poslední změně 259 testů OK, 22 podmíněně přeskočeno. První sandboxovaný full run selhal pouze na zákazu lokálních socketů; opakování mimo socketový sandbox prošlo.
- [x] [completed] **F-M2-SUMMARY-01-C — Potvrzená publikace, desktop UI a akceptace (PoC validated, 2026-09-18).** Autentizované desktopové API/UI nabízí explicitní výběr 1–64 artefaktů nebo zpráv přiřazeného chatu, volitelný focus, bezpečně vykreslený node-local preview a samostatné potvrzení zápisu. Publikace nejprve fixuje request v task journalu, znovu ověří HEAD, zdroje/message revizi, manifest, preview hash a privacy a přes standardní Workspace/Journal/CAS/index vytvoří jediný Markdown dokument s neměnnou `fpw-summary-v1` obálkou a vztahy `summarizes`. Retry se stejným task/operation ID je idempotentní; testy pokrývají pád před i po posunu refu a po dokončení Workspace, stale HEAD, `unknown`, restart, nejpřísnější privacy, neměnnou provenance a absenci Git zápisu při preview. Ověření po poslední změně: `py_compile`, `node --check`, cílené backend/API/UI/metadata testy a kompletní sada 264 testů OK, 22 podmíněně přeskočeno. Skutečný Qt/WebEngine smoke a živý Ollama model zůstávají prostředím podmíněné a v této sadě nebyly spuštěny.

### Povinné recovery hranice

- LLM dispatch a projektová publikace jsou dvě oddělené operace: neurčitý síťový výsledek se automaticky neopakuje a samotný preview/run nic necommitne.
- Před publikací se znovu ověří projektový HEAD, autorita, přesné vstupy a privacy; journal vlastní přesné výsledné bajty před CAS.
- Po posunu refu recovery pouze dokončí index a receipt; nevytváří další LLM běh, artefakt ani commit.
