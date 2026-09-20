<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — M3-UB-01: Usage & billing backendů

Milník M3; jedna dávka, plánovaná větev `feature/m3-ub-01-usage-billing`,
budoucí PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivována do TODO 2026-09-20 po začlenění
  F-M3-CHAT-MODES-01 jako PR #40 (`c8358d5`). Větev
  `feature/m3-ub-01-usage-billing` vznikla z `develop` na `cae87bc`.
- Původ: sekce 7C roadmapy a M3 požadují volitelný přehled usage a billing pro
  backendy, které tyto údaje skutečně poskytují. Dostupnost konkrétních provider
  API a potřebných oprávnění musí být před implementací ověřena.
- Výstup: provider-neutral kontrakt samostatných capabilities `usage` a
  `billing`, načítání podporovaných údajů a UI indikace jejich rozsahu, období,
  jednotek či měny, stáří a původu.
- Hranice: odlišit údaje jednoho běhu, workspace a celého provider účtu;
  skutečnou hodnotu od odhadu; nulu od chybějící hodnoty. Účetní souhrn nesmí
  být zpřístupněn běžnému uživateli backendu jen proto, že může spouštět model.
- Recovery: před implementací určit obnovování a cache mimo projektový Git.
  Timeout, rate limit, odmítnuté oprávnění nebo zastaralý přehled nesmějí změnit
  routing, cost policy ani stav samotného LLM běhu.
- Mimo rozsah: platby, změny tarifu či limitů, automatický výběr backendu podle
  ceny, nové provider capability, obrazové modely a creator/opponent workflow.

## Aktivní části dávky

- [x] [completed] **M3-UB-01-A — Provider a oprávnění review, kontrakt a reuse
  (designed).** ADR 0008 odděluje capability `usage` a `billing`, normalizuje
  jejich scope/status/období/jednotky a vymezuje
  atomickou node-local cache. Ollama podporuje jen providerem hlášené metriky
  běhu; OpenAI Responses usage zůstává run evidence a organization usage/costs
  používají samostatný admin credential. Provider project se bez ověřeného
  mapování nevydává za workspace a chyba přehledu nemění routing ani run.
- [x] [completed] **M3-UB-01-B — Načítání, cache, autorizace a UI
  (implemented).** Providerem hlášené Ollama/OpenAI run usage se normalizuje
  bez druhého run journalu. Nativní správa používá oddělený write-only OpenAI
  admin credential, bounded stránkování oficiálních usage/costs endpointů a
  atomickou node-local SQLite cache; chyba vrací `stale`, `forbidden` nebo
  `unavailable`, nikoli falešnou nulu. Account přehled není dostupný z běžného
  chatového handleru a UI jej nezaměňuje za workspace údaje. Cílených 70 testů
  prošlo se 2 Qt skipy, úplná sada 344 testů s 22 skipy a skutečný
  Qt/WebEngine smoke prošly; živý OpenAI Admin API refresh nebyl proveden.
- [ ] [planned] **M3-UB-01-C — Regrese, dokumentace a akceptace
  (implemented).** Ověřit obě capabilities, pouze usage a žádnou podporu; nulu
  proti chybějícímu údaji, oprávnění, timeout, rate limit, stale cache, restart
  a to, že výpadek přehledu nemění routing ani běh modelu. Provést úplnou sadu,
  relevantní UI smoke a aktualizovat uživatelskou dokumentaci.

## K předání do backlogu

- [ ] [planned] **F-M3-CHAT-DIRECT-01 — Přímý brainstormingový dispatch,
  historie requestu a streaming (cílová úroveň: PoC validated).** Nový
  uživatelský požadavek 2026-09-20 mění externí brainstormingový chat z
  povinného preview/confirm pro každý tah na přímý dispatch po aplikační
  kontrole oprávnění, privacy, Context Manifestu a přesného bindingu/modelu.
  Historie musí u každého běhu nabídnout bezpečně zobrazitelný přesný odeslaný
  provider request bez credentialu a autorizačních hlaviček; nejde již o
  předběžné potvrzení. Pokud adapter a provider deklarují streamování, UI
  průběžně zobrazuje nedůvěryhodné textové delty, ale autoritativní je až
  validovaná durable finální odpověď. Přerušení po zahájení sítě zůstává
  `unknown` bez automatického retry a bez skrytého fallbacku; provider bez
  stream capability používá dosavadní celou odpověď. Brainstorming nadále
  nepřijímá projektové artefakty ani `local-only` data pro externí model.
  Implementace vyžaduje samostatnou feature větev a změnu ADR 0008; nesmí se
  přimíchat do M3-UB-01.
