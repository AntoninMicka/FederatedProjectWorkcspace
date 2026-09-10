# ADR 0006 — Lokální transport/API pro desktop

Stav: přijato pro směr navazujícího PoC; produkční stack a desktopový obal zůstávají M0-06. Datum: 2026-09-09.

## Rozsah a hranice před implementací

Porovnat Unix domain socket a IPv4 loopback HTTP nad stejným verzovaným API. Obě varianty používají stejný HTTP handler, aby rozdíl nespočíval v jiné autorizaci nebo aplikační funkci. Unix socket je lokální IPC transport; neznamená samostatný backendový proces.

Jediná operace je `POST /v1/counter` s JSON `{"action":"increment"}`. Čítač je výhradně v paměti a dokládá, zda požadavek prošel až k mutaci. Experiment nemá přístup ke Git, LLM, projektovým souborům ani credentials. Pád ztratí čítač a token; nový start vytvoří nový token a endpoint. Čisté ukončení odstraní vlastní socketový adresář. Pád procesu může zanechat adresář/socket; nový start používá unikátní adresář a cizí ani staré sockety automaticky nemaže. Úklid po pádu a lifecycle launcheru patří do M0-06.

Budoucí napojení na Workspace musí zachovat [ADR 0003](0003-coordinated-operation.md). Ztracená HTTP odpověď po commitu nesmí vyvolat nový zápis; před připojením persistentních mutací je nutné určit klientské operation ID, retry a čtení receipt. PoC čítač toto neřeší a není API pro projektové zápisy.

## Kontrakt experimentu

- HTTP bind pouze `127.0.0.1`, port vybírá OS. Host musí přesně odpovídat adrese a portu; žádný wildcard, proxy hlavička ani alias `localhost`.
- Pro každý start náhodný 256bitový bearer token; test driver jej získává přímo v paměti, není veřejný bootstrap endpoint, token v URL ani souboru. Předání mezi launcherem a backendem je dosud návrh: zděděný chráněný kanál, bez logování či argumentů procesu.
- Origin, pokud je přítomen, musí přesně odpovídat vlastnímu HTTP originu. `null`, `file://`, cizí origin i duplicitní hlavičky jsou odmítnuty. Chybějící Origin je povolen pro nativního klienta, který stále musí prokázat token.
- CSRF kontrakt: bearer v explicitní Authorization hlavičce, žádná cookie autentizace, pouze JSON, žádné CORS povolení ani OPTIONS preflight. Fetch metadata `cross-site` a `same-site` se odmítají. Správný Origin nikdy nenahrazuje token. UI proto musí být ze stejného originu nebo použít posouzený nativní bridge; tento spike UI neservíruje.
- Jedna mutace na spojení, bez keep-alive a chunked requestů. Tělo nejvýše 4096 bajtů, jedno Content-Length a Content-Type, omezený existující JSON parser a přesné schéma. Socket read timeout 1 s; odpovědi no-store, bez odrazu vstupních dat, bez request logů.
- Unix varianta má soukromý rodičovský adresář 0700 vlastněný aktuálním UID, nový podadresář a socket 0600. Linux SO_PEERCRED musí vrátit povolené UID. Navíc používá stejný bearer kontrakt. Stejné UID ani root nepředstavují touto kontrolou izolovaného protivníka.

## Porovnání a rozhodnutí

| Vlastnost | Unix socket | Loopback HTTP |
| --- | --- | --- |
| Lokální hranice | Práva filesystemu + kernel UID + token | Bind loopback + token; samotná IP neidentifikuje aplikaci |
| Přístup webového UI | Vyžaduje nativní bridge/adapter | Vhodný pro UI servírované ze stejného originu |
| Browser útoky | Browser nemá přímý socketový endpoint; bridge potřebuje vlastní kontrolu původu | Nutné Host/Origin/CSRF kontroly, bez širokého CORS |
| Lifecycle | Soukromý runtime adresář, délka Unix cesty, pozůstatky po pádu | Ephemeral port, bezpečné předání endpointu a tokenu |
| Přenositelnost PoC | Linux SO_PEERCRED | Ověřeno pouze na Linux IPv4; jiné OS nejsou doloženy |
| Společné limity | Token bootstrap, bezpečnost UI, retry a napojení služeb neověřeny | Stejné |

**Pro pokračování se sdíleným webovým UI preferovat loopback HTTP se stejným originem.** Unix socket ponechat jako ověřenou alternativu, pokud M0-06 vybere nativní bridge. M0-04 nevybírá Qt ani Tauri a nezavádí produkční HTTP framework. Nejde o výkonové rozhodnutí; nebyl měřen výkon na cílovém zařízení.

## Důkazy a omezení

Implementace: [local_api.py](../../spikes/local_api.py). [Testy](../../tests/test_local_api.py) používají skutečné dočasné Unix sockety a loopback porty. Pokrývají úspěšné nativní i same-origin požadavky, chybějící/chybné/staré credentials, Host/Origin, cookie/query pokusy, CSRF formáty a metody, duplicitní hlavičky, délky, JSON duplicity, neplatné schéma, timeout a pipelining. Každé protokolové odmítnutí musí vrátit 4xx a zachovat čítač; testy kontrolují i absenci CORS a tokenu v odpovědi/logu.

UID test používá skutečné SO_PEERCRED a úmyslně odlišné povolené UID; nespouští proces jiného uživatele. Restart test znovu vytváří instanci serveru, nesimuluje SIGKILL backendu. Testy jsou protokolové, nikoli end-to-end browser/WebView testy; nepokrývají XSS, odcizení tokenu stejným uživatelem, plný parser fuzzing ani odolnost proti DoS. Jednovláknový server lze opakovanými pomalými klienty zdržovat i přes read timeout. Produkční server bude potřebovat limity souběhu a celkový deadline.

Python [http.server](https://docs.python.org/3/library/http.server.html) je dle jeho dokumentace určen pouze pro základní HTTP obsluhu a není doporučen pro produkci; zde slouží s vlastním handlerem bez servírování souborů. [socketserver](https://docs.python.org/3/library/socketserver.html) poskytuje obě transportní varianty bez nové pip závislosti. Aplikační parser adaptuje existující `spikes.metadata.parse_json`; druhý parser ani kopie externího aplikačního serveru nejsou potřeba.

Aktuální běh celé sady je evidován v [WORK_LOG](../../WORK_LOG.md). Síťová federace zůstává M5: vyžaduje samostatné peer identity, TLS, projektová oprávnění a revokaci; lokální bearer token se na ni nesmí rozšířit.
