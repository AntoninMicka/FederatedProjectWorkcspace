<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Navigace a neuložené změny

Rozložení záhlaví, prohlížeče/editoru a chatové části popisuje
[společný rámec stránky](page-layout.md).

Hlavní navigace přepíná levý panel i hlavní stránku. Z nastavení, historie,
importu, tvorby či opravy projektu a koše lze odejít výběrem jiné sekce.
Spodní odkazy Zpět se nepoužívají. Stejné přechody fungují kliknutím
i klávesami pro přepínání záložek. Navigace zůstává dostupná také v presenteru;
odchod uzavře relaci stávajícím postupem.

Výběr sekce vždy otevře její výchozí hlavní stránku. **Projekty** zobrazí
úvodku otevřeného projektu, nebo úvodní přehled, pokud žádný projekt otevřený
není. Přepínání sekcí, obnovení katalogu, koš, import ani kontrola jiného
projektu otevřený projekt nezavírají. **Plán** se vrací na hlavní graf,
**Nástroje** na přehled bez detailu modelu a **Výstupy** na přehled definic.

V panelu **Plán** otevírá **Fronta úloh** samostatnou stránku. Náhled roadmapy
frontu neobsahuje; její obnova, opětovné ověření a předání do IDE jsou v záhlaví
stránky fronty. Zavřít vrací na hlavní roadmapu a kliknutí na položku fronty
otevře její detail v roadmapě. Skutečně existující podgrafy zůstávají dostupné
v rozbalovacích **Výřezech roadmapy** u grafu; prázdná nabídka se nezobrazuje.
Fronta používá původní API, revizní kontroly, potvrzení odebrání a read-only
omezení. Přesun stránky nevytváří další frontu ani zápisovou cestu.

Roadmapa má filtr, export a stav v úsporném záhlaví. Graf vyplňuje zbytek
stránky a posouvá se ve vlastním rámu. Detail se objeví až po výběru položky,
posouvá se samostatně a lze jej zavřít pro zvětšení grafu. Na úzkém displeji
jsou graf a detail nad sebou, stále s nezávislým posouváním. Detail nepoužívá
styly boční navigace a celá stránka roadmapy se neposouvá.

Odeslání promptu otevře hlavní stránku i panel Chaty přes společnou ochranu
editorů. Průběh a výsledek sledují posouvané tělo stránky chatu. Při ručním
posunutí ke starším zprávám se automatické sledování pozastaví.

Akce **Zavřít projekt** je v projektovém panelu mezi Importem a Košem.
Bez otevřeného projektu je vypnutá. Zavření používá stejnou ochranu
neuložených změn jako ostatní navigace. Výběr jiného projektu dosavadní
projekt nahradí; výslovné odstranění otevřeného projektu jej také zavře.

Dokumentový/TODO editor, Julia editor, editor prezentací a řešení konfliktů
sdílejí dialog při neuložených změnách:

- **Zrušit přechod** zachová editor i vybranou sekci. Totéž provede Escape.
- **Uložit a přejít** nejprve validuje a uloží obsah stávající doménovou
  operací. Teprve úspěšná odpověď povolí přechod. Neplatný obsah nebo chyba
  uložení ponechá editor otevřený s rozepsaným obsahem a chybovou zprávou.
- **Zahodit a přejít** odstraní lokální draft bez nového zápisu do projektu.

Nezměněný editor ani editor, jehož obsah byl vrácen do původního stavu,
dialog neotevírá. Samotné načtení nové šablony není úprava. Při neověřeném
výsledku zápisu zůstává ochrana aktivní; opakované uložení používá původní
operation ID. Zahodit draft neznamená vrátit případný již dokončený commit.

Probíhající síťový nástroj či nasazení dovoluje přepnout jinam. Návrat do
probíhajícího nástroje zachová jeho stav a nevyvolá nový běh.

Řešení adaptuje existující shared shell a doménové save callbacky podle
[ADR 0058](adr/0058-shared-raw-editor-and-pattern-catalog.md). Nepřidává
další storage, journal ani obecný save endpoint. Crash boundaries a recovery
doménových operací zůstávají stejné: před commitem rozhoduje journal, po
commitu lze obnovit index z HEAD. Draft a navigační dialog jsou pouze v paměti.

Zavření či obnovení celého browserového okna nadále chrání nativní
`beforeunload` dialog prohlížeče; třícestný dialog patří přechodům uvnitř aplikace.

Automatická regrese: `python3 -m unittest tests.test_workspace_navigation -v`.
Izolovaný test skutečného Qt/WebEngine shellu lze zapnout pomocí
`M0_DESKTOP_TEST=1`; transport nahrazuje fixture a neověřuje živý uživatelský
profil ani backendové transakce.
