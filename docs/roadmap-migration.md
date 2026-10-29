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

## Revize návrhu po prvním fyzickém importu

Rozhodnutí 29. 10. 2026: první vygenerovaný import ani jeho deep-check
proposal queue nejsou vstupem další migrace. Lokální kontrola ukázala, že
transformace sice zachovala mnoho textových výskytů, ale rozhodovala izolované
source clustery proti již chybnému cíli. Tím ztratila sekvenční význam celých
dávek a dokázala navrhnout strukturálně platné, ale sémanticky nesprávné
zařazení. Tento výsledek se nebude ručně opravovat ani aplikovat po částech.

Nová migrace vznikne znovu pouze z připnutých původních zdrojů pomocí
provider-neutral lokálního LLM. Současný importovaný cíl bude při potvrzeném
apply kompletně nahrazen; do té doby se fyzicky nemaže a zůstává obnovitelný
z Git historie. Stará node-local queue se uklidí explicitně až spolu s touto
náhradou, aby s novým během nesdílela rozhodnutí ani fingerprinty.

### Oddělení tří workflow

1. **Jednorázová source-first migrace** rekonstruuje nový plán z původních
   sekvenčních dokumentů. Nepoužívá předchozí import jako autoritu, mapu ani
   pozitivní příklad.
2. **Roadmap refinement scan** kontroluje pouze novou kanonickou roadmapu,
   její explicitní seznamy úkolů, hierarchii, stavy a dependency. Po oddělení
   migračního režimu nebude procházet historické source artefakty ani obecné
   dokumenty a nebude z nich vytvářet úkoly.
3. **Document-to-plan workflow** bude samostatný budoucí nástroj: z nového
   nebo změněného dokumentu navrhne dílčí plán a jeho explicitní integraci.
   Není součástí jednorázové migrace ani refinement scanu.

### Nový transformační tok

1. **Deterministický source catalog.** Pro každý zdroj se uchová role
   dokumentu, commit, hash, cesta, byte/line rozsah, nadpisová cesta, celý
   logický blok, předchozí a následující blok a původní pořadí. Katalog
   explicitně popíše zvyklost TODO → celá uzavřená dávka ve WORK_LOG,
   rozdílnou roli BACKLOGu a strategického Master Checklistu a skutečnost,
   že pozdější výskyt je autoritativnější jen s doloženým výsledkem.
2. **LLM extraction bez cíle.** Model znovu načte celý zdrojový blok a
   relevantní okolí. Vrátí striktně typovaný mezimodel milestone, dávek,
   úkolů, checklistů, historie, popisů, vazeb a nejasností. Původní import
   ani jeho IDs nejsou součástí kontextu. Nejasný obsah zůstane podkladem;
   model jej nesmí vynutit do executable uzlu.
3. **Globální sestavení.** Deterministická vrstva spojí výstupy podle
   provenance a stabilních ID, odhalí kolize a sestaví celý kandidátní graf.
   Markdown a metadata se renderují až z tohoto mezimodelu, nikoli přímými
   volnými editacemi modelu.
4. **Nezávislý LLM audit.** Pro každý logický celek se znovu otevře původní
   zdroj i nový kandidát, s důrazem na zdroj. Audit rozliší `correct`,
   `equivalent`, `misplaced`, `distorted`, `missing`, `duplicated`,
   `unsupported-target` a `ambiguous` a musí citovat konkrétní lokátory.
5. **Měření věrnosti.** Report oddělí pokrytí zdrojů, správnost
   hierarchie, stavu, přiřazení, provenance a dependency a podíl nejasností.
   Souhrnné procento smí být pouze odvozenina těchto kontrol, nikoli
   nedoložená modelová confidence.
6. **Review po logických celcích.** Uživatel kontroluje milestone/dávku a její
   coverage, ne tisíce izolovaných vět. Blokující chyby nebo nízká věrnost
   znamenají nový běh stejného vstupu, případně s lepším lokálním modelem.
