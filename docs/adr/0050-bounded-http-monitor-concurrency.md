<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0050 — Omezená souběžnost HTTP monitoru

Datum: 2026-10-25. Stav: navrženo, implementováno a fyzicky akceptováno v
`OPS-WEB-CONCURRENCY-01-A–D`. Rozšiřuje provozní
hranici telemetrie z [ADR 0049](0049-node-and-ollama-runtime-telemetry.md),
nemění autority a recovery kontrakty z
[ADR 0008](0008-context-and-publication-contracts.md).

## Kontext

Aktualizace 10. 11. 2026: oddělení auditovaných projektových operací popisuje
dodatek na konci tohoto ADR. Původní společná aplikační linka nadále platí pro
zbývající neauditované operace, nikoli pro níže vyjmenovanou projektovou skupinu.

Desktopový loopback server v `running_api('http')` i síťový TLS `WebServer`
před touto změnou používaly jednovláknový `HTTPServer`. Streamovaná odpověď
proto vlastnila jediný obslužný tok až do dokončení providerového běhu a
periodický dotaz `/v1/node-telemetry/status` čekal za ní. Samotné nahrazení
serveru neomezeným `ThreadingHTTPServer` by však současně zpřístupnilo
paralelní zápisy, requesty čekající bez limitu a sdílený mutující stav handleru.

Webový handler navíc při každém spojení zapisoval skutečnou lokální autoritu do
`server.authority` a `server.origin`. To bylo bezpečné pouze v dosavadním
sekvenčním serveru. Telemetrické čtení také zatím může přes běžné `connect()`
providerových journalů provést `CREATE TABLE` nebo migraci, zatímco webová
autentizace může pod výlučným administračním zámkem bootstrapovat registry.
Takové operace nelze označit za paralelní read-only cestu.

## Rozhodnutí

### Dvě omezené obslužné linky

TCP varianta desktopového API a síťový TLS server dostanou společný bounded
request server s nejvýše čtyřmi aktivními request workery. Limit se získává
před vytvořením workeru; při vyčerpání se nové spojení bounded odmítne a
nevzniká neomezená fronta ani vlákno. Unixový transport zůstává sekvenčním M0
experimentem, protože jej produkční desktop nepoužívá a tato feature nepotřebuje
měnit jeho peer-credential kontrakt.

Po načtení request line rozhoduje pouze přesná dvojice metoda/cesta:

- `POST /v1/node-telemetry/status` používá jednu monitorovací linku s kapacitou
  jednoho aktivního requestu;
- všechny ostatní metody a cesty používají jedinou aplikační linku. Ta zahrnuje
  oba stream endpointy, projektové a node-local zápisy, statické assety,
  `/v1/chat/test`, `/v1/node-telemetry/run` i
  `/v1/node-telemetry/configure`.

Každá linka má bounded čekání nejvýše dvě sekundy. Po jeho vypršení odpoví
handler před doménovým dispatch `503` a spojení zavře; klient nedostane příslib,
že se operace provedla, a server ji automaticky neopakuje. Čtyři workery dovolí
jednomu streamu, jednomu telemetrickému requestu a krátce nejvýše dvěma
odmítaným/ukončovaným spojením existovat současně. Nejde o obecnou paralelizaci
API a přetížení může odmítnout i telemetrii; požadovaným kontraktem je průchod
jednoho periodického vzorku vedle jednoho dlouhého streamu.

Autentizace, kontrola Host/Origin, bounded načtení těla, RBAC/privacy a doménový
dispatch stále proběhnou právě jednou ve workeru, který vlastní request. Worker
drží svou linku od začátku bezpečnostních kontrol až po dopsání nebo uzavření
odpovědi. Jeden worker jako jediný vlastní socket, `rfile`, `wfile` a stav
handleru; stream callback zapisuje synchronně pouze do jeho `wfile`. Jiný
worker nesmí dopisovat stejnou odpověď ani převzít dokončení streamu.

### Skutečně read-only monitorovací cesta

Bootstrap a kompatibilní schema migrace administračního registru a
providerových run journalů smějí proběhnout jen existující zápisovou cestou v
aplikační lince. Dokud nejsou dokončené, paralelní read-only autentizace nebo
čtení existujícího nekompatibilního journalu selže uzavřeně; chybějící
providerový journal se považuje za prázdný. Monitorovací cesta:

