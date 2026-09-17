<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Backlog — další dávky

Aktuální dávku drží [TODO](TODO.md), uzavřené dávky [WORK_LOG](WORK_LOG.md), milníky a gates [roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>). Pravidla určuje [AGENTS](AGENTS.md).

Plánovací horizont tvoří zpravidla tři nejbližší **feature dávky**: jedna dávka, jedna feature větev, jeden PR do `develop`. Milníky M1–M6 zůstávají strategickým rámcem. Níže zachované široké a vzdálenější položky jsou zásobník požadavků, nikoli připravené PR dávky. Při běžné implementaci se tento soubor nemění; tato reorganizace je výslovně zadaná změna workflow. Při předání se další jediná dávka přesune do TODO se stejnými ID a návaznostmi. Ověřená práce se neopakuje.

## Nejbližší feature dávky

Názvy větví jsou návrhy, PR dosud nejsou vytvořené. Před zahájením každé dávky ověřit začlenění jejích konkrétních závislostí do `develop`; otevřený Gate M1 neznamená automatické uzavření ostatních požadavků.

F-M1-SOURCE-01/V-05 je po PR #20 (`7152d64`) uzavřena ve [WORK_LOG](WORK_LOG.md#f-m1-source-01--kontrakt-neměnnosti-a-verzování-zdrojů--2026-09-15). F-M1-META-02 je jediná aktivní dávka v [TODO](TODO.md). Backlog nyní drží tři další konkrétní dávky; jejich větve ani PR nejsou vytvořeny.

### F-M1-SOURCE-02 — Vynucení neměnných zdrojů a navazující verze

- Stav: [ ] [planned]; milník M1; cílová úroveň PoC validated.
- Původ: odložená implementace F-M1-SOURCE-01/V-05 a ADR 0024.
- Větev: `feature/f-m1-source-02-enforcement`; základ a jediný PR do `develop`.
- Výstup: transition validace všech publish/merge cest, metadata-only editace zdroje, import nové verze s novým UUID/`supersedes`, bezpečná detekce byte-identity a UI konfliktu.
- Mimo rozsah: content-addressed storage, automatické slučování duplicit a změna trust boundary externích zdrojů.
- Závislosti: ADR 0024 a aktivní F-M1-META-02; použít její parser/index/migraci bez duplikace.
- Akceptace jednoho PR: v1/v2, přímá Git změna obsahu/metadat, fast-forward/merge/stejné UUID, privacy reclassification, expected-HEAD/retry/receipt, pády před/po CAS a indexu, skutečný Qt a celá sada.

### F-M2-CONTEXT-01 — Bezpečný Context Builder

- Stav: [ ] [planned]; milník M2; cílová úroveň PoC validated.
- Původ: Context Builder část širokého M2, ADR 0008.
- Větev: `feature/f-m2-context-01-manifest`; základ a jediný PR do `develop`.
- Výstup: explicitní výběr vstupů, Context Manifest přesných bajtů a revalidace identity/privacy/oprávnění před předáním backendu.
- Mimo rozsah: celý M2, Ollama adapter, automatické souhrny, billing a role orchestrace; ty se připraví jako vlastní dávky.
- Závislosti: příslušné M1 gates a kontrakty ADR 0008; frontu lze posunout podle doložených závislostí, ne automaticky začít M2.
- Akceptace jednoho PR: exact bytes/digests, změna HEAD/oprávnění mezi výběrem a použitím, zákaz local-only exportu a implicitního fallbacku, testy chybových cest a dokumentace.

### F-M2-OLLAMA-01 — Důvěryhodná lokalita Ollama backendu

- Stav: [ ] [planned]; milník M2; cílová úroveň PoC validated.
- Původ: uživatelské doplnění plánu 2026-09-15; Ollama a execution boundaries z roadmapy/ADR 0008.
- Větev: `feature/f-m2-ollama-01-locality`; základ a jediný PR do `develop`.
- Výstup: Ollama adapter a binding, který prokazatelně rozliší `same-node` proces od privátního LAN endpointu; LAN cíl má samostatně rozhodnutou trust boundary, identitu cíle a transportní policy.
- Mimo rozsah: obecná federace, automatické hledání nedůvěryhodných služeb a cloud fallback.
- Závislosti: Backend/Context Manifest kontrakt ADR 0008 a F-M2-CONTEXT-01; před implementací zaznamenat rozšíření execution boundary v ADR.
- Akceptace jednoho PR: same-node/LAN nelze zaměnit konfigurací, DNS rebindingem ani redirectem; identita a skutečný cíl jsou součástí manifestu a revalidace. `local-only` se na LAN nikdy neposílá bez explicitní reklasifikace, neexistuje implicitní LAN/cloud fallback a testy pokrývají nedostupnost, změnu cíle a restart.

## Zjištěné mezery a navazující ověření

- [ ] [planned] **V-11 — Příprava veřejné distribuce (cílová úroveň: designed).** Před zveřejněním .deb nahradit maintainer placeholder skutečným kontaktem, určit aktualizační kanál a vyhodnotit licenční povinnosti vůči konkrétním souborům/verzím z distribučního inventáře. Úspěšná interní PoC instalace ani inventář hashů nejsou právním posouzením releasu.

