<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Záznam dokončené práce

## F-M3-EXPLICIT-TASK-ROUTING-01 — explicitní podklady, výstup a vykonání — 2026-10-17

Dávka na větvi `feature/f-m3-explicit-task-routing-01`, založené jako uživatelem
schválená stacked výjimka nad reader checkpointem `ea7d101`, dosáhla úrovně
**PoC validated**. Implementace je v lokálním commitu `2c72dfb`; větev nebyla
pushnuta a PR do `develop` nebyl vytvořen ani sloučen. Samostatné doručení musí
zachovat pořadí reader → routing.

- [x] [completed] **F-M3-EXPLICIT-TASK-ROUTING-01-A — přesný task-plan
  kontrakt a policy (implemented).** Uzavřený `ExplicitTaskPlan` odděluje
  podklady, jediný výstup a vykonání, váže je digestem a deterministicky vybírá
  jednu z rolí `task-output-{conversation,document,presentation}-v1`; rozhodnutí
  zachycuje ADR 0034.
- [x] [completed] **F-M3-EXPLICIT-TASK-ROUTING-01-B — backendové explicitní
  routování (implemented).** Lokální i externí backend dostává právě jedno
  schéma a jiný output kind se odmítne bez opravy či fallbacku. Web bez reader
  runu připraví pouze search, potvrzený reader run vstupuje do nového manifestu
  a externí výsledek se po potvrzení redukuje na přímou odpověď nebo
  reviewovatelný draft. Externí cíl nepřijme interní artefakty.
- [x] [completed] **F-M3-EXPLICIT-TASK-ROUTING-01-C — desktopové volby a
  diagnostika (implemented).** Režim Zadání úkolu zobrazuje samostatné volby
  podkladů, výsledku a backendu, zakázanou externí artifact hranici i skutečný
  plán; Volná konverzace zůstává přímým chatem.
- [x] [completed] **F-M3-EXPLICIT-TASK-ROUTING-01-D — automatické a fyzické
  ověření (PoC validated).** Celá sada `python3 -m unittest discover -s tests
  -v` prošla 634 testy, 27 volitelných testů bylo přeskočeno; samostatně prošla
  syntaxe desktopového JavaScriptu a `git diff --check`. Uživatel při fyzickém
  desktopovém průchodu potvrdil, že explicitní routování i reader pro dokončení
  rozdělaných dávek stačí.

### Výsledek, recovery a omezení

Plán, Context Manifest a oddělené search/reader/backend journaly zachovávají
stale HEAD/binding/privacy kontroly a `unknown` bez automatického retry.
Dokument ani prezentace se nezapíšou bez samostatného potvrzení. Fyzická
akceptace současně označila ovládání za těžkopádné; nejde o vadu blokující tuto
dávku, ale o explicitní vstup do `UX-FACELIFT-01` před prvním releasem. Jeho
scope se má určit interaktivně nad skutečným UI, ne předem zmrazeným redesignem.

## F-M3-PUBLIC-SOURCE-READER-01 — bounded statický reader — 2026-10-17

Dávka na větvi `feature/f-m3-public-source-reader-01`, založené z doručeného
`develop` `225ea01`, dosáhla úrovně **PoC validated**. Implementace je v lokálním
commitu `bed828b` a závislost fyzické akceptace v `ea7d101`; větev nebyla
pushnuta a PR do `develop` nebyl vytvořen ani sloučen. Fyzická akceptace byla
dokončena na navazující stacked větvi s explicitním routováním.

- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-A — kontrakt, journal a
  staging (implemented).** `PublicSourceRuns` váže binding, request a preview,
  ukládá raw/text bajty atomicky a po restartu převádí přerušený dispatch na
  `unknown` bez automatického opakování.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-B — SSRF-safe HTTPS a robots
  (implemented).** Transport validuje veřejné A/AAAA adresy, připíná spojení,
  zachovává hostname/SNI a fail-closed u redirectu, TLS, robots, MIME, charset,
  časových, wire, decoded a kompresních limitů.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-C/D — inertní projekce,
  Context Manifest a UI (implemented).** Jedna potvrzená SearXNG URL se zobrazí
  jako bounded inertní text s hashi a provenance, bez dalších fetchů či zápisu
  do projektu; UI odlišuje `unsupported`, `rejected`, `failed` a `unknown`.
- [x] [completed] **F-M3-PUBLIC-SOURCE-READER-01-E — automatické a fyzické
  ověření (PoC validated).** Readerová cílená sada prošla 36 testy s jedním
  volitelným přeskočením a tehdejší celá sada 631 testy s 27 přeskočeními.
  Živý explicitní smoke uspěl na `example.com` a RFC Editoru, dynamický Element
  skončil očekávaně `unsupported/no-static-text`. Navazující plná sada routingu
  prošla 634 testy s 27 přeskočeními. Uživatel následný fyzický desktopový
  průchod označil za dostačující pro dokončení obou rozdělaných dávek.

### Výsledek, recovery a omezení

Reader zůstává jediným potvrzovaným bounded HTTPS fetcherem, nikoli crawlerem,
browserem ani automatickým importem. Příprava nemá síťový účinek; `dispatching`
po pádu skončí `unknown`, úspěch se vydá jen proti ověřeným staging hashům a
případný Git artefakt vyžaduje novou Workspace operaci. Neověřuje se tím
browser automation, přihlášený obsah, PDF ani strukturované providerové API.

## F-M3-PUBLIC-SOURCES-01 — průzkum API a kontrakt veřejných zdrojů — 2026-10-17

Dávka na větvi `feature/f-m3-public-sources-01`, založené z doručeného
`develop` `8338a6c`, dosáhla cílové úrovně **designed**. Feature akceptace je
uzavřená; jediný PR do `develop` dosud nebyl vytvořen ani sloučen. Dávka nemění
aplikační kód ani neprohlašuje síťový reader za implementovaný.

- [x] [completed] **F-M3-PUBLIC-SOURCES-01-A — průzkum oficiálních zdrojů
  (designed).** Aktuální primární dokumentace ověřila CKAN/DCAT katalogy,
  MediaWiki REST, Crossref metadata, Atom a statickou HTTPS stránku. Výsledek
  odděluje providerovou identitu, revizi, autentizaci, proměnlivé kvóty,
  licenci a obsah a výslovně označuje odvozené závěry.
- [x] [completed] **F-M3-PUBLIC-SOURCES-01-B — provider-neutral kontrakt
  (designed).** ADR 0033 definuje verzovaný binding, request/preview digest,
  durable výsledek, bounded bajty a text, MIME/charset, HTTP validators,
  provenance, cache/revalidaci a `unknown` bez automatického retry.
- [x] [completed] **F-M3-PUBLIC-SOURCES-01-C — bezpečnostní a recovery návrh
  (designed).** Kontrakt vymezuje veřejné DNS adresy a connect pinning proti
  rebindingu, nulové redirecty, robots preflight, TLS, wire/decoded limity,
  inertní parser, prompt injection jako data, fsync staging, restart a oddělení
  fetch runu od SearchRuns i projektové publikace.
- [x] [completed] **F-M3-PUBLIC-SOURCES-01-D — reuse, rozhodnutí a předání
  (designed).** Adaptují se existující stavové automaty, stdlib HTTP/TLS,
  Context Manifest a immutable source/Workspace hranice, ne jejich databáze.
  Strukturované adaptéry mají přednost; explicitní `static-html-v1` je omezený
  fallback. Navazující `F-M3-PUBLIC-SOURCE-READER-01` je předán do BACKLOGu.

### Výsledek, recovery a omezení

Průzkum je v [samostatném podkladu](docs/public-sources-research.md), rozhodnutí
v [ADR 0033](docs/adr/0033-public-source-retrieval.md) a reuse závěr v
REUSE_CATALOG. Crash hranice budoucího fetch runu jsou navrženy jako
`prepared → dispatching → succeeded|unsupported|rejected|failed|unknown`:
před dispatch není síťový účinek, přerušený dispatch se bez nového potvrzení
neopakuje, úspěšné raw/projection bajty se fsyncnou před uzavřením SQLite stavu
a chybějící cache se nestahuje potichu znovu. Případný Git source vzniká až
samostatnou potvrzenou Workspace operací.

Ověření této čistě návrhové dávky tvoří kontrola primárních zdrojů, návazností,
lokálních odkazů, finálního diffu a `git diff --check`; aplikační testy nebyly
spuštěny, protože se aplikační kód, testy ani konfigurace nezměnily. Neověřeno
zůstává provedení síťového kontraktu, jeho automatické testy a fyzický průchod
dvěma veřejnými weby; ty jsou akceptací navazující implementační dávky.

## F-M4-PRESENTER-PDF-01 — export prezentace a záznamy relací — 2026-10-17

Dávka na větvi `feature/f-m4-presenter-pdf-01`, založené z doručeného
`develop` `aa7fa26`, dosáhla úrovně **PoC validated**. Feature akceptace je
uzavřená a jediný PR #69 byl doručen do `develop` jako merge commit `8338a6c`.
Implementace je v commitech `84c34b5`, `3dd89fe` a `6a1d245`.

- [x] [completed] **F-M4-PRESENTER-PDF-01-A — kontrakt relace a reuse
  (designed).** Omezené schema váže veřejné snapshoty na přesný deck a jeho
  revizi. Implementace adaptuje `PresentationDocuments`, `Artifacts.save`,
  existující Workspace transakci a allowlisted renderer; nevytváří druhý volný
  HTML renderer.
- [x] [completed] **F-M4-PRESENTER-PDF-01-B — durable zachycení a materializace
  relace (implemented).** Node-local SQLite journal ukládá pouze potvrzené
  audience snapshoty. Čisté ukončení vytvoří dokončenou relaci; restart uzavře
  rozpracovanou relaci jako přerušenou a stabilní artifact/operation ID brání
  duplicitě po nejistém výsledku projektového commitu.
- [x] [completed] **F-M4-PRESENTER-PDF-01-C — seznam a mazání v editoru
  (implemented).** Editor zobrazuje relace vybraného decku, stav, čas a počet
  stran. Smazání vyžaduje náhled, druhé potvrzení a exact-HEAD kontrolu;
  odstraní aktuální projektovou verzi, ale zachová Git historii.
- [x] [completed] **F-M4-PRESENTER-PDF-01-D — bezpečný tisk/PDF
  (implemented).** Kanonický export používá hlavní `next` linii, relační export
  přesné uložené audience snapshoty včetně skutečně promítnutých backupů,
  opakování, závěru a reveal stavů. Oba režimy používají stejný bounded 16:9
  offline vizuální model a explicitní plán, cíl i potvrzení přepsání.
- [x] [completed] **F-M4-PRESENTER-PDF-01-E — UI, testy, dokumentace a fyzická
  akceptace (PoC validated).** Automatické kontrakty, skutečný WebEngine smoke
  a uživatelský desktopový průchod ověřily dokončené i přerušené relace,
  kanonický i relační tisk, zrušení, přepsání, vizuální shodu a potvrzené
  smazání.

### Ověření a recovery

Cílené modelové, storage, UI-policy a atomické publikační testy pokryly oba
stavy relace, exact public reveal snapshoty, stale HEAD, nejisté potvrzení po
commitu bez duplicity, potvrzené smazání, stabilní pořadí, vyloučení soukromých
polí a zachování původního PDF při známém selhání. Úplná sada po posledních
aplikačních opravách prošla jako **619 testů OK, 27 volitelných testů
přeskočeno**. Samostatný Qt WebEngine smoke vytvořil dvoustránkový PDF;
`pdfinfo` potvrdil 2 strany, `1152 × 648 pt` (16:9) a PDF 1.4.

Živá relace zapisuje potvrzený veřejný snapshot do lokálního SQLite journalu
před oznámením úspěchu. Materializace pak používá jedinou existující
Workspace/journal/Git/index hranici; před commitem je autoritou journal a po
commitu lze index obnovit z HEAD. PDF vzniká v jednoznačně pojmenovaném
dočasném souboru ve stejné složce a cílovou cestu nahradí atomicky až po
dokončení. Známé selhání ani zrušení cíle původní soubor nemění.

### Fyzická akceptace a hranice rozsahu

Uživatel 2026-10-16 ověřil po úplném restartu desktopu funkční výběr cíle,
potvrzení a dokončení PDF exportu. Dne 2026-10-17 následně bez hlášeného
omezení potvrdil: dokončenou relaci se správným počtem stran; kanonické PDF;
PDF přesného průběhu relace a jeho vizuální shodu s audience výstupem; zrušení
výběru i potvrzené přepsání existujícího PDF; potvrzené smazání při zachování
Git historie; a po restartu správně materializovanou přerušenou relaci pouze z
již promítnutých snapshotů.

Fyzická kontrola během dávky odhalila a implementace opravila odmítnutí
allowlistovaného lokálního závěrečného slidu, nepředané nonce nativní PDF akci
a nekompatibilní převod JS objektu v použitém PySide6. Most nyní předává
explicitní bounded JSON a revaliduje nonce i digest. Mimo rozsah zůstává PPTX,
obecný reporting, DisclosureEvent, disclosure semafor a širší rozhodovací
scénář roadmapy 22C.

## F-M4-PRESENTER-01 — Markdown prezentace jako výstup orchestrace — 2026-10-16

Dávka na větvi `feature/f-m4-presenter-01-markdown-decks`, založené z
`develop` `6c94047`, začlenila a rozšířila existující presenterový základ z
`origin/feature/gamepad-demo-presenter`. Dosažená úroveň je **PoC validated**.
Feature akceptace je uzavřená a jediný PR
[#68](https://github.com/AntoninMicka/FederatedProjectWorkcspace/pull/68) byl
doručen do `develop` jako merge commit `aa7fa26`. Implementační historie je na
feature větvi včetně merge `fed649e` a navazujících commitů po `2042efd`.

- [x] [completed] **F-M4-PRESENTER-01-A — Začlenění a stabilizace základu
  (PoC validated).** Současný desktop zachoval chat, hledání, importy,
  publikaci a bezpečnostní hranice a doplnil presenter, audience assety,
  displejové role, backupy, profil a závěrečný slide. Runtime oprava odstranila
  závislost na vyřazeném nativním editoru; skutečné Qt testy následně prošly.
- [x] [completed] **F-M4-PRESENTER-01-A1 — Konfigurovatelné mapování gamepadu
  (implemented).** Výběr zařízení, mapování os/tlačítka, prahy a živý náhled
  používají node-local SQLite mimo Git. Použití pro relaci je bezzápisové;
  explicitní uložení je jedna synchronní transakce s doloženým restartem,
  crash scénáři a odmítnutím symlinku.
- [x] [completed] **F-M4-PRESENTER-01-A2 — Integrovaný editor prezentací
  (implemented).** Jediná responzivní workspace záložka nahradila samostatný
  dialog a sdílí navigaci, formuláře, náhled a stavové hlášky. Koncept, retry
  stejné operace a cizí změna HEAD zůstávají fail-closed; spustit lze jen přesně
  uloženou revizi.
- [x] [completed] **F-M4-PRESENTER-01-A3 — Seznam hotových prezentací
  (implemented).** Sidebar bezpečně zobrazuje uložené i neplatné decky a nabízí
  úpravu nebo spuštění platné přesné revize. Pouhé otevření seznamu nic
  nezapisuje; webová varianta lokální presenterovou záložku skrývá.
- [x] [completed] **F-M4-PRESENTER-01-B — Markdown kontrakt a migrace v1
  (implemented).** Formát `fpw-presentation` v2 kombinuje omezený YAML a
  čitelný Markdown se stabilními UUID. Strict loader odmítá neznámá pole,
  duplicity, aliasy, tagy a nadměrné zanoření; HTML se neinterpretuje. Legacy
  JSON se čte bez zápisu a migruje až explicitním uložením stejného artefaktu.
- [x] [completed] **F-M4-PRESENTER-01-C — Stabilní layout šablony
  (implemented).** Deck nese verzované allowlisted šablony titulního,
  obsahového, dvousloupcového, vizuálního a závěrečného slidu. Editor, speaker
  preview a audience sdílejí `presentation_visual.py`; volné HTML/CSS ani
  druhý renderer nevznikly.
- [x] [completed] **F-M4-PRESENTER-01-D — Validovaný návrh z orchestrace
  (PoC validated).** Task router přijímá uzavřený `presentation-proposal`,
  aplikačně ověřuje zdroje, layouty, privacy, HEAD, kanonický Markdown a
  SHA-256 a vytváří pouze durable návrh bez projektového zápisu.
- [x] [completed] **F-M4-PRESENTER-01-D1 — Zpřesněný návrhový kontrakt
  (implemented).** Po prvním fyzickém selhání instrukce vyžaduje všech pět polí
  slidu, allowlisted layout, 6–12 slidů bez zadaného rozsahu, jazyk zadání a
  obsah pouze z vybraných zdrojů; vadný návrh se automaticky neopravuje.
- [x] [completed] **F-M4-PRESENTER-01-D2 — Bounded PDF textová projekce
  (implemented).** Lokální Poppler převádí vybraný PDF artefakt na inertní text
  s limity 4 MiB, 2000 řádků a 15 sekund. Manifest dál váže původní bajty, ID,
  privacy, commit a SHA-256; selhání nemá fallback.
- [x] [completed] **F-M4-PRESENTER-01-D3 — Structured output schema
  (implemented).** Ollama dostává uzavřené JSON Schema všech výsledků a větev
  prezentace strojově vyžaduje layout i ostatní pole. Aplikační validace zůstává
  samostatnou autoritativní vrstvou.
- [x] [completed] **F-M4-PRESENTER-01-D4 — Presentation-only směrování
  (PoC validated).** Explicitní vytvoření či aktualizace decku používá zvlášť
  verzovanou roli, která nepovoluje dokumentovou větev. Regresní test používá
  přesný prompt `vytvoř z daného dokumentu prezentaci` a odmítá odlišný výstup.
- [x] [completed] **F-M4-PRESENTER-01-E — Povinné schválení create/update
  (PoC validated).** Návrh zobrazuje přesný before/after diff z historické base
  revision. Potvrzení je vázané na task, cíl, base revision, deck digest a
  approval digest. Stale nebo pozměněný návrh se odmítne; stabilní
  artifact/operation ID obnoví pád po projektovém commitu bez druhého commitu.
  Create zachová privacy vstupů a `llm-generated` provenance, update metadata
  existujícího decku.
- [x] [completed] **F-M4-PRESENTER-01-F — Dokumentace a fyzická akceptace
  (PoC validated).** README a uživatelský návod popisují editor, displeje,
  orchestration preview/confirm, recovery a omezení. REUSE_CATALOG eviduje
  adaptaci ContextBuilderu, registru rolí, OllamaRuns, TaskOutcomes a jediné
  Workspace/Journal/Git/index hranice. Roadmapa rozlišuje hotový omezený základ
  od otevřeného širšího Disclosure Presenter rozsahu.

### Ověření a recovery

Průběžné cílené testy pokryly renderer, editor, sidebar, Markdown migraci,
layouty, gamepad, task router, PDF projekci, structured output, přesný diff,
stale HEAD/digest, autentizované API a pád po projektovém commitu. Poslední
aplikační změna prošla úplnou sadou **610 testů za 127,797 s, 27 volitelných či
fyzických testů přeskočeno**; Python compilation a `git diff --check` prošly.
Po ní následovaly pouze dokumentační a evidenční změny kontrolované na odkazy,
konzistenci a finální diff.

Před projektovým commitem je autoritou existující journal; po commitu lze index
obnovit z HEAD. Modelový návrh ani presenterová relace nejsou důkazem uložení.
Bez explicitního schválení nevzniká artefakt ani commit; ztracená odpověď po
potvrzeném commitu se obnoví stejným operation ID bez druhého zápisu.

### Fyzická akceptace a hranice rozsahu

Uživatel 2026-10-15 a 2026-10-16 na Linux notebooku fyzicky potvrdil editor,
vytvoření i aktualizaci prezentace z vybraného dokumentu, načtení staršího
decku, dvoudisplejové spuštění a navigaci, oddělení speaker/audience obsahu,
odpojení displeje a fyzický gamepad; bez hlášeného omezení. Další vzhledové
úpravy editoru byly výslovně odloženy do `UX-FACELIFT-01`.

Mimo rozsah zůstává obecná projektová kompilace, plný Disclosure Registry,
expozice/semafor, trvalá relace schůzky, obecný rozhodovací strom a PPTX.
`F-M4-PRESENTER-PDF-01` byl se zachovaným bezpečnostním a recovery kontraktem
předán do BACKLOGu; širší ER-04/roadmapa 22C zůstává autoritativní a otevřená.

## F-M3-SEARCH-02 — Inteligentní iterativní vyhledávání — 2026-10-14

Dávka na větvi `feature/f-m3-search-02-iterative-search`, založené z `develop`
`3466a5f`, rozšířila potvrzované SearXNG hledání o bounded vícekolové hodnocení
a ruční zpřesňování. Dosažená úroveň je **PoC validated**. Uživatel živě
ověřil výsledky SearXNG a viditelný `intermediate` úsudek Gemmy a schválil
uzavření dávky s doloženým omezením. Feature akceptace je uzavřená; jediný PR
do `develop` dosud nebyl vytvořen ani sloučen.

- [x] [completed] **F-M3-SEARCH-02-A — Iterační kontrakt, reuse a ADR
  (designed).** ADR 0008 vymezuje uzavřené evaluator schéma, stabilní source
  ID, parent/child vazbu, ruční potvrzení, limity 3 kol / 3 dotazů / 30
  výsledků / 300 sekund a recovery hranice jediných `SearchRuns` a
  `OllamaRuns` journalů.
- [x] [completed] **F-M3-SEARCH-02-B — Durable workflow a evaluator
  (implemented).** Každé kolo má samostatný search a JSON `researcher-v2` run,
  přesný Context Manifest a durable evaluation. Uložené `succeeded` účinky se
  po restartu znovu validují bez dispatch; `unknown` se neopakuje. Živá Gemma
  vyžádala úzké normalizace jediného textového `limitations`, prázdného focus
  výběru a vymyšleného artifact UUID pouze při autoritativně nulovém výběru.
- [x] [completed] **F-M3-SEARCH-02-C — Sdílené API/UI mezivýsledků
  (implemented).** Desktop i web bezpečně zobrazují všechna kola, zdroje,
  omezení, provenance a budget. `final` s přiznaným omezením se konzervativně
  mění na `intermediate`; modelový návrh i vlastní text v composeru připraví
  další kolo stejného workflow, ale síťový dotaz se odešle až po kontrole a
  potvrzení.
- [x] [completed] **F-M3-SEARCH-02-D — Regrese, dokumentace a fyzická
  akceptace (PoC validated).** Cílené testy pokryly ruční follow-up a vlastní
  zpřesnění, restart, source ID, falešné `final`, budgety, deletion recovery a
  živě zjištěné modelové odchylky. Fyzický průchod prokázal bounded výsledky a
  mezivýsledek; uživatel jej akceptoval s níže uvedenou hranicí rozsahu.

Závěrečné automatické ověření po poslední aplikační změně: JavaScript
`node --check`, `git diff --check`, cílené regrese a úplná sada **549 testů OK
za 122,727 s, 24 volitelných přeskočeno**. Implementace je v commitech
`087b786`, `21c99da`, `d3ea3ff`, `2a9dc67`, `52ed398` a `9ef3840`.

Akceptované omezení: workflow pracuje pouze s bounded výsledky SearXNG
(titulek, URL, úryvek) a cílové URL automaticky neotevírá. Proto umí správně
označit chybějící konkrétní údaj a nabídnout další hledání, ale samotným
promptováním Gemmy nemůže spolehlivě získat data dostupná až na cílové stránce
nebo za interaktivním formulářem. Uživatel nechce jednorázový dopravní scraper.
Navazující `F-M3-PUBLIC-SOURCES-01` následně navrhlo provider-neutral bounded
získání veřejného zdroje; první implementační řez
`F-M3-PUBLIC-SOURCE-READER-01` je v BACKLOGu. Speciální dopravní capability
nevznikla.
Volitelný automatický dispatch zůstává samostatný `F-M3-SEARCH-03`.

## IMP-01 — Explicitní jednorázový import z Google Drive — 2026-10-14

Dávka na větvi `feature/imp-01-google-drive-import`, založené z `develop`
`a09538e`, přidala explicitní bounded výběr z osobního Google Drive,
bezpečný náhled a atomickou publikaci do aktivního projektu. Dosažená úroveň
je **PoC validated**. Uživatel po opravách reálného OAuth/Picker toku potvrdil
„import proběhl vpořádku“. Feature akceptace je uzavřená; jediný PR do
`develop` dosud nebyl vytvořen ani sloučen.

- [x] [completed] **IMP-01-A — OAuth/Picker kontrakt, reuse a ADR
  (designed).** ADR 0032 připnulo minimální `drive.file`, systémový prohlížeč,
  PKCE/state, přesné callbacky, raw/export mapování, limity, provenance a crash
  boundaries. Implementace adaptuje existující Workspace/Sources/UI a
  nezavádí provider SDK, průběžnou synchronizaci ani zápis do Drive.
- [x] [completed] **IMP-01-B — Bounded Drive adapter a durable staging
  (implemented).** Actor-scoped credentials a tokeny zůstávají mimo Git;
  výběr, metadata, revize, limity a staging jsou obnovitelné. Složky mají
  omezenou hloubku, počet položek i stránek a změna revize nebo odvolání
  přístupu selže před projektovou publikací.
- [x] [completed] **IMP-01-C — Atomická projektová publikace
  (implemented).** Blob soubory zachovávají přesné bajty a hash, Google
  Docs/Sheets/Slides mají viditelný PDF export a zdrojovou provenance.
  Potvrzená dávka publikuje všechny zdroje jednou Workspace operací a jedním
  commitem; duplicate/supersedes a retry jsou explicitní.
- [x] [completed] **IMP-01-D — Sdílené UI/API a akceptace
  (PoC validated).** Desktop a web sdílejí průvodce, bezpečný seznam, plán,
  potvrzení a recovery. Reálný desktopový průchod odhalil a opravil root
  loopback redirect, Google Testing/Test users, RFC 9207 `iss`, editorový
  `docs.google.com` `webViewLink` a obnovení dokončeného výběru po restartu.
  Webový HTTPS callback, RBAC a zákaz `local-only` pokrývá integrační test;
  skutečný webový deployment nebyl součástí fyzické akceptace.

Závěrečné automatické ověření po poslední aplikační změně: Python kompilace,
JavaScript `node --check`, cílených 11 Drive/desktop/HTTPS testů,
`git diff --check` a úplná sada **542 testů OK za 122,554 s, 24 volitelných
přeskočeno**. Skutečný osobní Drive vytvořil plán 13 položek bez blokací za
4,12 s a po uživatelském potvrzení publikoval 13 unikátních artefaktů jedním
commitem `ade0db7703b33c8e7469278c99d6c79189cbe9ca`; receipt je dokončený a HEAD
cílového projektu se s ním shodoval. Shared Drives, synchronizace, zápis zpět,
import bez aktivního projektu a další Google služby zůstávají mimo rozsah.

## F-M1-PROJECT-DELETE-01 — Bezpečné odstranění celého projektu — 2026-10-14

Dávka na větvi `feature/f-m1-project-delete-01-safe-project-removal`, založené
z `develop` `7373d81`, rozlišila obnovu odvozeného indexu, pouhé odregistrování,
obnovitelný lokální koš a samostatně potvrzený definitivní výmaz. Dosažená
úroveň je **PoC validated**. Uživatel fyzicky potvrdil odstranění slovy
„smazani ok“. Feature akceptace je uzavřená; implementace je v lokálním commitu
`f48a760`, ale jediný PR do `develop` dosud nebyl vytvořen ani sloučen.

- [x] [completed] **F-M1-PROJECT-DELETE-01-A — Kontrakt, inventář a reuse
  (designed).** ADR 0031 vymezilo autoritu Gitu, node registry, projektu,
  odvozeného indexu a samostatných chatových, AI, přenosových a administračních
  stavů. Implementace adaptuje jediný node writer lock a journal; nevytváří
  druhého Git writera ani obecný cleanup framework.
- [x] [completed] **F-M1-PROJECT-DELETE-01-B — Doménová služba a durable
  recovery (implemented).** Přesný preview a confirm vážou operation ID,
  digest, HEAD, inode/dev, původní a cílovou registraci i inventář dopadů.
  Přesun do koše, obnova a purge mají idempotentní receipts a fail-closed
  recovery; symlink se při purge nenásleduje.
- [x] [completed] **F-M1-PROJECT-DELETE-01-C — Sdílené UI/API
  (implemented).** Desktop a web používají společný adaptér. Náhled zobrazuje
  cesty, HEAD, dirty worktree, přenosy, členství, federační mapování,
  node-local historii a zachování vzdálených kopií. Cancel je bezpečný výchozí
  stav, webová mutace vyžaduje správce a purge nový náhled i potvrzení.
- [x] [completed] **F-M1-PROJECT-DELETE-01-D — Regrese, dokumentace a
  akceptace (PoC validated).** Jedenáct doménových testů pokrylo persistentní
  hranice, retry/recovery, blokátory, explicitní odebrání členství, zachování
  historie a symlink. Skutečná HTTPS cesta ověřila preview → koš → obnova;
  uživatel následně fyzicky akceptoval odstranění ve skutečném UI.

Závěrečné automatické ověření po poslední aplikační změně: JavaScript syntaxe,
`git diff --check`, cílené testy a úplná sada **530 testů OK za 116,058 s,
24 volitelných přeskočeno**. SQLite `ResourceWarning` z širší sady nebyla
selháním testů. Lokální operace nemaže vzdálené, federované nebo dříve sdílené
kopie,
nerevokuje publikovaná data ani sdílené credentials. Dokončená node-local
historie se zachovává a blokuje purge; ochrana před nekooperujícím procesem
stejného uživatele a libovolnými filesystemovými závody zůstává V-06.

## F-M3-SEARCH-01 — Řízené webové hledání přes SearXNG — 2026-10-13

Dávka na větvi `feature/f-m3-search-01-searxng`, založené z `develop`
`5c3b565`, přidala explicitně potvrzované webové hledání přes node-local
SearXNG binding a následnou Ollama syntézu. Dosažená úroveň je **PoC
validated**. Feature akceptace je uzavřená; jediný PR do `develop` dosud nebyl
vytvořen ani sloučen.

- [x] [completed] **F-M3-SEARCH-01-A — Kontrakt, reuse a konfigurace
  (designed).** ADR a reuse review vymezily explicitní binding, privacy,
  bounded výsledky, nedůvěryhodný obsah a oddělení search runu od LLM runu.
- [x] [completed] **F-M3-SEARCH-01-B — Bounded klient a durable search journal
  (implemented).** Same-node/private-network transport validuje endpoint a
  TLS pin, zakazuje redirect, omezuje odpověď, deduplikuje zdroje a drží
  `prepared`/`dispatching`/`succeeded`/`failed`/`unknown` bez skrytého retry.
- [x] [completed] **F-M3-SEARCH-01-C — Router, Context Manifest a syntéza
  (implemented).** Uzavřený `web-search` outcome váže přesné vstupy, HEAD,
  privacy a binding; bounded výsledky vstupují jako nedůvěryhodná data do
  nového manifestu role `researcher-v1` a existujícího Ollama run journalu.
- [x] [completed] **F-M3-SEARCH-01-D — Společné API a UI potvrzení
  (implemented).** Desktop/web nastavení umí binding a probe; náhled zobrazuje
  přesný dotaz, jazyk, endpoint, privacy a limit a až vědomé potvrzení spustí
  hledání. Odpověď, URL, titulky a úryvky se vykreslují jako bezpečný text.
- [x] [completed] **F-M3-SEARCH-01-E — Regrese, restart a fyzická akceptace
  (PoC validated).** Uživatel dokončil celý desktopový tok preview → potvrzení
  → SearXNG → Ollama. Dotaz na spojení Pardubice–Praha zobrazil syntézu a tři
  zdroje včetně IDOS; výsledek potvrdil slovy „lepší :)“.
