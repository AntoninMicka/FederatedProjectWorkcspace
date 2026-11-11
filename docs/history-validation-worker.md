<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Ověřování historie mimo HTTP obsluhu

Při příjmu projektu se 139 commity překračovala Omnia 60sekundový rozpočet
ve fázi `receive-verify-history`. Ve stejném intervalu trvalo otevření jiného
projektu 5,8 s. Volná aplikační linka sama neizoluje výpočetní zátěž Pythonu.
Tato oprava zachovává synchronní federační protokol, ale přesouvá sémantické
ověřování Git historie do jednorázového procesu.

## Validace a kapacita

`validate_history` uchovává nejvýše dva snapshoty a jejich ověřená metadata
v lokální cache jednoho volání. Interní kontrola přechodů použije tato metadata;
neprovádí znovu kompletní parsování obou snapshotů pro každou hranu historie.
Veřejné `validate_transition` vždy nejprve validuje oba vstupy. Každý rodič,
privacy, neměnnost zdrojů, provenance a reportingové reference se kontrolují
dál. Po vyřazení z cache se snapshot znovu ověří; nejde o dlouhodobou cache
validace, důvěry ani oprávnění.

Při exportu se úplná historie validuje v přesném výsledném bundlu. Odpadá
duplicitní úplný průchod zdrojovým repozitářem před vytvořením téhož bundlu.
Kontroly registrace, čistého pracovního stromu, zachycených refs a jejich
opětovné ověření před zveřejněním zůstávají zachované.

`history_validation.validate_histories` spustí aktivní aplikační Python
v izolovaném importním režimu, se stejným důvěryhodným zdrojovým balíkem.
Worker dostane pouze cestu izolovaného repozitáře, přesné heads, project ID,
privacy scope a absolutní deadline. Nedostane autoritu k publikaci.
Kapacita je jeden validační proces na backend, bez čekací fronty. Linuxový
worker i jeho Git potomci mají nižší CPU prioritu (`nice +10`). Izolace procesu
odděluje CPU/GIL a lifecycle, není sandboxem pro spouštění nedůvěryhodného kódu.

Původní 60sekundový rozpočet zahrnuje přípravu izolovaného repozitáře,
start workeru a všechny heads. Deadline se při předání neprodlužuje.
HTTP vlákno čeká omezeně na výsledek; ostatní HTTP linky a jejich rezervovaná
kapacita zůstávají dostupné. Nejde o asynchronní protokol s novým job ID.
Stávající projektové zámky se kvůli výpočtu nedrží; oprávnění a HEAD se před
publikací znovu kontrolují původními mechanismy.

## Crash boundaries a recovery

- Před úspěšnou validací existují pouze dočasné Git objekty, žádný nový inbound
  publikační intent. Timeout, nedostupná kapacita, pád či chybná odpověď workeru
  nesmějí vést k publikaci. Nejsou důkazem neplatnosti dat.
- Při timeoutu rodič ukončí celou procesní skupinu workeru včetně Git potomků
  a počká na ukončení workeru před úklidem dočasných vstupů. Kapacita se uvolní
  i při chybě startu nebo protokolu. Úspěch po deadline se odmítne.
- Při násilném pádu samotného backendu se výsledek workeru ztratí; worker nemá
  publikační pravomoc a jeho vlastní deadline omezuje další práci. Případné
  zbylé dočasné soubory nejsou recovery autoritou. Další pokus používá původní
  uložený outbound požadavek a znovu jej ověří.
- Po validaci se používá původní inbound journal, Workspace transakce, Git CAS,
  index a receipt podle [ADR 0081](adr/0081-complete-project-data-sync.md).
  Změna oprávnění během validace nadále zabrání publikaci. Dokončený replay
  zůstává v původní přesné idempotentní větvi.

## Opakování a diagnostika

Automatický scheduler po timeoutu či obsazení odloží stejný cíl o 60, 120,
240, 480 a nejvýše 900 sekund. Ostatní cíle může obsloužit dál. Ruční pokus
čekání obchází; jeho úspěch odstup zruší. Nemění se způsobilost projektů,
identita operace, uložené bajty ani oprávnění opakování. Odstup je omezená
volatilní projekce (nejvýše 128 cílů); restart obnoví původní scheduler,
nikoli novou persistentní frontu.

Lokální Git timeout má stav `busy`, nikoli tvrzení o offline protistraně.
Nedostupný validační proces má prostředek `history-validation`; jeho chybu
nelze zaměnit za odmítnutí neplatných dat. Přehled zobrazí prostředek i
nejbližší možný automatický pokus. Původní operace zůstává uložená.

## Měření a ověření

Na témže lokálním HEAD se 139 commity klesl počet úplných validací snapshotu
z 425 na 145; DAG může vyžadovat opakované načtení po vyřazení z omezené cache.
Stejný profilovaný průchod klesl z 24,959 s na 14,615 s. Samostatný neprofilovaný
worker doběhl za 11,372 s a rodič spotřeboval asi 0,001 s CPU. Tato měření
nejsou měřením odezvy Omnie ani příslibem stejného času na jiném hardwaru.

Cílené testy ověřují neměnnost zdrojů a privacy, obnovu stejným požadavkem po
timeoutu bez nového inbound intentu, dokončený replay, změnu oprávnění během
ověřování, chybu startu, chybnou odpověď workeru, ukončení jeho potomků,
sdílený deadline všech větví a zachování nativních zápisů při exportu.
Test skutečného autentizovaného HTTP projektu i uzlové akce proběhne během
CPU zátěže odděleného procesu. Retry testy kontrolují odstup po jednotlivých
cílech, reset po úspěchu a omezenou velikost volatilní projekce.

Závěrečný běh: **2050 testů, OK, 59 přeskočených**. Použity byly čtyři
izolované lokální kopie finálního zdrojového obsahu a projektní CI runner
`scripts/test_shards.py --shard N --shards 4`. Manifest pokrytí ověřil všech
187 top-level modulů právě jednou. Shardy: 519/509/517/505 testů, všechny OK;
nejdelší doběhl za 519,318 s. Přeskočené volitelné testy nejsou důkazem jejich
provedení. JavaScript prošel `node --check` a diff `git diff --check`.

Předchozí běhy odkryly dvě chyby testovacích předpokladů: dlouhý souhrnný
scénář znovu používal starý request handle po 60 sekundách a kontrola
ukončení potomka nepočítala s jeho odstraněním během čtení `/proc`.
Navazující samostatné čtení nyní otevře nový běžný bounded handle, bez změny
produkčního limitu. Kontrola potomka přijme ukončený či již odstraněný proces,
ale nadále odmítá běžícího; opakování této kontroly prošlo dvanáctkrát za sebou.

Živá akceptace vyžaduje sjednocené verze uzlů, úspěšný původní přenos a běžné
otevírání projektů během synchronizace. Lokální testy ani instalace samotná
tuto akceptaci nenahrazují.