- autentizuje proti již inicializovanému stavu read-only; nesmí vytvářet
  administrační adresář, Git registry, credential databázi ani provádět migraci;
- čte existující SQLite journal přes validovaný read-only connection; chybějící
  OpenAI nebo Ollama journal znamená prázdný součet, nikoli jeho vytvoření;
- může měnit jen procesní delta čítače uvnitř existujícího zámku
  `NodeTelemetry`; nepersistuje je a nevydává je za run evidence;
- neprovádí provider probe, dispatch, změnu bindingu/policy, projektový zápis
  ani recovery jiné operace.

Chybějící, nekompatibilní nebo nebezpečný persistentní stav proto fail-closed
ukončí startup nebo dané čtení. Monitor jej za běhu neopravuje. SQLite se kvůli
této feature nepřepíná do WAL; krátké existující transakce, timeouty a doménové
zámky zůstávají autoritativní.

### Serializace a autorita zápisů

Jediná aplikační linka zachová sekvenční HTTP vstup, ale nenahrazuje
autoritativní zámky. Projektové operace nadále serializují `Workspace` writer
lock, journal, validace a Git compare-and-swap. Providerové, chatové a ostatní
node-local operace nadále rozhodují podle vlastních SQLite transakcí a stavů.
Již existující schedulery mají stejné doménové zámky a nejsou zataženy pod HTTP
linku.

Providerový dispatch drží aplikační linku po celý stream. Read-only monitor smí
pozorovat durable stav `dispatching`, ale nesmí z něj odvodit retry, přechod
stavu ani druhý backendový request. Souběžný zápisový HTTP request se neprovede
vedle streamu: buď získá linku po jejím uvolnění v limitu, nebo před dispatch
obdrží `503`.

Konfigurované autority serveru jsou po startu immutable. Skutečná cílová IP a
port přijatého spojení se uloží pouze do instance handleru a `request_authority`
je porovná s touto per-request hodnotou nebo s explicitně nakonfigurovaným DNS
hostname. Host ani `X-Forwarded-*` nadále autoritu neurčují.

### Odpojení, shutdown a crash boundaries

Zápis do odpojeného klientského socketu může ukončit pouze transportní část
vlastněnou daným workerem. Nezruší již provedený provider dispatch a nesmí jej
opakovat. Doménová služba dokončí validaci a durable přechod, pokud zná výsledek;
nejistota po odeslání zůstane podle existujícího journalu `unknown`.

Shutdown postupuje v tomto pořadí:

1. uzavře admission a přestane přijímat nové requesty;
2. zastaví accept loop, ale ponechá již přidělené workery, klientské sockety a
   doménové autority platné;
3. bounded čeká na workery. Produkční horní mez je
   225 sekund, odvozená z maximálního providerového timeoutu 180 sekund,
   runtime probe 10 sekund a SQLite busy timeoutu 30 sekund s rezervou;
4. teprve po dokončení workerů uzavře server a vyčistí token či dočasný Unix
   runtime. Při vypršení grace uzavře aktivní klientské sockety a proces se
   ukončí jako crash, nikoli jako úspěšně vyřízený request; persistentní
   transakce a journaly musí unést stejnou hranici jako jiné přerušení procesu.

Pád před provider dispatch nemá externí účinek. Pád po dispatch a před
terminálním journal stavem ponechá `dispatching`/`unknown` a restart jej
automaticky neopakuje. Pád u projektového zápisu se nadále obnovuje jediným
Workspace journalem podle [ADR 0003](0003-coordinated-operation.md); monitor
nikdy nepublikuje Git ani index.
Pád u telemetrie zahodí pouze ephemerální vzorek a další CPU/síťové delta začne
stavem `awaiting-second-sample`.

## Reuse a odmítnuté varianty

Adaptuje se stdlib `HTTPServer`/`ThreadingMixIn`, existující HTTP/1.0
one-request-per-connection handler, `NodeTelemetry` lock a všechny stávající
doménové zámky/journally. Soukromá inventura neposkytuje komponentu se shodným
request ownership, per-route admission a recovery kontraktem; žádný externí
kód ani neveřejný detail se nepřenáší.

