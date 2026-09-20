<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — M3-UB-01: Usage & billing backendů

Milník M3; jedna dávka, plánovaná větev `feature/m3-ub-01-usage-billing`,
budoucí PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [planned]; aktivována do TODO 2026-09-20 po začlenění
  F-M3-CHAT-MODES-01 jako PR #40 (`c8358d5`). Implementační větev dosud nebyla
  vytvořena.
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

- [ ] [planned] **M3-UB-01-A — Provider a oprávnění review, kontrakt a reuse
  (designed).** Ověřit aktuálně podporovaná oficiální rozhraní vybraných
  backendů a potřebná oprávnění; navrhnout oddělené usage/billing capability,
  scope, freshness, actual/estimated a unavailable/error stavy. Zaznamenat
  reuse/adapt/reject vůči stávajícím backend bindingům a run usage.
- [ ] [planned] **M3-UB-01-B — Načítání, cache, autorizace a UI
  (implemented).** Implementovat pouze doložené provider větve, bezpečnou
  node-local cache a indikaci bez směšování run/workspace/account údajů.
  Nepodporovaný provider zůstane explicitně bez capability.
- [ ] [planned] **M3-UB-01-C — Regrese, dokumentace a akceptace
  (implemented).** Ověřit obě capabilities, pouze usage a žádnou podporu; nulu
  proti chybějícímu údaji, oprávnění, timeout, rate limit, stale cache, restart
  a to, že výpadek přehledu nemění routing ani běh modelu. Provést úplnou sadu,
  relevantní UI smoke a aktualizovat uživatelskou dokumentaci.
