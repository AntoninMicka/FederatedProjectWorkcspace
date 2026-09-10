# Architektura — pracovní návrh M0

## Hranice systému

Jeden uzel je samostatný backend s lokálními daty. Desktop spouští stejný backend jako server a přidává obal UI. První desktopový cíl pro ověření je Linux; Windows a macOS vyžadují samostatné ověření balení.

Výchozí návrh má jeden backendový proces a moduly Project/Artifact, GitStore, MetadataIndex, Identity/RBAC, Federation, BackendRegistry, ContextBuilder a Workflow. UI používá aplikační služby přes verzované API. Jádro pro M1 používá Python dle [ADR 0013](docs/adr/0013-m1-stack.md); doménové služby jsou nezávislé na HTTP adaptéru. Produkční serverový framework se bude vybírat proti konkrétním požadavkům V-10/M1. Výchozí Git adapter pro navazující implementaci zůstává Git CLI podle [ADR 0005](docs/adr/0005-git-adapter-comparison.md); C++/libgit2 je srovnaná alternativa. Testovací C++ executable nezavádí produkční hybrid ani další backendový proces.

Lokální transportní PoC podle [ADR 0006](docs/adr/0006-local-api-transport.md) porovnává Unix socket a loopback HTTP. Pro sdílené webové UI preferuje HTTP se stejným originem; Unix socket zůstává alternativou pro nativní bridge. Obal PySide6 a nativní předání tokenu jsou ověřeny v ADR 0010; volbu stacku uzavírá ADR 0013. Experiment mění pouze čítač v paměti, není napojen na aplikační služby.

## Data a zápis

Git drží projektové artefakty, jejich metadata, registry a schválené LLM výstupy. SQLite indexuje pouze validovaný commit. Identita uzlu, credentials a rozpracované operace jsou lokální autoritativní stav mimo projektový Git i index.

Jeden zapisující proces serializuje operace nad projektem. Návrh toku: validace vstupu → zápis s obnovitelným záznamem operace → validace projektu → commit → transakční aktualizace indexu. Pád po commitu se řeší obnovou indexu z HEAD. Pro pád před commitem existuje souborový journal a obnova v `spikes/journal.py`. Propojení pro kontrolovaný Linux PoC poskytuje `spikes/workspace.py`: journal drží operaci a kandidátní commit před compare-and-swap posunem větve, payloady maže až po indexaci. Společný zámek chrání apply/recover/read; pending operace blokuje čtení projekce přes Workspace. Podrobnosti a crash boundaries: [ADR 0003](docs/adr/0003-coordinated-operation.md). Produkční aplikační integrace zůstává otevřená.

Index musí nést commit ID. Dotazy při nesouladu vracejí stav obnovy, nikoli tiše stará data. Necommitnuté změny má editor zobrazovat odděleně. Synchronizace se připravuje v izolovaném pracovním prostoru a publikuje až po validaci a kontrole nezměněného výchozího HEAD.

## Odvozená lokální cache

Navržené materializované kompiláty jsou zahoditelné soubory odvozené ze zdrojů podle zachovaného zadání. Výsledky leží mimo projektový Git, neverzují se ani nesynchronizují; aktualizují se ručně. Nejsou projektovým indexem ani autoritativním journalem/run recordem. [ADR 0018](docs/adr/0018-materialized-compilations.md) vymezuje aktuálnost, privacy, obnovu po pádu a explicitní uložení výsledku jako artefaktu. Stav je designed, bez implementace.

## LLM rozhraní

Backend: ID, provider, model, capabilities, privacy policy, lokální odkaz na credentials. Role: ID, prompt template, povolené zdroje, požadovaný výstup a preference backendu. Běh: uživatel, role, backend, konkrétní verze vstupů, kontextový manifest, výsledek a stav schválení.

Backend adapter poskytuje capabilities a generate(request); ContextBuilder aplikačně kontroluje RBAC a privacy ještě před voláním. `local-only` se nepřenáší ani na jiný federační uzel bez explicitní změny klasifikace. Vzdálený backend není dostupný offline. Úloha nesmí být automaticky zopakována s potenciálními externími náklady po restartu.

## Stav implementace

`spikes/storage.py` je izolovaný experiment nad řízenými testovacími repozitáři. Neobsahuje produkční API, autentizaci ani import cizích repozitářů. Minimální schémata konfigurace projektu/uzlu validuje samostatně `spikes/configuration.py` podle [ADR 0004](docs/adr/0004-project-node-config.md); nejsou zatím napojena na storage lifecycle. Artefakty a registry již používají společný validátor v `spikes/metadata.py`. Produkční nasazení není připraveno.

Desktopové PoC spouští `./run.sh desktop`: Qt/WebEngine obal a backendové vlákno ve stejném Python procesu, token předán přímo nativnímu request interceptoru. Viz [ADR 0007](docs/adr/0007-desktop-poc.md). Jde o ověřený lifecycle statického UI a paměťového API; PySide6 a .deb jsou zvolený základ pro M1 dle ADR 0013; napojení projektových služeb a veřejný release zůstávají otevřené.

## Kontrakty M0-08

Závazné návrhové kontrakty Backend/Role/Context Manifest a tok deterministického orchestrátoru vymezuje [ADR 0008](docs/adr/0008-context-and-publication-contracts.md). Odděluje přenositelnou definici od lokálního bindingu, capabilities od execution boundary a ukládá manifest přesného požadavku mimo Git. Implementace LLM a RBAC zůstává otevřená.

Posouzení distribuční cesty v [ADR 0009](docs/adr/0009-desktop-distribution-assessment.md) doporučuje zachovat Python jádro a ověřit PySide6/WebEngine s nativním linuxovým balíkem. Toto původní doporučení následně ověřily ADR 0010–0012 a jako základ pro M1 přijímá ADR 0013.

Desktopové PoC nyní používá PySide6 dle [ADR 0010](docs/adr/0010-pyside-desktop-validation.md). Přechod zachovává API a životní cyklus; historický PyQt experiment ADR 0007 zůstává podkladem návrhu.
