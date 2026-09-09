# TODO — operativní práce

Aktuální milník: **M0 — Architecture spike**, Gate M0 je otevřený. Strategii a gates drží [master roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>); návrhová rozhodnutí drží [ADR 0001](docs/adr/0001-m0-baseline.md), [ADR 0002](docs/adr/0002-metadata-journal.md) a [ADR 0003](docs/adr/0003-coordinated-operation.md). Tento soubor je průběžný operativní stav, ne další roadmapa.

Stavy: `[ ] [planned]`, `[ ] [in progress]`, `[x] [completed]`, `[ ] [blocked]`. Úroveň výsledku je samostatná: designed / implemented / PoC validated / production-ready. Žádná aplikační část zatím není označena production-ready. Následující úkoly nejsou zahájené ani prokazatelně blokované jen kvůli svým závislostem.

## Nejbližší úkol M0

**M0-06 — Doplnit podklady pro finální volbu stacku a desktopového balení.** Review M0-09 je dokončené s výsledkem „Gate M0 nesplněn“. Další konkrétní krok: posoudit desktopový binding a způsob distribuce včetně závislostí/licencí a chybějících měření startu/paměti. Uživatel již úspěšně provedl ruční deploy a storage demo na Omnii; M0-05 zbývá doplnit měřením a ověřením filesystemu pracovních dat. Přechod do M1 zatím není schválen.

## Další zbývající práce M0

- [ ] **[planned] M0-05 — Ověřit cílové prostředí Turris Omnia/LXC.** Uživatel doložil Turris Omnia / TurrisOS 9.1.1 / ARMv7, LXC 6.0.5 a běžící Debian 13 Trixie kontejner na SSD (Btrfs). Uživatel následně doložil úspěšnou instalaci PyYAML 6.0.3, běh storage dema, Git commit, čtení indexu po znovuotevření a přepnutí current. Opakovaný uživatelský běh: 0,66 s pro celé demo, RUSAGE_CHILDREN.ru_maxrss 11 520 KiB (11,25 MiB), exit 0. Jde o jediné orientační měření, nikoli čas startu služby nebo součet paměti procesů. Demo pracovalo v /tmp; chybí výstup df pro ověření filesystemu pracovního projektu/journalu a jejich provozu na SSD. Zbývá změřit start, paměť, instalaci a provoz srovnávaných variant, včetně omezení journalu (Linux, lokální souborový systém, společný filesystem pro stav a projekt). Běh aarch64 na vývojovém hostu není tento důkaz.
- [ ] **[planned] M0-06 — Uzavřít backendový stack a desktopový obal.** Linux je první navržený desktopový cíl; zbývá balení, životní cyklus backendu a ověření Qt/WebView se sdíleným UI. Výchozí jeden proces zachovat; hybrid C++/Python přijmout jen s doloženým přínosem a náklady IPC, diagnostiky, obnovy a aktualizací. M0-06a ověřuje pouze desktopový PoC dle ADR 0007; finální rozhodnutí stále potřebuje M0-05 a distribuční/licenční posouzení.

## Gate review M0-09 — 2026-09-09

Historické posouzení před následným ručním deployem; novější důkaz je uveden u M0-05 a v dokončených výstupech. Rozhodnutí o gate zatím nebylo změněno.

Posouzený HEAD: `1c7b228`, vstupní pracovní strom čistý. Výsledek: **Gate M0 nesplněn; M1 nezahajovat automaticky.** Review je dokončené, schválení gate nikoli. Nezavádí se nové architektonické rozhodnutí ani změna priorit nasazení.

