<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Audit souběhu, čtení a kapacit — 11. 11. 2026

Historický nález nad výchozím zdrojem. Následné změny A01–A06 a jejich
omezení eviduje [náprava P1](concurrency-p1-remediation.md).

## Výsledek a rozsah

**Dosavadní úpravy neodstranily systémový problém dostupnosti.** Výhradní HTTP
vlastnictví stále často pokrývá celé dlouhé operace, včetně čtení, vzdáleného I/O
a odeslání odpovědi. Na několika místech blokuje i stav a rušení téže práce.
Jinde je problém opačný: asynchronní spuštění uniká limitu HTTP workerů, aniž
by dostalo vlastní společný kapacitní limit.

Audit je podklad k review, nikoli změna autoritativního plánu, akceptace nebo
oprávnění k hromadnému odstranění zámků. Identifikátory A01–A11 označují nálezy
tohoto dokumentu, nikoli nově založené úkoly Workspace. Implementace se během
auditu neměnila.

Auditovaný zdroj: `feature/rss-direct-pilot`, finálně commit
`8ec83f5605f9473425811512530e3ce5d7ba2ead`. Na začátku byly nad `1c63d05`
rozpracované čtyři soubory předchozí opravy reader budgetu; během auditu byly
začleněny do `8ec83f5`. Audit je už četl v této výsledné podobě.
Uložené propojení odpovídá projektu `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
tomuto repozitáři a exportní revizi
`5e9de351ac5e6ec033066a10eba2309fbbaf57cc1a3f9799478c172cd6025a39`;
status je stale/waiting-review. Audit neaktivuje archivované feature.

Inventura zahrnuje:

- 269 přesných rout v `http_admission_policy`, 262 deklarací desktop handleru
  a 264 web handleru; žádná jejich routa nechybí v klasifikaci;
- 27 pevných názvů HTTP domén a dynamické vlastnictví podle project ID;
- browser FIFO/Web Locks, transport rozšíření, HTTP admission a časové rozpočty;
- 102 řádků s primitivy/využitím zámků v Python runtime; nejde o 102 různých zámků;
- inventuru 176 SQLite/transaction výskytů ve 47 modulech, včetně rozdílu mezi
  společným `sqlite_connection` a přímým `sqlite3.connect`;
- native journal/index, node registry, queue/bridge/review, monitoring/RSS,
  Julia, federaci, import, publikaci, telemetrii a background lifecycle.

Jde o statický audit vlastnictví doplněný izolovanými reprodukcemi. Detailní
závěry mají níže konkrétní zdroje a typ důkazu. Inventura všech SQLite výskytů
není důkaz správnosti každé SQL transakce. Nebyl proveden formální důkaz absence
deadlocků, úplný load test, fyzická routerová akceptace ani audit cizích pluginů.

## Prioritizované nálezy

### A01 — P1: provider vlastnictví blokuje čtení i část rušicích cest

`provider_lane` sdílí **136 rout**, včetně streamů, konfigurace, stavů, importů
a `/v1/tasks/cancel`. `_in_request_lane` drží vlastníka přes celý callback
a odpověď. `task_stream.serve`, chat i external stream provádějí dlouhou práci
uvnitř tohoto callbacku. Navíc běžné provider routy získávají vlastníka ještě
před `_do_POST`, tedy před úplným přečtením těla. Platně autentizovaný požadavek
s neúplným JSON tělem tak blokuje provider doménu, přestože dispatch ještě neběžel.

**Důkaz:** při pozastaveném provider callbacku vrací chat status, tasks cancel
i konfigurace 503; nezávislé run-control a diagnostika 200. Samostatná sonda
s neúplným tělem vrací pro další status 503 a pro diagnostiku 200. Jde o test
middleware s řízeným callbackem, nikoli o živé LLM volání. Dlouhá produkční
cesta je doložena v handleru a `task_stream.serve`.

**Požadavek na nápravu:** admission až po validaci requestu; rozdělit skutečné
vlastnictví konfigurace, čtecích snapshotů a konkrétního běhu. Rušení musí mít
samostatně dosažitelnou control cestu. `/tasks/run-control` už ji má; nelze
proto tvrdit, že nefunguje žádné rušení. Samotné přidání workerů nebo retry
neodstraní tuto kolizi.

Zdroje: [klasifikace](../spikes/http_admission_policy.py),
[admission](../spikes/local_api.py), [stream](../spikes/task_stream.py),
[produkční dispatch](../spikes/desktop_ui.py).

### A02 — P1: monitoring run blokuje vlastní stav a cancel

Všech 40 monitoring rout sdílí jednu doménu napříč projekty. Handler volá
`run_now`, synthesis/workflow a processing inline; `Monitoring.execute` může
volat model a zapisovat výsledek. Stav a `/monitoring/cancel` čekají na tutéž
HTTP doménu. Background tick navíc není účastníkem HTTP mutexu: ten tedy sám
ani nepokrývá všechny zapisovatele.

**Důkaz:** při drženém run callbacku vrací view i cancel 503, diagnostika 200.
Je to reprodukce admission, podložená přímou produkční call cestou; nebyl
spouštěn skutečný model. **Náprava:** oddělit control/read od execution a
dlouhou práci omezit mimo handler přes původní run journal/claim mechanismus.
Nativní leases, receipt a explicitní unknown outcome musí zůstat autoritou.

Zdroje: [handler](../spikes/desktop_ui.py),
[monitoring](../spikes/monitoring.py), [scheduler](../spikes/reporting_scheduler.py).

### A03 — P1: projektová čtení stále drží výhradní vlastnictví přes těžkou práci

`Workspace.read_project` drží `journal.lock()` přes Git snapshot, validaci,
kontrolu projekce a stavbu task grafu. `_read_locked` může obnovit index, což
je skutečný zápis; to ale nedokládá nutnost držet EX i přes veškerou práci
v případě již aktuálního indexu. Nad tím HTTP `ProjectLanes` serializuje také
čtení a zápisy stejného projektu a po 100 ms další požadavek odmítá.

**Důkaz:** při pozastaveném `Git.snapshot` skutečného project-open s aktuálním
indexem selže paralelní čistý `snapshot_checkpoint` na `project-journal`.
`Index.rebuild` byl během sondy zakázán; nebyla tedy potřebná obnova indexu.
Čtení jiného projektu dokončí 200. Oddělení katalogu toto jiné projektové
čtení automaticky neopravilo.

**Náprava:** rozdělit čistý snapshot read a případnou opravu projekce.
Při nutném přechodu na writera znovu ověřit pending, HEAD i stav indexu;
neprovádět implicitní rebuild pod SH. Těžké výpočty nad neměnnými bajty
nedržet pod writerem. Zápis/index publication nadále potřebuje EX a původní CAS.

Zdroje: [Workspace](../spikes/workspace.py), [Index](../spikes/storage.py),
[projektová admission](../spikes/request_ownership.py).

### A04 — P1: diagnostický worker není rezervovaný před čtením hlaviček

Celkový pool se přijímá ještě před parsováním požadavku. `post_slots` odliší
diagnostiku až v `do_POST`. Všech pět přijatých spojení tedy může čekat na
hlavičky a žádný worker už endpoint diagnostiky nerozpozná.

**Důkaz:** pět loopback spojení s nedokončenými hlavičkami obsadilo všech
5 workerů; správně adresovaný diagnostický POST dostal 503. Nejde o důkaz
nefunkčnosti diagnostiky při každé dlouhé operaci: předchozí sondy ji naopak
úspěšně přečetly. Jde o konkrétní mezeru před klasifikací requestu.

**Náprava:** oddělit a omezit příjem/parsing spojení od kapacity aplikačního
dispatch, případně diagnostiku skutečně izolovat. Zachovat absolutní read
deadline a omezený počet socketů; nedělat neomezený pool čekajících parserů.

Web má navíc synchronní TLS handshake přímo v `WebServer.get_request`, s
timeoutem 2 s ještě před worker admission. Pomalý handshake tedy dočasně
blokuje i příjem dalších spojení v accept threadu. Toto rozšíření nálezu je
statické; TLS handshake storm se dynamicky netestoval.

Zdroje: [process_request/do_POST](../spikes/local_api.py),
[read budget](../spikes/http_request_budget.py), [TLS accept](../spikes/web_server.py).

### A05 — P1: Julia background execution nemá společný aplikační limit

`JuliaWorkspace.execute` omezuje duplicitní worker pro stejný key, ale pro
každé jiné operation ID vytvoří nový thread. `JuliaExecutor.execute` z něj
může spustit další proces. HTTP worker se rychle uvolní, takže velikost HTTP
poolu neomezuje celkový počet výpočtů. Per-run limity nejsou limitem jejich součtu.

**Důkaz je statický:** kontrola dispatch mapy, thread start a executor Popen.
Nebyl proveden zátěžový test ani spuštěno mnoho Julia procesů. Audit netvrdí,
že nasazený host nemůže mít dodatečný vnější OS limit.

**Náprava:** bounded node execution admission/queue před dispatch, zachovat
prepared intent a stejné operation ID, nezaměňovat plnou kapacitu s unknown
výsledkem již spuštěného procesu. Status/cancel nesmí čekat za výpočtem.

Zdroje: [workers](../spikes/julia_workspace.py),
[execution](../spikes/julia_computation.py).

### A06 — P1: čtecí SQLite API získávají writer reservation

`ReportingScheduler.get` používá `db()`, které i nad inicializovaným schématem
provádí `BEGIN IMMEDIATE` a drží transakci přes getter. `JuliaRunStore.get`
používá `connect()`, které před SELECT znovu získá writer reservation kvůli
schema bootstrapu a pak ji commitne. Tedy i čtecí requesty vyžadují vstup
do writer části, byť u Julie jen při inicializační části spojení.

**Důkaz:** při drženém `BEGIN IMMEDIATE` nad dočasným reporting journalem
obyčejné souběžné `SELECT COUNT(*)` úspěšně přečetlo jeden run, ale
`scheduler.get` nad týmž existujícím runem v HTTP kontextu skončil typed
SQLite busy. Po rollbacku getter opět fungoval. Getteru tedy nebránila
nedostupnost dat, ale jeho požadavek na writer reservation.

**Náprava:** oddělit bootstrap/migrace od read-only transakcí a getterů.
Reuse již existujícího vzoru `MessagePools.read_db`; nepředstírat čtecí
transakci tam, kde se opravdu připravuje claim, intent nebo migrace.

Zdroje: [reporting DB/get](../spikes/reporting_scheduler.py),
[Julia journal](../spikes/julia_computation.py),
[read-only vzor](../spikes/message_pools.py).

### A07 — P2: RSS HTTP zámek blokuje cache, kterou native reader umí přečíst

`RSSSources.refresh` při fetchi drží `refresh_lock`, ale krátký cache mutex
uvolní. Native `view` proto může ukázat `loading`. Vnější `rss_sources_lane`
však zablokuje samotný HTTP view po celou dobu fetch/parse.

**Důkaz:** nad skutečným RSSSources s pozastaveným lokálním fake fetcherem
vrátil přímý `view` stav `loading`, zatímco HTTP `/rss-sources/view` vrátil 503.
Žádný vzdálený feed nebyl kontaktován.

**Náprava:** rozdělit kapacitu fetchů a čtení cache; kopírovat snapshot pod
krátkým mutexem a normalizaci/sort dělat mimo něj. Revision-bound save stále
musí koordinovat subscription změnu s refresh.

Zdroj: [RSSSources](../spikes/rss_sources.py).

### A08 — P2: další serializaci přidávají klienti i nad bezpečnými čteními

Browser drží pro každý lane key jeden request do EOF, včetně Web Lock napříč
okny stejného originu. Backendový catalog reader budget se zde nevyužije.
Rozšíření má zase jeden FIFO pro celé connection ID, tedy pro všechny jeho
projekty, sidebar, sync a updater, přestože backend už některé domény oddělil.

**Důkaz:** statická FIFO pumpa a transportní key; stávající browser testy
záměrně ověřují EOF serializaci. Není tím doloženo, že lze bezpečně paralelně
odeslat libovolné dvě mutace nebo přeskočit pořadí zpráv.

**Náprava:** po oddělení backendových ownerů sdílet s klientem i informaci
o reader/control kapacitě, nikoli jen název domény. Zachovat FIFO účinků
a rozlišení timeout-before-send versus unknown-after-send. Žádný nový retry.

Zdroje: [browser](../spikes/http_ui_admission.py),
[IDE transport](../extensions/workspace-bridge/bridge.js).

### A09 — P2: bounded HTTP politika neplatí pro všechny native DB a síťové části

`sqlite_connection` při HTTP přepne SQLite čekání na nulu a překládá BUSY/LOCKED.
Řada dosažitelných store ale používá přímo `sqlite3.connect(timeout=30)`;
například CMS/Cloudflare, provider run stores a metric cache. Drive používá
timeout 2 s. Samotný ContextVar tak jejich čekání neomezuje. Drive token
exchange a Cloudflare deployment navíc probíhají pod dlouhým native EX ownerem.

**Důkaz je statický:** konkrétní connect/with/transport cesty. Audit nezměřil
30sekundový zásek v běžném profilu ani netvrdí, že každý direct connect vždy čeká.
CMS `status` navíc opravdu spouští recovery; jeho EX nelze jednoduše změnit na SH.

**Náprava:** oddělit initialized readers, řízené migrace a claim/publication.
Transportní čekání nenést pod globálním konfiguračním ownerem, pokud lze
stav předem připnout a před publikací ověřit revizi. Zachovat prepared/dispatching/
unknown a původní operation ID. Zmapovat všechny direct connect před plošnou změnou.

Zdroje: [SQLite helper](../spikes/sqlite_ownership.py),
[Drive](../spikes/google_drive_import.py), [CMS](../spikes/publication_cms.py),
[deployment](../spikes/publication_cloudflare.py), [runs](../spikes/ollama_backend.py).

### A10 — P2: shutdown scheduleru může ztratit referenci na živý thread

Catalog a replication scheduler po `join(timeout=20/35)` nastaví thread na None,
aniž by ověřily `is_alive`. Obdobně content scheduler používá bounded join.
`Monitoring.close` naopak skutečnou nedokončenost vrací. Reference None tedy
není spolehlivý důkaz ukončení všech background ownerů.

**Důkaz je statický:** stop implementace a volání ve web main. Nebyl
simulován reálný pomalý peer při shutdownu; není doložen výskyt poškození dat.

**Náprava:** deadline-aware drain s konkrétním clean/unclean výsledkem a
zachováním reference na živý worker. Bezpečné opuštění musí respektovat
journal/replay, nikoli bezpodmínečně ukončit proces v neznámé fázi.

Zdroje: [catalog stop](../spikes/federation_catalog.py),
[replication stop](../spikes/replication_control.py),
[content stop](../spikes/federation_sync.py), [monitoring close](../spikes/monitoring.py).

### A11 — P2: zbylé hrubé reader domény a dlouhé kritické sekce

Stejný 100ms HTTP admission limit platí pro mnoho rozdílných domén. Například
čistě odlišné roadmap graph a document-pattern požadavky sdílejí reference
mutex; Julia publish blokuje status/cancel; task-queue status je stále jeden
globální reader owner napříč projekty. Telemetrie drží interní mutex i během
`nvidia-smi` s timeoutem 2 s, přestože stateful jsou zejména delty CPU/sítě.

**Důkaz:** reference a Julia admission reprodukovaly 503 pro souběžné čtení
nebo control. Těžká Julia computation ale běží mimo HTTP — nález neříká, že
každý výpočet drží Julia HTTP mutex. Telemetrie a cross-project queue reader
jsou doloženy staticky, bez fyzického měření GPU nebo uživatelského multi-project toku.

**Náprava:** úzké owner scope a reader snapshots po doménách; oddělené control
cesty. Rozpočet má vyjadřovat zdroj a omezenou frontu, nikoli univerzální
100ms předpoklad, že každá operace bude rychlá.

## Matice všech HTTP vlastnictví

Počty jsou výchozí routy, nikoli další součet action overrides. `project`
je dynamický owner; ostatní řádky zahrnují všechny pevné lane názvy.

| Doména | Routy / override | Skutečná hranice a závěr |
|---|---:|---|
| application | fallback | Konzervativní neznámá cesta; nezaměňovat s oprávněním routy. |
| availability | 2 | Krátké probe/control; oddělení od dlouhé práce zachovat. |
| catalog | 1 | Committed labels/privacy, request-local Git; globální EX není datový invariant. |
| catalog_transfer | 1 | Node sync journal/registry; dlouhé I/O, nutný audit scope před paralelizací. |
| content_sync | 1 | Příjem/replay/publication, také native receive owner; zachovat recovery. |
| diagnostics | 1 | Krátké procesní snapshoty; samotná rezervace neřeší A04. |
| enrollment | 1 | Identity/credentials/registry; skutečné mutace musí zůstat koordinované. |
| federation_control | 5 | Bounded manual queue/settings; správně odděleno od transferu. |
| ide_queue | 12 | Smíšené mapping/mailbox/review/publication; native transakce jsou autorita, ne HTTP mutex. |
| ide_status | action | N−1 reader slots; resource policy, SH snapshot checkpoint. |
| ide_update | action | Manifest/package, request-local práce; kapacitní omezení není writer invariant. |
| julia | 12 | HTTP předání a sdílené worker mapy; malé mapové mutexy nestačí pro globální kapacitu A05. |
| monitoring | 40 | Lifecycle/sidecar + inline execution; A02/A06. |
| node_preferences | 6 | Sdílené application-access/process fields; mutace koordinovat, initialized reader oddělovat. |
| node_status | action | Initialized administration list má native SH; HTTP EX je konzervativní policy. |
| peer_catalog | 1 | Podpisy/nonces/catalog state; není automaticky bezstavový reader. |
| peer_probe | 1 | Peer ověření a discovery; omezená kapacita dává smysl, není důvod pro nekonečnou frontu. |
| peer_replication | 1 | Persistentní replication store; přímé SQLite cesty zahrnout do A09. |
| peer_state | 1 | Signed committed manifest/read-only projekce; auth a freshness zachovat. |
| presentation | 4 | Sdílený selected deck/public state/session; odůvodněný procesní owner. |
| project | 29 | Per-project HTTP owner + native journal; čtení příliš hrubé A03. |
| provider | 136 | Příliš široká směs, A01. |
| reference | 2 | Nesouvisející výpočty; reprodukovaná zbytečná vzájemná blokace A11. |
| replication_transfer | 1 | Native replication-control flock přes transfer; scope/resource policy k dalšímu zúžení. |
| review | 6 | Proposal store včetně bootstrap/migrací; read názvy nejsou důkaz čistoty. |
| rss_sources | 4 | Cache view/save/fetch; oddělit A07. |
| task_queue_status | action | Čtecí projection, ale globální EX admission a implicitní native index read; A03/A11. |
| telemetry | 1 | Stateful delty + stateless I/O pod jedním mutexem; A11. |

## Native ownery: co chrání a co zachovat

| Skupina | Chráněný stav / posouzení |
|---|---|
| Journal / Workspace writer | Filesystem → journal → Git CAS → index → receipt. EX přes skutečnou mutaci/recovery je potřebný. |
| Snapshot checkpoint | Initialized owner/pending/HEAD; SH před/po immutable validaci je odůvodněný, bez rebuild pod SH. |
| Index SQLite | Atomická projekce s commit ID; BEGIN IMMEDIATE pro přepsání tabulek, BEGIN pro read. Nejde o autoritu pending operace. |
| Administration | EX pro bootstrap/migraci/registry Git, SH pro initialized read; neměnit credential/revocation guards. |
| Project creation/deletion/relocation | Node registry a filesystem/journal intent; native flock a recovery nutné. Preview může vytvářet intent. |
| Project diagnostics/repair | EX nonblocking zkouška dostupnosti writera je validní; není to běžný dlouhý reader owner. |
| TaskQueue | Per-project/owner file flock a atomic fsync/rename. Řádky odpovědi už jsou mimo zámek; status/bootstrap lze dále rozdělit. |
| IDE bridge / prepared review / packets | SQLite intent/receipt, queue revision a immutable packet digest; bridge SQL writer se nedrží přes projektový zápis. Zachovat. |
| ReportingScheduler / JuliaRunStore | Reálné claim/transition zápisy zachovat; čisté gettery oddělit od writer bootstrapu podle A06. |
| MessagePools | Již má odlišné `db` a `read_db`; vhodný reuse vzor, nikoli druhý journal. |
| SourceCollector | Flock chrání fetch journal/backoff/publication koordinaci; native owner je nutný, scope a síťovou dobu dále měřit. |
| RSSMonitoring / ComposableMonitoring | Node worker flock a persistentní effect intents; nelze povolit duplicity účinků ani aktivaci příjmem definice. |
| Monitoring process lock / lazy services | Lock chrání tick a vytvoření sdílené služby; background + manual HTTP vyžadují i nativní leases/owners. |
| RSS cache / refresh | Krátký cache owner je potřebný; síťový refresh nemusí blokovat snapshot view. |
| Julia worker map | Krátký mutex pro mapu je správný; nenahrazuje A05 admission procesů. |
| RunDeadline / task stream output | RLock pro stav/control, output mutex pro integritu NDJSON; run-control musí zůstat nezávislé. |
| Backend configuration | Krátká reentrantní konfigurace/reset je odůvodněná; neopravňuje 136-routový dlouhý HTTP mutex. |
| Drive / CMS / Cloudflare | Credentials, import/deploy intents a unknown receipts jsou trvalá autorita; A09 není důvod odstranit je. |
| Replication / Git transfer / receive | Flock chrání native staged operation/replay; node-wide resource cap není důkaz, že různé projekty sdílejí data. |
| Refinement deep-check | Nonblocking scan owner brání dvojímu scanu; proposal reads s migrací vyžadují explicitní rozdělení. |
| Deployment preferences | EX nad read-modify-write + atomic replace; malý odůvodněný writer. |
| Telemetry | Delty vzorků potřebují mutex, externí GPU I/O pod ním není stejná potřeba. |
| Availability samples / retry / sync fingerprints / diagnostics | Krátké condition/mutex sekce nad bounded mapami; vhodné, nejsou datovou/recovery autoritou. |
| History validation | Jedna disposable lower-priority validační kapacita bez čekající fronty chrání CPU; policy měřit, neobcházet validaci historie. |

U SQLite inventura odlišuje helper-based HTTP busy překlad od přímých connectů.
Mezi přímé cesty patří kromě nálezu A09 také autonomy, chat threads, external
dispatch, media, output/task/workflow stores, public-source journal, transfer
outbox a některé readonly diagnostiky. Přítomnost v inventuře sama neznamená
chybu. Každá změna musí doložit schema bootstrap, transakční vlastnictví,
read/write účinky a cílový failure outcome konkrétního volání.

## Kapacitní a časové meze

| Mez | Důvod existence a auditní závěr |
|---|---|
| 4 ordinary workers + 1 rezervovaný u desktop/web | Bounded sockets/threads potřebné; přesná čtyřka není doložená univerzální výkonová konstanta. Rezerva má A04. |
| Catalog N−1 | Chrání poslední ordinary slot před samotným dispatchovaným katalogem; nezaručuje rezervu před parsingem ani při jiném zatížení. |
| Běžný lane/project/process wait 100 ms | Brání parkování poolu; neřeší chybné sdílení a může systematicky odmítat normální práci. |
| IDE owner + 1 waiter, default 2 s | Počet čekajících je bounded, timeout-before-dispatch explicitní. Se dvěma ordinary workery owner+waiter obsadí oba — běžné API pak rezervované není. |
| HTTP read absolute 60 s + socket inactivity 1 s | Omezuje trickling i idle socket. Nedokončené hlavičky přesto mohou do svého timeoutu obsadit celý pool. |
| Browser max 64 pending, wait 5 s, jeden active/key | Bounded memory/explicitní not-started expirace jsou správné; reader FIFO má A08. |
| IDE max 32/connection, wait 5 s, HTTP inactivity 10 s | Bounded retained entries včetně expirovaných tombstones; nejde o end-to-end deadline celé synchronizace. |
| Exact server-busy retries 250/500/1000 ms | Jen doložené pre-dispatch refusal; nerozšiřovat na unknown nebo neurčitou síťovou chybu. |
| Manual content queue 64, jeden drain worker/node | Chrání node transfer kapacitu; durable replay stále drží native store. |
| Availability 1 probe, cache 8, TTL 30 s, probe 10 s | Bounded process sample, status nečeká na probe; nezaměňovat sample za aktuální autorizaci. |
| History validation 1 worker, default Git budget 60 s | CPU izolace a explicitní admission/deadline; nedokládá optimální kapacitu pro každý host. |
| Task stream soft 180 s, hard 360 s nebo 1800 s po extend | Záměrný owner-scoped control; browser/HTTP serializace nesmí zablokovat stop. |
| Server shutdown grace 225 s | Omezené drain čekání, nikoli důkaz ukončení všech schedulerů; A10. |

## Ověření, důkazy a limity závěru

Izolované sondy běžely na loopback socketech a v dočasných repozitářích,
bez skutečného LLM, Google, Cloudflare, peerů nebo feedu. Stavové kódy byly:

| Držená operace / stav | Souběžný požadavek | Výsledek |
|---|---|---|
| Provider callback | chat/status, tasks/cancel, chat/configure | 503 / 503 / 503 |
| Provider callback | tasks/run-control, diagnostics | 200 / 200 |
| Nedokončené provider tělo | chat/status, diagnostics | 503 / 200 |
| Monitoring callback | monitoring/view, monitoring/cancel, diagnostics | 503 / 503 / 200 |
| RSS HTTP refresh | RSS HTTP view / přímý native view | 503 / `loading` |
| Julia publish callback | julia/cancel, julia/status, diagnostics | 503 / 503 / 200 |
| Roadmap graph callback | document-patterns, diagnostics | 503 / 200 |
| Pět nedokončených hlaviček | diagnostics | 503 při 5/5 workerech |
| Project read ve snapshot fázi, current index | SH checkpoint / jiný projekt | `project-journal` busy / 200 |
| Reporting SQLite RESERVED writer | obyčejný SELECT / scheduler.get | přečten 1 run / typed SQLite busy |

Callbackové sondy testují admission a neprohlašují falešný handler za plnou
integraci konkrétní feature. Projektový read, reporting getter a RSS native
reader používaly reálné příslušné implementace s řízenou pauzou / dočasným stavem.
Kódem doložené call cesty jsou oddělené od dynamického důkazu; zvlášť A05,
A09 a A10 nemají zátěžovou nebo fyzickou runtime akceptaci.

Existující cílený běh:

```sh
python3 -m unittest tests.test_local_api tests.test_project_http_ownership \
  tests.test_http_ui_admission tests.test_journal tests.test_ide_http_ownership -v
