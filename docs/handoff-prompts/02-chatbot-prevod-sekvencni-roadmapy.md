<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Instrukce pro chatbota: převod sekvenční roadmapy pro Workspace

Zadání níže vlož chatbotovi společně s původní roadmapou. Nejde o pokyn
k realizaci úkolů ani k automatické změně už existujícího projektu.

## Zadání k použití

Převeď přiloženou textovou/sekvenční roadmapu projektu **[NÁZEV PROJEKTU]**
na přehledný Markdown plán vhodný k převzetí do Federated Project Workspace.
Zachovej její věcný obsah; změň strukturu a zpřesni nejasnosti, které výslovně
označíš. Nezalož nový návrh projektu místo převodu dodaného zadání.

### Pravidla převodu

1. Uchovej všechny požadavky, omezení, akceptace, rozhodnutí, odklady a stavy.
   Žádný původní bod nesmí potichu zmizet. U rozporu zachovej obě tvrzení
   s odkazem na původ a předlož otázku k review.
2. Existující stabilní ID neměň. Nová ID vytvářej jednou a pak je zachovávej.
   Používej velká ASCII písmena, číslice a pomlčky, např. `APP-M1`, `APP-B1`,
   `APP-T1`. ID nesmí záviset na pozici v seznamu nebo se při přesunu přečíslovat.
   Pokud existující ID nevyhovuje parseru, zachovej je v mapování a navrhni
   nový alias k výslovnému schválení; netvrď, že neplatný plán je importovatelný.
3. Pořadí „1, 2, 3“ není samo o sobě závislost. `depends_on` přidej pouze
   tam, kde je doložený skutečný předpoklad. Domnělé závislosti napiš mezi
   otázky. Nezaváděj automaticky řetěz všech předchozích kroků.
4. Odděl hierarchii od závislostí. Vnoření určuje rodiče, `depends_on` nutný
   předpoklad. `relates_to` vyjadřuje souvislost a nesmí blokovat zahájení.
5. Jeden samostatný úkol má jeden konkrétní výstup a ověření. U příliš velkého
   bodu navrhni rozdělení s mapováním na originál. Neslučuj nezávislé funkce
   jen proto, že byly ve stejném odstavci.
6. Rozlišuj možnost začít od podmínek dokončení. Chybějící akceptace předchozího
   výsledku se nesmí vydávat za splněnou závislost. Pokud konkrétní stav nelze
   vyjádřit podporovanými poli, zachovej ho v popisu a označ otázku k review.
7. Nevymýšlej termíny, kapacity, odhady, vlastníky, testové výsledky ani lidskou
   akceptaci. Doporučené doplnění označ jako návrh, známý údaj odděl od neznámého.
8. U dodaného řešení rozlišuj designed, implemented, PoC validated,
   production-ready a lidské přijetí. Tyto úrovně patří do popisu a důkazů;
   nejsou to vlastní nové hodnoty parserového pole `status`.

### Hierarchie podle typu projektu

Pro softwarový projekt použij profil `software-development/v1` a přesně
hierarchii **milestone → batch → task**:

- Milník: smysluplný strategický výsledek nebo ověřovací brána.
- Dávka: jedna ucelená feature, normálně jedna větev a jeden PR.
- Úkol: nejmenší ověřitelná změna, normálně jeden commit.
- Pod task mohou patřit checkboxy akceptace, nikoli další task uzly.

Pro jiný typ projektu nevynucuj softwarové pojmy větev/PR/commit ani
nevymýšlej jiný profil. Použij neprofilovaný Markdown se stabilními ID,
vnořením a doloženými vztahy. Specializovaný profil zvol pouze tehdy, když
je skutečně doložený jako podporovaný. Níže uvedený příklad je softwarový.

### Přesný zápis

Plán ulož jako samostatný UTF-8 soubor `ROADMAPA-WORKSPACE.md`. Skutečný plán
nesmí být celý uzavřený v code fence: parser obsah ukázkových bloků ignoruje.
Kanonická definice každého ID smí být jen jednou. Přehledové tabulky,
diagramy a soupisy nejsou druhou definicí úkolů.

- Každý uzel začíná `- [ ] [STABILNI-ID] Název` nebo doloženým `- [x] ...`.
- V softwarovém profilu má každý uzel vlastní vnořené `- type: ...`.
- Metadata a popisy odsazuj dvěma mezerami pod vlastní uzel. Potomka
  zapiš na stejné úrovni odsazení jako metadata rodiče. Nepoužívej tabulátory.
- Vztahy piš např. `- depends_on: APP-T1, APP-T2`; odkazy musejí mířit na
  existující ID a dependency graf nesmí obsahovat cyklus.
- Popis piš v obyčejných vnořených odrážkách: cíl, rozsah, výstup,
  cílová úroveň, ověření, omezení a původ. Nenahrazuj popis dlouhým titulkem.
