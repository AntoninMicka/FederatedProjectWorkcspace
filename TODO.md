<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-SEARCH-01 — Řízené webové hledání přes SearXNG

Aktivní feature dávka navazuje na doručení `F-M3-OLLAMA-STREAM-01` v PR #63
(`develop` `5c3b565`). Práce probíhá na větvi
`feature/f-m3-search-01-searxng`, založené z tohoto commitu, s jediným cílovým
PR do `develop`. Původní požadavek je položka `F-M3-SEARCH-01` z backlogu;
cílová úroveň je **PoC validated**.

## Výstup a hranice rozsahu

Workspace přidá explicitní search capability nad uživatelem nakonfigurovaným
SearXNG endpointem. Task router smí navrhnout `web-search`, ale síťové hledání
proběhne až po aplikační privacy/policy kontrole a vědomém potvrzení přesného
dotazu, cíle a rozsahu. Bounded výsledky se uloží s URL, titulkem, úryvkem,
časem a provenance; následná Ollama syntéza dostane pouze jejich přesné bajty
v novém Context Manifestu.

Mimo rozsah jsou skryté modelové tool-calling, automatické stahování nalezených
stránek, crawler/RAG/embeddings, správa SearXNG kontejneru, automatický fallback
na externí LLM a oslabení `local-only`. Endpoint a execution boundary jsou
node-local konfigurace mimo projektový Git a nesmějí se odvozovat pouze z
dockerového názvu služby.

## Crash/recovery hranice

Search journal v node-local SQLite je autoritou jediného potvrzeného síťového
hledání; projektový Git ani obnovitelný index se nemění. Před durable stavem
`prepared` nevzniká síťový účinek. Přerušení po přechodu do `dispatching` je
`unknown` bez automatického retry. Úspěšné bounded výsledky se uloží před
Ollama syntézou; restart mezi těmito kroky znovu použije stejné výsledky.
Syntéza reuseuje jediný `OllamaRuns` journal a stejný run/manifest, takže pád po
odpovědi nevyvolá druhé modelové volání. Až potom se idempotentně uzavře
`TaskOutcomes`; tato dávka nezapisuje do Workspace journalu ani do Gitu.

## Úkoly

- [x] [completed] **F-M3-SEARCH-01-A — Kontrakt, reuse a konfigurace
  (cílová úroveň: designed).** Ověřit skutečný JSON kontrakt existujícího
  SearXNG, vymezit explicitní binding, privacy, limity, nedůvěryhodné URL/obsah
  a doplnit ADR/reuse rozhodnutí bez přenosu soukromých názvů a cest.
- [x] [completed] **F-M3-SEARCH-01-B — Bounded klient a durable search journal
  (cílová úroveň: implemented).** Přidat strict same-node/private-network
  binding, atomickou konfiguraci, TLS pin pro LAN, timeouty, zákaz redirectu,
  validaci/deduplikaci výsledků a stavy `prepared`/`dispatching`/`succeeded`/
  `failed`/`unknown` bez skrytého retry.
- [x] [completed] **F-M3-SEARCH-01-C — Router, Context Manifest a syntéza
  (cílová úroveň: implemented).** Rozšířit uzavřený task outcome o
  `web-search`, před dispatch znovu ověřit projekt, autoritu, privacy, binding a
  přesné vstupy a předat uložené výsledky jako nedůvěryhodná data roli
  `researcher-v1` přes existující Ollama adapter/run journal.
- [x] [completed] **F-M3-SEARCH-01-D — Společné API a UI potvrzení
  (cílová úroveň: implemented).** V nastavení přidat search binding a probe;
  desktop/web UI musí ukázat přesný dotaz, endpoint, privacy a limit, vyžádat
  potvrzení a bezpečně textově zobrazit odpověď i zdrojové odkazy.
- [ ] [in progress] **F-M3-SEARCH-01-E — Regrese, restart a fyzická akceptace
  (cílová úroveň: PoC validated).** Pokrýt nedostupnost, timeout, redirect,
  neplatný/příliš velký JSON, škodlivý text/URL, nulu a duplicity, změněný
  binding/HEAD, `local-only`, restart po hledání před syntézou a žádný
  automatický retry `unknown`; spustit cílené testy, syntaxe, úplnou sadu a
  skutečný SearXNG + Ollama průchod v dostupném desktopovém UI.
