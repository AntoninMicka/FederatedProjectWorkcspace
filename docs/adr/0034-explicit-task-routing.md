<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0034 — Explicitní routování zdrojů, výstupu a vykonání úkolu

Datum: 2026-10-17. Stav: přijato a implementováno v dávce
`F-M3-EXPLICIT-TASK-ROUTING-01`; fyzická akceptace zůstává otevřená.

## Kontext

Dosavadní obecný task prompt nabízel lokálnímu modelu současně schémata pro
odpověď, dokument, prezentaci, webové hledání a externí požadavek. Aplikace
kontrolovala výsledné schéma, ale model stále rozhodoval o druhu výsledku.
Veřejné modely proto mohly konzistentně preferovat prezentaci i tehdy, když ji
uživatel nevybral. Získání zdroje se navíc mísilo s výsledkem úkolu.

## Rozhodnutí

Režim `orchestration`, v UI pojmenovaný **Zadání úkolu**, přijímá uzavřený
`ExplicitTaskPlan` se třemi nezávislými osami:

- `source_kinds`: kanonicky seřazená neprázdná podmnožina `conversation`,
  `artifacts`, `public-web`;
- `output_kind`: právě jedna hodnota `conversation`, `document` nebo
  `presentation`;
- `execution`: právě jedna hodnota `local-ollama` nebo `external-openai`.

Plán dále váže search query nebo ID již potvrzených `PublicSourceRuns`. Query
je povolená jen před získáním zdroje; po získání se používají přesná run ID,
projekční hash, adapter/revize, URL, actor, projekt a expected HEAD. Aplikace
z plánu deterministicky vybere jedinou roli a jediné schéma:
`task-output-conversation-v1`, `task-output-document-v1` nebo
`task-output-presentation-v1`. Jiný druh modelového výsledku se odmítne;
neexistuje heuristická oprava ani fallback na jiný výstup.

`public-web` bez run ID vytvoří pouze durable návrh řízeného hledání. Search a
Public Source Reader si ponechají vlastní preview, potvrzení a journal podle
ADR 0033. Teprve úspěšný reader run je vstupem nového generačního task plánu.
Hledání ani fetch nejsou druhem výsledku a samy nezapisují do projektu.

Lokální Ollama smí po aplikační autorizaci přijmout konverzaci, interní
artefakty a potvrzené veřejné projekce. Externí OpenAI smí v prvním řezu
přijmout jen konverzaci a veřejné projekce; `artifacts` se odmítnou na klientu
i serveru. Externí task vždy projde přes přesný preview a souhlas. Provider
request používá JSON výstup zvolené role a odpověď znovu validuje aplikace.
Dokument a prezentace zůstávají dočasnými návrhy s odděleným potvrzením
projektového zápisu. `local-only` nesmí překročit `same-node`.

Režim `brainstorming`, v UI pojmenovaný **Volná konverzace**, zůstává přímým
textovým chatem s explicitním modelem. Nejde o task router a nepřijímá interní
artefakty. Starý modelový výběr `external-request` a `web-search` se pro nové
task plány nepoužívá; durable historické záznamy zůstávají čitelné.

## Recovery a persistentní hranice

Kanonický plán je součástí durable task requestu; jeho digest je součástí
routovaného výsledku. Context Manifest váže přesné vstupy, target, model,
privacy, task roli a expected HEAD. Změna plánu, vstupu, bindingu nebo HEAD
vyžaduje nový manifest/run.

Search, reader, lokální backend a externí backend mají oddělené právě-jednou
journaly. Stav `unknown` se automaticky neopakuje. Po úspěšném externím běhu se
validovaný přímý výsledek dokončí jako `direct-answer`; validovaný dokument či
prezentace atomicky nahradí `external-request` jako reviewovatelný draft. Pád
mezi provider success a touto náhradou se obnoví z durable provider response
bez druhého dispatch. Git zápis nastane až v existující samostatně potvrzené
publikační operaci.

## Reuse a odmítnuté varianty

Implementace reuse/adaptuje `ChatRunChoice`, `ContextBuilder`, `TaskOutcomes`,
`OllamaRuns`, `OpenAIRuns`, externí approval, search/reader journaly a
prezentační validátor. Přidává pouze malý uzavřený task-plan kontrakt a tři role;
nevzniká nový backend pool, workflow framework ani druhý context mechanismus.

Odmítá se volba druhu výsledku modelem, odvozování výstupu z formulace promptu,
automatické webové hledání/fetch, předání interních artefaktů externímu modelu,
automatická publikace a tichý fallback mezi providery. Tyto varianty by
obcházely uživatelův plán, privacy hranici nebo právě-jednou recovery.

## Důsledky

UI musí před dispatch vždy ukázat zvolené zdroje, výstup a vykonání a u
externího cíle viditelně zakázat interní artefakty. Dostupnost modelu nebo
provideru není důvod plán změnit; chyba zůstane konkrétní a vyžádá nový vědomý
běh. ADR 0008 zůstává autoritou Context Manifestu, backendů a chatových vláken,
ale jeho starší obecný modelový task router a omezení orchestrace pouze na
Ollamu jsou pro nové task plány tímto rozhodnutím nahrazeny.