- Checkbox bez ID je pouze checklist pod `task` a až po `type: task`.
  Z hotové dílčí podmínky neodvozuj dokončení celého úkolu.
- Podporované ruční stavy jsou `planned`, `in progress`, `resolved`, `failed`,
  `completed`, `deferred`; `sum` je odvozený stav z potomků. Neznámý stav
  popiš jako neověřený údaj, nepřidávej hodnotu `unknown` do pole `status`.
- `[x]` používej pouze pro doložené dokončení. Původní nevyhovující úkol
  zachovej jako `failed`; náhradní úkol lze spojit pomocí `supersedes`.
  Vyřešení náhradou potvrď až po její skutečné akceptaci.

### Příklad softwarového plánu

```markdown
<!-- fpw-plan-profile: software-development/v1 -->

# Roadmapa projektu

- [ ] [APP-M1] Ověřený import dat
  - type: milestone
  - status: sum
  - Cíl: Uživatel bezpečně načte a zkontroluje vstupní soubor.
  - [ ] [APP-B1] Načtení a validace
    - type: batch
    - status: sum
    - Rozsah: Jeden formát a jeho chybové stavy; bez síťové synchronizace.
    - [ ] [APP-T1] Validovat vstupní soubor
      - type: task
      - status: planned
      - Cíl: Odmítnout neplatný vstup před změnou projektu.
      - Výstup: Validátor a srozumitelná chyba.
      - Cílová úroveň: implemented.
      - Ověření: Platný, poškozený a neúplný vstup.
      - [ ] Neplatný soubor nezmění uložená data.
      - [ ] Chyba vysvětlí důvod odmítnutí.
    - [ ] [APP-T2] Zobrazit náhled validovaných dat
      - type: task
      - status: planned
      - depends_on: APP-T1
      - Výstup: Náhled skutečných vstupů před potvrzením importu.
      - Ověření: Uživatel rozliší náhled a dokončený import.
      - [ ] Náhled sám nic neuloží.
```

### Příklad neprofilovaného plánu

Příklad neprofilovaného plánu pro jiný typ projektu:

```markdown
# Roadmapa výukového projektu

- [ ] [KURZ-M1] Připravené první cvičení
  - Výstup: Samostatně použitelný materiál a ověřené řešení.
  - [ ] [KURZ-T1] Připravit zadání a referenční řešení
    - Ověření: Řešení odpovídá všem bodům zadání.
  - [ ] [KURZ-T2] Vyzkoušet cvičení se studentem
    - depends_on: KURZ-T1
    - Ověření: Zaznamenat skutečný průchod a nejasnosti.
```

### Co odevzdat vedle plánu

Vytvoř také `MAPOVANI-ROADMAPY.md` s tabulkou:

```text
Původní dokument a konkrétní bod | Původní ID | Nové/stávající ID |
Typ převodu | Zachovaný stav a důkaz | Nejasnost / změna k review
```

Každý původní bod musí mít dohledatelné zařazení. U rozdělení uveď všechny
nové cíle; u sloučení všechny zdroje a důvod. Odděl zachovaný obsah od nově
navržených akceptačních podmínek. Mapování ani seznam otázek nesmějí obsahovat
druhou sadu živých checkboxů definujících stejná ID.

Nejdřív preferuj jeden soubor s definicemi. Dělení na nativní dokumenty
Workspace a cesty `artifacts/UUID/...` nech na importu, který zná skutečná
artefaktová UUID. Nevyráběj falešné interní cesty nebo `project.json`.

### Kontrola před předáním

Zkontroluj jedinečnost ID, jejich formát, fyzické vnoření, typy, existenci
cílů vztahů, cykly, zachování původních bodů a doložení dokončených stavů.
Limity současného parseru: nejvýše 1000 uzlů, 4000 vztahů, 100 checklist
podmínek na task a 4000 celkem; název uzlu do 500 znaků a popis do 8 KiB.
Překročení přiznej a navrhni rozdělení, nic neusekávej.

Pokud máš skutečně k dispozici validátor Workspace, použij ho a uveď jeho
výsledek. Jinak napiš „Struktura zkontrolována podle zadání; validace ve
Workspace neprovedena.“ Nevymýšlej úspěšný import ani validační protokol.

Importovaný Markdown podklad není automaticky hlavní plán. Po lidském review
se jeho obsah převezme do hlavního editovatelného plánu cílového projektu;
interní značky a metadata nastavuje Workspace. Původní roadmapa zůstává
neměnným zdrojem a po převzetí se neudržuje jako konkurenční živé TODO.

## Ověřené podklady tohoto návodu

Kontrakt k 12. 11. 2026: [plán a vztahy](../task-planning.md),
[vzory a hierarchie](../document-patterns-and-task-authoring.md),
[závislosti](../roadmap-dependencies.md) a parser
[task_graph.py](../../spikes/task_graph.py).