7. **Úplná náhrada.** Jediný potvrzený preview/digest apply nahradí
   současný testovací import celým validovaným bundlem. Částečné přebírání
   starého výsledku ani jeho accepted proposals není dovoleno.

Model, prompt, parametry a raw bounded odpovědi jsou součástí run manifestu.
Stejný source catalog proto lze zopakovat s jiným volně dostupným modelem a
porovnat deterministické validační a auditní metriky bez nové ruční přípravy.

### Source-first utility

Implementovaný read-only nástroj odděluje přípravu připnutého katalogu od
modelových volání. Nový run adresář musí být soukromý a nesmí existovat:

```bash
python3 -m scripts.roadmap_rebuild \
  --node /home/antonin/.local/state/federated-workspace/node.json \
  --run-dir /tmp/dev-01-source-rebuild \
  prepare --repository . --revision SOURCE_COMMIT \
  --module MODULE_ID MODULE_REPOSITORY MODULE_COMMIT
```

`prepare` vytvoří `catalog.json` a `manifest.json`, ale nevolá model ani
neotevírá Workspace projekt. Katalog dělí zdroje po celých H2 logických
blocích; pouze blok nad 96 KiB se rekurzivně dělí na podsekce. Každý blok nese
přesný text, globální rozsah řádků, pořadí a předchozí/následující blok.

Resumovatelné zpracování se spouští opakovaně:

```bash
python3 -m scripts.roadmap_rebuild \
  --node /home/antonin/.local/state/federated-workspace/node.json \
  --run-dir /tmp/dev-01-source-rebuild run --limit 100000
```

Během každého modelového volání CLI průběžně ukazuje fázi
`extract`/`audit`, blok, opravný pokus, hotové logické jednotky, procenta, dobu
běhu aktuálního příkazu a orientační ETA. ETA vznikne až po první dokončené
odpovědi a průběžně se mění podle skutečné délky volání; opravné pokusy ji
automaticky prodlouží. V interaktivním terminálu se obnovuje jeden řádek,
při přesměrování jsou události samostatné logovací řádky.

Nejdříve dokončí všechny extraction bloky, deterministicky publikuje
`candidate.json` a `candidate.md` a teprve potom spustí nezávislé audity.
Dokončený běh má `report.json` a `report.md`. `import_ready=true` vyžaduje
kandidáta bez kolizí, neplatných rodičů a dependency a všechny auditní verdicts
jen `correct` nebo `equivalent`; samotná vysoká confidence modelu nestačí.

Každý modelový request používá stabilní run ID a existující
`OllamaRuns` journal. Atomicky publikovaný výsledek bloku se při opakování
nedispatchuje. Extraction schema v2 používá lokální `entity_key` a
`parent_ref`, odděluje source ID, execution status a maturity a dovolí pouze
ID z deterministického block allowlistu. Vadná JSON odpověď dostane nejvýše
dva opravné průchody se stejným zdrojem, původní odpovědí a konkrétní
validační chybou. Třetí neúspěch nebo nejasný transport se uloží jako
terminální `*.failed.json` pro daný run a ostatní bloky mohou pokračovat;
nový model, prompt nebo oprava takového bloku vyžadují nový run adresář. Pád před
atomickým rename nezveřejní částečný výsledek. Utility nemá apply ani
projektový writer, takže žádná z těchto hranic nemění Git, index ani journal
Workspace projektu.

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

Uživatel upřesnil, že celý dosavadní cílový plán je pouze testovací.
Není zdrojem migrace: jeho položky, vztahy ani stavy se nepřebírají.
Uživatel autorizoval úplné nahrazení. Původní bajty a cílový HEAD se čtou
pouze kvůli diffu, CAS a případné obnově; nevzniká z nich nový podkladový
artefakt ani povinné mapování testovacích ID. Transportní historie zpráv
zůstává oddělená, bez přenosu testovacích úkolů do nové roadmapy.

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
Potom ověřit celý vybraný rozsah a před skutečným zápisem dokončit
konkrétní náhled všech artefaktů existujícího projektu. Úplné nahrazení
testovacího plánu již uživatel autorizoval; samostatné opakované potvrzení
tohoto záměru není potřeba. Stále musí projít validace a recovery kontroly.

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

