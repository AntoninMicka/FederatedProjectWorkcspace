<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0043 — Explicitní řešení federované Git divergence

Datum: 2026-10-23. Stav: přijato, implementováno a fyzicky akceptováno jako
PoC v `F-M5-CONFLICT-RESOLUTION-01`.
Navazuje na [ADR 0017](0017-artifact-history.md),
[ADR 0040](0040-federation-sharing-levels-and-project-matrix.md) a
[ADR 0042](0042-bidirectional-native-git-sharing-sync.md).

## Kontext a rozhodnutí

Obousměrný interní sync při divergenci úmyslně nemění lokální větev. Protější
head zachová v `refs/federation/incoming/<peer>/<operation>/<branch>`. Tento řez
přidává vědomé lokální řešení: Git určí jediný merge base a sestaví kandidátní
strom. Merge base zůstává skrytým výpočetním podkladem; aplikace zobrazí tři
pracovní panely `lokální / výsledek / vzdálená` a až explicitní potvrzení
publikuje jeden commit se dvěma rodiči. Automatický merge během
synchronizace, rebase, force update a obecný Git endpoint zůstávají zakázané.

První verze řeší pouze změny pod `artifacts/` a `registries/`. Jakákoli změna
`project.json` nebo jiné projektové cesty celý návrh odmítne, aby merge commit
nemohl tiše tvrdit začlenění historie, jejíž část byla zahozena. UTF-8 text lze
ručně upravit nebo zvolit naši, protější, obě či smazanou variantu. Binární či
jinak nepodporovaný soubor dovolí jen celo-souborovou volbu. Přejmenování se v
první verzi rozloží na vlastněné cesty, ale UI je označí jako `rename/update`.

## Reuse a UI spike

- **Reuse/adapt:** `Git`, `Workspace`/Journal/Index, snapshot a relationship
  validace, administrativní trust/sharing policy, stávající projektový pohled a
  bezpečný omezený Markdown renderer. `git merge-base`, `git diff` a
  `git merge-tree` zůstávají autoritou společného předka, změněných cest a
  automatického výsledného stromu.
- **Defer:** `@codemirror/merge` 6.12.2 je MIT balíček s pěti deklarovanými
  runtime závislostmi. Nabízí side-by-side i unified diff, changed chunks,
  accept/reject a navigaci. Není však hotovým výsledkově orientovaným
  třípanelovým 3-way resolverem.
  Zdrojový GitHub mirror byl v dubnu 2026 archivován a repozitář workspace nemá
  npm lock, auditovaný bundler, notice generování ani distribuci JS závislostí.
  Úplný tranzitivní licenční audit, klávesnicová a fyzická mobilní akceptace
  proto nejsou doložené. Balíček se nyní nevendoruje ani nepřidává jako runtime
  závislost; existující textarea kontrakt je později nahraditelný bez změny API.
- **Reject pro tento řez:** Monaco, archivovaný `diff-match-patch`, vlastní
  merge algoritmus a kopie cizího UI. Nepřidávají potřebnou autoritu, snapshot
  validaci ani crash recovery a zvětšily by distribuční plochu. Malý bounded
  řádkový porovnávač slouží pouze k barevné prezentaci rozdílů; merge strom,
  rodiče ani publikovaný obsah neurčuje.

## Read-only model a bezpečnost

Seznam i preview vyžadují registrovaný project UUID, přesný aktuální HEAD a
incoming ref aktuální větve. Ref musí mít kanonické peer a operation UUID,
ukazovat na validní commit a být skutečně divergentní; fast-forward ani již
začleněný head se za konflikt nevydává. Oba heady a jejich snapshoty se ověří,
síťový režim odmítne `local-only` a počet refů/cest i velikost souborů jsou
omezené.

Resolver při každém čtení znovu vyžádá schváleného interního peeru. `same-team`
povoluje aktuální větev automaticky; `same-company` navíc vyžaduje zapnutý
projekt a větev povolenou aktuálním `selected-only` nebo `all-except-hidden`.
Do digestu náhledu se připne peer revision, sharing level a přesný scope.
Potvrzení pod project writer lockem sestaví preview znovu a změněný HEAD,
incoming head, base, trust nebo policy odmítne. Webová cesta navíc vyžaduje
lokální write RBAC; data ani federace samy roli neudělují.

`git merge-tree --write-tree` zapisuje objekty pouze do dočasného object store s
repozitářem jako read-only alternate. Preview nemění projektové objekty, refs,
index, worktree, journal ani projektový SQLite index. Dočasný store po požadavku
zanikne. Raw výstup používá textová pole; formátovaný Markdown používá pouze
DOM elementy a `textContent`, nikdy zdrojové HTML.

