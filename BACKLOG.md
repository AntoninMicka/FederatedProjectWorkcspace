<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Backlog — další dávky

Aktuální dávku drží [TODO](TODO.md), uzavřené dávky [WORK_LOG](WORK_LOG.md), milníky a gates [roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>). Pravidla určuje [AGENTS](AGENTS.md).

Plánovací horizont tvoří zpravidla tři nejbližší **feature dávky**: jedna dávka, jedna feature větev, jeden PR do `develop`. Milníky M1–M6 zůstávají strategickým rámcem. Níže zachované široké a vzdálenější položky jsou zásobník požadavků, nikoli připravené PR dávky. Při běžné implementaci se tento soubor nemění; tato reorganizace je výslovně zadaná změna workflow. Při předání se další jediná dávka přesune do TODO se stejnými ID a návaznostmi. Ověřená práce se neopakuje.

## Nejbližší feature dávky

Názvy větví jsou návrhy, PR dosud nejsou vytvořené. Před zahájením každé dávky ověřit začlenění jejích konkrétních závislostí do `develop`; splněný Gate M1 neznamená automatické uzavření ostatních požadavků.

F-M2-CONTEXT-01, F-M2-OLLAMA-01, F-M1-UI-01, F-M2-CHAT-01/02,
F-M2-SUMMARY-01, F-M2-EXTRACT-01, F-M2-META-AI-01, F-UX-SETTINGS-01 a
F-M3-BACKEND-01 jsou po PR #26–#35 uzavřeny ve WORK_LOG.
F-M3-EXTERNAL-01 je po PR #36 uzavřen ve WORK_LOG. F-M1-PROJECT-LOCATION-01 je
po PR #37, F-M3-CHAT-MODES-01 po PR #40, M3-UB-01 po PR #42 a
F-M3-CHAT-DIRECT-01 po PR #44 a MOD-01-UI po PR #45 jsou uzavřené ve WORK_LOG.
F-M3-MEDIA-01 je po PR #46 a F-M4-WORKFLOW-01 po PR #47 uzavřen ve WORK_LOG.
`IMP-02` bylo doručeno PR #48 a `UX-MOBILE-01` PR #49.
`F-M3-OLLAMA-ROBUST-01` bylo doručeno PR #50 a `F-M2-CHAT-03` PR #51.
`WEB-RUNTIME-01` bylo doručeno PR #52 jako merge commit `7bb4f5e`.
`UX-UNIFIED-01` bylo doručeno PR #53 jako konsolidovaný merge commit `571b430`;
jeho evidence je ve WORK_LOG. Prozatímní backlogová ID
`UX-UNIFIED-02A/02B` byla sloučena do dokončených `UX-UNIFIED-01-E/F` a nejsou
samostatnými feature. `UX-UNIFIED-02D` bylo doručeno PR #54 jako merge commit
`0ce9cb7`; evidence je ve WORK_LOG a další feature zatím nebyla aktivována.
`F-M3-OLLAMA-ORCH-LAN-01` bylo doručeno PR #56 jako merge commit `a9207c5` a
navazující `F-M3-OLLAMA-ORCH-LAN-01-FIX1` PR #57 jako merge commit `f8bc5b7`.
`M1-LXC-DNS-TLS-01` bylo doručeno PR #58 jako merge commit `916e5ec`. Evidence
je ve WORK_LOG. `F-M4-OUTPUT-ROUTER-01` bylo doručeno PR #59 jako merge commit
`d96fe7a`; evidence je ve WORK_LOG. `F-M4-OUTPUT-ROUTER-02` bylo doručeno PR #60
jako merge commit `1101d52` a `UX-UNIFIED-02C` PR #61 jako merge commit
`436f4e6`. `UX-UNIFIED-02C-FIX1` bylo po fyzické akceptaci doručeno PR #62 jako
merge commit `4d2e32c`; evidence je ve WORK_LOG. `F-M3-OLLAMA-STREAM-01` bylo
doručeno PR #63 jako commit `5c3b565`; evidence je ve WORK_LOG.
`F-M3-SEARCH-01` bylo doručeno PR #64 jako merge commit `7373d81`; evidence je
ve WORK_LOG. `F-M1-PROJECT-DELETE-01` bylo doručeno PR #65 jako merge commit
`a09538e`; evidence je ve WORK_LOG. `IMP-01` bylo po fyzické akceptaci
doručeno PR #66 jako merge commit `3466a5f`; evidence je ve WORK_LOG.
`F-M3-SEARCH-02` bylo doručeno PR #67 jako merge commit `6c94047`,
`F-M4-PRESENTER-01` PR #68 jako merge commit `aa7fa26` a
`F-M4-PRESENTER-PDF-01` PR #69 jako merge commit `8338a6c`; jejich evidence je
ve WORK_LOG. `UX-FACELIFT-01` bylo doručeno PR #72 jako merge commit `9fb4262`.
Vydání 0.1.0 bylo doručeno PR #74 do `main`, označeno tagem `v0.1.0` a jeho
evidence je ve WORK_LOG. Návrh `UX-PROJECT-REPAIR-01` byl doručen PR #75 jako
merge commit `618b1f7`; implementační dávka `UX-PROJECT-REPAIR-02` byla
doručena PR #76 jako commit `80c083b` a `F-M2-CHAT-LANGUAGE-01` PR #77 jako
commit `e1366be`. Cílový směr `UX-FEDERATION-02` byl doručen PR #78 jako commit
`192e79c`; jeho evidence je ve WORK_LOG. `F-M5-PERSONAL-SYNC-01` bylo doručeno
PR #79 jako merge commit `61df652`; jeho implementační evidence je ve WORK_LOG
a cílová fyzická akceptace byla následně naplněna novým obousměrným řezem.
`F-M5-PROJECT-CATALOG-01` bylo doručeno PR #80 jako merge commit `ae1b25e`;
evidence je ve WORK_LOG.
`F-M5-SHARING-SYNC-01` bylo doručeno PR #81 jako merge commit `c884cd2`; jeho
evidence je ve WORK_LOG. `F-M5-CONFLICT-RESOLUTION-01` bylo doručeno PR #82
jako merge commit `637bf90`; evidence je ve WORK_LOG. `M1-07-C` bylo
23. 10. 2026 fyzicky naplnilo akceptaci a Gate M1 a bylo doručeno PR #83 jako
commit `d15cec3`; evidence je ve WORK_LOG.
`F-M4-AUTONOMY-01` byla 23. 10. 2026 akceptována na úrovni PoC validated a
doručena PR #85 jako merge commit `7dce1c4`; evidence je ve WORK_LOG.
`F-M3-SEARCH-03` byla 24. 10. 2026 akceptována na úrovni PoC validated a
doručena PR #86 jako merge commit `6d12902`; evidence je ve WORK_LOG.
`F-M3-PUBLIC-SOURCE-READER-02` byla 24. 10. 2026 akceptována na úrovni PoC
validated a doručena PR #87 jako merge commit `023eae1`; evidence je ve
WORK_LOG. `F-M4-DYNAMIC-WORKFLOW-01` byla 24. 10. 2026 akceptována na úrovni
PoC validated a doručena PR #88 jako merge commit `5d74144`; evidence je ve
WORK_LOG. Navazující `F-M4-RESEARCH-WORKFLOW-01` byla po opravě fyzické regrese
25. 10. 2026 akceptována na úrovni PoC validated a její evidence je ve
WORK_LOG; doručena byla PR #89 jako squash commit `ba291f5`.

`OPS-NODE-MONITOR-01` byla 25. 10. 2026 akceptována na úrovni PoC validated a
doručena PR #90 jako merge commit `57009e2`; evidence je ve
[WORK_LOG](WORK_LOG.md). `OPS-WEB-CONCURRENCY-01` byla 25. 10. 2026
akceptována na úrovni PoC validated a doručena PR #91 jako merge commit
`25d065f`; evidence je ve WORK_LOG. `F-M3-MODEL-CATALOG-01` byla doručena PR
#92 jako merge commit `2da2628`; evidence je ve WORK_LOG.
`F-M3-ATLASCLOUD-01` byla 25. 10. 2026 akceptována na úrovni PoC validated a
doručena PR #93 jako merge commit `0405d14`; evidence je ve WORK_LOG.
Nezávislá infrastrukturní dávka `TEST-EXECUTION-01` byla doručena PR #94 jako
commit `b19d46a`; všechny čtyři CI shardy i souhrnný check uspěly a evidence je ve
WORK_LOG. Implementovaný rozsah `UX-BACKEND-MODEL-01` byl doručen PR #96 a
#97 a jeho skutečný stav je ve WORK_LOG. Navazující serverový pinning,
revalidace, agregace aliasů a fyzická akceptace `UX-BACKEND-MODEL-02` dosáhly
26. 10. 2026 úrovně PoC validated a byly doručeny PR #98. Vizualizace
`DEV-ROADMAP-GRAPH-01` byla doručena PR #99 a obecný plánovací graf PR #100.
`F-M5-CHAT-HISTORY-01` byla po fyzické akceptaci doručena PR #101 jako merge
commit `8c08be2`; evidence je ve WORK_LOG. Navazující
`F-M5-SYNC-CONTROLS-01` byla doručena PR #102 jako merge commit `64a7dac`;
evidence je ve WORK_LOG. `COMP-01` byla doručena PR #103 jako merge commit
`b104843`; evidence je ve WORK_LOG. `COMP-02` byla doručena PR #104 jako
commit `507c232`; evidence je ve WORK_LOG a backlog ji nedrží jako druhý
stavový záznam.

