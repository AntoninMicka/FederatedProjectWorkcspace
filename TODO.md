<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — aktuální feature dávka WF-03

Aktuální milník: **M1 — Single-node project workspace**. Gate M0 je splněný v rozsahu architecture spike ([review a důkazy](WORK_LOG.md#gate-m0)); Gate M1 zůstává otevřený. Žádná aplikační část zatím není production-ready.

[Roadmapa a gates](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Další backlog](BACKLOG.md) · [Dokončená práce a ověření](WORK_LOG.md) · [Pravidla](AGENTS.md)

Od 2026-09-14 platí **jedna dávka = jedna feature větev = jeden PR do `develop`**. Milník není dávka. Starší dokončená evidence je ve WORK_LOG, otevřené položky v BACKLOG; zde zůstává jen aktivní WF-03.

## Aktivní feature dávka — WF-03

- [ ] [in progress] **WF-03 — Feature dávky, větve a PR do develop (implemented, 2026-09-14; dokumentační ověření předání probíhá).** Explicitní požadavek uživatele před importem.
- Navržená větev: `feature/wf-03-feature-batches`; základ/cíl jediného PR: `develop`. Větev ani PR nebyly tímto krokem vytvořeny a merge není doložen.
- Rozsah: AGENTS pravidla, TODO přechod a backlog sestavený z konkrétních feature dávek. Mimo rozsah: aplikace, import implementace, automatický git push/PR/merge a uzavření M1 gate.
- Akceptace: konzistence pravidel a plánovacích karet, zachované ID/důkazy, každý připravený scope jedna reviewovatelná feature; dokumentační ověření a předání/sloučení jednoho PR do develop. Pravidla předání byla zkontrolována; nyní doplněno povinné čištění a přesun staré evidence. PR ani merge nejsou doložené.
- Další připravená feature: **F-M1-IMPORT-01** v BACKLOG. Její načtení nezahajuje implementaci automaticky; dosavadní práci předem předat tak, aby nová větev nevznikla s nesouvisejícími změnami.

## K předání do backlogu

Žádné nové nepředané položky. Import F-M1-IMPORT-01 čeká v BACKLOG na předání WF-03; implementace nebyla zahájena.
