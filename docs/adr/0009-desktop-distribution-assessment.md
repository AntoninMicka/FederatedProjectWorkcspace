<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0009 — Posouzení desktopového bindingu a distribuce

Datum: 2026-09-09. Stav: **navrženo, designed** (M0-06c). Doporučení pro ověření, nikoli finální uzavření stacku nebo distribuční release. Historická rozhodnutí [ADR 0005](0005-git-adapter-comparison.md) a [ADR 0007](0007-desktop-poc.md) zůstávají platná.

## Podklady

Posouzen checkout `3549811`, čistý pracovní strom. Současný launcher a desktop používají PyQt6, zdrojový balíček obsahuje Python zdroje bez Qt runtime. Na vývojovém Ubuntu 26.04.1 arm64 je importem potvrzen Qt/PyQt 6.10.2. PySide6 je přítomné, ale `find_spec` pro QtWebEngineCore i QtWebEngineWidgets vrací None. Místní apt-cache nabízí oba moduly ve verzi 6.10.2-6ubuntu1; jde o obsah lokálního katalogu, ne ověřené stažení, instalaci nebo spuštění.

Uživatelské důkazy v [WORK_LOG](../../WORK_LOG.md) potvrzují desktopové kliknutí/zavření/restart i headless Python storage demo na Omnia ARMv7, včetně běhu na SSD/Btrfs. Čas 0,66 s a RSS 11 520 KiB patří pouze celému demu v tmpfs. Nejsou měřením startu desktopu ani výkonu SSD. C++/libgit2 má srovnávací PoC na vývojovém hostu; produkční port Workspace by stále vyžadoval novou práci.

## Porovnání a doporučení

| Varianta | Přínos | Náklady a rozhodnutí |
| --- | --- | --- |
| Python + stávající Git CLI/SQLite | Zachovává journal, validátory a testy; běží i na cílovém ARMv7 | Doporučené společné jádro pro M1. Finální potvrzení závisí na zbývajícím M0-05; nový HTTP framework tím nevybíráme. |
| PyQt6 + Qt WebEngine | Současný ověřený desktop, bez portu | Zachovat pro dosavadní PoC. Pro distribuci by bylo nutné vyřešit GPL nebo komerční podmínky bindingu. |
| PySide6 + Qt WebEngine | Zachovává Qt návrh a nabízí LGPL cestu pro binding | Preferovaný kandidát pro distribuci. Nejprve ověřit skutečné API, vlastnictví Qt objektů, interceptor, shutdown a balení; shoda názvů tříd není důkaz kompatibility. |
| C++ Qt / libgit2 | Nativní alternativa již částečně prozkoumaná | Nyní nepřepisovat ověřené jádro. Hybrid přidává IPC a recovery hranice bez doložené potřeby. |
| Nový desktopový framework | Potenciální alternativa obalu | Nezahajovat další migraci bez selhání Qt kandidáta nebo konkrétního požadavku; další runtime a bridge by opakovaly bezpečnostní práci. |

Doporučení je inference z existujících důkazů a níže uvedených licenčních podkladů. Neprohlašuje PyQt za nepoužitelné s MPL ani LGPL za automatické schválení celého distribučního balíku. Licence projektu MPL-2.0 se nemění; komerční licence se nepořizuje.

## Distribuční cesta

První kandidát: nativní `.deb` pro konkrétní ověřenou Ubuntu verzi/architekturu se systémovým Pythonem, dynamickým Qt/PySide WebEngine a deklarovanými závislostmi. Výchozí ověřovací host je arm64; amd64 a jiné distribuce se nestávají podporovanými bez vlastního běhu. Dostupnost kompatibilního PyYAML (nyní přesně 6.0.3) musí být ověřena, nikoli obejita vypnutím kontroly verze. Nesoulad vyžaduje explicitní řešení závislostí a testy.

