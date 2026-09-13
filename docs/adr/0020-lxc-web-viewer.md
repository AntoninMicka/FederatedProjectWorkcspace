<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0020 — HTTPS náhled v LXC a dynamický vstup z routeru

Datum: 2026-09-10. Stav: přijato pro development PoC, implemented; cílové ověření otevřené v [M1-07](../../TODO.md).

## Rozsah a rozhodnutí

ADR 0013 ponechává serverový framework otevřený. Pro první LAN náhled adaptujeme existující stdlib HTTP handler, sdílené HTML/JS a Projects. Jeden Python proces v LXC obsluhuje HTTPS, bez Qt a nových pip závislostí. Toto rozhodnutí nevybírá produkční server ani neuzavírá Gate M1. Web umí katalog, hlavní TODO a náhledy; vytváření, editor a historie zůstávají nativní. Chat zachovává pouze lokální draft, bez LLM.

Server vyžaduje TLS certifikát/klíč a explicitní privátní IPv4 subnet klientů. Loopback je povolen pro healthcheck. Host se porovnává se skutečnou cílovou IP a portem socketu, Origin s HTTPS originem; proxy hlavičky nemění autoritu. URL s DNS jménem zatím není podporovaná. Přístupový klíč je náhodných alespoň 32 bajtů, uložený mimo projektový Git, v souboru 0600 vlastněném účtem služby. Ve webu zůstává pouze v paměti stránky, odesílá se v Authorization přes HTTPS; nepoužívá se URL, cookies ani localStorage. Odhlášení načte čistou stránku. Nejde o víceuživatelské RBAC: klíč zpřístupňuje registrované projekty včetně project/confidential pro jednoho důvěryhodného operátora.

Síťový režim odmítne celý projekt obsahující local-only entitu. Katalog skryje i jeho ID/název. Otevření a náhled kontrolují privacy nad stejným validovaným commitem pod stávajícím zámkem, před vrácením dat. Desktopové čtení se nemění. Automatická reklasifikace neexistuje.

## Dlaždice

### Rozšíření 2026-09-13: vytváření projektů a lokální správa

Webový správce nyní může vytvářet projekty přes stávající ProjectCreation
a journal ADR 0015. Individuální přístupové klíče oddělují lokální uživatele,
role a projektová členství; původní klíč zůstává bootstrap/recovery správcem.
Původní popis čistě čtecího a jednoklíčového webu výše je historický rozsah.
Správa eviduje UUID/domovský uzel uživatele a explicitní důvěru peerů,
ale neimplementuje federované přihlášení, handshake ani synchronizaci.
Rozhodnutí o samostatném Git registru správy, oddělených credentials,
CAS publikaci a crash boundaries popisuje [kontrakt správy](../administration.md).
Local-only kontrola nadále platí pro všechny identity. Registr není projektový
index ani distribuovaná autorita; serverový framework a Gate M5 zůstávají otevřené.

Formát registrace vychází z [oficiální specifikace Turris WebApps](https://gitlab.nic.cz/turris/webapps/-/blob/master/README.md), ověřené 2026-09-10. Nový vlastní kód používá číslovaný JSON pod `/etc/turris-webapps`, vlastní SVG a samostatnou lighttpd konfiguraci; cizí aplikační kód se nekopíruje.

Dlaždice má stálou relativní URL `/federated-workspace/`. Lighttpd předá požadavek pomocnému Python procesu na routerovém loopbacku. Ten spouští pouze pevný `lxc-info` s validovaným názvem kontejneru v `/srv/lxc`, vyžaduje RUNNING a právě jednu IPv4 v určeném subnetu, ověří HTTPS certifikát služby vůči připravené CA a vrátí necacheované 302 na její aktuální adresu. IPv6 se nevybírá. Při chybě, více IPv4, zastavení nebo změně během kontroly vrátí 503. Není použita periodická cache, shell s klientským vstupem ani přístupový klíč aplikace. Změna po dokončené kontrole zůstává přirozeným síťovým závodem; další kliknutí znovu vyhodnotí stav.

Routerový helper běží jako root kvůli čtení stavu LXC, ale poslouchá pouze na loopbacku a nemá mutující endpoint. Není to další backend projektu. Procd jej obnoví po restartu. Firewall se nemění; provoz je určen pro důvěryhodnou LAN. Certifikát musí pokrývat používané IP adresy: změna mimo jeho SAN se bezpečně odmítne do obnovení certifikátu. Instalace nesmí vypnout kontrolu TLS, aby zakryla tento stav.

## Persistence a recovery

Projektové zápisy se nepřidávají. Journal/index zachovávají hranice ADR 0003/0015; čtení může obnovit lokální index a inicializovat jeho state, nikoli měnit autoritativní Git.

LXC bootstrap publikuje kompletní identity/token soubory přes fsync a hardlink bez přepsání existujícího stavu. Pád mezi soubory lze opakováním doplnit; poškozené existující soubory se neobnovují generováním nové identity nebo klíče. Nedokončené dočasné soubory neobsahují autoritativní stav.

Opt-in deploy nejprve rozbalí nové vydání a ověří závislosti. Před přepnutím current a systemd unit uloží trvalý rollback snapshot (předchozí symlink, unit a enabled/active stav). Při chybě vrací tyto hodnoty; snapshot ponechá pro diagnostiku/obnovu. SIGKILL či výpadek napájení vyžaduje ruční obnovu před dalším deployem. Nová vydání, nainstalované systémové balíky, účet služby a prvotní konfigurace zůstávají zachované; nejde o transakční rollback celého OS. Projektová data se nemažou.

Routerový instalátor před změnou pěti vlastních souborů publikuje rollback journal s bajty, módy a stavem služby. `lighttpd -tt` musí projít před aktivací. Chyba vrátí původní soubory; přerušenou operaci dokončí příkaz recover. Opakované instalace používají stejné cesty a remove odstraňuje jen tyto soubory. CA je správcem dodaná a zůstává zachovaná. Journal se odstraní až po úspěšné aktivaci/obnově. Při selhání recovery zůstává k dalšímu pokusu. Současně smí běžet pouze jeden instalátor.

Postup, limity a cílová akceptace: [návod](../lxc-web.md). Průběžné testy a stav nasazení drží pouze TODO.
