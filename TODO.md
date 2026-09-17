<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — M1-07: LXC autostart a cílová restartová akceptace

Milník M1; Gate M1 zůstává otevřený. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## M1-07 — LXC webové nasazení a dlaždice na routeru

- Stav: [ ] [in progress]; cílová úroveň PoC validated na cílovém Turris Omnia.
- Původ: otevřená restartová akceptace M1-07; uživatel 2026-09-17 potvrdil zachování instalace a dat po restartu, ale kontejner `workspace-m0` se automaticky nespustil.
- Skutečná větev: `feature/m1-07-lxc-autostart`, založená z `develop` (`a93dd75`, PR #23 začleněn). Jediný PR do `develop`; není vytvořen.
- Výstup: bezpečné, idempotentní nastavení autostartu jen zvoleného kontejneru přes Turris `/etc/config/lxc-auto`, rollback instalace/odebrání a doložený restart routeru bez ručního startu.
- Mimo rozsah: změna dat či rootfs kontejneru, automatický reboot routeru bez explicitního pokynu, obecná správa cizích LXC a federovaná synchronizace M5.
- Akceptace: ostatní autostart sekce zůstanou zachované; kolize vlastněné sekce se odmítne; opakovaná instalace/odebrání a rollback jsou bezpečné; po cílovém rebootu běží kontejner i `federated-workspace.service`, dlaždice vede na aktuální IP a funguje přihlášení, katalog a náhled.

- [x] [completed] **M1-07-A — Lokální implementace autostartu (implemented, 2026-09-17).** Routerová instalace spravuje výhradně pojmenovanou UCI sekci `lxc-auto.federated_workspace`, zachovává ostatní kontejnery, odmítá cizí kolizi a zahrnuje stav do rollback journalu.
- [x] [completed] **M1-07-B — Cílené regresní testy (PoC validated lokálně, 2026-09-17).** `python3 -m unittest tests.test_router_tile tests.test_deploy_omnia -v`: 15 testů OK. Pokryto chybějící/existující/cizí UCI nastavení, install/remove, rollback a stávající deploy scénáře.
- [ ] [in progress] **M1-07-C — Dokumentace, plná regrese a cílové nasazení.** Aktualizovat runbook, spustit celou sadu a připravit přesný instalační/ověřovací krok. Změnu routeru a reboot provést pouze s explicitním oprávněním uživatele.

Průběžné ověření M1-07-C: `python3 -m unittest discover -s tests -v` mimo socketový sandbox — 216 testů OK, 22 podmíněných skipů. Runbook a ADR odkaz jsou aktualizované; zbývá skutečná instalace a restartová akceptace na routeru.

### Recovery hranice

- Před změnou se do existujícího routerového rollback journalu uloží, zda naše přesná UCI sekce existovala. Journal neobsahuje ani nepřepisuje cizí sekce.
- Instalace nejprve zapíše vlastní soubory a UCI autostart, poté aktivuje dlaždici; při chybě obnoví soubory, služby i předchozí stav autostartu.
- Odebrání smaže pouze vlastní přesně ověřenou sekci. Částečná nebo cizí sekce stejného jména se odmítne bez přepsání.
- Reboot je vnější destruktivní/provozní hranice a není automatickou součástí lokálních testů ani deploye.
