<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Vzory dokumentů, raw editor a skládání plánu

Tento dokument popisuje cílové používání. Funkce jsou zatím ve stavu
**designed**; současné UI je ještě celé neposkytuje. Architekturu určují
[ADR 0058](adr/0058-shared-raw-editor-and-pattern-catalog.md) a
[ADR 0059](adr/0059-file-plan-hierarchy-and-task-editor.md).

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

## Raw a speciální režim

Raw režim vždy ukazuje text, který bude předán doménové validaci. Speciální
režim může zobrazit jeho známé bloky jako formuláře nebo karty. Přepnutí režimu
nesmí samo uložit ani přeformátovat dokument.

Pokud strukturovaný parser nerozumí části textu, jsou možné jen dvě bezpečné
varianty:

- neznámou část beze změny zachová mimo editované spany;
- speciální režim zamkne pro zápis a vysvětlí, že změnu je nutné provést raw.

Tiché odstranění komentářů, neznámých polí nebo ručního Markdownu není
přípustné.

## Softwarová roadmapa v souborech

Kořenový hlavní TODO zvolí profil a může zahrnout další definice:

```markdown
<!-- fpw-plan-profile: software-development/v1 -->
<!-- fpw-plan-include: artifacts/018f.../content.md -->
```

Softwarový profil má tři úrovně:

| Typ | Význam | Obsahuje |
| --- | --- | --- |
| Milník (`milestone`) | strategický výsledek nebo gate | dávky |
| Dávka (`batch`) | jedna feature větev a jeden PR | úkoly |
| Úkol (`task`) | jedna nejmenší funkce/změna, normálně jeden commit | nic |

Kanonická definice každého ID je právě v jednom souboru. Definice mohou být v
hlavním TODO nebo v explicitně zahrnutém Markdown dokumentu. Nejde o kopie:
stav se mění v souboru, který dané ID vlastní.

Příklad:

```markdown
- [ ] [B-PATTERNS] Katalog vzorů a raw editor
  - type: batch
  - parent: M-EDITOR
  - parent_of: T-CATALOG

- [ ] [T-CATALOG] Validovat a filtrovat katalog
  - type: task
  - parent: B-PATTERNS
  - depends_on: T-ADAPTERS
```

Potřebuje-li se údajný task dále dělit, není ještě nejmenší jednotkou. Vzniknou
samostatné tasky ve stejné dávce a jejich pořadí se vyjádří vztahy.

## Podgrafy

Podgraf je nadále dokument s tagem `plan-subgraph`. Obsahuje pouze výběr ID:

```markdown
- [ ] [B-PATTERNS]
- [ ] [T-CATALOG]
```

Text, typ a checkbox v podgrafu nejsou autoritativní. Projekce je vždy načte z
kanonické definice napříč hlavním TODO a jeho explicitními include soubory.
Podgraf tedy může ukázat tým, téma, release nebo jiný řez bez kopírování stavů.

## Editor úkolů jako lego

Speciální editor nabídne kostku milníku, dávky nebo úkolu podle aktivního
profilu. Kostka obsahuje stabilní ID, stav, název, popis, rodiče a vztahy.
Nová kostka se vloží přes odpovídající katalogový vzor. Raw režim zůstane vždy
dostupný pro ruční text a nepodporované konstrukce.

První verze edituje jeden soubor najednou. Přesun uzlu do jiného dokumentu a
atomické vytvoření externího souboru spolu s include jsou samostatné
vícesouborové operace, nikoli skryté vedlejší účinky běžného uložení.

## Plánované pořadí realizace

```text
DOC-PATTERN-CATALOG-01 ─┬─> obnovení a dokončení COMP-03
                        └─> PLAN-TASK-EDITOR-01
PLAN-FILE-HIERARCHY-01 ───> PLAN-TASK-EDITOR-01
```

Katalog/raw editor a souborový kontrakt lze vyvíjet paralelně. Editor úkolů
začne až nad oběma stabilními kontrakty. Práce na `COMP-03` je přerušená;
po doručení katalogu a raw editoru se obnoví a zapojí jejich widget i Julia
adaptér bez změny umístění Julia editoru v Nástrojích.