Odmítá se neomezený `ThreadingHTTPServer`, obecný thread pool pro všechny
doménové operace, async framework, job server, druhý writer, WAL pouze kvůli
telemetrii, paralelní `/v1/chat/test`, sdílení handleru/socketu mezi vlákny,
automatický retry `503` nebo `unknown` a přesun streamu do detached background
úlohy.

## Důsledky a ověření

Deterministicky zkrácené limity testů doložily telemetrii dokončenou během
blokovaného streamu, nejvýše jeden telemetrický request, odmítnutý souběžný
zápis bez účinku, čtyřworkerový backpressure, per-request webovou autoritu,
odpojení klienta, čistý i deadline shutdown a restart bez druhého dispatch.
Úplná sada po části C prošla 824 testy s 28 přeskočenými. Skutečný desktop/web
TLS průchod v části D nad reálnou Ollamou dokončil 25,351s GPU stream s 1820
delta částmi; tři telemetrické requesty během něj odpověděly za 0,033–0,054 s
a souběžný zápis skončil bounded jako `503`. Restart zachoval jediný dokončený
run. Fyzické odpojení dalšího klienta po delta rámci zanechalo durable
`unknown/transport-unknown`; opakování po restartu selhalo před redispatch a
počet runů se nezměnil. Evidence a přesné výsledky regresí jsou ve WORK_LOG.


## Rozšíření 2026-10-30 — automatická dostupnost backendu

`OPS-BACKEND-AVAILABILITY-01` řeší konkrétní nález: UI automaticky volalo
`/v1/chat/test` každých 30 s i po běžných aplikačních operacích. Síťová sonda
`/api/tags` s timeoutem 10 s držela aplikační linku, jejíž čekací limit je 2 s.
Jde o doloženou možnost blokování; není to měření konkrétního uživatelského záseku.

Původní zákaz paralelního `/v1/chat/test` zůstává pro ruční test nastavení.
Automatický monitor nově používá přesný `POST /v1/chat/availability` v samostatné
krátké lince. Worker HTTP pouze provede stejné bezpečnostní kontroly, parsuje
binding a vrátí paměťový stav. Web vyžaduje admin oprávnění jako u ručního testu,
autentizuje však výhradně read-only, bez bootstrapu nebo migrace registru.

Jediný server-owned background worker provádí read-only `OllamaAdapter.probe`
(timeout 10 s) nad immutable validovaným bindingem se stejným boundary a TLS
pinem. Nemá referenci na handler, socket klienta, projekt ani zapisující službu.
V daném okamžiku běží nejvýše jedna automatická sonda pro celý server. Další dotaz sondu
neduplikuje ani nevkládá do fronty; při jiném bindingu dostane neověřený stav
nebo vlastní starší vzorek a doporučení znovu načíst stav za sekundu.

Cache má nejvýše osm vzorků, klíčem je celý binding včetně endpointu, modelu,
revize a TLS pinu. TTL 30 s se měří monotónně od dokončení sondy. Status nese
čas dokončení v UTC, `available` (true/false/null), `model_available`, `checking`
a `stale`. Selhání sondy je nový nedostupný vzorek; chyba načítání statusu v UI
nevydává sama o sobě backend za nedostupný. Při obnově UI zachová předchozí čas
měření a označí stáří. Při změně bindingu výsledek starého požadavku nepřevezme.
Pravidelné dotazy i následná kontrola po akci mohou číst cache bez nové sítě.

### Crash boundaries a shutdown

Nevzniká persistentní vrstva ani koordinace více úložišť. Pád před, během i po
sondě zahodí pouze paměťový vzorek; další proces začíná neověřeně. Síťový efekt
je pouze read-only `/api/tags`, nikoli generování, fallback nebo restart.
Sampler se neúčastní Workspace, Git, indexu ani providerového run journalu.
Jejich původní recovery se nemění. Běžný shutdown nejprve zavře HTTP admission,
poté dokončí přijaté requesty, zavře admission sampleru a čeká na běžící sondu
ve zbývající společné grace. Vypršení grace nastaví `shutdown_clean=false`;
proces nesmí hlásit čisté dokončení. Po uzavření sampler nepřijímá nové sondy
ani nepublikuje pozdní výsledky. Unixový M0 transport zůstává sekvenční.

