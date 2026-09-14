<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-DELETE-01: Ověření bezpečného odstranění dokumentu

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-DELETE-01 — Ověření bezpečného odstranění dokumentu

- Stav: [ ] [planned]; milník M1; cílová úroveň PoC validated.
- Původ: M1-08, konzistence po smazání v M1; ADR 0003/0016.
- Plánovaná větev: `feature/f-m1-delete-01-validation`; dosud nezaložena. Základ a jediný PR do `develop` po začlenění závislostí; implementace této dávky nezahájena.
- Výstup: ověření existující implementace odstranění a opravy nutné pro její akceptaci.
- Mimo rozsah: koš, UI obnovy historie, mazání sources, federovaná synchronizace.
- Závislosti: existující Artifacts/Workspace v `develop`; relační kontrakt F-M1-INDEX-01, pokud jej dokončení ovlivní.
- Akceptace jednoho PR: sidecar/frontmatter, blokování příchozích vztahů, stale/dirty, retry a procesní přerušení, skutečný Qt, celá sada a dokumentace.

- [ ] [planned] **M1-08 — Bezpečné odstranění dokumentu (implemented, 2026-09-14; částečně ověřeno indexní dávkou).** Navazující otevřený požadavek M1 na konzistenci po smazání. Nativní editor vyžaduje potvrzení, Artifacts odstraní verzované soubory dokumentu a metadata jednou Workspace operací; zachová Git historii, odmítne příchozí strukturované vztahy a neplatný výsledný snapshot ještě před přípravou journalu. Reuse stávajícího writer locku, CAS, operation_id/receipt a recovery podle ADR 0003/0016; opakování smazání používá stejný operation_id. Podmínka dokončení: cílené testy sidecar/frontmatter, vztahů, stale/dirty, retry a procesních přerušení; celá sada a ověření Qt. Původní implementační krok neměl samostatné ověření. F-M1-INDEX-01 následně doložila backendové odstranění a blokování příchozího vztahu v integračním testu; ostatní akceptační scénáře této dávky zůstávají otevřené. Gate M1 zůstává otevřený.

### Poznámky k zahájení

- Závislost F-M1-INDEX-01 je začleněna v lokálním `develop` (`948bf69`, PR #16). Současná implementace odstranění se nepřepisuje bez zjištěné chyby.
- Nejbližší úkol je M1-08 výše: doplnit chybějící cílené/recovery/Qt scénáře a teprve podle výsledků provést nutné opravy. Hranice ADR 0003/0016 zůstávají výchozím kontraktem.
