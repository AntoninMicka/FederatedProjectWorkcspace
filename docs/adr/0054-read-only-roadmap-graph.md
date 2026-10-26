<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0054: Read-only graf roadmapy nad autoritativními dokumenty

- Stav: přijaté pro PoC
- Datum: 2026-10-26
- Dávka: `DEV-ROADMAP-GRAPH-01`

## Kontext

Roadmapa, TODO, BACKLOG a WORK_LOG mají odlišné autoritativní role, ale jejich
textový pohled neukazuje souběžné proudy a závislosti přehledně. Samostatně
udržovaný graf by se rychle stal konkurenční roadmapou. Odvozovat hrany z volné
češtiny by naopak vytvářelo nedoložené vztahy.

## Rozhodnutí

Soubor `docs/roadmap-graph.json` je verzovaná anotace pouze pro stabilní ID,
milestone a explicitní `depends_on` hrany. Neduplikuje názvy, stav, popis ani
akceptaci. Read-only `RoadmapGraph` při každém požadavku bounded způsobem načte
anotaci i čtyři autoritativní Markdown dokumenty, dohledá v nich strukturované
záznamy názvů a stavů a sestaví projekci až po úplné validaci.

Neznámé nebo duplicitní ID, neznámá hrana, self-edge, cyklus, chybějící
autoritativní záznam, symlink, neregulární nebo nadlimitní zdroj odmítnou celý
výstup. Graf nic neopravuje heuristicky a nikdy nezapisuje stav úkolu.

Topologické pořadí, vrstva, jedna deterministická nejdelší kritická cesta a
právě připravené plánované dávky se počítají z validovaného snapshotu. Dávka je
„souběžně připravená“ pouze tehdy, když jsou všechny její deklarované
závislosti dokončené; odložený či blokovaný stav se za připravený nepovažuje.

JSON projekce nese SHA-256 revizi anotace i všech zdrojů. Statický SVG export
vyžaduje přesně tuto revizi a při změně zdrojů se odmítne jako stale. Sdílené
desktop/server UI používá bezpečné SVG DOM a `textContent`; statický renderer
XML escapuje text. Žádný externí CDN, grafová knihovna ani síťový zdroj nejsou
potřeba.

## Persistentní hranice a recovery

Schopnost je čistě read-only a nevytváří cache, journal ani projektový zápis.
Pád nebo změna souboru během zpracování může skončit pouze chybou konkrétního
požadavku. Obnova je nový požadavek nad aktuálními úplně zvalidovanými zdroji.

## Důsledky

Každá nová vizualizovaná feature musí mít autoritativní záznam a explicitní
anotaci hran. Graf může být neúplný proti celé textové strategii, ale nesmí
vymýšlet chybějící vazby. Budoucí `DEV-01` může formát adaptovat; tento PoC
nepřevádí roadmapu na projektová data a neposkytuje editaci.
