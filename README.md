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

Další krok: propojit journal, validaci, Git commit a index do jedné aplikační operace. V M0 zbývá také libgit2 PoC, lokální transport a ověření na cílovém Turris/LXC; poté uzavřít stack a začít M1.
