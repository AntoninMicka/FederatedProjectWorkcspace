# Katalog reuse

| Kandidát | Stav | Účel | Co zbývá ověřit |
| --- | --- | --- | --- |
| Git CLI | evaluate | Referenční storage PoC | Produkční izolace, autentizace, cílové balení |
| libgit2 / C++ | evaluate | Alternativní Git adapter | Knihovna není v prostředí dostupná přes pkg-config; sestavení a srovnávací PoC |
| Python stdlib SQLite | evaluate | Obnovitelný projektový index (`spikes/storage.py`) a oddělený autoritativní lokální journal rozpracovaných operací (`spikes/journal.py`), viz ADR 0002 | Integrace zápisu, úplná projekce metadat/vztahů, výkon a paměť na Turrisu |
| PyYAML 6.0.3 | evaluate | Omezený frontmatter parser v M0 | Produkční distribuce a audit závislosti před vydáním |
| Qt / WebView | candidate | Desktopový obal sdíleného UI | Distribuce, IPC, paměť |
| Vlastní starší projekty | candidate | Potenciální reuse | Repozitáře zatím nejsou určeny; licence a kompatibilita neověřeny |

Žádná komponenta zatím nemá schválený produkční status reuse. Licence a verze závislostí zaznamenat před zařazením do distribuované aplikace.
