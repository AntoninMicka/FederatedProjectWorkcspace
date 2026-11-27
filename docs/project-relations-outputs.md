<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Publikované výstupy propojených projektů — PROJECT-RELATIONS-01-D

Společný `ProjectRelationResolver` rozšiřuje [čtení hierarchie C](project-relations-hierarchy.md)
o výstupy přes `depends_on` a obousměrné `relates_to`. Používá
[model A](project-relations-contract.md), [lifecycle B](project-relations-lifecycle.md)
a původní explicitní publikaci `purpose: output` z
[ADR 0086](adr/0086-cross-project-artifact-sharing.md). UI, hledání a skutečné
sestavení/dispatch Context Manifestu navazují v E/F. Implementaci UI a
výslovných vstupů E popisuje [UI vztahů](project-relations-ui.md).

Zadání D: Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, export
`1f5b928c3217d8c068310df4d2d17bd9dbe5484a472893ce08d3408795056839`,
Workspace HEAD `f8bbcec5fad21878627623e4544c2f473c621815`;
zdrojový základ `f77fa3d`. Jde o identifikaci zadání, nikoli nový živý plán.

## Co je publikovaný výstup

Publikace je platné, neodvolané prohlášení `fpw-artifact-share-v1` s
`purpose: output`, které editor/správce zdroje **výslovně potvrdil** přes
původní `CrossReferences.share_write(..., confirm=True)`. Samotný název,
tag, uložená modelová odpověď ani genericky importovaný JSON nestačí.
Nativní confirmation je redakční přijetí dokumentu k publikaci. Nepotvrzený
náhled nic nezpřístupňuje. Pro publikaci neexistuje druhý writer ani tabulka.

Čtecí helper [project_output_publication.py](../spikes/project_output_publication.py)
ověří hotový místní receipt, přesné bajty původního prohlášení a jeho metadata,
příslušnost commitu do historie zdroje a request digest původního nativního
potvrzení. Request se rekonstruuje z původního commitu, takže receipt
obecného importu nelze zaměnit za potvrzení publikace. Soukromé názvy či cíle
z původní deklarace se do výsledku neexportují; proof obsahuje identitu,
commit a otisky. Stejně jako u vztahů B samotné synchronizované JSON bez
místně ověřitelné autority zatím nestačí. Federation authority náleží F.

Prohlášení musí jmenovat existující vlastní artefakt; reference, vztahové a
share záznamy ani pouhé registry nejsou publikací cizího obsahu. U modelového
chat výstupu se navíc kontroluje zachovaná provenance `fpw-chat-output-v1`:
všechny vybrané turns musí být `completed` bez chyby. Failed, unknown,
neúplná či nečitelná chat provenance nevyhoví ani přes prohlášení output.
Jiné dokumenty a modelové podklady vyžadují stejné výslovné redakční potvrzení;
resolver jejich přijetí neodvozuje z úspěšného dokončení modelového běhu.

Jedno potvrzení publikace platí pro identitu artefaktu a jeho aktuální
uložené revize, nikoli pro každý jednotlivý přijímající projekt. Nové uložené
revize zachovávají označení, dokud je aktivní prohlášení; neuložený draft
se nečte. Dočasné stažení výstupu vyžaduje odvolání jeho prohlášení.
Nový artefakt musí být ve zdroji vědomě prohlášen za výstup. V příjemci se
žádné soubory nepřipojují a žádné kopie či reference se nevyrábějí na pozadí.

## Směry a transitivní limit

| Vztah | Příjemce → poskytovatel | Dostupný rozsah |
| --- | --- | --- |
| `parent_of(A, B)` | A → B | data B |
| `depends_on(D, E)` | D → E | publikované vlastní výstupy E |
| `relates_to(E, F)` | E → F a F → E | publikované vlastní výstupy druhé strany |

Jakmile cesta obsahuje závislost nebo souvislost, její zbývající rozsah je
`outputs`. Pozdější rodičovská hrana jej nerozšíří zpět na `data`.
`D depends_on E; E parent_of F` poskytne D pouze publikované výstupy E/F.
`D depends_on E; E relates_to F` poskytne výstupy E/F, nikoli interní podklady.
Symetrické cykly souvislostí jsou očekávané: průchod neopakuje projekt na
jedné cestě a nepoužívá cyklus k rozšíření rozsahu. Alternativní jednoduché
cesty i jejich limity zůstávají oddělené a platí bounded limity katalogu C.

