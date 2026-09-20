<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-PROJECT-LOCATION-01: Umístění projektů a webový import

Milník M1; jedna dávka, větev `feature/f-m1-project-location-web-import`, budoucí
PR do `develop`. [Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; implementace a lokální akceptace jsou hotové,
  dávka čeká na uživatelem řízený commit/push/PR/merge. Aktivováno po začlenění
  PR #36 dne 2026-09-20 na přímý požadavek uživatele.
- Původ: opravit desktopové vytvoření projektu mimo domácí složku a zapamatovat
  výchozí rodičovskou složku; zpřístupnit registraci existujícího projektu a
  opravu jeho cesty; doplnit import souborů ve webové variantě.
- Výstup: node-local `projects_root`, nativní volby pro registraci a opravu
  umístění a autentizovaný bounded web upload, který reuse stávající immutable
  source import a Workspace transaction.
- Recovery: vytvoření/registrace zachovávají uzlový journal. Oprava cesty nejprve
  pod uzlovým zámkem ověří stejné project UUID, Git HEAD, filesystem a absenci
  pending projektové operace; journal owner a node registraci mění obnovitelně
  přes stejný operation receipt. Web retry váže stejné UUID, bajty, hash a
  operation ID; projektový zápis obnovuje Workspace.
- Mimo rozsah: přesun autoritativního projektového Git repozitáře aplikací,
  přesun lokálního stavu mezi filesystemy, import celého projektu přes browser,
  `local-only` data přes síť a odstranění projektu.

## Aktivní části dávky

- [x] [completed] **F-M1-PROJECT-LOCATION-01-A — Reuse a crash kontrakt
  (designed).** Adaptovány `ProjectCreation.register`, uzlový operation journal,
  `Projects`, `Sources` a Workspace; nový framework ani storage nevzniká.
- [x] [completed] **F-M1-PROJECT-LOCATION-01-B — Výchozí složka, registrace a
  oprava umístění (implemented).** Desktop ukládá potvrzený rodič do node-local
  konfigurace, dovoluje výběr mimo home, načte existující validní Git projekt a
  opraví přesunutou registraci. Cross-filesystem přesun stavu se bezpečně odmítá.
- [x] [completed] **F-M1-PROJECT-LOCATION-01-C — Webový import zdrojů
  (implemented).** Web přijímá Markdown/PNG/JPEG/PDF do 16 MiB, zachová přesné
  bajty a SHA-256, vyžaduje write roli a odmítá `local-only`; retry nevytvoří
  druhý commit.
- [x] [completed] **F-M1-PROJECT-LOCATION-01-D — Regrese, dokumentace a
  akceptace (PoC validated).** Rozšířená cílená sada prošla 63 testy se 4
  podmíněnými skipy. Finální úplná sada prošla: 325 testů, 22 podmíněných skipů.
  Samostatně prošel skutečný Qt/WebEngine smoke vytvoření/restartu desktopu a
  webového login/catalog/logout. Python kompilace, syntaxe výsledného webového
  JavaScriptu a `git diff --check` prošly. Skutečný browser file-picker průchod
  nebyl automatizován; HTTPS importní endpoint, přesné bajty nad 64 KiB, RBAC,
  privacy a idempotentní retry ověřují integrační testy. Reálný externí disk s
  odlišným filesystemem není podporovaná oprava cesty bez samostatně navrženého
  přesunu lokálního stavu.
