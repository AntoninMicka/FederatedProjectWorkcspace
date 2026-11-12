<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# MON-08 — podklady k dokončení a review, 12. 11. 2026

Audit důkazů a mezer, nikoli druhý plán či potvrzení dokončení.
Autoritou je Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
repository `https://github.com/AntoninMicka/FederatedProjectWorkcspace.git`.
Export načtený při zahájení: `stale=false`, synchronizace `2026-11-12T05:21:37.651Z`,
revize `eeb67f514d0d7177d25735dd56892c023555daf1ead1fbea2ac8acf469f9ff71`,
Workspace HEAD `15bbef2f157feff0bc87b82345c2e4a6cb500cb1`.
Výchozí source HEAD: `47de80b`, `feature/rss-direct-pilot`.
Výchozí export evidoval MON-08-01..06 jako completed a 07..12 jako in progress.
Uživatel požaduje dokončit tuto dávku; ostatní nálezy auditu souběhu odkládá
do oddělené dávky. Žádný úkol zde není automaticky akceptován.

Závěrečný readback: bridge hlásí `stale=true` a `ECONNREFUSED` při připojení
k místnímu backendu (12. 11. 2026, 06:39 UTC). Neexistuje novější platný
export stejného projektu. Výchozí revize proto zůstává podkladem zadaného
zásahu, nikoli důkazem aktuálního stavu akceptace. Zprávy completed ani
změny autoritativního plánu nebyly publikovány.

## Otevřené úkoly proti skutečným důkazům

| ID | Implementace / lokální důkaz | Hranice akceptace |
| --- | --- | --- |
| MON-08-07 | Redundantní místní RSS podle ADR 0082, processing s node UUID. Nový společný signed test odmítá LLM na nesprávném uzlu. | Fyzický běh Omnia/desktop neověřen. Vzdálený dispatch z ADR 0080 byl odložen. |
| MON-08-08 | Signed sync přenáší definice, pool a vydanou zprávu. Replay konverguje bez aktivace sběru/modelu a bez provozního journalu. | Živý přenos aktuálního kódu na obou skutečných uzlech je samostatný důkaz. |
| MON-08-09 | [Samostatná GUI a agregát](monitoring-entity-workspaces.md), [kalendář](monitoring-processing-calendar.md), skutečné Qt/WebEngine scénáře, výstupy ze sdíleného Gitu. | Chybí ruční akceptace. Rozvrh neznamená měsíční/roční syntézu vydaných zpráv v blokovém formuláři. |
| MON-08-10 | Frozen preview, odmítnutí změněného náhledu, operation ID/receipt, retirement a nezapnuté nové bloky; browser ověřuje servisní API i aktuální katalog. | Migrační panel byl výslovně odstraněn a nevrací se. Živá data nebyla převáděna. |
| MON-08-11 | [Posouzení X API a návrh odděleného řezu](x-connector-review.md). Konektor zůstává unavailable bez fallbacku. | Designed; účet, oprávnění, budget a API PoC neověřeny. Bez účtovaného volání. |
| MON-08-12 | Nový test RSS → pool → oprávněný LLM → review → vydání → signed sync → výstup bez lokálního run journalu. Původní testy pokrývají analytické syntézy a opravy. | Není to fyzický řetězec ani úplnost aktuálního UI pro převzaté scénáře MON-05. Dávka není akceptovaná. |

Test přiřazení používá pevného vykonavatele. Neprokazuje bezpečné převzetí
LLM účinku po změně přiřazení mezi uzly, pokud původní uzel uchovává unknown.
Interní journal ADR 0080 není zapojený vzdálený execution protokol; pouhá
volba jiného node UUID tuto část MON-08-07 nedokončuje.

## Převzaté požadavky MON-05 a mezery

MON-05 zůstává failed. Tvrzení o vyřešení náhradním úkolem vyžaduje lidskou
akceptaci MON-08-12, nikoli samotné úspěšné testy.

- Definice, pravidla, privacy a místní souhlas: `test_monitoring_definitions`,
  `test_monitoring_filters`, `test_monitoring_blocks`, `test_monitoring_placement`.
- Unknown, restart, opakovaný tick a jedno vydání: `test_monitoring_blocks`,
  `test_monitoring_synthesis`, `test_monitoring_migration`, `test_reporting_scheduler`.
- Analytické zprávy, cutoff, pozdní informace, stagnace/regrese, změna metodiky,
  rozpory a rozpracované případy: `test_monitoring`, `test_synthesis_analysis`,
  `test_synthesis_federation`. Jsou to důkazy nativních API, nikoli dostupnosti
  celého postupu z aktuálního blokového GUI.
