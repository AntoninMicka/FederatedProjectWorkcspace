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

## Upřesnění uživatele v rámci DEV-01

Cílová roadmapa ve Workspace je celá testovací a není zdrojem dat. Uživatel
výslovně autorizoval její kompletní nahrazení; nepřenášet testovací úkoly,
vazby ani stavy a nevytvářet z nich povinné migrační konflikty. Staré zprávy
jsou transportní historie, nikoli požadavek zachovat testovací plán.
Migrace má zahrnout i historické a realizované úkoly a dávky. Obecné myšlenky
mají být volným popisem pod jasným milníkem/dávkou; nejednoznačný obsah
samostatnými `.md` podklady. Nevyrábět pro něj umělé úkoly ani dávky.

## Úkoly dávky

- [x] [completed] **DEV-01-A — návrh migrace (designed).**
  Inventura zdrojů a existujících kontraktů, mapování ID/typů, moduly,
  preview, konflikty, recovery a předání autority. Podrobný návrh v odkazu výše.
  Návrh byl uživatelem schválen a následně upřesněn výše; fyzická migrace
  zatím akceptována ani provedena nebyla.
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
  modulových projektů. Nakládání s testovacím cílem již není otevřená otázka:
  úplně ho nahradit bez používání jeho obsahu jako zdroje. Zdrojové bajty a hashe zůstávají
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
  Historický náhled v1: `/tmp/dev-01-hierarchy-reviewed/summary.md` a `mapping.json`.
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
  tehdy se uvažovalo o archivaci v novém plánu. Tuto podmínku nyní ruší
  výslovný pokyn uživatele: testovací plán není zdroj a nepřebírá se. Git
  historie/transportní receipts se tím automaticky nemažou; aliasy nejsou potřeba.
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
  Aktuální náhled v2: `/tmp/dev-01-history-inclusive-preview/summary.md`,
  host source commit `145a02e`, module source commit `446d980`. Profilovaný
  hlavní plán má 10 milníků / 93 dávek / 384 úkolů; modul 10 / 1 / 8.
  Podporovaná část nyní zahrnuje všechny kanonické historické nadpisové
  záznamy WORK_LOG, i mimo starý graf. Samostatné starší úkoly bez doložené
  dávky zůstávají s původními ID/stavy v Markdown textu u milníku nebo v
  samostatném podkladu; nevytváříme fiktivní feature batch.
  Celkem 193 popisových Markdown dokumentů: 111 přiřazených vlastníkovi,
  82 samostatných. Volné myšlenky nejsou vykazované jako implementační tasky.
  M0/M1 mají stav převzatý jen z explicitních gate důkazů hlavní roadmapy.
  Historicky dokončená F-M5-CHAT-HISTORY-01 zůstává v roadmapě; vazba na
  plánovanou F-M5-TRUST-01 je historický kontext, nikoli důkaz dokončení TRUST.
  Politika `replace-test-plan` má autorizaci uživatele, ale `apply_validated`
  zůstává false, dokud není připraven celý artefaktový zápis. Testovací cílový
  obsah není v source_refs, normalizovaných uzlech ani odvozených podkladech.
  Aktuální report prošel task-graph validací; zůstávají otevřené úplné metadata,
  přemapování zdrojových odkazů, zápis/recovery a skutečné nasazení migrace.
  Bod 1 požadovaný uživatelem — sestavení celé logické operace — je připraven:
  `/tmp/dev-01-import-operation/summary.md` a `operation.json`. Zdrojový host
  commit `06ffda3`, modul `446d980`; inputy jsou připnuté v
  `/tmp/dev-01-step1-source` a `/tmp/dev-01-step1-mapping`.
  Hlavní projekt: 196 artefaktů / 392 souborů; modul: 17 / 34.
  Payload obsahuje hlavní plány, 193 Markdown popisů/podkladů, přesné
  originální zdroje, sidecar metadata, scoped mapování ID, source manifesty
  a propojení na navržený modulový projekt. Root ID a immutable metadata
  hlavního TODO zůstávají zachované; testovací text ani mutable popisky
  nejsou importovanými zdroji. Interní text modulu zůstává v modulovém payloadu.
  Manifest obsahuje samostatné operation ID, dependency modul → host,
  create/replace akce a hashe všech souborů; žádné implicitní mazání ostatních
  entit. Module project UUID je návrh podporovaný seeded create, fyzická
  cesta se ještě nezadává ani nevytváří.
  Základní schema a task graph celých payloadů prošly, včetně zachování
  ID/typů/rodičů a checkbox stavů. Bod 2 (úplná kontextová předzápisová
  validace) byl proveden read-only validátorem proti celému živému snapshotu;
  report je `/tmp/dev-01-prewrite-review-3/summary.md` a `review.json`.
  Devět kontrol prošlo: uzavření manifestu/blobů/payload mirror, lokální
  autor, modulový seed a jeho task graph, nativní replica policy, čistý
  očekávaný host HEAD, prázdný journal a celý sloučený snapshot včetně
  `validate_transition` a task graphu.
  První prověrku blokovalo 184 nepřevedených relativních odkazů v odvozených
  host dokumentech (72 odlišných cílů) a nezvolená fyzická cesta nového modulu.
  Oba blokátory jsou v opraveném balíku odstraněné. Vybrané zdroje se
  odkazují na importované artifact cesty; nevybrané cíle zůstávají čitelnou,
  neaktivní zdrojovou cestou. Modulová operace explicitně drží cíl
  `/home/antonin/Projekty/publication-experiment-registry`; read-only kontrola
  mimo vývojový sandbox potvrdila volný cíl, state adresář, skutečná práva
  parentu a nepřekrývání chráněných cest. Nic nebylo vytvořeno.
  Nový balík `/tmp/dev-01-import-operation-v3` má SHA-256
  `ae0df1d730259fa233ef87f6a253969674d96e6b2e08c7bc080a0476fa558e99`;
  `/tmp/dev-01-prewrite-review-v3-host` hlásí 11 passed / 0 blocked /
  3 needs-review.
  Review vyžaduje klasifikace privacy všech 13 zdrojů a devět externích
  odkazů, jejichž dostupnost nebyla síťově ověřena. Validátor je uzavřený,
  nic nevytváří v projektu ani state a neoznačuje tyto nálezy za prošlé.
  Writer/recovery a fyzický import zůstávají otevřené.
  `import_ready` je false. Vznik balíku nepoužívá projektový journal ani
  zapisující Workspace: pád před finálním manifestem zanechá jen neúplný
  report, který není importním receiptem. Retry použije zmrazené payloady.
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