- [x] [completed] **F-M3-SEARCH-01-F — Kompatibilita živého router outputu
  (implemented).** Přesný prázdný `message_ids` tvar lokálního routeru se
  bezpečně doplní aktuálním Focus ID; ostatní neplatné tvary zůstávají
  fail-closed.
- [x] [completed] **F-M3-SEARCH-01-G — Akční diagnostika chybějícího bindingu
  (implemented).** Chybějící binding má samostatný `not-configured` stav;
  před preview nevznikne prázdný journal a po preview lze vědomě obnovit přesný
  binding bez síťového účinku nebo nového modelového běhu.
- [x] [completed] **F-M3-SEARCH-01-H — Nezávislá kontrola webového dotazu
  (implemented).** Search preview je mimo pevný composer v rolovací části
  chatu a jeho bounded zobrazení už nezakrývá zadávací formulář.
- [x] [completed] **F-M3-SEARCH-01-I — Explicitní jazyk SearXNG dotazu
  (implemented).** Schvalovaný preview, durable request i HTTP query nesou
  `language=cs-CZ`; tím se odstranila reálná nula výsledků způsobená CAPTCHA
  při requestu bez jazyka.

Závěrečné ověření po poslední aplikační změně: Python kompilace, JavaScript
`node --check`, `git diff --check`, cílené regrese a úplná sada **517 testů OK,
24 volitelných přeskočeno**. Izolovaný živý průchod původního dotazu na spojení
Pardubice–Hradec Králové skončil `completed`, se 3 bounded zdroji a 988 znaky
syntézy; projekt ani uživatelské vlákno nezměnil. Recovery po úspěšném hledání
před syntézou znovu používá uložené výsledky i stejný Ollama run. Mimo rozsah
zůstává automatické otevírání nalezených stránek, crawler/RAG, skrytý fallback
a obecná jazyková policy odpovědí.

## F-M3-OLLAMA-STREAM-01 — Streamovaná odpověď a živý stav lokálního AI běhu — 2026-10-12

Dávka na větvi `feature/f-m3-ollama-stream-01`, založené z `develop`
`4d2e32c`, adaptovala existující Ollama adapter, jediný durable run journal a
workspace NDJSON kanál. Dosažená úroveň je **PoC validated**. Uživatel po
opakované fyzické kontrole potvrdil průběžné vykreslování, viditelný stav,
dlouhou odpověď i autoscroll slovy „takhle je to dokonalé“. Feature akceptace
je uzavřená; dávka byla doručena do `develop` v PR #63 jako commit `5c3b565`.

- [x] [completed] **F-M3-OLLAMA-STREAM-01-A — Kontrakt, reuse a crash
  boundaries (designed).** ADR 0008 a REUSE_CATALOG vymezily request digest,
  limity NDJSON, finální validaci a přechody `dispatching` →
  `succeeded`/`failed`/`unknown` bez druhého adapteru nebo run journalu.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-B/C — Ollama transport, API a
  přístupné UI (PoC validated).** `/api/generate` s `stream:true` skládá
  bounded delty, ale assistant zprávu a usage publikuje až po validním finálním
  rámci. Autorizovaný `/v1/chat/send-stream` odděluje stavové, textové a
  terminální události; reasoning text se nezobrazuje ani neukládá.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-D — Regrese, dokumentace a
  předání (PoC validated).** Opakovaná fyzická akceptace skutečného modelu
  potvrdila, že po počátečním `thinking` přichá text po deltách a UI jej
  průběžně zobrazuje. Checklist rozlišuje tokenový stream brainstormingu od
  celistvého výsledku task routeru.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-E/F — Projektové přiřazení vláken
  (implemented).** Nový přímý i taskový chat se atomicky přiřadí otevřenému
  projektu. Starší nezařazené vlákno lze explicitně přiřadit bez automatické
  migrace ostatních chatů.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-G/H/I — Viditelný průběh v
  historii zpráv (implemented).** Skutečný stavový DOM prvek, čas běhu a
  streamovaný text jsou ve viditelné oblasti historie; Ollama i OpenAI přímý
  chat používají stejnou projekci. Orchestrace ukazuje živý časovaný stav,
  ale nevydává celistvý task-router výsledek za tokenový stream.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-J/K — Telemetrie a capability při
  studeném startu (implemented).** Spotřeba běhu ukazuje zapnutí streamu,
  počet textových delt, první text a celkový UI čas. Fyzická diagnostika
  odhalila, že capability se dříve načetla až po otevření Nastavení; otevření
  projektu ji nyní načte před prvním chatem.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-L — Viditelná volba streamování
  (implemented).** Nastavení ukazuje zapnuto/vypnuto/nepodporováno. Uzlová
  volba je výchozí zapnutá, atomicky uložená mimo projektový Git a přežije
  restart; pád ponechá starou nebo novou celou hodnotu.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-M — Sledování konce dlouhé
  odpovědi (PoC validated).** Autoscroll sleduje spodní hranu skutečného
  kontejneru, pozastaví se při ručním odscrollování a po návratu na konec se
  obnoví. Reálný Qt/WebEngine smoke ověřil 300řádkovou odpověď, ruční
  odscrollování i opětovné sledování.

Závěrečné ověření po poslední aplikační změně: Python kompilace,
JavaScript `node --check`, `git diff --check`, cílená desktopová sada
**23 testů OK, 2 volitelně přeskočeny**, skutečný Qt/WebEngine smoke **OK**
a úplná sada **504 testů OK, 24 volitelných přeskočeno**. Omezení:
automatický reconnect/retry, per-token perzistence a tokenový stream task
routeru zůstávají mimo rozsah; živý webový průchod nebyl samostatně fyzicky
akceptován.

## UX-UNIFIED-02C-FIX1 — Samostatná stránka a spolehlivý picker — 2026-10-12

Dávka na větvi `fix/ux-unified-02c-notebooklm-navigation` opravila podle
opakované fyzické akceptace samostatnou importní stránku, nativní picker cíle,
viditelnou výslednou cestu a bezpečné přijetí cílové složky. Dosažená úroveň je
**implemented / PoC validated**. Uživatel potvrdil skutečný import, vytvoření a
otevření projektu; PR #62 byl sloučen do `develop` jako `4d2e32c`.

- [x] [completed] **UX-UNIFIED-02C-FIX1-A/B/D — Navigace, nativní pickery a
  viditelný cíl (implemented).** Import má vlastní stránku v levém panelu,
  systémové pickery používají jednorázové přesně validované nativní akce a
  ručně vybraná i výchozí cesta je součástí zobrazeného plánu.
- [x] [completed] **UX-UNIFIED-02C-FIX1-E — Bezpečná práva cíle
  (PoC validated).** Vlastní prázdný cíl s režimem `0775` byl odmítnut ještě
  před journalem a aplikace po explicitním souhlasu nabídla opravu na `0700`.
  Neprázdný, cizí nebo symlinkový cíl se automaticky neopravuje. Fyzický import
  po této opravě uživatel úspěšně dokončil.
- [x] [completed] **UX-UNIFIED-02C-FIX1-C — Regrese a předání
  (PoC validated).** `py_compile`, `node --check` a úplná sada prošly:
  **494 testů OK, 24 volitelných přeskočeno**. Izolovaný test skutečného
  privátního Takeoutu prošel; finální fyzická akceptace potvrdila import.

Oprava nepřidala persistentní vrstvu ani crash boundary a zachovala původní
parser, data importu a jediný `ProjectCreation` journal.

## UX-UNIFIED-02C — Společný NotebookLM import — 2026-10-12

Dávka na větvi `feature/ux-unified-02c-notebooklm-import`, založené z
`develop` `1101d52` po doručení F-M4-OUTPUT-ROUTER-02 v PR #60, převedla
existující NotebookLM preview → plán → potvrzení na jednu společnou stránku
a autorizované API pro desktop i web. Dosažená úroveň je **implemented /
lokálně PoC validated** a akceptační podmínky dávky jsou splněné. PR #61 byl
sloučen do `develop` jako merge commit `436f4e6`.

- [x] [completed] **UX-UNIFIED-02C-A — Společná stránka a API
  (implemented).** HTML/CSS/JavaScript workflow je součástí sdíleného shellu;
  oba runtime používají stejné `/v1/notebooklm/preview`, `/plan` a `/confirm`.
  Původní `NotebookLMImportDialog` a paralelní toolbar vstup byly odstraněny.
- [x] [completed] **UX-UNIFIED-02C-B — Capability a RBAC hranice
  (implemented).** Desktopový Qt picker vydává náhodnou in-process capability
  pro jeden přesný archiv a volitelně jeden cíl svázaný s operation ID;
  renderer dostává cílovou cestu jen jako štítek a API přijímá capability,
  nikoli libovolnou cestu. Web přijímá jen server-local cestu,
  vyžaduje node admina a odmítá capability i `local-only`. Potvrzení přijme
  jen nezměněný plán vydaný stejnou backendovou instancí.
- [x] [completed] **UX-UNIFIED-02C-C — Recovery a parita
  (PoC validated).** Adaptér reuseuje `NotebookLMProjectImport` a jediný
  `ProjectCreation` journal; nepřidává DB, writer ani persistentní capability.
  Retry stejné potvrzené operace vrací stejný receipt. Existující crash testy
  všech durable hranic zachovaly jediný projekt a commit.
- [x] [completed] **UX-UNIFIED-02C-D — Regrese, dokumentace a předání
  (PoC validated).** Cílené testy pokryly exact capability, cross-operation
  odmítnutí, vydaný plán, desktop `local-only`, webové RBAC a idempotentní
  potvrzení. Reálný offscreen Qt/WebEngine smoke prošel pro desktopový shell i
  mobilní serverový importní workflow. Úplná sada mimo socketově omezený
  sandbox prošla: **491 testů OK, 24 volitelných přeskočeno**. Praktické kroky
  jsou v [checklistu](docs/notebooklm-import-acceptance.md).

Reuse/adaptuje parser, plán, immutable seed, duplicate detekci, bezpečné
náhledy a `ProjectCreation` recovery z IMP-02 a capability vzor společného
vytváření projektu. Nativní OS picker zůstává v Qt; workflow ani autorita se
neduplikují. Omezení osobního Takeoutu, chybějící notes/původní binární
bajty a oddělený budoucí Drive import se nemění.

## F-M4-OUTPUT-ROUTER-02 — Execution kompozičního plánu — 2026-10-12

Dávka na větvi `feature/f-m4-output-router-02-execution`, založené z `develop`
`d96fe7a`, dodala první explicitně potvrzené durable provedení typovaného output
plánu a skutečný same-process `renderer.web-static@1.0`. Dosažená úroveň je
**implemented / lokálně PoC validated** a akceptační podmínky dávky jsou
splněné. PR #60 byl sloučen do `develop` jako `1101d52`.

- [x] [completed] **F-M4-OUTPUT-ROUTER-02-A — Execution a recovery kontrakt
  (designed).** ADR 0030 odděluje Git vstupy, node-local SQLite journal a
  obnovitelnou immutable cache. Request, privátní preview a approval digest
  vážou přesný plan/policy/catalog/HEAD i skutečné bajty; crash boundaries
  rozlišují připravený, `dispatching`, doloženě materializovaný a `unknown` stav.
- [x] [completed] **F-M4-OUTPUT-ROUTER-02-B — Durable executor a web-static
  renderer (implemented).** Topologický executor před každým krokem znovu
  ověřuje HEAD, Git blob, dřívější materializace, policy, descriptor, privacy a
  potvrzení. Mode-0600 SQLite drží manifesty a receipty; bounded generace se
  publikuje atomicky v mode-0700 cache mimo Git. První renderer escapuje
  nedůvěryhodný Markdown do script-free HTML a vrací bounded statický bundle.
- [x] [completed] **F-M4-OUTPUT-ROUTER-02-C — Preview, potvrzení a recovery
  surface (implemented).** Aplikační service a CLI smoke oddělují prepare od
  execute. Chybějící/stale/nevalidní vstup, neznámý adaptér a neurčitý krok
  zastaví potomky bez fallbacku či retry. Explicitní reconciliation převezme
  pouze úplnou generaci se shodným manifest hashem; jinak uzavře krok jako
  durable `unknown`.
- [x] [completed] **F-M4-OUTPUT-ROUTER-02-D — Regrese, dokumentace a předání
  (PoC validated).** Execution smoke dokončil preview i krok, zachoval HEAD a
  pracovní strom a neprovedl publikaci. Cílená sada pokryla potvrzení, stale
  HEAD, změnu policy/descriptoru, materializovaný vstup, tampering, bezpečné
  HTML, idempotenci, blokování potomků a pády před i po atomickém zveřejnění.
  Úplná sada mimo socketově omezený sandbox prošla: **487 testů OK, 25
  přeskočeno**. `py_compile` a `git diff --check` prošly bez chyby.

Reuse/adaptuje přesný katalog a DAG F-M4-OUTPUT-ROUTER-01, durable
journal/approval vzor F-M4-WORKFLOW-01 a atomickou generaci ADR 0018. Workspace
se nepoužívá k zápisu cache, publication adaptéry se nezaměňují za renderer a
ze soukromé inventury se nekopíroval kód. Nevznikl plugin framework, fronta ani
nová runtime závislost.

Omezení: PoC má jediný reviewovaný runtime adaptér `renderer.web-static@1.0` a
CLI/service surface, nikoli plnou sekci Výstupy v desktop/web UI. Julia runner,
LLM planner dispatch, prezentace, externí publikace, DNS/deploy a explicitní
uložení výsledku jako projektového artefaktu nejsou součástí dávky. Volitelné
reálné Qt/WebEngine a cílové zařízení nebyly touto lokální akceptací spuštěny.

## F-M4-OUTPUT-ROUTER-01 — Deklarativní katalog a read-only kompoziční plán — 2026-10-11

Dávka na větvi `feature/f-m4-output-router-01`, založené z `develop` `916e5ec`,
dodala staticky reviewovaný output capability katalog, read-only plan/step DAG
a aplikační review nedůvěryhodného planner návrhu. Dosažená úroveň je
**implemented / lokálně PoC validated** a akceptační podmínky dávky jsou
splněné. PR #59 byl sloučen do `develop` jako merge commit `d96fe7a`.

- [x] [completed] **F-M4-OUTPUT-ROUTER-01-A — Descriptor a fail-closed katalog
  (implemented / locally PoC validated).** Uzavřený v1 descriptor nese přesné
  capability/module revize, typované porty, šablonové hashe, role/backend
  požadavky, privacy, hranice, permissions, cost/side-effect a potvrzení.
  Statický katalog odmítá neznámá pole a verze, duplicity, symlinky, cizí
  schémata a node-local konfiguraci. První `renderer.web-static` descriptor je
  pouze lokální kompilace bez publikace, discovery nebo spuštění skriptů.
- [x] [completed] **F-M4-OUTPUT-ROUTER-01-B — Read-only plan/step DAG
  (implemented / locally PoC validated).** Plán v1 váže kanonická ID, přesný
  project commit, artifact a existující materializované snapshoty, typované
  porty a acyklické hrany. Samostatně dodaná policy je připnutá ID, revizí a
  hashem; přesná capability verze, permissions, privacy, execution boundary,
  cost a side-effect se ověřují bez dispatch, backend selection nebo fallbacku.
- [x] [completed] **F-M4-OUTPUT-ROUTER-01-C — Planner boundary a dokumentace
  (PoC validated).** Uzavřený `propose-output-plan` je pouze nedůvěryhodný
  návrh. Aplikace znovu ověří katalog, policy, HEAD a přesné trusted source
  snapshoty, sama vytvoří vysvětlení a kompatibilní alternativy a vrátí pouze
  handoff `not-authorized`. Plannerem přidané approval/execution pole se odmítne.
  Read-only smoke připne skutečný Git blob `README.md`, odmítne změněný SHA-256
  a ověří nezměněný pracovní strom; uživatelský checklist je v
  `docs/output-router-acceptance.md`.

Ověření po poslední změně kódu: cílená sada katalogu, DAG a planner boundary
**12 testů OK**; read-only smoke prošel se stavem `validated-read-only`,
`not-authorized`, odmítnutým pozměněným zdrojem a nezměněným worktree; úplná
sada **478 testů OK, 25 přeskočeno**. Python moduly prošly `py_compile` a
`git diff --check` byl čistý. Přeskočené testy vyžadují volitelný reálný
Qt/WebEngine, privátní vzorek nebo zvláštní prostředí.

Reuse/adaptuje bounded JSON parser, validační primitiva modulového manifestu,
provider-neutral role/capability kontrakty ADR 0008 a explicitní artefaktové
předání F-M4-WORKFLOW-01. Nevznikl nový plugin framework, runtime discovery ani
persistentní vrstva. Validace pouze čte a pracuje v paměti; pád nezanechá
rozpracovanou operaci.

Omezení: není integrován skutečný Ollama planner, UI, renderer execution,
runtime dostupnost, Context Manifest jednotlivých kroků, materializace, receipt,
`unknown` recovery ani publikace. Validní plán není approval. Tyto schopnosti
v době uzavření zůstávaly pro F-M4-OUTPUT-ROUTER-02; read-only checklist je
výslovně nedokládá. Pozdější výsledek této dávky je evidován výše.

## M1-LXC-DNS-TLS-01 — HTTPS přístup přes IP i DNS jméno — 2026-10-11

Dávka na větvi `feature/m1-lxc-dns-tls`, založené z `develop` `f8bc5b7`,
rozšířila přímý LXC HTTPS přístup o jednu explicitní DNS autoritu vedle IP.
Dosažená úroveň je **implemented / lokálně PoC validated** a lokální
akceptační podmínky dávky jsou splněné. PR do `develop` dosud nebyl vytvořen
ani sloučen.

- [x] [completed] **M1-LXC-DNS-TLS-01-A — Konfigurace a generování certifikátu
  (implemented).** `deploy-omnia --web-hostname` přijímá validované ASCII DNS
  jméno a generuje serverový certifikát s DNS SAN vedle loopback a aktuální
  privátní IPv4 LXC. Před opětovným použitím certifikátu kontroluje obě IP a
  DNS; instalační preflight odmítne certifikát bez požadovaného DNS SAN také v
  application-only režimu.
- [x] [completed] **M1-LXC-DNS-TLS-01-B — Přesná DNS autorita webu
  (implemented).** Systemd unit předává stejné jméno HTTPS serveru. Handler
  přijme pouze skutečnou číselnou autoritu socketu nebo přesné nakonfigurované
  `DNS:port` a u mutací vyžaduje odpovídající HTTPS Origin. Cizí Host, cizí
  Origin, wildcard a proxy hlavičky zůstávají odmítnuté.
- [x] [completed] **M1-LXC-DNS-TLS-01-C — Ověření a dokumentace (PoC
  validated).** Testy ověřují validaci jména, generované SAN/unit plány,
  shellovou syntaxi, IP/DNS Host a Origin i regrese lokálního API a routerového
  vstupu. Po poslední změně kódu prošla úplná sada **466 testů OK,
  25 přeskočeno**; Python moduly a shell prošly syntaktickou kontrolou a
  `git diff --check` byl čistý.

Reuse/adaptuje stávající TLS bootstrap, stdlib HTTPS handler a ADR 0020
release/rollback. Soukromá inventura byla zohledněna bez přenosu externího
kódu. TLS zůstává před aplikační rollback hranicí: automatická regenerace kvůli
novému SAN vytvoří novou lokální CA a vyžaduje obnovu důvěry klientů.

Omezení: na skutečném LXC nebyl v této dávce certifikát vydán ani ověřen přes
`openssl -checkip`/`-checkhost` a doménovou URL. DNS záznam, klientská důvěra,
firewall a routerová dlaždice se neměnily; cílová akceptace zůstává u M1-07-C v
BACKLOG.

## F-M3-OLLAMA-ORCH-LAN-01-FIX1 — Viditelný LAN orchestrační cíl — 2026-10-11

Dávka na větvi `fix/f-m3-ollama-lan-silent-composer`, založené z `develop`
`a9207c5`, opravila zavádějící společné web/desktop UI. Režim orchestrace
zamykal adapter na potvrzenou Ollamu, ale vždy ji označil jako „Lokální Ollama“
a nezobrazil, že binding míří do privátní sítě. Dosažená úroveň je
**implemented / lokálně PoC validated** a akceptační podmínky dávky jsou
splněné. Dávka byla následně doručena do `develop` jako PR #57, merge commit
`f8bc5b7`.

- [x] [completed] **F-M3-OLLAMA-ORCH-LAN-01-FIX1-A — Přesný cíl v composeru
  (implemented).** Adapter se podle potvrzeného bindingu označí „Ollama v
  privátní síti“ nebo „Ollama na tomto uzlu“. Samostatný živý stav ukáže model,
  skutečnou hranici a endpoint; bez bindingu přímo vyžádá jeho nastavení.
  Backend dál dostává přesné `binding_id` a `binding_revision`; privacy, TLS pin
  ani dispatch kontrakt se nezměnily.
- [x] [completed] **F-M3-OLLAMA-ORCH-LAN-01-FIX1-B — Regresní pokrytí
  (PoC validated).** Tři cílené testy rendereru prošly a ověřují LAN označení,
  přesný zobrazený cíl i zachování identity bindingu.
- [x] [completed] **F-M3-OLLAMA-ORCH-LAN-01-FIX1-C — Závěrečné ověření.** Po
  poslední změně kódu prošla úplná sada **464 testů OK, 25 přeskočeno**;
  JavaScript prošel syntaktickou kontrolou přes Node.js a `git diff --check`
  byl čistý.

Omezení: oprava dosud nebyla nasazena ani ručně přijata v prohlížeči na Turrisu.
Živě bylo před opravou pouze ověřeno, že server obsluhuje frontend z PR #56.

## F-M3-OLLAMA-ORCH-LAN-01 — Orchestrace přes privátní síťovou Ollamu — 2026-10-11

Dávka na větvi `feature/f-m3-ollama-orch-lan-01`, založené z `develop`
`3f34fa7`, rozšířila orchestration režim o explicitně vybraný TLS připnutý
`private-network` Ollama binding. Dosažená úroveň je **implemented / lokálně PoC
validated** a akceptační podmínky dávky jsou splněné. Dávka byla následně
doručena do `develop` jako PR #56, merge commit `a9207c5`.

- [x] [completed] **F-M3-OLLAMA-ORCH-LAN-01-A — Inventura, reuse a kontrakt
  (designed).** Reuse/adaptuje se jediný `OllamaBinding`, TLS pinning/probe,
  `ChatRunChoice`, `ContextBuilder`, `OllamaRuns` a task router. Nevznikl druhý
  transport, backend pool, implicitní fallback ani nový persistentní store.
- [x] [completed] **F-M3-OLLAMA-ORCH-LAN-01-B — Backendová režimová policy
  (PoC validated).** LAN orchestrace vyžaduje přesné `binding_id` a revizi
  aktuálního potvrzeného bindingu. Chybějící či stale výběr a změna konfigurace
  během přípravy kontextu se odmítnou před dispatch; `ContextBuilder` dál
  odmítá `local-only`. Každý vědomý nový pokus má nové manifest/run ID a
  durable `unknown` se automaticky neopakuje.
- [x] [completed] **F-M3-OLLAMA-ORCH-LAN-01-C — Společné web/desktop UI
  (implemented).** Renderer posílá pro orchestration přesnou identitu bindingu,
  zobrazuje model, skutečnou boundary a endpoint a neblokuje potvrzenou LAN
  Ollamu. Při změně cíle nebo privacy odmítnutí zachová zadání pro vědomý nový
  běh; nevybírá náhradní model ani provider.
