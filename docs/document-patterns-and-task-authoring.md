<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Vzory dokumentů, raw editor a skládání plánu

Tento dokument popisuje současné i cílové používání. Vestavěný katalog,
sdílený raw widget a jeho adaptéry pro Markdown/TODO a prezentaci jsou
**implemented** v `DOC-PATTERN-CATALOG-01`. Julia adaptér je připravený jako
neexekuční kontrakt, ale jeho UI zapojí až obnovená `COMP-03`. Souborový plán a
speciální task editor zůstávají **designed**. Architekturu určují
[ADR 0058](adr/0058-shared-raw-editor-and-pattern-catalog.md) a [ADR
0059](adr/0059-file-plan-hierarchy-and-task-editor.md).

## Čtyři oddělené části

1. **Julia editor** patří do hlavního panelu **Nástroje → Julia**. Výběr,
   preview, spuštění a publikace výsledku zůstávají ve **Výpočtech**.
2. **Raw editor** je společný textový widget. Typový adaptér určí formát,
   validaci, relevantní vzory a skutečnou operaci uložení.
3. **Speciální editor** materializuje známou strukturu do ovládacích prvků.
   Prezentace už takový editor mají; úkoly dostanou editor z „lego kostek“.
4. **Souborový plán** určuje typy uzlů, hierarchii, vztahy, zahrnuté soubory a
   podgrafy. Git soubory zůstávají autoritou.

## Jak funguje vzor

Katalog se nejprve filtruje podle typu otevřeného dokumentu. Uživatel může
vložit celý dokument, blok nebo fragment na kurzor. Vložení nic neukládá.

Markdownový vzor může vypadat například takto:

```markdown
## <!-- DOPLNIT: název části -->

<!-- DOPLNIT: účel a očekávaný výsledek -->
```

Julia vzor používá platné Julia komentáře:

```julia
# DOPLNIT: popište význam parametru
value = 0
```

U formátu bez komentářů zůstane vložený text syntakticky platný a nápověda se
zobrazí vedle editoru. Katalog nesmí vydávat neplatný JSON za použitelný vzor.
Vzory nejsou makra: samy nespouštějí kód, nevolají síť a nezískávají přístup k
projektu.

První katalog počítá se čtyřmi skupinami: obecný Markdown, úkol/plán,
prezentace a Julia. Jeden vzor může podporovat více kompatibilních typů, ale UI
nikdy nenabídne vzor mimo uzavřený seznam aktivního adaptéru.

V současném desktop/web UI otevře **Dokumenty → Nový dokument** nebo editor
hlavního TODO tentýž raw widget. Volba **Vzor** se filtruje podle aktivního
adaptéru; **Vložit vzor** změní jen lokální draft a **Ověřit obsah** zobrazí
výsledek bounded validace. Uložení nadále používá původní dokumentovou
operaci. Nativní select, tlačítka a textarea jsou ovladatelné klávesnicí; v
úzkém zobrazení se toolbar skládá do jednoho sloupce a textarea nepoužívá
mobilní zoom pod 16 px.

## Raw a speciální režim

Raw režim vždy ukazuje text, který bude předán doménové validaci. Speciální
režim může zobrazit jeho známé bloky jako formuláře nebo karty. Přepnutí režimu
nesmí samo uložit ani přeformátovat dokument.

Prezentační editor nabízí přepínač **Vizuální / Raw**. Přechod do Raw
serializuje skutečný deck, nic neukládá a používá stejný widget. Návrat do
vizuálního režimu nebo uložení projde jen pro validní kanonický deck s lossless
round-tripem; jinak raw draft zůstane otevřený s chybou.

Pokud strukturovaný parser nerozumí části textu, jsou možné jen dvě bezpečné
varianty:

- neznámou část beze změny zachová mimo editované spany;
- speciální režim zamkne pro zápis a vysvětlí, že změnu je nutné provést raw.

