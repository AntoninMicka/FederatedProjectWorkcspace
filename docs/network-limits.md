<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Síťové rozpočty a adresa federačního peeru (AUDIT-B5-T1)

Stav: **implemented**, čeká na review. Úkol AUDIT-B5-T1, nálezy B-ODD-05
a B-ODD-06 z [auditu B1](audit-b1-locks-versions-oddities.md#nálezy-b-odd).
Zdrojová větev `feature/audit-b4-error-states`: uživatel z 20. 11. 2026
výslovně povolil řešit dávky B4 až B7 v jedné větvi a jednom PR.

## Pojmenované rozpočty

Všechny hodnoty jsou v [`spikes/peer_transport.py`](../spikes/peer_transport.py).
Rozpočet je celková lhůta jedné odchozí HTTPS výměny
(`DeadlineHTTPSConnection`: připojení, TLS, odeslání i čtení odpovědi), nikoli
timeout jedné operace soketu.

| Konstanta | Hodnota | Použití |
|---|---|---|
| `CATALOG_EXCHANGE_TIMEOUT` | 15 s | výměna katalogu projektů |
| `CONTENT_STATE_TIMEOUT` | 15 s | dotaz na manifest stavu obsahu |
| `RSS_EXCHANGE_TIMEOUT` | 15 s | výměna předvoleb RSS |
| `REPLICATION_TIMEOUT` | 30 s | přenos jednoho replikačního balíku |
| `CONTENT_SYNC_TIMEOUT` | 60 s | přenos jednoho balíku synchronizace obsahu; také nejdelší čekání ručního workeru na vlastnictví zámku odesílání |
| `SHUTDOWN_MARGIN` | 5 s | rezerva při ukončení plánovače nad rámec rozběhnuté výměny |

Lhůta pro ukončení plánovače (`STOP_TIMEOUT`) se počítá jako
`stop_timeout(rozpočet)`, tedy rozpočet plus `SHUTDOWN_MARGIN`. Dřív šlo
o literály 20, 65 a 35 s. Hodnoty se nezměnily, jen se teď odvozují. Dřívější
tři stejnojmenné konstanty `NETWORK_TIMEOUT` s hodnotami 15, 60 a 30 s zanikly.

Mimo rozsah zůstávají ostatní číselné `timeout=` (audit jich napočítal 91).
Většina z nich patří SQLite, které řešil B-LOCK-08 v AUDIT-B2. Zbytek jsou
lokální subprocesy s vlastní hodnotou u volání.

## Adresa peeru

Jedna funkce `private_peer_endpoint` nahradila pět kopií v katalogu,
synchronizaci obsahu, replikaci, RSS a manifestu stavu. Pravidlo zní: HTTPS
origin bez cesty, přihlašovacích údajů, query a fragmentu, na doslovné privátní
IPv4 adrese, která není `0.0.0.0`. Hlášky jednotlivých volajících se nezměnily.

Audit uváděl, že replikace na rozdíl od ostatních zakazuje loopback. Ve
skutečnosti to rozdíl není: pro IPv4 je `127.0.0.0/8` součástí
`ipaddress.is_private`, takže replikace loopback povolovala stejně jako ostatní.
Testy replikace ostatně běží proti `127.0.0.1`. Sjednocení proto chování
nemění.

Jedna drobná změna: jméno hostitele místo IP adresy dřív skončilo obecnou
`ValueError` z modulu `ipaddress`. Nově vrací hlášku volajícího o privátní IPv4
(`ValidationError`, podtřída `ValueError`).

## Rozhodnutí o IPv6

Federační peer, bind webového serveru a desktopový síťový backend zůstávají
**jen IPv4**. Tento předpoklad už dříve dokumentovaly
[ADR 0020](adr/0020-lxc-web-viewer.md) a
[desktopový síťový backend](desktop-network.md); teď je výslovným rozhodnutím.
Důvody:

- `DeadlineHTTPSConnection` přijímá jen doslovnou IPv4 adresu. Díky tomu se
  při připojení nevolá systémový DNS resolver, který nemá horní mez trvání.
- Podsítě LAN klientů (`lan`) a výběr adresy kontejneru LXC počítají s IPv4
  a privátní IPv6 nemá v nasazení doložený případ použití.
- Registrovaný endpoint peeru se ukládá obecně jako HTTPS URL. Adresu IPv6 nebo
  jméno hostitele odmítne až přenos, a to výslovnou chybou „… private IPv4
  …“. Nic se tiše nevypne a nepoužije se jiná adresa.

Vstupy jsou ověřené takto:
- bind webového serveru hlásí IPv6 výslovně: „Specify a literal IPv4 bind
  address; IPv6 is not supported“;
- desktopový backend vrací „Vyberte konkrétní privátní IPv4 desktopu v povolené
  LAN.“;
- nasazení do LXC vrací „Expected private IPv4 LAN“.

Podpora IPv6 by byla samostatná feature. Potřebovala by doslovné adresy IPv6
v `DeadlineHTTPSConnection`, politiku pro ULA (`fc00::/7`) a link-local adresy
se zónou, SAN certifikátů a podsítě LAN klientů pro IPv6.

## Ověření

- `tests/test_peer_transport.py`:
  - pravidlo adresy: privátní adresa i loopback povolené, veřejná adresa, IPv6,
    jméno hostitele, `0.0.0.0`, cesta, přihlašovací údaje, query a fragment
    odmítnuté;
  - všech pět volajících používá společnou funkci a ponechává svou hlášku;
  - `STOP_TIMEOUT` plánovačů je odvozený z rozpočtu.
- Dotčené moduly federace, replikace, RSS a webového serveru: cílené testy.
