# Architektura — pracovní návrh M0

## Hranice systému

Jeden uzel je samostatný backend s lokálními daty. Desktop spouští stejný backend jako server a přidává obal UI. První desktopový cíl pro ověření je Linux; Windows a macOS vyžadují samostatné ověření balení.

Výchozí návrh má jeden backendový proces a moduly Project/Artifact, GitStore, MetadataIndex, Identity/RBAC, Federation, BackendRegistry, ContextBuilder a Workflow. UI používá aplikační služby přes verzované API. Konkrétní jazyk a framework zůstávají otevřené.

## Data a zápis

Git drží projektové artefakty, jejich metadata, registry a schválené LLM výstupy. SQLite indexuje pouze validovaný commit. Identita uzlu, credentials a rozpracované operace jsou lokální autoritativní stav mimo projektový Git i index.

Jeden zapisující proces serializuje operace nad projektem. Návrh toku: validace vstupu → zápis s obnovitelným záznamem operace → validace projektu → commit → transakční aktualizace indexu. Pád po commitu se řeší obnovou indexu z HEAD. Pro pád před commitem je nutné ještě implementovat journal a obnovu; samotný commit nestačí.

Index musí nést commit ID. Dotazy při nesouladu vracejí stav obnovy, nikoli tiše stará data. Necommitnuté změny má editor zobrazovat odděleně. Synchronizace se připravuje v izolovaném pracovním prostoru a publikuje až po validaci a kontrole nezměněného výchozího HEAD.

## LLM rozhraní

Backend: ID, provider, model, capabilities, privacy policy, lokální odkaz na credentials. Role: ID, prompt template, povolené zdroje, požadovaný výstup a preference backendu. Běh: uživatel, role, backend, konkrétní verze vstupů, kontextový manifest, výsledek a stav schválení.

Backend adapter poskytuje capabilities a generate(request); ContextBuilder aplikačně kontroluje RBAC a privacy ještě před voláním. `local-only` se nepřenáší ani na jiný federační uzel bez explicitní změny klasifikace. Vzdálený backend není dostupný offline. Úloha nesmí být automaticky zopakována s potenciálními externími náklady po restartu.

## Stav implementace

`spikes/storage.py` je izolovaný experiment nad řízenými testovacími repozitáři. Neobsahuje produkční API, autentizaci, import cizích repozitářů ani úplný datový validátor. Produkční nasazení není připraveno.