- [ ] **[planned] V-01 — Regresní test pro validátor CLI.** ADR 0002 zaznamenává ruční smoke test exit 0/1; CLI zatím nemá vlastní automatický test. Doplnit platnou projekci, osiřelý sidecar, chybějící cestu a jasně vymezit, že se nekontroluje project.json.
- [ ] **[planned] V-06 — Produkční ochrany před nasazením.** Statické kontroly cest nejsou ochrana před závodícími FS změnami; současný zámek vyžaduje kooperující procesy. Zvlášť prověřit práva existujícího stavového adresáře, cizí Git konfigurace/filtry, povolené transporty a čtení při pending stavu. Nezaměňovat test pádu procesu za výpadek napájení ani host testy za podporu Windows.
- [ ] [planned] **V-07 — Provozní životní cyklus operation receipts (cílová úroveň: implemented).** Před produkčním balením určit retenci dokončených záznamů a bezpečný úklid osiřelých staging adresářů/commit objektů po pádu uvnitř přípravy kandidáta. Pending journal a kandidátní commit se nesmějí odstranit. Doplnit testy přerušení Git podprocesů a postup řešení jejich zbylých lock souborů; současné checkpointy leží mezi voláními. Zahrnout uzlové creation receipts a osiřelé staging složky M1-02; konfliktní pending vytvoření potřebuje explicitní bezpečné zrušení/řešení, které zatím nemá UI.
- [ ] [planned] **V-08 — Zbývající lifecycle konfigurace (cílová úroveň: implemented).** Ověření při otevření je M1-01; vytvoření nového projektu, stabilní lokální author/node/project ID a obnovitelná registrace jsou M1-02 dle ADR 0015. Zbývá registrace již existujícího projektu s jeho původním stavem, změny/migrace konfigurací a vazba identity na credential úložiště. Projektové změny dále vést přes Workspace; index artefaktů není autoritou projektové konfigurace.
- [ ] [planned] **V-09 — Produkční Git transport a credentials (cílová úroveň: PoC validated).** Nad výchozím Git CLI ověřit TLS certifikáty, SSH host keys, zvolený credential store/helper, odmítnutí odvolaných credentials, timeout/cancel a restart přenosu. Loopback HTTP Basic test M0-03 ověřuje správné/chybné credentials, nikoli bezpečný internetový transport nebo federované RBAC. Vazba na V-06, cílové balení a M5.
- [ ] **[planned] R-01 — Posoudit zdrojové komponenty pro reuse (cílová úroveň: designed).** Před převzetím ověřit původ/licenci souborů, úplné závislosti, testy a kompatibilitu. Lokální inventura a její zbývající rozsah patří výhradně do volitelného soukromého katalogu; veřejné kandidáty evidovat v REUSE_CATALOG až po ověření veřejné dostupnosti.

- [ ] [planned] **V-10 — Integrace lokálního API (cílová úroveň: PoC validated).** Qt/WebEngine, same-origin UI a token v nativním interceptoru jsou ověřeny M0-06a. Zbývá lifecycle po násilném pádu, případný úklid Unix socketů a bezpečné vykreslení nedůvěryhodných artefaktů. Před persistentními mutacemi v M1 definovat klientské operation ID/retry/receipt podle ADR 0003, limity souběhu a celkový deadline requestu. Protokolový čítač ADR 0006 toto neprokazuje. M1-02 uzavírá pouze nativní vytváření: operation ID/receipt, jeden worker, neblokující uzlový zámek, deadline a recovery dle ADR 0015. M1-03 přidává nativní editor dle ADR 0016: stabilní operation ID/digest/receipt, kontrolu výchozího HEAD, neblokující zámek, recovery při otevření editoru a textové zobrazení nedůvěryhodného obsahu. Obecné mutující HTTP API zůstává neimplementované a pro tento nativní vstup není potřeba.

## Strategický zásobník — M2 až M4 (není připravená dávka)

Přeneseno z původní sekce 19 roadmapy. Široké M2 a M3/M4 se před implementací rozdělí na feature dávky s vlastní větví a PR; zachová se původ a návaznosti. Karty výše odkazují na tento strategický rozsah, neprohlašují celý milník za jednu feature.

- [ ] **[planned] M2 — Lokální AI:** Ollama adapter, auto-summary/description a Context Builder PoC dle ADR 0008: manifest přesných bajtů, revalidace před odesláním, zákaz implicitního fallbacku a recovery unknown běhů.
- [ ] **[planned] M3/M4 — Role a backendy:** implementovat Role/Backend modely a testy autorizace/execution boundaries dle ADR 0008 a následné předávání artefaktů mezi rolemi.

### Navazující konverzační feature dávky

Tyto dávky doplňují M2/M3, ale nemění pořadí tří nejbližších dávek výše. Před aktivací ověřit skutečné závislosti a aktualizovat ADR 0008; názvy větví jsou návrhy, větve ani PR nebyly vytvořeny.

#### F-M2-CHAT-01 — Lokálně perzistentní živé konverzace

- Stav: [ ] [planned]; milník M2; cílová úroveň PoC validated.
- Původ: uživatelské doplnění plánu 2026-09-15; volitelný orchestrator chat a LLM run records z ADR 0008.
- Větev: `feature/f-m2-chat-01-local-threads`; základ a jediný PR do `develop`.
- Výstup: backendově nezávislé vícekolové vlákno, lokální trvalé uložení a bezpečné navázání po restartu; samostatný chat má výchozí klasifikaci `brainstorming`.
- Mimo rozsah: projektová publikace, full/delta otisky, synchronizace vláken a automatické provádění navržených akcí.
- Závislosti: F-M2-CONTEXT-01 a alespoň jeden povolený backend; před implementací doplnit ADR 0008 o Thread/Message kontrakt, retenci a crash boundaries. Vlákno, jednotlivé run records a projektový index zůstávají oddělené.
- Akceptace jednoho PR: po pádu je rozlišen poslední potvrzený obsah od draftu a `unknown` běhu, navázání explicitně manifestuje vybrané zprávy, změna backendu/modelu/boundary je viditelná a nevyvolá tichý fallback. Testy pokrývají restart v každém trvalém přechodu, poškozený stav, souběh a oddělení projektů/uživatelů.

#### F-M2-CHAT-02 — Projektová vlákna, otisky a Markdown výstupy

