<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Kontrakt projektových vztahů — PROJECT-RELATIONS-01-A

**Designed, k review; dosud bez runtime implementace.** Rozhodnutí a hranice
obnovy: [ADR 0089](adr/0089-project-relations-and-derived-read-access.md).
Kanonický rozsah drží Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
exportní revize `52283563eac876420c6d0841d06530c2eaafe815ff6819a9b8af06449f363e45`,
projektový HEAD `53c668738cfdce9a3311b2f6261799249729f9ae`.
Zdrojový základ návrhu: `193c74d6ca3984f5c3b7aef1e10df92c57e707c9`.
Tyto hodnoty identifikují zadání A, nikoli druhý živý plán.

## Identita a orientace

Vztah má vlastní UUID, autoritativní `owner_project_id`, dva project UUID,
typ, orientaci, revizi, původce, důvod, časy a historii životního cyklu.
Repozitář projektu se identifikuje stejně jako u referencí logickou identitou
`fpw-project-git:<project UUID>`; nikoli cestou či credentialed URL.

| Typ | `source_project_id` | `target_project_id` | Směr čtení příjemce → zdroj | Rozsah |
| --- | --- | --- | --- | --- |
| `parent_of` | rodič | dítě | rodič → dítě | `data` |
| `depends_on` | závislý příjemce | poskytovatel | příjemce → poskytovatel | `outputs` |
| `relates_to` | menší UUID dvojice | větší UUID dvojice | oba směry | `outputs` |

Směr šipky v navigaci není směr toku bajtů: rodič čte dítě, poskytovatel
dodává výstupy závislému projektu. UI musí tyto role pojmenovat, ne nabídnout
jen neoznačenou šipku. Rodičovská vazba sama neposkytuje dítěti data rodiče.

`data` znamená vlastní Git-backed projektové artefakty včetně podkladů,
plánovacích dokumentů a výstupů. Staví nad nimi read-only pohled; nenahrazuje
autoritativní projekt ani jeho plán. Řídicí záznamy vztahů/sdílení se používají
jen jako ověřené důkazy politiky, nikoli běžné automatické promptové vstupy.
Node konfigurace, credentials, indexy, pracovní relace, cache a journals
do rozsahu nepatří. Cizí reference v podprojektu nepropůjčuje právo k jejímu
zdroji: ten se musí vyřešit a samostatně autorizovat původním resolverem.

`outputs` je podmnožina `data`: vlastní artefakt s aktivním, validním
prohlášením `purpose: output` podle ADR 0086. Název, tag „výstup“, existence
souboru ani dokončení modelového běhu samy publikací nejsou. Nepublikovaný
draft a failed/unknown nebo dosud nepřijatý modelový návrh se za publikovaný
výstup nepovažují. Navazující D musí použít důkaz potvrzené publikace,
nikoli přejmenovat všechny uložené odpovědi na výstupy.

Stávající `targets` share záznamu nadále omezuje explicitní sdílení tohoto
záznamu. Nová vztahová autorizace je samostatná: souhlas s `outputs` zahrnuje
všechny způsobilé vlastní výstupy, i dříve publikované jinému cíli. Náhled
vztahu tento dopad ukáže. Odvolání posledního aktivního prohlášení `output`
odebere artefakt z výstupového pohledu, i když soubor zůstává v projektu;
jiné platné prohlášení může publikaci nadále doložit.

## Transitní politika a více cest

Každý souhlas výslovně váže politiku `typed-paths-v1`: obsah smí pokračovat
přes schválené vztahové cesty podle této tabulky. Náhled musí vysvětlit,
že se tím povolují i budoucí podprojekty/výstupy a oprávnění příjemci na
takové cestě. Bez souhlasu s touto delegací je vazba pouze `pending`.
Neodvozuje se členství uživatele ve zdrojovém projektu.

Resolver vychází z příjemce, k němuž má uživatel aktuální právo čtení.
Po hraně `parent_of` postupuje k dítěti s limitem `data`, po `depends_on`
k poskytovateli s limitem `outputs`, po `relates_to` k druhému konci
s limitem `outputs`. Efektivní limit je průnik limitů celé cesty:
`data ∩ outputs = outputs`. Rozsah se tedy nikdy po cestě nerozšiřuje.
Každý krok vyžaduje aktuální souhlasy, dosažitelné registrované projekty,
povolený rozsah requestu a dodržení privacy/trust boundary.

Obcházení neznamená získat všechny projekty jedné neorientované komponenty.
Navštívené stavy jsou `(project_id, limit)`; `data` a `outputs` nelze sloučit
tak, že širší cesta později umožní interní data přes užší cestu. Pro výsledek
musí existovat alespoň jedna úplná cesta opravňující konkrétní rozsah.
Omezení počtu uzlů/hran nebo neúplná viditelnost nesmí vrátit „úplný“ výsledek
či přijmout mutaci s neověřenou acykličností; navazující implementace musí
ohlásit bounded neúplnost a mutaci odmítnout.

