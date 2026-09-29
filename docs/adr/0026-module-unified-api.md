<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0026 — Externě verzované moduly a jednotné API

Stav: přijato a v `MOD-01` implementováno jako **PoC validated**. Tento dokument
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

Manifest v1 je přenosná reviewovaná deklarace bez endpointu a credentials.
Obsahuje identitu a verzi modulu, verzi API a pro každou capability reference na
vstupní/výstupní schéma, oprávnění, privacy třídy, execution boundary, kladné
limity, idempotenci, side-effect třídu, stavy a požadavek provenance. Capability s
externím efektem musí deklarovat `unknown`.

Node-local binding se předává odděleně při načtení. PoC podporuje pouze
credential-free HTTP na explicitní literal loopback adrese a pevný endpoint
`/v1/module/manifest`; redirect, jiný content type, příliš velká odpověď nebo
jakýkoli rozdíl proti reviewovanému manifestu znamená nekompatibilitu. Kontrola
je read-only a modul neregistruje ani nespouští. Private-network transport,
discovery, instalace a autorizované capability volání vyžadují další kontrakt.

## Důsledky a ověření

Každý externí modul podléhá samostatnému reuse, licenčnímu, bezpečnostnímu a
kompatibilitnímu review. Nekompatibilní, chybějící nebo neautorizovaná capability
selže uzavřeně; jádro nemění chování ani nehledá náhradní modul.

První doložený modul má samostatný repozitář v ignorovaném `modules.local/` a
vrací manifest přes stejné API; jeho funkční roadmapa se do tohoto repozitáře
nekopíruje. Implementovaný validátor a CLI ověřují pouze kompatibilitu
deklarace. Instalace, discovery, autorizace volání a publikace zůstávají mimo
tento PoC.
