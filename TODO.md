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
  **502 testů OK, 24 volitelných přeskočeno**. Zbývá opakovaná fyzická kontrola
  podle [checklistu](docs/ollama-streaming-acceptance.md).
- [x] [completed] **F-M3-OLLAMA-STREAM-01-E — Nové vlákno patří otevřenému
  projektu (implemented).** Uživatelská oprava z fyzické akceptace: první
  uložení přímého Ollama/OpenAI chatu i taskového chatu zapisuje `project_id`
  otevřeného projektu atomicky se vznikem SQLite vlákna; navazující orchestrace
  přiřazení zdědí. Pád nemůže zanechat samostatně vytvořené nezařazené vlákno a
  staré nezařazené chaty se automaticky nepřesouvají. Cílená regrese chatového
  lifecycle, služby a desktopu: **72 testů OK, 2 volitelné přeskočeny**.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-F — Ruční zařazení a viditelný živý
  běh (implemented).** Nezařazené vlákno má v nabídce explicitní akci pro
  atomické přiřazení k otevřenému projektu. Prázdná průběžná odpověď během
  `thinking` ukazuje animovaný indikátor, stav a uplynulý čas; interní reasoning
  obsah se nadále nezobrazuje ani neukládá. Cílená regrese: **72 testů OK,
  2 volitelné přeskočeny**; úplná sada zůstává **502 testů OK,
  24 volitelných přeskočeno**.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-G — Viditelný průběh ve všech
  Ollama režimech (implemented).** Fyzická kontrola odhalila, že výchozí režim
  Orchestrace používá záměrně celistvý task-router výsledek a dřívější živý
  prvek byl navíc jen CSS pseudoobsah. UI nyní používá skutečný stavový DOM
  prvek, před dispatchí vynutí vykreslovací snímek a ukazuje čas běhu i pro
  orchestrace. Tokenové delty zůstávají omezené na přímý Brainstorming;
  interní reasoning text se nezobrazuje ani neukládá. Cílená desktopová sada:
  **22 testů OK, 2 volitelné přeskočeny**; reálný offscreen Qt/WebEngine smoke:
  **OK**; úplná sada: **502 testů OK, 24 volitelných přeskočeno**. Zbývá
  fyzická kontrola obou režimů podle checklistu.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-H — Živý stav v oblasti zpráv
  (implemented).** Opakovaná fyzická kontrola aktuálního checkoutu ukázala jen
  finální výsledek. Živá karta byla umístěná až pod vysokým composerem, zatímco
  výsledek se vykresloval ve scrollovatelné historii. Stav i rozepsaná odpověď
  jsou nyní sourozenci historie chatu přímo v hlavním panelu; composer si
  ponechává jen stručný operační stav. Izolovaný reálný Qt/WebEngine test
  ověřil nenulový rozměr a průnik karty s viditelným viewportem: **OK**;
  cílená desktopová sada: **22 testů OK, 2 volitelné přeskočeny**; úplná sada:
  **502 testů OK, 24 volitelných přeskočeno**.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-I — Jednotný viditelný stream
  providerů (implemented).** Read-only kontrola lokálních run journalů po třetí
  fyzické zkoušce ukázala po sobě Ollama i OpenAI Brainstorming běh; poslední
  pokus nebyl Ollama. OpenAI stream nyní používá stejnou viditelnou časovanou
  kartu a scrollování jako Ollama. Obě větve po dokončení vypíšou počet
  skutečně přijatých textových delt, aby fyzická akceptace rozlišila providerový
  stream od pouhého finálního výsledku; obsah ani reasoning se neloguje.
  Cílená desktopová sada: **22 testů OK, 2 volitelné přeskočeny**; reálný
  Qt/WebEngine test viditelnosti: **OK**; úplná sada: **502 testů OK,
  24 volitelných přeskočeno**.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-J — Viditelná transportní telemetrie
  (implemented).** Uživatelem předaný usage pro fyzický Ollama běh doložil
  48,75 s celkem, z toho 41,37 s generování, ale dřívější počet delt zůstal v
  jiném stavovém řádku. Zobrazená Spotřeba běhu nyní obsahuje i stav zapnutí
  streamu, počet textových delt, čas první delty a celkový čas měřený ve
  WebEngine. Telemetrie neobsahuje prompt, odpověď ani reasoning. Izolovaná
  sonda na stejné instalaci Qt potvrdila průběžný Fetch/ReadableStream mezi
  pěti půlsekundovými rámci; reálný app smoke: **OK**; cílená desktopová sada:
  **22 testů OK, 2 volitelné přeskočeny**; úplná sada: **502 testů OK,
  24 volitelných přeskočeno**.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-K — Capability při studeném startu
  (implemented).** Viditelná telemetrie fyzického běhu konečně doložila
  `stream nebyl v UI zapnutý`. `loadChat()` při otevření projektu načetl binding,
  ale nepřevzal capability; ta se nastavovala pouze po návštěvě Nastavení.
  Otevření projektu nyní načte Ollama i OpenAI capability ještě před povolením
  práce s chatem, takže čistý start volí stream endpoint bez skrytého mezikroku.
  Cílená desktopová sada: **23 testů OK, 2 volitelně přeskočeny**;
  skutečný Qt/WebEngine smoke: **OK**; úplná sada: **503 testů OK,
  24 volitelných přeskočeno**.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-L — Viditelná volba streamování
  (implemented).** Nastavení lokálního AI backendu
  zobrazuje přepínač i textový stav zapnuto/vypnuto/nepodporováno. Volba je
  uzlová, nesynchronizuje se do projektu a výchozí stav je zapnuto. Zápis
  používá dočasný soubor, `fsync` a atomické nahrazení; pád tedy ponechá
  buď původní, nebo novou celou hodnotu bez potřeby journal recovery.
  Cílená chatová a desktopová sada: **63 testů OK, 2 volitelně
  přeskočeny**; skutečný Qt/WebEngine smoke: **OK**; úplná sada:
  **504 testů OK, 24 volitelných přeskočeno**.
- [x] [completed] **F-M3-OLLAMA-STREAM-01-M — Sledování konce dlouhé
  odpovědi (implemented).** Původní
  `scrollIntoView(nearest)` považoval dlouhý blok za viditelný, i když jeho
  přibývající konec už byl pod viewportem. Stream nyní posouvá skutečný
  scrollovací kontejner na jeho spodní hranu. Pokud uživatel odscrolluje
  nahoru, automatické sledování se pozastaví; po ručním návratu ke konci se
  znovu zapne.
  Cílená desktopová sada: **23 testů OK, 2 volitelně přeskočeny**;
  skutečný Qt/WebEngine smoke s 300řádkovou odpovědí, ručním odscrollováním
  a opětovným sledováním konce: **OK**; úplná sada: **504 testů OK,
  24 volitelných přeskočeno**.

Akceptace: žádná delta sama nevytvoří zprávu ani durable úspěch; známá validní
chyba je `failed`, ztracený stream po dispatch hranici `unknown`; retry téhož
run ID neodešle druhý požadavek a UI nikdy nevydá částečný text za výsledek.
