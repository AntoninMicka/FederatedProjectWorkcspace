<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0026 — Externě verzované moduly a jednotné API

Stav: přijato jako **designed**. Implementace patří do `MOD-01`; tento dokument
nezavádí plugin runtime, dynamické načítání kódu ani distribuci modulů.

## Rozhodnutí

Dosavadní moduly zůstávají v hlavní roadmapě. Pouze nově výslovně vytipovaný
modul může mít vlastní repozitář, Git historii a roadmapu. Jeho lokální pracovní
kopie nebo symlink je pod `modules.local/`, které je ignorované Gitem tohoto
repozitáře. Složka je vývojová pomůcka, nikoli hranice důvěry, instalátor ani
součást release artefaktu.

Hlavní roadmapa a společná dokumentace neobsahují doslovný popis funkčnosti
externího modulu. Evidují jen jeho stabilní identitu, verzi/revizi, odkaz na
vlastní roadmapu, deklarované capability, závislosti a stav kompatibility.
Zobecnění je přípustné pouze v rozsahu nezbytném pro definici a dokumentaci
jednotného API.

## Jednotné API

Každá capability modulu má verzované vstupní a výstupní schéma, limity, známé
chyby, oprávnění, privacy a execution boundary, pravidla idempotence, model
stavu včetně `unknown` pro externí účinek a provenance. Kompatibilita se
posuzuje podle deklarované verze API a capability, nikoli podle přítomnosti
symlinku nebo názvu adresáře.

Modul nesmí přímo zapisovat projektový Git, SQLite index, operation journal ani
číst credentials. Používá autorizované aplikační služby; projektová mutace jde
přes běžný Workspace expected-HEAD/journal/commit/index/receipt lifecycle.
Symlink nebo checkout nesmí být automaticky načten, spuštěn, zabalen, importován
ani považován za autorizovaný či kompatibilní.

## Důsledky a ověření

Každý externí modul podléhá samostatnému reuse, licenčnímu, bezpečnostnímu a
kompatibilitnímu review. Nekompatibilní, chybějící nebo neautorizovaná capability
selže uzavřeně; jádro nemění chování ani nehledá náhradní modul. Konkrétní
mechanismus instalace, discovery, sandboxu a publikace se rozhodne až v `MOD-01`
nad doloženým prvním modulem a jeho testovacím kontraktem.