Práce na `COMP-03` byla rozhodnutím uživatele 27. 10. 2026 přerušena:
Julia authoring se nemá dokončovat nad další jednorázovou textovou plochou.
`DOC-PATTERN-CATALOG-01` už implementovala sdílený raw editor a Julia adaptér
a byla doručena PR #107 jako squash commit `ac4281a`; její akceptovaná evidence
je ve WORK_LOG. `PLAN-TASK-EDITOR-01` zahrnula souborový kontrakt
`PLAN-FILE-HIERARCHY-01` i úplnou task coverage katalogu a byla doručena PR
#108 jako squash commit `50284d1`. `DOC-PATTERN-LIBRARY-01` byla doručena PR
#109 jako squash commit `ab09744`. Navazující ad-hoc dávka
`PLAN-ROADMAP-MILESTONE-VIEW-01` je feature-akceptovaná a její doručení čeká v
TODO. Poté zůstávají podle uživatelem aktualizovaného pořadí připravené
`COMP-03`, `DEV-IDE-TODO-01` a `DEV-01`.
Každá položka
zůstává samostatnou feature dávkou a vlastním PR; nevzniká společná větev ani
stacked PR bez dalšího výslovného rozhodnutí.

- [ ] [planned] **COMP-03 — Workspace řízení Julia výpočtu (cílová úroveň:
  PoC validated; větev `feature/comp-03-julia-workspace`).** Nad doručeným
  `COMP-02` zpřístupnit v otevřeném projektu první řízený výpočet bez druhého
  runneru nebo zápisové cesty. Workspace načte pouze validovanou verzovanou
  `fpw-julia-computation-v1` definici z aktuálního Git commitu, vykreslí její
  typované parametry a přesný preview s revizí, vstupy, privacy, runtime a
  limity. Samostatné potvrzení spustí existující Julia journal; UI po restartu
  zobrazí `prepared/running/current/stale/failed/cancelled/unknown`, dovolí
  bezpečný cancel/reconcile a náhled deklarovaných výstupů. Teprve další
  explicitní potvrzení publikuje jeden vybraný výstup přes existující
  `Workspace` operaci s provenance. Otevření projektu, status ani změna
  parametrů nic nespouštějí; local-only a RBAC se znovu ověří před dispatch i
  publikací. Rozsah zahrnuje shared desktop/web UI a fyzický průchod na
  podporovaném ARM64 runtime. Uživatelské rozšíření na téže větvi přidává
  editor Julia modelu pod Nástroje. Rozpracovaná větev zůstává zachovaná a po
  doručení `DOC-PATTERN-CATALOG-01` lze práci i fyzickou akceptaci obnovit;
  `COMP-03` použije jeho widget a Julia adaptér bez paralelní jednorázové
  textové plochy. Mimo rozsah zůstává Pluto/Jupyter, automatický scheduler,
  síťové/GPU výpočty a instalace balíčků.

## Zjištěné mezery a navazující ověření

- [ ] [planned] **F-M5-EXTERNAL-EXPORT-01 — externí datový balíček a styčný
  uživatel (cílová úroveň: designed → implemented → PoC validated).** Ruční
  oznámení existence projektu není datový export. Navrhnout sestavený balíček
  bez vlastní historie, nejvýše s patchi z exportní větve, který styčný
  uživatel výslovně vytvoří a odešle. Protistrana si historii sestaví
  nezávisle; přímý a souborový přenos zůstávají rovnocenné kanály do pozdějšího
  rozhodnutí o spojení. **Odloženo rozhodnutím uživatele 23. 10. 2026:** tato
  funkčnost aktuálně není potřeba a nemá se aktivovat bez nového požadavku.

- [ ] [planned] **UX-FACELIFT-02 — budoucí doladění zbývajících stránek
  (cílová úroveň: designed → implemented → PoC validated).** Uživatel po
  akceptaci UX-FACELIFT-01 výslovně odložil obecné další kolo faceliftu.
  Konkrétní řez backendů/modelů byl dokončen dávkami `UX-BACKEND-MODEL-01/02`;
  tato položka drží pouze zbytek dosud nevybraných stránek. Před jejich
  aktivací znovu vygenerovat A4 inventuru ze skutečného
  sdíleného UI, uživatelsky vybrat jeden ucelený reviewovatelný řez a neměnit
  již přijaté vzory bez konkrétní potřeby. Akceptace zachová
  mobilní/klávesnicovou paritu, RBAC, privacy, potvrzení a recovery a bude
  zahrnovat fyzický průchod právě upravených stránek.

- [ ] **[planned] V-01 — Regresní test pro validátor CLI.** ADR 0002 zaznamenává ruční smoke test exit 0/1; CLI zatím nemá vlastní automatický test. Doplnit platnou projekci, osiřelý sidecar, chybějící cestu a jasně vymezit, že se nekontroluje project.json.
- [ ] **[planned] V-06 — Produkční ochrany před nasazením.** Statické kontroly cest nejsou ochrana před závodícími FS změnami; současný zámek vyžaduje kooperující procesy. Zvlášť prověřit práva existujícího stavového adresáře, cizí Git konfigurace/filtry, povolené transporty a čtení při pending stavu. Nezaměňovat test pádu procesu za výpadek napájení ani host testy za podporu Windows.
- [ ] [planned] **V-07 — Provozní životní cyklus operation receipts (cílová úroveň: implemented).** Před produkčním balením určit retenci dokončených záznamů a bezpečný úklid osiřelých staging adresářů/commit objektů po pádu uvnitř přípravy kandidáta. Pending journal a kandidátní commit se nesmějí odstranit. Doplnit testy přerušení Git podprocesů a postup řešení jejich zbylých lock souborů; současné checkpointy leží mezi voláními. Zahrnout uzlové creation receipts a osiřelé staging složky M1-02; konfliktní pending vytvoření potřebuje explicitní bezpečné zrušení/řešení, které zatím nemá UI.
- [ ] [planned] **V-08-ID — Zbývající lifecycle identity/configurace (cílová úroveň: implemented).** Ověření při otevření je M1-01; vytvoření, registrace existujícího projektu a oprava jeho cesty jsou pokryté M1-02/F-M1-PROJECT-LOCATION-01. Zbývá migrace budoucích verzí konfigurace a vazba lokální identity na credential lifecycle. Projektové změny dále vést přes Workspace; index artefaktů není autoritou projektové konfigurace.
- [ ] [planned] **V-09 — Produkční Git transport a credentials (cílová úroveň: PoC validated).** Nad výchozím Git CLI ověřit TLS certifikáty, SSH host keys, zvolený credential store/helper, odmítnutí odvolaných credentials, timeout/cancel a restart přenosu. Loopback HTTP Basic test M0-03 ověřuje správné/chybné credentials, nikoli bezpečný internetový transport nebo federované RBAC. Vazba na V-06, cílové balení a M5.
- [ ] **[planned] R-01 — Posoudit zdrojové komponenty pro reuse (cílová úroveň: designed).** Před převzetím ověřit původ/licenci souborů, úplné závislosti, testy a kompatibilitu. Lokální inventura a její zbývající rozsah patří výhradně do volitelného soukromého katalogu; veřejné kandidáty evidovat v REUSE_CATALOG až po ověření veřejné dostupnosti.

- [ ] [planned] **V-10 — Integrace lokálního API (cílová úroveň: PoC validated).** Qt/WebEngine, same-origin UI a token v nativním interceptoru jsou ověřeny M0-06a. Zbývá lifecycle po násilném pádu, případný úklid Unix socketů a bezpečné vykreslení nedůvěryhodných artefaktů. Před persistentními mutacemi v M1 definovat klientské operation ID/retry/receipt podle ADR 0003, limity souběhu a celkový deadline requestu. Protokolový čítač ADR 0006 toto neprokazuje. M1-02 uzavírá pouze nativní vytváření: operation ID/receipt, jeden worker, neblokující uzlový zámek, deadline a recovery dle ADR 0015. M1-03 přidává nativní editor dle ADR 0016: stabilní operation ID/digest/receipt, kontrolu výchozího HEAD, neblokující zámek, recovery při otevření editoru a textové zobrazení nedůvěryhodného obsahu. Obecné mutující HTTP API zůstává neimplementované a pro tento nativní vstup není potřeba.

