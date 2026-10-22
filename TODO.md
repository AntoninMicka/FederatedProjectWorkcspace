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
- [x] [completed] **F-M5-PERSONAL-SYNC-01-B — úzký replikační grant a durable
  desired state (cílová úroveň: implemented).** Nad schváleným peerem a
  aktivním oboustranným mapováním vydat podepsaný grant vázaný na oba uzly,
  project UUID, ref, směr a role primary/read-only replica. Zapnutí, zastavení,
  revokace a retry musí být auditovatelné a idempotentní; neznámý nebo stale
  stav nic nepovolí. Registry schema v4 (původně v3, následně migrované ADR
  0039) drží kanonický grant, podpisy obou uzlů,
  podepsaný revokační tombstone a lokální `enabled`; migrace v1/v2 zachovává
  účty a mapování. Podpisová doména replikace je oddělená od mapování účtů,
  specifikace připíná identity, účty, role, projekt, `refs/heads/main`, privacy
  bez `local-only` a pouze akce `read`/`replicate`. Aktivace vyžaduje současně
  schválený peer, aktivní přesné mapování, oba platné podpisy a lokální zapnutí;
  primary navíc potvrzuje vlastník projektu nebo `project-admin`. Opakování
  stejného stavu nevytváří další commit, změny mají pojmenovaný Git audit a
  revokace peeru grant podepsaně ukončí a vypne. Správu ostrovní federace může
  provádět `node-admin`; credential ani access key se do grantu nedostane.
  Cílené ověření nové logiky: **11 testů úspěšně**. Úplná sada po změně:
  **698 testů úspěšně, 28 přeskočeno** (volitelné fyzické/WebEngine scénáře).
- [x] [completed] **F-M5-PERSONAL-SYNC-01-C — bezpečný přenos a automatický
  fast-forward (cílová úroveň: implemented).** Rozšířit současný `public-only`
  přenos pouze v rozsahu přesného grantu. Odesílající i přijímající uzel ověří
  celý dosažitelný Git graf proti aktivnímu project/ref grantu a dovoleným
  privacy třídám; případný portable ACL smí výsledek pouze zúžit. `local-only`,
  nepokrytá historie, změněný HEAD, neplatný kandidát a revokace se odmítnou.
  Po pádu či ztrátě odpovědi recovery bezpečně určí stav bez duplicitního
  účinku. Sdílený bounded HTTPS endpoint nyní přijímá přesný podepsaný request
  a bundle bez browserového bearer tokenu; grant, identity, digest i celý Git
  graf ověřuje zdroj i příjemce. První přenos publikuje jedinou deterministickou
  repliku, další přenos používá dočasný ref a CAS fast-forward. Node-local
  journal uchovává request, bundle a podepsaný receipt, projektový journal
  odděluje recovery po změně refu; opakování stejné operace vrací tentýž
  výsledek. Divergence, dirty checkout, změněná větev, tampering, revokace a
  `local-only` selžou bez přepsání cíle. Cílené replikační ověření: **8 testů
  úspěšně** mimo socketově omezený sandbox. Spouštění/scheduler, pravdivé stavy
  v UI a serverové vynucení read-only pro všechny editory zůstávají úkolem D;
  fyzický desktop ↔ server scénář zůstává úkolem E. Úplná sada po finálním
  zpevnění: **706 testů úspěšně, 28 přeskočeno** (volitelné fyzické/WebEngine
  scénáře).