- [x] [completed] **F-M3-OLLAMA-ORCH-LAN-01-D — Restart, regrese a dokumentace
  (PoC validated).** Cílená sada režimové policy, služby a rendereru prošla
  **59 testů OK, 2 přeskočeny** v prostředí s povoleným loopbackem. Nové testy
  pokrývají LAN běh, restart, stale a souběžně změněný binding, `local-only` a
  durable `unknown` bez druhého transportu. Úplná sada po poslední změně kódu
  prošla **463 testů OK, 25 přeskočeno**; JavaScript prošel `node --check`.

Omezení: automatické testy používají řízený transport. Skutečný LAN Ollama
server, TLS reverse proxy, certifikátový pin, firewall a dostupnost po restartu
fyzického stroje nebyly v této dávce živě ověřeny. Známé neblokující
`ResourceWarning` testovacích SQLite spojení zůstaly beze změny.

## UX-UNIFIED-02D — Společný editor dokumentu a TODO — 2026-10-11

Dávka na větvi `feature/ux-unified-02d-document-todo-editor`, založené z
`develop` `571b430` po doručení UX-UNIFIED-01 jako PR #53, dokončila společný
editor pro server i desktop. Dosažená úroveň je **implemented / PoC validated**
a akceptační podmínky jsou splněné. Dávka byla následně doručena do `develop`
jako PR #54, merge commit `0ce9cb7`.

- [x] [completed] **UX-UNIFIED-02D-A — Inventura, reuse a recovery kontrakt
  (designed).** Existující `ArtifactActions`, `Artifacts`, Workspace journal,
  Git CAS a receipt pokrývají nový i existující dokument. Nový zápis před
  přípravou journalu znovu autorizuje projekt a ověří `base_head`; cizí HEAD,
  pending operace a síťově nepřípustné `local-only` projekty selžou zavřeně.
  Draft před potvrzením je výslovně jen volatilní stav rendereru.
- [x] [completed] **UX-UNIFIED-02D-B — Vytvoření nového dokumentu
  (PoC validated).** Záložka Podklady má společné tlačítko Nový dokument.
  Renderer drží stabilní artifact/operation ID, přesný uzavřený save payload a
  po úspěchu znovu načte validovaný projekt; retry stejné operace využije
  receipt bez druhého commitu.
- [x] [completed] **UX-UNIFIED-02D-C — Hlavní TODO (PoC validated).** Záložka
  Úkoly společně vytváří chybějící seznam a upravuje existující přes
  deterministické `main_todo_id`. Projektová projekce ID explicitně vrací a
  nevznikla paralelní storage ani zvláštní zapisovací cesta.
- [x] [completed] **UX-UNIFIED-02D-D — Dirty draft a odstranění Qt editoru
  (PoC validated).** Změněný formulář i nezavřený pokus jsou chráněné při
  zavření a navigaci; odmítnutý zápis zachová text i retry ID. Obecný Qt
  `EditorDialog`, jeho toolbarové akce a fragment hlavního TODO byly odstraněny;
  desktop-only systémové dialogy zůstaly beze změny.
- [x] [completed] **UX-UNIFIED-02D-E — Závěrečné ověření a předání.** Cílené
  doménové a HTTPS testy ověřily create, stale HEAD, receipt retry, RBAC,
  editaci a smazání. Skutečný Qt/WebEngine klient přes HTTPS vytvořil běžný
  dokument i hlavní TODO a ověřil zachování odmítnutého dirty draftu. Po
  poslední opravě přesného `{operation_id, document}` payloadu prošla úplná
  sada **461 testů OK, 25 volitelných testů přeskočeno**; výsledný JavaScript
  prošel `node --check` a `git diff --check` byl čistý.

Crash/recovery hranice zůstaly podle ADR 0003 a ADR 0016: před potvrzením není
draft durable, po potvrzení journal vlastní záměr a bajty, Git commit je
autoritativní, index lze obnovit z HEAD a receipt dělá retry idempotentní.
Skutečný Turris/LXC deployment v této dávce proveden nebyl; browserová akceptace
proběhla proti dočasnému lokálnímu HTTPS serveru a projektu.

## UX-UNIFIED-01 — Jednotný webový a desktopový frontend — 2026-10-11

Dávka na větvi `feature/ux-unified-01-shared-frontend`, založené z `develop`
`7bb4f5e`, dosáhla úrovně **implemented / PoC validated** a její feature
akceptace je splněná. Jeden společný frontend nyní obsluhuje web i desktopový
WebEngine; odlišné zůstávají pouze autentizační a přesně vymezené capability
adaptéry. Dávka byla doručena do `develop` jako PR #53, konsolidovaný merge
commit `571b430`.

- [x] [completed] **UX-UNIFIED-01-A — Jeden zdroj shellu a explicitní adaptéry.**
  Web a desktop servírují shodné HTML/CSS bez textových transformací assetů.
- [x] [completed] **UX-UNIFIED-01-B — Per-chat akční menu a strom vláken.**
  Zařazené a nezařazené chaty tvoří jeden strom; akce vlákna jsou v jeho menu a
  primární Nové vlákno/Nastavení backendu zůstávají nad seznamem.
- [x] [completed] **UX-UNIFIED-01-C — Qt/PySide inventura.** Hranice společného
  UI a skutečně desktop-only integrací je v `docs/ui-capability-inventory.md`.
- [x] [completed] **UX-UNIFIED-01-D — Společný import zdroje.** Samostatná
  stránka používá `Sources`/Workspace operation ID, journal a receipt; původní
  Qt importní dialog byl odstraněn.
- [x] [completed] **UX-UNIFIED-01-E — Společná historie a akce dokumentu.**
  Menu dokumentu otevírá HEAD-bound historii, editaci/přejmenování, potvrzené
  smazání a Kopírovat ID. Qt `HistoryDialog` byl odstraněn; zápisy dál používají
  `Artifacts`, expected HEAD, journal a idempotentní receipt.
- [x] [completed] **UX-UNIFIED-01-F — Společné vytvoření projektu.** Formulář
  vyžaduje backendem vydaný preview plán a potvrzení. Web používá pouze
  nakonfigurovaný projects root a administrátorské RBAC; desktopový systémový
  picker vydává operation-scoped in-process capability. Qt `CreationDialog` a
  paralelní toolbar vstup byly odstraněny, `ProjectCreation` recovery zůstalo
  autoritativní.
- [x] [completed] **UX-UNIFIED-01-G — Závěrečné předání.** Dokončená evidence
  byla přesunuta sem, navazující `UX-UNIFIED-02D` byl zpřesněn v BACKLOG a TODO
  bylo vyčištěno na čekání na doručení jediného PR.

Crash/recovery hranice nebyly nahrazeny UI stavem. Read-only historie a otevření
editoru zůstávají HEAD-bound; dokumentové zápisy používají `Artifacts`/Workspace
journal a projektové vytvoření uzlový journal `ProjectCreation`. Cizí HEAD,
pracovní změna nebo změněný cíl se odmítají bez přepsání.

Ověření po poslední aplikační změně: společný i výsledný webový JavaScript
prošel `node --check`; cílená sada adaptéru vytvoření, doménové služby, desktopu
a web serveru prošla **64 testů OK, 6 volitelných přeskočeno**. Úplná sada
`python3 -m unittest discover -s tests -q` prošla **458 testů OK,
25 volitelných native/package/live testů přeskočeno**. `git diff --check` byl
čistý. Známé neblokující `ResourceWarning` testovacích SQLite spojení zůstaly
beze změny.

Omezení: skutečný Qt/WebEngine průchod společným vytvořením projektu, HTTPS a
Turris/LXC deployment nebyly v této dávce provedeny. Vytvoření nového dokumentu
a hlavního TODO a odstranění posledního obecného Qt `EditorDialog` jsou
navazující samostatná feature `UX-UNIFIED-02D`; NotebookLM zůstává
`UX-UNIFIED-02C`.

## WEB-RUNTIME-01 — Úplná inicializace služeb webového serveru — 2026-10-11

Dávka na větvi `feature/web-runtime-01-service-wiring`, založené z `develop`
`7339336` po začlenění F-M2-CHAT-03 jako PR #51, opravila potvrzenou runtime
mezeru webového serveru. Dosažená úroveň je **implemented / PoC validated** a
akceptační podmínky jsou splněné. Dávka byla začleněna do `develop` jako PR #52,
merge commit `7bb4f5e`.

- [x] [completed] **WEB-RUNTIME-01-A — Inventura a reuse runtime wiring
  (designed).** Desktop již používal `SummaryService`, `ExtractionService` a
  `MetadataSuggestionService` nad společným `ChatService.state_dir`; webový
  handler vystavoval jejich endpointy bez odpovídajících atributů serveru.
  Reuse tohoto wiring nevyžadoval nový framework, store ani ADR.
- [x] [completed] **WEB-RUNTIME-01-B — Webový service wiring (implemented).**
  `make_server()` inicializuje stejné tři služby, sdílí s nimi chat state root
  a zachovává jejich oddělené task tabulky, backendové run záznamy a stávající
  Workspace publication lifecycle.
- [x] [completed] **WEB-RUNTIME-01-C — Regrese zděděných endpointů
  (PoC validated).** Skutečný HTTPS `WebServer` ověřuje reálný `status` a
  routing `preview`/`publish` pro summary, extraction a metadata suggestions;
  všech devět endpointů má runtime službu a shodnou state-dir vazbu s desktopem.
- [x] [completed] **WEB-RUNTIME-01-D — Závěrečné předání.** Stav PR #51 byl
  opraven v TODO/BACKLOG/roadmapě, tato dávka byla archivována a navazující
  pořadí připravuje UX-UNIFIED-01, F-M3-OLLAMA-ORCH-LAN-01 a
  F-M4-OUTPUT-ROUTER-01 jako samostatné feature.

Nevznikla nová operace přes persistentní vrstvy ani nová crash boundary.
Konstruktory pouze vážou existující služby; jejich durable task journals,
backendové run stavy a potvrzené Workspace publikace zachovávají dosavadní
recovery kontrakty.

Ověření po finální změně: cílená sada
`python3 -m unittest tests.test_web_server tests.test_summary_service
tests.test_extraction_service tests.test_metadata_suggestion_service -q`
prošla: **40 testů OK, 2 volitelné WebEngine testy přeskočeny**. Úplná sada
`python3 -m unittest discover -s tests -v` prošla: **451 testů OK,
27 volitelných native/package/live testů přeskočeno**; známé neblokující
`ResourceWarning` na testovací SQLite spojení zůstaly beze změny.

Omezení: opravený release nebyl nasazen na skutečný Turris/LXC a endpointy tam
nebyly znovu uživatelsky ověřeny. Lokální HTTPS regrese není důkaz živého
deploymentu. Obecná unifikace webového a desktopového frontendu je samostatná
navazující dávka UX-UNIFIED-01.

## F-M2-CHAT-03 — Správa a restartová akceptace lokálních vláken — 2026-10-11

Dávka na větvi `feature/f-m2-chat-03-thread-lifecycle`, založené z `develop`
`9ea0fb0` po začlenění F-M3-OLLAMA-ROBUST-01 jako PR #50, doplnila vědomý
lifecycle lokálně perzistentních chatových vláken. Po uživatelské změně
akceptace přidala seznam chatů do levého panelu. Dosažená úroveň je **PoC
validated** a akceptační podmínky feature jsou splněné. Dávka byla začleněna
do `develop` jako PR #51, merge commit `7339336`.

- [x] [completed] **F-M2-CHAT-03-A — Inventura, reuse a recovery kontrakt
  (designed).** ADR 0008 a reuse katalog vymezují vlastníka, read-only preview,
  blokaci aktivních a `unknown` účinků, durable crash boundaries a zachování
  již publikované Git historie. Adaptují existující `ChatThreads`,
  `TaskOutcomes`, `ExternalDispatches`, backendové run journals a bezpečné
  textové sdílené UI.
- [x] [completed] **F-M2-CHAT-03-B — Koordinovaný backendový lifecycle
  (implemented).** `thread-lifecycle.sqlite` durable váže operation ID,
  očekávanou revizi a digest přesného plánu. Deletion marker uzamkne běžné
  čtení a mutace vlákna; approval, task outcome, Ollama/OpenAI run a thread
  stores se odstraňují po idempotentních krocích a stav po restartu automaticky
  dokončí stejnou potvrzenou operaci. Omezený receipt neuchovává obsah zpráv.
- [x] [completed] **F-M2-CHAT-03-C — Uživatelská správa vláken
  (implemented).** Sdílené desktop/web API a UI umožňuje nové vlákno, vědomé
  otevření, rozlišení projektových/nepřiřazených a aktivních/archivovaných
  vláken, archivaci a dvoukrokové smazání. Preview vypíše lokální dopady a
  zachované publikované snapshoty/výstupy; nedůvěryhodný obsah se vkládá pouze
  přes `textContent`.
- [x] [completed] **F-M2-CHAT-03-D — Restart, souběh a závěrečná akceptace
  (PoC validated).** Testy pokrývají více vláken, oddělení vlastníků, stale
  revizi/preview, aktivní a `unknown` blokace, opakování po všech sedmi
  potvrzených hranicích, automatickou obnovu přes `ChatService.status`,
  idempotentní receipt a nezměněný publikovaný Git snapshot.
- [x] [completed] **F-M2-CHAT-03-E — Seznam chatů v levém panelu
  (implemented; změna akceptace 2026-10-11).** Třetí přístupná sidebar záložka
  „Chaty“ odděluje zařazená a nezařazená vlákna. Položka bezpečně textově uvádí
  režim, stav, počet zpráv a vazbu k projektu; kliknutí je vědomé navázání,
  přepne hlavní panel na chat a v mobilním draweru zavře navigaci. Klávesnicová
  navigace tablistu se odvozuje od skutečného počtu záložek. Nově vytvořené,
  archivované, odstraněné i dodatečně zařazené vlákno aktualizuje skupiny bez
  znovunačtení projektu.
- [x] [completed] **F-M2-CHAT-03-F — Pevný sidebar a návrat k projektům
  (implemented; změna akceptace 2026-10-11).** Samotný sidebar má pevnou výšku
  viewportu a nesroluje se. V dostupném prostoru se samostatně s overscroll
  containmentem posouvají pouze seznamy projektů a obsahové seznamy aktuální
  záložky; jejich nadpisy, stav, tablist, globální nastavení a informace o uzlu
  zůstávají na místě. Jediné tlačítko „Seznam projektů“ bylo přesunuto nahoru
  před záložky a na mobilu zavírá drawer se standardní obnovou focusu.
- [x] [completed] **F-M2-CHAT-03-G — Webová inicializace po přesunu navigace
  (PoC validated; ad-hoc regresní oprava 2026-10-11).** Hlášení ze skutečného
  Turris deploymentu odhalilo, že webová transformace stále vkládala formulář
  importu podle již přesunutého tlačítka `back-projects`. Chybějící formulář
  ukončil JavaScript na registraci listeneru a katalog zůstal na „Načítám
  projekty…“, přestože persistentní Git projekty, chatová SQLite data i
  autentizované HTTPS API byly zdravé. Import se nyní vkládá podle stabilního
  kontejneru projektového pohledu; strukturální test hlídá právě jednu instanci
  formuláře a skutečný WebEngine login → katalog průchod regresi reprodukoval
  před opravou a po opravě prošel.

Crash kontrakt: preview je read-only; confirm nejprve durable uloží přesný plán.
Pád před commitem nemění uživatelský stav. Po commitu marker uzamkne vlákno a
journal se posouvá až po durable commitu každého podporovaného store. Opakování
po pádu proto nemaže jiný nově naplánovaný rozsah. Projektový Git je po celou
operaci pouze čtenou a zachovanou autoritativní historií. „Úplné odstranění“
znamená úplné odstranění podporovaného aplikačního stavu, nikoli forenzní
přepsání SQLite stránek nebo média.

Závěrečné lifecycle ověření:
`python3 -m unittest tests.test_chat_threads tests.test_thread_lifecycle
tests.test_chat_service tests.test_desktop -q` — **68 testů OK, 2 volitelné
testy přeskočeny**. Následné UI ověření
`python3 -m unittest tests.test_desktop tests.test_web_server -q` prošlo:
**32 testů OK, 4 volitelné testy přeskočeny**. Úplná sada
`python3 -m unittest discover -s tests -q` po poslední sidebar změně prošla: **450 testů
OK, 27 volitelných native/package/live testů přeskočeno**. Běh vypsal známé
neblokující `ResourceWarning` na neuzavřená testovací SQLite spojení.

Po regresní opravě webové inicializace prošel znovu cílený běh 32 testů se
4 volitelnými skipy, samostatný skutečný WebEngine login → katalog smoke test
1/1 a následná úplná sada **450 testů OK, 27 volitelných testů přeskočeno**.
Skutečný Turris měl před opravou potvrzená neporušená data a funkční API; nový
release s opravou na zařízení zatím nasazen ani uživatelsky potvrzen nebyl.

Omezení: skutečný klikací Qt/WebEngine průchod lifecycle panelem ani novou
sidebar záložkou nebyl proveden; login a načtení katalogu byly po opravě
ověřeny skutečným WebEngine testem a zbytek UI má strukturální a HTTP/API
regresní testy.
Aplikace předpokládá jeden backendový proces a její HTTP server serializuje
požadavky; nekooperující přímý zapisovač do node-local SQLite stores není
součástí tohoto PoC. Požadavek na orchestration přes explicitní private-network
Ollamu zůstává samostatnou feature `F-M3-OLLAMA-ORCH-LAN-01` v BACKLOG;
současný režim stále vyžaduje `same-node`.

## F-M3-OLLAMA-ROBUST-01 — Odolnost lokálního AI běhu — 2026-10-11

Dávka na větvi `feature/f-m3-ollama-robust-01`, založené z `develop`
`2c9b1b2` po začlenění UX-MOBILE-01 jako PR #49, rozšířila lokální Ollama běh
o přesnou diagnostiku, bezpečné private-network připojení, vědomý nový pokus a
provozní LAN/restartovou akceptaci. Dosažená úroveň je **PoC validated** a
všechny akceptační podmínky dávky jsou splněné. Dávka byla začleněna do
`develop` jako PR #50, merge commit `9ea0fb0`.

Node-local `ollama-binding.json` zůstává autoritou konfigurace a
`ollama-runs.sqlite` autoritou stavu dispatchu. Před prvním síťovým bajtem je
durable `dispatching`; nejistota po této hranici končí `unknown` bez
automatického retry. Známé odmítnutí před odesláním nebo validovaná chyba končí
`failed`. Vědomý nový pokus používá nové run ID a zachované vstupy. Do
projektového Gitu se neukládají credentials, binding ani rozpracovaný běh.

- [x] [completed] **F-M3-OLLAMA-ROBUST-01-A — Kontrakt chyb, LAN onboarding
  a reuse (designed).** `docs/ollama-lan.md`, ADR-0008 a reuse katalog vymezují
  topologii Workspace → HTTPS proxy → loopback Ollama, numerickou privátní
  adresu, stabilní target ID, pin certifikátu, firewall, rotaci pinu a obnovu po
  restartu. Basic Auth ani mTLS nebyly bez samostatného credential lifecycle
  zavedeny.
- [x] [completed] **F-M3-OLLAMA-ROBUST-01-B — Diagnostika transportu a
  healthcheck (implemented).** Provider-neutral diagnostika rozlišuje
  nedostupnost, timeout, TLS/pin, HTTP, přerušenou či příliš velkou odpověď a
  neplatný JSON/Ollama envelope. Read-only test kandidátního bindingu používá
  omezený `GET /api/tags`, neposílá projektová data a nepotvrzuje konfiguraci.
- [x] [completed] **F-M3-OLLAMA-ROBUST-01-C — Vědomý nový pokus a UI
  (implemented).** Lokální workflow zachová draft a výběr kontextu, zobrazí
  bezpečnou konkrétní diagnostiku a nový run vytvoří pouze explicitní akcí.
  Externí preview/provider zůstává oddělený; LAN orchestrace a `local-only` se
  odmítnou před dispatch a žádný fallback se nespouští automaticky.
- [x] [completed] **F-M3-OLLAMA-ROBUST-01-D — Restart, souběh a závěrečná
  akceptace (PoC validated).** Testy pokryly pomalou a neplatnou odpověď,
  chybějící model, chybný pin, pád před i po durable hranici, restart, souběh,
  vědomý nový run a zákaz `local-only` na LAN. Skutečný Workspace na Omnii
  získal katalog i odpověď modelu přes připnutou LAN TLS Ollamu. Opravený
  `--update-only` deploy čeká na HTTPS readiness až 45 sekund, při selhání
  vypíše stav/journal a bezpečně vrátí předchozí release. Uživatel potvrdil
  úspěšný deploy, webovou službu a modelovou odpověď. Po restartu AI hostitele
  byly aktivní Open WebUI, ComfyUI a TLS proxy, kontejner `open-webui` byl
  healthy, Open WebUI API `0.12.0` a katalog modelů dostupné; uživatel potvrdil
  skutečnou odpověď modelu. Následný firewallový test potvrdil očekávané
  zdrojové omezení přístupu na port `11443`.
- [x] [completed] **F-M3-OLLAMA-ROBUST-01-E — Tolerantní fingerprint a
  neaktivní koncept nastavení (implemented; ad-hoc požadavek uživatele).** Běžný
  OpenSSL SHA-256 fingerprint se kanonizuje. Omezený koncept se ukládá atomicky
  v samostatném node-local souboru s módem 0600, přežije restart, neobsahuje
  credentials a nemění ani nepoužívá poslední platný binding.

Závěrečné ověření po poslední aplikační změně: cílené transportní, UI, deploy,
RBAC a packaging testy prošly. Úplná sada
`python3 -m unittest discover -s tests -v` byla nejprve spuštěna v omezeném
sandboxu, kde 36 lokálních HTTP/HTTPS testů selhalo pouze na zákazu socketu
`PermissionError: [Errno 1] Operation not permitted`. Stejná sada následně v
povoleném prostředí prošla: **443 testů OK, 27 volitelných native/package/live
testů přeskočeno**. Běh vypsal neblokující `ResourceWarning` na neuzavřená
testovací SQLite spojení. Dokumentační předání po tomto běhu aplikační kód ani
testy neměnilo.

Omezení: přístup na LAN proxy je založen na firewallovém omezení a připnutém
certifikátu, nikoli na aplikačním Basic Auth či mTLS. Konkrétní pravidla
firewallu spravuje hostitel mimo Workspace Git. Streamování lokální Ollama
odpovědi bylo předáno jako samostatná budoucí dávka
`F-M3-OLLAMA-STREAM-01` v BACKLOG; sjednocení webového runtime wiring bylo
později dokončeno v dávce `WEB-RUNTIME-01` evidované výše. Ani jedna změna
nebyla skrytou součástí této akceptované feature.

## UX-MOBILE-01 — Responzivní web pro telefon — 2026-10-09

Dávka na větvi `feature/ux-mobile-01-responsive-web`, založené z
`develop` `519dce8` po merge PR #48, přizpůsobila jediné stávající sdílené
HTML/CSS/JS úzkému dotykovému viewportu. Dosažená úroveň je PoC validated
a všechny akceptační podmínky dávky jsou splněné. Evidence byla při
závěrečném předání přesunuta z TODO. Dávka byla začleněna do `develop` jako
PR #49, merge commit `2c9b1b2`.

- [x] [completed] **UX-MOBILE-01-A — Mobilní navigace a layout
  (implemented).** Původní pevný levý sloupec nahradil na viewportu do 640 px
  otevíratelný panel pro projekty, úkoly, podklady a nastavení. Zavřený panel
  je `inert`, Escape jej zavře a vrátí focus jedinému otevíracímu tlačítku;
  desktopové rozložení zůstalo zachované.
- [x] [completed] **UX-MOBILE-01-B — Prioritní dotykové toky
  (implemented).** Katalog, import NotebookLM i jednotlivého zdroje, náhled
  artefaktu, taby, formuláře a potvrzovací bloky se vejdou do hlavního obsahu
  bez horizontálního overflow. Dotykové prvky mají nejméně 44 px, dlouhé
  názvy, chyby a bezpečné textové náhledy se zalamují.
- [x] [completed] **UX-MOBILE-01-C — Přístupnost a regresní testy
  (PoC validated).** Strukturální test hlídá ARIA vazby, inert/focus kontrakt,
  Escape, rozměry dotykových prvků, vnitřní rolování tabů a omezení importního
  preview. Bezpečný renderer nadále vkládá importovaný obsah pouze jako text.
- [x] [completed] **UX-MOBILE-01-D — Telefonní smoke a závěrečné
  ověření (PoC validated).** Skutečný Qt/WebEngine na 390 × 844 prošel
  přihlášením, přípravou a potvrzením NotebookLM plánu, katalogem,
  otevřením projektu, klávesnicovým zavřením panelu a návratem focusu,
  výběrem podkladu a jeho náhledem bez dokumentového overflow.

Cílená webová, preview a katalogová sada: **32 testů, 27 prošlo a 5
volitelných WebEngine testů bylo přeskočeno**. Samostatný mobilní WebEngine
smoke prošel; jeden předchozí pokus jednorázově timeoutoval při
startu/přihlášení Chromium a následující běh chybu nereprodukoval. Úplná
sada `python3 -m unittest discover -s tests -v` prošla: **429 testů OK, 27
volitelných testů přeskočeno**. Před dokumentačním předáním prošel také
`git diff --check`; po čistě dokumentačním předání se aplikační sada
neopakovala.

Omezení: smoke použil skutečný WebEngine s telefonním viewportem, nikoli
fyzický telefon nebo jeho mobilní prohlížeč. Nativní mobilní aplikace,
backendová API, RBAC/privacy hranice, importní autorita a persistentní
Workspace/journal kontrakty se neměnily; nevznikly nové crash boundaries.

## IMP-02 — Import kompletního projektu z NotebookLM — 2026-10-08

Dávka na větvi `feature/imp-02-notebooklm-project-import`, založené z
`develop` `8854d69`, dodala import jednoho kompletního osobního NotebookLM
notebooku ze skutečného Google Takeout TGZ jako nového Workspace projektu.
Dosažená úroveň je PoC validated a uživatel 2026-10-08 potvrdil všechny
zbývající kroky fyzické akceptace: vytvoření trvalého projektu přes běžné UI,
jeho otevření po běžném restartu a použitelnost zdrojů, výstupů, vztahů a
náhledů. Evidence byla při závěrečném předání přesunuta z TODO. Jediný PR do
`develop` zatím nebyl vytvořen; push ani merge nebyly provedeny.

„Kompletní“ znamená vše doložené skutečným exportem osobní Google AI edice,
nikoli domyšlený obsah nebo Enterprise API. Přijatý bundle je před potvrzením
jen bounded node-local vstup. Potvrzení váže přesný hash, formát, verzi
importéru, cílovou cestu, privacy a kanonický plán. `ProjectCreation` durable
stageuje validovaný seed, publikuje jediný počáteční commit a po pádu dokončí
stav, index a registraci ze stage bez opětovné potřeby Takeoutu. Retry stejné
operace vrací tentýž receipt, projekt UUID a commit; cizí cesta, změněný plán
nebo bundle a konflikt identity se odmítnou. Reuse adaptoval `ProjectCreation`,
`Sources`, provenance v2, source immutability, Workspace/Journal/Index,
bezpečný preview a desktop/web RBAC. Nevznikl druhý Git writer, index ani DB.

