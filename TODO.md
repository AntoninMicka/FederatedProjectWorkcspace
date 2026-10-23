<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M5-SHARING-SYNC-01: obousměrná synchronizace interních projektů

Původ: uživatelský požadavek 23. 10. 2026 pokračovat po katalogu přenosem
projektového obsahu a zachovat dříve navržené nativní Git přenosy. Navazuje na
ADR 0038, ADR 0040, ADR 0041 a fyzicky přijatý `F-M5-PROJECT-CATALOG-01`.
Cílová úroveň: **implemented → PoC validated**. Větev:
`feature/f-m5-sharing-sync-01`, základ `develop` na merge commitu `ae1b25e`
(PR #80), cíl PR: `develop`.

Dávka zavede automatický obousměrný přenos celé povolené Git historie pro
`same-team` a jen projektů/větví vybraných maticí pro `same-company`.
`external` zůstává mimo rozsah. Nativní `git bundle`, Git refs a ancestry
kontroly zůstávají jediným datovým transportem; aplikace neskládá vlastní
historii ani automatický merge.

## Úkoly dávky

- [x] [completed] **F-M5-SHARING-SYNC-01-A — kontrakt, reuse a recovery
  (cílová úroveň: designed).** ADR 0042 vymezuje branch scope, podepsané
  inventury, native bundle, fast-forward/divergence pravidla, persistentní
  autority a crash recovery. Řešení reuseuje `git_transfer`, podpis/TLS vzor
  `project_replication`, katalog, matici, Workspace/Journal/Index a
  `ProjectCreation`; nepřidává druhý Git writer ani skrytý merge.
- [x] [completed] **F-M5-SHARING-SYNC-01-B — podepsaná obousměrná výměna
  (cílová úroveň: implemented).** Jeden iniciátor pro jeden projekt vymění
  inventury a podle potřeby bounded native Git bundle v obou směrech.
  `same-team` zahrnuje všechny lokální projekty a větve, `same-company` pouze
  exportní scope místní matice; `external`, `unspecified` a nedůvěryhodný peer
  selžou closed. Nezměněné heady se znovu jako bundle neposílají.
- [x] [completed] **F-M5-SHARING-SYNC-01-C — CAS aplikace, divergence a
  recovery (cílová úroveň: implemented).** Chybějící projekt/větev se bezpečně
  založí a existující ref pouze fast-forwarduje. Každý divergentní head se
  zachová pod operation-scoped incoming refem. Durable outbound/inbound
  request/response journal, inode-bound staging, project writer lock a
  roll-forward obnova worktree/indexu zajišťují idempotentní retry.
- [x] [completed] **F-M5-SHARING-SYNC-01-D — scheduler a sdílené UI
  (cílová úroveň: implemented).** Interní peery se synchronizují automaticky
  po 60 sekundách, desktop může sync vyžádat ručně a dynamická serverová strana
  odpovídá při jeho spojení. Sdílené UI ukazuje idle/offline/rejected/conflict/
  error a divergenci výslovně nevydává za merge.
- [ ] [in progress] **F-M5-SHARING-SYNC-01-E — automatické a fyzické ověření
  (cílová úroveň: PoC validated).** Cílených **8 testů úspěšně** ověřilo první
  import, fast-forward oběma směry, vedlejší větev, `same-company` filtr,
  pinned TLS, retry po pádu za CAS, `local-only` odmítnutí, external fail-closed
  a zachování obou divergentních headů. Webová/desktopová regresní sada:
  **71 testů úspěšně, 6 přeskočeno**. Úplná sada: **736 testů úspěšně, 28
  přeskočeno**. `py_compile`, oba generované JavaScripty přes `node --check` a
  `git diff --check` prošly. Zbývá fyzicky potvrdit desktop ↔ LXC oba směry,
  offline návrat a viditelnou divergenci bez automatického merge.

## Akceptační podmínky

- přenos používá validovaný nativní Git objektový graf a zachová commit ID;
- žádný ref se nepřepíše non-fast-forward a divergence se automaticky
  neslučuje ani neztrácí;
- `same-team` synchronizuje všechny projekty/větve, `same-company` jen scope
  matice a `external` nikdy tento protokol nespustí;
- `local-only`, neplatná historie, změněná policy, identita nebo trust se
  odmítnou před publikací;
- pád/retry nezpůsobí dvojí účinek a index nikdy nevydá starý HEAD za aktuální;
- cílené i úplné testy projdou a fyzický desktop ↔ LXC scénář potvrdí oba
  směry, offline návrat a viditelnou divergenci bez automatického merge.
