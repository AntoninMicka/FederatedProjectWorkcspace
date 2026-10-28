<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# DEV-01 — plán migrace roadmapy do Workspace

Stav: **designed**, 28. 10. 2026. Pracovní plán jediné feature DEV-01,
nikoli druhá roadmapa produktu. Aktuální stav a úkoly drží [TODO](../TODO.md).
Importér se zápisem a přepnutí autority zatím nejsou implementované.
Read-only inventuru lze již spustit postupem níže; její výstup je návrh k review.

## Výstup a hranice

Převést plánování produktu do již propojeného projektu Federated Project
Workspace: hlavní roadmapu, otevřené dávky, podmínky splnění, popisy, závislosti
jednotlivých modulů a potřebné historické důkazy. Původní dokumenty uchovat
v přesných bajtech jako dohledatelné zdroje. Výsledkem bude jeden autoritativní
projektový plán podle [ADR 0055](adr/0055-project-task-plan.md) a
[ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md), ne paralelně
editované kopie TODO v aplikaci a ve zdrojovém repozitáři.

Součástí je bezpečný opakovaný import a export Markdown TODO / strojového
balíčku. UI úkolů v IDE, automatické zpracování zpráv a review dokončení
zůstávají DEV-02/DEV-03. Migrace není důvod označit starý checkbox za ověřenou
implementaci ani uzavřít celý milník.

## 1. Připnutá inventura a náhled bez zápisu

Výchozí checkout: `develop` po PR #112, commit
`83d882dbee39803bcb07790e237fd4d400819b16`. Pro skutečný import vytvořit nový
explicitní manifest aktuálně schválených zdrojových revizí; tento výchozí údaj
není pokynem ignorovat změny během návrhu nebo migrovat starou revizi.

| Zdroj | Úloha při migraci |
| --- | --- |
| Hlavní Master Checklist roadmapa | Úplný katalog požadavků, popisy, milníky a gates, včetně modulů již obsažených v dokumentu |
| TODO.md | Právě aktivní dávka a její průběžné důkazy |
| BACKLOG.md | Otevřené budoucí dávky, odklady a priority |
| WORK_LOG.md | Historie, dokončené dávky a doložené výsledky; nepřevádět automaticky na nové otevřené úkoly |
| docs/roadmap-graph.json | Existující explicitní ID, přiřazení milníkům a dependency hrany; nejde o úplný katalog požadavků |
| Relevantní ADR a odkazované specifikace | Zachované podpůrné dokumenty a vazby; nevyrábět nový úkol z každého Markdown odkazu |
| Registrované externí moduly | Explicitně vybrané manifesty a plánovací dokumenty v jejich vlastních připnutých revizích |

Orientační inventura při návrhu: hlavní roadmapa má 150 666 bajtů a 805
checkbox řádků, BACKLOG 62 a WORK_LOG 450 checkbox řádků. Jsou to textové
výskyty, **nikoli počet unikátních úkolů**: zahrnují opakované požadavky,
historii a potenciálně příklady. Před implementací sestavit skutečný coverage
report po sekcích, sémantických položkách a modulech. Stávající graf omezuje
bundle na 1000 uzlů a 4000 checklist položek; limit předem ověřit nad náhledem,
neskrývat nadlimitní data ani limit automaticky nezvyšovat.

Manifest musí pro každý vybraný soubor nést identitu zdrojového repozitáře,
commit, relativní cestu, SHA-256 a velikost, explicitní roli a privacy.
Zahrnout pouze schválené soubory, ne rekurzivní import celého checkoutu.
Neznámý/nedostupný modul, nejasné ID nebo nerozpoznaný blok patří do náhledu
jako nevyřešená položka; nesmějí se potichu přeskočit. Symlinky a lokální
convenience cesty nejsou oprávněním k následování neznámých zdrojů.

Cílový projekt již obsahuje ukázkový plán IMPORT/ADAPTACE/REALIZACE a TASK-01.
Náhled musí ukázat také jeho zachování, nahrazení či mapování. Existující
zprávy a receipts se nemažou. Bridge export je připnutý snapshot, nikoli důkaz
aktuálního serverového HEAD; před zápisem znovu načíst oprávněný cílový stav.

## 2. Kanonické ID, typy a úplnost

- Existující stabilní ID zachovat. Opakované zmínky v roadmapě, backlogu,
  WORK_LOG a grafu propojit s jedinou definicí; rozporné stavy nebo popisy
  předložit k rozlišení, nikoli vyřešit posledním výskytem v souboru.
- Bodům bez ID přidělit ID v prvním schváleném mapovacím manifestu a při
  dalších bězích ho znovu použít. Číslo řádku ani hash aktuálního textu nesmí
  být jedinou identitou: přejmenování by jinak vytvořilo nový úkol.