## Potvrzení, persistentní vrstvy a recovery

Po explicitním potvrzení se pro každou změněnou cestu vyžaduje přesně jedna
volba. Konfliktní cesta nesmí použít automatický výsledek. Z voleb se sestaví
celý kandidátní snapshot a před zápisem projde stejnou metadata, sidecar,
relationship a privacy validací jako běžný Workspace zápis.

Publikace rozšiřuje existující koordinovanou operaci pouze o nejvýše jednoho
dalšího rodiče:

1. Před durable journal záznamem ani zavření rozepsaného preview nemění projekt.
2. `prepared` uloží request digest, přesný base, druhého rodiče a změněné cesty.
   Je dovolen i prázdný seznam cest, pokud vědomé řešení zachová celý náš strom;
   druhý rodič je v takovém případě stále významný výsledek.
3. Journal aplikuje vlastněné bajty a privátní index vytvoří kandidátní strom.
   `commit-tree` vytvoří jediný commit s rodiči `lokální HEAD, incoming HEAD`.
4. CAS změní pouze očekávanou lokální větev. Pád před CAS ponechá obnovitelnou
   operaci; pád po CAS se při retry stejného operation ID roll-forward dokončí.
5. Worktree/Git index se srovná s publikovaným commitem a obnovitelný projektový
   SQLite index se přestaví z jeho HEAD. Až potom je operace označena hotová.

Incoming ref se automaticky nemaže. Po úspěchu je jeho head předkem nového HEAD,
takže seznam konfliktů jej skryje; ref zůstává auditovatelný a pozdější retence
je samostatná politika. Ztracená odpověď vrátí pro shodné operation ID stejný
receipt, zatímco jiný payload pod stejným ID se odmítne.

## UI a omezení PoC

Projekt zobrazí červenou akci pouze při dostupné divergenci. Resolver má výběr
incoming historie a nejprve zobrazí seznam dotčených souborů se stavem řešení.
Kliknutí na soubor otevře modální raw nebo bezpečně renderovaný třípanelový
pohled `lokální / výsledek / vzdálená`; potvrzení celého merge zůstává v
nadřazeném seznamu. UI ukazuje počet nevyřešených souborů a dovoluje přímou
editaci výsledku. Řádky odlišné od výsledku jsou na lokální a vzdálené straně
barevně označené; prostřední editor samostatně značí rozdíl vůči každé straně i
vůči oběma. Na užší obrazovce se panely skládají do jednoho sloupce. Zavření
celého resolveru i opuštění stránky s rozepsaným výsledkem varuje; zavření
dialogu pouze vrátí uživatele do seznamu a rozepsaný návrh v aktuální relaci
zachová. Návrh není durable a po restartu se znovu sestaví z připnutých commitů.