Reuse: stdlib Thread/Condition a bounded HTTP lifecycle, původní Ollama klient
a validátor, read-only admin autentizace, stávající panel Zdroje. Obecný worker
pool s frontou, změna serializace zápisů, neomezená vlákna, nová databáze a
externí framework se odmítají. Výsledky ověření patří do aktivního TODO a po
předání do WORK_LOG pod ID této feature, nikoli do historických počtů výše.

## Rozšíření diagnostiky a rezervace UI, 9. 11. 2026

Na výslovné zadání uživatele je změna součástí aktivní RSS větve.
Síťový web i skutečný desktopový management server mají vedle čtyř
běžných HTTP workerů jedno rezervované místo.
Nejde o druhý proces: čtyři POST operace mohou běžet/čekat současně,
další běžný POST dostane pre-dispatch 503. Statické GET assety obcházejí
aplikační zámek. OAuth callback jej stále používá. HTTP spojení před
rozpoznáním cesty sdílejí bounded pool, takže pomalé/neúplné hlavičky mohou
rezervaci krátce obsadit do původního socket timeoutu; nejde o izolovaný
server ani ochranu proti zahlcení sítě.

Při vyčerpání všech míst přijímací smyčka zkusí odeslat pevnou pre-dispatch
HTTP 503 odpověď `server busy`, s `Retry-After: 1` a limitem zápisu 100 ms;
nevytváří další vlákno ani frontu. Odpojený či nečtoucí klient nemusí
odpověď převzít. Obsazené UI linky čekají nejvýše 100 ms (nebo kratší nakonfigurovaný
limit), aby krátké kolize více oken nekončily 503. Delší operaci odmítnou,
aby čekání na zámek dlouhodobě nezabíralo workery. Samostatný nízkoúrovňový
transport bez UI rezervace zachovává původní bounded čekání. Automatický retry se touto změnou nezavádí.

Sdílené desktopové/webové UI omezuje vlastní souběh same-origin POST
požadavků na jednu operaci v každé přesné backendové lince. Nejvýše 64
čekajících požadavků na linku zůstává pouze v paměti prohlížeče; backendové
workery čekáním nezabírají. Telemetrie, dostupnost/run-control, review a
diagnostika mají oddělené pořadí. Zrušený čekající požadavek se neodešle.
Uvolnění linky čeká na konec těla odpovědi, ne pouze na hlavičky;
streamovaná odpověď se přesto předá svému konzumentovi ihned. Čtecí kopie
průběžně zahazuje chunky, nevytváří archiv odpovědi. Síťová chyba ani HTTP
odmítnutí nezpůsobí automatický retry. Toto řízení souběhu není durable
fronta a po zavření stránky se čekající požadavky neobnovují.

Přesný POST `/v1/diagnostics/status` má samostatnou linku a smí použít
rezervované místo. Na webu vyžaduje administrátora a read-only autentizaci;
nezískává projektový zámek, nespouští probe, sync, LLM ani recovery.
Sdílení projektů nabízí tlačítko **Diagnostika synchronizace**. Výpis je
lokální pro právě otevřený uzel, nikoli automaticky sesbíraný z peerů.

Přehled obsahuje počet workerů, obsazené HTTP linky a poslední fázi, časy
a typ chyby synchronizace. Paměťová evidence drží nejvýše 64 posledních
dvojic uzel/peer/projekt v procesu; příchozí i odchozí pokus mohou nahradit
poslední pozorování téže dvojice. Po restartu evidence zmizí. HTTP timeout,
obsazená linka, odmítnutí workeru a selhání sync vypisují bezpečný záznam do
standardního loggeru služby: bez URL, tokenu, payloadu či textu výjimky.
Nejde o automatické dumpy Python zásobníků ani průběžný profiler CPU.
HTTP přehled navíc uvádí počet odmítnutí a aktivní workery: pouze pevnou
kategorii operace, fázi obsluhy a dobu od přijetí spojení, nikdy raw URL.

Crash boundaries a recovery z ADR 0042 / 0081 / 0082 zůstávají platné:
diagnostika nezapisuje do Git, projektového indexu ani sync journalu.
Ztráta diagnostiky při pádu nemění stav přenosu; opakování používá původní
durable operaci. Změna neruší timeouty a neslibuje opravu samotného sync.
Zdrojové integrační testy a fyzické nasazení na Omnii se ověřují odděleně.

