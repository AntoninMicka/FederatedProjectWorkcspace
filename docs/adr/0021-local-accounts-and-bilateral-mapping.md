<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->
# ADR 0021 — Lokální účty, oboustranné mapování a přenos práv

Datum: 2026-09-13. Stav: přijato; lokální účty a offline podpisový protokol
implemented, portable ACL designed s vykonatelným validátorem; transport M5 otevřený.

## Rozhodnutí

Požadavek uživatele upřesňuje sekce 5A/6C roadmapy: sdílený uživatel federace
není globální přihlašovací účet. Každý účet patří jedinému lokálnímu uzlu.
Desktop má jediného běžícího OS uživatele se stabilním author UUID; web
více lokálních účtů. Autentizace je výhradně lokální a není odvozena z mapování.
Neexportovat hesla, jejich digesty, tokeny, sessions ani soukromé klíče.

Mapování je samostatný registr dvojice (node UUID, user UUID) na druhou takovou
dvojici a explicitní množinu projektových UUID. Jeho aktivace vyžaduje dvě
nezávislá schválení lokálních správců, kryptograficky ověřená za oba uzly.
Potvrzení s Ed25519 podpisem váže ID návrhu, obě identity, celý scope i rozhodnutí.
Otisk veřejného SPKI klíče je SHA-256, získaný nezávislou cestou a uložený u peeru.
Jeden uzel nemůže potvrdit druhý; změněný scope, neznámý klíč nebo cizí podpis
se odmítají. Žádné slučování podle jména, SSO, automatický účet ani kopie rolí.

Implementovaný offline protokol ručně vyměňuje podepsané JSON soubory; budoucí
transport přenáší tatáž ověřovaná rozhodnutí. Nespoléhá na VPN jako autoritu.
Aktivace není distribuovaná transakce: každý uzel potřebuje oba podpisy a
aktuální lokální účet, trust a politiku. Revokace je podepsaný tombstone;
staré potvrzení po ní nesmí mapování oživit ani při opačném pořadí doručení.
Změna mapování vyžaduje nové ID a nové dva podpisy. Odvolání peer trust trvale
revokuje související mapování; nové schválení uzlu není nové schválení účtu.

## Data a ACL

Plánované rozšíření M5 rozliší technický stav peeru od capability profilu vztahu.
Profily `same-company-same-team`, `same-company`, `trusted-partner`,
`holding-partner` a `partner` vedle výchozího `unspecified` nejsou numerickým
žebříčkem důvěry a samy nic neautorizují:

- `same-company-same-team` může přenášet identity uživatelů a jejich projektové
  role; hesla, credentials, session a možnost vzdáleného přihlášení zůstávají
  vždy lokální,
- `same-company` synchronizuje data, ale vzdáleného uživatele pouze eviduje jako
  kvalifikovanou identitu pro provenance a audit; nepřebírá jej jako lokální účet
  ani nesynchronizuje jeho role,
- `trusted-partner` dovoluje výběrové sdílení konkrétně mapovaným příjemcům,
- `holding-partner` dovoluje výběrové sdílení také ověřené společnosti jako celku;
  její členství je časově vymezené a verzované,
- `partner` dovoluje pouze chat a obsah, který uživatel explicitně odešle nebo
  nasdílí; nepovoluje background synchronizaci ani procházení projektu,
- `unspecified` je fail-closed.

Přenos neveřejné historie vyžaduje navíc oboustranně schválený project/branch
scope, případné mapování uživatelů či organizačního příjemce, origin ACL, právo
`export` a místní policy. Tím se public-only první přenos nerozšíří pouhou změnou
jednoho příznaku.

Portable rights manifest v1 má právě `schema_version`, `project_id`, `commit_id`
a `entries`. Každá entry má `entity_id`, `privacy` a `grants`; každý grant
`node_id`, `user_id`, `actions`. Akce jsou read/write/review/manage/export,
nikoli lokální node-admin nebo federation-admin. Neznámá pole/akce, duplicitní
entity či granty a chybějící manifest se odmítají. Granty bez akcí nic nepovolují.
Manifest musí přenos navázat na stejný validovaný Git commit a všechny skutečně
přenášené entity/bajty, včetně dosažitelné historie dle ADR 0008. Samotné
deklarované commit_id, podpis mapování ani validátor ACL tuto vazbu neprokazují.

Origin ACL a privacy se přenášejí společně s daty beze ztráty a beze změny
kvalifikovaných vlastníků. Mapování je používá při autorizaci, nepřepisuje je.
Účinné akce jsou průnik origin ACL, aktivního scope, lokální projektové role
a lokální politiky; ne součet grantů dvou účtů. Reader znamená pouze read,
reviewer read/review, editor read/write a project-admin read/write/review/manage.
Export vyžaduje explicitní politiku a právo, nelze jej domyslet z čtení.
Local-only nepřekračuje uzel; confidential se nesmí stát public při importu.
Odesílající i přijímající uzel kontrolují práva před přenosem a zpřístupněním.
Neřešitelné/konfliktní ACL nepublikovat; uchovat historii a vyžádat rozhodnutí.

`validate_rights` a `Administration.mapped_actions` jsou vykonatelný základ.
Transport, úplnost manifestu, ACL editace v artefaktech a jejich atomické
publikování s daty nejsou implementované; navazují na Workspace ADR 0003/0008.

## Persistence, crash boundaries a reuse

Reuse Git, native token/OS session, ProjectCreation.author_id a lokální credential
store; adapt UI do samostatných záložek/tabulek a přidej oddělené mappings v registru.
Nový podpisový protokol používá systémový OpenSSL, ne nový backend/framework.
Registr v2 se publikuje stejným flock a atomickým Git ref CAS jako ADR 0020.
Migrace v1 přidá prázdná mappings bez změny účtů a zachová rodiče historie.
Pád při změně ref znamená buď předchozí nebo nový kompletní registr; podpisy
se ukládají společně se specifikací, nikoli oddělenými částečnými checkboxy.
Credential/key soubory se nesynchronizují. První key bootstrap používá fsync
a hardlink bez overwrite; public marker lze po pádu doplnit ze stejného klíče.
Při chybějícím dříve označeném klíči obnovit originál, negenerovat novou identitu.
Pád po commit/ztráta odpovědi nevyžaduje opakované schválení: znovu načíst
registr a vydat uložený podepsaný soubor. Průběžná evidence a zbývající cílové
ověření jsou v [TODO](../../TODO.md); provozní postup v [návodu](../administration.md).

## Plánované federované konverzace

Federovaný lidský chat v M5 používá kvalifikované lokální identity a aktivní
oboustranné mapování; nevytváří globální účet ani vzdálené přihlášení. Zprávy a
jejich durable outbox/inbox jsou samostatný komunikační stav mimo projektový Git
a mimo obnovitelný projektový index. Stabilní ID, podpis/transportní provenance
a idempotentní příjem umožní offline retry bez tvrzení, že hodiny uzlů dávají
globální pořadí.

Uložení vybraného chatu, shrnutí, zadání nebo jiného podporovaného artefaktu je
samostatná explicitní Workspace publikace s preview, provenance a zděděnou
privacy. LLM je volitelný zpracovatel pod Context Manifestem; chat mezi lidmi
funguje bez něj. Publikovaný artefakt není autoritou živého vlákna a jeho editace
nemění původní zprávy. Přesný zprávový kontrakt, retence, skupinové členství a
crash boundaries uzavřou F-M5-CHAT-01/02 před implementací.
