<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Síťové rozpočty a adresy (AUDIT-B5-T1)

Stav: **implemented**, čeká na review. Úkol AUDIT-B5-T1 řeší nálezy B-ODD-05
a B-ODD-06 z [auditu B1](audit-b1-locks-versions-oddities.md#nálezy-b-odd).
Zdrojová větev je `feature/audit-b4-error-states`, protože uživatel
20. 11. 2026 výslovně povolil řešit dávky B4 až B7 v jedné větvi a jednom PR.

## Pojmenované rozpočty

Všechny hodnoty jsou v [`spikes/peer_transport.py`](../spikes/peer_transport.py).
Rozpočet je celková lhůta jedné odchozí HTTPS výměny: připojení, TLS, odeslání
i čtení odpovědi. Nejde o timeout jedné operace soketu.

| Konstanta | Hodnota | Použití |
|---|---|---|
| `CATALOG_EXCHANGE_TIMEOUT` | 15 s | výměna katalogu projektů |
| `CONTENT_STATE_TIMEOUT` | 15 s | dotaz na manifest stavu obsahu |
| `RSS_EXCHANGE_TIMEOUT` | 15 s | výměna předvoleb RSS |
| `REPLICATION_TIMEOUT` | 30 s | přenos jednoho replikačního balíku |
| `CONTENT_SYNC_TIMEOUT` | 60 s | přenos jednoho balíku synchronizace obsahu; zároveň nejdelší čekání ručního workeru na vlastnictví zámku odesílání |
| `ENROLLMENT_TIMEOUT` | 10 s | jeden požadavek enrollmentu |
| `PROBE_TIMEOUT` | 5 s | interaktivní test spojení s peerem |
| `SHUTDOWN_MARGIN` | 5 s | rezerva při ukončení plánovače nad rámec rozběhnuté výměny |
| `CONTENT_RECEIVE_BUDGET` | 45 s | ověření historie přijatého balíku synchronizace obsahu; o `RESPONSE_MARGIN` (15 s) kratší než lhůta odesílatele, aby přetížený příjemce stihl odpovědět „busy“ |

Lhůta pro ukončení plánovače (`STOP_TIMEOUT`) se počítá jako
`stop_timeout(rozpočet)`, tedy rozpočet plus `SHUTDOWN_MARGIN`. Dřív šlo
o literály 20, 65 a 35 s. Hodnoty se nezměnily, jen se teď odvozují.
Zanikly tři stejnojmenné konstanty `NETWORK_TIMEOUT` (15, 60 a 30 s)
a literály 10 s a 5 s v enrollmentu a testu spojení.

Mimo rozsah zůstávají ostatní číselné `timeout=` (audit jich napočítal 91).
Většina z nich patří SQLite, které řešil B-LOCK-08 v AUDIT-B2. Zbytek tvoří
lokální subprocesy s vlastní hodnotou přímo u volání.

Když peer spojení přijme, ale do konce rozpočtu neodpoví, synchronizace
obsahu skončí stavem `unanswered` („neodpověděl včas“), ne `offline`. Peer
je dosažitelný a další pokus zopakuje stejnou uloženou operaci. Stav
`offline` zůstává pro nedostupný peer (spojení se nenavázalo). Podrobnosti
k ověřování na příjmu jsou v [ADR 0042](adr/0042-bidirectional-native-git-sharing-sync.md).

## IPv4 a IPv6

Uživatel 20. 11. 2026 rozhodl, že IPv6 se nevyřazuje. Dřívější omezení
„jen IPv4“ bylo nedopatření, nikoli rozhodnutí. Webový server, desktopový
síťový backend i federační přenos proto podporují obě verze. Doplnění je
zapsané v [ADR 0020](adr/0020-lxc-web-viewer.md).

Povolené adresy (`private_address`, `private_lan`):

| | IPv4 | IPv6 |
|---|---|---|
| peer | `ipaddress.is_private` včetně loopbacku `127.0.0.0/8` | unique local `fc00::/7` a loopback `::1` |
| bind serveru | doslovná adresa; desktop navíc privátní a ne loopback | doslovná adresa; desktop navíc unique local |
| podsíť klientů (`lan`) | privátní, prefix `/8` nebo užší | podsíť `fc00::/7` |

Odmítá se vždy výslovnou chybou:

- jméno hostitele (adresa se nikdy nepřekládá přes systémový DNS resolver,
  který nemá horní mez trvání);
- veřejná adresa, včetně dokumentačního `2001:db8::/32`, které modul
  `ipaddress` považuje za „private“;
- link-local `fe80::/10`, protože vyžaduje zónu rozhraní;
- IPv4-mapped adresy `::ffff:a.b.c.d`, aby jeden uzel měl jeden zápis;
- neurčená adresa `0.0.0.0` a `::` u peeru;
- bind a podsíť klientů v různých verzích IP.

Webový server bez `--bind` naslouchá na `0.0.0.0`, nebo na `::`, pokud je
`--lan` IPv6.

Technické podrobnosti:

- `DeadlineHTTPSConnection` přijímá doslovnou IPv4 i IPv6 adresu a podle ní
  otevře soket `AF_INET` nebo `AF_INET6`.
- `WebServer` volí rodinu naslouchacího soketu podle bind adresy.
- Autorita soketu pro kontrolu hlavičky Host má u IPv6 hranaté závorky
  (`[fd00::1]:8443`), stejně jako ji posílá prohlížeč.
- `private_peer_endpoint` vrací netloc v kanonickém zápisu
  (`[FD00:0::1]` → `[fd00::1]`), takže hlavička Host od odesílatele odpovídá
  autoritě, se kterou ji příjemce porovnává.
- Klientská adresa z dual-stack soketu `::ffff:127.0.0.1` se převádí na
  IPv4 (`canonical_address`). Kontrola loopbacku tak nezávisí na verzi
  Pythonu: 3.11 tuto adresu za loopback nepovažuje, novější ano.
- Certifikát vytvořený desktopem obsahuje v SAN zvolenou adresu, `127.0.0.1`
  i `::1`.
- Nabídka adres desktopu (`address_candidates`) obsahuje i unique local IPv6.

### Odloženo: nasazení do LXC a na router

Skripty nasazení zůstávají zatím jen IPv4 a hlásí to výslovnou chybou
„Expected private IPv4 LAN“. Jde o `lxc_deployment`, `deploy_omnia`,
`install_web`, `router_entry` a `router_tile`. Detekují adresu kontejneru přes
`ip -4` a v shellu generují TLS SAN. Bez fyzického routeru a LXC je nelze
ověřit, proto jsou samostatným navrženým odkladem, nikoli součástí B5.
Desktop i server spuštěný ručně už IPv6 podporují.

## Adresa peeru: jedna funkce

Jedna funkce `private_peer_endpoint` nahradila sedm kopií kontroly: katalog,
synchronizaci obsahu, replikaci, RSS, manifest stavu, enrollment a test
spojení. Pravidlo zní: HTTPS origin bez cesty, přihlašovacích údajů, query
a fragmentu, na doslovné povolené adrese podle tabulky výše. Hlášky volajících
teď místo „private IPv4“ říkají „private IP address“.

Audit uváděl, že replikace na rozdíl od ostatních zakazuje loopback. Ve
skutečnosti to rozdíl není: pro IPv4 je `127.0.0.0/8` součástí
`ipaddress.is_private`. Test spojení loopback skutečně zakazoval, nově ho
povoluje stejně jako ostatní peery.

Jméno hostitele místo IP adresy dřív skončilo obecnou `ValueError` z modulu
`ipaddress`. Nově vrací hlášku volajícího (`ValidationError`, podtřída
`ValueError`).

## Ověření

- `tests/test_peer_transport.py`:
  - povolené a odmítnuté adresy obou verzí, kanonický netloc, `private_lan`,
    `origin` a `canonical_address`;
  - všech sedm volajících používá společnou funkci s vlastní hláškou;
  - rodina soketu u `DeadlineHTTPSConnection` a `WebServer`, autorita
    v hranatých závorkách;
  - kontrola bind a podsítě u webového serveru a desktopového backendu,
    nabídka adres s IPv6;
  - `STOP_TIMEOUT` plánovačů je odvozený z rozpočtu.
- `tests/test_federation_sync.py`: synchronizace obsahu přes skutečné TLS
  na `[::1]` s nekanonicky zapsaným endpointem.
- Cílené běhy všech 42 modulů, které dotčený kód používají, prošly.
  Celá sada se spustí před PR.