Veřejné prezentační okno sdílí řízení souběhu a při skrytí neprovádí polling
ani hlášení poměru stran. Viditelný polling má nanejvýš jeden aktivní pokus.

## 9. 11. 2026 — oddělení prověřených vlastníků při opravě dostupnosti

Běžný lokální provoz nadále dokládal kolize společné aplikační linky i při
operacích kolem 0,5–1,3 sekundy. Původní akceptace monitorovacího PoC není
akceptací obecné dostupnosti. Konkrétní inventuru, důvod změny a recovery
popisuje [HTTP concurrency audit](../http-concurrency-ownership.md).

Příjem content sync, katalog projektů a prezentační stav mají samostatné
serializované HTTP domény. Přesnou tabulku rout sdílí backend s browserem.
Zbytek operací zůstává v konzervativní aplikační doméně; zejména názvy
`status` a `preview` nejsou důkazem absence zápisů nebo recovery.
Katalog a prezentační doména na webu používají read-only autentizaci.
Projektové zápisy nadále rozhoduje existující Workspace journal/writer/CAS.

Celý inbound replay/publikační cyklus navíc vlastní uzlový neblokující
receive `flock`, společný i pro více listenerů a přímé volání receiveru.
Je oddělený od outbound zámku: příjem nesmí čekat na vlastní odesílání,
které čeká na odpověď peeru. Obsazení vrátí `503` bez doménového dispatch;
nedokončená durable operace se nezahazuje ani automaticky neopakuje.
Pád pouze uvolní procesní zámky; původní journaly zůstávají autoritou.
Počet workerů, timeouty, shutdown a bezpečnostní validace se nemění.

Jde o implementovaný lokální řez s automatizovaným ověřením, nikoli lidskou
akceptaci opravy všech kolizí, úplné odstranění aplikační domény nebo nové
nasazení na Omnii.

## Dodatek 10. 11. 2026 — projektové vlastnictví po autentizaci

Přesný seznam `PROJECT_ROUTES` v `http_admission_policy.py` odděluje 24
projektových operací: otevření projektu, náhled a historii artefaktů, editor
včetně položek plánu, Stage/Commit a projektové konflikty. Každá položka
explicitně určuje umístění `project_id`, včetně vnořeného dokumentu, položky,
resolution či preview. Neodvozuje se z názvu URL. Tyto handlery používají
request-local služby; nepřepisují `server.projects`, vybranou prezentaci ani
líně vytvořenou sdílenou službu. Zbývající operace si ponechávají předchozí
vlastnictví a vyžadují další audit.

Tato skupina nejprve provede Host/Origin, autentizaci a bounded načtení JSON.
Teprve potom validuje kanonické UUID a získá procesní zámek příslušného projektu,
s čekáním nejvýše 100 ms nebo menším nastaveným limitem. RBAC, privacy a celá
validace doménového requestu zůstávají v původním dispatchi. Registry bootstrap
včetně migrace proběhne na webu před vytvořením listeneru; projektová webová
autentizace používá existující read-only cestu. Dva různé projekty proto
nesdílejí HTTP zámek a nejsou zařazené za stream v aplikační lince.

Ani projektové čtení zde není deklarované jako čistě read-only: stále může
inicializovat journal nebo obnovit index. Tyto účinky vlastní projektový journal.
Request-local ContextVar přepne každý Journal flock získávaný během HTTP operace
na neblokující režim, včetně journalů vytvořených hluboko v desktopových službách.
Obsazení se přenáší samostatnou výjimkou `ProjectBusy`, aby se neztratilo v
obecné obsluze `OSError` jako validační chyba. Mimo tento kontext se původní
nativní režim zamykání nemění. Přímý SyncReceiver používá stejnou omezenou
hranici i bez HTTP adaptéru; svůj receive flock nadále drží samostatně.

Obsazený HTTP vlastník vrací 503, Retry-After a `outcome=not-started`. Obsazení
journalu během doménového dispatch vrací konzervativní `outcome=unknown`: mohla
již proběhnout dřívější fáze stejné operace. Klient zachová původní operation ID;
503 není automatický retry ani příslib, že neproběhl žádný zápis. Synchronizační
klient rozlišuje HTTP 503 stavem `busy` a zachovává původní outbound envelope.
422 nadále znamená odmítnutý obsah, 409 konflikt vyžadující rozhodnutí.

