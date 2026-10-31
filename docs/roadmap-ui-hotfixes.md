<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Hotfix: podklady roadmapy a seznam konfliktních souborů

Uživatelské zadání z 31. 10. 2026; samostatná větev
`hotfix/roadmap-links-conflict-scroll` z `develop` po PR #116.
Tento dokument popisuje změnu UI, není plánem Workspace.

Detail položky projektové roadmapy otevírá podklady z Markdown odkazů
`artifacts/<UUID>/<soubor>` přes existující projektový náhled. Nabízí také
„Otevřít zdrojový seznam“ podle identity zdroje uzlu. V náhledu lze stejným
způsobem pokračovat do dalších odkazovaných podkladů a podseznamů.
Obsah se načítá až při otevření; neprobíhá rekurzivní přednačítání.
Chybějící či zastaralý podklad odmítne existující preview API.
Externí URL a HTML zůstávají textem, odkazy v blocích kódu se neaktivují.
Náhledy verzí v řešiteli konfliktů zůstávají bez aktivních odkazů.

Seznam konfliktních souborů má vlastní svislé scrollování, omezenou výšku
podle viewportu a klávesnicový focus. Posun seznamu nemění pozici okolních
ovládacích prvků. Nezměněná logika potvrzení stále vyžaduje explicitní review.

Reuse/adapt: existující `showTaskPlanDetail`, bezpečný `renderMarkdown`,
`openPreview` a `.conflict-file-list` ze sdíleného desktop/web shellu.
Viz [ADR 0043](adr/0043-explicit-federated-conflict-resolution.md) a
[ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md).
Nový renderer, transport a samostatné úložiště nejsou potřeba.
Změna je pouze čtecí UI; nezavádí nové persistentní zápisy ani crash boundary.

Předávání úkolů mezi Workspace a IDE, kompilát kontextu a způsob potvrzení
splnění zůstávají otevřené pro další návrh. Tyto hotfixy jejich chování nemění.

## Ověření

Cílené selektory `tests.test_roadmap_hotfix`, `tests.test_task_graph` a
`tests.test_conflict_resolution`: 21 testů OK. Nová Node kontrola provádí
kliknutí v detailu i v podkladu, kontroluje neaktivní HTML/externí URL a
bloky kódu. Reálný Qt WebEngine při viewportu 1326 × 678 ověřil scroll
seznamu 702 souborů (výška 217 px, posun 900 px), zachování pozic okolních
prvků a kliknutí na projektový podklad. Jde o izolovaný DOM/layout smoke,
nikoli proklikání uživatelova běžícího projektu.

Závěrečná celá sada `python3 -m unittest discover -s tests -v`:
1 115 testů, OK, 39 podmíněných skipů, 270,818 s. Běh proběhl s povolenými
lokálními sockety; původní sandboxový běh byl přerušen po chybách API testů.
`node --check` emitovaného JS, místní odkazy a `git diff --check` prošly.
