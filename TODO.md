# TODO — operativní práce

Aktuální milník: **M0 — Architecture spike**, Gate M0 je otevřený. Strategii a gates drží [master roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>); návrhová rozhodnutí drží [ADR 0001](docs/adr/0001-m0-baseline.md), [ADR 0002](docs/adr/0002-metadata-journal.md) a [ADR 0003](docs/adr/0003-coordinated-operation.md). Tento soubor je průběžný operativní stav, ne další roadmapa.

Stavy: `[ ] [planned]`, `[ ] [in progress]`, `[x] [completed]`, `[ ] [blocked]`. Úroveň výsledku je samostatná: designed / implemented / PoC validated / production-ready. Žádná aplikační část zatím není označena production-ready. Následující úkoly nejsou zahájené ani prokazatelně blokované jen kvůli svým závislostem.

## Nejbližší úkol M0

**M0-03 — Srovnat libgit2/C++ s existujícím Git CLI PoC.** M0-01 a M0-02 jsou dokončené v rozsahu PoC; důkazy a limity jsou níže a v ADR 0003/0004. Gate M0 zůstává otevřený.

## Další zbývající práce M0

- [ ] **[planned] M0-03 — Srovnat libgit2/C++ s existujícím Git CLI PoC.** Nejprve ověřit dostupnost závislosti a reuse katalog; použít stejné scénáře commit/branch/conflict/abort/recovery, přenos a autentizaci. Zapsat výsledky a rozhodnutí o Git adaptéru včetně balení; nedostupnost knihovny v minulém prostředí není zamítnutí technologie.
- [ ] **[planned] M0-04 — Lokální transport/API PoC.** Porovnat IPC/socket s loopback HTTP pro desktop; ověřit autentizaci a nepovolené volání. U HTTP testovat token, Host/Origin a CSRF. Oddělit lokální spojení od budoucí federace. Podklad: SECURITY a roadmapa 12A.
- [ ] **[planned] M0-05 — Ověřit cílové prostředí Turris Omnia/LXC.** Určit dostupný testovací cíl a zaznamenat HW/OS/architekturu. Změřit start, paměť, instalaci a provoz srovnávaných variant, včetně omezení journalu (Linux, lokální souborový systém, společný filesystem pro stav a projekt). Běh aarch64 na vývojovém hostu není tento důkaz.
- [ ] **[planned] M0-06 — Uzavřít backendový stack a desktopový obal.** Linux je první navržený desktopový cíl; zbývá balení, životní cyklus backendu a ověření Qt/WebView se sdíleným UI. Výchozí jeden proces zachovat; hybrid C++/Python přijmout jen s doloženým přínosem a náklady IPC, diagnostiky, obnovy a aktualizací. Závisí na M0-03 až M0-05.
- [ ] **[planned] M0-07 — Ověřit zbývající konfliktové scénáře.** Existuje textový UX scénář a test divergence stejné entity. Doplnit simulaci změna–smazání a přejmenování–úprava páru obsah/sidecar, textově čistý merge s neplatnými vztahy a postup lidského rozhodnutí. Obnova lokálního přejmenování v journalu není distribuovaný merge. Síťová federace zůstává M5.
- [ ] **[planned] M0-08 — Zpřesnit návrhové kontrakty.** Doplnit pravidla větví a publikace při změně HEAD; uzavřít kontrakty Backend/Role/Context Manifest a lokální hranici důvěry v návaznosti na ARCHITECTURE, FEDERATION a SECURITY. LLM adapter ani RBAC engine tímto úkolem neimplementovat.
- [ ] **[planned] M0-09 — Gate review před M1.** Po ověření předchozích výstupů projít Gate M0, zaznamenat důkazy, otevřená omezení a rozhodnutí o připravenosti. Nepřejít do M1 jen na základě zelených spike testů.

## Zjištěné mezery a navazující ověření

