<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0055: Projektový TODO je autoritou read-only plánu

- Stav: přijaté pro PoC
- Datum: 2026-10-26
- Dávka: `PLAN-TASK-GRAPH-01`

## Kontext

Roadmapový graf ověřil vizualizaci DAG, ale jeho vstupy jsou vývojové dokumenty
tohoto repozitáře. Obecný projekt potřebuje stejný pohled bez nové databáze
stavů a bez ručně udržované kopie plánu.

## Rozhodnutí

Autoritou je hlavní Markdown TODO v validovaném Git snapshotu. Checkbox nese
stabilní ID a odsazené deklarace vztahů. Ukládá se jeden kanonický směr;
inverzní popisky se odvozují. Podgrafový dokument označený tagem
`plan-subgraph` pouze vybírá ID a nesmí přepsat stav nebo název.

Projekce je read-only a vzniká při otevření projektu pod existujícím
Workspace/Git snapshot kontraktem. Chyba vrátí nedostupný plán bez částečného
grafu, ale neznepřístupní samotný projekt ani editor. SVG export je odvozen ze
stejné revize. První řez nemění Git, index ani lokální journal.

## Důsledky

Starší checklist bez ID zůstane čitelný v panelu Úkoly, ale Plán vysvětlí,
že vyžaduje strukturovaná ID. Budoucí editace grafu musí být samostatná
feature a použít standardní expected-HEAD, journal, CAS a obnovu indexu.
