<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0068 — Ruční reporting jako jedna Workspace transakce

Datum: 2026-11-04. Stav: implementovaný lokální řez MON-01 k review.

## Kontext a rozhodnutí

MON-01 požaduje ruční task, zdroje/události/story a připnutý Markdown report,
bez scheduleru a povinného LLM. Reuse formátů [kontraktu v1](../reporting-contract-v1.md)
a autorit [ADR 0063](0063-reporting-contract-and-boundaries.md). Lokální CLI
připravuje úplné kandidátní bajty pod identitou vlastníka uzlu; nová lidská
rozhodnutí a vydání vyžadují explicitní --confirm. Tento řez nepřidává HTTP/RBAC
API, automatické schvalování, spouštění policy ani externí účinky.

Konkrétní zúžení obecné run pipeline ADR 0063: ruční operace nemá sběr,
provider request, cache draft ani delivery. Proto nepřidává druhý ReportRun
journal; celý intent s přesnými vstupy a potvrzením váže původní Workspace
request digest. Generation.run_id je UUID ruční operace. Nevzniká scheduled
ReportRun a neposouvá se last_successful_cutoff. Při připojení vícefázového
sběru/scheduleru musí MON-04 doplnit samostatný autoritativní run journal podle
původního kontraktu; index jej nenahradí. Důvodem zúžení je absence jakéhokoli
persistentního nebo externího mezikroku mimo jediný Workspace intent.

## Reuse a validace

- Reuse Artifacts.workspace, registrace, local_author, Workspace.transact,
  writer lock, journal, Git CAS, receipts a Index.
- Adapt metadata.validate_snapshot/validate_transition: rezervovaný
  record.json, uzavřená schémata, graph/append-only kontrola a neměnnost všech
  bajtů přijaté revize i při obecném zápisu/importu/merge. Následník nesmí
  znovu použít starý artifact ID.
- Čistý reportingový validátor nad stejnými strukturami. Před journalem
  a při přípravě kandidáta kontroluje lokální commit/path/hash reference,
  shodu task/scale/evidence, privacy a úplnost reportových vstupů.
- Podvržené review z importovaného JSON není autorizace. Manuální rozhraní
  nepřijímá actor/time pro nové review od volajícího a nemá remote endpoint.
  Pokročilé policy/RBAC/cross-project předání vyžaduje vlastní autorizační tok;
  pouhé UUID ho nenahrazuje. Policy je zde podklad místního lidského úsudku.

Veřejný i dostupný soukromý reuse katalog byl přečten. Místní transaction
engine je vhodný; externí kód, další DB, provider, frontend ani druhý writer
nejsou potřebné. Deduplikace je projekce posouzených rozhodnutí, nikdy mazání
původních zdrojů/událostí.

## Crash boundaries a recovery

Platí [ADR 0003](0003-coordinated-operation.md) beze změny storage protokolu:

| Hranice | Autorita a obnova |
| --- | --- |
| Před intentem | Žádná změna projektu; chybný/konfliktní požadavek se odmítne před journalem. |
| Prepared / dílčí soubory / files-applied | Jeden journal drží všechny bajty Markdownu i manifestu. Recovery dokončí tutéž operaci a znovu validuje; cizí změnu zachová a odmítne pokračovat. |
| Commit-created / commit-ready / před CAS | HEAD stále označuje původní vydání. Kandidát je v původním journalu; retry nemění operation ID, vstupy ani approval. |
| Po CAS / před indexem či receiptem | Vydání existuje v Gitu. Recovery rozpozná kandidátní HEAD, obnoví index a původní receipt; nevydá nový report. |
| Dokončeno / ztracená odpověď | Totožné operation ID a intent vrátí receipt; jiný intent nebo druhé základní vydání periody se odmítne. |
| Ztracený index | Obnoví se z HEAD. Ztráta autoritativního journalu není index rebuild ani povolení nového publikačního pokusu. |

Schválení je součástí request digestu. Změna textu, vstupů nebo potvrzení
pod stejným operation ID je konflikt. Nové UUID každého následníka/opravy
a přesné reference zachovávají staré reporty. Zákaz druhého základního vydání
kontroluje stejný zámek jako projektový zápis, i při novém připnutí téže
task revize v jiném commitu. Process-crash testy neprokazují odolnost vůči
fyzickému výpadku napájení, ztrátě disku/journalu ani libovolnému přerušení
Git/SQLite syscallu.

Použití: [ruční reporting](../manual-reporting.md). Akceptace a doručení PR
zůstávají samostatné lidské kroky ve Workspace.
