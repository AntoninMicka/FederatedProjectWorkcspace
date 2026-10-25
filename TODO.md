<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — OPS-NODE-MONITOR-01

Aktivní feature dávka `OPS-NODE-MONITOR-01` vznikla 25. 10. 2026 na větvi
`feature/ops-node-monitor-01` z lokálního `develop` na commitu `f3faf26`.
Cílem jediného PR do `develop` je doplnit omezenou read-only telemetrii uzlu a
doložit skutečný CPU/GPU režim Ollama běhu bez restartu, přepnutí backendu nebo
automatického opakování. Cílová úroveň je **PoC validated**.

Původ: uživatelské zjištění při `F-M4-RESEARCH-WORKFLOW-01`, že Ollama může po
změně prostředí tiše provádět inference pouze na CPU. Rozsah zahrnuje existující
panel Zdroje, explicitní očekávání runtime, same-node a private-network Ollama
diagnostiku, historickou run evidence, testy a fyzickou akceptaci. Nezahrnuje
automatickou nápravu, obecný monitoring server, alerting ani katalog modelů.

## Úkoly dávky

- [x] [completed] **OPS-NODE-MONITOR-01-A — diagnostický kontrakt, provenance
  a recovery (cílová úroveň: designed).** Oddělit živý systémový vzorek od
  historické Ollama run evidence, určit explicitní očekávání CPU/GPU, bounded
  zdroje metrik a stavy `unknown`/CPU/partial-GPU/GPU. Pro same-node i
  private-network binding použít pouze ověřený cílový endpoint; žádná metrika
  nesmí změnit Target, autorizaci ani privacy.
- [x] [completed] **OPS-NODE-MONITOR-01-B — systémová a Ollama runtime telemetrie
  (cílová úroveň: implemented).** Implementovat read-only CPU, RAM, disk, síť a
  volitelnou GPU/VRAM telemetrii uzlu, bounded Ollama runtime probe a durable
  evidence dokončeného běhu. Chybějící nástroj, model nebo vzdálený údaj se
  uloží jako `unknown`, nikoli jako nula.
- [x] [completed] **OPS-NODE-MONITOR-01-C — API a panel Zdroje (cílová úroveň:
  implemented).** Nahradit placeholdery skutečnými hodnotami se zdrojem a časem
  měření, zobrazit očekávaný/doložený režim a výrazné varování při očekávaném GPU
  a doloženém CPU-only běhu. Diagnostika nic automaticky neopravuje.
- [x] [completed] **OPS-NODE-MONITOR-01-E — spotřeba tokenů dokončených běhů
  (cílová úroveň: implemented).** Z providerem reportovaných hodnot v durable
  Ollama a OpenAI run journalech odvodit node-local součty vstupních, výstupních
  a celkových tokenů. Zvlášť uvést dokončené běhy bez usage, nic neodhadovat a
  nezaměnit tento přehled s OpenAI účetními metrikami.
- [x] [completed] **OPS-NODE-MONITOR-01-F — stabilní editace runtime
  očekávání (cílová úroveň: implemented).** Periodický telemetry refresh nesmí
  přepsat uživatelem změněnou, dosud neuloženou hodnotu CPU/GPU očekávání ani
  chybovou zprávu jejího uložení. Po úspěšném uložení se formulář znovu řídí
  autoritativní uloženou policy.
- [x] [completed] **OPS-NODE-MONITOR-01-G — viditelné kompaktní runtime
  varování (cílová úroveň: implemented).** CPU-only běh při očekávaném GPU musí
  být výrazně označen už v kompaktním panelu Zdroje, nejen v jeho detailním
  dialogu. Zrušení bindingu nesmí ponechat staré varování.
- [ ] [in progress] **OPS-NODE-MONITOR-01-D — regrese a fyzická akceptace (cílová
  úroveň: PoC validated).** Ověřit GPU, CPU-only, částečný offload,
  nedostupnou/opožděnou telemetrii, restart aplikace, private-network pinning a
  oddělení živého vzorku od historické evidence. Spustit cílené testy, úplnou
  sadu a skutečný desktopový průchod.

## Průběžné výsledky a ověření

