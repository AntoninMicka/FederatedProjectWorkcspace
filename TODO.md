<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-CHAT-MODES-01: Lokální orchestrace a brainstormingové režimy

Milník M3; jedna dávka, větev `feature/f-m3-chat-modes`, budoucí PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivováno 2026-09-20 na přímý požadavek
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

- [ ] [in progress] **F-M3-CHAT-MODES-01-A — Kontrakt, reuse a crash hranice
  (designed).** Prověřit `ChatThreads`, `ChatService`, backend bindings,
  ContextBuilder a desktop UI; určit migraci thread/turn evidence, režimovou
  policy a přesné recovery hranice bez nové autority úložiště.
- [ ] [planned] **F-M3-CHAT-MODES-01-B — Režimy, modelový výběr a UI
  (implemented).** Vynutit same-node orchestration, artifact-free brainstorming,
  explicitní výběr modelu jen pro brainstorming a ukončení/archivaci před
  založením nového orchestration vlákna.
- [ ] [planned] **F-M3-CHAT-MODES-01-C — Regrese, dokumentace a akceptace
  (PoC validated).** Ověřit privacy/boundary, stale/unknown/retry, restart na
  persistentních hranicích, neexistenci implicitního kontextu i skutečný
  Qt/WebEngine průchod.