- Stav: [ ] [planned]; milník M2/M3; cílová úroveň PoC validated.
- Původ: uživatelské doplnění plánu 2026-09-15; Git-backed artefakty, provenance a workflow výstupy z roadmapy.
- Větev: `feature/f-m2-chat-02-project-records`; základ a jediný PR do `develop`.
- Výstup: explicitní přiřazení vlákna ke konkrétnímu projektu jako navazovatelného živého vlákna; neměnný kompletní nebo rozdílový otisk a samostatné editovatelné Markdown artefakty pro výsledky úkolů, např. oponenturu, brainstormingový souhrn nebo tezi.
- Mimo rozsah: automatické ukládání každého soukromého chatu do projektu, ukládání credentials/provider session tokenů do Gitu a vydávání rozdílu bez jeho základu za kompletní historii.
- Závislosti: F-M2-CHAT-01, F-M1-META-01/F-M1-SOURCE-01 podle přijatého kontraktu a standardní Workspace/Journal/Git/index lifecycle.
- Akceptace jednoho PR: živé vlákno lze po restartu navázat ke správnému projektu; projektová reprezentace editovatelného obsahu je primárně Markdown. Kompletní otisk je samostatně čitelný, rozdílový nese ID/hash základu a odmítne chybějící či neshodný základ. Odvozený artefakt zachová vazbu na vlákno/run/vstupy/manifest a nejpřísnější privacy; expected-HEAD, retry, pád před/po commitu a obnova indexu jsou otestovány.

- [ ] [planned] **M3-UB-01 — Usage & billing backendů (cílová úroveň: implemented).** Navázat na sekci 7C roadmapy a Backend adapter: u vybraných backendů ověřit podporovaná rozhraní a potřebná oprávnění pro usage a billing samostatně, doplnit načítání a UI indikaci. Rozlišit údaje běhu/workspace a celého účtu, skutečné hodnoty a odhady, období, jednotky/měnu a stáří. Před implementací určit kontrakt, obnovování/cache a přístup k účetním údajům; dostupnost konkrétních provider API je zatím neověřená. Akceptace: scénáře obě capabilities / pouze usage / žádná podpora, nula vs. chybějící údaj, odmítnuté oprávnění, timeout/rate limit a zastaralá data; účetní souhrn se nezpřístupní běžnému uživateli backendu a výpadek přehledu nezmění jeho routing ani cost policy. Priorita M0 se nemění.

## Externí vztahy a disclosure — navazující strategický backlog

Rozsah a gates rozšíření drží sekce 22 master roadmapy. Jde o plánovanou práci, která nemění pořadí nejbližších dávek ani zpětně neotevírá uzavřený Gate M0. Původní patch označoval návrhový kontrakt jako M0-10; po uzavření M0 je zachován pod ID ER-00. Před použitím protokolových knihoven nebo rendereru provést reuse, licenční a capability review v `REUSE_CATALOG.md`; nevytvářet nový mail server.

- [ ] **[planned] ER-00 — Kontrakt externích vztahů, komunikace a disclosure (cílová úroveň: designed).**
  Uzavřít entity, identity příjemců, přesnou revizi a rozsah předaného obsahu, oddělení privacy, prezentační klasifikace a evidence a hranice komunikačního úložiště. Rozhodnout veřejný a soukromý katalog, per-project a cross-repo vztahy, append-only opravy, idempotenci, retenci a obnovu neurčitého externího účinku. Zaznamenat autoritu mail/DAV dat, outboxu a projektových importů; hesla a tokeny zůstávají mimo Git.
  Akceptace: návrhové scénáře částečného sdílení, nové revize, stejného příjmení či adresy, změny organizace, nového účastníka, odpojeného audience okna, pádu po SMTP přijetí a neúplné federované historie. Výstup zahrne migrační hranici vůči striktnímu schématu v1; samotný text roadmapy není důkaz implementace.

- [ ] **[planned] ER-01 — Verze schémat a projekce registrů (cílová úroveň: implemented).**
  Po ER-00 zavést vybraná schémata a migrace bez tichého rozvolnění v1. Rozšířit obnovitelný index, API a validaci oprávněných vztahů; zachovat jedinou zápisovou cestu Workspace/Journal/Git/index.
  Akceptace: starý projekt zůstává čitelný, nepodporovaná verze je odmítnuta, migrovaný projekt projde obnovou indexu a neplatný lokální nebo cross-repo vztah nepřinese falešná data. Návaznost V-03/V-04.

- [ ] **[planned] ER-02 — Partneři, adresář a schůzky (cílová úroveň: implemented).**
  Po ER-01 dodat CRUD osob, organizací a vztahů, kontaktní pohled, časové role a interní schůzky s agendou, skutečnými účastníky a follow-up úkoly. Soukromý katalog sdílet jen explicitně.
  Akceptace: dvě osoby se stejným jménem nebo sdílenou adresou nesplynou bez potvrzení; změna zaměstnavatele nepřenese historii; jiný projekt neuvidí soukromé poznámky a pozvánka neexportuje interní agendu automaticky.

- [ ] **[planned] ER-03 — Disclosure Registry a snapshoty (cílová úroveň: implemented).**
  Po ER-01/ER-02 dodat ruční inbound/outbound události, opravy a projekci podle příjemce; přesný payload a hash, úplné source refs a scope. Navrhnout retenci revizí a navázat existující IP publikační registr pouze referencí.
  Akceptace: summary neoznačí celý zdroj za předaný; přejmenování či nový HEAD nezmění starou revizi; export bez adresáta není doručení; opakovaný operation ID neduplikuje fakt a opravná událost zachová původní záznam. Projít crash boundaries dle DATA_MODEL.

- [ ] **[planned] ER-04 — Offline Disclosure Presenter MVP (cílová úroveň: PoC validated, potom implemented).**
  Po ER-02/ER-03 dodat hlavní deck, notes, privátní preview, backup triggery a návrat, audience-only renderer a trvalou relaci. Green/orange/red váží 0/0,5/1; prahy, count/time upozornění a klasifikaci vést odděleně od oprávnění. Bez závislosti na LLM nebo mail klientu.
  Akceptace: preview +0; orange → green → red dává 1,5 stupně; opakování stejného payloadu pro stejné publikum v relaci nezvedne skóre; nová revize nebo příjemce vyžaduje kontrolu a zavření nesníží expozici. Ověřit restarty, odpojenou obrazovku, zákaz přes override, neutral/blackout a safe export bez notes a skrytých dat. Před schůzkou ověřit reálné dvouobrazovkové nastavení Linux desktopu.

