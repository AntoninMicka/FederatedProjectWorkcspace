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

## Plánované rozšíření: typy a více definičních souborů

Současný PoC načítá kanonické definice pouze z hlavního TODO. Přijatý návrh
[ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md) jej v samostatné
dávce rozšíří o explicitní souborový bundle a uzavřené profily. Než bude
`PLAN-FILE-HIERARCHY-01` implementována, hlavičky `fpw-plan-profile` a
`fpw-plan-include` ani pole `type`/`parent` nejsou runtime kontraktem.

Softwarový profil bude používat `milestone → batch → task`: milník je
strategický výsledek, batch jedna feature větev/PR a task nejmenší změna
normálně cílená na jeden commit. Kanonická definice ID smí být právě v jednom
explicitně zahrnutém Markdown document artefaktu. Podgraf i potom pouze vybírá
ID a nepřebírá jejich stav. Uživatelský příklad a plánované pořadí jsou v
[návodu ke vzorům a skládání plánu](document-patterns-and-task-authoring.md).

Položka **Plán** v levé liště zpřístupňuje hlavní graf a seznam podgrafů.
První verze je pouze pro čtení. Neplatné nebo duplicitní ID, neznámý cíl
a dependency cyklus odmítnou celou projekci; projekt a editor zůstanou dostupné.