```

**74 testů: OK, 2 volitelné přeskočené.** Zahrnuje klasifikaci rout, HTTP
pool/admission, browser EOF/cancel, nativní busy, read/write flock mezi procesy,
prepared-review replay a journal crash/recovery. Zelený výsledek nepotvrzuje
dostupnost běžného profilu; některé testy právě očekávají doložené odmítnutí.
Celá repository sada, skutečný multi-window profil a Omnia nebyly spuštěny.

Pomocné sondy a jejich JSON/logy jsou dočasně pod `/tmp/fpw-concurrency-audit-*`
a `/tmp/fpw_concurrency_audit_*.py`; trvalý výsledek a podmínky jsou v tomto
dokumentu, nikoli závislé na zachování `/tmp`. Agent neprovedl commit, restart,
deploy, credential změnu ani změnu uživatelského projektu.

## Podmínky pro následné opravy

Prioritu mají A01–A06; A04 a A05 jsou samostatné kapacitní problémy, nikoli
další varianta stejného mutexu. Následné změny potřebují pro každý owner
konkrétní data, rozsah, pořadí získání, nejdelší kritickou sekci a recovery.
Před rozšířením souběhu rozdělit initialized read od implicitního writeru;
neprovádět upgrade SH→EX bez znovuověření HEAD/pending/revize.

Zachovat [ADR 0003](adr/0003-coordinated-operation.md),
[ADR 0060](adr/0060-local-file-ide-bridge.md) a
[ADR 0062](adr/0062-pinned-queue-handoff.md): journal, Git CAS, projekční index,
neměnné packet digests, receipts, lidskou akceptaci a stejné operation/message ID
při obnově. Po dispatch není timeout důkaz neprovedení operace.

Akceptace musí zahrnout souběžná běžná čtení, ovládání během dlouhé práce,
dosažitelný status/cancel/diagnostiku, více projektů/oken a klientů, částečné
requesty, přetížení, bounded background práci, shutdown a crash/replay. Každé
omezení má být buď datový invariant, doložená kapacitní policy, nebo explicitní
neověřený předpoklad. Název `status` ani zelený test zámku tuto klasifikaci nenahrazuje.
