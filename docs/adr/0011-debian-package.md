# ADR 0011 — Instalační kandidát Debian

Stav: návrh a implementační ověření M0-06e, nikoli produkční release. Navazuje na ADR 0009/0010.

## Hranice selhání před implementací

Balík vlastní pouze /usr/lib/federated-workspace-poc, launcher /usr/bin/federated-workspace-poc, desktop entry a /usr/share/doc/federated-workspace-poc. Nemá maintainer skripty, daemon, migrace ani zápis do HOME, projektů, konfigurace či journalu. Instalaci, upgrade a odstranění souborů řídí dpkg; není to atomická transakce s projektovými daty. Při přerušení instalace je nutné dokončit/opravit stav správce balíků před spuštěním. Balík sám neprovádí rollback ani recovery uživatelských operací. Běžící aplikaci před upgradem zavřít.

Builder připraví kompletní .deb v dočasném adresáři a zveřejní jej atomickým hardlinkem bez přepsání existujícího výstupu. Pád před zveřejněním ponechá nejvýše dočasné soubory, nikoli částečný cílový balík. Není slib odolnosti vůči výpadku napájení. Projekty a journal se balíkem nezálohují ani nemažou.

## Rozsah

Architektura all označuje čisté Python zdroje; podporu všech OS/CPU neprokazuje. První ověřovací cíl je Ubuntu 26.04 arm64. Závislosti Python >=3.11, PySide6 WebEngine, Git a PyYAML >=6.0.3,<6.0.4 odpovídají současnému PoC. Runtime se nepřibaluje, při spuštění se nic nestahuje. Nejde o nový projektový server.

Inventář distribuovaných komponent: vlastní spikes/*.py pod MPL-2.0, launcher a desktop entry tohoto projektu. LICENSE je přiložen jako copyright. Python, PySide/Shiboken, Qt/Chromium, PyYAML, Git a SQLite jsou systémové závislosti; balík nekopíruje jejich binární soubory. Jejich skutečné verze a distribuční copyright soubory musí být součástí posouzení cílového releasu. Komerční licence se nepořizují. Zdrojový archiv zůstává odděleným artefaktem.

## Ověření a limity

Test sestaví balík a zkontroluje rozsah souborů, absenci maintainer skriptů, ochranu existujícího výstupu a odmítnutí neplatné verze. Dpkg pracuje pouze s dočasným --root a --force-not-root, bez chrootu a bez změny hostitelské databáze. Prázdná databáze odmítne konfiguraci kvůli závislostem; následná kopie status databáze hostitele modeluje dostupný runtime. Instalace, upgrade a purge zachovají kontrolní projekt mimo vlastněné cesty. Grafická varianta spustí instalovaný launcher z /tmp; Python -I odmítá vliv PYTHONPATH a uživatelského site-packages. Dřívější testovací PySide overlay se nepoužívá.

Jde o validaci balíku a dpkg lifecycle na existujícím hostu, nikoli čistou instalaci celého OS, test výpadku napájení nebo skutečnou persistentní práci UI. Balík neobsahuje síťové instalátory; smoke používá pouze loopback, síťově izolovaný OS test je otevřený. Plné clean-OS ověření, aktualizační zdroj a release inventář musí předcházet produkční distribuci. Maintainer adresa je výslovně nefunkční placeholder pro lokální kandidát, před publikací ji nahradit skutečným kontaktem. Balík se nikam nepublikuje.
