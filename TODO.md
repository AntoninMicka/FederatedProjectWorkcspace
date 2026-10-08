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
- Opakování stejné potvrzené operace je idempotentní. Nový export se stejnou
  doloženou notebook identity, ale jinými bajty není tichý overwrite; preview
  jej označí jako novou verzi/import a zachová předchozí projekt i historii.

## Aktivní části dávky

- [ ] [in progress] **IMP-02-A — Edice, skutečný vzorek, kontrakt a reuse
  (cílová úroveň: designed).** Potvrdit osobní/Plus/Workspace versus Enterprise
  edici a získat jeden uživatelem schválený export kompletního notebooku.
  Inventarizovat přesnou strukturu a zvlášť doložit dostupnost zdrojů, poznámek,
  generovaných výstupů, citací/vztahů, chatu a notebookových metadat. Navrhnout
  kanonický import manifest, mapování notebook → projekt a položka → artefakt,
  limity, privacy, preview, duplicate/version pravidla a výše uvedenou recovery.
  ADR změnit jen pokud skutečný formát vyžaduje nové rozhodnutí.
- [ ] [planned] **IMP-02-B — Bounded parser a přesný preview
  (cílová úroveň: implemented).** Implementovat parser výhradně pro doložený
  exportní formát. Zachovat bundle a původní soubory podle limitů, odvozený text
  držet odděleně, nic nevykonávat a zobrazit soupis importovaných,
  nepodporovaných a chybějících částí před potvrzením. Ověřit poškozený archiv,
  traversal/symlinky, duplicity cest, size/count/depth limity, neznámá pole a
  změnu vstupu mezi preview a potvrzením.
- [ ] [planned] **IMP-02-C — Obnovitelné vytvoření celého projektu a UI
  (cílová úroveň: implemented).** Z potvrzeného plánu vytvořit jediný nový
  projekt přes stávající autority, s neměnnými source artefakty, oddělenými
  poznámkami/výstupy, vztahy a importní provenance. Desktop i oprávněný web
  ukážou edici, notebook, cílovou cestu, privacy, přesný obsah a receipt.
  Ověřit všechny durable hranice, restart, retry, kolizi cesty/identity a žádný
  částečný projekt nebo duplicitní commit.
- [ ] [planned] **IMP-02-D — Reálný workflow, regrese a dokumentace
  (cílová úroveň: PoC validated).** Importovat schválený skutečný notebook,
  otevřít jej po restartu a použít zdroje, poznámky, výstupy a vztahy v běžném
  Workspace workflow. Porovnat soupis s exportem, ověřit opakovaný identický i
  změněný import, jasně uvést neimportovatelné části a spustit cílené testy,
  úplnou sadu, relevantní Qt/WebEngine smoke, kontrolu dokumentace a
  `git diff --check`.

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
