<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Datový model

## Layout projektového repozitáře

```text
project.json
artifacts/<artifact-id>/document.md
artifacts/<artifact-id>/source.pdf
artifacts/<artifact-id>/metadata.json
registries/<kind>/<entity-id>.json
```

Každý adresář artefaktu obsahuje právě jeden primární soubor. Editovatelný Markdown má frontmatter a nemá metadata.json. Neměnný zdroj libovolného formátu má metadata.json a zůstává bajtově nezměněný. Cesty uvnitř metadat jsou relativní k adresáři artefaktu; absolutní cesty, `..`, symlinky a přístup do `.git` nejsou povoleny.

## Konfigurace projektu a uzlu v1

Spustitelný kontrakt drží `spikes/configuration.py`, rozhodnutí a pravidla verzování [ADR 0004](docs/adr/0004-project-node-config.md). Validátor je read-only a sdílí omezený JSON parser, UUID a UTC timestamp pravidla s artefaktovými metadaty.

Přenositelné `project.json` v kořeni projektového Gitu:

```json
{
  "schema_version": 1,
  "id": "11111111-1111-4111-8111-111111111111",
  "title": "Ukázkový projekt",
  "created_at": "2026-09-09T12:00:00Z",
  "author_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "description": "Volitelný popis"
}
```

Všechna pole kromě `description` jsou povinná. `title` je neprázdný text, `description` text; ID projektu i autora jsou kanonická UUID. Projektové ID zůstává stejné po klonování a přesunu. Lokální cesty, identity uzlů, backend konfigurace ani credentials sem nepatří.

Lokální `node.json`, například `/srv/workspace/node.json`, mimo registrované projekty:

```json
{
  "schema_version": 1,
  "id": "22222222-2222-4222-8222-222222222222",
  "name": "Lokální uzel",
  "identity_credential_ref": "credential:node-key",
  "projects": [
    {
      "project_id": "11111111-1111-4111-8111-111111111111",
      "root": "/srv/workspace/projects/demo",
      "state_dir": "/srv/workspace/state/demo"
    }
  ]
}
```

`identity_credential_ref` je volitelný neprůhledný lokální odkaz, nikoli klíč; formát a limity viz ADR 0004. Ostatní pole jsou povinná; `projects` může být prázdné. `root` a `state_dir` jsou absolutní Linux cesty, napříč všemi vazbami bez překryvů a vnoření i po rozlišení existujících symlinků. `state_dir` je per-project adresář pro Workspace journal/index; nesmí být v žádném registrovaném projektu. Node ID je stabilní při restartu/aktualizaci a nepřenáší se s projektem na jiný uzel.

Obě konfigurace mají limit 64 KiB, maximální JSON hloubku 16 a odmítají duplicity klíčů, neznámá pole/verze a neplatné typy. Verze projektu a uzlu se vyvíjejí nezávisle na artefaktovém schématu. Chybějící konfigurace se negeneruje; neexistuje implicitní migrace z v0 ani downgrade neznámé verze. Budoucí explicitní migrace musí zachovat ID a původní data při selhání, viz ADR 0004.

Ověření konfigurace nepotvrzuje existenci klíče, autentizaci, RBAC ani shodu registrovaného project_id s obsahem repozitáře. Kontrola umístění node.json zná pouze uvedené kořeny; není scannerem secrets v Gitu. Aplikační otevření, bezpečný zápis konfigurace a migrace zůstávají BACKLOG V-08. Stávající Workspace, Index a `check_project` nadále validují jen artefakty/registry, takže staré experimenty bez project.json fungují dál.

## Společná metadata

Spustitelný parser `spikes/metadata.py` přijímá striktní schémata v1 a v2 ve stejném snapshotu. Společná povinná pole: `schema_version` (1 nebo 2), `id` (UUID), `title` (neprázdný text), `kind`, `created_at` (UTC RFC3339), `author_id`, `privacy` (public/project/confidential/local-only), `provenance` (user/external/llm-generated/llm-transformed/snapshot). Sidecar navíc obsahuje `file`. Volitelná pole: description, tags, source_url a relations (typ vztahu + cílové ID). Registry navíc povinně obsahují `status` a `body`; `relations` zůstávají volitelné i u registrů.

