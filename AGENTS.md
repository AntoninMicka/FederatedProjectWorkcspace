<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Pokyny pro práci v repozitáři

Projekt je aktivně vyvíjený **Git-backed federated project knowledge & decision workspace**. Nevytvářej jej znovu jako greenfield. Zachovej existující práci, experimenty, testy, dokumentaci a historii ADR. Aktuální milník a stav práce čti z kanonického Workspace projektu podle docs/dev-01-handoff-review.md.

## Zahájení a rozsah úkolu

1. Zkontroluj `git status --short`, relevantní diff a změny od poslední kontroly. Nepřepisuj nesouvisející práci uživatele. Přečti platné pokyny pro dotčené adresáře.
2. Aktuální dávku, úkol, akceptaci a revizi čti z aktuálního exportu kanonického Workspace projektu. Ověř project ID, přiřazený repozitář, snapshot revizi a stav synchronizace. Archivované TODO/BACKLOG/WORK_LOG ani roadmapa nedokládají aktuální stav. Při nedostupném či stale exportu zachovej dosavadní práci a vyžádej aktuální zadání; neaktivuj další feature podle archivu. ADR a vývojové návody čti podle rozsahu.
3. Vymez konkrétní výstup a ověření. U návrhu nebo review prováděj potřebné čtení; soubory měň pouze v rozsahu zadání. U dokumentační změny ověř dotčené podklady, konzistenci a odkazy. Při změně kódu nebo jeho chování navíc přečti odpovídající implementaci a testy.
4. Před přidáním či nahrazením funkce prověř existující řešení. Pokud může být dostupné jinde, použij `REUSE_CATALOG.md` a uvedené zdrojové komponenty; zaznamenej důvod reuse/adapt/rewrite/reject. Je-li dostupný lokální `REUSE_CATALOG.private.md`, použij také jeho inventuru; soubor je ignorovaný Gitem a jeho soukromé názvy, cesty ani detaily nepřenášej do verzovaných dokumentů. Do veřejného katalogu zařazuj externí repozitáře až po ověření veřejné dostupnosti. Chybějící zdroj označ jako neověřený; nekopíruj kód automaticky ani neopakuj již doloženou inventuru beze změny podkladů.
5. U operace přes více persistentních vrstev (filesystem, Git, SQLite index, journal) před implementací explicitně popiš crash boundaries a očekávané recovery. Pokud je již popisuje platné ADR, odkaž na ně a popiš pouze změny. Úspěšný happy-path test nestačí k dokončení takové operace.

Pokud uživatel požádá o „další úkol“ bez upřesnění, vyber nejbližší otevřený úkol aktuální dávky v aktuálním Workspace exportu. Dokonči pouze tento rozsah včetně ověření a návrhu výsledku k review. Zpráva v bridge není akceptace ani oprávnění k automatickému dokončení autoritativního úkolu.

Skutečný kód a ověřené testy dokládají současný stav. Roadmapa není důkaz implementace a starý nezaškrtnutý bod není důvod zopakovat hotový experiment. Rozpor s architektonickým rozhodnutím pojmenuj; nepovažuj jej automaticky za nové rozhodnutí.

## Architektonické mantinely

- Git je autoritativní úložiště projektových artefaktů, metadat a registrů.
- SQLite **projektový index** je lokálně obnovitelná projekce validovaného Git commitu, nese jeho ID a nesynchronizuje se. Při nesouladu s HEAD nesmí vydávat stará data za aktuální.
- Identita uzlu, credentials a rozpracované operace zůstávají mimo projektový Git. SQLite journal je autoritativní záznam nedokončené operace, nikoli obnovitelný index; nezaměňuj tyto dvě role SQLite.
- Zápisy do projektu musí být serializované. Obnova před commitem používá journal, po commitu lze index obnovit z HEAD. Samostatné PoC moduly ještě nezaručují společné řízení celé operace.
- Merge vyžaduje sémantickou validaci schémat, ID a vztahů; textově čistý merge nestačí. Neztrácej konfliktní historii.
- Desktop je plnohodnotný uzel se stejným backendovým návrhem jako server. Výchozí návrh má jeden backendový proces; produkční stack zůstává otevřený podle ADR.
- Základem jsou artefakty, metadata, provenance, vztahy, předpoklady, hypotézy, rizika, otázky, rozhodnutí, úkoly a historie. Chat, LLM, RAG a vyhledávání nad nimi mohou pracovat.
- Bez explicitního architektonického rozhodnutí nezaváděj povinnou vektorovou DB, RAG, embeddings ani konkrétního LLM providera.
- Existující rozhodnutí měň pouze kvůli konkrétní doložené potřebě a změnu zaznamenej do architektury/ADR; nepřepisuj je podle generické šablony.

## LLM workflow

Role jsou nezávislé na modelech a providerech: creator, opponent, analyst, researcher, editor, extractor, summarizer, classifier, issue-spotter. Oponentovi automaticky nepředávej celou konverzaci tvůrce; používej explicitní předání artefaktů a kontextu.

Externí LLM požadavek musí mít explicitní Context Manifest. RBAC a privacy kontroluj aplikačně před voláním backendu. Privacy třídy zahrnují public, project, confidential, local-only. Data local-only nesmí opustit lokální hranici důvěry bez explicitní reklasifikace. Tyto požadavky jsou závazný návrh; neoznačuj je za implementované jen proto, že je validátor přijímá jako metadata.

## Plánování po předání DEV-01