| Kritérium | Důkaz a úroveň | Závěr |
| --- | --- | --- |
| Autoritativní data a obnova indexu | ADR 0002–0004, metadata/configuration/storage a jejich testy; designed + PoC validated | Splněno pro rozsah M0; integrace konfigurace a úplnější projekce zbývají V-03/V-08. |
| Koordinovaná obnova zápisu | ADR 0003 a tests/test_workspace.py: crash boundaries, CAS, pending stav, dva zapisovatelé | Splněno pro řízený Linux PoC; ne důkaz produkčního hardeningu nebo výpadku napájení. |
| Bezpečné lokální API a desktopové propojení | ADR 0006/0007, tests/test_local_api.py a tests/test_desktop.py | Návrh a PoC splněny; persistentní operace a nedůvěryhodný obsah zbývají V-10. |
| Konflikty entity a obsah/sidecar | M0-07, tests/test_merge_scenarios.py a FEDERATION | PoC splněno včetně sémanticky neplatného čistého merge; conflict UI a síťová federace nejsou implementované. |
| Orchestrace bez LLM, role, manifest, execution boundaries | ADR 0008 a návrhová tabulka scénářů | Designed splněno; LLM/RBAC implementace se neprohlašuje za hotovou. |
| Finální stack a distribuční cesta | ADR 0005 volí Git CLI; ADR 0007 pouze PoC binding; M0-06b zdrojový archiv | **Nesplněno:** finální backendový stack/binding a distribuční posouzení M0-06 zůstávají otevřené. |
| Cílové prostředí a provozní měření | M0-05 doložený LXC bez běhu aplikace; desktopové testy na vývojovém hostu | **Nesplněno:** měření na Omnia/ARMv7 a úplné posouzení startu, paměti a instalace cílových variant. |

Uživatel následně potvrdil úspěch ruční akceptace desktopu: kliknutí, zavření a restart fungují. Současné UI obsahuje jen paměťový čítač; nelze v něm ještě otevřít projekt, uložit artefakt ani ověřit zachování projektových dat po restartu. Ruční akceptace: třikrát „Ověřit spojení“ → 1/2/3, zavření → návrat terminálu, nový `./run.sh desktop` → 0 a opět funkční tlačítko. Výsledek je uživatelské potvrzení, nikoli nový automatický test.

Evidence testů je převzatá z dokončených úkolů níže (poslední plná sada u M0-07), nikoli nový běh v tomto review. Zkontrolovány současné zdroje UI, pokrytí testů, návaznost ADR a gate. Dokumentační ověření: lokální odkazy a finální diff. Po doplnění M0-05/M0-06 zopakovat rozhodnutí o gate s novými důkazy; dnešní negativní výsledek zachovat jako historii. Samotné potvrzení čítače gate neuzavře.

## Zjištěné mezery a navazující ověření

