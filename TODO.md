<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — OPS-WEB-CONCURRENCY-01

Aktivní feature dávka `OPS-WEB-CONCURRENCY-01` vznikla 25. 10. 2026 na větvi
`feature/ops-web-concurrency-01` z aktuálního `develop` na merge commitu
`57009e2` (PR #90). Cílem jediného PR do `develop` je umožnit omezenou
souběžnou read-only obsluhu monitoru během dlouhého streamu bez zavedení
druhého writeru, dvojí odpovědi nebo automatického retry. Cílová úroveň je
**PoC validated**.

Původ: uživatelské zjištění při `OPS-NODE-MONITOR-01`, že současný jediný
obslužný tok během streamované odpovědi nevyřídí monitorovací požadavek.
Závislost `OPS-NODE-MONITOR-01` je doručena PR #90. Rozsah zahrnuje návrh
vlastnictví a ukončení requestů, omezenou souběžnost HTTP obsluhy, zachování
serializace projektových a node-local zápisů, testy souběhu a fyzickou
akceptaci. Nezahrnuje obecný job server, více backendových writerů, změnu
bindingu/privacy/autorizace ani paralelní inference.

## Úkoly dávky

- [x] [completed] **OPS-WEB-CONCURRENCY-01-A — kontrakt souběhu, vlastnictví a
  recovery (výsledek: designed).** [ADR 0050](docs/adr/0050-bounded-http-monitor-concurrency.md)
  omezuje souběh na jediný `POST /v1/node-telemetry/status` vedle jediné
  aplikační linky, nejvýše čtyři request workery, dvousekundový backpressure a
  jednoho vlastníka socketu/odpovědi. Vyžaduje read-only autentizaci a journal
  connections fyzicky oddělené od bootstrapu a migrace,
  per-request webovou autoritu a bounded shutdown; projektové a node-local
  journally/zámky zůstávají autoritativní a `unknown` se neopakuje.
- [x] [completed] **OPS-WEB-CONCURRENCY-01-B — omezená souběžná HTTP obsluha
  (výsledek: implemented).** Desktopový TCP a webový TLS server používají
  nejvýše čtyři request workery, jednu aplikační a jednu přesně vyhrazenou
  telemetrickou linku. Read-only autentizace a providerové journal connections
  nebootstrapují ani nemigrují stav, webová autorita je per-request a jeden
  worker zůstává jediným vlastníkem socketu a odpovědi. Cílené HTTP/TLS testy
  doložily telemetrii dokončenou vedle blokované aplikační linky.
- [x] [completed] **OPS-WEB-CONCURRENCY-01-C — zápisové a shutdown regrese
  (výsledek: implemented).** Souběžný zápis při obsazené aplikační lince končí
  `503` před dispatch, páté spojení nevytvoří worker nad pevný limit čtyř a
  server při shutdownu nejprve bounded čeká na vlastněné requesty. Po vypršení
  225sekundové produkční grace uzavře jejich klientské sockety a vrátí crash
  boundary; zkrácené testovací limity ověřily obě větve. Odpojení klienta po
  Ollama dispatch ponechá durable `unknown` bez částečné odpovědi a restart
  stejný run znovu neodešle.
- [ ] [planned] **OPS-WEB-CONCURRENCY-01-D — úplná regrese a fyzická akceptace
  (cílová úroveň: PoC validated).** Spustit cílené testy, úplnou sadu a skutečný
  desktop/web průchod, v němž se monitor obnovuje během dlouhé streamované
  Ollama odpovědi a následný restart zachová jediný durable výsledek.

## Crash boundaries

Před implementací musí část A potvrdit, které existující Git a SQLite operace
zůstávají serializované a kdo vlastní dokončení streamu. Read-only worker nesmí
publikovat projektový stav ani měnit binding/policy. Pád nebo odpojení po
provider dispatch nesmí způsobit druhý dispatch; autoritativní journal nadále
rozhoduje mezi `succeeded`, `failed` a `unknown`. Shutdown musí přestat přijímat
nové requesty, bounded čekat na vlastněné operace a nesmí uzavřít sdílený stav
pod aktivním writerem.

Část B odstranila DDL-capable čtení z telemetrické cesty a oddělila read-only
webovou autentizaci od bootstrapu/migrace. Úplná sada po implementaci:
`python3 -m unittest discover -s tests -v` — 824 testů úspěšných, 28 přeskočeno.
Cílená sada `python3 -m unittest tests.test_local_api
tests.test_ollama_backend -v` — 51 testů úspěšných. Část C doplnila odmítnutí
zápisu před dispatch, čtyřworkerový backpressure, čisté i deadline ukončení a
odpojení po dispatch s kontrolou journalu po restartu. Fyzická desktop/web
akceptace s reálnou dlouhou Ollama odpovědí zůstává v D.

## Akceptace dávky

Dávka je přijatelná až po doloženém současném dlouhém streamu, periodické
read-only telemetrii a nezávislé zápisové interakci, včetně odpojení/restartu a
kontroly durable journalu. Samotný rychlejší monitor nebo unit test vláken není
důkaz zachování write serializace a recovery.
