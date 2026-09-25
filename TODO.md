<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-CHAT-DIRECT-01: Přímý brainstormingový dispatch

Milník M3; implementace byla začleněna PR #43 (`32cf743`) do `develop` před
uzavřením akceptace. Dokončení části D proto probíhá na navazující větvi
`feature/f-m3-chat-direct-01-acceptance` s cílem `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [x] [completed]; aktivována 2026-09-20 po začlenění M3-UB-01
  jako PR #42 (`43fc8e3`). Implementační větev
  `feature/f-m3-chat-direct-01` byla začleněna PR #43 (`32cf743`) ještě s
  otevřenou částí D; navazující acceptance větev vznikla z tohoto merge commitu.
- Původ: uživatelský požadavek 2026-09-20, aby brainstorming odesílal požadavek
  přímo, historie nadále ukázala skutečně odeslaný request a providerem
  podporovaná odpověď se zobrazovala streamovaně.
- Výstup: přímý externí brainstormingový dispatch po aplikační autorizaci a
  privacy kontrole, bezpečně zobrazitelná historie přesného provider requestu a
  volitelné streamované UI se stejným durable finálním výsledkem jako
  ne-streamovaný adapter.
- Hranice: brainstorming nepřijímá projektové artefakty ani externě neposílá
  `local-only`; režim/model zůstávají per-run. Historie nesmí vracet credential,
  autorizační hlavičky ani neveřejný interní stav adapteru. Streaming není
  autoritou výsledku a provider bez této capability používá celou odpověď.
- Recovery: `dispatching` musí být durable před prvním síťovým účinkem. Ztráta
  spojení po jeho zahájení zůstává `unknown`, nikdy automatický retry ani skrytý
  fallback. Textové delty jsou dočasné; teprve validovaná finální odpověď se
  uloží do vlákna a run evidence.
- Mimo rozsah: orchestration chat, projektový kontext v brainstormingu,
  creator/opponent workflow, obrazové capability, změna provider billing nebo
  obecná správa a mazání vláken.

- [ ] **[planned] D-01 — Demo presenter: Linux gamepad driver patch pro jiný projekt.**
  Příprava stručného přednáškového materiálu a demo flow pro udev/evdev gamepad patch z externího projektu. Výstup: přehled funkce, ukázka klíčových změn, výhody, rizika a návrhy dalšího kroku bez zasahování do aktuálního repozitáře.
  Úroveň: designed.

## Aktivní části dávky

- [x] [completed] **F-M3-CHAT-DIRECT-01-A — Kontrakt, provider review a reuse
  (designed).** ADR 0008 vymezuje přímý dispatch výhradně pro explicitní
  brainstormingový tah po serverové autorizaci, přesný request record bez
  secrets, SSE capability a durable hranici před sítí. Delty jsou ephemerální,
  finální `response.completed` musí projít dosavadní validací a ztráta streamu
  po `dispatching` zůstává `unknown` bez retry. Dosavadní adapter, run journal,
  Context Manifest, mode policy a vlastnictví vlákna se adaptují; preview store
  zůstává pro task workflow a historické záznamy. Oficiální Responses streaming
  guide byl ověřen 2026-09-20; cizí kód ani nový framework se nepřebírá.
- [x] [completed] **F-M3-CHAT-DIRECT-01-B — Přímý dispatch a historie requestu
  (implemented).** Explicitní externí brainstorming používá nový přímý endpoint
  nad stejným Context Manifestem, binding hashem, durable dispatch záznamem a
  OpenAI run journalem jako dosavadní potvrzený tok. Request body bez hlaviček a
  credentialu se váže na run ID a vlastník jej může rozbalit u odpovědi i po
  restartu. Lookup před opětovnou přípravou zajišťuje idempotentní retry bez
  druhého síťového účinku. Task a pokročilé preview/confirm zůstaly zachované.
  Web endpoint je do oddělení identity chat store od procesní desktop identity
  fail-closed omezený na administrátora; běžný webový člen dostane 403.
  Cílených 53 chat/OpenAI/UI/HTTPS testů prošlo se 2 Qt skipy.
- [x] [completed] **F-M3-CHAT-DIRECT-01-C — Volitelné streamované zobrazení
  (implemented).** Capability-gated Responses SSE transport a desktopové i
  webové UI zobrazují textové delty průběžně; provider bez deklarované podpory
  zachovává ne-streamovaný fallback. Dílčí text je pouze dočasný a durable chat
  dostane až validovanou finální odpověď. Chybná událost skončí jako `failed`,
  timeout, přerušení nebo zavření klienta jako `unknown`, bez částečné
  asistentovy zprávy. Webový endpoint zachovává administrátorskou RBAC hranici.
  Příprava runu používá stejnou hodnotu `stream` jako následný dispatch; tím se
  odstranila kolize request digestu, která dříve uzavřela lokální stream bez
  terminální odpovědi ještě před voláním providera. HTTP integrační test navíc
  čte skutečné NDJSON delty i terminální výsledek přes socket a kryje serializaci
  handleru včetně dříve chybějícího runtime importu.
  Cílených 68 OpenAI/chat/desktop/web testů prošlo se 3 Qt skipy, JavaScript
  prošel `node --check`; úplná sada 353 testů prošla s 22 skipy.
- [x] [completed] **F-M3-CHAT-DIRECT-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Automatické regrese pokrývají RBAC/privacy, přesný request
  bez secrets, běžnou i streamovanou odpověď, pořadí skutečných UTF-8 delt,
  restart/idempotenci, stale binding, timeout a přerušený běh jako `unknown`,
  malformed stream jako `failed`, absenci částečné durable odpovědi a vědomý
  nový run bez opakování původního síťového účinku. Uživatel 2026-09-20 živě
  potvrdil desktopový OpenAI stream po opravě přípravy request digestu a NDJSON
  serializace. Živý streamovaný webový smoke nebyl proveden; jeho endpoint,
  administrátorská RBAC hranice a wire formát jsou ověřené integračně.
  Závěrečných 69 cílených testů prošlo se 3 Qt skipy, výsledný JavaScript prošel
  `node --check` a úplná sada 354 testů prošla s 22 environmentálními skipy.

## Předání

Funkce je implementovaná a PoC validovaná. PR #43 obsahuje implementaci;
navazující acceptance diff doplňuje regresní testy a opravuje stavovou evidenci.
Po jeho začlenění přesunout tuto dávku do WORK_LOG a aktivovat jedinou další
dávku z BACKLOG podle pravidel předání.

## Ad-hoc úprava existujícího presenteru — D-02

- [x] [completed] **D-02 — Rozdělení pravého panelu presenteru (implemented).**
  Původ: požadavek uživatele 2026-09-25; pokračování existujícího demo UI
  na větvi `feature/gamepad-demo-presenter`, cíl případného PR `develop`.
  Rozsah: záložky a samostatný náhled dalšího obsahu s poznámkami;
  „K slidu“ používá další hlavní slide, „Backupy“ soukromý výběr backupu.
  Adaptuje existující renderer a presenter controls v `spikes/desktop_ui.py`;
  náhled aktuálního i vybraného slidu sdílí renderování poznámek a vzhled.
  Bez změny persistence či recovery. Akceptace: přepínání obsahu i poznámek,
  prázdný výběr a konec decku, zachování explicitního promítnutí.
  Cílených 16 desktopových testů prošlo se 2 Qt skipy; nový Node.js test
  ověřuje přepínání zdroje náhledu, poznámky a konec decku. Syntaxe JS ověřena.
  Úplná sada: 357 testů, 22 skipů, jediná chyba byla chybějící SPDX
  hlavička v existujícím `docs/gamepad-demo-presenter.md`. Hlavička doplněna
  jako oprava nutná pro ověření presenter větve; následný samostatný
  `python3 -m unittest tests.test_spdx -v` prošel. Po této čistě dokumentační
  opravě nebyla celá sada opakována. `node --check` a `git diff --check` prošly.
  Po dodání obrázku upřesněno rozložení na dva sloupce vedle sebe:
  vlevo záložky a samostatně posouvaný seznam, vpravo náhled a pod ním
  poznámky vyplňující zbývající výšku. Opraven kontrast nadpisů a poznámek
  v bílém panelu. Statický layout ověřen screenshotem headless Chromium
  při 1996 × 1120 s dlouhým seznamem backupů; živé Qt UI není ověřené.
  Finální úplná sada po změně CSS: 357 testů, OK (22 environmentálních
  skipů). `git diff --check` prošel. Historická evidence TODO popisuje jinou
  dávku než existující presenter větev; tato úprava ji administrativně neuzavírá.

- [x] [completed] **D-03 — Backupy přiřazené k aktuálnímu slidu (implemented).**
  Původ: navazující požadavek uživatele 2026-09-25 pro existující presenter
  na větvi `feature/gamepad-demo-presenter`, cíl `develop`.
  Rozsah a akceptace: záložka „K slidu“ ukazuje pouze backupy s explicitním
  `after_slide` odpovídajícím aktuálnímu hlavnímu slidu, aktualizuje se při
  navigaci, podporuje hledání, prázdný stav a soukromý výběr backupu.
  Reuse/adapt: existující pole `after_slide`, společná tvorba položek obou
  seznamů a dosavadní potvrzení promítnutí; bez změny persistence/recovery.
  Cílených 17 desktopových testů prošlo se 2 Qt skipy. Node.js regrese ověřuje
  explicitní vazbu včetně odmítnutí chybějící/null/textové hodnoty, změnu slidu,
  hledání, prázdný seznam a soukromý výběr. `node --check` prošel.
  Úplná sada: 358 testů, OK (22 environmentálních skipů).
  `git diff --check` prošel; živé Qt UI není ověřené.

- [x] [completed] **D-04 — Dočasné pořadí a listování joystickem (implemented).**
  Původ: požadavek uživatele 2026-09-25; existující větev
  `feature/gamepad-demo-presenter`, cíl `develop`.
  Výstup: v „K slidu“ volba plánovaného slidu nebo přiřazeného backupu;
  výběr backupu jej vloží za aktuální pozici do dočasného seznamu prezentace.
  Před prvním promítnutím lze tuto volbu nahradit jiným backupem nebo zrušit
  volbou plánovaného slidu. Již promítnuté backupy zůstávají v pořadí při
  procházení oběma směry; explicitní volba plánovaného slidu je může přeskočit,
  ale nemaže je. Levá páčka: doprava další, doleva předchozí; pravá páčka:
  vodorovně záložky, svisle výběr. Stejné pořadí používají tlačítka i šipky.
  Reuse/adapt: dosavadní presenter renderer, `after_slide` a veřejný control
  endpoint; nový lokální model pořadí nahrazuje přímé posouvání hlavního indexu.
  Akceptace: zachované pořadí při návratu přes více backupů, konec decku,
  změna dosud nepromítnuté volby, neutrální poloha před novým gestem,
  ignorování skrytého/neaktivního presenteru a sériové potvrzování navigace.
  Hranice/recovery: pořadí žije pouze v paměti rendereru po dobu jedné
  prezentace; nové otevření/reload ho resetuje. Nezapisuje Git, index ani
  journal, nejde o durable historii schůzky. Selhání control requestu nemění
  potvrzenou pozici; UI upozorní na nepotvrzený výstup, bez automatického retry.
  Cílených 20 testů prošlo se 2 Qt skipy: pořadí, změny volby, návraty,
  oddělení os, neutral/hold, reconnect/focus a selhání/souběh control requestů.
  Headless Chromium smoke se skutečným DOM, simulovaným gamepadem a mock
  control transportem prošel: výběr bez promítnutí, zrušení volby, vložení,
  průchod tam/zpět, držení páčky a ignorování skrytého presenteru.
  Finální úplná sada: 361 testů, OK (22 environmentálních skipů).
  `node --check` a `git diff --check` prošly; fyzický gamepad/živé Qt neověřeny.

- [x] [completed] **D-05 — Role displejů a veřejné okno (implemented).**
  Původ: požadavek uživatele 2026-09-25, dokončení existujícího presenteru
  na větvi `feature/gamepad-demo-presenter`, cíl `develop`.
  Rozsah/akceptace: nabídka rolí při otevření a změnách displejů, číslované
  identifikátory s navrhovanou rolí, odlišný displej pro řečníka a publikum,
  nácvik bez promítání, opětovné nastavení a skrytí výstupu při zavření.
  Reuse/adapt: existující Qt okna, veřejný renderer a nativní fragmentové
  akce; nový kontroler pouze řídí jejich umístění a životní cyklus. Navazuje
  na REUSE_CATALOG (Qt obal) a roadmapu 22C, nemění architekturu ADR 0007.
  Recovery: role jsou pouze v paměti, žádné nové zápisy do Git/indexu/journalu.
  Změna topologie skryje veřejné okno a vyžádá nové potvrzení; zrušení ponechá
  výstup skrytý. Restart začíná bez promítání. Systémové zrcadlení se nemění.
  Cílených 24 testů prošlo se 2 WebEngine skipy, včetně čtyř nových Qt testů
  (offscreen; dva displeje a jejich odpojení simulované). Syntaxe JS ověřena.
  Finální úplná sada: 365 testů, OK (22 environmentálních skipů).
  Samostatný skutečný Qt/WebEngine smoke potvrdil fragmentovou událost bez
  reloadu stránky. `git diff --check` prošel. Fyzické monitory/Wayland a celé
  živé propojení presenteru se dvěma displeji neověřeny; nejde o production-ready.

- [x] [completed] **D-06 — Oprava načítání diváckého okna (implemented).**
  Původ: uživatelské hlášení 2026-09-25 o nedostupné stránce publika;
  oprava nutná pro akceptaci presenteru na `feature/gamepad-demo-presenter`.
  Příčina: desktopový management handler přepisoval mapu assetů a vynechal
  `/presentation-screen`, takže ji blokoval i request interceptor. Po opravě
  skutečný WebEngine odhalil druhou chybu: CSP blokovala inline styl a skript.
  Reuse/adapt: management přebírá základní mapu a mění jen vlastní UI assety;
  divácký CSS/JS se servíruje jako samostatné lokální assety podle existující CSP.
  Bez oslabení CSP, rozšíření API oprávnění či změn persistence/recovery.
  Akceptace: skutečný management handler vrací stránku i její assety; divácké
  polling API stále vyžaduje token a WebEngine vykreslí schválený slide.
  HTTP regrese před opravou reprodukovala blokování stránky. Po opravě cílená
  sada 18 testů prošla se 2 skipy; nový samostatný Qt/WebEngine offscreen smoke
  ověřil stránku, CSS, autentizovaný polling a skutečně vykreslený schválený slide.
  Finální úplná sada: 367 testů, OK (23 environmentálních skipů, včetně
  opt-in WebEngine testu spuštěného výše samostatně). `node --check` a
  `git diff --check` prošly. Fyzické displeje neověřeny.

- [x] [completed] **D-07 — Základní projektový editor prezentací (implemented).**
  Původ: uživatelský požadavek 2026-09-25 na editor pozadí, barvy, tapety,
  nadpisu, odrážek a vazeb next/backup v obou směrech. Uživatel výslovně
  schválil pokračování v `feature/gamepad-demo-presenter`; pro tuto změnu
  jde o výjimku z oddělené feature větve. Cíl zůstává `develop`, PR nevytvořen.
  Rozsah: více verzovaných prezentací v projektu, přidání/odstranění hlavních
  slidů a backupů, soukromé poznámky, lokálně vložené tapety, nativní náhled,
  next/previous jako jedna konzistentní linie a sdílené backupy s opačným
  přiřazením. Presenter přebírá uloženou revizi až explicitním spuštěním;
  editace/uložení nemění veřejný výstup. Stará revize nesmí promítnout cizí slide.
  Reuse/adapt: `Artifacts.save`, `Workspace.transact`, `EditorWorker`, stávající
  nativní fragmentové akce, dočasná navigace a veřejný renderer. Žádný nový
  framework, HTTP writer ani externí asset; REUSE_CATALOG a ADR 0003 zachovány.
  Recovery: před commitem journal dokončí připravený zápis, po commitu rebuild
  indexu z HEAD; žádné nové crash boundaries oproti ADR 0003. Opakované uložení
  používá stejný operation ID/request, neuložený koncept žije v paměti editoru.
  Akceptace: save/reopen/restart a idempotentní retry; odmítnutí stale HEAD,
  chybných vazeb/ID/obrázků; recovery po pádu; obousměrné vazby v nativním UI;
  oddělený veřejný obsah se skutečně vykreslenou tapetou/barvami/odrážkami.
  Cílená sada: 35 testů, OK (3 opt-in WebEngine skipy). Samostatný skutečný
  Qt/WebEngine smoke prošel: demo i uložený slide, doslovné odrážky, barva
  textu a dekódovaná tapeta. Nové testy pokrývají čtyři skutečné pády procesu
  (`prepared`, `files-applied`, `ref-updated`, `indexed`), přesné obnovení decku
  a jediný commit. Tři nativní Qt testy ověřily editaci, sdílené backupy,
  save/reopen/use, odmítnutí zahození konceptu a opakování nejistého uložení.
  Oba JavaScript assety prošly `node --check`; editor vizuálně zkontrolován
  screenshotem při 1180 × 820. Finální úplná sada: 376 testů, OK
  (23 environmentálních skipů). Také dva launcher/WebEngine smoke testy
  (spuštění/zavření/restart a pád rendereru) prošly se softwarovým renderingem
  `QT_QUICK_BACKEND=software`, `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu`;
  první offscreen pokus s GPU selhal ztrátou grafického kontextu/SIGSEGV.
  `git diff --check`, syntaxe a whitespace nových souborů i odkaz na ADR
  v návodu ověřeny. Dokumentační změny po testech nemění běhový kód.
  Omezení: desktopový PoC, bez zanořených scénářů a trvalé relace; základní
  limity obsahu a 16:9 editorový náhled viz návod. Fyzické displeje neověřeny.

- [x] [completed] **D-08 — Výběr hlavní linie, jednorázové slidy a řádky (implemented).**
  Původ: požadavek uživatele 2026-09-25; navazuje na D-04/D-07 na existující
  větvi `feature/gamepad-demo-presenter`, cíl `develop`, PR nevytvořen.
  Rozsah/akceptace: soukromý výběr hlavního slidu levou páčkou, potvrzení
  tlačítkem A, dočasné přeuspořádání bez ztráty přeskočených slidů;
  promítnuté hlavní i backup slidy se bez explicitního opakování nenabízejí.
  Výjimkou je jednorázový výchozí návrat z backupu na předchozí slide.
  Editor nastavuje opakování a odrážky najednou/postupně; relace uchovává
  odhalené řádky, návrat přidává další řádek, dokončený slide se vyřadí.
  Reuse/adapt: existující sekvence, Qt editor, veřejný renderer a projektový
  dokument; žádná externí komponenta. Nahrazuje historické chování D-04.
  Recovery: nastavení se ukládá stejnou transakcí dle ADR 0003, beze změny
  crash boundaries; postup a pořadí jsou pouze v paměti relace. Při chybě
  potvrzení se lokální postup nemění, reload zakládá novou relaci.
  Staré dokumenty bez nových polí mají opakování vypnuté a řádky najednou.
  Finálních 35 cílených testů prošlo se 3 opt-in WebEngine skipy; testy
  pokrývají soukromý výběr, potvrzení, neutrální polohu, návraty, filtrování,
  postupné řádky, selhání/souběh requestů a save/reopen nových voleb.
  Finální úplná sada: 380 testů, OK (23 environmentálních/opt-in skipů).
  Syntaxe obou JS assetů prošla `node --check`; `git diff --check` prošel.
  Fyzický gamepad/displeje a živé Qt/WebEngine propojení této změny neověřeny.
  Změna je implemented, nikoli production-ready; širší historická dávka
  ani strategický Disclosure Presenter MVP se tím neuzavírají.

  Upřesnění D-08 od uživatele 2026-09-26: levá páčka nahoru/dolů mění
  soukromý výběr hlavní linie; doprava/doleva opět promítá další/předchozí
  dostupný slide. Pravidla opakování, návratu a řádků se nemění. Při šikmém
  gestu má promítnutí původní volby přednost před změnou výběru.
  Adaptace existujícího mapování bez změny persistence. Ověření 2026-09-26:
  6 cílených testů prošlo; úplná sada 380 testů, OK (23 skipů).
  `node --check` a `git diff --check` prošly; fyzický gamepad neověřen.

- [x] [completed] **D-09 — Historie promítání a závěrečný kontaktní slide (implemented).**
  Původ: požadavek uživatele 2026-09-26, upřesněný o kontakty v nastavení
  aplikace/profilu uživatele. Pokračuje stejná presenter feature na
  `feature/gamepad-demo-presenter`, cíl `develop`, PR nevytvořen.
  Výstup/akceptace: zpětný krok smí promítnout spotřebovaný slide; celé
  dočasné pořadí včetně backupů/návratů zůstává viditelné a zpětný průchod
  je nepřepisuje. Automatický závěr má uprostřed „Prostor pro Vaše dotazy“
  a vpravo dole kontakty a QR z lokálního uživatelského profilu.
  Reuse/adapt: současný renderer/navigace, native fragment actions a SQLite;
  QR přes Segno 1.6.6 (BSD-3-Clause), bez externí služby a kopírování kódu.
  Profil desktopového OS uživatele je samostatná lokální SQLite databáze
  vedle node.json, není projektový index ani journal. Jedna transakce ukládá
  celý profil; pád před commitem zachová původní hodnotu, po commitu novou.
  Dočasná sekvence a snímek profilu žijí v paměti relace; úprava profilu
  nezmění běžící promítání. Žádná změna crash boundaries ADR 0003.
  Ověření: 42 cílených testů, OK (3 opt-in skipy); úplná sada 388 testů,
  OK (24 environmentálních/opt-in skipů). Spuštěno se Segno 1.6.6 a
  volitelným nezávislým QR dekodérem z dočasné testovací instalace.
  Procesní pády před commitem prvního i dalšího uložení profilu zachovaly
  prázdnou/původní hodnotu; save/reopen nativního dialogu a snapshot relace
  ověřeny. Samostatný Qt/WebEngine test prošel při 16:9 a 4:3: vycentrovaný
  nadpis, kontakty vpravo dole, dekódovaný PNG. Screenshot při 1280 × 720
  vizuálně zkontrolován a jeho QR nezávisle přečten včetně české diakritiky.
  `node --check` pro oba assety, `bash -n run.sh` a `git diff --check` prošly.
  Lokální ignorovaná .venv má deklarované závislosti a přístup k systémovému
  Qt. Fyzický gamepad/projektor a instalace .deb na cílový OS neověřeny;
  historický audit runtime nebyl rozšířen na novou knihovnu. Implemented PoC,
  nikoli production-ready; širší dávka ani Disclosure Presenter MVP neuzavřeny.
