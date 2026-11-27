<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Čtecí pohled hierarchie projektů — PROJECT-RELATIONS-01-C

`ProjectRelationResolver` v
[`spikes/project_relation_resolver.py`](../spikes/project_relation_resolver.py)
přidává místní čtení vlastních dat a dat podprojektů přes schválené `parent_of`.
Navazuje na [lifecycle B](project-relations-lifecycle.md),
[model vztahů](project-relations-contract.md) a
[ADR 0089](adr/0089-project-relations-and-derived-read-access.md).
Jde o nativní Python API pro pozdější společné použití v aplikaci. Zapojení
UI, hledání a Context Manifestu zůstává E/F; C neodesílá data providerovi.
Tento dokument zachycuje řez C. Společný resolver nyní rozšiřuje
[výstupový pohled D](project-relations-outputs.md) o `depends_on`/`relates_to`;
tyto hrany nejsou další cestou k interním datům.

Zadání: Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
export `6df4f1fdb20310a328a5ac40166e0f1debcccfcd46f55b102b646562c663892c`,
Workspace HEAD `3e8a6338d681b562ba4929120d636dca22366523`;
zdrojový základ `f75e34f2ed809b4fad53d2cbc46daabf15c81923`.
Tento záznam identifikuje implementační rozsah C, neudržuje nový živý plán.

## API a dostupnost

```python
from spikes.project_relation_resolver import ProjectRelationResolver

resolver = ProjectRelationResolver(node_path, user_id=actor_id)
view = resolver.catalog(parent_id)
# view['sources']: původní projekty, jejich HEAD a alternativní důkazy cest
# view['items']: vlastní i zděděné entity se stabilními project/entity ID

pin = resolver.pin(parent_id, child_id, artifact_id)
result = resolver.read(pin)
assert result['read_only']
raw = result['raw']  # přesné připnuté bajty, bez kopie v rodičově Gitu
```

Každý nový `catalog` objevuje aktuální vlastní artefakty a registry všech
schváleně dosažitelných podprojektů. Vnoření, nové soubory i nové revize se
projeví bez připojování jednotlivých podkladů. Zahrnuté jsou uložené plánovací
dokumenty, původní zdroje včetně binárních souborů, projektové výstupy i
registry úkolů, rizik a dalších entit. Obsah se nekonvertuje ani neextrahuje;
čtení původního PDF/obrázku není tvrzení o fulltextovém pokrytí tohoto formátu.
Node konfigurace, credentials, SQLite, pracovní relace ani neuložené drafty
nepatří do Git snapshotu projektových entit a nejsou součástí výsledku.

Identita řádku je `(source_project_id, artifact_id, commit_id)`. Pole
`artifact_id` v source pinu pojmenovává také UUID entity z projektového
registru; její původní cesta zůstává `registries/<kind>/<UUID>.json`.
Stejné UUID ve dvou projektech se neslučuje. Více cest ke stejnému projektu
vytvoří jeden zdroj a jeden řádek jeho entity, ale zachová alternativní
uspořádané důkazy v `sources[].paths`. `inherited` rozlišuje vlastní a zděděné
zdroje. Resolver poskytuje pouze čtení; návratová data nepřidávají zápisová
práva ani automaticky nevytvářejí lokální kopii.

Směr je výhradně rodič → dítě. Dva rodiče stejného dítěte nezískají touto
cestou obsah druhého rodiče. Vlastní data nesouvisejícího projektu se neobjeví
ani podle společného uživatele, názvu, či společné neorientované komponenty.

Řízené návrhy, souhlasy, odvolání a explicitní share záznamy jsou důkazy
politiky, nikoli běžný obsah katalogu. Reference na třetí projekt se vrací
jako místní řádek `available=false`, `reason=xref-resolution-required`, bez
cizího source pinu. C ji nečte jako původní obsah a nepředává její descriptor
za obsah třetího projektu. Původní XREF resolver nadále vyžaduje vlastní
živou autorizaci původního zdroje; rodičovská vazba ji nevypíná.

## Čtecí právo a hranice

Vstupní recipient musí být aktuálně registrovaný a pro uživatele čitelný.
Aktivní reader/reviewer/editor/project-admin příjemce může číst data
schváleně dosažitelného dítěte bez individuálního členství v něm. To není
členství ani právo dítě spravovat. Každý krok cesty vyžaduje aktuální `active`
revizi a oba místně ověřené souhlasy B. Pending, odvolaná, konfliktní nebo
neověřitelná vazba nic neposkytuje. Omezení přijímání federovaných souhlasů
z B zůstává: samotný synchronizovaný JSON bez ověřené místní autority nestačí.

