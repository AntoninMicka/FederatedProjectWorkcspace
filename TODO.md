<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-SOURCE-01: Kontrakt neměnnosti a verzování zdrojů

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-SOURCE-01 — Kontrakt neměnných zdrojů a jejich verzí

- Stav: [x] [completed]; milník M1; cílová úroveň designed.
- Původ: V-05 a neměnné importované zdroje z roadmapy; uživatelské pokračování na další úkol 2026-09-15.
- Skutečná větev: `feature/f-m1-source-01-versioning`, vytvořená z čistého `develop` (`9acd0ef`) po doloženém začlenění F-M1-META-01 v PR #19. Jediný PR do `develop`; není vytvořen.
- Výstup: pravidla neměnných bajtů a provenance pod jedním source UUID, povolených metadata-only změn, nové verze s novým UUID a transition validace přímých Git změn.
- Mimo rozsah: implementace transition validátoru/UI, provenance v2, odstranění zdrojů, konektory a content-addressed storage.
- Závislosti: F-M1-META-01/ADR 0023; existující nativní import, Workspace/Journal/Index a vztahy.
- Akceptace jednoho PR: příklady stejného zdroje/nové verze, povolené změny metadat versus obsahu, konflikt při externí změně a vymezené validační/recovery hranice. Designed výstup se nevydává za vynucenou globální neměnnost.

- [x] [completed] **V-05 — Vymezit neměnnost zdrojů (designed, 2026-09-15).** Obsahové bajty, basename, identita a importní provenance jsou pod jedním source UUID neměnné. Povolené jsou verzované projektové anotace; privacy lze uvolnit jen explicitní autorizovanou reklasifikací.
- [x] [completed] **F-M1-SOURCE-01-A — Verze a duplicity (designed, 2026-09-15).** Nové bajty/revize dostanou nové UUID a mohou nést vztah `supersedes` na předchůdce. SHA-256 shoda pouze upozorňuje na stejné bajty; neslučuje automaticky odlišnou provenance, privacy ani projektový význam.
- [x] [completed] **F-M1-SOURCE-01-B — Transition validace a recovery (designed, 2026-09-15).** Snapshot kontrola nestačí: publish/fast-forward/merge musí porovnat base a kandidáta a odmítnout změnu chráněných polí/bajtů stejného UUID. Nová verze publikuje obsah, sidecar a vztah jednou expected-HEAD/Journal/CAS/index/receipt operací.

### Výsledek a ověření — 2026-09-15

- Kontrakt: [ADR 0024](docs/adr/0024-source-immutability-and-versioning.md); datový souhrn a vztah `supersedes`: [DATA_MODEL](DATA_MODEL.md).
- Reuse/adapt stávajícího importu, metadatového validátoru, Git historie, Workspace/Journal/Index a relačních vztahů. Nová databáze ani externí komponenta nejsou potřeba.
- Věcná kontrola proti importu, validátoru, mazání a existujícím testům potvrzuje, že dnešní UI source neupravuje ani nemaže, ale obecný transition invariant zatím není implementovaný. Kód/testy se nemění; celá sada se neopakovala.
- Omezení: pouze designed. Čerstvě přijatý repozitář bez externího důkazu neumí prokázat pravost původního souboru; v2 hash ani transition validace nejsou implementovány. Gate M1 zůstává otevřený.

## K předání do backlogu

- [ ] [planned] **F-M1-SOURCE-02 — Vynutit neměnné zdroje a import navazující verze (cílová úroveň: PoC validated).** Implementovat transition validaci všech publish/merge cest, metadata-only editaci zdroje, import nové verze s novým UUID/`supersedes`, bezpečnou detekci byte-identity a UI konfliktu. Propojit s F-M1-META-02 bez duplikace parseru/migrace. Podmínka dokončení: v1/v2, přímá Git změna obsahu/metadat, fast-forward/merge/stejné UUID, privacy reclassification, expected-HEAD/retry/receipt, pády před/po CAS a indexu, skutečný Qt a celá sada. Jde o samostatnou budoucí feature, nikoli podmínku designed dávky F-M1-SOURCE-01.
