<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — DEV-01

Aktivní feature dávka: **Roadmapa jako projektová data a export úkolů**.
Milník: vlastní rozvoj produktu, návaznost M6. Původní požadavek: DEV-01,
uživatelská upřesnění 28. 10. 2026 — roadmapa včetně vložených modulů;
po PR #112 připravit nejprve plán migrace.
Skutečná větev: `feature/dev-01-roadmap-migration`, založena z čistého
`develop` `83d882d` po merge DEV-IDE-TODO-01 v PR #112.
Základ/cíl jediného PR: `develop`. PR této dávky není vytvořen ani sloučen.
Cíl dávky: **implemented → PoC validated**; návrh je **designed**,
read-only inventura **implemented**.
Návrh: [plán migrace](docs/roadmap-migration.md). Samotná migrace ani přepnutí
autority zatím neproběhly. Návrh uživatel schválil; probíhá inventura
a příprava mapovacího náhledu.

## Původní rozsah a akceptace DEV-01

Po `PLAN-TASK-GRAPH-01` převést uživatelem vybraný rozsah roadmapy do verzovaných entit požadavků, milníků, feature dávek, rozhodnutí, rizik, závislostí a úkolů bez vytvoření druhého autoritativního plánu. Akceptace: stabilní ID a provenance na zdrojovou revizi, opakovaný import bez duplikace, konflikt ruční a zdrojové změny, odstraněný/přejmenovaný bod a export Markdown TODO i strojově čitelného task balíčku se scope, dependencies a acceptance. Export nemění stav zdrojového úkolu; interní roadmapa použije stejný obecný plánovací kontrakt jako ostatní projekty. Uživatelské doplnění 28. 10. 2026: migrovat také vložené moduly a doplňkové roadmapy s jejich úkoly a popisy; zachovat hierarchii, include vazby, stabilní ID a provenance. Před migrací určit kanonický zdroj každé definice, ověřit úplnost vložených modulů a stanovit přechod autority do Workspace bez konkurenčního živého plánu ve zdrojovém repozitáři.

Hranice: import vybraných dokumentů do existujícího projektu, explicitní
mapování modulů na cílové projekty, úplná provenance, bez druhého živého plánu.
UI úkolů v IDE a automatické review zpráv zůstávají v DEV-02/DEV-03.
Závislosti PLAN-TASK-GRAPH-01, ADR 0059 / file-plan editor a bridge jsou
začleněné do základu. Nové entity požadavků/rozhodnutí/rizik se neprohlašují
za implementované místo jejich zachování v podpůrných dokumentech.

## Upřesnění uživatele v rámci DEV-01

Cílová roadmapa ve Workspace je celá testovací a není zdrojem dat. Uživatel
výslovně autorizoval její kompletní nahrazení; nepřenášet testovací úkoly,
vazby ani stavy a nevytvářet z nich povinné migrační konflikty. Staré zprávy
jsou transportní historie, nikoli požadavek zachovat testovací plán.
Migrace má zahrnout i historické a realizované úkoly a dávky. Obecné myšlenky
mají být volným popisem pod jasným milníkem/dávkou; nejednoznačný obsah
samostatnými `.md` podklady. Nevyrábět pro něj umělé úkoly ani dávky.
První fyzický import a jeho deep-check výsledky uživatel 29. 10. 2026 odmítl
jako celek: nepřebírat z nich uzly, IDs ani schválené proposals a neopravovat je
ručně. Nová migrace vznikne source-first pouze z původních sekvenčních dat
pomocí lokálního LLM; starý import kompletně nahradí až potvrzený nový bundle.

## Úkoly dávky

- [x] [completed] **DEV-01-A — návrh migrace (designed).**
  Inventura zdrojů a existujících kontraktů, mapování ID/typů, moduly,
  preview, konflikty, recovery a předání autority. Podrobný návrh v odkazu výše.
  Návrh byl uživatelem schválen a následně upřesněn výše; fyzická migrace
  zatím akceptována ani provedena nebyla.
- [ ] [in progress] **DEV-01-B — potvrzený manifest a mapování (designed).**
  Přesné soubory/revize, cílový existující projekt, seznam a cíle externích
  modulů, ID bez identity, konflikty a zacházení s ukázkovým cílovým plánem.
  Výstup: úplný coverage report; žádné tiché vynechání nebo automatické smazání.
  První konkrétní report: `/tmp/dev-01-inventory-final-20261028/summary.md`
  a `inventory.json`. Zdrojový host commit `27d88d4`, explicitně vybraný
  publikační modul commit `446d980`; 13 souborů, 1361 checkbox výskytů,
  570 explicitních ID v rámci zdrojových repozitářů a 864 checkboxů bez ID.
  Nejde o počty samostatných úkolů. Návrh mapuje 821 anonymních bodů na
  požadavky, 4 na strategické požadavky a 39 na historické důkazy;
  18 opakovaně zmíněných ID má navržené jediné místo definice a zachované
  všechny zdrojové výskyty. Všechny 75 existující dependency uzly mají
  dohledatelnou definici, graf je validovaný. Nebyl nalezen rozpor samotných
  checkbox stavů; shoda stavu není důkaz sémantické shody popisů.
  Mapování zůstává návrhem (`mapping_approved: false`), nikoli potvrzeným
  plánem: zbývá obsahové rozlišení typů/hierarchie a konkrétní cíle modulů
  modulových projektů. Nakládání s testovacím cílem již není otevřená otázka:
  úplně ho nahradit bez používání jeho obsahu jako zdroje. Zdrojové bajty a hashe zůstávají
  dohledatelné; chybějící ID nejsou bez review vydávána za executable tasky.
  Předběžná MIG-REQ ID platí jen pro tento připnutý návrh; před importem se
  musí schválená mapa persistovat, ne generovat znovu po přejmenování.
  Reuse/adapt: Git wrapper, validátor modulového manifestu a topologické
  ověření existujícího roadmapového grafu. Žádná síťová volání ani zápis
  do projektu, Gitu, SQLite indexu či journalu. Pád inventury cílová data
  nemění; neúplný lokální report lze vytvořit znovu v novém adresáři.
