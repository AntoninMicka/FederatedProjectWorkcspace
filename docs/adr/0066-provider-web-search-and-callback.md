<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0066: Hledání u providera a zpětné volání do Workspace

- Stav: přijato uživatelem 2. 11. 2026; implementováno pro Claude, Grok, OpenAI
  a Ollama + SearXNG, nebylo ověřeno proti živým API providerů. Gemini není nabídnuté.
- Datum: 2026-11-02
- Dávka: `NEW-FA92ACE959-BATCH-1` (`TASK-1`, `TASK-3`)
- Mění: [ADR 0008](0008-context-and-publication-contracts.md) v tom, že webové
  hledání nesmí být modelový tool call
- Mění: [ADR 0045](0045-governed-automatic-search-dispatch.md) v tom, že `confidential`
  nesmí běžet v automatickém režimu
- Podklady: [podmínky providerů](../web-search-providers.md)

## Kontext

Workspace hledá jen přes SearXNG a každý dotaz před odesláním zobrazí. Uživatel
požaduje možnost nechat model hledat autonomně u podporovaného providera,
a v `TASK-3` hledání podle uvážení modelu přes zpětné volání. Podmínky providerů
se liší. Gemini nejvíce omezuje ukládání výsledků. Současné záznamy
(`BackendRuns.response`, `TaskOutcomes`, chat `messages`) ukládají odpověď na disk.

## Rozhodnutí

### Režimy hledání

| Režim | Backend | Dotaz odesílá | Kontrola před odesláním |
|---|---|---|---|
| Řízené hledání (dnešní stav) | Ollama + SearXNG | Workspace | náhled nebo odpočet |
| Zpětné volání (`TASK-3`) | backend s nástroji | Workspace přes SearXNG | podle privacy, viz níže |
| Hledání u providera (`TASK-1`) | Claude, Gemini, Grok, OpenAI | provider | žádná |

Ollama nemá hledání prováděné serverem, nabízí jen první dva režimy. `local-only`
data jsou ve všech režimech s webovým hledáním zakázaná, jako dosud.

### Zacházení s výsledky hledání u providera

| Provider | Odpověď a výsledky | Po restartu | Další zpracování v LLM |
|---|---|---|---|
| Gemini | jen RAM, včetně textu odpovědi | zmizí | zakázané |
| Claude | výsledky jen RAM; odpověď s citacemi se ukládá | výsledky zmizí, odpověď zůstane | za běhu ano, potom jen uložená odpověď |
| Grok, OpenAI | ukládá se stručný výtah a odkazy | výtah a odkazy zůstanou | výtah |

Výsledek v režimu RAM se nezapisuje do `BackendRuns.response`, `TaskOutcomes`,
chatu, Gitu ani exportů a nepřenáší se federací. Gemini výsledek se navíc nesmí
stát vstupem Context Manifestu: nelze jej vybrat jako kontext, přeložit ani
shrnout. Zobrazí se jen uživateli, který poslal prompt, spolu s návrhy Google
Search, jak vyžadují podmínky.

Pokud nelze návrhy zobrazit v požadované podobě, Workspace hledání přes Gemini
nenabídne. Současná CSP (`style-src 'self'`) dodaný HTML úryvek pravděpodobně
nepovolí; ověření je vstupní podmínkou Gemini části.

### Jazyk

Volba jazyka platí jen pro odpověď LLM. Hledání ji nepřebírá. Překlad zdroje je
ruční akce, označená jako strojová, a originál zachovává.

### Volba backendu

Hledání u providera zůstává dostupné. Workspace k Ollamě vede nenápadně:

- je-li nastavená Ollama a SearXNG, je v nové volbě hledání předvybraná;
- u externího backendu se vedle upozornění ukáže krátká nabídka přepnutí na Ollamu;
- nabídka se nezobrazí, pokud Ollama nebo SearXNG nejsou nastavené.

Povinné upozornění z manuálu se tím neoslabuje ani neskrývá, a externí možnost
není schovaná ani obtížněji dostupná.

### Zpětné volání a privacy

Zpětné volání používá `SearchRuns`, jejich budget a zákaz automatického opakování.
Dotazy z `public` a `project` kontextu smějí běžet automaticky v aktivovaném limitu.
Pro `confidential` se každý dotaz potvrzuje, protože nedůvěryhodný výsledek může
model navést k dotazu, který vynese data z kontextu. Totéž platí pro režim
hledání u providera: `confidential` kontext se do něj bez výslovné reklasifikace
nepředá, protože potvrzení dotazu tam není možné.

## Crash boundaries a recovery

| Hranice | Stav | Obnova |
|---|---|---|
| Pád před odesláním | běh `prepared`, síť nedotčena | běh lze zrušit nebo vědomě spustit |
| Pád během volání providera | běh `dispatching` nebo `unknown`, bez obsahu | žádné automatické opakování, poplatek mohl vzniknout; uživatel spustí nový běh |
| Odpověď přijata, režim RAM | běh `succeeded` jen s metadaty, obsah v RAM | po restartu viditelně „výsledek nebyl uložen“, nevydává se za chybu ani úspěch s obsahem |
| Odpověď přijata, Claude | výsledky RAM, odpověď uložena přes `TaskOutcomes` | pád mezi přijetím a uložením se chová jako `unknown` |
| Odpověď přijata, Grok, OpenAI | stejné jako Claude, obsah je výtah a odkazy | stejné jako Claude |