- [ ] **[planned] ER-05 — Plnohodnotný mail klient (cílová úroveň: implemented).**
  Po registry a policy základu vybrat a ověřit IMAP/SMTP adaptér pro první účty, včetně TLS a OAuth2 podle poskytovatele; dodat složky, threading a hledání, přílohy, compose/reply/forward, offline koncepty a durable outbox. Import do projektu je oddělen od synchronizace schránky.
  Akceptace: změna UIDVALIDITY, ztráta spojení, expirovaný token a částečné odmítnutí příjemců nevedou ke ztrátě či automatické duplicitní zásilce. Ověřit pád po SMTP přijetí se stavem unknown, obnovu fronty, Bcc/reply-all, citovaný citlivý obsah, vazbu přesných příloh na ER-03 a sandbox HTML. Nezvyšovat potichu limity příloh.

- [ ] **[planned] ER-06 — Kalendář a synchronizovaný adresář (cílová úroveň: implemented).**
  Po ER-02 a relevantní transportní a policy vrstvě přidat CalDAV kalendáře, pozvánky a odpovědi a CardDAV projekci partnerů; určit mapování polí, UID a verzí a zdroj pravdy při oboustranné editaci. Provider-specific adaptér až podle ověřené potřeby.
  Akceptace: časová pásma, výjimka opakování, změna nebo odvolání pozvánky, ETag konflikt, smazání a offline návrat jsou deterministické; soukromé poznámky nevstoupí do vzdáleného kalendáře nebo kontaktu. Příchozí pozvánka se nepotvrdí bez povolení.

- [ ] **[planned] ER-07 — Federace vztahů a evidence (cílová úroveň: PoC validated, potom implemented).**
  Navázat na M5 a ER-03. Ověřit autorizované projekce partnerů a událostí bez přenosu celé schránky, secretů nebo citlivé historie zdrojového repozitáře. Zpracovat offline události podle stabilních ID a provenance; nepředstírat globální pořadí jen podle hodin uzlu.
  Akceptace: dvě offline relace neztratí událost; shodné ID s rozdílným obsahem vyvolá konflikt; peer bez přístupu ke zdroji obdrží jen povolenou projekci a nedostupná historie zůstane neověřená. Před implementací uzavřít přenosové hranice ve FEDERATION/ADR.

- [ ] **[planned] ER-08 — Kontext partnera a volitelný LLM poradce (cílová úroveň: implemented).**
  Po ER-03 navázat oprávněné vztahy na M6 a volitelné modely M2–M4: návrh klasifikace, rozdíl revizí, příprava schůzky a otázky nebo reciprocita zadávané uživatelem. Používat Context Manifest, zdrojové reference a lidské schválení.
  Akceptace: nepovolený zdroj ani cizí projekt nevstoupí do kontextu; prompt injection v mailu nevyvolá odeslání; reciprocita sama neodblokuje red slide a nedostupnost lokálního LLM nezpůsobí externí fallback. Základní Presenter a registry fungují i bez modelu.

## Vzdálenější strategické požadavky (před aktivací rozdělit na feature dávky)

- [ ] [planned] **M5 — Federovaná publikace (cílová úroveň: PoC validated).** Implementovat izolovaný příjem, autorizaci celého přenášeného obsahu včetně historie, validaci kandidáta a CAS/recovery dle ADR 0008. Ověřit změnu HEAD po lidském řešení, neplatný fast-forward/merge, revokaci a odmítnutí přenosu local-only historie; zachovat konfliktní rodiče.

## Import externích dat — navazuje na aplikační import M1

Strategický rozsah drží sekce 3C master roadmapy; tyto úkoly nemění prioritu desktopového PoC.

- [ ] [planned] **IMP-01 — Import z Google služeb přímo i z exportu (cílová úroveň: implemented).** První rozsah je Drive včetně Docs/Sheets/Slides: ověřit OAuth scopes, výběr souborů, download/export podle typu a limity. Souběžně navrhnout bezpečný lokální import uživatelem dodaného Takeout/nativního exportu; každou další službu aktivovat až po ověření skutečného API nebo vzorku. Navázat na aplikační import a ADR 0023/0024. Akceptace: binární soubor i nativní Google dokument oběma dostupnými cestami, oddělený doložený čas vzniku od importu, provenance exportu, duplicita/nová revize, odvolané oprávnění, limity a přerušený přenos nebo archiv bez částečného publikování do projektu. Před zápisy popsat crash boundaries podle ADR 0003.
- [ ] [planned] **IMP-02 — NotebookLM import (cílová úroveň: PoC validated).** Určit edici účtu a ověřit dostupné oficiální exporty/API zvlášť pro zdroje, poznámky, generované výstupy a chat. Enterprise preview nepovažovat za obecné API osobního účtu. Akceptace: uživatelem poskytnutý vzorek, zachované dostupné citace/provenance, jasný seznam neimportovatelných částí a funkční souborový fallback tam, kde export existuje. Nezavádět automaticky placenou Enterprise závislost.
- [ ] [planned] **IMP-03 — Import exportů konverzací (cílová úroveň: implemented).** Získat uživatelem schválené anonymizované vzorky ChatGPT a Gemini/Takeout, ověřit skutečnou strukturu a vytvořit lokální import s náhledem. Akceptace: role/pořadí/větvení podle dostupnosti, chybějící metadata, přílohy, opakovaný import a poškozený archiv; omezit velikost i rozbalení archivu, odmítnout traversal/symlinky a nevykonávat importované HTML. Generační API není předpokládaným zdrojem historie webového účtu.
- [ ] [planned] **IMP-04 — Vstupní fronta a lokální LLM návrh zařazení (cílová úroveň: PoC validated).** Umožnit import bez aktivního projektu do soukromé lokální fronty a nad validovaným vstupem nabídnout návrh nuly, jednoho nebo více oprávněných cílových projektů. LLM je pouze lokální volitelný poradce; bez něj zůstává ruční zařazení. Akceptace: vysvětlení/confidence a navržená privacy, lidské potvrzení před prvním projektovým zápisem, nezařazení/odmítnutí, multi-project fan-out se samostatným stavem a idempotentním retry pro každý projekt, částečný úspěch bez tichého rollbacku commitů, pád před/po jednotlivých publikacích a žádný externí fallback pro `local-only`. Závisí na příslušném importéru, Workspace recovery a lokálním LLM/Context Manifest kontraktu.

