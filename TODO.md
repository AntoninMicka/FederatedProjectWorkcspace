<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — M1-07-C restartová akceptace LXC autostartu

## Vymezení dávky

- **Feature:** `M1-07-C — Cílová restartová akceptace LXC autostartu`.
- **Původ:** odložená fyzická akceptace M1-07 po PR #24 (`3c09090`) a
  M1-LXC-DNS-TLS-01 po PR #58 (`916e5ec`); uživatel ji znovu aktivoval
  23. 10. 2026.
- **Milník:** M1; dokončení je poslední známou podmínkou jeho gate.
- **Cílová úroveň:** PoC validated na Turris Omnia.
- **Větev:** `feature/m1-07-c-restart-acceptance`, založená z `develop`
  `637bf90` po začlenění PR #82; cíl jednoho PR je `develop`.
- **Výstup:** viditelný návod po application-only aktualizaci, ověřená vlastní
  UCI/procd konfigurace a doložený skutečný restart se spuštěným LXC, službou,
  aktuální dlaždicí, přihlášením, projektem a TLS identitami.
- **Mimo rozsah:** změny ostatních UCI sekcí/kontejnerů, automatický restart,
  skryté změny hostitele a externí export `F-M5-EXTERNAL-EXPORT-01`, který
  uživatel výslovně odložil.

## Crash boundaries a recovery

Platí existující kontrakty M1-07 a ADR 0020. `router_tile.py install` před
změnou uloží soubory, enabled/active stav i vlastní autostart sekci do
durable journalu; chyba provede rollback a přerušený běh se obnovuje přes
`router_tile.py recover`. Application-only deploy nemění UCI ani procd.
Restart následuje až po čistém journalu a read-only kontrole přesného stavu.
LXC služba používá vlastní deploy lock/snapshot; případná obnova je oddělená
od routerové integrace a nesmí zahodit projekty, identitu ani credentials.

## Úkoly dávky

- [x] [completed] **M1-07-C-A — Aktivace a administrativní předání
  (implemented, 2026-10-23).** Ověřen čistý `develop` shodný s
  `origin/develop`, začlenění PR #82 jako `637bf90` a vytvořena samostatná
  feature větev. Externí export zůstává v BACKLOG jako vědomě odložená,
  aktuálně nepotřebná feature.
- [x] [completed] **M1-07-C-B — Viditelný update-only návod
  (implemented).** Úspěšná application-only aktualizace nyní výslovně uvádí,
  že autostart nezměnila, a vypíše přesný UCI check i oddělený staging,
  `plan` a `install` postup. Hostitel se bez vědomé akce správce nemění.
- [ ] [in progress] **M1-07-C-C — Předrestartová kontrola a instalace
  (cílová úroveň: PoC validated).** Na skutečné Omnii ověřit či přes
  zkontrolovaný plán idempotentně doplnit jen
  `lxc-auto.federated_workspace`, čistý rollback journal, routerovou službu,
  LXC službu a vydaný certifikát pro aktuální IP a DNS autoritu.
- [ ] [planned] **M1-07-C-D — Skutečný restart a uživatelská akceptace
  (cílová úroveň: PoC validated).** Po výslovně potvrzeném termínu restartovat
  router a doložit automatický běh `workspace-m0` a
  `federated-workspace.service`, aktuální dlaždici, přihlášení a náhled
  existujícího projektu; ověřit přímou IP i DNS URL a důvěru klienta.
- [ ] [planned] **M1-07-C-E — Regrese, Gate M1 a předání
  (cílová úroveň: PoC validated).** Spustit cílené a úplné testy po poslední
  změně kódu, zapsat skutečné zařízení/datum/výsledky a omezení, vyhodnotit
  Gate M1 a provést závěrečné předání jediné feature dávky.

## Průběžné ověření

- 23. 10. 2026: cílené testy deploye a routerové integrace **18 OK**;
  `py_compile` a `git diff --check` prošly.
- 23. 10. 2026: úplná sada v prostředí s povolenými lokálními sockety
  **751 OK, 28 podmíněně přeskočeno**. První omezený běh selhal jen na 66
  zakázaných HTTP/HTTPS/Unix socketových operacích a není vydáván za výsledek
  aplikace.
- Read-only SSH pokus na uložený cíl `root@192.168.100.1` skončil před
  spuštěním vzdálených příkazů na chybějící neinteraktivní autentizaci
  (`Permission denied`); stav routeru se nezměnil. Předrestartová kontrola
  proto čeká na uživatelsky zadané SSH heslo v jeho terminálu.

## Akceptační podmínky

1. Update-only úspěch už nemůže budit dojem, že nastavil autostart; přesný
   bezpečný postup je automaticky viditelný a otestovaný.
2. Před restartem existuje přesně vlastněná UCI sekce se jménem
   `workspace-m0` a timeoutem `60`; cizí konfigurace zůstává nedotčená.
3. Po skutečném restartu se LXC a aplikace spustí automaticky a dlaždice vede
   na aktuální adresu bez obcházení přihlášení.
4. Přihlášení a náhled existujícího projektu fungují; certifikát projde
   `openssl -checkip` i `-checkhost` a klient důvěřuje IP i DNS přístupu.
5. Výsledky jsou zaznamenané jako fyzická PoC akceptace; bez nich zůstávají
   M1-07-C i Gate M1 otevřené.
