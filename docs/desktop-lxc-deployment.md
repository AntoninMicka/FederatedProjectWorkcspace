<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->
# Desktopové nasazení LXC uzlu

V nativní liště desktopu otevřete **Nasadit LXC uzel…**. Zadejte SSH router,
název běžícího Debian kontejneru na SSD /srv, privátní LAN a pro prvotní
propojení skutečný HTTPS endpoint desktopového backendu. Současný desktopový
loopback HTTP server slouží pouze UI; není síťový federační endpoint.

Operace mají souhrn a explicitní potvrzení před vzdálenými změnami. Průvodce
používá jeden OpenSSH proces pro celou operaci, nikoli nové přihlášení pro každý
krok. Ověřování host key zůstává StrictHostKeyChecking=yes: důvěryhodný host
musí být předem v known_hosts. Lze použít ssh-agent nebo nativní askpass;
heslo se nezapisuje do konfigurace, logu ani do souboru. Router vyžaduje Python 3.

Instalace a application-only aktualizace adaptují stávající deploy. IP se po
nasazení zjišťuje přes lxc-info; v zadané LAN musí být právě jedna IPv4. Veřejná
CA se přenese do /etc/federated-workspace-ca.pem na router, soukromé klíče nikoli.
Aktualizace restartuje jen webovou službu, ne router ani kontejner.

## První instalace a důvěra

Pouze při nové instalaci vznikne lokální webový správce federace odpovídající
aktuálnímu desktopovému uživateli. Má vlastní deterministické user UUID a vlastní
credential; nejde o přihlášení desktopovým účtem ani přenos jeho hesla. Lokální
klíč správce je na LXC v soukromém adresáři
/var/lib/federated-workspace/.node.json.administration/deployment-admin-key.
Průvodce jej nepřenáší do desktopu ani nevypisuje do logu.

Průvodce získá veřejné Ed25519 identity přes schválené, ověřené SSH spojení a
schválí peery na obou uzlech. Pin se nikdy nemění automaticky. Existující peer
s jiným endpointem/pinem nebo neschválenou důvěrou vyžaduje ruční rozhodnutí ve
správě. Při aktualizaci ani opakované instalaci se účty a párování nepřepisují.

Projektové mapování se potvrzuje samostatným podpisem na každém uzlu pouze pro
společné registrované projekty. Nasazení nekopíruje projektová data. Prázdný nový
uzel proto skončí stavem „uzly propojeny, mapování čeká na společný projekt“;
nejde o aktivní projektové mapování ani synchronizaci. Později použijte správu
federace podle [existujícího kontraktu](administration.md). Práva se neslučují
ani nepřenášejí jako administrátorská role.

## Přerušení a recovery

Kód aplikace používá release/current a rollback snapshot z
[ADR 0020](adr/0020-lxc-web-viewer.md). Selhání následného párování nevrací
úspěšný deploy ani neresetuje funkční web. Účty a peer záznamy používají stávající
flock/CAS Git registr správy; není distribuovaná transakce přes oba uzly.
Pád mezi schváleními nebo podpisy může ponechat jednostranný stav, který je nutné
zkontrolovat a dokončit přes správu. Průvodce zatím nemá journal celé operace ani
automatické pokračování neúplného párování.

Credential správce se uloží před publikací registru. Pád před Git ref může
ponechat soukromý klíč bez aktivního účtu; setup jej nepřepisuje a vyžaduje
explicitní řešení. Pád po ref ponechá platný lokální účet. Původní bootstrap
access-key zůstává recovery cestou. Zálohujte identity, registry i credentials.

**Obnovit přerušené nasazení** obnoví předchozí release a službu v LXC.
**Resetovat stav** zahodí rollback snapshot a zastaví službu; není rollback.
Při chybě po úspěšném deployi nejprve řešte navazující krok, ne reset webu.

Implementace je neověřená: nebyly spuštěny nové testy, packaging ani vzdálené
nasazení. Nejde o production-ready federaci či ověřenou síťovou komunikaci.