Balíček má oddělit aplikační soubory od uživatelských projektů, identity, credentials a journalu. Instalace/aktualizace nemá přepisovat autoritativní data ani spouštět pip do systémového Pythonu. Budoucí instalátor musí mít vlastní popis hranic selhání a recovery před implementací. Po odinstalaci musí zůstat uživatelská data. Za běhu se nic automaticky nestahuje a není potřeba root.

Zdrojový tar.gz z M0-06b zůstává vývojový/distribuční zdroj, nikoli hotový instalační balík. Přibalený runtime přes pyside6-deploy nebo jiný freezer je druhá možnost pro případ doložené nevyhovující systémové distribuce: navíc vyžaduje dohledání WebEngine helperu, zdrojů/locales/pluginů, licenčních souborů a aktualizace vlastního Qt/Chromium runtime. Nástroj sám nezaručuje úplný a bezpečný balík. Více formátů současně nyní nezavádět.

Omnia zůstává headless bez Qt; stávající ruční deploy zachovat. Sdílené Python jádro nevyžaduje shodný instalační formát desktopu a serveru. Vzdálené připojení desktopu ani serverový daemon toto rozhodnutí neimplementuje.

## Licenční podklady

Oficiální podklady ověřené při tomto posouzení:

- [Riverbank: PyQt](https://www.riverbankcomputing.com/software/pyqt): binding má GPL v3 nebo komerční licenci; LGPL licence přibaleného Qt nemění licenci PyQt.
- [Qt for Python: licences](https://doc.qt.io/qtforpython-6/licenses.html): LGPL/komerční rámec a samostatné podmínky použitých komponent třetích stran.
- [Qt WebEngine licensing](https://doc.qt.io/qt-6/qtwebengine-licensing.html): licenční režim Qt části a samostatné licence Chromium a dalších komponent. Neodvozovat licenci celého runtime jen z bindingu.
- [Qt for Python deployment](https://doc.qt.io/qtforpython-6/deployment/index.html): zdrojový archiv, Python balíček, frozen aplikace a instalátor jsou různé distribuční varianty; dostupnost nástroje není test tohoto projektu.

Před releasem vytvořit inventář skutečně distribuovaných verzí/souborů a jejich licencí (Python, binding/Shiboken, Qt/WebEngine/Chromium, PyYAML, případně přibalený Git/SQLite). U každé komponenty určit notices, zdroje/jejich zpřístupnění a ostatní povinnosti podle zvoleného režimu; ověřit možnost výměny dynamických knihoven a podmínky instalace. Samostatné systémové balíčky zjednodušují správu závislostí, neruší licenční povinnosti. Posouzení je technický výběr cesty, nikoli hotový právní audit konkrétního releasu.

## Akceptace navazujícího ověření

1. Získat PySide WebEngine do izolovaného prostředí nebo explicitní instalací; zaznamenat verze a původ. Adaptovat minimální Qt vazbu, ne storage ani UI protokol. Běh musí určit binding jednoznačně, bez tichého fallbacku maskujícího chybu.
2. Ověřit stejné bezpečnostní a lifecycle scénáře jako M0-06a: skutečné JS kliknutí, native token pouze správnému cíli, zakázané navigace/downloady, zavření portu, restart a pád rendereru. Spustit celou sadu dle AGENTS; grafické testy skutečně zapnout.
3. Změřit start do připraveného UI a do první úspěšné API odpovědi, klidovou i špičkovou paměť včetně Chromium potomků. Zaznamenat metodu, platformu a několik běhů, nikoli vydávat samotné RSS rodiče za celek.
4. Teprve s ověřeným bindingem sestavit instalační kandidát, otestovat čistou instalaci bez checkoutu, start bez sítě, chybějící závislost, upgrade/odinstalaci bez ztráty uživatelských dat a velikost instalace. Doplnit inventář skutečných distribučních licencí.

M0-06c tím uzavírá posouzení variant. M0-06d ověří binding a měření, M0-06e instalační kandidát; celý M0-06 a Gate M0 zůstávají otevřené. Žádný kód, persistentní lifecycle ani chování run.sh se v tomto návrhu nemění.
