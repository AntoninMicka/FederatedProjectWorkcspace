<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Behaviorální testy UI místo testů zdrojového textu (AUDIT-B7-T1)

Stav: **implemented**, čeká na review. Úkol AUDIT-B7-T1 řeší nález B-ODD-04
z [auditu B1](audit-b1-locks-versions-oddities.md#nálezy-b-odd). Zdrojová
větev je `feature/audit-b4-error-states`, protože uživatel 20. 11. 2026
výslovně povolil řešit dávky B4 až B7 v jedné větvi a jednom PR. Rozsah
(pět největších toků) a spouštění v CI zvolil uživatel téhož dne.

## Harness: headless Chromium bez nových závislostí

[`tests/browser_harness.py`](../tests/browser_harness.py) řídí Chromium nebo
Chrome přes DevTools protokol na `--remote-debugging-pipe`. Používá jen
standardní knihovnu Pythonu.

- Stránku i assety servíruje skutečný desktopový `running_api`
  s `DesktopManagementHandler`. Hlavičky a Content Security Policy jsou tedy
  skutečné.
- Každý požadavek `/v1/*` posoudí skutečná desktopová `request_policy`, stejně
  jako interceptor Qt. Ta rozhodne, zda se připojí nativní token.
- Požadavek pak jde na skutečný backend. Služby zapojí
  `attach_desktop_services` ze [`spikes/desktop.py`](../spikes/desktop.py),
  takže test i aplikace sdílejí stejné zapojení. Funkci jsem kvůli tomu
  vyjmul z `main()` beze změny chování.
- Stavy, které se těžko vyvolají (chyby, „unknown“, externí poskytovatelé),
  odpovídá skriptovaný `FakeApi`. Skript, který vrátí `None`, předá požadavek
  skutečnému backendu.
- Test čte odeslané požadavky (cesta, tělo, token, HTTP stav, tělo odpovědi)
  a výsledný DOM, ne zdrojový text UI.
- Harness dál obsluhuje nativní dialogy `alert`/`confirm` (zaznamená text a
  odpoví jako uživatel), zaznamenává nativní akce přes `location.hash` (to,
  co čte Qt), sleduje rozpracované síťové požadavky (`wait_idle`) a zachytává
  výjimky stránky.

[`tests/fake_providers.py`](../tests/fake_providers.py) poskytuje loopback
HTTP fake Ollamy (`/api/tags`, `/api/generate` včetně NDJSON streamu,
`/api/ps`) a SearXNG (`/search`). Skutečné adaptéry s nimi mluví přes HTTP,
takže test pokrývá cestu UI → API → služba → adaptér. Žádný požadavek neopustí
počítač a nic se nezapisuje mimo dočasný uzel. Generování a nasazení
publikačního CMS jsou proto skriptované, protože skutečné generování zapisuje
do `modules.local`.

[`tests/ui_flow_case.py`](../tests/ui_flow_case.py) vytvoří pro každý test
nový uzel s projektem a nabízí uživatelské akce: otevřít projekt a chat,
odeslat prompt, kliknout podle textu.

### Reuse

- **Playwright, Selenium a podobné knihovny: zamítnuto.** CI instaluje jen
  `requirements.txt` a nová testovací závislost by vyžadovala rozhodnutí.
  DevTools pipe pokryje potřebné minimum bez ní.
- **Stávající testy ve Qt WebEngine (`M0_DESKTOP_TEST=1`): ponechány,
  nerozšiřovány.** Potřebují PySide6 a v CI neběží.
- **Testy v Node se stuby: ponechány.** Nemají DOM ani backend.
- **Harness: vlastní řešení** v rozsahu jednoho testovacího modulu.

### CI

Prohlížeč se hledá přes `FPW_BROWSER` nebo na `PATH` (google-chrome,
chromium, chromium-browser). Bez prohlížeče se testy lokálně přeskočí. V CI
nastavuje [`ci.yml`](../.github/workflows/ci.yml) `FPW_REQUIRE_BROWSER=1`,
takže chybějící prohlížeč znamená selhání, ne tiché přeskočení. Runner
ubuntu-24.04 má Chrome předinstalovaný; **to ověří až první běh CI**, lokálně
ověřeno nebylo. Při `CI=true` harness přidá `--no-sandbox`, protože Ubuntu
24.04 omezuje jmenné prostory, které sandbox Chromu potřebuje. Stránky jsou
lokální testovací data. Shardy objevují moduly `test_*.py` automaticky.

## Převedené toky

| Původní test zdrojového textu | Aserce před → po | Behaviorální náhrada |
|---|---|---|
| `test_web_search_ui_requires_exact_preview_and_renders_sources_as_text` | 92 → 6 | [`test_ui_web_search_browser.py`](../tests/test_ui_web_search_browser.py) |
| `test_presentation_ui_and_backend_are_exposed` | 80 → 38 | [`test_ui_presenter_browser.py`](../tests/test_ui_presenter_browser.py) |
| `test_presentation_editor_is_integrated_in_shared_workspace` | 36 → 12 | [`test_ui_presentation_editor_browser.py`](../tests/test_ui_presentation_editor_browser.py) |
| `test_node_settings_are_global_and_backend_form_is_not_duplicated` | 84 → 35 | [`test_ui_node_settings_browser.py`](../tests/test_ui_node_settings_browser.py) |
| `test_chat_ui_uses_authenticated_api_and_explicit_message_selection` | 375 → 65 | [`test_ui_chat_browser.py`](../tests/test_ui_chat_browser.py), [`test_ui_backend_settings_browser.py`](../tests/test_ui_backend_settings_browser.py), [`test_ui_workspace_browser.py`](../tests/test_ui_workspace_browser.py) |

Ponechané aserce jsou kontrakty: ID prvků, na které spoléhá JS a nativní
vrstva, seznamy rout (`post_paths`), shoda servírovaných assetů, pythonový
payload veřejné obrazovky a absence nativních dialogů Qt. U chatu zůstaly
i kontroly serverových hlášek v Pythonu, protože nejde o zdrojový text UI.

Odstraněné aserce se nepřevádějí jedna za jednou. Skupina asercí, která
popisovala jedno chování, má jeden behaviorální test tohoto chování:

- **Webové hledání:** dotaz odejde až po přesném náhledu a potvrzení, nedůvěryhodné
  výsledky zůstanou textem, obnova konfigurace, zpřesnění dalšího kola,
  autonomní plán s potvrzením a odpočtem, veřejný zdroj až po schválení,
  pořadí časové osy, popis výzkumných kroků, jednorázová obnova workflow bez
  dalšího kroku.
- **Presenter:** promítání, poznámky, náhled dalšího snímku, klávesnice, zálohy
  se soukromým náhledem a expozicí, návrat, ukončení relace, rozvržení
  (sloupce 15 % / 25 %, obrazovka 16:9), gamepad, veřejná obrazovka bez
  poznámek a s poměrem stran.
- **Editor prezentací:** uložení do projektu, seznam ve výstupech, spuštění,
  dvousloupcové rozvržení, export PDF přes nativní výběr cíle, výběr displejů
  a kontrola, že **každá funkce, kterou Qt volá přes `runJavaScript`, na
  stránce existuje**.
- **Nastavení uzlu:** prvky jen pro desktop, oprava a odebrání nedostupného
  projektu, obnova přerušené operace, výběr umístění nového projektu,
  navigace nastavení, uložení Ollamy, publikační CMS (povolení, sandboxovaný
  náhled, generování podle digestu, nasazení bez uchování tokenu).
- **Chat:** stream s textovým vykreslením, připnutí k nabídce, explicitní
  kontext vlákna, nový běh po odmítnutí a stejná operace po nejasném výsledku,
  vypnutí streamu, nové vlákno, obnova vlákna po znovuotevření, otisk a výstup,
  archivace, smazání a jeho zrušení, orchestrace, externí model (local-only
  se neodešle, odeslaný request, odmítnutý stream mimo historii, ruční náhled,
  potvrzení privacy, návrh Ollamy).
- **Formuláře backendů:** OpenAI a AtlasCloud bez uchování klíče, test Ollamy
  bez uložení, otisk certifikátu, obnova po neúspěšném uložení, profil,
  pevná dostupnost desktopu.
- **Pracovní prostor:** postranní panel a nástroje projektu, kompaktní režim,
  pořadí akcí, dashboard, monitor prostředků, dokument s historií a porovnáním,
  mazání dokumentu, hlavní TODO, import zdroje.

## Chyby nalezené behaviorálními testy a jejich opravy

Uživatel rozhodl opravit je v této větvi. Každá má test, který bez opravy
selže; ověřeno dočasným vrácením opravy.

1. **`ProjectCreation.author_id()` bral pro čtení výhradní zámek uzlu.**
   Souběžné stavové dotazy (například při otevření nastavení) dostávaly
   `503 resource busy` s `busy_resource: node-operations`, nastavení se
   nenačetlo a UI ukázalo holé „resource busy“. Nově se autor čte přes SQLite
   jen pro čtení. Řádek vzniká jednou v potvrzené transakci pod zámkem
   a nemění se. Bez journalu, bez řádku, při horkém journalu nebo jiné chybě
   SQLite zůstává původní zamčená cesta, která autora vytvoří nebo obnoví.
   Hranice pádu se nemění. Test: `tests/test_project_creation.py`.
2. **Po „Uložit otisk“ nebo „Uložit poslední odpověď“ chat zmizel.**
   `runChatRecord` znovu otevřel projekt a vybral záložku, ale chat nenačetl.
   Nově chat načte a ponechá hlášku o výsledku.
3. **Po zrušení náhledu smazání vlákna zůstalo „Připravit smazání“
   zablokované.** Tlačítko se odblokuje i po úspěšném náhledu.
4. **Systémově: 45 asynchronních obsluh četlo `event.currentTarget` po
   `await`**, kdy je už `null`. Obsluha spadla s `TypeError` a tlačítko
   zůstalo zablokované (například „Náhled externího volání“ po použití nebo
   potvrzení hledání po chybě). Mechanická úprava zachytí prvek před prvním
   `await`. Statická kontrola [`tests/test_ui_event_handlers.py`](../tests/test_ui_event_handlers.py)
   běží v CI i bez prohlížeče a hlídá, aby se vzor nevrátil.

### Regrese z AUDIT-B6-T1 na webu

Po nasazení hlavy větve hlásilo webové přihlášení „request rejected“. AUDIT-B6-T1
odstranil skryté tlačítko `#presentation-editor`, ale webový bootstrap
(`WEB_JS` v `spikes/web_server.py`) ho dál skrýval. Skript tak spadl dřív,
než zaregistroval obsluhu přihlášení. Formulář se pak odeslal nativně jako
`GET` s přístupovým klíčem v URL a server ho odmítl. Testy desktopu webový
bootstrap nespouštějí, proto chybu nezachytily.

Oprava:

- Odkaz na odstraněný prvek je pryč.
- Webová CSP je sjednocená s desktopem na `form-action 'none'`. Případně
  rozbitý skript tak klíč do URL nikdy nepošle. Web nativně odesílané
  formuláře nepoužívá, `method="dialog"` CSP neomezuje.
- Harness umí webovou variantu (`BrowserPage(web=True)`): skutečný
  `make_server` přes TLS na loopbacku s vygenerovanou testovací CA.
- [`tests/test_ui_web_login_browser.py`](../tests/test_ui_web_login_browser.py)
  ověřuje přihlášení a odmítnutí chybného klíče bez opuštění stránky.
  Statická kontrola, že oba bootstrapy odkazují jen na existující prvky,
  běží v CI i bez prohlížeče.

**Doporučení:** přístupový klíč použitý při selhaném přihlášení mohl zůstat
v historii prohlížeče a v adresním řádku. Pokud to vadí, vyměňte ho.

## Další zjištění (neopraveno, k rozhodnutí)

- `closeSettings()` (návrat z nastavení na původní záložku) volá jen smoke
  test v `spikes/desktop.py`. V UI na ni nevede žádný ovládací prvek,
  uživatel odchází přes záložky postranního panelu.
- Při chybě `503` s `busy_resource` zobrazuje chat holé „resource busy“
  bez vysvětlení, že jde o přechodný stav. Jiné části UI mají pro
  `busy_resource` srozumitelné hlášky.
- Hlavička presenteru ukazuje pevný ukázkový text („Demo workspace ·
  Ukázková schůzka“) i pro vlastní deck uživatele.

## Odklad

V `tests/test_desktop.py` zůstává asi 222 asercí zdrojového textu
(145 JS, 31 CSS, 46 HTML mimo ID) v 19 menších testech. Patří k tokům mimo
zvolenou pětici: rozložení promptového widgetu a přehledu projektu, revize
roadmapy, průběh chatu, řešení konfliktů, Julia, Google Picker, obrazové
a extrakční toky, NotebookLM, role workflow, koš projektů a metadata.
Navrhuji je převést v samostatné dávce stejným harnessem.

## Omezení

- Externí poskytovatelé (OpenAI, AtlasCloud, Cloudflare) a načtení veřejné
  stránky jsou skriptované. Testy ověřují chování UI a požadavky, ne
  skutečnou integraci s poskytovatelem.
- Harness simuluje Qt jen v rozsahu `request_policy`, nativních akcí přes
  `location.hash` a volání `runJavaScript`. Nenahrazuje smoke test ve
  skutečném WebEngine (`M0_DESKTOP_TEST=1`).
- Vzácný souběh, který jsem v testech webového hledání viděl dřív, měl
  příčinu v chybě 1. Pro případný další výskyt hlásí aserce
  `assert_prompt_status` stav a tělo odpovědi trasy.

## Ověření

- Nové behaviorální testy v Chromiu: 8 modulů, všechny procházejí lokálně.
- `tests/test_ui_event_handlers.py`, `tests/test_project_creation.py`
  a `tests/test_desktop.py` procházejí.
- Celá sada se spustí před PR.
