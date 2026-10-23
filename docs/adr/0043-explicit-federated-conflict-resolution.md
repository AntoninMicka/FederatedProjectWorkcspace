<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0043 — Explicitní řešení federované Git divergence

Datum: 2026-10-23. Stav: přijato a implementováno jako PoC v
`F-M5-CONFLICT-RESOLUTION-01`; fyzická desktop ↔ LXC akceptace ještě neproběhla.
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
retenci incoming refs. Fyzická klávesnicová, mobilní a desktop ↔ LXC akceptace
zůstává podmínkou uzavření dávky; implementované chování a automatické důkazy
eviduje [TODO](../../TODO.md).
