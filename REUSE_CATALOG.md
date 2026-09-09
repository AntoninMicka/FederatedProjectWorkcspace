# Veřejný katalog reuse

Katalog verzovaný v Gitu obsahuje technologie, komponenty tohoto workspace a pouze externí zdrojové repozitáře s ověřenou veřejnou dostupností.

## Externí zdrojové repozitáře

Zatím žádné. Před zařazením uvést veřejnou URL, ověřit přístup bez přihlášení a zaznamenat licenci, revizi a důvod reuse/adapt/reject. Samotná veřejná dostupnost neznamená oprávnění k převzetí kódu.

Soukromou lokální inventuru drží volitelný soubor `REUSE_CATALOG.private.md`, ignorovaný Gitem. Jeho absence v čerstvém klonu je očekávaná. Lokální cesty, neveřejné názvy repozitářů a podrobnosti jejich posouzení se do verzovaných dokumentů nepřenášejí.

## Technologie a závislosti

| Kandidát | Stav | Účel | Co zbývá ověřit |
| --- | --- | --- | --- |
| Git CLI | adapt (výchozí adapter, ADR 0005) | Referenční storage a Workspace; reuse wrapperu, vlastní staging a compare-and-swap podle ADR 0003 | Produkční izolace, autentizace, cílové balení |
| libgit2 / C++ | evaluate (PoC validated) | Ověřená alternativa, `spikes/libgit2/probe.cpp`, ADR 0005 | Runtime 1.9.1 dostupný; chybějící dev headers rozbaleny do /tmp. Produkční port Workspace, cílové balení a TLS/SSH neověřeny |
| Python stdlib SQLite | adapt (M0 PoC) | Obnovitelný projektový index (`spikes/storage.py`) a oddělený autoritativní lokální journal rozpracovaných operací (`spikes/journal.py`), viz ADR 0002 | Koordinace ověřena v Workspace (ADR 0003); zbývá produkční integrace, úplná projekce metadat/vztahů, výkon a paměť na Turrisu |
| PyYAML 6.0.3 | evaluate | Omezený frontmatter parser v M0 | Produkční distribuce a audit závislosti před vydáním |
| Qt / WebView | candidate | Desktopový obal sdíleného UI | Distribuce, IPC, paměť |

Žádná komponenta zatím nemá schválený produkční status reuse. Licence a verze závislostí zaznamenat před zařazením do distribuované aplikace.

M0-01 adaptuje existující `spikes/journal.py`, `spikes/storage.py` a jejich testy: zachovává validátor, fsync/recovery a commitovou projekci, přidává trvalý operation record a nadřazený zámek. Rewrite by opakoval ověřený PoC.

Shellový launcher adaptuje existující unittest příkaz a `spikes.check_project`; dočasné demo používá `Workspace`/`Git` přímo. Nevytváří další storage implementaci ani aplikační server.

M0-02 adaptuje omezený JSON parser a UUID/timestamp validaci z `spikes/metadata.py`; schéma konfigurace přidává v `spikes/configuration.py`. Sdílené primitivy omezují rozcházení pravidel s artefakty; další parser ani závislost nejsou potřeba.

M0-03 adaptuje existující storage/index testovací scénáře; C++ probe je nová minimální testovací vazba přímo na libgit2, nikoli kopie cizího adapteru. Důvod zachování Git CLI a náklady případného přenosu koordinace jsou v [ADR 0005](docs/adr/0005-git-adapter-comparison.md).

## Již používané vlastní komponenty

Zdrojem je tento repozitář, základ průzkumu `384370e`. Závislosti: Python 3.11+, stdlib včetně sqlite3 a Linux fcntl, Git CLI; jediná deklarovaná pip závislost je PyYAML 6.0.3 v [requirements.txt](requirements.txt). Bash zajišťuje launcher. C++17/libgit2 je volitelný srovnávací experiment podle [ADR 0005](docs/adr/0005-git-adapter-comparison.md).

| Komponenta / zdroj | Rozhodnutí a důvod | Důkazy a omezení |
| --- | --- | --- |
| [Validace metadat](spikes/metadata.py) | **adapt**: společný omezený JSON/YAML parser, UUID a vztahy; nepřidávat další parser | [Testy](tests/test_metadata.py); V-04/V-05: kontrakt provenance a neměnnost zdrojů |
| [Journal](spikes/journal.py) a [Workspace](spikes/workspace.py) | **adapt**: zachovat společnou serializaci a obnovitelnou operaci | [ADR 0003](docs/adr/0003-coordinated-operation.md), [testy](tests/test_workspace.py); V-06/V-07: produkční ochrany a lifecycle |
| [Git a SQLite index](spikes/storage.py) | **adapt**: validovaný commit a rebuild projekce místo druhé autority | [Testy](tests/test_storage.py); V-02/V-03: integrační důkaz a úplnější projekce |
| [Konfigurace](spikes/configuration.py) | **adapt**: sdílená validační primitiva, oddělený projekt a uzel | [ADR 0004](docs/adr/0004-project-node-config.md), [testy](tests/test_configuration.py); V-08: zapojení do lifecycle |
| [Launcher](run.sh), [demo](spikes/demo.py), [check_project](spikes/check_project.py), [check_config](spikes/check_config.py) | **reuse** v nynějším vývojovém workflow | Příkazy v [README](README.md), důkazy v [TODO](TODO.md); V-01: automatizace CLI validátoru; není to aplikační server/UI |

