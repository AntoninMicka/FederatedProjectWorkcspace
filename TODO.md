<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-META-02: Implementace importní provenance v2

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-META-02 — Implementace importní provenance v2

- Stav: [x] [completed]; milník M1; dosažená úroveň PoC validated.
- Původ: odložená implementace F-M1-META-01/V-04 a ADR 0023; uživatelské pokračování na další úkol 2026-09-17.
- Skutečná větev: `feature/f-m1-meta-02-provenance-v2`, vytvořená z čistého `develop` (`0e61e64`) po doloženém začlenění F-M1-SOURCE-01 v PR #20 (`7152d64`). Jediný PR do `develop`; není vytvořen.
- Výstup: souběžné čtení v1/v2 v parseru a indexu, zápis nových importů v2, explicitní migrace pouze doložitelných v1 importů a UI zobrazení provenance.
- Mimo rozsah: automatická plošná migrace, vymýšlení původního autora/času/revize, obecný transition validátor F-M1-SOURCE-02 a externí konektory.
- Závislosti: ADR 0023, F-M1-SOURCE-01/ADR 0024 a existující import/Workspace/Index/preview.
- Akceptace jednoho PR: striktní formát/limity, smíšený snapshot, původní bajty/hash, expected-HEAD/retry/receipt, procesní recovery před/po commitu, atomická indexace/migrace, skutečný Qt a celá sada.

- [x] [completed] **F-M1-META-02-A — Parser a projekce v2 (PoC validated, 2026-09-17).** Striktní parser přijímá v1/v2 ve smíšeném snapshotu, podmíněný `import` blok odmítá neznámá a nedoložená pole a source hash váže skutečné bajty. Index v2 normalizuje úplný importní blok; v0/v1 migruje pouze atomickým rebuildem z validovaného HEAD a starou/částečnou projekci nevydá.
- [x] [completed] **F-M1-META-02-B — Nový import a doložená migrace (PoC validated, 2026-09-17).** Native import zapisuje schema v2 a request digest váže bajty, hash i všechna vstupní provenance pole. Explicitní migrace vyžaduje původní Workspace importní commit, ancestry, přidání artefaktu, trailer operace a shodu neměnných polí/bajtů; žádná externí fakta nevymýšlí.
- [x] [completed] **F-M1-META-02-C — UI, recovery a akceptace (PoC validated, 2026-09-17).** Podrobnosti bezpečně zobrazují čas/aktéra importu, hash, importér a dostupná volitelná pole. Retry/receipt, odmítnutí chyb, pády před/po CAS a během indexace, skutečný Qt/WebEngine, balení i offline provoz prošly.

### Průběžný návrh a recovery — 2026-09-17

- Reuse/adapt stávajícího striktního parseru, nativního importu, Workspace/Journal/Git/index lifecycle a bezpečného preview. Soukromá inventura neposkytuje vhodnější komponentu; nový framework ani databáze nejsou potřeba.
- Nový import i explicitní migrace jsou jedna idempotentní operace: request a přesné bajty se svážou digestem, journal vznikne před publikací kandidáta, ref se posune CAS a index se po commitu atomicky obnoví. Pád před refem v2 nezveřejní; po refu recovery dokončí index a receipt bez druhého commitu.
- Migrace nebude odhadovat externího autora, čas, URL ani revizi. Převzetí `created_at`/`author_id` a výpočet hashe je dovoleno jen po ověření explicitně zadaného commitu, který původní source artefakt přidal se shodnými bajty a neměnnými poli.

### Výsledek a ověření — 2026-09-17

- Implementace: `spikes/metadata.py`, `spikes/source_import.py`, `spikes/storage.py` a bezpečné zobrazení v `spikes/desktop_ui.py`; kontrakt a provozní popis aktualizují ADR 0022/0023/0024, DATA_MODEL a návody.
- Cílená sada `python3 -m unittest tests.test_metadata tests.test_source_import tests.test_index_projection -v`: 24 testů prošlo bez chyb a skipů. Pokrývá striktní v2, smíšený v1/v2 snapshot, nesoulad hashe, nové importy, volitelnou doloženou provenance, idempotentní migraci a procesní pády před/po publikaci i při indexaci.
- Závěrečná sada `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v` mimo socketový sandbox: 209 testů, 205 prošlo, čtyři volitelné libgit2 probe testy přeskočeny, bez chyb (130,346 s). Skutečný WebEngine ověřil i zobrazení v2 hashe/aktéra/importéra; běžely Qt dialogy, izolovaná instalace/upgrade/remove `.deb` a offline desktop.
- Před závěrečným úspěšným během jednou selhal nesouvisející HTTPS browser smoke na TLS handshake; izolovaný retry prošel a celý opakovaný běh výše následně prošel. Nejde o routerové ani cloudové ověření.
- Omezení: migrace je explicitní programová operace, nikoli plošný UI wizard. Obecná neměnnost přes všechny publish/fast-forward/merge cesty, metadata editace source a import navazující verze zůstávají F-M1-SOURCE-02. Výpadek napájení, pád uvnitř libovolného syscallu a cílové zařízení nejsou tímto lokálním PoC doloženy; Gate M1 zůstává otevřený. PR není vytvořen ani sloučen.
