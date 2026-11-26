<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Uživatelské rozhraní vztahů — PROJECT-RELATIONS-01-E

V otevřeném projektu použijte tlačítko **Vztahy a propojené podklady**.
Panel sdílí desktop i web. Zobrazuje vztahy, jejich směr a stav, vlastní
podklady a zděděná data či publikované výstupy s důvodem dostupnosti.
Filtr hledá v názvech podkladů a projektů; nejde o fulltext obsahu.

Nový vztah nebo změna typu/směru nejprve připraví nativní náhled včetně
rozsahu a dopadu. Po jeho uložení musí každý konec zvlášť potvrdit přesnou
revizi za svůj projekt. Navigace do druhého projektu vyžaduje jeho přímé
oprávnění; nepřímý čtenář může podklad zobrazit bez členství ve zdroji,
nikoli zdroj spravovat. Změna revize vyžaduje nové souhlasy. Ukončení vazby
vyžaduje důvod, náhled a potvrzení a nic nemaže ze zdrojové historie.

**Otevřít** zobrazí konkrétní zdrojovou revizi jen ke čtení. Relativní odkazy
na artefakty se znovu ověřují přes stejný resolver a nepřepnou otevřený projekt.
**Použít v zadání** výslovně vybere textový podklad. Ve výběru vstupů jej lze
odznačit. Podle současného kontraktu chatu je dostupný pro režim **Úkol**
s backendem **Ollama**, včetně odpovědi uložené do konverzace. Samotná
implicitní dostupnost nevkládá žádné podklady do promptu. Binární podklady
se automaticky neextrahují ani neposílají jako text.

## Integrace a hranice

`ProjectRelationsPanel` je fasáda nad [lifecycle B](project-relations-lifecycle.md)
a společným [resolverem C](project-relations-hierarchy.md), který zahrnuje
[publikace D](project-relations-outputs.md). Správa ponechává původní přímé
request scope, role a dva nezávislé souhlasy. Webový účet získává odvozené
čtení po autorizaci kořenového projektu; explicitní delegovaný scope služby
se tím nerozšiřuje. Hranice webového náhledu vylučuje `local-only` položky.
Původní katalog webových projektů dál skrývá projekt obsahující lokální data.

`ChatService.project_source_provider(project_id)` vystavuje společné
`catalog/pin/read` pro budoucí PROJECT-SEARCH-01 a jeho LLM nástroj. E
nezavádí samostatný fulltext ani automatickou registraci modelového nástroje.
Nemění plán, závislosti ani rozsah této další dávky.

Vybrané vstupy mají identitu odvozenou z dvojice projekt/artefakt, aby se
stejné UUID v různých projektech neslilo. Context Manifest uchovává přesný
pin zdroje, cestu souhlasů, případný publikační důkaz, privacy, zdrojový HEAD,
otisk a velikost skutečně posílaných bajtů i citaci
`[project:<project-id>/artifact:<artifact-id>@<commit-id>]`.
Posílaný text je označen jako nedůvěryhodný a jen ke čtení. Připnutí je
kontrolováno při přípravě i bezprostředně před dispatch. Odvolání cesty či
publikace blokuje starý výběr; změna zdrojového HEAD mezi přípravou a
dispatch vyžaduje novou přípravu i při nezměněném HEAD příjemce. Stejná kontrola platí pro následné kroky webového hledání;
lokální data nesmějí přejít k externímu vyhledávači.

## Persistence a recovery

UI nepřidává persistentní vrstvu. Náhled, explicitní výběr a rozepsaná
operace žijí v paměti stránky. Potvrzení používá původní CAS/journal/receipt
writer a opakuje tentýž operation ID při nejistém výsledku. Crash boundaries
a obnovu zápisu určuje [lifecycle B](project-relations-lifecycle.md) a jeho
odkazy na ADR; E je nemění. Obnovení stránky výběr zahodí, neudělí souhlas.
Přesné vstupy a výsledek odeslaného úkolu uchovává dosavadní task/manifest
workflow; po chybě UI zachová zadání a nespouští samo nový placený běh.

## Ověření a zadání

Behaviorální testy `test_project_relations_panel`,
`test_ui_project_relations_browser` a `test_project_relations_web` ověřují
oddělené souhlasy, nepřímé čtení bez správy zdroje, read-only odkazy,
výslovný výběr, citaci, změnu typu/směru a odvolání. Testy manifestu
zahrnují revokaci publikace i cestu přes mezilehlý projekt, jehož změna
neposune HEAD příjemce. Browser používá dočasný profil a lokální falešnou
Ollamu; nedokládá lidskou akceptaci ani federovanou důvěru úkolu F.

Zadání E: Workspace projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, export
`668a6bc034beb694f2e7b3fc7a5116ef951f5b74c259c30c911889c6f490f1bd`,
Workspace HEAD `4e3ac6d1ed77a15fcf14981ae665f883ce81b960`, zdrojový základ
`0b327cc`. Jde o identifikaci zadání, nikoli nový živý plán.
