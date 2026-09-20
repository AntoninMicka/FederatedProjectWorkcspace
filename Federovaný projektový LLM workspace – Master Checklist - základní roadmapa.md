<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Federovaný projektový LLM workspace
## Master Checklist / základní roadmapa

Aktuální implementační práce: **M2 — Local AI**; Gate M1 zůstává otevřený kvůli odložené cílové restartové akceptaci. Aktuální feature dávka je v [TODO.md](TODO.md), další připravené feature dávky a strategický zásobník v [BACKLOG.md](BACKLOG.md) a uzavřené dávky s důkazy ve [WORK_LOG.md](WORK_LOG.md); pravidla vývoje v [AGENTS.md](AGENTS.md). Jedna dávka představuje jednu ucelenou feature, jednu feature větev a jeden PR do `develop`; milník se skládá z více takových dávek a jeho gate se vyhodnocuje samostatně.

Tento dokument drží strategii, milníky, gates a původní katalog požadavků. Průběžné implementační podrobnosti a ad-hoc úkoly patří do TODO; BACKLOG a WORK_LOG se aktualizují při uzavření a předání dávky podle AGENTS. Nezaškrtnuté požadavky neznamenají, že se již přijatá architektonická rozhodnutí znovu otevírají. U dokončených bodů rozlišujeme **designed** a **PoC validated**; ani jeden stav sám o sobě neznamená produkční implementaci. M1–M6 zůstávají otevřené i tam, kde existuje související M0 experiment.

Podpůrnou IP, publikační a crowdfundingovou agendu drží [IP roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>) a její dva registry. Navazuje na významná architektonická rozhodnutí (FTO screening a posouzení disclosure), veřejné releases (archivace commit/tag/release a případného DOI) a přípravu kampaně (Gate C0, IP freeze a crowdfunding readiness). Tyto kontroly nemění pořadí M0–M6 ani neprokazují splnění produktových gates. Technické integrační úkoly jsou v BACKLOG; administrativa zůstává v `docs/IP`.

Rozšíření o externí vztahy, komunikaci a řízené sdílení drží sekce 22. Jde o plánované schopnosti nad stávajícím jádrem, nikoli druhou roadmapu nebo implementovaný mail klient. Původní návrh patche označoval kontrakt jako M0-10; protože Gate M0 je již uzavřen, je požadavek veden jako navazující návrhová práce v BACKLOG a zpětně M0 neotevírá.

## 0. Cíl MVP

- [ ] Definovat systém jako **self-hosted projektový workspace** provozovatelný primárně:
  - [ ] na Turris Omnia,
  - [ ] v LXC kontejneru,
  - [ ] jako desktopovou aplikaci s vlastním lokálním uzlem,
  - [ ] případně později na běžném Linux serveru / workstation.
- [ ] Jeden uzel = samostatně provozovatelná instance.
- [ ] Desktopová aplikace je plnohodnotný uzel federace s lokálním backendem a daty; umí samostatný provoz i připojení k dalším uzlům.
- [ ] Více uzlů = federace definovaných důvěryhodných uzlů.
- [ ] Projektová data primárně ukládat jako **soubory verzované Gitem**.
- [ ] Oddělit:
  - [ ] projektová data,
  - [ ] metadata,
  - [ ] uživatele,
  - [ ] role,
  - [ ] LLM backendy,
  - [ ] historii rozhodnutí,
  - [ ] generované snapshoty.
- [ ] Umožnit používat více LLM providerů s jasně definovanými rolemi.
- [ ] Core orchestrace systému nesmí být závislá na dostupnosti LLM; deterministický aplikační orchestrátor musí fungovat i bez lokálního nebo externího modelu.
- [ ] Konverzační orchestraci („orchestrator chat“) navrhnout jako volitelnou LLM vrstvu nad deterministickým aplikačním orchestrátorem.
- [ ] Nedostupnost lokálního LLM nesmí způsobit tichý fallback na externího providera; změna execution boundary musí být explicitně povolená policy.
- [ ] Lokální Ollama používat primárně jako:
  - [ ] klasifikátor,
  - [ ] extraktor,
  - [ ] sumarizátor,
  - [ ] filtr kontextu,
  - [ ] případně anonymizátor/redaktor před odesláním dat ven,
  - [ ] volitelně orchestrator chat / planner, pokud je lokální model dostupný.
- [ ] Externím LLM neposílat automaticky celý projekt, ale pouze **sestavený kontext potřebný pro konkrétní úlohu**.

---

# 1. Průzkum a recyklace existujících řešení

## 1A. Inventura vlastních projektů

- [ ] Projít existující vlastní projekty a vytvořit katalog potenciálně znovupoužitelných komponent.
- [ ] U každé komponenty evidovat:
  - [ ] zdrojový projekt,
  - [ ] cestu/repository,
  - [ ] účel,
  - [ ] jazyk/framework,
  - [ ] závislosti,
  - [ ] licenci,
  - [ ] stav,
  - [ ] vhodnost pro reuse,
  - [ ] nutné úpravy.
- [ ] Zmapovat existující řešení pro:
  - [ ] federaci uzlů,
  - [ ] ZeroTier/WireGuard networking,
  - [ ] správu uzlů,
  - [ ] uživatele a autentizaci,
  - [ ] role/RBAC,
  - [ ] Git operace,
  - [ ] REST API,
  - [ ] frontend,
  - [ ] správu konfigurace,
  - [ ] import/export,
  - [ ] práci s Ollama,
  - [ ] externí LLM API,
  - [ ] práci s dokumenty,
  - [ ] audit/logování.

## 1B. Evidence kandidátních řešení

- [x] Zavést `reuse-catalog` — evidence kandidátů existuje v REUSE_CATALOG.md; inventura vlastních projektů zůstává otevřená.
- [ ] Každému kandidátu přiřadit stav:
  - [ ] `candidate`
  - [ ] `evaluate`
  - [ ] `reuse`
  - [ ] `adapt`
  - [ ] `reject`
- [ ] Evidovat důvod rozhodnutí.
- [ ] Nepřenášet komponenty automaticky – nejprve posoudit kompatibilitu s novou architekturou.

---

# 2. Datový model projektu

## 2A. Git jako primární projektový datastore

**Stav M0/M1:** autoritativní Git a lokální index jsou přijatý návrh; relační projekce metadat a vztahů v1 je lokálně PoC validated dle ADR 0022. F-M1-META-01 upřesňuje význam v1 a navrhuje kompatibilní importní provenance v2 v [ADR 0023](docs/adr/0023-metadata-and-import-provenance.md); v2 parser, index ani migrace nejsou implementovány.

- [ ] Jeden projekt reprezentovat Git repozitářem.
- [x] Definovat základní adresářovou strukturu — designed pro M0 v DATA_MODEL.md; minimální project.json/node.json v1 a samostatná validace viz ADR 0004.
- [ ] Oddělit:
  - [ ] aktivní projektové dokumenty,
  - [ ] zdroje,
  - [ ] metadata,
  - [ ] rozhodnutí,
  - [ ] hypotézy,
  - [ ] úkoly,
  - [ ] LLM výstupy,
  - [ ] snapshoty,
  - [ ] statická aktiva.
- [ ] Stanovit pravidla automatických commitů.
- [ ] Umožnit ruční commit s komentářem.
- [ ] Evidovat autora změny.
- [ ] Připravit mechanismus řešení konfliktů.
- [ ] Projektová metadata a registry verzovat v Gitu jako autoritativní data.
- [ ] SQLite používat jako lokální, z Gitu obnovitelný index pro dotazy a vztahy; databázový soubor nesynchronizovat.
- [ ] SQLite index neslouží k řešení souběžných změn ani merge konfliktů; ty řešit nad autoritativními soubory před aktualizací indexu.
- [ ] Změny projektových metadat zapisovat přes soubory v Gitu; index aktualizovat po úspěšném commitu/merge a při startu ověřit jeho verzi vůči HEAD.
- [ ] Oddělit obnovitelný projektový index od autoritativního lokálního stavu uzlu (identita, credentials, rozpracované operace).
- [ ] Každou entitu registru ukládat do samostatného souboru se stabilním ID; společné seznamy generovat z indexu.
- [ ] Rozdělení registrů omezuje kolize změn různých entit; souběžné změny stejné entity stále vyžadují sloučení a validaci.
- [ ] Index označit ID indexovaného commitu; při nesouladu jej obnovit a do té doby nezobrazovat zastaralé výsledky jako aktuální. Rozpracované změny zobrazovat odděleně od indexu commitnutého stavu.
- [ ] Po merge validovat schémata, unikátnost ID a vztahy; textově čistý merge nemusí být významově správný.

## 2B. Typy souborů

- [ ] Markdown jako primární formát pro:
  - [ ] teze,
  - [ ] poznámky,
  - [ ] analýzy,
  - [ ] rozhodnutí,
  - [ ] checklisty,
  - [ ] jednodušší projektové dokumenty.
- [ ] JSON/YAML pro:
  - [ ] strukturovaná metadata,
  - [ ] konfiguraci,
  - [ ] registry,
  - [ ] vztahy mezi objekty,
  - [ ] strojově zpracovávané projektové entity.
- [ ] PDF používat jako:
  - [ ] časový snapshot,
  - [ ] externí dokument,
  - [ ] neměnný zdroj,
  - [ ] archivní výstup.
- [ ] Binární/static assets:
  - [ ] obrázky,
  - [ ] schémata,
  - [ ] přílohy,
  - [ ] případně CAD a další projektové soubory.

## 2C. Uložení metadat podle formátu

**Stav M0: PoC validated.** Frontmatter/sidecar parser, společné schéma, registry po entitách a kontrola vztahů jsou implementované v `spikes/metadata.py`. Zachování bajtů importu a obnova souborových změn jsou ověřené. Níže uvedené aplikační schopnosti zůstávají otevřené do integrace; neimplementovat znovu jejich PoC. Přejmenování v journalu není ověřením distribuovaného merge.

- [ ] Pro editovatelné projektové Markdown dokumenty používat YAML frontmatter jako jediné místo autoritativních metadat dokumentu.
- [ ] Importované zdroje, které mají zůstat beze změny, zachovat v původních bajtech včetně Markdownu; jejich projektová metadata uložit do sidecaru — import PoC validated, pravidla následných změn a verzí designed v [ADR 0024](docs/adr/0024-source-immutability-and-versioning.md), transition validátor není implementován.
- [ ] Pro PDF, obrázky a další formáty bez vhodných editovatelných metadat použít sidecar se stabilním ID artefaktu.
- [x] V M0 určit povinná pole, verzi schématu a konvenci umístění sidecaru; vazbu založit na stabilním ID s evidencí aktuální cesty souboru — PoC validated, ADR 0002.
- [ ] Přejmenování nebo smazání artefaktu promítnout do sidecaru a odkazů v jednom commitu; před commitem ověřit konzistenci.
- [x] Navrhnout obnovu přerušené změny souboru a sidecaru — PoC validated pomocí journalu (ADR 0002); koordinace celé operace s commitem/indexem je Linux PoC validated v ADR 0003.
- [ ] Konflikty změna–smazání, přejmenování–úprava a osiřelý sidecar řešit explicitně; metadata nesmějí být tiše zahozena.
- [ ] Metadata neduplikovat mezi frontmatter a sidecarem; použít společné logické schéma pro oba způsoby uložení.
- [ ] Strukturované entity registrů ukládat jako JSON s vlastními poli ID a verze schématu; nepřidávat k nim duplicitní sidecar.

## 2D. Verzovací filtry

- [ ] Navrhnout normalizační pipeline před commitem.
- [ ] Odstraňovat nedeterministická metadata tam, kde je to bezpečné.
- [ ] Stabilizovat formát JSON/YAML.
- [ ] Normalizovat Markdown.
- [ ] Oddělit obsah od automaticky generovaných metadat.
- [ ] Pro velké binární soubory zvážit Git LFS.
- [ ] Připravit diff-friendly reprezentaci vybraných komplikovaných formátů.


## 2E. Materializované kompiláty

**Stav: designed, neimplementováno.** [ADR 0018](docs/adr/0018-materialized-compilations.md) vymezuje lokální zahoditelné výsledky zpracování zdrojů podle zadání, například orientační rozpočtové obálky. Návrh vznikl z ad-hoc požadavku M1-AH-01; důkaz návrhové kontroly drží [WORK_LOG](WORK_LOG.md).

- [ ] Uchovat zadání a pravidlo výběru zdrojů odděleně od výsledku; přenositelné definice verzovat, výstupní soubory ukládat jako lokální cache mimo projektový Git.
- [ ] Nabídnout ruční aktualizaci z aktuálních verzí i nových zdrojů odpovídajících pravidlu výběru. Neprovádět automatický výpočet při otevření či restartu.
- [ ] Zobrazit použitou verzi vstupů, stáří, neaktuálnost a stav výpočtu; změnu/odstranění zdroje neskrývat.
- [ ] Cache neverzovat ani nepřenášet při federaci/exportu; umožnit její odstranění a nový výpočet bez ztráty zdrojů či zadání.
- [ ] Respektovat privacy a oprávnění vstupů, Context Manifest pro LLM a recovery oddělené od autoritativního journalu/run recordu.
- [ ] Výsledek určený k trvalému uchování uložit pouze explicitní akcí jako běžný verzovaný artefakt s provenance.

Navazuje na zdroje a metadata M1, případné LLM zpracování na M2/M3. Nezavádí novou podmínku Gate M1 ani povinný LLM backend. Konkrétní implementační kroky patří do pracovní dávky podle priority.