Aktuální pravidlo v2 do profilované části zařazuje aktuální feature a
historické dávky ze zdrojového WORK_LOG, včetně těch, které starý neúplný
dependency graf neobsahuje. Široké
backlogové body zůstávají požadavky; samotný grafový uzel není důkaz jedné
reviewovatelné feature. Pokud historicky dokončená dávka má ve starém grafu hranu k dosud
plánovanému požadavku, dokončená dávka zůstane v roadmapě a hrana se zachová
jako viditelný historický kontext a v původním manifestu. Požadavek se tím
neoznačí za dokončený ani nepovýší na feature dávku. U aktivní práce se
nevyřešená dependency hranice nadále nesmí vynechat a vydávat uzel za ready. Checkbox
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
Report označí cílový obsah jako nepotřebná testovací data a uživatelskou
autorizaci nahrazení eviduje odděleně od technického dokončení apply.
Testovací ID neřeší jako migrační konflikt ani jim nevyrábí aliasy. Nic
se tímto read-only krokem do projektu neukládá. Cílový HEAD musí skutečný apply později znovu ověřit.

`--reuse-mapping MAPPING_JSON` znovu použije zmrazené identity a rozhodnutí
nad stejnou inventurou; neslučuje se s novými module placements. Změna
inventurního digestu vyžaduje explicitní rebase a review, nikoli nové ID
odvozené z posunutého řádku. Bez nového `--target` jde o replay původního
cílového náhledu, nikoli nové ověření aktuálního cílového HEAD. Všechna
rozhodnutí zůstávají návrhem a flag `import_ready` je false.

## Upřesněný obsah: historie a volné popisy

Politika `history-inclusive-and-free-descriptions-v2` zachovává realizované
úkoly i návrhové dávky, nikoli jen starou vybranou podmnožinu grafu. Stav
completed návrhu je dokončení návrhového rozsahu; nevydává se za produkční
implementaci. Maturity text a původní důkazy zůstávají dohledatelné.

Historické dávky vycházejí z kanonických nadpisových záznamů ve WORK_LOG.
Přiřazení milníku používá existující anotaci, explicitní namespace ID nebo
kurátorované mapování hostitelských historických feature v
`spikes/roadmap_history.py`; důvod je součástí mappingu. Ad-hoc task se přiřadí
podle doložené fyzické batch sekce, i když má jiný ID prefix. ID, pro které
není doložená dávka, nepřevádíme na umělý batch: jeho původní text, ID a stav
zůstávají v podkladu připojeném k milníku, případně v samostatném Markdownu.

Obecné myšlenky a nejednoznačné zdrojové body nejsou automaticky task ani
batch. Explicitní kontext sekce určí vlastníka popisu (milník nebo dávku).
Není-li jednoznačný, vytvoří se samostatný `.md` podklad a odkaz v hlavním
roadmapovém dokumentu. Tyto texty nedostávají v cílové mapě vymyšlená
MIG-REQ ID; původní stabilní ID konkrétních bodů se naopak neztrácejí.

Podklady jsou v reportu samostatné Markdown soubory s původními zdrojovými
sekcemi. Krátký volný text se promítne i do popisu vlastníka. Limit popisu
se neobchází: úplný text je vždy ve zdrojovém podkladu, nadlimitní části se
neuseknou. Zdroje zůstávají také v přesných bajtech v source archivu.
Explicitně doložený stav gate z hlavní roadmapy se zachová s odkazem na
řádek; splnění milníku se neodvozuje z počtu zaškrtnutých podúkolů.

Původní generované náhledy politiky v1 zůstávají historickými diagnostickými
výstupy, nejsou aktuálním migračním zadáním. Jde stále o náhled před úplným
artefaktovým apply plánem: metadata, přemapování odkazů a autorizovaný
zápis/recovery nejsou doloženy samotným validním task grafem.

