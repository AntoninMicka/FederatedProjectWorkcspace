<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# MON-08 — akceptace a závěrečné review, 16. 11. 2026

## Aktuální lidská akceptace — 16. 11. 2026

Tato aktualizace nahrazuje závěry o otevřených úkolech v historickém auditu
níže; zachovává jeho tehdejší důkazy a omezení. Aktuální plán zůstává pouze
ve Workspace, tento dokument je podkladem review implementace.

Nativní readback projektu `c898b941-8eb0-4406-8dad-6e2b96c06d59` na HEAD
`69750667c388ef99009ba35feccab0a61be0261d` vrátil platný plán (`ready`),
MON-08 i MON-08-01..12 jako `completed`. Uživatel přijal UI, generování,
řetězení a následně opravu neúplných období. Migraci výslovně nepožaduje;
X/Twitter přijal v rozsahu připravené implementace PoC bez ověření API.
Záznam nemění autoritativní úkoly ani stav MON-05.

Výsledné chování doplňují [řetězení zpráv](monitoring-report-chains.md),
[ochrana a ruční opakování](report-protection.md),
[sdílená aktivace a výsledky](monitoring-shared-state.md) a
[agregované GUI](monitoring-entity-workspaces.md). Chybějící vydání zdroje
neblokuje syntézu dostupných podkladů; výstup i evidence přiznávají mezery.
Hodinová ochrana začíná skutečným sestavením, povoluje jediné přegenerování
na svém konci a do té doby blokuje vydání. Ruční opakování po ochraně
probíhá místně; návrhy i chyby se přenášejí.

Akceptace není důkazem produkční připravenosti [X PoC](x-connector-poc.md),
placeného readu, fyzického výpadkového scénáře ani komplexního předávání
práce mezi uzly. Tyto rozsahy nejsou výsledkem lokálních regresních testů.

### Rozsah větve pro review

Zdrojová větev `feature/x-twitter-poc` obsahuje celý navazující vývoj
monitoringu, nejen X konektor: proti ověřenému vzdálenému `develop`
`2b563fb61303516f7bbaa0226e4a394686638423` jde před těmito závěrečnými
opravami o 82 commitů a 275 souborů. Poslední uložený source HEAD je
`d0ef4668e4039865be36e7c28730011b26861f67`. Závěrečné lokální opravy
popsané níže ještě vyžadují commit; toto review není push ani otevřený PR.

- Sběr RSS/Atom, normalizované konektory, filtry a retence, deduplikované
  pooly, propojené definice a výsledky se samostatnými identitami.
- Vydané zprávy připnuté podle ID zpracování, kontext modelu, provenience,
  opravy, upozornění na neúplnost a možné zastarání.
- Oddělené GUI částí a tabulkový agregát; zprávy, export a návazné prezentace.
- Sdílená aktivace, přenos návrhů a chyb, redundantní RSS a místní ruční běh.
- Související opravy omezeného HTTP souběhu, SQLite a Git vlastnictví,
  validace historie synchronizace, diagnostiky, IDE fronty a LLM timeoutů.
- Místní X/Twitter PoC s explicitním ručním placeným sběrem; skutečný účet,
  placené API a produkční provoz zůstávají neověřené.

### Integrační opravy při závěrečném ověření