Browser sdílí stejnou tabulku a používá frontu/Web Lock podle projektu, včetně
vnořených requestů. Celkově přijme nejvýše 64 čekajících či aktivních požadavků
na stránku. Nezvyšuje počet HTTP workerů. Procesní mapa vlastníků zahazuje
nepoužívané klíče; diagnostika uvádí deklarovanou operaci a validované project ID.

Persistentní formát, journal a Git CAS se nemění. Před admission nevzniká intent.
Po zapsání intentu, po Git publikaci i po ztracené odpovědi se použije stejné
recovery podle ADR 0003/0081. Procesní zámek není důkaz úspěchu a jeho uvolnění
nevyvolává recovery. Konfliktní pracovní soubory se nepřepisují. Tato změna
neodstraňuje zbývající aplikační linku ani nemění federační protokol.

Stejná request-local hranice omezuje také flock administračního registru:
projektový write_guard nesmí HTTP worker neomezeně zablokovat přes node state.
Mimo request kontext zůstává jeho původní blokující režim. Desktop i web
bootstrapují administraci před spuštěním listeneru. Automatizované důkazy a
zbývající rozsah jsou v `docs/http-concurrency-ownership.md`; lidská akceptace
ani nasazení se z těchto testů neodvozují.

### Navazující audit všech hranic čekání, 10. 11. 2026

[Inventura čekání](../http-blocking-audit.md) rozlišuje HTTP admission,
file/process zámky, SQLite, Git, síť, browser fronty a shutdown. Samotná kapacita
fronty či socket inactivity timeout není celkový deadline požadavku.
Zbývající blokující file flocks v HTTP používají společný `bounded_flock`,
včetně sdíleného read-only zámku autentizace. Mimo request kontext zůstává
původní nativní kontrakt. Odchozí sync coordinator má také bounded kontext,
kontrolu zrušení před admission a neblokující uzlový zámek, s kapacitou jeden.

Typed busy po odeslání hlaviček NDJSON streamu se hlásí terminálním rámcem 503
s unknown výsledkem, nikoli druhou HTTP odpovědí. Původní worker dál vlastní
socket. Tato změna nepřesouvá stream do úlohy, nemění jeho run journal ani
neznamená dokončení auditu všech procesních zámků a timeoutů.

Šest existujících konfiguračních/reset scope v ChatService nyní získává svůj
stávající RLock přes bounded HTTP acquisition (100 ms). Reentrance a původní
nativní chování se zachovávají. Tím se omezuje čekání na vlastníka; neurčuje se
tím celkový čas jeho chráněné práce a nepovoluje souběžný dispatch/reset.

### Providerová linka a načítání administrace

Navazující přesná klasifikace odděluje providerovou skupinu od aplikační linky.
Tři streamy sdílejí kapacitu jedna s konfigurací/resetem backendů, chat lifecycle
recovery, souvisejícími workflow službami a destruktivními projektovými/node
operacemi. Jejich původní pořadí se zachovává. Ostatní auditované aplikační
operace používají své dosavadní nativní vlastníky a mohou pokračovat vedle
providerového čekání. Worker pool ani persistentní protokol se nemění.

Přesná akce `list` na `/v1/administration` dostává samostatnou node-status linku
po autentizaci a bounded parsování JSON. Není to obecné read-only vyjmutí;
agregace může zapisovat synchronizační status a inicializovat schéma pod
existujícími nativními zámky. Mutace a neznámé akce zůstávají v providerové
skupině. Server i browser používají tutéž tabulku akcí. Streamy také získávají
linku po autentizaci/těle; stop/extend zůstává nezávislý.

Tabulka obsahuje všech 258 registrovaných JSON rout a čtyři peer protokoly.
Produkční desktop/web startup odmítne novou registrovanou JSON routu bez
klasifikace. Podrobné vlastnictví, omezení a crash kontrakty jsou v navazující
sekci `docs/http-concurrency-ownership.md`; nejde o dokončení celé náhrady.

