<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Federovaný projektový LLM workspace

Self-hosted workspace s projektovými soubory v Gitu, lokálními LLM backendy a desktopovým uzlem federace.

Projekt vstupuje do **M1 — Single-node project workspace** po splnění Gate M0. Obsahuje návrh, storage experiment a spustitelné desktopové PoC; desktop vytváří a registruje projekty a zobrazuje artefakty z Gitu. Nativní Markdown editor podporuje checklisty, hlavní TODO projektu a prohlížení historie/diffů uložených dokumentů.

## Desktop

```sh
./run.sh desktop
```

V horní liště klikněte na **Nový projekt…**, zadejte název a dosud neexistující cílovou složku a potvrďte **Vytvořit a otevřít**. Aplikace připraví Git, projektová metadata, lokální stav a registraci; po restartu projekt zůstane dostupný. JSON není nutné psát ručně. Výchozí uzel se ukládá do `$XDG_STATE_HOME/federated-workspace/node.json`, jinak `~/.local/state/federated-workspace/node.json`. Volba `--node /cesta/node.json` vybere jiný uzel.

[Postup, obnova a izolovaná ukázka](docs/project-opening.md) popisují umístění dat a omezení. Přerušené vytvoření se při běžném restartu obnovuje; existující cílová složka se nepřepisuje. Vyberte projekt a použijte **Dokumenty…** nebo **Úkoly projektu…**; změny potvrďte tlačítkem **Uložit**. Tlačítko **Ověřit spojení** zůstává jako test lokálního backendu. Návrh: [ADR 0015](docs/adr/0015-project-creation.md), desktopový binding: [ADR 0010](docs/adr/0010-pyside-desktop-validation.md).

Desktop nyní vyžaduje PySide6, bez fallbacku na PyQt6. Na ověřeném Ubuntu jsou potřebné moduly dostupné v repozitáři; pro běžné spuštění je připravte explicitně (při ověřování byly pouze rozbaleny do /tmp):

```sh
sudo apt-get install python3-pyside6.qtwebenginewidgets poppler-utils
```

Wrapper preferuje `.venv/bin/python`; pokud v něm Qt chybí, použije systémový `python3` pouze tehdy, pokud má WebEngine i požadovaný PyYAML 6.0.3. Jinak skončí s chybou. `./run.sh setup` připravuje storage závislosti, Qt neinstaluje. Desktop vyžaduje běžného uživatele a grafickou relaci; nespouštět přes sudo. Automatické vypínání Chromium sandboxu ani TLS kontrol není použito.

Grafické ověření (Python s dostupným Qt):

```sh
M0_DESKTOP_TEST=1 python3 -m unittest tests.test_desktop -v
python3 -m spikes.desktop --smoke
```

Volitelně `--smoke --screenshot /tmp/workspace-desktop.png` uloží snímek vlastního okna. Bez `M0_DESKTOP_TEST=1` se grafický test v celé sadě přeskočí; ostatní desktopové testy běží vždy. `demo` zůstává výchozím příkazem wrapperu.

## Spuštění storage experimentu

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

