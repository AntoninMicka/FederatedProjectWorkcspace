<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Webové hledání a podmínky providerů

Workspace hledá třemi způsoby:

- **Vždy vyhledat na webu** (režim Úkol) používá vlastní SearXNG službu: viz
  [akceptace SearXNG](searxng-search-acceptance.md). Dotaz sestaví model z vybraných
  vstupů; na kartě ho vidíte, můžete upravit a před odesláním potvrzujete. Když model
  použitelný dotaz nevrátí, předvyplní se text zadání a karta na to upozorní. Externí
  backend dotaz sestaví až po náhledu a potvrzení externího odeslání; výsledky vždy
  zpracuje Ollama, bez ní se hledání nespustí.
- **Uvažovat s možností dohledání** (režim Úkol, jen Ollama) používá stejnou službu
  a kartu, ale model sám rozhodne, zda hledání vyžádá.
- **Model smí hledat na webu** (Volná konverzace, Claude, Grok, OpenAI) nechá hledat
  přímo providera, bez potvrzení jednotlivých dotazů. Gemini tuto volbu zatím nemá.

Hledání nepřebírá zvolený jazyk odpovědi; ten platí jen pro odpověď LLM. Překlad zdroje
pomocí LLM zatím není implementovaný. Chování vůči živým API providerů nebylo ověřené.

Údaje jsou ověřené v dokumentaci providerů k 2. 11. 2026. Ceny a podmínky se
mění, před použitím je ověřte v odkazech níže. Shrnutí není právní rada.

## Dva způsoby hledání

| | SearXNG přes Workspace | Autonomní hledání u providera |
|---|---|---|
| Kdo formuluje dotaz | model navrhne, Workspace zobrazí | model, bez zásahu Workspace |
| Kdy se dotaz odešle | po potvrzení nebo viditelném odpočtu | ihned, během generování odpovědi |
| Kdo dotaz vidí | SearXNG a jím použité vyhledávače | provider a jeho vyhledávací služba |
| Kontrola před odesláním | přesný náhled dotazu | žádná, dotaz je známý až z odpovědi |
| Cena | vlastní provoz | poplatek za hledání a tokeny výsledků |

## Podmínky jednotlivých služeb

| Provider | Cena | Omezení počtu hledání | Uchování dat | Trénování na API datech |
|---|---|---|---|---|
| Claude | 10 USD / 1000 hledání + tokeny výsledků | `max_uses` | ZDR dostupné po dohodě; hledání je způsobilé mimo Covered Models a mimo dynamické filtrování | ne bez výslovného svolení |
| Gemini (Gemini 3 a novější) | 5000 hledání měsíčně zdarma, pak 14 USD / 1000 | v dokumentaci nenalezeno; výchozí kvóta 1500 za den na projekt | 30 dní pro hledání (Grounding) | placené služby ne; neplacené ano, včetně lidské kontroly |
| Grok (xAI) | 5 USD / 1000 volání + tokeny | v dokumentaci nenalezeno | 30 dní; ZDR zapíná správce týmu a vypíná stavové Responses API | ne bez výslovného svolení |
| OpenAI | 10 USD / 1000 volání + tokeny výsledků | v dokumentaci nenalezeno | 30 dní abuse monitoring; ZDR s omezeními, viz níže | ne bez výslovného opt-in |
| Ollama | v dokumentaci neuvedeno | `max_results` jen pro výsledky jednoho volání (nejvýše 10) | v dokumentaci neuvedeno | v dokumentaci neuvedeno |

Starší modely Gemini (2.5 a dříve) se účtují za prompt, nikoli za dotaz.

### Claude

- Nástroj se přidá do požadavku Messages API; správce organizace jej může
  v konzoli vypnout nebo omezit domény. Vypnutí vrátí chybu 400.
- Výsledek obsahuje použité dotazy a citace. **Citace se musí zobrazit** u výstupu
  přímo ukázaného uživateli; při přepracování výstupu doporučuje dokumentace
  konzultaci s právníkem.
- Pokračování konverzace vyžaduje vrátit výsledky včetně `encrypted_content`
  beze změny. Dlouhý běh může skončit `pause_turn` a vyžaduje navazující požadavek.
- Modely Fable a Mythos (Covered Models) vyžadují 30denní uchování, ZDR pro ně
  neplatí. Dynamické filtrování (výchozí od verze `web_search_20260209`) není
  způsobilé pro ZDR; přímé volání zapíná `allowed_callers: ["direct"]`.

### Gemini

Podmínky hledání (Grounding with Google Search) jsou pro Workspace nejpřísnější:

- Výsledky se zobrazují **jen uživateli, který poslal prompt**, a to spolu
  s návrhy Google Search (nejvýše 5). Mezi odkaz a cílovou stránku nesmí vložit
  mezistránku a nesmí se sledovat kliknutí na konkrétní výsledek.
