<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-PROJECT-REPAIR-02 / diagnostika a bezpečné opravy projektu

Aktivní implementační dávka realizuje přijatý kontrakt
[ADR 0035](docs/adr/0035-project-check-and-repair.md). Skutečná větev je
`feature/ux-project-repair-02`, základ je `develop` na merge commitu `618b1f7`
(PR #75) a cílem jediného PR je `develop`.

První řez přidá desktopovou read-only kontrolu registrovaného projektu,
stabilní kódy zjištění a sdílenou webovou stránku **Zkontrolovat projekt…**.
Mutující část smí po odděleném náhledu a potvrzení pouze atomicky přestavět
odvozený index nebo pokračovat v přesně identifikovaném journalovém intentu.
Chybějící kořen dál používá stávající opravu umístění. Reset Gitu, změny práv,
heuristická oprava obsahu, přepis identity a mazání dat jsou mimo rozsah.

- [x] [completed] **UX-PROJECT-REPAIR-02-A — skutečně read-only diagnostický
  backend (cílová úroveň: implemented).** Bez inicializace `Workspace`,
  `Journal` nebo `Index` zkontrolovat registraci, root/state, Git, committed i
  pracovní `project.json`, snapshot, journal a index. Vrátit bezpečný report se
  stabilními kódy a `check_token`; souběžnou změnu označit `retry`. Implementace
  v `spikes/project_repair.py` používá read-only SQLite URI, zakazuje volitelné
  Git locky a před/po kontrole porovnává otisk sledovaného stavu. Rozlišuje
  zdravý, opravitelný, ruční a nestabilní stav bez zveřejnění lokálních cest.
- [x] [completed] **UX-PROJECT-REPAIR-02-B — potvrzené opravy a receipt
  (cílová úroveň: implemented).** Revalidovat preview a token pod writer
  lockem, podporovat pouze `rebuild-index` a `resume-operation`, bezpečný retry
  po lost response a následnou úplnou kontrolu. Neznámý stav zůstane `manual`.
  `ProjectRepairActions` váže náhled na projekt, akci, HEAD, journalový intent a
  `check_token`; potvrzení znovu kontroluje celý stav pod existujícím
  neblokujícím writer lockem. Rebuild používá `Index.rebuild`, recovery původní
  `Workspace`/`Journal` cestu a receipt zůstává v existující tabulce operací.
  Standalone vyčištění intentu a receipt sdílejí jednu SQLite transakci;
  dokončený Workspace intent nebo index bez wrapper receipt lze bezpečně
  rekoncilovat po ztracené odpovědi a vždy následuje nová úplná diagnostika.
- [x] [completed] **UX-PROJECT-REPAIR-02-C — desktopové API a sdílené webové UI
  (cílová úroveň: implemented).** Přidat položku do menu nedostupného projektu,
  vrstvený report, přesný náhled účinku a samostatné potvrzení. Endpointy
  zůstanou pouze v autentizovaném desktopovém handleru; síťový katalog
  nezveřejní cesty ani diagnostická data. Sdílená stránka nyní skládá bezpečný
  report přes DOM `textContent`, nabízí právě jednu backendem povolenou opravu
  a vyžaduje samostatné potvrzení jejího přesného plánu. Autentizovaný desktop
  poskytuje oddělené `check`, `preview`, `confirm` a `receipt` routy; síťový
  handler je explicitně vrací jako 404, službu neinicializuje a katalog zůstává
  beze změny.
- [ ] [planned] **UX-PROJECT-REPAIR-02-D — regresní a fyzická akceptace
  (cílová úroveň: PoC validated).** Ověřit zdravý i poškozený projekt, nulové
  mutace při kontrole, stale token, lock, lost response/retry, recovery
  checkpointy, API/UI, celou sadu a skutečný Qt WebEngine průchod.

## Persistentní a crash hranice

- diagnostika otevírá existující filesystem/SQLite/Git stav pouze pro čtení a
  nesmí vytvořit inode, tabulku, zámek ani Git objekt;
- projektový Git commit je autorita obsahu, projektový journal autorita
  nedokončeného intentu a `index.sqlite` pouze obnovitelná projekce;
- rebuild indexu publikuje celou projekci atomicky; pád ponechá starou nebo
  novou celou projekci a identický retry je bezpečný;
- recovery journalu pouze vyvolá stávající `recover` nad původním operation ID
  nebo digestem přesných pending řádků; obsah intentu nemění;
- změna kterékoli precondition mezi check/preview/confirm zneplatní akci.

## Podmínky dokončení

- všechny vrstvy a stabilní kódy ADR 0035 mají deterministické testy;
- read-only kontrola prokazatelně nemění inode, mtime, SQLite bajty ani Git
  objekty, a to i u chybějících nebo poškozených částí;
- opravy vyžadují samostatné oprávnění, preview a explicitní potvrzení a mají
  bezpečný receipt/retry bez záměny operation ID;
- UI ukáže konkrétní příčinu a právě povolenou další akci, ale neuniknou z něj
  lokální cesty do síťového režimu;
- cílené testy, úplná sada, relevantní syntaxe a skutečný desktopový smoke
  projdou; omezení zůstanou výslovně zdokumentovaná.

## Průběžné ověření

- `python3 -m unittest tests.test_project_repair tests.test_spdx` — 9 testů
  prošlo; pokryty jsou stabilní otisk zdravého projektu, nulové změny inode,
  metadat, bajtů a Git objektů, varianty indexu a journalu, souběžná změna,
  writer lock i bezpečné chyby bez úniku cest;
- `python3 -m unittest tests.test_projects tests.test_storage
  tests.test_index_projection tests.test_project_repair` — 37 testů prošlo,
  2 Qt testy byly očekávaně přeskočeny;
- `python3 -m py_compile spikes/project_repair.py
  tests/test_project_repair.py` a `git diff --check` — prošlo.
- `python3 -m unittest tests.test_project_repair tests.test_journal
  tests.test_workspace tests.test_storage tests.test_index_projection
  tests.test_spdx` — 51 testů prošlo; zahrnují změněný/tamperovaný plán,
  restartově čitelný receipt, lost response pro rebuild, standalone journal i
  Workspace recovery a přesnou vazbu operation ID;
- `python3 -m unittest discover -s tests` — 680 testů prošlo, 27 bylo
  přeskočeno; výstup obsahoval existující `ResourceWarning` z mockovaných
  SQLite spojení, testovací CLI chyby a recovery logy, návratový kód byl 0.
- `python3 -m unittest tests.test_web_server tests.test_desktop
  tests.test_projects tests.test_project_repair tests.test_spdx` — 98 testů
  prošlo, 8 bylo přeskočeno; ověřena autentizace desktopových rout, oddělený
  check/preview/confirm/receipt kontrakt, bezpečný payload a síťové 404;
- po integraci API/UI `python3 -m unittest discover -s tests` — 683 testů
  prošlo, 27 bylo přeskočeno; stejné existující warningy a testovací logy,
  návratový kód 0;
- `python3 -c 'from spikes.desktop_ui import JS; print(JS)' | node --check`,
  relevantní `py_compile` a `git diff --check` — prošlo.

Úplná sada bude po integraci API/UI zopakována a skutečný Qt WebEngine průchod
náleží až závěrečné akceptaci úkolu `UX-PROJECT-REPAIR-02-D`.

## K předání do backlogu

Zatím žádné nové nezávislé požadavky.