- [x] [completed] **F-M5-PERSONAL-SYNC-01-D — sdílené webové/desktopové UI
  synchronizace (cílová úroveň: implemented).** Ve správě federace nabídnout
  výběr schváleného peeru a projektu, potvrzení primary/replica směru, zapnutí
  a zastavení. Zobrazit poslední úspěch, čekání/offline, odmítnutí, revokaci a
  konflikt; read-only replika nesmí v editoru předstírat možnost zápisu.
  Sdílená správa nyní vytváří, oboustranně potvrzuje, importuje/exportuje,
  zapíná, zastavuje a odvolává grant; primary nabízí i okamžité spuštění.
  Backendový scheduler po zapnutí každých 60 sekund serializovaně dorovnává
  primary grant a durable stav rozlišuje `idle`, `pending`, `offline`,
  `rejected`, `conflict` a `error` včetně posledního úspěšného HEAD. Offline
  retry zachová přesný operation ID a bundle, i když primary mezitím pokročí.
  Otevřený projekt nese explicitní replikační roli, UI skrývá editační akce a
  centrální guard znovu odmítne každý `Workspace.apply`/`transact` pod writer
  lockem; nejde tedy jen o kosmetické omezení. Správu ostrovní federace vidí i
  `node-admin`, zatímco udělení vyšší role zůstává oddělené. Cílené replikační
  a účtové ověření: **25 testů úspěšně**; širší sdílené UI/API ověření:
  **98 testů úspěšně, 6 přeskočeno**. Úplná sada: **709 testů úspěšně,
  28 přeskočeno** (volitelné fyzické/WebEngine scénáře).
- [ ] [in progress] **F-M5-PERSONAL-SYNC-01-E — automatické a fyzické ověření
  (cílová úroveň: PoC validated).** Pokrýt první přenos, následný fast-forward,
  restart na persistentních hranicích, offline návrat, idempotentní retry,
  zastavení/revokaci, změněný HEAD, neúplnou historii, `local-only`, neplatný
  kandidát a divergenci bez přepsání cíle. Nakonec ověřit desktopový a
  LXC/serverový uzel se skutečným projektem a zaznamenat zbývající omezení.
  Automatický TLS integrační scénář nyní bez mocku transportu ověřuje první
  repliku, nový control po restartu, následný fast-forward, offline stav,
  retry stejného durable operation ID po návratu peeru, zastavení a revokaci
  bez další změny repliky. Samostatný podepsaný thin bundle bez base commitu se
  odmítne bez změny replica refu; dřívější testy dále pokrývají crash hranice,
  tampering, změněný HEAD, divergenci a `local-only`. Cílená sada:
  **13 testů úspěšně**. Úplná sada: **711 testů úspěšně, 28 přeskočeno**.
  Fyzická příprava 22. 10. 2026 ověřila TLS i podepsanou identitu existujícího
  LXC peeru a projekt `Pokus` jako čistou přenositelnou historii tří commitů.
  První capability kontrola během probíhající aktualizace ještě vrátila HTTP
  401; po jejím dokončení vzdálená replikační cesta vrací očekávané protokolové
  413 na prázdný request a TLS i podepsaná identita zůstaly platné. Zbývá
  vytvořit oboustranné mapování/grant a fyzicky potvrdit první přenos,
  fast-forward a offline návrat. Při dosavadní kontrole nebyl vytvořen grant
  ani změněn desktopový či LXC projekt.
- [x] [completed] **F-M5-PERSONAL-SYNC-01-UI1 — facelift správy
  federovaných uzlů (cílová úroveň: implemented).** Nahradit vložený formulář
  výběrovou tabulkou s akcemi Přidat, Upravit a Odebrat. Přidání a editace
  používají samostatný webový dialog; UUID a otisk zůstávají při editaci
  neměnnou připnutou identitou. Odebrání je bezpečná revokace s auditní stopou,
  nikoli fyzické smazání registru. Dosavadní mapování a replikační formuláře
  zůstanou po dobu navazujícího návrhu skrytou přechodovou implementací.
  Sdílené webové/desktopové UI nyní nabízí výběrovou tabulku, samostatný
  editor pro přidání i úpravu a webové potvrzení odebrání. Atomická operace
  `update-peer` mění pouze název, HTTPS endpoint a důvěru; UUID a fingerprint
  nepřijímá a při revokaci používá stejné durable tombstones jako původní
  trust flow. Reuse: adaptován existující HTML `<dialog>` vzor a revokační
  kontrakt; nový Qt dialog ani fyzické mazání registru nebyly zavedeny.
  Cílené ověření: **10 testů úspěšně**, vygenerovaný JavaScript prošel
  `node --check`; úplná sada: **712 testů úspěšně, 28 přeskočeno** (volitelné
  fyzické/WebEngine scénáře). Následná oprava navigace zajistila, že otevření
  Federace nebo Uživatelů přímo z boční nabídky nejen přepne panel, ale také
  načte administrační stav; jinak zůstávala nová tabulka v počátečním prázdném
  stavu, přestože backend peer správně vracel.