PoC neposkytuje blokovou 3-way editaci, syntaktické Markdown slučování, obecný
binární merge, octopus merge, více merge bases, trvalé drafty ani automatickou
retenci incoming refs. Uživatel fyzicky potvrdil opravu konfliktu mezi desktopem
a LXC i následný sync výsledku. Samostatná fyzická mobilní a úplná
klávesnicová akceptace nebyla doložena a zůstává omezením mimo přijatý desktopový
scénář. Implementované chování a důkazy eviduje
[WORK_LOG](../../WORK_LOG.md#f-m5-conflict-resolution-01--historie-a-ruční-řešení-divergence--2026-10-23).

## Doplnění 2026-11-10 — místní změny blokující synchronizaci

Přehled konfliktů rozlišuje commitnutou divergenci, necommitnuté místní změny
a poslední hlášení konfliktu při synchronizaci s peerem. Místní změna se zobrazí
i bez incoming refu. Text pod `artifacts/` a `registries/` má omezený unified
diff proti aktuálnímu HEAD; binární obsah, změny pouze v Git indexu a ostatní
cesty mají položku s vysvětlením nedostupného textového porovnání. Obsah je
inertní text. Web znovu ověřuje privacy i podle místního kandidátního snapshotu;
neplatná metadata nebo `local-only` obsah se nesmějí přes toto porovnání zveřejnit.
Nedostupný přehled se v UI nevydává za nepřítomnost konfliktů.

Položka necommitnuté změny je read-only porovnání, nikoli druhá cesta publikace.
Neprovádí stash, reset, commit ani obnovu projektu. Existující merge potvrzení
zůstává odmítnuté při nečistém projektu; UI tuto překážku také výslovně zobrazuje
a zablokuje publikaci. Hlášení peeru neobsahuje jeho necommitnutý obsah:
uživatel jej prohlíží na uzlu, který změnu vlastní.

Příjem synchronizace po ověření podpisu a přesné kontrole uloženého requestu
nejprve rozpozná dokončený replay. Pro ostatní požadavky zkontroluje registrovaný
cílový projekt pod neblokujícím writer lockem ještě před ověřením Git historie.
Nečistý projekt bez rozpracovaného journalového zápisu vrátí stávající HTTP 409;
odesílatel zachová původní outbound operation ID a zobrazí stav `conflict`.
Metadata-only poll má stejnou kontrolu, protože i jeho odpověď připravuje Git stav.
Nejde o změnu formátu federačního protokolu.

Crash hranice ADR 0042/0081 ani publikační recovery výše se nemění. Včasné
odmítnutí nevytváří nový inbound intent, nepotvrdí přenos a nesmaže existující
nedokončený request. Rozpracovaná journalová operace má nadále původní
roll-forward cestu; její vlastní rozpracované bajty se nesmějí zaměnit za cizí
necommitnutou úpravu. Po vyřešení místní změny lze pokračovat stejným operation
ID. Dokončený replay vrací původní odpověď i při novější místní úpravě, protože
nic znovu nepublikuje. Kontrola čistoty při skutečném zápisu zůstává zachovaná
kvůli změnám vzniklým až po předběžné kontrole.

### Výslovné vyřešení místní změny

Na další žádost uživatele přibývá k původnímu read-only porovnání samostatný
náhled/potvrzení pro **obsah jednoho sledovaného artefaktu**. Uživatel může
zachovat prověřené bajty a uložit je do historie, nebo obnovit uloženou verzi
pracovního souboru. Metadata, nesledované soubory, registry a odlišná staged
verze nejsou tímto krokem automaticky přepsány; takový stav vyžaduje vlastní
posouzení. Akce neřeší následnou divergenci commitnutých větví za uživatele.

Webová varianta vyžaduje současné write RBAC a původní lokální write guard.
Jde o explicitní výjimku pro tento omezený conflict workflow, nikoli povolení
obecných Stage/Commit endpointů ve webu: ty nadále zůstávají desktopové.
Náhled váže project ID, HEAD, větev, jedinou deklarovanou cestu obsahu, přesné
hashe původních a pracovních bajtů a digest celého rozhodnutí. Síťová cesta
odmítne `local-only` jak v původním, tak kandidátním snapshotu. Potvrzení znovu
ověří shodu pod writer lockem; samotný náhled nezapisuje.

**Zachovat:** adaptuje `ArtifactGit.stage` a `ArtifactGit.commit` nad původním
Workspace writerem. Stage má deterministické dílčí UUID odvozené od hlavního
operation ID. Digest celého rozhodnutí včetně zprávy je připnutý v obou
fázích. Crash po Stage se dokončuje stejným intentem; commit prochází původní
metadata/reporting/plan validací, journalem, CAS a indexací. Pád po CAS ani
ztracená odpověď nevytvoří druhý commit. Pozdější pracovní bajty zůstávají
zachované jako další necommitnutá změna, nikoli součást starého rozhodnutí.

**Obnovit:** nový druh `artifact-working-restore` v témže privátním projektovém
journalu nemění Git HEAD ani Git index. Před zásahem atomicky uloží request
digest, HEAD/větev/index tree, vlastněnou cestu, původní bajty jako base64 zálohu
a původní journalové before/after obrazy. Po fsync intentu použije existující
atomickou souborovou obnovu Journalu. Až po úspěchu v jedné SQLite transakci
označí operaci dokončenou a odstraní pending payload. Záloha zůstává v privátním
operation recordu mimo projektový Git; HTTP receipt vrací pouze její operation
ID, ne zálohované bajty. Nový formát Git artefaktů ani federace nevzniká.

Obnova po pádu před zápisem či po výměně souboru kontroluje původní HEAD,
větev, Git index a souborové before/after bajty. Cizí editace vede ke konfliktu
a ponechání intentu i zálohy, nikoli k přepsání. Opakování již dokončené obnovy
je no-op i při novější pracovní úpravě. Stávající správa oprav může přerušenou
operaci dokončit přes `Workspace.recover`; downgrade s nedokončenou novou
operací nemá být vydáván za ověřenou kompatibilní recovery cestu.

UI vyžaduje náhled, popis a explicitní potvrzení. Neznámý výsledek opakuje se
stejným operation ID; opuštění stránky nezruší serverový intent. Nepotvrzený
náhled lze zavřít bez změny projektu. Akceptace skutečné uživatelské volby se
neodvozuje od nasazení ani od testů na dočasných projektech.