- [ ] [in progress] **DEV-01-C — import preview a stabilní identity (implemented).**
  Deterministický náhled, přesné source bajty, provenance, mapování existujících
  a nových ID, validace úplného bundle a kontrola limitů před zápisem.
  Historický náhled v1: `/tmp/dev-01-hierarchy-reviewed/summary.md` a `mapping.json`.
  Aktualizovaná inventura čte host commit `f55c0ec`, stejný modulový commit
  `446d980`; zdrojové bajty jsou součástí privátního reportu. Pokryto je všech
  1456 výskytů včetně nadpisových definic, nikoli jen 1361 checkboxů.
  Profilovaná podmnožina prošla stávajícím task-graph validátorem: hlavní
  projekt 3 milestone / 16 batch / 82 task, modul 1 milestone / 1 batch / 8 task.
  Strategické požadavky a nezahrnuté historické položky zůstávají v katalogu
  s původními ID/provenance; nejsou automaticky povýšeny na feature dávky.
  Checklist podmínky mají vlastníka v tasku, nikoli duplicitní požadavek.
  Celková akceptace dávky se neodvozuje z počtu zaškrtnutých podúkolů.
  Dva historicky completed uzly `F-M5-CHAT-HISTORY-01` a
  `F-M5-SYNC-CONTROLS-01` mají dependency hranici proti plánovanému rozsahu;
  rozporné hrany i původní stavy se zachovaly, do nové profilované části se
  bez rozhodnutí nepromítají. Nejde o nové rozhodnutí jejich stav změnit.
  Read-only načtení skutečného cíle potvrdilo HEAD `c36af3e` a čistý strom.
  Report obsahuje původní hlavní TODO a konkrétní `federated-workspace/target.diff`.
  Původní ukázkové MILESTONE-01/02/03, BATCH-01 a TASK-01 nejsou v novém návrhu:
  tehdy se uvažovalo o archivaci v novém plánu. Tuto podmínku nyní ruší
  výslovný pokyn uživatele: testovací plán není zdroj a nepřebírá se. Git
  historie/transportní receipts se tím automaticky nemažou; aliasy nejsou potřeba.
  Zmrazený mapping je svázán s inventory SHA-256; replay dal totožný výsledek,
  změněný zdroj vyžaduje explicitní rebase. Návrhy ID a definic nejsou tímto
  uživatelsky schválené a `import_ready` zůstává false.
  Zbývá úplný náhled metadat/operace přes všechny artefakty, review širokých
  požadavků, potvrzení modulového cíle a zdrojové identity při změně revize;
  samotný validní task graf není validací celého importu.
  Reuse/adapt: existující source katalog `_catalog`, profilovaný task graph,
  Projects.repository (bez inicializace indexu/journalu). Zápisový lifecycle
  ADR 0003 se nemění; tento krok zapisuje jen nový privátní report do /tmp.
  Pád při vytváření reportu nemění zdroj ani cílový projekt a není receipt
  importu. Další report používá nový adresář, původní se nepřepisuje.
  Aktuální náhled v2: `/tmp/dev-01-history-inclusive-preview/summary.md`,
  host source commit `145a02e`, module source commit `446d980`. Profilovaný
  hlavní plán má 10 milníků / 93 dávek / 384 úkolů; modul 10 / 1 / 8.
  Podporovaná část nyní zahrnuje všechny kanonické historické nadpisové
  záznamy WORK_LOG, i mimo starý graf. Samostatné starší úkoly bez doložené
  dávky zůstávají s původními ID/stavy v Markdown textu u milníku nebo v
  samostatném podkladu; nevytváříme fiktivní feature batch.
  Celkem 193 popisových Markdown dokumentů: 111 přiřazených vlastníkovi,
  82 samostatných. Volné myšlenky nejsou vykazované jako implementační tasky.
  M0/M1 mají stav převzatý jen z explicitních gate důkazů hlavní roadmapy.
  Historicky dokončená F-M5-CHAT-HISTORY-01 zůstává v roadmapě; vazba na
  plánovanou F-M5-TRUST-01 je historický kontext, nikoli důkaz dokončení TRUST.
  Politika `replace-test-plan` má autorizaci uživatele, ale `apply_validated`
  zůstává false, dokud není připraven celý artefaktový zápis. Testovací cílový
  obsah není v source_refs, normalizovaných uzlech ani odvozených podkladech.
  Aktuální report prošel task-graph validací; zůstávají otevřené úplné metadata,
  přemapování zdrojových odkazů, zápis/recovery a skutečné nasazení migrace.
  Bod 1 požadovaný uživatelem — sestavení celé logické operace — je připraven:
  `/tmp/dev-01-import-operation/summary.md` a `operation.json`. Zdrojový host
  commit `06ffda3`, modul `446d980`; inputy jsou připnuté v
  `/tmp/dev-01-step1-source` a `/tmp/dev-01-step1-mapping`.
  Hlavní projekt: 196 artefaktů / 392 souborů; modul: 17 / 34.
  Payload obsahuje hlavní plány, 193 Markdown popisů/podkladů, přesné
  originální zdroje, sidecar metadata, scoped mapování ID, source manifesty
  a propojení na navržený modulový projekt. Root ID a immutable metadata
  hlavního TODO zůstávají zachované; testovací text ani mutable popisky
  nejsou importovanými zdroji. Interní text modulu zůstává v modulovém payloadu.
  Manifest obsahuje samostatné operation ID, dependency modul → host,
  create/replace akce a hashe všech souborů; žádné implicitní mazání ostatních
  entit. Module project UUID je návrh podporovaný seeded create, fyzická
  cesta se ještě nezadává ani nevytváří.
  Základní schema a task graph celých payloadů prošly, včetně zachování
  ID/typů/rodičů a checkbox stavů. Bod 2 (úplná kontextová předzápisová
  validace) byl proveden read-only validátorem proti celému živému snapshotu;
  report je `/tmp/dev-01-prewrite-review-3/summary.md` a `review.json`.
  Devět kontrol prošlo: uzavření manifestu/blobů/payload mirror, lokální
  autor, modulový seed a jeho task graph, nativní replica policy, čistý
  očekávaný host HEAD, prázdný journal a celý sloučený snapshot včetně
  `validate_transition` a task graphu.
  První prověrku blokovalo 184 nepřevedených relativních odkazů v odvozených
  host dokumentech (72 odlišných cílů) a nezvolená fyzická cesta nového modulu.
  Oba blokátory jsou v opraveném balíku odstraněné. Vybrané zdroje se
  odkazují na importované artifact cesty; nevybrané cíle zůstávají čitelnou,
  neaktivní zdrojovou cestou. Modulová operace explicitně drží cíl
  `/home/antonin/Projekty/publication-experiment-registry`; read-only kontrola
  mimo vývojový sandbox potvrdila volný cíl, state adresář, skutečná práva
  parentu a nepřekrývání chráněných cest. Nic nebylo vytvořeno.
  Nový balík `/tmp/dev-01-import-operation-v3` má SHA-256
  `ae0df1d730259fa233ef87f6a253969674d96e6b2e08c7bc080a0476fa558e99`;
  `/tmp/dev-01-prewrite-review-v3-host` hlásí 11 passed / 0 blocked /
  3 needs-review. Tyto review body jsou nyní uzavřené manifestem
  `docs/roadmap-migration-source-review.json`, který je svázaný s bundle SHA,
  hashem každého zdroje a přesnou množinou URL/výskytů. Všech 13 zdrojů je
  po obsahové kontrole `project`: nejsou v nich credentials, privátní klíče,
  osobní e-maily ani domácí cesty; interní testovací IP a popisy secret
  lifecycle nejsou hodnotami tajemství. Osm unikátních externích URL
  (devět výskytů) bylo dohledáno na oficiálních cílech; OpenAI Help URL má
  doložené přesměrování a GitHub API potvrdilo sloučený PR #68.
  `/tmp/dev-01-prewrite-review-v4-host` hlásí 14 passed / 0 blocked /
  0 needs-review a `prewrite_checks_passed: true`. Validátor je uzavřený,
  nic nevytváří v projektu ani state a neakceptuje nesvázané nebo neúplné
  review vstupy.
  Writer/recovery a fyzický import zůstávají otevřené.
  `import_ready` je false. Vznik balíku nepoužívá projektový journal ani
  zapisující Workspace: pád před finálním manifestem zanechá jen neúplný
  report, který není importním receiptem. Retry použije zmrazené payloady.