## Read-only artefakty sdílené mezi projekty

- [ ] [planned] **XREF-01 — Připnuté meziprojektové reference artefaktů (cílová úroveň: PoC validated).** Navrhnout verzovaný referenční záznam a implementovat první rozsah mezi dvěma lokálně registrovanými projekty. Reference je read-only, identifikuje zdrojový projekt/repozitář, artifact ID, úplný commit a hash; není filesystemový symlink ani kopie bajtů. Akceptace: vytvoření a zobrazení připnuté revize, nabídka novější revize bez automatického přepnutí, opětovná kontrola oprávnění/privacy, offline cache se stale indikací, revokovaný/smazaný/nedostupný zdroj, explicitní fork s novým ID a provenance, zahrnutí do indexu/Context Manifestu pouze s autorizovanými přesnými bajty a recovery zápisu reference přes Workspace. Závisí na F-M1-SOURCE-02 a stabilní registraci projektů; vzdálené reference zůstávají pro M5 a identity cross-repo koordinovat s ER-00/ER-01.

## Podpůrné IP / release integrace — nepřebírají prioritu M0

Podrobnou administrativu, screening a crowdfundingové checklisty drží [IP roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>) a její registry. Níže jsou pouze konkrétní integrace do repozitáře; žádná publikační automatizace zatím neexistuje.

- [ ] [planned] **IP-01 — Release a citation metadata (cílová úroveň: implemented).** Před prvním publikačním releasem určit archiv a ověřené autory, licenci, repository URL a verzi; doplnit CITATION.cff a/nebo metadata zvoleného archivu. Akceptace: metadata odkazují na konkrétní disclosure, tag a commit, neobsahují vymyšlené identifikátory a projdou validací zvoleného formátu.
- [ ] [planned] **IP-02 — Archive/release workflow a DOI integrace (cílová úroveň: implemented).** Po určení archivu z IP-01 připravit kontrolu verzí a referencí, následně automatizaci podle sekce 29 IP roadmapy. Akceptace: kontrola odmítne nesoulad tag/commit/disclosure; případné DOI je propojeno obousměrně. Samotné vytvoření tohoto úkolu nepublikuje release ani DOI.
- [ ] [planned] **IP-03 — Propojit financovaný scope s produktovými milníky (cílová úroveň: designed).** Při přípravě kampaně přiřadit schválené balíčky ke stávajícím M1–M6 a určit zařazení Open WebUI integrace; odlišit hotové, financované a budoucí schopnosti. Akceptace: jeden konzistentní rozsah s rozpočtem a readiness review podle IP roadmapy, desktopový základ zůstává M1. Kampaň ani její spuštění tím nejsou schválené.

## Otevřená práce převzatá ze široké dávky M1 — 2026-09-14

Administrativní přesun při čištění TODO, nikoli uzavření či merge. Níže jsou autoritativní zbývající úkoly; jejich implementace a důkazy se zachovávají. Stav planned zde znamená odložené dokončení/ověření, nikoli chybějící již popsanou implementaci. Před aktivací je seskupit či rozdělit na jednu feature a jeden PR do develop podle pravidel AGENTS. Souhrnný M1 je strategický požadavek, ne feature dávka. U V-08/V-11 jsou již doložené části ve WORK_LOG; původní širší backlog položky dál evidují pouze jejich zbývající rozsah.

- [ ] **[planned] M1 — Aplikační základ:** vytvořit LXC development deployment, desktopový launcher/balení, persistentní identitu a úložiště uzlu; implementovat Project/Artifact služby a Git službu adaptací ověřených PoC. Po volbě stacku doplnit frontend, Markdown editor/viewer a Git history UI. Produkční integrace metadat/indexu zůstává otevřená, jejich PoC se neopakuje.

Tento převzatý souhrn M1 je zastřešující úkol; M1-05 níže je jeho konkrétní první krok. Zahrnuje zbývající požadavky sekce M1 roadmapy, včetně typů artefaktů, metadat, obnovy indexu po přejmenování/smazání, recovery zápisů a zachování původních bajtů importu. Hotové části souhrnu doložené ve WORK_LOG se znovu neimplementují. Další kroky rozepisuj zde podle ověřeného stavu; relevantní existující V-* položky v BACKLOG používej jako návaznosti, jejich doplnění dočasně zachyť níže.

Podmínka uzavření: dokončené a ověřené zbývající požadavky M1 i přijaté ad-hoc úkoly a doložené review Gate M1 (použitelný workspace bez LLM v LXC i desktopu). Případné zúžení dávky musí výslovně zachovat otevřený gate a odloženou práci; samotné dokončení M1-05 nestačí.

## Na řadě

- [ ] [planned] **M1-AH-15 — Durable journal odchozího Git přenosu (implemented, 2026-09-14; neověřeno).** Navazující otevřená recovery část M1-AH-14 po uživatelském potvrzení skutečného přenosu. Authoritative SQLite journal mimo projektový Git uchovává přesný bundle BLOB, source HEAD, digest, operation ID a identity/piny obou uzlů; není obnovitelným projektovým indexem. Publikace celé exportní dávky jednou SQLite transakcí s synchronous FULL před SSH. Retry/restart obnoví stejné bajty a ID, odmítá změněný zdroj/identity; dokončení se zaznamená až po vzdálené odpovědi. Chyba lokálního completion nezamlčí úspěšný vzdálený import. Native formulář nabídne pokračování nedokončeného přenosu. Příjemní staging recovery před publikací zůstává omezené dle M1-AH-14. Podmínka dokončení: SQLite/crash/restart/lost-response/foreign-source testy, GUI, celé testy a cílová akceptace; testy ani kontroly nebyly spuštěny.

Uživatelská akceptace M1-AH-14: projekt se skutečně přenesl podle potvrzení uživatele. Historická práva navrhuje uživatel řídit na úrovni větví, ne jednotlivých commitů. Návrh zatím není implementované oprávnění: branch policy musí autorizovat všechny dosažitelné historické objekty a nesmí povolit únik local-only přes společné předky/merge/jiný ref. Public-only gate zůstává beze změny; návrh branch ACL patří k následnému rozhodnutí M5.

