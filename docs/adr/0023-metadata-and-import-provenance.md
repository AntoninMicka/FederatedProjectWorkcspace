<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0023 — Metadata v1 a rozšířená importní provenance

Datum: 2026-09-15. Stav: přijato pro F-M1-META-01/V-04; schema v2, nový import a doložená migrace implementovány ve F-M1-META-02 dne 2026-09-17 jako lokální PoC.

## Kontext a rozhodnutí

Spustitelný validátor `spikes/metadata.py` je autoritou současného kontraktu v1. Je striktní: odmítá neznámá pole a jinou `schema_version`. Nové provenance pole proto nelze přidat do v1 bez porušení kompatibility a bez rozporu mezi starými a novými validátory. Podrobná importní provenance bude samostatné schéma v2; v1 zůstane čitelné beze změny.

Význam společných polí v1:

- `created_at` je čas vzniku projektové entity v tomto workspace. U nativního importu je to čas importu, nikoli doložený čas vzniku externího díla.
- `author_id` je lokální projektový aktér, který entitu vytvořil nebo import spustil. Nesmí se vydávat za původního autora zdroje.
- `provenance` je hrubá třída `user | external | llm-generated | llm-transformed | snapshot`, nikoli kompletní auditní manifest.
- `source_url` je volitelný uživatelsky/importérem dodaný locator. Jeho přítomnost nedokládá autora, licenci, revizi ani shodu obsahu.
- Git blob/commit a importní request digest dovolují ověřit konkrétní uložené bajty a operaci, ale v1 jejich hash ani původní externí metadata nenese ve svém aplikačním schématu.

Artefakt i registry používají stejnou hlavičku v1. Registry navíc vyžadují `status` a `body`; `relations` jsou v obou případech volitelné. Sidecar vyžaduje `file`. Tato formulace odpovídá validátoru a nic tiše nezpřísňuje.

## Importní blok v2

Schéma v2 zachová význam existujících polí a pro entitu s `provenance: external` přidá objekt `import`. Pro nový nativní import zdroje je povinný; pro jinou provenance je zakázaný.

Objekt `import` přijímá přesně pole uvedená níže a odmítá neznámé klíče. Jeho `importer` přijímá přesně `name` a volitelné `version`. Celé metadata nadále dodržují limit 64 KiB, hloubku 16, zákaz duplicit klíčů a stejné UUID/časové formáty jako v1.

| Pole `import` | Požadavek a význam |
| --- | --- |
| `imported_at` | Povinný UTC RFC3339 čas přijetí do projektu. U nové entity se rovná `created_at`. |
| `imported_by` | Povinné kanonické UUID projektového aktéra; u nativního importu se rovná `author_id`. |
| `content_sha256` | Povinný lowercase SHA-256 původních přijatých bajtů. Hash nenahrazuje uchování zdroje ani licenci. |
| `source_author` | Volitelný neprázdný text převzatý z doloženého vstupu; není lokálním user ID. |
| `source_created_at` | Volitelný UTC RFC3339 čas vzniku deklarovaný a doložený zdrojem. Je nezávislý na `imported_at` a běžně mu může předcházet; neznámý čas se vynechá. |
| `source_revision` | Volitelný neprázdný identifikátor/verze zdroje, beze změny významu poskytovatele. |
| `importer` | Povinný objekt s neprázdným `name` a volitelnou neprázdnou `version`; popisuje transformační software, ne uživatele. |

`source_url` zůstává volitelným top-level locatorem, aby se neměnil jeho dosavadní význam. Neznámý původní autor, čas, URL ani revize se nevymýšlejí a pole se vynechá. Importovaný neměnný soubor zůstává v původních bajtech; `content_sha256` se počítá z těchto bajtů před publikací.

`created_at` a `imported_at` popisují vznik entity a přijetí do tohoto projektu, nikoli vznik externího díla. UI je proto zobrazuje odděleně od `source_created_at`; pořadí se neslévá do jednoho „data dokumentu“. Doložený čas vzniku může být výrazně starší než import. Schéma nevynucuje jejich pořadí, protože `source_created_at` je tvrzení převzaté ze zdroje a může být chybné či používat jinou publikační událost; původ hodnoty musí nést importér.

Příklad sidecaru v2:

```json
{
  "schema_version": 2,
  "id": "11111111-1111-4111-8111-111111111111",
  "title": "Zápis jednání",
  "kind": "source",
  "created_at": "2026-09-15T08:00:00Z",
  "author_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "privacy": "project",
  "provenance": "external",
  "file": "zapis.pdf",
  "source_url": "https://example.invalid/zapis/7",
  "import": {
    "imported_at": "2026-09-15T08:00:00Z",
    "imported_by": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "content_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    "source_author": "Rada projektu",
    "source_revision": "7",
    "importer": {"name": "workspace-native-import", "version": "2"}
  }
}
```

Registry v1 nadále používá stejná společná pole a svá povinná data:

```json
{
  "schema_version": 1,
  "id": "22222222-2222-4222-8222-222222222222",
  "title": "Ověřit tvrzení",
  "kind": "questions",
  "created_at": "2026-09-15T08:05:00Z",
  "author_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "privacy": "project",
  "provenance": "user",
  "status": "open",
  "body": "Který zdroj tvrzení dokládá?"
}
```

V2 registr s `provenance: external` používá stejný validovaný `import` blok. Současné native UI registry tohoto typu nevytváří.

## Kompatibilita, migrace a recovery

- Čtenář v2 musí podporovat v1 i v2 v jednom validovaném Git snapshotu. Zápis nového importu použije v2 a nesmí potichu přepsat jinou entitu v1.
- Plošná migrace není podmínkou zavedení v2. V1 zůstane platným historickým záznamem s omezenou provenance.
- Explicitní migrace smí vyplnit jen doložitelné hodnoty. `imported_at`/`imported_by` lze převzít z `created_at`/`author_id` pouze pro prokazatelný import; hash se počítá z blobu importního commitu. Původního autora, čas, URL ani revizi nelze odhadnout.
- Migrace nebo budoucí import přes více persistentních vrstev použije standardní Workspace operaci: expected HEAD, writer lock, kandidátní snapshot, validaci, journal před CAS, commit, obnovu/index a receipt podle ADR 0003. Pád před posunem refu nepublikuje v2; po posunu refu recovery dokončí index bez druhého commitu.
- Index musí být před nasazením v2 aktualizován tak, aby neznámou verzi odmítl nebo v2 celou projektoval podle nového indexového schématu. Nesmí vydat částečnou v2 provenance ani starý index jako aktuální.

F-M1-META-02 implementuje souběžné čtení v1/v2, zápis native importu v2, kontrolu source hashe, úplnou indexovou projekci a zobrazení provenance v Podrobnostech. Explicitní `Sources.migrate_source` vyžaduje původní native Workspace importní commit: ancestry, přidání artefaktu v daném commitu, trailer operace a shodu neměnných polí/bajtů. Vytvoří pouze povinná doložitelná pole a identitu původního v1 importéru; žádná externí fakta neodhaduje. Automatická plošná migrace neexistuje.

Neměnnost hodnot v `import` bloku a vytváření nového source UUID při změně bajtů vymezuje navazující [ADR 0024](0024-source-immutability-and-versioning.md).