- [ ] **[planned] V-01 — Regresní test pro validátor CLI.** ADR 0002 zaznamenává ruční smoke test exit 0/1; CLI zatím nemá vlastní automatický test. Doplnit platnou projekci, osiřelý sidecar, chybějící cestu a jasně vymezit, že se nekontroluje project.json.
- [ ] **[planned] V-03 — Vyjasnit omezení projekce indexu.** Index nyní validuje vztahy, ale ukládá pouze id/title a commit ID. Před relačními dotazy navrhnout a otestovat rozšíření projekce; neoznačovat existující index za kompletní databázi vztahů.
- [ ] **[planned] V-04 — Sjednotit přesný kontrakt metadat.** DATA_MODEL uvádí u registrů status/body/relations, implementace vyžaduje status/body a relations ponechává volitelné. Upřesnit znění nebo rozhodnout o změně schématu; nic tiše nezpřísňovat. Dále rozhodnout o datu importu a podrobném manifestu provenance, které roadmapa požaduje, ale současné schéma nepodporuje.
- [ ] **[planned] V-05 — Vymezit neměnnost zdrojů při následných úpravách.** Import zachovává bajty a je testovaný. Journal ale obecně přijímá změnu obsahu i provenance; nevynucuje celoživotní neměnnost zdroje. Zaznamenat pravidla aktualizace/verzí a doplnit odpovídající validaci až v implementačním úkolu.
- [ ] **[planned] V-06 — Produkční ochrany před nasazením.** Statické kontroly cest nejsou ochrana před závodícími FS změnami; současný zámek vyžaduje kooperující procesy. Zvlášť prověřit práva existujícího stavového adresáře, cizí Git konfigurace/filtry, povolené transporty a čtení při pending stavu. Nezaměňovat test pádu procesu za výpadek napájení ani host testy za podporu Windows.
- [ ] [planned] **V-07 — Provozní životní cyklus operation receipts (cílová úroveň: implemented).** Před produkčním balením určit retenci dokončených záznamů a bezpečný úklid osiřelých staging adresářů/commit objektů po pádu uvnitř přípravy kandidáta. Pending journal a kandidátní commit se nesmějí odstranit. Doplnit testy přerušení Git podprocesů a postup řešení jejich zbylých lock souborů; současné checkpointy leží mezi voláními.
- [ ] [planned] **V-08 — Aplikační integrace konfigurace (cílová úroveň: implemented).** Navázat na schéma v1 z M0-02: při otevření projektu ověřit project_id registrace, existenci a bezpečné umístění kořenů/stavu, podporovanou verzi a vazbu identity na credential úložiště. Navrhnout bezpečnou inicializaci a serializovaný zápis project.json přes Workspace a oddělený obnovitelný zápis node.json, včetně budoucích explicitních migrací. Před změnou popsat crash boundaries; současný samostatný validátor nic nezapisuje a storage projekce konfiguraci nečte.
- [ ] [planned] **V-09 — Produkční Git transport a credentials (cílová úroveň: PoC validated).** Nad výchozím Git CLI ověřit TLS certifikáty, SSH host keys, zvolený credential store/helper, odmítnutí odvolaných credentials, timeout/cancel a restart přenosu. Loopback HTTP Basic test M0-03 ověřuje správné/chybné credentials, nikoli bezpečný internetový transport nebo federované RBAC. Vazba na V-06, cílové balení a M5.
- [ ] **[planned] R-01 — Posoudit zdrojové komponenty pro reuse (cílová úroveň: designed).** Před převzetím ověřit původ/licenci souborů, úplné závislosti, testy a kompatibilitu. Lokální inventura a její zbývající rozsah patří výhradně do volitelného soukromého katalogu; veřejné kandidáty evidovat v REUSE_CATALOG až po ověření veřejné dostupnosti.

- [ ] [planned] **V-10 — Integrace lokálního API (cílová úroveň: PoC validated).** Qt/WebEngine, same-origin UI a token v nativním interceptoru jsou ověřeny M0-06a. Zbývá lifecycle po násilném pádu, případný úklid Unix socketů a bezpečné vykreslení nedůvěryhodných artefaktů. Před persistentními mutacemi v M1 definovat klientské operation ID/retry/receipt podle ADR 0003, limity souběhu a celkový deadline requestu. Protokolový čítač ADR 0006 toto neprokazuje.

## Pozdější operativní backlog — nezahajovat místo M0

Přeneseno z původní sekce 19 roadmapy; nejde o rozšíření aktuálního úkolu. Milníky a gates zůstávají v roadmapě.

- [ ] **[planned] M1 — Aplikační základ:** vytvořit LXC development deployment, desktopový launcher/balení, persistentní identitu a úložiště uzlu; implementovat Project/Artifact služby a Git službu adaptací ověřených PoC. Po volbě stacku doplnit frontend, Markdown editor/viewer a Git history UI. Produkční integrace metadat/indexu zůstává otevřená, jejich PoC se neopakuje.
- [ ] **[planned] M2 — Lokální AI:** Ollama adapter, auto-summary/description a Context Builder PoC dle ADR 0008: manifest přesných bajtů, revalidace před odesláním, zákaz implicitního fallbacku a recovery unknown běhů.
- [ ] **[planned] M3/M4 — Role a backendy:** implementovat Role/Backend modely a testy autorizace/execution boundaries dle ADR 0008 a následné předávání artefaktů mezi rolemi.

- [ ] [planned] **M3-UB-01 — Usage & billing backendů (cílová úroveň: implemented).** Navázat na sekci 7C roadmapy a Backend adapter: u vybraných backendů ověřit podporovaná rozhraní a potřebná oprávnění pro usage a billing samostatně, doplnit načítání a UI indikaci. Rozlišit údaje běhu/workspace a celého účtu, skutečné hodnoty a odhady, období, jednotky/měnu a stáří. Před implementací určit kontrakt, obnovování/cache a přístup k účetním údajům; dostupnost konkrétních provider API je zatím neověřená. Akceptace: scénáře obě capabilities / pouze usage / žádná podpora, nula vs. chybějící údaj, odmítnuté oprávnění, timeout/rate limit a zastaralá data; účetní souhrn se nezpřístupní běžnému uživateli backendu a výpadek přehledu nezmění jeho routing ani cost policy. Priorita M0 se nemění.

