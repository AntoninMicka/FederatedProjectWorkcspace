<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0012 — Ověření instalačního kandidáta v čistém OS

Stav: PoC validated pro čistou instalaci M0-06e; tento dokument nevybírá nový stack. Navazuje na [ADR 0011](0011-debian-package.md).

## Protokol a izolace

Nový dočasný kontejner z oficiálního obrazu Ubuntu 26.04, nikoli kopie hostitelské dpkg databáze. Připojen pouze konkrétní .deb pro čtení na /tmp/app.deb, bez checkoutu, hostitelského Pythonu, Qt, projektových dat nebo Docker socketu. Uvnitř běží apt-get update a apt-get install --no-install-recommends /tmp/app.deb xvfb xauth iproute2. APT musí skutečně vyřešit a stáhnout závislosti; grafické nástroje jsou testovací infrastruktura.

Virtuální displej Xvfb běží uvnitř kontejneru, desktop pod běžným uživatelem tester. Před offline během se odpojí pouze síť nově vytvořeného kontejneru. Hostitelská síť a uživatelské přesměrované X11 zůstanou nedotčené. Nepoužívá se vypnutí Chromium sandboxu. Po experimentu se odstraní pouze kontejner vytvořený tímto testem; základní image může zůstat v Docker cache.

Instalační crash boundaries a rozsah vlastněných cest drží ADR 0011. Kontejner je zahoditelný, bez uživatelských dat; neprovádějí se migrace. Úspěch znamená čistou instalaci tohoto PoC, nikoli podporu všech distribucí/CPU, práci s persistentním projektem nebo odolnost proti výpadku napájení.

## Identifikace podkladů

- Checkout: ab56e4d.
- Image ubuntu:26.04, digest sha256:513c074113a871b51a8d16ab445c88779d6452d937a164fb5cc479f32668a41d.
- .deb SHA-256: 95f8fdb3a8afb94e2d058d40432c155723a3023ebd7d277631d7ba9be1b42fcb.
- Zdroj instalace: Ubuntu ports, resolute + updates/security, podpisové kontroly APT zůstávají zapnuté.

## Výsledek

Čistá instalace prošla bez změny .deb závislostí a bez dodatečného ručního doplňování runtime. APT nainstaloval 213 nových balíků a aktualizoval jeden; přenesl přibližně 218 MB a oznámil 812 MB dodatečného místa. Tyto hodnoty zahrnují i Xvfb, xauth a iproute2 a závisí na image/repozitáři; nejsou velikostí samotné aplikace. Aplikační adresář /usr/lib/federated-workspace-poc měl dle du 84 KiB. Kandidát má 22 060 bajtů.

| Komponenta | Verze ve skutečném kontejneru |
| --- | --- |
| OS | Ubuntu 26.04.1, aarch64 |
| federated-workspace-poc | 0.1.0~m0 |
| python3 | 3.14.3-0ubuntu2 |
| python3-yaml | 6.0.3-1build1 |
| python3-pyside6.qtwebenginewidgets | 6.10.2-6ubuntu1 |
| libqt6webenginecore6 | 6.10.2+dfsg-1 |
| xvfb | 2:21.1.22-1ubuntu1 |

Všechny uvedené balíky měly dpkg status installed; dpkg --audit nevydal chyby. Launcher běžel jako tester přes `runuser -u tester -- xvfb-run -a federated-workspace-poc --smoke`, s běžným Docker nastavením, bez privileged režimu, bez změny seccomp a bez vypnutí Chromium sandboxu. První běh se sítí skončil exit 0.

Po `docker network disconnect bridge <ID testovacího kontejneru>` zůstalo jediné rozhraní lo s IPv4/IPv6 loopback adresami a prázdné směrovací tabulky. Dva následné starty skončily exit 0; každý zobrazil autentizovanou hodnotu 1 a potvrdil ukončení backendu. Systémový D-Bus v minimálním kontejneru chyběl a Chromium vypsalo diagnostiku, ale funkční scénář tím nebyl přerušen. Hostitelský X server nebyl připojen ani použit.

Offline byl nainstalován nový kandidát 0.1.1~m0 přes dpkg -i, opět prošel grafický smoke, následoval apt-get purge. Launcher byl odstraněn; kontrolní soubory v /home/tester/projects a /home/tester/.local/state/workspace zůstaly bajtově stejné. Jsou to sentinel fixtures, nikoli důkaz recovery skutečného journalu. Runtime závislosti se záměrně neodstraňovaly přes autoremove. Testovací kontejner byl po úspěchu odstraněn; obraz zůstává v lokální Docker cache.

Tím je čistý instalační a offline scénář **PoC validated** pro tuto konkrétní platformu. Jde o ručně orchestrovaný experiment nad existujícím builderem, ne nový CI test. Kód aplikace/builderu se neměnil, celá unittest sada nebyla znovu spouštěna. Reprodukce vyžaduje Docker, uvedený image a .deb, dostupný podepsaný APT repozitář pro instalační fázi a dost místa. Veškeré instalace a změny sítě se provádějí pouze uvnitř nového testovacího kontejneru.

Release licenční povinnosti, aktualizační kanál a skutečný maintainer kontakt jsou nadále otevřené před veřejnou distribucí. Experiment neuzavírá měření a recovery na Omnii ani celý Gate M0.
