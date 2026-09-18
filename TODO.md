<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-EXTRACT-01: Lokální strukturovaná extrakce

Milník M2; jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M2-EXTRACT-01 — Lokální strukturovaná extrakce

- Stav: [x] [completed]; PoC validated 2026-09-19, čeká samostatný commit/push/PR a merge do `develop`.
- Původ: roadmapa M2 „Extractor“, sekce 8 a bezpečný Context Builder/LLM kontrakt ADR 0008; navazuje na F-M2-SUMMARY-01 začleněný PR #31.
- Skutečná větev: `feature/f-m2-extract-01-structured-extraction`, založená z `develop` (`3059dbb`); jediný budoucí PR do `develop`.
- Výstup: uživatelem vyžádaná lokální extrakce z explicitně vybraných artefaktů nebo zpráv do jednoho předem zvoleného podporovaného schématu; striktně validovaný náhled a teprve po potvrzení verzovaný projektový artefakt.
- Mimo rozsah: uživatelem dodané libovolné JSON Schema, automatická volba zdrojů/schématu, background extrakce, externí provider, RAG/embeddings, popisy a štítky.
- Recovery: LLM run, durable preview a projektová publikace zůstávají oddělené; `unknown` se neopakuje, nevalidní modelový JSON se nepublikuje a stejný task/operation ID nesmí vytvořit druhý běh, artefakt ani commit.
- Akceptace: přesný výběr/HEAD/privacy/cíl a schema ID/revize v manifestu; odmítnutí neplatného či neočekávaného JSON a chybějících polí; source references a nejpřísnější privacy; stale/unknown/restart/retry; pád před i po publikaci; bezpečné desktopové vykreslení bez aktivního obsahu.

- [x] [completed] **F-M2-EXTRACT-01-A — Kontrakt schémat, validace a reuse review (designed, 2026-09-19).** ADR 0008 definuje uzavřený katalog `facts-v1`/`action-items-v1`, striktní pole a limity, source reference pouze do explicitního výběru, kanonický preview, neměnný `fpw-extraction-v1` source artefakt a oddělené síťové/task/Workspace recovery. Reuse rozhodnutí adaptuje ContextBuilder, Ollama lifecycle, Workspace, omezený JSON parser a vzor SummaryTasks bez externího schema frameworku či převzetí nedoloženého klienta.
- [x] [completed] **F-M2-EXTRACT-01-B — Lokální extractor a durable validovaný preview (implemented, 2026-09-19).** Verzovaná role/instrukce používá same-node dispatch a oddělený node-local task store; striktní parser kanonizuje pouze podporovaný JSON, kontroluje všechna pole i source reference a nevalidní/neurčitý běh nelze vydávat ani automaticky opakovat. Restart vrací durable preview bez nového dispatch a bez zápisu do projektu.
- [x] [completed] **F-M2-EXTRACT-01-C — Potvrzená publikace, desktop UI a akceptace (PoC validated, 2026-09-19).** Explicitní volba schématu a podkladů, bezpečný JSON preview a potvrzená recovery-safe publikace zachovávají provenance, `derived-from` vztahy a nejpřísnější privacy. Invalidní JSON, autentizované API, restart/retry, stale HEAD a pády před/po refu i po Workspace commitu prošly; kompletní sada po implementaci: 274 testů, 22 přeskočeno kvůli opt-in nativním/WebEngine/libgit2/deployment podmínkám. Živý Ollama a skutečný Qt/WebEngine průchod v této dávce spuštěny nebyly.

### Následující dávky po samostatném merge

- `F-M2-META-AI-01` — návrhy popisu a štítků.
- `F-UX-SETTINGS-01` — centralizovaná stránka nastavení.
