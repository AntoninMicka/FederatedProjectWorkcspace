<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-AUTONOMY-01 — Obecná řízená autonomie orchestrace

Původ: roadmapa a [BACKLOG](BACKLOG.md), uživatelem schváleno 23. 10. 2026.
Milník M4, cílová úroveň **designed → implemented → PoC validated**. Větev
`feature/f-m4-autonomy-01` vznikla z `develop` `8ed574f`; cílem je jediný PR do
`develop`.

Předchozí `UX-WEB-NAV-01` byl před aktivací této dávky administrativně uzavřen:
PR #84 je v `develop` jako `8ed574f` a evidence zůstává ve
[WORK_LOG](WORK_LOG.md#ux-web-nav-01--webové-kategorie-výstupy-a-federace--2026-10-23).

## Rozsah a hranice

Společný fail-closed action registry a node-local durable fronta dovolí pro
konkrétní workflow explicitně zvolit ruční nebo bounded automatický režim.
LLM smí pouze navrhovat plán; autorizaci, budget, pořadí a dispatch řídí
deterministická aplikace. `F-M3-SEARCH-03`, nový provider, message queue a
obecný agent framework nejsou součástí dávky.

Každé vytvoření uživatelsky adresovatelného lokálního souboru, dokumentu nebo
artefaktu vyžaduje samostatné explicitní schválení přesného cíle, typu,
obsahu/hash, privacy a provenance. Countdown ani automatický režim jej nikdy
nenahrazují. Existující přísnější potvrzení změn, publikace, odeslání či mazání
zůstávají v platnosti.

## Úkoly

- [x] [completed] **F-M4-AUTONOMY-01-A — Action registry a policy kontrakt
  (implemented).** Uzavřeně deklaruje typ účinku,
  oprávnění, privacy, vstupy, budget, automatizovatelnost a požadované
  potvrzení; neznámá akce a nedůvěryhodný planner návrh selžou fail-closed.
  Přesný plán, režim a budget navíc vyžadují samostatný opt-in digest; samotné
  plannerem navržené `automatic` nic neaktivuje. Kontrakt a recovery popisuje
  [ADR 0044](docs/adr/0044-governed-orchestration-autonomy.md).
- [x] [completed] **F-M4-AUTONOMY-01-B — Durable bounded fronta a recovery
  (implemented).** Node-local journal pokrývá
  ruční/automatický režim,
  viditelný stav a mezivýsledky, pause/resume/cancel, limity kroků/času/nákladů,
  souběžná workflow, owner-filtered bounded výpis a zákaz automatického retry
  neurčitého účinku. Restart odpojí UI, pozastaví bezpečně obnovitelné kroky a
  změní rozpracovaný dispatch na terminální `unknown`.
- [x] [completed] **F-M4-AUTONOMY-01-C — Integrační service a approval boundary
  (implemented).** Deterministicky autorizuje registrované
  adaptéry pro read-only analýzu, externí dotaz a rolový handoff; návrh
  lokálního výstupu vždy zastaví na přesném lidském checkpointu. Adaptéry
  používají existující externí, role-workflow a publikační journal; web navíc
  fail-closed skrývá a odmítá `local-only` plány.
- [ ] [in progress] **F-M4-AUTONOMY-01-D — UI, regrese a akceptace (cílová úroveň:
  PoC validated).** Zobrazit frontu, budget, mezivýsledky a globální pauzu;
  ověřit editaci plánu, změny oprávnění/privacy, vyčerpaný budget, neznámou
  akci, odpojení UI, restart v každém stavu, souběh a `unknown` bez auto-retry.

## Crash boundaries

Projektový Git zůstává autoritou pouze potvrzených projektových zápisů.
Action registry je statický kód/konfigurace; node-local SQLite journal je
autoritou fronty a rozpracovaných dispatchů, nikoli obnovitelným projektovým
indexem. Před dispatch se znovu ověří policy, přesné vstupy a budget. Pád před
dispatch lze bezpečně obnovit jako pozastavený; pád během účinku musí skončit
`unknown` bez automatického opakování. Lokální obsah se vytváří až samostatnou
existující zapisovací operací po konkrétním approval.

## Akceptace

- Kombinovaný workflow projde povolenými read-only/externími/handoff kroky,
  ale před každým lokálním výstupem se vždy zastaví.
- Ruční i bounded automatický režim zůstávají opt-in, auditovatelné a po ztrátě
  UI či restartu fail-closed pozastavené.
- Cílené testy, úplná sada `python3 -m unittest discover -s tests -v`, relevantní
  statické kontroly a `git diff --check` projdou; omezení budou zdokumentována.

## Průběžné ověření — 2026-10-23

- `tests.test_action_autonomy`: **15 testů OK** — registry, explicitní opt-in,
  kombinovaný workflow, manuální režim, přesný lokální checkpoint, změny
  oprávnění/privacy/HEAD, globální pause, odpojení UI, editace, souběh, restart
  návrhu/approval/`dispatching`, migraci journalu, backendový countdown a lease,
  časový budget, cancel a `unknown` bez retry.
- `tests.test_autonomy_service`: **6 testů OK** — konkrétní doménové adaptéry,
  stale HEAD, přesný lokální výstup, `local-only` webová hranice, editace plánu
  a desktop API/UI kontrakt. Dva cílené HTTPS webové testy také prošly.
- Úplná sada `python3 -m unittest discover -s tests -v`: **772 testů OK,
  28 volitelných testů přeskočeno**. `py_compile`, kontrola generovaného JS přes
  `node --check` a `git diff --check` prošly.
- Sdílené UI nyní zobrazuje/importuje a před účinkem edituje návrh, vyžaduje
  samostatnou aktivaci, ukazuje budget/stavy/výsledky, drží krátký lease,
  provádí countdown a nabízí pause/resume/cancel i globální pauzu. Fyzická
  desktop/web akceptace v reálném prohlížeči ještě zbývá; dávka zůstává otevřená.