Stavy těchto komponent jsou implemented / PoC validated dle odkazovaných ADR a TODO. Tento dokument nezaznamenává nový běh testů ani novou volbu stacku. Navazující úkoly a aktuální výsledky drží TODO.

M0-04 **adaptuje** omezený JSON parser z `spikes/metadata.py` a **reuse** stdlib HTTP/socketserver pro izolovaný [transportní experiment](spikes/local_api.py). Vlastní minimální handler odděluje zkoušku autentizace od aplikačního stacku; nejde o přenos cizího serveru ani produkční volbu frameworku. Rozhodnutí a limity: [ADR 0006](docs/adr/0006-local-api-transport.md).

M0-06a **adaptuje** `spikes/local_api.py` s odděleným statickým UI handlerem a **evaluate** systémový PyQt6/Qt WebEngine pro desktopový PoC. Důvodem je dostupný binding a zachování Python backendu bez portu či dalšího aplikačního procesu. Ověření a licenční/distribuční omezení: [ADR 0007](docs/adr/0007-desktop-poc.md); produkční Qt binding zatím není vybrán.

Ruční deploy **reuse** existující `spikes.demo` a requirements; **adapt** launcheru přidává transport omezeného archivu a oddělená vydání bez nové storage implementace. Aktualizace current nastává až po úspěšném demu; vzdálené ověření zůstává M0-05.

M0-06b **reuse** stávající launcher a desktopový kód ve zdrojovém archivu. Samostatný allowlist zdrojové distribuce zahrnuje testy a veřejné dokumenty; užší allowlist Omnia deploye zůstává oddělený, protože nepřenáší celý vývojový balíček. Nezavádí se bundler ani kopie Qt runtime.

M0-07 **adaptuje** existující storage scénáře a fixtures, **reuse** Git/Index/validate_snapshot. Nové případy ověřují konflikt páru obsah/sidecar a sémantickou validaci bez dalšího Git adapteru nebo kopírování cizí synchronizační vrstvy.

M0-06c **adapt**: doporučení zachovat Python/Git/SQLite a Qt UI, ověřit PySide6 místo portu jádra. **Evaluate** systémové závislosti a .deb; runtime bundler odložen do doložené potřeby. Důvody, oficiální licenční podklady a neověřené části jsou v [ADR 0009](docs/adr/0009-desktop-distribution-assessment.md).

M0-06d **adaptuje** stávající Qt obal na PySide6 a shiboken6; sdílené UI/API beze změny. Použity distribuční binding moduly rozbalené do /tmp, bez převzetí cizího aplikačního kódu. Ověření a měření: [ADR 0010](docs/adr/0010-pyside-desktop-validation.md).

Instalační .deb **reuse** stávající spikes a systémové dpkg-deb; **adapt** vzoru úplného dočasného artefaktu s hardlink publikací. Balík má užší runtime allowlist než zdrojový archiv; neobsahuje další kopii Qt ani instalační framework. Viz [ADR 0011](docs/adr/0011-debian-package.md).

Offline test **reuse** .deb builder a existující WebEngine smoke, **adapt** Linux unshare/setpriv/ip pro oddělenou síť s lokálním X11 socketem. Nezavádí druhý desktop ani produkční sandbox; hranice v ADR 0011.

M0-06 uzavírá **adapt/reuse** Python/Git CLI/SQLite a PySide6 pro M1 dle [ADR 0013](docs/adr/0013-m1-stack.md). C++ port ani hybrid se bez doloženého problému nezahajují. Produkční status reuse tím není přiznán.

Cílový probe **adaptuje** scénář z `tests/test_workspace.py` a dvojici obsah/sidecar z testových fixtures; **reuse** Workspace, Git a snapshot. Samostatný modul ve spikes lze přenést stávajícím deploy allowlistem bez rozšíření přístupu na jiná data nebo přidání nové storage vrstvy. Měření rozlišuje čas celé pomocné operace a apply/recover; Python RSS není součet všech procesů.
