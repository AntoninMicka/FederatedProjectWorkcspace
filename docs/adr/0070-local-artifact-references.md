<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0070 — Připnuté lokální meziprojektové reference

Datum: 2026-11-04. Stav: implementovaný PoC XREF-01 k review.

## Rozhodnutí

`fpw-artifact-reference-v1` je dokument s kanonickým `reference.json`.
Obsahuje source project UUID, logickou identitu repozitáře
`fpw-project-git:<project UUID>`, artifact UUID, úplný commit, cestu, SHA-256
obsahu, SHA-256 kanonických metadat a privacy. Registrace uzlu mapuje identitu
na lokální repozitář; fyzické cesty ani credentialed URL se do reference nepíší.
Reference má vlastní lokální ID. Není symlinkem ani kopií cizího obsahu.
Stejné ID reference zachovává zdrojový projekt a artefakt; repin mění pouze
explicitně potvrzenou revizi. Reference nelze implicitně změnit na kopii.

Resolver používá živé oprávnění uživatele k oběma projektům, průnik s rozsahem
konkrétního requestu a aktuální privacy zdroje. Zpřísnění privacy se uplatní
i na starou připnutou revizi. Známé smazání, revokace, neplatný pin nebo
pending source operace neposkytují fallback do cache. Neregistrovaný zdroj
se odmítne. Offline cache vyžaduje stále platnou místní autorizaci; při
nedostupném registrovaném repozitáři smí sloužit jen pro same-node zobrazení
s `offline-stale` a `privacy_unverified`. Nenahrazuje kontrolu aktuální privacy.

SQLite projektový index drží pouze místní deskriptor. Autorizovaný přehled
resolveru doplní dostupnost bez ukládání cizích bajtů do indexu. ContextBuilder
získá přesné zdrojové bajty živým resolverem a manifest zaznamená pin, source
HEAD, revizi oprávnění, hash deskriptoru a efektivní privacy. Před dispatch
ověří vše znovu. Cache nikdy není vstupem Context Manifestu ani forku.
ChatService předává resolveru aktuálního uživatele a omezení requestu.

Explicitní fork dostane nové ID a neměnnou provenance `fpw-artifact-fork-v1`.
Markdown dokument lze pak lokálně upravovat; jiné bajty se uloží jako raw
Source podle dosavadního importního kontraktu. Kopie žije samostatně a další
změny/revokace zdroje ji automaticky nemažou. Revokace také nevymaže historii
Git ani dříve získané bajty. Řetězení referencí a vzdálený transport patří
do dalšího návrhu; první řez pracuje se dvěma lokálně registrovanými projekty.

## Reuse a crash boundaries

Reuse/adapt: Artifacts/Projects, Administration, ContextBuilder, inertní
artifact_preview, metadata/index a Workspace.transact. Veřejná i soukromá
inventura neposkytly důvod nahrazovat tyto komponenty. Bez externího kódu,
nového writeru, distribuované transakce nebo další autoritativní DB.
Platí [ADR 0003](0003-coordinated-operation.md).

| Hranice | Autorita a recovery |
| --- | --- |
| Preview / před Workspace prepare | Žádný projektový zápis. Nový HEAD, grant či privacy vyžadují novou kontrolu; potvrzení váže přesný preview digest. |
| Čtení zdroje a příprava cíle | Source writer lock je neblokující, aby reciproční reference nezpůsobily deadlock. Busy/pending/stale se odmítne. Nevzniká atomická transakce přes dva Git repozitáře. |
| Workspace prepared / soubory / commit-ready | Journal cíle už obsahuje přesné schválené bajty deskriptoru či forku. Recovery je nedočítá ze zdroje a funguje i po jeho odpojení. |
| Git CAS / commit / index / ztracená odpověď | Původní Workspace obnova, rebuild indexu z HEAD. Stejné operation ID a request vrátí receipt bez opakovaného zápisu či přístupu ke zdroji. |
| Cache před/po rename | Privátní per-user soubor, bounded parse, ověření hashů, atomic replace a fsync. Ztráta cache nepoškodí projekt ani journal; lze ji znovu získat živým autorizovaným čtením. |

Připravený trvalý intent může být dokončen po pozdější revokaci zdroje;
nejde o nový import. Nové čtení nebo fork vždy vyžaduje živou autorizaci.
Reálný výpadek napájení nebyl simulován; testy ukončují proces na devíti
hranách transakce a obnovují cíl s odpojeným zdrojem.

## Ověření a rozsah

CLI/service PoC, nikoli nový grafický formulář. Generický GUI viewer může
ukázat samotný deskriptor; resolved zobrazení poskytuje CLI s původním inertním
rendererem. Návod, opakovatelná ukázka a důkazy jsou v
[meziprojektových referencích](../cross-project-references.md).
