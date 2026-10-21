<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0035 — Kontrola a oprava registrovaného projektu

Datum: 2026-10-21. Stav: navrženo v dávce `UX-PROJECT-REPAIR-01`.

## Kontext

Katalog dnes záměrně skryje detail chyby jednoho projektu a ukáže pouze jeho
nedostupnost. Pro doslova chybějící kořen už existují bezpečné akce opravy
umístění a odregistrování. Stejná nabídka ale nesmí řešit neplatná práva,
poškozenou registraci, cizí Git repozitář, neplatný commit, nedokončenou
operaci nebo chybný odvozený index: tyto stavy mají jinou autoritu i recovery.

Cílem je nejprve stav přesně a pouze pro čtení rozlišit. Teprve samostatná
potvrzená akce smí použít existující doménový recovery mechanismus. Nejde o
obecný `fsck`, obnovu ztracených dat ani heuristickou opravu projektu.

## Rozhodnutí

### Read-only kontrola

Kontrola přijme ID jedné registrace a provede pevné pořadí sond:

1. **registrace** — validní uzlová konfigurace, právě jedna vazba ID, bezpečné
   a vzájemně nepřekryté cesty;
2. **filesystem** — existence, typ, vlastník, práva, symlinky a vztah
   filesystemu kořene a lokálního stavu;
3. **Git** — skutečný nebare kořen, čitelný `HEAD`, podporovaná větev a žádná
   cizí probíhající Git operace;
4. **projekt** — committed `project.json`, shoda registrovaného ID, limity a
   sémantická validita celého snapshotu; pracovní `project.json` a dirty stav
   se hlásí odděleně od validity commitu;
5. **journal** — bezpečný existující stavový adresář, podporované schéma,
   správný vlastník kořene a přesně rozlišená pending/aktivní operace;
6. **index** — absence, zastaralost, podporovaná starší verze, neznámé schéma,
   integrita a shoda projekce s týmž validovaným `HEAD`.

Sonda nesmí inicializovat `Workspace`, `Journal` ani `Index`, protože jejich
konstruktory mohou vytvářet adresáře, databáze, tabulky nebo zámky. Existující
SQLite soubory se otevírají read-only; chybějící soubor je pozorování, nikoli
důvod k jeho vytvoření. Kontrola nevytváří Git objekty a nespouští příkazy,
které mění index nebo pracovní strom.

Report obsahuje `project_id`, stav `healthy`, `repairable`, `manual` nebo
`retry`, bezpečný souhrn a seřazená zjištění. Každé zjištění má stabilní
aplikační `code`, komponentu, závažnost, lidské vysvětlení a jednu z hodnot
`none`, `rebuild-index`, `resume-operation`, `repair-location` nebo `manual`.
Lokální desktop může po vědomém rozbalení ukázat cestu; síťová odpověď ji,
SQLite obsah ani výstup Git příkazů nikdy neobsahuje.

Report se váže na neprůhledný `check_token`, jehož digest pokrývá kanonickou
vazbu registrace, identity relevantních inode, `HEAD`, větev, stav pracovního
stromu a identifikátor/stav journalu a indexu. Pokud se vstup během kontroly
změní, výsledkem je `retry`; dílčí starý report se nepoužije jako podklad
opravy.

První verze kontraktu používá následující rodiny stabilních kódů; nový stav
smí přidat nový kód, ale nesmí změnit význam existujícího:

| Vrstva | Kódy zjištění |
| --- | --- |
| Registrace | `registration-invalid`, `registration-duplicate`, `registration-missing` |
| Kořen a stav | `root-missing`, `root-unsafe`, `state-missing`, `state-unsafe`, `state-filesystem-mismatch` |
| Git | `git-invalid-root`, `git-bare`, `git-head-missing`, `git-detached`, `git-operation-active`, `git-dirty` |
| Projekt | `project-config-missing`, `project-config-invalid`, `project-id-mismatch`, `project-worktree-mismatch`, `project-snapshot-invalid` |
| Journal | `journal-missing`, `journal-invalid`, `journal-owner-mismatch`, `journal-pending`, `journal-operation-active`, `journal-recovery-conflict` |
| Index | `index-missing`, `index-stale`, `index-legacy`, `index-invalid`, `index-unsupported`, `index-diverged` |
| Konzistence | `writer-busy`, `state-changed` |

`root-missing` vede pouze na dnešní opravu umístění/odregistrování.
`index-missing`, `index-stale` a podporované `index-legacy` jsou opravitelné
rebuildem. `journal-pending` a `journal-operation-active` jsou opravitelné jen
odpovídající recovery cestou. `writer-busy` a `state-changed` vyžadují nové
načtení; ostatní kódy jsou bez dalšího doménového rozhodnutí ruční.

### Povolené akce

První implementační řez smí nabídnout jen:

- **Rebuild indexu** — pouze pokud je registrace, filesystem, Git, committed
  konfigurace, snapshot a journal validní, není aktivní operace a index je
  chybějící, zastaralý nebo v podporované starší verzi. Akce znovu ověří token,
  získá existující writer lock a použije `Index.rebuild` nad pevným `HEAD`.