- Registr HTTP vlastnictví nyní klasifikuje všech pět X cest. Chybějící
  záznamy před opravou blokovaly start webového serveru. Správa místního X
  stavu má serializovanou linku; placený sběr existující monitoring execution.
  Podrobnosti a zachované recovery jsou v [X PoC](x-connector-poc.md#integrace-http-před-předáním-pr--16-11-2026).
- Test nezávislosti HTTP linek respektuje existující přesun RSS sync do
  `catalog_transfer`; nově zkouší také izolaci místní správy X.
- Test katalogu konektorů nyní zahrnuje `x-twitter`, jeho provider cursor
  a nenakonfigurovaný stav bez implicitního placeného readu.
- Tiskový export formulářů zahrnuje také tři nové X formuláře; inventura
  tak opět pokrývá všechny aktuální formuláře sdíleného UI.
- Izolované UI testy výstupů mají doplněný DOM panel evidence a jeho
  renderovací závislost, aby dál ověřovaly připnuté vytvoření prezentace
  a rozlišení nevydaného návrhu po rozšíření detailu zprávy.
- Grafický test menu předává velkou UI fixture přes stdin. Předchozí
  `python -c` překročil limit délky jednoho argumentu; kontrolované chování
  menu ani aplikační kód se tím nemění.

### Závěrečné lokální ověření

Po poslední relevantní změně kódu a testů:

```sh
python3 -m unittest discover -s tests -v
```

**2 230 testů, OK (skipped=60), 1 542,083 s**, návratový kód 0.
Provedeno na Linuxu s Pythonem 3.14.4. Přeskočené případy zahrnují opt-in
Qt/WebEngine, privátní vstupní vzorek, nativní libgit2, izolaci namespaces,
ARM64 Julia runtime, Debian runtime, živé Ollama a volitelný QR decoder;
nejde o jejich úspěšné ověření. CI běh na Pythonu 3.11 zde nebyl spuštěn.

Navíc finální cílený grafický běh s `M0_DESKTOP_TEST=1`: **5 testů OK,
31,582 s** — `test_monitoring_blocks_browser`, `test_report_reprocess_browser`,
`test_rss_subscription_sync_browser`, `test_rss_sources_browser` a
`test_sidebar_menu_browser`. Ověřují skutečný Qt/WebEngine nad izolovanými
projekty a řízenými transporty, nikoliv fyzické uzly nebo živý model.

`node --check extensions/workspace-bridge/bridge.js`, lokální odkazy review
a `git diff --check` prošly. Inventura CI sharding skriptu zahrnuje všech
205 top-level modulů právě jednou ve čtyřech shardech; nejde o nové spuštění
shardů. Samostatný build/lint není nakonfigurovaný.

Opravy X HTTP registrace a formulářového exportu a úpravy testovacích
fixtures jsou v lokálním diffu nad `d0ef466`. Testy nezpůsobily aktivaci X,
placené volání ani nasazení na živé uzly. Vzdálený `develop` při závěrečné
kontrole stále odpovídal `2b563fb61303516f7bbaa0226e4a394686638423`.
Připraveno k uživatelskému review a následnému commitu/push/PR; tyto kroky
nebyly v tomto předání provedeny.

## Historický audit — 12. 11. 2026

Následující záznamy zachovávají tehdejší stav. Aktuální akceptace je výše.

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

### Funkční ladění LLM návrhů podle zdroje

Navazující zadání uživatele přidává
[kalibraci návrhů filtrů a sestav](monitoring-design-calibration.md).
Výchozí source HEAD tohoto řezu: `4ec4279`. Závěrečný readback bridge je
opět `stale=false` (synchronizace `2026-11-12T09:11:40.295Z`); projekt,
repository a exportní revize uvedené v úvodu jsou beze změny. Starší záznam
odpojení výše popisuje tehdejší stav, nikoli tento readback.

Návrh používá zvolené skutečné RSS položky, dostupné kategorie a omezené
texty odkazovaných stránek. Review samostatně zkouší původním enginem nové
i převzaté filtry, přiznává prázdné/nesamplované vstupy a neposkytuje
automatickou záruku pro jiné kanály stejné redakce. Samostatný návrh filtru
nemusí vytvářet komplexní úlohu. Source/model intent, manifest, CAS a
recovery zůstávají původní; scope neaktivuje sběr ani nevkládá ukázky do poolu.

Finální cílená regrese: `test_monitoring_design_samples`, `test_rss_pilot`,
`test_source_connectors`, `test_monitoring_filters`, `test_monitoring_blocks`,
`test_rss_monitoring`, `test_rss_sources`, `test_monitoring_http`,
`test_monitoring_polling`: **111 testů OK** (131,435 s). Zahrnují skutečný
pád procesu během vzorkování, odmítnutí dalšího GET při replay, Context
Manifest, původní filtrovací engine, změnu HEAD, local-only a prázdné vzorky.
Finální `M0_DESKTOP_TEST=1 tests.test_monitoring_blocks_browser`: **1 test OK**
(14,760 s), včetně výběru kanálu, odeslání návrhu, výsledků a uložení filtru.
Model a články byly v těchto regresích řízené transporty, nikoli živé LLM.

Samostatný read-only pokus skutečně načetl text článku ČT24 označeného
uživatelem; 8 000 znaků do návrhového výřezu, označeno jako zkrácené. To není
ověření jiných redakcí, historického archivu, modelové kvality ani živého syncu.
JavaScript prošel `node --check`, diff a lokální odkazy kontrolou.
Plná sada výše tuto novou změnu nepokrývá a nebyla opakována. Bez commitu,
nasazení nebo automatické změny akceptace Workspace úkolů.

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