- A je na úrovni **designed**: kontrakt, zdroje, RBAC/privacy, omezení `/api/ps`
  a crash boundaries jsou v [ADR 0049](docs/adr/0049-node-and-ollama-runtime-telemetry.md),
  reuse rozhodnutí v [REUSE_CATALOG](REUSE_CATALOG.md) a fyzický scénář v
  [akceptačním postupu](docs/ollama-runtime-acceptance.md).
- B je na úrovni **implemented**: ephemerální systémové vzorky a atomická
  runtime policy jsou v `spikes/node_telemetry.py`; přesný read-only `/api/ps`
  probe a durable evidence dokončeného běhu rozšiřují `OllamaRuns`. Policy se
  váže na konfigurační binding a bezpečně ji dědí jen jeho ověřená immutable
  per-run modelová revize.
- C je na úrovni **implemented**: desktopové API a panel Zdroje zobrazují zdroj,
  čas, `unknown`, očekávání i historickou evidence; CPU-only při očekávaném GPU
  má výrazné varování. Activity metriky se obnovují po 2 s, kapacitní po 15 s,
  čísla jsou uvnitř progress barů a dostupnost Ollamy se ověřuje při náběhu,
  po interakci a periodicky po 30 s. Síťový status/policy je admin-only a
  evidence runu ověřuje vlastnictví vlákna.
- E je na úrovni **implemented**: tokenové součty se při
  náběhu, po interakci a v kapacitním 15s cyklu znovu odvozují z úspěšných řádků
  existujících providerových journalů. Panel ukazuje zvlášť Ollama/OpenAI detail,
  společný kompaktní součet a počet dokončených běhů bez úplné usage evidence.
  Prázdný OpenAI journal se pouhým čtením monitoru nevytváří.
- F je na úrovni **implemented**: změna selectu označí formulář jako
  rozpracovaný, takže periodický refresh nepřepíše hodnotu ani chybovou zprávu.
  Po úspěšném uložení se rozpracovaný stav zruší a vykreslí se autoritativní
  revize policy. Cílený UI test a `node --check` prošly; následná úplná sada je
  uvedena v souhrnném automatickém ověření níže.
- G je na úrovni **implemented**: kompaktní řádek Ollamy při doloženém CPU-only
  běhu a očekávaném GPU zobrazuje kontrastní textové varování; po odstranění
  bindingu se jeho stav i styl explicitně vyčistí. Fyzické ověření kompaktního
  varování čeká na nasazení této úpravy.
- Automatické ověření 25. 10. 2026: nová cílená sada monitoru, backendů,
  chat služby a desktop/web rozhraní prošla v rozsahu **197 testů, 6 skipped**.
  Generovaný JS prošel `node --check`; úplná sada
  `python3 -m unittest discover -s tests -v` po poslední změně kódu prošla v
  rozsahu **817 testů, 28 skipped**. Závěrečný `git diff --check` je uveden po
  kontrole finálního diffu.
- Skutečný Qt/WebEngine smoke nad existujícím node configem prošel: vykreslené
  UI, autentizovaný fetch a čisté ukončení backendu; screenshot byl pouze
  dočasný v `/tmp`. Živý read-only vzorek doložil CPU/RAM/disk/síť, ale
  `nvidia-smi` nedokázalo komunikovat s ovladačem, takže GPU/VRAM správně zůstaly
  `unknown`. Přesný same-node Ollama `/api/ps` odpověděl, ale nakonfigurovaný
  model právě neběžel, proto správně vrátil `unknown: model-not-running`.
  Navazující read-only dostupnostní probe nad stejným bindingem doložil
  `available`, nakonfigurovaný model mezi 12 dostupnými modely a žádnou změnu
  Targetu.
- Následná fyzická kontrola uživatele 25. 10. 2026 doložila, že živý GPU
  ukazatel skutečně reaguje na inference Ollamy spuštěnou přes Open WebUI. Tím
  bylo ověřeno čtení aktuálního zatížení GPU uzlu při reálné zátěži.
