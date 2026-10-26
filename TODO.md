<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M5-SYNC-CONTROLS-01

Aktivní feature dávka: **Hromadná ruční a volitelná automatická synchronizace**

- Původ: uživatelský požadavek po fyzické akceptaci PR #101.
- Milník: M5 / federace.
- Cílová úroveň: **PoC validated**.
- Větev: `feature/f-m5-sync-controls-01` z `develop` `8c08be2`.
- Cíl PR: `develop`.
- Rozsah: jedno ruční spuštění všech oprávněných interních scope,
  node-local přepínač existujícího background scheduleru, souhrn výsledku,
  desktopové i webové UI a recovery.
- Mimo rozsah: automatický merge konfliktů, externí export, samostatný
  tray/daemon po ukončení desktopové aplikace a globální transakce napříč
  projekty.
- Reuse: adaptovat `ContentSyncControl`, `ContentSyncScheduler`,
  `ManualSyncTasks`, existující project×peer policy a node-local SQLite journal;
  nezavádět druhý scheduler ani druhou synchronizační autoritu.

## Crash hranice a recovery

- Nastavení automatiky je node-local mimo projektový Git a publikuje se
  transakčně v existujícím SQLite journalu. Pád před commitem zachová starou
  hodnotu, po commitu je autoritou nová revize.
- Hromadná akce není globální transakce. Každá dvojice projekt×peer použije
  stávající lock, durable journal, cancel a roll-forward; chyba jedné dvojice
  nevrací zpět již dokončené nebo rozpracované ostatní projekty.
- Retry smí oznámit `již běží` a nesmí vytvořit druhý worker pro stejný
  scope. Revokace, `external`, chybějící endpoint a nepovolená same-company
  matice zůstávají fail-closed.

## Úkoly dávky

- [x] [completed] **F-M5-SYNC-CONTROLS-01-A — nastavení a autorizovaný
  výběr scope (implemented).** Zavést revizně vázaný atomický přepínač s
  výchozí hodnotou zapnuto a jediný sdílený výpočet oprávněných scope pro
  automatiku i hromadnou ruční akci.
- [x] [completed] **F-M5-SYNC-CONTROLS-01-B — hromadná ruční akce
  (implemented).** Spustit každý oprávněný scope přes existující worker a
  vrátit souhrn spuštěno / již běží / přeskočeno / chyba.
- [x] [completed] **F-M5-SYNC-CONTROLS-01-C — desktop/web UI (implemented).** Ve
  Správě federace doplnit tlačítko „Synchronizovat vše“, přepínač automatiky,
  viditelný stav a bezpečné opakování.
- [ ] [in progress] **F-M5-SYNC-CONTROLS-01-D — regrese, dokumentace a fyzická
  akceptace (PoC validated).** Ověřit default/migraci, CAS konflikt, restart,
  disabled scheduler, filtrování scope, částečný neúspěch, dvojklik, desktop i
  HTTPS UI a reálný uzel.

## Aktuální ověření

- Cílená federační, desktopová a HTTPS sada prošla: **25 testů úspěšně,
  1 podmíněný WebEngine test přeskočen**. Pokryla default a migraci bez
  řádku nastavení, revizní CAS, restart, vypnutý scheduler, sdílený policy
  výběr, částečný hromadný výsledek, dvojí start, autorizaci endpointů,
  pinned HTTPS, oba směry, konflikt, cancel a chatovou regresi.
- Samostatně prošel skutečný Qt/WebEngine smoke a ověřil renderované tlačítko
  **Synchronizovat vše**, checkbox automatiky i původní RW fork chatu.
- Změněné Python moduly prošly `py_compile`, generovaný administrační
  JavaScript konstrukcí `new Function` v Node.js a průběžný diff
  `git diff --check`.
- Zbývá fyzická akceptace na reálném desktop–server nasazení a poté finální
  úplná testovací sada / CI před předáním PR.