Explicitní `allowed_projects` omezuje příjemce i všechny navštívené zdroje;
pohled toto request scope nerozšiřuje podle oprávnění globálního node ownera.
Vyloučený projekt ani jeho podstrom nemá ve výsledku názvy, UUID či počty.

Každé volání kontroluje boundary. `local-only` se objeví pouze uvnitř
`same-node`; pro jinou boundary katalog tyto řádky nevrací a nenabízí jejich
počet, pin/read je odmítne. `privacy_filtered` vysvětluje takto vymezený rozsah.
Při čtení historického pinu platí přísnější z původní a nynější klasifikace.
Povolení v tomto čtecím API nenahrazuje externí Context Manifest, RBAC ani
poslední privacy kontrolu před skutečným LLM dispatch v E/F.

## Připnutí a změny zdrojů

Pin `fpw-project-relation-input-v1` váže původní project/entity ID, logickou
repository identitu, plný commit, cestu, SHA-256 obsahu i metadat a privacy.
Autorizace připíná přístupovou revizi příjemce a právě jednu cestu: pořadí
relation UUID/revizí/digestů a oba approval piny každého kroku včetně
projektových commitů. Vlastní zdroj má prázdnou cestu a důvod `project`.

`read(pin)` znovu ověří oprávnění, aktuální cestu a historické doklady. Commity
musí patřit do historie aktuálně registrovaných projektů a obsahovat přesné
připnuté důkazy. Změna zdrojového textu nevymění historické bajty; vrátí se
původní obsah a `newer` s aktuálním source pinem. Smazaná entita už číst nejde,
ani když Git stále obsahuje její starší blob. Změna práv, odvolání vazby nebo
nová nepotvrzená revize zablokují nový read starého pinu.

Volitelné `relation_ids=[...]` při `pin` vybírá konkrétní dostupnou cestu.
Odvolaný pin se automaticky nepřepne na jinou cestu. Nový katalog a nový pin
mohou explicitně použít jiný stále platný důvod; starý záznam se nepřepisuje.
Připnutí a validace C jsou podkladem pro integraci Context Manifestu, nikoli
jejím dokončením.

## Konzistence, limity a obnova

Nevzniká nový persistentní zápis přes více vrstev. Platí crash boundaries
ADR 0089: samostatné projektové commity, lokální journal pro nedokončený
zápis a obnovitelný index. Resolver čte validované snapshoty; existující
Workspace umí obnovit stale index, ale resolver nedokončuje pending intent
za uživatele. Nedokončený zápis, offline zdroj nebo neověřitelný graf znamená
nedostupnost, nikoli úspěšně prázdný pohled či čtení staré cache.

Během sestavení se ověřují konkrétní HEAD a před návratem znovu celý graf,
přístupová revize i efektivní stavy. Změna během čtení vrátí obsahově neutrální
`RelationViewUnavailable`, nikoli částečný úspěch. Není předstírán atomický
snapshot různých Git repozitářů. Čte se vždy uložený commit, ne dirty soubor.

Přehled má limity 16 hran cesty, 1 024 cest včetně vlastní prázdné cesty,
10 000 výsledných entit a 8 MiB serializovaného katalogu; navíc platí limity
grafu B. Překročení vrací `coverage-limit` bez částečného výsledku. `complete`
se vztahuje pouze k deklarované coverage a boundary, nikoli k obsahu cizích
referencí. Původní rozsah C je own/parent_of; D přidává výstupové hrany podle
svého kontraktu. Piny, bajty ani doklady se neukládají do cache nebo rodičova Gitu.

Ověřovací scénáře jsou v
[test_project_relation_resolver.py](../tests/test_project_relation_resolver.py).
Zahrnují skutečné nativní vztahy/souhlasy, vnoření a nové podklady, binární
zdroj a registry, více rodičů/cest, UUID kolize mezi projekty, čtenáře jen
v rodiči, local-only, odvolání, přepsání/smazání zdroje, pending recovery,
změnu během čtení, limity a zákaz cizí reference. GUI a živá LLM/federovaná
akceptace celé dávky patří E–G.