- Další fyzický průchod ve Workspace doložil dokončený streamovaný Ollama běh
  modelu `qwen3-coder:latest`: provider reportoval 68 vstupních a 222 výstupních
  tokenů, UI přijalo 217 částí a historická evidence běhu v čase
  `2026-10-25T15:55:46.486560Z` klasifikovala runtime jako `GPU` s VRAM 100 %
  modelu. Tím je ověřeno propojení skutečné odpovědi, per-run tokenů a přesné
  `/api/ps` evidence.
- Fyzická kontrola po restartu aplikace doložila obnovený kompaktní součet
  `Tokeny běhů · 451 101` a poslední Ollama runtime `gpu`. OpenAI účetní řádek
  zůstal samostatný, takže node-local součet providerových run journalů není v
  UI zaměněn s účetním reportem.
- Navazující fyzické porovnání začalo na součtu `451 101`, po jediném dalším
  Ollama běhu ukázalo `451 360` (přesný přírůstek 259 tokenů) a po následujícím
  restartu zůstalo `451 360`. Tím je doložena aktualizace agregátu z dokončeného
  run journalu, restartová obnova i absence dvojího započtení při samotném
  restartu.
- Záměrný CPU-only průchod při očekávaném GPU fyzicky doložil správnou
  klasifikaci i výrazné varování ve velkém monitorovacím dialogu. Při akceptaci
  se ukázalo, že kompaktní panel zobrazoval pouze neutrální `cpu`; navazující
  úprava G přidává varování i tam a čeká na fyzické potvrzení po nasazení.
- D zůstává otevřené pro toto kompaktní potvrzení a private-network pinning.
  Partial-GPU nelze na aktuálním hostu smysluplně vyvolat, protože CPU
  a GPU používají sdílenou paměť; tento scénář zůstává explicitně neověřený,
  nikoli neúspěšný. Ollama běží v Dockeru, proto lze CPU-only průchod provést
  izolovanou vedlejší instancí bez GPU na jiném loopback portu, aniž by se
  měnila funkční instance. Plný GPU Workspace běh, jeho historická evidence,
  tokeny a restartová obnova jsou na aktuálním hostu ověřeny.

## Crash boundaries

- Živý systémový vzorek je ephemerální read-only projekce. Pád během čtení nic
  neobnovuje; další požadavek sestaví nový vzorek a jednotlivé nedostupné metriky
  zůstanou explicitně `unknown`.
- Ollama runtime probe je read-only dotaz na tentýž ověřený endpoint a běží po
  providerově dokončené odpovědi, ale před atomickým dokončením run journalu.
  Výsledek nebo doložené `unknown` se uloží spolu s úspěšným runem. Pád před
  durable dokončením zachová dosavadní stav `unknown` a nikdy nevyvolá retry.
- Změna očekávaného runtime je node-local nastavení mimo projektový Git a váže
  se na přesné ID/revizi nakonfigurovaného bindingu; immutable revize odvozená
  pouze pro explicitní brainstormingový model ji zdědí. Běh používá přesnou
  revizi očekávání zachycenou při dispatch a pozdější změna nepřepisuje
  historickou evidence.
- Tokenové součty jsou obnovitelná read-only projekce durable providerových
  odpovědí, nikoli další účetní autorita. Pád během výpočtu nic nezapisuje;
  další načtení provede celý součet znovu. Započítají se jen úspěšné běhy s
  úplnými nezápornými providerovými počty, ostatní se vedou jako `bez usage`.

## K předání do backlogu

- [ ] [planned] **OPS-WEB-CONCURRENCY-01 — souběžná obsluha streamu a monitoru
  (cílová úroveň: designed → implemented).** Původ: uživatelské zjištění
  25. 10. 2026, že současný jediný obslužný tok během streamované odpovědi
  nevyřídí monitorovací požadavek. Navrhnout omezenou souběžnost se zachováním
  serializace zápisů, vlastnictví requestů, čistého ukončení a fail-closed
  recovery; dokončeno až po testu současného streamu, read-only telemetrie a
  zápisové interakce. Není podmínkou akceptace této dávky.

## Akceptace dávky

Dávka je přijatelná až po automatických regresích a fyzickém průchodu nad
alespoň jedním skutečným Ollama během. Nedostupná GPU nebo private-network
infrastruktura se nesmí vydávat za ověření odpovídajícího scénáře; neprovedené
části zůstanou otevřené.
