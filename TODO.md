<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-BACKEND-MODEL-01: výběr backendu a modelu v chatu

Feature dávka vznikla 25. 10. 2026 na větvi
`feature/ux-backend-model-01-chat-selector` z `develop` `b19d46a` po doručení
TEST-EXECUTION-01 v PR #94. Cílová úroveň je **designed → implemented →
PoC validated**, cíl jediného PR je `develop`. Původem je uživatelský požadavek
25. 10. 2026 na společný částečný facelift backendů a modelů. AtlasCloud
integrace se neotevírá; je jedním providerem společného katalogu.

## Rozsah a hranice

- **Výstup:** oddělit backendové připojení/credential/profil od přesné
  modelové nabídky. Backend a model se volí v chatovém composeru pro konkrétní
  běh. Backend-first volba filtruje modely a model-first volba filtruje backendy
  podle skutečných nabídek a požadovaných capabilities role, akce a výstupu.
- **Nastavení backendů:** podle vzoru federace zobrazit tabulku všech
  podporovaných backendů, jejich stavu a služeb. Každý backend má vlastní
  dialog připojení a pouze akce Nastavit/Resetovat; služby mohou zahrnovat
  modely, obraz, hledání, storage/import nebo resource metriky.
- **Katalog modelů:** samostatná read-only stránka Nastavení ukáže modely
  napříč backendy, jejich obecné capabilities a v detailu doložené capabilities,
  protokoly, stav a provenance jednotlivých providerových nabídek.
- **Zdroje:** monitor zobrazí provider-neutral spotřebu a dostupné
  balance/quota metriky. Tokeny AtlasCloud uložených běhů se zobrazí u jeho
  provider card; živé kredity pouze pokud je doložený resource adapter skutečně
  poskytne. Spotřeba, cena, kredit a limit zůstanou odlišené veličiny.
- **Backendové modifikátory:** více providerových nabídek může odkazovat na
  stejný kanonický model. Nabídka přidá protokol, endpoint, request/response
  pravidla, limity a doložené capabilities, ale nemění identitu modelu ani
  optimisticky nedoplňuje neznámou dovednost.
- **Preference:** node-local pořadí oblíbených kanonických modelů určuje
  první úroveň nabídky; ostatní jsou pod „Další“. Preference pouze řadí,
  nic sama nevybírá, neautorizuje, nepřepíná ani nenahrazuje fallback.
- **Recovery:** potvrzený run před externím účinkem fixuje backend/binding,
  offer/model, protokol, capability snapshot a revize. Pozdější změna katalogu
  nebo preferencí nesmí změnit připravený ani rozpracovaný run. Preference jsou
  node-local, mimo projektový Git, credential store i autoritativní run journal.
- **Mimo rozsah:** automatický výběr nebo fallback, nedoložený žebříček
  kvality/ceny a změna providerových credentialů během dispatch.

## Úkoly dávky

- [x] [completed] **UX-BACKEND-MODEL-01-A — kontrakt, reuse a recovery
  (designed).** [ADR 0053](docs/adr/0053-chat-backend-model-selection.md)
  zachovává bindingy, credentials, katalog a jediný provider run journal jako
  autority. Zavádí pouze revizovanou serverovou projekci voleb, explicitní
  `RunSelection`, model-first/backend-first filtr, kanonické node-local
  preference s CAS a atomickým zápisem a fail-closed revalidaci před durable
  `prepared`. Popsané crash boundaries zakazují po restartu přepočet rozpracovaného
  runu z nového katalogu i automatický retry/fallback.
- [x] [completed] **UX-BACKEND-MODEL-01-AH-01 — backendové služby,
  nastavení a zdroje (designed).** Uživatelské doplnění rozšířilo ADR 0053
  o katalog podporovaných backendů a jejich služeb, providerové dialogy,
  bezpečný reset, samostatný read-only modelový katalog a obecný resource
  kontrakt. Existující AtlasCloud evidence prokazuje tokenovou spotřebu runů,
  nikoli kreditní balance; UI tyto hodnoty nesmí zaměnit.
- [x] [completed] **UX-BACKEND-MODEL-01-AH-02 — historie chatů nezávislá na
  pomocných stavech (implemented).** Uživatelské hlášení 26. 10. 2026: po
  otevření projektu zmizela ze stromu i nezařazená vlákna. Autoritativní
  `/v1/chat/status` se nyní načte a vykreslí před providerovými stavy,
  projekcí úloh a frontou automatiky; jejich chyba zobrazí lokální diagnostiku,
  ale nesmaže seznam chatů. Revize načtení brání opožděné odpovědi přepsat stav
  po rychlém přepnutí projektu. Data ani přiřazení vláken se nemigrují.
- [ ] [in progress] **UX-BACKEND-MODEL-01-B — společná nabídka a serverová
  revalidace (cíl: implemented).** Sestavit provider-neutral projekce
  backendů/služeb, modelů/nabídek/modifikátorů a resource metrik. Před dispatch
  znovu fail-closed ověřit přesnou čerstvou revizi, RBAC a privacy bez
  providerových hard-code větví ve widgetu; reset nesmí smazat historii runů.
- [ ] [in progress] **UX-BACKEND-MODEL-01-C — sdílený composer a preference
  i Nastavení (cíl: implemented).** Ve stávajícím `spikes/desktop_ui.py`
  realizovat tabulku backendů s vlastními dialogy Nastavit/Resetovat,
  samostatnou read-only tabulku/detail modelů a provider cards monitoru.
  Composer realizuje
  backend-first i model-first filtr, capability zúžení a přístupnou první úroveň
  oblíbených modelů s volbou „Další“. Node-local preference ukládat atomicky
  a po restartu je striktně revalidovat.