## Strategický zásobník — M2 až M4 (není připravená dávka)

Přeneseno z původní sekce 19 roadmapy. Široké M2 a M3/M4 se před implementací rozdělí na feature dávky s vlastní větví a PR; zachová se původ a návaznosti. Karty výše odkazují na tento strategický rozsah, neprohlašují celý milník za jednu feature.

- [ ] **[planned] M2 — Lokální AI:** Ollama adapter, auto-summary/description a Context Builder PoC dle ADR 0008: manifest přesných bajtů, revalidace před odesláním, zákaz implicitního fallbacku a recovery unknown běhů.
- [ ] **[planned] M3/M4 — Role a backendy:** implementovat Role/Backend modely a testy autorizace/execution boundaries dle ADR 0008 a následné předávání artefaktů mezi rolemi.

## Vlastní rozvoj produktu a coding agenti — navazuje na M6

- [ ] [planned] **PLAN-ROADMAP-TASK-VIEW-01 — další vizuální úroveň roadmapy
  (cílová úroveň: designed).** Po uživatelském zhodnocení milestone/batch
  pohledu určit způsob zobrazení task úrovně bez změny autority souborového
  plánu. Neaktivovat před rozhodnutím o požadované podobě a rozsahu; nejde o
  podmínku doručení `PLAN-ROADMAP-MILESTONE-VIEW-01`.

- [ ] [planned] **DEV-IDE-TODO-01 — VS Code/VSCodium jako zdroj TODO (cílová úroveň: PoC validated).** Po `PLAN-TASK-GRAPH-01` dodat malé rozšíření pro společný podporovaný průnik obou IDE, které zpřístupní explicitně vybraný workspace TODO zdroj a jeho revizi. První řez je read-only zdroj/importní preview bez spouštění coding agenta a bez zápisu mimo standardní Workspace lifecycle; plný handoff zůstává v DEV-02 a DEV-03.
- [ ] [planned] **DEV-01 — Roadmapa jako projektová data a export úkolů (cílová úroveň: implemented).** Po `PLAN-TASK-GRAPH-01` převést uživatelem vybraný rozsah roadmapy do verzovaných entit požadavků, milníků, feature dávek, rozhodnutí, rizik, závislostí a úkolů bez vytvoření druhého autoritativního plánu. Akceptace: stabilní ID a provenance na zdrojovou revizi, opakovaný import bez duplikace, konflikt ruční a zdrojové změny, odstraněný/přejmenovaný bod a export Markdown TODO i strojově čitelného task balíčku se scope, dependencies a acceptance. Export nemění stav zdrojového úkolu; interní roadmapa použije stejný obecný plánovací kontrakt jako ostatní projekty.
- [ ] [planned] **DEV-02 — Handoff kontrakt pro coding agenty (cílová úroveň: PoC validated).** Definovat provider-neutral request, run record a result receipt pro implementačního agenta. Akceptace: task ID, repozitář/výchozí commit/větev, explicitní Context Manifest a povolené operace, testovací kontrakt, oddělení reportu od ověření, `unknown` přerušený běh, stale HEAD, retry bez duplicitní externí akce a žádný automatický commit/push/PR nebo dokončení úkolu bez příslušného oprávnění a akceptace.
- [ ] [planned] **DEV-03 — Rozšíření pro Microsoft Visual Studio Code a VSCodium (cílová úroveň: PoC validated).** Nad DEV-01/DEV-02 vytvořit IDE rozšíření používající jejich společný podporovaný Extension API průnik a autorizované lokální workspace API. Akceptace: otevření odpovídajícího workspace projektu/repozitáře, zobrazení roadmapových entit a úkolů, export vybraného task balíčku, spuštění nakonfigurovaného agent adaptéru, náhled/import výsledku a jasné stavy stale/unknown/unauthorized. Rozšíření nesmí zapisovat projektová data mimo Workspace lifecycle. Ověřit instalaci v obou IDE, podporované distribuční kanály a offline balíček bez tvrzení o univerzální kompatibilitě všech VS Code rozšíření.
- [ ] [planned] **DEV-04 — Codex adaptér pro implementaci (cílová úroveň: PoC validated).** Nad DEV-02/DEV-03 ověřit v době implementace podporované oficiální rozhraní Codexu a připojit je jako vyměnitelný coding-agent adaptér, nikoli jako hostitele pluginu. Akceptace: export jednoho schváleného úkolu z IDE, implementace v izolované feature větvi, návrat diffu, změněných souborů a skutečných testů, vazba na původní task/revizi, odmítnutí nepovoleného kontextu/akce a lidské rozhodnutí před aktualizací autoritativního plánu. První end-to-end kandidát může být vlastní repozitář workspace, ale bez jakékoli privilegované výjimky.

## Externí vztahy a disclosure — navazující strategický backlog

Rozsah a gates rozšíření drží sekce 22 master roadmapy. Jde o plánovanou práci, která nemění pořadí nejbližších dávek ani zpětně neotevírá uzavřený Gate M0. Původní patch označoval návrhový kontrakt jako M0-10; po uzavření M0 je zachován pod ID ER-00. Před použitím protokolových knihoven nebo rendereru provést reuse, licenční a capability review v `REUSE_CATALOG.md`; nevytvářet nový mail server.

- [ ] **[planned] ER-00 — Kontrakt externích vztahů, komunikace a disclosure (cílová úroveň: designed).**
  Uzavřít entity, identity příjemců, přesnou revizi a rozsah předaného obsahu, oddělení privacy, prezentační klasifikace a evidence a hranice komunikačního úložiště. Doplnit verzovaný DecisionScenario/ScenarioNode, sdílenou BackupLibrary, vazby slidu na otázky/doplňky a přesný návratový bod relace; navigace, očekávaná odpověď, potvrzený skutečný výrok a DisclosureEvent zůstávají oddělené. Rozhodnout veřejný a soukromý katalog, per-project a cross-repo vztahy, append-only opravy, idempotenci, retenci a obnovu neurčitého externího účinku. Zaznamenat autoritu mail/DAV dat, outboxu a projektových importů; hesla a tokeny zůstávají mimo Git.
  Akceptace: návrhové scénáře částečného sdílení, nové revize, stejného příjmení či adresy, změny organizace, nového účastníka, sdíleného backupu ve více větvích, jiné/odmítnuté odpovědi, přerušení uprostřed odhalení slidu, odpojeného audience okna, pádu po SMTP přijetí a neúplné federované historie. Výstup zahrne migrační hranici vůči striktnímu schématu v1; samotný text roadmapy není důkaz implementace.

- [ ] **[planned] ER-01 — Verze schémat a projekce registrů (cílová úroveň: implemented).**
  Po ER-00 zavést vybraná schémata a migrace bez tichého rozvolnění v1. Rozšířit obnovitelný index, API a validaci oprávněných vztahů; zachovat jedinou zápisovou cestu Workspace/Journal/Git/index.
  Akceptace: starý projekt zůstává čitelný, nepodporovaná verze je odmítnuta, migrovaný projekt projde obnovou indexu a neplatný lokální nebo cross-repo vztah nepřinese falešná data. Návaznost V-03/V-04.

- [ ] **[planned] ER-02 — Partneři, adresář a schůzky (cílová úroveň: implemented).**
  Po ER-01 dodat CRUD osob, organizací a vztahů, kontaktní pohled, časové role a interní schůzky s agendou, skutečnými účastníky a follow-up úkoly. Soukromý katalog sdílet jen explicitně.
  Akceptace: dvě osoby se stejným jménem nebo sdílenou adresou nesplynou bez potvrzení; změna zaměstnavatele nepřenese historii; jiný projekt neuvidí soukromé poznámky a pozvánka neexportuje interní agendu automaticky.

- [ ] **[planned] ER-03 — Disclosure Registry a snapshoty (cílová úroveň: implemented).**
  Po ER-01/ER-02 dodat ruční inbound/outbound události, opravy a projekci podle příjemce; přesný payload a hash, úplné source refs a scope. Navrhnout retenci revizí a navázat existující IP publikační registr pouze referencí.
  Akceptace: summary neoznačí celý zdroj za předaný; přejmenování či nový HEAD nezmění starou revizi; export bez adresáta není doručení; opakovaný operation ID neduplikuje fakt a opravná událost zachová původní záznam. Projít crash boundaries dle DATA_MODEL.

