<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Sdílená aktivace a výsledky monitoringu

Upřesnění MON-08-07 schválené uživatelem 15. 11. 2026 nahrazuje původní
výhradně místní aktivace. Zapnutí i pozastavení kanálu nebo zpracování lze
provést na kterémkoliv oprávněném uzlu. Stav se přenese běžnou schválenou
synchronizací projektu. Definice bez aktivačního záznamu zůstává vypnutá;
přijetí samotné nové definice není aktivace.

Aktivované RSS kanály sbírají redundantně všechny oprávněné připojené uzly.
Plánovanou zprávu sestavuje pouze uzel určený definicí zpracování. Ruční
sestavení, spuštění komplexní úlohy a **Zpracovat znovu** používají vždy
místní uzel, jeho oprávnění a místní modelové nastavení. Zpráva zaznamená
skutečného vykonavatele vedle původní připnuté definice. Ruční spuštění nemění
určení plánovaného vykonavatele ani jeho obsloužený kalendářní slot. Již
přenesený výsledek stejného periodového ID se použije bez nového modelového
volání také po změně požadovaného uzlu. Tato idempotence nad známými výsledky
není distribuovaná rezervace ani automatické převzetí rozpracovaného běhu.

Nedostupnost modelu, chyba přípravy vstupů nebo nejistý výsledek vytváří
viditelný chybový výsledek. Ten obsahuje popis problému a původ běhu, nikoliv
credentials nebo provozní manifest. Error text odstraňuje Bearer/API tokeny,
URL userinfo a query. Stav unknown zůstává přiznaný. U chybového výsledku lze
výslovně spustit nový místní pokus ihned; ten má nové ID a původní výsledek
zachová. U úspěšných zpráv zůstává původní hodinová ochrana podle
[kontraktu zpráv](report-protection.md).

## Přenos a autority

Stávající kolekce `message-pools/pools.sqlite` přijímá další dva typy logických
záznamů: `activation` a `report-outcome`. Přenášejí se stejným podepsaným
same-team/all sidecarem jako pooly, nikoliv kopírováním SQLite souboru.
Definice a vydané artefakty zůstávají v Gitu. Aktivační rozhodnutí a sdílené
výsledky patří autoritativní logické kolekci; `block_bindings` obsahuje její
místní projekci a místní HTTP stav. `block_jobs`, modelové journaly, leases,
credentials, HTTP validátory, next_due a last_slot zůstávají místní.

Přenesený výsledek obsahuje návrh zprávy nebo chybový popis, stav, původní run
ID, skutečný uzel, časové okno, připnutou definici a reference vstupů. Neobsahuje
kopii raw poolů, poskytovatelova manifestu ani jeho odpovědí. Na druhém uzlu
je čitelný a lze z něj spustit nový místní pokus. Dokončený posouzený návrh
lze vydat původním Workspace writerem i z přijímajícího uzlu; tím se na něj
nepřenáší vlastnictví původního worker journalu. Git artefakt a receipt mají
stejné deterministické ID. Opakování publikace ověří dostupné historické bajty
již vydaného artefaktu a nezkouší vytvořit druhý soubor.

Podpis, projektové mapování a oprávnění řídí dosavadní native exchange.
Importer navíc ověřuje druhy záznamů, obsahové identity, návaznosti, přesný
historický pin definice i vydaného artefaktu, privacy a digest schvalovaného textu/vstupů.
Local-only záznamy se neexportují. Velikostní limity sidecaru zůstávají
8 MiB / 20 000 záznamů; překročení zůstane viditelnou chybou přenosu.
Starší příjemce nové druhy záznamů odmítne, proto musí být oba backendy
aktualizované před jejich společným používáním.

## Souběh, retence a recovery

Aktivace má neměnnou identitu a seznam předchůdců. Změna po synchronizaci
naváže na viditelné hlavy. Souběžné souhlasné změny mají shodný účinek;
protichůdné změny vytvoří viditelný konflikt a zpracování zůstane vypnuté.
Nové výslovné zapnutí/pozastavení naváže na všechny hlavy a konflikt vyřeší.
Nevybírá se podle hodin nebo UUID. Historie aktivace se zachovává včetně
pozastavení. Existující místní binding bez sdílené historie se při prvním
pracovním cyklu převede na odpovídající rozhodnutí; příjem se nesmí zaměnit
za nové místní rozhodnutí. Čtení katalogu nic nezapisuje.

Výsledky mají oddělenou historii podle run ID a skutečného vykonavatele.
Neslučitelné souběžné výsledky se zobrazí jako nejednoznačný výsledek; žádný
uzel nesmí být automaticky vybrán jako vítěz. Po skončení retence se smažou
texty výsledků z kolekce i jejich soukromé pracovní kopie podle dosavadních
pravidel. Aktivační historie zůstává. Dokončené sync payloady mají původní
transportní lifecycle; nejde o novou garanci purge všech vzdálených kopií.

Crash boundaries doplňují ADR 0082:

1. Aktivační rozhodnutí a místní binding se uloží jednou FULL transakcí.
   Před commitem se obojí vrátí, po commitu lze binding z historie obnovit.
2. Před modelem zůstává původní soukromý dispatch intent. Výsledek a jeho
   sdílený záznam se potvrzují jednou FULL transakcí. Pád před ní nepřenese
   zdánlivě úspěšný návrh; po commitu se použije uložený výsledek.
3. Při restartu se přerušený dispatch označí unknown a připraví se sdílený
   chybový výsledek bez dalšího volání modelu. Dokončené starší místní běhy
   se mohou doplnit do sdílené kolekce bez nového zpracování.
4. Příjem používá původní transakční merge a signed exchange replay. Neimportuje
   vzdálené `block_jobs`. Pád po Git publikaci, ale před uložením výsledkové
   reference používá původní Workspace receipt při opakování schválené akce.

Panel dostupnosti/schopností, vzdálený dispatch, automatické převzetí ani
komplexní předávání rozpracovaných běhů nejsou součástí tohoto řezu.
Uživatel prakticky potvrdil běžný redundantní provoz; řízený fyzický test
výpadku není podmínkou zde schváleného zúženého rozsahu. Cílené testy používají
dva izolované uzly se skutečným podepsaným přenosem a řízeným modelem.