`created_at` označuje vznik entity v projektu. U dnešního nativního importu je zároveň časem importu, nikoli doloženým časem vzniku externího díla. `author_id` je projektový aktér, který entitu vytvořil nebo import spustil, nikoli automaticky původní autor. `source_url` je pouze volitelný locator a `provenance` hrubá třída, ne kompletní auditní manifest.

Schéma v2 s `provenance: external` povinně nese striktní blok `import`: `imported_at`, `imported_by`, lowercase SHA-256 přijatých bajtů, identitu/verzi importéru a pouze doložené volitelné údaje původního zdroje. U nového native importu se čas/aktér rovnají `created_at`/`author_id`; oddělený volitelný `source_created_at` je doložený čas vzniku externího zdroje a může importu předcházet. Hash source sidecaru se při validaci snapshotu porovnává se skutečnými bajty. Pro jinou provenance je blok zakázaný. Přesný kontrakt, kompatibilitu a explicitní doloženou migraci stanoví [ADR 0023](docs/adr/0023-metadata-and-import-provenance.md). V1 zůstává čitelné a nemigruje se automaticky.

### Definice vazeb mezi entitami

`relations` je ve spustitelném schématu v1 seznam objektů s přesně dvěma klíči:
- `type` — typ vazby (řetězec),
- `target_id` — UUID cílové entity,

Pole `note` není ve v1 podporováno. Doporučené typy níže nejsou validační
allowlist; vlastní neprázdný typ, pořadí a duplicity se zachovávají. Inverzní
vazby se automaticky nedoplňují, viz [ADR 0022](docs/adr/0022-relational-index.md).

Doporučené typy vztahů:
- `supports` — A je podpůrný kontext pro B; B je základ/zdroj pro A.
- `supported_by` — inverzní k `supports`, tedy B podporuje A.
- `contains` — A obsahuje B jako součást obsahu nebo seskupení.
- `part_of` — B je součástí A.
- `depends_on` — A závisí na B pro správný kontext/interpretaci.
- `references` — A pouze odkazuje na B bez silné závislosti.
- `cites` — A cituje B.
- `derived_from` — A vzniklo z B nebo je transformací B.
- `supersedes` — nový source artefakt nahrazuje uvedenou předchozí verzi; předchozí artefakt se nemění.
- `implements` — A realizuje zadání nebo návrh popsaný v B.
- `produces` — A vytváří, generuje nebo odvozuje B.

Frontmatter má stejné klíče v YAML mezi úvodními oddělovači `---`. Parser musí odmítat duplicitní klíče, neznámou verzi schématu a nepodporované YAML konstrukce; limity jsou 64 KiB metadat a 16 úrovní vnoření. Import nesmí bez potvrzení přepisovat metadata původního zdroje.

Registry: JSON objekt pro každou entitu, společná metadata plus `status`, `body` a `relations`. Povolené druhy registrů a jejich stavy jsou definovány ve `STATES` v `spikes/metadata.py`; pole `kind` se musí shodovat s názvem adresáře registru. JSON serializovat stabilně, UTF-8 a s koncovým newline. ID se nemění při přejmenování. Kolizi ID, chybějící cíl vztahu nebo sidecar bez obsahu nelze automaticky schválit.

## Konzistence

Smazání prověřuje příchozí vztahy. Přejmenování obsahu a změna pole `file` patří do stejného commitu. Zachování obou konfliktních verzí vytváří nové ID pro kopii a vyžaduje rozhodnutí o odkazech. Změna–smazání vyžaduje volbu člověka.

U `kind: source` jsou obsahové bajty, basename v `file`, identita a importní provenance neměnné pod jedním UUID. Nové bajty se ukládají jako nový artefakt s novým UUID a volitelným vztahem `supersedes` na předchůdce. Běžné projektové anotace lze měnit samostatným commitem; přesná pravidla, transition validace a recovery jsou v [ADR 0024](docs/adr/0024-source-immutability-and-versioning.md). Současný snapshot validátor tato historická pravidla ještě nevynucuje.