- [ ] [planned] **M5 — Federovaná publikace (cílová úroveň: PoC validated).** Implementovat izolovaný příjem, autorizaci celého přenášeného obsahu včetně historie, validaci kandidáta a CAS/recovery dle ADR 0008. Ověřit změnu HEAD po lidském řešení, neplatný fast-forward/merge, revokaci a odmítnutí přenosu local-only historie; zachovat konfliktní rodiče.

## Import externích dat — navazuje na aplikační import M1

Strategický rozsah drží sekce 3C master roadmapy; tyto úkoly nemění prioritu desktopového PoC.

- [ ] [planned] **IMP-01 — Google Drive import (cílová úroveň: implemented).** Ověřit OAuth scopes a výběr souborů, download/export podle typu a limity; navázat na aplikační import a V-04/V-05. Akceptace: binární soubor i nativní Google dokument, provenance exportu, duplicita/nová revize, odvolané oprávnění, rate limit a přerušený přenos bez částečného publikování do projektu. Před zápisy popsat crash boundaries podle ADR 0003.
- [ ] [planned] **IMP-02 — NotebookLM import (cílová úroveň: PoC validated).** Určit edici účtu a ověřit dostupné oficiální exporty/API zvlášť pro zdroje, poznámky, generované výstupy a chat. Enterprise preview nepovažovat za obecné API osobního účtu. Akceptace: uživatelem poskytnutý vzorek, zachované dostupné citace/provenance, jasný seznam neimportovatelných částí a funkční souborový fallback tam, kde export existuje. Nezavádět automaticky placenou Enterprise závislost.
- [ ] [planned] **IMP-03 — Import exportů konverzací (cílová úroveň: implemented).** Získat uživatelem schválené anonymizované vzorky ChatGPT a Gemini/Takeout, ověřit skutečnou strukturu a vytvořit lokální import s náhledem. Akceptace: role/pořadí/větvení podle dostupnosti, chybějící metadata, přílohy, opakovaný import a poškozený archiv; omezit velikost i rozbalení archivu, odmítnout traversal/symlinky a nevykonávat importované HTML. Generační API není předpokládaným zdrojem historie webového účtu.

## Podpůrné IP / release integrace — nepřebírají prioritu M0

Podrobnou administrativu, screening a crowdfundingové checklisty drží [IP roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>) a její registry. Níže jsou pouze konkrétní integrace do repozitáře; žádná publikační automatizace zatím neexistuje.

- [ ] [planned] **IP-01 — Release a citation metadata (cílová úroveň: implemented).** Před prvním publikačním releasem určit archiv a ověřené autory, licenci, repository URL a verzi; doplnit CITATION.cff a/nebo metadata zvoleného archivu. Akceptace: metadata odkazují na konkrétní disclosure, tag a commit, neobsahují vymyšlené identifikátory a projdou validací zvoleného formátu.
- [ ] [planned] **IP-02 — Archive/release workflow a DOI integrace (cílová úroveň: implemented).** Po určení archivu z IP-01 připravit kontrolu verzí a referencí, následně automatizaci podle sekce 29 IP roadmapy. Akceptace: kontrola odmítne nesoulad tag/commit/disclosure; případné DOI je propojeno obousměrně. Samotné vytvoření tohoto úkolu nepublikuje release ani DOI.
- [ ] [planned] **IP-03 — Propojit financovaný scope s produktovými milníky (cílová úroveň: designed).** Při přípravě kampaně přiřadit schválené balíčky ke stávajícím M1–M6 a určit zařazení Open WebUI integrace; odlišit hotové, financované a budoucí schopnosti. Akceptace: jeden konzistentní rozsah s rozpočtem a readiness review podle IP roadmapy, desktopový základ zůstává M1. Kampaň ani její spuštění tím nejsou schválené.

