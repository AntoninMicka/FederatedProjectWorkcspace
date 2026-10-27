<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Projektový plán a podgrafy

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
```

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

Položka **Plán** v levé liště zpřístupňuje hlavní roadmapu a seznam podgrafů.
Hlavní profilovaný pohled zobrazuje milníkové pruhy s jejich popisem a batch
karty s popisem. Dependency hrany batch mohou vést i mezi různými milníky;
plátno proto roste do šířky a lze je vodorovně posouvat, zatímco levý nadpis a
popis milníku zůstávají ukotvené. Samostatná vizuální úroveň tasků je odložená;
tasky však parser i editor nadále materializují a podgraf je může zobrazit v
obecném grafu.

Roadmapa je pouze pro čtení. Hlavní TODO a odkazované task soubory lze upravit
specializovaným editorem **Kostky / Raw text**. Kostky mění jen rozpoznané
řádky; před uložením existujícího souboru se celý draft ověří proti přesnému
committed bundle a expected HEAD. Neplatné nebo duplicitní ID, neznámý cíl,
profilový či dependency cyklus odmítnou projekci; projekt a raw editor zůstanou
dostupné.
