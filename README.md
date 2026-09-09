# Federovaný projektový LLM workspace

Self-hosted workspace s projektovými soubory v Gitu, lokálními LLM backendy a desktopovým uzlem federace.

Projekt je ve fázi **M0 — Architecture spike**. Obsahuje návrh, storage experiment a spustitelné desktopové PoC; práce s projekty v UI ještě není implementovaná.

## Desktop

```sh
./run.sh desktop
```

Otevře samostatné Qt/WebEngine okno s tlačítkem **Ověřit spojení**. Tlačítko volá lokální backend; čítač se při zavření ztratí a backend se ukončí spolu s oknem. Jde o propojení UI/backendu, zatím bez otevření a ukládání projektů. Návrh a limity: [ADR 0007](docs/adr/0007-desktop-poc.md).

Na ověřeném Linux hostu jsou Qt moduly již dostupné. Na Debianu/Ubuntu lze chybějící systémové moduly připravit explicitně:

```sh
sudo apt-get install python3-pyqt6 python3-pyqt6.qtwebengine
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
- [IP, defensive publication a crowdfunding roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>)
- [Patent Risk Register](docs/IP/PATENT_RISK_REGISTER.md)
- [Defensive Disclosures](docs/IP/DEFENSIVE_DISCLOSURES.md)
- [První rozhodnutí a stav M0](docs/adr/0001-m0-baseline.md)
- [Metadata a journal: chování, ověření a omezení](docs/adr/0002-metadata-journal.md)

Aktuální pořadí práce drží [TODO](TODO.md). Lokální API i desktopové PoC jsou ověřené; distribuční balení a měření backendu na Turris/LXC zůstávají otevřené před uzavřením M0.

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

Skutečný vzdálený deploy zatím není ověřen; M0-05 čeká na ruční běh a výsledky měření.

## Zdrojový balíček desktopového PoC

```sh
./run.sh package-desktop
# nebo vlastní cesta (existující soubor se nikdy nepřepíše):
./run.sh package-desktop --output /tmp/workspace-poc.tar.gz
```

Výchozí výstup je `dist/federated-workspace-poc.tar.gz` (ignorovaný Gitem). Obsahuje zdrojový kód, testy a veřejnou dokumentaci; nepřenáší `.git`, `.venv`, privátní katalog ani Qt knihovny. SHA256 každého souboru je v `MANIFEST.sha256.json`, hash archivu vypíše příkaz. Stejné bajty zdrojů vytvoří stejný archiv bez závislosti na čase sestavení. Hash dokládá integritu, není to podpis vydavatele.

Po rozbalení do nového adresáře spusťte `./run.sh desktop` uvnitř `federated-workspace-poc`. Platí stejné systémové závislosti jako v sekci Desktop; případný `./run.sh setup` připraví pouze Python závislosti. Balíček neobsahuje vlastní Python/Qt runtime, není to AppImage ani instalátor a není určen jako schválené produkční vydání.

Sestavení bere aktuální obsah vybraných zdrojů včetně necommitnutých změn. Kompletní archiv se nejprve zapíše do dočasného souboru ve výstupním adresáři a teprve poté zveřejní pod cílovým názvem bez přepsání existujícího souboru. Pád může zanechat `.package-*`; projektová data se nemění.
