<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-PUBLIC-SOURCE-READER-01

Feature dávka **F-M3-PUBLIC-SOURCE-READER-01 — bounded statický reader
veřejného zdroje** navazuje na designed `F-M3-PUBLIC-SOURCES-01`, doručené do
`develop` PR #70 jako commit `225ea01`. Aktivní větev je
`feature/f-m3-public-source-reader-01`, základ i cíl PR je `develop`. Cílová
úroveň: **implemented → PoC validated**.

Rozsah tvoří společná obálka `public-source-fetch-v1`, samostatný node-local
`PublicSourceRuns` journal, SSRF-safe HTTPS transport a jediný adaptér
`static-html-v1` pro jednu uživatelem vybranou URL z výsledků SearXNG. Fetch
nevytváří projektový artefakt; případná publikace zůstává samostatnou budoucí
Workspace operací. Mimo rozsah jsou crawler, JavaScriptový renderer, login,
cookies, automatické redirecty, PDF/binární parsery a strukturované providerové
adaptéry.

Crash hranice: `prepared → dispatching → succeeded|unsupported|rejected|failed|unknown`.
Před `dispatching` nenastal síťový účinek. Přerušené `dispatching` je po
restartu `unknown` a bez nového potvrzení se neopakuje. Úspěšné raw a textové
bajty se nejprve fsyncnou do run-scoped node-local stagingu a až poté se
atomicky uzavře SQLite stav. Chybějící či hashově neshodný staging se nevydává
za použitelný výsledek a nestahuje se potichu znovu.

- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-A — kontrakt, journal a
  staging (cílová úroveň: implemented).** Implementovat validovaný binding,
  request/preview digest, durable výsledky, oddělený journal, atomické fsync
  staging bajty a recovery bez automatického retry. Implementováno v
  `spikes/public_source.py`; po restartu se neurčité `dispatching` uzavírá jako
  `unknown`, úspěch se vydá jen proti ověřenému staging hashi.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-B — SSRF-safe HTTPS a robots
  (cílová úroveň: implemented).** Validovat veřejné A/AAAA adresy, připnout
  connect k ověřené adrese se zachováním hostname/SNI, zakázat redirecty a
  uplatnit TLS, robots, timeout, MIME, charset, wire/decoded a kompresní limity.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-C — statická projekce a Context
  Manifest (cílová úroveň: implemented).** Inertně projektovat povolený HTML
  nebo text, nic dalšího nestahovat, zachovat přesné hashe/provenance a nabídnout
  výsledek jako explicitní nedůvěryhodný vstup Context Manifestu bez zápisu do
  projektu.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-D — výběr výsledku, UI a
  diagnostika (cílová úroveň: implemented).** Nad konkrétním SearXNG výsledkem
  zobrazit přesný fetch plán, dva možné GET účinky, privacy, limity a potvrzení;
  vykreslit bounded text a odlišit `unsupported`, `rejected`, `failed` a
  `unknown`. Statický a API kontrakt je ověřen automaticky; fyzický průchod je
  součástí položky E.
- [ ] [blocked] **F-M3-PUBLIC-SOURCE-READER-01-E — automatické a fyzické
  ověření (cílová úroveň: PoC validated).** Pokrýt DNS rebinding, smíšené DNS,
  redirect na interní/jiný origin, TLS/timeout/429/503, lživou délku,
  kompresní limity, MIME/charset, malformed/deep HTML, robots stavy, prompt
  injection jako data, restart ve všech stavech, stale binding/HEAD a dva
  nezávislé veřejné statické weby; dynamický web skončí `unsupported`.

  Automatické ověření 2026-10-17: cílená sada reader/context/chat/UI/package
  prošla (36 testů, 1 volitelný packaged-WebEngine test přeskočen); celá sada
  `python3 -m unittest discover -s tests -v` prošla 631 testy, 27 volitelných
  testů bylo přeskočeno. Živý explicitní smoke uspěl na `https://example.com/`
  a `https://www.rfc-editor.org/rfc/rfc9309.html`; `https://app.element.io/`
  skončilo očekávaně `unsupported/no-static-text`. Zbývá fyzicky potvrdit
  desktopový preview/cancel/confirm/restart průchod nad SearXNG výsledkem podle
  `docs/public-source-reader-acceptance.md`. Fyzická akceptace je pozastavena,
  protože implicitní modelové routování nyní nespolehlivě volí prezentaci i pro
  jiné záměry. Odblokuje ji samostatná stacked dávka
  `F-M3-EXPLICIT-TASK-ROUTING-01`; po jejím ověření se reader dokončí na této
  větvi a obě feature se doručí odděleně v pořadí reader → routing.

Akceptace dávky vyžaduje cílené testy, celou současnou testovací sadu,
`git diff --check`, kontrolu dokumentace a fyzický průchod popsaný v ADR 0033.
