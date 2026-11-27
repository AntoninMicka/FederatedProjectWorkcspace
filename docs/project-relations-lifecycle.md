<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Nativní lifecycle projektových vztahů — PROJECT-RELATIONS-01-B

Nativní Python služba `ProjectRelations` v
[`spikes/project_relations.py`](../spikes/project_relations.py) implementuje
místní návrh, potvrzení, změnu typu/směru a odvolání vztahu podle
[ADR 0089](adr/0089-project-relations-and-derived-read-access.md) a
[modelového kontraktu](project-relations-contract.md). B neimplementuje
čtení cizího obsahu ani UI; odvozený resolver a federation authority patří
navazujícím řezům C–F. Souhlas autorizuje politiku `typed-paths-v1`, nikoli
jednotlivé per-artifact shares. Žádné share záznamy se nevyrábějí na pozadí.
Místní čtení schválených podprojektů nyní dodává samostatný
[resolver C](project-relations-hierarchy.md); federované ověření a UI zůstávají
navazujícími řezy.

Zadání B: Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
export `6df4f1fdb20310a328a5ac40166e0f1debcccfcd46f55b102b646562c663892c`,
projektový HEAD `3e8a6338d681b562ba4929120d636dca22366523`;
zdrojový základ `00dc92b`. Jde o identifikaci zadání, nikoli konkurenční plán.

## Použití nativní služby

Všechny tři kroky mají vlastní náhled a explicitní potvrzení. Volající
zobrazí `preview.impact` a uchová celý přesný náhled, jeho digest a operation
UUID pro případ nejistého výsledku. UUID z příkladu se nenahrazují názvy.

```python
from uuid import uuid4
from spikes.project_relations import ProjectRelations

service = ProjectRelations(node_path, user_id=actor_id)
proposal = service.proposal_preview(parent_id, child_id, 'parent_of', 'Společný projekt')
# Po review tohoto přesného náhledu:
service.confirm(proposal['preview'], proposal['sha256'], str(uuid4()), confirm=True)
relation = proposal['preview']['record']
owner = relation['owner_project_id']
relation_id = relation['id']

# Dva auditovatelné souhlasy, každý pod správou příslušného projektu.
for endpoint in (parent_id, child_id):
    operation_id = str(uuid4())
    approval = service.evidence_preview(owner, relation_id, endpoint, operation_id)
    # Po review; lze také použít jiného správce pro každý konec.
    service.confirm(approval['preview'], approval['sha256'], operation_id, confirm=True)

assert service.view(owner, relation_id)['state'] == 'active'
```

Vytvoření nebo změna návrhu vyžaduje aktuální správu obou konců. Reader,
reviewer ani editor nemůže udělit souhlas. Následné souhlasy mohou dát dva
různí správci, každý pro svůj konec; stejný správce může spravovat oba.
Odvolání jedním správcem vlastního konce stačí k zákazu vazby. Autorizace
respektuje aktivní účet, projektovou registraci i omezení request scope;
před přípravou intentu se znovu ověřuje. Node owner a explicitní správci
uzlu používají existující pravidla `Administration`.

Změna používá `proposal_preview(..., relation_id=relation_id)`: dvojice
projektů, vlastník, původce a čas vzniku zůstávají stabilní; revize roste
právě o jednu. Lze obrátit směr a změnit typ nebo důvod. Stará revize přestane
platit už commitem nového návrhu; oba nové souhlasy jsou nutné znovu.

Odstranění vazby je auditované odvolání, nikoli smazání důkazů:

```python
operation_id = str(uuid4())
revocation = service.evidence_preview(owner, relation_id, parent_id, operation_id,
                                      revoke=True, reason='Spolupráce skončila')
# Po review náhledu:
service.confirm(revocation['preview'], revocation['sha256'], operation_id, confirm=True)
assert service.view(owner, relation_id)['state'] == 'revoked'
```

Odvolat lze i dosud nepotvrzený návrh. Revoked revizi nelze znovu schválit;
nová spolupráce potřebuje novou revizi a nové souhlasy.

## Registry, náhled a ochrana

Vlastnický projekt ukládá `artifacts/<relation UUID>/relation.json`; předchozí
návrhy zůstávají v Git historii. Souhlas a odvolání jsou samostatné neměnné
artefakty `relation.json` v potvrzujícím projektu. Jejich UUID je UUIDv5
z relation UUID a řetězce `<revision>:<project UUID>:approval|revocation`.
Metadata mají stejné ID, schema tag, soukromí nejméně `project` a druh
`document`. Odvolání jmenuje konkrétní approval ID i digest návrhu.