- [x] [completed] **IMP-02-A — Edice, skutečný vzorek, kontrakt a reuse
  (designed).** Potvrzena byla osobní edice přes Google One a skutečný Takeout
  s 243 bezpečnými členy a šesti notebooky. ADR 0029 vymezuje
  source/artifact/chat mapping, manifest, limity, privacy, duplicate pravidla a
  recovery. Vzorek poskytuje zejména HTML/JSON reprezentace, nikoli původní
  binární soubory; chybějící notes a nerozřešitelné artifact source UUID se
  hlásí. Enterprise API, scraping, session cookies, vykonání HTML a spojování
  pouze podle názvu jsou mimo rozsah.
- [x] [completed] **IMP-02-B — Bounded parser a přesný preview
  (implemented).** Fail-closed TGZ parser zachovává bundle a původní soubory,
  nic nevykonává a před potvrzením rozlišuje importované, nepodporované a
  chybějící části. Testy pokryly traversal, odkazy, case-fold kolizi, nested
  archiv, neznámá pole/kategorii, orphan obsah, script v chatu, poškozený gzip,
  limity a změnu archivu/digestu. Skutečný vzorek prošel pro všech šest
  notebooků: 113 sources, tři výstupy, jeden chat a jedna sada discovered
  sources.
- [x] [completed] **IMP-02-C — Obnovitelné vytvoření celého projektu a UI
  (implemented).** Desktop nabízí nativní dvoukrokový dialog; webový tok je
  node-admin only, používá server-local TGZ a nepovoluje `local-only`. Přesné
  exportní bajty jsou immutable sources, odvozený report a metadata jsou
  oddělené snapshots. Testy všech creation hranic, restartu, retry a kolizí
  zachovaly jediný projekt a commit; nový operation ID před potvrzením ukáže
  shodné existující importy.
- [x] [completed] **IMP-02-D — Reálný workflow, regrese a dokumentace
  (PoC validated).** Opt-in test importoval největší skutečný notebook s
  22 895 488 deklarovanými bajty jako 69 artefaktů / 138 souborů v jediném
  commitu, znovu jej otevřel a ověřil shodný receipt při retry. HTML se
  převádí do bounded Markdownu bez předání značek rendereru; JSON se zobrazuje
  v Markdown code blocku bez ztráty polí. Původní bajty zůstávají beze změny.
  Uživatelská akceptace následně potvrdila trvalý UI projekt i jeho běžné
  použití po restartu.

Ověření před fyzickou akceptací: cílených 22 testů prošlo se třemi volitelnými
grafickými skipy; samostatný offscreen Qt/WebEngine smoke zobrazil Markdown,
HTML text, JSON, PNG i PDF. Opt-in test skutečného notebooku ověřil také
odvozené Markdown náhledy HTML a JSON. Úplná sada
`python3 -m unittest discover -s tests -v` prošla: **427 testů OK, 26 opt-in
testů přeskočeno**. Tehdejší `git diff --check` prošel. Při závěrečném předání
se měnila pouze dokumentace, proto se aplikační sada neopakovala.

Omezení: osobní Takeout neposkytl notes ani původní binární bajty za HTML/JSON
reprezentacemi, proto je import nevymýšlí. Přímý NotebookLM konektor,
Enterprise API, průběžná synchronizace, zápis zpět a automatické odesílání
importovaných dat LLM nejsou součástí dávky. Navazující požadavek `IMP-01` na
explicitní jednorázový výběr podkladů z Google Drive byl sloučen do existující
položky BACKLOG a zůstává samostatnou budoucí feature.

## F-M4-WORKFLOW-01 — Artifact-based creator/opponent handoff — 2026-10-07

Dávka na větvi `feature/f-m4-workflow-01-artifact-handoff` dodala první
deterministicky řízený creator → opponent workflow. Dosažená úroveň je PoC
validated a všechny akceptační podmínky dávky jsou splněné. Evidence byla při
závěrečném předání přesunuta z TODO. PR #47 byl 2026-10-07 sloučen do `develop`
jako `8854d69`.
Větev vznikla 2026-10-06 z `develop` `da449bc` po začlenění F-M3-MEDIA-01 v
PR #46.

Projektový Git je autoritou až pro samostatně potvrzenou publikaci. Workflow,
step/run záznamy, přesné Context Manifesty, materializovaný mezivýstup a
approval zůstávají node-local durable stav mimo projektový Git a nejsou
obnovitelným indexem. Každý backendový run zachovává vlastní
`dispatching`/`unknown` hranici: pád po odpovědi nesmí vyvolat druhý providerový
účinek, handoff se váže na uložené bajty/hash a publikace obnovuje stejné
Workspace operation ID. Změna HEAD, vstupů, policy, oprávnění, role, bindingu
nebo mezivýstupu ruší starý souhlas a vyžaduje vědomě nový workflow. Reuse
adaptoval `ContextBuilder`, `RoleRegistry`, backendové adaptery, durable vzor
`SummaryTasks`, Workspace recovery, bezpečný Markdown preview a existující
desktop/web RBAC; `ChatThreads`, nový agent framework, fronta, provider pool,
druhý Git writer, projektový index nebo vektorová DB byly pro tuto dávku
odmítnuty.

- [x] [completed] **F-M4-WORKFLOW-01-A — Kontrakt workflow, isolation a reuse
  (designed).** ADR 0008 vymezil právě jeden creator a nejvýše jeden opponent
  krok, samostatná workflow/step/run/manifest ID a oddělená potvrzení dispatch,
  handoff a publikace. Creator output je neměnný bounded UTF-8 Markdown se
  SHA-256; opponent dostává jen jeho uložené bajty a nula až 64 explicitně
  vybraných artefaktů. Privacy je nejpřísnější průnik skutečných vstupů a
  execution boundary se nesmí rozšířit. Vlastní mode-0600 SQLite workflow
  journal je oddělený od backendových run journalů a Workspace autority.
  Kontrakt zahrnuje neměnný výstup do 1 MiB, přesnou instruction/revision,
  formát, privacy/provenance a approval digest; opponent nedostává creator
  prompt, chat ani celý creator kontext. `local-only` nesmí bez samostatné
  oprávněné reklasifikace opustit lokální hranici důvěry.
- [x] [completed] **F-M4-WORKFLOW-01-B — Durable dvoukrokový orchestrátor
  (implemented).** `RoleWorkflows` a `RoleWorkflowService` drží kanonický
  request, preview, manifest, payload, approval digest, bounded výstup a stavy
  obou kroků. Před dispatch se znovu autorizují HEAD, RBAC, binding i přesné
  bajty. Restart převezme doložený úspěch bez druhého providerového účinku;
  `dispatching`/`unknown` se automaticky neopakují. Runtime role `opponent-v1`
  nemění projektový Git ani oprávnění.
  Cílených 29 souvisejících testů prošlo mimo socketově omezený sandbox;
  tehdejší úplná sada prošla v rozsahu 392 testů s 22 přeskočenými volitelnými
  native/integration smoke testy. Skutečný Ollama dispatch byl odložen do části
  D, nikoli vydáván za ověřený už v části B.
- [x] [completed] **F-M4-WORKFLOW-01-C — UI, opponent preview a publikace
  (implemented).** Desktop a oprávněný web zobrazují oba kroky, přesné requesty,
  explicitní zdroje, role, binding/model, privacy a textově vykreslené
  nedůvěryhodné výsledky. Creator dispatch, opponent handoff/dispatch a
  publikace mají samostatná potvrzení. Web váže actora na projektové write RBAC,
  odmítá `local-only` a nemůže podstrčit endpoint či pin. Publikace přes
  Workspace je idempotentní a zapisuje workflow provenance bez promptu,
  mezivýstupu, endpointu či TLS pinu.
  Oba targety musí být uložený node-local Ollama binding nebo jeho
  deterministická per-run model revision. Workflow journal fixuje publish
  request/receipt a schéma 1 migruje na 2 v jediné SQLite transakci. Cílených
  33 workflow/UI/web testů prošlo se třemi volitelnými native skipy,
  JavaScript prošel `node --check` a tehdejší úplná sada prošla v rozsahu 396
  testů s 22 volitelnými skipy. Skutečné Qt/WebEngine a živý provider zůstaly
  do části D výslovně neověřené.
- [x] [completed] **F-M4-WORKFLOW-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Regrese pokryla stejné i různé explicitní backendy/modely,
  nulový implicitní creator kontext, hashe/provenance, privacy/RBAC, stale
  HEAD/selection/policy/binding, malformed a oversized odpověď, známé selhání
  versus `unknown`, vědomě nový workflow a recovery po `run-bound`,
  `response-received`, `succeeded`, `publishing` i `workspace-complete`.
  Opakovaná publikace zachovala jediný commit bez druhého providerového účinku.

Cílená sada s oběma živými opt-in kontrolami prošla 38 testy bez přeskočení.
Skutečný Qt/WebEngine smoke dvakrát spustil a zavřel desktop; další smoke
vytvořil, po restartu otevřel projekt a ověřil workflow panel. Živý same-node
Ollama test s `phi:latest` provedl oba kroky a doložil hashovaný materializovaný
handoff bez původního účelu. Úplná výchozí sada
`python3 -m unittest discover -s tests -v` prošla: 401 testů, 23 podmíněných
native/package/live testů bylo přeskočeno. Private-network Ollama ani klikací
end-to-end dispatch z Qt nebyly součástí této PoC akceptace. Závěrečný
`git diff --check` a kontrola odkazů byly provedeny při předání dávky.

Splněný kontrakt akceptace: každý krok má stabilní identitu, přesný request a
durable recovery bez automatického opakování neurčitého síťového účinku;
opponent dostává pouze hashovaný materializovaný handoff a explicitní podklady;
projektový artefakt vzniká jen samostatnou potvrzenou publikací s
workflow/step/run/manifest provenance a retry vrací stejný receipt/commit.
Desktop a web zachovávají stejné serverové autorizační hranice a bezpečné
textové vykreslení nedůvěryhodného výstupu. Obecný output/plugin router zůstává
samostatnou plánovanou dávkou `F-M4-OUTPUT-ROUTER-01` v BACKLOG.

## F-M3-MEDIA-01 — Externí obrazové capability — 2026-10-05

Dávka na větvi `feature/f-m3-media-01` dodala provider-neutral explicitní
generování jednoho PNG přes samostatné OpenAI Images a ComfyUI adaptery,
bezpečný preview/confirmation tok a oddělenou publikaci projektového artefaktu.
Dosažená úroveň je PoC validated. Evidence byla podle výslovné dohody s
uživatelem přesunuta z TODO ještě před PR. PR #46 byl 2026-10-05 sloučen do
`develop` jako `da449bc`.

- [x] [completed] **F-M3-MEDIA-01-A — Kontrakt, provider/licenční review a
  reuse (designed).** ADR 0008 vymezil `generate-image`, jeden inline PNG,
  přesné rozměry/limity, Context Manifest, samostatný BLOB run journal a zákaz
  URL downloadu, implicitního fallbacku i LLM-sestaveného ComfyUI workflow.
- [x] [completed] **F-M3-MEDIA-01-B — Adapter, durable dispatch a bezpečné
  přijetí výsledku (implemented).** OpenAI Images a ComfyUI mají oddělené
  explicitní bindingy, přesný request, allowlisted workflow parametry,
  strictní PNG/IHDR/CRC/rozměrovou validaci a durable `unknown` bez retry.
- [x] [completed] **F-M3-MEDIA-01-C — UI a explicitní publikace artefaktu
  (implemented).** Desktop i oprávněný web oddělují preview, potvrzený dispatch,
  validovaný výsledek a publikaci přes Workspace. Approval/run přežijí restart;
  metadata schema v3 zapisují binding/run/workflow a hashe bez promptu.
- [x] [completed] **F-M3-MEDIA-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Testy pokryly secrets, RBAC/privacy, malformed a oversized
  odpověď, 4/16 MiB limity, timeout/`unknown`, vědomě nový run, restart mezi
  providerem a approval evidencí a idempotentní recovery publikace. Regrese
  opravila klasifikaci oversized PNG z `unknown` na známé `failed`.

Automatizovaná cílená media/desktop/web sada prošla 43 testy se 3 podmíněnými
browser skipy. Úplná sada po poslední změně prošla 388 testy s 22 podmíněnými
skipy. Skutečný Qt/WebEngine smoke prošel pro běžný start i izolované vytvoření
projektu a vykreslenou kartu Obrázek. `git diff --check` byl čistý.

Živý ComfyUI smoke použil uživatelem dodaný workflow na same-node endpointu
`http://127.0.0.1:8188`, revision `cyberrealisticxl-v90-api-v1`, workflow
revision `cyberrealisticxl-v90-workflow-v1` a SHA-256
`e2ffd0a880341c2031b65266c8af4cde62c1068e5c36b764e5de16e94e26ccb9`.
Izolovaný dočasný projekt prošel preview, potvrzeným dispatch, validací PNG
1024 × 1024 / 864 300 B a publikací; retry publikace vrátil stejný commit,
provenance odpovídala runu/bindingu/workflow a prompt nebyl v metadatech.
Uživatel vizuálně potvrdil očekávanou červenou kostku.

Jeden uživatelem výslovně schválený placený OpenAI Images smoke proběhl nad
novým prázdným dočasným projektem, nikoli nad soukromým registrovaným projektem.
`gpt-image-1` vrátil validní PNG 1024 × 1024 / 1 180 851 B; HEAD zůstal beze
změny a výsledek nebyl publikován. Dočasný projekt, node/state a dočasná kopie
credentialu byly odstraněny. Trvale zůstávají pouze schválené node-local
provider bindingy mimo projektový Git; žádný secret není v evidenci.

## MOD-01-UI — Publikační CMS ve Workspace — 2026-10-05

Dávka na větvi `feature/mod-01-publication-registry` navázala před vytvořením PR
na MOD-01 a dodala úzce připnuté CMS capability, správu propojených domén a
potvrzený Cloudflare deployment. Dosažená úroveň je PoC validated. Evidence byla
na výslovný pokyn uživatele přesunuta z TODO ještě před PR; PR do `develop`
dosud nebyl vytvořen ani sloučen a dávka se tím nepovažuje za začleněnou.

- [x] [completed] **MOD-01-UI-A (designed)** — ADR 0027 vymezil spuštění dvou
  CMS capabilities bez obecného plugin runtime; ADR 0028 přijal jeden
  host-routed Cloudflare Worker, oddělené potvrzení a durable `unknown` recovery.
- [x] [completed] **MOD-01-UI-B (implemented)** — node-local binding, přesná
  kontrola manifestu/capabilities/runtime hashů a izolované spuštění pevného
  entrypointu modulu.
- [x] [completed] **MOD-01-UI-C (implemented)** — desktopové a administrátorské
  webové UI pro správu domén, přesný request, sandboxed HTML náhled a samostatné
  potvrzení generování.
- [x] [completed] **MOD-01-UI-D (PoC validated)** — serializované generování,
  SQLite journal a recovery pádu mezi odvozeným výstupem a atomickým uložením
  node-local konfigurace.
- [x] [completed] **MOD-01-UI-E (implemented)** — automatická detekce modulu a
  explicitní Povolit/Zakázat podle kompatibility manifestu namísto ruční cesty
  nebo Git pinu.
- [x] [completed] **MOD-01-UI-F (PoC validated)** — přidávání a odebírání domén,
  nezávislé sekce Profil/CV/Timeline, zachování vypnutého obsahu a bezeztrátová
  migrace staré konfigurace.
- [x] [completed] **MOD-01-UI-G (PoC validated)** — read-only provider status,
  přesný deployment plán, samostatné potvrzení, přímý Workers Static Assets tok
  a `unknown` bez automatického retry. Živá akceptace odhalila, že Cloudflare
  asset upload vrací také úspěšný HTTP 202; adapter jej po cílené regresi přijímá
  pouze s platnou úspěšnou envelope a completion JWT.

Živá akceptace 2026-10-05 nasadila release
`46465cf5933abe03023f228426363188e3c18a06ce9580ec28fd54db7a78564f` jako
Worker verzi `b81f5b22-e4d4-474c-9fdb-ff61b9e09daa` a deployment
`445aa43c-e051-4d77-9943-589850603c88`. Následný read-only refresh vrátil
`current` a stejný provider release tag. `antoninmicka.cz`, `proofofidea.cz` a
`tonymicka.cz` odpověděly přes validované HTTPS stavem 200 a `CF-Cache-Status:
HIT`; SHA-256 každého těla se přesně shodoval s potvrzeným lokálním
`dist/sites/<hostname>/index.html`. Deployment nezměnil DNS ani Custom Domains.

Předchozí dva nejednoznačné pokusy byly po read-only kontrole operátorsky
uzavřeny jako `abandoned`: aktivní version/deployment ID zůstaly shodné s
očekávaným stavem před pokusem a provider neobsahoval žádnou verzi s cílovým
release tagem. Nový upload se spustil až poté. Cílená sada
`python3 -m unittest tests.test_publication_cms -v` prošla 10 testy. Po opravě
adapteru prošla úplná sada `python3 -m unittest discover -s tests -v`: 369
testů, z toho 22 podmíněných testů přeskočeno.

## MOD-01 — Kontrakt externě verzovaných modulů — 2026-09-29

Dávka na větvi `feature/mod-01-publication-registry` implementovala obecný
manifest v1 a fail-closed load-time ověření proti API prvního samostatně
verzovaného modulu. Dosažená úroveň je PoC validated; PR dosud nebyl vytvořen
ani sloučen. Samostatný modulový repozitář zůstává mimo hostitelský Git v
ignorovaném `modules.local/` a nemá vytvořený commit.

- [x] [completed] **MOD-01-A — Obecný manifest a capability kontrakt
  (implemented).** Manifest deklaruje identitu/verzi, API, vstupní a výstupní
  schema reference, oprávnění, privacy, execution boundary, limity,
  idempotenci, side effect/stavy a provenance bez endpointu nebo credentials.
- [x] [completed] **MOD-01-B — Fail-closed load-time ověření (implemented).**
  Bounded parser a read-only CLI v1 přijímají pouze explicitní literal loopback
  HTTP, nesledují redirect a vyžadují přesnou shodu API odpovědi s reviewovaným
  manifestem. Selhání nic neregistruje a nemění projektový stav.
- [x] [completed] **MOD-01-C — První samostatný modul (implemented).** Externí
  repozitář obsahuje vlastní MPL-2.0 licenci, roadmapu a bezpečnostní hranice,
  provider-neutral registry model, read-only API, prázdný sandbox manifest a
  Worker katalog/detail/404. Jeho budoucí funkce se do hlavní roadmapy
  nekopírují.
- [x] [completed] **MOD-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Pět cílených hostitelských testů prošlo s reálným
  loopbackem, samostatný modul prošel 6 Python testy a Worker suite; skutečný
  host↔module compatibility smoke přijal verzi 0.1.0. Finální hostitelská sada
  prošla: 359 testů, 22 environmentálních skipů. `git diff --check`, kontrola
  nových souborů a oddělení obou Git repozitářů byly součástí předání.

Cloudflare Worker nebyl nasazen, DNS/TLS ani tři cílové hostname nebyly živě
ověřeny. Mutující publish/unpublish, durable externí operation journal,
disclosure, proxy, analytika a marketingové UI patří do vlastní roadmapy modulu.

## F-M3-CHAT-DIRECT-01 — Přímý brainstormingový dispatch — 2026-09-20

Dávka byla dokončena navazujícím acceptance PR #44 jako commit `8171923` v
`develop`; implementační PR #43 (`32cf743`) dodal přímý externí dispatch,
historii přesného requestu a volitelné streamované zobrazení. Dosažená úroveň
je PoC validated. Živý desktopový OpenAI stream byl potvrzen; živý streamovaný
webový smoke nebyl proveden.

- [x] [completed] **F-M3-CHAT-DIRECT-01-A — Kontrakt, provider review a reuse
  (designed).** ADR 0008 vymezil přímý dispatch po serverové autorizaci,
  request evidence bez secrets, ephemerální SSE delty a durable `unknown` bez
  automatického retry.
- [x] [completed] **F-M3-CHAT-DIRECT-01-B — Přímý dispatch a historie requestu
  (implemented).** Brainstorming používá Context Manifest, binding hash a run
  journal; vlastník vidí request i po restartu a webový vstup je do oddělení
  identity store omezen na administrátora.
- [x] [completed] **F-M3-CHAT-DIRECT-01-C — Volitelné streamované zobrazení
  (implemented).** Capability-gated stream zachovává jediný durable finální
  výsledek; timeout nebo přerušení končí `unknown`, chybná událost `failed`.
- [x] [completed] **F-M3-CHAT-DIRECT-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Cílených 69 testů prošlo se 3 Qt skipy, JavaScript prošel
  `node --check` a úplná sada 354 testů prošla s 22 environmentálními skipy.

Implementace i akceptace byly sloučeny do `develop`; evidence byla přesunuta z
TODO při aktivaci následující uživatelem vyžádané dávky.

## M3-UB-01 — Usage & billing backendů — 2026-09-20

Dávka uzavřena po začlenění PR #42 jako commit `43fc8e3` v `develop`; feature
větev `feature/m3-ub-01-usage-billing` dodala providerem hlášené run usage,
oprávněný OpenAI account usage/costs přehled a stručnou indikaci v desktopové i
webové variantě. Dosažená úroveň je PoC validated; živý OpenAI Admin API refresh
nebyl proveden a nejde o production-ready provider acceptance.

- [x] [completed] **M3-UB-01-A — Provider a oprávnění review, kontrakt a reuse
  (designed).** ADR 0008 odděluje `usage` a `billing`, run/account scope,
  skutečnou hodnotu od chybějící a atomickou node-local cache mimo projektový
  Git. Ollama má pouze doložené run metriky; OpenAI account report používá
  samostatný write-only admin credential.
- [x] [completed] **M3-UB-01-B — Načítání, cache, autorizace a UI
  (implemented).** OpenAI stránkování je bounded, 401/403/429 a nedostupnost se
  rozlišují, poslední platná cache může být `stale` a výpadek nemění routing ani
  LLM běh. Account report zpřístupňují desktop a web pouze node/federation
  administrátorům; běžný chatový handler jej nevydává.
- [x] [completed] **M3-UB-01-C — Regrese, dokumentace a akceptace
  (PoC validated).** Regrese pokrývají nulu/unsupported, oprávnění, timeout,
  rate limit, stale cache, restart a nezávislost chatového dispatch; uživatelská
  dokumentace popisuje scope, stáří, jednotky, měnu a oprávnění.

Ověření finálního obsahu: sedm cílených akceptačních testů a úplná sada 347
testů prošly s 22 environmentálními skipy; skutečný webový Qt/WebEngine smoke
indikátoru prošel před poslední test-only změnou. JavaScript syntaxe a
`git diff --check` prošly. Živý OpenAI Admin API refresh zůstal neověřený.

## F-M3-CHAT-MODES-01 — Lokální orchestrace a brainstormingové režimy — 2026-09-20

Dávka uzavřena po začlenění PR #40 jako commit `c8358d5` v `develop`; feature
větev `feature/f-m3-chat-modes` dodala per-run volbu režimu a modelu, oddělené
hranice kontextu a obnovitelný návrat z brainstormingu do nové orchestrace.
Dosažená úroveň je PoC validated. Obecná správa a úplné aplikační smazání
vláken, creator/opponent workflow, usage/billing a další provider capability
zůstávají samostatnými dávkami.

- [x] [completed] **F-M3-CHAT-MODES-01-A — Kontrakt, reuse a crash hranice
  (designed).** `ChatThreads` v3 a `ChatRunChoice` vážou klasifikaci vlákna,
  per-run model a oddělené textové/projektové vstupy; odvozený binding nemění
  globální konfiguraci.
- [x] [completed] **F-M3-CHAT-MODES-01-B — Režimy, modelový výběr a UI
  (implemented).** Orchestrace vynucuje nakonfigurovaný same-node model a
  explicitní artefakty. Brainstorming přijímá jen explicitní text a zprávy,
  volí Ollama/OpenAI model pro běh a externí dispatch vede přes preview a
  potvrzení. Návrat archivuje brainstorming a atomicky zakládá prázdnou
  orchestrace bez implicitního přenosu kontextu.
- [x] [completed] **F-M3-CHAT-MODES-01-C — Regrese, dokumentace a akceptace
  (PoC validated).** Cílených 52 testů prošlo se 2 podmíněnými Qt skipy;
  úplná sada 340 testů prošla s 22 skipy. Samostatný skutečný Qt/WebEngine
  smoke, JavaScript syntaxe, Python kompilace a `git diff --check` prošly.
  Živý externí provider nebyl v této dávce znovu volán.

## F-M1-PROJECT-LOCATION-01 — Umístění projektů a webový import — 2026-09-20

Dávka uzavřena po začlenění PR #37 jako commit `de4e627` v `develop`; feature
větev `feature/f-m1-project-location-web-import` dodala node-local výchozí
složku, registraci existujícího Git projektu, obnovitelnou opravu umístění a
bounded webový import zdrojů. Následné bezpečné odregistrování doslova
chybějícího rootu odstraňuje pouze node registraci, nikoli Git data nebo lokální
stav. Dosažená úroveň je PoC validated; bezpečné odstranění celého projektu,
přesun stavu mezi filesystemy a browserový import celého projektu zůstávají mimo
rozsah.

- [x] [completed] **F-M1-PROJECT-LOCATION-01-A–B — Kontrakt, výchozí složka,
  registrace a oprava cesty (implemented).** Uzlový journal a atomická publikace
  zachovávají state owner, UUID, HEAD a filesystem boundary; cizí projekt,
  pending operace i cross-filesystem přesun se odmítají.
- [x] [completed] **F-M1-PROJECT-LOCATION-01-C — Webový import zdrojů
  (implemented).** Autentizovaný upload Markdown/PNG/JPEG/PDF do 16 MiB zachová
  přesné bajty/SHA-256, vyžaduje write roli, odmítá `local-only` a retry nevytváří
  další commit.
- [x] [completed] **F-M1-PROJECT-LOCATION-01-D — Regrese, dokumentace a
  akceptace (PoC validated).** Odebrání ztraceného rootu je idempotentní a
  recovery bezpečně rozlišuje stav před a po atomickém zveřejnění registrace.

Ověření finálního obsahu: kompletní sada 328 testů OK, 22 podmíněných skipů;
skutečný Qt/WebEngine smoke vytvoření/restartu desktopu a webový
login/catalog/logout prošly. Python kompilace, syntaxe výsledného JavaScriptu a
`git diff --check` prošly. Browserový file-picker nebyl samostatně automatizován;
integrační testy ověřují HTTPS importní endpoint, bajty nad 64 KiB, RBAC,
privacy a idempotentní retry. Gate M1 nadále čeká na `M1-07-C`.

## F-M3-EXTERNAL-01 — První externí provider a řízené volání — 2026-09-20

Dávka uzavřena po začlenění PR #36 jako commit `494670e` v `develop`; feature
větev `feature/f-m3-external-01-first-provider` dodala OpenAI Responses adapter,
přesný potvrzovaný dispatch a jednotné lokální zadání s přímou odpovědí,
artefaktovým návrhem nebo externím requestem. Dosažená úroveň je PoC validated;
usage/billing, obrazové capability, automatický routing a webové hledání zůstaly
mimo rozsah.

- [x] [completed] **F-M3-EXTERNAL-01-A–C — Kontrakt, credential, adapter,
  preview a privacy (PoC validated).** Durable `dispatching`/`unknown`, `store=false`,
  modelový katalog, exact approval a zákaz `local-only` byly ověřeny bez skrytého
  retry nebo fallbacku.
- [x] [completed] **F-M3-EXTERNAL-01-D–E — Ollama návrh a jednotné UI (PoC
  validated).** Striktní outcome dovoluje pouze direct answer, artifact draft
  nebo external request; potvrzené výstupy mají oddělenou durable evidenci a
  explicitní Workspace publikaci.

