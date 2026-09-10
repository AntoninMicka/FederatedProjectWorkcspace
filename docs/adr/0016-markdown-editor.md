# ADR 0016 — Markdown editor, checklisty a hlavní TODO

Stav: přijato pro M1-03, lokální Linux PoC. Rozšiřuje nativní vstup ADR 0015 a koordinovanou operaci [ADR 0003](0003-coordinated-operation.md); nemění autoritu Gitu ani schéma v1.

## Dokumenty a hlavní TODO

Editor vytváří `artifacts/<UUID>/content.md` a `metadata.json` jako jednu operaci. Nový artefakt má kind document, privacy project, provenance user a stabilního lokálního autora z uzlového journalu vytváření, nikoli node UUID. Existující Markdown s frontmatterem i sidecarem zachová umístění a všechna metadata kromě explicitně upraveného názvu. Čtení obsahu a metadat vychází z jednoho validovaného commitu; SQLite zůstává projekcí. PoC editor omezuje tělo na 1 MiB; není editorem PDF, sources nebo registrů.

Hlavní TODO je běžný document se zvláštním stabilním ID: UUIDv5 s namespace rovným project UUID a názvem `federated-workspace:main-todo:v1`. Tato konvence nevyžaduje změnu project.json, zvláštní databázi ani nový metadata field. Název souboru ani titulek neurčuje roli; přejmenování titulku ji zachová. Jeden projekt může mít nejvýše jeden artefakt tohoto ID díky existující validaci unikátních ID. Rezervované ID obsazené nekompatibilním artefaktem se nepřepíše. Změna project UUID není migrací tohoto kontraktu a není podporována.

Hlavní TODO se nabídne samostatným tlačítkem i u starého/prázdného projektu a vznikne až potvrzeným uložením. Vytvoření projektu podle ADR 0015 zůstává prázdné. Jiné checklisty mohou být v libovolném editovaném dokumentu. Podporovaná syntaxe je `- [ ]`, `- [x]` / `- [X]`, také odrážky `+`/`*` a odsazené seznamy. Backtick/tilde fenced code bloky se neinterpretují jako úkoly. Checklist panel mění pouze stavový znak původního textu; nejde o převod na task registry nebo o synchronizaci samostatných entit. Číslované seznamy, úplná CommonMark/GFM interpretace a bohatý preview nejsou součástí tohoto kroku.

## Nativní mutující kontrakt a autorizace

Uživatel v desktopu vybere registrovaný projekt a otevře nativní dialog. Z rendereru se převezme pouze vybrané ID, které služba znovu ověří proti lokální registraci. Cesty nejsou parametry editoru. Ověření vlastnictví, disjunktních root/state, soukromého stavu, konfigurace a commitnuté identity adaptuje Projects a ADR 0014/0015. Jde o oprávnění lokálního uživatele, nikoli plné RBAC či ochranu před nekooperujícím FS útočníkem (V-06).

Při uložení dialog zmrazí požadavek `{project_id, artifact_id, base_head, title, body, new}` a přidělí operation UUID. Workspace pod společným zámkem sváže ID s SHA-256 kanonického JSON požadavku včetně lokálního author ID. Stejné ID/parametry dokončí pending operaci nebo vrátí trvalý receipt, i když odpověď zmizela a mezitím vznikl další commit. Stejné ID s jinými parametry odmítne. Kontrola base HEAD probíhá pod zámkem před sestavením změn a znovu při přípravě journalu. Změna HEAD nezpůsobí tichý overwrite ani automatický rebase rozepsaného textu.

Jeden dialog má nejvýše jeden worker, po dobu práce blokuje mutující ovládání a běžné zavření. Modalita brání souběžným dialogům ve stejném okně. Další proces dostane neblokující busy nebo stale/pending chybu. Nejasný výsledek ponechá text a původní požadavek; opakování použije stejné operation ID. Při přepnutí dokumentu, opětovném načtení nebo zavření s neuloženými změnami je nutné potvrdit jejich zahození. Rozpracovaný text před uložením není trvalý draft.

