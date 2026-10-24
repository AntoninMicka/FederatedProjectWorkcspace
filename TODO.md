<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M4-DYNAMIC-WORKFLOW-01 — katalog činností a dynamický plán

Původ: uživatelem schválený směr po ověření řízené automatiky hledání,
převzatý se stejným ID z [BACKLOG](BACKLOG.md). Milník M4, cílová úroveň
**designed → implemented**. Větev `feature/f-m4-dynamic-workflow-01` vznikla z
`develop` `023eae1`; cílem je jediný PR do `develop`.

Předchozí dávka `F-M3-PUBLIC-SOURCE-READER-02` byla doručena PR #87 jako merge
commit `023eae1`; její evidence je ve
[WORK_LOG](WORK_LOG.md#f-m3-public-source-reader-02--strukturovaná-čitelná-projekce--2026-10-24).

## Rozsah a hranice

Rozšířit uzavřený action registry o typované vstupy, výstupy, předpoklady a
povolené návaznosti. Aktivovaný workflow smí po dokončeném kroku navrhnout,
deterministicky validovat a append-only přidat či zopakovat činnost nebo plán
předčasně ukončit v rámci schváleného celkového limitu.

Limit je nejzazší hranice, nikoli povinný počet kroků. Rozpracovaný bounded
krok se dosažením celkového limitu nepřeruší. Zvýšení limitu vyžaduje přesnou
uživatelem potvrzenou novou revizi plánu; samotný countdown, dokončení kroku
ani schválení jednoho účinku limit nezvýší. Model smí pouze navrhovat a nikdy
nerozšiřuje permissions, privacy, execution boundary ani limity. Doménové
journaly zůstávají autoritou vlastních účinků; tato dávka nevytváří druhého
doménového writera ani automatickou publikaci projektových artefaktů.

Konkrétní výzkumné fáze a profily patří do navazující samostatné dávky
`F-M4-RESEARCH-WORKFLOW-01`; tato dávka dodává obecný katalog a revizní
mechanismus, nikoli search-only pipeline.

## Úkoly

- [x] [completed] **F-M4-DYNAMIC-WORKFLOW-01-A — současný kontrakt, reuse a
  crash boundaries (cílová úroveň: designed).** Prověřit `ActionRegistry`,
  `AutonomyQueue`, plan/step revisions, doménové adaptéry a sdílené UI.
  Vymezit typovaný katalog návazností, append/repeat/early-finish kontrakt,
  vlastnictví persistentních stavů a recovery před/po revizi bez druhého
  writeru. Výsledek: [ADR 0047](docs/adr/0047-dynamic-workflow-plan-revisions.md)
  odděluje statickou policy, kumulativní limit a append-only revize, určuje
  autority obou journalů a recovery včetně souběhu, pádu před/po revizi a
  `unknown` doménového účinku. Reuse/reject je zaznamenán v
  [REUSE_CATALOG](REUSE_CATALOG.md).
- [x] [completed] **F-M4-DYNAMIC-WORKFLOW-01-B — typovaný katalog a validátor
  návazností (cílová úroveň: implemented).** Deklarovat bounded vstupy,
  výstupy, předpoklady a povolené následníky; odmítnout neznámou akci,
  nekompatibilní vazbu, chybějící výstup a pokus o rozšíření oprávnění,
  privacy nebo execution boundary. Výsledek: action descriptor v2 uzavírá
  typy vstupů/výstupů, preconditions, verzované successor hrany s typovanými
  bindingy a execution boundary. Registry kontroluje celý graf při načtení,
  plán přesný vstup a queue výstup handleru; `validate_transition` fail-closed
  ověřuje výstupy předchůdců i aktivovanou policy. Ověření: 18 cílených testů
  `tests.test_action_autonomy` a úplná sada 783 testů prošly, 28 testů bylo
  přeskočeno podle svých podmínek prostředí.
- [x] [completed] **F-M4-DYNAMIC-WORKFLOW-01-C — append-only revize plánu a
  limitu (cílová úroveň: implemented).** Po dokončeném kroku umožnit přesný
  návrh přidání, opakování nebo předčasného ukončení. Zvýšení kumulativního
  limitu musí být atomicky svázané s explicitně potvrzenou novou revizí;
  staré revize a dokončená historie zůstávají neměnné. Výsledek: obecný plán
  v3 váže typované akce, permissions a execution boundaries; journal v5
  odděluje immutable aplikované revize od durable návrhů. `append`, `repeat`
  a `finish` se aplikují pod `BEGIN IMMEDIATE`, stale souběh se odmítá a
  zvýšení kteréhokoli kumulativního limitu čeká na přesný confirmation digest
  v živém UI. Migrace v4 zachová existující plán jako revizi 1; rollback před
  commitem a replay po ztracené odpovědi nevytvoří druhou revizi ani krok.
  Ověření: 22 cílených testů `tests.test_action_autonomy` a úplná sada 787
  testů prošly, 28 testů bylo přeskočeno podle podmínek prostředí.
- [ ] [in progress] **F-M4-DYNAMIC-WORKFLOW-01-D — orchestrace, UI a recovery
  (cílová úroveň: implemented).** Zobrazit aktuální plán, důvod a dopad změny,
  zbývající limit a samostatné potvrzení revize. Restart před/po revizi,
  `unknown` doménový účinek a ztráta UI musí zůstat fail-closed bez
  automatického retry nebo implicitního zvýšení limitu.
- [ ] [planned] **F-M4-DYNAMIC-WORKFLOW-01-E — regrese a akceptace (cílová
  úroveň: implemented).** Ověřit append, repeat, early-finish, odmítnutou
  neplatnou návaznost, atomickou revizi limitu, souběh, restartové hranice,
  `unknown` bez retry a zachování autority doménových journalů. Dokončit
  úplnou sadu, statické kontroly, dokumentaci a realistický fyzický průchod.

## Akceptace

- Katalog a validátor deterministicky povolí jen typově a policy kompatibilní
  návaznosti; návrh modelu sám nemění plán ani oprávnění.
- Dokončená historie je append-only a přidání, opakování, early-finish i
  navýšení limitu mají přesnou revizi a auditovatelný důvod.
- Celkový limit je nejzazší hranice; běžící bounded krok se nepřeruší uprostřed
  a limit se bez samostatného potvrzení nové revize nezvýší.
- Recovery nevytváří druhý doménový účinek, `unknown` se automaticky neopakuje
  a projektový zápis stále vyžaduje vlastní potvrzenou publikační operaci.
- Cílené testy, úplná sada, statické kontroly, dokumentace a realistická
  fyzická akceptace projdou; omezení budou výslovně zaznamenána.
