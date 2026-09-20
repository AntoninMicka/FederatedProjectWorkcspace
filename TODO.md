<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-CHAT-MODES-01: Lokální orchestrace a brainstormingové režimy

Milník M3; jedna dávka, větev `feature/f-m3-chat-modes`, budoucí PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; implementace a lokální akceptace jsou hotové,
  dávka čeká na uživatelem řízený commit/push/PR/merge. Aktivováno 2026-09-20 na přímý požadavek
  uživatele z `develop` po ověření, že F-M1-PROJECT-ROOT-01 je začleněn jako
  PR #39 (`4bd45b8`).
- Původ: uživatel požaduje režim `orchestration` pouze s lokálním `same-node`
  LLM a explicitním artefaktovým kontextem; režim `brainstorming` s volbou
  policy-povoleného backendu/modelu s explicitně připraveným textovým kontextem,
  ale bez artefaktového kontextu. Návrat do
  orchestrace ukončí brainstormingové vlákno a založí nové bez jeho kontextu.
- Výstup: verzovaný turn/thread kontrakt a desktopové ovládání režimu/modelu;
  lokální orchestrace pro přípravu kontextu/dat, filtraci a návrhy artefaktů;
  brainstormingový běh s explicitně připraveným textovým kontextem, ale bez
  přímých či odvozených artifact inputs.
- Recovery: změna režimu nesmí proběhnout s aktivním nebo `unknown` během.
  Ukončení brainstormu a archivace původního vlákna spolu se založením nového
  orchestration vlákna musí být obnovitelné a idempotentní; žádná zpráva,
  artefakt ani binding se nepřenese implicitně. Každý běh má nový Context
  Manifest a před dispatch znovu ověří privacy, policy a cílový binding.
- Mimo rozsah: workflow opponent/creator, automatické provádění LLM návrhů,
  obecné mazání vláken F-M2-CHAT-03, federovaný lidský chat, nové externí
  providery, usage/billing a automatický fallback.

## Aktivní části dávky

- [x] [completed] **F-M3-CHAT-MODES-01-A — Kontrakt, reuse a crash hranice
  (designed).** `ChatThreads` v3, `ChatRunChoice`, stávající bindingy a
  ContextBuilder vymezují režim, per-run model, oddělené textové/projektové
  vstupy a atomický návrat do orchestrace. Odvozený binding nemění globální
  konfiguraci a recovery nesmí použít později změněný základní binding.
- [x] [completed] **F-M3-CHAT-MODES-01-B — Režimy, modelový výběr a UI
  (implemented).** Orchestrace vynucuje nakonfigurovaný same-node model a
  explicitní artefakty; brainstorming přijímá jen text/zprávy, volí per-run
  Ollama/OpenAI model a externí běh vede přes preview/confirm. Návrat atomicky
  archivuje brainstorming a zakládá prázdnou orchestrace bez přenosu kontextu.
- [x] [completed] **F-M3-CHAT-MODES-01-C — Regrese, dokumentace a akceptace
  (PoC validated).** Cílených 52 testů prošlo se 2 podmíněnými Qt skipy;
  úplná sada 340 testů prošla s 22 skipy v povoleném lokálním prostředí. Samostatný skutečný
  Qt/WebEngine smoke prošel a ověřil přepnutí obou režimů. JavaScript syntaxe,
  Python kompilace a `git diff --check` prošly. Integrační testy pokrývají
  privacy/boundary, zákaz artefaktů v brainstormingu, per-run lokální i OpenAI
  model, preview/confirm, stale/unknown, restart a zákaz přímého externího
  dispatch; živý externí provider nebyl v této dávce znovu volán.