## Bod 1 — sestavení importního balíku bez zápisu

`spikes/roadmap_bundle.py` nyní skládá konkrétní payload pro každý projekt.
Reuse/adaptuje existující metadata v1/v2, source import provenance a task-graph
validátor; nevytváří nový store ani zápisové API. Providerově omezené
`Sources.import_sources` se jako obecný importér nepoužívá. Pro samostatný
modul je navrženo seeded vytvoření, které `ProjectCreation.create` již
podporuje včetně explicitního project UUID a počátečního snapshotu.

```bash
python3 -m scripts.roadmap_migration_bundle \
  --inventory INVENTORY_JSON --mapping MAPPING_JSON \
  --source-root REPOSITORY_ID REPOSITORY_PATH \
  --author-id LOCAL_AUTHOR_UUID --privacy project \
  --output /tmp/dev-01-import-operation
```

Všechny zdrojové repozitáře musí být uvedené explicitně. Autor je durable
lokální author UUID, nikoli node UUID ani odhad podle autora zdrojového
souboru. Čas přípravy se uloží do manifestu; volitelné `--created-at` umožní
reprodukovat balík se stejnými vstupy. Původní neznámé source časy se
nedoplňují. Navržená privacy ještě nenahrazuje kontrolu kontextu před zápisem.

Balík obsahuje:

- `operation.json`: project/operation ID, výchozí HEAD, navržená metadata,
  přesné cesty, create/replace akce, SHA-256, velikosti a závislosti operací;
- `blobs/<sha256>`: přesné bajty každého obsahu i metadat;
- `payload/<repository-id>/artifacts/...`: stejný obsah v běžné podobě pro
  review, včetně hlavního plánu a všech Markdown podkladů;
- `summary.md`: přehled a odkazy na hlavní plány.

Každý projekt má vlastní source manifest a mapování ID v samostatných
verzovaných source artefaktech. Interní text modulu se nekopíruje do hlavního
projektu; ten drží pouze propojení na navržený modulový project UUID.
Původní zdroje zachovávají přesné bajty a Git revize. Generované source
manifesty mají identitu odvozenou i od jejich obsahu, aby se při nové verzi
nepřepisoval neměnný source artefakt.

Hlavní TODO zachovává svou stabilní identitu a immutable origin metadata;
mutable testovací název, popis a tagy se nepřebírají. Jeho obsah se celý
nahrazuje novým plánem. Ostatní existující entity se implicitně nemažou.
Modulový root používá main_todo_id navrženého modulového projektu; jeho
konkrétní filesystem umístění ještě musí určit další validační krok.
Hostitelská operace závisí na dokončení modulové, ale každá má vlastní
receipt/transakční hranici podle ADR 0003; nejde o cross-project transakci.

Příprava běží jen v paměti a do nového privátního adresáře mimo projekt.
Před zápisem manifestu ověří úplnost a hashe blobů. Při přerušení před
`operation.json` není balík kompletní; lze jej znovu vytvořit v novém
adresáři. Manifest se publikuje poslední přes dočasný soubor. Není to
receipt importu ani záruka obnovy po výpadku napájení. Živý Git, index,
journal a node registrace se nemění.

Intrinsic metadata shape a task graph se při sestavení kontrolují, ale
`import_ready` zůstává false. Bod 2 řeší aktuální oprávnění/HEAD,
privacy, celého cílového kandidáta včetně nepozměněných entit, kolize,
zdrojové odkazy a umístění nového projektu. Retry budoucího writeru použije
zmrazený balík; nemá jej vytvářet znovu s novým časem. Samotný writer a jeho
recovery patří do bodů 3/4 a DEV-01-D.

## Bod 2 — read-only prověrka celého výsledku

Sestavený balík se před implementací writeru kontroluje proti celému
aktuálnímu snapshotu projektu, nikoli jen jako izolovaný payload:

```bash
python3 -m scripts.roadmap_migration_validate \
  --bundle /tmp/dev-01-import-operation \
  --output /tmp/dev-01-prewrite-review
```

