<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — COMP-03

Aktivní feature dávka: **Workspace řízení Julia výpočtu**

- **Původ:** uživatelský požadavek spustit výpočet přímo z Workspace po
  doručení `COMP-02`; roadmapa 2G a navazující dávka v BACKLOG.
- **Milník a úroveň:** M6-COMPUTE, cílově **PoC validated**.
- **Větev a PR:** `feature/comp-03-julia-workspace` z `develop` `507c232`,
  cílová větev PR `develop`.
- **Závislosti:** doručené `COMP-01` a `COMP-02`; používá jejich validovaný
  kontrakt, node-local runtime binding, Julia journal, materializaci a
  explicitní Workspace publikaci bez druhého runneru nebo zápisové cesty.
- **Rozsah:** shared desktop/web UI otevřeného projektu umí z bezpečné šablony
  atomicky vytvořit nebo upravit projektově spravovaný Julia model a načte pouze validované
  `fpw-julia-computation-v1` definice z přesného Git HEAD, nabídne typované
  parametry, přesný preview, explicitně potvrzený běh, bezpečný
  cancel/reconcile, stav po restartu, náhled deklarovaných výstupů a odděleně
  potvrzenou publikaci jednoho výstupu s provenance.
- **Mimo rozsah:** obecné IDE, Pluto/Jupyter, automatický scheduler,
  síťové/GPU/distribuované výpočty, instalace runtime či balíčků a automatická
  publikace.
- **Crash boundaries a recovery:** preview je read-only. Potvrzený běh používá
  autoritativní SQLite journal a exact request z `COMP-02`; pád před durable
  dispatch nic nespustí, neurčitý pád po dispatch zůstane `unknown` bez
  automatického retry a exact materializace se pouze reconciliuje. Publikace
  používá samostatnou serializovanou Workspace operaci; po commitu se index
  obnoví z HEAD a retry nesmí vytvořit druhý artefakt. UI drží jen projekci
  těchto stavů. Rozepsaný editor je pouze klientský draft. Save před durable
  journalem nemá projektový účinek; čtyři soubory a metadata se validují a
  commitují jednou Workspace transakcí, po commitu recovery obnoví index a
  opakování stejného operation ID nevytvoří druhý balíček.

- [x] [completed] **COMP-03-A — projektová projekce definic a přesný preview
  (cílová úroveň: implemented).** Prověřit reuse stávajícího runner API a
  shared route/adaptérů; načíst validované definice z aktuálního HEAD, vykreslit
  typované parametry a vrátit revizně připnutý preview se vstupy, privacy,
  runtime a limity bez dispatch.
- [x] [completed] **COMP-03-B — potvrzený běh a lifecycle (cílová úroveň:
  implemented).** Samostatné potvrzení smí spustit pouze exact preview přes
  existující Julia journal. Status rozliší `prepared/running/current/stale/
  failed/cancelled/unknown`; cancel a reconcile respektují bezpečné hranice a
  restart nesmí způsobit automatický nový běh.
- [x] [completed] **COMP-03-C — výstupy a explicitní publikace (cílová úroveň:
  implemented).** Nabídnout bounded náhled deklarovaných výstupů a oddělené
  potvrzení jednoho vybraného výstupu přes existující Workspace publikaci;
  znovu ověřit HEAD, RBAC a privacy a zachovat idempotentní receipt/provenance.
- [x] [completed] **COMP-03-D — shared desktop/web UI (cílová úroveň:
  implemented).** Zpřístupnit celý tok v otevřeném projektu se stejným
  bezpečným DOM a klávesnicovou/mobilní dostupností; otevření projektu, změna
  parametru ani čtení statusu nesmí nic spustit nebo publikovat.
- [x] [completed] **COMP-03-F — editor Julia modelu a šablony (cílová úroveň:
  implemented).** Na explicitní doplnění uživatele vytvořit ve shared UI
  specializovaný editor, který v jedné Workspace transakci uloží `.jl`,
  `Project.toml`, Pkg manifest a hashovanou definici. Nabídnout spustitelnou
  bez-závislostní šablonu, kontrakty parametrů/výstupů a pokročilé limity;
  importované immutable zdroje nepřepisovat a uložením nic nespouštět. Po
  uživatelské korekci umístit vstup do editoru výhradně pod **Nástroje →
  Julia** v hlavním panelu; záložka **Výpočty** zůstává pro preview, běh a
  publikaci, nikoli pro authoring.
- [ ] [in progress] **COMP-03-E — regrese, dokumentace a fyzická akceptace
  (cílová úroveň: PoC validated).** Pokrýt validní i fail-closed cesty,
  concurrency/restart/stale/cancel/unknown/publikaci, shared web wiring a
  fyzicky projít jeden výpočet a publikaci na podporovaném Julia 1.10.12
  Linux glibc aarch64 runtime. Před dokončením spustit plnou testovací sadu,
  zkontrolovat dokumentaci, finální diff a `git diff --check`.

### Průběžné výsledky a ověření

- Shared servis reuse stávající `JuliaExecutor`, journal, materializaci a
  Workspace publikaci. Katalog připíná i samotnou definici jako vstup; její
  privacy se proto započte do výsledku. Síťová projekce před vytvořením runu
  skryje definici i každý výpočet závislý na `local-only` artefaktu.
- Background dispatch neblokuje omezený HTTP worker. Safe pre-dispatch chyba
  ponechá durable preview připravené a vrátí session diagnostiku; aktivní
  worker nelze reconcile. Restart nic automaticky neopakuje a nedokončený
  durable dispatch používá původní `unknown` recovery.
