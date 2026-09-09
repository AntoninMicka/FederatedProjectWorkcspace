# Federovaný projektový LLM workspace

Self-hosted workspace s projektovými soubory v Gitu, lokálními LLM backendy a desktopovým uzlem federace.

Projekt je ve fázi **M0 — Architecture spike**. Zatím obsahuje návrh a spustitelný storage experiment, nikoli hotovou aplikaci.

## Spuštění experimentu

Vyžaduje Python 3.11+ a Git v PATH, bez dalších Python závislostí:

```sh
python3 -m unittest discover -s tests -v
```

Testy vytvářejí izolované dočasné repozitáře a SQLite databáze. Nepoužívají síť ani nemění globální Git konfiguraci.

## Dokumentace

- [Architektura](ARCHITECTURE.md)
- [Datový model](DATA_MODEL.md)
- [Federace a konfliktové UI](FEDERATION.md)
- [Bezpečnost](SECURITY.md)
- [Katalog reuse](REUSE_CATALOG.md)
- [První rozhodnutí a stav M0](docs/adr/0001-m0-baseline.md)

Další krok: libgit2 PoC, ověření na cílovém Turris/LXC, frontmatter/sidecar validátor a obnova přerušené změny dvojice souborů. Poté uzavřít stack a začít M1.