Tiché odstranění komentářů, neznámých polí nebo ručního Markdownu není
přípustné.

## Softwarová roadmapa v souborech

Kořenový hlavní TODO zvolí profil:

```markdown
<!-- fpw-plan-profile: software-development/v1 -->
```

Softwarový profil má tři úrovně:

| Typ | Význam | Obsahuje |
| --- | --- | --- |
| Milník (`milestone`) | strategický výsledek nebo gate | dávky |
| Dávka (`batch`) | jedna feature větev a jeden PR | úkoly |
| Úkol (`task`) | jedna nejmenší funkce/změna, normálně jeden commit | nic |

Kanonická definice každého ID je právě v jednom souboru. Batch má task potomky
buď jako vnořené odrážky, nebo jeho titul odkazuje na přesnou verzovanou cestu
document artefaktu. Nejde o kopie: stav se mění v souboru, který dané ID vlastní.

Příklad:

```markdown
- [ ] [M-EDITOR] Editory
  - type: milestone
  - [ ] [B-PATTERNS] Katalog vzorů a raw editor
    - type: batch
    - [ ] [T-CATALOG] Validovat a filtrovat katalog
      - type: task
      - depends_on: T-ADAPTERS

  - [ ] [B-EXTERNAL] [Externí dávka](artifacts/018f.../content.md)
    - type: batch
```

Odkazovaný dokument začíná `<!-- fpw-plan-document: definitions/v1 -->` a v
první verzi obsahuje pouze kořenové leaf tasky dané dávky. Inline potomci a
souborový odkaz se na jednom batch nekombinují. Graf obě varianty materializuje
na stejné uzly a `parent_id`; není dalším úložištěm stavu.

Potřebuje-li se údajný task dále dělit, není ještě nejmenší jednotkou. Vzniknou
samostatné tasky ve stejné dávce a jejich pořadí se vyjádří vztahy.

## Podgrafy

Podgraf je nadále dokument s tagem `plan-subgraph`. Obsahuje pouze výběr ID:

```markdown
- [ ] [B-PATTERNS]
- [ ] [T-CATALOG]
```

Text, typ a checkbox v podgrafu nejsou autoritativní. Projekce je vždy načte z
kanonické definice napříč hlavním TODO a jeho odkazovanými task soubory.
Podgraf tedy může ukázat tým, téma, release nebo jiný řez bez kopírování stavů.

## Editor úkolů jako lego

Speciální editor nabídne kostku milníku, dávky nebo úkolu podle aktivního
profilu. Kostka obsahuje stabilní ID, stav, název, popis, rodiče a vztahy.
Nová kostka se vloží přes odpovídající katalogový vzor. Raw režim zůstane vždy
dostupný pro ruční text a nepodporované konstrukce.

První verze edituje jeden soubor najednou. Přesun uzlu do jiného dokumentu a
atomické vytvoření externího souboru spolu s odkazem jsou samostatné
vícesouborové operace, nikoli skryté vedlejší účinky běžného uložení.

## Pořadí realizace

```text
DOC-PATTERN-CATALOG-01 ──> obnovení a dokončení COMP-03
DOC-PATTERN-CATALOG-01 + PLAN-TASK-GRAPH-01 ──> PLAN-TASK-EDITOR-01
DOC-PATTERN-CATALOG-01 ──> DOC-PATTERN-LIBRARY-01 (ostatní adaptéry)
```

Katalog/raw editor je implementovaný a doručený; `COMP-03` je tím odblokovaná.
Task editor ve své feature dávce dodává úplnou coverage vlastních operací a
souborový kontrakt. Samostatná `DOC-PATTERN-LIBRARY-01` zůstává pro obecné
rozšíření Markdown, prezentačních a Julia vzorů. Obnovená `COMP-03` zapojí
sdílený widget i Julia adaptér bez změny umístění Julia editoru v Nástrojích.
