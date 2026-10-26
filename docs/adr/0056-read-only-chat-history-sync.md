<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0056: Synchronizovaná historie chatu je read-only snapshot

- Stav: přijaté pro PoC
- Datum: 2026-10-26
- Dávka: `F-M5-CHAT-HISTORY-01`

## Kontext

Autoritativní `ChatThreads` jsou node-local a zahrnují vazby na lokální běhy,
journaly a credentials, které se mezi uzly nesmějí kopírovat. Uživatel ale
potřebuje přesunout vybranou historii mezi svými schválenými uzly bez vzniku
federovaného lidského chatu nebo vzdáleného přihlášení.

## Rozhodnutí

Jedna explicitní operace přenese 1–32 stabilních vláken jednomu připnutému
peeru přes aktivní bilaterální mapování přesných uživatelů. Projektové vlákno
musí být ve scope mapování; nezařazené vlákno je povoleno pouze pro
`same-team`. Celé vlákno se odmítne při `local-only` zprávě nebo
neterminálním turnu. Přenášejí se stabilní ID, obsah, privacy, autoři, pořadí,
terminální stav a odkaz `manifest_id`, nikoli manifest payload, provider
session, credential ani run journal.

Zdroj před transportem uloží přesný podepsaný balík do node-private SQLite.
Po možné ztrátě odpovědi je operace `unknown`; explicitní reconcile smí znovu
odeslat pouze stejné uložené bajty. Příjemce ověří aktuální peer, mapping,
scope, pin i podpis a v jedné SQLite transakci uloží snapshot a podepsanou
účtenku. Stejný operation ID a digest je idempotentní. Jiný digest stejného
origin vlákna se uchová jako další divergentní snapshot.

Přijaté snapshoty se nikdy nevkládají do `ChatThreads`. UI je zobrazuje v
samostatné větvi, zakáže composer i lokální runtime akce a nenabídne archivaci,
publikaci či replay. Dříve přijatý snapshot zůstává auditovatelný po revokaci,
ale revokace nebo změněná autorita blokuje každý nový přenos.

## Crash boundaries

- Pád před uložením outbound balíku nemá síťový účinek.
- Pád po uložení a před requestem ponechá `prepared` pro explicitní reconcile.
- Pád nebo timeout po requestu ponechá `unknown`; nevytváří nový snapshot.
- Inbound transakce publikuje snapshot a idempotentní receipt společně.
- Lokální ani přijatá historie se nepřepisuje a projektový Git/index se této
  operace neúčastní.

## Důsledky

Obousměrná synchronizace znamená dvě explicitní jednosměrné operace. PoC
neřeší průběžný background sync, editaci přijaté historie, stažení vzdáleného
run detailu ani plné capability profily `F-M5-TRUST-01`. Starší historie bez
dostupného manifest payloadu zachová pouze jeho ID a nesmí předstírat, že lze
původní backend request rekonstruovat.