Běhový záznam drží stav, digest požadavku, počet hledání a citované odkazy, nikoli
surové výsledky ani dotazy. Protože Workspace dotazy nezná předem, audit je záměrně
neúplný. Surové výsledky backend po odpovědi nedrží: existují jen v odpovědi na první
potvrzení a v paměti okna. Opakované potvrzení, ztracená odpověď, obnovení okna
i restart je už nevrátí.

## Implementační upřesnění

- Přímé hledání je doplňková volba ve **Volné konverzaci** a u akce **Uvažovat**
  v režimu Úkol, ve výchozím stavu vypnutá. Request vždy prochází přesným náhledem
  a nejde použít se streamováním. Dotaz odesílá provider, ale spuštění celého běhu
  uživatel potvrzuje; bez vlastního potvrzení běží jednotlivé dotazy. V Úkolu odpovídá
  model textem, protože uložená odpověď nese povinné citace.
- Podporu určuje adaptér, nikoli model: Claude ji dokumentuje pro všechny modely,
  u Grok a OpenAI model bez podpory požadavek odmítne a běh skončí chybou.
- Claude používá základní verzi nástroje bez dynamického filtrování a s `max_uses` 5.
  Ukončení `pause_turn` se neobnovuje a běh skončí chybou.
- U Grok a OpenAI je „výtahem“ odpověď modelu; Workspace surové výsledky nepožaduje.
- `TASK-3` má akci **Uvažovat s možností dohledání** pro všechny backendy v režimu Úkol.
  Výchozí je zpětné volání: model odpoví, nebo vyžádá jedno hledání, a to prochází
  stávající kartou. Kolo se spustí ručně; automatický odpočet si u `public` a `project`
  dat volí uživatel na kartě. Nejde o tool calling, požadavek je JSON v odpovědi. Backend
  bez JSON režimu (Claude) vrací stejný JSON přes textovou roli a tolerují se ohraničení
  kódu. Výsledky hledání vždy zpracuje Ollama, nevrací se externímu modelu.
- Automatický režim hledání se u `confidential` nově odmítne při přípravě plánu i v UI;
  tím se uzavírá riziko z ADR 0045. Už běžící workflow se tím nemění.
- **Vždy vyhledat na webu** už neposílá text zadání jako dotaz. Plán nese
  `search_compose` a role `task-output-search-query-v1` vrací jen dotaz; dříve vytvořené
  plány s pevným `search_query` platí dál. Dotaz jde před náhledem upravit, úprava je
  jeden atomický zápis do `TaskOutcomes` a po připravení náhledu je zamčená. Nepoužitelná
  odpověď modelu vede k předvyplnění zadání s upozorněním; selhání spojení zůstává chybou.
- Externí model smí sestavit dotaz jen přes stávající náhled a potvrzení. Syntéza výsledků
  běží vždy na Ollamě a její nedostupnost se odmítne před připravením hledání.
  Pád po odpovědi providera a před zápisem karty řeší žurnál externího běhu: opakované
  potvrzení providera znovu nevolá.
- Vyhodnocení výsledků má uzavřené schéma s povolenými ID zdrojů. Instrukce obou režimů
  nesou datum vytvoření požadavku, takže je příprava běhu stabilní.
- Nefinální vyhodnocení (`intermediate`, `insufficient`) musí podle schématu uvést aspoň
  jeden důvod v `limitations`; finální žádný. Pokud model důvod přesto vynechá, použije se
  jeho zdůvodnění, protože běh se automaticky neopakuje. Výsledek ukládá důvody a zdůvodnění
  a odpověď je zobrazí; důvody vidí i model v historii kol. Chyby bez vyhodnocení modelem
  (nedostupné SearXNG, neplatný výstup modelu) zůstávají chybou běhu.
- Kola úkolů nejsou zprávy vlákna, proto se při zdroji **Aktuální konverzace** předává
  nejvýše 6 předchozích kol jako zprávy: zadání a odpověď, zkrácené. Místo výsledků hledání
  je jen dotaz a zástupný text, že výsledky nejsou součástí kontextu. Zrušená a selhaná
  kola se nepředávají, `local-only` kola se nepředávají externímu backendu a úprava souboru
  historii nedostává. Privacy kol zvyšuje privacy běhu. Historie je uložená v záznamu úkolu,
  takže opakované směrování a pozdější náhled používají tutéž.
- Schválení hledání dočasně nahrazuje celý widget zadání.
- Gemini zůstává nenabídnuté, dokud nebude ověřené zobrazení návrhů Google Search.
  Ukládání jen v RAM je pro něj rozhodnuté, ale neimplementované.

## Důsledky a otevřené otázky

- Omezený počet hledání je možný jen u Claude (`max_uses`). U ostatních providerů
  cenu omezí nejvýše tokenový limit a uživatel je na to upozorněn.
- Uživatelsky je potřeba rozlišit výsledek, který po restartu nezůstane.
- Zda výtah u Grok a OpenAI odpovídá jejich podmínkám, je ověřeno jen proti
  prostudované dokumentaci, nikoli proti celým obchodním podmínkám.
- Účast na Google podmínkách: platí 30denní uchování u Google i placená služba
  v EHP. RAM režim se týká jen Workspace.

## Reuse

**Reuse:** `SearchRuns`, Context Manifest, role a `DirectRuns`. **Adapt:** běhový
záznam o režim bez obsahu. **Reject:** druhý search journal; ukládání výsledku
Gemini v šifrované podobě, protože podmínky omezují i samotné uložení.