- [ ] [in progress] **DEV-01-D — bezpečný apply a opakovaný import (implemented).**
  Stávající autorizovaný writer, expected HEAD/digest, víceartefaktová
  transakce, receipts, idempotence, třícestné porovnání, rename/removal review
  a crash recovery podle plánu. Žádné přímé SQL nebo obcházení Workspace.
  Implementace používá `ProjectCreation.create` pro přesný seeded modul a
  jednu `Workspace.transact` operaci pro všechny hostitelské cesty. Vyžaduje
  exact bundle SHA a bundle-bound review; create/replace kolize i expected HEAD
  se znovu kontrolují pod nativními zámky. Stabilní operation ID a request
  digest vracejí nativní receipts při lost-response retry. Mezi projekty není
  předstíraná atomicita: dokončený modul se nerollbackuje, navazující host
  operace se bezpečně dokončí při retry. Souhrnný receipt není nový store.
  Izolovaně ověřen normální apply/replay bez druhého commitu, pád mezi
  projekty, recovery hostu od `prepared` a odmítnutí nesprávného explicitního
  bundle SHA před zápisem. Fyzický apply na skutečný projekt patří DEV-01-F
  a zatím spuštěn nebyl. Pro uzavření D ještě zbývá doložit navazující
  import nové source revize: ruční změnu proti novému mappingu, explicitní
  rename/removal review a odmítnutí tichého přepsání. Aktuální one-shot
  balík žádné deletion akce neobsahuje, takže je nelze vydávat za ověřené.
- [ ] [planned] **DEV-01-E — izolovaná zkouška a export (PoC validated).**
  Reálné připnuté zdroje a modulový vzorek, Markdown/strojový task export,
  konflikty, změny revizí, limity a injektované pády. Po poslední relevantní
  změně spustit celou unittest bránu.
