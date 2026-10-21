<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# UX facelift — tiskový balíček formulářů

Generátor `scripts/render_facelift_forms.py` skládá z aktuálního sdíleného UI
a z používaných nativních PySide6 dialogů samostatný A4 balíček pro ruční
anotace. Nejde o nový návrh ani o aplikační export uživatelských dat: formuláře
obsahují pouze statické popisky, výchozí hodnoty a prázdné zástupné plochy.

```sh
python3 scripts/render_facelift_forms.py
```

Výstupy `dist/ux-facelift-forms-a4.html` a
`dist/ux-facelift-forms-a4.pdf` jsou lokální build artefakty a Git je ignoruje.
PDF používá A4 na výšku, zmenšenou kopii aktuálního formuláře a tečkovanou
plochu pro poznámky. Obsahuje společné web/desktop formuláře, průvodce,
potvrzovací panely, editor prezentace, presenterové ovládání a používané
nativní dialog LXC deploymentu. Profil, role displejů, přenos veřejného projektu
a síťový backend už inventura přebírá ze společných webových formulářů.
Starý samostatný Qt editor prezentací není součástí balíčku, protože produkční
desktop používá společný webový editor.

Test `tests/test_facelift_forms.py` porovnává inventuru se všemi aktuálními
HTML `<form id>` a při přidání nezařazeného formuláře selže. Formulářové panely
bez elementu `<form>` zůstávají explicitními položkami seznamu `SHEETS`.

Generátor **reuse** aktuální `spikes.desktop_ui.HTML` a `CSS`; nepřepisuje je
do paralelní šablony. Pro lokální PDF **adaptuje** již používaný Chromium/Qt
print model na A4 a nepřidává runtime závislost aplikace. Nativní dialogy jsou
v tiskovém balíčku pouze statickou inventurou polí podle jejich PySide6 zdroje,
protože jejich živé vykreslení závisí na konkrétním OS tématu a displeji.