Kontrola znovu uzavře manifest, content-addressed blobs i jejich čitelné
payload mirror, ověří lokálního autora, připnutý čistý HEAD a stav
journalu. U existujícího projektu sloučí payload s celým Git snapshotem a
nad výsledkem spustí `validate_transition`, `validate_snapshot` a task-graph
validaci. Tím se zachytí kolize i dangling vazby v nepřepisovaných datech.
Nový modul validuje jako seed; fyzickou cestu lze dodat opakovaným
`--location SCOPE=/absolutni/cesta`. Validátor cestu nevytváří a odmítne
překryv s node konfigurací, runtime, registrovanými projekty, jejich state
adresáři a explicitně zadanými `--source-root`.

Privacy zdrojů se nepotvrzuje odhadem. Jednotlivé klasifikace se předávají
jako `--source-privacy SOURCE=CLASS`; chybějící klasifikace zůstane
`needs-review` a příliš nízká cílová privacy je blokátor. Odkazy v odvozených
Markdown dokumentech musí směřovat na konkrétní `artifacts/...` v kandidátu.
Původní source snapshoty se nemění; jejich historické relativní odkazy jsou
součástí původních bajtů, nikoli aktivní navigace Workspace. Externí odkazy
jsou pouze evidovány, bez síťového tvrzení o dostupnosti.

Konkrétní prověrka balíku
`1d52f1c3ece9c18c276434f84f5888f4fecc3d46e328392cfa6ba040c91561d0`
je v `/tmp/dev-01-prewrite-review-3`: devět kontrol prošlo, dvě blokují a tři
vyžadují review. Prošla integrita balíku, lokální autor, modulový seed,
nativní replica policy, živý HEAD, prázdný journal i celý sloučený host
snapshot. Zápis blokuje 184 relativních odkazů v odvozených host dokumentech
(72 různých cílů) a
nezvolená fyzická cesta nového modulového projektu. Obsahové review zbývá
pro privacy 13 zdrojů a dostupnost devíti externích odkazů. `import_ready`
proto zůstává `false`; i po opravě těchto nálezů chybí writer, jeho
journal recovery a idempotentní retry.

### Odstranění blokátorů prověrky

Odvozené dokumenty nyní přepisují relativní odkazy na vybrané zdroje na
jejich content-addressed source artefakty. Odkaz na soubor mimo vybraný import
se nepokouší předstírat funkční navigaci: zachová popisek a původní cíl jako
text `zdrojová cesta`. Nemění se tím archivované source artefakty ani jejich
hash; transformace se týká pouze odvozených popisů a plánu.

Pro modul `cz.proofofidea.publication-experiment-registry` je v operaci
explicitně svázána cesta
`/home/antonin/Projekty/publication-experiment-registry`. Odpovídající state
adresář je
`/home/antonin/Projekty/.workspace-state-af24865c-a81f-58c9-b572-a397bd0c3d6e`.
Read-only kontrola mimo omezený vývojový sandbox potvrdila vlastnictví a
zapisovatelnost parentu, neexistenci obou cílů a absenci překryvu. Adresáře
nebyly vytvořeny.

Opravený balík je `/tmp/dev-01-import-operation-v3`, SHA-256
`ae0df1d730259fa233ef87f6a253969674d96e6b2e08c7bc080a0476fa558e99`.
Prověrka `/tmp/dev-01-prewrite-review-v3-host` má 11 kontrol `passed`, nula
`blocked` a tři `needs-review`. Otevřené review privacy 13 zdrojů a devíti
externích URL není tímto krokem automaticky schválené. Zápis stále
neproběhl a `import_ready` zůstává false do jejich rozhodnutí a implementace
writeru/recovery.

### Privacy zdrojů a externí URL