- Cílená Julia sada: **29 testů, OK, 2 podmíněně přeskočeny**. Shared
  desktop/web API a UI testy prošly; dočasný rozpor aktivního TODO s grafovou
  projekcí byl opraven a následných 7 grafových testů prošlo.
- Fyzická akceptace přes `JuliaWorkspaceService` nad oficiálním Julia 1.10.12
  Linux glibc aarch64 runtime prošla: Git definice, exact preview, potvrzený
  bubblewrap běh, odmítnutá síť, výstup `real-julia=42;network=denied` a
  explicitní Workspace publikace.
- Editorová šablona byla navíc fyzicky vytvořena přes shared službu a prošla
  skutečným Julia 1.10.12 bubblewrap během; cílený test ověřuje i update téhož
  čtyřartefaktového balíčku bez duplicitní definice. Manifest zůstává přesný
  projektový vstup a editor jej automaticky negeneruje ani neinstaluje balíčky.
- Po rozšíření editoru prošla celá cílená Julia sada včetně fyzické akceptace:
  **30 testů, OK, 1 podmíněně přeskočen**. Shared editor API/UI, roadmap graf,
  JavaScript syntax a Python compile prošly. Plná sada doběhla všech **937
  testů** se 3 chybami pouze kvůli novému formuláři chybějícímu v tiskovém
  inventáři; inventář byl doplněn a všech 3 původně chybných testů i navazující
  UI/graf kontroly následně prošlo (**5 testů, OK**).
- Plná sada před závěrečným oddělením read-only Git projekce: **936 testů,
  OK, 35 podmíněně přeskočeno, 233,044 s**. Po této úzké opravě znovu prošla
  celá Julia sada a projektový side-effect test: **30 testů, OK, 2 podmíněně
  přeskočeny**. JavaScript navíc prošel `node --check`; finální plnou sadu
  zopakovat po viditelné akceptaci a poslední případné opravě.
- Po přesunu authoringu do hlavní záložky **Nástroje** prošly Python compile,
  `node --check`, 5 cílených UI/form testů a plná sada mimo socketově omezený
  sandbox: **937 testů, OK, 35 podmíněně přeskočeno, 236,049 s**. Test hlídá,
  že editor není v panelu **Výpočty** a že levé **Nástroje → Julia editor**
  otevřou hlavní panel **Nástroje**.
- Zbývá viditelná uživatelská akceptace záložek **Nástroje** a **Výpočty** ve
  skutečném desktopovém nebo webovém Workspace. Real Qt/WebEngine scénáře jsou
  v běžné sadě podmíněně přeskočené. Read-only inventura sedmi aktuálně
  registrovaných projektů našla 0 validních Julia definic, takže akceptace
  potřebuje oddělený demonstrační projekt nebo uživatelem vybraný existující
  projekt. Bez této kontroly dávku nearchivovat ani nedoporučovat PR.

### K předání do backlogu

- [ ] [planned] **DOC-PATTERN-CATALOG-01 — katalog textových vzorů a sdílený
  raw editor (cílová úroveň: implemented).** Původ: upřesněný uživatelský
  požadavek z 2026-10-27. Typ dokumentu/format adaptér zpřístupní jen relevantní
  vzory; vzor je validní textový fragment a místa k doplnění používají komentář
  jen u syntaxí, které jej podporují. Sdílený widget poskytne raw text, vložení
  vzoru, ochranu rozepsané práce a validaci, ale persistence zůstane v
  konkrétním Workspace adaptéru. První sada: úkoly, obecný Markdown,
  prezentace a Julia. Samostatná feature větev a PR.
- [ ] [planned] **PLAN-FILE-HIERARCHY-01 — souborový kontrakt roadmapy a
  podgrafů (cílová úroveň: designed).** Popsat profilovatelné typy uzlů a
  agregaci bez nové databáze. Softwarový profil používá `milestone → batch →
  task`, kde batch je jedna feature větev/PR a task nejmenší koherentní změna
  cílená na jeden commit. Podúkoly lze deklarovat ve stejném souboru nebo
  explicitním odkazem na verzovaný dokument; podgraf pouze vybírá kanonická ID
  a nepřebírá autoritu nad jejich stavem. Jiné roadmapové profily mohou mít
  jiné úrovně, ale musí je uzavřeně deklarovat. První dávka je pouze popis a
  příklady nad soubory, bez DB nebo speciálního editoru.
- [ ] [planned] **PLAN-TASK-EDITOR-01 — specializovaný editor hlavního TODO
  (cílová úroveň: implemented).** Původ: uživatelský požadavek z 2026-10-27.
  Až nad `DOC-PATTERN-CATALOG-01` a `PLAN-FILE-HIERARCHY-01` materializovat
  známé bloky do widgetů typu „lego“: typ, stabilní ID, stav, popis a kanonické
  vztahy (`depends_on`, `blocks`, `duplicates`, `supersedes`, `relates_to`,
  `parent_of`). Autoritou zůstává textový TODO v Gitu a raw režim; neznámý
  obsah se nesmí při round-trip ztratit. Samostatná feature větev a PR.

### Podmínky akceptace

Uživatel z otevřeného projektu vybere validovanou definici, vyplní typované
parametry, zkontroluje exact preview a až samostatným potvrzením spustí běh.
Po restartu vidí pravdivý stav a může bezpečně cancel/reconcile. Výstup lze
prohlédnout bez zápisu do Gitu a jeden vybraný výstup publikovat až druhým
explicitním potvrzením; změna HEAD, oprávnění, privacy, runtime nebo preview
selže před účinkem. Automatické otevření, retry běhu ani publikace neexistují.
