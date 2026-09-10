<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0007 — Spustitelný desktopový PoC

Stav: přijato pro desktopový experiment; produkční stack/balení zůstává otevřené. Datum: 2026-09-09.

## Rozsah a změna pořadí

Uživatel odložil měření backendu na Turrisu a požádal nejprve o desktopový PoC. Z jeho výstupů je doložen Turris Omnia, TurrisOS 9.1.1, ARMv7, LXC 6.0.5 a spuštěný Debian 13 Trixie kontejner na SSD. Instalace závislostí a běh aplikace na tomto cíli ověřeny nejsou. M0-05 ani celý M0-06 tím nejsou dokončené.

Výstupem je `./run.sh desktop`: Qt okno, statické české UI a autentizované volání paměťového čítače podle [ADR 0006](0006-local-api-transport.md). Projektové služby, soubory, Git, LLM ani federace nejsou na toto UI připojené.

## Lifecycle a hranice stavu před implementací

Backend běží v řízeném vlákně stejného Python procesu jako Qt obal. Není další aplikační backend ani IPC bootstrap soubor; Chromium má vlastní pomocné procesy rendereru. Zavření okna ukončí Qt smyčku, backend se shutdown/join uzavře a jeho token se zahodí. SIGINT/SIGTERM ukončují stejnou smyčku. Násilný pád procesu ztratí pouze čítač/token a OS zavře jeho socket. Žádná nová autoritativní persistence nevzniká; skutečný SIGKILL/recovery projektových dat není tímto experimentem ověřen.

Token vzniká v existujícím `running_api` a zůstává v nativní paměti. Request interceptor jej doplní jen pro POST na přesný `/v1/counter`, přesný server origin a požadavek iniciovaný tímto originem. Není v HTML, JavaScriptu, URL, cookie, argumentech procesu ani na disku. Statické assety mohou být načteny bez tokenu, neobsahují data projektu. Samotné API stále vyžaduje token a kontroly ADR 0006; spuštění běžného browseru na stejné URL mu autentizaci nezajistí.

Pro napojení Workspace nadále platí [ADR 0003](0003-coordinated-operation.md): klientská operation ID, opakování po ztracené odpovědi a receipts musí být vyřešeny před persistentními mutacemi, viz V-10.

## Volba obalu a omezení

Použít dostupný systémový PyQt6/WebEngine pro tento Linux PoC, bez portování backendu do C++ a bez nové pip závislosti storage. Na vývojovém hostu ověřeny balíčky `python3-pyqt6` 6.10.2 a `python3-pyqt6.qtwebengine` 6.10.0, Qt 6.10.2. PySide6 WebEngine nebyl dostupný. To je důvod lokální volby, nikoli finální srovnání distribučních variant.

Systémový copyright soubor PyQt6 uvádí GPL-3. Před distribuovaným balíkem je nutné posoudit licence všech částí, včetně Qt/Chromium, a zvolit závazně binding/balení; tato poznámka neprohlašuje právní kompatibilitu ani nemění MPL-2.0 projektu. PoC nekopíruje externí aplikační kód a neinstaluje nic při běžném spuštění.

Qt profil je bezejmenný (off-the-record), navigace povoluje pouze kořen vlastního originu, interceptor blokuje ostatní URL a nepovolené metody. Nová okna a downloady jsou odmítnuty. UI používá externí statický JS/CSS bez inline skriptů, CSP omezuje zdroje na vlastní origin a zakazuje framing, formuláře a změnu base URI. Žádné výjimky TLS ani vypnutí Chromium sandboxu se nepřidávají.

Jde o pevné důvěryhodné UI. Bezpečné vykreslování nedůvěryhodných dokumentů, XSS, systémový vault, více uživatelů, produkční HTTP server a instalovatelný desktopový balík nejsou tímto PoC vyřešené. Obnovu rendereru řešíme ukončením procesu s chybou, nikoli automatickým opakováním mutací.

Reference k mechanismům Qt: [request info / initiator](https://doc.qt.io/qt-6/qwebengineurlrequestinfo.html), [request interceptor](https://doc.qt.io/qt-6/qwebengineurlrequestinterceptor.html), [off-the-record profile](https://doc.qt.io/qt-6/qwebengineprofile.html). Dostupné binding API bylo ověřeno skutečným WebEngine během.

## Ověření

`tests/test_desktop.py` ověřuje hranici tokenu/originu, statické assety bez credentials, požadavek bez autentizace, nepovolené cesty a uzavření portu. Volba `M0_DESKTOP_TEST=1` navíc spustí skutečné Qt okno dvakrát: načtení stránky, JS kliknutí, autentizovaný fetch, hodnota 1 a zavření backendu. Bez volby je tento grafický test explicitně skipped. Testy nemění router ani projektová data.

Aktuální výsledky celé sady jsou ve [WORK_LOG](../../WORK_LOG.md), zbývající práce v [BACKLOG](../../BACKLOG.md). Tento výsledek uzavírá spustitelné desktopové demo, nikoli Gate M0/M1.
