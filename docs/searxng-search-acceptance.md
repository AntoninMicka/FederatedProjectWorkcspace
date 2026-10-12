<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Akceptace řízeného hledání přes SearXNG

Checklist ověřuje feature `F-M3-SEARCH-01`. SearXNG a Ollama jsou samostatné
explicitní bindingy; dostupnost jedné služby nesmí změnit druhou ani privacy.

## Konfigurace

1. Otevřete **Nastavení → AI backend → Řízené webové hledání**.
2. Pro službu na stejném hostiteli zadejte číselný loopback HTTP endpoint,
   stabilní cíl `local-process`, limit 1–10 a timeout 1–60 sekund.
3. Stiskněte **Ověřit veřejným testovacím dotazem**. UI musí přiznat, že odešle
   pevný dotaz `SearXNG`, a potvrdit počet bounded výsledků bez změny bindingu.
4. Uložte binding. Po restartu musí zůstat stejný endpoint, target, limit a
   revize. Pro privátní síť použijte číselné HTTPS a ověřený SHA-256 pin.

## Uživatelský průchod

1. Otevřete projekt, režim **Orchestrace** a lokální Ollama binding.
2. Zadejte požadavek vyžadující aktuální veřejné informace. Router má vrátit
   kartu **Návrh webového hledání**; v této chvíli nesmí odejít search GET.
3. Otevřete náhled. Zkontrolujte přesný dotaz, účel, privacy, endpoint, revizi,
   limit a seznam ID vstupů.
4. Bez zaškrtnutí potvrzení musí být dispatch zakázaný. Po potvrzení proběhne
   právě jeden search a následná Ollama syntéza.
5. Výsledek musí zobrazit odpověď, čas hledání a bounded zdroje. Titulky,
   snippets i URL jsou text; aplikace sama neotevře ani nestáhne žádnou stránku.

## Chybové a recovery scénáře

- `local-only` odmítnout před preview a před sítí.
- Nedostupnost, connect timeout, TLS/pin chyba, redirect, HTTP odmítnutí,
  neplatný nebo příliš velký JSON a neplatná URL skončí známým `failed`.
- Přerušení po odeslání skončí `unknown`; opakování stejného search ID nesmí
  vyvolat druhý dotaz.
- Nula výsledků je validní a nesmí aktivovat jiný search ani LLM provider.
- Duplicitní URL se objeví jednou; počet výsledků nepřekročí binding limit.
- HTML, script nebo instrukce ve snippetu se zobrazí jako text a Ollama je
  dostane výslovně označené jako nedůvěryhodná data.
- Změna SearXNG bindingu nebo project HEAD po preview se odmítne před dispatch.
- Po pádu po `succeeded` search a před syntézou restart použije stejné uložené
  výsledky. Po pádu po Ollama odpovědi použije stejný synthesis run.
- Smazání vlákna s `prepared`, `dispatching` nebo `unknown` search je blokované;
  po terminálním stavu potvrzené deletion recovery odstraní task, search i
  navázané backend runy a zachová publikovanou Git historii.
