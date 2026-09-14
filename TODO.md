<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-IMPORT-01: Nativní import zdrojových dokumentů

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a předání

- Větev: **`feature/f-m1-import-01-native-sources`**, založená z čistého lokálního `develop` při zahájení úkolu. PR do `develop` zatím nevytvořen; push/merge neprovedeny.
- Původ: uživatelem schválený import, zbývající požadavek M1; související V-04/V-05, ADR 0003/0016.
- Cílová úroveň: PoC validated. Aktuálně implemented, **neověřeno**.
- Výstup: nativní výběr Markdown/PNG/JPEG/PDF, zachování původních bajtů, sidecar metadata/privacy/provenance, potvrzený společný zápis a zobrazení v Podkladech.
- Mimo rozsah: externí konektory IMP-01–03, LLM, synchronizace, obecná migrace metadat a globální zákaz externích Git úprav zdrojů.
- Kontrakt: imported source má kind=source/provenance=external, vytvoření artefaktu znamená okamžik importu. Obsah je v nativním editoru nepozměnitelný, nová verze má nové UUID. Samostatné imported_at a původní autor externího zdroje nejsou novými schema fields; V-04/V-05 zůstávají mimo tento omezený kontrakt otevřené.

## Úkoly této feature

- [ ] [in progress] **F-M1-IMPORT-01 — Nativní import (implemented, 2026-09-14; neověřeno).** Sources adaptuje Artifacts/Workspace, originální soubor a metadata publikuje jedním commitem, request digest váže SHA-256 přesných bajtů a opakování stejné operation ID. Před přípravou journalu validuje výsledný snapshot. Native picker má explicitní potvrzení a retry/recovery; uložený source se zobrazí přes stávající Podklady/preview. Bez nové mutující HTTP route.
- [ ] [planned] **Ověření:** byte-identita Markdown včetně CRLF/frontmatter, PNG/JPEG/PDF, 16 MiB limit a nezávislý 4 MiB preview limit, unsafe/symlink/změněný zdroj, metadata/privacy, stale/dirty/busy/foreign, receipt/retry a procesní checkpointy, source-only editor hranice, skutečný Qt a celá sada testů. Testy ani kontrolní běhy zatím nebyly spuštěny.
- [ ] [planned] **Předání PR:** doložené výsledky, omezení a recovery, jeden PR do `develop`; po jeho uzavření vyčistit TODO podle AGENTS.

## K předání do backlogu

Ověření 2026-09-14: izolované backendové scénáře importu prošly (původní bajty včetně CRLF/frontmatter, PNG/JPEG/PDF hlavičky, metadata, receipt/retry, náhled Markdown/PNG/PDF, odmítnutí stale HEAD, jiného SHA-256 a symlinku). Obnova po skutečném ukončení procesu na osmi checkpointech prošla s jediným commitem a čistým pracovním stromem. První běh celých testů v sandboxu: 183 testů, 20 socketových errors a 20 volitelných skip; běží opakování mimo socketové omezení. Skutečný Qt odhalil blokující chybu `RuntimeError: Failed to connect signal finished()` při otevření ImportDialog: handler `finished` koliduje s QDialog signálem. Oprava zatím neprovedena, feature není připravena k merge. Dočasné ověřovací scénáře nejsou novými trvalými regresními testy.

Žádné nové nezávislé feature. Návaznosti V-04/V-05 zůstávají v BACKLOG se svými původními ID.

Závěrečný regresní běh mimo socketově omezený sandbox: `python3 -m unittest discover -s tests -v` — 183 testů, 163 prošlo, 20 volitelných přeskočeno, bez chyb, 49,613 s. Tento existující unittest běh neobsahuje nový ImportDialog smoke; jeho samostatně zjištěná Qt chyba proto dál blokuje akceptaci feature. Kompletní oprava/UI re-test zatím nebyly provedeny.

Oprava Qt blockeru (2026-09-14): handler přejmenován na operation_finished. Opakovaný skutečný Qt smoke prošel otevřením dialogu, zrušením potvrzení bez změny HEAD, potvrzeným importem, worker completion, zachováním přesných CRLF/frontmatter bajtů a čistým Git stromem. Qt blocker je odstraněný; po této opravě byla opakována pouze cílená UI kontrola, nikoli znovu celá regresní sada. PR/merge stále neprovedeny.
