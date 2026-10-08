<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — IMP-02: Import kompletního projektu z NotebookLM

Navazující importní dávka; větev
`feature/imp-02-notebooklm-project-import`, základ `develop` `8854d69`, budoucí
jediný PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivována 2026-10-08 po doloženém merge
  F-M4-WORKFLOW-01 v PR #47. Původ: roadmapa 3C, backlog `IMP-02` a upřesnění
  uživatele, že cílem nejsou samostatné konverzace, ale kompletní projekty z
  Google NotebookLM.
- Výstup: jeden skutečný NotebookLM notebook se importuje jako jeden nový
  Workspace projekt. Dostupné zdroje, uživatelské poznámky, generované výstupy
  a chat se mapují na oddělené artefakty a vztahy; původní notebooková hranice,
  doložené citace, identifikátory, časy a původní přijaté bajty se zachovají.
  Přehled importu výslovně uvede každou nedostupnou nebo nepodporovanou část.
- „Kompletní“ znamená vše prokazatelně dostupné ve skutečném exportu nebo
  oficiálním API konkrétní edice, nikoli domyšlený obsah. Osobní NotebookLM,
  NotebookLM Plus/Workspace a Gemini Notebook Enterprise se nesmějí zaměnit.
  Enterprise Preview API není fallback pro osobní účet a placená Enterprise
  závislost se nezavádí bez samostatného rozhodnutí.
