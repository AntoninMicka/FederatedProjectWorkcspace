<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0059 — Souborová hierarchie plánu a lossless editor úkolů

- Stav: přijatý návrh
- Datum: 2026-10-27
- Dávka: `DOC-EDITOR-CONTRACTS-01`
- Implementace: `PLAN-TASK-EDITOR-01` (zahrnuje původní souborový rozsah
  `PLAN-FILE-HIERARCHY-01` a task coverage katalogu)

## Kontext

ADR 0055 používá hlavní Markdown TODO jako jedinou autoritu obecného plánu a
vedlejší dokumenty pouze jako podgrafové selektory. To stačí pro plochý seznam,
ale ne pro větší roadmapu, ve které je potřeba rozlišit úroveň uzlu a rozdělit
kanonické definice do více souborů. Strukturovaný editor navíc nesmí získat
vlastní databázi ani při uložení přepsat neznámý Markdown.

## Rozhodnutí: autoritativní souborový bundle

Hlavní TODO zůstává kořenem plánu a deklaruje profil:

```markdown
<!-- fpw-plan-profile: software-development/v1 -->
```

Batch reprezentuje své task potomky právě jedním ze dvou způsobů. Buď jsou
checkbox odrážky fyzicky vnořené pod batch, nebo je titul batch přesným
Markdown odkazem na verzovaný document artefakt:

```markdown
  - [ ] [BATCH-01] Dávka s inline úkoly
    - type: batch
    - [ ] [TASK-01] První úkol
      - type: task

  - [ ] [BATCH-02] [Dávka v souboru](artifacts/UUID/content.md)
    - type: batch
```

Odkazovaný soubor deklaruje svůj účel a v první verzi obsahuje pouze kořenové
leaf tasky daného batch:

```markdown
<!-- fpw-plan-document: definitions/v1 -->
```

Souborový bundle je uzavřen přes odkazy rozpoznaných batch uzlů z jednoho
aktuálního validovaného Git snapshotu; globální hledání všech `.md` souborů ani
sledování jiných Markdown odkazů se nepoužije. Batch nesmí současně mít inline
potomky i souborový odkaz a externí soubor nesmí odkazovat na další soubor.

Každé stabilní ID má právě jednu kanonickou definici v celém bundle. Její text,
typ a stav jsou autoritativní v souboru, ve kterém je definována. Duplicita,
neznámý odkaz, source artefakt, cesta mimo projekt, cyklus/rekurze, nepovolená
privacy nebo změna HEAD odmítne celou projekci plánu, nikoli projekt či raw
editor. Odkaz míří na verzovanou artifact cestu obsahující stabilní UUID;
přejmenování souboru se řeší explicitní změnou batch odrážky.

Podgraf z ADR 0055 zůstává pouze dokumentem s tagem `plan-subgraph`, který
vybírá kanonická ID z již sestaveného bundle. Nikdy nedefinuje stav, typ,
hierarchii ani souborový odkaz a není druhou autoritou.

## Profily a hierarchie

Kořen deklaruje jeden uzavřený profil. Profil určuje povolené typy, jejich
popisky, povolené parent-child hrany a leaf typ. Neznámý profil nebo typ je
chyba, nikoli automaticky obecný úkol. Jiné domény tak mohou později dodat jiné
úrovně bez rozvolnění softwarového kontraktu.

Profil `software-development/v1` má přesně:

1. `milestone` — strategický výsledek/gate, může obsahovat `batch`;
2. `batch` — jedna ucelená feature, jedna feature větev a jeden PR, může
   obsahovat `task`;
3. `task` — nejmenší implementační jednotka, cílená na jednu funkci nebo
   koherentní změnu a normálně jeden commit; nemá děti.

Task, který je potřeba dále dělit, ještě není leaf task: rozpadne se na více
sourozeneckých tasků v dávce s explicitními dependency hranami. Opravný commit
nebo administrativní výjimka musí být popsány; nemění pravidlo, že batch je
jediný PR.

Příklad definic používá vnoření jako kanonickou hierarchii:

```markdown
- [ ] [M-EDITOR] Editory dokumentů
  - type: milestone
  - [ ] [B-PATTERNS] Katalog vzorů a raw editor
    - type: batch
    - [ ] [T-CATALOG] Zavést validovaný registr vzorů
      - type: task
      - depends_on: T-ADAPTERS
```

