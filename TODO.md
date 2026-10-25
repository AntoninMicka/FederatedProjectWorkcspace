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
  má výrazné varování. Síťový status/policy je admin-only a evidence runu
  ověřuje vlastnictví vlákna.
- Automatické ověření 25. 10. 2026: cílených 44 testů prošlo, generovaný JS
  prošel `node --check`, úplná sada `python3 -m unittest discover -s tests -v`
  prošla v rozsahu **814 testů, 28 skipped** a `git diff --check` byl čistý.
- Skutečný Qt/WebEngine smoke nad existujícím node configem prošel: vykreslené
  UI, autentizovaný fetch a čisté ukončení backendu; screenshot byl pouze
  dočasný v `/tmp`. Živý read-only vzorek doložil CPU/RAM/disk/síť, ale
  `nvidia-smi` nedokázalo komunikovat s ovladačem, takže GPU/VRAM správně zůstaly
  `unknown`. Přesný same-node Ollama `/api/ps` odpověděl, ale nakonfigurovaný
  model právě neběžel, proto správně vrátil `unknown: model-not-running`.
- D zůstává otevřené: je nutný alespoň jeden skutečný dokončený Ollama běh přes
  nové UI a kontrola historické evidence po restartu. GPU/partial-GPU,
  záměrný CPU-only varovný scénář a private-network pinning lze uzavřít pouze
  tam, kde je příslušná infrastruktura skutečně dostupná; aktuální host GPU
  scénář nedokládá.

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

## Akceptace dávky

Dávka je přijatelná až po automatických regresích a fyzickém průchodu nad
alespoň jedním skutečným Ollama během. Nedostupná GPU nebo private-network
infrastruktura se nesmí vydávat za ověření odpovídajícího scénáře; neprovedené
části zůstanou otevřené.
