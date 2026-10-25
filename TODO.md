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

- [ ] [planned] **OPS-WEB-CONCURRENCY-01-A — kontrakt souběhu, vlastnictví a
  recovery (cílová úroveň: designed).** Zmapovat současný server, stream,
  SQLite/Git writery a shutdown cestu; určit přesně povolené read-only requesty,
  limity workerů, serializační hranice a chování při pádu či odpojení klienta.
- [ ] [planned] **OPS-WEB-CONCURRENCY-01-B — omezená souběžná HTTP obsluha
  (cílová úroveň: implemented).** Umožnit periodické telemetrii dokončit během
  dlouhého streamu, aniž by se změnil request ownership, autentizace, RBAC,
  privacy, binding nebo autorita existujících journalů a zámků.
- [ ] [planned] **OPS-WEB-CONCURRENCY-01-C — zápisové a shutdown regrese
  (cílová úroveň: implemented).** Ověřit souběh streamu, read-only telemetrie a
  nezávislé zápisové interakce, bounded backpressure, odpojení klienta, restart
  a čisté ukončení bez ztraceného durable stavu, dvojí odpovědi či retry
  `unknown`.
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

## Akceptace dávky

Dávka je přijatelná až po doloženém současném dlouhém streamu, periodické
read-only telemetrii a nezávislé zápisové interakci, včetně odpojení/restartu a
kontroly durable journalu. Samotný rychlejší monitor nebo unit test vláken není
důkaz zachování write serializace a recovery.
