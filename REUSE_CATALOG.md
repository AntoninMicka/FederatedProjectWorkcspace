<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Veřejný katalog reuse

Katalog verzovaný v Gitu obsahuje technologie, komponenty tohoto workspace a pouze externí zdrojové repozitáře s ověřenou veřejnou dostupností.

## Externí zdrojové repozitáře

Zatím žádné. Před zařazením uvést veřejnou URL, ověřit přístup bez přihlášení a zaznamenat licenci, revizi a důvod reuse/adapt/reject. Samotná veřejná dostupnost neznamená oprávnění k převzetí kódu.

Soukromou lokální inventuru drží volitelný soubor `REUSE_CATALOG.private.md`, ignorovaný Gitem. Jeho absence v čerstvém klonu je očekávaná. Lokální cesty, neveřejné názvy repozitářů a podrobnosti jejich posouzení se do verzovaných dokumentů nepřenášejí.

## Technologie a závislosti

| Kandidát | Stav | Účel | Co zbývá ověřit |
| --- | --- | --- | --- |
| Git CLI | adapt (výchozí adapter, ADR 0005) | Referenční storage a Workspace; reuse wrapperu, vlastní staging a compare-and-swap podle ADR 0003 | Produkční izolace, autentizace, cílové balení |
| libgit2 / C++ | evaluate (PoC validated) | Ověřená alternativa, `spikes/libgit2/probe.cpp`, ADR 0005 | Runtime 1.9.1 dostupný; chybějící dev headers rozbaleny do /tmp. Produkční port Workspace, cílové balení a TLS/SSH neověřeny |
| Python stdlib SQLite | adapt (M0/M1 PoC) | Obnovitelný relační projektový index (`spikes/storage.py`, ADR 0022) a oddělený autoritativní lokální journal rozpracovaných operací (`spikes/journal.py`), viz ADR 0002 | Koordinace ověřena v Workspace (ADR 0003); ověření metadat/vztahů ve [WORK_LOG](WORK_LOG.md#f-m1-index-01--relační-projekce-projektového-indexu--2026-09-15), zbývá produkční integrace, výkon a paměť na Turrisu |
| PyYAML 6.0.3 | approved | Omezený frontmatter parser v M0 | Produkční release: doplnit evidence licenčních textů/notice pro všechny distribuované třetí strany; aktuálně je pro PyYAML 6.0.3 v M1 audit potvrzen jako MIT-approved (2026-09-10). |
| Qt / WebView | candidate | Desktopový obal sdíleného UI | Distribuce, IPC, paměť |

Nad rámec komponent najdeš evidenci compliance závislostí v [docs/legal/DEPENDENCIES.toml](docs/legal/DEPENDENCIES.toml).

Žádná komponenta zatím nemá schválený produkční status reuse. Licence a verze závislostí zaznamenat před zařazením do distribuované aplikace.

M0-01 adaptuje existující `spikes/journal.py`, `spikes/storage.py` a jejich testy: zachovává validátor, fsync/recovery a commitovou projekci, přidává trvalý operation record a nadřazený zámek. Rewrite by opakoval ověřený PoC.

Shellový launcher adaptuje existující unittest příkaz a `spikes.check_project`; dočasné demo používá `Workspace`/`Git` přímo. Nevytváří další storage implementaci ani aplikační server.

M0-02 adaptuje omezený JSON parser a UUID/timestamp validaci z `spikes/metadata.py`; schéma konfigurace přidává v `spikes/configuration.py`. Sdílené primitivy omezují rozcházení pravidel s artefakty; další parser ani závislost nejsou potřeba.

M0-03 adaptuje existující storage/index testovací scénáře; C++ probe je nová minimální testovací vazba přímo na libgit2, nikoli kopie cizího adapteru. Důvod zachování Git CLI a náklady případného přenosu koordinace jsou v [ADR 0005](docs/adr/0005-git-adapter-comparison.md).

## Již používané vlastní komponenty

Zdrojem je tento repozitář, základ průzkumu `384370e`. Závislosti: Python 3.11+, stdlib včetně sqlite3 a Linux fcntl, Git CLI; jediná deklarovaná pip závislost je PyYAML 6.0.3 v [requirements.txt](requirements.txt). Bash zajišťuje launcher. C++17/libgit2 je volitelný srovnávací experiment podle [ADR 0005](docs/adr/0005-git-adapter-comparison.md).

| Komponenta / zdroj | Rozhodnutí a důvod | Důkazy a omezení |
| --- | --- | --- |
| [Validace metadat](spikes/metadata.py) | **adapt**: společný omezený JSON/YAML parser, UUID a vztahy; nepřidávat další parser | [Testy](tests/test_metadata.py); V-04/V-05: kontrakt provenance a neměnnost zdrojů |
| [Journal](spikes/journal.py) a [Workspace](spikes/workspace.py) | **adapt**: zachovat společnou serializaci a obnovitelnou operaci | [ADR 0003](docs/adr/0003-coordinated-operation.md), [testy](tests/test_workspace.py); V-06/V-07: produkční ochrany a lifecycle |
| [Git a SQLite index](spikes/storage.py) | **adapt**: validovaný commit a atomický rebuild relační projekce místo druhé autority | [Testy](tests/test_storage.py), [relační testy](tests/test_index_projection.py), [ADR 0022](docs/adr/0022-relational-index.md); F-M1-INDEX-01/V-03: ověření a omezení ve [WORK_LOG](WORK_LOG.md#f-m1-index-01--relační-projekce-projektového-indexu--2026-09-15) |
| [Konfigurace](spikes/configuration.py) | **adapt**: sdílená validační primitiva, oddělený projekt a uzel | [ADR 0004](docs/adr/0004-project-node-config.md), [testy](tests/test_configuration.py); V-08: zapojení do lifecycle |
| [Launcher](run.sh), [demo](spikes/demo.py), [check_project](spikes/check_project.py), [check_config](spikes/check_config.py) | **reuse** v nynějším vývojovém workflow | Příkazy v [README](README.md), důkazy ve [WORK_LOG](WORK_LOG.md); [BACKLOG](BACKLOG.md) V-01: automatizace CLI validátoru; není to aplikační server/UI |

Stavy těchto komponent jsou implemented / PoC validated dle odkazovaných ADR a WORK_LOG. Tento dokument nezaznamenává nový běh testů ani novou volbu stacku. Navazující úkoly drží TODO/BACKLOG, výsledky ověření WORK_LOG.

M0-04 **adaptuje** omezený JSON parser z `spikes/metadata.py` a **reuse** stdlib HTTP/socketserver pro izolovaný [transportní experiment](spikes/local_api.py). Vlastní minimální handler odděluje zkoušku autentizace od aplikačního stacku; nejde o přenos cizího serveru ani produkční volbu frameworku. Rozhodnutí a limity: [ADR 0006](docs/adr/0006-local-api-transport.md).

M0-06a **adaptuje** `spikes/local_api.py` s odděleným statickým UI handlerem a **evaluate** systémový PyQt6/Qt WebEngine pro desktopový PoC. Důvodem je dostupný binding a zachování Python backendu bez portu či dalšího aplikačního procesu. Ověření a licenční/distribuční omezení: [ADR 0007](docs/adr/0007-desktop-poc.md); produkční Qt binding zatím není vybrán.

Ruční deploy **reuse** existující `spikes.demo` a requirements; **adapt** launcheru přidává transport omezeného archivu a oddělená vydání bez nové storage implementace. Aktualizace current nastává až po úspěšném demu; vzdálené ověření zůstává M0-05.

M1-07 **adapt/reuse** Projects, Workspace, statického UI, HTTP validačního handleru, ručního deploye a licenčního allowlistu; síťový režim přidává kontrolu local-only nad čteným commitem. Nový vlastní routerový helper používá LXC CLI a registrační formát [Turris WebApps](https://gitlab.nic.cz/turris/webapps/-/blob/master/README.md), ověřený 2026-09-10. Soukromá inventura posloužila k posouzení integračních vzorů, žádný externí aplikační kód ani asset se nepřenášel. Nový framework není pro omezený LAN náhled potřebný; nejde o produkční server. Hranice, TLS a recovery: [ADR 0020](docs/adr/0020-lxc-web-viewer.md).

F-M2-CONTEXT-01 **adaptuje** existující `Workspace` writer lock, validaci
projektového snapshotu, Git commit identity a omezený `require`/UUID kontrakt.
Context Manifest a kanonický payload jsou nový malý stdlib modul; další storage,
vektorová databáze ani externí framework nejsou potřeba. Modul je read-only a
nepředstírá backend adapter, RBAC službu ani durable run recovery; ty zůstávají
navazujícími schopnostmi podle ADR 0008.

F-M2-OLLAMA-01 **adaptuje** Context Builder `Target` a validační primitiva;
endpoint parsing používá pouze Python stdlib `urllib.parse` a `ipaddress`.
PoC nezavádí discovery knihovnu ani obecný HTTP framework: číselné adresy a
explicitní TLS pin jsou záměrná ochrana před DNS rebindingem. Transport musí
zakázat redirect a ověřit skutečný socketový cíl. Adapter používá stdlib
`http.client`, `ssl` a autoritativní lokální SQLite run journal; nevytváří další
projektové úložiště ani implicitní retry/fallback vrstvu. Perzistence bindingu
adaptuje stejný bezpečný vzor node-local stavu: omezená oprávnění, bounded read,
striktní revalidace a atomické nahrazení po `fsync`; není obnovitelným projektovým
indexem ani synchronizovanou konfigurací.

F-M2-CHAT-01 **adaptuje** bezpečnostní vzor node-local SQLite run journalu,
striktní UUID/text/privacy validaci Context Builderu a jeho explicitní výběr
přesných bajtů. Thread store je samostatná autorita pro vlákna, zprávy a turny;
nesmí sdílet tabulky ani recovery s obnovitelným projektovým indexem a nesmí
předstírat atomickou transakci s backendovým run storem. Vazba přes stabilní run
ID a idempotentní reconciliation řeší crash boundary bez externí databáze či
message-queue závislosti. Implementovaný `spikes/chat_threads.py` používá stdlib
SQLite jako samostatný node-local store; UI draft se nereusuje jako persistentní
zpráva.

F-M2-CHAT-02 **reuse/adaptuje** `ChatThreads`, standardní artifact metadata,
`Artifacts` a jediný `Workspace`/Journal/Index lifecycle. Projektový full/delta
otisk je validovaný Markdown snapshot v existujícím Gitu, nikoli nová databáze
nebo content-addressed storage; editovatelný výstup zůstává běžný Markdown
document. Obecné Git utility se nepřebírají, protože nenahrazují explicitní
vlastněné cesty, expected HEAD, kandidátní validaci a recovery ADR 0003.

F-M2-SUMMARY-01 **reuse/adaptuje** Context Builder a jeho dvoufázovou
revalidaci, `OllamaBindings`/`OllamaAdapter`/`OllamaRuns`, Workspace a běžný
Markdown document lifecycle. Backendově neutrální task/preview journal adaptuje
striktní node-local SQLite vzor `ChatThreads`, ale zůstává samostatnou autoritou
a nesdílí chatové tabulky ani projektový index. Kanonická provenance obálka a
její transition ochrana adaptují `fpw-chat-output-v1`. Soukromá inventura byla
zohledněna bez přenosu názvů či cest: obecné backendové utility nemají potřebný
Context Manifest, aplikační autorizaci ani recovery a jejich licence nejsou pro
převzetí doložené. Nová vektorová DB, RAG, message queue, externí parser či
framework nejsou pro explicitní summarizer v1 potřebné.

F-M2-META-AI-01 **reuse/adaptuje** Context Builder, same-node Ollama lifecycle,
striktní JSON/metadata validaci, oddělený task/preview vzor extractoru a jediný
Workspace/Journal/Index metadata commit. Editorový `Artifacts.save` je zdroj
ověřeného metadata patch vzoru, ale nepoužije se přímo, protože vyžaduje
Markdown body a nepokrývá source artefakty ani vazbu na potvrzený AI preview.
Nová databáze, tagovací knihovna, schema framework, RAG či externí klient nejsou
pro explicitní návrh jednoho artefaktu potřeba.

F-UX-SETTINGS-01 **reuse/adaptuje** existující bezpečně vykreslovaný DOM,
autentizované same-origin API, `ChatService.configure/status` a atomicky ukládaný
node-local `OllamaBindings`. Formulář se přesune, nebude duplikován a nevznikne
druhá autorita konfigurace, projektový zápis, databáze ani UI knihovna.

F-M3-BACKEND-01-A **reuse/adaptuje** `ContextBuilder.Target` a
`DispatchHandoff`, striktní `OllamaBinding`, právě-jednou hranici
`OllamaAdapter`/`OllamaRuns` a existující role služeb. Společný kontrakt bude
malé interní Python rozhraní a registr, ne nový framework, SDK, routing service
ani storage. Soukromá inventura byla znovu posouzena: dostupné obecné backendové
abstrakce mohou posloužit jen jako srovnání tvaru capabilities; nepřebírají se,
protože nedokládají Context Manifest, aplikační privacy autorizaci, přesnou
identitu bindingu ani durable `unknown` recovery. Existující Ollama kód se
adaptuje za provider-neutral rozhraní bez kopie transportu a bez automatického
fallbacku. Rozhodnutí a kompatibilní migrace: [ADR 0008](docs/adr/0008-context-and-publication-contracts.md#provider-neutral-aplikační-kontrakt-v1).

F-M3-EXTERNAL-01-A **adaptuje pouze ověřené koncepty**, nikoli cizí kód:
soukromá inventura obsahuje obecné backendové capability, textový a obrazový
adapter i prioritní pool, ale nedokládá licenci pro převzetí a postrádá Context
Manifest, explicitní privacy autorizaci, přesný target a durable `unknown`
recovery. Automatický výběr prvního dostupného backendu, odhad capabilities z
názvu modelu, převod chyb na prázdný výsledek a stahování libovolné URL se
odmítají. První textový adapter se napíše nad společným interním kontraktem a
aktuálním oficiálním [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create);
obrazová capability zůstává oddělená podle [Images API](https://developers.openai.com/api/reference/resources/images/methods/generate).
Ze soukromého adapteru se později adaptoval pouze koncept explicitního načtení
seznamu přes oficiální [Models API](https://developers.openai.com/api/reference/resources/models/methods/list):
nová implementace je bounded, fail-closed, cachovaná mimo Git a neodvozuje
capability pouze z názvu. Seznam je pomůcka UI a nemění binding bez potvrzení.
Bez doložené kompatibilní licence se ze soukromého zdroje nekopíruje žádný kód.
Rozhodnutí: [ADR 0008](docs/adr/0008-context-and-publication-contracts.md#první-externí-provider-a-řízený-návrh-volání).

M0-06b **reuse** stávající launcher a desktopový kód ve zdrojovém archivu. Samostatný allowlist zdrojové distribuce zahrnuje testy a veřejné dokumenty; užší allowlist Omnia deploye zůstává oddělený, protože nepřenáší celý vývojový balíček. Nezavádí se bundler ani kopie Qt runtime.

M0-07 **adaptuje** existující storage scénáře a fixtures, **reuse** Git/Index/validate_snapshot. Nové případy ověřují konflikt páru obsah/sidecar a sémantickou validaci bez dalšího Git adapteru nebo kopírování cizí synchronizační vrstvy.

M0-06c **adapt**: doporučení zachovat Python/Git/SQLite a Qt UI, ověřit PySide6 místo portu jádra. **Evaluate** systémové závislosti a .deb; runtime bundler odložen do doložené potřeby. Důvody, oficiální licenční podklady a neověřené části jsou v [ADR 0009](docs/adr/0009-desktop-distribution-assessment.md).

M0-06d **adaptuje** stávající Qt obal na PySide6 a shiboken6; sdílené UI/API beze změny. Použity distribuční binding moduly rozbalené do /tmp, bez převzetí cizího aplikačního kódu. Ověření a měření: [ADR 0010](docs/adr/0010-pyside-desktop-validation.md).

Instalační .deb **reuse** stávající spikes a systémové dpkg-deb; **adapt** vzoru úplného dočasného artefaktu s hardlink publikací. Balík má užší runtime allowlist než zdrojový archiv; neobsahuje další kopii Qt ani instalační framework. Viz [ADR 0011](docs/adr/0011-debian-package.md).

Offline test **reuse** .deb builder a existující WebEngine smoke, **adapt** Linux unshare/setpriv/ip pro oddělenou síť s lokálním X11 socketem. Nezavádí druhý desktop ani produkční sandbox; hranice v ADR 0011.

M0-06 uzavírá **adapt/reuse** Python/Git CLI/SQLite a PySide6 pro M1 dle [ADR 0013](docs/adr/0013-m1-stack.md). C++ port ani hybrid se bez doloženého problému nezahajují. Produkční status reuse tím není přiznán.

Cílový probe **adaptuje** scénář z `tests/test_workspace.py` a dvojici obsah/sidecar z testových fixtures; **reuse** Workspace, Git a snapshot. Samostatný modul ve spikes lze přenést stávajícím deploy allowlistem bez rozšíření přístupu na jiná data nebo přidání nové storage vrstvy. Měření rozlišuje čas celé pomocné operace a apply/recover; Python RSS není součet všech procesů.

M1-01 **adaptuje** konfiguraci v1, Workspace/Index a autentizovaný lokální handler. Služba Projects pouze propojuje existující validaci a koordinované čtení; nepřebírá cizí storage/API framework. UI používá stávající PySide obal a bezpečné textové vykreslení. Soukromá inventura nepřidává pro tento omezený krok potřebnou komponentu; žádný externí kód nebyl kopírován. Kontrakt: [ADR 0014](docs/adr/0014-project-read.md).

M1-02 **adaptuje** Git, Workspace, konfigurační validátory a fsync/flock vzor journalu. Nový uzlový journal řídí inicializaci a registraci (odlišný lifecycle od změn artefaktů); neslouží jako druhý projektový index. **Reuse** nativních Qt dialogů zachovává jeden aplikační proces a neotevírá rendereru mutující API. Přenos cizího frameworku ani komponenty z lokální inventury není pro tento kontrakt potřebný. [ADR 0015](docs/adr/0015-project-creation.md).

M1-03 **adaptuje** Workspace transakce o stabilní ID/digest požadavku, Projects o sdílený autorizovaný přístup a nativní Qt widgets o Markdown editor/checklist panel. **Reuse** Git/Index, metadatových validátorů a lokálního autora z ProjectCreation. Hlavní TODO používá rezervované UUIDv5 uvnitř existujícího schématu; nová storage ani cizí editor nejsou potřeba. [ADR 0016](docs/adr/0016-markdown-editor.md).

M1-03a **reuse/adapt**: společné čisté Markdown funkce z editoru přesunuty do `spikes/markdown_documents.py`, čtení TODO rozšiřuje existující Workspace snapshot a autentizovaný projektový přehled. HTML details/summary poskytují sbalitelné větve bez nové knihovny, parseru nebo mutujícího endpointu. [Kontrakt](docs/adr/0016-markdown-editor.md).

M1-04 **reuse/adapt**: ArtifactHistory používá autorizovaný Workspace, Git wrapper, validaci snapshotu a sdílený Markdown document reader. Qt historie reuse EditorWorker a readonly textové widgety. Git diff pracuje jen s adresářem vybraného UUID bez externích driverů; historické project.json používá stejný validátor se samostatným ověřením dnešní konfigurace. Žádná další storage/framework ani externí komponenta není potřebná. [ADR 0017](docs/adr/0017-artifact-history.md).

M1-03b **reuse/adapt**: záložky levého panelu používají stejný `result.artifacts` a `main_todo` ze stávajícího projektového čtení. DOM textContent zachovává bezpečné vykreslení názvů/ID, ARIA záložky doplňují klávesnicové přepínání. Bez další knihovny, API, parseru nebo zápisové cesty.

F-M1-DELETE-01/M1-08 **reuse/adapt** existujícího odstranění v Artifacts, Workspace/Journal/Index a nativního potvrzení Qt. Samostatné [akceptační testy](tests/test_artifact_deletion.py) rozšiřují ověření o odstranění sidecar/frontmatter a procesní recovery bez nové storage nebo knihovny. Kontrakt ADR 0003/0016 se nemění; výsledky drží [WORK_LOG](WORK_LOG.md#f-m1-delete-01--ověření-bezpečného-odstranění-dokumentu--2026-09-15).

F-M1-META-01/V-04 **reuse/adapt** současného striktního validátoru metadat, importního request digestu, Git blobů a Workspace/Journal/Index recovery. Designed výstup [ADR 0023](docs/adr/0023-metadata-and-import-provenance.md) nepřidává parser, storage ani externí závislost; zachovává v1 a vyhrazuje novou verzi pro podrobnou importní provenance. Implementace v2 a migrace jsou samostatná navazující feature.

F-M1-SOURCE-01/V-05 **reuse/adapt** nativního importu, validátoru metadat, Git historie, Workspace/Journal/Index a relačních vztahů. [ADR 0024](docs/adr/0024-source-immutability-and-versioning.md) definuje neměnné bajty pod jedním UUID, novou verzi jako nový artefakt a transition validaci bez nové databáze nebo content-addressed storage. Implementace vynucení a UI zůstává navazující feature.
