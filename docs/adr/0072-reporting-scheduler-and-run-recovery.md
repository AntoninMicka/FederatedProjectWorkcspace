<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0072 — Reporting scheduler a autorita běhu

Datum: 2026-11-05. Stav: lokální implementace MON-04 k review.

## Zadání a rozhodnutí

Zdrojový základ `411e853081300a1cc1cfedf1ba79aade1c4fde24` je ověřený
`origin/develop` po PR #138. Pracovní strom byl čistý; nová větev je
`feature/mon-04-reporting-scheduler`. Kanonický projekt
`c898b941-8eb0-4406-8dad-6e2b96c06d59` při načtení potvrdil MON-03 jako
user_confirmed a MON-04 jako první zahajitelný úkol bez blockers.
Packet `a968e3f76bd02e44e34a6de24bd228dcbe807c34c31db09e3df33db94de0e750`,
queue revision `215`, projektový HEAD `3fa6e7e66093e2348c9e65284bd7afb32c5ddc7b`,
exportní revize `d34e34d03bfdfd61fe643f40db98b2448b1f4860767592f5fc406d223d57ee5d`;
`current=true`, `stale=false`, repository mapping i baseline odpovídaly.
Všech devět podkladů bylo ověřeno podle velikosti a SHA-256. Rozsah a akceptaci
určuje předaný BACKLOG source artefakt
`3928de31-234c-5754-a6a6-b31f587d2a45`, řádek 349; ne archivovaný místní plán.
MON-05 a ostatní položky nejsou součástí této dávky.

ReportingScheduler je lokální API vlastníka uzlu pro konečný tick/catch-up,
rezervaci, převzetí práce, předání úplného kandidáta k review a idempotentní
vydání. Není to instalovaný daemon ani automatické schvalování reportů.
Používá [kontrakt MON-00](../reporting-contract-v1.md) a
[původní writer](0068-manual-reporting-transactions.md). Výpočet obsahu
reportu, diferenční syntéza a periodické LLM workflow patří navazujícím dávkám.
Scheduler je funkční také bez sítě a LLM.

## Kalendář, rezervace a workeři

- Weekly/monthly/quarterly/annual hranice se nejprve vypočtou v místním
  kalendáři, pak převedou do UTC. Kontrolují se offset, timezone, půlnoc,
  pondělí a kalendářní revize. Custom periodu lze zadat explicitním intentem,
  nikoli automaticky odhadnout její délku. Časové hranice vyžadují kanonický
  ISO zápis, aby jiný zápis nulových
  mikrosekund nevytvořil další rezervaci stejného intervalu.
  Neexistující/nesprávná hranice se
  odmítne, neposune se potichu na jiný čas.
- Catch-up vytváří jen uzavřené periody. Limit je explicitní, vrací next_start
  a more; nedokončené starší periody blokují claim novější periody stejného
  task entity/kind. Výjimkou je failed/cancelled stará revize, jejíž přesný
  interval už dokončila náhradní revize; unknown se takto neignoruje.
  Návrat more neznamená dokončení catch-up.
- Run key a request digest respektují kontrakt. Unikátní základní rezervace
  používá project + task entity/revision + period + identity/hash pravidel;
  čerstvější commit obsahující stejnou revizi ji neobchází. Jiný cutoff nebo
  input_head pod existující rezervací není nové základní vydání. Opakovaný
  tick vrátí první zmrazený intent; změnu delivery_required nelze tiše skrýt.
- Run JSON zachovává pole fpw-reporting-run-v1. Delivery requirement, node/owner
  vazba a lease/fencing jsou lokální databázové údaje. Nejsou dalšími poli
  projektového ReportingTasku ani exportovanou node identitou.
- SQLite BEGIN IMMEDIATE serializuje claim. Jeden aktivní worker dostane
  token s omezenou platností; cizí nebo starý token nesmí předat výsledek.
  Expirace collecting znamená unknown, nikoli automatické převzetí účinku
  jiným workerem. Explicitní reconciliation no-effect je lidské rozhodnutí.
- Failed/cancelled před vydáním dovoluje potvrzený retry stejného intentu a
  nový attempt. Unknown ani issuing/completed nelze takto přeznačit. Nová
  task revize má novou rezervaci; starý běh zůstává připnutý a může dokončit
  původní revizi po aktuálním ověření oprávnění a novém lidském review.

## Kandidát, vydání a externí účinek

Worker používá existující collector/backendové služby a jejich samostatné
journals; žádný přímý externí účinek nezískává právo ignorovat jejich unknown.
Tento lokální řez má úplný kandidát v SQLite BLOB. Draft se sestavuje v paměti,
nikoli jako částečně potvrzený projektový soubor: collecting přejde atomicky
na review, bez dalšího persistentního draft stavu. Přidání restartovatelného
vícefázového sběru musí uchovat jeho reference/účinky v příslušných službách.

