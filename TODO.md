<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — DEV-01

Aktivní feature dávka: **Roadmapa jako projektová data a export úkolů**.
Milník: vlastní rozvoj produktu, návaznost M6. Původní požadavek: DEV-01,
uživatelská upřesnění 28. 10. 2026 — roadmapa včetně vložených modulů;
po PR #112 připravit nejprve plán migrace.
Skutečná větev: `feature/dev-01-roadmap-migration`, založena z čistého
`develop` `83d882d` po merge DEV-IDE-TODO-01 v PR #112.
Základ/cíl jediného PR: `develop`. PR této dávky není vytvořen ani sloučen.
Cíl dávky: **implemented → PoC validated**; návrh je **designed**,
read-only inventura **implemented**.
Návrh: [plán migrace](docs/roadmap-migration.md). Samotná migrace ani přepnutí
autority zatím neproběhly. Návrh uživatel schválil; probíhá inventura
a příprava mapovacího náhledu.

## Původní rozsah a akceptace DEV-01

Po `PLAN-TASK-GRAPH-01` převést uživatelem vybraný rozsah roadmapy do verzovaných entit požadavků, milníků, feature dávek, rozhodnutí, rizik, závislostí a úkolů bez vytvoření druhého autoritativního plánu. Akceptace: stabilní ID a provenance na zdrojovou revizi, opakovaný import bez duplikace, konflikt ruční a zdrojové změny, odstraněný/přejmenovaný bod a export Markdown TODO i strojově čitelného task balíčku se scope, dependencies a acceptance. Export nemění stav zdrojového úkolu; interní roadmapa použije stejný obecný plánovací kontrakt jako ostatní projekty. Uživatelské doplnění 28. 10. 2026: migrovat také vložené moduly a doplňkové roadmapy s jejich úkoly a popisy; zachovat hierarchii, include vazby, stabilní ID a provenance. Před migrací určit kanonický zdroj každé definice, ověřit úplnost vložených modulů a stanovit přechod autority do Workspace bez konkurenčního živého plánu ve zdrojovém repozitáři.

Hranice: import vybraných dokumentů do existujícího projektu, explicitní
mapování modulů na cílové projekty, úplná provenance, bez druhého živého plánu.
UI úkolů v IDE a automatické review zpráv zůstávají v DEV-02/DEV-03.
Závislosti PLAN-TASK-GRAPH-01, ADR 0059 / file-plan editor a bridge jsou
začleněné do základu. Nové entity požadavků/rozhodnutí/rizik se neprohlašují
za implementované místo jejich zachování v podpůrných dokumentech.

## Úkoly dávky

- [x] [completed] **DEV-01-A — návrh migrace (designed).**
  Inventura zdrojů a existujících kontraktů, mapování ID/typů, moduly,
  preview, konflikty, recovery a předání autority. Podrobný návrh v odkazu výše.
  Jde o připravený návrh k review, nikoli uživatelskou akceptaci migrace.
- [ ] [in progress] **DEV-01-B — potvrzený manifest a mapování (designed).**
  Přesné soubory/revize, cílový existující projekt, seznam a cíle externích
  modulů, ID bez identity, konflikty a zacházení s ukázkovým cílovým plánem.
  Výstup: úplný coverage report; žádné tiché vynechání nebo automatické smazání.
  První konkrétní report: `/tmp/dev-01-inventory-final-20261028/summary.md`
  a `inventory.json`. Zdrojový host commit `27d88d4`, explicitně vybraný
  publikační modul commit `446d980`; 13 souborů, 1361 checkbox výskytů,
  570 explicitních ID v rámci zdrojových repozitářů a 864 checkboxů bez ID.
  Nejde o počty samostatných úkolů. Návrh mapuje 821 anonymních bodů na
  požadavky, 4 na strategické požadavky a 39 na historické důkazy;
  18 opakovaně zmíněných ID má navržené jediné místo definice a zachované
  všechny zdrojové výskyty. Všechny 75 existující dependency uzly mají
  dohledatelnou definici, graf je validovaný. Nebyl nalezen rozpor samotných
  checkbox stavů; shoda stavu není důkaz sémantické shody popisů.
  Mapování zůstává návrhem (`mapping_approved: false`), nikoli potvrzeným
  plánem: zbývá obsahové rozlišení typů/hierarchie a konkrétní cíle modulů
  i zacházení s ukázkovým cílovým plánem. Zdrojové bajty a hashe zůstávají
  dohledatelné; chybějící ID nejsou bez review vydávána za executable tasky.
  Předběžná MIG-REQ ID platí jen pro tento připnutý návrh; před importem se
  musí schválená mapa persistovat, ne generovat znovu po přejmenování.
  Reuse/adapt: Git wrapper, validátor modulového manifestu a topologické
  ověření existujícího roadmapového grafu. Žádná síťová volání ani zápis
  do projektu, Gitu, SQLite indexu či journalu. Pád inventury cílová data
  nemění; neúplný lokální report lze vytvořit znovu v novém adresáři.
- [ ] [planned] **DEV-01-C — import preview a stabilní identity (implemented).**
  Deterministický náhled, přesné source bajty, provenance, mapování existujících
  a nových ID, validace úplného bundle a kontrola limitů před zápisem.
- [ ] [planned] **DEV-01-D — bezpečný apply a opakovaný import (implemented).**
  Stávající autorizovaný writer, expected HEAD/digest, víceartefaktová
  transakce, receipts, idempotence, třícestné porovnání, rename/removal review
  a crash recovery podle plánu. Žádné přímé SQL nebo obcházení Workspace.
- [ ] [planned] **DEV-01-E — izolovaná zkouška a export (PoC validated).**
  Reálné připnuté zdroje a modulový vzorek, Markdown/strojový task export,
  konflikty, změny revizí, limity a injektované pády. Po poslední relevantní
  změně spustit celou unittest bránu.
- [ ] [planned] **DEV-01-F — fyzická migrace a předání autority (PoC validated).**
  Potvrzený konkrétní náhled → existující Workspace projekt, ověření obsahu
  v aplikaci i IDE. Samostatně akceptovat úplnost modulů a úpravu workflow
  zdrojového repozitáře; žádné předčasné odstranění původní evidence.
- [ ] [planned] **DEV-01-G — závěrečná akceptace a předání dávky (PoC validated).**
  Konsolidovat důkazy, archivovat dávku a odklady, vyčistit TODO a připravit
  jeden PR do develop; spuštění další feature není součástí této dávky.

## Ověření aktuálního kroku

`python3 -m unittest tests.test_roadmap_migration tests.test_roadmap_graph tests.test_spdx -v`:
17 testů OK, z toho 10 testů inventury. Pokryté jsou připnuté bajty při
změně pracovního stromu, stabilita náhledu, Unicode byte offsety, ignorování
příkladů/komentářů, neukončené bloky, symlink/missing/nadlimitní zdroj,
konfliktní checkbox stavy bez automatického výběru, scoped module ID,
nevybraný/neshodný modul, podadresář bez vlastního repozitáře, neplatné
hrany/cykly a kolize navrhovaných ID. Skutečný read-only běh nad uvedenými
revizemi vytvořil report bez zápisu do Workspace. Celá finální runtime brána
bude spuštěna po poslední relevantní změně před dokončením celé dávky.
