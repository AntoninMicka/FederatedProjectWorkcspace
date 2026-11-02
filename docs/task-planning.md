<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Projektový plán a podgrafy

## Úprava jedné položky

V pohledu **Plán** otevřete detail milníku, dávky nebo úkolu a zvolte
**Upravit tuto položku**. Společný raw editor načte vlastní Markdown blok
položky s popisem, vztahy a případným checklistem. Podúkoly dávky ani ostatní
obsah souboru do editoru nevstupují. **Uložit** změní pouze tento blok a vrátí
vás do plánu; neuložené změny chrání běžný dialog při odchodu z editoru.

Stabilní ID, typ a hierarchie se tímto způsobem nemění. Pro přesun použijte
celý zdrojový seznam. Při chybě revize zůstane draft zachovaný;
po nejasném výsledku lze zopakovat stejné uložení se stejným ID operace.
Projekt pouze pro čtení tuto akci nenabízí. Recovery a přesné hranice změny
popisuje [ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md#dílčí-úprava-jedné-položky-plan-editor).

## Nová položka, závislosti a mazání

**Přidat kořenovou položku** nad plánem vytvoří milník. V detailu milníku nebo
dávky přidáte **Přidat dávku** / **Přidat úkol**: vyplňte název, volitelně popis,
stabilní ID (jinak se vygeneruje) a závislosti. Položka se zařadí jako poslední
potomek a typ určí profil plánu.

**Upravit závislosti** v detailu nastaví přesný seznam předpokladů; cyklus nebo
neznámé ID se neuloží. Závislost zapsanou u jiné položky přes `blocks` je nutné
odebrat tam.

**Smazat položku** nejprve ukáže celý mazaný podstrom. Smazání se nenabídne,
pokud na položce závisí jiná položka, je ve vaší frontě úkolů, odkazuje na ni
výřez nebo jiný vztah, nebo jde o dávku v samostatném souboru. Text zůstává
v historii projektu. Recovery popisuje
[ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md#vytvoření-závislosti-a-mazání-položky).

## Zápis plánu a vztahů

Hlavní seznam úkolů je autoritou. Každý checkbox začíná stabilním ID:

```markdown
- [x] [CORE-01] Připravit základ
- [ ] [UI-02] Zobrazit výsledek
  - závisí na: CORE-01
  - souvisí s: DOC-01
```

Podporované kanonické vztahy jsou `depends_on`, `duplicates`, `supersedes`,
`relates_to` a `parent_of`. České popisky `závisí na`, `blokován`, `blokuje`,
`duplikuje`, `duplikován`, `nahrazuje`, `souvisí s` a `rodič` se převedou na
jedinou kanonickou hranu. Jen dependency hrany ovlivňují připravenost,
blokování a kritickou cestu.

Podgraf je běžný Markdown dokument s tagem `plan-subgraph`. Jeho checkboxy
odkazují pouze na existující ID, např. `- [ ] [UI-02]`. Stav a případný text
v podgrafu se ignorují; zobrazí se kanonický úkol z hlavního TODO.

## Profilované typy a více definičních souborů

Profil `software-development/v1` podle [ADR
0059](adr/0059-file-plan-hierarchy-and-task-editor.md) používá
`milestone → batch → task`: milník je strategický výsledek, batch jedna feature
větev/PR a task nejmenší změna normálně cílená na jeden commit. Typ je povinné
metadata `type` a rodič vychází z fyzického vnoření.

Každý z těchto uzlů může mít pod `type` jednu nebo více obyčejných vnořených
odrážek. Ty tvoří víceřádkový popis uzlu; rozpoznaná metadata jako `type` a
`depends_on` do popisu nepatří. Například:

```markdown
- [ ] [MILESTONE-01] Import projektu
  - type: milestone
  - Importovat roadmapu, úkoly a popisy z původního projektu.
  - [ ] [BATCH-01] Načíst soubory plánu
    - type: batch
    - Zachovat původní bajty a stabilní ID položek.
    - [ ] [TASK-01] Ověřit vstup
      - type: task
      - Neplatný bundle odmítnout bez částečné projekce.
      - [x] Neplatný vstup skončí validační chybou.
      - [ ] Chyba zachová původní soubor beze změny.
```

Checkbox odrážky bez stabilního ID jsou v profilovaném plánu povolené pouze
pod uzlem `task` a až po jeho `type: task`. Jsou bounded podmínkami splnění se
stavem a textem, nikoli další úrovní hierarchie. Nevstupují do počtu uzlů,
dependency grafu ani stromu roadmapy; task zůstává leaf typem.

Batch může tasky obsahovat jako vnořené odrážky, nebo jeho titul může být
přesný Markdown odkaz `artifacts/UUID/content.md`. Odkazovaný dokument začíná
`<!-- fpw-plan-document: definitions/v1 -->` a obsahuje kořenové leaf tasky.
Obě varianty vytvářejí stejné `parent_id`; graf je materializovaná read-only
projekce verzovaných task souborů, nikoli další autorita. Kombinace odkazu a
inline potomků, neznámá cesta, rekurze a duplicitní ID fail-closed odmítnou
projekci.

Kanonická definice ID smí být právě v jednom souboru bundle. Podgraf i potom
pouze vybírá ID a nepřebírá jejich stav. Uživatelský příklad je v
[návodu ke vzorům a skládání plánu](document-patterns-and-task-authoring.md).

Položka **Plán** v levé liště zpřístupňuje strom roadmapy a seznam podgrafů.
Kořen `/` otevírá hlavní profilovaný pohled: milníkové pruhy s popisem a batch
karty s popisem. Dependency hrany batch mohou vést i mezi různými milníky;
plátno proto roste do šířky a lze je vodorovně posouvat, zatímco levý nadpis a
popis milníku zůstávají ukotvené. Pod `/` strom obsahuje milestone a jejich
batch, ale už ne tasky. Výběr milestone přepne plátno na pruhy jeho batch a
task karty uvnitř; výběr batch tentýž pohled zúží na jediný pruh. Karta tasku
shrnuje stav checklistu a detail ukáže jednotlivé podmínky.

Roadmapa je pouze pro čtení. Hlavní TODO a odkazované task soubory lze upravit
specializovaným editorem **Kostky / Raw text**. Kostky mění jen rozpoznané
řádky; před uložením existujícího souboru se celý draft ověří proti přesnému
committed bundle a expected HEAD. Neplatné nebo duplicitní ID, neznámý cíl,
profilový či dependency cyklus odmítnou projekci; projekt a raw editor zůstanou
dostupné.
