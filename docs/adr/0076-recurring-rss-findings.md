<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0076 — Průběžný RSS sběr a neměnné nálezy

Datum: 2026-11-06. Stav: implementace MON-08-03 k review.

## Rozsah a autorita

Navazuje na [samostatné definice](0074-independent-monitoring-definitions.md)
a [konektorový kontrakt](0075-source-connector-contract.md) v téže dávce MON-08.
Zadání při zahájení: projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
HEAD `e4fcb0edeef1119675c2b467d16027dbea01661b`, export
`d723aff55d14c49f4b2b43b2b79b91152ad3dd6e165db8243800ef643a9a803d`,
stale=false, zdrojový základ `35ddbd7`.

Tento řez řídí RSS kontroly a evidenci nálezů, nikoli celý reportovací tok.
Rozvrh zdroje je nezávislý na rozvrhu zprávy. Jeden původní backendový
worker Monitoring obslouží také RSS; nevzniká druhý daemon ani časovač.
Při vypnuté aplikaci sběr neběží; po zapnutí provede jednu splatnou kontrolu,
ne předstírané zpětné zachycení každého vynechaného intervalu.

## Rozhodnutí a reuse

Git zůstává autoritou nálezů a raw zachycení. Reporting dostává aditivní
typ `SourceFinding` / `fpw-reporting-finding-v1`: přesný pin WatchDefinition,
input ID, normalizovanou položku, aliases, hash nativní položky, stav,
rozhodnutí/důvod/verzi filtru, důvod revize a raw ref. Nativní položkový hash
zahrnuje i metadata; obsahový hash položky dál pokrývá jen obsahové bajty.
Oprava je následník téže identity. První discovered_at/imported_at a dosavadní
aliases jsou neměnné / append-only. Různé identity nebo zdroje se neslučují
jen kvůli totožnému obsahu. Konfliktní GUID/URL vazby selžou bez importu.

Reporting.apply je rozšířený o interní bounded RSS capture vstup.
Jedna původní Workspace transakce atomicky uloží dekódované XML bajty jako
inertní source a nejvýše 500 nových/opravených nálezů. MIME uloženého formátu
je XML; raw hash zde není hash případného gzip wire streamu. Opakované
položky nepřidají nález, processing intent ani nový Git commit. SourceFinding
není Event, EvidenceAssessment ani potvrzení tvrzení. Generic writer
vynucuje neměnnost, privacy, vazbu na konkrétní RSS input a raw hash.
Importované záznamy mají import provenance; metadata SourceFinding zůstávají
external i po ruční změně processing stavu. MIME původní odpovědi se uloží,
pokud je známé; neznámé se nevymýšlí.

Operational state rozšiřuje původní ReportingScheduler DB, schema 3:
`rss_bindings` a `rss_polls`. Transakční migrace z vlastněných schema 1/2
zachovává původní runy, approvals a cutoffy; neznámý owner/schéma selže.
Definice a artefakty se z této DB neregenerují. Ztráta DB v existujícím
state není nový prázdný runtime. Úplná ztráta node-state vyžaduje původní
operátorskou reconciliation, nikoli nové automatické účinky.

Binding obsahuje přesný definition pin, input, interval, režim, příští čas
a lokální HTTP validátory. Výslovné potvrzení aplikace uloží grant hashe
definice do původní watch_grants. Před GET a před novou publikací se znovu
ověří aktuální definice, aktivita, writable role, privacy a místní souhlas.
Změněná definice potřebuje nové potvrzení. Samotné active=true ani import
definice nemohou spustit síť. Pozastavení je možné i po změně definice.

RSS reader/transport podporuje pouze If-None-Match a If-Modified-Since,
bez CR/LF, ne-ASCII nebo libovolných dalších hlaviček. DNS/IP/TLS, robots,
redirect/MIME/size/gzip/XML kontroly zůstávají. HTTP 304 má explicitní
not_modified výsledek a nepovažuje se za prázdný feed. RSS connector deklaruje
http-validators continuation; jejich persistenci vlastní run journal,
nikoli connector. Validátory se posunou teprve po úplné publikaci nálezů
nebo ověřeném 304. 429/503 sdílejí původní per-origin collector_backoff;
další URL/nový binding jej nemůže obejít. Není okamžitý retry.

Režim capture-only ukládá captured / not-evaluated. Queue-all výslovně vybírá
všechny nové/opravené položky do pending; netvrdí sémantickou relevanci a
neinterpretuje volný text instrukcí jako vykonaný filtr. Pravidla/pin,
verze jednoduché policy a důvod jsou zaznamenané. Selected/pending,
processed, discarded s důvodem a processing failed/unknown rozlišují
neměnné stavové revize. Změna stavu vyžaduje výslovné potvrzení a má
idempotentní operation ID; znovudoručení už processed nález nezařadí znovu.
LLM, automatický report, pokrok ani průlom tento sběr nevytváří.

Reuse/adapt: Reporting/Workspace writer a sémantický gate, ReportingScheduler
owner/DB/grants/receipts, SourceCollector origin backoff, rss_reader.observe,
bezpečný HTTP reader a společný SourceItem. Druhá DB, writer, daemon,
provider SDK a automatické lidské schvalování byly odmítnuty. Veřejná i
dostupná soukromá inventura byly zkontrolovány; externí kód se nepřenášel.

## Crash boundaries a recovery

Platí [ADR 0068](0068-manual-reporting-transactions.md),
[ADR 0069](0069-reporting-source-collector.md) a
[ADR 0072](0072-reporting-scheduler-and-run-recovery.md). Mezi node-local
journalem a projektovým Gitem není distribuovaná atomicita.

| Hranice | Autorita a obnova |
| --- | --- |
| Prepared před dispatch | Journal drží původní binding intent. Po získání process locku lze bezpečně pokračovat. |
| Dispatching / přerušená odpověď | Unknown; žádný další slot nebo nový GET automaticky. Process lock brání záměně živého workeru za přerušený. |
| Fetched, před plánem | SQLite FULL drží bounded XML a validátory. Restart vytvoří plán bez sítě, s novou kontrolou oprávnění. Vadný feed je failed, nikoli nulový nález. |
| Publishing, před Workspace prepare | Journal drží přesný request, operation ID a expected HEAD. Stale/foreign změna se nepřepíše; není automatický nový intent. |
| Workspace prepared / soubory / Git CAS / index | Původní Workspace journal dokončí přesné bajty. Stejný operation ID vrátí receipt bez dalších nálezů/commitu. |
| Git receipt, před posunem validátorů | Replay publikačního requestu získá původní receipt bez GET; pak atomicky uzavře poll a posune next_due/validátory. |
| Completed / failed | V journalu zůstane výsledek, chyba, hashe a receipt. Velké staging XML a plán se nahradí souhrnem až po konečném výsledku; publikované XML/nálezy zůstávají v Gitu. |

Explicitní reconciliation unknown běh opustí a další GET dovolí až v novém
pozdějším slotu. U publishing se nejdřív obnoví Workspace: existující receipt
dokončí původní poll; bez receipt lze intent opustit pouze tehdy, když
nikdy nevznikla Workspace operace. Pending/conflicting Workspace intent se
nezahodí. Pause a recovery nejsou lidskou akceptací nálezů nebo feature.

Zapnutí přes API, stavový přehled a důkazy:
[Průběžný RSS sběr](../recurring-rss.md). Plné formuláře, obecné filtry,
zpracování a federace zůstávají navazujícími úkoly MON-08.