Ověření finálního obsahu před merge: kompletní sada 321 testů OK a 22
podmíněných skipů; uživatel živě potvrdil všechny tři větve, restart návrhu,
potvrzený OpenAI dispatch i obnovené zobrazení odpovědi. Nestabilita Ollamy a
správa více vláken byly předány jako samostatné navazující požadavky.

## F-M3-BACKEND-01 — Provider-neutral backend a role kontrakt — 2026-09-19

Dávka uzavřena po začlenění PR #35 jako commit `eb828fe` v `develop`; feature
větev `feature/f-m3-backend-01-provider-neutral` dodala provider-neutral runtime
kontrakt, explicitní capabilities a role a rozšířenou durable run evidence při
zachování stávajícího Ollama bindingu. Dosažená úroveň je lokální PoC validated;
první externí provider, credentials, usage/billing a Gate M3 zůstaly mimo rozsah.

- [x] [completed] **F-M3-BACKEND-01-A — Kontrakt backendu, capabilities, rolí a reuse review (designed).** ADR 0008 uzavírá binding, capabilities, role, adapter/run kontrakt, fail-closed registry a kompatibilní migraci.
- [x] [completed] **F-M3-BACKEND-01-B — Společný adapter/run kontrakt a migrace Ollamy (implemented).** Společné runtime typy vážou adapter, binding, capability, roli, manifest a request digest; legacy `prepared` migruje pouze při shodě a `unknown` se neopakuje.
- [x] [completed] **F-M3-BACKEND-01-C — Integrace služeb, negativní scénáře a dokumentace (PoC validated).** Chat, summarizer, extractor a metadata advisor procházejí společným kontraktem; neznámé adaptery/capabilities/role a změny cíle se odmítají fail-closed.

Ověření finálního obsahu: cílených 22 testů OK; kompletní sada 290 testů OK a
22 podmíněných skipů; `py_compile` a `git diff --check` prošly. První běh úplné
sady v omezeném sandboxu selhal pouze na 24 zakázaných socketových operacích;
opakování s povolenými lokálními sockety prošlo. Gate M1 nadále čeká na
odložený `M1-07-C`.

## F-UX-SETTINGS-01 — Centralizovaná stránka nastavení — 2026-09-19

Dávka uzavřena po začlenění PR #34 jako commit `f493a33` v `develop`; feature
větev `feature/f-ux-settings-01-central-settings` dodala globální node-local
nastavení s přímými záložkami AI backend, Uživatelé a Federace. Dosažená úroveň
je lokální PoC validated; skutečný průchod nové stránky v Qt/WebEngine zůstal
neověřený.

- [x] [completed] **F-UX-SETTINGS-01-A — Informační architektura, hranice stavu a reuse review (designed).** ADR 0025 odděluje uzlové nastavení od projektových dat, Gitu, credentials a federace a zachovává jedinou autoritu `OllamaBindings`.
- [x] [completed] **F-UX-SETTINGS-01-B — Stránka nastavení a přesun uzlových vstupů (implemented).** Globální stránka zachovává návratový kontext; jediný Ollama formulář a existující uživatelská/federační správa jsou v hlavní ploše bez dialogu, při zachování desktopového admin kontraktu a webového RBAC.
- [x] [completed] **F-UX-SETTINGS-01-C — Regresní ověření a dokumentace (PoC validated).** Neplatná rekonfigurace zachová a znovu načte potvrzený binding; návod a statické UI/API/RBAC kontrakty byly aktualizovány.

Ověření finálního obsahu: cílená sada 26 testů OK se 3 podmíněnými skipy;
kompletní sada 284 testů OK a 22 podmíněných skipů; Python, JavaScript a
`git diff --check` prošly. Gate M1 nadále čeká na `M1-07-C`.

## F-M2-META-AI-01 — Návrhy popisu a štítků — 2026-09-19

Dávka uzavřena po začlenění PR #33 jako commit `e5b5d9d` v `develop`; feature
větev `feature/f-m2-meta-ai-01-metadata-suggestions` dodala potvrzované návrhy
popisu a štítků pro explicitně vybraný artefakt. Dosažená úroveň je lokální
PoC validated; živý Ollama a skutečný Qt/WebEngine průchod zůstaly neověřené.

- [x] [completed] **F-M2-META-AI-01-A — Kontrakt návrhu, potvrzení a reuse review (designed).** ADR 0008 vymezuje bounded výstup, vazbu na obsah i původní metadata, samostatné potvrzení popisu a aditivních štítků a zákaz automatického mazání či změny privacy/provenance.
- [x] [completed] **F-M2-META-AI-01-B — Durable lokální návrh a validovaný diff (implemented).** Same-node role `metadata-advisor-v1` používá serverem kanonizovaný snapshot, vlastní durable task store a striktní validaci; neurčitý běh se automaticky neopakuje.
- [x] [completed] **F-M2-META-AI-01-C — Potvrzený metadata zápis, desktop UI a akceptace (PoC validated).** UI potvrzuje jednotlivá pole a Workspace znovu váže HEAD, metadata i obsah; retry a pády nevytvoří duplicitní commit.

Ověření finálního obsahu: cílené backend/API/UI/recovery testy a kompletní sada
282 testů OK, 22 podmíněných skipů. Testy pokryly prázdný výběr, nevalidní
návrh, stale HEAD, restart/retry a pády před i po posunu refu i po dokončení
Workspace. Gate M1 nadále čeká na `M1-07-C`.

## F-M2-EXTRACT-01 — Lokální strukturovaná extrakce — 2026-09-19

Dávka uzavřena po začlenění PR #32 jako commit `0f085e3` v `develop`; feature
větev `feature/f-m2-extract-01-structured-extraction` dodala uzavřený katalog
schémat, durable validovaný náhled a potvrzenou projektovou publikaci. Dosažená
úroveň je lokální PoC validated; živý Ollama a skutečný Qt/WebEngine průchod
zůstaly podmíněné prostředím.

- [x] [completed] **F-M2-EXTRACT-01-A — Kontrakt schémat, validace a reuse review (designed).** ADR 0008 definuje `facts-v1` a `action-items-v1`, striktní pole, limity, source reference jen do explicitního výběru a neměnný `fpw-extraction-v1` source artefakt.
- [x] [completed] **F-M2-EXTRACT-01-B — Lokální extractor a durable validovaný preview (implemented).** Same-node role `extractor-v1` používá Context Manifest a oddělený task store; nevalidní nebo neurčitý běh nelze vydávat ani automaticky opakovat.
- [x] [completed] **F-M2-EXTRACT-01-C — Potvrzená publikace, desktop UI a akceptace (PoC validated).** Autentizované API/UI vybírá artefakty nebo zprávy, bezpečně vykresluje JSON a Workspace publikuje jediný source artefakt s provenance, privacy a `derived-from` vztahy.

Ověření finálního obsahu: `py_compile`, `node --check`, cílené
backend/API/UI/recovery testy a kompletní sada 274 testů OK, 22 podmíněných
skipů. Testy pokryly invalidní JSON, stale/unknown, restart, idempotentní retry
a pády před i po posunu refu i po dokončení Workspace. Gate M1 nadále čeká na
odložený `M1-07-C`.

## F-M2-SUMMARY-01 — Lokální projektové souhrny — 2026-09-18

Dávka uzavřena po začlenění PR #31 jako commit `3059dbb` v `develop`; feature
větev `feature/f-m2-summary-01-local-summaries` dodala explicitní lokální
summarizaci, trvalý náhled a potvrzenou projektovou publikaci. Dosažená úroveň
je lokální PoC validated; skutečný Qt/WebEngine smoke a živý Ollama model
zůstaly podmíněné prostředím.

- [x] [completed] **F-M2-SUMMARY-01-A — Kontrakt souhrnu a reuse review (designed).** ADR 0008 vymezuje `fpw-summary-request-v1`, role `summarizer-v1`, výhradní artifact nebo message selection, limity, nejpřísnější privacy a oddělení LLM běhu od projektové publikace.
- [x] [completed] **F-M2-SUMMARY-01-B — Lokální summarizer a bezpečný náhled (implemented).** Context Manifest váže čitelnou instrukci, přesné vstupy/focus/cíl; same-node Ollama a node-local task journal obnoví úspěšný běh bez druhého transportu a automaticky neopakují `unknown`.
- [x] [completed] **F-M2-SUMMARY-01-C — Potvrzená publikace, desktop UI a akceptace (PoC validated).** Autentizované UI/API nabízí výběr, bezpečný náhled a potvrzení; Workspace publikuje jediný Markdown dokument s neměnnou `fpw-summary-v1` provenance, nejpřísnější privacy a vztahy `summarizes`.

Ověření finálního obsahu: `py_compile`, `node --check`, cílené
backend/API/UI/metadata testy a kompletní sada 264 testů OK, 22 podmíněných
skipů. Testy pokryly stale/unknown, restart, absenci Git zápisu při preview,
idempotentní retry a pády před i po posunu refu i po dokončení Workspace.
Gate M1 nadále čeká na odložený `M1-07-C`.

## F-M2-CHAT-02 — Projektová vlákna, otisky a Markdown výstupy — 2026-09-18

Dávka uzavřena po začlenění PR #30 jako commit `db4917e` v `develop`; feature
větev `feature/f-m2-chat-02-project-records` dodala explicitní projektové
přiřazení živého vlákna, neměnné full/delta otisky a editovatelné odvozené
Markdown výstupy. Dosažená úroveň je lokální PoC validated; Gate M2 pokračuje
summarizerem a dalšími lokálními AI schopnostmi.

- [x] [completed] **F-M2-CHAT-02-A — Kontrakt přiřazení, full/delta otisku a odvozeného výstupu (designed).** ADR 0008 vymezuje node-local projektovou vazbu, kanonické `fpw-chat-snapshot-v1`/`fpw-chat-output-v1`, nejpřísnější privacy a standardní expected-HEAD/Journal/CAS/index recovery.
- [x] [completed] **F-M2-CHAT-02-B — Projektové záznamy a recovery (implemented).** SQLite v1→v2 migrace váže projekt a Context Manifest; full/delta publikace validuje základ, thread revizi a souvislou sequence a používá jediný Workspace commit/receipt.
- [x] [completed] **F-M2-CHAT-02-C — Markdown výstup, desktop UI a akceptace (PoC validated).** Autentizované UI ukládá otisk nebo poslední odpověď s thread/message/turn/run/manifest provenance; průběžný stav LLM je trvale viditelný u promptu a editace výstupu zachovává provenance obálku.

Ověření finálního obsahu: celá sada 253 testů OK a 22 podmíněných skipů;
`py_compile` a `git diff --check` prošly. Ověřeny byly stale HEAD, pád po journal
prepare, idempotentní retry, restart/rebuild indexu a autentizované API/UI
kontrakty. Reálný Qt/WebEngine smoke této poslední změny zůstal podle opt-in
podmínky přeskočen. Gate M1 nadále čeká na odložený `M1-07-C`.

## F-M2-CHAT-01 — Lokálně perzistentní živé konverzace — 2026-09-18

Dávka uzavřena po začlenění PR #29 jako commit `5dec3a8` v `develop`; feature
větev `feature/f-m2-chat-01-local-threads` dodala node-local vícekolový chat,
Context Manifest napojení a bezpečný Ollama dispatch. Dosažená úroveň je PoC
validated; projektové otisky a artefakty pokračují ve F-M2-CHAT-02.

- [x] [completed] **F-M2-CHAT-01-A — Thread/Message kontrakt a crash boundaries (designed).** ADR 0008 odděluje vlákno, neměnné zprávy, draft, turn a backendový run včetně retence a obnovy bez duplicitního dispatch.
- [x] [completed] **F-M2-CHAT-01-B — Lokální thread store a recovery (implemented).** Striktní SQLite v1 store používá vlastnictví node/user, transakční pořadí, hashované zprávy, turn/run vazby a explicitní terminal states.
- [x] [completed] **F-M2-CHAT-01-C — Context/adapter napojení a desktop UI (PoC validated).** Každý běh váže přesný HEAD, thread/revizi, seřazené message ID/role/bajty, privacy a přesný backend bez fallbacku; desktop stav po restartu znovu načte.
- [x] [completed] **F-M2-CHAT-01-AH-01 — Odolnost studeného startu.** Backend čeká 180 sekund a desktop 210 sekund; `unknown` se automaticky neopakuje. Živý minimální běh `gemma4` odpověděl přes loopback za 7,74 s.
- [x] [completed] **F-M2-CHAT-01-AH-02 — Čitelný Ollama prompt.** Manifestovaný JSON/Base64 se deterministicky převádí na UTF-8 transcript rolí; request digest jej dál váže k manifestu.
- [x] [completed] **F-M2-CHAT-01-AH-03 — Čisté nové vlákno.** UI může začít nový kontext bez odstranění starší lokální historie.

Ověření finálního obsahu: cílených 22 testů OK se dvěma opt-in skipy; celá
sada 245 testů OK a 22 podmíněných skipů; `py_compile` a `git diff --check`
prošly. Samostatný reálný Qt/WebEngine test otevření projektu a restartu prošel.
Skutečný LAN/TLS Ollama endpoint nebyl ověřen. Gate M1 zůstává otevřený kvůli
odloženému `M1-07-C`; Gate M2 vyžaduje F-M2-CHAT-02.

## F-M1-UI-01 — Přepnutí do chatu až při odeslání — 2026-09-18

Dávka uzavřena po začlenění PR #28 jako commit `a6dfbf6` v `develop`; feature větev `feature/f-m1-ui-01-prompt-submit-tab` oddělila editaci promptu od jeho odeslání.

- [x] [completed] **F-M1-UI-01-A — Oddělit editaci a odeslání promptu.** Psaní pouze mění dostupnost odesílacího tlačítka a zachová aktivní náhled či chat; validní submit Enterem nebo tlačítkem teprve přepne do chatu.
- [x] [completed] **F-M1-UI-01-B — Regresní ověření a dokumentace.** Unit kontrakt, skutečný Qt/WebEngine smoke, uživatelský návod a ADR 0019 byly aktualizovány.

Ověření: cílených 5 testů OK včetně skutečného Qt/WebEngine; celá sada 231 testů OK a 22 podmíněných skipů. `py_compile` a `git diff --check` prošly. Zprávy i draft nadále zůstávají jen v paměti stránky; perzistence patří do F-M2-CHAT-01.

## F-M2-OLLAMA-01 — Důvěryhodná lokalita Ollama backendu — 2026-09-18

Dávka uzavřena po začlenění PR #27 jako commit `d1fc6f4` v `develop`; feature větev `feature/f-m2-ollama-01-locality` dodala lokální PoC Ollama adapteru, striktního node-local bindingu a durable run journalu. Gate M2 tím není uzavřen.

- [x] [completed] **F-M2-OLLAMA-01-A — Execution boundary a binding kontrakt.** `same-node` přijímá jen číselný loopback HTTP; `private-network` jen číselnou privátní HTTPS adresu, pin certifikátu a stabilní identitu. DNS, credentials a neznámá pole se odmítají.
- [x] [completed] **F-M2-OLLAMA-01-B — Ollama adapter a bezpečný dispatch.** Autorizovaný handoff je vázán na přesný Target a request digest; `dispatching` je durable před sítí, ztracená odpověď skončí `unknown` bez automatického retry a úspěch se po restartu znovu neodesílá.
- [x] [completed] **F-M2-OLLAMA-01-C — Restart, chybové scénáře a ověření.** Atomicky uložený binding se po restartu striktně načte; testy pokryly redirect, kontrolu TLS pinu před requestem, změny cíle/modelu, nedostupnost a zákaz `local-only` na LAN.
- [x] [completed] **F-M2-OLLAMA-AH-01 — Návrh periodického monitoringu.** Strategický požadavek je zachován v sekci 23 roadmapy a dávkách `MON-00` až `MON-06` v BACKLOG; nebyl součástí implementace adapteru.

Ověření: 14 cílených testů OK; celá sada 230 testů OK a 22 podmíněných skipů. `py_compile` a `git diff --check` prošly. Živá Ollama ani skutečný LAN/TLS endpoint nebyly ověřeny; jde o lokální PoC, nikoli production-ready síťovou integraci.

## F-M2-CONTEXT-01 — Bezpečný Context Builder — 2026-09-17

Dávka uzavřena po začlenění PR #26 jako commit `ab2a5ea` v `develop`; feature větev `feature/f-m2-context-01-manifest` dodala backendově neutrální read-only Context Builder. Dosažená úroveň je lokální PoC validated; Gate M1 ani Gate M2 tím nejsou uzavřeny.

- [x] [completed] **F-M2-CONTEXT-01-A — Striktní manifest a snapshoty.** Kanonický manifest a payload vážou explicitní projektové/ad-hoc bajty, SHA-256, velikost, privacy, commit, autoritu, policy a přesný binding/cíl.
- [x] [completed] **F-M2-CONTEXT-01-B — Revalidace dispatch handoffu.** Oddělené `prepare` a `authorize_for_dispatch` pod writer lockem znovu kontrolují session/uživatele/uzel, HEAD, čtecí práva, policy, cíl a bajty; nic samy neodesílají.
- [x] [completed] **F-M2-CONTEXT-01-C — Chybové scénáře a dokumentace.** Stale/tampered/unauthorized/local-only/fallback hranice jsou pokryté testy a ADR 0008/reuse evidence jsou aktualizované.

Ověření: 4 cílené testy OK; celá sada mimo socketový sandbox 220 testů OK a 22 podmíněných skipů. První sandboxový běh selhal pouze na 20 zakázaných HTTP/HTTPS/Unix socketech. Backend adapter, durable run record a skutečný síťový účinek zůstaly mimo rozsah.

## M1-07 — LXC autostart; implementační předání s odloženou cílovou akceptací — 2026-09-17

Implementace byla začleněna PR #24 jako commit `3c09090` v `develop`; feature větev `feature/m1-07-lxc-autostart` dodala bezpečné idempotentní nastavení vlastní sekce `lxc-auto.federated_workspace`, rollback a testy. Dávka je administrativně předána na výslovné rozhodnutí uživatele odložit další restart routeru. Nejde o splnění cílové restartové akceptace ani uzavření Gate M1; otevřené ověření je zachováno v BACKLOG jako `M1-07-C`.

- [x] [completed] **M1-07-A — Lokální implementace autostartu (implemented, 2026-09-17).** Instalace spravuje jen vlastní pojmenovanou UCI sekci, zachovává ostatní kontejnery, odmítá cizí kolizi a zahrnuje stav do rollback journalu.
- [x] [completed] **M1-07-B — Lokální regresní ověření (PoC validated lokálně, 2026-09-17).** Cílených 15 testů prošlo; plná sada měla 216 úspěšných testů a 22 podmíněných skipů. Skutečný reboot nebyl součástí běhu.

Omezení: uživatel dříve potvrdil zachování instalace a dat po restartu, ale kontejner se tehdy automaticky nespustil. Oprava autostartu po novém reálném restartu dosud ověřena není. Ověřit běh kontejneru a služby, dlaždici, přihlášení a náhled; výsledek teprve může doložit zbývající část Gate M1.

## F-M1-SOURCE-02 — Vynucení neměnných zdrojů a navazující verze — 2026-09-17

Dávka uzavřena po začlenění PR #23 jako commit `a93dd75` v `develop`; feature větev `feature/f-m1-source-02-enforcement` končí `55c0211`. Dosažená úroveň je lokální PoC validated; Gate M1 zůstává otevřený.

- [x] [completed] **F-M1-SOURCE-02-A — Transition validátor a podporované publikační cesty.** Workspace kontroluje base/kandidát před journalem i commitem; první Git přenos kontroluje každý parent→child přechod převzaté historie. Změna či odstranění source bajtů, identity, basename nebo v2 import provenance pod stejným UUID se odmítá.
- [x] [completed] **F-M1-SOURCE-02-B — Metadata-only editace a navazující verze.** Povolené anotace jsou verzované, uvolnění privacy explicitně autorizované; nová verze má nové UUID a volitelný vztah `supersedes`. SHA-256 duplicity se pouze hlásí a neslučují automaticky.
- [x] [completed] **F-M1-SOURCE-02-C — UI, recovery a dokumentace.** Importní dialog nabízí předchůdce a upozornění na shodné bajty; operace používají společný Workspace journal/CAS/index/receipt lifecycle.

Ověření: cílená sada 33 testů OK s jedním podmíněným Qt skipem; samostatný skutečný Qt test 1/1 OK; plná sada mimo socketový sandbox 215 testů OK a 22 podmíněných skipů. Obecný merge/fast-forward projektů není současnou aplikační schopností a musí při budoucí implementaci použít stejný transition validátor. Cílové zařízení ani výpadek napájení tato dávka neověřovala.

## F-M1-META-02 — Implementace importní provenance v2 — 2026-09-17

Dávka uzavřena po doloženém začlenění PR #22 jako commit `fb613ad` v `develop`; feature větev `feature/f-m1-meta-02-provenance-v2` obsahovala implementaci i následné uživatelské upřesnění času vzniku zdroje. Dosažená úroveň je lokální PoC validated; Gate M1 zůstává otevřený.

- [x] [completed] **F-M1-META-02-A — Parser a projekce v2 (PoC validated, 2026-09-17).** Striktní parser podporuje smíšený v1/v2 snapshot, podmíněný importní blok a vazbu hashe na skutečné source bajty. Index projektuje úplnou provenance a staré/rozpracované schéma atomicky obnovuje z validovaného HEAD.
- [x] [completed] **F-M1-META-02-B — Nový import a doložená migrace (PoC validated, 2026-09-17).** Nové importy zapisují v2; request digest váže bajty, hash i provenance. Explicitní migrace vyžaduje doložený původní Workspace commit, ancestry, operation trailer a shodu neměnných polí/bajtů.
- [x] [completed] **F-M1-META-02-C — UI, recovery a akceptace (PoC validated, 2026-09-17).** UI bezpečně zobrazuje importní provenance; retry/receipt, chybné vstupy, pády před/po CAS a při indexaci, skutečné Qt/WebEngine, balení a offline provoz byly ověřeny.
- [x] [completed] **F-M1-META-AH-01 — Oddělit čas importu a vznik zdroje (implemented, 2026-09-17).** Import přijímá pouze explicitní doložený `source_created_at`; automatický `imported_at` zůstává samostatný a pozdější. Neznámý vznik se neodhaduje.

Oveření na finálním obsahu před předáním:

- Cílená sada metadata/import/index: 24 testů prošlo bez chyb a skipů.
- Rozšířená sada před posledním ad-hoc UI doplněním: 209 testů, 205 prošlo a čtyři volitelné libgit2 probe testy byly přeskočeny; skutečné Qt/WebEngine, `.deb` a offline scénáře běžely.
- Po F-M1-META-AH-01 prošlo 14 cílených backendových testů s jedním očekávaným Qt skipem a samostatné skutečné Qt dialog + WebEngine scénáře 2/2. Celá rozšířená sada měla 210 testů: 205 prošlo, čtyři libgit2 byly přeskočeny a jednou selhal nesouvisející HTTPS browser smoke bez očekávaného stdout; bezprostřední izolovaný retry prošel. Po poslední UI změně proto není doložen nový celý bezchybný běh.

Omezení: migrace je programová, nikoli plošný UI wizard. Obecná transition ochrana všech publish/fast-forward/merge cest, metadata-only editace source a import navazující verze pokračují ve F-M1-SOURCE-02. Výpadek napájení, pád uvnitř libovolného syscallu a cílové zařízení nebyly touto dávkou doloženy.

## F-M1-SOURCE-01 — Kontrakt neměnnosti a verzování zdrojů — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #20 jako squash commit `7152d64` v `develop`; feature větev `feature/f-m1-source-01-versioning` končí `f20482f`. Šlo o designed dokumentační výstup bez implementace transition validátoru nebo schématu v2.

- [x] [completed] **V-05 — Neměnnost zdrojů (designed, 2026-09-15).** [ADR 0024](docs/adr/0024-source-immutability-and-versioning.md) vymezuje neměnné bajty, basename, identitu a importní provenance pod jedním source UUID; projektové anotace zůstávají verzovaně editovatelné a uvolnění privacy vyžaduje explicitní autorizovanou reklasifikaci.
- [x] [completed] **F-M1-SOURCE-01-A/B — Verze, duplicity, transition validace a recovery (designed, 2026-09-15).** Nové bajty nebo revize dostávají nové UUID a mohou použít vztah `supersedes`; SHA-256 shoda sama neslučuje provenance ani privacy. Publish/fast-forward/merge musí v budoucí implementaci porovnávat base a kandidáta a novou verzi publikovat jednou expected-HEAD/Journal/CAS/index/receipt operací.

Kontrakt byl věcně zkontrolován proti importu, validátoru, mazání, Git historii a existujícím testům; lokální odkazy a `git diff --check` prošly. Celá sada se neopakovala, protože se aplikační kód, testy ani konfigurace nezměnily. Implementace provenance v2 pokračuje ve F-M1-META-02 a obecná transition ochrana/import navazující verze ve F-M1-SOURCE-02; Gate M1 zůstává otevřený.

## F-M1-META-01 — Přesný kontrakt metadat a importní provenance — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #19 jako squash commit `9acd0ef` v `develop`; feature větev `feature/f-m1-meta-01-contract` končí `da7647a`. Šlo o designed dokumentační výstup bez změny aplikačního kódu nebo schématu.

- [x] [completed] **V-04 — Přesný kontrakt metadat v1 (designed, 2026-09-15).** Registry povinně nesou `status`/`body`, `relations` jsou volitelné. `created_at` je vznik entity v projektu a u nativního importu čas importu; `author_id` je projektový aktér/importér, nikoli původní autor. Spustitelný validátor v1 zůstal beze změny autoritou současného formátu.
- [x] [completed] **F-M1-META-01-A/B — Importní provenance, kompatibilita a recovery (designed, 2026-09-15).** [ADR 0023](docs/adr/0023-metadata-and-import-provenance.md) vyhrazuje v2 s podmíněným `import` blokem, zachovává smíšené v1/v2 čtení a zakazuje vymýšlení chybějící provenance. Explicitní migrace použije standardní expected-HEAD/Journal/CAS/index/receipt recovery.

Kontrola proti `spikes/metadata.py`, `spikes/source_import.py`, `spikes/storage.py` a testům potvrdila popsané v1. Oba JSON příklady, lokální odkazy a `git diff --check` prošly; celá testovací sada se neopakovala, protože se kód, testy ani konfigurace nezměnily. Implementace v2, migrace a jejich recovery testy zůstávají F-M1-META-02; Gate M1 zůstává otevřený.

## F-M1-DELETE-01 — Ověření bezpečného odstranění dokumentu — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #17 jako squash commit `ab296fd` v `develop`; původní pracovní větev byla `F-M1-DELETE-01/M1-08`. Archivace evidence a aktivace další dávky probíhá na `feature/f-m1-meta-01-contract`; není novým během testů ani uzavřením Gate M1.

- [x] [completed] **M1-08 — Bezpečné odstranění dokumentu (PoC validated, 2026-09-15).** Nativní editor vyžaduje potvrzení; Artifacts odstraní verzovaný Markdown dokument a sidecar/frontmatter jednou Workspace operací, zachová Git historii, odmítne příchozí strukturované vztahy a neplatný kandidátní snapshot. Retry používá stejný operation ID/receipt, writer lock, expected HEAD, CAS a recovery dle ADR 0003/0016.
- [x] [completed] **Akceptační a recovery ověření (PoC validated, 2026-09-15).** Sidecar/frontmatter, vlastněné cesty, zachování ostatních entit/historie, příchozí vztahy z artefaktů i registrů, self/outgoing vztahy, hlavní TODO, stale/dirty/staged/busy, neplatné vstupy/snapshot, odmítnutí sources a skutečný Qt cancel/retry/reload byly ověřeny.