- [ ] [in progress] **DEV-01-E-REFINE-01 — iterativní lokální dotřídění (implemented).**
  Ad-hoc doplnění uživatele po fyzickém importu: resumovatelný same-node
  Ollama crawl, který navrhuje dávky oprav, vyžaduje lidské potvrzení a lze jej
  opakovat do konvergence. První bezpečný řez umí pouze připojit samostatný
  podklad pod existující milestone/batch/task nebo jej ponechat samostatně;
  nemění ID/stavy/text, nemaže a nepovyšuje zachované požadavky na uzly.
  Proposal queue je privátní node-local SQLite, vstup má Context Manifest a
  exact HEAD. `unknown`/`failed` se automaticky neopakují; fingerprint zahrnuje
  obsah, katalog cílů a revizi analyzátoru. Accepted dávka se zapisuje jednou
  `Workspace.transact` operací a znovu prochází task-graph validací.
  Izolovaně ověřen proposal-only scan, deduplikace, terminální reject, odmítnutí
  vymyšleného cíle, jediný validovaný apply a striktní oddělení sdílené lokální
  queue podle project ID. První živý běh nad 82
  samostatnými podklady: starý velký kontext `unknown`, zmenšený kontext
  uspěl; revize v3 vytvořila 1 dismissed / 1 pending / 1 failed. Pending
  `COMP-01-A` je obsahově chybný a nebyl potvrzen ani aplikován. Failed
  rozpoznání `IMP-03` bezpečně odmítla absence tohoto ID v executable grafu.
  Návod a evidence: `docs/roadmap-refinement.md`. Zbývá lidské review první
  dávky, delší crawl a podle jeho nálezů explicitní proposal typy pro
  promotion/split/merge; nejsou součástí aktuálního bezpečného apply.
  Jednorázové stdlib `curses` TUI nyní poskytuje list/detail, explicitní bounded
  scan, accept/reject a dvoukrokově potvrzený apply bez druhého storu či writeru.
  Review z přesného proposal HEAD doplňuje čitelný název a cestu zdroje,
  `zdroj → cíl`, název/typ cíle, popis dopadu a náhled zdrojového textu;
  technická UUID a HEAD zůstávají v auditní části. Tabulka a detail mají
  přepínatelný fokus a samostatné stránkování; filtr umí skrýt accepted,
  rejected, dismissed a applied položky bez ztráty jejich stavu nebo apply.
  Scan běží v background threadu s živým UI a chráněným ukončením; tabulkové
  buňky jsou ohraničené, víceřádkové a vybraný blok se drží uprostřed viewportu.
  Vykreslovací hranice normalizuje newline/tab/CR a další řídicí znaky, takže
  importovaný víceřádkový text nemůže posunem kurzoru rozbít sousední buňky.
  TUI lze spustit i bez project ID: read-only katalog nabídne lokální projekty
  názvem a UUID, nedostupný projekt odmítne a po potvrzení otevře jeho oddělenou
  proposal queue. Přímé `--project` a povinné UUID neinteraktivních příkazů
  zůstávají zachované.
