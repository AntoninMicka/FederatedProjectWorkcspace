<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0024 — Neměnnost a verzování importovaných zdrojů

Datum: 2026-09-15. Stav: přijato; transition pravidla jsou **PoC validated** ve F-M1-SOURCE-02 pro Workspace a podporovaný první Git přenos. Obecný merge/fast-forward projektů zatím není aplikační schopnost.

## Rozhodnutí

Artefakt `kind: source` zachovává pod jedním UUID původní importované bajty. Změna obsahu není novou revizí stejného artefaktu: vytváří nový source artefakt s novým UUID. Starý artefakt a jeho Git historie zůstávají beze změny.

U existujícího source UUID jsou neměnné:

- obsahové bajty a basename uložený v sidecar `file`,
- `id`, `kind`, `created_at`, `author_id` a `provenance`,
- u v2 celý `import` blok včetně `content_sha256`.

Povolené metadata-only změny stejného UUID jsou projektové anotace `title`, `description`, `tags`, `relations` a oprava `source_url`. Všechny procházejí standardní verzovanou Workspace operací, takže původní hodnota zůstává v Git historii. `privacy` lze zpřísnit; její uvolnění je explicitní autorizovaná reklasifikace, nikoli běžná editace metadat. Oprava locatoru nemění neměnná fakta importu a sama nedokládá identitu zdroje.

Přejmenování source souboru se v první implementaci nepovoluje. Tím se `file` zachová jako původní importovaný basename bez rozšíření schématu o druhé jméno. Pozdější požadavek na zobrazované jméno použije `title`; změna tohoto pravidla vyžaduje samostatné rozhodnutí a zachování původního basename v provenance.

## Nová verze a duplicita

Nové bajty nebo nová vydaná revize externího podkladu se importují jako nový artefakt. Nový artefakt může nést explicitní směrovaný vztah `supersedes` na bezprostředně předchozí source UUID. Starý zdroj se zpětně neupravuje; inverzní dotaz lze odvodit z relačního indexu. Větev verzí nebo nejistá návaznost se zachová jako více explicitních vztahů/artefaktů, ne tichým přepsáním.

SHA-256 shoda je upozornění na stejné bajty, nikoli identita artefaktu. Uživatel může zvolit existující zdroj, nebo vytvořit nový artefakt, pokud se liší provenance, privacy či projektový význam. Automatická deduplikace nesmí sloučit metadata ani zpřístupnit obsah mezi projekty/uživateli.

Odstranění zdroje není součástí tohoto rozhodnutí. Současná aplikační cesta jej odmítá; budoucí archive/delete feature musí zachovat historii, vyhodnotit příchozí vztahy a privacy/export dopady.

## Validace snapshotu a přechodu

Neměnnost je přechodový invariant, ne pouze vlastnost jednoho stromu:

1. Snapshot validace kontroluje layout, metadata a u v2 shodu `import.content_sha256` s aktuálními bajty.
2. Transition validátor před publikací porovná base a kandidáta. Pro každé source UUID existující v obou odmítne změnu bajtů, `file` nebo jiného neměnného pole; to platí i pro v1, kde digest spočítá z obou blobů.
3. Fast-forward, merge i explicitní přijetí externího Git stavu podléhají stejné kontrole. Stejné UUID zavedené nezávisle s jinými bajty je sémantický konflikt, i když textový merge projde.
4. Změna provedená mimo aplikační zámek se nesmí automaticky přijmout jako nová verze. Vůči poslednímu validovanému commitu se označí jako konflikt; u čerstvě přijatého repozitáře lze ověřit vnitřní historii/hash, nikoli pravost původního externího souboru bez dalšího důkazu.

`validate_snapshot()` kontroluje jeden strom; `validate_transition()` navíc porovnává base a kandidáta. Workspace jej volá před journalem i nad sestaveným Git stromem před commitem. První Git přenos ověřuje každý parent→child přechod celé přijímané historie. Obecné merge/fast-forward přijímání dosud není podporováno a nesmí být přidáno bez stejné kontroly.

## Zápis a recovery

Metadata-only změna i import nové verze použijí expected HEAD, společný writer lock, validaci celého kandidáta, journal před CAS, commit, index a receipt podle ADR 0003. Nová verze publikuje obsah, sidecar a vztah `supersedes` v jednom commitu. Pád před CAS nepublikuje částečnou verzi; po CAS recovery nevytváří druhý artefakt ani commit a dokončí index.

Cizí změna base, chybějící/starý předchůdce nebo kolize UUID operaci zastaví. Retry se stejným operation ID musí použít stejné zachycené bajty, nové UUID a vztah; znovu nečte externí soubor. Odlišná data jsou nový záměr a nová operace.

## Návaznost

Reuse/adapt stávajícího importu, metadatového validátoru, Git historie, Workspace/Journal/Index a relačních vztahů. Není potřeba nová databáze ani content-addressed storage. Implementace transition validátoru, editace povolených metadat zdroje, importu navazující verze a v2 provenance patří do samostatné navazující feature.