Osmnáct procesních přerušení sidecaru a sedmnáct frontmatteru (35 hranic včetně `before-ref` a pěti indexových checkpointů) skončilo po native open jedním commitem a indexem bez odstraněného UUID. Receipt zajistil idempotentní retry; cizí znovuvytvořený soubor při pending zůstal zachován a recovery odmítla pokračovat.

Ověření na finálním obsahu dávky:

- `M0_DESKTOP_TEST=1 QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_artifact_deletion -v`: 9 testů prošlo (16,350 s).
- `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v`: 204 testů prošlo za 133,575 s, 4 volitelné libgit2 testy přeskočeny. Skutečné Qt/WebEngine, izolované balení/instalace a offline testy byly zapnuté.

Omezení: lokální Linux PoC bez cílového LXC/routerového ověření, výpadku napájení nebo přerušení uvnitř libovolného Git/SQLite syscallu. Koš, UI obnovy odstraněných dokumentů, mazání sources a federovaná synchronizace nebyly součástí dávky. Gate M1 zůstává otevřený.

## F-M1-INDEX-01 — Relační projekce projektového indexu — 2026-09-15

Dávka uzavřena po doloženém začlenění PR #16 v lokálním `develop` (`948bf69`); feature větev `feature/f-m1-index-01-relations` končí `22d5098`. Porovnání implementace, testů a ADR 0022 mezi feature větví a `develop` je bez rozdílu. Archivace je dokumentační předání, nikoli nový běh testů ani uzavření Gate M1.

- [x] [completed] **F-M1-INDEX-01 / V-03 — Relační projekce (PoC validated, výstup 2026-09-14).** Metadata v1 artefaktů/registrů, cesty, štítky a explicitní směrované vztahy; atomická migrace/rebuild a přesný commit ID, FK a stale/pending hranice podle ADR 0022.
- [x] [completed] **F-M1-INDEX-AH-01 — Desktop smoke akceptace (PoC validated, 2026-09-14).** Selektor omezený na výběr projektu a sidebar test připojený k aktuálním assets; skutečné UI scénáře a závěrečná sada ověřeny.

Původní výsledky, návrh, recovery a omezení jsou zachovány níže. Závěrečná sada z 2026-09-14 měla 195 testů, 191 prošlo a čtyři volitelné libgit2 skip; desktop, HTTP/backend, balení a offline scénáře běžely. V tomto předání nebyla sada opakována, kód/testy se nemění. Git zůstává autoritou; SQLite projekce není journalem. V-04/V-05, cílové měření výkonu a Gate M1 zůstávají otevřené.

F-M1-DELETE-01/M1-08 přesunuta z BACKLOG do TODO jako jediná plánovaná feature; její implementace a větev nezahájeny. Částečný backendový důkaz odstranění z indexních testů nepokrývá celé M1-08. Backlog nyní připravuje tři další konkrétní dávky: návrh metadat V-04, návrh neměnnosti V-05 a Context Builder s podmínkami M1. V-04/V-05 mají stále svůj původní otevřený rozsah, návrh nenahrazuje jejich budoucí implementaci.

<details>
<summary>Původní evidence indexní dávky před uzavřením</summary>

Historický přepis zachovává původní důkazy a stav před PR. Formulace „PR není otevřen ani sloučen“ nebo „čeká na sloučení“ jsou překonány doloženým PR #16 výše, nejsou aktuálními otevřenými úkoly.

#### F-M1-INDEX-01 — Relační projekce projektového indexu

- Stav: [x] [completed]; milník M1; lokální PoC validated. Výstup ověřen, dávka čeká na předání a sloučení PR do `develop`.
- Původ: V-03 a zbývající integrace metadat/indexu M1; ADR 0002/0003.
- Větev: `feature/f-m1-index-01-relations`, založena 2026-09-14 z lokálního `develop` (`0849ec8`). Dokumentační předání importní dávky bylo před implementací commitnuto (`54a2d39`). Cíl jediného PR: `develop`; PR zatím nevytvořen; implementace a ověření dokončeny, commit/push/merge v tomto běhu neprovedeny.
- Výstup: doložený kontrakt a implementace lokálně obnovitelné projekce vztahů/metadat, nesoucí přesný commit ID.
- Mimo rozsah: změna Git autority, synchronizace SQLite, nové LLM/RAG databáze.
- Závislosti: stabilní metadata kontrakt v `develop`; importní změny pouze pokud jej ovlivní.
- Akceptace jednoho PR: rebuild z HEAD, stale/pending odmítnutí, referenční integrita a změny po rename/delete/import, bezpečná migrace projekce, testy a dokumentace.

##### Úkoly a ověření

- [x] [completed] **F-M1-INDEX-01 / V-03 — Relační projekce (PoC validated, 2026-09-14).** Index ukládá všechna validovaná metadata v1 artefaktů a registrů, cestu obsahu/registry, štítky a směrované vztahy vázané na přesný commit ID. FK, pořadí i duplicity se zachovávají; příchozí/odchozí dotazy filtrují explicitní hrany. Atomická migrace/rebuild, stale/pending odmítnutí a recovery po procesních přerušeních ověřeny. Native import, editace metadat, rename/delete a rebuild chybějící DB ověřeny; skutečný desktop, HTTP/backend, balení a offline běžely v celé sadě. Kontrakt: [ADR 0022](docs/adr/0022-relational-index.md).

V-03 — Vyjasnit omezení projekce indexu — je součástí této feature; jeho aktuální stav je zde. Výchozí index validoval vztahy, ale ukládal pouze id/title a commit ID. Rozšíření nyní pokrývá úplná validovaná metadata v1 artefaktů/registrů a explicitní vztahy; nejde o univerzální grafovou DB, další schémata ani produkční nasazení. Git zůstává autoritou, SQLite index je obnovitelná lokální projekce a není journalem rozpracovaných operací.

#### Kontrakt před implementací — 2026-09-14

Adapt/reuse současného Index/Workspace, validátoru metadat a stdlib SQLite; nový storage framework ani externí kód nejsou potřeba. Soukromá inventura neposkytuje důvod nahrazovat tuto koordinaci. Git schéma se nemění; projekce zachová metadata včetně absence volitelných polí, cestu obsahu/registru, pořadí štítků a směrovaných vztahů i duplicity. Validátor dovoluje neprázdné vlastní typy vztahů; index je nezpřísní ani nedoplní inverzní vazby. Pole note není součástí spustitelného v1 schématu a index je nezavádí.

Crash boundaries ADR 0003 zůstávají platné. Rozšíření: migrace staré projekce a výměna entit/štítků/vztahů/commit ID proběhne v jedné explicitní SQLite transakci; pád před potvrzením ji vrátí, po potvrzení lze rebuild opakovat. Stará projekce se nepublikuje jako aktuální; neznámá budoucí verze se odmítne bez přepsání. Journal, Git commit, soubory a receipt se migrací nemění. Při pending stavu aplikační čtení odmítá data; samostatný Index journal nezná. Čtení kontroluje HEAD před i po SQL dotazu. Výpadek napájení a nekooperující FS/Git útočník zůstávají mimo PoC.

#### Průběžné ověření — 2026-09-14

- `python3 -m unittest tests.test_index_projection tests.test_storage tests.test_workspace -v`: 25 testů prošlo, bez skip a chyb (8,915 s). Nových osm regresních testů pokrývá projekci všech v1 metadat, frontmatter/sidecar/registry, FK a příchozí/odchozí dotazy, vlastní typy/duplicity/pořadí, neplatný Git snapshot, drift HEAD při rebuild i čtení, migraci staré DB a odmítnutí budoucí verze, SQL čtenáře během výměny a 15 procesních přerušení (pět checkpointů při migraci, rebuild i Workspace recovery).
- Integrační native služby: import přesných CRLF/frontmatter bajtů, privacy local-only, změna popisu/štítků, rename bez změny vazeb, blokované odstranění při příchozí vazbě, následné odstranění a rebuild chybějící DB. Projektový přehled odmítne nesoulad projekce metadat/vztahů/štítků s validovaným commitem.
- První celá sada se zapnutým desktopem/balením/offline: 194 testů, šest UI selhání a jedna chyba vyčerpaného HEAD mocku, čtyři libgit2 skip (158,763 s). Příčiny odstraněny a ověřeny závěrečným během níže. Cílové LXC/router ani uživatelské projekty nejsou měněny; bez měření cílového výkonu, bez dokončení V-04/V-05 a bez uzavření Gate M1.

- [x] [completed] **F-M1-INDEX-AH-01 — Obnovit platnost skutečného desktop smoke při závěrečné akceptaci (PoC validated, 2026-09-14).** Původ: úplný běh odhalil timeouty v projektových smoke scénářích; historický globální selektor select odmítal i skryté administrační formuláře přítomné už v HEAD a sidebar test injektoval JavaScript do starých assets. Rozsah: omezit smoke kontrolu na projektový katalog/levý výběr projektu a připojit sidebar test k aktuálním desktopovým assets. Podmínka dokončení: všech šest dotčených WebEngine scénářů a následná celá sada. Nejde o samostatnou UI feature.

Doplnění crash/migrační ochrany: constructor odmítá i neznámé legacy tabulky/sloupce bez přidání indexových tabulek, včetně DB s operations; journal se nesmí inicializovat jako index. Cílený běh po této úpravě: 26 testů, bez chyb/skip (9,439 s). Pořadí volání HEAD v legacy testu bylo nahrazeno trvající změnou HEAD; projektový read při driftu odmítne reindexaci jiného snapshotu.

Cílené UI re-testy po opravách: tři scénáře náhledu/projektového přehledu/záložek prošly (22,646 s); další tři scénáře readonly TODO stromu, create/reopen a sidebar cancel/save prošly (17,421 s). Závěrečný běh celé sady po posledních změnách prošel, viz níže. Devět nových projekčních regresních testů prošlo (3,926 s).

#### Závěrečné ověření a předání — 2026-09-14

- `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v` mimo omezení lokálních socketů/Qt v sandboxu: **195 testů, 191 prošlo, 4 přeskočeny, bez chyb (114,552 s)**. Skutečné Qt/WebEngine, native editor/history/preview, HTTP/HTTPS, izolované balení/install/upgrade/remove a offline provoz běžely. Přeskočeny pouze čtyři volitelné testy libgit2 probe; aplikace používá Git CLI.
- Devět nových projekčních regresních testů v `tests/test_index_projection.py`; procesní přerušení uvnitř SQL transakce (mezi checkpointy) při migraci/rebuild i při Workspace recovery. Výsledky dřívějších běhů výše jsou historické, tento běh pokrývá finální kód/testy.
- Dokumentace a místní odkazy ověřeny; `git diff --check`, finální diff i nové soubory zkontrolovány. Samostatný build/lint není pro aplikaci nakonfigurován; existující balicí kontroly běžely.

Scope jednoho PR `feature/f-m1-index-01-relations -> develop`: relační projekce metadat/cest/štítků/vztahů, atomická migrace z v0, FK a směrované dotazy, společná stale/pending hranice, porovnání celé projekce s Git snapshotem, regresní/recovery testy a ADR 0022. Nezbytná ad-hoc oprava zpřesňuje pouze testovací smoke selektor a používané assets; běžné UI workflow se nemění.

Recovery: před commitem zůstává autoritou journal; po commitu index rebuild z validovaného HEAD. Pád před SQL potvrzením vrátí celou projekci/migraci, po potvrzení lze indexaci opakovat bez dalšího commitu; pending se uvolní až po journalovém úklidu. Neznámá verze/layout DB se odmítá bez smazání/downgrade, journal se nemění. Omezení: lokální Linux PoC, bez cílového měření výkonu/paměti nebo nového LXC/router nasazení, bez výpadku napájení a nekooperačních FS záruk; V-04/V-05 a Gate M1 zůstávají otevřené. PR není otevřen ani sloučen; dokončené úkoly zůstávají v TODO do uzavření dávky.

</details>

## F-M1-IMPORT-01 — Nativní import zdrojových dokumentů — 2026-09-14

- [x] [completed] **F-M1-IMPORT-01 — Nativní import (PoC validated).** Výběr Markdown/PNG/JPEG/PDF, původní bajty, sidecar metadata/privacy/provenance a společný Workspace commit; zobrazení v Podkladech. Bez nové mutující HTTP route.
- [x] [completed] **Ověření (PoC validated).** Závěrečný běh na lokálním `develop` `0849ec8`: `python3 -m unittest discover -s tests -v` mimo socketové omezení sandboxu — 186 testů, 166 prošlo, 20 přeskočeno, bez chyb (53.058 s). Obsahuje tři nové regresní testy formátů, importního limitu 16 MiB a nezávislého limitu náhledu 4 MiB. Volitelné scénáře nebyly zapnuté; první sandboxový běh selhal na lokálních socketech, nikoli na importních testech.
- [x] [completed] **Předání (PoC validated).** Lokální historie `develop` dokládá začlenění importu v PR #13 (`082b69f`), následné opravy Qt v #14 (`86e1fd6`) a regresních testů/dokumentace v #15 (`0849ec8`). Původní plán jednoho PR byl fakticky předán třemi již začleněnými PR ze dvou větví; tento dodatek popisuje doloženou historii. V tomto běhu nebyl proveden commit, push, otevření PR ani merge.

Nová samostatná kontrola `/tmp/fw-import-recovery-check.py`: 17 skupin prošlo, včetně byte-identity CRLF/frontmatter, metadata/privacy, unsafe/symlink/změněného zdroje, digestu, dirty/busy/stale, receipt/retry a pádu procesu na 12 checkpointech ADR 0003. Konfliktní cizí editace zůstala zachována; její odstranění proběhlo pouze v izolované fixture. Po obnově právě jeden commit, čistý Git a žádná pending operace. Dočasný harness není trvalý regresní test.

Nový skutečný Qt smoke (`QT_QPA_PLATFORM=offscreen`, `/tmp/fw-continue-import-qt.py`) prošel načtením dialogu, pickerem, zrušením potvrzení bez změny HEAD, potvrzeným importem a dokončením workeru/saved signálu; přesné původní bajty, jediný commit a čistý Git. Uživatel už dříve potvrdil import a zobrazení ve skutečném desktopu. Offscreen test neznamená nové cílové ověření LXC/routeru.

Recovery a mantinely ADR 0003/0016 se nemění. V-04/V-05 zůstávají otevřené v BACKLOG: samostatné datum importu/podrobná provenance a ochrana před externími Git úpravami nejsou dodány. Gate M1 zůstává otevřený. Relační projekce F-M1-INDEX-01/V-03 je přesunuta do TODO jako jediná plánovaná dávka; její implementace a větev nejsou zahájeny.

<details>
<summary>Původní evidence importní dávky před závěrečným předáním</summary>

Historický přepis zachovává původní důkazy a dočasné chyby/stavy. Formulace o neopravené Qt chybě, chybějícím regresním běhu a neprovedeném merge byly pozdějšími výsledky výše překonány; nejde o aktuální otevřené úkoly. Původní sekce „K předání do backlogu“ obsahovala převážně časový průběh ověření, který patří do historie; otevřené V-04/V-05 zůstávají pod původními ID v BACKLOG.

#### Rozsah a předání

- Větev: **`feature/f-m1-import-01-native-sources`**, založená z čistého lokálního `develop` při zahájení úkolu. PR do `develop` zatím nevytvořen; push/merge neprovedeny.
- Původ: uživatelem schválený import, zbývající požadavek M1; související V-04/V-05, ADR 0003/0016.
- Cílová úroveň: PoC validated. Aktuálně implemented, částečně ověřeno; rozsah důkazů a zbývající kontroly níže.
- Výstup: nativní výběr Markdown/PNG/JPEG/PDF, zachování původních bajtů, sidecar metadata/privacy/provenance, potvrzený společný zápis a zobrazení v Podkladech.
- Mimo rozsah: externí konektory IMP-01–03, LLM, synchronizace, obecná migrace metadat a globální zákaz externích Git úprav zdrojů.
- Kontrakt: imported source má kind=source/provenance=external, vytvoření artefaktu znamená okamžik importu. Obsah je v nativním editoru nepozměnitelný, nová verze má nové UUID. Samostatné imported_at a původní autor externího zdroje nejsou novými schema fields; V-04/V-05 zůstávají mimo tento omezený kontrakt otevřené.

#### Úkoly této feature

- [x] [completed] **F-M1-IMPORT-01 — Nativní import (implemented, 2026-09-14; částečně ověřeno).** Sources adaptuje Artifacts/Workspace, originální soubor a metadata publikuje jedním commitem, request digest váže SHA-256 přesných bajtů a opakování stejné operation ID. Před přípravou journalu validuje výsledný snapshot. Native picker má explicitní potvrzení a retry/recovery; uložený source se zobrazí přes stávající Podklady/preview. Bez nové mutující HTTP route.
- [ ] [completed] **Ověření:** byte-identita Markdown včetně CRLF/frontmatter, PNG/JPEG/PDF, 16 MiB limit a nezávislý 4 MiB preview limit, unsafe/symlink/změněný zdroj, metadata/privacy, stale/dirty/busy/foreign, receipt/retry a procesní checkpointy, source-only editor hranice, skutečný Qt a celá sada testů. Přidané cílené testy v `tests/test_source_import.py` ověřují: 1) podporu a uložení Markdown/PNG/JPEG/PDF, 2) odmítnutí nepodporovaného typu a překročení 16 MiB, 3) nezávislost náhledového limitu 4 MiB na importním limitu.
- [ ] [in progress] **Předání PR:** zakreslit scope, důkazy, omezení a recovery; připravit jeden PR `feature/f-m1-import-01-native-sources -> develop` bez mergování.

#### Návrh předání PR

- Scope: kompletní implementace nativního importu Markdown/PNG/JPEG/PDF přes picker a importní pipeline, validace integrity (SHA-256 byte-identita), sidecar metadata (`kind=source`, `provenance=external`, `privacy=project`), zobrazení přes Podklady/preview, journaling + recovery flow, validace limitů a bezpečnostních hranic.
- Důkazy: `tests/test_source_import.py` (lokální cílené scénáře), dočasný harness `/tmp/fw-import-recovery-check.py` (restart a checkpointy), real-time offscreen Qt smoke, a úplný výpis ověřovací sekce v TODO.
- Omezení: mimo testy nebylo ověřeno nasazení na cílové hardwarové instance/routery; `WorkingDirectory`/deploy path a externí LXC scénáře jsou mimo rozsah; Gate M1 zůstává otevřený.
- Recovery: retry přes stejné `operation_id` vrací původní receipt; stale/retry konflikty a cizí změny po prepare aktivují `RecoveryConflict`; po explicitní čisté obnově se import dokončí deterministicky, bez pending operací a při zachování cizích změn.

#### Důkazy ověření — 2026-09-14

- Uživatel potvrdil import a zobrazení zdroje ve skutečném desktopu.
- Po opravě kolize ImportDialog.finished se signálem Qt: skutečný offscreen Qt dialog a worker prošly; načtení aktivuje výběr souboru. Celá stávající sada po opravě: 183 testů, 163 prošlo, 20 přeskočeno, bez chyb (49,942 s, mimo socketová omezení sandboxu). Sada sama nepokrývá všechny nové importní scénáře.
- Izolovaný dočasný harness /tmp/fw-import-recovery-check.py: 17 skupin kontrol prošlo. Odmítnuty unsafe názvy, symlink, adresář, nepodporovaný formát, neplatné UTF-8/NUL, zdroj nad 16 MiB, změna při čtení, chybný digest a metadata. Dirty tree a obsazený writer lock odmítnuty bez přepsání cizích dat. Identický retry vrací původní receipt, změněný intent a stale HEAD jsou odmítnuty.
- Proces byl ukončen os._exit(73) na prepared, file:0, file:1, applied, files-applied, commit-created, commit-ready, ref-updated, committed, git-indexed, indexed a completed. Po restartu ve všech 12 případech přesné původní Markdown bajty včetně CRLF/frontmatter, kind=source/provenance=external/privacy=project, právě jeden commit, čistý Git a žádná pending operace. Cizí změna po přípravě vyvolá RecoveryConflict a zůstane zachována; po jejím explicitním odstranění pouze v testovací fixture recovery dokončí import.
- Harness není trvalý regresní test; živý LXC/router ani uživatelské projekty nebyly měněny. Tato kontrola neuzavírá celou dávku ani Gate M1.
- Definice obousměrných typů vazeb (`supports/supported_by`, `contains/part_of`, `depends_on`, `implements`, `derived_from`, `references`, `cites`, `produces`) byla doplněna v [DATA_MODEL.md](DATA_MODEL.md).

#### K předání do backlogu

Ověření 2026-09-14: izolované backendové scénáře importu prošly (původní bajty včetně CRLF/frontmatter, PNG/JPEG/PDF hlavičky, metadata, receipt/retry, náhled Markdown/PNG/PDF, odmítnutí stale HEAD, jiného SHA-256 a symlinku). Obnova po skutečném ukončení procesu na osmi checkpointech prošla s jediným commitem a čistým pracovním stromem. První běh celých testů v sandboxu: 183 testů, 20 socketových errors a 20 volitelných skip; běží opakování mimo socketové omezení. Skutečný Qt odhalil blokující chybu `RuntimeError: Failed to connect signal finished()` při otevření ImportDialog: handler `finished` koliduje s QDialog signálem. Oprava zatím neprovedena, feature není připravena k merge. Dočasné ověřovací scénáře nejsou novými trvalými regresními testy.

Žádné nové nezávislé feature. Návaznosti V-04/V-05 zůstávají v BACKLOG se svými původními ID.

Závěrečný regresní běh mimo socketově omezený sandbox: `python3 -m unittest discover -s tests -v` — 183 testů, 163 prošlo, 20 volitelných přeskočeno, bez chyb, 49,613 s. Tento existující unittest běh neobsahuje nový ImportDialog smoke; jeho samostatně zjištěná Qt chyba proto dál blokuje akceptaci feature. Kompletní oprava/UI re-test zatím nebyly provedeny.

Oprava Qt blockeru (2026-09-14): handler přejmenován na operation_finished. Opakovaný skutečný Qt smoke prošel otevřením dialogu, zrušením potvrzení bez změny HEAD, potvrzeným importem, worker completion, zachováním přesných CRLF/frontmatter bajtů a čistým Git stromem. Qt blocker je odstraněný; po této opravě byla opakována pouze cílená UI kontrola, nikoli znovu celá regresní sada. PR/merge stále neprovedeny.

</details>

## WF-03 — Předání pravidel feature dávek — 2026-09-14

Pravidla feature větví/PR, čištění TODO a reorganizace backlogu byla předána uživatelem navazujícím pokynem zahájit další feature. Čistý lokální `develop` obsahoval commit `a450205 docs(workflow): automate feature branch creation and recommend pull requests`. Ověřeno při zahájení importní dávky; vzdálený stav PR ani merge nebyly kontrolovány a nejsou tímto tvrzené. Jde o administrativní předání podle pokynu uživatele, nikoli nový gate review. Dřívější kontrola úklidu doložila TODO o 24 řádcích a jednu aktivní dávku; následné úpravy pravidel nebyly znovu kompletně dokumentačně ověřeny. Nativní import má samostatnou větev a jediný plánovaný PR do develop.

Dokončené výstupy, výsledky ověření a historická gate review. Aktuální dávku včetně dosud nearchivovaných dokončených úkolů drží [TODO](TODO.md), vzdálenější otevřené položky [BACKLOG](BACKLOG.md), strategii a gates [roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>).

Starší záznamy od review M0-09R níže byly beze změny důkazů přesunuty z TODO. Časy, počty testů, popisy tehdejšího stavu a starší negativní review jsou historické; neoznačují automaticky dnešní stav. Nové záznamy přidávejte nahoru až při uzavření celé dávky, s ID úkolů, daty, úrovní výsledků, ověřením a omezeními. Během dávky zůstávají výsledky v TODO. Původní ID a důkazy zachovávejte; věcné opravy doplňujte jako datované dodatky.


## Administrativní předání dokončené evidence M1 — 2026-09-14

Převzaté dříve označené dokončené výstupy a původní důkazy ze širokého TODO. Nejde o nové testy, uzavření celé dávky M1 ani doložený merge PR. Otevřené části byly přesunuty do BACKLOG; milník a gates zůstávají otevřené. Staré formulace o umístění v TODO jsou historické, současný stav evidence určují TODO/BACKLOG.

- [x] [completed] **M1-AH-08 — Desktop federace bez prvního projektu a viditelné chyby (PoC validated, 2026-09-13).** Hlášení uživatele: desktopové nastavení federace tiše selhává. Opraveny dvě doložené mezery: chybějící node.json nového desktopu a status mimo odscrollovaný viewport. Native handler bezpečně inicializuje prázdný uzel přes ProjectCreation writer lock, zachová author/node UUID, nepřepíše poškozenou konfiguraci ani nenahradí identitu existujícího registru. Sticky status a role alert zobrazují API/HTML validation/nenačtenou správu/chybějící scope. Reuse bootstrap fsync/publikace a existujícího journalu; žádný nový projekt ani účet. Celá sada `python3 -m unittest discover -s tests -v` mimo socketový sandbox: **183 testů, 163 prošlo, 20 volitelných přeskočeno, bez chyb**, 49,349 s. Nové testy: peer před prvním projektem, stabilní UUID, corrupt/lost config bez overwrite, retry po chybě publikace. Skutečný Qt/WebEngine s desktopovou request_policy/token politikou ověřil prázdný uzel, viditelné HTML/API chyby v odscrollovaném dialogu a úspěšné přidání peeru. JS syntaxe a whitespace diff bez chyb. Běh nezapínal všechny volitelné balicí/offline/Qt/libgit2 scénáře; uživatelova konkrétní běžící instalace nebyla aktualizovaná ani ověřena. M1-AH-07/M5 cílové akceptace zůstávají otevřené.

Ověření M1-AH-07 (2026-09-13, lokální PoC validated): závěrečné `python3 -m unittest discover -s tests -v` mimo socketově omezený sandbox — **180 testů, 160 prošlo, 20 volitelných přeskočeno, bez chyb**, 49,973 s. Dva dočasné uzly se skutečnými Ed25519 klíči ověřily samostatné podpisy, aktivaci až se dvěma potvrzeními, chybný pin/tampering, cizí login, ACL průnik s reader a zachování origin manifestu/privacy, revokaci/replay včetně revokace doručené před potvrzením, neobnovení mapování po opětovném trust a migraci registru bez změny credential. Ověřen i nativní token proti webovému klíči, jediná desktopová identita a odmítnutí dalších účtů; ztracený node key není nahrazen. Skutečný Qt/WebEngine smoke pro web i native handler prošel přepínáním samostatných záložek a tabulek a kontrolou jednoho desktopového účtu/skrytí tvorby účtů. JS syntaxe web/native a diff whitespace bez chyb. Celkový běh nezapínal všechny volitelné Qt/offline/balicí/libgit2 testy. Cílové nasazení, automatický transport a atomické publikování ACL s daty nebyly ověřeny ani implementovány v tomto kroku; nejsou tímto označené za hotové.

- [x] [completed] **V-11 — Příprava veřejné distribuce (designed, 2026-09-10).** Distribuční metadata a update channel byly sjednoceny pro aktuální PoC release režim: v `.deb` kontrolním souboru je explicitní `Maintainer` (už bez placeholderu), doplněn `Homepage` repozitáře a v dokumentaci je explicitně řečeno, že update je v této fázi ruční (`.deb` + `apt`), bez auto-updateru. V kontrolním testu .deb je potvrzeno, že placeholder byl odstraněn.

