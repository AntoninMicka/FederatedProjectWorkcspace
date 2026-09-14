<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->
# Desktopový síťový backend a test spojení

V nativní liště otevřete **Síť a test spojení…**. Vyberte konkrétní privátní
IPv4 desktopu, port 1024–65535 a povolenou LAN klientů. Backend je opt-in,
běží pouze s desktopovou aplikací, ve stejném procesu a se stejnou node identitou.
Neinstaluje systémovou službu ani nemění firewall. Zavření desktopu jej zastaví.

TLS lze zadat existujícími certifikátem/klíčem/CA nebo výslovně vytvořit lokální
CA a serverový certifikát pro vybranou IP. Generování nové CA mění důvěru TLS;
nezmění Ed25519 identitu uzlu. Nastavení a TLS jsou v soukromém adresáři
`.node.json.network` vedle node.json, nikoli v projektovém Gitu. Zálohujte je.
Neaktivní TLS adresář po přerušení není autoritativní konfigurace. Settings se
publikují až po úspěšném spuštění. Běžná chyba vrátí předchozí backend.

Aktivní HTTPS adresa se automaticky předvyplní v deploy průvodci. Změna
naslouchací IP/portu však nepřepíše existující desktopový peer na LXC;
aktualizujte tam jeho evidenci samostatně. Zjištěná IP není trvalá DHCP rezervace.

## Co se vystavuje

Backend desktopu vystavuje pouze POST `/v1/federation/probe` s UUID challenge.
Požadavek musí projít TLS, LAN a Host/Origin kontrolou, má limit 1024 bajtů.
Odpověď obsahuje node UUID, origin, přesnou challenge, veřejný Ed25519 klíč a
podpis. Jde o veřejnou kryptografickou identitu, ne o login. Nevrací token,
credential, uživatele, registry, projekty ani artefakty. GET a jiné POST route
na desktopovém síťovém backendu nejsou dostupné. Native UI server zůstává loopback.

Stejný probe doplňuje LXC web. Pro test musí být na LXC aktualizované nové
vydání; starší vydání vrátí 404 s doporučením aktualizace. Deploy přenese pouze
veřejnou CA přes ověřené SSH a uloží ji lokálně pod node UUID. Při starším deployi
lze v testu zadat důvěryhodný CA soubor ručně; nepoužívejte vypnutí TLS ověřování.

## Ověření protějšího uzlu

Vyberte zapamatovaný LXC uzel, jeho CA a **Ověřit HTTPS a identitu protějšího
uzlu**. Test používá aktuální endpoint schváleného peeru, čerstvou challenge,
kontrolu CA/SAN a podpisu proti původnímu pinu. Redirecty a proxy se nepoužívají.
Podpis jiné identity nebo stará odpověď se odmítají bez změny důvěry.

TLS chyba odkazuje na CA/platnost/SAN. HTTP 404 odkazuje na starou verzi uzlu.
Timeout/refused hlásí dostupnost backendu, adresu, port, směrování a možný firewall;
není to důkaz, že firewall je skutečná příčina. Úspěch ověřuje pouze spojení
**desktop → LXC**, HTTPS a identitu. Neověřuje opačný směr, login, přenos ACL,
revokací či projektových dat. Automatická datová synchronizace zůstává M5.

Implementace zatím nebyla ověřena testy, reálným Qt ani cílovým spojením.
