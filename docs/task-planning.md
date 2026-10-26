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

Položka **Plán** v levé liště zpřístupňuje hlavní graf a seznam podgrafů.
První verze je pouze pro čtení. Neplatné nebo duplicitní ID, neznámý cíl
a dependency cyklus odmítnou celou projekci; projekt a editor zůstanou dostupné.
