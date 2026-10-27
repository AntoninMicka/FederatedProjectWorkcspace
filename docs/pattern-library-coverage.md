<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Coverage vestavěné knihovny vzorů

Tato mapa je reviewovaný rozsah `DOC-PATTERN-LIBRARY-01`. Popisuje pouze
vestavěné read-only vzory společného raw editoru. Katalog nic neukládá,
nespouští Julia kód, nevolá síť a nepřiděluje oprávnění. Text se do lokálního
draftu vloží až po explicitním stisku **Vložit vzor**.

## Obecný Markdown

| Scénář | Stabilní vzor | Formát | Vložení |
| --- | --- | --- | --- |
| Začít minimální dokument | `markdown.document` | `text/markdown` | celý dokument |
| Přidat sekci | `markdown.section` | `text/markdown` | na kurzor |
| Přidat ověřitelný checklist | `markdown.checklist` | `text/markdown` | na kurzor |
| Založit stručný rozhodovací záznam | `markdown.decision` | `text/markdown` | celý dokument |
| Založit zápis ze schůzky | `markdown.meeting-notes` | `text/markdown` | celý dokument |

Checkbox v obecném dokumentu je pouze Markdown. Projektovou task entitu a
graf vytváří výhradně profilovaný plán; jeho úplná coverage zůstává pod
`task-plan.*` a byla dodána v `PLAN-TASK-EDITOR-01`.

## Prezentace

| Scénář | Stabilní vzor | Formát | Vložení |
| --- | --- | --- | --- |
| Začít jedním slidem | `presentation.document` | `application/x-fpw-presentation-markdown` | celý dokument |
| Připravit tříslidový briefing | `presentation.briefing` | `application/x-fpw-presentation-markdown` | celý dokument |
| Připravit rozhodovací review s backupem | `presentation.decision-review` | `application/x-fpw-presentation-markdown` | celý dokument |

Prezentační vzory jsou celé kanonické decky. Každý musí projít doménovou
validací a lossless `decode → encode` round-tripem; samostatný raw fragment
slidu se nenabízí, protože by sám nebyl platným dokumentem. Jednotlivé slidy se
po vložení upravují existujícím vizuálním editorem.

## Julia

| Scénář | Stabilní vzor | Formát | Vložení |
| --- | --- | --- | --- |
| Začít malý skript | `julia.script` | `text/x-julia` | celý dokument |
| Přidat funkci | `julia.function` | `text/x-julia` | na kurzor |
| Začít modul | `julia.module` | `text/x-julia` | celý dokument |
| Začít runner entrypoint s result manifestem | `julia.runner-entrypoint` | `text/x-julia` | celý dokument |
| Založit připnutý `Project.toml` | `julia.project-toml` | `application/toml` | celý dokument |
| Založit úplný computation kontrakt v1 | `julia.computation-json` | `application/json` | celý dokument |

`julia.computation-json` je úplný doménově validní
`fpw-julia-computation-v1`; nulové hashe, UUID a cesty jsou neutrální hodnoty,
které musí specializovaný editor nahradit referencemi skutečného committed
snapshotu. `julia.runner-entrypoint` zapisuje deklarovaný výstup a jeho
`fpw-julia-result-v1.json`, ale samotné vložení ani běžná raw validace kód
nespouští. Fyzické provedení, víceartefaktové uložení a ARM64 akceptace patří
do `COMP-03`.

## Kontextová nápověda

Každý adaptér nese krátkou nápovědu a vyplněnou textovou ukázku pro každý
svůj formát; každý vzor má vlastní detail a vyplněný příklad bez zástupných
hodnot `DOPLNIT`. Po otevření raw editoru není
předvybraný žádný vzor a pravý panel popisuje celý aktivní soubor včetně
ukázky skutečného souboru. Po explicitním výběru položky panel nahradí tento
obsah názvem, podrobným popisem a vyplněným textem zvoleného vzoru. Vše se
vykresluje jako bezpečný text. Pouhá změna výběru nemění textarea.

Raw editor umožňuje u fragmentu nebo bloku zvolit aktuální pozici
kurzoru/výběru, nebo konec textu. Kostkový task editor nabízí konec souboru a
pozici před každým rozpoznaným uzlem; vložení stále mění jen lokální draft a
pořadí ostatního textu zachovává.

Na širokém desktopu panel neukrajuje prostor z dosavadní 820px pracovní šířky
editoru, ale využívá prázdné místo napravo od formuláře. Při viewportu do
1250 px se editor a panel složí do jednoho sloupce.

Katalogový registr strojově zveřejňuje tutéž mapu jako `coverage`. Modulová
validace odmítne chybějící, duplicitní nebo s adaptérem, formátem či insertion
mode nekonzistentní řádek. Projektové, uživatelské a síťově získané katalogy,
makra, pluginy a generický template engine zůstávají mimo rozsah.