- [ ] **[planned] V-01 — Regresní test pro validátor CLI.** ADR 0002 zaznamenává ruční smoke test exit 0/1; CLI zatím nemá vlastní automatický test. Doplnit platnou projekci, osiřelý sidecar, chybějící cestu a jasně vymezit, že se nekontroluje project.json.
- [ ] **[planned] V-02 — Upřesnit test neplatného indexovaného stavu.** `test_invalid_merge_projection_does_not_replace_previous_index` dnes narazí na nesoulad názvu souboru s ID, nikoli nutně na duplicitu ID. Samostatný test validátoru duplicitu pokrývá; doplnit integrační test indexu, který prokáže zamýšlený důvod odmítnutí. Žádný dosavadní test neprokazuje skutečný textově čistý, významově chybný merge (M0-07).
- [ ] **[planned] V-03 — Vyjasnit omezení projekce indexu.** Index nyní validuje vztahy, ale ukládá pouze id/title a commit ID. Před relačními dotazy navrhnout a otestovat rozšíření projekce; neoznačovat existující index za kompletní databázi vztahů.
- [ ] **[planned] V-04 — Sjednotit přesný kontrakt metadat.** DATA_MODEL uvádí u registrů status/body/relations, implementace vyžaduje status/body a relations ponechává volitelné. Upřesnit znění nebo rozhodnout o změně schématu; nic tiše nezpřísňovat. Dále rozhodnout o datu importu a podrobném manifestu provenance, které roadmapa požaduje, ale současné schéma nepodporuje.
- [ ] **[planned] V-05 — Vymezit neměnnost zdrojů při následných úpravách.** Import zachovává bajty a je testovaný. Journal ale obecně přijímá změnu obsahu i provenance; nevynucuje celoživotní neměnnost zdroje. Zaznamenat pravidla aktualizace/verzí a doplnit odpovídající validaci až v implementačním úkolu.
- [ ] **[planned] V-06 — Produkční ochrany před nasazením.** Statické kontroly cest nejsou ochrana před závodícími FS změnami; současný zámek vyžaduje kooperující procesy. Zvlášť prověřit práva existujícího stavového adresáře, cizí Git konfigurace/filtry, povolené transporty a čtení při pending stavu. Nezaměňovat test pádu procesu za výpadek napájení ani host testy za podporu Windows.
- [ ] [planned] **V-07 — Provozní životní cyklus operation receipts (cílová úroveň: implemented).** Před produkčním balením určit retenci dokončených záznamů a bezpečný úklid osiřelých staging adresářů/commit objektů po pádu uvnitř přípravy kandidáta. Pending journal a kandidátní commit se nesmějí odstranit. Doplnit testy přerušení Git podprocesů a postup řešení jejich zbylých lock souborů; současné checkpointy leží mezi voláními.
- [ ] [planned] **V-08 — Aplikační integrace konfigurace (cílová úroveň: implemented).** Navázat na schéma v1 z M0-02: při otevření projektu ověřit project_id registrace, existenci a bezpečné umístění kořenů/stavu, podporovanou verzi a vazbu identity na credential úložiště. Navrhnout bezpečnou inicializaci a serializovaný zápis project.json přes Workspace a oddělený obnovitelný zápis node.json, včetně budoucích explicitních migrací. Před změnou popsat crash boundaries; současný samostatný validátor nic nezapisuje a storage projekce konfiguraci nečte.
- [ ] **[planned] R-01 — Identifikovat starší zdrojové projekty pro reuse.** Katalog zatím neobsahuje konkrétní repository/cesty těchto projektů. Po jejich identifikaci prověřit licence, závislosti, kompatibilitu a důvod reuse/adapt/rewrite/reject. Nevyvozovat, že inventura proběhla.

## Pozdější operativní backlog — nezahajovat místo M0

Přeneseno z původní sekce 19 roadmapy; nejde o rozšíření aktuálního úkolu. Milníky a gates zůstávají v roadmapě.

- [ ] **[planned] M1 — Aplikační základ:** vytvořit LXC development deployment, desktopový launcher/balení, persistentní identitu a úložiště uzlu; implementovat Project/Artifact služby a Git službu adaptací ověřených PoC. Po volbě stacku doplnit frontend, Markdown editor/viewer a Git history UI. Produkční integrace metadat/indexu zůstává otevřená, jejich PoC se neopakuje.
- [ ] **[planned] M2 — Lokální AI:** Ollama adapter, auto-summary/description a Context Builder PoC dle explicitního manifestu a pravidel privacy.
- [ ] **[planned] M3/M4 — Role a backendy:** implementovat Role/Backend modely nad kontrakty uzavřenými v M0 a následné předávání artefaktů mezi rolemi.

- [ ] [planned] **M3-UB-01 — Usage & billing backendů (cílová úroveň: implemented).** Navázat na sekci 7C roadmapy a Backend adapter: u vybraných backendů ověřit podporovaná rozhraní a potřebná oprávnění pro usage a billing samostatně, doplnit načítání a UI indikaci. Rozlišit údaje běhu/workspace a celého účtu, skutečné hodnoty a odhady, období, jednotky/měnu a stáří. Před implementací určit kontrakt, obnovování/cache a přístup k účetním údajům; dostupnost konkrétních provider API je zatím neověřená. Akceptace: scénáře obě capabilities / pouze usage / žádná podpora, nula vs. chybějící údaj, odmítnuté oprávnění, timeout/rate limit a zastaralá data; účetní souhrn se nezpřístupní běžnému uživateli backendu a výpadek přehledu nezmění jeho routing ani cost policy. Priorita M0 se nemění.

## Podpůrné IP / release integrace — nepřebírají prioritu M0

Podrobnou administrativu, screening a crowdfundingové checklisty drží [IP roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>) a její registry. Níže jsou pouze konkrétní integrace do repozitáře; žádná publikační automatizace zatím neexistuje.

- [ ] [planned] **IP-01 — Release a citation metadata (cílová úroveň: implemented).** Před prvním publikačním releasem určit archiv a ověřené autory, licenci, repository URL a verzi; doplnit CITATION.cff a/nebo metadata zvoleného archivu. Akceptace: metadata odkazují na konkrétní disclosure, tag a commit, neobsahují vymyšlené identifikátory a projdou validací zvoleného formátu.
- [ ] [planned] **IP-02 — Archive/release workflow a DOI integrace (cílová úroveň: implemented).** Po určení archivu z IP-01 připravit kontrolu verzí a referencí, následně automatizaci podle sekce 29 IP roadmapy. Akceptace: kontrola odmítne nesoulad tag/commit/disclosure; případné DOI je propojeno obousměrně. Samotné vytvoření tohoto úkolu nepublikuje release ani DOI.
- [ ] [planned] **IP-03 — Propojit financovaný scope s produktovými milníky (cílová úroveň: designed).** Při přípravě kampaně přiřadit schválené balíčky ke stávajícím M1–M6 a určit zařazení Open WebUI integrace; odlišit hotové, financované a budoucí schopnosti. Akceptace: jeden konzistentní rozsah s rozpočtem a readiness review podle IP roadmapy, desktopový základ zůstává M1. Kampaň ani její spuštění tím nejsou schválené.

## Dokončené výstupy a důkazy

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