Testy vytvářejí izolované dočasné repozitáře a SQLite databáze a nemění globální Git konfiguraci. Výchozí sada používá dočasné Unix sockety a porty na `127.0.0.1` pro [lokální API PoC](docs/adr/0006-local-api-transport.md); nepotřebuje internet. Sandbox musí povolit lokální bind, jinak jde o selhání testu. Cíleně: `python3 -m unittest tests.test_local_api -v`. Volitelné [srovnání C++/libgit2](spikes/libgit2/README.md) vyžaduje samostatné sestavení; jeho explicitně zapnutý HTTP test používá pouze loopback a smyšlené credentials. Bez sestaveného probe jsou srovnávací testy označené jako skipped.

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
- [Compliance evidence](docs/legal/COMPLIANCE.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [IP, defensive publication a crowdfunding roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>)
- [Patent Risk Register](docs/IP/PATENT_RISK_REGISTER.md)
- [Defensive Disclosures](docs/IP/DEFENSIVE_DISCLOSURES.md)
- [První rozhodnutí a stav M0](docs/adr/0001-m0-baseline.md)
- [Metadata a journal: chování, ověření a omezení](docs/adr/0002-metadata-journal.md)

Aktuální dávku (milník), její průběžné výsledky a ad-hoc úkoly drží [TODO](TODO.md), další dávky [BACKLOG](BACKLOG.md) a uzavřené dávky s ověřením [WORK_LOG](WORK_LOG.md). Archivace a načtení další dávky probíhají až při jejím uzavření. Lokální API, desktopový instalační kandidát i cílový storage probe na Turris/LXC jsou ověřené v rozsahu M0. M1 nyní propojuje čtení registrovaných projektů s desktopem; produkční release zůstává otevřený.

## Ruční deploy na Omnii

Pro existující **běžící Debian LXC** na SSD připojeném na routeru jako `/srv`:

```sh
./run.sh deploy-omnia root@ADRESA_ROUTERU --container workspace-m0 --dry-run
./run.sh deploy-omnia root@ADRESA_ROUTERU --container workspace-m0
```

První příkaz pouze vypíše plán a seznam přenášených souborů. Druhý se připojí přes SSH (může požádat o heslo), ověří Btrfs mount `/srv`, běžící kontejner a shodu zařízení jeho kořenového filesystemu s SSD. Existující SSH host key musí být v known_hosts. Používá `ssh -F /dev/null`, tedy bez uživatelských aliasů/proxy nastavení; host zadávejte přímo. Hesla se neukládají. Příkazy se nespouštějí automaticky při startu desktopu.

Přenáší aktuální obsah `spikes/*.py`, `requirements.txt` a `LICENSE`, včetně případných lokálních úprav těchto souborů. Soukromý katalog, `.git`, `.venv`, jiné lokální repozitáře a projektová data se neposílají. V kontejneru vytvoří nové `/opt/federated-workspace/releases/<id>`, přes apt připraví Python/venv/Git/CA a přes pip závislosti, poté spustí dočasné storage demo. Instalace potřebuje internet v kontejneru a mění jeho balíčky; na routeru žádné balíčky neinstaluje, kontejner nevytváří ani nerestartuje.

Odkaz `/opt/federated-workspace/current` přepne atomicky až po úspěšném demu. Při selhání zůstává předchozí odkaz a nedokončené vydání pro diagnostiku. Změny apt/pip nejsou transakčně vráceny; žádná uživatelská data ani starší vydání se automaticky nemažou. Souběžná úspěšná nasazení mají vlastní adresáře, poslední přepnutí určuje current.

Jde o **instalaci headless PoC**, ne produkční služby: daemon, síťové API ani Qt na routeru nespouští. Demo lze ručně zopakovat na routeru:

```sh
lxc-attach -P /srv/lxc -n workspace-m0 -- sh -c \
  'cd /opt/federated-workspace/current && .venv/bin/python -m spikes.demo'
```

Ruční deploy a storage demo na Omnii jsou potvrzené uživatelským výstupem; důkaz a omezení drží WORK_LOG u M0-05. Potvrzen je také běh s TMPDIR=/var/tmp/workspace-poc na SSD/Btrfs. Výchozí /tmp je v ověřeném kontejneru tmpfs; měření tohoto běhu nelze vydávat za výkon SSD. Provozní měření a recovery na cílovém zařízení zbývají.

## Zdrojový balíček desktopového PoC

```sh
./run.sh package-desktop
# nebo vlastní cesta (existující soubor se nikdy nepřepíše):
./run.sh package-desktop --output /tmp/workspace-poc.tar.gz
```

Výchozí výstup je `dist/federated-workspace-poc.tar.gz` (ignorovaný Gitem). Obsahuje zdrojový kód, testy a veřejnou dokumentaci; nepřenáší `.git`, `.venv`, privátní katalog ani Qt knihovny. SHA256 každého souboru je v `MANIFEST.sha256.json`, hash archivu vypíše příkaz. Stejné bajty zdrojů vytvoří stejný archiv bez závislosti na čase sestavení. Hash dokládá integritu, není to podpis vydavatele.

Po rozbalení do nového adresáře spusťte `./run.sh desktop` uvnitř `federated-workspace-poc`. Platí stejné systémové závislosti jako v sekci Desktop; případný `./run.sh setup` připraví pouze Python závislosti. Balíček neobsahuje vlastní Python/Qt runtime, není to AppImage ani instalátor a není určen jako schválené produkční vydání.

Sestavení bere aktuální obsah vybraných zdrojů včetně necommitnutých změn. Kompletní archiv se nejprve zapíše do dočasného souboru ve výstupním adresáři a teprve poté zveřejní pod cílovým názvem bez přepsání existujícího souboru. Pád může zanechat `.package-*`; projektová data se nemění.

## Instalační kandidát .deb (Ubuntu 26.04 arm64)

```sh
./run.sh package-deb
sudo apt install ./dist/federated-workspace-poc.deb
federated-workspace-poc
```

Příkaz build potřebuje `dpkg-deb`; nic neinstaluje. Instalaci spusťte samostatně, aplikaci jako běžný uživatel. Závislosti dodává systém, včetně PySide6 WebEngine a PyYAML 6.0.3. Balík přidává také položku Projektový workspace PoC do nabídky aplikací. UI nabízí projekty, Markdown editor, checklisty a hlavní TODO; testovací čítač zůstává pro kontrolu spojení.

Aktualizační kanál je v této fázi explicitně **ruční**: nový release se instaluje opět přes nový `.deb` soubor a aktivní verzi pak řeší `apt install`/`dpkg`. `federated-workspace-poc` zatím nemá vlastní update feed ani auto-updater.

Pro další vydání zvolte vyšší verzi a jiný výstup; builder existující soubor nepřepisuje:

```sh
./run.sh package-deb --version 0.1.1~m0 --output /tmp/workspace-next.deb
sudo apt install /tmp/workspace-next.deb
sudo apt remove federated-workspace-poc
```

Před upgradem aplikaci zavřete. Balík nemá migrační/odinstalační skripty ani vlastnictví uživatelských projektů. Důkazy a omezení izolovaného dpkg testu: [ADR 0011](docs/adr/0011-debian-package.md). Čistá instalace, offline běh a upgrade/purge v Ubuntu 26.04 arm64 kontejneru jsou ověřeny v [ADR 0012](docs/adr/0012-clean-os-validation.md); produkční release zatím není připraven. Lokální balík není podepsaný repozitář ani automatický updater.

Volitelné ověření dpkg lifecycle na hostu s připravenými systémovými závislostmi: `M0_DEB_TEST=1 M0_DESKTOP_TEST=1 python3 -m unittest tests.test_package_deb -v`. Použije dočasný kořen, nikoli systémovou instalaci.

Offline grafický test bez odpojování hostitelské sítě (Linux, lokální X11 socket, `unshare`, `setpriv`, `ip`, `dpkg-deb` a připravené desktopové závislosti):

```sh
M0_OFFLINE_TEST=1 python3 -m unittest tests.test_desktop_offline -v
```

Test vyžaduje povolené user/network namespaces. Běží jako běžný uživatel, odmítá vzdálené/přesměrované DISPLAY a spustí rozbalený `.deb` pouze s loopbackem. Nemění hostitelské síťové rozhraní. Bez explicitní volby je přeskočen. Podrobnosti a hranice důkazu jsou v ADR 0011.

## Měření a recovery na Omnii (ruční M0-05)

Po nasazení aktuálních zdrojů přes `run.sh deploy-omnia` spusťte **uvnitř Debian kontejneru**:

```sh
cd /opt/federated-workspace/current
mkdir -p /var/tmp/workspace-poc
.venv/bin/python -m spikes.target_probe --base /var/tmp/workspace-poc
```

Probe vyžaduje Btrfs; nesouhlas filesystemu odmítne před vytvořením projektu. Pracuje jen ve vlastním novém adresáři, který při úspěchu odstraní. Při chybě adresář ponechá a vypíše jeho cestu pro diagnostiku. Nevypíná kontejner ani jiné procesy, nepřistupuje k síti. Disk musí být SSD podle ověřeného mountu; samotný typ Btrfs neprokazuje fyzické médium.

Výstup obsahuje prostředí, tři měření zápisu a 12 přerušení vlastního procesu na hranicích ADR 0003. Kontroluje pending čtení, zachování kandidáta, přesné bajty, jediný commit operace, opakovanou recovery a rebuild smazaného indexu. `process_s` zahrnuje start Pythonu, inicializaci dočasného Git projektu a apply; `apply_s` jen apply; `recovery_s` jednu recover operaci v řídicím procesu. `python_peak_rss_kib` je peak RSS Python workeru, nezahrnuje součet Git podprocesů ani paměť kontejneru. Nejde o benchmark velkých dat, trvalou službu ani výpadek napájení.

Úspěch končí `target probe: PASS; 3 measured runs, 12 crash boundaries; temporary data removed`. Výstup pošlete k vyhodnocení M0-05; lokální test tohoto nástroje sám neuzavírá cílové ověření. Volba `--expected-fstype` slouží pro explicitní ověření na jiném filesystemu, například v lokálních testech; na Omnii ponechte výchozí Btrfs.
