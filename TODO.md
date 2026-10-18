<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-FACELIFT-01

Feature dávka **UX-FACELIFT-01 — interaktivní facelift pro první release**
začala 2026-10-17 na větvi `feature/ux-facelift-01` z doručeného `develop`
`8b24452` (konsolidovaný reader a task routing, PR #71). Cíl PR je `develop`;
push, otevření PR ani merge této dávky zatím nejsou schválené. Cílová úroveň:
**designed → implemented → PoC validated**.

Rozsah je záměrně interaktivní: uživatel bude nad skutečnými obrazovkami a
papírovými anotacemi průběžně určovat priority, takže konkrétní vizuální změny
nejsou předem zmrazené. Dávka zůstává jednou ucelenou UI feature: smí měnit
informační hierarchii, rozložení, popisky a ovladatelnost sdíleného web/desktop
frontendu, nikoli přidávat nové backendové schopnosti nebo uvolňovat RBAC,
privacy, potvrzovací a recovery hranice. Každý implementovaný řez se před
zařazením ověří proti uživatelským anotacím a mobilní/klávesnicové paritě.

- [x] [completed] **UX-FACELIFT-01-A — A4 inventura všech formulářů
  (cílová úroveň: implemented).** Vygenerovat z aktuálního UI tiskový balíček
  všech webových formulářů, formulářových panelů, potvrzení a používaných
  nativních Qt dialogů. A4 může používat menší písmo či měřítko, ale popisky,
  pole, volby a hranice jednotlivých obrazovek musí zůstat čitelné a musí být
  ponechaný prostor pro ruční kreslení. Generátor musí selhat, pokud nový
  webový `<form id>` není v inventuře. Generátor nyní pokrývá 31 formulářových
  listů: všech 17 aktuálních HTML formulářů, další formulářové/potvrzovací
  panely a pět používaných nativních dialogů. Lokální výstup má 33 stran A4;
  zdrojový skript ani aplikační JavaScript se do PDF nevykreslují. Vizuálně byly
  zkontrolovány titulní strana, běžný formulář, vícestránkové CMS, editor
  prezentací a nativní dialogy. Reprodukovatelný postup a hranice drží
  `docs/ux-facelift-forms-a4.md`. Cílené tři testy inventury prošly; následná
  celá sada `python3 -m unittest discover -s tests -v` prošla **637 testy**,
  27 volitelných testů bylo přeskočeno. `pdfinfo` potvrdilo 33 stran formátu A4
  a `git diff --check` prošel bez chyb.
- [ ] [in progress] **UX-FACELIFT-01-B — ruční anotace a společná revize
  (cílová úroveň: designed).** Uživatel vytiskne nebo anotuje balíček; společně
  projdeme priority, přesuny, slučování a odstranění tření. Konkrétní scope
  změn vznikne z této revize, nikoli z automaticky domyšleného redesignu.
  První schválený řez revize určuje novou informační architekturu levého
  hlavního panelu:

  - panel vždy zobrazuje ve stejném pořadí záložky **Projekty**, **Chaty**,
    **Úkoly**, **Podklady**, **Nástroje**, **Výstupy** a **Nastavení**;
  - **Projekty** a **Chaty** jsou dostupné i bez zvoleného projektu, zatímco
    ostatní záložky se zpřístupní až po jeho zvolení;
  - **Projekty** obsahují tlačítko pro vytvoření projektu, tlačítko pro import
    projektu s NotebookLM jako jednou z importních možností a samostatně
    scrollovatelný seznam projektů;
  - **Chaty** přebírají současný seznam vláken a před ním zobrazují tlačítko
    **Nové vlákno**;
  - **Úkoly** a **Podklady** přebírají svůj současný obsah a chování;
  - nové **Nástroje** budou katalogem výpočetních a simulačních skriptů
    (například Julia). Nástroj může vzniknout jako výstup chatu, číst podklady
    i vybrané výstupy a vytvářet nové výstupy; tento řez zatím neurčuje nový
    spouštěcí backend ani persistence kontrakt;
  - **Výstupy** nyní obsahují prezentace a počítají s budoucími grafy a
    výstupy výpočtů;
  - **Nastavení** zobrazují samostatně scrollovatelný seznam jednotlivých
    nastavení.

  Před implementací ještě společná revize určí chování globálních Chatů bez
  zvoleného projektu a přesné položky seznamu Nástrojů a Nastavení; facelift
  sám nesmí potichu přidat novou schopnost spouštět výpočty ani změnit
  projektové, RBAC nebo privacy hranice.
- [ ] [planned] **UX-FACELIFT-01-C — iterativní implementace schváleného řezu
  (cílová úroveň: implemented).** Promítnout schválené anotace do jediného
  sdíleného frontendu a zachovat mobilní layout, klávesnicovou přístupnost,
  bezpečné textové vykreslení a aplikační autorizační hranice.
- [ ] [planned] **UX-FACELIFT-01-D — regresní a fyzická akceptace
  (cílová úroveň: PoC validated).** Ověřit dotčené desktopové i webové průchody,
  úzký viewport, klávesnici, potvrzení a finální fyzický průchod s uživatelem.

Akceptace celé dávky zůstává otevřená do dokončení interaktivní revize a
uživatelem schváleného implementačního řezu. Samotný A4 balíček dokončuje jen
položku A a není souhlasem s konkrétním redesignem.
