<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# F-M5-FULL-DATA-SYNC-01 — přenos úplných projektových podkladů

Rozšíření původního obousměrného sync z
[ADR 0042](adr/0042-bidirectional-native-git-sharing-sync.md).
Rozhodnutí, limity a recovery: [ADR 0081](adr/0081-complete-project-data-sync.md).

Přenášejí se původní artefakty, metadata, vztahy, zdroje/raw podklady,
reportingové záznamy a historie povolených větví. Projektové RW chaty
pokračují přes dosavadní podepsaný payload. Oprávnění řídí původní
Administration/trust/mapping; credentials a provozní journaly zůstávají místní.

Podklad nepřítomný v přenášené historii odmítne celý přenos před publikací.
Skrytou větev musí zvlášť povolit odpovídající policy; sync ji sám nepřidá.
Kolektor ani model se pouhým přijetím dat nespouští. Nativní zpracování používá
skutečně přenesené piny po samostatném oprávnění a kontrole dostupnosti.

## Ověření

`python3 -m unittest tests.test_full_data_sync -v` zahrnuje:

- Celou zprávu, zdrojové záznamy a původní raw bajty v obou směrech;
  opakování bez nových commitů nebo opakovaného connector fetch.
- Podvržený, ale platně podepsaný bundle s chybným reportingovým pinem:
  odmítnutí před změnou cílového projektu.
- Pin jen ve skryté větvi: omezený bundle se odmítne; scope povolující
  obě větve je úplný a projde.
- Bare repo s unborn HEAD a přesný kontext každého historického commitu.
- Skutečný subprocess exit po ref update před checkout/indexem a opakování
  původního requestu: roll-forward bez další publikace.
- Explicitní sémantické review divergence nezávislých zdrojů a konvergenci.
- Dvě základní publikace téhož období: textově čistý merge se odmítne
  a oba heady/incoming historie zůstanou zachované.
- S MON-08 schématy také WatchDefinition a vybrané SourceFinding; příjemci
  nevznikne aktivní RSS binding a neproběhne GET. Bez těchto schémat je
  pouze tento integrační test explicitně skipped.

Regrese: `tests.test_federation_sync`, `tests.test_reporting`,
`tests.test_project_replication`. Skutečné HTTPS testy potřebují povolený
localhost; odmítnutí sandboxem není ověření produktu.

Doplňkový PoC používá dva oddělené dočasné profily s vlastními podpisovými
identitami, účty/mapping a připnuté localhost HTTPS. Přenáší zprávu/raw bytes,
projektový chat, stáhne projekt vzniklý jen na serveru a ověřuje automatický
přenos dalšího commitu. Nepracuje s uživatelskými projekty a nedokládá dva
fyzické stroje. Doplňkové protokoly leží mimo zdrojový Git v `/tmp`.

Read-only pokus o přihlášení na dříve schválený Omnia cíl skončil odmítnutím
SSH autentizace. Fyzický PoC a lidská akceptace zůstávají nedoložené;
izolované výsledky je nesmějí nahrazovat.

## Výsledky tohoto řezu — 7. 11. 2026

- Cílené regrese transportu/reportingu/replikace a skutečného pádu procesu:
  55 testů, OK, 1 skipped (volitelný Qt průchod).
- Celá sada po poslední změně kódu/testů:
  `python3 -m unittest discover -s tests -v` — **1646 testů, OK,
  51 skipped**, 729,402 s. Mezi přeskočenými je integrační test MON-08,
  protože tato schémata samostatný develop základ dosud neobsahuje.
- Dočasný složený checkout s MON-08 source
  `4620f19b71e763bd2e2ea12a479f21141854ddcb` a přesným transportním patchem:
  všech **9 testů `tests.test_full_data_sync` OK**, včetně monitorovacích
  definic/nálezů bez aktivace příjemce. Větve se tím nesloučily.
- Doplňkový izolovaný PoC přes skutečné připnuté HTTPS: OK; úplná zpráva,
  raw bytes a projektový chat, opačný přenos serverového projektu a další
  automatický přenos po změně dat. Credentials zůstaly ve fixture profilech.
- Dokumentační odkazy a `git diff --check`: OK.

Plná sada není fyzické ověření Omnia ↔ desktop ani lidská akceptace úkolu.