- Každá zdrojová položka musí skončit jako kanonický uzel, checklist podmínka,
  popis/podpůrný dokument nebo dohledaná reference/duplicita. Náhled ukáže
  původní i cílové místo a důvod klasifikace; nepokryté položky blokují tvrzení
  o úplné migraci.
- Milník → dávka → úkol použít jen pro skutečné plánovací uzly. Široký
  požadavek není automaticky jedna feature dávka. Bez-ID checkbox pod task
  může být checklist; nadpis, gate ani strategický požadavek se nesmí
  mechanicky převést na checklist jen kvůli omezení parseru.
- Rozhodnutí, rizika a požadavky zachovat nejméně v podpůrných dokumentech
  s provenance. Jejich případný převod na nové strukturované entity závisí
  na existujících schématech; nezavádět kvůli importu neodsouhlasenou náhradu
  ER-00/ER-01 ani tvrdit, že libovolný text je již typovaná entita.
- Původní stav zachovat jako zdrojový údaj. Nesoulad starého checkboxu
  a novějšího doloženého výsledku předložit v review. Nevymýšlet testy,
  technické dependency ani úroveň production-ready.

Výsledný kořen TODO zahrne definiční soubory explicitními batch odkazy
`artifacts/UUID/content.md`; každé ID bude mít právě jednoho vlastníka.
Podgrafy zůstanou pouze výběrem existujících ID. Původní bajty dokumentů
nebudou přepsány normalizovaným Markdownem.

## 3. Moduly a jejich autorita

Moduly popsané přímo v hlavní roadmapě zůstávají součástí hlavního projektu.
Samostatně verzované moduly mají podle
[ADR 0026](adr/0026-module-unified-api.md) vlastní plán a historii; místní
přítomnost checkoutu není oprávněním k jeho importu či změně.

Ověřený hostitelský manifest
[Publication & Experiment Registry](../modules/publication-experiment-registry.module.json)
deklaruje vlastní `ROADMAP.md`. Návrh migrace počítá s odděleným propojeným
Workspace projektem pro tento druh modulů. Hlavní projekt bude držet identitu
modulu, provenance a integrační závislosti, nikoli druhou živou kopii jeho
vnitřního plánu. Vlastní modulová ID se nerozpustí v hostitelském namespace;
kolizi řeší explicitní mapování identity zdroje na cílové ID.

Před skutečným importem potvrdit seznam modulů a cílové projekty. Pokud má
být plný modulový plán kanonický uvnitř hlavního projektu, je nejprve potřeba
explicitně vyřešit odchylku od ADR 0026. Nedostupný modul označit neověřený;
neprohlašovat jeho roadmapu za přenesenou. Historii cizího repozitáře ani
runtime, credentials a build výstupy neimportovat jako součást plánu.

## 4. Import, opakování a konflikt

První náhled nabídne přesný diff artefaktů, mapování ID, coverage report,
konflikty, limity a všechny položky, které by změnily aktuální cílový plán.
Potvrzení se váže na digest náhledu, zdrojové hashe, cílový projekt a expected
HEAD. Výchozí privacy nesmí import automaticky uvolnit.

- Stejný operation ID a stejný request vrací původní receipt bez dalšího
  commitu; stejný obsah v nové operaci nesmí vytvořit duplicitní entity.
- U změněného zdroje porovnat poslední importovanou verzi, nový zdroj a
  současný cílový obsah. Ruční změnu ve Workspace nepřepsat; oboustrannou
  změnu stejného pole/bloku označit jako konflikt k review.
- Odstraněný zdrojový bod označit jako kandidáta k vyřazení, nikoli smazat
  bez review. Přejmenování s existující mapovanou identitou zachová ID.
- Změna zdrojové revize, cílového HEAD, include vazby nebo oprávnění po
  preview zneplatní schválení; nový náhled musí ukázat nové skutečnosti.
- Cílový bundle validovat jako celek ještě před prvním zápisem: jedinečnost
  ID, typy, vazby, cykly, privacy a dostupnost všech definičních artefaktů.

## 5. Zápis a recovery

Reuse/adapt: `spikes/task_graph.py` pro bundle a validaci,
`spikes/roadmap_graph.py` pro již explicitní ID/závislosti,
`spikes/source_import.py` pro přesné zdroje/provenance a bounded batch,
`spikes/artifacts.py` a `Workspace.transact` pro jediný writer.
Z NotebookLM importu převzít vzor preview/digest/receipt, nikoli jeho
NotebookLM parser ani logiku vytvoření nového projektu místo existujícího.
Veřejný a lokální reuse katalog byly zkontrolovány; nový framework, druhá
stavová databáze ani obecný rewriter Markdownu se nezavádí.

Platí [ADR 0003](adr/0003-coordinated-operation.md) a ADR 0059. Před
implementací ověřit přesné integrační možnosti víceartefaktové transakce:

