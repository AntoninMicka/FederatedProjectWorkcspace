<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0069 — Reportingový Source Collector nad existujícím readerem

Datum: 2026-11-04. Stav: implementovaný PoC MON-02 k review.

## Rozhodnutí a reuse

Reuse/adapt PublicSourceBinding/Request/Runs, StaticHTMLAdapter a bounded
projekce z [ADR 0033](0033-public-source-retrieval.md). První vertikála je
statický UTF-8 text přes HTTPS na přesné URL. Úzký adaptér přidává přísnější
robots/MIME/storage kontroly; obecné reader chování se nemění. Nový crawler,
SDK, browser, parserový framework, HTTP server ani writer nejsou potřebné.

Ruční reporting [ADR 0068](0068-manual-reporting-transactions.md) poskytuje
Source envelope, neměnné revize a jednu Workspace transakci. Collector uloží
raw source a deskriptor atomicky; nevkládá Event ani nepotvrzuje tvrzení.
Externí text se neinterpretuje jako policy.

Připnutý lokální user document má uzavřený policy formát: binding, exact URL
allowlist, limity, source role a posouzenou licenci/podmínky/retenci. Před
síťovým účinkem a importem se ověří živý writer guard, místní autor a platnost
task/policy/podkladů. Local-only/cross-project vstupy se odmítnou. Licence se
nehádá z URL/robots. Veřejný i soukromý reuse katalog byl zkontrolován;
externí kód se nepřenášel.

Soukromá složka collectoru používá původní PublicSourceRuns DB/staging,
odděleně od chatových fetchů. Flock serializuje její dispatch/recovery/import,
aby recovery neoznačila živý fetch jako přerušený. Collector_backoff ve stejné
DB drží per-origin Retry-After; není projektovým indexem ani schedulerem.
Obecný ReportRun a jeho cutoffy patří MON-04.

## Crash boundaries a recovery

Platí ADR 0033 pro fetch a [ADR 0003](0003-coordinated-operation.md) pro
publikaci. Mezi SQLite autoritami nevzniká distribuovaná transakce.

| Hranice | Autorita a obnova |
| --- | --- |
| Preview před prepare | Žádný GET/projektový zápis. Změna policy/HEAD vyžaduje nový posouzený plán. |
| Fetch prepared | PublicSourceRuns drží request a preview digest. Před dispatch se znovu kontroluje policy a backoff. |
| Dispatching / částečná odpověď / staging před succeeded | Pád je unknown bez automatického vyslání znovu. Částečná data nejsou Source a nemohou do importu. |
| 429/503 | Backoff se uloží před uzavřením výsledku; nové/připravené runy ho nesmějí obejít. |
| Succeeded po fsync stagingu | Replay ověří hashe. Ztráta/změna zneplatní fetch; nic se automaticky nestáhne znovu. |
| Import preview před intentem | Raw/Source candidate váže fetch result, expected HEAD a potvrzení přesných digestů. |
| Workspace prepared / soubory / commit-ready | Původní journal drží všechny bajty. Obnova nepoužívá síť/staging. Cizí změny vyžadují reconciliation. |
| Git CAS / index / ztracený receipt | Git drží raw/deskriptor. Stejné operation ID vrátí původní receipt i bez fetch stagingu, nevytvoří druhý import. |
| Ztracený index | Rebuild z HEAD. Fetch journal/pending intent se z indexu neregenerují. |
| Chybějící/prázdná fetch DB v existujícím state | Nový GET/import se odmítne bez vytvoření prázdné náhrady. Připravená Workspace operace/receipt zůstává obnovitelná samostatně. Úplná ztráta node-state vyžaduje operátorskou reconciliation. |

Backoff, fetch výsledky a staging jsou node-local. Git drží jen schválené raw
bajty, provenance a Source s policy/licenčními odkazy. Same-commit raw sibling
validuje původní writer před journalem i při sestavení kandidáta. Stejná URL
má Source následníka a nové raw ID; jiný původ se neslučuje podle hashe.
HTTP failure/withdrawal nemaže starý capture a nevytváří událost. Retention
či unknown reconciliation UI nejsou součástí řezu; unknown nedává oprávnění
k opakování.

## Ověření a hranice

Deterministické testy pokrývají allowlist/privacy, licence/policy revokaci,
nedůvěryhodnou policy ze source, robots/redirect/auth/rate limit/MIME/velikost,
změny zdrojů a různé původy stejných bajtů, CLI a pády procesu. Existující
transportní testy zahrnují DNS pinning, SNI i neplatný certifikát. Síťový probe
ověřuje skutečný veřejný HTTPS text a robots; nedokládá akceptaci projektové
archivace. Fyzický power-loss ani production-ready crawler nejsou prokázané.
Použití a důkazy: [Source Collector](../source-collector.md).
