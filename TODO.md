<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M5-PERSONAL-SYNC-01: osobní federace dvou vlastních uzlů

Původ: roadmapa M5, ADR 0021, ADR 0037 a uživatelem schválené odlehčení plné
federace pro individuální použití. Cílová úroveň: **PoC validated**. Větev:
`feature/f-m5-personal-sync-01`, základ `develop` na commitu `192e79c`, cíl PR:
`develop`.

Dávka propojí dva uzly spravované jedním člověkem přes existující lokální účty
a roli `node-admin`. Po ručním schválení peeru, přesného projektu a směru bude
jeden uzel primární zapisující a druhý automatická read-only replika. Nezavádí
centrální registr, MFA, sdílené uživatele, role nad uzlem, obecný policy engine,
multi-master ani automatické řešení divergence a sama neuzavírá Gate M5.

## Úkoly dávky

- [x] [completed] **F-M5-PERSONAL-SYNC-01-A — inventura, reuse a kontrakt
  operace (cílová úroveň: designed).** Prověřit skutečnou implementaci peer
  trust, oboustranného mapování účtů, portable ACL, bundle transferu, Git sync,
  UI federace a jejich testů. Porovnat `REUSE_CATALOG.md` a případnou lokální
  soukromou inventuru; pro reuse/adapt/rewrite/reject zaznamenat důvod bez
  přenosu soukromých detailů. Před zápisem popsat autoritu desired state,
  grantů a stavů synchronizace, serializaci, journal/CAS, crash boundaries a
  recovery mezi registry, Git objekty/refy a obnovitelným projektovým indexem.
  ADR 0038 potvrzuje reuse existujícího trust/mapping/bundle/outbox základu,
  odmítá SSH/askpass pro automatiku i falešné použití neúplného rights manifestu
  a definuje podepsaný HTTPS protokol, autority, pořadí locků, CAS a roll-forward
  recovery. Soukromá inventura neposkytla přímo převzatelnou komponentu.
  Cílená sada trust/mapping/transfer/desktop a compliance testů prošla mimo
  socketově omezený sandbox: **28 testů úspěšně**; první sandboxový běh měl tři
  očekávané `PermissionError` pouze při vytvoření loopback HTTP serveru.
- [ ] [planned] **F-M5-PERSONAL-SYNC-01-B — úzký replikační grant a durable
  desired state (cílová úroveň: implemented).** Nad schváleným peerem a
  aktivním oboustranným mapováním vydat podepsaný grant vázaný na oba uzly,
  project UUID, ref, směr a role primary/read-only replica. Zapnutí, zastavení,
  revokace a retry musí být auditovatelné a idempotentní; neznámý nebo stale
  stav nic nepovolí.
- [ ] [planned] **F-M5-PERSONAL-SYNC-01-C — bezpečný přenos a automatický
  fast-forward (cílová úroveň: implemented).** Rozšířit současný `public-only`
  přenos pouze v rozsahu přesného grantu. Odesílající i přijímající uzel ověří
  celý dosažitelný Git graf proti aktivnímu project/ref grantu a dovoleným
  privacy třídám; případný portable ACL smí výsledek pouze zúžit. `local-only`,
  nepokrytá historie, změněný HEAD, neplatný kandidát a revokace se odmítnou.
  Po pádu či ztrátě odpovědi recovery bezpečně určí stav bez duplicitního
  účinku.
- [ ] [planned] **F-M5-PERSONAL-SYNC-01-D — sdílené webové/desktopové UI
  synchronizace (cílová úroveň: implemented).** Ve správě federace nabídnout
  výběr schváleného peeru a projektu, potvrzení primary/replica směru, zapnutí
  a zastavení. Zobrazit poslední úspěch, čekání/offline, odmítnutí, revokaci a
  konflikt; read-only replika nesmí v editoru předstírat možnost zápisu.
- [ ] [planned] **F-M5-PERSONAL-SYNC-01-E — automatické a fyzické ověření
  (cílová úroveň: PoC validated).** Pokrýt první přenos, následný fast-forward,
  restart na persistentních hranicích, offline návrat, idempotentní retry,
  zastavení/revokaci, změněný HEAD, neúplnou historii, `local-only`, neplatný
  kandidát a divergenci bez přepsání cíle. Nakonec ověřit desktopový a
  LXC/serverový uzel se skutečným projektem a zaznamenat zbývající omezení.

## Akceptační podmínky

- synchronizace nezačne pouhou dosažitelností nebo schválením peeru, ale až po
  potvrzení přesného projektu, refu, směru a rolí uzlů;
- automatika provádí pouze validovaný fast-forward primárního refu do read-only
  repliky a při divergenci nebo nejasném výsledku se bezpečně zastaví;
- revokace či zastavení zabrání novému přenosu a žádný retry nevytvoří druhou
  repliku ani neopakuje již potvrzený účinek;
- přenos autorizuje celý dosažitelný Git graf a nikdy nepřenese `local-only`;
- UI pravdivě zobrazuje stav a vynucuje read-only repliku na webu i desktopu;
- cílené i úplné automatické testy projdou a fyzický desktop ↔ LXC/server
  scénář potvrdí první i následnou synchronizaci a obnovu po offline stavu.