| Hranice pádu | Očekávané chování |
| --- | --- |
| Čtení / preview, před zápisem journalu | Cílový projekt zůstává beze změny; nový náhled lze zopakovat |
| Po připravení journalu, před Git commitem | Obnova přes stejnou operation/request identitu; částečně zapsané soubory se nesmějí vydávat za nový platný plán |
| Po Git commitu, před publikací indexu | Git commit je autoritou; index se obnoví z HEAD a nesmí nabízet starou projekci jako aktuální |
| Po publikaci, před vrácením odpovědi | Retry vrátí uložený receipt bez dalšího commitu |
| Mezi importy různých projektů | Každý má vlastní receipt; hlavní projekt nesmí tvrdit globální dokončení, pokud modulový projekt nedokončil import |
| Mezi cílovým importem a úpravou zdrojových dokumentů | Ještě nedošlo k přepnutí autority; stav předání výslovně čeká na dokončení obou kroků |

Kořen a jeho nové definiční soubory publikovat v jedné validované projektové
operaci, nikoli jako nezávislé commity s dočasně neplatnými odkazy. Pokud to
existující API neumí, nejprve rozšířit konkrétní doménovou operaci a její
recovery testy. Nepoužít přímé editace projektového Gitu ani SQL indexu.

## 6. Izolovaná zkouška a skutečné předání

Nejprve migrovat připnutý reálný vzorek do izolovaného projektu: obsahující
hlavní sekci, dávku, checklist, historický důkaz a samostatný modulový plán.
Potom ověřit celý vybraný rozsah a teprve před skutečným zápisem předložit
konkrétní náhled aktuálního existujícího projektu k potvrzení.

Předání autority má dva výslovné kroky, nikoli předstíranou transakci mezi
repozitáři:

1. Importovat schválený bundle; porovnat coverage report a skutečný plán v
   aplikaci, zachování popisů/odkazů/modulů i export do IDE.
2. Po akceptaci označit původní plánovací dokumenty jako archivovaný snapshot
   s odkazem na kanonický Workspace projekt/revizi. Ve zdrojovém repozitáři
   zachovat AGENTS, ADR a vývojové návody; upravit workflow odkazy tak, aby
   už nevyžadovaly druhou živou evidenci v TODO/BACKLOG/WORK_LOG. Tento krok
   musí být součástí konkrétního schváleného migračního diffu; před akceptací
   původní evidenci nemažeme ani neoznačujeme za přestěhovanou.

Před přepnutím lze návrh zahodit bez změny autority. Po přepnutí se změny
opravují novou verzovanou Workspace operací; návrat ke zdrojovým dokumentům
vyžaduje explicitní předání včetně mezitím vzniklých změn. Git reset nebo
smazání importovaných dat není recovery postup.

## Ověření a podmínky dokončení

- Každý vstupní bod má doložený cíl nebo explicitně schválenou klasifikaci;
  žádná ztracená sekce, modul, checklist, popis či historický důkaz.
- Cílené testy: opakovaný import, konflikt ruční změny, přejmenování,
  odstranění, kolize ID/modulů, nedostupný modul, stale HEAD, cyklus,
  chybějící include a překročení limitů.
- Injektované pády na každé výše popsané persistentní hranici; po restartu
  jediný konzistentní plán a jeden receipt pro původní operaci.
- Po implementaci plná unittest brána podle AGENTS a relevantní kontroly
  JavaScriptu; po samotném návrhu stačí konzistence, odkazy a diff.
- Fyzicky ověřit existující projekt v desktopovém Workspace a jeho IDE
  export; izolovaný test nesmí být prezentován jako skutečná migrace.
- Uživatel akceptuje přenesený obsah i předání autority. DEV-01 se uzavře
  odděleně od DEV-02/DEV-03 a od stavu doručení PR.

## Spustitelná read-only inventura

```bash
python3 -m scripts.roadmap_migration_preview \
  --repository . --revision SOURCE_COMMIT \
  --output /tmp/dev-01-inventory
```

`SOURCE_COMMIT` nahraďte schválenou Git revizí; výstupní adresář nesmí
existovat. Bez výslovného výběru externího modulu report ukáže
`unselected-module` místo tvrzení, že je modul zahrnutý. Pro každý vybraný
modul přidejte `--module MODULE_ID MODULE_REPOSITORY MODULE_COMMIT`;
repozitář i revizi zadává uživatel explicitně. Místní cesty modulů se do
reportu nekopírují a žádné Markdown odkazy se automaticky nenásledují.