## Dokončené výstupy a důkazy

- [x] [completed] **PoC validated — ruční deploy a storage demo na Omnii.** Uživatelem dodaný výstup potvrzuje instalaci PyYAML 6.0.3, vytvoření artefaktu a Git historie, index po znovuotevření, úklid dočasných dat a hlášku úspěšné instalace do current. Daemon se nespustil. Jde o úspěšný smoke běh, nikoli celou testovou sadu nebo recovery na cílovém zařízení. Následné orientační měření uživatele: celé demo 0,66 s, max RSS potomků 11 520 KiB, exit 0; podrobnosti a omezení u M0-05. Demo mělo pracovní data v /tmp; umístění těchto dat na SSD není tímto výstupem prokázáno. Zbývající ověření drží M0-05; desktopové připojení k serveru zatím neexistuje.

- [x] [completed] **M0-09 — Designed: Gate review před M1.** Kritéria, podklady a negativní rozhodnutí jsou v sekci Gate review výše. M0-05/M0-06 zůstávají otevřené; dokončení review neznamená splnění gate. Bez nového běhu testů a bez vzdáleného nasazení.

- [x] [completed] **M0-08 — Designed: kontrakty a pravidla publikace.** [ADR 0008](docs/adr/0008-context-and-publication-contracts.md) vymezuje Backend/Role/Context Manifest, přesné vstupy a cíl, autorizaci před odesláním, fallback, nejistý výsledek síťového volání a CAS publikaci při změně HEAD. Návrhové review scénářů zahrnuje uzel bez LLM, Ollamu, cloud, peer, local-only i zakázaný obsah v Git historii. Ověřena konzistence s ADR 0003/0004, roadmapou a odkazy; čistě dokumentační změna bez nového běhu testů. Implementace a akceptační scénáře navazují v M1–M5/V-10 a M3-UB-01; Gate M0 zůstává otevřený.

- [x] [completed] **M0-07 — PoC validated: zbývající merge scénáře.** `tests/test_merge_scenarios.py` ověřuje modify/delete s abortem a obnovou úplného páru obsah/sidecar, rename/edit s přesnými bajty a metadaty a textově čistý merge dvou validních větví s dangling relation. Validace kandidáta odmítne publikaci; úmyslně neplatný commit v negativním testu nenahradí index a čtení odmítne stale stav. Ověřena lidská oprava a rodiče merge; scénáře a limity jsou ve FEDERATION. Produkční synchronizace ani conflict UI nevznikají. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 66 testů prošlo bez skipů. Ověřeny lokální odkazy a finální diff.
- [x] [completed] **V-02 — PoC validated: přesný důvod odmítnutí duplicity indexem.** Existující test ve `tests/test_storage.py` nyní vytváří platnou Markdown entitu se stejným ID jako registr a vyžaduje chybu Duplicate ID; zachování indexu a odmítnutí stale čtení zůstává ověřeno. Původní nesoulad názvu JSON souboru již výsledek nezastíní.

