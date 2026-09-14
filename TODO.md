<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-INDEX-01: Relační projekce projektového indexu

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-INDEX-01 — Relační projekce projektového indexu

- Stav: [ ] [planned]; milník M1; cílová úroveň PoC validated.
- Původ: V-03 a zbývající integrace metadat/indexu M1; ADR 0002/0003.
- Větev: `feature/f-m1-index-01-relations`, založena 2026-09-14 z lokálního `develop` (`0849ec8`). Předchozí necommitnuté dokumentační předání importní dávky zachováno v pracovním stromu. Cíl jediného PR: `develop`; PR zatím nevytvořen, implementace nezahájena.
- Výstup: doložený kontrakt a implementace lokálně obnovitelné projekce vztahů/metadat, nesoucí přesný commit ID.
- Mimo rozsah: změna Git autority, synchronizace SQLite, nové LLM/RAG databáze.
- Závislosti: stabilní metadata kontrakt v `develop`; importní změny pouze pokud jej ovlivní.
- Akceptace jednoho PR: rebuild z HEAD, stale/pending odmítnutí, referenční integrita a změny po rename/delete/import, bezpečná migrace projekce, testy a dokumentace.

### Úkoly a ověření

- [ ] [planned] **F-M1-INDEX-01 — Relační projekce (cílová úroveň: PoC validated).** Před implementací prověřit současný Index, validátor metadat a testy; vymezit projekci, migraci a recovery podle ADR 0002/0003. Doplnit rebuild a kontrolu přesného commit ID, relační integritu a ověření rename/delete/import. Dokončit celou sadu a dokumentaci podle akceptace výše.

V-03 — Vyjasnit omezení projekce indexu — je součástí této feature; jeho aktuální stav je zde. Index nyní validuje vztahy, ale ukládá pouze id/title a commit ID. Před relačními dotazy navrhnout a otestovat rozšíření projekce; neoznačovat existující index za kompletní databázi vztahů. Git zůstává autoritou, SQLite index je obnovitelná lokální projekce a není journalem rozpracovaných operací.
