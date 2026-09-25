<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-CHAT-DIRECT-01: Přímý brainstormingový dispatch

Milník M3; implementace byla začleněna PR #43 (`32cf743`) do `develop` před
uzavřením akceptace. Dokončení části D proto probíhá na navazující větvi
`feature/f-m3-chat-direct-01-acceptance` s cílem `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [x] [completed]; aktivována 2026-09-20 po začlenění M3-UB-01
  jako PR #42 (`43fc8e3`). Implementační větev
  `feature/f-m3-chat-direct-01` byla začleněna PR #43 (`32cf743`) ještě s
  otevřenou částí D; navazující acceptance větev vznikla z tohoto merge commitu.
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

- [ ] **[planned] D-01 — Demo presenter: Linux gamepad driver patch pro jiný projekt.**
  Příprava stručného přednáškového materiálu a demo flow pro udev/evdev gamepad patch z externího projektu. Výstup: přehled funkce, ukázka klíčových změn, výhody, rizika a návrhy dalšího kroku bez zasahování do aktuálního repozitáře.
  Úroveň: designed.

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
  Příprava runu používá stejnou hodnotu `stream` jako následný dispatch; tím se
  odstranila kolize request digestu, která dříve uzavřela lokální stream bez
  terminální odpovědi ještě před voláním providera. HTTP integrační test navíc
  čte skutečné NDJSON delty i terminální výsledek přes socket a kryje serializaci
  handleru včetně dříve chybějícího runtime importu.
  Cílených 68 OpenAI/chat/desktop/web testů prošlo se 3 Qt skipy, JavaScript
  prošel `node --check`; úplná sada 353 testů prošla s 22 skipy.
- [x] [completed] **F-M3-CHAT-DIRECT-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Automatické regrese pokrývají RBAC/privacy, přesný request
  bez secrets, běžnou i streamovanou odpověď, pořadí skutečných UTF-8 delt,
  restart/idempotenci, stale binding, timeout a přerušený běh jako `unknown`,
  malformed stream jako `failed`, absenci částečné durable odpovědi a vědomý
  nový run bez opakování původního síťového účinku. Uživatel 2026-09-20 živě
  potvrdil desktopový OpenAI stream po opravě přípravy request digestu a NDJSON
  serializace. Živý streamovaný webový smoke nebyl proveden; jeho endpoint,
  administrátorská RBAC hranice a wire formát jsou ověřené integračně.
  Závěrečných 69 cílených testů prošlo se 3 Qt skipy, výsledný JavaScript prošel
  `node --check` a úplná sada 354 testů prošla s 22 environmentálními skipy.

## Předání

Funkce je implementovaná a PoC validovaná. PR #43 obsahuje implementaci;
navazující acceptance diff doplňuje regresní testy a opravuje stavovou evidenci.
Po jeho začlenění přesunout tuto dávku do WORK_LOG a aktivovat jedinou další
dávku z BACKLOG podle pravidel předání.

## Ad-hoc úprava existujícího presenteru — D-02

- [x] [completed] **D-02 — Rozdělení pravého panelu presenteru (implemented).**
  Původ: požadavek uživatele 2026-09-25; pokračování existujícího demo UI
  na větvi `feature/gamepad-demo-presenter`, cíl případného PR `develop`.
  Rozsah: záložky a samostatný náhled dalšího obsahu s poznámkami;
  „K slidu“ používá další hlavní slide, „Backupy“ soukromý výběr backupu.
  Adaptuje existující renderer a presenter controls v `spikes/desktop_ui.py`;
  náhled aktuálního i vybraného slidu sdílí renderování poznámek a vzhled.
  Bez změny persistence či recovery. Akceptace: přepínání obsahu i poznámek,
  prázdný výběr a konec decku, zachování explicitního promítnutí.
  Cílených 16 desktopových testů prošlo se 2 Qt skipy; nový Node.js test
  ověřuje přepínání zdroje náhledu, poznámky a konec decku. Syntaxe JS ověřena.
  Úplná sada: 357 testů, 22 skipů, jediná chyba byla chybějící SPDX
  hlavička v existujícím `docs/gamepad-demo-presenter.md`. Hlavička doplněna
  jako oprava nutná pro ověření presenter větve; následný samostatný
  `python3 -m unittest tests.test_spdx -v` prošel. Po této čistě dokumentační
  opravě nebyla celá sada opakována. `node --check` a `git diff --check` prošly.
  Po dodání obrázku upřesněno rozložení na dva sloupce vedle sebe:
  vlevo záložky a samostatně posouvaný seznam, vpravo náhled a pod ním
  poznámky vyplňující zbývající výšku. Opraven kontrast nadpisů a poznámek
  v bílém panelu. Statický layout ověřen screenshotem headless Chromium
  při 1996 × 1120 s dlouhým seznamem backupů; živé Qt UI není ověřené.
  Finální úplná sada po změně CSS: 357 testů, OK (22 environmentálních
  skipů). `git diff --check` prošel. Historická evidence TODO popisuje jinou
  dávku než existující presenter větev; tato úprava ji administrativně neuzavírá.

- [x] [completed] **D-03 — Backupy přiřazené k aktuálnímu slidu (implemented).**
  Původ: navazující požadavek uživatele 2026-09-25 pro existující presenter
  na větvi `feature/gamepad-demo-presenter`, cíl `develop`.
  Rozsah a akceptace: záložka „K slidu“ ukazuje pouze backupy s explicitním
  `after_slide` odpovídajícím aktuálnímu hlavnímu slidu, aktualizuje se při
  navigaci, podporuje hledání, prázdný stav a soukromý výběr backupu.
  Reuse/adapt: existující pole `after_slide`, společná tvorba položek obou
  seznamů a dosavadní potvrzení promítnutí; bez změny persistence/recovery.
  Cílených 17 desktopových testů prošlo se 2 Qt skipy. Node.js regrese ověřuje
  explicitní vazbu včetně odmítnutí chybějící/null/textové hodnoty, změnu slidu,
  hledání, prázdný seznam a soukromý výběr. `node --check` prošel.
  Úplná sada: 358 testů, OK (22 environmentálních skipů).
  `git diff --check` prošel; živé Qt UI není ověřené.
