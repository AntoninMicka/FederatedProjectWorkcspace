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

Sdílené web/desktop UI připraví projektově omezený VSIX s konkrétní relací.
Desktop spustí vybrané dostupné code/codium CLI bez shellu po nativním
potvrzení; web stáhne VSIX pro lokální instalaci. Po instalaci rozšíření
znovu potvrdí server/projekt a uživatel vybere repozitář odpovídající přesné
URL origin nebo absolutní cestě. Přihlašovací klíč není v URI/argumentech CLI,
ale pouze v generovaném VSIX a SecretStorage. VSIX je citlivý lokální
instalační soubor; uživatel ho po instalaci odstraní. Reinstalace rozšíření
nepřepíná existující relaci bez explicitního příkazu Propojit projekt.

Token má náhodných 32 bajtů, backend ukládá jen SHA-256. Platí 30 dní, lze jej
odvolat a autentizuje výhradně `/v1/ide-bridge/exchange`, nikoli obecné API.
Web při každém přístupu znovu kontroluje aktivitu účtu, credential_ref a
aktuální právo editora k danému projektu. Bootstrap admin relaci odvolává
explicitně; změna bootstrap tokenu sama není odvoláním vydaných relací.
Standardní Host/Origin/JSON/no-CORS ochrany zůstávají. Síťový server vyžaduje
HTTPS, plaintext je dovolen pouze na loopback desktopu. Soukromá CA se vybírá
lokálně; TLS validace se nevypíná. Obsah local-only se neexportuje ani přes
lokální desktop pairing. Instrukce a vybraný plán se zobrazují explicitně;
bridge sám nevolá externího LLM a neposkytuje mu automatická oprávnění.

První profil je lokální desktopové IDE napojené na desktop či web Workspace.
Browser-only rozšíření, Remote SSH, WSL a Codespaces nejsou podporované.
Windows používá tentýž Node adaptér, ale fyzické ověření Windows je samostatná
akceptace. Codex není hostitelem rozšíření: soubory mu lze explicitně předat
podle jeho povolených cest; orchestrace a automatické spouštění patří DEV-02/04.

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