SQLite obsahuje lokálně obnovitelnou projekci metadat a cest entit, štítků a směrovaných vztahů a jeden commit ID pro celý snapshot; neobsahuje jedinou kopii uživatelských dat. Migruje se z validovaného HEAD atomicky, samostatně od Git schématu a journalu, viz [ADR 0022](docs/adr/0022-relational-index.md). Při selhání validace nový index nepublikovat. MVP nepotřebuje sdílenou SQLite databázi ani synchronizaci jejího souboru.

## Implementovaný rozsah M0

`spikes/metadata.py` validuje výše uvedená metadata, cestu a identitu artefaktu, stavy registrů, unikátnost ID a cíle vztahů. Autor je kanonické UUID; jeho existenci musí později ověřit služba identity. `kind` artefaktu je document/source/snapshot. Neznámá pole a verze se odmítají. UTC čas používá koncové Z, volitelně 1–6 desetinných míst sekundy.

Sidecar má `file` jako jeden název souboru ve stejném adresáři; adresář musí obsahovat právě obsah a metadata.json. Markdown s frontmatterem je jediný soubor svého adresáře. U neměnného Markdown zdroje se projektová metadata čtou pouze ze sidecaru a původní frontmatter je součástí neinterpretovaného zdroje.

Projekce má v PoC limit 16 MiB na soubor, 64 MiB celkem a 10 000 souborů. Minimální project.json/node.json v1 validuje samostatně `spikes/configuration.py`; integrace do storage lifecycle a další konfigurace zůstávají otevřené. Journal podporuje připravené vytvoření, úpravu, přejmenování a smazání souborů s následnou obnovou; podrobnosti a omezení viz [ADR 0002](docs/adr/0002-metadata-journal.md).

## Plánované rozšíření: externí vztahy a řízené sdílení

**Návrhové podklady pro budoucí kontrakt, nikoli implementované schéma v1.** Následující entity a pole dosavadní validátor nepodporuje. Před zavedením vyžadují verzovaný kontrakt, migrační rozhodnutí a testy (BACKLOG ER-01); nelze tiše měnit `STATES`, povinná pole nebo chování starých projektů. Rozsah a návaznost drží sekce 22 master roadmapy.

### Entity a vlastnictví údajů

| Entita / pohled | Účel a hranice |
| --- | --- |
| Person | Stabilní UUID osoby; kontaktní adresy jsou atributy se zdrojem, nikoli identita nebo důkaz ověření. |
| Organization | Samostatné UUID organizace, identifikátory a provenance; příslušnost ke skupině nezpřístupňuje data ostatním členům. |
| Relationship | Vazba osoba–organizace či partner–projekt, role, platnost od/do a zdroj; historické příjemce nelze odvozovat z dnešního pracovního místa. |
| Counterparty | Role osoby nebo organizace v konkrétním vztahu. Nemá vytvářet duplicitní kontakt ani automatické RBAC členství. |
| Meeting | Projekt, pozvaní a skuteční účastníci, agenda, revize decku, interní poznámky, policy a follow-up vazby. |
| DisclosureEvent | Samostatná událost předání, přijetí nebo opravy s důkazem, rozsahem a neměnnou referencí na obsah. |
| DecisionScenario | Verzovaný interní scénář jednání se stabilními ID uzlů, směrem otázky, očekávanými odpověďmi, připravenými reakcemi, hranami a odkazy na existující backupy; není disclosure událostí. |
| BackupLibrary | Verzovaný katalog referencí na schválené slidy, grafy, obrázky nebo výřezy. Jeden obsah lze odkazovat z více slidů a větví bez kopírování. |
| PresentationSession | Trvalý záznam relace: deck a scénář v konkrétní revizi, publikum, verze policy, aktuální větev, navigační zásobník, přerušený slide/krok odhalení, odložená témata, navštívené revize a expozice; UI je projekce. |

Kandidátní registry mají zachovat konvenci `registries/<kind>/<UUID>.json`; konečné názvy a stavy uzavře návrhový kontrakt. Tato dokumentační změna je nezakládá. Definice decku a slidy jsou verzované artefakty, ne kopie v odděleném prezentačním úložišti.

Soukromý katalog může mít vlastní autoritativní privátní repozitář. Projekt dostane jen autorizované reference nebo projekce; globální vyhledávání je nesmí spojovat bez oprávnění. Meziprojektová reference potřebuje ID repozitáře a entity, ne jen lokální UUID. Stávající validátor vztahů umí pouze lokální cíle; tuto mezeru nelze řešit automatickým kopírováním neveřejných osob nebo falešnými placeholder entitami.

