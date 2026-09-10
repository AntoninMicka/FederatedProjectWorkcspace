<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Pokyny pro práci v repozitáři

Projekt je aktivně vyvíjený **Git-backed federated project knowledge & decision workspace**. Nevytvářej jej znovu jako greenfield. Zachovej existující práci, experimenty, testy, dokumentaci a historii ADR. Aktuální milník a stav práce čti z roadmapy a TODO.

## Zahájení a rozsah úkolu

1. Zkontroluj `git status --short`, relevantní diff a změny od poslední kontroly. Nepřepisuj nesouvisející práci uživatele. Přečti platné pokyny pro dotčené adresáře.
2. Zjisti aktuální milník a nejbližší úkol z `TODO.md`; z dokumentu `Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md` a ADR čti relevantní části. `WORK_LOG.md` a `BACKLOG.md` prohledej jen pro konkrétní potřebné důkazy či návaznosti; nenačítej automaticky celý archiv. Již přečtené podklady v rámci konverzace použij znovu, pokud se nezměnily; při chybějícím kontextu je znovu načti. Nevytvářej druhou konkurenční roadmapu.
3. Vymez konkrétní výstup a ověření. U návrhu nebo review prováděj potřebné čtení; soubory měň pouze v rozsahu zadání. U dokumentační změny ověř dotčené podklady, konzistenci a odkazy. Při změně kódu nebo jeho chování navíc přečti odpovídající implementaci a testy.
4. Před přidáním či nahrazením funkce prověř existující řešení. Pokud může být dostupné jinde, použij `REUSE_CATALOG.md` a uvedené zdrojové komponenty; zaznamenej důvod reuse/adapt/rewrite/reject. Je-li dostupný lokální `REUSE_CATALOG.private.md`, použij také jeho inventuru; soubor je ignorovaný Gitem a jeho soukromé názvy, cesty ani detaily nepřenášej do verzovaných dokumentů. Do veřejného katalogu zařazuj externí repozitáře až po ověření veřejné dostupnosti. Chybějící zdroj označ jako neověřený; nekopíruj kód automaticky ani neopakuj již doloženou inventuru beze změny podkladů.
5. U operace přes více persistentních vrstev (filesystem, Git, SQLite index, journal) před implementací explicitně popiš crash boundaries a očekávané recovery. Pokud je již popisuje platné ADR, odkaž na ně a popiš pouze změny. Úspěšný happy-path test nestačí k dokončení takové operace.

Pokud uživatel požádá o „další úkol“ bez upřesnění, pokračuj nejbližší otevřenou položkou aktuální dávky v TODO. Dokonči ji včetně ověření a dokumentace; další samostatný úkol automaticky nezahajuj. Dokončenou položku ponech v TODO do uzavření celé dávky. Je-li dávka dokončená, proveď předání popsané níže; samotné naplnění TODO další dávkou není pokynem ji celou implementovat.

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

## Roadmapa a práce po dávkách

- **Roadmapa** drží strategii, milníky, schopnosti a gates. Zachovej původní katalog požadavků; není to průběžný pracovní deník ani druhý backlog.
- **TODO.md** obsahuje celou aktuální dávku, zpravidla jeden milník, včetně ad-hoc úkolů. Nemá limit 5 položek. Uvádí rozsah, pořadí práce a podmínky dokončení dávky. Hotové položky i jejich ověření zde zůstávají do uzavření dávky.
- **BACKLOG.md** připravuje další dávky, typicky tři navazující milníky. Jde o plánovací horizont, nikoli důvod zahazovat již evidované vzdálenější úkoly. Ty lze ponechat v oddělené části bez dalšího rozepisování. Ad-hoc práce může být součástí dávky nebo samostatnou budoucí položkou.
- **WORK_LOG.md** obsahuje uzavřené dávky, jejich dokončené úkoly, ověření a historická gate review. Starší jednotlivé záznamy zachovej; nově archivuj po dávkách, nejnovější nahoru.

### Během dávky

Z těchto pracovních evidencí aktualizuj pouze TODO: stav, výsledky, ověření, omezení a nová zjištění. BACKLOG a WORK_LOG průběžně nesynchronizuj. To neomezuje potřebné změny kódu, testů, návodů či ADR; roadmapu měň jen při skutečné změně rozsahu nebo rozhodnutí, nikoli kvůli každému hotovému úkolu.

Ad-hoc úkol zapiš se stabilním ID, původem/požadavkem, rozsahem, cílovou úrovní a podmínkou dokončení. Patří-li do aktuální dávky, zařaď jej podle priority mezi její úkoly. Práci pro později zachyť v TODO v sekci „K předání do backlogu“; tato sekce není součástí podmínek dokončení dávky. Při novém zjištění k existujícímu backlogovému úkolu odkaž na jeho ID a zaznamenej doplnění, nevytvářej druhý stavový záznam. Nezařazuj spekulativní úkoly do počtu.

