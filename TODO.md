<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-SOURCE-02: Vynucení neměnných zdrojů a navazující verze

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-SOURCE-02 — Vynucení neměnných zdrojů a navazující verze

- Stav: [x] [completed]; milník M1; dosažená úroveň PoC validated; čeká na commit/push/PR a sloučení.
- Původ: odložená implementace F-M1-SOURCE-01/V-05 a ADR 0024; aktivováno po začlenění F-M1-META-02 v PR #22 dne 2026-09-17.
- Skutečná větev: `feature/f-m1-source-02-enforcement`, vytvořená z čistého `develop` (`fb613ad`). Jediný PR do `develop`; není vytvořen.
- Výstup: transition validace všech podporovaných publikačních cest (Workspace a první Git přenos), bezpečná metadata-only editace source, import navazující verze s novým UUID/`supersedes`, byte-identity detekce a UI konfliktu.
- Mimo rozsah: content-addressed storage, automatické slučování duplicit, externí konektory, obecná federace M5 a změna trust boundary externích zdrojů.
- Závislosti: začleněné ADR 0024, provenance v2 z PR #22, Workspace/Journal/Git/index a existující source import/preview.
- Akceptace jednoho PR: v1/v2, přímá Git změna obsahu/metadat, Workspace publish a převzatá Git historie se stejným UUID, explicitní privacy reclassification, expected-HEAD/retry/receipt, procesní pády před/po CAS a indexu, skutečný Qt a celá sada; budoucí obecný merge/fast-forward musí použít stejný validátor.

- [x] [completed] **F-M1-SOURCE-02-A — Transition validátor a všechny podporované publikační cesty (PoC validated).** V1/v2 source obsah, basename, identita a v2 import provenance se porovnávají před journalem i před Workspace commitem; odstranění source se odmítá. První Git přenos kontroluje každý parent→child přechod převzaté historie. Obecný merge/fast-forward projektů dosud není podporovaná aplikační cesta.
- [x] [completed] **F-M1-SOURCE-02-B — Metadata-only editace a navazující verze (PoC validated).** `Sources.edit_metadata` omezuje patch na anotace z ADR 0024, uvolnění privacy vyžaduje explicitní příznak; nový import může nést nové UUID a `supersedes`. Shodné bajty se hlásí v rámci projektu a automaticky se neslučují.
- [x] [completed] **F-M1-SOURCE-02-C — UI, recovery, dokumentace a akceptace (PoC validated).** Importní dialog nabízí předchůdce, ukazuje SHA-256 duplicity a chyby invariantu bez tichého přepisu. Standardní Workspace operation ID/journal/CAS/index/receipt hranice zůstaly společné; dokumentace a ADR byly aktualizovány.

### Ověření a omezení

- `python3 -m unittest tests.test_git_transfer tests.test_source_import tests.test_workspace tests.test_metadata -v`: 33 testů OK, 1 přeskočený Qt test.
- `M0_DESKTOP_TEST=1 QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_source_import.SourceImportTests.test_native_dialog_keeps_source_creation_separate_from_import_time -v`: 1 test OK.
- `python3 -m unittest discover -s tests -v` mimo socketový sandbox: 215 testů OK, 22 přeskočeno podmínkami prostředí. První sandboxový běh měl výhradně 20 `PermissionError` při bindu socketů; opakování mimo sandbox prošlo.
- Obecná synchronizace/merge/fast-forward projektů zůstává mimo současný rozsah. Dávka není uzavřená ani sloučená: PR dosud neexistuje.

### Recovery hranice před implementací

- Validace base/kandidát proběhne před posunem refu. Neplatný kandidát se nesmí publikovat ani projektovat do indexu.
- Metadata-only editace i import navazující verze použijí jednu serializovanou Workspace operaci: stabilní operation ID/request digest, journal před změnami, expected HEAD, CAS publikaci, rebuild indexu a trvalý receipt.
- Pád před CAS nezmění autoritativní HEAD; recovery dokončí nebo bezpečně odmítne připravenou operaci. Pád po CAS nesmí vytvořit druhý commit; index a receipt se obnoví z publikovaného HEAD.
- Merge/fast-forward přinášejí cizí kandidát a nesmějí obcházet stejnou transition validaci. Konflikt zůstane explicitní; automatická oprava nebo přepis historie není součástí dávky.