Validátory snapshotů odmítají neznámé verze, politiku, podvržený stav active,
netypovanou revizi, nekánonický obsah i rozpor mezi sidecarem a metadaty.
Přechod chrání identitu, přírůstek revize a neměnné důkazy. Obecné nativní
zápisy, import a merge nedostanou interní capability lifecycle; změna
řízených záznamů se odmítne ještě před intentem. Záznamy nejsou běžné
katalogové dokumenty a XREF je nesmí sdílet jako podklady.

Aktivitu neurčuje JSON autora ani Git email. Každý místní souhlas musí mít
hotový receipt nativního relation lifecycle, správný operation ID, totožné
bajty v jeho commitu a tento commit v historii aktuálního HEAD. Oba souhlasy
musí mířit na aktuální digest návrhu. Přijaté vztahové souhlasy ze sítě zatím
bez této místní autority zůstávají `unavailable`; journal se nekopíruje.
Navazující [bezpečnostní kontrakt F](project-relations-security.md) vymezuje
podmínky federované autority a ověřuje tento zákaz na druhém uzlu. Pozitivní
federovaná delegace bez místního receipt implementovaná není; obyčejný
importovaný JSON ani podpis přenosu se za projektový grant nepovažuje.

Náhled ukazuje odebrané a potenciálně nově dostupné směrované cesty s limitem
`data`/`outputs`; není to načtení artefaktů ani seznam jejich bajtů. Zahrnuje
budoucí zdroje a transitivní politiku. Nejužší rozsah cesty zůstává zachovaný.
Výsledek obsahuje pouze projekty, které smí volající číst; neviditelné názvy
ani ID se neexportují. Úplná interní mapa HEAD se váže jedním digestem;
náhled obsahuje pouze viditelné piny.

Validace má limit 128 registrovaných projektů a 4 096 řízených záznamů.
Neúplný, rozpracovaný nebo nedostupný graf neumožní nový zápis. Každá mutace
váže aktuální registrovaný graf a všechny jeho HEAD; i nesouvisející změna
HEAD může konzervativně vyžadovat nový náhled. Duplicitní aktivní hrany,
sebevazby a hierarchické, závislostní i smíšené strukturální cykly jsou
odmítnuté. Více rodičů a symetrické `relates_to` jsou podporované. Aktivní
projekce kontroluje graf znovu a konfliktní strukturální komponentu označí
`conflict`; nevybírá vítěze ani nemaže historii.

## Crash boundaries a obnova

B používá hranice ADR 0089 beze změny. Každý zápis má původní Workspace
CAS, serializaci, journal, receipt a obnovitelný index. Žádný zámek není
držen přes síť nebo lidské potvrzení druhého konce. Čtení ostatních projektů
při validaci používá neblokující sdílené zámky; souběžný writer vyžaduje
nový pokus po načtení aktuálního stavu, nikoli čekání se dvěma writer zámky.

- Před `prepared`: žádný nový grant; neplatný/stale náhled se nezapíše.
- Po `prepared`, před Git ref: intent vlastní přesné schválené bajty.
  Explicitní recovery/same-operation retry používá tento intent, nikoli
  nový náhled nebo nová UUID. Souhlas je závazně udělen při přípravě intentu.
- Po Git ref, před indexem/receiptem: obnova dokončí tentýž commit a projekci;
  nepořizuje další souhlas ani neduplikuje první projektový zápis.
- Mezi návrhem a souhlasy: `pending`; neexistuje atomický commit obou projektů.
- Po novém návrhu bez obou souhlasů: `pending`, starší souhlasy neplatí.
- Po jednostranném odvolání: `revoked`; replay starého receipt nic neoživí.
- Po ztracené odpovědi: stejný náhled a operation ID vrátí původní receipt.
  Změněný request se stejným operation ID se odmítne. Automatický retry není.

Testy [test_project_relations.py](../tests/test_project_relations.py) zahrnují
průchod lifecycle, oprávnění a jejich odvolání, stale HEAD druhého konce,
replay, duplicitní/smíšené cykly, více rodičů a output limit. Obnova se
ověřuje na deseti checkpoints nativního writeru i skutečným `os._exit`
v samostatném procesu před ref a po ref. Regrese XREF/Workspace se ověřují
odděleně. B nedokládá běh UI, sdílení obsahu C/D, federovanou akceptaci ani
splnění celé dávky G.

F navíc kontroluje, že aktuální HEAD obsahuje historii všech místně známých
hotových nativních vztahových operací. Návrat na starší větev nesmí skrýt již
známé odvolání. Při nesouladu se vrací nedostupnost; řešením je zachovat a
obnovit/sloučit projektovou historii, nikoli smazat journal. Viz doplnění ADR 0089.