- [x] [completed] **F-M5-PERSONAL-SYNC-01-UI2 — explicitní typy
  federačních vztahů (cílová úroveň: implemented).** Rozlišit serverové P2P a
  klient–server spojení, staré záznamy bezeztrátově označit jako `legacy` a v
  tabulce i editoru zobrazit typ a lokální roli. Legacy vztah ponechat funkční,
  ale při editaci povolit jen převod nebo bezpečné odebrání. Převod atomicky
  odvolá dosavadní mapování i replikační granty a vrátí trust do `pending`;
  P2P lze ručně založit jen mezi servery. Přihlášení desktopového klienta k
  serveru, vydání node credentialu a automatické mapování serverového účtu je
  výslovně navazující řez a současné UI je nesmí předstírat. Kontrakt, migraci
  registru v1–v3 na v4 a crash/recovery hranice definuje ADR 0039. Registry
  validátor vynucuje přípustnou kombinaci typu, lokální role a endpointu;
  klient–server nelze ručně založit ani schválit. Cílené ověření migrací,
  převodu a revokace: **12 testů úspěšně**; vygenerovaný JavaScript prošel
  `node --check` a změněné Python moduly `py_compile`. Úplná sada po změně:
  **716 testů úspěšně, 28 přeskočeno** (volitelné fyzické/WebEngine scénáře).
  Přihlašovací enrollment a jeho fyzická akceptace zůstávají navazující prací.
- [x] [completed] **F-M5-PERSONAL-SYNC-01-UI3 — serverová správa lokálních
  účtů (cílová úroveň: implemented).** Na desktopu skrýt správu uživatelů a
  nový kontaktní profil bezpečně předvyplnit zobrazovaným jménem systémového
  účtu bez odvozování kontaktů či oprávnění. Na serveru nahradit vložené
  formuláře výběrovou tabulkou s akcemi Přidat, Upravit,
  Aktivovat/Deaktivovat a Nový klíč; přidání i editace používají samostatný
  webový dialog a citlivé stavové operace potvrzení. Fyzické mazání účtů
  nezavádět, aby zůstaly zachované identity a audit. Federační mapování zůstává
  oddělenou entitou a jeho matice je navazující řez. Cílené testy správy účtů
  a profilu: **14 úspěšně, 1 přeskočen** (volitelný QR dekodér); inventura
  formulářů: **3 úspěšně**; statický desktopový kontrakt: **1 úspěšně**.
  Vygenerovaný JavaScript prošel `node --check` a změněné Python moduly
  `py_compile`. Úplná sada po změně: **718 testů, OK (28 přeskočeno)**;
  přeskočené scénáře vyžadují volitelné závislosti nebo fyzický WebEngine.

## K předání do backlogu

- [ ] [planned] **F-M5-FED-MAPPING-UI-01 — matice mapování účtů (cílová
  úroveň: designed → implemented).** Samostatná tabulka s lokálními účty v
  řádcích a cizími uzly ve sloupcích; buňka určí vzdáleného uživatele, stav a
  rozsah mapování. U P2P vyžadovat oboustranné potvrzení, u klient–server
  odvodit mapování z enrollmentu. Doplnit filtr podle uživatele a uzlu a pro
  mobil použít lineární seznam bez vnořeného vodorovného scrollování. Tato
  položka není podmínkou dokončení současné dávky.
- [ ] [planned] **F-M5-FED-ENROLL-01 — klient–server enrollment (cílová
  úroveň: implemented).** Podle ADR 0039 nahradit dočasnou hlášku skutečným
  přihlášením desktopového klienta serverovým účtem přes ověřené TLS. Připnout
  node key klienta, vydat omezený obnovitelný node credential a atomicky
  vytvořit explicitní mapování lokální desktopové identity na přihlášený účet;
  heslo ani dlouhodobý uživatelský access key neukládat. Pokrýt odvolání,
  rotaci, ztracenou odpověď, opakování, změnu serverového účtu a fyzický
  desktop ↔ server scénář. Tato položka není podmínkou dokončení současné
  dávky.

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