`inventory.json` obsahuje source hashe, přesné revize, lokátory výskytů
včetně byte offsetů, explicitní ID, návrhy mapování anonymních bodů,
původní checkbox stavy, dependency hints a seznam odkazovaných dokumentů.
`summary.md` shrnuje pokrytí a opakovaně zmíněná ID. Report není autoritou
úkolů a vždy uvádí `import_ready: false`, `approval: pending-review`;
privacy každého zdroje čeká na review, neodvozuje se z místní dostupnosti.

Návrhy definic preferují aktuální TODO, potom BACKLOG, poté historickou
sekci a nakonec samotný požadavek. To slouží k usnadnění obsahového review,
nikoli k automatickému řešení rozdílných popisů či ověření akceptace.
Bez-ID body požadavků dostanou předběžná scoped `MIG-REQ-*` ID bez převodu
na implementační úkoly; historické důkazy se nepřepisují na nové úkoly.
Před apply musí být schválená mapa samostatně uložená a znovupoužitá při
změnách zdroje; pořadí řádků není stabilní identita pro opakovaný import.

Tato fáze nevolá Workspace API ani nepoužívá credentials, nevytváří commity
ani index/journal a neprovádí skutečnou migraci. Stav konkrétního ověření
patří pouze do TODO; zde je postup, nikoli druhý stavový záznam.

## Read-only náhled hierarchie a cílového diffu

Nad uloženou inventurou lze nyní sestavit kandidátní profilovaný plán:

```bash
python3 -m scripts.roadmap_migration_plan \
  --inventory /tmp/dev-01-inventory/inventory.json \
  --source-root REPOSITORY_ID REPOSITORY_PATH \
  --output /tmp/dev-01-hierarchy
```

Zadejte `--source-root` pro každý repozitář v inventuře, včetně hostitele
`federated-workspace`. Přesné source bajty se znovu ověří vůči zaznamenaným
revizím a hashům. Výstupem jsou TODO návrhy, katalogy požadavků/historie,
zdrojové archivy a `mapping.json` se všemi lokátory i plnými původními bloky.
Žádný report nepředstavuje autoritativní plán nebo výsledek importu.

Výchozí pravidlo do profilované části zařazuje aktuální feature a historicky
completed feature dávky ze stávajícího autoritativního katalogu. Široké
backlogové body zůstávají požadavky; samotný grafový uzel není důkaz jedné
reviewovatelné feature. Pokud kandidát závisí na nezahrnutém požadavku,
nesmí se hrana vynechat a uzel vydávat za ready. Uzel i původní hrana zůstanou
v podpůrném katalogu a report ohlásí dependency hranici k review. Checkbox
konflikt v různých zdrojích se automaticky nevyřeší.

Tasky se odvozují jen z explicitních ID uvnitř známé batch sekce; checklist
podmínka patří tasku a nevytváří duplicitní requirement uzel. Všechny
popisy a neznámé konstrukce zůstávají v úplných zdrojových blocích a přesných
archivech; první profilovaný náhled u uzlů odkazuje na zdrojový dokument.
Pokud původní označení obsahuje jen ID a úroveň výsledku, titulek může být
výtahem prvního původního popisného řádku; mapping to výslovně označuje
`title_is_excerpt` a zachovává celý popis. Validační výsledek zatím dokládá
jen task graf, nikoli schéma metadat, typované registry požadavků/rizik,
kompletní artefaktový diff nebo připravenost skutečného apply.

Pro modul použijte `--module-placements PLACEMENTS_JSON`: explicitní seznam
objektů s `repository_id`, `batch_id`, `milestone_id`, `milestone_title`,
`source` a `heading`. `source` je klíč z inventury a `heading` přesný řádek
připnuté roadmapy; titul musí odpovídat tomuto nadpisu. Přiřazení nesmí
vzniknout jen z místní přítomnosti modulu. Nezaškrtnutý batch nadpis se
nepřepne na completed pouze proto, že jsou zaškrtnuté všechny jeho tasky.

Volitelné `--target NODE_CONFIG PROJECT_ID` načte skutečný registrovaný
projekt přes read-only Git cestu, bez inicializace journalu/indexu. Přidá
původní hlavní TODO, jeho hash a metadata, expected HEAD a `target.diff`.
Report ukáže původní ID, která v návrhu nejsou, a požadavek na archivování
původní revize a zachování zpráv. Neodvozuje jejich nové aliasy a nic neukládá
do projektu. Cílový HEAD musí skutečný apply později znovu ověřit.

`--reuse-mapping MAPPING_JSON` znovu použije zmrazené identity a rozhodnutí
nad stejnou inventurou; neslučuje se s novými module placements. Změna
inventurního digestu vyžaduje explicitní rebase a review, nikoli nové ID
odvozené z posunutého řádku. Bez nového `--target` jde o replay původního
cílového náhledu, nikoli nové ověření aktuálního cílového HEAD. Všechna
rozhodnutí zůstávají návrhem a flag `import_ready` je false.
