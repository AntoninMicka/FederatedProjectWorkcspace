<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

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

Jde o validaci balíku a dpkg lifecycle na existujícím hostu, nikoli čistou instalaci celého OS, test výpadku napájení nebo skutečnou persistentní práci UI. Balík neobsahuje síťové instalátory; smoke používá pouze loopback, síťově izolovaný OS test je otevřený. Plné clean-OS ověření, aktualizační zdroj a release inventář musí předcházet produkční distribuci. Maintainer adresa je v lokálním kandidátu nastavena na projektem určený kontakt; před produkčním zveřejněním je nutné potvrdit oficiální kontaktní údaje a jejich soulad s právní dokumentací. Balík se nikam nepublikuje.

Konkrétní kandidát a systémové závislosti zachycuje [inventář M0](0011-runtime-inventory.md). Jde o snapshot s hash vazbou na .deb, nikoli obecné potvrzení licenčních povinností. Aktuální výsledky uživatelských instalací a gate review drží [WORK_LOG](../../WORK_LOG.md).

## Následné offline ověření

`tests/test_desktop_offline.py` s volbou M0_OFFLINE_TEST=1 sestaví .deb, rozbalí jej mimo checkout a spustí jeho launcher dvakrát v novém Linux user/network namespace. Zachová běžné UID; setup pomocí keep-caps aktivuje pouze loopback v novém namespace, pak setpriv odstraní bounding/inheritable/ambient capabilities. Kontrola před GUI vyžaduje nulové effective/permitted/ambient capabilities, odlišné ID síťového namespace, jediné rozhraní lo ve stavu UP a prázdné IPv4/IPv6 směrovací tabulky. Pokus o TCP spojení na dokumentační adresu 192.0.2.1 musí skončit chybou chybějící trasy, nikoli pouze timeoutem. Nejde o ping ani kontakt živé služby.

DISPLAY musí označovat lokální X11; test použije unix socket /tmp/.X11-unix a odmítá přesměrovaný displej. Nezasahuje do sítě hostitele ani uživatelského kontejneru. Ověří skutečné JS kliknutí, autentizovanou loopback odpověď, zavření backendu a restart s novým čítačem. Chybějící namespace oprávnění nebo závislosti při explicitním zapnutí znamenají selhání testu, nikoli tichý skip.

Ověřeno na vývojovém Ubuntu arm64 s připravenými systémovými závislostmi. Je to důkaz běhu bez přímé externí IP konektivity, nikoli izolace filesystemu/IPC nebo čerstvé instalace OS. Lokální X server a systémový runtime jsou záměrně sdílené. Chromium sandbox se nevypíná. Předchozí odstavec popisuje historický stav před tímto experimentem; aktuální výsledky testů drží WORK_LOG. Výsledek se nepřenáší automaticky na uživatelův Debian s přesměrovanými Xky.

Následné ověření skutečné čisté instalace bez runtime hostitele, včetně interního Xvfb, offline restartu a upgrade/purge, je zaznamenáno v [ADR 0012](0012-clean-os-validation.md). Výše uvedená omezení původního izolovaného dpkg experimentu zůstávají historickým popisem jeho rozsahu.