- [ ] [in progress] **DEV-01-E-RECONCILE-01 — úplná jednorázová sémantická
  reconciliation importu (implemented proposal scan).** Uživatelský požadavek 2026-10-28:
  popsat původní sekvenční workflow TODO → celý batch ve WORK_LOG, význam
  BACKLOGu/Master Checklistu a požadovaný nový kanonický stav; nad všemi
  hostitelskými i vybranými modulovými roadmapami nejprve vytvořit konečnou
  resumovatelnou source-cluster queue a poté ji nechat přes noc zpracovat
  same-node Ollamou. Výstupem jsou pouze typované návrhy keep-history/
  description/canonical, promote, residual, split/merge, update, dependency a
  conflict s exact source/target provenance; žádný průběžný zápis. Human review
  složí přijaté návrhy do jednoho kandidáta, celý graf validuje a teprve jedna
  potvrzená `Workspace.transact` operace proti původnímu HEAD může změnit plán.
  Crash boundaries, noční recovery, coverage a akceptace jsou v
  `docs/roadmap-reconciliation.md`. Režim `scan --deep-check` nyní před dispatch
  zmrazí kompletní source-cluster inventuru proti exact HEAD, dohledá stejné ID
  v podpůrných Markdown podkladech, dávkově vytváří striktně validované návrhy
  ve stejné SQLite queue a používá společné list/decide/TUI. Restart pokračuje
  jen z `queued`, zbylé `running` fail-closed převede na `unknown`; paralelní
  deep scan blokuje node-local lock. Accepted strukturovaný návrh zatím `apply`
  odmítne před zápisem. Otevřené zůstává skládání a validace společného
  kandidáta, transakční writer, fyzický úplný scan a review; obecná produktová
  integrace je nadále samostatný `PLAN-SEMANTIC-AUDIT-01` k předání do backlogu.
  Cílené ověření 2026-10-28: `python3 -m unittest
  tests.test_roadmap_refinement tests.test_roadmap_refinement_tui -v` — 20/20
  testů prošlo; CLI help potvrzuje `scan --deep-check`, `git diff --check`
  prošel. Fyzický Ollama běh nad importovaným projektem nebyl v tomto kroku
  spuštěn.
  Následně přibyla explicitní volba `--forget-previous`: pod node-local lockem
  smaže pouze deep-check queue vybraného projektu a z aktuálního HEAD ji znovu
  vytvoří; detached rozhodnutí ani Git nemění.
  Ad-hoc oprava pomalého otevření TUI: `refresh()` již nestaví exact-revision
  snapshot a task graph pro každý řádek fronty. Detail se načítá lazy jen pro
  vybranou položku, cachuje se v session a úvodní obrazovka oznamuje načítání.
  Ad-hoc požadavek 2026-10-29 integruje review do Workspace UI: projekt s řádky
  fronty dostane pod Nástroji samostatnou stránku s tabulkou, lazy detailem,
  filtrem, jednotlivým a potvrzeným hromadným accept/reject. UI používá stejnou
  queue a nevystavuje apply; reader smí číst, rozhodovat smí editor/admin.
  Cílené ověření 2026-10-29: 24/24 testů roadmap refinement/TUI/API/UI prošlo;
  celý `tests.test_desktop`: 52 testů OK, 6 fyzických Qt/WebEngine smoke testů
  přeskočeno podle opt-in podmínky; celý `tests.test_web_server`: 41 testů OK,
  8 opt-in browser smoke testů přeskočeno. Sdílený JavaScript prošel
  `node --check`. Read-only živá projekce skutečné queue projektu načetla 1581
  řádků; žádné rozhodnutí ani projektový zápis při kontrole nevznikly.
  Oprava po fyzickém startu 2026-10-29: původní UI při otevření projektu
  materializovalo všech 1581 řádků (přibližně 8000 DOM buněk) a každý review
  request plánoval nesouvisející backend probe, což mohlo zahltit jedinou
  application lane. Tabulka je nyní stránkovaná po 100, úvodní projekce je
  menší a review requesty backend refresh neplánují. Odpojený WebEngine klient
  při odpovědi nezapisuje BrokenPipe traceback. Transportní sada 13/13 prošla
  mimo sandbox; první sandbox běh byl neplatný kvůli zákazu loopback/Unix socketů.
  Celý desktop modul po opravě: 52 testů OK, 6 opt-in smoke přeskočeno. Pokus o
  real-WebEngine smoke nad skutečným projektem se k UI nedostal: jiný proces
  držel Workspace journal lock (`BlockingIOError`); proces ani zámek nebyly
  násilně ukončeny. GBM hlášení bylo pouze fallback na Vulkan.
  Navazující traceback odhalil chybějící recovery hranici automatického
  federation catalog scheduleru: očekávaná kolize se sdíleným node writer
  lockem ukončila jeho daemon vlákno. Scheduler nyní přechodné selhání zachytí,
  nejvýše pět sekund vyčká a pokus bezpečně opakuje; stav journalu ani zámek
  nemění. Regresní test prvního selhání a následného zotavení prošel spolu
  s kontrolou automatického výběru peerů (2/2).
  Stejná recovery mezera byla nalezena a opravena v project replication
  scheduleru; audit periodických daemon smyček potvrdil, že content sync již
  odpovídající retry hranici měl. Replication worker nyní po node-lock/startup
  kolizi rovněž pokračuje a cílený test zotavení i běžného control-plane toku
  prošel (2/2).
  Následná kontrola prázdného review UI potvrdila 1581 řádků ve skutečné
  node-local queue. Klient však při přechodném selhání úvodního list requestu
  odstranil odkaz na nástroj a chybu ponechal jen ve skrytém panelu. Chybový
  stav je nyní fail-visible v levém panelu, stránka zůstane dostupná a nabízí
  opakování přes „Obnovit seznam“; úspěšné načtení stav chyby odstraní.
  Read-only list/detail byly následně odděleny do vlastní serializované HTTP
  lane, takže startovní backend kontroly v application lane již nevracejí
  `server busy`; rozhodovací zápisy zůstávají v application lane a atomické
  SQLite transakci. Regresní test načetl seznam i při explicitně obsazené hlavní
  lane. Detailní panel navíc resetuje obecné styly levého `<aside>`, využívá celý
  pravý sloupec a při užším viewportu se dále skládá pod tabulku.
  Review tabulka nyní nabízí kombinovatelný checklist všech skutečně nalezených
  stavů s počty a rychlou volbou všech/žádných. Stabilní řazení podporuje původní
  pořadí, stav, návrh, zdroj, cíl a jistotu vzestupně i sestupně; změna ovládání
  vrací stránkování na začátek a filtry se při obnovení fronty zachovají.
  Stejný kombinovatelný checklist s počty a volbou všech/žádných byl doplněn
  také pro hodnotu návrhu (`attach`, `keep-detached`, deep-check outcomes aj.).
  Globální „Provést schválené“ nyní po potvrzení používá existující exact-HEAD
  `Workspace.transact` apply a při nejasném timeoutu zachová operation ID pro
  idempotentní opakování. Deep-check nyní nejprve skládá exact diff: evidenční
  výsledky nemění Git, create/update/dependency změny se aplikují po jedné a po
  každé se validuje celý task graph; preview SHA stale-protectuje potvrzení.
  Scan nově odmítá neplatný typ rodiče, změnu typu/rodiče existujícího uzlu a
  dependency bez existujícího cíle už před lidským review.
  Review UI umí vrátit jednotlivé i všechny accepted návrhy zpět do pending,
  označuje evidence/mutation a orientační riziko a dovoluje preview a provedení
  pouze vybraného accepted záznamu bez ovlivnění ostatních rozhodnutí.
  Živá kontrola 2026-10-29 našla 87 accepted deep-check, 0 accepted detached a
  1271 pending položek. Nejméně jeden přijatý create-node návrh navíc navrhuje
  task přímo pod milestone. Read-only preview nad živou queue jej zachytil bez
  zápisu: 87 proposals, 50 evidenčních výsledků, 25 strukturovaných změn a 16
  blokátorů (14 chybných typů rodiče, 2 neplatné kořenové tasky). Opakovaný scan
  s `--forget-previous` tyto staré odpovědi nahradí návrhy podle přísnějšího
  kontraktu; samotné UI apply DEV-01 neuzavírá.
  Migrační použití tohoto scanu je po fyzickém vyhodnocení odmítnuté:
  lokální cluster proti chybnému cíli nezachoval sekvenční kontext. Queue se
  neaplikuje. Implementace zůstává podkladem pro pozdější omezení na audit
  kanonické task roadmapy bez původních dat a obecných artefaktů.
- [x] [completed] **DEV-01-E-REPLAN-01 — opravený source-first návrh migrace
  (designed).** Zdokumentováno úplné odmítnutí prvního importu, oddělení
  migration/refinement/document-to-plan workflow a nový tok: deterministický
  source catalog se sekvenčním kontextem → LLM extraction bez cíle → globální
  mezimodel → nezávislý source-vs-candidate audit → metriky věrnosti → review
  po logických celcích → jediná úplná náhrada. Návrh je v
  `docs/roadmap-migration.md`; v tomto kroku se data ani queue nemažou.
