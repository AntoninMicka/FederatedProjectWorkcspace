<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M1-PROJECT-ROOT-01: Vytvoření v existující prázdné složce

Milník M1; jedna dávka, větev `feature/f-m1-project-existing-root`, budoucí
PR do `develop`. [Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivováno 2026-09-20 na přímý uživatelský
  report, že vytvoření do existujícího kořene nefunguje.
- Původ: F-M1-PROJECT-LOCATION-01 vytvořil/uložil rodičovskou složku, ale
  odmítal i prázdný adresář již zvolený jako cílový kořen.
- Výstup: desktop a `ProjectCreation.create()` přijmou novou nebo existující
  prázdnou vlastněnou složku bez symlinků; obsah ani existující Git projekt se
  nepřepisují.
- Recovery: journal ukládá inode existujícího cíle. Staging se s prázdným cílem
  atomicky vymění; po pádu se pokračuje jen při shodě inode/obsahu, jiný cíl se
  zachová jako konflikt. Stav, Git commit a node registrace nadále používají
  existující receipt a hranice ADR 0015.
- Mimo rozsah: převzetí neprázdného adresáře, import existujícího Git projektu
  (řeší `register`), přesun repozitáře/stavu nebo odstranění projektu.

## Aktivní části dávky

- [x] [completed] **F-M1-PROJECT-ROOT-01-A — Kontrakt a recovery (designed,
  implemented).** Reuse `ProjectCreation`, jeho node-local journal, `renameat2`
  a stávající receipt. Existující prázdný cíl je identifikován inode/dev;
  nepřibývá nový storage ani framework.
- [x] [completed] **F-M1-PROJECT-ROOT-01-B — Služba a desktopový vstup
  (implemented).** Vytvoření přijímá prázdný vlastněný root; UI jej správně
  popisuje. Obsah, symlink, jiný inode nebo neprázdný cíl se odmítne bez zápisu.
- [x] [completed] **F-M1-PROJECT-ROOT-01-C — Úplná regrese a předání
  (PoC validated).** Cílené `tests.test_project_creation`: 22 OK, 2 podmíněné
  Qt/WebEngine skipy. Úplná `unittest discover -s tests -q` prošla v povoleném
  lokálním prostředí; `git diff --check` a finální kontrola dokumentace prošly.