- [ ] **[planned] ER-04 — Offline Disclosure Presenter MVP (cílová úroveň: PoC validated, potom implemented).**
  Po ER-02/ER-03 dodat modul přípravy verzovaného hlavního decku z projektových artefaktů a médií, notes, kroky postupného odhalení, privátní preview, editor rozhodovacího scénáře, kontextové doplňky, globální backup knihovnu, větvenou navigaci s řízeným přerušením/návratem, audience-only renderer, zkušební režim a trvalou relaci. Prezentační akce oddělit od fyzického vstupu a vedle klávesnice dodat volitelný gamepad adaptér s lokálním mapováním. Green/orange/red váží 0/0,5/1; expozici, count/time/depth upozornění, navigaci a klasifikaci vést odděleně od oprávnění a Disclosure Registry. Bez závislosti na LLM nebo mail klientu.
  Akceptace: scénář s několika odpověďmi, fallbackem, dvěma úrovněmi zanoření a jedním backupem použitým ve více větvích; průchod bez dalšího slidu, promítnutí backupu a správný návrat z hlubší větve i k přerušenému kroku. Preview, focus, změna větve, hledání, zrušené promítnutí a nácvik mají +0 a neuniknou publiku; orange → green → red dává 1,5, stejný payload/revize/rozsah pro stejné publikum se v relaci znovu neboduje a ústní sdělení vznikne jen potvrzením. Ověřit novou revizi, chybějící nebo změněný zdroj decku, odloženou otázku, zaznamenanou skutečnou odpověď, restart uprostřed větve, unknown audience výsledek, odpojenou obrazovku, autorizační zákaz navzdory override, neutral/blackout, klávesnicové i gamepadové ovládání a safe export bez scénáře/notes/skrytých dat. Gamepad otestovat pro připojení za běhu, odpojení, ztrátu focusu, neznámé mapování, držené či opakované tlačítko a pokus odhalit obsah bez požadovaného potvrzení; porucha ovladače nesmí automaticky změnit audience výstup a klávesnice zůstává funkční fallback. Celé základní ovládání funguje offline a bez LLM; před schůzkou ověřit reálné dvouobrazovkové nastavení Linux desktopu a fyzický podporovaný gamepad.

- [ ] **[planned] ER-05 — Plnohodnotný mail klient (cílová úroveň: implemented).**
  Po registry a policy základu vybrat a ověřit IMAP/SMTP adaptér pro první účty, včetně TLS a OAuth2 podle poskytovatele; dodat složky, threading a hledání, přílohy, compose/reply/forward, offline koncepty a durable outbox. Import do projektu je oddělen od synchronizace schránky.
  Akceptace: změna UIDVALIDITY, ztráta spojení, expirovaný token a částečné odmítnutí příjemců nevedou ke ztrátě či automatické duplicitní zásilce. Ověřit pád po SMTP přijetí se stavem unknown, obnovu fronty, Bcc/reply-all, citovaný citlivý obsah, vazbu přesných příloh na ER-03 a sandbox HTML. Nezvyšovat potichu limity příloh.

- [ ] **[planned] ER-06 — Kalendář a synchronizovaný adresář (cílová úroveň: implemented).**
  Po ER-02 a relevantní transportní a policy vrstvě přidat CalDAV kalendáře, pozvánky a odpovědi a CardDAV projekci partnerů; určit mapování polí, UID a verzí a zdroj pravdy při oboustranné editaci. Provider-specific adaptér až podle ověřené potřeby.
  Akceptace: časová pásma, výjimka opakování, změna nebo odvolání pozvánky, ETag konflikt, smazání a offline návrat jsou deterministické; soukromé poznámky nevstoupí do vzdáleného kalendáře nebo kontaktu. Příchozí pozvánka se nepotvrdí bez povolení.

- [ ] **[planned] ER-07 — Federace vztahů a evidence (cílová úroveň: PoC validated, potom implemented).**
  Navázat na M5 a ER-03. Ověřit autorizované projekce partnerů a událostí bez přenosu celé schránky, secretů nebo citlivé historie zdrojového repozitáře. Zpracovat offline události podle stabilních ID a provenance; nepředstírat globální pořadí jen podle hodin uzlu.
  Akceptace: dvě offline relace neztratí událost; shodné ID s rozdílným obsahem vyvolá konflikt; peer bez přístupu ke zdroji obdrží jen povolenou projekci a nedostupná historie zůstane neověřená. Před implementací uzavřít přenosové hranice ve FEDERATION/ADR.

- [ ] **[planned] ER-08 — Kontext partnera a volitelný LLM poradce (cílová úroveň: implemented).**
  Po ER-03 navázat oprávněné vztahy na M6 a volitelné modely M2–M4: návrh klasifikace, rozdíl revizí, příprava schůzky a otázky nebo reciprocita zadávané uživatelem. Používat Context Manifest, zdrojové reference a lidské schválení.
  Akceptace: nepovolený zdroj ani cizí projekt nevstoupí do kontextu; prompt injection v mailu nevyvolá odeslání; reciprocita sama neodblokuje red slide a nedostupnost lokálního LLM nezpůsobí externí fallback. Základní Presenter a registry fungují i bez modelu.

## Vzdálenější strategické požadavky (před aktivací rozdělit na feature dávky)

- [ ] [planned] **UX-FEDERATION-02-B — úplný lifecycle identity, účtů, skupin
  a autentizace (cílová úroveň: designed).** Dokončit lifecycle vytvoření,
  deaktivace, obnovy a zániku identity, plnohodnotný webový login, MFA, vazbu
  desktopové instance na OS uživatele a správu user groups. Zachovat
  kvalifikované identity, zákaz federace credentials/session a strop lokálního
  účtu `node-admin` podle ADR 0037. Nejde o podmínku osobního synchronizačního
  řezu `F-M5-PERSONAL-SYNC-01`.

- [ ] [planned] **UX-FEDERATION-02-C — úplný jednotný policy model (cílová
  úroveň: designed).** Definovat verzované strojové schéma, precedence,
  dědičnost, vysvětlitelnost a oddělené akce pro ACL, export, příjem, delegaci a
  replikaci. Neznámá nebo konfliktní policy zůstává fail-closed a `local-only`
  nikdy neopustí uzel.

- [ ] [planned] **UX-FEDERATION-02-D — automatická federace spravovaných
  skupin (cílová úroveň: designed).** Dokončit podepsané členství, discovery,
  desired state, replication sets, offline outbox/inbox, revokaci, konflikty,
  mazání, úplnost historie a audit bez předpokladu globální transakce nebo
  spolehlivých hodin.

- [ ] [planned] **UX-FEDERATION-02-E — threat model, migrace a implementační
  rozpad plné federace (cílová úroveň: designed).** Pokrýt bootstrap,
  rotaci/ztrátu klíčů, obnovu účtu a MFA, kompromitovaný uzel, stale členství,
  rolling upgrade, metadata leakage, kvóty a nouzové zastavení; poté rozsah
  rozdělit na samostatné implementační dávky.

- [ ] [planned] **AUTH-CENTRAL-01 — centrální autorita identity a offline
  projekce (cílová úroveň: designed → PoC validated).** Autorita A vydává
  stabilní kvalifikované identity a časově omezené podepsané claims. Oddělit
  adresář/provisioning, autentizační assertions a lifecycle WebAuthn/TOTP.
  Centrální registr je nutnou autoritou pro `network-group-admin` a
  `network-admin`; uzly nereplikují hesla, digesty, MFA secrets ani session.

- [ ] [planned] **F-M5-TRUST-01 — Profily federace a branch policy (cílová
  úroveň: designed).** Rozšířit peer registry o capability profil `unspecified` /
  `same-company-same-team` / `same-company` / `trusted-partner` /
  `holding-partner` / `partner`, oddělený od `pending` / `approved` / `revoked`.
  Profily nejsou pořadí důvěry: první může federovat uživatele a jejich projektové
  role; `same-company` jen data a vzdálené identity pro provenance/audit bez
  převzetí účtů či rolí; `trusted-partner` vybraná data konkrétním příjemcům;
  `holding-partner` vybraná data také celé ověřené společnosti; `partner` jen
  chat a uživatelem explicitně odeslaný či sdílený obsah.

  Způsob nasazení serveru zachovat jako auditní/bootstrap provenance, nikoli
  jako capability strop. Server instalovaný desktopem lze explicitně převést na
  obecný víceuživatelský uzel. Jeden fyzický desktop je jeden uzel se systémovou
  node službou a oddělenými OS uživateli. Identity jsou kvalifikované autoritou,
  například `U1@A`; vzdálená projekce nepřebírá autoritu nad credentials.

  Zavést role `network-admin`, `network-group-admin`, `node-admin`,
  `group-admin`, `project-admin` a `user` podle ADR 0037. Správní role samy
  nezpřístupňují projektová data. Lokální účet může být nejvýše `node-admin`;
  role `network-group-admin` a `network-admin` musí vydat centrální registr.
  Ostrovní federaci bez registru řídí `node-admin` jednotlivých uzlů, každý jen
  za vlastní uzel. Oddělit network groups, user groups, replication sets a
  project ACL. Automatická replikace začne až vědomým zařazením projektu do
  replication setu; první režim je jeden primární zapisující uzel a automatické
  read-only repliky.

  Pro `trusted-partner` a `holding-partner` určit aktivního místního styčného
  uživatele přijímajícího uzlu, který auditovatelně přiděluje práva k převzatým
  datům místním uživatelům pouze jako podmnožinu origin ACL, privacy, akcí a
  exportních omezení. Uzavřít verzovanou policy pro project UUID, ref/branch,
  mapované uživatele nebo organizačního příjemce, styčného uživatele, povolené
  privacy a akce včetně `export`.

  Akceptace: žádný profil, správní role, společný původ ani přijetí dat samo
  neudělí přístup nebo nespustí replikaci; všechny vrstvy schválí přesný scope.
  Podepsaná offline projekce má výchozí platnost 8 hodin a předem schválené
  maximum 24 hodin; vypršelá autorita si ji během výpadku neprodlouží. Ztráta,
  rotace a obnova identity mají explicitní fail-closed lifecycle. Organizační
  grant používá ověřené, časově vymezené a verzované členství; změna, downgrade
  nebo revokace má nové ID/verzi. Výměna či deaktivace styčného uživatele
  zachová audit, zabrání novým grantům a
  dovolí bezpečné odebrání existujících; pokus styčného uživatele rozšířit origin
  práva se odmítne; neznámá policy fail-closed; credentials, session, vzdálené
  přihlášení a `local-only` jsou vždy odmítnuty.

