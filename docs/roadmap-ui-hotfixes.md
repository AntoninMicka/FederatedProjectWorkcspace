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

## Oprava po uživatelském ověření

První izolovaný smoke neověřil celý shell s promptem ani zdrojový dokument
nad 2 000 řádků. Uživatelské snímky doložily obě mezery; předchozí výsledky
neznamenají akceptaci těchto scénářů.

Markdown nyní používá stránky po nejvýše 2 000 zdrojových řádcích v rámci
stávajícího celkového limitu 4 MiB. Přepínače stránek jsou před obsahem;
podklady zůstávají klikatelné na každé stránce. Při přechodu uvnitř fenced
bloku náhled obnoví jeho kontext, aby kód nezačal vykreslovat jako aktivní
odkazy. Každá stránka nadále vyžaduje očekávaný HEAD. PDF zachovává rozsah
1–100; Markdown dovoluje nejvýše 4 096 stránek a odmítá neexistující stránku.
HTML/JSON náhledy své dosavadní limity nemění.

Konfliktní panel nyní rozděluje dostupnou výšku celým flex řetězcem až
k seznamu. Kompaktní hlavička a společný řádek potvrzení ponechávají tlačítko
nad promptem. Scrolluje pouze seznam; ostatní ovládání se při jeho posunu
nehýbe. Na nízkém viewportu se seznam zmenší podle zbývajícího prostoru.

Nový opakovatelný test `tests.roadmap_layout_smoke` používá skutečné HTML/CSS,
702 položek, viditelný sidebar, prompt a neprázdný stav nevyřešeného konfliktu.
Při 1545 × 863 i 1326 × 678 kontroluje pozici potvrzení vůči promptu a posun
seznamu. Spouští se selektorem
`M0_DESKTOP_TEST=1 python3 -m unittest tests.test_roadmap_hotfix.RoadmapHotfixTests.test_full_conflict_layout_keeps_confirmation_above_prompt -v`.
Samostatné Qt ověření skutečné roadmapy (2 369 řádků) provedlo přechod na
stránku 2/2 produkční funkcí `openPreview`; druhá stránka obsahovala
119 odkazů a neprázdný text. Projektová data se při ověření neměnila.

Starší volitelný `test_real_main_panel_markdown_image_pdf` skončil timeoutem
v kroku `sidebarStage=todo`, ještě před zahájením náhledu. Stejný timeout byl
zopakován v izolované kopii původního commitu `6c7a8b7`; nejde o nový důkaz
regrese stránkování. Tento obecný desktop smoke zůstává neúspěšný a není
vydáván za úspěšné end-to-end ověření.

Po poslední relevantní změně prošla cílená sada: 30 testů OK, 2 podmíněné
skipy; nový úplný layout test byl navíc spuštěn samostatně a prošel.
Závěrečná celá sada: `python3 -m unittest discover -s tests -v` —
1 117 testů, OK, 40 podmíněných skipů, 271,860 s. Emitovaný JS prošel
`node --check`; místní odkazy a finální `git diff --check` jsou v pořádku.
