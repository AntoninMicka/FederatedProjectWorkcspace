# Datový model — návrh v1

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

Povinná pole: `schema_version` (1), `id` (UUID), `title` (neprázdný text), `kind`, `created_at` (UTC RFC3339), `author_id`, `privacy` (public/project/confidential/local-only), `provenance` (user/external/llm-generated/llm-transformed/snapshot). Sidecar navíc obsahuje `file`. Volitelná pole: description, tags, source_url a relations (typ vztahu + cílové ID).

Frontmatter má stejné klíče v YAML mezi úvodními oddělovači `---`. Parser musí odmítat duplicitní klíče, neznámou verzi schématu a nepodporované YAML konstrukce; limity jsou 64 KiB metadat a 16 úrovní vnoření. Import nesmí bez potvrzení přepisovat metadata původního zdroje.

Registry: JSON objekt pro každou entitu, společná metadata plus `status`, `body` a `relations`. Povolené druhy registrů a jejich stavy jsou definovány ve `STATES` v `spikes/metadata.py`; pole `kind` se musí shodovat s názvem adresáře registru. JSON serializovat stabilně, UTF-8 a s koncovým newline. ID se nemění při přejmenování. Kolizi ID, chybějící cíl vztahu nebo sidecar bez obsahu nelze automaticky schválit.

## Konzistence

Smazání prověřuje příchozí vztahy. Přejmenování obsahu a změna pole `file` patří do stejného commitu. Zachování obou konfliktních verzí vytváří nové ID pro kopii a vyžaduje rozhodnutí o odkazech. Změna–smazání vyžaduje volbu člověka.

SQLite obsahuje projekci entit a commit ID; neobsahuje jedinou kopii uživatelských dat. Při selhání validace nový index nepublikovat. MVP nepotřebuje sdílenou SQLite databázi ani synchronizaci jejího souboru.

## Implementovaný rozsah M0

`spikes/metadata.py` validuje výše uvedená metadata, cestu a identitu artefaktu, stavy registrů, unikátnost ID a cíle vztahů. Autor je kanonické UUID; jeho existenci musí později ověřit služba identity. `kind` artefaktu je document/source/snapshot. Neznámá pole a verze se odmítají. UTC čas používá koncové Z, volitelně 1–6 desetinných míst sekundy.

Sidecar má `file` jako jeden název souboru ve stejném adresáři; adresář musí obsahovat právě obsah a metadata.json. Markdown s frontmatterem je jediný soubor svého adresáře. U neměnného Markdown zdroje se projektová metadata čtou pouze ze sidecaru a původní frontmatter je součástí neinterpretovaného zdroje.

Projekce má v PoC limit 16 MiB na soubor, 64 MiB celkem a 10 000 souborů. Minimální project.json/node.json v1 validuje samostatně `spikes/configuration.py`; integrace do storage lifecycle a další konfigurace zůstávají otevřené. Journal podporuje připravené vytvoření, úpravu, přejmenování a smazání souborů s následnou obnovou; podrobnosti a omezení viz [ADR 0002](docs/adr/0002-metadata-journal.md).
