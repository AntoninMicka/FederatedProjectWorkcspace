<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# MON-08-11 — posouzení X/Twitter konektoru

Datum ověření veřejné dokumentace: **12. 11. 2026**.
Úroveň tohoto podkladu: **designed**, bez API dispatch, přihlášení,
útraty či aktivace konektoru. Přístup konkrétního účtu a jeho aktuální
limity nebyly ověřeny. Není to důkaz PoC ani lidská akceptace úkolu.

## Dostupné rozhraní a cena

Oficiální [Search Posts](https://docs.x.com/x-api/posts/search/introduction)
popisuje recent search za posledních sedm dnů a samostatný full-archive search.
Recent search má stránkování, nejvýše 100 příspěvků v odpovědi a běžný limit
dotazu 512 znaků. Vyžaduje schválený developer účet, projekt/aplikaci a token.
[User timeline](https://docs.x.com/x-api/posts/timelines/introduction)
umožňuje číst až 3 200 posledních příspěvků konkrétního uživatele.
Přístup k seznamům by byl další samostatně ověřovaný scope; zde není přislíben.

Podle aktuálního [ceníku](https://docs.x.com/x-api/getting-started/pricing)
se předplacené kredity čerpají podle použití; čtení příspěvku stojí
0,005 USD za vrácený resource. Například 100 nových položek denně po 30 dnů
odpovídá 15 USD jen za tato čtení, bez dalších operací a poplatků. Nejde
o cenovou garanci ani změřenou spotřebu. Konkrétní sazby a budget musí
uživatel zkontrolovat v konzoli před aktivací.
[Rate limits](https://docs.x.com/x-api/fundamentals/rate-limits) jsou samostatné
omezení podle endpointu a způsobu autentizace; cena není limit počtu requestů.

## Navržený oddělený řez

První implementační rozsah: výslovně vybraný účet nebo recent-search dotaz,
read-only, bez streamu, interakcí a automatického full-archive přepnutí.
Před aktivací zobrazit přesný účet/dotaz, interval, stránkovací limit,
očekávané maximum čtení a budget. Token zůstane v node-local credential slotu.
Budget, scope a místní souhlas musí projít kontrolou před dispatch.
Nedostupný endpoint, chybějící token, 429 nebo unknown neznamená prázdný
úspěšný nález ani oprávnění přejít na scraping, xAI search nebo jiný provider.

Normalizace adaptuje `fpw-source-item-v1`, stabilní post ID a původní datum.
Oprava je nová obsahová revize stejné identity. Smazání či explicitně omezený
přístup má samostatný stav; nepřítomnost ve stránce výsledků sama nedokládá
smazání. [Batch Compliance](https://docs.x.com/x-api/compliance/batch-compliance/introduction)
je kandidát pro sledování změn dostupnosti, nikoli zde implementovaný cleanup.
Před uložením musí být posouzeny retence, licence a následné odstranění
textu ve všech spravovaných kopiích. Samotný hash není důkaz pravdivosti.

Příspěvek zůstává nedůvěryhodným signálem. Potvrzená událost vyžaduje původní
evidence workflow; počet sdílení ani shrnutí LLM ji nevytvoří.
RSS, interní zdroje a tvorba zpráv fungují bez tohoto konektoru.

Reuse/adapt: společný source kontrakt, pool deduplikace, explicitní filter
provenance, node-local credentials a durable effect journal. Reject:
automatický alternativní sběr, druhá synchronizační databáze a ukládání
credentials do definic. Ve zdroji zůstává `platform-channel` unavailable;
jeho odmítnutí bez RSS fallbacku ověřuje `tests.test_source_connectors`.

Přechod k PoC vyžaduje výslovný výběr rozhraní, oprávněný přístup a budget.
Tento návrh není požadavek na nákup kreditů ani povolení účtovaného volání.

## Připravený neověřený řez 16. 11. 2026

Na výslovnou žádost uživatele vznikla
[implementace PoC bez testování](x-connector-poc.md): samostatný `x-twitter`
adaptér, místní odběry a budget, ruční placený read do existujících poolů,
trvalé operation ID a lokální odstranění surových kopií. Obecný
`platform-channel` zůstává unavailable. Veřejné pricing a reference endpointů
byly znovu přečteny 16. 11. 2026; konkrétní API účet nebyl použit.
Původní návrh automatického intervalu v tomto prvním neověřeném řezu
nahrazuje pouze explicitní ruční spuštění. Tento implementační krok sám
nebyl ověřením ani uzavřením úkolu. Následnou lidskou akceptaci a integrační
regresi shrnuje [review MON-08](mon-08-review.md); živé X API zůstává neověřené.
