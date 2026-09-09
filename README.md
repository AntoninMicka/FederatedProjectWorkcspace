# Federovaný projektový LLM workspace

Self-hosted workspace s projektovými soubory v Gitu, lokálními LLM backendy a desktopovým uzlem federace.

Projekt je ve fázi **M0 — Architecture spike**. Zatím obsahuje návrh a spustitelný storage experiment, nikoli hotovou aplikaci.

## Spuštění experimentu

Vyžaduje Linux, Bash, Python 3.11+, Git v PATH a PyYAML 6.0.3. Spouštěcí wrapper [run.sh](run.sh):

```sh
./run.sh setup                 # jednorázová příprava .venv a instalace závislostí
./run.sh                       # dočasné storage demo (totéž jako ./run.sh demo)
./run.sh test                  # celá sada testů
./run.sh check "/cesta/k/projektu"
./run.sh config project "/cesta/k/projektu/project.json"
./run.sh config node "/cesta/k/lokalnimu/node.json"
./run.sh help
```

Pokud už jsou závislosti dostupné, krok `setup` lze vynechat. Použije se `.venv/bin/python`, pokud existuje, jinak `python3`; běžné spuštění nic neinstaluje. `setup` potřebuje podporu Python venv/pip a přístup ke zdroji balíčků; instaluje pouze do `.venv`.

Výchozí demo přes `spikes/demo.py` založí izolovaný dočasný Git repozitář, uloží Markdown artefakt přes Workspace a vypíše commit, index po znovuotevření a historii. Po dokončení se demo data odstraní. **Nespouští se webový server ani desktopové UI; nejde zatím o aplikaci pro běžnou práci.** Při násilném ukončení může zůstat dočasný adresář uvedený ve výstupu; demo není určeno k uchování dat.

Wrapper lze zavolat absolutní cestou z jiného adresáře; relativní cesta u `check` se vztahuje k adresáři volajícího. `check` vrací 0 pro platnou projekci a 1 při chybě validace, neplatné argumenty wrapperu vracejí 2.

Ruční příprava a spuštění bez wrapperu:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Pokud už je požadovaný PyYAML dostupný, lze testy spustit přímo `python3 -m unittest discover -s tests -v`.

Testy vytvářejí izolované dočasné repozitáře a SQLite databáze. Nepoužívají síť ani nemění globální Git konfiguraci.

Pracovní projekci existujícího projektu lze ověřit bez zápisu:

```sh
.venv/bin/python -m spikes.check_project /cesta/k/projektu
```

Kontrola zahrnuje artefakty, sidecary, registry a jejich vztahy. Neověřuje zatím `project.json` ani konfiguraci uzlu. Neplatná projekce vrací exit code 1.

## Kontrola konfigurace

`./run.sh config project CESTA` a `./run.sh config node CESTA` validují samostatný JSON soubor podle [kontraktu v1](DATA_MODEL.md). Alternativně použijte `python3 -m spikes.check_config project CESTA` nebo `node CESTA` (s příslušným Python prostředím). Cesty jsou relativní k adresáři volajícího. Úspěch vrací 0, neplatný/nečitelný soubor 1 a chybné argumenty 2.

Kontrola nic nevytváří ani nemigruje. `node.json` musí ležet mimo registrované projekty a obsahovat pouze lokální odkazy na credentials. Ověření skutečné identity, dostupnosti klíčů a shody projektových registrací patří do budoucí aplikační integrace. Dosavadní `check` i dočasné demo zůstávají artefaktovým/registry PoC bez povinné konfigurace.

## Koordinovaný storage PoC

`spikes.workspace.Workspace(root, state)` poskytuje `apply(changes, author_name=..., author_email=..., message=...)`, `recover()`, `read()` a `receipt(operation_id)`. Změny jsou mapa projektových cest na bajty nebo `None` pro smazání; validuje se celý výsledný artefaktový/registry snapshot. `apply` vrátí receipt s operation ID, výsledným commit ID a stavem `indexed`. `recover` dokončí pending operaci nebo vrátí `None`. Konflikt zachová journal a vyžaduje lidské řešení; `read` při pending stavu vyvolá `PendingOperation`.

Vyžaduje kontrolovaný repozitář s existujícím commitem na běžné větvi, čistým worktree/staging a jediným soukromým stavovým adresářem mimo projekt na stejném filesystemu. Všechny aplikační zápisy a čtení musí procházet tímto vstupem; samostatné `Git.commit`, `Journal` a `Index` zůstávají nízkoúrovňovými experimenty. Nejde o podporu cizích repozitářů, síťové federace ani produkční aplikaci. Crash boundaries a ověření: [ADR 0003](docs/adr/0003-coordinated-operation.md).

## Dokumentace

- [Architektura](ARCHITECTURE.md)
- [Datový model](DATA_MODEL.md)
- [Federace a konfliktové UI](FEDERATION.md)
- [Bezpečnost](SECURITY.md)
- [Katalog reuse](REUSE_CATALOG.md)
- [IP, defensive publication a crowdfunding roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>)
- [Patent Risk Register](docs/IP/PATENT_RISK_REGISTER.md)
- [Defensive Disclosures](docs/IP/DEFENSIVE_DISCLOSURES.md)
- [První rozhodnutí a stav M0](docs/adr/0001-m0-baseline.md)
- [Metadata a journal: chování, ověření a omezení](docs/adr/0002-metadata-journal.md)

Další krok: M0-03 — srovnání libgit2/C++ s Git CLI PoC. Minimální schémata project.json/node.json a jejich samostatná validace jsou připravené; aplikační integrace zbývá. Koordinovaná operace journal → Git → index je ověřený Linux PoC. V M0 zbývá také libgit2 PoC, lokální transport a ověření na cílovém Turris/LXC; poté uzavřít stack a začít M1.