Dvojí dosažení zdroje s limity data/outputs neslučuje práva do širší cesty.
Katalog vrátí jeden řádek s jeho skutečnými `scopes`. Zdroje nesou obě cesty;
pro nepublikovaný interní artefakt ale existuje pouze datový důvod.
Výslovný výběr užší cesty nemůže použít oprávnění jiné širší cesty.

`targets` deklarace stále omezuje původní explicitní XREF. Projektový vztah
je samostatný, oběma konci schválený důvod: může zpřístupnit publikovaný výstup,
i když jeho původní prohlášení nabízelo výstup jinému cíli. Kontrola cíle
explicitního XREF se tím nevypíná a interní podklad s `purpose: share` není
publikovaný výstup pro vztahovou větev.

## API a připnutá historie

Používá se stejné `catalog`, `pin` a `read` jako u C:

```python
from spikes.project_relation_resolver import ProjectRelationResolver

resolver = ProjectRelationResolver(node_path, user_id=actor_id)
view = resolver.catalog(consumer_id)
pin = resolver.pin(consumer_id, provider_id, published_artifact_id)
assert pin['authorization']['scope'] == 'outputs'
result = resolver.read(pin)
```

Katalog nyní deklaruje `coverage=['own', 'parent_of', 'depends_on', 'relates_to']`.
Obsahuje vlastní data, hierarchicky dostupná data a publikované výstupy
ostatních poskytovatelů. Neprozrazuje názvy, UUID ani počty jejich interních
artefaktů. Názvy samotných projektů a důkazy schválených cest jsou dostupné
podle schválené vztahové politiky. Další oddělené rodiny nemají společný obsah.

Datové piny C zůstávají `fpw-project-relation-input-v1`. Výstupové piny mají
novou verzi `fpw-project-relation-input-v2`, scope `outputs` a navíc přesný
`publication` proof: source project/artifact ID, share ID, originator,
operation ID, plný commit původního potvrzení a SHA-256 deklarace. Starý
reader musí novou verzi odmítnout, nikoli ignorovat publikační důkaz.

Každé čtení ověří aktuální vztahovou cestu i **stejné** dosud aktivní
prohlášení. Nepoužije jinou publikaci nebo širší cestu automaticky.
Odvolání posledního aktivního output prohlášení odstraní výstup z pohledu,
ikoli z Gitu zdroje. Má-li artefakt jiné platné prohlášení, nový katalog jej
stále nabídne; použití potřebuje nový pin s novým důvodem.

Zdrojový commit pinu musí být potomkem příslušného nativního potvrzení:
starší nepřijatý draft nelze podvrhnout jako již publikovanou revizi.
Změna zdroje nepřepisuje historické bajty: starý pin vrací původní obsah
s nabídkou `newer`; nový pin používá aktuální commit. Smazání zdroje, zánik
způsobilosti, revokace, změna práv a boundary se kontrolují živě, stejně jako C.

## Obnova a ověření

Platí beze změny crash boundaries ADR 0086/0089. Potvrzení publikace je jediná
původní projektová Workspace transakce. Před commitem není nový grant; pending
intent blokuje čtení. Recovery dokončí původní schválené bajty a receipt.
Ztracená odpověď neznamená nové potvrzení s novým operation ID. Čtení samo
žádný intent nedokončuje a nepoužívá starou cache.

Kontroly publikace mají navíc limit 64 native receipts obsahujících cestu
jednoho share. Překročení odmítne katalog, nikoli neúplné vydání za úplné.
Nejde o distribuovaný snapshot. Pohyb HEAD během čtení se odmítá existující
kontrolou konzistence C. Nevzniká nové úložiště ani kopie journalu.

[Testy D](../tests/test_project_relation_outputs.py) pokrývají směry, symetrii
a cykly, mix s hierarchií, nové publikace bez připojení u příjemce, alternativní
cesty, dvojí prohlášení/revokaci, historické piny, generický podvržený JSON,
modelové drafty/failed/unknown, skutečný nativní chatový publication flow,
pending/recovery a local-only. Regrese C a původního XREF se ověřují odděleně.
Živá UI/LLM/federovaná akceptace a závěrečná sada celé dávky zůstávají E–G.
