# Katalog reuse

| Kandidát | Stav | Účel | Co zbývá ověřit |
| --- | --- | --- | --- |
| Git CLI | adapt (M0 PoC) | Referenční storage a Workspace; reuse wrapperu, vlastní staging a compare-and-swap podle ADR 0003 | Produkční izolace, autentizace, cílové balení |
| libgit2 / C++ | evaluate | Alternativní Git adapter | Knihovna není v prostředí dostupná přes pkg-config; sestavení a srovnávací PoC |
| Python stdlib SQLite | adapt (M0 PoC) | Obnovitelný projektový index (`spikes/storage.py`) a oddělený autoritativní lokální journal rozpracovaných operací (`spikes/journal.py`), viz ADR 0002 | Koordinace ověřena v Workspace (ADR 0003); zbývá produkční integrace, úplná projekce metadat/vztahů, výkon a paměť na Turrisu |
| PyYAML 6.0.3 | evaluate | Omezený frontmatter parser v M0 | Produkční distribuce a audit závislosti před vydáním |
| Qt / WebView | candidate | Desktopový obal sdíleného UI | Distribuce, IPC, paměť |
| Vlastní starší projekty | candidate | Potenciální reuse | Repozitáře zatím nejsou určeny; licence a kompatibilita neověřeny |

Žádná komponenta zatím nemá schválený produkční status reuse. Licence a verze závislostí zaznamenat před zařazením do distribuované aplikace.

M0-01 adaptuje existující `spikes/journal.py`, `spikes/storage.py` a jejich testy: zachovává validátor, fsync/recovery a commitovou projekci, přidává trvalý operation record a nadřazený zámek. Rewrite by opakoval ověřený PoC; starší zdrojové projekty nadále nejsou identifikované ani ověřené.

Shellový launcher adaptuje existující unittest příkaz a `spikes.check_project`; dočasné demo používá `Workspace`/`Git` přímo. Nevytváří další storage implementaci ani aplikační server.

M0-02 adaptuje omezený JSON parser a UUID/timestamp validaci z `spikes/metadata.py`; schéma konfigurace přidává v `spikes/configuration.py`. Sdílené primitivy omezují rozcházení pravidel s artefakty; další parser ani závislost nejsou potřeba.
