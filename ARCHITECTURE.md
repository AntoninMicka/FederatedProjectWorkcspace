# Architektura — pracovní návrh M0

## Hranice systému

Jeden uzel je samostatný backend s lokálními daty. Desktop spouští stejný backend jako server a přidává obal UI. První desktopový cíl pro ověření je Linux; Windows a macOS vyžadují samostatné ověření balení.

Výchozí návrh má jeden backendový proces a moduly Project/Artifact, GitStore, MetadataIndex, Identity/RBAC, Federation, BackendRegistry, ContextBuilder a Workflow. UI používá aplikační služby přes verzované API. Konkrétní jazyk a framework zůstávají otevřené. Výchozí Git adapter pro navazující implementaci zůstává Git CLI podle [ADR 0005](docs/adr/0005-git-adapter-comparison.md); C++/libgit2 je srovnaná alternativa. Testovací C++ executable nezavádí produkční hybrid ani další backendový proces.

Lokální transportní PoC podle [ADR 0006](docs/adr/0006-local-api-transport.md) porovnává Unix socket a loopback HTTP. Pro sdílené webové UI preferuje HTTP se stejným originem; Unix socket zůstává alternativou pro nativní bridge. Obal a bezpečné předání tokenu uzavře M0-06. Experiment mění pouze čítač v paměti, není napojen na aplikační služby.

## Data a zápis

Git drží projektové artefakty, jejich metadata, registry a schválené LLM výstupy. SQLite indexuje pouze validovaný commit. Identita uzlu, credentials a rozpracované operace jsou lokální autoritativní stav mimo projektový Git i index.

Jeden zapisující proces serializuje operace nad projektem. Návrh toku: validace vstupu → zápis s obnovitelným záznamem operace → validace projektu → commit → transakční aktualizace indexu. Pád po commitu se řeší obnovou indexu z HEAD. Pro pád před commitem existuje souborový journal a obnova v `spikes/journal.py`. Propojení pro kontrolovaný Linux PoC poskytuje `spikes/workspace.py`: journal drží operaci a kandidátní commit před compare-and-swap posunem větve, payloady maže až po indexaci. Společný zámek chrání apply/recover/read; pending operace blokuje čtení projekce přes Workspace. Podrobnosti a crash boundaries: [ADR 0003](docs/adr/0003-coordinated-operation.md). Produkční aplikační integrace zůstává otevřená.

Index musí nést commit ID. Dotazy při nesouladu vracejí stav obnovy, nikoli tiše stará data. Necommitnuté změny má editor zobrazovat odděleně. Synchronizace se připravuje v izolovaném pracovním prostoru a publikuje až po validaci a kontrole nezměněného výchozího HEAD.

## LLM rozhraní

Backend: ID, provider, model, capabilities, privacy policy, lokální odkaz na credentials. Role: ID, prompt template, povolené zdroje, požadovaný výstup a preference backendu. Běh: uživatel, role, backend, konkrétní verze vstupů, kontextový manifest, výsledek a stav schválení.

Backend adapter poskytuje capabilities a generate(request); ContextBuilder aplikačně kontroluje RBAC a privacy ještě před voláním. `local-only` se nepřenáší ani na jiný federační uzel bez explicitní změny klasifikace. Vzdálený backend není dostupný offline. Úloha nesmí být automaticky zopakována s potenciálními externími náklady po restartu.

## Stav implementace

`spikes/storage.py` je izolovaný experiment nad řízenými testovacími repozitáři. Neobsahuje produkční API, autentizaci ani import cizích repozitářů. Minimální schémata konfigurace projektu/uzlu validuje samostatně `spikes/configuration.py` podle [ADR 0004](docs/adr/0004-project-node-config.md); nejsou zatím napojena na storage lifecycle. Artefakty a registry již používají společný validátor v `spikes/metadata.py`. Produkční nasazení není připraveno.

Desktopové PoC spouští `./run.sh desktop`: Qt/WebEngine obal a backendové vlákno ve stejném Python procesu, token předán přímo nativnímu request interceptoru. Viz [ADR 0007](docs/adr/0007-desktop-poc.md). Jde o ověřený lifecycle statického UI a paměťového API; volba produkčního bindingu/balíku a napojení projektových služeb zůstávají otevřené.
