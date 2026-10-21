<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0010 — PySide6 desktopové PoC

Datum: 2026-09-09. Stav: přijato pro M0-06d, PoC validated na vývojovém Ubuntu arm64. Navazuje na návrh [ADR 0009](0009-desktop-distribution-assessment.md); instalační kandidát a finální Gate M0 zůstávají otevřené.

## Rozhodnutí a hranice

Adaptovat Qt obal na PySide6/WebEngine. Launcher i přímý modul vyžadují jediný binding PySide6; nepřepínají potichu na PyQt. Uvolnění view před profilem používá shiboken6.delete místo sip.delete; callback runJavaScript má explicitní world ID. UI, token interceptor a backendové API se nemění. Lifecycle a crash boundaries z ADR 0007 platí nadále: pouze paměťový čítač/token, žádná nová persistence. Qt/Chromium pomocné procesy nejsou druhý aplikační backend. Toto mění binding PoC, nikoli automaticky produkční status všech komponent.

## Ověřovací prostředí

Ubuntu 26.04.1 arm64, Python 3.14, Qt/PySide 6.10.2. Systémové PySide postrádalo WebEngine; z Ubuntu ports byly přes apt-get download staženy balíky python3-pyside6.qtwebenginewidgets, qtwebenginecore, qtwebchannel a qtprintsupport verze 6.10.2-6ubuntu1 a přes dpkg-deb -x rozbaleny do /tmp/m0-pyside/root. Ostatní runtime závislosti již byly přítomné. Systém nebyl instalací změněn.

Testovací /tmp/m0-pyside/sitecustomize.py přidal rozbalený adresář do PySide6.__path__; PYTHONPATH=/tmp/m0-pyside tuto izolovanou vrstvu zapnul i pro potomky a test rozbaleného zdrojového balíčku. Tato dočasná vazba není součástí produktu. Normální spuštění potřebuje instalaci dle README; čistou instalaci bez této testovací vrstvy ověří M0-06e.

## Měření

Tři po sobě jdoucí běhy skutečného `python3 -m spikes.desktop --smoke`, bez vyprázdnění cache. Externí Python měřil monotonic čas od zahájení Popen po příjem stdout markeru. UI ready znamená loadFinished, nikoli přesný okamžik prvního vykresleného pixelu. API confirmed znamená JS zobrazení hodnoty 1 i shodu backendového čítače; polling přidává až přibližně 100 ms.

Externí vzorkovač přibližně každých 20 ms četl PPid a VmRSS z /proc/*/status, rekurzivně nalezl potomky desktopového PID a sečetl RSS. Peak je maximum vzorků, idle vzorek poblíž markeru 800 ms po úspěšném API, před zavřením. Kratší špičky mohou uniknout, čtení stromu není atomické a idle není dlouhodobý ustálený provoz. RSS může společné stránky započíst vícekrát; nejde o PSS ani unikátní fyzickou paměť. Do součtu nepatří měřicí proces. Chromium hlásilo fallback z GBM na Vulkan; výsledky neextrapolovat na jiný renderer/stroj.

| Běh | UI ready (s) | API confirmed (s) | Idle strom RSS (KiB) | Peak strom RSS (KiB) | Idle procesy |
| --- | --- | --- | --- | --- | --- |
| 1 | 0,894 | 0,915 | 582972 | 698164 | 4 |
| 2 | 0,915 | 1,015 | 577216 | 692596 | 4 |
| 3 | 0,927 | 0,936 | 580384 | 695836 | 4 |

Všechny měřené běhy skončily exit 0. Jde o desktopovou režii WebEngine, nikoli headless Omnia backend. Nejde o srovnání výkonu PySide a PyQt při stejných podmínkách ani důkaz produkční kapacity.

## Regrese a omezení

Stávající testy pokrývají policy URL/origin/token, statické assety, API a zavření socketu. Skutečný WebEngine smoke ověřuje JS kliknutí, restart a také rozbalený zdrojový balík. Nový opt-in --smoke-crash po úspěšném spojení ukončí renderer SIGKILL; aplikace musí skončit exit 1, nikoli falešným úspěchem. Není to SIGKILL celého backendu ani recovery persistentního projektu. Zákaz navigace/downloadů zůstává v nativním obalu; úplný adversariální browser test nedůvěryhodných artefaktů zůstává V-10.

Přesný závěrečný výsledek sady drží WORK_LOG. Instalační/licenční inventář skutečného releasu a ověření dalších architektur zbývají M0-06e. Současná měření nejsou důvod měnit jeden Python backend ani nasazovat Qt na Omnii.