- [ ] [planned] **F-M5-TRANSFER-01 — Privacy-aware přenos celé historie (cílová úroveň: PoC validated).** Nahradit public-only omezení prvního bundle přenosu autorizací všech objektů dosažitelných z vybraného refu podle F-M5-TRUST-01 a portable ACL ADR 0021. Jde o přímou návaznost na odmítnutí `project` entity v historickém commitu oznámené 2026-09-17. Akceptace: `project` data projdou pouze s oboustranně platným branch/project grantem a mapováním; confidential vyžaduje explicitní policy; local-only, nepokrytý předek, skrytý další ref, změněný HEAD, revokace a neúplný manifest se odmítnou před odesláním; příjem znovu ověří stejný obsah a práva.

- [ ] [planned] **F-M5-CHAT-01 — Federovaná lidská vlákna a durable delivery (cílová úroveň: PoC validated).** Přímý chat a explicitně založené skupinové vlákno mezi mapovanými uživateli schválených peerů; výchozí klasifikace `brainstorming`. Stabilní message/thread ID, kvalifikovaný autor, podpis/provenance, durable outbox/inbox, deduplikace a pending/sent/delivered/failed/unknown bez globálního pořadí odvozeného pouze z hodin. Profil `partner` nesmí chat využít k background synchronizaci ani procházení projektu; mimo samotné zprávy projde jen obsah explicitně přiložený nebo nasdílený uživatelem. Akceptace: offline obě strany, retry/lost response, duplicita, změněný mapping, downgrade profilu, revokace, restart na každé persistentní hranici a oddělení vláken/projektů; chat funguje bez LLM.

- [ ] [planned] **F-M5-CHAT-02 — Otisk, shrnutí a publikace výsledku chatu (cílová úroveň: PoC validated).** Z vybraných zpráv nabídnout preview a explicitní vytvoření úplného/rozdílového otisku, shrnutí, zadání nebo jiného schématem podporovaného artefaktu. Volitelné LLM zpracování používá Context Manifest a povolenou execution boundary. Akceptace: lidské potvrzení cílového projektu/typu/obsahu/privacy; provenance na přesná thread/message ID a vstupy; nejpřísnější privacy a průnik práv; stale/revoked/změněné zprávy, expected HEAD, retry a pád před/po CAS; editace artefaktu nepřepisuje chat.

- [ ] [planned] **F-M5-CHAT-XMPP-01 — Oddělený interní a veřejný XMPP adaptér
  (cílová úroveň: designed → PoC validated).** Interní XMPP smí obsloužit jen
  bilaterální vztahy `same-company-same-team` a `same-company`. Veřejný
  federovaný XMPP je oddělený vnější kanál s vlastní doménou, účty, credentials,
  úložištěm, moderací a disclosure policy; není mezi nimi implicitní bridge.
  Před PoC uzavřít identity/JID mapping, durable delivery a `unknown`, MUC,
  přílohy, DNS/TLS, server-to-server interoperabilitu, E2EE, retenci, anti-spam
  a explicitní import/přeposlání s provenance/privacy. Vnější zpráva nesmí
  automaticky získat projektový kontext ani spustit LLM, plugin či nástroj.

- [ ] [planned] **M5 — Federovaná publikace (cílová úroveň: PoC validated).** Implementovat izolovaný příjem, autorizaci celého přenášeného obsahu včetně historie, validaci kandidáta a CAS/recovery dle ADR 0008. Ověřit změnu HEAD po lidském řešení, neplatný fast-forward/merge, revokaci a odmítnutí přenosu local-only historie; zachovat konfliktní rodiče. Dílčí pořadí: F-M5-TRUST-01 → F-M5-TRANSFER-01 → F-M5-CHAT-01 → F-M5-CHAT-02.

## Import externích dat — navazuje na aplikační import M1

Strategický rozsah drží sekce 3C master roadmapy; tyto úkoly nemění prioritu desktopového PoC.

- [ ] [planned] **IMP-03 — Import exportů konverzací (cílová úroveň: implemented).** Získat uživatelem schválené anonymizované vzorky ChatGPT a Gemini/Takeout, ověřit skutečnou strukturu a vytvořit lokální import s náhledem. Akceptace: role/pořadí/větvení podle dostupnosti, chybějící metadata, přílohy, opakovaný import a poškozený archiv; omezit velikost i rozbalení archivu, odmítnout traversal/symlinky a nevykonávat importované HTML. Generační API není předpokládaným zdrojem historie webového účtu.
- [ ] [planned] **IMP-04 — Vstupní fronta a lokální LLM návrh zařazení (cílová úroveň: PoC validated).** Umožnit import bez aktivního projektu do soukromé lokální fronty a nad validovaným vstupem nabídnout návrh nuly, jednoho nebo více oprávněných cílových projektů. LLM je pouze lokální volitelný poradce; bez něj zůstává ruční zařazení. Akceptace: vysvětlení/confidence a navržená privacy, lidské potvrzení před prvním projektovým zápisem, nezařazení/odmítnutí, multi-project fan-out se samostatným stavem a idempotentním retry pro každý projekt, částečný úspěch bez tichého rollbacku commitů, pád před/po jednotlivých publikacích a žádný externí fallback pro `local-only`. Závisí na příslušném importéru, Workspace recovery a lokálním LLM/Context Manifest kontraktu.

## Read-only artefakty sdílené mezi projekty

- [ ] [planned] **XREF-01 — Připnuté meziprojektové reference artefaktů (cílová úroveň: PoC validated).** Navrhnout verzovaný referenční záznam a implementovat první rozsah mezi dvěma lokálně registrovanými projekty. Reference je read-only, identifikuje zdrojový projekt/repozitář, artifact ID, úplný commit a hash; není filesystemový symlink ani kopie bajtů. Akceptace: vytvoření a zobrazení připnuté revize, nabídka novější revize bez automatického přepnutí, opětovná kontrola oprávnění/privacy, offline cache se stale indikací, revokovaný/smazaný/nedostupný zdroj, explicitní fork s novým ID a provenance, zahrnutí do indexu/Context Manifestu pouze s autorizovanými přesnými bajty a recovery zápisu reference přes Workspace. Závisí na F-M1-SOURCE-02 a stabilní registraci projektů; vzdálené reference zůstávají pro M5 a identity cross-repo koordinovat s ER-00/ER-01.

## Periodický monitoring a reporting — navazuje na M6

Strategický rozsah drží sekce 23 master roadmapy. Jde o plánovanou schopnost a referenční task, nikoli běžící scheduler nebo schválení automatického publikování. Před aktivací rozdělit každý krok na jednu feature větev a jeden PR; externí zdroje a konkrétní provider adaptéry vyžadují capability, licenční a bezpečnostní review.

