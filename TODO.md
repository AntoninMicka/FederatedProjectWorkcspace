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
- Cílová úroveň: PoC validated. Aktuálně implemented, částečně ověřeno; rozsah důkazů a zbývající kontroly níže.
- Výstup: nativní výběr Markdown/PNG/JPEG/PDF, zachování původních bajtů, sidecar metadata/privacy/provenance, potvrzený společný zápis a zobrazení v Podkladech.
- Mimo rozsah: externí konektory IMP-01–03, LLM, synchronizace, obecná migrace metadat a globální zákaz externích Git úprav zdrojů.
- Kontrakt: imported source má kind=source/provenance=external, vytvoření artefaktu znamená okamžik importu. Obsah je v nativním editoru nepozměnitelný, nová verze má nové UUID. Samostatné imported_at a původní autor externího zdroje nejsou novými schema fields; V-04/V-05 zůstávají mimo tento omezený kontrakt otevřené.

## Úkoly této feature

- [x] [completed] **F-M1-IMPORT-01 — Nativní import (implemented, 2026-09-14; částečně ověřeno).** Sources adaptuje Artifacts/Workspace, originální soubor a metadata publikuje jedním commitem, request digest váže SHA-256 přesných bajtů a opakování stejné operation ID. Před přípravou journalu validuje výsledný snapshot. Native picker má explicitní potvrzení a retry/recovery; uložený source se zobrazí přes stávající Podklady/preview. Bez nové mutující HTTP route.
- [ ] [completed] **Ověření:** byte-identita Markdown včetně CRLF/frontmatter, PNG/JPEG/PDF, 16 MiB limit a nezávislý 4 MiB preview limit, unsafe/symlink/změněný zdroj, metadata/privacy, stale/dirty/busy/foreign, receipt/retry a procesní checkpointy, source-only editor hranice, skutečný Qt a celá sada testů. Přidané cílené testy v `tests/test_source_import.py` ověřují: 1) podporu a uložení Markdown/PNG/JPEG/PDF, 2) odmítnutí nepodporovaného typu a překročení 16 MiB, 3) nezávislost náhledového limitu 4 MiB na importním limitu.
- [ ] [in progress] **Předání PR:** zakreslit scope, důkazy, omezení a recovery; připravit jeden PR `feature/f-m1-import-01-native-sources -> develop` bez mergování.

## Návrh předání PR

- Scope: kompletní implementace nativního importu Markdown/PNG/JPEG/PDF přes picker a importní pipeline, validace integrity (SHA-256 byte-identita), sidecar metadata (`kind=source`, `provenance=external`, `privacy=project`), zobrazení přes Podklady/preview, journaling + recovery flow, validace limitů a bezpečnostních hranic.
- Důkazy: `tests/test_source_import.py` (lokální cílené scénáře), dočasný harness `/tmp/fw-import-recovery-check.py` (restart a checkpointy), real-time offscreen Qt smoke, a úplný výpis ověřovací sekce v TODO.
- Omezení: mimo testy nebylo ověřeno nasazení na cílové hardwarové instance/routery; `WorkingDirectory`/deploy path a externí LXC scénáře jsou mimo rozsah; Gate M1 zůstává otevřený.
- Recovery: retry přes stejné `operation_id` vrací původní receipt; stale/retry konflikty a cizí změny po prepare aktivují `RecoveryConflict`; po explicitní čisté obnově se import dokončí deterministicky, bez pending operací a při zachování cizích změn.

## Důkazy ověření — 2026-09-14

- Uživatel potvrdil import a zobrazení zdroje ve skutečném desktopu.
- Po opravě kolize ImportDialog.finished se signálem Qt: skutečný offscreen Qt dialog a worker prošly; načtení aktivuje výběr souboru. Celá stávající sada po opravě: 183 testů, 163 prošlo, 20 přeskočeno, bez chyb (49,942 s, mimo socketová omezení sandboxu). Sada sama nepokrývá všechny nové importní scénáře.
- Izolovaný dočasný harness /tmp/fw-import-recovery-check.py: 17 skupin kontrol prošlo. Odmítnuty unsafe názvy, symlink, adresář, nepodporovaný formát, neplatné UTF-8/NUL, zdroj nad 16 MiB, změna při čtení, chybný digest a metadata. Dirty tree a obsazený writer lock odmítnuty bez přepsání cizích dat. Identický retry vrací původní receipt, změněný intent a stale HEAD jsou odmítnuty.
- Proces byl ukončen os._exit(73) na prepared, file:0, file:1, applied, files-applied, commit-created, commit-ready, ref-updated, committed, git-indexed, indexed a completed. Po restartu ve všech 12 případech přesné původní Markdown bajty včetně CRLF/frontmatter, kind=source/provenance=external/privacy=project, právě jeden commit, čistý Git a žádná pending operace. Cizí změna po přípravě vyvolá RecoveryConflict a zůstane zachována; po jejím explicitním odstranění pouze v testovací fixture recovery dokončí import.
- Harness není trvalý regresní test; živý LXC/router ani uživatelské projekty nebyly měněny. Tato kontrola neuzavírá celou dávku ani Gate M1.
- Definice obousměrných typů vazeb (`supports/supported_by`, `contains/part_of`, `depends_on`, `implements`, `derived_from`, `references`, `cites`, `produces`) byla doplněna v [DATA_MODEL.md](DATA_MODEL.md).

## K předání do backlogu

Ověření 2026-09-14: izolované backendové scénáře importu prošly (původní bajty včetně CRLF/frontmatter, PNG/JPEG/PDF hlavičky, metadata, receipt/retry, náhled Markdown/PNG/PDF, odmítnutí stale HEAD, jiného SHA-256 a symlinku). Obnova po skutečném ukončení procesu na osmi checkpointech prošla s jediným commitem a čistým pracovním stromem. První běh celých testů v sandboxu: 183 testů, 20 socketových errors a 20 volitelných skip; běží opakování mimo socketové omezení. Skutečný Qt odhalil blokující chybu `RuntimeError: Failed to connect signal finished()` při otevření ImportDialog: handler `finished` koliduje s QDialog signálem. Oprava zatím neprovedena, feature není připravena k merge. Dočasné ověřovací scénáře nejsou novými trvalými regresními testy.

Žádné nové nezávislé feature. Návaznosti V-04/V-05 zůstávají v BACKLOG se svými původními ID.

Závěrečný regresní běh mimo socketově omezený sandbox: `python3 -m unittest discover -s tests -v` — 183 testů, 163 prošlo, 20 volitelných přeskočeno, bez chyb, 49,613 s. Tento existující unittest běh neobsahuje nový ImportDialog smoke; jeho samostatně zjištěná Qt chyba proto dál blokuje akceptaci feature. Kompletní oprava/UI re-test zatím nebyly provedeny.

Oprava Qt blockeru (2026-09-14): handler přejmenován na operation_finished. Opakovaný skutečný Qt smoke prošel otevřením dialogu, zrušením potvrzení bez změny HEAD, potvrzeným importem, worker completion, zachováním přesných CRLF/frontmatter bajtů a čistým Git stromem. Qt blocker je odstraněný; po této opravě byla opakována pouze cílená UI kontrola, nikoli znovu celá regresní sada. PR/merge stále neprovedeny.
