<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Zachování odmítnutého zadání — CHAT-SUBMISSION-RECOVERY-01

Uživatel 22. 11. 2026 ohlásil odmítnutí posledního zadání obecnou zprávou
„nelze provést“ a ztrátu jeho textu. Původní text ani jednoznačný odpovídající
záznam se nepodařilo dohledat. Příčina konkrétního odmítnutí není potvrzená.
Starší providerové chyby nejsou důkazem příčiny nového případu.

Následný konkrétní případ ze snímku už byl dohledán v zachyceném pokusu:
„doplň seznam úkolů o úkoly pro návrh a implementaci sw agenta pro správu
sw a nastavení uzlu sítě“. Při úpravě projektového seznamu byly vybrané
také důvěrné vstupy. Kontrola `File edit cannot lower the privacy of its
context` odmítla požadavek ještě před spuštěním modelu. Nešlo o velikost
dokumentu ani o neplatný modelový výstup. Toto zjištění nedokládá příčinu
původního nedochovaného zadání.

Konflikt nyní vrací stejný typovaný důvod v HTTP i streamu a ukáže úroveň
soukromí cílového souboru a vstupů. Nabídka **Použít jen cílový soubor a
zadání** výslovně odebere ostatní soubory, konverzaci a veřejné zdroje.
Text zadání, cílový soubor a jejich soukromí zachová. Model nespustí;
uživatel zkontroluje vstupy a znovu stiskne Zpracovat. Pokud je samotné
zadání citlivější než cíl, tato nabídka není dostupná. Změněný kontext
se před použitím znovu kontroluje. Ochrana před snížením privacy zůstává
v backendu i při pozdějším náhledu a potvrzení. Starší uložený obecný důvod
se rozpozná podle přesného otisku pouze při čtení, bez přepisování receiptů.
Generovaný návrh se nadále ukládá až po kontrole ve společném editoru
a výslovném potvrzení diffu.

Na následný výslovný požadavek uživatele byla doplněna i druhá možnost:
**Provést i přes omezení**. Po samostatném souhlasu spustí nové zpracování
se všemi vybranými podklady a výjimku připne k přesnému plánu; změna vstupů
ji zneplatní. Klasifikace původních podkladů se nemění. Finální uložení
výsledku má nadále vlastní potvrzení, které ukáže ochranu cíle a výjimku.
Editory dokumentů, plánu/položek a prezentací nyní umožňují měnit ochranu
celého souboru; Julia používá potvrzovanou volbu pro celý svůj balík.
Snížení vyžaduje souhlas a zůstává v auditu. Podrobnosti a obnova:
[ADR 0089](adr/0089-explicit-document-privacy-review.md).

Při čtení a reprodukci byly ověřeny samostatné mezery: formulář má limit
16 000 znaků, ačkoli backend přijímá až 1 MiB; úspěšná odpověď bezpodmínečně
maže i text rozepsaný během běhu; odmítnutí před `TaskOutcomes.prepare`
nevytvoří běžnou historii zadání. Výběr aktuálního souboru se navíc blokoval
jen pro OpenAI, přestože stávající explicitní task plán odmítá projektové
artefakty u všech externích execution typů. Oprava nezavádí nové oprávnění
k odesílání projektových podkladů externím providerům.

## Uživatelský průchod

Formulář už neřeže vložený text na 16 000 znaků. Před odesláním ověří
existující backendový limit 1 MiB v UTF-8; větší text ponechá ve formuláři
a žádný model nespustí. Nemění providerové tokenové či časové rozpočty.

Před validací plánu a modelovým účinkem handler pro `/v1/tasks/route`,
`/v1/chat/send`, `/v1/external/send` a jejich stream varianty uloží pokus.
Podmínkou je platná základní identita, text do 1 MiB, privacy, registrovaný
a právě čitelný projekt. Nepovolené nebo nebezpečné vstupy nejsou důvodem
k uložení cizích dat. Chyba trvalého uložení zastaví zpracování před dispatch;
UI nesmí tvrdit, že je zadání uložené.

Sekce **Neúspěšná a neověřená zadání** u promptu ukáže nejvýše 50 posledních
nedokončených pokusů daného uživatele a projektu. Přehled obsahuje jen krátký
náhled, nikoli 50 plných dlouhých promptů. **Obnovit text zadání** načte přesný
uložený text; nevytvoří nový běh, nepřepne projekt ani nepřevezme starý Context
Manifest či backendový výběr. Nahrazení jiného rozepsaného textu se potvrzuje.
Privacy formuláře se zachová nebo zpřísní na privacy pokusu; nezmění se
implicitně z local-only/confidential na project/public. Vstupy a výsledek
je před novým odesláním nutné zkontrolovat.

**Smazat uložený text** po potvrzení odstraní obsah pokusu a ponechá pouze
malý identifikační receipt `discarded`, aby jej pozdní odpověď nebo replay
neoživily. Nevymaže nynější rozepsaný formulář a nezastaví modelový běh.
Jde o oddělenou místní evidenci vstupu, nikoli o smazání běžné chatové
historie nebo již předaných dat u providera.

Úspěšné odeslání vyprázdní formulář pouze při stále stejném projektu,
pracovním vláknu a textu odeslaného zadání. Nově psaný text ponechá.
Neodeslaný koncept není touto opravou automaticky ukládaný. Původní již
ztracené zadání ani starší chybějící pokusy se zpětně nevytvoří.