- [ ] [planned] **MON-00 — Reporting kontrakt a hranice (cílová úroveň: designed).** Uzavřít verze ReportingTask, Event, Source, Story, evidence/maturity hodnocení, ReportRun a vydaného ReportSnapshotu. Akceptace: oddělené `event_date`/`detected_at`/import, neznámé datum, append-only oprava, source versus tvrzení, late discovery, změna hodnoticí škály, privacy odvozeniny a migrace starší verze jsou jednoznačné; návrh popíše lokální autority, crash boundaries, retenci a co nikdy nepatří do projektového Gitu.
- [ ] [planned] **MON-01 — Ruční task, event/story registry a report snapshot (cílová úroveň: implemented).** Implementovat bez scheduleru a bez povinného LLM ruční založení tasku, události s více zdroji, explicitní deduplikaci/story vazbu a vydání připnutého Markdown reportu. Akceptace: opakované operation ID, konflikt editací, zrušená deduplikace, nový odporující zdroj, oprava vydaného reportu následníkem, obnova indexu a pády před/po Git CAS.
- [ ] [planned] **MON-02 — Bezpečný Source Collector (cílová úroveň: PoC validated).** Začít jedním ověřeným typem veřejného zdroje; allowlist, limity, licence/robots/podmínky přístupu, timeout, redirect, obsahový typ, velikost a prompt injection fail-closed. Akceptace: změněný/stažený zdroj, duplicita URL versus shodný obsah, rate limit, částečný download, neplatný certifikát, přihlášení, smazání a nedostupnost nepublikují falešnou událost; původní bajty/provenance se zachovají podle policy.
- [ ] [planned] **MON-03 — Extrakce, evidence a story tracking (cílová úroveň: PoC validated).** Nad Context Manifestem přidat volitelné role extractor/researcher/evidence evaluator; LLM pouze navrhuje entity, deduplikaci, maturity a story vazby. Akceptace: lidské/policy potvrzení významných tvrzení, marketing versus provoz, konfliktní zdroje, komunitní signál, chybějící primární důkaz, změna modelu/promptu a běh bez LLM; žádné automatické přepsání historie.
- [ ] [planned] **MON-04 — Idempotentní scheduler a run recovery (cílová úroveň: PoC validated).** Spouštět task podle timezone a typu periody se stabilním klíčem task+period+revision. Akceptace: DST, missed run/catch-up, dvojí worker, restart ve všech persistentních stavech, změna tasku uprostřed období, ruční rerun a stav externího účinku `unknown`; jeden běh nevytvoří dvě vydání a neúspěch neposune poslední úspěšný cutoff.
- [ ] [planned] **MON-05 — Týdenní, měsíční a výroční syntéza (cílová úroveň: implemented).** Generovat rozdílovou weekly noticku, samostatnou měsíční trendovou syntézu, kvartální rozšíření a výroční dokument z připnutých vstupů. Akceptace: nulová změna, pozdní stará událost, změna trendu, opravený zdroj, přesný cutoff, reprodukce, draft/review/publish, neúplný či nedostupný LLM bez implicitního fallbacku a bezpečný Markdown export.
- [ ] [planned] **MON-06 — Case studies, federované role a Humanoid Robotics Watch (cílová úroveň: PoC validated).** Zavést provenance vizualizace a referenční task s verzovanými benchmarky a periodami z roadmapy. Akceptace: realistický scénář versus výhled, syntetické označení, prompt/model/inputs, fyzická care safety hranice, lokální citlivý zdroj, vzdálený veřejný collector, revokace a částečný federovaný výsledek; nejméně dvě simulované po sobě jdoucí periody bez duplicitního vydání.
- [ ] [planned] **MON-07 — Doménové observační moduly: síť, mapy a satelitní snímky (cílová úroveň: designed → PoC validated).** Nad MON-00 až MON-04 definovat provider-neutral `ObservationSource` a jako první adaptovat schopnosti samostatně vyvíjeného RIPE Atlas Webcockpitu pro dlouhodobé síťové časové řady; mapové vrstvy a satelitní snímky ponechat jako samostatné následné adaptéry stejného kontraktu. Akceptace: capability discovery, stabilní source/observation ID, oddělený čas měření/pořízení, zveřejnění a importu, prostorový rozsah a jednotky, licence/retence/privacy, credential reference mimo Git, idempotentní pull i durable stav aktivního měření, rate limit a částečný výsledek, připnutí původních dat a odvozeniny s provenance. Síťový PoC projde dvěma periodami; výpadek probe/API se nesmí vydávat za výpadek cíle. Mapová projekce ani satelitní změnová detekce nesmí tvrdit kauzalitu bez potvrzené evidence.

## Podpůrné IP / release integrace — nepřebírají prioritu M0

Podrobnou administrativu, screening a crowdfundingové checklisty drží [IP roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>) a její registry. Níže jsou pouze konkrétní integrace do repozitáře; žádná publikační automatizace zatím neexistuje.

- [ ] [planned] **IP-01 — Release a citation metadata (cílová úroveň: implemented).** Před prvním publikačním releasem určit archiv a ověřené autory, licenci, repository URL a verzi; doplnit CITATION.cff a/nebo metadata zvoleného archivu. Akceptace: metadata odkazují na konkrétní disclosure, tag a commit, neobsahují vymyšlené identifikátory a projdou validací zvoleného formátu.
- [ ] [planned] **IP-02 — Archive/release workflow a DOI integrace (cílová úroveň: implemented).** Po určení archivu z IP-01 připravit kontrolu verzí a referencí, následně automatizaci podle sekce 29 IP roadmapy. Akceptace: kontrola odmítne nesoulad tag/commit/disclosure; případné DOI je propojeno obousměrně. Samotné vytvoření tohoto úkolu nepublikuje release ani DOI.
- [ ] [planned] **IP-03 — Propojit financovaný scope s produktovými milníky (cílová úroveň: designed).** Při přípravě kampaně přiřadit schválené balíčky ke stávajícím M1–M6 a určit zařazení Open WebUI integrace; odlišit hotové, financované a budoucí schopnosti. Akceptace: jeden konzistentní rozsah s rozpočtem a readiness review podle IP roadmapy, desktopový základ zůstává M1. Kampaň ani její spuštění tím nejsou schválené.

## Otevřená práce převzatá ze široké dávky M1 — 2026-09-14

Administrativní přesun při čištění TODO, nikoli uzavření či merge. Níže jsou autoritativní zbývající úkoly; jejich implementace a důkazy se zachovávají. Stav planned zde znamená odložené dokončení/ověření, nikoli chybějící již popsanou implementaci. Před aktivací je seskupit či rozdělit na jednu feature a jeden PR do develop podle pravidel AGENTS. Souhrnný M1 je strategický požadavek, ne feature dávka. U V-08/V-11 jsou již doložené části ve WORK_LOG; původní širší backlog položky dál evidují pouze jejich zbývající rozsah.

- [ ] **[planned] M1 — Aplikační základ:** vytvořit LXC development deployment, desktopový launcher/balení, persistentní identitu a úložiště uzlu; implementovat Project/Artifact služby a Git službu adaptací ověřených PoC. Po volbě stacku doplnit frontend, Markdown editor/viewer a Git history UI. Produkční integrace metadat/indexu zůstává otevřená, jejich PoC se neopakuje.

Tento převzatý souhrn M1 je zastřešující úkol; M1-05 níže je jeho konkrétní první krok. Zahrnuje zbývající požadavky sekce M1 roadmapy, včetně typů artefaktů, metadat, obnovy indexu po přejmenování/smazání, recovery zápisů a zachování původních bajtů importu. Hotové části souhrnu doložené ve WORK_LOG se znovu neimplementují. Další kroky rozepisuj zde podle ověřeného stavu; relevantní existující V-* položky v BACKLOG používej jako návaznosti, jejich doplnění dočasně zachyť níže.

Podmínka uzavření: dokončené a ověřené zbývající požadavky M1 i přijaté ad-hoc úkoly a doložené review Gate M1 (použitelný workspace bez LLM v LXC i desktopu). Případné zúžení dávky musí výslovně zachovat otevřený gate a odloženou práci; samotné dokončení M1-05 nestačí.

## Na řadě

- [ ] [planned] **M1-AH-15 — Durable journal odchozího Git přenosu (implemented, 2026-09-14; neověřeno).** Navazující otevřená recovery část M1-AH-14 po uživatelském potvrzení skutečného přenosu. Authoritative SQLite journal mimo projektový Git uchovává přesný bundle BLOB, source HEAD, digest, operation ID a identity/piny obou uzlů; není obnovitelným projektovým indexem. Publikace celé exportní dávky jednou SQLite transakcí s synchronous FULL před SSH. Retry/restart obnoví stejné bajty a ID, odmítá změněný zdroj/identity; dokončení se zaznamená až po vzdálené odpovědi. Chyba lokálního completion nezamlčí úspěšný vzdálený import. Native formulář nabídne pokračování nedokončeného přenosu. Příjemní staging recovery před publikací zůstává omezené dle M1-AH-14. Podmínka dokončení: SQLite/crash/restart/lost-response/foreign-source testy, GUI, celé testy a cílová akceptace; testy ani kontroly nebyly spuštěny.

Uživatelská akceptace M1-AH-14: projekt se skutečně přenesl podle potvrzení uživatele. Historická práva navrhuje uživatel řídit na úrovni větví, ne jednotlivých commitů. Návrh zatím není implementované oprávnění: branch policy musí autorizovat všechny dosažitelné historické objekty a nesmí povolit únik local-only přes společné předky/merge/jiný ref. Public-only gate zůstává beze změny; návrh branch ACL patří k následnému rozhodnutí M5.

