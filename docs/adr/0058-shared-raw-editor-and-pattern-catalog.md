<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0058 — Sdílený raw editor a typovaný katalog vzorů

- Stav: přijaté rozhodnutí, implementováno
- Datum: 2026-10-27
- Dávka: `DOC-EDITOR-CONTRACTS-01`
- Implementace: `DOC-PATTERN-CATALOG-01` na větvi
  `feature/doc-pattern-catalog-raw-editor`; doručení PR zůstává samostatný stav

## Kontext

Workspace má obecný Markdown editor, strukturovaný editor prezentací a na
větvi `feature/comp-03-julia-workspace` specializovaný editor Julia modelu.
Další samostatné textové plochy by duplikovaly ochranu rozepsané práce,
vkládání vzorů, validaci, přístupnost a stav uložení. Zároveň nelze sjednotit
zápis dokumentu, prezentačního decku a víceartefaktového Julia modelu do jedné
generické transakce: každý typ má jinou autoritu, validaci a recovery.

## Rozhodnutí

Vznikne jeden sdílený **raw editor widget**. Widget vlastní pouze editaci
jednoho textového bufferu, výběr a vložení vzoru, stav dirty, ochranu před
opuštěním, zobrazení validačních chyb a klávesnicové/mobilní chování. Nezná
projektové cesty, Git, journal ani endpoint pro uložení.

Konkrétní použití dodá **typový adaptér**, který uzavřeně deklaruje:

- stabilní typ dokumentu a podporované textové formáty;
- přípustné vzory a místo vložení (`document`, `block`, `cursor`);
- syntaxi komentářů, pokud ji formát skutečně podporuje;
- parser/validátor a případnou bezpečnou serializaci;
- read-only důvod, limity a callback jediné existující zápisové operace;
- zda lze raw obsah lossless předat specializovanému editoru a zpět.

**Katalog vzorů** je oddělený read-only registr. Každý vzor má stabilní ID,
verzi, název, cílové typy/formáty, režim vložení, text a stručnou nápovědu.
První implementace dodá pouze verzované, reviewované vestavěné vzory pro
obecný Markdown, úkol/plán, prezentaci a Julia. Projektové, uživatelské nebo
síťově získané katalogy jsou samostatný budoucí rozsah a nesmějí se tiše
sloučit s vestavěnými položkami.

Vzor je textový příklad, nikoli makro ani spustitelný plugin. U syntaxí s
komentáři označuje místa k doplnění platný komentář daného formátu, například
`<!-- DOPLNIT: ... -->` v Markdownu, `# DOPLNIT: ...` v Julii/TOML nebo
`// DOPLNIT: ...` jen tam, kde jsou `//` komentáře platné. Formát bez komentářů
nesmí dostat neplatný pseudokomentář: použije validní neutrální hodnotu a
instrukci v metadatech vzoru. Vložení vzoru pouze mění lokální draft; nikdy
automaticky neukládá, nespouští Julia kód ani nepublikuje výstup.

Specializovaný editor může nad stejným bufferem materializovat známé části do
widgetů. Raw text zůstává kanonickým fallbackem. Přepnutí režimu nesmí
reformátovat neznámý obsah; pokud adaptér neumí lossless round-trip, nabídne
strukturovaný režim pouze pro čtení nebo jej odmítne s konkrétní chybou.
Existující prezentační editor zůstává specializovaným editorem a postupně
připojí společný raw režim. Julia zůstane pod **Nástroje → Julia**; záložka
**Výpočty** není editor.

## Persistenční a recovery hranice

Výběr typu, filtrování katalogu, vložení vzoru, změna raw/special režimu a
validace před uložením jsou ephemerální operace bez zápisu. Pád před uložením
může ztratit neuložený draft stejně jako současný editor; případná durable
draft recovery vyžaduje samostatné rozhodnutí.

Po explicitním uložení adaptér předá přesný validovaný draft jediné existující
doménové operaci:

- běžný dokument použije `ArtifactActions` a Workspace/Journal/Git/index;
- prezentace použije svou atomickou projektovou operaci;
- Julia model použije svou víceartefaktovou Workspace transakci;
- budoucí task editor použije dokumentovou operaci nad autoritativním souborem.

Widget nevytváří společnou databázi, druhý journal ani souběžný zápis. Stale
HEAD, lost response a opakování se řeší doménovým operation ID a receiptem.
Po commitu lze index obnovit z HEAD; před commitem rozhoduje existující journal
daného adaptéru. Obecný happy path tedy nezakrývá odlišné crash boundaries.

## Bezpečnost a důsledky

- Typ a vzor se vybírají z uzavřených registrů; neznámý typ selže bezpečně.
- Text se vykresluje jako text, nikoli jako HTML nebo executable preview.
- Vzor nezískává oprávnění, privacy ani zápisový target; ty určuje dokument a
  adaptér při uložení.
- Read-only source, replika nebo importovaný immutable vstup zůstává read-only.
- Jeden widget sníží UI duplicity, ale nepředstírá jednotný datový formát ani
  jednotnou transakci všech dokumentů.

## Stav implementace

`spikes/document_patterns.py` poskytuje uzavřený verzovaný katalog, čtyři
typové adaptéry a bounded validaci. Sdílený widget ve
`spikes/desktop_ui.py` je zapojený do obecného Markdown/TODO editoru a jako
lossless raw režim existujícího prezentačního editoru. Katalog i validace jsou
read-only API; neexistuje společný save endpoint ani execution callback.

Julia adaptér a jeho platné Julia/TOML/JSON vzory jsou implementované jako
neexekuční kontrakt pro `COMP-03`. Zapojení do rozpracovaného Julia authoringu,
spuštění kódu, víceartefaktové uložení a fyzická ARM64 akceptace zůstávají v
`COMP-03`. Obecný Markdown v této dávce používá bounded textovou validaci;
specializovaný task parser vznikne až nad souborovým kontraktem v
`PLAN-TASK-EDITOR-01`.

## Reuse rozhodnutí

**Reuse/adapt:** shared artifact editor a jeho draft guard, bezpečné DOM
vykreslování, `ArtifactActions`, prezentační editor a existující
validační/zápisové služby. Sdílený widget a Julia adaptér se implementují
před obnovením přerušené `COMP-03`; ta je následně zapojí do Julia editoru.
**Reject:** nový UI
framework, executable template engine, druhý projektový store a univerzální
save endpoint. Soukromá inventura neposkytla doložený komponent s odpovídající
Git autoritou, recovery a lossless round-trip kontraktem; žádný její kód ani
neveřejný detail se nepřenáší.