## 2F. Read-only artefakty sdílené mezi projekty

**Stav: designed / plánováno, neimplementováno.** Cílem je umožnit použít jeden autoritativní artefakt ve více projektech bez tichého vytvoření editovatelných kopií. Jde o aplikační meziprojektovou referenci podobnou symlinku, nikoli o filesystemový symlink; ten současné bezpečnostní a validační kontrakty nadále odmítají.

- [ ] Konzumující projekt ukládá verzovaný referenční záznam, který identifikuje zdrojový projekt/repozitář, artifact ID, úplný Git commit, očekávaný hash obsahu a rozsah reference. Samotná lokální cesta, název projektu, branch nebo pohyblivý `HEAD` nestačí.
- [ ] Výchozí reference je připnutá na konkrétní revizi a v cílovém projektu pouze pro čtení. Volitelné sledování zdroje smí nabídnout novou revizi, ale nesmí bez potvrzení přepsat použitý obsah ani reprodukovatelnost starého commitu.
- [ ] Oprávnění kontrolovat při vytvoření i každém rozlišení reference. Přístup cílového projektu nezakládá přístup ke zdrojovému projektu; efektivní privacy nesmí být méně přísná než u zdroje. Revokovaný, smazaný nebo nedostupný zdroj zobrazit jako nerozlišenou/stale referenci, ne jako prázdný či nový artefakt.
- [ ] Offline cache je pouze lokální ověřená projekce konkrétní revize s hashem a stavem stáří; není druhou autoritativní kopií a nesmí se automaticky commitnout do konzumenta nebo federovat bez oprávnění.
- [ ] Pokus o editaci nabídne explicitní vytvoření vlastní kopie/forku s novým artifact ID a provenance na přesnou zdrojovou revizi. Původní reference zůstává beze změny; zpětný zápis do zdrojového projektu není součástí této schopnosti.
- [ ] Index, hledání, Context Builder a export musejí odlišit vlastní artefakt, read-only referenci, lokální cache a explicitní snapshot. Do LLM kontextu nebo exportu lze zahrnout jen znovu autorizované bajty přesné revize; bez nich se přenáší pouze reference a stav nedostupnosti.

První implementační rozsah je sdílení mezi dvěma lokálně registrovanými projekty na jednom uzlu. Vzdálené rozlišení reference a federace cache navazují na M5; obecný externí katalog a cross-repo identity koordinovat s ER-00/ER-01. Konkrétní dávku drží BACKLOG XREF-01.

## 2G. Modelování a výpočty v Julii

**Stav: Julia zvolena jako preferovaný výpočetní backend; integrace je designed / plánována, neimplementována.** Cílem je workflow pro numerické modely, simulace, optimalizace, statistiku, tabulkové výpočty a grafické výstupy obdobné použití MATLABu, nikoli implementace jeho kompatibility nebo závislosti na něm. Julia navazuje na materializované kompiláty z 2E a používá stejné hranice autoritativních zdrojů, lokální cache a explicitní publikace.

- [ ] Verzovat zdrojový model jako běžné projektové artefakty (`.jl` a související dokumentace), jeho deklarované vstupy a reprodukovatelné Julia prostředí. Minimální kontrakt prostředí zahrne `Project.toml` a odpovídající `Manifest.toml`; credentials, registry cache, stažené balíčky, compiled cache a uživatelský startup do projektového Gitu nepatří.
- [ ] První rozsah realizovat jako lokální CLI runner pro explicitně zvolený entry point, parametry a zmrazené revize vstupů. Notebookové UI (např. Pluto/Jupyter) ani interaktivní MATLAB-like desktop nejsou podmínkou prvního PoC a vyžadují samostatné capability, bezpečnostní a distribuční posouzení.
- [ ] Run record uchová project/operation/run ID, commit modelu, artifact ID a hash každého vstupu, entry point a parametry, verzi Julia/runtime a platformu, hash prostředí, volitelný seed, časy, stav/exit code, stdout/stderr a hashe výstupů. Shodné vstupy ani seed samy negarantují bitově shodný numerický výsledek napříč verzemi, platformami a knihovnami.
- [ ] Výstupy nejprve publikovat jako atomickou lokální generaci materializovaného kompilátu mimo projektový Git. Tabulku, graf, report, dataset nebo jiný výsledek uložit jako verzovaný projektový artefakt pouze explicitní akcí s provenance na run record, model, prostředí a přesné vstupy.
- [ ] Julia kód považovat za spustitelný a potenciálně nedůvěryhodný. Import ani otevření projektu jej nesmí spustit; běh vyžaduje explicitní potvrzení, execution policy, limity času/procesů/paměti/výstupu, izolovaný pracovní adresář a výchozí zákaz sítě. Izolaci nevydávat za bezpečný sandbox bez samostatného ověření cílového OS.
- [ ] Privacy a oprávnění vstupů znovu ověřit před během i před publikací; výstup nesmí automaticky dostat slabší privacy než nejpřísnější vstup. Nedostupný runtime/balíček, změna HEAD, timeout, pád, neúplný výstup a přerušený běh musí mít rozlišitelné stavy a bezpečný retry bez vydávání staré cache za aktuální.
- [ ] Způsob instalace Julia runtime a balíčků, podporované verze/platformy, offline depot, aktualizace, licence a distribuční velikost rozhodnout a ověřit před přidáním do `.deb`; vývojová instalace na jednom stroji není důkazem podporované distribuce.

Operativní rozpad drží BACKLOG COMP-01 a COMP-02. Julia runner není LLM backend a jeho deterministické nebo numerické výstupy se nesmějí evidenčně smíchat s LLM run records.

---

# 3. Metadata a zdrojování

## 3A. Metadata dokumentu

**Stav F-M1-META-01: designed.** Současné `created_at` je vznik entity v projektu a u nativního importu čas importu; `author_id` je projektový aktér/importér, nikoli původní autor zdroje. Podrobná importní provenance vyžaduje verzované schéma v2 podle ADR 0023; v1 zůstává beze změny platné.

- [ ] Každému souboru umožnit přiřadit:
  - [ ] ID,
  - [ ] název,
  - [ ] stručný popis,
  - [ ] typ,
  - [ ] autora,
  - [ ] datum vzniku,
  - [x] datum importu — designed pro v2 v ADR 0023; implementace a migrace zůstávají otevřené,
  - [ ] zdroj,
  - [ ] URL/reference,
  - [ ] tagy,
  - [ ] vztahy k ostatním dokumentům.
- [ ] Popis umožnit:
  - [ ] zadat ručně,
  - [ ] automaticky vygenerovat přes Ollama,
  - [ ] automaticky aktualizovat pouze po potvrzení uživatelem.

## 3B. Provenance

- [ ] Rozlišovat:
  - [ ] primární zdroj,
  - [ ] uživatelský dokument,
  - [ ] externí zdroj,
  - [ ] LLM-generated,
  - [ ] LLM-transformed,
  - [ ] snapshot.
- [ ] U LLM výstupu ukládat:
  - [ ] backend,
  - [ ] model,
  - [ ] roli,
  - [ ] čas,
  - [ ] vstupní artefakty,
  - [ ] prompt/template,
  - [ ] případně parametry inference.
- [ ] Umožnit dohledat:
  **„Z čeho tento závěr vznikl?“**

---

## 3C. Import z Google služeb, NotebookLM a chatbotů

**Stav: designed / plánováno, žádný konektor ani automatické zařazení nejsou implementovány.** „Gemini notebook“ zde znamená NotebookLM; konkrétní edici účtu ověřit před implementací. Navazuje na import artefaktů M1 a provenance; neblokuje současné desktopové PoC. Operativní kroky drží BACKLOG IMP-01 až IMP-04.

- [ ] Google služby podporovat dvěma vstupními cestami: přímý konektor přes oficiální API, pokud pro konkrétní službu a edici existuje, a lokální import uživatelem dodaného exportu (např. Google Takeout nebo nativní export služby). Každou službu, scope, formát a omezení ověřovat samostatně; Data Portability API ani Drive API nepovažovat za univerzální přístup ke všem datům účtu.
- [ ] Google Drive: umožnit explicitní výběr souborů/složek, stažení binárních souborů a export podporovaných Google Docs/Sheets/Slides přes oficiální API. U nativních Workspace dokumentů evidovat exportní formát a transformaci, neoznačovat export za původní bajty zdroje. Další Google služby přidávat po samostatném ověření API nebo skutečného exportu, nikoli jen podle názvu produktu.
- [ ] NotebookLM: importovat dostupné zdroje, uživatelské poznámky a generované výstupy jako odlišné artefakty; zachovat citace a vazby, pokud jsou exportem/API poskytovány. Nedostupné části uvést v přehledu importu. Rozlišit běžný NotebookLM a Enterprise; existence Enterprise API není důkaz dostupnosti stejné funkce běžnému účtu ani exportu celé historie chatu.
- [ ] Chatboty: podporovat import uživatelem získaných exportů (např. ChatGPT nebo Gemini/Takeout) a ručně dodaného textu/Markdownu. Konkrétní formáty potvrdit na vzorcích; odlišit archiv konverzace od samostatné odpovědi. Zachovat role, pořadí, čas, větvení, přílohy a zdrojová ID, pokud je export obsahuje; chybějící hodnoty nevymýšlet.
- [ ] Dostupnost čtení historie ověřovat samostatně pro každý produkt a edici. Generační API modelu není automaticky přístup k historii jeho webového chatbota. Při chybějícím oficiálním API nabídnout souborový import; nevyžadovat session cookies ani neoficiální interní endpointy.
- [ ] Import s aktivním projektem nejprve nabídne náhled výběru, cílový projekt a privacy třídu. Oprávnění cloudového zdroje nepřenášet automaticky na projektové RBAC; OAuth credentials držet mimo Git, používat minimální potřebná oprávnění a zvládnout odvolání přístupu.
- [ ] Podporovat také import bez aktivního projektu do lokální soukromé vstupní fronty. Přijatá data se před rozhodnutím nesmějí zapsat do projektového Gitu ani automaticky sdílet; fronta musí mít doložený lifecycle, limity, karanténu chyb, obnovu po pádu a explicitní odstranění.
- [ ] Volitelný lokální LLM nad vstupní frontou navrhne zařazení do nuly, jednoho nebo více projektů, včetně důvodu, confidence, navržené privacy třídy a metadat. Smí posuzovat pouze projekty, do nichž má aktér právo zapisovat; `local-only` obsah nesmí opustit stejný uzel a nedostupnost lokálního modelu nesmí vyvolat externí fallback. Návrh sám nic nezapisuje a uživatel jej může upravit, odmítnout nebo ponechat nezařazený.
- [ ] Potvrzené zařazení do více projektů provést jako samostatné obnovitelné Workspace operace s výsledkem pro každý projekt; částečný úspěch neskrývat ani kompenzačně nemažat již publikovaný commit. Společný vstup, hash a bezpečný identifikátor příjmu musí umožnit dohledání a idempotentní retry bez předstírání jedné atomické transakce napříč repozitáři.
- [ ] Evidovat původní službu/ID/URL, zdrojovou revizi, doložený `source_created_at` a dostupné zdrojové časy změny/exportu odděleně od `imported_at`, dále hash importovaných bajtů a způsob převodu. Časy vzniku mohou importu předcházet a chybějící hodnoty se neodhadují z času importu ani souborového mtime. Uchovat přijatý export jako neměnný zdroj a odvozený text odděleně. U LLM výstupů nepředpokládat dostupnost modelu, promptu či úplného Context Manifestu.
- [ ] Opakovaný import musí rozpoznat duplicity a nabídnout novou verzi při změně zdroje; lokální editace nesmí tiše přepsat. Import není obousměrná synchronizace ani automatický zápis zpět do cloudu. Importované dokumenty se bez explicitního dalšího kroku neposílají LLM.