- Text výsledku lze uložit nejvýše na **2 roky** a jen pro hodnocení zobrazení,
  pro chat historii daného uživatele nebo dočasně pro zpřesnění odpovědi.
  Výsledky se nesmí cachovat, analyzovat ani se z nich nesmí učit.
- Pro aplikaci dostupnou uživatelům v **EHP, Švýcarsku nebo Spojeném království
  jsou povolené pouze placené služby**.
- Do neplacených služeb podmínky zakazují vkládat citlivé, důvěrné nebo osobní
  údaje, protože data mohou číst lidští kontroloři.

**Dopad na Workspace:** až bude hledání přes Gemini dostupné, výsledek zůstane jen
v RAM a nepůjde do Gitu ani federace. Dnes se nenabízí, protože není ověřené zobrazení
návrhů Google Search v požadované podobě.

### Grok (xAI)

- Nástroj `web_search` běží přes Responses API. Grok sám rozhoduje o hledání
  i procházení stránek. Domény lze omezit, nejvýše na 5 v jednom seznamu.
- Výchozí stavové Responses API ukládá prompty a odpovědi 30 dní. Zapnutí ZDR
  platí pro celý tým a odpovědi nesou hlavičku `x-zero-data-retention`.
- **Neověřeno přímo:** dodatek o zpracování osobních údajů (DPA) podle výsledků
  vyhledávání požaduje pro osobní údaje ZDR API. Stránku se nepodařilo načíst
  (HTTP 403); před použitím s osobními údaji ji přečtěte.

### OpenAI

- Použijte nástroj `web_search` v Responses API; `web_search_preview` je starší
  varianta a ignoruje `external_web_access`.
- **Citace musí být v rozhraní viditelné a klikatelné.**
- Dokumentace popisuje ZDR pro hledání jen nepřímo: hledání s živým přístupem na
  internet není způsobilé pro HIPAA ani BAA, režim jen z cache
  (`external_web_access: false`) ano, a to v ZDR projektu.
  Data předaná třetím stranám se řídí jejich pravidly.

### Ollama

- Ollama **nenabízí hledání provedené serverem během generování**. Model si
  nástroj vyžádá, volání provádí klient a výsledek vrací modelu; jde tedy
  o zpětné volání.
- Lokální instalace sama hledání neumí. Volá se `https://ollama.com/api/web_search`
  s API klíčem z účtu Ollama, takže **dotaz opouští lokální stroj**.

## Podmínky platné pro všechny providery

- Data `local-only` se k takovému backendu nesmějí dostat, protože dotaz sestavuje
  model z celého kontextu a nelze jej předem zkontrolovat.
- Výsledky jsou nedůvěryhodný text a mohou obsahovat instrukce pro model. Takový
  obsah může model navést k dalšímu dotazu, který vynese data z kontextu.
- Počet hledání určuje model, cena proto není dopředu známá.

## Co Workspace při hledání u providera dělá

Po zapnutí volby se zobrazí toto upozornění:

> Model bude hledat na webu sám. Dotazy vytvoří z kontextu tohoto požadavku
> a {provider} je odešle bez vašeho potvrzení. Hledání se účtuje zvlášť a řídí
> se podmínkami providera. Důvěrná a local-only data nelze takto použít.

Je-li nastavená Ollama a SearXNG, nabídne se vedle upozornění přepnutí na ně.

- Odpověď se uloží do chatu s odkazy na citované zdroje.
- Surové výsledky Claude jsou vidět jen v okně a po obnovení se nezachovají.
- U Grok a OpenAI se ukládá odpověď modelu jako výtah a odkazy.
- Běh, který skončí nejistým výsledkem, se automaticky neopakuje. Poplatek už mohl
  vzniknout.

Rozhodnutí a recovery popisuje [ADR 0066](adr/0066-provider-web-search-and-callback.md).

## Zdroje

- Claude: [web search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool),
  [uchování dat](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)
- Gemini: [hledání](https://ai.google.dev/gemini-api/docs/google-search),
  [podmínky](https://ai.google.dev/gemini-api/terms) (účinné od 23. 3. 2026)
- xAI: [web search](https://docs.x.ai/developers/tools/web-search),
  [ceny](https://docs.x.ai/developers/pricing),
  [zabezpečení](https://docs.x.ai/developers/faq/security),
  [DPA](https://x.ai/legal/data-processing-addendum)
- OpenAI: [web search](https://developers.openai.com/api/docs/guides/tools-web-search),
  [ceny](https://developers.openai.com/api/docs/pricing),
  [data](https://developers.openai.com/api/docs/guides/your-data)
- Ollama: [web search](https://docs.ollama.com/capabilities/web-search)
- SearXNG: [Search API](https://docs.searxng.org/dev/search_api.html),
  [bot detection](https://docs.searxng.org/src/searx.botdetection.html)
