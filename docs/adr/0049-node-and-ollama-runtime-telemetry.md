<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0049 — Telemetrie uzlu a evidence runtime Ollamy

Datum: 2026-10-25. Stav: navrženo a implementováno v
`OPS-NODE-MONITOR-01`; fyzická akceptace určuje výslednou úroveň dávky.
Rozšiřuje přesný Ollama binding a run journal z
[ADR 0008](0008-context-and-publication-contracts.md), provozní hranice
[Ollamy v LAN](../ollama-lan.md) a společný panel Zdroje.

## Kontext

Dostupný Ollama endpoint ani úspěšná modelová odpověď nedokládají, že inference
proběhla očekávaným způsobem. Po změně hostitele, ovladače nebo kontejneru může
stejný model tiše běžet pouze na CPU. Dosavadní panel Zdroje současně obsahoval
jen statické indikátory a nemohl rozlišit aktuální stav uzlu od historické
evidence konkrétního běhu.

Diagnostika nesmí měnit autorizovaný Target, přepínat backend, restartovat
službu ani automaticky opakovat neurčitý síťový účinek. Metrika využití GPU v
jednom okamžiku navíc sama nedokládá, na jakém procesoru proběhla celá inference.

## Rozhodnutí

### Dva oddělené kontrakty

1. `NodeTelemetry` sestavuje ephemerální read-only vzorek lokálního workspace
   uzlu. Obsahuje CPU a síťové delta čítače z `/proc`, RAM z `/proc/meminfo`,
   zaplnění filesystemu se stavem uzlu přes `statvfs` a volitelně NVIDIA
   GPU/VRAM přes bounded `nvidia-smi`. Každá hodnota nese stav, jednotku a
   zdroj; nedostupný zdroj je `unknown`, nikdy odhadnutá nula.
2. `OllamaRuns.runtime_evidence` je durable evidence jednoho dokončeného běhu.
   Po validní providerové odpovědi se přes tentýž přesný `OllamaBinding` provede
   read-only `GET /api/ps`. Jediná přesná shoda modelu se podle `size_vram` vůči
   `size` klasifikuje jako `cpu`, `partial-gpu` nebo `gpu`. Chybějící či
   nejednoznačný model a chyba probe se uloží jako doložené `unknown`.

`/api/ps` dokládá Ollamou reportovanou aktuální alokaci/offload modelu po běhu,
nikoli průběh využití všech zařízení během celé inference. Živá GPU metrika je
samostatný okamžitý vzorek a historickou run evidence nedoplňuje ani nepřepisuje.

Frontend čte živé metriky průběžně i při zavřeném detailu: activity skupinu
CPU/GPU/síť po 2 sekundách a kapacitní RAM/VRAM/disk po 15 sekundách. Skrytá
karta ani neadministrátorský web probe nespouští. Dostupnost nakonfigurované
Ollamy se read-only ověřuje při náběhu, po dokončené aplikační interakci přes
debounce a nejpozději po 30 sekundách. Tyto intervaly jsou UI provozní policy,
nikoli součást historické evidence běhu.

Panel současně odvozuje spotřebu tokenů z providerem reportovaných hodnot již
uložených v úspěšných Ollama a OpenAI run journalech. Zobrazuje vstupní,
výstupní a celkový počet tokenů i pokrytí dokončených běhů. Běh bez úplné usage
evidence se započte do `unreported_runs`, ale jeho tokeny se neodhadují. Jde o
node-local součet modelových běhů, nikoli OpenAI účetní či billing metriku;
účetní report zůstává oddělený.

### Očekávání a vyhodnocení

Správce může pro přesné nakonfigurované binding ID a revizi uložit node-local očekávání
`unspecified`, `cpu` nebo `gpu`. Hodnota se atomicky ukládá mimo projektový Git
v souboru vlastněném aktuálním uživatelem s módem `0600`. Dispatch zachytí
přesnou revizi očekávání ještě před překročením transportní hranice a uloží ji
s runtime evidence. Odvozená immutable revize stejného bindingu pro explicitní
brainstormingový model očekávání zdědí; jiná konfigurační revize nikoli.
Pozdější změna policy historický běh nemění.

