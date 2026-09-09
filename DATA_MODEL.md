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

Projekce má v PoC limit 16 MiB na soubor, 64 MiB celkem a 10 000 souborů. Project.json a strojová schémata dalších konfigurací zůstávají otevřená. Journal podporuje připravené vytvoření, úpravu, přejmenování a smazání souborů s následnou obnovou; podrobnosti a omezení viz [ADR 0002](docs/adr/0002-metadata-journal.md).