`python3 -m unittest tests.test_roadmap_validation -v`: 3 nové validační
testy OK. Pokrývají úspěšné sloučení celého živého snapshotu bez zápisu,
ponechání chybějící cesty/privacy jako otevřených stavů a rozlišení
relativního a neexistujícího artifact odkazu. Skutečný report nad aktuálním
balíkem potvrdil nezměněný živý HEAD a nulový rozpracovaný journal.
Společný cílený běh validačních, bundle, mapping, inventory, task-graph,
roadmap-graph a SPDX testů po poslední změně: 52 testů OK. Log:
`/tmp/dev-01-blocker-tests.log`. Celá finální unittest brána zůstává pro
uzavření dávky.

`python3 -m unittest tests.test_roadmap_bundle tests.test_roadmap_mapping tests.test_roadmap_migration tests.test_task_graph tests.test_roadmap_graph tests.test_spdx -v`:
47 testů OK, z toho 6 balíkových testů. Pokryto je sestavení celých metadat,
shoda plánu, zachování přesných source bajtů a původní identity rootu,
nepoužití testovacích dat, izolace modulového obsahu, navržený seed root,
deterministický rebuild, ochrana proti relaxaci privacy a odmítnutí chybějících,
změněných či nadbytečných blobů i přepsání existujícího balíku. Dřívější
historické/grafové testy zůstávají. Skutečný běh vytvořil 213 artefaktů /
426 souborů (3 589 550 bajtů logických payloadů); z disku byly zpětně
porovnány přesné bajty všech souborů. Živý projekt se nezměnil.
Celá finální runtime brána zbývá před dokončením dávky; bod 2 a zápis/recovery
nejsou těmito shape testy označené za dokončené.
