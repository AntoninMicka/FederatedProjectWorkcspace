<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-OLLAMA-STREAM-01

Feature dávka **F-M3-OLLAMA-STREAM-01 — Streamovaná odpověď a živý stav
lokálního AI běhu** je aktivní na větvi `feature/f-m3-ollama-stream-01`,
založené z `develop` `4d2e32c`; cílem jediného PR je `develop`. Původní
požadavek je veden v roadmapě M3 a v BACKLOG. Cílová úroveň je **PoC
validated**.

Rozsah: adaptovat existující ephemerální stream UI pro Ollama `/api/generate`
NDJSON, aniž by se slučoval providerový transport nebo vznikl druhý run
journal. Autoritativní assistant zpráva a usage vzniknou až z validního
koncového rámce. Mimo rozsah jsou automatický retry/reconnect, tokenová
perzistence, task role a změna externího OpenAI streamu.

- [x] [completed] **F-M3-OLLAMA-STREAM-01-A — Kontrakt, reuse a crash
  boundaries (designed).** ADR upřesňuje request digest, bounded NDJSON,
  validaci finálního rámce, timeouty a přechody `dispatching` →
  `succeeded`/`failed`/`unknown`. Řešení adaptuje `OllamaAdapter`, `OllamaRuns`
  a existující UI NDJSON kanál; providerový SSE parser nekopíruje.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-B — Ollama stream transport
  (PoC validated).** `stream:true` je součástí request digestu. Bounded NDJSON
  parser skládá text pouze z validních průběžných rámců, přijme jediný finální
  rámec a teprve potom uloží normalizovaný výsledek s usage. První-token a idle
  timeout, předčasný EOF či ztráta callbacku jsou durable `unknown`; známý
  neplatný rámec je `failed`. Živý smoke proti uloženému same-node modelu
  `gemma4` vrátil tři delty, `stream-ok`, `done:true` a tokenové usage.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-C — Chat API a přístupné živé UI
  (implemented).** Autorizovaný `/v1/chat/send-stream` posílá oddělené stavové,
  textové a finální NDJSON události. Web vyžaduje write oprávnění k projektu.
  UI ukazuje přípravu, připojování, čekání, generování a dokončení; stručný stav
  je `aria-live="polite"`, zatímco tokenová projekce je `aria-live="off"`.
- [ ] [in progress] **F-M3-OLLAMA-STREAM-01-D — Regrese, dokumentace a předání
  (PoC validated automaticky, fyzická UI akceptace vrácena k opravě).** První
  fyzická kontrola viděla až finální výsledek. Časovaná diagnostika 2026-10-12
  potvrdila, že uložený model `gemma4` skutečně posílá NDJSON průběžně, ale
  nejprve několik sekund pouze v poli `thinking`; následný text přišel v desítkách
  samostatných delt. Oprava rozlišuje bezpečný stav přemýšlení bez zveřejnění
  reasoning textu, udržuje rozepsanou odpověď ve viditelné části a nový HTTP
  test prokazuje flush delty před terminálním výsledkem. Cílená regrese po
  opravě prošla: **109 testů OK, 5 volitelných přeskočeno**; úplná sada:
  **501 testů OK, 24 volitelných přeskočeno**. Zbývá opakovaná fyzická kontrola
  podle [checklistu](docs/ollama-streaming-acceptance.md).

Akceptace: žádná delta sama nevytvoří zprávu ani durable úspěch; známá validní
chyba je `failed`, ztracený stream po dispatch hranici `unknown`; retry téhož
run ID neodešle druhý požadavek a UI nikdy nevydá částečný text za výsledek.