- [ ] [planned] **M1-AH-14 — První nativní Git přenos veřejného projektu (implemented, 2026-09-14; neověřeno).** Explicitní požadavek uživatele přenést projekt nativním Gitem bez hlavního workflow v hookách. Native dialog potvrzuje jednosměrný desktop→LXC přenos celé vybrané historie. Git fetch do izolovaného exportu a bundle jediné větve, příjem do izolované složky, incoming ref, sémantická validace všech dosažitelných commitů a prvotní registrace přes ProjectCreation journal. UUID/historie/provenance beze změny. Bez merge či aktualizace již existujícího cíle. Ochrana historie je zatím fail-closed: pouze public entity a project.json/artifacts/registries ve všech commitech, max 500 commitů/64 MiB bundle; project/confidential/local-only i historicky se odmítají bez reklasifikace. Historické ACL pro neveřejná data nejsou implementované; nejde o plnou synchronizaci M5. Reuse Git CLI se zakázanými hooky, validátorů, registrace/recovery a jediného SSH procesu; credentials/node/journal/index mimo přenos. Transfer intent/digest a staging mimo projektový Git umožňují identifikaci operace; pád před publikací se může zastavit k ruční obnově, po publikaci lze obnovit registraci. Podmínka dokončení: export/import a fail-closed testy, UUID/dirty/foreign/retry/SIGKILL/registration recovery, Qt, celé testy a cílová akceptace. Testy ani kontroly nebyly spuštěny.

Uživatelská akceptace M1-AH-13: oba směry desktop↔LXC prošly TLS a podepsaným identity probe podle vloženého výpisu. Jde o cílové potvrzení uživatele, nikoli agentní testy ani důkaz datové synchronizace.

- [ ] [planned] **M1-AH-13 — Obousměrný test desktop/LXC a veřejná CA (implemented, 2026-09-14; neověřeno).** Navazující úkol po uživatelském potvrzení HTTPS backendu a podepsaného testu desktop→LXC. Native tlačítko potvrzuje SSH přenos pouze veřejné desktopové CA a CAS aktualizaci endpointu již schváleného desktopového peeru na LXC. Jeden SSH proces; kontrola původních node ID/pinů obou uzlů, poté podepsaný test LXC→desktop s nonce a TLS/SAN. Identity/práva/credentials/firewall beze změny. Reuse NetworkBackend, probe, SSHSession a Administration; žádný reset webu. Pád mezi CA/endpoint/testem ponechá částečný stav, opakování jej může dokončit; nejsou jednou distribuovanou transakcí. Podmínka dokončení: Qt/SSH/TLS a mismatch/přerušení/CAS testy, celé testy a cílová obousměrná akceptace. Žádné nové testy ani kontroly nebyly spuštěny; synchronizace dat zůstává M5.

Uživatelský důkaz M1-AH-09/10/11/12: aktualizace LXC dokončena se zachováním identity/credentials, detekována IP 192.168.100.247, přenesena veřejná CA a zapamatován uzel. Desktopový backend hlásí https://192.168.100.192:8443 a podepsaný test desktop→LXC prošel. Jde o výpisy uživatele, ne nové agentní testy; opačný směr nebyl tímto doložen.

- [ ] [planned] **M1-AH-12 — Desktop HTTPS backend a podepsaný test spojení (implemented, 2026-09-14; neověřeno).** Souhlas uživatele s navazujícím síťovým krokem. Nativní nastavení bind/port/LAN/TLS, opt-in backend ve stejném desktopovém procesu a identitě, uložené nastavení a automatická aktivní adresa v deploy průvodci. Reuse WebServer TLS/LAN, Administration writer lock a Ed25519; nový nonce-bound probe neautentizuje účty a nezpřístupňuje projekty ani synchronizaci. LXC web doplňuje stejný podepsaný endpoint. Native test kontroluje CA/SAN, challenge/node ID/endpoint, schválený pin a podpis; rozlišuje TLS, HTTP/nepodporovaný endpoint a nedostupnost (firewall pouze možná příčina). Veřejná CA z autorizovaného SSH deploye se uloží také lokálně, soukromé klíče se nepřenášejí. Network settings/TLS mimo projektový Git; immutable TLS adresář je flushnut před atomic settings publikací, pád může ponechat pouze neaktivní TLS adresář. Změna nastavení zachovává předchozí backend při běžném selhání. Podmínka dokončení: Qt, socket/TLS/auth boundaries, nonce/replay/pin mismatch, persistence/recovery, cílové desktop–LXC obousměrné ověření. Testy ani kontroly nebyly spuštěny; implementovaný test je desktop→LXC, nikoli důkaz obousměrnosti nebo datového transportu. Firewall/router nezměněny.

- [ ] [planned] **M1-AH-11 — Zapamatované LXC uzly a změny adres (implemented, 2026-09-14; neověřeno).** Požadavek uživatele: průvodce pamatuje nasazené uzly, nabízí vlastní adresy a aktualizuje adresu kontejneru. Soukromé lokální deployment preferences mimo projektový Git obsahují SSH cíl/kontejner/LAN/endpointy a veřejnou identitu, nikoli credentials. Publikace přes lokální flock, fsync a atomic replace; po chybě zápisu se úspěšná vzdálená operace nevrací. Výběr uzlu předvyplní formulář, IPv4 rozhraní nabídnou neověřené HTTPS návrhy s portem 8443. Samostatná změna adresy přes jedno SSH ověří jednoznačnou IP v LAN, původní node ID/pin a TLS SAN, pak CAS aktualizuje pouze endpoint schváleného desktopového peeru, nikoli důvěru/práva/mapování. Reuse registry a SSH session M1-AH-10; žádný redeploy, reset nebo regenerace CA. Podmínka dokončení: persistence/restart, Qt, IP/TLS/identity mismatch, CAS a selhání lokální publikace; testy ani kontroly nebyly spuštěny. Návrh desktopové adresy není důkaz běžícího HTTPS backendu.

