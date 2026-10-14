<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0031 — Obnovitelné odstranění lokálního projektu

Stav: přijato pro `F-M1-PROJECT-DELETE-01`, omezený Linux PoC. Navazuje na
ADR 0003/0015; nemění autoritu projektového Gitu, Workspace journalu ani
node-local backendových journalů.

## Rozhodnutí a vlastnictví

Společný desktop/web formulář nabízí tři rozdílné operace:

1. **Obnova odvozeného indexu** odstraní pouze `index.sqlite`. Registrace,
   repozitář, Workspace journal a receipts zůstanou; další otevření obnoví
   projekci z validovaného HEAD.
2. **Odregistrování** atomicky odebere pouze vazbu z `node.json`. Repozitář,
   projektový stav, chaty, backendové běhy a credentials zůstanou na místě.
3. **Obnovitelný koš** atomickými rename na stejném filesystemu přesune
   přesný inode repozitáře a projektového stavu do soukromého skrytého
   adresáře vedle původního rootu. Teprve poté publikuje odregistrování.

Definitivní výmaz není režim první operace. Je dostupný pouze nad dokončenou
položkou koše, má nový preview digest, nové operation ID a druhé explicitní
potvrzení. Jestliže existuje jakákoli projektová node-local historie, purge se
zastaví; první PoC neumí atomicky mazat řádky z mnoha samostatných autorit.
Symlink uvnitř potvrzeného koše se pouze unlinkne a jeho cíl se nenásleduje.

Node-local SQLite journal operací vedle `node.json` nově sdílí jediný writer
lock vytváření/registrace s tabulkou `project_deletions`. Záznam před prvním
účinkem připne operation ID, digest potvrzeného preview, project ID, root,
state, HEAD, inode/dev, původní a cílové bajty `node.json` a zvolený režim.
Stejné ID a požadavek vrátí receipt; jiný požadavek se odmítne.

## Inventář a blokátory

Preview pod projektovým writer lockem ověří root/state, HEAD, dirty worktree,
existenci indexu a pending Workspace operace. Dále inventarizuje odchozí Git
přenosy, aktivní účty a nerevokovaná federační mapování a známé projektové
záznamy chatů, AI úloh, hledání, rolových workflow a materializací.

Pending Workspace nebo transfer, aktivní federovaná vazba a stav
`prepared`, `run-bound`, `dispatching`, `running`, `publishing` nebo `unknown`
jsou fail-closed blokátor. Dokončené node-local záznamy se při odregistrování
a přesunu do koše zachovají a preview to výslovně ukazuje; zároveň blokují
definitivní purge. Sdílené provider credentials se nikdy nemažou automaticky.
Lokální operace vždy uvádí, že vzdálené, federované a dříve sdílené
kopie zůstávají nedotčené.

## Crash boundaries a recovery

| Hranice | Recovery |
| --- | --- |
| `prepared` | Journal už obsahuje přesný záměr a identity; projekt ani registrace ještě nemusejí být změněné. |
| `trash-created` | Přijme se jen přesný soukromý adresář se zaznamenaným inode/dev; cizí obsah je konflikt. |
| `root-trashed` | Chybějící původní root a shoda inode v `repository/` dokazují první rename; recovery pokračuje stavem. |
| `state-trashed` | Oba přesuny jsou doložené identitou; node registrace ještě může ukazovat původní bajty. |
| `node-published` | `node.json` odpovídá přesnému cíli; recovery už pouze uloží receipt. Cizí node změnu nepřepíše. |
| `root-restored`, `state-restored` | Opačné rename při obnově je doložené stejnými inode/dev; obsazený původní cíl operaci zastaví. |
| `trash-removed` | Prázdný operation trash je odstraněn; přesná původní registrace se publikuje až poté. |
| `derived-cleared` | Chybějící index je bezpečný opakovatelný stav; Git/journal zůstávají autoritou. |
| `purged` | Přesný zaznamenaný koš již neexistuje; opakovaná recovery nic dalšího nemaže a dokončí receipt. |
| `completed` | Stejné operation ID vrací uložený receipt bez dalšího filesystemového nebo síťového účinku. |

Všechny podporované mutace jsou serializované s vytvořením, registrací a
opravou umístění projektu. Startup obnoví pouze již explicitně potvrzenou
pending operaci. Změněný inode, HEAD/dopady před potvrzením, cizí obsah,
obsazený cíl nebo změněná node registrace se zachovají jako konflikt.

## Hranice PoC

Jde o lokální Linux PoC. Neodstraňuje vzdálené kopie, nerevokuje dříve
publikovaná data a neprovádí distribuovanou transakci. Dokončenou chatovou/AI
historii zatím umí pouze inventarizovat a zachovat, ne projektově hromadně
smazat. Ochrana proti nekooperujícímu procesu stejného Unix uživatele a
libovolným filesystemovým závodům zůstává V-06. `shutil.rmtree` nad přesným
soukromým trash inode je PoC hranice, nikoli obecný privilegovaný mazací
primitiv.

Implementace reuse/adaptuje node journal a atomickou publikaci ADR 0015,
Workspace writer/pending kontrakt ADR 0003, Git/Index a existující
preview/confirm UI. Nevzniká druhý projektový writer ani nová závislost.
Ověření drží `tests/test_project_deletion.py`, sdílené UI/API regrese
`tests/test_desktop.py` a `tests/test_web_server.py`; aktuální výsledky patří
do TODO/WORK_LOG podle stavu dávky.