- [x] [completed] **F-M3-SEARCH-01-F — Kompatibilita živého router outputu
  (cílová úroveň: implemented; původ: fyzická akceptace 2026-10-13).** Živá
  Ollama správně zvolila `web-search` a bounded dotaz, ale navzdory povinnému
  Focus ID vrátila `message_ids: []`. Parser nyní pouze pro tento přesný tvar
  doplní aktuální Focus ID; cizí ID, další pole, prázdný externí request a
  ostatní neplatné tvary zůstávají fail-closed. Dokončení vyžadovalo cílenou
  regresi a živé zopakování původního veřejného dotazu přes router i search.
- [x] [completed] **F-M3-SEARCH-01-G — Akční diagnostika chybějícího bindingu
  (cílová úroveň: implemented; původ: fyzická akceptace 2026-10-13).** Druhý
  fyzický průchod korektně připravil `web-search` i durable preview, ale před
  potvrzením už node-local `searxng-binding.json` nebyl přítomný a UI skrylo
  příčinu za obecnou chybou chatu. Preview i confirm nyní vracejí samostatný
  `not-configured` stav s akčním UI: před preview otevře nastavení a po preview
  lze vědomým tlačítkem obnovit přesný binding z kontrolovaného náhledu bez
  nového modelového běhu. Chybějící binding před preview nevytvoří prázdný
  search journal a chybějící binding po preview zachová search v bezpečném
  stavu `prepared` bez síťového účinku.
- [x] [completed] **F-M3-SEARCH-01-H — Nezávislá kontrola webového dotazu
  (cílová úroveň: implemented; původ: fyzická akceptace 2026-10-13).** Přesný
  search preview a jeho obnovovací akce už nejsou uvnitř pevného spodního
  chatového formuláře, kde rozbalený JSON vytlačil celý composer. Kontrola je
  v rolovací části chatu, dlouhý obsah má omezenou výšku a zadání zůstává
  dostupné; regrese kontroluje oddělené umístění obou prvků.

## Aktuální ověření a omezení — 2026-10-13

- Strict transport, binding, router, restart/reuse, lifecycle, API a bezpečné UI
  regrese prošly. Úplná sada po poslední změně: **517 testů OK, 24 volitelných
  přeskočeno**. `python3 -m py_compile` pro dotčené moduly a `git diff --check`
  jsou bez chyby.
- Izolovaný živý `scripts/searxng_search_smoke.py` prošel proti dostupnému
  SearXNG `127.0.0.1:8888` a Ollamě `127.0.0.1:11434`: stav `completed`, model
  `gemma4:latest`, 3 bounded zdroje a 911 znaků syntézy. Stejný smoke nepoužil
  projektová ani uživatelská data.
- Po zjištění F doplnil stejný smoke volitelný skutečný task-router průchod.
  Přesný dotaz `vyhledej výsledky voleb podzim 2026` prošel s
  `--route-through-model` do stavu `completed`, se 3 bounded zdroji a 1 257
  znaky syntézy; původní uživatelský projekt ani vlákno test neměnil.
- Skutečný Qt/WebEngine start, autentizovaný fetch, interakce a restart prošly
  přes opt-in desktop smoke. Konkrétní celý search preview → potvrzení → výsledek
  ale ještě nebyl uživatelem fyzicky proklikán v desktopovém okně; proto zůstává
  E otevřené, cílová úroveň **PoC validated** ani PR zatím nejsou uzavřené.

## Akceptační podmínky

- Bez potvrzení přesného preview neodejde search dotaz; `local-only` je vždy
  odmítnuto před sítí a žádný provider/fallback se nevolí skrytě.
- Jeden search ID neopakuje neurčitý síťový účinek. Po restartu mezi úspěšným
  hledáním a syntézou se použijí stejné uložené výsledky a stejný Ollama run.
- Do syntézy vstoupí pouze bounded, validované a jako nedůvěryhodné označené
  výsledky; Workspace automaticky neotevírá jejich URL ani nevykonává obsah.
- Konfigurace, search journal, úplný Context Manifest a výsledky před vědomou
  projektovou publikací zůstávají node-local mimo projektový Git.
- Cílené regresní testy, úplná sada, kontroly syntaxe/diffu a skutečný lokální
  SearXNG + Ollama smoke projdou; neprovedený webový či fyzický scénář zůstane
  výslovně uveden jako omezení.
