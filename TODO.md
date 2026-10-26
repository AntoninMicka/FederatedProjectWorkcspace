<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M5-CHAT-HISTORY-01

Aktivní feature dávka: **Projektové chaty v obousměrné obsahové synchronizaci**

- Původ: uživatelská priorita po PR #100; fyzická akceptace byla 2026-10-26
  znovu otevřena, protože po Sync nebyl přenos ani jeho výsledek viditelný.
- Milník: M5 / federace.
- Cílová úroveň: **PoC validated**.
- Větev: `feature/f-m5-chat-history-01` z `develop` `3c0b675`.
- Cíl PR: `develop`.
- Rozsah: Git a projektová RW chatová vlákna v jedné obousměrné content-sync
  operaci, viditelný počet přenesených chatů a obnovení seznamu po Sync.
- Mimo rozsah: nezařazená vlákna, synchronizované mazání, runtime journal a
  automatický obsahový merge divergentních odpovědí.

## Úkoly dávky

- [x] [completed] **F-M5-CHAT-HISTORY-01-A — integrovaný content-sync v2
  (implemented).** Git i chat používají jednu podepsanou operaci a journal.
- [x] [completed] **F-M5-CHAT-HISTORY-01-B — obousměrný RW import
  (implemented).** Přesné mapování překládá vlastníka na místní účet.
- [x] [completed] **F-M5-CHAT-HISTORY-01-C — fork konfliktu a recovery
  (implemented).** Divergence konverguje na původní vlákno a RW fork.
- [x] [completed] **F-M5-CHAT-HISTORY-01-D — automatické regrese
  (PoC validated).** Prošly migrace, oba směry, privacy, crash retry, pinned
  HTTPS, balení a původní WebEngine průchod.
- [ ] [in progress] **F-M5-CHAT-HISTORY-01-E — viditelný výsledek a obnovení
  chatu (implemented; fyzická reakceptace selhala).** Stav rozlišuje počet
  sdílených/přijatých chatů, nulové aktivní mapování a nulový přenositelný
  obsah. Dokončení Sync i kliknutí na Chaty obnoví otevřený seznam vláken.
  Reálný seznam směšoval synchronizovaná projektová vlákna s lokálními
  nezařazenými vlákny, takže výsledek nebyl jednoznačně ověřitelný.
- [x] [completed] **F-M5-CHAT-HISTORY-01-F — automatická autorita enrollmentu
  (implemented; ad-hoc).** Klient–server sync deterministicky používá
  `account_binding` vytvořený přihlášením; nevyžaduje druhé ruční mapování.
  Aktivita serverového účtu a jeho projektové oprávnění se ověřují při každém
  exportu/importu. P2P kontrakt zůstává ručně bilaterální.
- [x] [completed] **F-M5-CHAT-HISTORY-01-G — webová identita synchronizovaného
  chatu (implemented; ad-hoc).** Webové chatové API čte i mění historii pod
  autentizovaným serverovým účtem, na který enrollment import mapuje vlákna;
  request-local vazba neuniká mezi souběžnými požadavky a desktop dál používá
  node-local autora.
- [ ] [in progress] **F-M5-CHAT-HISTORY-01-H — konvergence viditelné množiny
  (in progress; fyzická reakceptace selhala).** UI odděluje projektová vlákna od
  nezařazených vláken dostupných pouze na daném uzlu. Webová identita se nově
  zachovává také při zařazení vlákna a publikaci projektového záznamu. Reálný
  registr navíc ukázal rozdělení historie mezi starý serverový účet a nový účet
  z enrollmentu; webová správa proto musí odlišit úspěch transportu od
  viditelnosti výsledku v aktuální přihlášené relaci.

## Aktuální ověření

- Cílených 16 integračních testů prošlo, jeden podmíněný WebEngine test byl
  přeskočen; tentýž skutečný Qt/WebEngine test samostatně prošel a ověřil obě
  cesty obnovení seznamu.
- Samostatný end-to-end test klient–server provedl skutečný TLS enrollment,
  první projektový sync a následný přenos RW chatu pouze přes automatický
  `account_binding`; ruční mapping v testu nevznikl.
- Po opravě webové identity prošlo šest cílených regresí: HTTPS výpis a změna
  historie autentizovaného účtu, oddělení node-local historie, enrollment sync,
  stavové UI a obě původní desktopové cesty.
- Fyzická reakceptace znovu selhala kvůli rozdílným viditelným seznamům.
  Read-only kontrola lokálních metadat projektu `pokus` ukázala 33 projektových
  vláken a poslední receipt 33 odeslaných / 33 přijatých se všemi 33 shodnými
  ID i digesty; vedle nich UI zobrazovalo osm lokálních nezařazených vláken.
  Nový regresní test navíc ověřuje konvergenci dvou původně disjunktních
  projektových sad po jedné výměně.
- Po opravě rozlišení scope prošly čtyři cílené regrese: HTTPS vlastnictví a
  zařazení vlákna, webová oprávnění, textové rozlišení UI a konvergence sad.
- Registry evidence ukázala, že současný enrollment cílí na serverový účet
  `07a55f22…`, zatímco starší odvolané mapování stejného desktopového vlastníka
  používalo serverový účet `fa2e7150…`. Sync proto správně neslučuje jejich
  oddělené historie bez explicitního rebindu nebo migrace vlastníka. Nová
  fail-closed diagnostika porovnává webovou relaci s vlastníkem aktivního
  mapování a při rozdílu nehlásí chatový výsledek jako viditelný.
- Po doplnění diagnostiky identity prošlo šest cílených regresí včetně pinned
  HTTPS obousměrné výměny a disjunktních vstupních množin; úplná sada neběžela.
- Úplná sada před opravou webové identity prošla: **896 testů bez selhání,
  33 přeskočeno, za 219,253 s**. Následná oprava G je kvůli délce lokálního
  běhu ověřována cíleným víceuživatelským HTTPS testem; celá sada se zopakuje
  až před finálním PR nebo v CI. Zbývá finální diff a uživatelská reakceptace
  na reálných uzlech. Bez aktivního
  bilaterálního mapování se chat záměrně nepřenese a UI to nyní výslovně oznámí
  místo neurčitého „Obsah aktuální“.
