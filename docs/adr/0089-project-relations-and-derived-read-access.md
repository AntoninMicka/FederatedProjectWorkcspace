<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0089 — Projektové vztahy a odvozený přístup ke zdrojům

Datum: 22. 11. 2026. Úkol **PROJECT-RELATIONS-01-A**.
Stav modelu: **designed**. Nativní místní zápis a lifecycle B popisuje
[implementační kontrakt](../project-relations-lifecycle.md), místní čtení
schválené hierarchie C má [vlastní kontrakt](../project-relations-hierarchy.md).
Výstupový pohled D má [vlastní kontrakt](../project-relations-outputs.md).
Integraci E popisuje [UI kontrakt](../project-relations-ui.md). Bezpečnost,
odvolání a recovery F shrnuje [bezpečnostní kontrakt](../project-relations-security.md).
Pozitivní federovaná delegace souhlasů a živá akceptace celé dávky nejsou
tímto prokázané; neověřené importované souhlasy zůstávají nedostupné.
Cílová úroveň celé dávky je PoC validated.

## Potřeba a změna dosavadního rozhodnutí

[ADR 0070](0070-local-artifact-references.md) a
[ADR 0086](0086-cross-project-artifact-sharing.md) poskytují připnutou referenci
jednoho podkladu. `CrossReferences.authorize` vyžaduje přístup uživatele
k oběma projektům; v2 navíc ověřuje explicitní sdílení konkrétního podkladu.
To neřeší schválené zadání: rodič má používat i budoucí data podprojektů,
závislý projekt publikované výstupy poskytovatele a související projekty
výstupy obousměrně, bez ručního připojení každého souboru a jednotlivých
uživatelů ke každému zdroji.

Rozšiřujeme proto důvody **čtecí** dostupnosti o schválenou projektovou
vazbu. Neměníme pravidla existujících referencí v1/v2, nevytváříme z nich
automaticky projektové vztahy a nepřepisujeme jejich historické piny.
Nová větev autorizace musí mít vlastní důkaz vztahové cesty; nelze prostě
vypnout `authorize(source)` nebo vyrábět jednotlivé share záznamy na pozadí.

## Rozhodnutí

Normativní model, orientace, tabulka případů a příklad záznamu jsou v
[kontraktu projektových vztahů](../project-relations-contract.md).

- `parent_of(parent, child)`: data tečou z dítěte do rodiče, včetně dalších
  úrovní podprojektů a nových projektových artefaktů.
- `depends_on(consumer, provider)`: poskytovatel nabízí příjemci pouze
  publikované vlastní výstupy.
- `relates_to(left, right)`: oba projekty poskytují druhému pouze publikované
  vlastní výstupy. Dvojice je kanonicky seřazená; dvě zrcadlové vazby nevznikají.
- Přenos přes další hrany zachovává nejužší rozsah celé cesty. Jakmile cesta
  obsahuje hranu `outputs`, další hierarchie ji nerozšíří na interní data.
  Souhlas s vazbou zahrnuje tuto pojmenovanou transitivní politiku a její dopad.
- Více rodičů je povoleno. Sebevazby, významové duplicity a cykly hierarchie
  a závislostí se odmítají; symetrická souvislost není závislostní cyklus.
- UUID vztahu a dvojice jeho projektů jsou stabilní. Jediný autoritativní
  záznam má určený vlastnický projekt, druhý konec potvrzuje přesnou revizi.
  Nepotvrzená či konfliktní revize nezpřístupňuje obsah.
- Projektová vazba neposkytuje zápis do zdroje, správu členů, credentials,
  lokální journal ani oprávnění k synchronizaci zdrojových bajtů na nový uzel.
  Odvozené čtení mají aktivní role reader/reviewer/editor/project-admin
  příjemce, v průniku s rozsahem requestu, privacy a trust boundary.
  Souhlasy spravuje projektový správce nebo oprávněný správce uzlu;
  editor příjemce sám nemůže zpřístupnit cizí projekt.
- Živý přehled objevuje nové zdroje. Každé skutečné použití připne původní
  project/artifact ID, commit, obsah, metadata i důkaz cesty. Context Manifest
  před odesláním znovu ověří oprávnění, zdroj a všechny vztahové revize.

Explicitní v2 sdílení z ADR 0086 a odvozený vztah jsou samostatné důvody
přístupu. Zrušení jednoho nezruší jiný platný důvod. Důvod, který byl
odvolán, se však nesmí potichu nahradit jiným v již připraveném manifestu;
nové použití vyžaduje nově sestavený a schválený kontext.

## Autority a crash boundaries pro navazující implementaci