Ověření V-11:
- `python3 -m unittest tests.test_package_deb -v`
- `grep -n "Maintainer"` v `scripts/package_deb.py` a `tests/test_package_deb.py` potvrzuje novou hodnotu a regresní kontrolu.
- `git diff --check`.

Poznámka k otevřené části: před skutečným veřejným releasem zůstává právní review komponent distribuce mimo čistě projektovou kódovou základnu a oficiální potvrzení kontaktních dat v publikované licenci/release metadatech.

- [x] [completed] **V-08 — Registrace existujícího projektu (implemented, 2026-09-10).** Doplněn registrační tok pro již existující Git projekt: nová cesta `ProjectCreation.register` validuje kořenový Git repozitář, `project.json` v `HEAD` i pracovní kopii, kontroluje konfliktní/duplicitní `project_id`, vytváří lokální state vedle repozitáře a zapisuje registraci přes recovery flow.

Ověření V-08:
- `python3 -m py_compile spikes/project_creation.py tests/test_project_creation.py`
- `python3 -m unittest tests.test_project_creation.CreationTests -k register -v`: 4 testy OK, 2 testy přeskočeny.
- `python3 -m unittest tests.test_project_creation.CreationTests -v`: 15 testů, 1 chyba v legacy síťovém testu `test_default_path_is_lazy_and_http_cannot_create` (sandbox PermissionError na HTTP socketu), 2 přeskočeno.
- `git diff --check`.