Review manifest
[`roadmap-migration-source-review.json`](roadmap-migration-source-review.json)
je svázaný s bundle SHA-256 a se SHA-256 každého ze 13 zdrojů. Všechny
zdroje jsou klasifikované jako `project`: jde o projektové plány, historii,
ADR, graf a modulový kontrakt. Obsahová kontrola nenašla credential, privátní
klíč, osobní e-mail ani domácí cestu. BACKLOG a WORK_LOG obsahují interní
testovací IP adresy a popis zacházení s credentials/secrets, nikoli jejich
hodnoty; proto nevyžadují `confidential` ani `local-only`. Cílová privacy
`project` je nezlehčuje.

Manifest eviduje osm unikátních externích URL a jejich devět výskytů.
Oficiální dokumentace Google, Google Cloud, OpenAI a W3C byla 28. 10. 2026
dohledána; GitHub API potvrdilo PR #68 jako existující a sloučený. Původní
OpenAI Help URL legitimně přesměrovává na aktuální slug a manifest ukládá
oba cíle. Jde o bodovou kontrolu dostupnosti, nikoli příslib budoucí
dostupnosti externí služby.

Validátor přijímá manifest přes `--source-review`. Odmítne jiný bundle,
změněný source hash, neúplnou klasifikaci, neznámou URL nebo odlišný počet
výskytů. Prověrka `/tmp/dev-01-prewrite-review-v4-host` tak uzavřela všech
14 kontrol: 14 `passed`, 0 `blocked`, 0 `needs-review` a
`prewrite_checks_passed: true`. `import_ready` zůstává `false`, protože
bezpečný writer, journal recovery a idempotentní apply jsou samostatný další
krok.

## Bod 3 — recoverable a idempotentní writer

`spikes.roadmap_importer.RoadmapImporter` aplikuje pouze kompletní balík,
jehož SHA-256 volající zopakuje v `expected_bundle_sha256` a který projde
bundle-bound source review i celou aktuální předzápisovou prověrkou. Nepřidává
nový storage mechanismus:

1. Modulový projekt vytváří existující `ProjectCreation.create` jako seeded
   projekt s přesným project ID, operation ID, created_at, request digestem a
   validovanými payload bajty.
2. Hostitelský payload zapisuje jedinou `Workspace.transact` operací pod
   existujícím writer lockem a expected HEAD. `create` cesty nesmějí existovat,
   `replace` cesty musí existovat a nepřepisované entity se zachovají.
3. Pořadí je odvozené z dependency grafu operace. Každý projekt má vlastní
   nativní receipt; souhrnný JSON je pouze odvozené předání, nikoli třetí
   transakční autorita.

Crash boundaries:

- před modulem není nic změněno;
- přerušený seeded create obnovuje `ProjectCreation` z jeho lokální operace;
- po dokončeném modulu a před hostem zůstává validní modul a nezměněný
  host, retry replayuje module receipt a pokračuje;
- přerušený host zápis obnovuje `Workspace` podle ADR 0003; validátor povolí
  pouze pending operaci se stejným operation ID a vlastní recovery následně
  znovu kontroluje request digest, větev, HEAD, staging i cizí změny;
- po obou commitech replay vrátí stejné receipts a nevytvoří druhý commit.

Mezi projekty není atomicita ani automatický rollback. To je záměrné:
dokončený modul je platný stav a host na něj naváže při retry. CLI vyžaduje
explicitní digest a novou cestu pro odvozený receipt:

```bash
python3 -m scripts.roadmap_migration_apply \
  --bundle /tmp/dev-01-import-operation-v3 \
  --source-review docs/roadmap-migration-source-review.json \
  --expected-bundle-sha256 ae0df1d730259fa233ef87f6a253969674d96e6b2e08c7bc080a0476fa558e99 \
  --source-root /home/antonin/Projects/FederatedProjectWorkcspace \
  --source-root /home/antonin/Projects/FederatedProjectWorkcspace/modules.local/publication-experiment-registry \
  --receipt /tmp/dev-01-import-receipt.json
```

Tento příkaz je fyzický zápis a v rámci přípravy writeru nebyl spuštěn
nad živým projektem. Izolované testy ověřují normální průchod, replay,
pád mezi projekty, pending host recovery a odmítnutí jiného potvrzeného SHA.