- Workspace je jediná autorita aktuálního plánu. Zdrojový Git zůstává autoritou
  implementace, AGENTS, ADR, návodů a historie kódu; Git-backed projekt Workspace
  je autoritou jeho plánovacích artefaktů. Lokální SQLite index tuto autoritu nenahrazuje.
- Rozlišuj připojení Workspace, projektové mapování a konkrétní připnutý task balíček.
  Export a zprávy zůstávají v obyčejných souborech mimo zdrojový Git podle ADR 0060.
  Nikdy z nich nevytvářej druhé živé TODO ve zdrojovém repozitáři.
- Jedna dávka = jedna ucelená feature = jedna feature větev = jeden PR do develop.
  Před implementací načti stabilní ID, rozsah, závislosti, cílovou úroveň,
  akceptaci a explicitní předání kontextu. Historický source snapshot není nové zadání.
- Při schváleném zahájení nové feature ověř čistý strom, aktuální develop a začlenění
  závislostí; vytvoř a přepni její feature větev. Správnou existující větev použij
  znovu. Při kolizi či nesouvisejících změnách domluv bezpečné předání. Automatický
  stash, reset a práce na nesouvisející feature v develop nejsou povolené.
- Nesouvisející feature nepřidávej do aktivní dávky. Stacked PR vyžaduje výslovnou
  výjimku. Push, otevření PR, merge a commity ve vývojovém repozitáři vyžadují
  výslovný požadavek uživatele podle sekce Commity.
- Průběžné výsledky, nové požadavky a odklady předávej jako zprávy či návrhy se
  stabilním task ID, přesnou exportní revizí, repository HEAD a důkazy. Pokud
  současný transport potřebný typ nepodporuje, připrav konkrétní návrh k review;
  neoznačuj jej za doručený ani uložený. Změna autoritativního plánu používá
  výhradně schválený Workspace lifecycle a oprávnění.
- Po dokončení celé dávky připrav review rozsahu, výsledků, recovery, omezení
  a odkladů. Akceptaci feature eviduj odděleně od doručení PR. Další dávku
  aktivuj až po merge na vlastní větvi z aktuálního develop.
- Root TODO.md slouží jen jako informace o předání zdrojové větve, nikoli plán.
  BACKLOG.md, WORK_LOG.md a původní Master Checklist zachovávají archivovanou
  evidenci a požadavky; neaktualizuj je jako konkurenční plán Workspace.
- Dokončení neodvozuj od checkboxu nebo hlášení agenta. Rozlišuj designed,
  implemented, PoC validated a production-ready; ověřené chování a stav review
  musí odpovídat skutečným důkazům. Stale a unknown se nesmějí tiše vydávat za úspěch.

## Dokončení a ověření

- Během implementace spouštěj cílené testy chování i chybových cest přes explicitní unittest selektory. Celou současnou sadu spusť jednou po poslední relevantní změně kódu, testů či konfigurace před dokončením dávky a předáním PR: lokálně `python3 -m unittest discover -s tests -v`, v CI ekvivalentními izolovanými shardy `scripts/test_shards.py` (Linux, Python 3.11+, závislosti z `requirements.txt`; instalace viz README). Shardy dohromady musí zahrnout každý top-level testovací modul právě jednou; cílený běh plnou závěrečnou bránu nenahrazuje. Relevantní existující build/lint spusť, pokud je nakonfigurovaný; samostatný build/lint nyní není nakonfigurovaný.
- Po úspěšném běhu opakuj ověření pouze při relevantní změně kódu, testů, závislostí či konfigurace nebo nové pochybnosti. Po následných čistě dokumentačních úpravách stačí kontrola dokumentace a diffu. Pokud deklaruješ nové výsledky testů, skutečně je spusť; neprovedené kontroly označ jako neověřené.
- U čistě dokumentačních změn zkontroluj věcnou konzistenci, odkazy a diff. Před dokončením každé ucelené změny zkontroluj `git diff --check`, finální diff i nově vytvořené soubory. Shrň výsledek, ověření a relevantní zbývající omezení.

## Commity

Nevytvářej commit v tomto vývojovém repozitáři bez výslovného požadavku uživatele. Git commity v izolovaných dočasných repozitářích jsou součástí schválených testů a toto pravidlo jim nebrání.

Po každé ucelené změně navrhni zprávu odvozenou z **finálního diffu**, ne z původního zadání. Formát: `<type>(<scope>): <short summary>`. Preferované typy: feat, fix, refactor, docs, test, chore, build, ci. Pokud diff obsahuje logicky nezávislé změny, navrhni více commitů a uveď jejich obsah.

Implementační odpovědi (včetně změn dokumentace/workflow) vždy zakonči řádkem `Suggested commit: ...`.

PR doporuč až po dokončení a relevantním otestování **všech úkolů aktuální dávky**, splnění jejích akceptačních podmínek a závěrečných kontrolách po poslední změně. Dokud zbývá úkol, neprovedené ověření nebo blokující chyba, neuváděj řádek Suggested PR ani předběžný návrh PR s dovětkem „zatím nepřipraveno“. Průběžně uváděj stav, zbývající práci a Suggested commit; samotný návrh commitu neznamená dokončení dávky. Po splnění dávky před Suggested commit doporuč jeden PR do `develop`: `Suggested PR: <feature branch> -> develop — <title>`, se stručným rozsahem a skutečnými výsledky ověření. Doporučení není otevření PR ani souhlas s push/merge. Nesouvisející feature patří do samostatných dávek a samostatných PR.

Mechanismus souboru AGENTS.md popisuje [oficiální dokumentace OpenAI](https://learn.chatgpt.com/docs/agent-configuration/agents-md); konkrétní pravidla výše jsou pravidla tohoto projektu.
