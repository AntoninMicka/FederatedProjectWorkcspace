<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-META-01: Přesný kontrakt metadat a importní provenance

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-META-01 — Přesný kontrakt metadat a importní provenance

- Stav: [x] [completed]; milník M1; cílová úroveň designed.
- Původ: V-04, společná metadata a importní evidence z roadmapy; uživatelské pokračování na další úkol 2026-09-15.
- Skutečná větev: `feature/f-m1-meta-01-contract`, vytvořená z čistého `develop` (`5a3529d`) po doloženém začlenění F-M1-DELETE-01 v PR #17 (`ab296fd`). Jediný PR do `develop`; není vytvořen.
- Výstup: přesný význam povinných/volitelných polí v1 a navržený verzovaný kontrakt v2 pro importéra, původního autora, čas importu, hash a další doloženou provenance.
- Mimo rozsah: implementace parseru/indexu/importéru v2, plošná migrace Git dat, externí konektory a vynucení celoživotní neměnnosti zdrojů.
- Závislosti: importní/indexní kontrakty v `develop`; zachování existujících dat, ID a validního v1.
- Akceptace jednoho PR: konzistence DATA_MODEL/validátoru/ADR, konkrétní příklady pro artefakt a registry i import, rozhodnutí o nové verzi a popis migrace/recovery. Návrh sám není implementovaná provenance.

- [x] [completed] **V-04 — Sjednotit přesný kontrakt metadat (designed, 2026-09-15).** `spikes/metadata.py` zůstává autoritou spustitelného v1: registry povinně nesou `status`/`body`, zatímco `relations` jsou volitelné. `created_at` je vznik entity v projektu a u nativního importu čas importu; `author_id` je projektový aktér/importér, nikoli původní autor. Neznámá provenance se nevymýšlí.
- [x] [completed] **F-M1-META-01-A — Rozhodnout verzi a importní evidenci (designed, 2026-09-15).** Striktní v1 se nemění; podrobná evidence vyžaduje v2 s podmíněným objektem `import`: povinné `imported_at`, `imported_by`, `content_sha256`, `importer.name`, volitelné doložené `source_author`, `source_created_at`, `source_revision` a `importer.version`. `source_url` zůstává volitelným top-level locatorem.
- [x] [completed] **F-M1-META-01-B — Vymezit kompatibilitu a recovery (designed, 2026-09-15).** Budoucí čtenář v2 podporuje smíšený validovaný snapshot v1/v2; automatická plošná migrace se neprovádí. Explicitní migrace doplní jen doložitelné hodnoty a použije expected HEAD, writer lock, validaci kandidáta, journal před CAS, commit, index/recovery a receipt dle ADR 0003.

### Výsledek a ověření — 2026-09-15

- Kontrakt a příklady: [ADR 0023](docs/adr/0023-metadata-and-import-provenance.md); souhrn současného v1 a navrženého v2: [DATA_MODEL](DATA_MODEL.md).
- Reuse/adapt stávajícího striktního validátoru, nativního importního request digestu, Git blobů a Workspace/Journal/Index lifecycle. Nový parser, storage ani externí komponenta se pro designed výstup nezavádí.
- Věcná kontrola proti `spikes/metadata.py`, `spikes/source_import.py`, `spikes/storage.py` a jejich testům potvrzuje popsané současné chování v1. Aplikační kód, schéma a testy nebyly změněny; celá testovací sada se proto neopakovala.
- Omezení: v2 je pouze designed. Současný import nadále zapisuje v1 bez `import` bloku; parser i index v2 odmítají jako neznámou verzi. Implementace a migrační/recovery testy vyžadují samostatnou navazující feature. Gate M1 zůstává otevřený.

## K předání do backlogu

- [ ] [planned] **F-M1-META-02 — Implementovat importní provenance v2 (cílová úroveň: PoC validated).** Implementovat souběžné čtení v1/v2 v parseru a indexu, zápis nových importů v2, explicitní migraci pouze doložitelných v1 importů a UI zobrazení všech dostupných provenance polí. Podmínka dokončení: striktní formát/limity, smíšený snapshot, původní bajty/hash, odmítnutí vymyšlených hodnot, expected-HEAD/retry/receipt, procesní recovery před/po commitu, atomická indexace/migrace, skutečný Qt a celá sada. Jde o samostatnou budoucí feature, nikoli podmínku dokončení designed dávky F-M1-META-01.