- [x] [completed] **M0-06b — Implemented: reprodukovatelný zdrojový desktopový balíček.** `run.sh package-desktop` vytváří allowlistovaný tar.gz s manifestem SHA256, bez privátního katalogu, prostředí a binárních závislostí. Atomické zveřejnění kompletního souboru bez přepsání existujícího vydání; ověření rozbalené kopie je součástí grafických testů. Systémový runtime stále vyžaduje Python/Qt/PyYAML; finální binding, distribuční licence, instalační balík a M0-05 zůstávají otevřené. Závěrečná sada `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 63 testů prošlo bez skipů, včetně skutečného WebEngine z rozbaleného archivu mimo checkout. Bash syntax, lokální odkazy, finální diff a sestavení archivu ověřeny.

- [x] [completed] **Implemented — ruční deploy headless PoC na Omnii.** `run.sh deploy-omnia` poskytuje dry-run a explicitní SSH nasazení do běžícího Debian LXC na SSD, omezený archiv zdrojů, oddělená vydání a přepnutí current až po demu. Lokální testy ověřují obsah archivu, validaci vstupů, chyby SSH a zachování previous/current po chybě instalace. Závěrečná sada s `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1`: 60 testů prošlo bez skipů; bash syntax, dry-run, odkazy a diff ověřeny. Vzdálený deploy nebyl spuštěn; uživatel jej provede ručně, M0-05 zůstává otevřené.

- [x] [completed] **Designed — rozsah importu Drive, NotebookLM a konverzací.** Doplněna sekce 3C roadmapy a IMP-01 až IMP-03. Ověřeny oficiální podklady k dílčím API/exportům, lokální odkazy a diff. Konektory, autentizace ani parsery exportů nejsou implementované; žádná uživatelská cloudová data nebyla načtena.

- [x] [completed] **M0-06a — PoC validated: spustitelné desktopové okno.** `./run.sh desktop`, `spikes/desktop.py` a `desktop_ui.py` adaptují existující lokální API; Qt okno používá stejný Python proces s backendovým vláknem, token pouze v nativní části a off-the-record WebEngine. Skutečné UI/JS kliknutí ověřuje autentizované API a zavření backendu; nový start resetuje čítač. [ADR 0007](docs/adr/0007-desktop-poc.md) vymezuje změnu pořadí na žádost uživatele a otevřené produkční balení/licence i M0-05. Závěrečné `M0_DESKTOP_TEST=1 M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 56 testů prošlo bez skipů. Ověřeno vykreslené okno ze screenshotu, `bash -n run.sh`, help/chybné argumenty a skutečný launcher z /tmp včetně SIGTERM. Kontrola odkazů, soukromých údajů a diffu dokončena.