- Edice potvrzena uživatelem 2026-10-08: osobní Gemini Notebook/NotebookLM s
  Google AI plánem přes Google One; Enterprise funkce účet odmítá. V1 proto
  necílí na Google Cloud Enterprise API. Oficiální nápověda potvrzuje oddělené
  Google AI plány a Cloud Enterprise, export jednotlivých poznámek do Docs a
  vybraných Studio výstupů do Docs/Sheets; kopie notebooku přenáší sources a
  Studio obsah, ale výslovně ne chat history ani notes. Jediný úplný přenosný
  formát osobního notebooku tím není doložen a musí jej určit skutečný Takeout
  export. Podklady ověřené 2026-10-08: [plány Gemini Notebook](https://support.google.com/gemininotebook/answer/16213268?hl=en),
  [export poznámek](https://support.google.com/gemininotebook/answer/16262519?hl=en),
  [obsah a kopie notebooku](https://support.google.com/gemininotebook/answer/16206563?hl=en)
  a [Google Takeout](https://support.google.com/accounts/answer/3024190?hl=en).
- První verze importuje uživatelem dodaný lokální export/bundle. Nečte session
  cookies, nevolá neoficiální interní endpointy, nescrapuje přihlášené UI,
  nezapisuje zpět do NotebookLM a neposílá importovaný obsah LLM. Přímý
  oficiální konektor lze přidat pouze pokud je doložen pro skutečnou edici a
  stejný importní manifest.
- Archiv/bundle je nedůvěryhodný vstup. Preview musí před zápisem omezit
  celkovou i rozbalenou velikost, počet souborů, hloubku a délku cest; odmítnout
  absolutní cesty, traversal, symlinky, hardlinky, zařízení, duplicitní cesty,
  nested archive bombs a spustitelné HTML/skripty. Neznámé soubory se neprovádějí
  ani potichu nezahazují.
- Reuse: adaptovat `ProjectCreation`, `Sources`, metadata/provenance v2,
  source immutability, Workspace/Journal/Index, bezpečný preview a existující
  desktop/web RBAC. Soukromý katalog nepřinesl komponentu, která by nahradila
  tyto autority. Nevytvářet druhý Git writer, projektový index, cloudovou kopii
  credentials, obecný ETL framework ani novou databázi.

## Persistentní vrstvy a crash boundaries

- Před potvrzením je přijatý bundle pouze node-local bounded vstup s hashem a
  read-only preview; projektový Git, registr uzlu a projektový index se nemění.
- Potvrzení se váže na přesný hash bundle, edici/formát, verzi importéru,
  cílovou cestu, privacy a kanonický importní plán. Změna kteréhokoli pole ruší
  preview a vyžaduje nový operation ID.
- Vytvoření projektu, jeho počáteční validovaný Git snapshot, lokální stav,
  index a registrace uzlu musí mít jednu autoritativní durable operaci. Návrh
  části A rozhodne, zda bezpečně rozšířit existující `ProjectCreation`, nebo
  použít nadřazený journal; samostatná série nevratných importních commitů bez
  recovery není přípustná.
- Pád před publikací cílového rootu nesmí zanechat registrovaný či částečně
  viditelný projekt. Po publikaci rootu recovery dokončí stav/index/registraci
  a vrátí tentýž receipt, projekt UUID a commit, nikdy druhý projekt. Cizí
  cílová cesta, změněný bundle/plán nebo konflikt registrace musí fail-closed.
- Opakování stejné potvrzené operace je idempotentní. Protože osobní Takeout
  nedoložil stabilní notebook/source ID, změněný nebo přejmenovaný export se
  nespojí pouze podle názvu; vyžaduje explicitní volbu existujícího importu či
  nového projektu a zachová předchozí historii.

## Aktivní části dávky

- [x] [completed] **IMP-02-A — Edice, skutečný vzorek, kontrakt a reuse
  (designed).** Osobní Google AI edice a skutečný Takeout TGZ byly potvrzeny.
  Bez extrakce bylo ověřeno 243 běžných členů, šest NotebookLM notebooků,
  bezpečné cesty a reprezentativní notebook s 63 sources, třemi tailored-report
  artefakty a jedním chatem. ADR 0029 vymezuje source/artifact/chat mapping,
  přesný manifest, limity, privacy, absence stabilních provider ID, duplicate
  pravidla a seeded `ProjectCreation` recovery. Vzorek exportuje source obsah
  jako HTML/JSON reprezentace, nikoli původní binární bajty; chybějící notes a
  nerozřešitelné artifact source UUID se musí hlásit. Enterprise API, scraping,
  session cookies, vykonání HTML, spojování podle názvu a nový writer/DB byly
  odmítnuty.
- [x] [completed] **IMP-02-B — Bounded parser a přesný preview
  (cílová úroveň: implemented).** Implementovat parser výhradně pro doložený
  exportní formát. Zachovat bundle a původní soubory podle limitů, odvozený text
  držet odděleně, nic nevykonávat a zobrazit soupis importovaných,
  nepodporovaných a chybějících částí před potvrzením. Ověřit poškozený archiv,
  traversal/symlinky, duplicity cest, size/count/depth limity, neznámá pole a
  změnu vstupu mezi preview a potvrzením. Implementováno jako fail-closed TGZ
  parser s content-free preview a revalidovanou materializací jednoho výběru.
  Syntetická sada pokrývá platný export, traversal, symlink, case-fold kolizi,
  nested archiv, neznámé pole/kategorii, orphan obsah, script v chatu, poškozený
  gzip a změněný archiv/digest. Skutečný vzorek prošel pro všech šest notebooků:
  113 sources, tři výstupy, jeden chat a jedna sada discovered sources.
- [x] [completed] **IMP-02-C — Obnovitelné vytvoření celého projektu a UI
  (cílová úroveň: implemented).** Z potvrzeného plánu vytvořit jediný nový
  projekt přes stávající autority, s neměnnými source artefakty, oddělenými
  poznámkami/výstupy, vztahy a importní provenance. Desktop i oprávněný web
  ukážou edici, notebook, cílovou cestu, privacy, přesný obsah a receipt.
  Ověřit všechny durable hranice, restart, retry, kolizi cesty/identity a žádný
  částečný projekt nebo duplicitní commit. `ProjectCreation` nyní durable
  stageuje předem validovaný seed, vytvoří jeden počáteční commit a po pádu už
  Takeout znovu nepotřebuje. Všechny creation hranice prošly s jedním projektem
  a commitem. Desktop má nativní dvoukrokový dialog; webový tok je node-admin
  only, používá server-local TGZ a nepovoluje `local-only`. Přesné exportní
  bajty jsou immutable sources, odvozený report a metadata obálka snapshots;
  nový operation ID zobrazí shodné existující importy před potvrzením.
- [ ] [in progress] **IMP-02-D — Reálný workflow, regrese a dokumentace
  (cílová úroveň: PoC validated).** Importovat schválený skutečný notebook,
  otevřít jej po restartu a použít zdroje, poznámky, výstupy a vztahy v běžném
  Workspace workflow. Porovnat soupis s exportem, ověřit opakovaný identický i
  změněný import, jasně uvést neimportovatelné části a spustit cílené testy,
  úplnou sadu, relevantní Qt/WebEngine smoke, kontrolu dokumentace a
  `git diff --check`. Opt-in test importoval do izolovaného uzlu největší
  skutečný notebook (22 895 488 deklarovaných bajtů) jako 69 artefaktů / 138
  souborů v jediném commitu, znovu jej otevřel a ověřil stejný receipt při
  retry. Po uživatelském zjištění, že Takeout poskytuje hlavně HTML/JSON, byl běžný
  artifact preview rozšířen o bounded Markdown z HTML bez předání značek
  rendereru a o JSON v Markdown code blocku bez ztráty polí. Původní
  importované bajty se nemění. Cílených 22 testů prošlo se třemi volitelnými
  grafickými skipy; samostatný offscreen Qt/WebEngine smoke zobrazil Markdown,
  HTML text, JSON, PNG i PDF. Opt-in test největšího skutečného notebooku
  ověřil po importu odvozené Markdown náhledy HTML i JSON. Úplná sada po poslední
  změně: 427 testů OK, 26 opt-in přeskočeno; `git diff --check` prošel. Stále
  zbývá uživatelské vytvoření trvalého projektu a potvrzení použití po běžném
  restartu skutečného okna.

## Podmínky dokončení dávky

- Jeden skutečný NotebookLM notebook vznikne jako použitelný nový Workspace
  projekt bez ručního rozebírání exportu a bez ztráty doložených částí.
- Přehled přesně rozliší importované, nepodporované a v exportu chybějící části;
  žádný chat, prompt, citace, čas, autor ani revize se nevymýšlejí.
- Původní přijaté bajty, odvozeniny, provenance, privacy a vztahy zůstávají
  rozlišitelné; importované zdroje se potichu nepřepisují ani automaticky
  neposílají modelu.
- Přerušení na každé durable hranici a retry nevytvoří částečný či duplicitní
  projekt. Cílená regrese, úplná sada a skutečný vzorek projdou; neprovedené
  ověření zůstane výslovně otevřené.

## K předání do backlogu

- **IMP-01 — doplnění z uživatelského workflow 2026-10-08:** uživatel často
  uchovává jednotlivé projektové podklady na osobním Google Drive. První
  praktický tok má nabídnout explicitní ruční výběr jednoho nebo více
  souborů či složky a jejich jednorázový import do zvoleného aktivního projektu
  s náhledem, privacy a provenance. Nemá bez samostatného rozhodnutí procházet
  celý Drive, zapnout průběžnou synchronizaci ani zapisovat zpět do Drive.
  Běžné soubory stáhnout v původních bajtech; nativní Docs/Sheets/Slides
  exportovat do explicitně uvedeného formátu a transformaci nezaměňovat za
  původní obsah. OAuth scopes, picker, sdílené položky, duplicity/revize,
  odvolání přístupu, limity a recovery přerušeného přenosu ověřit při aktivaci
  samostatné dávky proti aktuálnímu oficiálnímu API.
