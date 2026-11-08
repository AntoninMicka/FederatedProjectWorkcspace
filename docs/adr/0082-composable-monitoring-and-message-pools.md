<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# ADR 0082 — samostatné bloky sledování a synchronizované pooly

Datum: 2026-11-08. Rozhodnutí schválené uživatelem v zadání; implementace
ani automatizované testy nenahrazují lidskou akceptaci celé dávky MON-08.
Podklad: projekt c898b941-8eb0-4406-8dad-6e2b96c06d59, export
c3ee867bcf19915337e3d23cf32b63f8964ed1952604480d920e1d360309595d.

## Rozhodnutí

Samostatné verzované bloky: zdroj, filtr, pool, zpracování a komplexní úloha.
Vazby jsou source→filter→pool→processing; processing může navíc použít
web-search source výhradně na vyžádání. Úloha skládá existující i nové bloky.
Využití se odvozuje ze skutečných vazeb; bloky se nekopírují při připojení.
LLM sestavuje editovatelný návrh, který před uložením projde stejnou
validací jako ruční sestava. Uložení neaktivuje sběr ani nepublikuje zprávu.

Git zůstává autoritou definic, jejich revizí a vydaných zpráv. Obsah poolů
je samostatná synchronizovaná kolekce mimo Git. Její SQLite je autoritativní
úložiště, nikoli projektový index ani kopie provozního journalu druhého uzlu.
Synchronizují se validované logické záznamy, nikdy SQLite soubor, granty,
credentials ani stav rozpracovaných operací. Privacy nesmí při toku klesat.

RSS sbírají redundantně všechny místně aktivované oprávněné uzly. Nový režim
nepoužívá výhradního vlastníka ani koordinátora. Nahrazuje výhradní umístění
RSS z ADR 0080 pro nové bloky; starší WatchDefinition se automaticky nemigrují.
Umístění LLM zpracování ani pravidla publikace se tím neuvolňují.
Jednorázový, výslovně posouzený převod starších zadání nově popisuje
[ADR 0083](0083-one-time-monitoring-migration.md); čtení ani sync převod samy nespouštějí.

Identita položky vychází z connector + stabilní source ID + původní ID/URL.
Obsahová revize neobsahuje node ID ani časy načtení. Pozorování uzlů a
rozhodnutí filtrů jsou oddělená množina. V poolu se stejné URL seskupí,
souběžné odlišné obsahy se zachovají; pořadí příjmu není pořadím oprav.
Zpracování neodebírá zprávy z poolu ostatním uživatelům.

## Crash boundaries a recovery před implementací

- Definice: reuse Reporting.apply / Workspace.transact podle ADR 0068.
  Všechny nové bloky sestavy se uloží jedním commitem. Před commitem journal,
  po commitu receipt a rebuild projektového indexu. Žádný nový Git writer.
- RSS: durable dispatch intent se uloží před HTTP. Pád během HTTP nebo před
  uložením výsledku znamená unknown; není automatický opakovaný GET. Po
  potvrzeném restartu uživatel může povolit další kontrolu. Raw feed se do
  Gitu ani dlouhodobého journalu neukládá.
- Přijetí vybraných položek, jejich pozorování, rozhodnutí a dokončení pollu
  je jedna SQLite transakce s FULL synchronizací. Pád před COMMIT nepřijme
  nic; po COMMIT replay nesmí přidat kopii. Nevybrané texty se neukládají.
- Pool sync je množinové idempotentní sloučení validovaných revizí a vazeb
  v jedné transakci. Stejný klíč s odlišným obsahem se odmítne. Rozpracovaný
  sync lze zopakovat ze stejných bajtů; nemění runtime souhlas na příjemci.
- LLM: manifest a zmrazené vstupy vzniknou před dispatch. Pád po dispatch
  znamená unknown; samotný timeout nesmí spustit nový modelový pokus.
- Vydání návrhu: nejdřív Git transakce se stabilním operation ID, potom
  lokální potvrzení. Po pádu se původní receipt dohledá a dokončí potvrzení.
- Pool sidecar v podepsaném exchange v3 navazuje na původní durable inbound
  journal: po Git publication se sloučí kolekce a až poté se potvrdí transport.
  Pád mezi těmito kroky se dokončí ze stejného payloadu. Pool zápis má jednu
  transakci; samostatný lokální údaj o posledním příjmu lze obnovit replayem.
- Retence: spravované expirované členství a neodkazované obsahy se uklízejí
  před čtením a sync. Historické feedy v Gitu se nemažou ani nepřepisují.
  Offline uzel provede úklid při startu; nejde o forenzní přepsání média.
  Kolekční TTL neodstraňuje vydané zprávy, modelové audity ani původní
  transportní inbound/outbound payloady. Úplná retence těchto dalších vrstev
  vyžaduje samostatný lifecycle, není zde vydávána za implementovanou.

## Reuse

Adapt: Reporting revize, sémantická validace a Workspace writer, RSS transport
s robots/TLS/DNS/limity a HTTP validátory, source connector položky, izolovaný
regex evaluator, ContextBuilder a původní backend run journal, sdílené UI a
federation podpisy/policy. Reject: nový Git writer, přenos provozních databází,
implicitní modelový dispatch z feedu, kopírování sdílených bloků a volba
výhradního RSS leadera. Soukromá inventura nepřidává potřebnou komponentu;
žádný externí kód ani nová knihovna se nepřebírá.
