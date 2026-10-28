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
- [ ] [in progress] **DEV-01-C — import preview a stabilní identity (implemented).**
  Deterministický náhled, přesné source bajty, provenance, mapování existujících
  a nových ID, validace úplného bundle a kontrola limitů před zápisem.
  Pokračování: `/tmp/dev-01-hierarchy-reviewed/summary.md` a `mapping.json`.
  Aktualizovaná inventura čte host commit `f55c0ec`, stejný modulový commit
  `446d980`; zdrojové bajty jsou součástí privátního reportu. Pokryto je všech
  1456 výskytů včetně nadpisových definic, nikoli jen 1361 checkboxů.
  Profilovaná podmnožina prošla stávajícím task-graph validátorem: hlavní
  projekt 3 milestone / 16 batch / 82 task, modul 1 milestone / 1 batch / 8 task.
  Strategické požadavky a nezahrnuté historické položky zůstávají v katalogu
  s původními ID/provenance; nejsou automaticky povýšeny na feature dávky.
  Checklist podmínky mají vlastníka v tasku, nikoli duplicitní požadavek.
  Celková akceptace dávky se neodvozuje z počtu zaškrtnutých podúkolů.
  Dva historicky completed uzly `F-M5-CHAT-HISTORY-01` a
  `F-M5-SYNC-CONTROLS-01` mají dependency hranici proti plánovanému rozsahu;
  rozporné hrany i původní stavy se zachovaly, do nové profilované části se
  bez rozhodnutí nepromítají. Nejde o nové rozhodnutí jejich stav změnit.
  Read-only načtení skutečného cíle potvrdilo HEAD `c36af3e` a čistý strom.
  Report obsahuje původní hlavní TODO a konkrétní `federated-workspace/target.diff`.
  Původní ukázkové MILESTONE-01/02/03, BATCH-01 a TASK-01 nejsou v novém návrhu:
  před skutečným nahrazením se musí archivovat původní obsah/metadatový kontext
  a zachovat zprávy s původní task/revision vazbou; aliasy se nevymýšlejí.
  Zmrazený mapping je svázán s inventory SHA-256; replay dal totožný výsledek,
  změněný zdroj vyžaduje explicitní rebase. Návrhy ID a definic nejsou tímto
  uživatelsky schválené a `import_ready` zůstává false.
  Zbývá úplný náhled metadat/operace přes všechny artefakty, review širokých
  požadavků, potvrzení modulového cíle a zdrojové identity při změně revize;
  samotný validní task graf není validací celého importu.
  Reuse/adapt: existující source katalog `_catalog`, profilovaný task graph,
  Projects.repository (bez inicializace indexu/journalu). Zápisový lifecycle
  ADR 0003 se nemění; tento krok zapisuje jen nový privátní report do /tmp.
  Pád při vytváření reportu nemění zdroj ani cílový projekt a není receipt
  importu. Další report používá nový adresář, původní se nepřepisuje.
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

`python3 -m unittest tests.test_roadmap_mapping tests.test_roadmap_migration tests.test_task_graph tests.test_roadmap_graph tests.test_spdx -v`:
37 testů OK. Nové testy ověřují celé source coverage, profil a checklist,
zachování originálů, explicitní modulové přiřazení, nevymyšlenou akceptaci,
source-state konflikt, dependency hranici bez falešného ready stavu, integritu
zmrazené mapy a odmítnutí neřešeného rename, plné zdrojové bloky i víceřádkové
názvy a skutečný read-only target diff bez inicializace Workspace stavu.
Skutečný běh nad připnutými zdroji a cílovým hlavním TODO prošel; následný
CLI replay souhlasil s uloženým mappingem beze změny. Předchozí inventurní
ověření 17 testů je rozšířeno tímto cíleným během. Celá finální runtime brána
zbývá před dokončením dávky. Žádný projektový zápis ani fyzická migrace
neproběhly.