- Vydaná zpráva a Markdown export: `test_report_outputs`, `test_report_outputs_ui`,
  `test_monitoring_http`. Nový
  `PoolSyncTests.test_collector_to_assigned_model_and_published_output_roundtrip`
  dokládá vzdálený výstup bez kopie provozního journalu.
- Aktuální processing formulář vybírá pooly a hledání. Nepřipojuje jinou
  vydanou zprávu do měsíční/roční analytické syntézy. Testy staršího
  WatchSynthesis tuto mezeru aktuálního GUI neodstraňují.
- [Prezentace z vydané zprávy](report-output-presentations.md) nyní má
  samostatně potvrzenou akci nad aktuálním výstupem, source pin, zpětné
  odkazy a projekci zastarání bez přepsání původního decku. Native testy
  zahrnují skutečné pády procesu a signed přenos. Ruční akceptace této
  převzaté části MON-05 zůstává oddělená.

## Závěrečné ověření lokálního zdroje

Úplná současná sada: **2 120 testů, OK, 58 skipped**. Čtyři izolované kopie
obsahovaly stejné finální zdroje jako aktivní checkout, ověřené SHA-256 všech
679 souborů. Běžel původní CI runner `scripts/test_shards.py`; všech 192
top-level testovacích modulů patřilo právě do jednoho shardu, bez vynechání.
Nešlo o vzdálený CI běh ani změnu aktivní vývojové větve.

| Shard | Moduly | Testy | Skip | Čas |
| --- | ---: | ---: | ---: | ---: |
| 1 | 47 | 528 | 15 | 300,699 s |
| 2 | 48 | 514 | 14 | 374,831 s |
| 3 | 48 | 520 | 16 | 500,910 s |
| 4 | 49 | 558 | 13 | 437,675 s |

Samostatná brána `M0_DESKTOP_TEST=1`: čtyři skutečné Qt/WebEngine scénáře,
**4 testy OK**, 24,360 s. Ověřily aktuální katalogy a pool, oddělené editory,
tabulkový agregát, práci se sdílenými položkami, počty příjmu, vydání zprávy,
prezentaci a zpětný odkaz, týdenní formulář, servisní migraci a RSS reader.
Nešlo o běžný uživatelský profil. HTML tiskový review pack má 45 listů a
39 formulářů; komplexní úloha nemá formulář bloku. PDF render nebyl ověřen.

JavaScript prošel `node --check`, Python soubory syntaktickou kontrolou,
lokální odkazy a finální diff včetně nových souborů kontrolou whitespace.
Po testech se mění pouze tento záznam výsledků; kód, testy a konfigurace
zůstávají shodné s ověřenými kopiemi.

Do závěrečné regrese patří i aktualizace dvou starých očekávání po P1:
samotná HTTP writer admission již neblokuje čisté čtení dashboardu/dokumentu.
Autentizace a původní serializace skutečných zápisů zůstávají testované.

### Následná oprava nezávislého načítání kanálu

Podle upřesnění uživatele 12. 11. byly odstraněny blokace příjmu po změně
filtru/poolu. Aktivovaný kanál načítá vlastní interval i bez filtrů;
změna výběru vynutí celé tělo při příští splatné kontrole, ne novou aktivaci.
Zdrojová aktivace, privacy, unknown recovery a původní transakce zůstávají.
`python3 -m unittest tests.test_monitoring_blocks tests.test_message_pool_sync -v`:
**36 testů OK**. Zahrnují restart dříve blokovaného kanálu, nové filtry nad
nezměněným ETag, přidání/odebrání filtru, příjem bez filtrů, pády a signed sync.
Celá sada 2 120 testů výše předchází této opravě a nedokládá její úplnou
regresi; plná závěrečná brána se zopakuje před finálním předáním dávky.
Oprava nebyla nasazena na Omnii a nenahrazuje diagnostiku živého sběru/syncu.

## Fyzické ověření a delivery

Read-only pokus na uloženém SSH cíli skončil odmítnutím autentizace. Trust,
credentials, granty ani živé služby se neměnily. Je vyžádán funkční SSH alias
nebo účet, nikoli heslo či klíč v konverzaci. Před izolovaným PoC ověřit
skutečné identity, revize a mapování obou uzlů podle
[runbooku](monitoring-placement-poc.md), s upřesněním redundantního RSS v ADR 0082.
Synthetic model ani veřejný RSS pilot nejsou akceptací živého LLM řetězce.

Pool TTL nevymazává staré feedy z Git historie ani všechny transportní zálohy.
Vzdálený provoz není opravený jen podle lokálního zdroje. Tato práce neprovádí
commit, push, merge, deployment ani automatické uzavření úkolů.