- [ ] [planned] **M1-AH-14 — První nativní Git přenos veřejného projektu (implemented, 2026-09-14; neověřeno).** Explicitní požadavek uživatele přenést projekt nativním Gitem bez hlavního workflow v hookách. Native dialog potvrzuje jednosměrný desktop→LXC přenos celé vybrané historie. Git fetch do izolovaného exportu a bundle jediné větve, příjem do izolované složky, incoming ref, sémantická validace všech dosažitelných commitů a prvotní registrace přes ProjectCreation journal. UUID/historie/provenance beze změny. Bez merge či aktualizace již existujícího cíle. Ochrana historie je zatím fail-closed: pouze public entity a project.json/artifacts/registries ve všech commitech, max 500 commitů/64 MiB bundle; project/confidential/local-only i historicky se odmítají bez reklasifikace. Historické ACL pro neveřejná data nejsou implementované; nejde o plnou synchronizaci M5. Reuse Git CLI se zakázanými hooky, validátorů, registrace/recovery a jediného SSH procesu; credentials/node/journal/index mimo přenos. Transfer intent/digest a staging mimo projektový Git umožňují identifikaci operace; pád před publikací se může zastavit k ruční obnově, po publikaci lze obnovit registraci. Podmínka dokončení: export/import a fail-closed testy, UUID/dirty/foreign/retry/SIGKILL/registration recovery, Qt, celé testy a cílová akceptace. Testy ani kontroly nebyly spuštěny.

Uživatelská akceptace M1-AH-13: oba směry desktop↔LXC prošly TLS a podepsaným identity probe podle vloženého výpisu. Jde o cílové potvrzení uživatele, nikoli agentní testy ani důkaz datové synchronizace.

- [ ] [planned] **M1-AH-13 — Obousměrný test desktop/LXC a veřejná CA (implemented, 2026-09-14; neověřeno).** Navazující úkol po uživatelském potvrzení HTTPS backendu a podepsaného testu desktop→LXC. Native tlačítko potvrzuje SSH přenos pouze veřejné desktopové CA a CAS aktualizaci endpointu již schváleného desktopového peeru na LXC. Jeden SSH proces; kontrola původních node ID/pinů obou uzlů, poté podepsaný test LXC→desktop s nonce a TLS/SAN. Identity/práva/credentials/firewall beze změny. Reuse NetworkBackend, probe, SSHSession a Administration; žádný reset webu. Pád mezi CA/endpoint/testem ponechá částečný stav, opakování jej může dokončit; nejsou jednou distribuovanou transakcí. Podmínka dokončení: Qt/SSH/TLS a mismatch/přerušení/CAS testy, celé testy a cílová obousměrná akceptace. Žádné nové testy ani kontroly nebyly spuštěny; synchronizace dat zůstává M5.

Uživatelský důkaz M1-AH-09/10/11/12: aktualizace LXC dokončena se zachováním identity/credentials, detekována IP 192.168.100.247, přenesena veřejná CA a zapamatován uzel. Desktopový backend hlásí https://192.168.100.192:8443 a podepsaný test desktop→LXC prošel. Jde o výpisy uživatele, ne nové agentní testy; opačný směr nebyl tímto doložen.

- [ ] [planned] **M1-AH-12 — Desktop HTTPS backend a podepsaný test spojení (implemented, 2026-09-14; neověřeno).** Souhlas uživatele s navazujícím síťovým krokem. Nativní nastavení bind/port/LAN/TLS, opt-in backend ve stejném desktopovém procesu a identitě, uložené nastavení a automatická aktivní adresa v deploy průvodci. Reuse WebServer TLS/LAN, Administration writer lock a Ed25519; nový nonce-bound probe neautentizuje účty a nezpřístupňuje projekty ani synchronizaci. LXC web doplňuje stejný podepsaný endpoint. Native test kontroluje CA/SAN, challenge/node ID/endpoint, schválený pin a podpis; rozlišuje TLS, HTTP/nepodporovaný endpoint a nedostupnost (firewall pouze možná příčina). Veřejná CA z autorizovaného SSH deploye se uloží také lokálně, soukromé klíče se nepřenášejí. Network settings/TLS mimo projektový Git; immutable TLS adresář je flushnut před atomic settings publikací, pád může ponechat pouze neaktivní TLS adresář. Změna nastavení zachovává předchozí backend při běžném selhání. Podmínka dokončení: Qt, socket/TLS/auth boundaries, nonce/replay/pin mismatch, persistence/recovery, cílové desktop–LXC obousměrné ověření. Testy ani kontroly nebyly spuštěny; implementovaný test je desktop→LXC, nikoli důkaz obousměrnosti nebo datového transportu. Firewall/router nezměněny.

- [ ] [planned] **M1-AH-11 — Zapamatované LXC uzly a změny adres (implemented, 2026-09-14; neověřeno).** Požadavek uživatele: průvodce pamatuje nasazené uzly, nabízí vlastní adresy a aktualizuje adresu kontejneru. Soukromé lokální deployment preferences mimo projektový Git obsahují SSH cíl/kontejner/LAN/endpointy a veřejnou identitu, nikoli credentials. Publikace přes lokální flock, fsync a atomic replace; po chybě zápisu se úspěšná vzdálená operace nevrací. Výběr uzlu předvyplní formulář, IPv4 rozhraní nabídnou neověřené HTTPS návrhy s portem 8443. Samostatná změna adresy přes jedno SSH ověří jednoznačnou IP v LAN, původní node ID/pin a TLS SAN, pak CAS aktualizuje pouze endpoint schváleného desktopového peeru, nikoli důvěru/práva/mapování. Reuse registry a SSH session M1-AH-10; žádný redeploy, reset nebo regenerace CA. Podmínka dokončení: persistence/restart, Qt, IP/TLS/identity mismatch, CAS a selhání lokální publikace; testy ani kontroly nebyly spuštěny. Návrh desktopové adresy není důkaz běžícího HTTPS backendu.

- [ ] [planned] **M1-AH-10 — Desktopový deploy LXC a prvotní propojení (implemented, 2026-09-14; neověřeno).** Explicitní požadavek uživatele: desktopový průvodce, detekce IP, jedno SSH spojení, aktuální uživatel jako lokální správce nového uzlu a jeho propojení s desktopem. Native Qt dialog používá jeden OpenSSH proces s framed transportem pro deploy, zjištění IP, přenos veřejné CA a párování; heslo zadává ephemeral native askpass bez uložení. Adaptace existujícího CLI install/update/recover/reset, registru správy a Ed25519 protokolu, nikoli nový backend. První instalace vytvoří deterministickou lokální identitu správce; její klíč zůstává v LXC. Schválení obou peerů je součástí výslovně potvrzeného SSH setupu. Projektové mapování používá skutečná společná projektová UUID; prázdný nový uzel čeká na jejich registraci. Vyžaduje skutečný HTTPS endpoint desktopového backendu; současný loopback desktopový UI server se nevydává za síťový backend. Existující instalace automatické účty/párování vynechá. Cílová úroveň PoC validated; podmínka dokončení: Qt, packaging, jediné SSH/password/agent, IP ambiguity, přerušení bootstrapu/párování, CAS/retry a reálné LXC ověření. Testy ani kontroly nebyly spuštěny. Obnova neúplného párování zatím přes stávající správu; automatické pokračování po ztrátě spojení není implementované.

- [ ] [planned] **M1-AH-09 — Inkrementální LXC deploy a vedená obnova (implemented, 2026-09-14; neověřeno).** Požadavek uživatele: aktualizovat pouze vlastní software, přeskočit již splněné instalační kroky a doporučit recovery/reset při chybě. `--update-only` vyžaduje existující web, zachová TLS/identitu/credentials, nepouští apt ani bootstrap; běžná instalace doplňuje pouze chybějící systémové balíky. Nové vydání má vlastní venv a Python dependencies. Reuse release/current a rollback snapshotu ADR 0020. `--recover` obnovuje v LXC, retry dostane nové release ID a obnova již neběží omylem na routeru. Chyby vypisují konkrétní recovery/reset kroky bez automatického destruktivního resetu. Podmínka dokončení: cílené/full testy a cílové update/recovery scénáře; zatím neprovedeno. Restart routeru odložen na přání uživatele kvůli zachování sítě.

Uživatelská akceptace (2026-09-14): webové vytváření projektů (M1-AH-05) a správa uživatelů (M1-AH-06/07) fungují na nasazení. Nastavení federace funguje na úrovni zadání, nikoli doloženého transportu. Jde o potvrzení uživatele, ne nové agentní testy; neuzavírá celý M1/M5 gate ani ostatní scénáře.