Podklady ověřené 2026-09-17: [Drive download/export](https://developers.google.com/workspace/drive/api/guides/manage-downloads), [Google Takeout](https://support.google.com/accounts/answer/3024190?hl=en), [Data Portability API](https://developers.google.com/data-portability/user-guide/overview), [Notebook Enterprise API — preview](https://docs.cloud.google.com/gemini/enterprise/notebooklm-enterprise/docs/api-notebooks), [ChatGPT export](https://help.openai.com/en/articles/7260999-how-do-i-export-my-chatgpt-history-and-data), [Gemini Apps export přes Takeout](https://support.google.com/gemini/answer/16920332?hl=en). Tyto podklady potvrzují dílčí rozhraní/exporty, nikoli jejich dostupnost pro každý produkt, region, edici nebo účet ani úplnost importu.

---

# 4. Projektové registry

- [ ] Zavést registr předpokladů.
- [ ] Zavést registr hypotéz.
- [ ] Zavést registr otevřených otázek.
- [ ] Zavést registr rizik.
- [ ] Zavést decision log.
- [ ] Zavést registr zamítnutých variant.
- [ ] Zavést registr externích zdrojů.
- [ ] Zavést registr témat vyžadujících odborné ověření.
- [ ] Zavést registr úkolů.
- [ ] Navázat registry partnerů, vztahů, schůzek a sdílení konkrétních revizí podle sekce 22; adresář a prezentační či komunikační UI mají používat společné entity, ne paralelní databáze.
- [ ] Umožnit vztahy typu:
  - [ ] dokument → předpoklad,
  - [ ] předpoklad → rozhodnutí,
  - [ ] zdroj → tvrzení,
  - [ ] riziko → rozhodnutí,
  - [ ] otázka → odpověď,
  - [ ] rozhodnutí → následné úkoly.
- [ ] Připravit možnost pozdějšího impact analysis:
  **„Která rozhodnutí jsou ovlivněna změnou tohoto předpokladu?“**

---

# 5. Uživatelé, identity a RBAC

## 5A. Federovaní uživatelé

- [ ] Navrhnout globální identitu uživatele v rámci federace.
- [ ] Oddělit:
  - [ ] identitu uživatele,
  - [ ] členství v projektu,
  - [ ] projektové role,
  - [ ] lokální oprávnění uzlu.
- [ ] Definovat mechanismus distribuce uživatelů mezi uzly.
- [ ] Definovat řešení konfliktu změn identity.
- [ ] Definovat deaktivaci/revokaci uživatele.

## 5B. Role uživatelů

- [ ] Minimální RBAC:
  - [ ] federation-admin,
  - [ ] node-admin,
  - [ ] project-admin,
  - [ ] editor,
  - [ ] reviewer,
  - [ ] reader.
- [ ] Oprávnění řídit minimálně pro:
  - [ ] projekty,
  - [ ] soubory,
  - [ ] Git operace,
  - [ ] LLM backendy,
  - [ ] federaci,
  - [ ] export,
  - [ ] administraci.

---

# 6. Federace uzlů

## 6A. Node model

- [ ] Každému uzlu přidělit stabilní Node ID.
- [ ] Rozlišovat způsob nasazení uzlu: Turris/LXC, Linux server a desktop.
- [ ] Používat společný model identity, oprávnění a federační protokol pro všechny způsoby nasazení.
- [ ] Desktop považovat za přerušovaně dostupný uzel; chod ostatních uzlů nesmí záviset na jeho dostupnosti.
- [ ] Evidovat:
  - [ ] jméno,
  - [ ] adresy,
  - [ ] veřejný klíč,
  - [ ] capabilities,
  - [ ] dostupné backendy,
  - [ ] projekty,
  - [ ] stav synchronizace.
- [ ] Definovat trust model mezi uzly.
- [ ] Vedle technického stavu peeru (`pending` / `approved` / `revoked`) evidovat capability profil federačního vztahu `same-company-same-team`, `same-company`, `trusted-partner`, `holding-partner` nebo `partner`; nejde o automatické pořadí důvěry ani oprávnění. Neurčený profil zůstává explicitně `unspecified` a je fail-closed.
- [ ] `same-company-same-team` smí federovat identity uživatelů a jejich projektové role; credentials, session a vzdálené přihlášení zůstávají lokální. `same-company` federuje data, ale vzdálené uživatele pouze eviduje pro provenance a audit, nepřebírá je jako lokální účty ani nesynchronizuje jejich role.
- [ ] Desktop může mít s běžným peerem nejvýše `same-company`, včetně mapování kvalifikovaných identit. Pouze peer přímo založený z desktopu může mít se svým zakládajícím desktopem jednu `same-company-same-team` vazbu doloženou neměnným podepsaným původem. Tento peer ji nesmí navázat ani delegovat vůči nikomu dalšímu, ve všech ostatních vztazích se posuzuje jako desktop a běžný peer nelze dodatečně povýšit na tuto výjimku.
- [ ] `trusted-partner` smí obdržet jen vybraná data konkrétně mapovanými příjemci. `holding-partner` smí obdržet jen vybraná data, ale grant lze udělit také ověřené společnosti jako celku; členství společnosti musí být časově vymezené a verzované. `partner` má jen chat a obsah explicitně odeslaný nebo nasdílený uživatelem, bez background synchronizace a procházení projektu.
- [ ] Pro `trusted-partner` a `holding-partner` určit na přijímajícím uzlu aktivního místního styčného uživatele. Převzatá data nezpřístupnit ostatním automaticky; styčný uživatel jim přiděluje a odnímá lokální práva jen jako podmnožinu origin ACL, privacy, povolených akcí a exportních omezení. Jeho určení, výměna, deaktivace a změny grantů jsou verzované a auditované; bez aktivního styčného uživatele se nové granty odmítnou.
- [ ] Profil vztahu svázat s verzovanou lokální policy, nikoli s implicitním přístupem. Přenos `project`/`confidential` vyžaduje konkrétní project/branch scope, příslušné mapování uživatele či organizačního příjemce a právo `export`; `local-only` federaci nikdy neopouští.
- [ ] Autorizovat celý dosažitelný Git graf vybraného refu, nejen HEAD. Změna úrovně, scope, mapování nebo revokace nesmí zpětně zpřístupnit dříve odmítnutou historii bez nového explicitního rozhodnutí.

## 6B. Transport

- [ ] Primárně předpokládat privátní overlay síť.
- [ ] Podporovat ZeroTier.
- [ ] Připravit architekturu kompatibilní s WireGuardem.
- [ ] Nevázat aplikační federaci přímo na konkrétní VPN technologii.

## 6C. Synchronizace

- [ ] Git používat pro synchronizaci projektových artefaktů.
- [ ] Samostatně řešit synchronizaci:
  - [ ] uživatelů,
  - [ ] node konfigurace,
  - [ ] federation metadata.

- [ ] Definovat:
  - [ ] pull,
  - [ ] push,
  - [ ] divergence,
  - [ ] konflikt,
  - [ ] offline node,
  - [ ] návrat uzlu po delší době.
- [ ] MVP navrhnout jako **eventual consistency**, nikoli distribuovanou transakční DB.
- [ ] Na desktop synchronizovat pouze vybrané projekty, ke kterým má uživatel oprávnění.
- [ ] Lokální úpravy a commity umožnit i offline; po připojení znovu ověřit oprávnění a synchronizovat.
- [ ] Při divergenci zachovat obě historie a nabídnout řešení konfliktu bez tichého přepsání změn.
- [ ] Synchronizaci bezpečně obnovit po uspání, ukončení aplikace nebo výpadku sítě.
- [ ] V M0 určit topologii MVP, výběr synchronizačního peeru a pravidla větví; oddělit důvěru mezi uzly od směrování synchronizace.
- [ ] Již v M0 navrhnout UI konfliktu s verzemi „moje“, „příchozí“ a společným základem, náhledem výsledku a možností řešení odložit.
- [ ] Pro binární soubory nabídnout výběr verze nebo zachování obou jako samostatných artefaktů.
- [ ] Nevyřešený merge nepublikovat jako aktuální projektový stav; zachovat původní data a zobrazit blokovanou synchronizaci.

## 6D. Federovaný uživatelský chat

- [ ] Umožnit chat mezi explicitně mapovanými lokálními uživateli schválených peerů; federace nezavádí vzdálené přihlášení, globální účet ani přenos credentials.
- [ ] První rozsah tvoří přímé a explicitně založené skupinové vlákno. Každá zpráva má stabilní ID, kvalifikovaného autora, thread ID, lokální pořadí, čas přijetí a podpis/transportní provenance; samotné hodiny uzlů neurčují globální pořadí.
- [ ] Zprávy přenášet přes durable outbox/inbox s idempotentním doručením, deduplikací, stavy pending/sent/delivered/failed/unknown, offline pokračováním a revokací dalšího přístupu. Již přijatou historii tiše nepřepisovat ani nevydávat odvolání za kryptografické smazání cizí kopie.
- [ ] Vlákno bez jiného účelu klasifikovat jako `brainstorming`. Lidský chat funguje bez LLM; volitelné shrnutí nebo návrh zadání smí použít jen backend povolený privacy a execution-boundary policy.
- [ ] Nabídnout explicitní uložení vybraného rozsahu konverzace, shrnutí, zadání nebo jiného podporovaného typu artefaktu. Před zápisem zobrazit cílový projekt, typ, obsah, provenance, účastníky a výslednou privacy; samotná zpráva ani LLM návrh nic nepublikuje.
- [ ] Publikovaný artefakt váže thread/message ID a přesné revize vstupů, dědí nejpřísnější privacy a průnik oprávnění použitých zpráv/příloh a zapisuje se standardním Workspace expected-HEAD/journal/CAS/index/receipt lifecycle. Libovolný artefakt znamená pouze typ podporovaný schématem a oprávněními, nikoli spustitelný či nevalidovaný obsah.
- [ ] Oddělit lokální pracovní stav chatu, federované doručení a Git artefakt. Snapshot či shrnutí v projektu není autoritativní kopií živého vlákna a jeho editace nepřepisuje původní zprávy.

---

# 7. LLM backend abstraction

## 7A. Backend registry

- [ ] Vytvořit abstraktní definici LLM backendu.
- [ ] Backend definovat nezávisle na projektu.
- [ ] Každý uzel spravuje vlastní backendy.
- [ ] Backend může být:
  - [ ] Ollama,
  - [ ] OpenAI-compatible API,
  - [ ] konkrétní cloud provider,
  - [ ] budoucí vlastní adapter.
- [ ] U backendu evidovat:
  - [ ] endpoint,
  - [ ] provider,
  - [ ] model,
  - [ ] capabilities,
  - [ ] limity,
  - [ ] privacy classification,
  - [ ] cenu/cost policy,
  - [ ] účel/capabilities použití (např. orchestrator chat, role execution, extraction/summarization, Context Builder).
- [ ] Oddělit účel backendu od jeho execution boundary.
- [ ] Rozlišovat minimálně execution boundary:
  - [ ] `same-node`,
  - [ ] `trusted-federation`,
  - [ ] `external-provider`.
- [ ] Dostupnost backendu nesmí sama změnit autorizaci ani povolenou trust boundary.

## 7B. Secrets

- [ ] API klíče nikdy neukládat do projektového Gitu.
- [ ] Secrets držet lokálně na uzlu.
- [ ] Backend konfiguraci rozdělit na:
  - [ ] synchronizovatelnou definici,
  - [ ] lokální credentials.

## 7C. Usage & billing — volitelná indikace

- [ ] U backendů, kde to dává smysl a lze údaje získat podporovaným rozhraním, zobrazovat spotřebu a billing podle dostupných capabilities; podporu usage a billing rozlišovat samostatně.
- [ ] Usage může zahrnovat vstupní/výstupní tokeny, počet požadavků nebo jiné backendem poskytované jednotky; billing náklady za období, zbývající kredit či čerpání kvóty, pokud jsou dostupné.
- [ ] Rozlišovat spotřebu konkrétního běhu/workspace od souhrnu poskytovatele za účet nebo organizaci. U hodnot uvádět rozsah, období, jednotku/měnu, zdroj a čas poslední aktualizace; souhrn účtu nevydávat za spotřebu projektu.
- [ ] Oddělit poskytovatelem hlášené náklady od odhadu podle ceníku; odhad jasně označit a uvést použitý ceník/verzi. Lokální backend ani chybějící billing údaj automaticky neznamenají nulové náklady.
- [ ] V UI odlišit nepodporováno, chybějící oprávnění, dočasně nedostupné a zastaralé údaje od skutečné nuly. Výpadek načítání přehledu sám o sobě neblokuje použití backendu ani nemění routing či existující cost policy.
- [ ] Účetní souhrny zobrazovat pouze oprávněným uživatelům; oprávnění používat backend samo nedává přístup k billingu celého účtu. Případné další credentials držet lokálně mimo projektový Git; účetní data automaticky nesynchronizovat s projektem.
- [ ] Přehled zpřístupnit v detailu backendu a stručnou indikaci při jeho výběru; dostupné usage konkrétního běhu také u výsledku. Jde o přehled, nikoli správu plateb nebo změny předplatného.

---

# 8. LLM role

- [ ] Role definovat nezávisle na konkrétním modelu.
- [ ] Základní role:
  - [ ] creator,
  - [ ] opponent,
  - [ ] analyst,
  - [ ] researcher,
  - [ ] editor,
  - [ ] extractor,
  - [ ] summarizer,
  - [ ] issue-spotter.
- [ ] Role obsahuje:
  - [ ] system prompt,
  - [ ] povolené zdroje,
  - [ ] požadovaný typ kontextu,
  - [ ] preferovaný backend/model,
  - [ ] privacy policy,
  - [ ] očekávaný formát výstupu.
- [ ] Umožnit projektové override rolí.
- [ ] Umožnit uživateli pro konkrétní běh změnit backend.
- [ ] Umožnit vynutit procesní oddělení:
  - [ ] creator ≠ opponent backend,
  - [ ] opponent nevidí pracovní historii creator role.

---

# 9. Lokální Ollama pipeline

- [ ] Ollama je volitelná lokální inteligentní vrstva, nikoli systémová závislost uzlu.
- [ ] Uzel bez Ollamy musí zachovat plnou základní projektovou funkcionalitu přes deterministické UI/příkazy/workflow.
- [ ] Pokud Ollama obsluhuje orchestrator chat, pouze interpretuje požadavek/plán; provedení operací zůstává v deterministickém aplikačním orchestrátoru pod RBAC, privacy policy a validací.
- [ ] Fallback orchestrator chatu konfigurovat explicitně, minimálně jako `disabled | external | selected-backend`; výchozí chování nesmí být tichý externí fallback.

## 9A. Ingest

- [ ] Import dokumentu.
- [ ] Extrakce textu.
- [ ] Identifikace typu dokumentu.
- [ ] Generování stručného popisu.
- [ ] Extrakce tagů.
- [ ] Extrakce potenciálních entit.
- [ ] Chunking.
- [ ] Uložení výsledných metadat.

## 9B. Context filter

- [ ] Uživatel zadá úlohu.
- [ ] Systém určí požadovanou LLM roli.
- [ ] Lokální model vyhledá relevantní projektové artefakty.
- [ ] Lokální model sestaví kandidátní kontext.
- [ ] Privacy filtr odstraní data, která nesmí odejít.
- [ ] Uživatel může před odesláním zobrazit:
  **„Co přesně bude odesláno externímu LLM?“**
- [ ] Teprve následně volat externí backend.

## 9C. Privacy classes

- [ ] Zavést například:
  - [ ] `public`
  - [ ] `project`
  - [ ] `confidential`
  - [ ] `local-only`
- [ ] `local-only` chápat jako `same-node`: neposílat jej jinému federovanému uzlu ani externímu providerovi bez explicitní reklasifikace.
- [ ] Pro ostatní privacy třídy určit povolené execution boundaries projektovou/user policy.
- [ ] Kontrolu provádět aplikačně, nikoli pouze promptem pro LLM.
- [ ] Výpadek nebo nedostupnost backendu nesmí automaticky rozšířit povolenou execution boundary.

---

# 10. Context builder

- [ ] Vytvořit samostatnou službu/modul Context Builder.
- [ ] Vstupy:
  - [ ] úloha,
  - [ ] uživatel,
  - [ ] role,
  - [ ] projekt,
  - [ ] vybraný backend,
  - [ ] execution boundary a capabilities cílového backendu/uzlu.
- [ ] Výstup:
  - [ ] system instructions,
  - [ ] relevantní artefakty,
  - [ ] metadata,
  - [ ] explicitní otázka.
- [ ] Podporovat:
  - [ ] automatický context,
  - [ ] ruční výběr souborů,
  - [ ] kombinaci obou.
- [ ] Evidovat manifest použitého kontextu včetně execution boundary (`same-node` / `trusted-federation` / `external-provider`).
- [ ] Umožnit později přesně rekonstruovat LLM request i místo/trust boundary jeho vykonání.

---

# 11. Workflow engine

## MVP

- [ ] Jednorázové spuštění role nad vybranými artefakty.
- [ ] Uložení výsledku jako nového artefaktu.
- [ ] Možnost výsledek:
  - [ ] přijmout,
  - [ ] zamítnout,
  - [ ] upravit,
  - [ ] předat jiné roli.

## Další fáze

- [ ] Podporovat workflow:

`creator → opponent → analyst → human decision`

- [ ] Podporovat:

`návrh → oponentura → analýza → ověření → rozhodnutí → nový návrh`

- [ ] Každý krok musí mít explicitní vstupní artefakty.
- [ ] Nepřenášet implicitně kompletní historii předchozí role.
- [ ] Umožnit checkpoint člověka mezi jednotlivými rolemi.

---

# 11A. Konverzační vlákna, persistence a projektové otisky

Konverzační vlákno je samostatný uživatelský objekt nad posloupností LLM běhů. Není totožné s jedním run recordem, Context Manifestem ani s výsledným projektovým artefaktem. Implementační dávky a jejich závislosti drží BACKLOG; tato sekce je strategický kontrakt, nikoli tvrzení o hotové implementaci.

Tato sekce pokrývá lokální LLM konverzace. Federovaný chat mezi lidmi používá stejné principy explicitního otisku a publikace, ale má vlastní zprávový transport, identity a recovery v sekci 6D; lidská zpráva není LLM run record.

- [x] Umožnit běžnou vícekolovou konverzaci s vybraným backendem/modelem a po restartu bezpečně navázat na lokálně perzistentní vlákno — F-M2-CHAT-01, PR #29.
- [x] Samostatnou konverzaci bez explicitního workflow nebo projektové role inicializovat jako `brainstorming`; klasifikace popisuje účel vlákna a sama nemění oprávnění, privacy ani roli jednotlivého LLM běhu — F-M2-CHAT-01.
- [x] Lokální pracovní stav vlákna držet mimo projektový Git a mimo obnovitelný projektový index. Oddělit jej od autoritativních run recordů; pád ani ztracená odpověď nesmí způsobit automatické zopakování `unknown` volání — F-M2-CHAT-01.
- [x] Umožnit vlákno explicitně přiřadit ke konkrétnímu projektu jako živé vlákno s možností navázání. Projektová reprezentace historie má být verzovaný Markdown s omezenými strukturovanými metadaty; lokální credentials, provider session tokeny a nepublikovaný provozní stav do Gitu nepatří — F-M2-CHAT-02.
- [ ] Každé pokračování má explicitně určené zprávy a artefakty v Context Manifestu. Backend nesmí skrytě doplnit celou starší historii ani obsah z jiného projektu.
- [x] Umožnit explicitní projektový otisk vlákna jako neměnný snapshot — F-M2-CHAT-02:
  - [x] kompletní otisk zvolené verze vlákna,
  - [x] rozdílový otisk od explicitního základního otisku/verze.
- [x] Rozdílový otisk musí nést ID a hash základu, rozsah zpráv a dostatečnou provenance. Chybějící nebo neshodný základ se nesmí tiše vydávat za kompletní konverzaci — F-M2-CHAT-02.
- [x] Rozlišit pokračující živé vlákno, jeho historický otisk a samostatný výstup konkrétního úkolu. Oponentura, brainstormingový souhrn, teze, analýza a podobné editovatelné výstupy se ukládají jako samostatné Markdown artefakty s vazbou na zdrojové vlákno/run, vstupy a Context Manifest; nejsou pouze zprávou uvnitř chatu — F-M2-CHAT-02.
- [x] Uživatelská editace odvozeného Markdown výstupu vytváří další projektovou verzi a zachová původní LLM provenance. Faktickou historii zpráv nepřepisovat bez auditovatelné nové verze — F-M2-CHAT-02.
- [x] Při přiřazení, navázání, otisku i odvození uplatnit standardní RBAC/privacy, expected-HEAD, serializovaný Git zápis, validaci a recovery. Privacy odvozeniny nesmí být slabší než nejpřísnější použitý vstup bez explicitní reklasifikace — lokální vlastník a projektová hranice PoC ověřeny ve F-M2-CHAT-02; úplné RBAC zůstává širším navazujícím rozsahem.
- [x] Před implementací rozšířit ADR 0008 o verzi a retenci vlákna, vazbu lokálního stavu na projektovou reprezentaci, full/delta kontrakt a crash boundaries publikace — F-M2-CHAT-02-A.
- [x] Režimy chatu jsou `orchestration` a `brainstorming` — F-M3-CHAT-MODES-01,
  PR #40.
  Orchestrace používá výhradně lokální `same-node` LLM a explicitní artefaktový
  kontext pro přípravu kontextu/dat, kompilaci návrhu artefaktu a filtraci;
  LLM pouze navrhuje, deterministický orchestrátor vykonává autorizované akce.
  Brainstorming dovoluje pro každý běh vybrat libovolný policy-povolený model,
  ale může přijmout explicitně připravený textový/chatový kontext; nesmí přijmout
  projektové artefakty ani jejich automaticky odvozený context. Přepnutí
  `orchestration` → `brainstorming` vždy znovu sestaví
  manifest a nepřenáší historii ani artefakty implicitně. Návrat
  `brainstorming` → `orchestration` vyžaduje ukončit a lokálně archivovat
  brainstormingové vlákno; případný Git otisk je samostatné potvrzení. Poté
  vznikne nové prázdné orchestration vlákno bez kontextu ukončeného vlákna.
  Každý budoucí vstup se znovu autorizuje a uloží do vlastního Context Manifestu.
- [ ] Doplnit uživatelskou správu lokálních vláken, úplné aplikační smazání a restartovou akceptaci — F-M2-CHAT-03: nové/navázané vlákno musí být vědomá volba, UI rozliší nepřiřazená a projektová vlákna, jejich archivaci a stav persistence. Potvrzené smazání koordinovaně odstraní všechny podporované node-local zprávy, turns, task outcomes, preview/approval a navázané run záznamy bez osiřelých dat; aktivní nebo `unknown` účinek je fail-closed a operace přes více SQLite stores má durable recovery. Publikované Git otisky a artefakty zůstávají neměnnou historií a UI je před smazáním výslovně uvede. Ověřit více vláken jednoho projektu, oddělení projektů a uživatelů, souběh i restart na každé hranici; „úplné“ není příslib forenzního přepsání média.

---

# 11B. Vlastní rozvoj produktu, IDE rozšíření a integrace coding agenta

**Stav: designed / plánováno, neimplementováno.** Workspace má po dosažení potřebných M1–M6 schopností umožnit analyzovat, plánovat a evidovat rozvoj tohoto produktu v něm samotném. Rozšíření pro Microsoft Visual Studio Code a VSCodium zpřístupní tento workflow přímo v IDE; implementaci zdrojového kódu lze předat samostatnému coding agentovi, například Codexu. Workspace zůstává autoritou projektových požadavků, rozhodnutí, úkolů, oprávnění a akceptace.

- [ ] Převést vybrané části roadmapy do verzovaných projektových entit: požadavky, milníky, feature dávky, úkoly, závislosti, rozhodnutí, rizika a akceptační podmínky. Každá odvozená entita zachová ID, zdrojovou revizi a provenance; synchronizace nesmí vytvářet druhý konkurenční stav roadmapy ani zahazovat ruční změny.
- [ ] Umožnit export lidsky čitelného Markdown TODO i strojově čitelného balíčku úkolů. Export obsahuje stabilní task ID, cíl, rozsah/mimo rozsah, závislosti, akceptaci, prioritu, stav, oprávněné vstupy a jejich přesné revize; export sám nemění stav úkolu.
- [ ] Definovat provider-neutral handoff kontrakt pro coding agenty: repozitář, výchozí commit/větev, povolené operace, Context Manifest, vybrané podklady, požadované kontroly a hranice pro commit, push, PR, externí síť a destruktivní akce. Integrace nesmí coding agentovi odvodit širší oprávnění z pouhého přidělení úkolu.
- [ ] Vytvořit rozšíření pro společný podporovaný průnik Extension API Microsoft Visual Studio Code a VSCodium. V IDE zobrazí projekt, roadmapové entity a úkoly, umožní vybrat/exportovat implementační balíček, spustit povolené předání agentovi a zkontrolovat/importovat výsledek. Komunikuje s autorizovaným lokálním workspace API a nesmí obcházet Workspace/Journal/Git/index zápisovou cestu.
- [ ] Distribuci rozšíření navrhnout pro ověřené kanály obou IDE a offline instalovatelný balíček; dostupnost konkrétního marketplace, API a značky ověřit v době implementace. Rozdíly VS Code/VSCodium nesmějí měnit doménový kontrakt ani bezpečnostní policy.
- [ ] Konkrétní Codex adaptér držet odděleně od IDE rozšíření a realizovat přes v době implementace oficiálně podporované a ověřené rozhraní. Produktový kontrakt nevázat napevno na jednu dnešní podobu integrace ani na jediného providera; stejné IDE rozšíření může později použít jiný kompatibilní coding-agent adaptér.
- [ ] Výsledek běhu importovat jako oddělený run record a návrh aktualizace projektových dat: stav, shrnutí, diff/změněné soubory, testy a jejich skutečné výsledky, vytvořené commity/PR pouze pokud byly povoleny, omezení a vazbu na původní task ID a vstupní revizi. Přerušený běh má stav `unknown`, nikoli automaticky failed nebo completed.
- [ ] Workspace označí úkol za dokončený až po validaci deklarovaných důkazů a lidském nebo explicitně schváleném policy rozhodnutí. Text reportu agenta, úspěšný exit code ani existence commitu samy nejsou důkazem splnění akceptace.
- [ ] Ošetřit stale vstupní commit, souběžnou změnu roadmapy/úkolu, opakované předání, restart, duplicitní výsledek a částečně provedené externí akce. Každý export i import výsledku musí mít stabilní operation/run ID a idempotentní receipt.

Vlastní repozitář produktu nemá privilegovanou cestu: podléhá stejnému RBAC, privacy, Git/Workspace recovery, branch/PR pravidlům a lidskému schválení jako jiný projekt. Operativní rozpad drží BACKLOG DEV-01 až DEV-04.

---

# 11C. Externě verzované moduly a jednotné API

**Stav: planned / designed, neimplementováno.** Dosavadní moduly a jejich
požadavky zůstávají v této hlavní roadmapě. Pouze nově výslovně vytipovaný modul
může mít samostatný repozitář a roadmapu; jeho pracovní kopie nebo symlink leží
v lokální, Gitem ignorované složce `modules.local/`. Hlavní plán jej neobsahuje
jako kopii a jeho konkrétní funkčnost sem nepřepisuje.

- [ ] Pro každý externí modul evidovat jen stabilní identitu, verzi/revizi,
  odkaz na jeho vlastní roadmapu, deklarované capability, závislosti a stav
  kompatibility s jednotným API. Text společné dokumentace musí být zobecněním
  potřebným pro API, ne doslovným přepisem modulové specifikace.
- [ ] Jednotné API verzovat a pro každou capability určit vstupní a výstupní
  schéma, chyby a limity, oprávnění, privacy/execution boundary, idempotenci,
  `unknown` externí účinek a provenance. Modul nepřistupuje přímo k projektovému
  Gitu, indexu, journalu ani credentials; mutace používají autorizované
  aplikační služby a Workspace lifecycle.
- [ ] `modules.local/` je pouze lokální convenienční adresář: může obsahovat
  symlinky nebo samostatně verzované checkouty, ale jejich obsah, Git historie,
  credentials, build výstupy a roadmapy nejsou součástí tohoto repozitáře ani
  distribučního balíku. Symlink není důkaz kompatibility, oprávnění ani trusted
  execution boundary a nesmí se sledovat při balení, importu či automatickém
  načítání kódu.
- [ ] Před přijetím capability modulu provést její samostatné reuse, bezpečnostní,
  licenční a kompatibilitní review; odmítnutý nebo nedostupný modul nesmí změnit
  chování jádra ani spustit fallback.

Podrobný návrhový kontrakt drží [ADR 0026](docs/adr/0026-module-unified-api.md);
implementační rozpad drží `MOD-01` v BACKLOG.

---

# 12. Webové UI

## MVP obrazovky

- [ ] Login.
- [ ] Seznam projektů.
- [ ] Project dashboard.
- [ ] File browser.
- [ ] Markdown editor/viewer.
- [ ] Metadata editor.
- [ ] Git history.
- [ ] LLM action panel.
- [ ] Konverzační pohled se seznamem lokálních a projektových vláken, stavem persistence, klasifikací, backendem/modelem a akcemi navázat, přiřadit k projektu, uložit kompletní otisk nebo uložit rozdíl od zvoleného základu.
- [ ] Indikace usage & billing u podporovaných backendů podle sekce 7C, v rozsahu oprávnění uživatele.
- [ ] Context preview.
- [ ] Výběr:
  - [ ] role,
  - [ ] backendu,
  - [ ] modelu.
- [ ] Správa registrů.
- [ ] Node administration.
- [ ] Federation status.
- [ ] User/RBAC administration.

## UX princip

- [ ] Projekt nesmí působit primárně jako „chat s AI“.
- [ ] Chat je pouze jeden z možných pohledů.
- [ ] Orchestrator chat je volitelný; bez dostupného/povoleného LLM musí stejné základní projektové operace zůstat dostupné deterministickým UI/workflow.
- [ ] Hlavní objekty jsou:
  **artefakty – zdroje – tvrzení – rozhodnutí – úkoly – role.**

---

# 12A. Desktopová aplikace jako uzel sítě

- [ ] Sdílet aplikační jádro a UI s webovou/serverovou variantou.
- [ ] Přibalit lokální backend pro správu projektů, Git operace, metadata a federaci.
- [ ] Umožnit založení a editaci lokálního projektu bez dostupnosti jiného uzlu.
- [ ] Ukládat projektové repozitáře a stav uzlu do persistentního uživatelského adresáře.
- [ ] Zachovat Node ID a lokální data při aktualizaci aplikace.
- [ ] Přidat připojení k federaci přes ověření identity a schválení důvěry mezi uzly.
- [ ] Zobrazovat dostupnost ostatních uzlů, poslední synchronizaci, čekající změny a konflikty.
- [ ] Umožnit ruční synchronizaci a nastavit automatickou synchronizaci při dostupném spojení.
- [ ] Umožnit lokální Ollama backend i povolené vzdálené backendy; UI musí zobrazit jejich dostupnost.
- [ ] Offline zpřístupnit lokální artefakty a lokální backendy; u vzdálených akcí jasně zobrazit nedostupnost.
- [ ] Stanovit chování při zavření okna: ukončení uzlu nebo volitelný běh na pozadí.
- [ ] Lokální API zpřístupnit pouze aplikaci přes autentizované lokální spojení; síťový endpoint federace spravovat odděleně.
- [x] Posoudit lokální socket/IPC oproti HTTP na loopbacku — protokolový PoC a podmíněná preference HTTP pro same-origin UI v [ADR 0006](docs/adr/0006-local-api-transport.md); ověření konkrétního obalu zůstává M0-06.
- [ ] Při použití HTTP vázat lokální API pouze na loopback, ověřovat Host a povolený Origin a zavést ochranu proti CSRF; CORS nepovažovat za autentizaci.
- [ ] Vyžadovat náhodný token pro každé spuštění lokálního API, předat jej aplikaci chráněným kanálem a nevkládat jej do URL ani logů.
- [ ] Pokud je token předáván souborem, omezit přístup na uživatele aplikace (na Unixu režim 0600, na Windows odpovídající ACL).
- [ ] Ověřit odmítnutí požadavků bez tokenu, s neplatným tokenem a z nepovolené webové stránky.
- [ ] Credentials ukládat do úložiště přihlašovacích údajů operačního systému, mimo projektový Git a synchronizaci.
- [ ] V M0 vybrat první podporovaný desktopový OS a technologii balení; posoudit Linux, Windows a macOS.
- [ ] Připravit instalaci, aktualizace, migrace dat a odinstalaci s explicitní volbou zachování dat.

---

# 13. API

- [ ] Definovat interní REST API.
- [ ] Oddělit endpointy:
  - [ ] `/projects`
  - [ ] `/artifacts`
  - [ ] `/git`
  - [ ] `/users`
  - [ ] `/roles`
  - [ ] `/backends`
  - [ ] `/llm`
  - [ ] `/workflows`
  - [ ] `/federation`
  - [ ] `/nodes`
- [ ] Připravit API tak, aby frontend nebyl těsně svázán s implementací backendu.
- [ ] API verzovat od začátku.

---

# 14. Turris Omnia / LXC deployment

- [ ] Vytvořit minimální LXC image/container setup.
- [ ] Integrovat dlaždici aplikace na uvítací stránce routeru s odkazem na aktuální adresu LXC služby, včetně změny IP, restartu a nedostupnosti kontejneru (zbývající úkol M1-07 v [BACKLOG](BACKLOG.md)).
- [ ] Oddělit persistentní:
  - [ ] Git repositories,
  - [ ] DB,
  - [ ] config,
  - [ ] secrets,
  - [ ] cache.
- [ ] Ollama považovat za samostatnou volitelnou službu/backend; její absence nesmí degradovat uzel pod základní non-LLM funkcionalitu.
- [ ] Nevyžadovat, aby velký LLM běžel přímo na Turrisu.
- [ ] Umožnit Ollama endpoint na:
  - [ ] stejném uzlu,
  - [ ] LAN serveru,
  - [ ] výkonném federovaném uzlu.
- [ ] Připravit systemd/procd startup.
- [ ] Healthcheck.
- [ ] Backup.
- [ ] Restore.
- [ ] Upgrade/migration mechanismus.

---

# 15. Bezpečnost

- [ ] Threat model.
- [ ] TLS i uvnitř overlay sítě.
- [ ] Node authentication.
- [ ] User authentication.
- [ ] RBAC.
- [ ] Secrets management.
- [ ] Audit log.
- [ ] Rate limiting.
- [ ] Validace uploadů.
- [ ] Ochrana proti path traversal.
- [ ] Ochrana Git command invocation.
- [ ] LLM prompt injection považovat za bezpečnostní problém.
- [ ] Externí dokument nikdy automaticky nepovažovat za důvěryhodnou instrukci.
- [ ] Privacy policy aplikovat před LLM requestem.

---

# 16. Audit a reprodukovatelnost LLM

- [ ] Pro každý významný LLM výstup evidovat:
  - [ ] uživatele,
  - [ ] čas,
  - [ ] roli,
  - [ ] backend,
  - [ ] model,
  - [ ] vstupní artefakty,
  - [ ] verze vstupních artefaktů,
  - [ ] prompt template,
  - [ ] výsledný artefakt.
- [ ] Umožnit odpovědět:

**Kdo, kdy, pomocí čeho a z jakých zdrojů tento text/závěr vytvořil?**

---

# 17. MVP – doporučené pořadí implementace

## Milestone M0 – Architecture spike

Zahájeno 2026-09-09. Důkazy: [ADR 0001](docs/adr/0001-m0-baseline.md), [ADR 0002](docs/adr/0002-metadata-journal.md), [ADR 0003](docs/adr/0003-coordinated-operation.md) a `tests/`. Výsledky ověření drží [WORK_LOG.md](WORK_LOG.md), zbývající kroky [TODO.md](TODO.md) a [BACKLOG.md](BACKLOG.md). **Gate M0 splněn dle [závěrečného review M0-09R](WORK_LOG.md#gate-m0); navazuje M1.**

- [x] Návrh layoutu a hranic autoritativních projektových dat / lokálního stavu — designed v DATA_MODEL a ARCHITECTURE.
- [x] Artefaktová metadata, frontmatter/sidecar, registry a obnova SQLite indexu — PoC validated; minimální schéma projektu/uzlu v1 a samostatná validace viz ADR 0004, storage integrace zbývá.
- [x] Obnova souborových změn před commitem — Linux PoC validated, včetně pádu procesu; nejde o celou aplikační transakci.
- [x] Popsat uživatelský scénář konfliktu a ověřit divergenci stejné entity — designed + Git CLI PoC validated; UI není implementované.
- [x] Vymezit společné jádro desktopu/serveru a výchozí jeden backendový proces — designed; Python, PySide6 a .deb jako základ pro M1 dle ADR 0013.
- [x] Počáteční threat model — designed v SECURITY; ověření transportu a produkčních ochran zbývá.
- [x] Minimální datové kontrakty projektu/uzlu v1, verzování a pravidla migrací — designed + samostatná validace PoC validated, [ADR 0004](docs/adr/0004-project-node-config.md); aplikační lifecycle zbývá BACKLOG V-08.
- [x] Návrhové kontrakty Backend, Role a Context Manifest — designed v [ADR 0008](docs/adr/0008-context-and-publication-contracts.md); implementace zbývá M2–M4.
- [x] Designed dle ADR 0008: Uzavřít kontrakt `UI / orchestrator chat → application orchestrator → Context Builder / workflow → LLM backend`: deterministický orchestrátor funguje bez LLM, orchestrator chat je volitelná capability a externí/federovaný fallback vyžaduje explicitní policy.
- [x] Designed dle ADR 0008: V M0 rozlišit backend capability od execution boundary a ověřit návrh pro uzel bez LLM, uzel s lokální Ollamou, zakázaný externí fallback, explicitně povolený externí backend, trusted-federation backend a `local-only` kontext.
- [x] Propojit journal, validaci, Git commit a index do jedné obnovitelné operace se společným řízením přístupu — Linux PoC validated, Workspace a ADR 0003; produkční integrace a hardening zbývají.
- [x] Designed dle ADR 0008: Uzavřít pravidla větví a publikace (M0-08). Konflikty obsahu/sidecaru včetně textově čistého sémanticky neplatného merge jsou PoC validated v M0-07, scénáře a limity ve [FEDERATION](FEDERATION.md); produkční synchronizace zůstává M5.
- [x] Ověřit lokální transport/API podle SECURITY a sekce 12A — PoC validated, [ADR 0006](docs/adr/0006-local-api-transport.md); browser/obal a bootstrap ověřeny v ADR 0010; aplikační integrace zbývá v BACKLOG V-10.
- [x] Vybrat výchozí Git adapter na základě C++/libgit2 vs. Git CLI PoC — Git CLI, [ADR 0005](docs/adr/0005-git-adapter-comparison.md). Lokální přenos/autentizace a náklady distribuce posouzeny; cílové ověření a PoC balení dokončeny v M0-05/M0-06; produkční TLS/SSH a release zbývají v BACKLOG V-09/V-11.
- [x] Turris Omnia/LXC a desktop — PoC validated pro zvolený stack: cílový SSD probe M0-05, desktopové měření ADR 0010 a čistá instalace ADR 0012. Přesné metriky a hranice důkazů drží WORK_LOG; nejde o produkční kapacitní test.
- [x] Stack pro M1 uzavřen — designed v [ADR 0013](docs/adr/0013-m1-stack.md): Python, Git CLI/SQLite, Linux PySide6/WebEngine a .deb. Lifecycle a čistá/offline instalace jsou PoC validated dle ADR 0010–0012. Cílové měření M0-05 je PoC validated; produkční release zůstává otevřený.
- [x] Připravenost pro M1 schválena v závěrečném review M0-09R: cílové ověření M0-05 a stack M0-06 doloženy. Historická negativní review a aktuální důkazy drží [WORK_LOG](WORK_LOG.md).

**Gate M0:** existuje zaznamenaná volba stacku podložená PoC, schéma autoritativních dat a obnovy indexu, návrh bezpečného lokálního API a průchod scénářem konfliktu stejné entity i dvojice soubor–sidecar. Je uzavřen kontrakt deterministické orchestrace bez LLM, volitelného orchestrator chatu a execution boundaries; dostupnost backendu nesmí sama měnit autorizaci ani trust policy. Implementace federace zůstává v M5.

## Milestone M1 – Single-node project workspace

M1-01 propojuje otevření registrovaného projektu a seznam artefaktů s desktopem; M1-02 přidává nativní vytvoření/registraci nového projektu a obnovu při přerušení (PoC validated, důkazy ve WORK_LOG). M1-03 přidává nativní Markdown editor, checklisty a jeden hlavní TODO dokument projektu; jde o PoC validated, kontrakt a důkazy drží [WORK_LOG](WORK_LOG.md) a [ADR 0016](docs/adr/0016-markdown-editor.md). M1-04 (PoC validated) přidává readonly historii dokumentu, prohlížení verzí a diff obsahu/metadat dle [ADR 0017](docs/adr/0017-artifact-history.md); důkazy drží WORK_LOG. F-M1-IMPORT-01 přidává nativní import Markdown/PNG/JPEG/PDF se zachováním původních bajtů a obnovou koordinovaného zápisu — lokální PoC validated, důkazy ve [WORK_LOG](WORK_LOG.md#f-m1-import-01--nativní-import-zdrojových-dokumentů--2026-09-14). F-M1-INDEX-01/V-03 rozšiřuje obnovitelný index o metadata, cesty, štítky a směrované vztahy s atomickou migrací a recovery — lokální PoC validated dle [ADR 0022](docs/adr/0022-relational-index.md), důkazy a uzavřené předání ve [WORK_LOG](WORK_LOG.md#f-m1-index-01--relační-projekce-projektového-indexu--2026-09-15). F-M1-DELETE-01/M1-08 je po PR #17 lokální PoC validated; důkazy drží [WORK_LOG](WORK_LOG.md#f-m1-delete-01--ověření-bezpečného-odstranění-dokumentu--2026-09-15). F-M1-META-01/V-04 a navazující F-M1-META-02 upřesňují a implementují importní provenance v2 dle [ADR 0023](docs/adr/0023-metadata-and-import-provenance.md). F-M1-SOURCE-01/V-05 a F-M1-SOURCE-02 navrhují a vynucují neměnné bajty pod jedním UUID a novou verzi jako nový source artefakt dle [ADR 0024](docs/adr/0024-source-immutability-and-versioning.md). Zbývající lifecycle registrace a Gate M1 zůstávají otevřené.

Aktualizace 2026-09-20: F-M1-META-02 a F-M1-SOURCE-02 jsou po PR #22/#23 lokálně PoC validated. M1-07 autostart je po PR #24 implementovaný a lokálně ověřený, ale druhý skutečný restart po application-only aktualizaci opět naběhl bez kontejnerů; cílová akceptace a dodatečný návod k nastavení zůstávají pod `M1-07-C` v BACKLOG. Gate M1 proto zůstává otevřený. Context Builder, Ollama adapter, UI oprava, lokálně perzistentní konverzace, projektové otisky, souhrny, extrakce, návrhy metadat, centralizovaná nastavení a externí provider jsou po PR #26–#36 začleněné. Aktivní F-M1-PROJECT-LOCATION-01 doplňuje umístění/registraci projektů a webový source import bez tvrzení o splnění Gate M1.

- [ ] LXC deployment.
- [ ] Jeden uživatel.
- [ ] Jeden projekt.
- [ ] Git repository.
- [ ] Markdown/JSON/PDF/assets.
- [ ] Metadata.
- [ ] Git history.
- [ ] Web UI.
- [ ] Desktopové balení se spuštěním lokálního uzlu a sdíleným UI.
- [ ] Ověření lokální práce bez sítě a zachování dat po restartu desktopové aplikace.
- [x] Ověření obnovy projektového indexu z Gitu a konzistence metadat po přejmenování či smazání artefaktu — lokální PoC; důkazy přejmenování a indexu drží WORK_LOG, odstranění [TODO](TODO.md).
- [ ] Ověření obnovy po přerušení zápisu artefaktu/sidecaru a po commitu před aktualizací indexu; import neměnného zdroje musí zachovat jeho původní bajty.
- [ ] Bezpečné odstranění celého projektu — F-M1-PROJECT-DELETE-01: rozlišit
  odregistrování, odstranění obnovitelného lokálního stavu, přesun repozitáře do
  koše a definitivní výmaz. Preview musí zahrnout projektová i chatová data,
  credentials, sdílené reference, pending operace a známé federované kopie;
  operace přes registraci/filesystem/Git/SQLite má durable journal a idempotentní
  recovery. Lokální smazání nesmí předstírat výmaz dříve publikovaných,
  sdílených nebo vzdálených revizí.

**Gate M1:** systém je použitelný jako projektový Git-backed knowledge workspace bez LLM v LXC i v desktopové aplikaci na prvním podporovaném OS.

## Milestone M2 – Local AI

- [x] Ollama backend — lokální PoC adapteru váže autorizovaný Context Manifest handoff na přesný model/cíl a vede durable run journal; živá služba a produkční provoz zůstávají neověřené.
- [x] Bezpečně rozlišit skutečný `same-node` Ollama proces od Ollama endpointu v lokální síti — lokální PoC vynucuje číselný loopback proti privátní číselné HTTPS adrese, připnutý certifikát a identitu cíle; odmítá DNS, redirect, fallback a `local-only` na LAN. Skutečný LAN/TLS endpoint nebyl ověřen.
- [x] Lokálně perzistentní vícekolová konverzace s výchozí klasifikací `brainstorming` a bezpečným navázáním po restartu — F-M2-CHAT-01, PR #29.
- [x] Explicitní přiřazení živého vlákna k projektu a uložení kompletního nebo rozdílového otisku; editovatelné výstupy konkrétních úkolů ukládat primárně jako Markdown artefakty — F-M2-CHAT-02, PR #30.
- [x] Summarizer — F-M2-SUMMARY-01 lokálně PoC validated a začleněn PR #31: explicitní artifact/message výběr, same-node preview, potvrzená recovery-safe publikace a desktopové API/UI.
- [x] Extractor — F-M2-EXTRACT-01 lokálně PoC validated: uzavřený schema kontrakt, lokální validovaný preview a potvrzená recovery-safe publikace s provenance a desktopovým API/UI; živý Ollama a skutečný Qt/WebEngine průchod zůstávají neověřené.
- [x] Auto-description — F-M2-META-AI-01 lokálně PoC validated: durable same-node návrh, bezpečný diff a potvrzený recovery-safe metadata commit; živý Ollama a skutečný Qt/WebEngine průchod zůstávají neověřené.
- [x] Tagging — F-M2-META-AI-01 lokálně PoC validated; v1 ukládá pouze jednotlivě potvrzené aditivní štítky bez automatického mazání.
- [x] Context builder — lokální read-only PoC fixuje přesné bajty a manifest a před dispatch handoffem znovu ověřuje HEAD, autoritu, privacy, policy a cíl; Ollama adapter a durable run record jsou navázány přes provider-neutral kontrakt F-M3-BACKEND-01. První externí provider zůstává další práce.

**Gate M2:** systém dokáže při dostupném lokálním LLM lokálně zpracovat projekt, sestavit relevantní kontext a obnovit lokální konverzační vlákno bez záměny skutečného `same-node` backendu za LAN službu. Živé projektové vlákno, full/delta otisk a odvozený Markdown výstup zachovávají provenance a privacy; bez lokálního LLM zůstává funkční M1 workspace a orchestrator chat je pouze nedostupná volitelná capability.

## Milestone M3 – External LLM

Aktualizace 2026-09-19: centralizovaná node-local nastavení byla začleněna PR
#34. Dávka `F-M3-BACKEND-01` byla začleněna PR #35 a lokálně PoC validuje
provider-neutral backend, explicitní capabilities, role a durable execution
identitu nad současnou Ollamou. `F-M3-EXTERNAL-01` je po PR #36 začleněn:
implementuje první externí textový provider, context preview, privacy filtr a
striktní návrh přes Ollamu. Uživatel živě potvrdil přímou odpověď, publikaci
artefaktového návrhu, potvrzený OpenAI request, restart návrhu i obnovené
zobrazení externí odpovědi. F-M3-CHAT-MODES-01 je po PR #40 začleněn a odděluje
lokální orchestrace od brainstormingu s per-run modelem. Usage/billing, obrazové capability, webové hledání
a obecný workflow zůstávají samostatné navazující schopnosti; Gate M3 proto
není vydáván za celý uzavřený.

- [x] Backend abstraction — F-M3-BACKEND-01: explicitní adapter registry bez discovery/fallbacku, verzované capabilities a execution identita svázaná s bindingem, rolí, manifestem a request digestem; první implementací zůstává Ollama.
- [x] První externí provider — F-M3-EXTERNAL-01 po PR #36 PoC validated:
  OpenAI Responses adapter, přesné preview, potvrzený dispatch, uzavřený outcome,
  artefaktový kontext a durable dočasné/redukované projekce v jednotném UI.
- [ ] Volitelný usage & billing přehled podle sekce 7C pro backendy, které poskytují příslušné údaje — aktivní dávka M3-UB-01.
- [x] Role — F-M3-BACKEND-01: provider/model-neutral registr task rolí `summarizer`, `extractor` a `metadata-advisor`; `brainstorming` zůstává klasifikací vlákna a role sama neuděluje oprávnění ani nemění execution boundary.
- [x] Context preview — F-M3-EXTERNAL-01-C: durable přesný náhled vstupů, targetu a provider requestu před ručně potvrzeným externím dispatch.
- [x] Privacy filter — F-M3-EXTERNAL-01-C: `local-only` fail-closed před preview; `project` a `confidential` pouze po explicitním potvrzení přesného hashe.
- [ ] Provenance.
- [ ] Řízené webové hledání — F-M3-SEARCH-01: použít konfigurovatelný SearXNG
  adaptér kompatibilní s lokální službou používanou Open WebUI. Ollama může
  navrhnout samostatný výstup `web-search`, ale nevolá síť ani nástroj přímo;
  aplikace před dispatch ověří privacy/policy a po návratu předá Ollamě pouze
  přesný bounded výsledek přes Context Manifest. Evidovat dotaz, čas, URL,
  titulky, úryvky a provenance; obsah výsledků je nedůvěryhodný vstup, nikoli
  instrukce ani automaticky projektový zdroj. Search run má vlastní durable stav,
  timeout a `unknown` hranici a nesmí se zaměnit s placeným externím LLM během.

**Gate M3:** lze bezpečně předat omezený projektový kontext vybranému LLM.

## Milestone M4 – Multi-role workflow

- [ ] Creator.
- [ ] Opponent.
- [ ] Analyst.
- [ ] Editor.
- [ ] Workflow handoff.
- [ ] Human approval.
- [ ] Artifact-based context isolation.

**Gate M4:** lze provést nezávislou oponenturu bez sdílení původní konverzační historie.

## Milestone M5 – Federation

- [ ] Node identity.
- [ ] Trust.
- [ ] Capability profily `same-company-same-team` / `same-company` / `trusted-partner` / `holding-partner` / `partner` oddělené od peer trust state a explicitních oprávnění.
- [ ] Git sync.
- [ ] Shared users.
- [ ] Federovaný uživatelský chat s offline doručením.
- [ ] Explicitní publikace chatu, shrnutí, zadání nebo jiného podporovaného artefaktu do projektu.
- [ ] Node-local backend registry.
- [ ] Federation status.
- [ ] Offline/reconnect.

- [ ] Ověřit synchronizaci desktopového a Turris/LXC nebo Linux serverového uzlu.
- [ ] Ověřit souběžné úpravy stejného souboru a stejné entity registru během offline provozu desktopu a následné řešení konfliktu.
- [ ] Ověřit konflikty změna–smazání a přejmenování–úprava u artefaktu se sidecarem, validaci vztahů po merge a aktualizaci indexu až po vyřešení konfliktů.
- [ ] Ověřit návrat desktopu po uspání a odmítnutí synchronizace při odvolané důvěře/oprávnění.

**Gate M5:** desktopový a serverový uzel mohou podle explicitního capability profilu a relationship/branch policy sdílet jen povolená data; pouze neměnným původem doložená vazba zakládající desktop–jím založený peer používá `same-company-same-team` a federuje uživatele a jejich projektové role. Druhá, tranzitivní nebo dodatečně povýšená same-team vazba se odmítne; ostatní profily zachovají své užší hranice. Uzly mohou používat rozdílné LLM backendy, synchronizovat změny po offline práci bez ztráty historie a vést federovaný chat. Chat funguje bez LLM; jeho uložení, explicitní sdílení či odvození do projektu je auditovatelné a neobchází privacy ani lidskou akceptaci.

## Milestone M6 – Project intelligence

- [ ] Assumption registry.
- [ ] Decision log.
- [ ] Risk register.
- [ ] Source registry.
- [ ] Relations.
- [ ] Impact analysis.
- [ ] Advanced context selection.
- [ ] Reprodukovatelné modelování a numerické výpočty s preferovaným Julia backendem.
- [ ] Převod roadmapy na projektové entity a export TODO/task balíčků.
- [ ] Provider-neutral předání implementačního úkolu coding agentovi a import ověřitelného výsledku.
- [ ] Rozšíření pro Microsoft Visual Studio Code/VSCodium a volitelné coding-agent adaptéry včetně Codexu, bez převzetí autority nad plánem a akceptací.
- [ ] Verzionované jednotné API pro nově vytipované externě verzované moduly,
  při zachování dosavadních modulů v hlavní roadmapě.

**Gate M6:** systém už není pouze „Git + LLM“, ale projektový knowledge/decision engine. Umí také převést schválený plán na dohledatelné projektové úkoly a bezpečně předat implementaci coding agentovi, aniž by jeho report automaticky měnil autoritativní stav nebo obcházel lidskou akceptaci.

---

# 18. Explicitně odložit za MVP

- [ ] Vector DB jako povinnou komponentu.
- [ ] Komplexní distribuovanou databázi.
- [ ] Real-time collaborative editing.
- [ ] Kubernetes.
- [ ] Automatický multi-agent swarm.
- [ ] Autonomní změny projektových dokumentů bez potvrzení člověkem.
- [ ] Vlastní model training.
- [ ] Plnohodnotný replacement GitHub/GitLab.
- [ ] Automatickou synchronizaci secrets.
- [ ] Mobilní aplikaci.

---

# 19. Operativní práce a návaznost na implementaci

Konkrétní otevřené úkoly drží [BACKLOG.md](BACKLOG.md), aktuální dávku [TODO.md](TODO.md) a uzavřené dávky [WORK_LOG.md](WORK_LOG.md), včetně původních položek pro deployment, desktop, Project/Artifact/Git služby, UI, Ollama, role a Context Builder. Zde se již neduplikuje jejich průběžný stav.

- [x] Pracovní architektonické dokumenty, ADR, reuse katalog a kostra experimentů — designed / implemented.
- [x] Frontmatter/sidecar validátor, obnovitelný index, souborový journal a CLI kontrola projekce — implemented v M0; ověření a limity viz ADR 0002 a WORK_LOG.
- [ ] Integrovaná aplikace a nasazení podle M1; existující experimenty adaptovat podle finálního stacku.

---

# 20. Definice prvního skutečně použitelného prototypu

První prototyp je hotový, pokud lze:

- [ ] založit projekt,
- [ ] přidat Markdown/PDF/JSON/obrázek,
- [ ] soubor popsat ručně nebo přes Ollama,
- [ ] commitnout změny do Gitu,
- [ ] zobrazit historii,
- [ ] vybrat několik dokumentů,
- [ ] nechat Ollama sestavit jejich stručný relevantní kontext,
- [ ] zobrazit uživateli přesně tento kontext,
- [ ] vybrat roli,
- [ ] vybrat externí LLM backend,
- [ ] odeslat kontext,
- [ ] uložit odpověď jako nový verzovaný artefakt,
- [ ] zaznamenat, z jakých zdrojů odpověď vznikla.

**Federace ještě není podmínkou prvního prototypu.**

První prototyp ověřit i jako samostatně běžící desktopovou aplikaci s lokálními daty.

Teprve po ověření tohoto workflow propojit desktopový a serverový uzel a řešit synchronizaci, distribuované identity a konflikty.

---

# 21. Ollama / Open WebUI – obousměrná integrace

Vedle použití Ollamy jako interního backendu workspace umožnit také opačný směr integrace: federovaný projektový workspace může vystupovat jako zdroj kontextu, nástrojů a projektových artefaktů pro externí LLM rozhraní, zejména Ollama/Open WebUI.

- [ ] Navrhnout integrační API nezávislé na konkrétním UI klientovi.
- [ ] Umožnit přístup z Ollama/Open WebUI k vybranému projektu v rozsahu oprávnění přihlášeného uživatele.
- [ ] Umožnit z externího LLM rozhraní:
  - [ ] vybrat projekt,
  - [ ] vyhledat projektové artefakty,
  - [ ] načíst explicitně vybraný kontext,
  - [ ] použít Context Builder workspace,
  - [ ] získat Context Manifest,
  - [ ] pracovat s projektovými registry a vztahy v rozsahu povolených capabilities.
- [ ] Zachovat stejné RBAC, privacy a execution-boundary kontroly jako při použití interního UI.
- [ ] Externí klient nesmí získat přímý neomezený přístup k projektovému Git repozitáři nebo filesystemu.

## Zpětný zápis výsledků

- [ ] Umožnit vrátit výsledek práce z Ollama/Open WebUI zpět do workspace.
- [ ] Výsledek importovat jako explicitní artefakt nebo návrh změny, nikoli jako automatickou modifikaci existujícího projektového obsahu.
- [ ] U importovaného výsledku evidovat provenance minimálně:
  - [ ] zdrojovou integraci,
  - [ ] uživatele,
  - [ ] projekt,
  - [ ] backend/model, pokud je znám,
  - [ ] čas,
  - [ ] použité vstupní artefakty / Context Manifest, pokud jsou dostupné,
  - [ ] původní conversation/run ID, pokud jej integrace poskytuje.
- [ ] Výsledek může být následně:
  - [ ] uložen jako nový artefakt,
  - [ ] připojen jako návrh k existujícímu artefaktu,
  - [ ] předán projektové LLM roli,
  - [ ] použit jako vstup workflow,
  - [ ] přijat, upraven nebo zamítnut člověkem.
- [ ] Zápis do autoritativních projektových dat musí vždy projít standardní aplikační cestou:
  `integration → authorization → validation → application orchestrator → Git operation → index`.
- [ ] Open WebUI ani jiný externí LLM klient nesmí obcházet aplikační orchestrátor, Git lifecycle, audit nebo human-approval pravidla.

## Integrační princip

Integrace má být obousměrná:

`workspace → Context Builder → Ollama / Open WebUI → LLM`

a

`LLM / Open WebUI → návrh/výsledek → workspace → validace → verzovaný artefakt`

Open WebUI tedy může sloužit jako alternativní konverzační frontend nad projektovými daty, ale **workspace zůstává autoritou pro projektová data, oprávnění, provenance, rozhodnutí a verzování**.

Integrace nesmí vytvořit druhý paralelní systém projektového stavu uvnitř Open WebUI. Konverzační historie může zůstat vlastnictvím externího klienta; do workspace se vracejí explicitně vybrané výsledky, artefakty a jejich dohledatelná provenance.

---

# 22. Externí vztahy, komunikace a řízené sdílení

**Stav: plánovaný rozsah; návrhový kontrakt a implementace jsou budoucí práce.** Cílem je dohledat, komu byl jaký obsah v konkrétní revizi zpřístupněn, v jakém rozsahu, jakým kanálem a s jakým dokladem. Evidence předání není tvrzení o skutečných znalostech příjemce. Datové podklady jsou v [DATA_MODEL.md](DATA_MODEL.md), bezpečnostní mantinely v [SECURITY.md](SECURITY.md) a implementační úkoly ER-01 až ER-08 v [BACKLOG.md](BACKLOG.md).

## 22A. Relationship Registry a schůzky

- [ ] Evidovat osoby, organizace, jejich role a časově vymezené vztahy, kontaktní body, zdroje údajů a vazby na projekty. Partner může být firma, samostatná osoba, poradce nebo veřejná instituce; partner není automaticky uživatel workspace.
- [ ] Adresář realizovat jako pohled na tento registr. E-mailovou adresu nepoužívat jako identitu člověka; sloučení osob a změna organizace vyžadují kontrolu.
- [ ] Oddělit soukromý katalog kontaktů od projektově sdílených informací. Meziprojektové propojení nesmí automaticky zpřístupnit cizí korespondenci nebo vztahy.
- [ ] Schůzku propojit s projektem, skutečnými účastníky, agendou, zdrojovou komunikací, revizí prezentace, poznámkami a následnými úkoly. Interní poznámky nepatří automaticky do pozvánky.

## 22B. Disclosure Registry

- [ ] Evidovat odchozí i přijaté informace, včetně případných omezení jejich dalšího použití. U příjmu zachovat zdroj a původní bajty vybraného importovaného artefaktu.
- [ ] Odkazovat na stabilní ID projektu nebo repozitáře a artefaktu, úplný Git commit ID a přesný předaný snapshot s hashem. Samotný název, větev nebo štítek revize nestačí.
- [ ] Rozlišovat `full`, `excerpt`, `summary`, `derived`; prezentace odvozeného shrnutí neznamená předání celého zdrojového modelu. Evidovat konkrétní výřez nebo slide a jeho zdrojové revize.
- [ ] Rozlišovat přípravu, export, promítnutí, předání dopravnímu serveru, potvrzené doručení nebo přístup a ručně zaznamenané ústní sdělení. Neurčitý výsledek ponechat jako neověřený.
- [ ] Události zapisovat append-only aplikační cestou s idempotentními ID; opravy přidávat jako navazující události, nikoli přepisovat původní historii. Git sám není nezměnitelný auditní systém.
- [ ] Nabídnout pohled partnera na evidované sdílení, rozsah a poslední předanou revizi, včetně rozdílu vůči nové verzi. Nepředpokládat, že obsah znají všichni zaměstnanci nebo všechny společnosti skupiny.
- [ ] Navázat veřejné publikace na existující administrativní registr `docs/IP/DEFENSIVE_DISCLOSURES.md` referencí, nikoli založením jeho konkurenční kopie. Citlivá partner data nepatří do veřejného vývojového repozitáře.

## 22C. Disclosure Presenter

- [ ] Přidat modul pro přípravu verzovaných prezentací: skládat deck z projektových artefaktů a médií, spravovat pořadí, šablonu, poznámky řečníka a kroky postupného odhalení a před spuštěním ověřit chybějící zdroje i přesné revize. Vytvořený deck a jeho bezpečný export nesmějí obsahovat privátní scénář, poznámky nebo skryté backupy, pokud je uživatel výslovně nezahrne do oprávněného výstupu.
- [ ] Dvě oddělená zobrazení: publikum vidí pouze schválený aktuální slide; řečník poznámky, privátní náhled, nabídku backupů, jejich triggery a návrat do hlavní linie.
- [ ] Zachovat lineární hlavní prezentaci a doplnit interní verzovaný rozhodovací scénář se stabilními ID uzlů. Uzel rozlišuje otázku řečníka a očekávanou otázku protistrany, možné odpovědi, stručnou a podrobnou reakci, navazující větve a volitelné backupy; povinná je cesta pro jinou odpověď, „nevím“ nebo odmítnutí odpovědi.
- [ ] Backup ponechat volitelný: větev může pokračovat doplňující otázkou, ústní odpovědí, odložením tématu nebo návratem bez dalšího slidu. Odkazovat na existující obsah v konkrétní revizi; jeden backup smí sloužit více slidům a větvím bez kopií.
- [ ] Ke každému slidu i backupu umožnit kontextové doplňující otázky, interní poznámky/zdroje a veřejné doplňky. Vedle nich držet globální knihovnu „Všechny backupy“ dostupnou odkudkoli, s hledáním podle tématu/otázky, filtrem citlivosti a označením již použité revize.
- [ ] Kokpit nabídne pohledy „K tomuto slidu“, „Všechny backupy“ a „Odložené otázky“. Zobrazí aktuální otázku, připravenou reakci a nejbližší možnosti; celý strom zůstane rozbalitelný. Neočekávanou otázku lze stručně poznamenat nebo odložit bez editace celého scénáře.
- [ ] Větev vybírá řečník ručně. Focus, výběr, privátní náhled a akce „Zobrazit publiku“ jsou rozdílné stavy; šipky, hledání ani volba možné odpovědi nesmějí promítat obsah nebo tvrdit, že odpověď skutečně zazněla. Klávesnicové ovládání a focus/selection model navrhnout podle [W3C APG Tree View](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/).
- [ ] Ovládání prezentace abstrahovat na významové akce (`další/předchozí krok`, `privátní náhled`, `zobrazit publiku`, `backup`, `návrat`, `neutral/blackout`) a vedle klávesnice nabídnout volitelný gamepad adaptér s lokálním mapováním a testem tlačítek. Samotný vstup z gamepadu nesmí obejít autorizaci, disclosure potvrzení ani oddělení preview/audience; odpojení, ztráta focusu, opakování tlačítka nebo neznámý ovladač nesmějí automaticky posunout či odhalit obsah a vždy zůstává dostupné klávesnicové ovládání.
- [ ] Akce „Doplňující otázka“ uloží přesný návratový bod včetně slidu, kroku postupného odhalení a rozehrané větve. Zachovat historii zanoření a samostatné akce „zpět o úroveň“, „návrat k přerušenému výkladu“ a „pokračovat hlavní prezentací“; předběhnutý pozdější slide pouze označit, ne automaticky přeskočit.
- [ ] Základní deck připravovat jako zelený po kontrole obsahu. Každý backup má vlastní `green / orange / red`; změněná nebo nezkontrolovaná revize nesmí zdědit automatické schválení.
- [ ] Kumulativní globální semafor: zelený slide +0, oranžový +0,5, červený +1 stupeň. Prahy a režim schůzky nastavit předem a evidovat jejich verzi.
- [ ] Přírůstek účtovat až při evidovaném zobrazení publiku, ne při privátním náhledu. Opakování totožného obsahu stejnému publiku během stejné schůzky logovat, ale nezapočítávat znovu; nová revize, nový rozsah či příjemce vyžadují nové posouzení.
- [ ] Před zobrazením ukázat přírůstek a výslednou expozici; u navržené sekvence také předpokládaný součet bez započtení nevybraných alternativ. Citlivou ústní odpověď započítat pouze po ruční akci „Sděleno ústně“. Citlivý obsah nebo překročený měkký limit může vyžadovat potvrzení, autorizační zákaz jím obejít nelze.
- [ ] Skóre pouhým zavřením slidu, přechodem mezi větvemi nebo návratem nesnižovat. Oddělit expozici aktuální schůzky od historie partnera a samostatně sledovat čas, počet odboček a hloubku zanoření. Upozornění nabídne stručnou odpověď, doplňující otázku, odložení nebo návrat.
- [ ] Dříve sdílený červený obsah zůstává červený; stav předání je samostatná osa. „Známá revize“ není povolení k dalšímu odeslání nebo reklasifikace na public.
- [ ] Navigační historii oddělit od evidence sdílení a očekávanou odpověď od samostatně potvrzené skutečné odpovědi. Strom, interní reakce a vyjednávací poznámky ponechat pouze řečníkovi; nesmějí být skrytým obsahem audience rendereru ani exportovaného decku.
- [ ] Zajistit offline provoz, obnovu konkrétní revize decku/scénáře, aktuální větve, návratových bodů, odložených témat a expozice po pádu, bezpečný neutrální výstup a explicitní stav neověřeného promítnutí.
- [ ] Přidat zkušební režim s kontextovými i obecnými doplňujícími otázkami, simulovaným semaforem, časem odboček a návratem. Nácvik je oddělen od skutečné relace a nikdy nezapisuje DisclosureEvent ani tvrzení, že partner obsah obdržel.

## 22D. Communications Hub — plnohodnotný klient

- [ ] Mail: více účtů, IMAP synchronizace, SMTP odesílání, složky, hledání, vlákna, přílohy, odpovědi a přeposílání, koncepty a odchozí fronta. Výchozí obsah a činnosti jsou soukromé; přiřazení projektu je explicitní nebo potvrzené pravidlo.
- [ ] Připojení stavět na standardních protokolech a capability adaptéru. TLS a podporovaný způsob autentizace včetně OAuth2 řešit už pro prvního cílového poskytovatele; neslibovat univerzální kompatibilitu bez ověření.
- [ ] Kalendář: CalDAV, více kalendářů, pozvánky a odpovědi, opakování, časová pásma a vazba na interní schůzku. Kontakty: CardDAV pohled nad Relationship Registry, mapování polí a řízené konflikty bez druhého CRM.
- [ ] Před odesláním zkontrolovat konkrétní příjemce, citovaný text, přílohy a jejich revize. Pozvánka i sdílený kontakt jsou rovněž možné externí přenosy.
- [ ] Do projektového Gitu ukládat jen vědomě vybrané komunikační artefakty, metadata a disclosure události. Celá schránka, cache, synchronizační kurzory, koncepty a odchozí fronta mají oddělený lokální nebo poskytovatelský životní cyklus.

## 22E. Zařazení a produktové gates rozšíření

Jde o navazující schopnosti v této master roadmapě, nikoli přejmenování M1–M6. M4 zůstává Multi-role workflow a M6 Project intelligence. Implementace se plánuje až po nezbytném aplikačním základu; samostatný Presenter nepotřebuje dokončený mail klient ani LLM.

| Rozsah | Návaznost | Podmínka použitelnosti rozšíření |
| --- | --- | --- |
| Kontrakty | BACKLOG ER-00 | Zaznamenané entity, revize, privacy hranice a migrace; bez zpětného otevření Gate M0. |
| Registry a ruční evidence | Po M1; ER-01 až ER-03 | Partner, schůzka, přesný snapshot a oprava události projdou autorizovaným zápisem, restartem a obnovou indexu. |
| Presenter MVP | Po registry a policy základu; ER-04 | Dvě zobrazení, váhy 0/0,5/1, privátní preview bez započítání, verzovaný scénář, kontextové i globální backupy, návrat z přerušení a restart bez ztráty relace. |
| Mail, kalendář, kontakty | Po registry a policy základu; ER-05 a ER-06 | Ověřené cílové účty, konflikty a offline návrat; bez opakovaného odeslání při neurčitém výsledku bez rozhodnutí uživatele. |
| Federované vztahy a evidence | Navazuje na M5; ER-07 | Autorizovaný přenos událostí, deduplikace, oddělení soukromých dat a žádný implicitní přenos zdrojového repozitáře. |
| Kontext vztahu a LLM poradce | Volitelně navazuje na M2–M4/M6; ER-08 | Kontext z oprávněných revizí, explicitní manifest a pouze návrhy; chybějící LLM nesmí blokovat deterministický provoz. |

Reciprocita je dobrovolná poznámka řečníka, ne automatický „kredit“ dovolující zveřejnit další data. Přijaté citlivé informace nesmějí snižovat policy ochranu. Obecný CRM prodejní pipeline, hromadné kampaně ani vlastní mail server nejsou součástí tohoto rozšíření.

---

# 23. Periodický monitoring a analytický reporting

**Stav: plánovaný rozsah navazující na M6; nejde o implementovaný scheduler, webový výzkum ani automatickou publikaci.** Reporting Framework je obecná schopnost workspace, zatímco Reporting Task je samostatná verzovaná definice tématu, zdrojů, periodicity, hodnoticích kritérií a výstupů. První referenční task je Humanoid Robotics Watch; další doménové moduly mohou dodávat časové řady síťových měření, mapových vrstev nebo satelitních pozorování. Implementační dávky `MON-00` až `MON-07` drží [BACKLOG](BACKLOG.md).

## 23A. Události, zdroje a dlouhodobé příběhy

- [ ] Evidovat každý poznatek jako samostatnou událost se stabilním ID a `task_id`; oddělit čas zjištění `detected_at`, doložený čas události `event_date` a čas importu. Neznámé či pouze odhadované datum výslovně označit a neodvozovat je z času stažení.
- [ ] Událost nese titulek, shrnutí, kategorii, entity, geografii, relevance, confidence, maturity, novelty, impact, evidence, tagy a provenance. Původní dokument, přesná citace, screenshot, fotografie, video či PDF jsou samostatné zdroje/artefakty s vlastní privacy a hashem, nikoli neověřená součást shrnutí.
- [ ] Rozlišit primární, sekundární a komunitní zdroje. Komunitní zdroj je signál; zásadní tvrzení má nést nezávislý či primární důkaz, případně zůstat výslovně neověřené.
- [ ] Oddělit oznámení, demonstraci, laboratorní výsledek, řízené demo, pilot, omezené produkční nasazení a nezávisle ověřený provoz. Marketingové tvrzení se nesmí automaticky změnit na prokázanou schopnost.
- [ ] Použít verzovanou škálu zralosti 0–5 od konceptu po běžně použitelnou technologii. Hodnocení relevance, novosti, praktického dopadu a confidence uchovat společně s použitou revizí pravidel a důkazy.
- [ ] Deduplikace vytváří jednu událost s více `Sources[]`; neodstraňuje ani nepřepisuje původní zdroje. Nové zjištění je nová událost/revize nebo explicitní vazba na předchozí záznam. Události se propojují do dlouhodobých `Story / Development Thread`, aby šel rekonstruovat vývoj, nikoli jen seznam článků.

## 23B. Reportingové vrstvy a neměnné snapshoty

- [ ] Týdenní noticka obsahuje jen významné změny oproti předchozímu uzavřenému reportu, typicky 3–7 položek: co se stalo, význam, stav důkazu, možný dopad a zdroj.
- [ ] Měsíční report je nová syntéza, nikoli spojení týdenních textů. Obsahuje executive summary, události, vývoj oblastí a zralosti, produkty/projekty, piloty/nasazení, výzkum, problémy/neúspěchy, trendy a výhled; výslovně hodnotí změnu trendu.
- [ ] Každý třetí měsíční report může přidat kvartální srovnání a realistickou vizuální case study. Výroční zpráva je samostatný analytický dokument se stavem na začátku roku, milníky, ekonomikou/dostupností, regulací, bezpečností, slepými cestami, posunem k praxi, výhledem a archivem hlavních zdrojů.
- [ ] Vydaný report je připnutý neměnný snapshot s obdobím, časovým pásmem, query/cutoff, revizí tasku, revizí hodnoticích pravidel, přesnými vstupními event/source ID a Context Manifest/run provenance. Oprava vytvoří následníka; nepřepisuje vydaný report. Editovatelný draft a vydaný snapshot jsou rozdílné stavy.
- [ ] Report bez nového vývoje nesmí vyrábět falešnou novinku. Pozdně nalezená starší událost zachová skutečné `event_date`, pozdější `detected_at` a je viditelně označena jako doplnění, aby nebyl zkreslen trend.

## 23C. Scheduler, sběr a recovery

- [ ] Scheduler spouští konkrétní Reporting Task s typem `weekly`, `monthly`, `quarterly` nebo `annual`, stabilním run ID, časovým pásmem a vypočteným intervalem. DST, zmeškaný běh, souběh, ruční opakování a změna konfigurace nesmějí vytvořit dvojí vydání stejného tasku/období.
- [ ] Pipeline odděluje sběr, extrakci, deduplikaci, hodnocení důkazů, aktualizaci story, generaci reportu, volitelnou vizualizaci, lidskou kontrolu a publikaci. Částečný výsledek zůstává draft/failed/unknown; neposune „poslední vydaný report“.
- [ ] Externí rešerše a stažení mají allowlist zdrojů, limity, rate limiting, respektování přístupových pravidel/licencí a ochranu proti prompt injection. Stažený obsah je nedůvěryhodný vstup a nesmí měnit task, policy, scheduler ani sám spouštět akce.
- [ ] Automatické publikování je výslovná per-task policy. Výchozí režim vyžaduje lidské schválení; nedostupný LLM, zdroj nebo generátor obrázků nesmí vést k implicitnímu externímu fallbacku ani k vydání neúplného reportu jako hotového.

## 23D. Vizualizace a federované provedení

- [ ] Generovaná či dokumentární case study ukládá prompt/zadání, datum, model/nástroj, seed a parametry podle dostupnosti, vstupní důkazy, vztah k přesnému reportu a popis scénáře. Dokumentární asset zachová licenci a zdroj; syntetický obraz je viditelně označen.
- [ ] Realistická case study popisuje prostředí, úlohy systému, činnosti člověka, bezpečnostní omezení a technologické limity. Smí zobrazit prokázané schopnosti, současný pilot nebo explicitně označený krátkodobý výhled; nesmí vydávat sci-fi či marketing za doložený stav.
- [ ] Federované uzly mohou plnit role collector, extractor, evidence evaluator, story tracker, report generator a visualization generator pouze podle Context Manifestu, privacy a execution boundary. Citlivý zdroj zůstává lokální; odvozenina dědí nejpřísnější omezení a federovaný výsledek se před přijetím znovu validuje.

## 23E. Referenční task Humanoid Robotics Watch

- [ ] Sledovat humanoidní a humanlike robotiku se zaměřením na housekeeping, péči o seniory/pacienty, domácí a kancelářskou asistenci; dynamicky evidovat významné výrobce a projekty bez automatického tvrzení o jejich relevanci či úspěchu.
- [ ] Verzovat benchmarky humanlike interakce, manipulace, lokomoce, housekeeping a care. U přímé fyzické péče (hygiena, vstávání, transfer, prevence pádu a práce s nepohyblivým pacientem) vyžadovat zvláštní bezpečnostní klasifikaci a nezávislé důkazy; report není klinické ani bezpečnostní schválení.
- [ ] Výstupy: Humanoid Robotics Weekly Notes, Monthly Report, kvartální Hospital Room case study a Annual Report se čtyřmi case studies Hotel/Hospital/Home/Office. Konkrétní názvy firem, schopnosti, ceny a predikce jsou data tasku v dané revizi, nikoli trvalá fakta roadmapy.
- [ ] Dlouhodobé dotazy nad event/story registry musí umět doložit první výskyt a vývoj schopnosti, nasazení, ceny, autonomie, problémů a rozdílu mezi opakovaným provozem a demonstrací; odpověď odkazuje na přesné události a zdroje a přizná mezery v datech.

## 23F. Doménové observační moduly

- [ ] Reporting Framework musí přijímat moduly přes verzovaný provider-neutral kontrakt `ObservationSource`, nikoli zabudovat API jednoho poskytovatele do tasku. Modul deklaruje capabilities, prostorový a časový rozsah, jednotky, limity, licenci, privacy, credential reference a způsob získání; tajemství ani providerový runtime stav nepatří do projektového Gitu.
- [ ] Síťový modul může adaptovat samostatně vyvíjený RIPE Atlas Webcockpit pro dlouhodobé sledování dostupnosti, latence, tras a změn pozorovaných z explicitní množiny probes. Jednorázové aktivní měření je externí účinek vyžadující samostatné oprávnění, limity a durable run stav; veřejné výsledky nejsou automaticky důkazem příčiny ani stavu celé sítě.
- [ ] Geospatial modul může připínat verzované mapové vrstvy, výřezy a odvozené geometrie s CRS, bbox/zoom, časem platnosti, licencí a hashem. Interaktivní mapa je projekce; autoritativní pozorování a použitá revize vrstvy musí zůstat reprodukovatelné i bez poskytovatele.
- [ ] Earth-observation modul může sledovat časové řady satelitních snímků a odvozených produktů. Musí evidovat platformu/senzor, acquisition time oddělený od publication/import time, footprint, pásma/produkt, rozlišení, cloud/quality masku, zpracovatelskou úroveň a licenci. Změnová detekce je odvozené tvrzení s vlastní provenance a confidence, nikoli náhrada původního snímku.
- [ ] Různé moduly lze spojit do jedné story pouze explicitní časoprostorovou vazbou a s přiznáním rozdílného pokrytí, rozlišení a nejistoty. Shoda na mapě nebo v čase sama neprokazuje kauzalitu; LLM smí korelaci pouze navrhnout k validaci.

## 23G. Gate rozšíření

| Rozsah | Návaznost | Podmínka použitelnosti |
| --- | --- | --- |
| Kontrakt a ruční task | Po M1; MON-00/MON-01 | Striktní verze schémat, oddělené časy, provenance, append-only opravy a ručně spustitelný report bez LLM. |
| Sběr a evidence | M2–M4/M6; MON-02/MON-03 | Bezpečný source adapter, deduplikace se zachováním zdrojů, evidence/maturity review a reprodukovatelný story update. |
| Scheduler a reporty | Po stabilním run recovery; MON-04/MON-05 | Idempotentní perioda, restart/souběh/missed run, draft versus vydání a report připnutý na přesné vstupy. |
| Vizualizace a federace | Volitelně po M5/M6; MON-06 | Auditovatelná realistická case study a rozdělené provedení bez úniku privacy či implicitního fallbacku. |
| Doménové observační moduly | Po MON-00 až MON-04; MON-07 | Alespoň síťový modul projde dvěma periodami se stabilní provenance; mapové a satelitní adaptéry zůstávají samostatné capabilities s licenčními, časovými a prostorovými metadaty. |

**Gate periodického reportingu:** jeden obecný task a Humanoid Robotics Watch projdou alespoň dvěma po sobě jdoucími periodami; opakovaný či přerušený běh nevytvoří duplicitní vydání, zdrojové události a pozdní doplnění zůstanou dohledatelné, report lze reprodukovat z připnutých vstupů a žádné tvrzení ani vizualizace nejsou vydány jako ověřené bez odpovídající evidence a policy rozhodnutí.
