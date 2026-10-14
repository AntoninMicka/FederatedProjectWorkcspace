<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-SEARCH-02 — Inteligentní iterativní vyhledávání

Původ: roadmapa sekce 3C/F-M3 a připravená dávka v BACKLOGu. Cílová úroveň:
**designed → PoC validated**. Aktivní větev:
`feature/f-m3-search-02-iterative-search`, základ a cíl jediného PR: `develop`
na merge commitu PR #66 `3466a5f`.

## Rozsah feature

Nad explicitně potvrzovaným SearXNG tokem F-M3-SEARCH-01 přidat bounded
iterativní workflow. Ollama po každém kole vrátí uzavřené hodnocení `final`,
`intermediate` nebo `insufficient`, použitá source ID, omezení, odpověď a
případné navazující dotazy. Každé kolo zůstane viditelné a durable se svým
search/LLM během, Context Manifestem a parent/child vazbou.

Mimo rozsah je automatické odesílání navazujících dotazů, countdown a obecná
autonomie F-M4-AUTONOMY-01, automatické otevírání výsledků, crawler/RAG,
externí LLM fallback a vytvoření projektového artefaktu. Každý další dotaz
vyžaduje stejné explicitní potvrzení jako první kolo.

## Persistentní hranice a recovery

Autoritou síťového účinku zůstává jediný node-local `SearchRuns` SQLite
journal a autoritou každého modelového účinku jediný `OllamaRuns` journal.
Workflow/round metadata se přidají do stejné search databáze; nevznikne druhý
search journal. Search `dispatching` nebo `unknown` se automaticky neopakuje.
Po `succeeded` se znovu použijí uložené bounded výsledky, po úspěšném evaluatoru
stejný modelový run a teprve durable evaluation uzavře kolo. Pád před
TaskOutcomes completion nesmí vyvolat druhý search ani LLM dispatch.

## Úkoly

- [x] [completed] **F-M3-SEARCH-02-A — Iterační kontrakt, reuse a ADR
  (designed).** Upřesnit uzavřené evaluator schéma, source ID, budgety,
  parent/child vazbu, manuální potvrzení a crash/recovery hranice.
- [x] [completed] **F-M3-SEARCH-02-B — Durable workflow a evaluator
  (implemented).** Rozšířit SearchRuns o atomický workflow/round stav,
  validovat modelový výstup a zachovat idempotentní search i Ollama recovery.
- [x] [completed] **F-M3-SEARCH-02-C — Sdílené API/UI mezivýsledků
  (implemented).** Zobrazit všechna kola, hodnocení, zdroje, omezení, budget a
  ručně potvrzované follow-up dotazy v desktopu i webu.
- [ ] [in progress] **F-M3-SEARCH-02-D — Regrese, dokumentace a fyzická akceptace
  (PoC validated).** Ověřit finální první kolo, užitečný mezivýsledek,
  nedostatečné/rozporné zdroje, vyčerpaný budget, restart a úplnou provenance.

## Aktuální výsledek a ověření

- **Aktivace 2026-10-14:** PR #66 je v `develop`; větev vznikla z `3466a5f`.
  Reuse směřuje na `AITaskOutcome`, `TaskOutcomes`, `ContextBuilder`, jediný
  `SearchRuns`/`OllamaRuns` journal a společné desktop/web UI.
- **Implementace 2026-10-14:** uzavřený evaluator ukládá `final`,
  `intermediate` nebo `insufficient`, stabilní source ID, omezení a nejvýše tři
  navržené follow-up dotazy. Workflow má nejvýše 3 kola, 3 dotazy, 30 výsledků
  a 300 sekund; každé nové kolo vyžaduje samostatný preview a potvrzení.
- **UI a recovery 2026-10-14:** karta bezpečně zobrazuje všechna kola, bounded
  zdroje, hodnocení, provenance a budget. Restart obnoví mezivýsledek bez
  druhého dispatch; deletion plán odstraní všechna kola a evaluator runy.
- **Ověření 2026-10-14:** cílené testy pokrývají ruční follow-up, restart,
  falešné source ID, zakázaný `final` s follow-upem, vyčerpání třetího kola a
  deletion recovery. Úplná sada `python3 -m unittest discover -s tests -v`:
  549 testů OK, 24 přeskočených volitelných fyzických testů. `git diff --check`
  bez chyb. Zbývá fyzická akceptace podle `docs/searxng-search-acceptance.md`.
- **Fyzické zjištění 2026-10-14:** první pokus odhalil, že evaluator používal
  textový `researcher-v1`, přestože nový kontrakt vyžaduje JSON. Opraveno na
  explicitní JSON roli `researcher-v2` a konkrétní UI diagnostiku. Neplatný
  succeeded modelový run se bezpečně neopakuje; fyzický retest nového hledání
  zůstává otevřený.
- **Fyzické zjištění 2026-10-14, pokračování:** JSON evaluator dokončil běh,
  ale Gemma vrátila jediné `limitations` jako text místo seznamu. Přidána úzká
  normalizace neprázdného textu na jednoprvkový seznam; uložený succeeded run
  lze po restartu znovu vyhodnotit bez opakování search nebo Ollama dispatch.
  Recovery již dokončených účinků smí doběhnout i po vypršení 300sekundového
  budgetu; limit nadále blokuje každý nový search nebo nový evaluator dispatch.
- **Fyzické zjištění 2026-10-14, směrovač návazného hledání:** `task-router-v1`
  správně zvolil `web-search`, ale při nulovém výběru projektových artefaktů
  vrátil jedno vymyšlené artifact UUID. Bezpečná normalizace nyní vynutí
  autoritativní prázdný seznam pouze pro `web-search` bez vybraných artefaktů;
  cizí UUID při skutečném výběru i v jiném druhu požadavku nadále fail-closed.
- **Fyzické zjištění 2026-10-14, ruční zpřesnění:** evaluator označil obecné
  odkazy jako `final`, ačkoli současně přiznal chybějící konkrétní jízdní řád;
  následný text v composeru pak bez search kontextu skončil jako nesmyslná
  přímá odpověď. `final` s omezením se nyní konzervativně mění na
  `intermediate` a ručně napsané zpřesnění v composeru připraví další kolo
  stejného workflow. Síťový dotaz se nadále odešle až po kontrole a potvrzení.
  UI nyní při chybějícím modelovém návrhu výslovně ukazuje, kam vlastní
  zpřesnění napsat, používá odpovídající placeholder a netvrdí, že návrh
  existuje. Evaluator má také explicitně zachovat jazyk focus požadavku.

## Podmínky dokončení

- Modelové `final` je viditelně označený úsudek, nikoli garance pravdivosti;
  použité source ID musí odkazovat jen na skutečné výsledky daného workflow.
- Každé kolo, dotaz, zdroje, hodnocení, omezení, parent/child vazba a přesný
  Context Manifest zůstávají dohledatelné po restartu.
- Limity kol, dotazů, výsledků a času jsou viditelné a fail-closed; změna HEAD,
  privacy, policy nebo bindingu a `unknown` účinek workflow zastaví.
- Žádný follow-up dotaz se neodešle automaticky; cílené testy, úplná sada,
  `git diff --check` a fyzická akceptace odpovídají dosaženému stavu.

## K předání do backlogu

Zatím bez nových odkladů.
