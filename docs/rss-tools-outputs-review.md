<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Závěrečné ověření RSS, Nástrojů a Výstupů — 11. 11. 2026

Rozsah potvrdil uživatel jako dokončení práce z konverzace. Tento záznam
shrnuje implementaci a ověření, nenahrazuje autoritativní plán Workspace
ani jeho lidskou akceptaci. Export při kontrole hlásil `stale=true`
a `waiting_review=true`; aktuální dávku MON-08 proto nelze označit za přijatou.

## Rozsah

- [Zdroje](rss-sources-reader.md): levý seznam, položková menu, ikonové akce,
  editor názvu/URL/periody, náhled importu OPML/XML a podporovaných JSON odběrů.
- [Nástroje](tools-sidebar.md): společný strom, soustředěné založení položek
  a hlídané smazání včetně starších zadání se zachováním historie a výstupů.
- Společná menu mimo posuvný rámeček seznamu, včetně fallbacku pro starší
  prohlížeče, ovládání klávesnicí a zachování původních obsluh akcí.
- [Výstupy](report-outputs.md): konkrétní vydání zpráv, přímé čtení textu,
  export a zmrazené datum/čas sestavení v nových názvech.
- Synchronizace projektových definic a obsahu poolů používá původní
  [přenos dat](full-data-sync.md). Místní odběry samostatné RSS čtečky
  a provozní journaly se tímto přenosem nesynchronizují.

Implementace těchto řezů je na větvi `feature/rss-direct-pilot` do HEAD
`3b81532`. Závěrečná lokální oprava aktualizuje zastaralé kontroly stromu
Výstupů a dashboardového requestu a doplňuje RSS editor do tiskového přehledu
formulářů (39 formulářů). Nezavádí další writer ani persistentní operaci;
platí recovery popsané v odkazovaných dokumentech a ADR 0082.

## Ověření

Po opravě kontrol byl skutečně dokončen celý běh:

```sh
python3 -m unittest discover -s tests -v
```

Výsledek: **2039 testů za 1413,501 s, OK, 59 přeskočených**. Přeskočené
testy zahrnují volitelné Qt/WebEngine, nezpřístupněné runtime/proby,
soukromé vzorky a nahrazené UI scénáře; nejsou doložením jejich provedení.
Samostatné cílené GUI výsledky předchozích řezů uvádějí jejich dokumenty.
První běh odhalil zastaralé kontroly a byl nahrazen tímto úplným během
nad opraveným stavem. Čtyři opravené kontroly prošly také cíleně.

Samostatný HTML přehled formulářů byl vygenerován. Instalační skripty
připravené aktualizace prošly `sh -n`; všech 230 souborů archivu odpovídá
hashům v jeho manifestu. Finální diff prošel `git diff --check`.

## Živá kompatibilita a hranice dokončení

Read-only kontrola ověřila stejný již připravený projektový Git bundle
lokálním i nasazeným validátorem. Lokálně prošel, starší Omnia jej odmítla
ve fázi `receive-verify-history` jako `ValidationError: Unknown reporting value`.
Bundle obsahuje dva záznamy `MonitoringDeletion`; nasazené verzi chybí
modul jejich obsluhy i nový modul Výstupů. Historie ani validační pravidla
nebyly kvůli kompatibilitě změněny.

Připravena je aplikační aktualizace původním instalačním postupem s kontrolou
výchozího release a identity uzlu pod instalačním zámkem. Zachovává unit,
identitu, credentials, TLS, projektová data i journaly; při neúspěšném startu
použije původní rollback. Nasazení a restart vyžadují samostatné schválení.
Tato kontrola nic nenasadila, nerestartovala ani neakceptovala ve Workspace.
Úspěšnou živou synchronizaci a uživatelskou akceptaci nového UI je nutné
ověřit na sjednocených verzích; plná lokální sada je nenahrazuje.
