<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-EXTERNAL-01: První externí provider a řízené volání

Milník M3; jedna dávka, větev `feature/f-m3-external-01-first-provider`, budoucí
PR do `develop`. [Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivováno po PR #35 dne 2026-09-19.
- Výstup: první externí textový provider, write-only credential, přesný preview a
  potvrzený dispatch; jednotné zadání Ollamě vrací přímou odpověď, návrh
  artefaktu, nebo připravený externí dotaz.
- Recovery: approval váže přesný manifest, payload, binding/model a credential
  reference. Durable `dispatching` vzniká před sítí; ztracená odpověď je
  `unknown` bez retry. Ollama sama nezapisuje do Gitu ani nevolá providera.
- Mimo rozsah: usage/billing `M3-UB-01`, obrazový pipeline `F-M3-MEDIA-01`,
  automatický routing/fallback, obecný agent runtime a synchronizace credentialů.

## Dokončené části dávky

- [x] [completed] **F-M3-EXTERNAL-01-A — Reuse a kontrakt (designed).** ADR 0008
  volí `openai-responses`, opaque node-local credential a nedůvěryhodný návrh
  Ollamy; soukromý kód bez doložené licence nebyl převzat.
- [x] [completed] **F-M3-EXTERNAL-01-B — Credential a textový adapter
  (implemented).** Přesný `store=false` request, striktní response parser,
  durable run journal, `unknown` bez retry a bezpečné nastavení bez vracení
  secretu. Úplná sada po opravě modelových ID: 300 testů, 22 skipů.
- [x] [completed] **F-M3-EXTERNAL-01-B1 — Modelový katalog (implemented).**
  Explicitní omezené načtení, cache vázaná na binding/credential revizi a ruční
  modelové ID. Úplná sada: 302 testů, 22 skipů.
- [x] [completed] **F-M3-EXTERNAL-01-C — Preview, privacy a potvrzený dispatch
  (PoC validated).** `local-only` fail-closed; ostatní privacy vyžadují potvrzení
  přesného hashe. Recovery po restartu/pádu neodesílá podruhé. Úplná sada:
  306 testů, 22 skipů.
- [x] [completed] **F-M3-EXTERNAL-01-D — Ollama návrh a živá integrační
  akceptace (PoC validated).** Striktní návrh, explicitní výběr, nový manifest a
  samostatné potvrzení. První živé pokusy odhalily chybějící UUID v promptu a
  `reasoning` položku Responses API; obě opravy jsou fail-closed a tool cally
  zůstávají odmítnuté. Dva dřívější provider requesty mohou být účtované a
  neopakují se. Uživatel 2026-09-19 potvrdil úspěšný celý průchod po opravě.
  Ověření: 311 testů, 22 skipů, plus živá Ollama → OpenAI akceptace.

## Aktivní část E — jednotné lokální zadání a tři typy výstupu

- [x] [completed] **F-M3-EXTERNAL-01-E1 — Uzavřený outcome kontrakt
  (implemented).** `AITaskOutcome` dovoluje pouze `direct-answer`,
  `artifact-draft` nebo `external-request`; omezuje velikost, typ artefaktu a
  UUID zdrojů, odmítá provider/credential/tool pole. Přidána provider-neutral
  role `task-router-v1`. Ověření: vlastní testy a úplná sada 313 testů,
  22 environmentálních skipů dne 2026-09-19.
- [x] [completed] **F-M3-EXTERNAL-01-E2 — Durable orchestrace a artefaktový
  kontext (PoC validated).** `task_route` sestaví jeden manifest z explicitních
  artefaktů, seřazených zpráv a nového focus zadání, autorizuje jen vybraná UUID
  a striktně validuje outcome i jeho zdrojová ID. Context Builder nově bezpečně
  rozlišuje projektové vstupy od konverzace a focusu. Privacy výsledku je maximum
  všech manifestových vstupů; stejný request po restartu načte durable Ollama
  výsledek bez dalšího transportu. Ověření: cílené testy a úplná sada 315 testů,
  22 environmentálních skipů dne 2026-09-19.
- [x] [completed] **F-M3-EXTERNAL-01-E3 — Dočasné dlouhé zprávy a potvrzení
  (PoC validated).** Node-local `TaskOutcomes` obnoví po reloadu celý návrh a
  promítá jej jako dočasný, dokud jej uživatel nepotvrdí nebo nezamítne.
  Artifact potvrzení používá idempotentní Workspace operaci, zachová nejsilnější
  privacy a provenance `llm-generated`, poté obsah nahradí stabilním odkazem.
  Externí potvrzení znovu sestaví manifest i z vybraných artefaktů, používá
  existující exact approval/durable run a sjednocený tok redukuje na neobsahový
  provozní záznam bez zápisu plného requestu/response do `ChatThreads`.
  Crash hranice a retry jsou popsány v ADR 0008; backendové endpointy pokrývají
  route/list/cancel, artifact publish a external preview/confirm/cancel.
  Ověření: úplná sada 319 testů, 22 environmentálních skipů dne
  2026-09-19; předchozí sandboxový běh selhal pouze na zakázaném socket bindu.
- [ ] [in progress] **F-M3-EXTERNAL-01-E4 — Jednotné UI a integrační
  akceptace (implemented; živá akceptace otevřená).** Hlavní `Zpracovat`
  používá jednotný task router, explicitní volbu projektových podkladů a
  bezpečně vykresluje přímou odpověď, celý dočasný návrh artefaktu nebo
  externí request. Potvrzení/zamítnutí mění projekci na odkaz či provozní
  záznam; projektový reload obnoví poslední task vlákno i přesný rozpracovaný
  externí preview. Staré ruční externí akce jsou sbalené jako pokročilé.
  Dlouhý obsah se v kartě neořezá a všechen nedůvěryhodný text jde přes
  `textContent`. Ověření: cílené lifecycle/UI testy, `node --check` a úplná
  sada 319 testů, 22 environmentálních skipů dne 2026-09-19. Zbývá ruční
  průchod skutečným desktopem přes všechny tři větve a reload. Při živé
  akceptaci bylo zjištěno, že opožděný `loadChat()` nebo chybová obnova mohou po
  volbě nového vlákna obnovit staré ID a odeslat jeho zprávy. UI nyní invaliduje
  starší načtení a při chybě dohledává durable výsledek pouze podle přesného ID
  právě odesílaného tasku/vlákna. Další živý pokus prokázal čisté nové vlákno,
  ale Gemma požadavek na dokument pouze zopakovala jako `direct-answer`;
  routerová instrukce nyní explicitně rozlišuje dokumentový návrh, požadavek na
  aktuální/externí hledání a přímou odpověď a zakazuje vydat parafrázi zadání za
  výsledek. Následující pokus zvolil správný `artifact-draft`, ale Gemma vložila
  jeho pole do nepovoleného objektu `artifact`; instrukce proto nyní obsahuje
  celé ploché JSON šablony a výslovný zákaz vnoření. Známá validační chyba 422
  uvolní klientské operation ID pro nový vědomý pokus, zatímco `unknown` se dál
  automaticky neopakuje. Chyby `/v1/tasks/*` už nejsou nesprávně hlášeny jako
  chyba otevření projektu. Uživatel 2026-09-19 následně živě potvrdil čisté nové
  vlákno, úspěšný průchod `artifact-draft` až po vytvoření artefaktu a načtení
  výsledku po reloadu. Reload současně potvrdil UX mezeru: bez voliče vláken UI
  skládá klasický chat a poslední task projekci do jednoho pohledu. Oddělení a
  výběr drží prioritní `F-M2-CHAT-03`. V této dávce zbývá ověřit přímou odpověď
  a externí návrh/volání; webové hledání přes SearXNG je samostatná navazující
  feature.

## K předání do backlogu

- [ ] [planned] **F-M2-CHAT-03 — Správa a restartová akceptace lokálních
  vláken (cílová úroveň: PoC validated).** Prověřit a v UI zpřístupnit životní
  cyklus vláken: založení nového vlákna, vědomé navázání, seznam podle projektu
  a nepřiřazených vláken, přiřazení/archivaci, zobrazení persistence a úplné
  smazání lokálního vlákna. Mazání musí nejprve ukázat rozsah, vyžádat potvrzení,
  odmítnout aktivní či `unknown` běh a koordinovaně odstranit zprávy, turns,
  task outcomes, preview/approval a navázané lokální run záznamy bez osiřelých
  dat; pád mezi více SQLite stores musí mít durable recovery a idempotentní
  dokončení. Publikované Git otisky a artefakty se nemažou skrytě, ale preview
  je předem uvede jako zachované historické výstupy. „Úplné“ znamená úplné z
  podporovaného aplikačního stavu, nikoli garantovaný forenzní výmaz z média.
  Ověřit restart desktopu, více vláken jednoho projektu, oddělení projektů a
  uživatelů, souběžnou změnu i smazání před/po jednotlivých crash boundaries.
  Autoritou pracovní historie zůstává node-local `chat-threads.sqlite` mimo Git
  a obnovitelný projektový index; projektové Git artefakty vznikají jen
  explicitním full/delta otiskem nebo publikací výstupu.
- [ ] [planned] **F-M3-SEARCH-01 — Řízené webové hledání přes SearXNG
  (cílová úroveň: PoC validated).** Adaptovat existující lokální SearXNG
  používaný Open WebUI jako explicitní search capability. Task router smí
  navrhnout `web-search`, ale síťové volání provede až aplikace po policy/privacy
  kontrole; nejde o skrytý Ollama tool call ani o externí-modelový dispatch.
  Výsledek uchová dotaz, čas hledání, URL, titulky, bounded úryvky a provenance,
  následná odpověď Ollamy dostane jen přesný Context Manifest. Akceptace zahrne
  nedostupnou službu, timeout, neplatný JSON, nedůvěryhodný obsah/URL, nulové a
  duplicitní výsledky, restart mezi hledáním a syntézou a zákaz automatického
  oslabení `local-only`; endpoint a síťová hranice budou konfigurovatelné a
  nebudou odvozeny pouze z dockerového názvu `searxng`.
- [ ] [planned] **F-M1-PROJECT-DELETE-01 — Bezpečné odstranění celého projektu
  (cílová úroveň: designed → PoC validated; pozdější priorita).** Oddělit pouhé
  odregistrování, odstranění lokálního odvozeného stavu, přesun repozitáře do
  obnovitelného koše a definitivní výmaz. Před každou variantou zobrazit přesné
  cesty a dopady na chatová vlákna, sdílené/cross-project reference, credentials,
  pending operace a federované kopie; projekt s aktivní operací, nevyřešeným
  přenosem nebo neznámým externím účinkem se nesmí tiše odstranit. Více
  persistentních vrstev vyžaduje journal, idempotentní recovery a samostatné
  potvrzení definitivního výmazu; odstranění lokální kopie není tvrzení, že
  zmizely vzdálené či dříve sdílené revize.