- [ ] [in progress] **DEV-01-E-REBUILD-01 — lokální LLM source-first migrační
  utility (cílová úroveň: implemented).** Implementovat resumovatelný katalog,
  provider-neutral extraction a audit run manifest, validovaný mezimodel,
  deterministický kandidát a coverage/fidelity report. První krok nesmí měnit
  Workspace projekt; apply úplné náhrady zůstává odděleným potvrzeným krokem.
  Implementovány CLI `prepare/run/status`, commit-pinned sekvenční bloky s
  okolím, striktní extraction/audit schémata, stabilní Ollama run IDs,
  atomické resumovatelné výsledky, bounded oprava a terminální evidence vadné odpovědi,
  deterministické sloučení kompatibilních ID, validace hierarchie/dependency a
  JSON/Markdown candidate i fidelity report. Utility nečte existující cílový
  projekt a nemá writer. Zbývá fyzický běh nad připnutými reálnými zdroji,
  vyhodnocení schopnosti zvoleného modelu a review výsledného kandidáta.
  Read-only fyzické `prepare` nad host HEAD `692e47a` a modulem
  `cz.proofofidea.publication-experiment-registry` `446d980` vytvořilo v
  `/tmp/dev-01-source-rebuild-20261029-v5-final` katalog 6 souborů / 607109 bajtů /
  185 logických bloků; největší blok má 24477 bajtů. První smoke dispatch
  odhalil nedostupný Ollama endpoint ještě před modelovou odpovědí; utility
  proto nyní před prvním blokem ověří endpoint i připnutý model a
  nedostupnost už nekonzumuje blokový run. Fyzický v4 extraction dokončil
  140/185 bloků; 23 rodičů odhalilo chybějící lokální reference ve schema v1,
  16 entit míchalo ID/maturity a 6 citovalo řádky mimo blok. Schema v2 proto
  zavádí `entity_key`, lokální/source refs, deterministický ID allowlist,
  oddělenou maturity a nejvýše dva correction průchody. První fyzický blok
  čistého v5 prošel bez opravy a správně zachoval licenční preambuli jako
  description bez falešného ID.
  CLI nyní při každém volání zobrazuje fázi, blok, pokus, logický postup,
  procenta, elapsed a průběžnou ETA. Fyzický druhý blok ověřil 2/370 (0,5 %)
  bez opravy; trval přibližně 70 sekund a první hrubý odhad celého zbytku
  byl 7 h 10 min, při dalších blocích se bude zpřesňovat.
  Celý v5 extraction skončil 94/185 validními bloky a 91 terminálními chybami;
  audit se správně nespustil bez úplného kandidáta. Diagnostika 241 opravných
  volání odhalila tři chyby kontraktu utility: 55 obsahově správných
  neexekučních záznamů odmítla kvůli rodiči, 7 explicitních skupin více ID
  odmítla místo předání k review a všech 16 odpovědí s odlišnými poli pouze
  zopakovalo pomocné `validation_error`, protože opravný prompt neopakoval
  cílové schéma. Opravený kontrakt dovoluje kontextový `parent_ref`, skupině
  source ID přidělí `MIG-*` a blokátor `combined-source-ids`, používá samostatný
  úplný repair prompt pro extraction/audit a vrací podrobnější validační chyby.
  Zbývající skutečné odchylky (zejména citace řádků mimo blok a neplatné refs)
  zůstávají fail-closed. Cílená migrační sada (`roadmap_rebuild`,
  `roadmap_migration`, `roadmap_mapping`, `roadmap_importer`): 37/37 prošlo.
  Čistý v6 nad stejnými připnutými revizemi je připraven v
  `/tmp/dev-01-source-rebuild-20261030-v6`: extraction zlepšila výsledek na
  155/185 validních bloků a 30 terminálních chyb po 99 opravných voláních.
  Z nich bylo 21 mechanických parent refs (`"null"` nebo UUID obálky), 8
  nepřesných rozsahů řádků, 6 source ID mimo allowlist, 3 bezpečně neurčité
  transporty a 1 neformální maturity; některé bloky měly více vad. V7 proto
  předává očíslovaný zdroj, normalizuje pouze dvě jednoznačné transportní
  reprezentace rodiče, rozpozná historické shorthand ID z deklarovaných názvů,
  odděluje zmíněná ID použitelná jen jako reference a zachovává každou
  ambiguity jako blokátor kandidáta. Vymyšlené ID a obsah mimo blok zůstávají
  fail-closed. Cílená migrační sada: 40/40 prošlo. Zbývá čistý fyzický v7 běh.
  V7 dokončila extraction se 178/185 validními bloky, 15 opravnými voláními a
  7 terminálními chybami: šestkrát source ID mimo allowlist a jednou neurčitý
  transport. ID mimo allowlist se nyní odstraní se zachováním obsahu a
  povinným `source-ambiguity` blokátorem. Nový `derive --from-run` přebírá jen
  znovu validované extraction výsledky, eviduje jejich hashe a lineage a
  nechává znovu zpracovat pouze chybějící bloky; candidate a audity vzniknou
  vždy znovu. Cílená migrační sada po změně: 42/42 prošlo.
  První selektivní run převzal 178 bloků, šest opravil bez correction volání a
  jediný 23 080B blok `WORK_LOG.md:4153-4265` podruhé skončil jako durable
  `unknown` na obecném 180s response timeoutu; nevznikla raw odpověď, nejde
  tedy o doloženou obsahovou chybu. Rebuild má nyní vlastní manifestem
  připnutý limit 600 sekund bez změny globálního Ollama adapteru. Druhý
  selektivní run `/tmp/dev-01-source-rebuild-20261030-v7-retry-2` převzal 184
  validních extrakcí. Poslední blok uspěl za přibližně 3 min 29 s, takže
  extraction je úplná 185/185. První sestavení kandidáta odhalilo čistě
  prezentační chybu: dva vědomě nerozřešené dependency blokátory byly v JSON
  `null`, ale Markdown renderer je před auditem zkoušel přímo spojit jako
  řetězce. Renderer nyní zobrazuje `<unresolved>` a bezpečně označí případný
  cyklus; autoritativní candidate JSON ani modelové výsledky se nemění.
  Audit dokončil 182/185 validních bloků; tři terminální chyby byly pouze
  redundantní pozitivní findings druhu `correct` při celkovém verdictu
  `correct` a skóre 100. Z validních auditů bylo 170 `correct`, 8 `equivalent`,
  3 `distorted` a 1 `missing`; skutečné výhrady se soustředily do čtyř bloků.
  Původní globální sloučení mělo 793 blokátorů, protože každý odlišný
  sekvenční výskyt stejného ID považovalo za konflikt. Autoritativní
  reconciliation nyní zachovává 261 variant u 90 uzlů, preferuje dokončenou
  historickou evidenci a vytváří jen jedinou skutečnou stejně autoritativní
  `reconciliation-ambiguity` (`M0-06`). Deterministický náhled nad stejnými 185
  extrakcemi klesl na 296 blokátorů: 205 neplatných/neurčených rodičů, 42
  kombinovaných ID, 42 zdrojových nejasností, 6 dependency a 1 reconciliation
  konflikt. Nový audit uvidí i varianty přes `provenance_all`. Odvozený run
  `/tmp/dev-01-source-rebuild-20261030-v7-reconciled` převzal všech 185
  extrakcí a čeká pouze na nové audity; cílená migrační sada: 46/46 prošlo.
  Reconciled audit dokončil všech 185 bloků s fidelity 97,87: 164 `correct`,
  14 `equivalent`, 6 `misplaced` a 1 `distorted`. Šest ze sedmi výhrad
  pocházelo z vloženého modulu, jehož lokální M0–M6 byly chybně sloučeny s
  hostitelskými milníky. Reconciliation nyní klíčuje identitu dvojicí
  repository/ID, parent i dependency řeší pouze uvnitř stejného projektu a
  candidate nese explicitní `repository_id`. Deterministický náhled má 697
  hostitelských a 18 modulových uzlů; odhaluje tři skutečné lokální
  reconciliation ambiguity místo cross-project kolizí. Odvozený run
  `/tmp/dev-01-source-rebuild-20261030-v7-scoped` převzal 185 extrakcí a 166
  auditů s kanonicky shodným vstupem; zbývá jen 19 auditů dotčených novým
  scoped kandidátem. Cílená migrační sada: 48/48 prošlo.
  Scoped audit je úplný: fidelity 99,57, coverage 99,84, hierarchy 99,59,
  status 99,14, provenance 99,84 a dependencies 99,46; verdicts 172 `correct`,
  11 `equivalent`, 1 `misplaced` a 1 `distorted`. Jediné `misplaced` XREF-01
  odporuje přímo zdrojové formulaci, podle níž master roadmap drží strategický
  požadavek a konkrétní budoucí dávku BACKLOG; jde proto o auditní návrh k
  odmítnutí, nikoli automatickou změnu. `distorted` blok M5 je věcný: chybí
  několik plánovaných trust/chat/backend/conflict požadavků a vyžaduje cílené
  doplnění ze zdrojových řádků 1460–1501. Candidate zůstává `import_ready=false`
  také kvůli 304 strukturálním blokátorům: 211 parent, 42 combined-source-ids,
  42 source-ambiguity, 6 dependency a 3 reconciliation ambiguity. Žádný apply
  před jejich cíleným reconciliation/review neproběhne.