- [ ] [planned] **UX-BACKEND-MODEL-01-D — regrese a fyzická akceptace
  (cíl: PoC validated).** Automaticky pokrýt prázdný/stale/offline katalog,
  neznámé/conflicting capabilities, více nabídek jednoho modelu, restart, změnu
  revize, RBAC/privacy, bezpečný reset, backend bez modelů, chybějící resource
  metriku a neměnnnost rozpracovaného runu. Fyzicky projít tabulky/dialogy,
  AtlasCloud tokenovou spotřebu a backend-first i model-first tok nejméně na
  dvou backendech a potvrdit odeslaný přesný pár.

## Akceptace

Stejný sdílený desktop/web composer obousměrně filtruje backendy a modely bez
providerových hard-code větví, zohlední skutečné capabilities a prezentuje
oblíbené vs. „Další“ bez automatické volby. Server před dispatch znovu ověří
přesnou nabídku a uložený run prokazuje zobrazený backend/model i jejich revize.
Automatické a fyzické průchody splní podmínky úkolu D.

Nastavení navíc poskytne jednu tabulku podporovaných backendů s jejich
službami a samostatný read-only katalog modelů; monitor pravdivě oddělí
historickou spotřebu, account usage/cost, zůstatek a limit podle skutečně
dostupných dat backendu.

## Průběžné ověření

Návrhový krok A a doplnění AH-01 byly zkontrolovány proti ADR 0051/0052,
skutečnému
`ChatRunChoice`, `BackendExecution`, providerovým bindingům a run journalům i
sdílenému composeru, existujícímu nastavení/federačnímu vzoru a
`backend_metrics`. Dokumentační odkazy a finální diff prošly kontrolou
`git diff --check`; aplikační kód ani testy se v těchto krocích neměnily.

První implementační řez B/C přidal provider-neutral katalog backendů a jejich
služeb, read-only agregaci modelových nabídek, atomické CAS preference a resource
schema, které samostatně rozlišuje spotřebu, volné tokeny a předplacené tokeny.
Sdílené Nastavení obsahuje tabulku backendů a samostatnou tabulku/detail
modelů; monitor nově zobrazuje AtlasCloud tokeny doložené uloženými runy a
pravdivý stav chybějícího balance reportu. Cílená sada 150 testů
`test_backend_catalog`, `test_model_catalog`, `test_chat_service`, `test_desktop`
a `test_web_server` mimo socketově omezený sandbox prošla, 7 volitelných
WebEngine testů bylo přeskočeno.

Druhý implementační řez přesunul všech šest podporovaných backendů z inline
nastavení do akcí `Nastavit`/`Resetovat` v jedné tabulce. Jednotný reset je na
webu omezen na administrátora; nejprve trvale zneplatní aktivní profil a až
potom odstraní credential. OpenAI reset zahrnuje i navázaný Images profil,
Google Drive maže konfiguraci a tokeny jednou SQLite transakcí a všechny
varianty zachovávají historii běhů/importů, katalogy a preference. Credentialové
backendy mají malý durable reset journal, takže pád mezi oběma kroky zanechá
`reset-pending` a opakování bezpečně dokončí odstranění credentialu. Cílená sada
162 testů `test_backend_catalog`, `test_chat_service`, `test_media_service`,
`test_google_drive_import`, `test_desktop` a `test_web_server` mimo socketově
omezený sandbox prošla; 7 volitelných WebEngine testů bylo přeskočeno. Zbývá
obousměrný composer, serverové pinning/revalidace a fyzická akceptace; B/C proto
zůstávají rozpracované.

Třetí implementační řez přidal explicitní načtení modelů Ollamy z přesně
zadaného endpointu přes `/api/tags`. Před uložením jde pouze o dočasnou nabídku
v dialogu; teprve úspěšné načtení pro právě aktivní revizi bindingu vytvoří
durable discovery snapshot. Nedostupný nebo neplatný katalog neblokuje ruční
zadání přesného ID modelu a nevytváří osiřelý snapshot. Sdílený composer nyní
čte serverovou projekci čerstvých nabídek, podporuje backend-first i model-first
zúžení a odděluje preferované kanonické modely od nabídky „Další“, aniž by
cokoliv automaticky vybral. Pro orchestration je Ollama do dokončení nového
serverového run kontraktu bezpečně omezena na model aktivního bindingu. Zbývá
serverové pinning/revalidace přesné nabídky, plná regrese a fyzická akceptace;
B/C proto zůstávají rozpracované. Cílená sada 197 testů
`test_backend_catalog`, `test_model_catalog`, `test_ollama_backend`,
`test_chat_modes`, `test_chat_service`, `test_desktop` a `test_web_server`
mimo socketově omezený sandbox prošla; 7 volitelných WebEngine testů bylo
přeskočeno.

Ad-hoc oprava AH-02 oddělila načtení historie chatů od volitelných providerových,
task a autonomy projekcí. Regresní test hlídá, že se zařazená i nezařazená
vlákna vykreslí ještě před `Promise.allSettled` pomocných stavů a že přepnutí
projektu zneplatní opožděné načtení. Kompletní sada
`python3 -m unittest discover -s tests -v` mimo socketově omezený sandbox
prošla: 866 testů, 29 volitelných testů přeskočeno. JavaScript navíc prošel
`node --check`, Python soubory `py_compile` a finální diff `git diff --check`.