Platí [ADR 0003](0003-coordinated-operation.md) a
[ADR 0081](0081-complete-project-data-sync.md). Projektové registry jsou v Gitu;
projektové SQLite indexy jsou obnovitelné projekce. Lokální journal řídí
nedokončenou operaci a nesynchronizuje se. Nezavádíme distribuovaný commit.

| Hranice | Požadované chování B/F |
| --- | --- |
| Náhled před intentem | Bez zápisu; váže oba HEAD, úplnou revizi vztahu, politiku a dopad na dosažitelnost. |
| Intent / Git commit vlastnického projektu | Původní Workspace journal a CAS; bez potvrzení druhého konce žádné nové čtení. |
| První commit bez druhého | Viditelné `pending`, nikoli úspěšně aktivní vztah. Recovery používá původní operation ID, digest a schválené bajty. |
| Druhý souhlas / ztracená odpověď | Aktivní jen přesná shoda obou souhlasů s aktuální vlastnickou revizí; receipts brání duplicitě. |
| Odvolání jen na jednom konci | Jakmile je aktuálně zjištěné, stačí k zákazu cesty. Dostupná starší replika druhého konce ho nesmí oživit. |
| Změna typu nebo směru | Nová revize a nové dva souhlasy; stará revize se nejprve vyřadí. Neúplný přechod znamená dočasně nedostupnou vazbu, ne širší přístup. |
| Commit / index / restart | Index se obnoví z příslušného HEAD; nemůže nahradit chybějící souhlas nebo rozhodovat o nedokončeném intentu. |
| Offline, neznámá nebo konfliktní revize | Bez nového použití v LLM a bez odvozování nových práv z cache; diagnostika neprozradí nepovolené názvy. |

Jednotlivé zámky se nesmějí držet přes čekání na druhý projekt či síť.
Budoucí B/F musí doložit souběh, změnu práv, pád na každé hraně a přesný replay.
Tento návrhový řez žádný nový persistentní zápis vztahu neimplementuje.

## Reuse a předání

Reuse/adapt: `Projects`, `CrossReferences`, `reference_schema`,
`ArtifactSharing`, `Administration`, Workspace writer/journal, validace
snapshotů a Context Manifest. Přehled musí řešit skutečný zdroj, nikoli
řetězit textové deskriptory referencí nebo kopírovat cizí obsah do indexu.
Nová dávka vyžaduje typovaný projektový registr a větev odvozené autorizace;
existující share schema ani task graph nejsou jejich náhradou.
Externí implementace není pro návrh potřeba.

A dodává tento kontrakt k review. B implementuje nativní lifecycle,
C/D dostupnost dat/výstupů, E UI a integraci hledání, F bezpečnost a recovery,
G skutečné integrační testy a lidskou akceptaci. Není tím aktivována samostatná
dávka PROJECT-SEARCH-01 ani automaticky dokončen některý Workspace úkol.

## Doplnění F — 27. 11. 2026: známá historie souhlasů a revokací

Konkrétní adversariální test ukázal, že pouhý návrat lokálního HEAD na commit
před odvoláním dokázal obnovit starou aktivní projekci: původní souhlasy byly
stále v jeho historii. Nestačí proto kontrolovat jen důkazy přítomné v právě
čteném snapshotu. Nativní receipt už v B prokazuje místní udělení souhlasu;
F používá stejnou místní evidenci také k zákazu návratu před známé rozhodnutí.

`ProjectRelations._scan` nyní vyžaduje, aby všechny hotové místní operace
s interním `relation_lifecycle` receipt a commit ID patřily do historie
aktuálního HEAD příslušného projektu. Stejná kontrola platí uvnitř native
writeru při přípravě další operace. Starší nebo divergující větev nesmí
skrýt známé odvolání, novou revizi ani souhlas. Nejde o porovnání ancestry
zdrojového programu; týká se výhradně projektových vztahových dokladů.

Chybějící známá historie znamená nedostupný vztahový pohled. Obnova vyžaduje
vrátit či sémanticky sloučit příslušnou projektovou historii, nikoli smazat
journal nebo přegenerovat souhlasy z indexu. Index nadále zůstává projekcí;
žádná nová databáze ani synchronizace journalu se nezavádí. Pending intent
řídí původní recovery; do této kontroly vstupují jen hotové nativní operace.

Uzel bez těchto místních dokladů nezískává grant z pouhých Git kopií JSON.
Bez pozitivně ověřené federované autority zůstává taková vazba nedostupná.
To neprokazuje globální aktuálnost revokace, kterou daný uzel nikdy neviděl;
pozitivní federovaná delegace stále vyžaduje definovaný důkaz autority a
aktuálnosti podle [bezpečnostního kontraktu F](../project-relations-security.md).
