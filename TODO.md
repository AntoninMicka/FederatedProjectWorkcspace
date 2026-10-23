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
- [ ] [in progress] **F-M4-AUTONOMY-01-B — Durable bounded fronta a recovery
  (cílová úroveň: implemented).** Implementovaný node-local journal už pokrývá
  ruční/automatický režim,
  viditelný stav a mezivýsledky, pause/resume/cancel, limity kroků/času/nákladů,
  souběžná workflow a zákaz automatického retry neurčitého účinku. Zbývá
  doplnit test vyčerpaného časového budgetu, cancel/restart všech stavů a
  bezpečný výpis více workflow pro UI.
- [ ] [planned] **F-M4-AUTONOMY-01-C — Integrační service a approval boundary
  (cílová úroveň: implemented).** Deterministicky autorizovat registrované
  adaptéry pro read-only analýzu, externí dotaz a rolový handoff; návrh
  lokálního výstupu vždy zastavit na přesném lidském checkpointu.
- [ ] [planned] **F-M4-AUTONOMY-01-D — UI, regrese a akceptace (cílová úroveň:
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

- `tests.test_action_autonomy`: **10 testů OK** — registry, explicitní opt-in,
  kombinovaný workflow, manuální režim, přesný lokální checkpoint, změny
  oprávnění/privacy/HEAD, globální pause, odpojení UI, editace, souběh, restart
  v `dispatching` a `unknown` bez retry.
- Související regresní sada `test_action_autonomy`, `test_output_capabilities`,
  `test_output_execution`, `test_role_workflow_service` mimo socketově omezený
  sandbox: **35 testů OK, 1 volitelný live test přeskočen**.
- `py_compile` nového modulu a testu prošel. Úplná sada ani UI/integration
  akceptace zatím spuštěné nebyly; dávka zůstává otevřená.
