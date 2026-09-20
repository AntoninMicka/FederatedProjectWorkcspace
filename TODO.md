<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-CHAT-DIRECT-01: Přímý brainstormingový dispatch

Milník M3; jedna dávka, větev `feature/f-m3-chat-direct-01`, budoucí PR do
`develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivována 2026-09-20 po začlenění M3-UB-01
  jako PR #42 (`43fc8e3`). Větev `feature/f-m3-chat-direct-01` vznikla z tohoto
  commitu v `develop`.
- Původ: uživatelský požadavek 2026-09-20, aby brainstorming odesílal požadavek
  přímo, historie nadále ukázala skutečně odeslaný request a providerem
  podporovaná odpověď se zobrazovala streamovaně.
- Výstup: přímý externí brainstormingový dispatch po aplikační autorizaci a
  privacy kontrole, bezpečně zobrazitelná historie přesného provider requestu a
  volitelné streamované UI se stejným durable finálním výsledkem jako
  ne-streamovaný adapter.
- Hranice: brainstorming nepřijímá projektové artefakty ani externě neposílá
  `local-only`; režim/model zůstávají per-run. Historie nesmí vracet credential,
  autorizační hlavičky ani neveřejný interní stav adapteru. Streaming není
  autoritou výsledku a provider bez této capability používá celou odpověď.
- Recovery: `dispatching` musí být durable před prvním síťovým účinkem. Ztráta
  spojení po jeho zahájení zůstává `unknown`, nikdy automatický retry ani skrytý
  fallback. Textové delty jsou dočasné; teprve validovaná finální odpověď se
  uloží do vlákna a run evidence.
- Mimo rozsah: orchestration chat, projektový kontext v brainstormingu,
  creator/opponent workflow, obrazové capability, změna provider billing nebo
  obecná správa a mazání vláken.

## Aktivní části dávky

- [x] [completed] **F-M3-CHAT-DIRECT-01-A — Kontrakt, provider review a reuse
  (designed).** ADR 0008 vymezuje přímý dispatch výhradně pro explicitní
  brainstormingový tah po serverové autorizaci, přesný request record bez
  secrets, SSE capability a durable hranici před sítí. Delty jsou ephemerální,
  finální `response.completed` musí projít dosavadní validací a ztráta streamu
  po `dispatching` zůstává `unknown` bez retry. Dosavadní adapter, run journal,
  Context Manifest, mode policy a vlastnictví vlákna se adaptují; preview store
  zůstává pro task workflow a historické záznamy. Oficiální Responses streaming
  guide byl ověřen 2026-09-20; cizí kód ani nový framework se nepřebírá.
- [x] [completed] **F-M3-CHAT-DIRECT-01-B — Přímý dispatch a historie requestu
  (implemented).** Explicitní externí brainstorming používá nový přímý endpoint
  nad stejným Context Manifestem, binding hashem, durable dispatch záznamem a
  OpenAI run journalem jako dosavadní potvrzený tok. Request body bez hlaviček a
  credentialu se váže na run ID a vlastník jej může rozbalit u odpovědi i po
  restartu. Lookup před opětovnou přípravou zajišťuje idempotentní retry bez
  druhého síťového účinku. Task a pokročilé preview/confirm zůstaly zachované.
  Web endpoint je do oddělení identity chat store od procesní desktop identity
  fail-closed omezený na administrátora; běžný webový člen dostane 403.
  Cílených 53 chat/OpenAI/UI/HTTPS testů prošlo se 2 Qt skipy.
- [x] [completed] **F-M3-CHAT-DIRECT-01-C — Volitelné streamované zobrazení
  (implemented).** Capability-gated Responses SSE transport a desktopové i
  webové UI zobrazují textové delty průběžně; provider bez deklarované podpory
  zachovává ne-streamovaný fallback. Dílčí text je pouze dočasný a durable chat
  dostane až validovanou finální odpověď. Chybná událost skončí jako `failed`,
  timeout, přerušení nebo zavření klienta jako `unknown`, bez částečné
  asistentovy zprávy. Webový endpoint zachovává administrátorskou RBAC hranici.
  Cílených 67 OpenAI/chat/desktop/web testů prošlo se 3 Qt skipy, JavaScript
  prošel `node --check`; úplná sada 352 testů prošla s 22 skipy.
- [ ] [planned] **F-M3-CHAT-DIRECT-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Ověřit RBAC/privacy, přesný request bez secrets, běžnou i
  streamovanou odpověď, pořadí a UTF-8 delt, reconnect/restart, stale binding,
  timeout, malformed stream, lost response `unknown`, vědomý nový pokus a
  desktop/web UI. Spustit úplnou sadu a relevantní skutečný UI/provider smoke;
  neprovedené živé ověření ponechat výslovně otevřené.