- [x] [completed] **M1-06 — Přejmenování souboru Markdown dokumentu (PoC validated, 2026-09-10).** Navazující krok souhrnného M1 podle požadavku na konzistenci po přejmenování. Nativní editor ukládá název souboru, obsah a metadata jednou operací; zachová UUID, strukturované vztahy, hlavní TODO a historii. Sidecar aktualizuje file, frontmatter se přesune; čisté přejmenování přes službu zachová původní bajty. Reuse/adapt Artifacts, Workspace, validátoru a Qt; crash boundaries ADR 0003/0016 beze změny. [Kontrakt a limity](docs/adr/0016-markdown-editor.md#přejmenování-souboru-dokumentu--m1-06), [návod](docs/project-opening.md#přejmenování-souboru-dokumentu).

Ověření M1-06: cílených 21 testů artefaktů se skutečnými Qt widgety OK; doplněná ochrana dlouhého existujícího názvu následně ověřena cíleným Qt testem i závěrečnou celou sadou. Pokryty sidecar/frontmatter, souběžná změna textu/metadat, historie a příchozí vztahy, obnova odstraněného indexu, neplatné názvy, kolize s cizím souborem, stale/busy, cizí editace při recovery, ztracená odpověď/retry a restart, procesní přerušení na 13 checkpointech přejmenování. Závěrečný běh `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v`: **131 testů, 127 prošlo, 4 přeskočeny**, 91,259 s, bez chyb. Přeskočeny pouze volitelné testy porovnání libgit2 kvůli chybějícímu sestavenému probe; skutečný desktop, balení/upgrade/odstranění i offline běžely. Sandbox blokoval první pokus připojení Qt; ověření mimo sandbox prošlo. Místní odkazy včetně kotev, finální diff a `git diff --check` v pořádku. Omezení: volné textové odkazy na názvy se automaticky nepřepisují; Qt může normalizovat konce řádků. Lokální Linux PoC, bez nového ověření na cílovém zařízení. Mazání a import zůstávají otevřenými požadavky souhrnného M1; Gate M1 zůstává otevřený. Záznam zůstává v TODO do uzavření dávky.

- [x] [completed] **M1-05 — Metadata dokumentu v editoru (PoC validated, 2026-09-10).** Záložka Metadata zobrazuje uložená metadata pouze pro čtení a dovoluje upravit popis/štítky. Obsah i explicitní změny metadat se ukládají jednou operací s původním operation ID/retry/receipt; identita, autor, vytvoření, privacy a provenance se zachovávají. Podporovány sidecary i frontmatter, vyčištění hodnot a samostatná editace metadat. Po uložení se čte potvrzený stav z Gitu. Reuse/adapt Artifacts, Qt widgetů a validátoru; crash boundaries ADR 0003/0016 beze změny. Kontrakt a limity: [ADR 0016](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

Ověření M1-05: cílených 15 testů artefaktů OK se skutečnými Qt widgety; společný obsah/metadata a historie, restart, readonly metadata, ztracená odpověď a retry, vazba digestu na změny metadat, odmítnutí nepovolených/nevalidních/nadměrných metadat bez pending a recovery na všech 12 procesních checkpointech. Celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **119 testů OK, bez vynechání**, 62,895 s. Místní odkazy a `git diff --check` v pořádku. Lokální Linux PoC; produkční připravenost ani nové ověření na cílovém zařízení se tím neprohlašují. Zůstává v TODO do uzavření dávky M1.


## Ad-hoc úkoly aktuální dávky

- [x] [completed] **WF-02 — Práce po dávkách (implemented, 2026-09-10).** Požadavek uživatele: celé milníky v TODO, navazující dávky v BACKLOG, průběžně měnit jen TODO a archivovat až po uzavření dávky; podporovat ad-hoc práci. Upraveny pokyny a pracovní dokumenty, souhrnný úkol M1 přesunut z BACKLOG do této dávky. Ověření: konzistence pravidel a odkazů, zachování původních otevřených položek a historických záznamů, `git diff --check`. Pouze dokumentační změna; aplikační testy znovu nespouštěny. Záznam zůstává zde do uzavření dávky M1.

- [x] [completed] **M1-AH-01 — Materializované kompiláty v roadmapě (designed, 2026-09-10).** Ad-hoc požadavek uživatele: soubory s výsledky zpracování zdrojů podle zadání (např. orientační rozpočtové obálky), ručně obnovitelné z aktuálních i nových zdrojů, bez verzování a přenosu výsledků. Doplněna sekce 2E roadmapy, [ADR 0018](docs/adr/0018-materialized-compilations.md) a vazba v architektuře: zachované zadání, lokální cache mimo Git, manifest vstupů, aktuálnost, privacy, recovery a explicitní uložení trvalého artefaktu. Ověřena konzistence s Git autoritou, oddělením indexu/journalu a ADR 0008; návrhové scénáře zahrnují změny zdrojů, revokaci a pády. Místní odkazy a `git diff --check` ověřeny. Pouze návrh, bez implementace či nových runtime testů; Gate M1 se nerozšiřuje. Záznam zůstává v aktuální dávce.

- [x] [completed] **M1-AH-02 — Hlavní panel chatu a náhledů (PoC validated, 2026-09-10).** Hlavní panel přepíná orchestrační chat a náhled vybraného artefaktu s uloženým popisem/metadaty. Podporuje základní Markdown, PNG/JPEG a stránkový raster PDF; chat bez backendu umožňuje pouze lokální rozepsání zadání a odesílání je nedostupné. Přepnutí záložek zachová obsah, změna projektu jej vymaže a opožděné odpovědi se odmítají. Autentizovaný endpoint čte jeden validovaný commit a odmítá pending/stale; projektové soubory se nemění. Reuse Projects/Workspace, token/origin kontrol a DOM; PDF používá systémový Poppler deklarovaný v .deb. Kontrakt, limity a recovery: [ADR 0019](docs/adr/0019-main-panel-preview.md), [návod](docs/project-opening.md).

Ověření M1-AH-02: cílené API a skutečný WebEngine pro Markdown/PNG/PDF, klávesnicové přepínání, zachování draftu mezi záložkami, vymazání při změně projektu, neaktivní HTML, validace registrace/ID, stale/pending, čtení commitnutých bajtů, limity a chybné/nedostupné PDF. Vizuálně zkontrolováno skutečné okno 1100 × 800. Závěrečná celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **123 testů OK, bez vynechání**, 74,043 s, včetně instalace/upgrade/odstranění a offline desktopu. Místní odkazy, syntaxe JS a `git diff --check` ověřeny. Omezení: vstup 4 MiB, Markdown 2000 odřádkování a omezené formátování, PDF stránky 1–100/raster 1200 px/timeout 15 s; není to sandbox PDF parseru, plné RBAC ani zapojený LLM chat. Zůstává v TODO do uzavření dávky M1.


- [x] [completed] **M1-AH-03 — Projektové karty a společný prompt (PoC validated, 2026-09-10).** Na požadavek uživatele úvod zobrazuje karty projektů s názvy/popisy a stručný seznam vlevo; otevřený projekt úvod skryje. Výběr artefaktu automaticky aktivuje náhled a označí položku. Prompt zůstává pod náhledem i chatem, psaní přepne na chat, Enter/tlačítko přidá lokální zadání bez volání backendu. Dole je návrat na seznam projektů, který vymaže projektový obsah/draft. Reuse/adapt Projects, Git, validátoru project.json a DOM; katalog čte bez inicializace indexu/journalu a zvládá nedostupné položky jednotlivě. Nativní editor přebírá skutečně otevřené ID. Kontrakt a hranice: [ADR 0019](docs/adr/0019-main-panel-preview.md), [návod](docs/project-opening.md).

Ověření M1-AH-03: cílené testy katalogu/projektů/náhledů a skutečný WebEngine, karty a stručný seznam, automatický chat při psaní, lokální přidání zadání, trvale viditelný prompt, klávesnicové záložky, návrat a znovuotevření, zachování a vymazání draftu, nedůvěryhodné názvy, autentizace a katalog bez zápisů. Obě obrazovky vizuálně ověřeny v okně 1100 × 800. Závěrečná celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **124 testů OK, bez vynechání**, 76,158 s. Syntaxe JS, místní odkazy a `git diff --check` v pořádku. Chat/zadání zůstávají jen v paměti okna; LLM ani trvalý registr úkolů nejsou zapojené. Záznam zůstává v aktuální dávce.


- [x] [completed] **M1-AH-04 — Srozumitelné UI pro ukázku partnerům (PoC validated, 2026-09-10).** Požadavek uživatele: lidské popisky a vytvoření chybějícího hlavního seznamu úkolů z levého panelu. UI používá Úkoly, Podklady, Náhled, Chat a srozumitelné popisky editoru, historie i podrobností. Chybějící seznam nabízí Vytvořit seznam úkolů; otevře stávající nativní editor, dokument vznikne až uložením. Po uložení se přehled obnoví a tlačítko zmizí. Reuse/adapt EditorDialog a sidebaru; ukládání/recovery ADR 0016 beze změny, bez nového HTTP zápisu. [Kontrakt](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

Ověření M1-AH-04: cílených 32 testů OK, následně skutečné zahození návrhu přes potvrzovací dialog, opakované otevření, uložení jediného dokumentu a obnovení sidebaru. Vizuální kontrola levého panelu a editoru v Qt; existující/nepodporovaný seznam nenabízí vytvoření. Závěrečná celá sada `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **125 testů OK, bez vynechání**, 83,027 s. Syntaxe JS, místní odkazy a `git diff --check` v pořádku. Úkol pro ukázku UI uzavřen v rozsahu lokálního PoC; asistent nadále neodpovídá a zadání nejsou trvale uložená. Gate M1 zůstává otevřený, záznam zůstává v TODO do uzavření dávky.


- [x] [completed] **M1-LC-01 — Compliance baseline a notices (implemented, 2026-09-10).** Dokončena integrace compliance patchu: přidané `THIRD_PARTY_NOTICES.md`, právní evidence pod `docs/legal/*` (`COMPLIANCE.md`, `LICENSE_SOURCES.md`, `DEPENDENCIES.toml`, `RELINKING.md`, `licenses/*`), nový `scripts/license_files.py`, a `tests/test_license_packaging.py`; úprava balicích skriptů pro zařazení povinných licenčních souborů do source i `.deb` distribuce. Ověření: `python3 -m unittest discover -s tests -p 'test_license_packaging.py' -v`, validace `git diff --check` po změnách, dokumentační vazby do `README.md` a `REUSE_CATALOG.md` podle zadání. Ověření plného regresního běhu po tomto commitu: `python3 -m unittest discover -s tests -v` -> selhalo (11 errors, 19 skipped, 114 passed) kvůli sandboxovým omezením síťových socketů/`socket` (PermissionError: Operation not permitted) u API lokálních testů; tyto chyby označují omezení prostředí, ne regresi aplikační logiky. Konkrétně `test_authentication*`, `test_framing*`, `test_same_contract*`, `test_stalled_client*`, `test_unix_peer_uid*`, `test_default_path_is_lazy_and_http_cannot_create`, `test_authenticated_api_and_no_filesystem_parameters`, `test_assets_do_not_bootstrap_token_and_api_still_requires_auth` a `test_real_api_auth_validation_and_no_path_access`. Ověřené i relevantní UI/paketizační testy: `test_deb_carries_notices...`, `test_contents_and_no_overwrite`, `test_source_archive_contains_all_legal_files_and_manifest`, `test_missing_notice_stops_deb_before_publishing` a `test_missing_license_stops_source_build` (závěr: pro compliance commit úspěšně ověřeno). Skippované testy označeny explicitně: Qt/WebEngine (`Requires real Qt/WebEngine`, `Requires real desktop`, `Requires actual sidebar tabs`) a instalační runtime (`Requires installed Debian runtime dependencies`) považuji jako neověřené v tomto prostředí. Testovaná revize: `HEAD`.

## K předání do backlogu

Doplnění k **V-11** při předání dávky: příští distribuční inventář musí zahrnout novou systémovou závislost `poppler-utils` pro PDF náhledy (M1-AH-02). Historické inventáře se nepřepisují; veřejný release zůstává samostatným úkolem.
## WF-01 — Přehledné aktuální okno práce — 2026-09-10

- [x] [completed] **WF-01 — Oddělení aktuální práce, backlogu a historie (implemented).** AGENTS vymezuje roadmapu pro milníky/gates, TODO pro nejvýše 5 bezprostředních úkolů, BACKLOG pro ostatní otevřenou práci a WORK_LOG pro dokončené výstupy a ověření. Úkol se přesouvá se stejným ID a kontextem; historie se nepřepisuje. Z původních 23 otevřených položek zůstává M1-05 v TODO a 22 v BACKLOG; všechny historické sekce byly zachovány beze změny důkazů. Opraveny odkazy a zastaralý aktuální milník v úvodu roadmapy na M1. Existující allowlist zdrojového balíčku byl rozšířen o oba nové dokumenty, včetně kontroly v manifest testu.

Ověření: automatické porovnání původních a přesunutých sekcí i všech otevřených položek, kontrola místních odkazů a finálního diffu. Cílené testy balíčku prošly (Qt v prvním běhu vynecháno); následně `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **117 testů OK, bez vynechání**, 62,380 s. `git diff --check` bez chyb. Tato změna nezahajuje M1-05 ani nemění aplikační chování či produkční připravenost.

<a id="gate-m0"></a>
## Závěrečné Gate review M0-09R

Posouzený HEAD `1efc6d3`, pracovní strom čistý. **Gate M0 splněn pro rozsah architecture spike; přechod do M1 je schválen.** Toto rozhodnutí nahrazuje předchozí negativní review, která zůstávají níže jako historie. Neprohlašuje produkční připravenost ani splnění Gate M1.

| Podmínka Gate M0 | Důkaz | Závěr |
| --- | --- | --- |
| Zaznamenaný stack podložený PoC | ADR 0013; srovnání Git ADR 0005, PySide/měření ADR 0010 | Splněno: Python, Git CLI/SQLite, PySide/WebEngine, Linux .deb. |
| Autoritativní schéma a obnova indexu | ADR 0002/0004, validátory a testy; M0-05 rebuild indexu na cíli | Splněno pro minimální schéma. |
| Koordinace a recovery | ADR 0003, Workspace testy a M0-05: všech 12 checkpointů na Omnia SSD | Splněno pro procesní pády ve vymezeném PoC. |
| Návrh bezpečného lokálního API | ADR 0006/0007/0010, token/origin policy, skutečné Qt okno | Splněno pro návrh a transportní PoC. |
| Konflikt entity a obsah/sidecar | M0-07, FEDERATION a test_merge_scenarios | Splněno včetně čistého sémanticky neplatného merge. |
| Orchestrace bez LLM a execution boundaries | ADR 0008, návrhové scénáře | Splněno jako designed; LLM/RBAC engine se nepředstírá. |
| Cílové prostředí a balení | ADR 0012 čistá instalace/offline/upgrade/purge; M0-05 ARMv7/Btrfs měření | Splněno jako PoC validated. |

Poslední plná sada má 73 úspěšných testů (důkaz u cílového probe); nový uživatelský výstup potvrzuje cílové ověření. V tomto dokumentačním review se testy neopakovaly. Ověřeny návaznost důkazů, odkazy a finální diff.

Otevřené V-01 až V-11 se nepřevádějí na hotové: V-08 a V-10 jsou integrační podmínky práce s projekty, V-04/V-05 podmínky rozšíření metadat/importu, V-06/V-07 produkční ochrany a V-11 veřejný release. Výpadek napájení, plné RBAC, síťová federace, LLM, kapacita velkých projektů ani další OS nejsou vstupními podmínkami M1 podle definice Gate M0. Jejich backlog zůstává zachovaný. Produkční HTTP server není schválen pouhým úspěchem loopback PoC.

- [x] [completed] **M1-01 — PoC validated: otevření existujícího projektu v desktopu.** Služba Projects ověřuje registraci v1, shodu commitnutého project.json, existující vlastněný root a soukromý state. Workspace vrací název, commit ID a artefakty pod společným zámkem; pending blokuje čtení, chybějící/stale index se obnovuje, neplatná projekce se nevydává za aktuální. Lokální API přijímá pouze registrovaná ID a zachovává token/Host/Origin ochrany. UI vykresluje názvy jako text a při změně výběru/chybě odstraňuje starý výsledek. Spuštění `./run.sh desktop --node SOUBOR` zachovává cesty vůči volajícímu. [Postup a izolovaná ukázka](docs/project-opening.md), [hranice recovery](docs/adr/0014-project-read.md).

  Ověření: plná sada s `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **83 testů úspěšně, bez skipů**. Nových deset testů pokrývá dva projekty/restart, ztrátu a stale index, nevalidní registraci/verzi/config, symlink/hardlink, pending, poškozenou projekci, změnu HEAD, přerušenou inicializaci a rollback indexace, autentizované HTTP, prázdný projekt, wrapper a skutečné Qt vykreslení HTML názvů jako textu. `bash -n run.sh` a `git diff --check` prošly. Nejde o produkční RBAC/Git sandbox ani nový cílový běh na Omnii. Balení a offline testy ověřují regresi původního smoke; nové projektové čtení má vlastní Qt test z checkoutu. Přesný příklad z návodu prošel skutečným desktopovým smoke; vizuálně ověřen název, commit a artefakt. Návod je zahrnut i v allowlistu zdrojového balíčku.

- [x] [completed] **M1-02 — PoC validated: vytvoření a registrace projektu z desktopu.** Nativní dialog přijímá název a neexistující cílovou složku; jeden worker připraví Git/project.json, lokální stav a index, atomicky publikuje registraci a otevře projekt. Bez `--node` používá výchozí XDG uzel, jehož konfigurace vzniká až při potvrzeném vytvoření. Uzlový SQLite journal drží stabilní ID/parametry/receipts, používá společný neblokující flock a při běžném restartu automaticky obnovuje pending vytvoření. Existující cíl, nesoulad konfigurace nebo cizí změna se nezahladí. HTTP zůstává pouze pro čtení; nativní mutující kontrakt a crash boundaries jsou v [ADR 0015](docs/adr/0015-project-creation.md). [Postup](docs/project-opening.md) a nápověda aktualizovány.

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **95 testů úspěšně, bez skipů**. Dvanáct nových testů pokrývá skutečné procesní pády na osmi hranicích, deterministickou obnovu prvního commitu, opakování ID/parametrů, dva projekty, busy/pending/timeout, zachování existujícího cíle a cizích změn, selhání atomického zápisu node.json, lazy default konfiguraci, odmítnutí mutace přes HTTP, skutečný Qt dialog a restart i automatickou obnovu/otevření při běžném startu GUI. Test nainstalovaného .deb nyní vytváří skutečný dočasný projekt a ověřuje jeho i node.json zachování po purge. Regresní offline start a předchozí storage crash testy prošly. `bash -n run.sh`, lokální odkazy a `git diff --check` ověřeny. Nejde o nové ověření na Omnii ani výpadek napájení.

- [x] [completed] **M1-03 — PoC validated: Markdown editor, checklisty a hlavní TODO projektu.** Nativní Qt dialog vytváří/upravuje Markdown document artefakty přes registrovaný Workspace; obsah/sidecar se commitují společně, existující frontmatter i metadata se zachovávají. Checklist panel mění značky přímo v Markdownu, hlavní TODO má rezervované stabilní UUIDv5 a vznikne až při prvním uložení. GUI drží operation ID při retry, Workspace váže požadavek na digest/receipt, kontroluje výchozí HEAD a používá neblokující zámek/deadline. Nativní otevření editoru dokončí pending journal; HTTP zůstává pro čtení. [Kontrakt a crash boundaries](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **105 testů úspěšně, bez skipů**. Deset nových testů ověřuje přesné Git bajty a metadata, hlavní TODO/rename, checklisty včetně Unicode a code fences, skutečný Qt dialog a opětovné otevření, ztracenou odpověď/retry, dvě souběžná vytvoření TODO, stale/busy/deadline, neplatné vstupy, cizí editaci, ztrátu indexu a skutečné procesní pády na 12 hranicích. Regresní testy desktopu, .deb a offline startu prošly; nové editování má vlastní Qt test z checkoutu, nejde o nový cílový běh na Omnii. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. PoC limit: 1 MiB těla dokumentu; rozepsaný neuložený text není trvalý draft, není implementovaný bohatý preview, automatické sloučení editací ani výpadek napájení. Gate M1 zůstává otevřený.

- [x] [completed] **M1-03a — PoC validated: stromový přehled hlavního TODO v levém panelu.** Přehled zobrazuje uložené checklisty podle odsazení, stav dokončení a sbalitelné větve. Sdílí validovaný commit a zámek s přehledem projektu, bez mutací/recovery; nativní uložení využívá existující refresh. Starý výsledek se odstraní při změně projektu/načítání/chybě a opožděná odpověď se zahodí. Parser/čtení dokumentu sdílí editor a přehled přes `markdown_documents.py`. [Kontrakt](docs/adr/0016-markdown-editor.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **108 testů úspěšně, bez skipů**. Tři nové testy a rozšířený WebEngine smoke ověřují hierarchii/počet hotových položek, committed proti neuloženému obsahu, pending bez recovery, prázdný/nepodporovaný/velký TODO, readonly checkboxy, bezpečné texty, sbalení větví, vyčištění a opětovné načtení i restart. Vizuálně ověřen screenshot vlastního dočasného projektu. Regrese editoru, .deb a offline startu prošly. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. Limit přehledu je prvních 1000 položek s upozorněním; nadpisy nejsou stromové uzly a externí změny vyžadují nové otevření. Historie M1-04 nebyla zahájena.

- [x] [completed] **M1-04 — PoC validated: historie změn dokumentu.** Tlačítko Historie v editoru otevírá nativní readonly dialog s verzemi, datem/autorem/zprávou, původním Markdownem, metadaty a diffem uložených souborů. ArtifactHistory čte jen registrovaný projekt pod společným zámkem, kontroluje HEAD před/po čtení a odmítá pending bez recovery. Historické snapshoty validuje samostatně; neplatné verze zůstávají označené v seznamu. Full-history zachovává obě větve merge, diff nepouští externí drivery/textconv, draft se nemění. [ADR 0017](docs/adr/0017-artifact-history.md), [návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **116 testů úspěšně, bez skipů**. Osm nových testů pokrývá verze a diff checklistu/metadat, zachování HEAD/stagingu/journalu/indexu/draftů, unregistered/revspec/nedosažitelné revize, stale/busy/deadline/pending, historickou konfiguraci, invalidní snapshot, rename, obě větve merge, limit seznamu, smazání/recreate, zákaz externího diff driveru a skutečný Qt dialog se zachováním rozepsaného textu a vyčištěním výsledku po chybě. Vizuálně ověřen finální dialog nad vlastním dočasným projektem. Regrese .deb/offline/desktopu prošly; nový viewer má vlastní Qt test z checkoutu. `bash -n run.sh`, odkazy a `git diff --check` ověřeny. PoC limit: nejvýše 100 záznamů a 1 MiB těla; bez revertu, prohlížeče nyní smazaných artefaktů nebo nového cílového ověření na Omnii. Gate M1 zůstává otevřený.

- [x] [completed] **M1-03b — PoC validated: přepínání TODO a zdrojů/artefaktů v levém panelu.** Dvě readonly záložky používají společný snapshot otevřeného projektu. Seznam zahrnuje dokumenty i zdroje s názvem/ID. Přepínání kliknutím a šipkami/Home/End, zachovaná volba při refreshi a odstranění starých dat při přepnutí/chybě. Reuse existujícího seznamu artefaktů bez nového backendového endpointu nebo změn ukládání. [Návod](docs/project-opening.md).

  Ověření finálního kódu: `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: **117 testů úspěšně, bez skipů**. Nový test skutečného WebEngine ověřuje PDF zdroj vedle dokumentu, prázdný projekt a neměnný HEAD; rozšířený smoke kontroluje obě záložky, klávesnici/fokus/ARIA, přesné názvy/ID jako text, zachování volby při refreshi a vyčištění obsahu. Vizuální kontrola vlastního dočasného projektu, odkazy, `bash -n run.sh` a `git diff --check` prošly. Volba záložky je pouze pro aktuální okno; po restartu začíná TODO. Seznam zatím neotevírá obsah zdrojů. Metadata M1-05 nebyla zahájena.

## Gate review M0-09 — 2026-09-09

Historické posouzení před následným ručním deployem; novější důkaz je uveden u M0-05 a v dokončených výstupech. Aktuální rozhodnutí drží závěrečné M0-09R výše.

Posouzený HEAD: `1c7b228`, vstupní pracovní strom čistý. Výsledek: **Gate M0 nesplněn; M1 nezahajovat automaticky.** Review je dokončené, schválení gate nikoli. Nezavádí se nové architektonické rozhodnutí ani změna priorit nasazení.

| Kritérium | Důkaz a úroveň | Závěr |
| --- | --- | --- |
| Autoritativní data a obnova indexu | ADR 0002–0004, metadata/configuration/storage a jejich testy; designed + PoC validated | Splněno pro rozsah M0; integrace konfigurace a úplnější projekce zbývají V-03/V-08. |
| Koordinovaná obnova zápisu | ADR 0003 a tests/test_workspace.py: crash boundaries, CAS, pending stav, dva zapisovatelé | Splněno pro řízený Linux PoC; ne důkaz produkčního hardeningu nebo výpadku napájení. |
| Bezpečné lokální API a desktopové propojení | ADR 0006/0007, tests/test_local_api.py a tests/test_desktop.py | Návrh a PoC splněny; persistentní operace a nedůvěryhodný obsah zbývají V-10. |
| Konflikty entity a obsah/sidecar | M0-07, tests/test_merge_scenarios.py a FEDERATION | PoC splněno včetně sémanticky neplatného čistého merge; conflict UI a síťová federace nejsou implementované. |
| Orchestrace bez LLM, role, manifest, execution boundaries | ADR 0008 a návrhová tabulka scénářů | Designed splněno; LLM/RBAC implementace se neprohlašuje za hotovou. |
| Finální stack a distribuční cesta | ADR 0005 volí Git CLI; ADR 0007 pouze PoC binding; M0-06b zdrojový archiv | **Nesplněno:** finální backendový stack/binding a distribuční posouzení M0-06 zůstávají otevřené. |
| Cílové prostředí a provozní měření | M0-05 doložený LXC bez běhu aplikace; desktopové testy na vývojovém hostu | **Nesplněno:** měření na Omnia/ARMv7 a úplné posouzení startu, paměti a instalace cílových variant. |

Uživatel následně potvrdil úspěch ruční akceptace desktopu: kliknutí, zavření a restart fungují. Současné UI obsahuje jen paměťový čítač; nelze v něm ještě otevřít projekt, uložit artefakt ani ověřit zachování projektových dat po restartu. Ruční akceptace: třikrát „Ověřit spojení“ → 1/2/3, zavření → návrat terminálu, nový `./run.sh desktop` → 0 a opět funkční tlačítko. Výsledek je uživatelské potvrzení, nikoli nový automatický test.

Evidence testů je převzatá z dokončených úkolů níže (poslední plná sada u M0-07), nikoli nový běh v tomto review. Zkontrolovány současné zdroje UI, pokrytí testů, návaznost ADR a gate. Dokumentační ověření: lokální odkazy a finální diff. Po doplnění M0-05/M0-06 zopakovat rozhodnutí o gate s novými důkazy; dnešní negativní výsledek zachovat jako historii. Samotné potvrzení čítače gate neuzavře.

## Aktualizované posouzení M0 po instalaci .deb

Historické posouzení před offline testem; novější důkaz je níže v dokončených výstupech.

Posouzený HEAD `2b0adf2`, vstupní pracovní strom čistý. Historický review výše se nepřepisuje. Nové důkazy: PySide6 skutečné okno, měření desktopu a renderer crash (ADR 0010), instalační balík s izolovaným dpkg lifecycle (ADR 0011), uživatelsky potvrzené instalované GUI na Ubuntu arm64 a v Debian kontejneru x86_64 pod běžným uživatelem, headless Omnia demo na SSD. Poslední plná sada je u balíku: 69 testů, v tomto dokumentačním review nebyla opakována.

[Inventář kandidáta](docs/adr/0011-runtime-inventory.md) obsahuje SHA-256 balíku, přibalených souborů a distribučních copyright souborů 229 systémových závislostí na vývojovém hostu. Je úplný pro popsaný průchod Depends/Pre-Depends, nikoli univerzální SBOM všech platforem nebo hotový licenční audit. Uživatelův Debian má vlastní doložené verze; inventář Ubuntu se na něj nepřenáší.

**Výsledek: Gate M0 zůstává otevřený.** Podklady pro Python/Git/SQLite + PySide a .deb výrazně pokročily; funkční instalace neznamená finální schválení produkčního stacku. M0-06e zbývá izolovaný offline start a doložení čistého OS bez checkoutu/testovací vrstvy, M0-05 cílová provozní měření. Před zveřejněním balíku navíc zbývá skutečný maintainer kontakt, licenční posouzení a způsob aktualizací.

Uživatel přesměrovává X11 přes síť; odpojení jeho kontejneru by přerušilo i displej a nebylo by vhodným testem aplikace. Offline ověření zůstává planned, nikoli tvrzené jako úspěch ani obecně blocked. **Nejbližší konkrétní krok:** připravit lokální grafický smoke v oddělené síťové konfiguraci se zachovaným loopbackem a lokálním displejem, bez zásahu do uživatelova X11 spojení. Akceptace: žádná externí konektivita, funkční čítač, zavření/restart; zaznamenat způsob izolace a závislosti. V této změně se tento experiment nespouští.

## Dokončené výstupy a důkazy

- [x] [completed] **M0-09R — Designed: závěrečné Gate review.** Podmínky Gate M0 splněny podle tabulky výše; přechod do M1 schválen. První implementační úkol M1-01 vymezen bez zahájení implementace. Produkční omezení a historické negativní review zachovány.

- [x] [completed] **M0-05 — PoC validated: cílový běh a recovery na Omnii SSD.** Uživatel doložil `spikes.target_probe` s výsledkem PASS: Btrfs, armv7l, Python 3.13.5, SQLite 3.46.1, Git 2.47.3. Navazuje na potvrzený Debian LXC a SSD /dev/sda; pracovní adresář /var/tmp/workspace-poc. Všech 15 případů má verified=true: tři normální běhy a 12 pádů vlastního workeru. Probe ověřil pending čtení, zachování kandidáta, přesné bajty, jediný commit operace, idempotenci recovery, rebuild smazaného indexu a úklid dočasných dat. Jde o uživatelský cílový výstup, nikoli nový běh celé unittest sady. Původní demo 0,66 s běželo na tmpfs a nemíchá se s novými SSD měřeními.

  | Normální běh | Celý worker (s) | Apply (s) | Python peak RSS (KiB) |
  | --- | --- | --- | --- |
  | 1 | 0,8741 | 0,489111 | 11392 |
  | 2 | 0,8749 | 0,487234 | 11648 |
  | 3 | 0,8655 | 0,481006 | 11648 |

  | Hranice přerušení | Recovery (s) |
  | --- | --- |
  | prepared | 0,4496 |
  | file:0 | 0,4446 |
  | file:1 | 0,4455 |
  | applied | 0,4472 |
  | files-applied | 0,4243 |
  | commit-created | 0,4261 |
  | commit-ready | 0,2838 |
  | ref-updated | 0,2765 |
  | committed | 0,2620 |
  | git-indexed | 0,2606 |
  | indexed | 0,2758 |
  | completed | 0,0011 |

  `process_s` zahrnuje start Pythonu a inicializaci Git projektu, nikoli start serverové služby; RSS patří Python workeru, ne celému kontejneru/Git potomkům. Normální recover bez pending operace trval 0,0010–0,0011 s. Pád procesu na checkpointu není výpadek napájení ani pád uvnitř libovolného syscallu. Malá fixture není kapacitní benchmark. Úroveň je PoC validated pro zvolený stack; další produkční hardening drží V-06/V-07. Ověřena konzistence dodaných hodnot, odkazy a diff; Gate M0 čeká na review M0-09R.

- [x] [completed] **Implemented — cílový probe pro M0-05.** `spikes.target_probe` přenáší stávající crash scénáře do ručního deploye, vyžaduje explicitní základ a očekávaný filesystem, měří tři normální běhy a ověřuje 12 pádů workeru, obnovu a přesné bajty bez duplicitního commitu. Při úspěchu uklidí jen vlastní data, při selhání je ponechá. Lokální regresní testy pokrývají skutečné pády, chybný filesystem bez zápisu a zachování diagnostiky. Závěrečné `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 73 testů prošlo bez skipů. Ověřeny odkazy a finální diff. Skutečný běh na Omnia SSD zatím neproběhl v této změně, M0-05 zůstává otevřený.

- [x] [completed] **M0-06 — Designed: stack pro M1 uzavřen.** [ADR 0013](docs/adr/0013-m1-stack.md) přijímá Python, Git CLI, oddělené SQLite index/journal, PySide6/WebEngine, same-origin UI a linuxový .deb na základě již ověřených PoC. C++ port/hybrid není potřeba bez doloženého problému. Rozlišena volba technologií od produkčního HTTP serveru, release a cílových měření M0-05; gate zůstává otevřený. Ověřena návaznost ADR, odkazy a diff, bez nového běhu testů.

- [x] [completed] **M0-06e — PoC validated: instalační kandidát v čistém OS.** [ADR 0012](docs/adr/0012-clean-os-validation.md) dokládá nový oficiální Ubuntu 26.04 arm64 kontejner, skutečné stažení a vyřešení APT závislostí bez doporučených balíků, instalovaný launcher pod běžným uživatelem přes interní Xvfb, dva offline starty a upgrade/purge se zachováním kontrolních projektových/stavových souborů. Není použit checkout ani runtime hostitele. Dpkg audit čistý; runtime verze, velikosti, image digest a .deb hash zaznamenány. Kontejner odstraněn. Bez změny kódu a nového běhu celé unittest sady; provedeny skutečné instalační/grafické experimenty, kontrola odkazů a diffu. Inventář kandidáta drží ADR 0011; licenční posouzení veřejného releasu není tímto uzavřeno.

- [x] [completed] **PoC validated — offline grafický běh .deb.** `tests/test_desktop_offline.py` vytváří samostatný user/network namespace s pouze aktivním loopbackem; ověřuje namespace ID, nulové capabilities aplikace, nepřítomnost tras a odmítnutí externího TCP bez trasy. Lokální X11 socket zajišťuje skutečné okno, dva běhy ověřují kliknutí, zavření backendu a restart rozbaleného .deb. Hostitelská síť ani uživatelovo přesměrování X11 se nemění. Metoda a limity v ADR 0011; nejde o čistý OS ani obecný bezpečnostní sandbox. Závěrečné `M0_OFFLINE_TEST=1 M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 70 testů prošlo bez skipů. Odkazy a finální diff ověřeny.

- [x] [completed] **Designed — distribuční inventář a aktualizované M0 review.** Inventarizován konkrétní .deb a místní runtime, doplněny důkazy uživatelské instalace a omezení přesměrovaného X11. Rozhodnutí o gate zůstává otevřené; odkazy, shoda hashů a diff ověřeny, bez nového běhu aplikačních testů.

- [x] [completed] **Implemented — evidence uživatelského ověření .deb na druhém prostředí.** Uživatel hlásí funkční aplikaci v kontejneru; dodané os-release uvádí Debian GNU/Linux 13 Trixie 13.6, uname x86_64. Dpkg-query uvádí federated-workspace-poc 0.1.0~m0, python3 3.14.7-3, python3-pyside6.qtwebenginewidgets 6.8.2.1-4 a python3-yaml 6.0.3-1+b1. Jde o konkrétní uživatelské prostředí, nikoli automaticky standardní čistý Debian nebo obecnou podporu amd64. Původ balíků a offline start nejsou doloženy. Uživatel upřesnil spuštění instalovaného launcheru přes sudo -u user federated-workspace-poc: grafické okno tedy běželo pod běžným uživatelem, nikoli rootem. Funkčnost okna je uživatelsky potvrzená; diagnostický výpis pocházel z root shellu. Zaznamenání evidence neuzavírá M0-06e ani gate; bez nového běhu testů, ověřena konzistence a diff.

- [x] [completed] **Implemented / PoC validated — .deb kandidát a izolovaný dpkg lifecycle (část M0-06e).** `run.sh package-deb`, builder, launcher a desktop entry používají systémové závislosti bez instalace za běhu. Ověřeny obsah, nepřepsání výstupu, chybějící závislosti, upgrade/purge se zachováním kontrolních dat a skutečné instalované okno. Rozsah a předem popsané crash boundaries v ADR 0011; čistý OS test zůstává otevřený. Závěrečné `M0_DEB_TEST=1 M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 69 testů prošlo bez skipů. Ověřen výsledný .deb, shellová syntaxe, odkazy a finální diff.

- [x] [completed] **M0-06d — PoC validated: PySide6/WebEngine a měření desktopu.** Desktop i launcher používají PySide6 bez fallbacku na PyQt, shiboken6 zajišťuje pořadí destrukce objektů. Skutečný click/close/restart, pád rendereru a rozbalený zdrojový balík ověřeny. `PYTHONPATH=/tmp/m0-pyside M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 67 testů prošlo bez skipů. Ověřen launcher z /tmp a SIGTERM, bash syntax a help. Tři měřené běhy a omezení RSS/loadFinished jsou v [ADR 0010](docs/adr/0010-pyside-desktop-validation.md). Runtime moduly byly rozbaleny do /tmp, běžný uživatel je musí připravit dle README; čistá instalace zůstává M0-06e. Dokumentace, lokální odkazy a finální diff zkontrolovány.

- [x] [completed] **M0-06c — Designed: posouzení bindingu a distribuce.** [ADR 0009](docs/adr/0009-desktop-distribution-assessment.md) porovnává PyQt/PySide, zachování Python jádra a instalační varianty. Ověřeny oficiální licenční podklady, místní Qt/PyQt importy a apt kandidáti chybějících PySide WebEngine modulů. Doporučení PySide/.deb je podmíněné skutečným runtime a instalačním ověřením M0-06d/e. Žádná instalace ani změna kódu; dokumentační kontrola konzistence, odkazů a diffu, bez nového běhu testové sady.

- [x] [completed] **PoC validated — ruční deploy a storage demo na Omnii.** Uživatelem dodaný výstup potvrzuje instalaci PyYAML 6.0.3, vytvoření artefaktu a Git historie, index po znovuotevření, úklid dočasných dat a hlášku úspěšné instalace do current. Daemon se nespustil. Jde o úspěšný smoke běh, nikoli celou testovou sadu nebo recovery na cílovém zařízení. Následné orientační měření uživatele: celé demo 0,66 s, max RSS potomků 11 520 KiB, exit 0; podrobnosti a omezení u M0-05. Měřený běh používal /tmp na tmpfs. Další uživatelský výstup potvrzuje úspěšný neměřený běh s TMPDIR=/var/tmp/workspace-poc na /dev/sda/Btrfs, včetně indexu po znovuotevření a úklidu. Nejde o restart kontejneru ani test pádu. Zbývající ověření drží M0-05; desktopové připojení k serveru zatím neexistuje.

- [x] [completed] **M0-09 — Designed: Gate review před M1.** Kritéria, podklady a negativní rozhodnutí jsou v sekci Gate review výše. M0-05/M0-06 zůstávají otevřené; dokončení review neznamená splnění gate. Bez nového běhu testů a bez vzdáleného nasazení.

- [x] [completed] **M0-08 — Designed: kontrakty a pravidla publikace.** [ADR 0008](docs/adr/0008-context-and-publication-contracts.md) vymezuje Backend/Role/Context Manifest, přesné vstupy a cíl, autorizaci před odesláním, fallback, nejistý výsledek síťového volání a CAS publikaci při změně HEAD. Návrhové review scénářů zahrnuje uzel bez LLM, Ollamu, cloud, peer, local-only i zakázaný obsah v Git historii. Ověřena konzistence s ADR 0003/0004, roadmapou a odkazy; čistě dokumentační změna bez nového běhu testů. Implementace a akceptační scénáře navazují v M1–M5/V-10 a M3-UB-01; Gate M0 zůstává otevřený.

- [x] [completed] **M0-07 — PoC validated: zbývající merge scénáře.** `tests/test_merge_scenarios.py` ověřuje modify/delete s abortem a obnovou úplného páru obsah/sidecar, rename/edit s přesnými bajty a metadaty a textově čistý merge dvou validních větví s dangling relation. Validace kandidáta odmítne publikaci; úmyslně neplatný commit v negativním testu nenahradí index a čtení odmítne stale stav. Ověřena lidská oprava a rodiče merge; scénáře a limity jsou ve FEDERATION. Produkční synchronizace ani conflict UI nevznikají. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 66 testů prošlo bez skipů. Ověřeny lokální odkazy a finální diff.
- [x] [completed] **V-02 — PoC validated: přesný důvod odmítnutí duplicity indexem.** Existující test ve `tests/test_storage.py` nyní vytváří platnou Markdown entitu se stejným ID jako registr a vyžaduje chybu Duplicate ID; zachování indexu a odmítnutí stale čtení zůstává ověřeno. Původní nesoulad názvu JSON souboru již výsledek nezastíní.

- [x] [completed] **M0-06b — Implemented: reprodukovatelný zdrojový desktopový balíček.** `run.sh package-desktop` vytváří allowlistovaný tar.gz s manifestem SHA256, bez privátního katalogu, prostředí a binárních závislostí. Atomické zveřejnění kompletního souboru bez přepsání existujícího vydání; ověření rozbalené kopie je součástí grafických testů. Systémový runtime stále vyžaduje Python/Qt/PyYAML; finální binding, distribuční licence, instalační balík a M0-05 zůstávají otevřené. Závěrečná sada `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 63 testů prošlo bez skipů, včetně skutečného WebEngine z rozbaleného archivu mimo checkout. Bash syntax, lokální odkazy, finální diff a sestavení archivu ověřeny.

- [x] [completed] **Implemented — ruční deploy headless PoC na Omnii.** `run.sh deploy-omnia` poskytuje dry-run a explicitní SSH nasazení do běžícího Debian LXC na SSD, omezený archiv zdrojů, oddělená vydání a přepnutí current až po demu. Lokální testy ověřují obsah archivu, validaci vstupů, chyby SSH a zachování previous/current po chybě instalace. Závěrečná sada s `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1`: 60 testů prošlo bez skipů; bash syntax, dry-run, odkazy a diff ověřeny. Vzdálený deploy nebyl spuštěn; uživatel jej provede ručně, M0-05 zůstává otevřené.

- [x] [completed] **Designed — rozsah importu Drive, NotebookLM a konverzací.** Doplněna sekce 3C roadmapy a IMP-01 až IMP-03. Ověřeny oficiální podklady k dílčím API/exportům, lokální odkazy a diff. Konektory, autentizace ani parsery exportů nejsou implementované; žádná uživatelská cloudová data nebyla načtena.

- [x] [completed] **M0-06a — PoC validated: spustitelné desktopové okno.** `./run.sh desktop`, `spikes/desktop.py` a `desktop_ui.py` adaptují existující lokální API; Qt okno používá stejný Python proces s backendovým vláknem, token pouze v nativní části a off-the-record WebEngine. Skutečné UI/JS kliknutí ověřuje autentizované API a zavření backendu; nový start resetuje čítač. [ADR 0007](docs/adr/0007-desktop-poc.md) vymezuje změnu pořadí na žádost uživatele a otevřené produkční balení/licence i M0-05. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 56 testů prošlo bez skipů. Ověřeno vykreslené okno ze screenshotu, `bash -n run.sh`, help/chybné argumenty a skutečný launcher z /tmp včetně SIGTERM. Kontrola odkazů, soukromých údajů a diffu dokončena.

- [x] [completed] **M0-04 — PoC validated: lokální socket a loopback HTTP.** `spikes/local_api.py` a sedm testů v `tests/test_local_api.py` porovnávají stejný paměťový endpoint přes Unix socket a IPv4 loopback. Ověřeny token/rotace, Host/Origin, CSRF formáty/metody, UID/práva, limity/duplicity JSON a hlaviček, timeout a pipelining; odmítnuté požadavky nemění stav. [ADR 0006](docs/adr/0006-local-api-transport.md) preferuje same-origin loopback HTTP pro navazující UI, s Unix alternativou. Browser/obal, bootstrap tokenu a napojení Workspace zůstávají V-10. Závěrečné `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 53 testů prošlo bez skipů. Sandbox původně odmítl bind; běh s povolenými lokálními sockety uspěl. Dokumentace, odkazy a `git diff --check` ověřeny.

- [x] [completed] **R-00 — Implemented: oddělený veřejný a soukromý reuse katalog.** REUSE_CATALOG obsahuje technologie a komponenty workspace; seznam veřejných externích repozitářů je zatím prázdný. Lokální inventura je v `REUSE_CATALOG.private.md`, vyloučeném z Gitu. Ověřeny odkazy, absence soukromých detailů ve změněných veřejných dokumentech, ignore pravidlo a diff; bez nového běhu aplikačních testů. Detailní posouzení před převzetím zůstává R-01.

- [x] [completed] **M0-03 — PoC validated: Git CLI vs. C++/libgit2.** `spikes/libgit2/probe.cpp` sestaven s C++17 a `-Wall -Wextra -Werror` proti libgit2 1.9.1. `tests/test_git_comparison.py` spouští obě varianty nad stejnými scénáři commit/branch/clone/fetch, divergence/abort/merge, CAS a restart před/po publikaci, odmítnutí neplatné projekce a loopback HTTP autentizace. Finální `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 46 testů prošlo bez skipů. HTTP test vyžaduje povolený loopback socket; bez explicitních voleb jsou srovnávací testy skipped. [ADR 0005](docs/adr/0005-git-adapter-comparison.md) zachovává Git CLI jako výchozí adapter; libgit2 je ověřená alternativa, ne produkční náhrada Workspace. Zaznamenány build/runtime závislosti a orientační velikosti/start; cílové balení M0-05/M0-06 a produkční transporty V-09 zbývají. Hlavičky byly pouze rozbaleny do /tmp; systém ani produkční stack nebyly změněny.

- [x] [completed] **M0-02 — PoC validated: minimální project.json a konfigurace uzlu.** `spikes/configuration.py` a read-only `check_config`/`run.sh config` validují přenositelný projekt, lokální uzel, stabilní UUID, verzi v1, nepřekrývající se lokální cesty a opaque credential reference. Sdíleny parserové limity a UUID/timestamp pravidla; neznámé verze se odmítají bez migrace. Kontrakt a budoucí explicitní migrační pravidla: [ADR 0004](docs/adr/0004-project-node-config.md), příklady v DATA_MODEL. Deset nových testů konfigurace pokrývá i chybové cesty a read-only CLI. `python3 -m unittest discover -s tests -v`: 42 testů prošlo; `bash -n run.sh` a kontrola dokumentovaných příkladů/odkazů prošly. Zapojení konfigurace do aplikačního lifecycle, ověření identity/vaultu a migrační zápis zbývají V-08; distribuce uživatelů není implementována.

- [x] [completed] **Implemented — shellový launcher storage PoC.** `run.sh` poskytuje výchozí dočasné demo, explicitní setup do `.venv`, test, check a help; `spikes/demo.py` používá existující Workspace/Git a lifecycle podle ADR 0003. Ověřeno demo, `bash -n`, spuštění z cizího adresáře, relativní cesta s mezerami, chyby argumentů a neplatný/chybějící projekt bez zápisu. Přes `./run.sh test` prošlo 32 testů. Síťová instalace `setup` nebyla v tomto běhu provedena. Launcher není UI/server; běžná aplikace a balení zůstávají v M1.

- [x] [completed] **Implemented — optimalizace projektových instrukcí AGENTS.md.** Rozlišeno čtení pro návrh, dokumentaci a implementaci; doplněno opětovné použití nezměněných podkladů, pravidlo „další úkol“, aktualizace TODO po uceleném výsledku a evidence ověření bez duplikace počtů testů. Crash boundaries přesunuty před implementaci, zpřesněno cílené a závěrečné ověření. Architektonické mantinely, LLM workflow a pravidla commitů zachovány. Ověřena konzistence, lokální odkazy a diff; čistě dokumentační změna bez nového běhu testů.

- [x] **[completed] M0-01 — Jedna koordinovaná operace journal → validace → Git commit → index.**
  **PoC validated:** `spikes/workspace.py` adaptuje Journal/Git/Index a poskytuje apply/recover/read/receipt. Společný zámek, trvalé UUID a kandidátní commit před compare-and-swap posunem větve, blokované čtení pending operace a dokončený receipt. `tests/test_workspace.py`: 13 nových testů, včetně skutečných pádů procesu a dvou zapisovatelů; celkem 32 testů prošlo. Podrobnosti: [ADR 0003](docs/adr/0003-coordinated-operation.md). Původní akceptační požadavky:

  Operace musí mít stabilní `operation_id` a explicitní stavový životní cyklus. Minimálně musí být možné po restartu rozlišit:

  `prepared → files-applied → committed → indexed`

  Implementace nemusí použít přesně tyto názvy, ale stav musí být obnovitelný bez odhadu podle neúplných vedlejších efektů.

  Journal / operation record nesmí být definitivně odstraněn pouze proto, že byly úspěšně zapsány soubory. Musí zůstat dost informace k rozpoznání, zda příslušný Git commit již vznikl a zda byl index aktualizován.

  Operace eviduje minimálně:

  - operation ID,
  - výchozí HEAD,
  - zamýšlené změněné cesty,
  - stav operace,
  - po commitu výsledný commit ID.

  Recovery musí být idempotentní: opakovaný restart nesmí vytvořit další commit stejné operace.

  Git commit nesmí používat neomezené `git add --all`. Musí commitnout pouze cesty vlastněné aktuální operací, nebo operaci bezpečně odmítnout, pokud nelze oddělit cizí změny.

  Před commitem ověřit, že HEAD stále odpovídá výchozímu HEAD operace. Změna HEAD během operace nesmí být tiše přepsána.

  Akceptace: zámek pokrývá celý životní cyklus, pending stav brání publikaci neúplného projektu; commit obsahuje pouze zamýšlené změny a explicitního autora; restart po zápisu/před commitem i po commitu/před indexací neztratí změny ani nevytvoří duplicitní commit. Ověřit změnu HEAD, cizí rozpracované změny, opakovanou obnovu a dva kooperující zapisovatele. Původní podklad: ADR 0002; samostatný `Git.commit` zůstává testovacím helperem s `add --all`. Workspace jej nepoužívá a drží journal až do indexace. Limity: existující commit a běžná větev, čistý vstup, kooperující procesy se společným stavovým adresářem; ne produkční aplikace.

- [x] [completed] **IP-00 — Implemented: dokumentační integrace IP roadmapy.** Zachována podpůrná roadmapa v `docs/IP`, založeny PATENT_RISK_REGISTER a DEFENSIVE_DISCLOSURES s neověřeným watchlistem a rezervovanými DD náměty; propojeny master roadmapa, README a CONTRIBUTING. Zohledněna existující MPL-2.0. Ověřeny lokální odkazy, věcná konzistence a diff; patentová rešerše, publikace, DOI a crowdfunding zůstávají neprovedené.

- [x] **[completed] Designed — základní návrhy a kostra experimentů.** ARCHITECTURE, DATA_MODEL, FEDERATION, SECURITY, REUSE_CATALOG a ADR 0001/0002 existují; aplikační skeleton, síť ani UI tím nejsou hotové.
- [x] **[completed] PoC validated — Git divergence a historie.** `tests/test_storage.py`: dvě lokální repo kopie, tři konfliktní verze, abort, merge se dvěma rodiči. Žádná síťová federace/autentizace.
- [x] **[completed] PoC validated — validace artefaktů a registrů.** `spikes/metadata.py`, `tests/test_metadata.py`: schéma, UUID, JSON/YAML duplicity, limity, frontmatter, sidecar a vztahy.
- [x] **[completed] PoC validated — SQLite index.** `spikes/storage.py`, `tests/test_storage.py`: validovaný commit, stale detection, obnova z HEAD i po odstranění databáze, oddělení necommitnutých změn.
- [x] **[completed] PoC validated — souborový journal.** `spikes/journal.py`, `tests/test_journal.py`: vytvoření, přejmenování, smazání, přerušená obnova, cizí editace, zachování binárních bajtů a návazný ručně koordinovaný commit/index. Testy používají skutečné `os._exit` v pomocném procesu.
- [x] **[completed] Implemented, ručně ověřeno — CLI validátor projekce.** `spikes/check_project.py`; důkaz smoke testu v ADR 0002, automatizace zbývá V-01.
- [x] **[completed] Implemented — vývojový workflow.** AGENTS.md, tento TODO a reconciliace roadmapy vůči kódu; architektura, ADR a experimenty zachovány.

## Posouzení repozitáře k 2026-09-09

Výchozí HEAD posouzení: `71424f2`; pracovní strom byl čistý. Přečteny dokumenty, oba ADR, všechny spikes a testy. Opětovně spuštěno `python3 -m unittest discover -s tests -v`: **19 testů prošlo** na současném vývojovém hostu. Repozitář neobsahuje nakonfigurovaný build/lint/CI. Přehled neprohlašuje produkční připravenost.

Rozpory a opravy stavu: nezaškrtnuté frontmatter/sidecar, index a definice metadat v roadmapě jsou nyní výslovně PoC validated; původní operativní seznam sekce 19 je převeden sem. Návrhové body backendu, federace, desktopu a bezpečnosti jsou designed, ne implementované. Katalog SQLite nyní zahrnuje i lokální autoritativní journal, což nemění rozhodnutí o neautoritativním projektovém indexu. Věcné otevřené mezery metadat, indexu a testových důkazů jsou V-01 až V-06. Historické počty testů v ADR 0001/0002 zachovávají význam výsledků jednotlivých experimentů.