Při očekávání `gpu` a doloženém `cpu` vrací služba výrazné varování. Částečný
offload je zobrazen zvlášť a není vydáván za plný GPU režim. Neznámá evidence
zůstává neznámá; aplikace z ní neodvozuje shodu ani chybu hardware.

### Cíl, privacy a oprávnění

Runtime probe používá stávající stdlib HTTP/TLS transport a stejný validovaný
binding jako běh. `same-node` proto zůstává číselný loopback a
`private-network` používá přesný privátní endpoint, target ID a připnutý
certifikát. Probe nepřijímá URL z UI a nemůže změnit model, binding ani boundary.

Desktop má status a změnu očekávání jako důvěryhodnou lokální správu. Na
síťovém webu jsou živý systémový status a změna policy pouze pro administrátora.
Historická evidence konkrétního běhu je dostupná vlastníkovi vlákna po ověření,
že run ID patří do jeho dostupné konverzace. Do projektového Gitu se živé
metriky, policy ani run evidence nezapisují.

### Persistence a crash boundaries

Živý systémový vzorek se nepersistuje. První CPU a síťový dotaz pouze uloží
procesní čítač pro další delta vzorek; restart začne znovu explicitním
`awaiting-second-sample`.

Ollama odpověď se validuje před runtime probe. Probe je bounded a probíhá ještě
před atomickým přechodem runu z `dispatching` do `succeeded`; odpověď a evidence
se uloží v jedné SQLite transakci. Chyba probe uloží `unknown`, ale nezahodí
validní odpověď. Pád před dokončením ponechá existující fail-closed stav
`dispatching`/`unknown`; aplikace požadavek automaticky neopakuje. Opětovné
načtení již úspěšného runu neprovádí nový probe.

Atomická změna runtime policy používá dočasný soubor, `fsync`, `rename` a
`fsync` adresáře. Pád před `rename` zachová předchozí revizi, po `rename` je
nová revize autoritativní; osiřelý dočasný soubor se nepoužije jako nastavení.

Tokenový přehled se nepersistuje jako další autorita. Při náběhu, po aplikační
interakci a v kapacitním obnovovacím cyklu projde durable úspěšné řádky obou
providerových journalů a sestaví novou read-only projekci. Pád nebo restart
nemůže součty rozdělit či zdvojit; opakovaný výpočet nad jedním `run_id` jej
započte právě jednou. Neexistující journal se stavovým čtením nevytváří.

## Reuse a odmítnuté varianty

Reuse/adaptují se `OllamaBinding`, jeho ověření stejného uzlu či TLS pinu,
stdlib transport, `OllamaRuns`, node-local stavový adresář a existující panel
Zdroje. Linuxové `/proc`, `statvfs`, bounded `nvidia-smi` a oficiální Ollama
`/api/ps` postačují bez nové runtime závislosti.

Odmítá se nový monitoring daemon, `psutil`, persistování živých vzorků nebo
odvozených tokenových součtů,
odvozování runtime pouze z okamžitého GPU utilization, fuzzy shoda názvu modelu,
dotaz na jiný endpoint, automatický restart Ollamy, přepnutí bindingu, fallback
na jiný backend a retry `unknown` běhu.

## Důsledky a omezení

Systémová telemetrie v prvním řezu pokrývá Linux a NVIDIA nástroje dostupné na
workspace uzlu. U vzdálené Ollamy popisují CPU/RAM/GPU řádky stále lokální
workspace uzel; vzdálený runtime dokládá pouze `/api/ps` evidence z přesného
Ollama endpointu. AMD/Intel GPU, historické grafy, alerting a obecný fleet
monitoring nejsou součástí tohoto rozhodnutí.

Současný HTTP server obsluhuje stream a monitorovací požadavky sekvenčně, takže
živý monitor může během dlouhé streamované odpovědi čekat. Omezená souběžnost
je samostatný navazující úkol `OPS-WEB-CONCURRENCY-01`; jeho návrh drží
[ADR 0050](0050-bounded-http-monitor-concurrency.md). Toto rozhodnutí ji bez
samostatné implementace zápisové serializace nezavádí.