`parent_of` je volitelná kontrolní deklarace a musí přesně odpovídat fyzickému
vnoření nebo rodiči odkazovaného souboru. Projekce uloží jediný směr
`parent_id`. Stávající `depends_on`, `blocks`, `duplicates`,
`supersedes` a `relates_to` zůstávají ortogonální k hierarchii. Dependency
cyklus je zakázaný; hierarchie musí být acyklická a odpovídat profilu.

## Popisné odrážky a roadmapový pohled

Obyčejná odrážka vnořená pod milestone, batch nebo task, která nemá
rozpoznaný metadatový klíč, je řádek popisu nejbližšího uzlu. Rozpoznaná
metadata (`type`, dependency a další vztahy) zůstávají oddělená. Projekce
spojuje více popisných odrážek v pořadí souboru, ale raw Markdown neupravuje;
platí stejný limit a fail-closed sestavení bundle jako pro ostatní data uzlu.

Hlavní pohled profilu `software-development/v1` materializuje nejprve pouze
milestone a batch úroveň. Milník tvoří vodorovný pruh s ukotveným nadpisem a
popisem, batch je karta s vlastním popisem. Dependency hrana batch není
omezena hranicí milníku, takže plátno smí růst do šířky a vodorovně se
posouvat. Task data zůstávají v projekci i editoru, ale jejich samostatná
vizuální úroveň není součástí tohoto prvního pohledu.

## Speciální editor úkolů

Task editor je specializovaný pohled nad raw textem a profilem, nikoli nový
store. Známé bloky materializuje jako samostatné widgety („lego kostky“) pro
typ, stabilní ID, stav, název, popis, hierarchii a vztahy. Vložení nové kostky
použije vzor z katalogu ADR 0058 filtrovaný pro aktivní profil a typ dokumentu.
Uživatel volí konec souboru nebo pozici před libovolným rozpoznaným uzlem;
editor převede volbu na přesnou pozici v raw bufferu a nemění okolní text.

Task coverage je součástí stejné feature dávky: každý materializovaný typ bloku
a každá insert operace nabízená UI má stabilní validovaný vzor. Obecné
rozšíření katalogu pro jiné adaptéry zůstává oddělené v
`DOC-PATTERN-LIBRARY-01`.

Round-trip musí být lossless pro obsah, který editor nevlastní. Implementace
smí měnit pouze přesně rozpoznané span bloky; zachová pořadí, komentáře,
neznámé odstavce, whitespace a ostatní metadata. Pokud parser neumí určit
bezpečné hranice nebo dokument obsahuje nepodporovanou konstrukci, strukturovaný
režim zůstane read-only a raw editor bude jedinou zápisovou cestou. Uživatel
musí před uložením vidět validační chyby a může se kdykoli vrátit k raw textu.

První task editor pracuje s jedním vybraným souborem bundle. Přesun uzlu mezi
soubory je víceartefaktová operace a není součástí první implementace. Přidání
existujícího externího souboru do bundle upravuje pouze odkaz v batch odrážce a
podléhá běžnému expected-HEAD, journal, Git CAS a index recovery kontraktu.

## Crash boundaries a důsledky

Čtení a sestavení bundle jsou read-only projekce jednoho commitu. Editace
jednoho souboru používá stávající document Workspace operaci. Pád před jejím
commitem obnoví journal, po commitu lze obnovit index z HEAD. Odkaz a nově
vytvořený externí dokument nesmějí v první verzi vznikat dvěma nezávislými
commity vydávanými za atomický výsledek; buď použijí jednu koordinovanou
vícesouborovou Workspace operaci, nebo uživatel nejprve uloží dokument a až
další explicitní operací jej připojí.

ADR 0059 rozšiřuje ADR 0055 pouze pro explicitně profilovaný bundle. Starší
hlavní TODO bez profilu zůstává platný a používá dosavadní plochý graf. SQLite
index zůstává obnovitelnou projekcí; stav uzlů se nefederuje jinudy než jako
projektové Git soubory.

## Reuse rozhodnutí

**Reuse/adapt:** parser a fail-closed graf ADR 0055, shared Markdown editor a
`ArtifactActions`, vztahové validátory, Workspace/Journal/Git/index a widgetové
principy existujícího prezentačního editoru. **Reject:** druhý task store,
automatické skenování repozitáře, obecný AST rewriter, ukládání odvozeného
stavu do SQLite a tiché přeformátování dokumentu.