Otevření nativního editoru nebo tlačítko obnovy dokončí journal a načte aktuální commit. Webový přehled nadále pending odmítá a sám projektové zápisy neobnovuje. HTTP nemá editor mutation endpoint, credentials ani celý Markdown nevstupují do WebEngine. QPlainTextEdit a checklist položky zobrazují text; HTML se nespouští, odkazy ani obrázky nevyvolávají síťové požadavky.

## Crash boundaries a recovery

Hranice ADR 0003 zůstávají beze změny. Rozšíření před implementací bylo vymezeno takto:

- Před transakcí journalu může vzniknout lokální author ID; projektové soubory ani HEAD se nemění. GUI draft se při pádu může ztratit.
- V `prepared` se digest požadavku, operation ID a přesné payloady potvrzují společně. Recovery nevyžaduje opětovné sestavení metadat ani původní dialog.
- Mezi zápisem obsahu/sidecaru, vytvořením kandidáta, posunem větve a indexací se pokračuje dle ADR 0003. Cizí změny operaci zastaví a zůstanou zachovány.
- Po `completed`, před doručením odpovědi do GUI, existuje trvalý receipt. Retry ani nové otevření nevytvoří druhý commit stejné operace.

Git operace sdílejí deadline 60 sekund, SQLite čekání má limit 2 sekundy, flock editoru je neblokující. Deadline není preempce blokujícího filesystemového syscallu. Žádná z těchto záruk nedokládá výpadek napájení či odolnost proti pádu uvnitř libovolného Git podprocesu; retence receipts zůstává V-07.

## Reuse a ověření

Adaptovány Workspace/Journal/Git/Index, Projects, lokální author z ProjectCreation a nativní Qt widgets. Nový parser pouze mapuje checklisty na pozice textu; nepřibývá Markdown renderer, závislost nebo cizí framework. Soukromá inventura neposkytuje potřebný důvod nahrazovat existující storage či Qt cestu.

`tests/test_artifacts.py` ověřuje nové/změněné dokumenty, metadata, stabilní TODO, retry/receipt, stale/busy, odmítnuté vstupy, cizí editace, obnovu indexu, procesní pády na hranicích ADR 0003 a skutečný Qt editor s checkboxem i ztracenou odpovědí. Aktuální běhy a readiness drží [WORK_LOG](../../WORK_LOG.md). Obecné mutující HTTP API, plné RBAC, preview, registry úkolů a produkční provoz zůstávají mimo tento PoC.

## Read-only strom hlavního TODO — M1-03a

Na požadavek uživatele přidává levý panel přehled checklistů. `Workspace.read_project` vrací `main_todo` ze stejného validovaného snapshotu jako artefakty a commit ID, pod stejným zámkem a s původním odmítnutím pending. Crash boundaries ani zápisový kontrakt se nemění; případná inicializace/indexace čtení zůstává dle ADR 0014. Přehled nikdy nevolá editorové `Artifacts.open`, které by spustilo recovery.

Čisté funkce pro document, hlavní TODO ID a checklisty jsou sdílené v `markdown_documents.py`. Renderer dostává pouze titulek, texty položek, stavy a hloubku stromu; nedostává celé tělo, metadata, cesty ani credentials. Hierarchie vychází z odsazení checklistových položek (tabulátor = čtyři mezery); nadpisy a běžný text se nezobrazují jako uzly. Zobrazuje se prvních 1000 položek, souhrn počítá celý checklist; limit těla zůstává 1 MiB. Nepodporovaný formát/velikost má vlastní stav, neblokuje ostatní validní artefakty projektu.

UI používá textContent, disabled checkboxy a nativní HTML details/summary pro sbalení větví. Výběr projektu, nové načtení i chyba odstraní předchozí obsah; opožděná odpověď patřící staršímu požadavku se zahodí. Úspěšné uložení v nativním editoru využívá existující refresh přehledu. Externí změny se načtou opětovným otevřením projektu, periodické dotazování nevzniká. [Testy artefaktů](../../tests/test_artifacts.py) a rozšířený WebEngine smoke ověřují strom, stavy, readonly vykreslení a obnovení; výsledky drží WORK_LOG.
