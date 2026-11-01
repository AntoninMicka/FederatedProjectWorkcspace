<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Společný rámec stránky

`spikes/page_layout.py` dodává společné záhlaví a tělo stránky do sdíleného
webového/desktopového shellu. Adaptuje existující DOM a navigaci; nepřidává
framework, druhý editor ani nový zápisový endpoint.

Rámec se připojuje pouze k panelům hlavních záložek a samostatným stránkám.
Nativní `dialog` není stránka: adaptér jej odmítne a zachová jeho formulář,
výchozí skrytí i otevírání v modálním režimu.

## Struktura

- Záhlaví obsahuje jeden nadpis a pod ním řádek akcí dané stránky.
- Tělo obsahuje seznam sekce, prohlížeč nebo editor. Samostatně se posouvá;
  záhlaví a chatová část nejsou součástí posouvaného souboru.
- Úvod Podkladů obsahuje seznam souborů; úvod Nástrojů seznam dostupných
  nástrojů. Ostatní sekce používají své stávající seznamy a specializované obsahy.
- Původní hlavní záložky pracovních nástrojů jsou dostupné pod
  **Nástroje → Další nástroje**. Nezabírají záhlaví každého dokumentu.

Adaptér `mountWorkspacePage` přijímá existující nadpis, uzly akcí, sekci pro
návrat, druh obsahu (`list`, `viewer`, `editor`, `page`) a výchozí režim chatu.
Akce se přesouvají jako původní uzly se svými listenery. U dokumentového a
Julia editoru zůstávají uvnitř původního formuláře, takže validace, FormData,
submit i retry používají stejné ovládací prvky a doménové operace.
Kontextové nástroje obsahu, filtry a akce jednotlivých formulářů v nastavení
zůstávají u příslušného obsahu; adaptér z nich nedělá globální akce stránky.

## Prohlížeč a editor

Výběr dokumentu, obrázku, PDF nebo definice výstupu nejprve otevře prohlížeč.
**Zavřít** vrací na výchozí stránku aktuální sekce a nezavírá projekt.
V záhlaví se **Editovat** nabízí jen pro podporovaný zapisovatelný dokument nebo
prezentaci; read-only projekt, obrázek, PDF a obecný JSON tuto akci nenabízejí.
U prezentací na webu zůstávají zachovaná dosavadní omezení editace.

Editor má v záhlaví **Uložit**, **Zavřít editor** a podporované režimy:
strukturovaný/raw pro plán a vizuální/raw pro prezentaci. Obecný Markdown a
Julia nedostávají nový předstíraný WYSIWYG režim. Zavření editoru používá
[ochranu neuložených změn](desktop-navigation.md) a vrací uložený soubor do
prohlížeče; zahozený nový koncept vede na seznam sekce.

Obsah souboru se kvůli layoutu nemění. Pokud je první Markdown H1 totožné
s názvem v záhlaví, potlačí se pouze jeho druhé vykreslení v náhledu. Metadata
zůstávají v rozbalovacích Podrobnostech. Stavové/chybové zprávy se zachovávají;
v editorech jsou průběžná a chybová hlášení na začátku těla stránky.
Trvalé štítky „otevřený projekt“ a „uložená verze / pouze pro čtení“ ustupují
obsahu. Read-only omezení projektu zůstává viditelné.

## Výchozí zobrazení chatové části

Stránka deklaruje `data-chat-default` na svém registrovaném kořeni:

| Hodnota | Chování |
| --- | --- |
| `full` | Dosavadní plný formulář zadání, včetně jeho ovládacích prvků. |
| `hidden` | Formulář se skryje, přepínače zobrazení zůstanou dostupné a rozepsané zadání se zachová. |
| `compact` | Ovladače zhruba ve dvoutřetinové velikosti leží uvnitř spodního okraje promptu, s popiskem vedle výběru; odesílání je uvnitř vpravo. |

Prohlížeče standardně používají `full`, editory `hidden`. Stránka může
výchozí hodnotu změnit bez zásahu do doménového backendu. Tři přepínače na
dělicí hraně jsou dostupné ve všech režimech. Ruční volba má přednost před
výchozími hodnotami stránek až do obnovení aplikace; neukládá se do projektu.
Přepnutí zachovává původní formulář, jeho ovladače, hodnoty i rozepsaný text.
Na užších displejích se kompaktní ovladače zalamují uvnitř promptu.
Existující `data-prompt-default` slouží
jen jako kompatibilní vstup pro dosavadní záložky; deklarace stránky má přednost.

## Reuse, persistence a ověření

Rámec reuse/adaptuje `openPreview`, `renderMarkdown`, `renderSlideVisual`,
`navigateSidebarTab`, sdílený raw widget a existující save callbacky podle
[ADR 0058](adr/0058-shared-raw-editor-and-pattern-catalog.md). Nový rich-text
framework, renderer aktivního HTML a univerzální save endpoint se nezavádějí.
Náhled prezentace používá validovaný deck jen při shodě projektového HEAD.
Uložený Markdownový formát prezentace se rozpozná pouze jako kandidát;
validaci a dekódování zajišťuje existující backendový adaptér. Bez validovaného
decku zůstává dostupný původní bezpečný textový náhled bez akce Editovat.
Po známé změně HEAD se seznam podkladů obnoví z projektového read modelu. Nesoulad HEAD nebo chyba
načtení ponechá chybovou zprávu a prázdný seznam, nikoli starý seznam vydávaný
za aktuální. Neprovádí se automatický retry uložené operace.

Rozložení, výběr stránky a režim chatu jsou jen v paměti. Crash boundaries se
nemění: před commitem rozhoduje existující doménový journal, po commitu lze
obnovit index z HEAD. Přesun tlačítka nezahajuje zápis a režim chatu nic
neodesílá ani neukládá.

Regrese: `python3 -m unittest tests.test_page_layout tests.test_workspace_navigation -v`.
Volba `M0_DESKTOP_TEST=1` navíc zapne izolovaný Qt/WebEngine smoke.
`WORKSPACE_LAYOUT_WIDTH=390` použije mobilní šířku. Jde o automatické DOM/layout
ověření s náhradním transportem, nikoli o akceptaci instalované aplikace.
