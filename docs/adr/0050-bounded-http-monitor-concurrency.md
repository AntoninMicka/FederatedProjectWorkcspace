<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0050 — Omezená souběžnost HTTP monitoru

Datum: 2026-10-25. Stav: navrženo a implementováno v
`OPS-WEB-CONCURRENCY-01-A–C`; fyzická akceptace zůstává v části D. Rozšiřuje provozní
hranici telemetrie z [ADR 0049](0049-node-and-ollama-runtime-telemetry.md),
nemění autority a recovery kontrakty z
[ADR 0008](0008-context-and-publication-contracts.md).

## Kontext

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
průchod s dlouhou Ollama odpovědí zůstává neověřený do části D.