- [ ] [planned] **M1-AH-10 — Desktopový deploy LXC a prvotní propojení (implemented, 2026-09-14; neověřeno).** Explicitní požadavek uživatele: desktopový průvodce, detekce IP, jedno SSH spojení, aktuální uživatel jako lokální správce nového uzlu a jeho propojení s desktopem. Native Qt dialog používá jeden OpenSSH proces s framed transportem pro deploy, zjištění IP, přenos veřejné CA a párování; heslo zadává ephemeral native askpass bez uložení. Adaptace existujícího CLI install/update/recover/reset, registru správy a Ed25519 protokolu, nikoli nový backend. První instalace vytvoří deterministickou lokální identitu správce; její klíč zůstává v LXC. Schválení obou peerů je součástí výslovně potvrzeného SSH setupu. Projektové mapování používá skutečná společná projektová UUID; prázdný nový uzel čeká na jejich registraci. Vyžaduje skutečný HTTPS endpoint desktopového backendu; současný loopback desktopový UI server se nevydává za síťový backend. Existující instalace automatické účty/párování vynechá. Cílová úroveň PoC validated; podmínka dokončení: Qt, packaging, jediné SSH/password/agent, IP ambiguity, přerušení bootstrapu/párování, CAS/retry a reálné LXC ověření. Testy ani kontroly nebyly spuštěny. Obnova neúplného párování zatím přes stávající správu; automatické pokračování po ztrátě spojení není implementované.

- [ ] [planned] **M1-AH-09 — Inkrementální LXC deploy a vedená obnova (implemented, 2026-09-14; neověřeno).** Požadavek uživatele: aktualizovat pouze vlastní software, přeskočit již splněné instalační kroky a doporučit recovery/reset při chybě. `--update-only` vyžaduje existující web, zachová TLS/identitu/credentials, nepouští apt ani bootstrap; běžná instalace doplňuje pouze chybějící systémové balíky. Nové vydání má vlastní venv a Python dependencies. Reuse release/current a rollback snapshotu ADR 0020. `--recover` obnovuje v LXC, retry dostane nové release ID a obnova již neběží omylem na routeru. Chyby vypisují konkrétní recovery/reset kroky bez automatického destruktivního resetu. Podmínka dokončení: cílené/full testy a cílové update/recovery scénáře; zatím neprovedeno. Restart routeru odložen na přání uživatele kvůli zachování sítě.

Uživatelská akceptace (2026-09-14): webové vytváření projektů (M1-AH-05) a správa uživatelů (M1-AH-06/07) fungují na nasazení. Nastavení federace funguje na úrovni zadání, nikoli doloženého transportu. Jde o potvrzení uživatele, ne nové agentní testy; neuzavírá celý M1/M5 gate ani ostatní scénáře.

K předání podle požadavku uživatele (2026-09-14): pohodlnější lokální přihlašování místo ručně zadávaného tokenu a uhlazení UI správy uživatelů/federace. Zatím pouze požadavek, bez zvolené auth architektury; hesla se mezi uzly nepřenášejí.

Poznámka uživatele k federaci (2026-09-14): nastavení desktopu a kontejneru dokončeno, vzájemná komunikace přes přímé adresy zatím nepotvrzena; případný firewall není doložená příčina. Na přání uživatele se síťová diagnostika odkládá. Automatický transport zůstává otevřenou prací M5; nebyly měněny firewall ani cílová zařízení.

- [ ] [planned] **M1-AH-07 — Lokální účty a oboustranné federační mapování (implemented, 2026-09-13; portable ACL designed s vykonatelným validátorem).** Upřesnění uživatele: samostatné záložky/tabulky uživatelů a federace; desktop jediný běžící uživatel, web více lokálních účtů, login pouze lokálně, credentials nepřenášet, oboustranné mapování a zachování práv s daty. Adaptace stávající správy; registr v2 a migrace v1 zachovávají UUID/credentials. Offline Ed25519 potvrzení a revokace se ověřují vůči pinům obou uzlů, stale/změněné návrhy se odmítají. Native správa používá pouze process token, nevytváří webové účty. [ADR 0021](docs/adr/0021-local-accounts-and-bilateral-mapping.md), [návod](docs/administration.md). Podmínka dokončení: testy dvou uzlů, native/web autentizace, migrace, revokace/replay, průniku ACL, UI a cílová akceptace. Datový transport, vazba ACL na skutečně přenášené bajty/historii a automatická distribuce revokací zůstávají M5, nikoli hotová federovaná synchronizace. Výsledky závěrečného ověření doplnit níže.

- [ ] [planned] **M1-AH-05 — Webové vytvoření projektu (implemented, 2026-09-13).** Požadavek uživatele po funkčním LXC deploy: vytvoření projektu bez desktopu. Adaptace ProjectCreation/Projects, opravené DOM ID, povolená autentizovaná route, operation_id/receipt pro retry, obnova journalu před startem webu. Podmínka dokončení: cílené i celkové testy a ověření vytvoření/otevření na zařízení. Cílové ověření zatím neprovedeno v tomto běhu; testové výsledky doplnit níže.

- [ ] [planned] **M1-AH-06 — Lokální správa uživatelů a federace (implemented, 2026-09-13).** Explicitní požadavek uživatele navázat správou uživatelů s ohledem na federaci a správou federace. Individuální klíče, stabilní user/home-node UUID, lokální node role, projektová členství, deaktivace/rotace, UI správy a Git registr s CAS; credentials mimo Git. Peery pending/approved/revoked, pin ověřený správcem. [Kontrakt, recovery a reuse](docs/administration.md), rozšíření ADR 0020. Cílová úroveň: PoC validated. Podmínka dokončení této části: testy autentizace/ACL/revokace/CAS/přerušené publikace a cílová akceptace UI. Síťový handshake, distribuce identit/revokací a Git synchronizace nejsou implementované a zůstávají M5; toto neuzavírá Gate M5 ani nezavádí důvěru automaticky. Cílový deploy zatím nebyl proveden v tomto běhu.

