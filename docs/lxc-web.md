<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Webový náhled v LXC a dlaždice na routeru

Development PoC pro existující Debian LXC na SSD `/srv`, Turris WebApps/lighttpd a Python 3 na routeru. Cílové nasazení zatím není ověřené. Web nabízí čtení registrovaných projektů, TODO a náhledy Markdown/obrázků/PDF; editor, tvorba a historie zůstávají v desktopu. [Rozhodnutí a recovery](adr/0020-lxc-web-viewer.md), [aktuální stav M1-07](../BACKLOG.md).

## Příprava

Určete privátní IPv4 subnet klientů a kontejneru. Příklady používají dokumentační placeholdery `ROUTER` a `LAN_SUBNET`; dosaďte skutečné hodnoty. Výchozí kontejner je `workspace-m0`. Serverový port je 8443, routerový helper používá pouze `127.0.0.1:8846`. Přístup přes IPv6 a DNS jméno zatím není implementovaný.

V kontejneru je potřeba mít `/etc/federated-workspace/tls.crt` (certifikát a případný řetězec), `tls.key` a `ca.crt` (důvěryhodná CA pro instalační healthcheck). Pokud chybí, `deploy-omnia --web-lan` je umí vytvořit automaticky (včetně `keyUsage` a `subjectAltName`, včetně `127.0.0.1`). Certifikát musí být důvěryhodný pro klientské prohlížeče a zahrnovat IP adresy, které může tento kontejner dostat. Lze použít vlastní LAN CA a certifikát se SAN pro vyhrazený DHCP pool; změna mimo SAN vyžaduje obnovu certifikátu a restart služby. Nepoužívejte vypnutí ověřování TLS. `deploy-omnia --web-lan` navíc automaticky přenáší veřejný CA certifikát z kontejneru na router do `/etc/federated-workspace-ca.pem`; soukromý TLS klíč zůstává v LXC.

Prohlížeč vyžaduje náhodný přístupový klíč aplikace. První instalace jej vygeneruje v `/var/lib/federated-workspace/access-key` (0600); správce jej přečte uvnitř LXC a předá oprávněnému operátorovi mimo URL. Restart ani upgrade klíč nemění. Pro odvolání přístupu správce bezpečně nahradí soubor novým náhodným klíčem alespoň 32 bajtů, zachová vlastnictví/mód a restartuje službu. Klíč neopravňuje k práci přes SSH.

## LXC instalace

Nejdřív zkontrolujte plán z checkoutu:

```sh
./run.sh deploy-omnia root@ROUTER --container workspace-m0 --web-lan LAN_SUBNET --dry-run
```

Po přípravě TLS a schválení nasazení spusťte stejný příkaz bez `--dry-run`. Vyžaduje ověřený SSH host key. Balík obsahuje pouze zdroje a veřejné licenční podklady; lokální konfigurace a projekty se nekopírují. Bez `--web-lan` zůstává původní headless demo.

Služba `federated-workspace.service` běží pod účtem `federated-workspace`; persistentní data a projekty umisťujte pod `/var/lib/federated-workspace`. První start vytvoří prázdný `node.json` se stálým UUID. Registrace v něm používá stejný formát jako desktop, s absolutními cestami platnými uvnitř LXC. Projekt a state musí patřit účtu služby, state musí být 0700 a ležet na stejném filesystému. Registraci existujících projektů provádějte stávající službou ProjectCreation z lokální administrace pod tímto účtem; nekopírujte desktopový node.json s neplatnými cestami. Projekty s local-only entitou web nezobrazí ani v katalogu.

Kontrola uvnitř LXC:

```sh
systemctl status federated-workspace.service
journalctl -u federated-workspace.service -n 30
```

## Routerová dlaždice