## Autorita, privacy a diagnostika

`ChatAttempts` adaptuje existující soukromý `TaskOutcomes` SQLite journal
v `.<node-filename>.chat/task-outcomes.sqlite`, tabulka `chat_attempts`.
Není to projektový index, druhý plán, projektový artefakt ani modelový
run journal. Přidání tabulky při prvním zachycení nemění existující outcomes;
read-only přehled starého store bez tabulky vrátí prázdný seznam.

Identita je dvojice ID pokusu / autentizovaný uživatel uzlu. UUID je původní
task/turn/run ID a příslušné ID se zachová i při stream/nonstream replayi.
Otisk původního požadavku brání použití stejné identity pro jiné zadání.
Ukládá se jen text promptu, jeho privacy a omezená identifikační metadata,
nikoli celý request, credential, obsah vybraných souborů nebo raw výjimka.
Privacy se konzervativně zvýší podle validovaných metadat projektu, stejně
jako u task-work záznamů. Čtení znovu ověřuje uživatele, projekt a trust
boundary; web neposkytne desktopový local-only prompt. Uživatel se neurčuje
z těla requestu. Tabulka není součástí projektového Git ani chat sync payloadu.

Diagnostika nese ID pokusu, stav, kód známého důvodu, třídu výjimky,
basename modulu / řádek a SHA-256 důvodu. Neobsahuje raw text výjimky,
cestu v souborovém systému, token ani prompt. Známé validace mají konkrétní
bezpečný popis; neznámá výjimka se nevydává za odhalenou příčinu.
HTTP odmítnutí po zachycení vrátí také `request_id` a `prompt_saved`.

Stejný `/v1/tasks/list` vrací `attempts` pro vlastní oprávněný projekt.
Volitelný `attempt_id` vrací jen odpovídající plný prompt a prázdné outcomes;
nezakládá další modelové nebo projektové API s odlišnými pravidly přístupu.
Varianta `/v1/tasks/cancel` s `project_id` a `attempt_id` odstraní pouze
uložený text vlastního pokusu; původní cancel podle `task_id` zůstává oddělený.
Úspěšný pokus ztratí duplikovaný text a ponechá malý receipt, aby pozdější
odmítnutý replay neoživil záznam. Běžná úspěšná historie zůstává v původním
TaskOutcomes/ChatThreads. Neúspěšné texty zůstávají v soukromém lokálním
journalu i po reloadu a restartu; limit 50 je limit přehledu, nikoli mazání.

## Crash boundaries

Platí původní autority [ADR 0003](adr/0003-coordinated-operation.md) a
[ADR 0088](adr/0088-task-work-context.md). Nativní projektový zápis ani
providerový journal se nezaměňuje za evidenci pokusu.
Zúžení vstupů mění jen formulář; nepřidává persistentní vrstvu. Následná
úprava používá původní CAS, potvrzení a nativní journal podle těchto ADR.

| Hranice | Chování |
| --- | --- |
| Před commitem zachycení | Model ani plánový writer nezačaly. Selhání uložení zastaví dispatch; text zůstane ve formuláři. |
| Lokální commit / před validací či modelem | Pokus je `unknown`; po restartu lze obnovit text, nikoli usuzovat, že model běžel. |
| Validace / známé odmítnutí | Pokus je `failed` s bezpečnou diagnostikou; text zůstává dostupný. |
| Běh / přerušení / ztracený výsledek | Původní run ID a `unknown`; žádný automatický replay, změna modelu nebo zvýšení rozpočtu. |
| Nativní úspěch / před finalizací pokusu | Nativní journal a uložený výsledek jsou autorita; starý pokus může zůstat konzervativně `unknown`. Nedělá se z něj automaticky nový účinek. |
| Finalizace / ztracená HTTP odpověď | Receipt je completed a neobnoví ho odmítnutý souběžný replay. Úspěšná historie již obsahuje původní zadání. |

SQLite writer se nedrží přes projektový writer, síť ani model. Selhání
sekundární finalizace nezmění úspěšnou nativní odpověď na výzvu k opakování.
Procesové testy nejsou simulací fyzického výpadku napájení.

## Ověření

Izolované testy `tests.test_chat_attempts`, `tests.test_chat_attempts_http`
a `tests.test_chat_attempts_browser` ověřují procesový pád, pre-validation
odmítnutí, owner/privacy hranice, bezpečnou diagnostiku, přesný replay,
selhání capture bez dispatch, dlouhý český text a skutečný restart lokálního
backendu s novým originem i prohlížečovým profilem. Obnovení nezavolá model.
Další průchod ponechá nový text zapsaný během starého běhu. Modely jsou
loopback testovací náhrady; původní uživatelská chyba ani živá akceptace
tohoto opravného řezu tím nejsou prokázané.

Navazující test konfliktu soukromí používá stejné české zadání a ověřuje
odmítnutí před modelem, výslovné zúžení vstupů, jeden následný modelový běh,
kontrolu v editoru a potvrzené rozšíření validní roadmapy. Původní ID,
soukromí cíle a obsah důvěrného podkladu zůstávají zachované. HTTP/stream
mají shodný důvod; čtení starší diagnostiky nemění uložený receipt.