Ověření M1-AH-05/M1-AH-06 (2026-09-13): závěrečná sada `python3 -m unittest discover -s tests -v` mimo socketově omezený sandbox — **171 testů, 151 prošlo, 20 volitelných přeskočeno, bez chyb**, 46,249 s. Ověřeny HTTPS individuální klíče, filtrovaný katalog a otevření jen přiděleného projektu, odmítnutí administrace/vytvoření běžným členem, rotace/deaktivace, stejný receipt po retry, restart registru, stale CAS, credentials mimo Git, osiřelá credential a selhání rotace před změnou ref se zachováním původního klíče, peer approval/revocation a omezení node-admin. Starší deploy reset test opraven: neodkazuje na pevný index SSH volby místo vzdáleného skriptu. Samostatný skutečný Qt/WebEngine login/katalog/logout prošel; další skutečný browser smoke v dočasném serveru prošel vytvořením/otevřením projektu, vydáním uživatelského klíče a přidáním/schválením/odvoláním testovacího peeru. JS syntaxe a jedinečnost HTML ID ověřeny. Volitelné balicí/offline/desktop/libgit2 testy nebyly v celkovém běhu zapnuté; samostatné browser ověření nenahrazuje všechny přeskočené testy. Cílová akceptace na routeru a skutečná federovaná synchronizace nejsou doložené; položky zůstávají otevřené do vymezené cílové akceptace.

Aktualizace M1-07 podle hlášení uživatele (2026-09-13): deploy již proběhl, web běží v LXC i přes routerovou dlaždici a stránka se načítá; dřívější SSH blokace níže je historická. Tyto údaje jsou uživatelské potvrzení, nikoli nové agentní real-device ověření. Restart/změna IP a ostatní akceptační scénáře zůstávají otevřené.

Aktualizace M1-07 podle hlášení uživatele (2026-09-17): restart routeru zachoval instalaci a data, ale kontejner `workspace-m0` se po bootu nespustil automaticky. Jde o částečný real-device důkaz persistence, nikoli splnění restartové akceptace. Doplnit bezpečný LXC autostart a zopakovat reboot bez ručního startu včetně služby uvnitř kontejneru, dlaždice, přihlášení a náhledu.

- [ ] [planned] **M1-07 — LXC webové nasazení a dlaždice na routeru (cílová úroveň: PoC validated).** Navazuje na otevřené LXC nasazení v souhrnném M1; požadavek uživatele z 2026-09-10 doplňuje dlaždici aplikace na uvítací stránce routeru. Implementace je lokálně hotová (`TODO` + ADR + unit testy), cílové ověření čeká na reálné zařízení. Výchozí stav před M1-07: `scripts/deploy_omnia.py` instaloval pouze headless demo, bez webové služby a dlaždice; síťové zpřístupnění musí řešit autentizaci a hranice přístupu podle ADR 0013. Dokončit real-device runbook včetně: SSH ověření routeru, dry-run, produkční deploy bez `--dry-run`, ověření otevření aplikace z dlaždice (login + katalog + náhled), restart/redeploy/retry scénářů, změna IP, restart LXC i routeru, zastavení kontejneru, opakované nasazení a odstranění integrace bez poškození ostatních dlaždic.

Ověření cílového prostředí (2026-09-13): SSH přístup k cílovému routeru zatím blokuje `Permission denied (publickey,password,keyboard-interactive)`, změna cílové cesty už byla dočasně potvrzena v `docs/lxc-web.md` a v `scripts` kódu. Do odblokování SSH a prvního nasazení zůstává celá položka otevřená.

Průběžný výsledek M1-07 (2026-09-10, implemented): připraven opt-in HTTPS náhled, přístupový klíč mimo Git, ochrana local-only, bootstrap persistentní identity, systemd nasazení s rollbackem a samostatná routerová dlaždice s dynamickým LXC rozlišením a ověřením TLS. [Návod](docs/lxc-web.md), [ADR 0020](docs/adr/0020-lxc-web-viewer.md). Web zatím pouze čte; nativní editor/tvorba/historie nemají webovou náhradu. Skutečné nasazení a cílová akceptace zůstávají otevřené: SSH přístup k uživatelem určené výchozí bráně jako root byl odmítnut (`Permission denied (publickey,password,keyboard-interactive)`). Na router nebyly přeneseny soubory ani provedeny změny; stav jeho WebApps/Python/LXC a certifikátů nebyl ověřen. Po obnovení SSH přístupu ověřit prostředí a připravit konkrétní nasazení; samostatně doložit restart/změnu IP a ostatní cílové scénáře. Gate M1 zůstává otevřený.

Ověření M1-07 (2026-09-10): závěrečný běh `M0_DESKTOP_TEST=1 M0_DEB_TEST=1 M0_OFFLINE_TEST=1 python3 -m unittest discover -s tests -v` — **158 testů, 154 prošlo, 4 přeskočeny, bez chyb**, 97,839 s. Testován základ `c2768120bddf5330fee7e90c04ba2d8cf40e191a` plus necommitnuté změny M1-07; nejde o výsledek samotného tohoto commitu. Skutečné Qt/WebEngine včetně webového přihlášení/katalogu/odhlášení, izolovaná instalace/upgrade/odstranění `.deb` a offline testy běžely. Přeskočeny pouze čtyři testy `test_git_comparison` pro nativní libgit2 probe (CAS/restart, clone/merge, HTTP autentizace a nevalidní projekce); bez sestaveného probe zůstávají neověřené. Nové testy ověřují HTTPS/Host/Origin/token, skutečné přesměrování a odmítnutí chybějící CA, ochranu local-only se skutečným Gitem, opakovaný bootstrap identity, změny adres a nedostupnost LXC, opakovanou instalaci/odebrání a návrat souborů při chybě; LXC instalační rollback je ověřen vykonáním shellu s nahrazenými systémovými příkazy, nikoli na skutečném systemd/LXC. První úplný běh odhalil chybějící nový návod v balicím fixture; opraveno a závěrečný běh výše prošel. Ověřena syntaxe JS, shellové instalační plány, lokální odkazy, obsah source allowlistu, finální diff a `git diff --check`. Cílové TLS, procd/lighttpd, restart routeru a změna IP na zařízení zůstávají neověřené; odblokování vyžaduje funkční SSH přístup k potvrzenému routeru a připravené TLS podklady podle návodu.
