<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0059 — Souborová hierarchie plánu a lossless editor úkolů

- Stav: přijatý návrh
- Datum: 2026-10-27
- Dávka: `DOC-EDITOR-CONTRACTS-01`
- Implementace: plánovaná jako `PLAN-FILE-HIERARCHY-01` a
  `PLAN-TASK-EDITOR-01`

## Kontext

ADR 0055 používá hlavní Markdown TODO jako jedinou autoritu obecného plánu a
vedlejší dokumenty pouze jako podgrafové selektory. To stačí pro plochý seznam,
ale ne pro větší roadmapu, ve které je potřeba rozlišit úroveň uzlu a rozdělit
kanonické definice do více souborů. Strukturovaný editor navíc nesmí získat
vlastní databázi ani při uložení přepsat neznámý Markdown.

## Rozhodnutí: autoritativní souborový bundle

Hlavní TODO zůstává kořenem plánu. Může explicitně zahrnout další verzované
Markdown document artefakty stejného projektu. Souborový bundle je uzavřený
seznam z aktuálního validovaného Git snapshotu; globální hledání všech `.md`
souborů ani implicitní sledování odkazů se nepoužije.

Plánovaný hlavičkový kontrakt vypadá například takto:

```markdown
<!-- fpw-plan-profile: software-development/v1 -->
<!-- fpw-plan-include: artifacts/UUID/content.md -->
```

Zahrnutý soubor deklaruje svůj účel, ale nemůže dále rekurzivně rozšiřovat
bundle v první verzi:

```markdown
<!-- fpw-plan-document: definitions/v1 -->
```

Každé stabilní ID má právě jednu kanonickou definici v celém bundle. Její text,
typ a stav jsou autoritativní v souboru, ve kterém je definována. Duplicita,
neznámý include, source artefakt, cesta mimo projekt, cyklus/rekurze, nepovolená
privacy nebo změna HEAD odmítne celou projekci plánu, nikoli projekt či raw
editor. Include odkazuje na verzovanou artifact cestu obsahující stabilní UUID;
přejmenování souboru se řeší explicitní změnou kořenového dokumentu.

Podgraf z ADR 0055 zůstává pouze dokumentem s tagem `plan-subgraph`, který
vybírá kanonická ID z již sestaveného bundle. Nikdy nedefinuje stav, typ,
hierarchii ani include a není druhou autoritou.

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

Příklad definic:

```markdown
- [ ] [M-EDITOR] Editory dokumentů
  - type: milestone
  - parent_of: B-PATTERNS
- [ ] [B-PATTERNS] Katalog vzorů a raw editor
  - type: batch
  - parent: M-EDITOR
  - parent_of: T-CATALOG
- [ ] [T-CATALOG] Zavést validovaný registr vzorů
  - type: task
  - parent: B-PATTERNS
  - depends_on: T-ADAPTERS
```

`parent: X` je pouze čitelný inverzní zápis kanonické hrany `X parent_of Y`;
projekce uloží jediný směr. Stávající `depends_on`, `blocks`, `duplicates`,
`supersedes` a `relates_to` zůstávají ortogonální k hierarchii. Dependency
cyklus je zakázaný; hierarchie musí být acyklická a odpovídat profilu.

## Speciální editor úkolů

Task editor je specializovaný pohled nad raw textem a profilem, nikoli nový
store. Známé bloky materializuje jako samostatné widgety („lego kostky“) pro
typ, stabilní ID, stav, název, popis, hierarchii a vztahy. Vložení nové kostky
použije vzor z katalogu ADR 0058 filtrovaný pro aktivní profil a typ dokumentu.

Round-trip musí být lossless pro obsah, který editor nevlastní. Implementace
smí měnit pouze přesně rozpoznané span bloky; zachová pořadí, komentáře,
neznámé odstavce, whitespace a ostatní metadata. Pokud parser neumí určit
bezpečné hranice nebo dokument obsahuje nepodporovanou konstrukci, strukturovaný
režim zůstane read-only a raw editor bude jedinou zápisovou cestou. Uživatel
musí před uložením vidět validační chyby a může se kdykoli vrátit k raw textu.

První task editor pracuje s jedním vybraným souborem bundle. Přesun uzlu mezi
soubory je víceartefaktová operace a není součástí první implementace. Přidání
existujícího externího souboru do bundle upravuje pouze kořenový include a
podléhá běžnému expected-HEAD, journal, Git CAS a index recovery kontraktu.

## Crash boundaries a důsledky

Čtení a sestavení bundle jsou read-only projekce jednoho commitu. Editace
jednoho souboru používá stávající document Workspace operaci. Pád před jejím
commitem obnoví journal, po commitu lze obnovit index z HEAD. Include a nově
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