- **Pokračovat v operaci** — pouze pokud existující journal jednoznačně
  identifikuje podporovaný nedokončený intent. Akce znovu ověří token a vyvolá
  jeho dnešní doménovou `recover` cestu: aktivní Workspace operaci se stejným
  operation ID nebo standalone `Journal.recover` nad digestem přesných pending
  řádků. Check & Repair obsah journalu neupravuje a nevymýšlí náhradní intent.
- **Opravit umístění** — pouze přesměruje na existující potvrzený
  `ProjectCreation.relocate` tok pro doslova chybějící kořen; není novou
  opravnou akcí tohoto ADR.

Každá akce má samostatný náhled s přesným účinkem, dotčenou lokální vrstvou,
preconditions, recovery popisem a novým explicitním potvrzením. Úspěch vrací
receipt a následuje nová úplná kontrola; výsledek se neodvozuje pouze z návratové
hodnoty opravné funkce.

Automaticky se neopravují práva/vlastník, symlinky a cesty, node registrace,
ID, Git refs/branch/working tree, konfliktní či neplatná metadata, neznámé
SQLite schéma, cizí locky ani journalový konflikt. Nástroj také nemaže index,
journal, lokální stav nebo repozitář. Tyto stavy dostanou konkrétní ruční postup
nebo odkaz na samostatnou lifecycle akci; obecné tlačítko „Opravit vše“
nevznikne.

## UI a oprávnění

U nedostupného projektu přibude položka **Zkontrolovat projekt…**. Otevře
sdílenou webovou stránku s postupem kontroly a výsledky po vrstvách; samotné
filesystemové a Git sondy zůstávají desktop-only capability. Dostupný projekt
může mít stejnou kontrolu později v nástrojích, není to podmínka prvního řezu.

Kontrola je explicitní uživatelská akce, ne automatická mutace při načítání
katalogu. Backend znovu autorizuje konkrétní projekt a schopnost. Opravná akce
má užší samostatné oprávnění než diagnostika a nelze ji vyvolat pouze znalostí
ID nebo starého tokenu. UI nezobrazuje akci, kterou report a capability
současně nepovolují.

## Persistentní hranice a recovery

| Vrstva | Autorita | Povolená recovery |
| --- | --- | --- |
| Projektová data | validovaný Git commit | žádná automatická obsahová oprava; uživatel musí použít běžný verzovaný workflow |
| Pracovní strom a Git index | lokální projekce a rozpracovaná práce | diagnostika pouze hlásí stav; žádný reset, checkout ani odstranění locku |
| Projektový journal | autoritativní intent nedokončené operace | pokračování existující operace přes její `recover`; konflikt zůstane zachovaný |
| `index.sqlite` | obnovitelná projekce validovaného `HEAD` | atomický `Index.rebuild`; pád ponechá starou celou projekci nebo novou celou projekci a retry je bezpečný |
| Uzlová registrace | atomicky publikovaný node config a uzlový journal | pouze existující `relocate`/`unregister_missing` nebo budoucí zvláštní lifecycle operace |
| Identity a credentials | node-local správa mimo projekt | nikdy se neopravují z projektových dat ani z diagnostického reportu |

Pokud se proces ukončí před mutací, nezměnilo se nic. Po zahájení rebuild/recover
platí checkpointy a recovery příslušné existující služby. Pád po jejím dokončení
a před receipt či následnou kontrolou se řeší idempotentním dotazem na receipt a
novou kontrolou, nikoli opakováním jiné akce. Neznámý stav se označí `retry`
nebo `manual`, nikdy `healthy`.

## Reuse a odmítnuté varianty

Návrh reuse/adaptuje `Projects.catalog`, `directory`/`missing`,
`configuration`, `Git`, `validate_snapshot`, `Workspace.recover`,
`Journal.recover`, `Index.rebuild` a uzlové `ProjectCreation` operace. CLI
`check_project` poskytuje dílčí validaci artefaktové projekce, ale nekontroluje
registraci, `project.json`, Git, journal ani index, a proto není samo o sobě
Check & Repair backendem. Externí komponenta ani nový framework nejsou potřeba.

Odmítá se použití otevření projektu jako diagnózy, protože může inicializovat
stav a rebuild indexu; zachycení libovolné výjimky do jednoho textu; automatická
oprava při startu; „fix all“; kopie poškozených dat do Git commitu; reset Gitu;
mazání SQLite souborů; a odvozování projektu pouze podle cesty. Tyto varianty
stírají autority, skrývají konkrétní příčinu nebo mohou přepsat obnovitelný
intent a uživatelskou práci.

## Akceptační scénáře navazující implementace

Implementace musí testovat zdravý projekt, chybějící kořen, nepřístupnou a
symlink cestu, cizího vlastníka/práva, špatný Git kořen, detached HEAD a
probíhající Git operaci, chybějící/neplatný/cizí `project.json`, neplatný
snapshot, dirty pracovní strom, chybějící/stale/starší/neznámý/poškozený index,
samostatný pending journal, aktivní Workspace operaci, recovery konflikt,
obsazený writer lock a změnu každé vrstvy mezi check/preview/confirm.

U mutací se ověří přerušení na všech existujících checkpointech, lost response,
opakování stejného požadavku, cizí změna a následná úplná kontrola. Zvlášť se
prokáže, že samotná diagnostika na zcela novém či poškozeném stavu nezměnila
žádný inode, Git objekt, SQLite bajt ani čas změny souboru.