| Aktivní vztahy / požadavek | Výsledek |
| --- | --- |
| A rodič B, B rodič C; čtení v A | vlastní data B a C, včetně nových souborů; bez jejich kopírování |
| Stejná hierarchie; čtení v C | žádná data A/B pouze z rodičovské vazby |
| A i X rodiče B | A a X mohou číst B; A nemá automaticky data X ani X data A |
| D závisí na E, E souvisí s F; čtení v D | publikované vlastní výstupy E/F přes doložené cesty, nikoli jejich interní podklady |
| D závisí na E, E rodič F; čtení v D | pouze publikované vlastní výstupy E/F; hierarchie neobnoví limit `data` |
| E souvisí s F; čtení v E nebo F | publikované výstupy druhé strany, nikoli interní podklady |
| D závisí na E; čtení v E | žádné výstupy D jen na základě této závislosti |
| A → B → C a A → X → C v hierarchii | jeden výsledek C s více ověřenými důvody dostupnosti |
| C je dostupné přes dvě cesty; jedna odvolána | nová čtení mohou použít druhou platnou cestu; starý manifest se nepřepisuje |
| Zdroj U bez schválené směrované cesty | nedostupný; společný uživatel nebo slovo „související“ v popisu nestačí |

Identita výsledku je `(source_project_id, artifact_id, commit_id)`; pro aktuální
pohled je u každého zdroje zvolen jediný validovaný snapshot. Deduplikace
zachová alternativní důkazy dostupnosti, nikoli duplicitní soubory. Stejné
artifact UUID ve dvou projektech nejsou jeden výsledek. Změna zdrojového HEAD
při sestavení pohledu vyžaduje konzistentní nové ověření; neexistuje společný
atomický snapshot více Git repozitářů.

## Kanonický návrh záznamu a souhlasů

Nový řízený artefakt `relation.json`, schema `fpw-project-relation-v1`,
navržený pro B; A jej neregistruje do runtime validátorů. Metadata artefaktu
mají stejné `id` a tag schema. `owner_project_id` je při vzniku deterministicky
menší UUID dvojice bez ohledu na směr a zůstává neměnné. To neuděluje jeho
správci právo jednat za druhý projekt. Návrh aktuální vlastnické revize:

```json
{
  "schema": "fpw-project-relation-v1",
  "id": "33333333-3333-4333-8333-333333333333",
  "owner_project_id": "11111111-1111-4111-8111-111111111111",
  "source_project_id": "11111111-1111-4111-8111-111111111111",
  "target_project_id": "22222222-2222-4222-8222-222222222222",
  "type": "parent_of",
  "revision": 1,
  "policy": "typed-paths-v1",
  "originator_id": "44444444-4444-4444-8444-444444444444",
  "updated_by": "44444444-4444-4444-8444-444444444444",
  "reason": "Podprojekt dodává inventář nadřízenému projektu.",
  "created_at": "2026-11-22T09:00:00Z",
  "updated_at": "2026-11-22T09:00:00Z",
  "state": "proposed"
}
```

Časy jsou UTC RFC 3339, revize kladné celé číslo, důvod 1–1 000 znaků bez NUL.
`updated_by` identifikuje autora konkrétní revize; při vzniku je shodný
s původcem. Pole návrhu `state` smí být jen `proposed`: aktivita i odvolání
se odvozují z dokladů, nikoli přepsáním tohoto pole.
Kanonický otisk je SHA-256 UTF-8 JSON se seřazenými klíči podle stávajícího
`reference_schema`/reporting encoderu. Neznámé schema nebo politika se odmítá
podle ADR 0085; nesmí tiše přejít na slabší v1/v2 grant.

Každý konec uloží přes nativní lifecycle chráněné potvrzení obsahující
`relation_id`, `owner_project_id`, `revision`, `proposal_sha256`, potvrzující
`project_id`, `approved_by`, `approved_at` a stabilní `operation_id`.
Vlastnický návrh tedy není současně souhlasem druhé strany.
Jeden správce s oprávněním k oběma koncům může schválit oba kroky, ale pořád
jako dvě auditovatelné projektové transakce. Autor UUID v obyčejném JSON
ani podpis Git autora sám o sobě nenahrazuje autorizované schválení.
B/F musí chránit řízené záznamy i před obejitím přes generický editor/import
a u přijímané historie ověřit autoritu projektové větve podle federation trust.

Souhlas je neměnný; odvolání je nový trvalý řízený záznam s identitou
schválení/revize, autorem, časem a důvodem. Souhlasy a odvolání se nemažou.
Souhlas/odvolání na druhém konci není druhá autoritativní definice vztahu;
je dokladem souhlasu s otiskem jediné vlastnické definice.

Efektivní stav se **odvozuje**, nečte se z podvrhnutelného `state: active`:

| Efektivní stav | Podmínka |
| --- | --- |
| `pending` | validní proposed revize; jeden nebo oba přesné souhlasy ještě chybí |
| `active` | aktuální proposed revize a oba platné autorizované souhlasy pro tentýž digest; žádné odvolání |
| `revoked` | kterýkoli konec odvolal danou revizi |
| `superseded` | historickou revizi nahradil vlastník novější platnou definicí; staré souhlasy již neopravňují čtení |
| `conflict` | neslučitelné definice/revize, neplatná historie, duplicitní aktivní vztahy nebo neověřitelná autorita |
| `unavailable` | nejde právě ověřit oba registry; nepředstavuje aktivní grant |