- [ ] [planned] **DEV-01-F — fyzická migrace a předání autority (PoC validated).**
  Potvrzený konkrétní náhled → existující Workspace projekt, ověření obsahu
  v aplikaci i IDE. Samostatně akceptovat úplnost modulů a úpravu workflow
  zdrojového repozitáře; žádné předčasné odstranění původní evidence.
- [ ] [planned] **DEV-01-G — závěrečná akceptace a předání dávky (PoC validated).**
  Konsolidovat důkazy, archivovat dávku a odklady, vyčistit TODO a připravit
  jeden PR do develop; spuštění další feature není součástí této dávky.

## K předání do backlogu

- [ ] [planned] **PLAN-SEMANTIC-AUDIT-01 — obecný sémantický audit a proposal
  engine roadmapy (cílová úroveň: implemented).** Uživatelský požadavek
  2026-10-28 navazuje na fyzické dotřídění importu: integrovat do Workspace
  opakovatelný scan hlubší logické a sémantické správnosti roadmapy a změněných
  podkladů. Samostatné striktně validované typy návrhů mají nejprve pokrýt
  `add/remove-dependency`, `create-task`, `update-description`,
  `flag-contradiction` a `flag-duplicate/orphan`; `split/merge` zůstane
  navazující rozšíření podle reálných nálezů. Speciální varianta
  `derive/update-subplan` zpracuje nový nebo změněný podklad do návrhu dílčího
  plánu a `integrate-subplan` navrhne jeho začlenění do kanonické roadmapy:
  mapování na existující milestone/batch/task, nové uzly, dependency hrany,
  rozpory a body, které mají zůstat pouze volným popisem. Dílčí plán je
  verzovaný projektový artefakt s vlastní stabilní identitou, ale nikoli druhá
  autorita stavu; jeho uzly nesmějí být současně vydávány za samostatný aktuální
  plán a za integrované kanonické uzly. Vazba source artifact ID + source digest
  + analyzer revision + subplan ID umožní opakovaný běh bez duplikace. Změna
  zdroje se porovnává s předchozí zdrojovou revizí i posledním odvozeným plánem;
  ruční úpravy dílčího či hlavního plánu se nesmějí tiše přepsat a odstraněný
  požadavek vznikne jako explicitní removal/deprecation proposal, nikoli jako
  automatické smazání. Review nejprve potvrdí obsah dílčího plánu a samostatně
  jeho integrační diff; podle rozsahu lze obě potvrzené části zapsat jednou
  Workspace transakcí proti témuž expected HEAD. Každý proposal zachová exact
  HEAD, analyzer revision, zdrojové artefakty/revize a citované úseky, dotčená
  stabilní ID, strukturovaný before/after náhled, důvod, confidence, rizika a
  validační dopad. Nový úkol vyžaduje validovaný typ, rodiče, rozsah, akceptaci,
  provenance
  a kolizně bezpečné provisional ID; LLM nesmí samo měnit stav dokončení ani
  obejít katalog/ID validaci. Statické kontroly musí předcházet LLM návrhům:
  neznámé cíle, cykly, orphan uzly, duplicity ID, neplatná hierarchie a chybějící
  povinná pole se nemají řešit volným textem modelu. Scan pouze plní projektově
  izolovanou node-local proposal queue; `unknown` se tiše neopakuje. Human review
  podporuje jednotlivé i dávkové accept/reject a jasný source → change → target
  diff. Accepted návrhy se proti nezměněnému expected HEAD aplikují jednou
  autorizovanou `Workspace.transact` operací, celý kandidát znovu prochází
  schématem a task-graph validací; stale návrh se neaplikuje a musí být znovu
  vyhodnocen. Pád před commitem obnovuje Workspace journal, po commitu receipt a
  projekce z HEAD; proposal queue není druhá autorita roadmapy. Integrace patří
  do sdíleného Workspace UI a později může být zpřístupněna IDE bridge, nikoli
  ponechána jako trvalý migrační TUI skript. Jde o samostatnou feature dávku,
  větev a PR po uzavření `DEV-01`; není součástí akceptace aktuální migrace.

