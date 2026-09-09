# Federovaný projektový LLM workspace

Self-hosted workspace s projektovými soubory v Gitu, lokálními LLM backendy a desktopovým uzlem federace.

Projekt je ve fázi **M0 — Architecture spike**. Zatím obsahuje návrh a spustitelný storage experiment, nikoli hotovou aplikaci.

## Spuštění experimentu

Vyžaduje Linux, Python 3.11+, Git v PATH a PyYAML 6.0.3:

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

Další krok: M0-02 — schéma project.json a minimální konfigurace uzlu. Koordinovaná operace journal → Git → index je ověřený Linux PoC. V M0 zbývá také libgit2 PoC, lokální transport a ověření na cílovém Turris/LXC; poté uzavřít stack a začít M1.
