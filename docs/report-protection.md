<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Ochrana zprávy před pozdními vstupy

Nové návrhy zpráv ze zpracování bloků, ruční i plánované, mají hodinové
ochranné období od dokončení první verze. Uzel, který v plánovaný okamžik
neběžel, sestaví aktuální splatnou zprávu při nejbližším běhu; hodina se počítá
od jejího skutečného sestavení. Restart původní termín ochrany neposouvá.
Starší uložené návrhy se zpětně nepřegenerovávají.

Po dobu ochrany lze návrh číst a exportovat. Nelze jej potvrdit/vydat:
blokaci vynucuje backend, nejen tlačítka v historii běhů a detailu zprávy.
Uplynutí času samo zprávu neodblokuje. Pracovní cyklus musí dokončit závěrečnou
kontrolu, také po výpadku uzlu. Stav ukazuje konec ochrany a přírůstek vstupů.

Kontrola porovnává obsahové reference ve vstupních poolech. Další pozorování
stejné obsahové verze ani nový přispívající filtr nejsou novým obsahem. Nový
článek nebo opravená obsahová verze vyvolají na konci ochrany jediné nové
sestavení. Nové sestavení včetně případného webového hledání používá původní
lookback okno ukotvené k prvnímu spuštění, ne posunuté o hodinu. U položek
s datem publikace rozhoduje toto datum; novější publikace patří příštímu
oknu. Položky bez data publikace používají čas prvního pozorování a mohou se
doplnit během ochrany. Časové okno všech poolů se čte z jedné uložené sady.

Původní návrh zůstává v místní historii výsledku jako `initial_draft` do
vypršení retence. Závěrečný běh má stabilní odvozené ID, přesné zmrazené vstupy
a případný vlastní Context Manifest. Pomocný výsledek nelze samostatně vydat.
Původní běh po úspěchu zpřístupní závěrečný návrh; schválení zahrnuje obsah
zprávy i reference vstupů. Ochranná lhůta se znovu neprodlužuje. Vstupy přijaté
po zmrazení závěrečného sestavení toto vydání už nemění.

Hodina není důkaz úplnosti zdrojů: nedostupný kanál nebo pozdější synchronizace
mohou doručit data až po uzavření ochrany. Chyba závěrečné kontroly či změna
připnuté definice během ochrany ponechá zprávu blokovanou s konkrétním důvodem.
Nejisté modelové volání se samo neopakuje; je nutné lidské posouzení a případně
nový explicitní běh. Existující aktivace a periodové ID zůstávají zachované.

## Sběr na pozadí a recovery

RSS má samostatný pracovní thread a effect flock nezávislý na modelovém
zpracování. Obě smyčky kontrolují práci každých 10 sekund; zdroje mají vlastní
intervaly, HTTP validátory a backoff. Sběr vyžaduje běžící backend, místní
aktivaci kanálu a dostupnou registraci projektu. Zavření samotného panelu jej
nezastaví. Vypnutý backend RSS nesbírá. Pomalý model nedrží zámek RSS.

Obě větve používají stejné krátké SQLite transakce. Maintenance/odstranění
získává oba zámky v pořadí intake → processing; běžný sběr ani model nedrží
SQLite transakci během sítě. Recovery smí označit jako unknown pouze dispatch
v získané větvi; běžící druhou větev nesmí změnit na unknown. Před souběžným
provozem musí být aktualizovány všechny backendové procesy sdílející runtime.

Crash boundaries doplňují [ADR 0082](adr/0082-composable-monitoring-and-message-pools.md):

- První výsledek a konec ochrany se uloží jednou SQLite transakcí. Přerušení
  před uložením zachová nejistý dispatch, nikoli schválitelnou zprávu.
- Před závěrečným modelem se uloží intent pod stabilním ID. Po pádu před
  potvrzením výsledku zůstane unknown bez automatického opakování.
- Po uložení závěrečného výsledku, ale před odblokováním původního běhu,
  restart použije stejný uložený výsledek bez dalšího modelového volání.
- Závěrečné vstupy, výsledek a odblokování původního běhu se zapíšou atomicky.
  Vydání drží processing flock, proto nemůže schválit přepisovaný návrh.
- Vydání do projektového Gitu nadále používá původní Workspace journal,
  deterministické operation ID a receipt. Recovery před/po Git commitu se nemění.
  Retence původního návrhu se přegenerováním neprodlužuje.

Reuse/adapt: stávající `block_jobs`, pool obsahové identity, ContextBuilder,
modelový journal, periodová ID a Workspace writer. Nevzniká další databáze,
transport ani writer. Ověření: `tests.test_report_protection`, kalendář,
blokový monitoring, HTTP publikace a skutečný Qt/WebEngine scénář.