Reálné browser scénáře navíc odhalily kolizi původních výlučných registry čtení.
Web autentizace nyní vždy používá stávající read-only cestu; HTTP listing a
projektová replikační role čtou sdílený snapshot s přesným registry commitem.
Nativní volání mimo bounded kontext zachovává bootstrap. Startup připraví také
stávající podpisovou identitu; HTTP čtení její chybějící klíč/marker neinicializuje.
Původní atomické publikování key/marker a fail-closed integrita se nemění.
Účet se po admission znovu ověří před doménovým RBAC, aby odvolání během čekání
nepoužilo starý actor snapshot. Viz podrobné crash boundaries v auditním dokumentu.

Stejný sdílený snapshot v bounded kontextu používají také kontrola mapovaných
akcí, aktivní replikace, počty chatových mapování, federační katalog/content
oprávnění a identita probe odpovědi. Čtecí agregace tím nevstupuje zpět do
výlučného bootstrapu přes pomocný dotaz. Poslední cílený běh prošel 293 testy
včetně skutečného Qt; přímý katalog/probe dalších 11. Plná sada a širší audit
nejsou dokončené. Výsledek není nová fyzická akceptace Omnie.

### Pětisekundová browser admission hranice

Browser má společný limit pěti sekund pro čekání ve FIFO a na originový Web
Lock. Nejde o timeout již spuštěného streamu. Zrušené/vypršelé položky se z FIFO
odeberou a uvolní kapacitu; nevytváří se neomezený řetězec příslibů za otevřeným
streamem. Pozdní timer/lock callback před fetch znovu ověří elapsed deadline.

Před zavoláním transportu má neúspěch `outcome=not-started` pro tento pokus.
Po zavolání fetch je nejistota `unknown`; původní signál a operation ID se
nemění. Caller abort neuvolňuje obsazenou linku před EOF/chybou transportu.
Projektový JSON a NDJSON klient zachovávají rozlišení a z neúplné odpovědi
nevyrábějí potvrzený výsledek. Automatický retry ani zahození backend journalu
se nezavádí. Úplný kontrakt, stale-export výjimka podle instrukce uživatele a
99 cílených testů včetně skutečného Qt jsou v navazujícím auditním dokumentu.

### SQLite contention při otevření projektu

Projektový journal, projektový index (včetně inicializace a rebuild) a read-only
čtení stavu sync konfliktů adaptují stávající bounded request kontext: SQLite
busy timeout je v něm nulový. BUSY/LOCKED včetně rozšířených kódů přejdou do
stávajícího `ProjectBusy`; ostatní databázové chyby se nepřeklasifikují.
HTTP worker při kolizi nečeká na databázi. Mimo tento kontext zůstávají původní
nativní timeouty. Nejde o celkový deadline SQL/disku ani dokončení auditu všech
SQLite stores; inicializující čtení se tím nestávají čistě read-only.

Transakční recovery zůstává podle ADR 0003: rollback aktuální nepotvrzené
transakce neruší dříve uložený intent ani publikovaný Git commit. Při busy během
indexace zůstává stejná rozpracovaná operace a recovery dokončí její index a
receipt. Žádný nový writer, retry, schema či WAL migrace se nezavádí. Důkazy
a zbývající rozsah jsou v [auditu vlastnictví](../http-concurrency-ownership.md).

### Připojení inicializovaného stavu při projektovém čtení

Otevření projektu, plán a preview mohou místo bootstrapu připojit existující
journal a aktuální index. Vlastník journalu se ověří pod jeho zámkem ještě před
otevřením indexu. Chybějící stav a rozpoznané starší projekce používají původní
inicializaci/obnovu; chyba, obsazení či neplatný vlastník nejsou resetovací cesta.
Pending, HEAD, privacy a sémantické kontroly se nemění. Čtení může dál opravovat
index, proto se jeho HTTP linka nepřeklasifikuje na volně souběžnou read-only.

Desktopové HTTP otevření/plán sdílí původní webový 30s Git rozpočet od validace
registrace po view/draft. Timeout draftu není volitelná chyba; před vrácením view
se kontroluje konec rozpočtu. CPU/disk a samostatné registry Git volání tím nejsou
preemptivně přerušovány. Crash boundaries a journal recovery zůstávají ADR 0003;
změna nepřidává persistentní formát ani automatickou obnovu pending operace.