K předání podle požadavku uživatele (2026-09-14): pohodlnější lokální přihlašování místo ručně zadávaného tokenu a uhlazení UI správy uživatelů/federace. Zatím pouze požadavek, bez zvolené auth architektury; hesla se mezi uzly nepřenášejí.

Poznámka uživatele k federaci (2026-09-14): nastavení desktopu a kontejneru dokončeno, vzájemná komunikace přes přímé adresy zatím nepotvrzena; případný firewall není doložená příčina. Na přání uživatele se síťová diagnostika odkládá. Automatický transport zůstává otevřenou prací M5; nebyly měněny firewall ani cílová zařízení.

- [ ] [planned] **M1-AH-07 — Lokální účty a oboustranné federační mapování (implemented, 2026-09-13; portable ACL designed s vykonatelným validátorem).** Upřesnění uživatele: samostatné záložky/tabulky uživatelů a federace; desktop jediný běžící uživatel, web více lokálních účtů, login pouze lokálně, credentials nepřenášet, oboustranné mapování a zachování práv s daty. Adaptace stávající správy; registr v2 a migrace v1 zachovávají UUID/credentials. Offline Ed25519 potvrzení a revokace se ověřují vůči pinům obou uzlů, stale/změněné návrhy se odmítají. Native správa používá pouze process token, nevytváří webové účty. [ADR 0021](docs/adr/0021-local-accounts-and-bilateral-mapping.md), [návod](docs/administration.md). Podmínka dokončení: testy dvou uzlů, native/web autentizace, migrace, revokace/replay, průniku ACL, UI a cílová akceptace. Datový transport, vazba ACL na skutečně přenášené bajty/historii a automatická distribuce revokací zůstávají M5, nikoli hotová federovaná synchronizace. Výsledky závěrečného ověření doplnit níže.

- [ ] [planned] **M1-AH-05 — Webové vytvoření projektu (implemented, 2026-09-13).** Požadavek uživatele po funkčním LXC deploy: vytvoření projektu bez desktopu. Adaptace ProjectCreation/Projects, opravené DOM ID, povolená autentizovaná route, operation_id/receipt pro retry, obnova journalu před startem webu. Podmínka dokončení: cílené i celkové testy a ověření vytvoření/otevření na zařízení. Cílové ověření zatím neprovedeno v tomto běhu; testové výsledky doplnit níže.

- [ ] [planned] **M1-AH-06 — Lokální správa uživatelů a federace (implemented, 2026-09-13).** Explicitní požadavek uživatele navázat správou uživatelů s ohledem na federaci a správou federace. Individuální klíče, stabilní user/home-node UUID, lokální node role, projektová členství, deaktivace/rotace, UI správy a Git registr s CAS; credentials mimo Git. Peery pending/approved/revoked, pin ověřený správcem. [Kontrakt, recovery a reuse](docs/administration.md), rozšíření ADR 0020. Cílová úroveň: PoC validated. Podmínka dokončení této části: testy autentizace/ACL/revokace/CAS/přerušené publikace a cílová akceptace UI. Síťový handshake, distribuce identit/revokací a Git synchronizace nejsou implementované a zůstávají M5; toto neuzavírá Gate M5 ani nezavádí důvěru automaticky. Cílový deploy zatím nebyl proveden v tomto běhu.

Ověření M1-AH-05/M1-AH-06 (2026-09-13): závěrečná sada `python3 -m unittest discover -s tests -v` mimo socketově omezený sandbox — **171 testů, 151 prošlo, 20 volitelných přeskočeno, bez chyb**, 46,249 s. Ověřeny HTTPS individuální klíče, filtrovaný katalog a otevření jen přiděleného projektu, odmítnutí administrace/vytvoření běžným členem, rotace/deaktivace, stejný receipt po retry, restart registru, stale CAS, credentials mimo Git, osiřelá credential a selhání rotace před změnou ref se zachováním původního klíče, peer approval/revocation a omezení node-admin. Starší deploy reset test opraven: neodkazuje na pevný index SSH volby místo vzdáleného skriptu. Samostatný skutečný Qt/WebEngine login/katalog/logout prošel; další skutečný browser smoke v dočasném serveru prošel vytvořením/otevřením projektu, vydáním uživatelského klíče a přidáním/schválením/odvoláním testovacího peeru. JS syntaxe a jedinečnost HTML ID ověřeny. Volitelné balicí/offline/desktop/libgit2 testy nebyly v celkovém běhu zapnuté; samostatné browser ověření nenahrazuje všechny přeskočené testy. Cílová akceptace na routeru a skutečná federovaná synchronizace nejsou doložené; položky zůstávají otevřené do vymezené cílové akceptace.

Aktualizace M1-07 podle hlášení uživatele (2026-09-13): deploy již proběhl, web běží v LXC i přes routerovou dlaždici a stránka se načítá; dřívější SSH blokace níže je historická. Tyto údaje jsou uživatelské potvrzení, nikoli nové agentní real-device ověření. Restart/změna IP a ostatní akceptační scénáře zůstávají otevřené.

Aktualizace M1-07 podle hlášení uživatele (2026-09-17): restart routeru zachoval instalaci a data, ale kontejner `workspace-m0` se po bootu nespustil automaticky. Jde o částečný real-device důkaz persistence, nikoli splnění restartové akceptace. Doplnit bezpečný LXC autostart a zopakovat reboot bez ručního startu včetně služby uvnitř kontejneru, dlaždice, přihlášení a náhledu.

**Historická poznámka:** M1-07 již není aktivní v [TODO](TODO.md). Následující odstavce zachovávají starší důkazy, nikoli druhý aktuální stav feature; otevřené návaznosti M1 zůstávají v tomto backlogu a roadmapě. Výchozí stav před M1-07: `scripts/deploy_omnia.py` instaloval pouze headless demo, bez webové služby a dlaždice; síťové zpřístupnění musí řešit autentizaci a hranice přístupu podle ADR 0013.

Ověření cílového prostředí (2026-09-13): SSH přístup k cílovému routeru zatím blokuje `Permission denied (publickey,password,keyboard-interactive)`, změna cílové cesty už byla dočasně potvrzena v `docs/lxc-web.md` a v `scripts` kódu. Do odblokování SSH a prvního nasazení zůstává celá položka otevřená.

Průběžný výsledek M1-07 (2026-09-10, implemented): připraven opt-in HTTPS náhled, přístupový klíč mimo Git, ochrana local-only, bootstrap persistentní identity, systemd nasazení s rollbackem a samostatná routerová dlaždice s dynamickým LXC rozlišením a ověřením TLS. [Návod](docs/lxc-web.md), [ADR 0020](docs/adr/0020-lxc-web-viewer.md). Web zatím pouze čte; nativní editor/tvorba/historie nemají webovou náhradu. Skutečné nasazení a cílová akceptace zůstávají otevřené: SSH přístup k uživatelem určené výchozí bráně jako root byl odmítnut (`Permission denied (publickey,password,keyboard-interactive)`). Na router nebyly přeneseny soubory ani provedeny změny; stav jeho WebApps/Python/LXC a certifikátů nebyl ověřen. Po obnovení SSH přístupu ověřit prostředí a připravit konkrétní nasazení; samostatně doložit restart/změnu IP a ostatní cílové scénáře. Gate M1 zůstává otevřený.

Ověření M1-07 (2026-09-10): závěrečný běh `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v` — **158 testů, 154 prošlo, 4 přeskočeny, bez chyb**, 97,839 s. Testován základ `c2768120bddf5330fee7e90c04ba2d8cf40e191a` plus necommitnuté změny M1-07; nejde o výsledek samotného tohoto commitu. Skutečné Qt/WebEngine včetně webového přihlášení/katalogu/odhlášení, izolovaná instalace/upgrade/odstranění `.deb` a offline testy běžely. Přeskočeny pouze čtyři testy `test_git_comparison` pro nativní libgit2 probe (CAS/restart, clone/merge, HTTP autentizace a nevalidní projekce); bez sestaveného probe zůstávají neověřené. Nové testy ověřují HTTPS/Host/Origin/token, skutečné přesměrování a odmítnutí chybějící CA, ochranu local-only se skutečným Gitem, opakovaný bootstrap identity, změny adres a nedostupnost LXC, opakovanou instalaci/odebrání a návrat souborů při chybě; LXC instalační rollback je ověřen vykonáním shellu s nahrazenými systémovými příkazy, nikoli na skutečném systemd/LXC. První úplný běh odhalil chybějící nový návod v balicím fixture; opraveno a závěrečný běh výše prošel. Ověřena syntaxe JS, shellové instalační plány, lokální odkazy, obsah source allowlistu, finální diff a `git diff --check`. Cílové TLS, procd/lighttpd, restart routeru a změna IP na zařízení zůstávají neověřené; odblokování vyžaduje funkční SSH přístup k potvrzenému routeru a připravené TLS podklady podle návodu.
