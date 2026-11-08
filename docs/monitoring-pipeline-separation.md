<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Oddělení RSS, skenů, poolu a zpráv

Aktualizace 8. 11. 2026: tento původní návrh nahrazuje schválené členění
na zdroje, filtry, pooly, zpracování a komplexní úlohy v
[ADR 0082](adr/0082-composable-monitoring-and-message-pools.md) a
[návodu](composable-monitoring.md). Výhradní RSS uzel a Git ukládání nových
poolů z níže uvedeného návrhu se nepřebírají. Text níže zachovává původní
rozbor retence, nikoli aktuální implementační kontrakt.

Stav: **návrh k review**, nikoli implementovaná retence nebo nové GUI.
Zadání uživatele 8. 11. 2026 upřesňuje MON-08-07/08/09/10 v aktuální dávce.
Podklad: Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, exportní
revize `c3ee867bcf19915337e3d23cf32b63f8964ed1952604480d920e1d360309595d`,
zdrojový HEAD `616d4ed`. Dokument je návrh předání; nemění autoritativní plán.

## Čtyři samostatné části GUI

| Část | Ovládání a výstup |
| --- | --- |
| Zdroje → RSS | Záložky kanálů a společný přehled. URL, pravidelný odběr, konkrétní těžební uzel, poslední úspěch/chyba a další načtení. Položky NEW a SCANED podle zadání; výsledek skenu selected/rejected/error samostatně. |
| Pravidla skenování RSS | Samostatný seznam a editor pravidel, přiřazené kanály, revize, náhled nad dočasným vstupem, aktivace a rozvrh skenu. Rozhodují o přijetí do poolu; nevytvářejí zprávu. |
| Pool zpráv a zdrojů | Přijaté položky, původní kanál/URL, čas, důvod a revize přijetí, platnost a retenční zadání. Samostatný přehled dočasných deduplikačních záznamů odmítnutých položek bez textu. |
| Pravidla vyhledávání a zpráv | Samostatný editor cíle, vstupu pool/web/obojí, časového okna, pravidel vyhledání a sestavení, zpracovatelského uzlu a ručního/plánovaného spuštění. Vstupy se před spuštěním zmrazí; vydání má vlastní review. |

První část přesune pravidelné načítání a skenování z nynějšího společného
editoru sledování do RSS. Obě činnosti mají vlastní rozvrh: stažená položka
je NEW; dokončený sken je SCANED. Chyba skenu není dokončení a musí mít
viditelnou možnost obnovy. Změna pravidel nespouští automaticky opakovaný
sken starého obsahu; uživatel zvolí rozsah a novou revizi skenu.

Těžební a zpracovatelský uzel jsou nezávislé konkrétní identity. Synchronizace
definice ani výsledku neaktivuje práci na příjemci. Webový vstup využije
stávající zdrojový kontrakt a přístupová pravidla; model potřebuje původní
Context Manifest a privacy kontrolu. Ruční spuštění není souhlas k vydání.

## Retence bez uchování odmítnutého textu v Gitu

Uživatel výslovně požaduje odstranit i uložený text; pro deduplikaci má zůstat
jen dočasný identifikátor/hash. Nestačí skrýt položku nebo smazat její soubor
z aktuálního HEAD. Dnešní RSS zachycení ukládá celý surový feed do Gitu, takže
by v historii zůstaly i odmítnuté položky. Tento mechanismus musí být před
zapnutím nové garance nahrazen pro nový příjem následujícím tokem:

1. Celý feed a nevyhodnocené položky patří do omezeného dočasného stagingu
   mimo projektový Git. Retence zahrnuje i NEW položky a chyby skenu; limit
   musí být explicitní v konfiguraci, s kontrolou objemu a expirace.
2. Sken používá přesně připnutou revizi pravidel. Vybraná položka se přijme
   původním projektovým writerem jako samostatný zachycený zdroj a nález.
   Do Gitu nesmí uniknout celý feed obsahující odmítnuté texty.
3. Provenance rozliší hash původního feedu od hashe skutečně uložené položky,
   URL a čas pozorování, pravidla extrakce a filtrů. Filtrované bajty se nesmějí
   vydávat za původní celý feed. Nový kontrakt vyžaduje verzování a validaci.
4. Odmítnutý text se odstraní nejpozději při své expiraci. Po dobu dedup TTL
   zbude pouze projekt/kanál, identifikátor nebo hash a čas expirace, bez
   titulku, výňatku a těla. Identifikátor nesmí být obcházením privacy;
   nesmí obsahovat citlivý text ani tokeny z URL. Po TTL se odstraní také on.
