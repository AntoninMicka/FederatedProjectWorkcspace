# Katalog reuse

| Kandidát | Stav | Účel | Co zbývá ověřit |
| --- | --- | --- | --- |
| Git CLI | adapt (výchozí adapter, ADR 0005) | Referenční storage a Workspace; reuse wrapperu, vlastní staging a compare-and-swap podle ADR 0003 | Produkční izolace, autentizace, cílové balení |
| libgit2 / C++ | evaluate (PoC validated) | Ověřená alternativa, `spikes/libgit2/probe.cpp`, ADR 0005 | Runtime 1.9.1 dostupný; chybějící dev headers rozbaleny do /tmp. Produkční port Workspace, cílové balení a TLS/SSH neověřeny |
| Python stdlib SQLite | adapt (M0 PoC) | Obnovitelný projektový index (`spikes/storage.py`) a oddělený autoritativní lokální journal rozpracovaných operací (`spikes/journal.py`), viz ADR 0002 | Koordinace ověřena v Workspace (ADR 0003); zbývá produkční integrace, úplná projekce metadat/vztahů, výkon a paměť na Turrisu |
| PyYAML 6.0.3 | evaluate | Omezený frontmatter parser v M0 | Produkční distribuce a audit závislosti před vydáním |
| Qt / WebView | candidate | Desktopový obal sdíleného UI | Distribuce, IPC, paměť |
| Vlastní starší projekty | candidate | Potenciální reuse | Repozitáře zatím nejsou určeny; licence a kompatibilita neověřeny |

Žádná komponenta zatím nemá schválený produkční status reuse. Licence a verze závislostí zaznamenat před zařazením do distribuované aplikace.

M0-01 adaptuje existující `spikes/journal.py`, `spikes/storage.py` a jejich testy: zachovává validátor, fsync/recovery a commitovou projekci, přidává trvalý operation record a nadřazený zámek. Rewrite by opakoval ověřený PoC; starší zdrojové projekty nadále nejsou identifikované ani ověřené.

Shellový launcher adaptuje existující unittest příkaz a `spikes.check_project`; dočasné demo používá `Workspace`/`Git` přímo. Nevytváří další storage implementaci ani aplikační server.

M0-02 adaptuje omezený JSON parser a UUID/timestamp validaci z `spikes/metadata.py`; schéma konfigurace přidává v `spikes/configuration.py`. Sdílené primitivy omezují rozcházení pravidel s artefakty; další parser ani závislost nejsou potřeba.

M0-03 adaptuje existující storage/index testovací scénáře; C++ probe je nová minimální testovací vazba přímo na libgit2, nikoli kopie cizího adapteru. Důvod zachování Git CLI a náklady případného přenosu koordinace jsou v [ADR 0005](docs/adr/0005-git-adapter-comparison.md). Starší vlastní projekty zůstávají neidentifikované; jejich inventura se tím neprohlašuje za hotovou.
