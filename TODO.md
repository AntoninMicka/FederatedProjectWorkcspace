<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — DEV-IDE-TODO-01 (znovu otevřená akceptace)

Feature: lokální souborový IDE bridge, návaznost M6 / vlastní rozvoj produktu.
Větev `feature/dev-ide-todo-01-file-bridge`, základ/cíl PR `develop`.
PR dosud není vytvořen ani sloučen. Historické důkazy a původní úkoly:
[WORK_LOG](WORK_LOG.md#dev-ide-todo-01--lokální-souborový-ide-bridge--2026-10-28).
Uživatelské hlášení 2026-10-28 znovu otevřelo desktopovou akceptaci:
připojení vznikne, ale chybí nativní potvrzení a rozšíření se nenainstaluje.

- [ ] [in progress] **DEV-IDE-TODO-01-H — předání instalačního balíčku do Qt (implemented).**
  Rozsah: opravit stávající nativní instalátor, nikoli přidat novou integrační
  cestu. Reuse/adapt: existující same-origin nativní akce a JSON předávání
  používané ostatními desktopovými dialogy; žádný nový framework.
  Příčina reprodukována skutečným Qt WebEngine: objekt vrací prázdný řetězec,
  JSON.stringify vrací použitelný JSON. Oprava přenáší JSON a zachovává
  jednorázové smazání citlivého payloadu z window.
  Recovery se nemění (ADR 0060): vytvoření připojení a instalace nejsou
  transakce; při přerušení připojení zůstane a lze je odvolat, balíček je
  dočasný. Projektový Git/index/journal se tímto krokem nemění.
  Dokončení: regresní Qt test, finální sada a skutečné potvrzení/instalace
  z restartovaného desktopu do uživatelského VSCodia. Poslední krok zatím
  neověřený; vytvoření připojení není důkaz nainstalovaného rozšíření.
  Ověření: skutečný Qt regresní test
  `M0_DESKTOP_TEST=1 QT_QPA_PLATFORM=offscreen QTWEBENGINE_CHROMIUM_FLAGS=--no-sandbox python3 -m unittest tests.test_desktop.DesktopTests.test_real_webengine_transfers_ide_install_payload_once -v`
  prošel (1 test); ověřuje obsah přeneseného JSON i spotřebování payloadu.
  Úplná sada `python3 -m unittest discover -s tests -v` byla spuštěna,
  výsledek zatím není k dispozici (log `/tmp/workspace-ide-fix-tests.log`).