5. Po dobu dedup TTL se stejná položka znovu neskenuje. Po expiraci může nový
   výskyt vstoupit jako NEW. Změny obsahu, kolize identifikátorů a nová revize
   pravidel potřebují explicitní politiku, ne tiché přepsání výsledku.
6. Platné položky se ukládají a synchronizují podle retenčního zadání.
   Gitová historie sama neumí zaručit fyzické odstranění jejich obsahu;
   požadavek na takovou retenci musí být odmítnut nebo mít samostatně
   navržené úložiště. Nelze jej prezentovat jako hotovou TTL funkci.

Dočasné texty nesmějí přežít v run výsledcích, logu, zálohách, SQLite WAL
nebo kopiích stagingu. Implementace musí stanovit podporované úložiště,
cleanup a backup pravidla. Jde o odstranění spravovaných kopií aplikace,
nikoli slib forenzního přepsání SSD nebo cizích záloh. Historický obsah již
uložený v Gitu vyžaduje samostatný inventář a schválenou migraci; tento návrh
neprovádí rewrite historie ani automatické mazání na ostatních uzlech.

## Persistentní hranice a recovery před implementací

Nový staging není obnovitelný projektový index. Jeho provozní stav musí
navazovat na RSS journal a zachovat jednoznačnou obnovu rozpracované operace.
Původní Workspace writer, serializace, receipts a obnova indexu z HEAD zůstávají.

| Přerušení | Požadovaná obnova |
| --- | --- |
| Během HTTP dispatch | Původní RSS unknown/reconciliation; žádný automatický druhý GET kvůli ztracenému stagingu. |
| Po uložení stagingu před skenem | Dokončit nad stejnými bajty, nebo expirovat bez předstírání výsledku skenu. |
| Po rozhodnutí před přijetím do Gitu | Stejný stabilní import ID; žádný duplicitní nález. Expirace nesmí smazat vstup živému writeru. |
| Po Git commitu před potvrzením | Najít původní receipt, obnovit index z HEAD, pak odstranit nepotřebný staging. |
| Během TTL cleanup | Idempotentní dokončení včetně blobů a podpůrných kopií; žádné obnovení odstraněného textu z journalu. |
| Unknown operace na hranici expirace | Zastavit navazující práci, vyřešit vlastnictví/živé handly a bezpečně ukončit přístup k textu; nelze odsunout TTL bez viditelné chyby ani označit úklid za úspěšný. |

Před zapnutím retence potřebuje tento kontrakt ADR pro staging a odstranění,
včetně chování při výpadku uzlu: po startu proběhne cleanup před čtením,
skenem či synchronizací. Neaktivní proces nemůže slíbit smazání ve stanovenou
sekundu; tuto provozní mez musí konfigurace a GUI přiznat.

## Reuse a pořadí ověření

Adaptovat existující RSS parser/transport, filtrované SourceItem, pravidla
`selection.pipeline`, WatchDefinition revize, SourceFinding, WatchSynthesis,
ReportingScheduler a Git sync. Sdílený pool oddělit od jediné reportovací
definice a uchovat vazbu na konkrétní rozhodnutí skenu. Stávající dvoufázový
editor musí zůstat čitelný do explicitní migrace. Nepřidávat druhý projektový
writer, nesynchronizovat provozní SQLite ani převzít cizí externí kód.

Nejprve dokončit identitu vykonavatele a kontrakt retence, poté dočasný příjem
a skeny, pool a jeho GUI, nakonec samostatný editor zpráv nad pool/web vstupy.
Každá část potřebuje cílené ověření před předáním do review:

- Desktop → Omnia zachová UUID; jen přiřazený a místně oprávněný uzel může
  aktivovat sběr. Legacy local neprovede GET. Offline uzel se nenahrazuje.
- NEW → SCANED nastane až po dokončeném skenu; restart nezpůsobí druhý import.
- Odmítnutý unikátní testovací text nebude v žádném Git commitu ani sync
  payloadu a po expiraci ani v podporovaném stagingu/journalu/WAL/logu.
- Dedup blokuje opakovaný sken před TTL a přestane po TTL; testy používají
  řízené hodiny včetně restartu a výpadků na uvedených hranicích.
- Vybrané položky se synchronizují s ověřenou provenance; syntéza na druhém
  uzlu neprovádí další fetch a zachová přesné vstupy, review a privacy.

Související: [nezávislé sledování](independent-monitoring.md),
[filtry](monitoring-filters.md), [syntéza](watch-synthesis.md),
[identita a execution agreement](adr/0080-monitoring-execution-placement.md).