### Tři nezávislé osy

- `privacy`: stávající public/project/confidential/local-only a navazující RBAC určují povolenou hranici přenosu.
- `exposure_class`: green/orange/red je prezentační varování pro zkontrolovanou revizi a daný kontext, nikoli nové oprávnění nebo náhrada privacy.
- Evidence sdílení: příjemce, revize, rozsah, kanál a spolehlivost dokladu. „Již předáno“ nezmění citlivost obsahu a neznamená, že příjemce obsah četl.

Hlavní deck může být celý green po kontrole; neznámá klasifikace ani změna revize nesmí mít implicitní povolení. Stav public nevzniká odesláním jedné firmě. Evidovaná veřejná publikace má vlastní rozsah, revizi a zdroj; sama neprokazuje přečtení konkrétní osobou.

### Reference na to, co skutečně odešlo

| Skupina polí | Požadovaný význam |
| --- | --- |
| Identita události | UUID události, operation ID, původní node/actor, směr inbound/outbound, čas události a čas záznamu. |
| Publikum | Konkrétní osoby či kontaktní body známé v okamžiku předání; organizace jako kontext. Skupinová adresa nebo neznámí posluchači zůstávají explicitně neurčení. |
| Revize | ID projektu/repozitáře, artifact ID, úplný Git commit ID včetně typu hashe; čitelný revision label je jen doplněk. |
| Payload | Archivovaný přesný předaný nebo renderovaný snapshot, jeho ID a digest s algoritmem, včetně použitých assetů. |
| Rozsah | `full / excerpt / summary / derived`, identifikátor slidu, výřezu či claimu a odkazy na konkrétní revize zdrojů. |
| Kontext | Schůzka nebo komunikační operace, kanál, účel, klasifikace a verze policy, výsledek autorizace a případného potvrzení. |
| Důkaz | Typ pozorované události, stav známý/neověřený a reference na doklad; oprava odkazuje na původní událost a uvádí důvod. |
| Přijaté podmínky | Zdroj příchozí informace a případná omezení použití nebo dalšího předání; nepřepisovat je odchozí prezentační barvou. |

Commit zdroje sám nepopisuje vyrenderovanou prezentaci nebo přeposlaný e-mail. Zdrojové reference a předaný payload se proto vedou odděleně; sdílení shrnutí nezpřístupňuje celý model. Živá externí data se před prezentací zachytí do snapshotu, nebo se záznam označí za nereprodukovatelný. Retence musí chránit odkazované revize a snapshoty před neúmyslným zánikem; hash bez dostupných bajtů není archiv.

Auditní události se přidávají po souborech s deduplikací podle ID. Oprava, supersession nebo revokace je nová událost; revokace nevrací již předaný obsah. Aplikační append-only nebrání správci přepsat Git historii. Požadavky na podpisy, checkpointy a řízenou retenci jsou samostatný bezpečnostní návrh.

Příprava ani export nejsou předáním. Potvrzení audience rendereru dokládá zobrazení aplikací, nikoli pozornost lidí. SMTP přijetí není přečtení; doručenky a přístupy jsou další doklady, nikoli změna minulého faktu. Ústní sdělení je ruční záznam s určeným autorem a mírou jistoty.

### Relace Presenteru a odvozené pohledy

Scénář je interní graf, nikoli povinná cesta prezentací. Uzel rozlišuje otázku řečníka a očekávanou otázku protistrany, možné odpovědi, stručnou a podrobnou připravenou reakci, další uzly a volitelné reference na backupy. Obsahuje explicitní větev pro jinou odpověď, nevědomost nebo odmítnutí. Větev smí skončit ústní odpovědí, doplňující otázkou, odložením nebo návratem bez promítnutí slidu. Kontextové doplňky slidu i globální knihovna odkazují na stejný verzovaný obsah; klasifikace doplňku se nedědí z hlavního slidu.

