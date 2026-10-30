<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0060 — Lokální souborový IDE bridge

Datum: 2026-10-28. Stav: accepted (rozhodnutí uživatele).
Navazuje na ADR 0003, 0008, 0055 a 0059; feature DEV-IDE-TODO-01.

## Rozhodnutí a autorita

VS Code/VSCodium rozšíření vystaví obyčejné TODO.md, INSTRUCTIONS.md,
snapshot.json, inbox/*.json a receipts/*.json v privátním globalStorage
editoru. Nejsou projektovými artefakty ani novým autoritativním plánem.
Git-backed Workspace zůstává autoritou; stav úkolu mění výhradně běžný editor
s Workspace/Journal/Git/index recovery. Zpráva completed je návrh k lidskému
posouzení, nikoli akceptace. Nevyvolává commit ani spuštění agenta.

Uživatel výslovně odmítl FUSE a FileSystemProvider a požaduje neverzované
komunikační soubory. Adapter odmítá úložiště uvnitř libovolného Git worktree,
symlinky, neprivátní adresáře a neodpovídající zdrojový repozitář. Backendová
schránka je mimo projektový Git vedle node konfigurace a rovněž odmítá Git
worktree. Tyto cesty se nevkládají do zdrojového repozitáře ani jako záložní
kopie TODO; `.gitignore` není jedinou ochrannou hranicí. Explicitní `git add -f`
či pozdější ruční vytvoření Gitu uživatelem nejsou operace bridge; při další
synchronizaci se Git-contained storage odmítne.

## Propojení, privacy a instalace

Uživatelské upřesnění z 28. 10. 2026 znovu otevřelo akceptaci feature.
Ve verzi 0.2 je plnohodnotná stránka Nastavení → IDE a editory nezávislá na
otevřeném projektu. Rozlišuje připojení editoru k Workspace a tabulku
propagovaných projektů s konkrétní složkou či .code-workspace.

Nový generovaný VSIX schema-v2 nese připojení k Workspace, nikoli projekt.
Připojení samo nezpřístupní žádný projektový obsah: dovolí katalog aktuálně
oprávněných projektů a explicitní vytvoření/odvolání jejich mapování také
z nastavení rozšíření. Je to rozšíření původního credential scope schválené
uživatelem; token nesmí obsloužit obecné API. Každé mapování má vlastní
immutable projektový snapshot a schránku. Propagace bez vybraného lokálního
cíle zůstává unbound; před prvním exportem musí IDE potvrdit konkrétní cíl.
Repozitář a editor_workspace jsou oddělené údaje: .code-workspace může nést
více složek, jeho konkrétní Git root uživatel zvolí zvlášť.

Desktop instaluje přes potvrzené code/codium CLI bez shellu, web stáhne VSIX
pro lokální instalaci. Přihlašovací klíč není v URI ani argumentech CLI, ale
v citlivém generovaném VSIX a SecretStorage. Uživatel balíček po instalaci
odstraní. Jeden profil editoru používá jedno aktivní připojení a více mapování;
přepnutí připojení odstraní starý aktivní credential, zachová soubory.
Původní schema-v1 projektové relace i jejich zprávy/odvolání zůstávají dostupné.

Token má náhodných 32 bajtů, backend ukládá jen SHA-256. Platí 30 dní a je
odvolatelný. Schema-v2 autentizuje pouze `/v1/ide-bridge/connection/exchange`,
schema-v1 pouze původní `/v1/ide-bridge/exchange`. Web při každém přístupu
znovu kontroluje aktivní účet a credential_ref. Katalog nabízí jen aktuální
RW projekty editora; mapování i exchange navíc ověří projektová oprávnění,
read-only replikaci a privacy. Cizí připojení nesmí běžný člen spravovat.
Bootstrap admin připojení odvolává explicitně; změna bootstrap tokenu sama
není odvoláním vydaných credentialů. Odvolání rodiče blokuje všechny potomky;
odvolání mapování neodpojí ostatní projekty.

Standardní Host/Origin/JSON/no-CORS ochrany zůstávají. Síťový server vyžaduje
HTTPS, plaintext je dovolen jen na loopback desktopu. Soukromá CA se vybírá
lokálně, TLS validace se nevypíná. Local-only obsah se neexportuje ani přes
desktop. Bridge sám nevolá externí LLM a nepřidává mu oprávnění k cestám.

První profil je lokální desktopové IDE napojené na desktop či web Workspace.
Browser-only rozšíření, Remote SSH, WSL a Codespaces nejsou podporované.
Windows používá tentýž Node adaptér, fyzické ověření Windows je samostatná
akceptace. Codex není hostitelem rozšíření; orchestrace a spuštění patří DEV-02/04.

## Revize, zprávy a recovery

Export vyžaduje validní plán se stabilními ID; obsahuje přesný projektový
commit, revizi plánu a všechny kanonické definice včetně zahrnutých souborů.
Je immutable v rámci relace, nejvýše 1 MiB. Při změně HEAD je relace stale a
nové zprávy mají stale receipt. Uživatel připraví nové propojení, nepřepisuje
se zadání pod běžícím agentem. Zdrojový repozitář zůstává oddělený: zpráva
nese jeho skutečný commit, nikoli tvrzení backendu o ověřeném obsahu diffu.

Zpráva obsahuje message_id (UUID), task_id, kind completed/clarification/message,
body (nejvýše 16 KiB), revision a repository_commit. Zpracování je nejvýše
20 zpráv na exchange. Neznámá pole, cizí task ID/revize a kolize stejného
message_id s jinými bajty jsou odmítnuty. Stejné ID a payload vrátí stejné
potvrzení. received označuje pouze trvalé přijetí, acceptance zůstává
pending-human-review. Přehled ve Workspace zobrazuje zprávy jako bezpečný text;
člověk posoudí důkazy a případně upraví autoritativní TODO běžným editorem.

Crash boundaries:

1. Vytvoření relace zapisuje jednu SQLite transakci. Pád před commitem
   nezaloží platný token; pád po commitu před vrácením VSIX může nechat
   nepoužitou relaci. Je viditelná v přehledu a lze ji odvolat; nové propojení
   má nové ID. Nevznikl žádný projektový Git účinek.
2. Lokální zpráva se zapisuje do dočasného souboru, fsync a rename zveřejní
   hotový JSON. Rozpracované `.tmp` se neposílají; automaticky se nemažou.
3. Backend SQLite je autoritou přijetí a receipts. Každá zpráva a její
   receipt se commitnou spolu. Pád před commitem umožní nový příjem, pád po
   commitu před HTTP odpovědí vrátí při retry stejné potvrzení. U více zpráv
   může být přijatý prefix: retry celé dávky je idempotentní.
4. Klient zapisuje receipts atomicky a ponechává inbox beze změny. Pád před
   lokálním receipt způsobí bezpečný retry. Restart IDE načte SecretStorage
   a opět projde schránku; timer je jen probuzení, ne autorita doručení.
5. Snapshot soubory se nahrazují po jednom a snapshot.json se zveřejní po
   TODO a instrukcích. Pád uprostřed opraví další sync stejné immutable
   relace; nevzniká směs dvou revizí. STATUS není důkaz akceptace úkolu.
6. Odvolání a zveřejnění receipt sdílejí SQLite writer transakci. Již přijatá
   data zůstávají zachována. Odpojení v IDE zastaví sync a odstraní aktivní
   SecretStorage klíč, nemaže lokální zprávy; server se odvolává v aplikaci.

Doplněné crash boundaries mapování (stejná SQLite autorita, žádný Git zápis):

7. Tabulka connections vznikne přes CREATE TABLE IF NOT EXISTS, původní
   sessions/messages se nemění. Pád při inicializaci lze opakovat bez migrace
   původních credentialů. DDL a provozní zápisy používají uzavřené connection.
8. Změna cíle/revize odvolá předchozí session a vloží novou v jediné SQLite
   writer transakci. Pád či chyba mezi těmito kroky vrátí původní mapování;
   po commitu je aktivní pouze nové. Historické messages/receipts se nemažou.
   expected_mapping blokuje stale přepsání, stejný payload po ztrátě odpovědi
   vrátí aktuální relaci. Opakované vypnutí pozná odpovídající tombstone.
9. Bind přiřadí ověřený lokální repo/editor workspace a bound flag společně.
   Pád před commitem ponechá unbound, po commitu lze přesný bind opakovat.
   Klient uloží lokální přiřazení do SecretStorage až po potvrzení serveru;
   po ztrátě odpovědi konfigurace zopakuje map/bind bez ztráty zpráv.
10. Parent revokace, výměna mapování a receipt commit sdílejí SQLite writer
    hranici. Před přijetím zprávy se znovu ověří aktivní child i parent.
    Zpráva dokončená před revokací zůstane historickým přijetím, další
    zápis je odmítnut. Selhání jednoho lokálního projektu neblokuje sync jiných.

SQLite bridge journal není obnovitelný projektový index ani náhrada
Workspace journalu. Nevzniká operace zapisující současně Git a bridge SQLite;
proto se stávající ADR 0003 publikační recovery nemění. Testy pádu procesu
nenahrazují ověření výpadku napájení a Windows ACL.

## Reuse a zdroje

Reuse/adapt: Projects a ArtifactActions pro přesný validovaný snapshot,
same-origin handler pro transport, stdlib SQLite pro trvalý příjem, existující
sdílené UI a nativní navigační capability pro desktop instalaci. Malé nové
rozšíření používá stabilní Extension API, Node filesystem/HTTP a Git CLI.
Žádný externí kód se nekopíruje; soukromá inventura nenabídla hotový ekvivalent.
Odmítá se další writer, FUSE, FileSystemProvider, broker a povinné MCP.

Primární podklady ověřené 28. 10. 2026:
[VSIX distribuce](https://code.visualstudio.com/api/working-with-extensions/publishing-extension),
[CLI instalace](https://code.visualstudio.com/docs/configure/command-line),
[Extension API](https://code.visualstudio.com/api/references/vscode-api).
Runtime výsledky drží TODO, po uzavření WORK_LOG; dokument sám není důkaz testů.


## Doplnění 30. 10. 2026 — restart desktopu (DEV-IDE-RECONNECT-01)

Fyzický uživatelský log vykázal ECONNREFUSED na uloženém loopback portu.
Desktop running_api používá náhodný port při každém startu; připnutá síťová
adresa proto nestačila pro trvalé propojení. Zachováváme dynamický loopback
server a přidáváme node-local obnovitelnou discovery, nikoli pevný společný
port nebo nové párování. Zachování mapování je podmínka opravy.

Desktop zveřejní pro každé aktivní neexpirované připojení a původní schema-v1
relaci ID, aktuální loopback origin a HMAC-SHA256 podpis. Klíčem je existující
SHA-256 digest credentialu v SQLite; editor jej odvodí z SecretStorage.
Podepisované bajty jsou UTF-8 `id + "\n" + origin`. Token se do souboru
neukládá. Schema-v2 potomci používají descriptor rodiče, nikoli nový token.
Discovery je v privátní složce stejného lokálního uživatele mimo Git pod
`~/.local/state/federated-workspace/ide-discovery/`; ID oddělují uzly.
Rozšíření kontroluje typ/vlastníka/práva/symlinky, ID, podpis a přesnou HTTP
adresu 127.0.0.1 ještě před přenosem credentialu. HTTPS discovery nepoužívá.
Hranicí důvěry je stejný OS uživatel, nikoli ochrana před kompromitovaným
účtem s přístupem k databázi či SecretStorage. Server stále kontroluje
credential, expiraci, revokaci, privacy a oprávnění při každém požadavku.

Crash boundaries rozšiřují původní body výše:

1. Credential/mapování je commitnuté v SQLite před publikací descriptoru.
   Pád při publikaci nezruší credential; další start obnoví projekci z DB.
   Ztracená instalační odpověď má dosavadní recovery přes přehled připojení.
2. Publikace používá privátní dočasný soubor, fsync, rename a fsync adresáře.
   Čtenář vidí celý starý nebo nový descriptor; `.tmp` nepoužívá. Pád před
   rename může ponechat starou adresu, následující start ji znovu zveřejní.
3. Při ukončení descriptor zůstává: havárie a řádné vypnutí mají stejnou
   obnovu. Odmítnuté spojení nemaže SecretStorage, mapování ani zprávy.
   Další automatická synchronizace načte nově podepsanou adresu. Neplatný
   descriptor se odmítne bez síťového požadavku; chybějící descriptor zachová
   kompatibilitu s původním endpointem staršího desktopu.
4. Obecný aktualizační VSIX neobsahuje pairing.json. Aktualizace rozšíření
   stejného ID/profilu zachová credentials a mapování bez nového párování.
   Expirace, odvolání a explicitní změna identity uzlu tím nejsou obcházené.

Recovery testy a skutečný IDE smoke této opravy jsou evidovány u samostatné
feature dávky; původní historické důkazy zůstávají platné v původním rozsahu.