## Ověření aktuálního kroku

`python3 -m unittest tests.test_roadmap_refinement tests.test_roadmap_importer
tests.test_roadmap_validation tests.test_roadmap_bundle tests.test_roadmap_mapping
tests.test_roadmap_migration tests.test_task_graph tests.test_roadmap_graph
tests.test_spdx -v`: po doplnění projektového selektoru 72 testů OK.
Původní 4 refinement testy
ověřují proposal-only scan a deduplikaci, terminální reject, odmítnutí
vymyšleného cíle a jedinou autorizovanou Workspace transakci po akceptaci.
Následný cílený běh `python3 -m unittest tests.test_roadmap_refinement -v`:
5 testů OK; pátý test kryje izolaci jedné lokální queue mezi dvěma projekty.
`python3 -m unittest tests.test_roadmap_refinement_tui -v`: 10 testů OK;
ověřeno explicitní spuštění scanu, review přes existující service, zákaz apply
bez druhého potvrzení, bezpečný quit, terminál bez podpory skrytí kurzoru,
samostatné stránkování tabulky/detailu, filtr rozhodnutých stavů a živé UI
po dobu blokovaného background scanu se zákazem předčasného ukončení. Devátý
test vkládá newline, tab a CR do všech víceřádkových polí a ověřuje, že curses
nedostane žádný řídicí znak. Desátý ověřuje výběr dostupného projektu podle
názvu/UUID a odmítnutí nedostupného projektu.
Skutečný PTY smoke otevřel TUI nad hostitelským projektem a ukončil jej přes
`q` s exit 0; scan, rozhodnutí ani apply při smoke spuštěny nebyly.
`python3 -m py_compile spikes/roadmap_refinement.py
scripts/roadmap_refinement.py`: OK. Celá finální unittest brána zůstává pro
uzavření dávky.

`python3 -m unittest tests.test_roadmap_validation -v`: 3 nové validační
testy OK. Pokrývají úspěšné sloučení celého živého snapshotu bez zápisu,
ponechání chybějící cesty/privacy jako otevřených stavů a rozlišení
relativního a neexistujícího artifact odkazu. Skutečný report nad aktuálním
balíkem potvrdil nezměněný živý HEAD a nulový rozpracovaný journal.
Společný cílený běh validačních, bundle, mapping, inventory, task-graph,
roadmap-graph a SPDX testů po poslední změně: 57 testů OK. Log:
`/tmp/dev-01-writer-tests.log`. Celá finální unittest brána zůstává pro
uzavření dávky.

`python3 -m unittest tests.test_roadmap_bundle tests.test_roadmap_mapping tests.test_roadmap_migration tests.test_task_graph tests.test_roadmap_graph tests.test_spdx -v`:
47 testů OK, z toho 6 balíkových testů. Pokryto je sestavení celých metadat,
shoda plánu, zachování přesných source bajtů a původní identity rootu,
nepoužití testovacích dat, izolace modulového obsahu, navržený seed root,
deterministický rebuild, ochrana proti relaxaci privacy a odmítnutí chybějících,
změněných či nadbytečných blobů i přepsání existujícího balíku. Dřívější
historické/grafové testy zůstávají. Skutečný běh vytvořil 213 artefaktů /
426 souborů (3 589 550 bajtů logických payloadů); z disku byly zpětně
porovnány přesné bajty všech souborů. Živý projekt se nezměnil.
Celá finální runtime brána zbývá před dokončením dávky; bod 2 a zápis/recovery
nejsou těmito shape testy označené za dokončené.