### Uzavření a načtení další dávky

Po dokončení a relevantním ověření všech úkolů aktuální dávky:

1. Vyhodnoť podmínky dávky a příslušný gate. Dokončení dávky samo neprokazuje splnění celého milníku; neověřenou či blokovanou práci neoznačuj jako hotovou. Při nutném odložení výslovně zaznamenej změnu rozsahu a zbývající práci.
2. Přesuň dokončenou dávku z TODO do WORK_LOG s ID úkolů, daty dokončení, úrovní výsledků, důkazy ověření a omezeními; zachovej i ad-hoc úkoly a důvody změn rozsahu.
3. Přenes odložené úkoly a poznámky z „K předání do backlogu“ do odpovídajících dávek BACKLOG; aktualizuj stávající položky podle ID. Nedokončené úkoly zůstávají otevřené.
4. Přesuň další dávku z BACKLOG do TODO, vymez její rozsah a pořadí podle roadmapy a doložených návazností. Backlog podle potřeby doplň směrem k přibližně třem dalším milníkům, bez vymýšlení práce. Není-li další dávka doložená, ponech TODO prázdné a uveď to.
5. Ve stejné změně oprav odkazy a případný stav milníku/gate v roadmapě. Jeden úkol má jediný aktuální záznam; odkazy a historické důkazy nejsou konkurenčními kopiemi stavů.

Stavy používej přesně:

- `[ ] [planned]` — zbývající práce.
- `[ ] [in progress]` — skutečně probíhající práce v TODO.
- `[x] [completed]` — dokončený a relevantně ověřený výstup; do uzavření dávky v TODO, poté ve WORK_LOG.
- `[ ] [blocked]` — konkrétní překážka s důvodem a podmínkou odblokování.

U položek uváděj úroveň: designed, implemented, PoC validated nebo production-ready. Návrh ani spike neznamená produkční implementaci. Chybějící ověření ponech otevřené nebo výslovně neověřené. Závislost na plánovaném úkolu sama není důvod vše označit jako blocked.

## Dokončení a ověření

- Průběžný stav a výsledky ověření zapisuj do TODO, včetně dokončených a ad-hoc úkolů aktuální dávky. BACKLOG a WORK_LOG aktualizuj při předání dávky. Kosmetické mezikroky nepotřebují vlastní položky.
- Roadmapu aktualizuj pouze při skutečné změně milníku, rozsahu nebo stavu schopnosti/gate. Na důkazy odkazuj do TODO u aktuální dávky, do WORK_LOG u uzavřených dávek; při přesunu oprav odkazy. Celkový počet testů nekopíruj do dalších dokumentů.
- Architekturu či ADR měň pouze při skutečném návrhovém rozhodnutí nebo opravě konkrétního věcného rozporu. Do ADR patří důkazy příslušného rozhodnutí; jejich historické výsledky zachovej. Průběžná evidence patří do TODO.
- Během implementace spouštěj cílené testy chování i chybových cest. Před dokončením změny kódu nebo testů spusť celou současnou sadu: `python3 -m unittest discover -s tests -v` (Linux, Python 3.11+, závislosti z `requirements.txt`; instalace viz README). Relevantní existující build/lint spusť, pokud je nakonfigurovaný; nyní samostatný build/lint ani CI nejsou nakonfigurované.
- Po úspěšném běhu opakuj ověření pouze při relevantní změně kódu, testů, závislostí či konfigurace nebo nové pochybnosti. Po následných čistě dokumentačních úpravách stačí kontrola dokumentace a diffu. Pokud deklaruješ nové výsledky testů, skutečně je spusť; neprovedené kontroly označ jako neověřené.
- U čistě dokumentačních změn zkontroluj věcnou konzistenci, odkazy a diff. Před dokončením každé ucelené změny zkontroluj `git diff --check`, finální diff i nově vytvořené soubory. Shrň výsledek, ověření a relevantní zbývající omezení.

## Commity

Nevytvářej commit v tomto vývojovém repozitáři bez výslovného požadavku uživatele. Git commity v izolovaných dočasných repozitářích jsou součástí schválených testů a toto pravidlo jim nebrání.

Po každé ucelené změně navrhni zprávu odvozenou z **finálního diffu**, ne z původního zadání. Formát: `<type>(<scope>): <short summary>`. Preferované typy: feat, fix, refactor, docs, test, chore, build, ci. Pokud diff obsahuje logicky nezávislé změny, navrhni více commitů a uveď jejich obsah.

Implementační odpovědi (včetně změn dokumentace/workflow) vždy zakonči řádkem `Suggested commit: ...`.

Mechanismus souboru AGENTS.md popisuje [oficiální dokumentace OpenAI](https://learn.chatgpt.com/docs/agent-configuration/agents-md); konkrétní pravidla výše jsou pravidla tohoto projektu.
