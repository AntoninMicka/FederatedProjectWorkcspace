<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-DELETE-01: Ověření bezpečného odstranění dokumentu

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M1-DELETE-01 — Ověření bezpečného odstranění dokumentu

- Stav: [x] [completed]; milník M1; cílová úroveň PoC validated.
- Původ: M1-08, konzistence po smazání v M1; ADR 0003/0016.
- Skutečná větev: `F-M1-DELETE-01/M1-08`, vytvořená uživatelem; čistý pracovní strom při zahájení, základ `develop` (`948bf69`), přípravný commit `f2ccc1a`. Jediný PR do `develop`; není vytvořen.
- Výstup: ověření existující implementace odstranění a opravy nutné pro její akceptaci.
- Mimo rozsah: koš, UI obnovy historie, mazání sources, federovaná synchronizace.
- Závislosti: existující Artifacts/Workspace v `develop`; relační kontrakt F-M1-INDEX-01, pokud jej dokončení ovlivní.
- Akceptace jednoho PR: sidecar/frontmatter, blokování příchozích vztahů, stale/dirty, retry a procesní přerušení, skutečný Qt, celá sada a dokumentace.

- [x] [completed] **M1-08 — Bezpečné odstranění dokumentu (implemented, 2026-09-14; částečně ověřeno indexní dávkou).** Navazující otevřený požadavek M1 na konzistenci po smazání. Nativní editor vyžaduje potvrzení, Artifacts odstraní verzované soubory dokumentu a metadata jednou Workspace operací; zachová Git historii, odmítne příchozí strukturované vztahy a neplatný výsledný snapshot ještě před přípravou journalu. Reuse stávajícího writer locku, CAS, operation_id/receipt a recovery podle ADR 0003/0016; opakování smazání používá stejný operation_id. Podmínka dokončení: cílené testy sidecar/frontmatter, vztahů, stale/dirty, retry a procesních přerušení; celá sada a ověření Qt. Původní implementační krok neměl samostatné ověření. F-M1-INDEX-01 dříve doložila backendové odstranění a blokování příchozího vztahu; tato dávka nyní ověřila všechny své akceptační scénáře. Gate M1 zůstává otevřený.

### Základ a postup

- Závislost F-M1-INDEX-01 je začleněna v lokálním `develop` (`948bf69`, PR #16). Současná implementace odstranění se nepřepisuje bez zjištěné chyby.
- Nejbližší úkol je M1-08 výše: doplnit chybějící cílené/recovery/Qt scénáře a teprve podle výsledků provést nutné opravy. Hranice ADR 0003/0016 zůstávají výchozím kontraktem.

### Ověření M1-08 — 2026-09-15

- Reuse stávající implementace bez změn aplikačního kódu; crash boundaries a recovery podle ADR 0003/0016 zůstávají beze změny.
- `M0_DESKTOP_TEST=1 QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_artifact_deletion -v`: 9 testů prošlo (16,350 s). Sidecar/frontmatter, přesné odstranění vlastněných cest a zachování historie/ostatních entit, příchozí vztahy z artefaktů i registrů, self/outgoing vztahy, opětovné vytvoření hlavního TODO, stale/dirty/staged/busy, neplatné vstupy/snapshot a odmítnutí sources.
- Procesní `os._exit(73)` na 18 hranicích sidecaru a 17 frontmatteru (35 přerušení), včetně `before-ref` a pěti checkpointů indexu: native open dokončí jeden commit, index neobsahuje odstraněné UUID, receipt zajistí idempotentní retry i po pozdějším commitu. Cizí znovuvytvořený soubor při pending zůstane zachován a recovery odmítne pokračovat.
- Skutečný Qt dialog: prostý text a výchozí Cancel, zrušení zachová draft i HEAD, potvrzení po ztracené odpovědi zachová původní operation_id pro retry, úspěch obnoví seznam a vyšle saved; reload dokončí operaci přerušenou v prepared.
- `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v`: 204 testů prošlo za 133,575 s, 4 volitelné libgit2 testy přeskočeny. Skutečné Qt/WebEngine, izolované balení/instalace a offline testy byly zapnuté.
- Omezení: pouze lokální Linux PoC. Bez cílového LXC/routerového ověření, výpadku napájení či přerušení uvnitř libovolného Git/SQLite syscallu. Koš, UI obnovy odstraněných dokumentů a mazání sources nejsou součástí dávky. Gate M1 zůstává otevřený.
