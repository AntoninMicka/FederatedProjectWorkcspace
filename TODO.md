<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-PUBLIC-SOURCE-READER-02 — strukturovaná čitelná projekce

Původ: uživatelské zjištění při akceptaci `F-M3-SEARCH-03`, převzato se
stejným ID z [BACKLOG](BACKLOG.md). Milník M3, cílová úroveň
**implemented → PoC validated**. Větev
`feature/f-m3-public-source-reader-02-structured-projection` vznikla z
`develop` `6d12902`; cílem je jediný PR do `develop`.

Předchozí dávka `F-M3-SEARCH-03` byla doručena PR #86 jako merge commit
`6d12902`; její evidence zůstává ve
[WORK_LOG](WORK_LOG.md#f-m3-search-03--volitelný-automatický-dispatch-hledání--2026-10-24).

## Rozsah a hranice

Nad existujícím `PublicSourceRuns` a explicitním `static-html-v1` přidat
verzovanou strukturovanou projekci, která zachová dokumentové pořadí,
nadpisovou cestu a typ obsahového bloku. Sdílené desktop/web UI musí zobrazit
čitelný výtah a umožnit kontrolu proti původnímu bounded textu bez interpretace
nedůvěryhodného HTML.

Dávka nemění SSRF, DNS, TLS, robots, redirect, MIME, charset, wire/decoded,
časové ani privacy hranice ADR 0033. Nestahuje další odkazy, nespouští
JavaScript, nezavádí crawler/headless browser a sama nepublikuje obsah do
projektového Gitu. Raw bajty, stávající text a jejich hashe zůstávají
auditovatelné; nová projekce nesmí změnit recovery autoritu fetch runu.

## Úkoly

- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-02-A — parser a reuse kontrakt
  (cílová úroveň: designed).** Prověřit současný HTML parser, serializaci
  `PublicSourceResult`, Context Manifest a oba UI renderery. Navrhnout uzavřené
  schéma bloků, stabilní source anchors, limity a kompatibilitu se starými
  runy. Zaznamenat reuse/adapt/reject a crash hranice bez druhého fetch
  journalu.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-02-B — strukturovaná projekce
  (cílová úroveň: implemented).** Deterministicky projektovat title, nadpisy,
  odstavce, seznamy a tabulky v dokumentovém pořadí, zachovat heading path a
  bounded stabilní anchor. Navigační/skriptový balast nesmí promíchat obsah;
  neznámá nebo příliš složitá struktura musí degradovat viditelně a
  deterministicky.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-02-C — čitelné sdílené UI a
  provenance (cílová úroveň: implemented).** Zobrazit strukturované bloky jako
  inertní text s jasnou hierarchií a nabídnout kontrolní původní text. Context
  Manifest a výstup musí vázat verzi projekce, anchor a hashe bez nového
  automatického fetch nebo Git zápisu.
- [ ] [in progress] **F-M3-PUBLIC-SOURCE-READER-02-D — regrese a fyzická akceptace
  (cílová úroveň: PoC validated).** Pokrýt realistické články, vnořené sekce,
  seznamy, tabulky, navigační balast, malformed/deep HTML, truncation, starý
  run, restart a tampering. Dokončit úplnou sadu, statické kontroly,
  dokumentaci a fyzický desktop/web průchod nad skutečnými stránkami.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-02-E — durable položky readeru
  v časové ose (cílová úroveň: implemented).** Ad-hoc oprava z fyzické
  akceptace 24. 10. 2026: úspěšně načtené stránky se po restartu nesmějí
  ztratit v dočasném společném panelu. Každý run se zobrazí samostatně podle
  `fetched_at`, včetně opakovaných načtení stejného zdroje, a rozbalí přesnou
  lokální projekci bez nového síťového fetch.

## Průběžné výsledky a ověření

- `public-source-structured-v1` je uzavřená bounded projekce s title,
  dokumentovým pořadím, heading path, sedmi typy bloků, tabulkovými řádky a
  deterministickými anchory. Duplicitní bloky dostávají stabilní pořadové
  zakončení.
- Nový run fsyncne `projection.json` vedle původních raw/text souborů a váže
  schema i SHA-256 do výsledku a Context Manifestu. Recovery kontroluje hash i
  schema; text-only run první verze zůstává čitelný bez migrace.
- Sdílené UI vykresluje strukturu pouze přes DOM `textContent`, nabízí
  přepnutí na původní bounded text a nezavádí síťový ani Git účinek.
- Oprava z fyzické akceptace promítá každý úspěšný reader run do časové osy
  vlákna. Rozbalení volá pouze lokální result endpoint; předchozí chyba
  obnovovala po restartu metadata, ale plný výtah nechávala jen v dočasném
  panelu a při opakování stejného zdroje zvýraznila pouze poslední run.
- Návrh, crash hranice, reuse a omezení jsou v
  [ADR 0046](docs/adr/0046-structured-public-source-projection.md), katalogu a
  aktualizovaném [akceptačním checklistu](docs/public-source-reader-acceptance.md).
- Původní cílená sada 25 testů prošla; cílená regrese durable časové osy má
  dalších 16 úspěšných testů. Úplná sada zopakovaná po opravě časové osy mimo
  omezený socket sandbox prošla:
  `780` testů, `28` přeskočených volitelných/fyzických testů. `py_compile`,
  `node --check` generovaného JavaScriptu a `git diff --check` prošly.
- Zbývá fyzická desktop/web akceptace nad nejméně dvěma skutečnými statickými
  stránkami, kontrola tabulky/seznamu a restartu. Bez ní dávka není
  `PoC validated` a není připravena k předání PR.

## Akceptace

- Výtah zachová srozumitelné pořadí a hierarchii podstatného obsahu a
  nepromíchá tabulky, navigaci a odstavce do nečitelného textu.
- Každý blok má bounded deterministický anchor, typ a heading path; UI jej
  vykreslí pouze jako nedůvěryhodný inertní obsah.
- Staré uložené runy zůstanou čitelné a audit raw/text hashů se nezmění.
- Cílené testy, úplná sada, statické kontroly a realistická fyzická akceptace
  projdou; omezení budou zdokumentována.