Stage zkontroluje identitu intentu, aktuální policy a celý kandidát stejným
Reporting builderem a sémantickým validátorem jako při vydání. Read-only
validace nevytváří Workspace intent ani trvalé lidské schválení. Preview po
restartu vrátí přesné zmrazené request/Markdown bajty a approval digest.
Approve vyžaduje confirm a shodu digestu; identitu a čas review určí aplikace.
Publikace znovu kontroluje digest kandidáta a aktuální oprávnění. Stale HEAD
se automaticky nerebasuje. CLI/remote endpoint pro obcházení review nevzniká.

Publish operation ID je stabilně shodné s run ID. Tím se zachovává i dosavadní
manual generation.run_id bez druhého writeru. Základní ReportSnapshot i
Markdown vzniknou jedním původním Workspace commitem. Další ruční vydání
stejné periody vyžaduje existující correction cestu, nikoli scheduler retry.

Last issued snapshot se zapíše po ověřeném receipt; last successful cutoff
zůstává null/předchozí do completed. Je-li delivery_required, run zůstane
issued. Begin delivery nejprve uloží přesný intent hash, delivery ID a stabilní
idempotency key a přejde do unknown před externím voláním. Žádný provider se
zde automaticky nevolá. Místní aplikace/člověk musí skutečný provider receipt
ověřit a při reconciliation předat shodné delivery ID, key, intent a
node-local receipt reference. Samotný modelový text nebo timeout není receipt.
Až toto potvrzení atomicky nastaví completed a cutoff. Opaque reference není
důkaz vzdáleného účinku bez ověření volající aplikací; reálný delivery adaptér
ani jeho vzdálené dohledávání tento PoC nedodává.

## Crash boundaries a recovery

Platí [ADR 0003](0003-coordinated-operation.md). Mezi run journalem a
Workspace journalem není distribuovaná transakce:

| Hranice | Autorita a obnova |
| --- | --- |
| Před run intentem | Nic není rezervováno; chybné/stale vstupy jsou odmítnuté. |
| Run prepared / collecting | Run journal drží neměnný intent a attempts. Po expiraci nejistého collecting se účinek nepouští znovu. |
| Review / approved | SQLite drží úplný kandidát a digest, approval je oddělené. Restart vrátí stejné preview; cizí změna kandidáta se odmítne. |
| Issuing před Workspace | Run uloží publish_operation_id. Resume používá přesně stejné UUID a request, nikoli nový kandidát. |
| Workspace prepared / files-applied / před CAS | Obnova dle ADR 0003; dokončí původní záznam a chrání cizí změny. |
| Po CAS, před run receipt | Workspace receipt je autorita už vydaného commitu. Recover + stejné apply obnoví index/receipt bez druhého vydání; původní snapshot se přesně připne. |
| Run issued/completed | State, receipt, last issued pointer a případný cutoff se potvrzují jedinou run DB transakcí. Ztracená odpověď vrací původní výsledek. |
| Delivery intent / neznámý účinek | Journal zůstává unknown; není slepý resend ani nové vydání. Ověřený receipt propojí původní identitu a completed/cutoff. |
| Ztracený projektový index | Původní engine jej obnoví z validovaného HEAD. Run journal se z indexu nevytváří. |
| Ztracený/prázdný run journal | Existující adresář s chybějícím journalem ani prázdné schéma se automaticky neinicializují. Je nutná reconciliation/obnova autority, nikoli nový pokus téhož tasku. |

Journal používá vlastní nový adresář mimo všechny Git repozitáře, owned 0700,
databázi 0600 bez symlink/hardlink přesměrování, vazbu na node/owner a známou
verzi schématu. FULL SQLite commity a fsync adresářů navazují na původní
mechanismy. Neuklízet otevřené/unknown runy, rezervace ani receipty. Automatická
retence, migrace, multi-node distributed lease a fyzický power-loss test nejsou
součástí tohoto řezu; procesní crash test není jejich náhradou.

## Reuse a důkazy

Reuse Reporting/Workspace.transact, Journal lock/recovery/receipts, schémata
Period/ReportSnapshot a SourceCollector.resolve. Adapt node-local SQLite
vzorů RoleWorkflows/PublicSourceRuns; vznik samostatné run autority je požadavek
ADR 0063, nikoli druhý projektový writer. Existující AutonomyService řeší jiné
akce a oprávnění a nenese rezervaci reportové periody ani vazbu na cutoff;
nepřebíráme jeho stavový automat jako reportingový journal. Bez nové závislosti,
provideru či převzatého externího kódu. Veřejný i dostupný soukromý katalog
byly přečteny; soukromé detaily se nepřenášely.

Použití a skutečné výsledky ověření: [scheduler](../reporting-scheduler.md).
Autoritativní akceptace MON-04 a doručení PR jsou oddělené lidské kroky.