Na routeru musí být Python 3, LXC nástroje, procd, lighttpd a `lighttpd-mod-proxy`. Před instalací ověřte, že cesta `/federated-workspace/` a port 8846 nejsou obsazené jinou aplikací. Podpora lighttpd a umístění JSON odpovídají [oficiální specifikaci WebApps](https://gitlab.nic.cz/turris/webapps/-/blob/master/README.md).

Po schválení přenosu zkopírujte **pouze** `scripts/router_tile.py` a `scripts/router_entry.py` do společného staging adresáře na routeru. TLS privátní klíč ani přístupový klíč aplikace na router nekopírujte. CA certifikát je už přenesen automaticky při `deploy-omnia --web-lan`. Ve staging adresáři:

```sh
python3 router_tile.py plan --container workspace-m0 --lan LAN_SUBNET
python3 router_tile.py install --container workspace-m0 --lan LAN_SUBNET
```

Instalace dlaždice zároveň vytvoří výhradně vlastní pojmenovanou UCI sekci
`lxc-auto.federated_workspace` v `/etc/config/lxc-auto`. Tím se kontejner
`workspace-m0` spustí při bootu routeru podle mechanismu Turris LXC; ostatní
sekce a kontejnery se nemění. Existující nekompatibilní sekce stejného jména se
odmítne bez přepsání. Opakovaná instalace je idempotentní a `remove` odstraní
jen tuto přesně ověřenou sekci. Stav autostartu je součástí stejného rollback
journalu jako soubory a služby dlaždice.

Před restartem ověřte konfiguraci bez ruční úpravy souboru:

```sh
uci show lxc-auto.federated_workspace
# očekáváno:
# lxc-auto.federated_workspace=container
# lxc-auto.federated_workspace.name='workspace-m0'
# lxc-auto.federated_workspace.timeout='60'
```

Instalátor spravuje pět vlastních souborů: helper, procd službu, lighttpd konfiguraci, JSON dlaždice a SVG. Ostatních dlaždic se nedotýká. JSON směřuje na stálou routerovou cestu; aktuální IP kontejneru se zjišťuje až při kliknutí. Bez právě jedné IPv4 v subnetu nebo při neplatném TLS/nedostupné službě se zobrazí zpráva o nedostupnosti. Dlaždice neobchází přihlášení do aplikace.

Odebrání integrace (projekty, LXC služba a CA zůstanou):

```sh
python3 router_tile.py remove
```

Při přerušené instalaci nejprve:

```sh
python3 router_tile.py recover
```

Trvalý rollback journal `/etc/federated-workspace-tile-rollback.json` se při neúspěšné obnově ponechá. Obsahuje předchozí soubory a stav služby; nemažte jej místo obnovy. Instalátor používá zámek proti souběhu.

## Obnova LXC instalace

Při běžné chybě se vrací předchozí `current`, unit a enabled/active stav. Snapshot `/opt/federated-workspace/web-rollback` zůstane pro kontrolu. Po přerušení procesu proveďte obnovu jako root v kontejneru, se zastavenou službou a bez souběžného deploye:

```sh
base=/opt/federated-workspace
unit=/etc/systemd/system/federated-workspace.service
exec 9>"$base/web-deploy.lock"
flock -n 9 || exit 1
test -d "$base/web-rollback" || exit 1
systemctl stop federated-workspace.service
if test -s "$base/web-rollback/previous"; then
    ln -s "$(cat "$base/web-rollback/previous")" "$base/.manual-restore"
    mv -Tf "$base/.manual-restore" "$base/current"
else
    rm -f "$base/current"
fi
if test -f "$base/web-rollback/unit"; then
    cp -p "$base/web-rollback/unit" "$unit"
else
    rm -f "$unit"
fi
systemctl daemon-reload
if test -f "$base/web-rollback/enabled"; then
    systemctl enable federated-workspace.service
else
    systemctl disable federated-workspace.service
fi
if test -f "$base/web-rollback/active"; then
    systemctl start federated-workspace.service
fi
```

Zkontrolujte návrat předchozího stavu a teprve poté odstraňte `web-rollback`. Nainstalované balíky/uživatelský účet, nové vydání a persistentní data zůstávají zachované. Toto není rollback operačního systému.

## Cílová akceptace

Ověřte otevření dlaždice a přihlášení, skutečný projekt/náhled, změnu IP v certifikovaném poolu, restart kontejneru i routeru, zastavení LXC, nejednoznačnou adresu, neplatný certifikát, opakované nasazení, obnovu po chybě a odebrání dlaždice se zachováním ostatních aplikací. Výsledky zapisujte do M1-07 v TODO; lokální unit testy nejsou důkazem této cílové akceptace.

## Runbook pro reálné ověření na routeru

1) Ověřte SSH k routeru a identifikujte cílový container:

```sh
ssh root@ROUTER "cat /etc/turris-version ; lxc list --format csv -n : name,state,ipv4"
```

2) Připravte TLS materiály a certifikáty (při `--web-lan` se doplní automaticky; ověřte, že SAN obsahuje cílové IP klienta/routeru).
3) Proveďte simulovaný nasazení:

```sh
./run.sh deploy-omnia root@ROUTER --container workspace-m0 --web-lan LAN_SUBNET --dry-run
```

4) Pokud je plán čistý, proveďte produkční deploy:

```sh
./run.sh deploy-omnia root@ROUTER --container workspace-m0 --web-lan LAN_SUBNET
```

Při problémové situaci použijte:

```sh
./run.sh deploy-omnia root@ROUTER --container workspace-m0 --web-lan LAN_SUBNET --reset
./run.sh deploy-omnia root@ROUTER --container workspace-m0 --web-lan LAN_SUBNET --regen-tls
```

`--reset` vyčistí `web-rollback` a znovu načte čistý stav deploymentu.
`--regen-tls` vynutí nové `/etc/federated-workspace/ca.crt`, `tls.crt`, `tls.key` před deployem.

5) Na routeru proveďte deployment kontrol a reálné scénáře:

```sh
ssh root@ROUTER "uci show lxc-auto.federated_workspace; lxc-attach -P /srv/lxc -n workspace-m0 -- systemctl status federated-workspace.service; /etc/init.d/omc-federated-workspace-web status; cat /var/lib/federated-workspace/access-key"
python3 router_tile.py install --container workspace-m0 --lan LAN_SUBNET
```
Routery bez `systemctl` kontroluj stav tile služby přes `/etc/init.d/omc-federated-workspace-web status`.

6) Ověření scénářů uživatelem:
Ověření 1: otevření dlaždice bezchybně načte přihlašovací stránku přes HTTPS 8443.
Ověření 2: zobrazení katalogu + náhled existujícího projektu.
Ověření 3: změna IP kontejneru po restarte (`lxc start/stop`, `lxc restart`) vede k nové adrese a tile ji při dalším kliknutí respektuje.
Ověření 4: restart routeru zachová funkčnost přihlášení po návratu služby.
Ověření 5: zastavený LXC hlásí srozumitelnou nedostupnost.
Ověření 6: při neplatném certifikátu je přihlášení odmítnuto.
Ověření 7: opakované nasazení je idempotentní.
Ověření 8: `python3 router_tile.py recover` vrací původní stav po přerušené instalaci.

7) Úklid:

```sh
python3 router_tile.py remove
```

8) Zapište časový záznam do `TODO.md`:
Zapište datum a zařízení; výsledky kroků 1–8; popis selhání a přesný příkaz oprav.

## Aktualizace aplikace a vedená obnova

Pro existující webové nasazení použijte:

```sh
./run.sh deploy-omnia root@ROUTER --container workspace-m0 --web-lan LAN_SUBNET --update-only
```

Režim vyžaduje existující službu, release a node/access-key. Nepouští apt,
nevytváří účet služby, nebootstrapuje uzel a negeneruje TLS. Připraví nové
izolované vydání s vlastní venv, nainstaluje jeho Python dependencies a teprve
pak přepne službu s rollback snapshotem a HTTPS healthcheckem. Aktualizace
krátce restartuje aplikaci, nikoli router či kontejner. Není to offline update.
Chybějící systémové závislosti řešte běžným deployem bez `--update-only`;
ten nyní přeskočí apt, pokud jsou všechny požadované balíky již nainstalované.

Při přerušeném nasazení preferujte skutečnou obnovu:

```sh
./run.sh deploy-omnia root@ROUTER --container workspace-m0 --web-lan LAN_SUBNET --recover
```

Obnova se provede v LXC a vrátí předchozí current, unit a enabled/active stav.
Snapshot se odstraní až po dokončení obnovy. Retry po selhání používá stejnou
obnovu a nové release ID; neúplná vydání zůstávají pro diagnostiku.
`--reset` není rollback: zahodí snapshot a zastaví službu, potom je potřeba
nový deploy. Používejte jej pouze jako výslovný poslední krok, nikoli první
reakci na chybu. Chyba deploye nyní vypisuje tyto příkazy pro konkrétní cíl.
`--regen-tls` patří k běžnému deployi a mění CA důvěru; nelze ho spojit s update,
recover ani reset. Žádný z těchto režimů nemění firewall.

Změny jsou implementované, zatím bez nového testového či cílového ověření.

Desktop nabízí také nativní **Nasadit LXC uzel…** s jedním SSH spojením,
detekcí IP a prvotním založením lokálního správce/propojením peerů.
[Průvodce, hranice párování a neověřené scénáře](desktop-lxc-deployment.md).
