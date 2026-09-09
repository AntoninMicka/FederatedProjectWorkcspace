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

Frontmatter má stejné klíče v YAML mezi úvodními oddělovači `---`. Parser musí odmítat duplicitní klíče, neznámou verzi schématu a nepodporované YAML konstrukce; limity parseru se stanoví před importem. Import nesmí bez potvrzení přepisovat metadata původního zdroje.

Registry: JSON objekt pro každou entitu, společná metadata plus `status`, `body` a `relations`. Povolené stavy podle druhu registru se doplní do strojového schématu. JSON serializovat stabilně, UTF-8 a s koncovým newline. ID se nemění při přejmenování. Kolizi ID, chybějící cíl vztahu nebo sidecar bez obsahu nelze automaticky schválit.

## Konzistence

Smazání prověřuje příchozí vztahy. Přejmenování obsahu a změna pole `file` patří do stejného commitu. Zachování obou konfliktních verzí vytváří nové ID pro kopii a vyžaduje rozhodnutí o odkazech. Změna–smazání vyžaduje volbu člověka.

SQLite obsahuje projekci entit a commit ID; neobsahuje jedinou kopii uživatelských dat. Při selhání validace nový index nepublikovat. MVP nepotřebuje sdílenou SQLite databázi ani synchronizaci jejího souboru.

Storage PoC záměrně používá pouze minimální entitu `id/title`; úplné schéma a frontmatter/sidecar parser nejsou implementovány.