Stejné relation UUID nemůže přejít na jinou dvojici projektů ani změnit původce
a created_at. Změna typu, směru nebo důvodu znamená revizi +1 s novým digestem
a novými dvěma souhlasy. Před aktivací náhrady se stará revize vyřadí;
historie zůstává. Revoked revize je konečná, její souhlas nelze replayem oživit.
Nová revize může vzniknout jako nový návrh a musí znovu získat oba souhlasy.

## Validace grafu, souběh a oprávnění

Významový klíč je `(type, source_project_id, target_project_id)`;
`relates_to` má nejprve kanonicky seřazené konce. Pro jeden takový klíč nesmějí
být dvě aktivní relation UUID. Shodný synchronizovaný záznam ve více replikách
se naopak deduplikuje podle identity, revize a hashe, nepočítá se jako další hrana.
Sebevazba se odmítá u všech typů.

Aktivní hierarchie musí být DAG. Aktivní závislosti musí být DAG. Pro ověření
smíšeného cyklu se testuje také jejich sjednocení orientované jako čtení
(`parent → child`, `consumer → provider`): dvojice různých typů nesmí zakrýt
kruhovou strukturální závislost. Více rodičů DAG neporušuje. `relates_to`
nepatří do tohoto strukturálního testu: je záměrně symetrické a jeho cykly
ukončí deduplikace stavů při čtení.

Náhled, potvrzení obou konců a aktivní projekce musí každý ověřit graf nad
přesnými commit/revision piny. Dvě jednotlivě platné souběžné operace mohou
po spojení vytvořit cyklus nebo duplicitu. Textově čistý merge ani oba
souhlasy proto nestačí: výsledná aktivní projekce se sémanticky zvaliduje
znovu a konfliktní komponenta neposkytne odvozený přístup. Historie se
zachová k opravě, neodstraňuje se libovolně „pozdější“ vazba.

Správu každého konce potvrzuje jeho projektový správce, nebo správce uzlu
s existující explicitní pravomocí pro daný projekt. Odvozené čtení nikdy
nedává pravomoc schválit další vztah. Reader/reviewer/editor/project-admin
příjemce jsou způsobilí pro odvozené read-only použití, pokud zůstávají aktivní
a smí příjemce číst. Uživatelské ACL, request scope, privacy a trust boundary
se ověřují před náhledem, načtením obsahu a LLM dispatch; local-only zůstává
jen same-node. Název nepovoleného projektu ani jeho existence se neodhalují
v diagnostice pro neoprávněného uživatele.

Příjem synchronizovaného registru nepřidává členství, nespouští job ani úkol
a nesmí rozšířit transportní oprávnění. Bez oprávněně dostupného zdroje a
ověřitelných obou konců zůstane vztah nedostupný. Cache/index mohou zrychlit
vyhledání kandidáta, ne rozhodovat o přístupu. Nové LLM použití offline
nepoužije starý souhlas ani cache jako živý důkaz. Detaily invalidace a
náhrobků pro všechny odvozené cesty musí dodat F s reuse ADR 0070/0086.

## Provenance použití a ověřovací případy pro B–G

Každé použití uloží source pin z ADR 0070 a důkaz `authorization_kind:
project-relation` s cílovým projektem, efektivním limitem, uspořádanou cestou
relation ID/revizí/digestů, oběma approval piny včetně projektových commitů
a aktuální revizí oprávnění. Manifest zaznamená vybranou konkrétní cestu.
Přidání nové cesty ani nový zdrojový obsah nepřepíše starý manifest;
odvolaná původní cesta blokuje jeho dispatch do nové přípravy kontextu.
Metadata provenance zůstávají v povolené privacy, nikoli odkryté všem příjemcům.

Kontrakt vyžaduje ověření všech řádků tabulky dostupnosti, zejména:

- dvě rodiny A/B/C a D/E/F bez propojení nemají vzájemný obsah;
- přidání souboru podprojektem nevyžaduje share/attach, výstup vyžaduje publikaci;
- dvojice rodičů a více cest nezpůsobí duplicity či přístup mezi rodiči;
- výstupová cesta zůstane výstupová i přes další hierarchii;
- opačná hierarchy/dependency hrana, self-link a zrcadlové relates duplicity
  se odmítnou; souběh a merge se sémanticky ověřují znovu;
- cizí reference, smazání, odvolání posledního output prohlášení, změna práv,
  unknown schema, offline druhý konec a lokální-only zdroj neposkytnou fallback;
- po každém procesovém pádu je buď původní stav, nedostupný pending/conflict,
  nebo přesně doložená aktivní revize; žádný automatický modelový účinek.

Jde o předané akceptační případy, nikoli hlášení jejich úspěšného provedení.
Nynější runtime dále poskytuje pouze původní explicitní XREF sdílení.