- [x] [completed] **M0-04 — PoC validated: lokální socket a loopback HTTP.** `spikes/local_api.py` a sedm testů v `tests/test_local_api.py` porovnávají stejný paměťový endpoint přes Unix socket a IPv4 loopback. Ověřeny token/rotace, Host/Origin, CSRF formáty/metody, UID/práva, limity/duplicity JSON a hlaviček, timeout a pipelining; odmítnuté požadavky nemění stav. [ADR 0006](docs/adr/0006-local-api-transport.md) preferuje same-origin loopback HTTP pro navazující UI, s Unix alternativou. Browser/obal, bootstrap tokenu a napojení Workspace zůstávají V-10. Závěrečné `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 53 testů prošlo bez skipů. Sandbox původně odmítl bind; běh s povolenými lokálními sockety uspěl. Dokumentace, odkazy a `git diff --check` ověřeny.

- [x] [completed] **R-00 — Implemented: oddělený veřejný a soukromý reuse katalog.** REUSE_CATALOG obsahuje technologie a komponenty workspace; seznam veřejných externích repozitářů je zatím prázdný. Lokální inventura je v `REUSE_CATALOG.private.md`, vyloučeném z Gitu. Ověřeny odkazy, absence soukromých detailů ve změněných veřejných dokumentech, ignore pravidlo a diff; bez nového běhu aplikačních testů. Detailní posouzení před převzetím zůstává R-01.

- [x] [completed] **M0-03 — PoC validated: Git CLI vs. C++/libgit2.** `spikes/libgit2/probe.cpp` sestaven s C++17 a `-Wall -Wextra -Werror` proti libgit2 1.9.1. `tests/test_git_comparison.py` spouští obě varianty nad stejnými scénáři commit/branch/clone/fetch, divergence/abort/merge, CAS a restart před/po publikaci, odmítnutí neplatné projekce a loopback HTTP autentizace. Finální `M0_LIBGIT2_PROBE=/tmp/m0-libgit2/probe M0_GIT_HTTP=1 python3 -m unittest discover -s tests -v`: 46 testů prošlo bez skipů. HTTP test vyžaduje povolený loopback socket; bez explicitních voleb jsou srovnávací testy skipped. [ADR 0005](docs/adr/0005-git-adapter-comparison.md) zachovává Git CLI jako výchozí adapter; libgit2 je ověřená alternativa, ne produkční náhrada Workspace. Zaznamenány build/runtime závislosti a orientační velikosti/start; cílové balení M0-05/M0-06 a produkční transporty V-09 zbývají. Hlavičky byly pouze rozbaleny do /tmp; systém ani produkční stack nebyly změněny.

- [x] [completed] **M0-02 — PoC validated: minimální project.json a konfigurace uzlu.** `spikes/configuration.py` a read-only `check_config`/`run.sh config` validují přenositelný projekt, lokální uzel, stabilní UUID, verzi v1, nepřekrývající se lokální cesty a opaque credential reference. Sdíleny parserové limity a UUID/timestamp pravidla; neznámé verze se odmítají bez migrace. Kontrakt a budoucí explicitní migrační pravidla: [ADR 0004](docs/adr/0004-project-node-config.md), příklady v DATA_MODEL. Deset nových testů konfigurace pokrývá i chybové cesty a read-only CLI. `python3 -m unittest discover -s tests -v`: 42 testů prošlo; `bash -n run.sh` a kontrola dokumentovaných příkladů/odkazů prošly. Zapojení konfigurace do aplikačního lifecycle, ověření identity/vaultu a migrační zápis zbývají V-08; distribuce uživatelů není implementována.

- [x] [completed] **Implemented — shellový launcher storage PoC.** `run.sh` poskytuje výchozí dočasné demo, explicitní setup do `.venv`, test, check a help; `spikes/demo.py` používá existující Workspace/Git a lifecycle podle ADR 0003. Ověřeno demo, `bash -n`, spuštění z cizího adresáře, relativní cesta s mezerami, chyby argumentů a neplatný/chybějící projekt bez zápisu. Přes `./run.sh test` prošlo 32 testů. Síťová instalace `setup` nebyla v tomto běhu provedena. Launcher není UI/server; běžná aplikace a balení zůstávají v M1.

- [x] [completed] **Implemented — optimalizace projektových instrukcí AGENTS.md.** Rozlišeno čtení pro návrh, dokumentaci a implementaci; doplněno opětovné použití nezměněných podkladů, pravidlo „další úkol“, aktualizace TODO po uceleném výsledku a evidence ověření bez duplikace počtů testů. Crash boundaries přesunuty před implementaci, zpřesněno cílené a závěrečné ověření. Architektonické mantinely, LLM workflow a pravidla commitů zachovány. Ověřena konzistence, lokální odkazy a diff; čistě dokumentační změna bez nového běhu testů.

- [x] **[completed] M0-01 — Jedna koordinovaná operace journal → validace → Git commit → index.**
  **PoC validated:** `spikes/workspace.py` adaptuje Journal/Git/Index a poskytuje apply/recover/read/receipt. Společný zámek, trvalé UUID a kandidátní commit před compare-and-swap posunem větve, blokované čtení pending operace a dokončený receipt. `tests/test_workspace.py`: 13 nových testů, včetně skutečných pádů procesu a dvou zapisovatelů; celkem 32 testů prošlo. Podrobnosti: [ADR 0003](docs/adr/0003-coordinated-operation.md). Původní akceptační požadavky:

  Operace musí mít stabilní `operation_id` a explicitní stavový životní cyklus. Minimálně musí být možné po restartu rozlišit:

  `prepared → files-applied → committed → indexed`

  Implementace nemusí použít přesně tyto názvy, ale stav musí být obnovitelný bez odhadu podle neúplných vedlejších efektů.

  Journal / operation record nesmí být definitivně odstraněn pouze proto, že byly úspěšně zapsány soubory. Musí zůstat dost informace k rozpoznání, zda příslušný Git commit již vznikl a zda byl index aktualizován.

  Operace eviduje minimálně:

  - operation ID,
  - výchozí HEAD,
  - zamýšlené změněné cesty,
  - stav operace,
  - po commitu výsledný commit ID.

  Recovery musí být idempotentní: opakovaný restart nesmí vytvořit další commit stejné operace.

  Git commit nesmí používat neomezené `git add --all`. Musí commitnout pouze cesty vlastněné aktuální operací, nebo operaci bezpečně odmítnout, pokud nelze oddělit cizí změny.

  Před commitem ověřit, že HEAD stále odpovídá výchozímu HEAD operace. Změna HEAD během operace nesmí být tiše přepsána.

  Akceptace: zámek pokrývá celý životní cyklus, pending stav brání publikaci neúplného projektu; commit obsahuje pouze zamýšlené změny a explicitního autora; restart po zápisu/před commitem i po commitu/před indexací neztratí změny ani nevytvoří duplicitní commit. Ověřit změnu HEAD, cizí rozpracované změny, opakovanou obnovu a dva kooperující zapisovatele. Původní podklad: ADR 0002; samostatný `Git.commit` zůstává testovacím helperem s `add --all`. Workspace jej nepoužívá a drží journal až do indexace. Limity: existující commit a běžná větev, čistý vstup, kooperující procesy se společným stavovým adresářem; ne produkční aplikace.

- [x] [completed] **IP-00 — Implemented: dokumentační integrace IP roadmapy.** Zachována podpůrná roadmapa v `docs/IP`, založeny PATENT_RISK_REGISTER a DEFENSIVE_DISCLOSURES s neověřeným watchlistem a rezervovanými DD náměty; propojeny master roadmapa, README a CONTRIBUTING. Zohledněna existující MPL-2.0. Ověřeny lokální odkazy, věcná konzistence a diff; patentová rešerše, publikace, DOI a crowdfunding zůstávají neprovedené.

- [x] **[completed] Designed — základní návrhy a kostra experimentů.** ARCHITECTURE, DATA_MODEL, FEDERATION, SECURITY, REUSE_CATALOG a ADR 0001/0002 existují; aplikační skeleton, síť ani UI tím nejsou hotové.
- [x] **[completed] PoC validated — Git divergence a historie.** `tests/test_storage.py`: dvě lokální repo kopie, tři konfliktní verze, abort, merge se dvěma rodiči. Žádná síťová federace/autentizace.
- [x] **[completed] PoC validated — validace artefaktů a registrů.** `spikes/metadata.py`, `tests/test_metadata.py`: schéma, UUID, JSON/YAML duplicity, limity, frontmatter, sidecar a vztahy.
- [x] **[completed] PoC validated — SQLite index.** `spikes/storage.py`, `tests/test_storage.py`: validovaný commit, stale detection, obnova z HEAD i po odstranění databáze, oddělení necommitnutých změn.
- [x] **[completed] PoC validated — souborový journal.** `spikes/journal.py`, `tests/test_journal.py`: vytvoření, přejmenování, smazání, přerušená obnova, cizí editace, zachování binárních bajtů a návazný ručně koordinovaný commit/index. Testy používají skutečné `os._exit` v pomocném procesu.
- [x] **[completed] Implemented, ručně ověřeno — CLI validátor projekce.** `spikes/check_project.py`; důkaz smoke testu v ADR 0002, automatizace zbývá V-01.
- [x] **[completed] Implemented — vývojový workflow.** AGENTS.md, tento TODO a reconciliace roadmapy vůči kódu; architektura, ADR a experimenty zachovány.

## Posouzení repozitáře k 2026-09-09

Výchozí HEAD posouzení: `71424f2`; pracovní strom byl čistý. Přečteny dokumenty, oba ADR, všechny spikes a testy. Opětovně spuštěno `python3 -m unittest discover -s tests -v`: **19 testů prošlo** na současném vývojovém hostu. Repozitář neobsahuje nakonfigurovaný build/lint/CI. Přehled neprohlašuje produkční připravenost.

Rozpory a opravy stavu: nezaškrtnuté frontmatter/sidecar, index a definice metadat v roadmapě jsou nyní výslovně PoC validated; původní operativní seznam sekce 19 je převeden sem. Návrhové body backendu, federace, desktopu a bezpečnosti jsou designed, ne implementované. Katalog SQLite nyní zahrnuje i lokální autoritativní journal, což nemění rozhodnutí o neautoritativním projektovém indexu. Věcné otevřené mezery metadat, indexu a testových důkazů jsou V-01 až V-06. Historické počty testů v ADR 0001/0002 zachovávají význam výsledků jednotlivých experimentů.