Navigační volba, focus, privátní náhled a skutečné předání jsou samostatné stavy. Volba očekávané odpovědi sama nezaznamená skutečný výrok protistrany ani vyslovení připravené reakce. Skutečná odpověď a citlivé ústní sdělení vyžadují samostatné ruční potvrzení; pouze potvrzené předání vstupuje do Disclosure Registry a expozice. Navigační historie zůstává oddělená od auditní evidence.

Přerušení zachová slide, krok postupného odhalení, rozehranou větev a celý zásobník návratů. Samostatné akce vracejí o uzel, k přerušenému místu nebo do hlavní prezentace. Předběhnutý budoucí slide lze označit jako probraný, ale automaticky se nepřeskakuje. Restart obnoví navigaci, odložená témata i expozici; neurčitý výsledek audience operace zůstává `unknown`.

Globální expozici lze reprezentovat celými půlkroky: green 0, orange 1, red 2; UI zobrazuje 0 / 0,5 / 1 stupně. Součet, prahy a historie jsou deterministické. Počítá se potvrzený nový payload nebo rozsah pro aktuální publikum, ne kliknutí v privátním preview. Opakované promítnutí se zaznamená, ale stejný payload v téže relaci se nezapočítá znovu. Změna účastníků a nové revize vyžadují nové posouzení.

Relace se po pádu obnoví ze záznamů, ne z vynulovaného UI. Zavření backupu nesnižuje skóre. Oprava chybného záznamu může opravit odvozený výsledek, ale musí zůstat vysvětlitelná. Historie předchozích schůzek se zobrazuje zvlášť; badge známé revize nesnižuje její klasifikaci. Při neúplné federované historii se uvádí „neověřeno“, nikoli „dosud nesdíleno“.

Diff má primárně porovnávat skutečně předané výřezy a payloady. Změna neveřejné části zdrojového modelu sama není nově odhalená informace. LLM může rozdíl vysvětlit, ale nesmí bez potvrzení prohlásit novou revizi za již sdílenou.

### Autorita mailu, kalendáře a kontaktů

| Data | Navržená autorita / uložení |
| --- | --- |
| Projektově přijatá zpráva, příloha, agenda, poznámka, disclosure event | Vybraný Git artefakt nebo registr; SQLite jen obnovitelný projektový index. |
| Celá mailbox cache, mailový vyhledávací index a synchronizační kurzory | Oddělený lokální stav adaptéru navázaný na poskytovatele, nikoli celý projektový Git. |
| Neodeslaný koncept, odchozí fronta a neurčitý výsledek odeslání | Trvalý lokální autoritativní stav s obnovou a zálohou; nikoli zahoditelná cache. |
| IMAP složky/zprávy, CalDAV události, vzdálené CardDAV kontakty | Explicitní mapování vzdálených zdrojů a konfliktní synchronizace; zdroj pravdy pro jednotlivá pole a operace určí adaptér. |
| Hesla, OAuth refresh tokeny a klíče | Lokální secret store; projekt může nést pouze netajný odkaz, nikoli hodnotu. |

IMAP identifikace používá účet, mailbox, UIDVALIDITY a UID; Message-ID je doplňková korelace pro threading, ne jediný klíč. CalDAV/CardDAV potřebují mapu vzdálených identit, verzí a konfliktů. Kalendář zachová UID, časové pásmo, opakování a změny pozvánek; interní zápis schůzky není stejný objekt jako veřejně sdílený popis události.

Celá schránka se do projektu automaticky nevkládá podle domény odesílatele. Import vybraných zpráv a příloh zachovává původní bajty a provenance; projektové doplnění metadat je oddělené. Rozšíření nad velikostní limity M0 vyžaduje vlastní návrh streamování a úložiště, nikoli tiché zvětšení limitů.

### Obnova na hranici externího účinku

Lokální Git transakce nemůže atomicky potvrdit zároveň SMTP odeslání nebo zobrazení na druhé obrazovce. Před účinkem musí existovat trvalý operation record a připravený přesný payload; po něm doklad výsledku. Pád mezi účinkem a potvrzením vede na explicitní stav unknown, nikoli automatické opakování odeslání nebo vymyšlený úspěch. Recovery nesmí duplikovat disclosure událost; při nejistotě musí UI vyžádat rozhodnutí a konzervativně počítat s možným zpřístupněním.
