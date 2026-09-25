<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Demo presenter: gamepad driver patch

## 1. Cíl demo

Ukázat, jak patch pro Linux gamepad driver přidává základní podporu pro ovladač typu joystick/gamepad do aplikace nebo desktopového prostředí s nízkou integrační zátěží.

Tento konkrétní patch pracuje se zařízením přes `udev` a `evdev`, detekuje layout ovladače, odvozuje osy pro pohyb, spouští overlay klávesnice a umožňuje simulaci myši a kláves pro přístupnost a alternativní ovládání.

---

## 2. Krátký příběh pro prezentaci

"V jednom projektu jsme potřebovali podpořit gamepad jako běžné vstupní zařízení pro desktopové aplikace. Místo hardcoded mapování pro jediný model ovladače jsme přidali automatickou detekci zařízení a přizpůsobení layoutu podle skutečných `input` os a tlačítek. Výsledek je univerzální vstupní vrstva, která najde levý/pravý stick, trigger, D-pad a propojí ho s existujícím UI event systémem."

---

## 3. Co patch přidává

### 3.1. Detekce zařízení přes udev

Patch rozšiřuje build konfiguraci o knihovny `udev` a `evdev` a přiřazuje je do projektu:

- přidá hledání knihoven ve build systému,
- vynutí kompilaci s definicí `WITH_UDEV`,
- připojí zdrojové soubory pro správu gamepadu,
- naváže linkování na `Pkg::udev` a `Pkg::evdev`.

To je důležité, protože Linux zařízení neřešíme jen jako obecný `stdin`, ale jako konkrétní HID/joystick event stream.

### 3.2. Autodetekce layoutu ovladače

V `EvdevGamepad` se čtou data z `/dev/input` event zařízení, zjišťují se ABS osy a následně se odvozují:

- levý stick: `ABS_X` / `ABS_Y`,
- pravý stick: `ABS_RX` / `ABS_RY`, `ABS_Z` / `ABS_RZ` nebo varianty `ABS_THROTTLE` / `ABS_RUDDER`,
- levý a pravý trigger: osy typu trigger,
- D-pad: buď přes `ABS_HAT0X` / `ABS_HAT0Y`, nebo přes tlačítka typu `BTN_DPAD_*`.

To umožňuje přístup i pro různé gamepady bez ručního hardcoded mapování.

### 3.3. Režim ovládání a emulace vstupu

Patch navíc propojuje gamepad s komponentami pro:

- simulaci kláves a myši,
- vykreslení overlay klávesnice,
- zpracování osových dat přes pravidelný timer,
- přepínání mezi joystick mode a alternativním přístupovým režimem.

Z pohledu demo je to klíčová část: gamepad se nepoužívá jen jako input pro hru, ale jako vstupní rozhraní pro obecnou aplikaci.

---

## 4. Proč je to užitečné

### Business value

- přístupnost pro uživatele bez klasické klávesnice nebo myši,
- kompatibilita s více typy joysticků na Linuxu,
- snadnější integrace do desktopových aplikací,
- méně manuálních konfigurací u různých zařízení.

### Technická hodnota

- přidává robustní vrstvu nad Linux `evdev` API,
- sleduje skutečné hardwarové vlastnosti zařízení,
- používá deklarativní mapování namísto statických konstant pro jeden model.

---

## 5. Ukázka demového scénáře

### Demo flow (2–3 min)

1. Zahájení prezentace: "Na Linuxu máme několik joysticků, ale každý má jiné ABS osy. Potřebujeme generickou vrstvu."
2. Ukázat, že patch detekuje ovladač přes udev a event interface.
3. Popsat, jak se odvozuje layout ovladače z hodnot `ABS_*`.
4. Předvést, že se D-pad a spouštěče rozpoznají bez přesného modelu.
5. Ukázat, že data mohou být převedena do myš/klávesní emulace přes overlay a tlačítka.
6. Uzavření: "Výsledek je zařízení-agnostický input abstraction, které může sloužit pro UX, přístupnost i jednoduché hraní."

---

## 6. Rizika a omezení

- patch je založený na Linux specifických API, takže není zcela multiplatformní,
- `udev` a `evdev` musí být dostupné v cílovém prostředí,
- autodetekce může být citlivá na neobvyklé nebo nekompletní HID mapování,
- pokud zařízení nepublikuje standardní ABS hodnoty, bude nutná ruční korekce layoutu.

Toto je vhodné uvést jako "good engineering baseline, not final universal HID abstraction".

---

## 7. Co by následovalo dál

- přidat konfiguraci slotů a mapování pro jednotlivé modely,
- exportovat standardní mapping profile pro gaming i accessibility mode,
- otestovat více zařízení a edge cases (wired, wireless, emulované střední zařízení),
- rozšířit event pipeline o deadzone a smoothing pro analogové osy,
- oddělit input abstraction od UI akce a zlepšit přenositelnost do dalších projektů.

---

## 8. Shrnutí pro presenter

"Tento patch není jen o gamepadu. Je to ukázka robustního přístupu k hardware input API: detekce zařízení, statické mapování z metadat, adaptivní layout a konverze do univerzálního UX event stream. To je přesně ten druh řešení, který se dá znovu použít i v jiném projektu."

## 9. Displeje řečníka a diváků

Po otevření presenteru se zobrazí nativní dialog **Displeje a role prezentace**.
Vyberte displej pro řečníka (ovládání a soukromé poznámky) a jiný displej pro
publikum (pouze schválený slide). Čísla odpovídají indikátorům na obrazovkách;
indikátory ukazují navrhovanou roli, po čtyřech sekundách zmizí a lze je znovu
zobrazit tlačítkem **Identifikovat displeje**. Změny platí až po **Použít role**.

Výchozí volba je **Bez promítání**; hodí se i pro nácvik na jednom monitoru.
Veřejné okno se otevře přes celou zvolenou obrazovku, řečníkovo okno se
maximalizuje na jeho displeji. Nastavení lze znovu otevřít tlačítkem
**Displeje a role…** v presenteru. Zrušení dialogu ponechá veřejné okno skryté.

Připojení, odpojení nebo změna geometrie displejů během prezentace skryje
veřejné okno a nabídne nové přiřazení. Zavření presenteru skryje promítání a
obnoví původní geometrii hlavního okna. Role žijí jen po dobu běhu aplikace;
restart vyžaduje nový výběr. Pro oddělené zobrazení nastavte v systému rozšířenou
plochu: zrcadlení displejů aplikace nevypíná. Umístění oken může omezovat správce
oken, zejména na Waylandu; fyzické zapojení je nutné před přednáškou vyzkoušet.

## 10. Základní editor prezentací

Otevřete **Prezentace…** v horní liště desktopu nebo **Editor prezentací…**
v panelu promítání. Editor používá aktuální projekt; pokud žádný není otevřený,
nabídne výběr z registrovaných projektů. Nový projekt založte běžným projektovým
ovládáním. V horním seznamu editoru lze přepínat uložené prezentace nebo založit novou.

- Přidávejte hlavní slidy a backupy. Každý slide má nadpis, odrážky (jednu na
  řádek), soukromé poznámky, barvu pozadí, barvu textu a volitelnou tapetu.
  **Zobrazení odrážek** volí všechny řádky najednou nebo postupné odhalování.
  **Povolit opakované promítnutí** výslovně povolí opětovné nabízení slidu.
- Tapetu vyberte z místního PNG/JPEG/WebP souboru. Editor vloží zmenšenou PNG
  kopii do prezentace; pozdější přesun původního obrázku ji neporuší. Tapeta
  překrývá barvu pozadí, po jejím odebrání je barva opět vidět. Síťové URL ani
  SVG se nepoužívají.
- V záložce **Vazby** upravte **Next** nebo **Previous**. Změna přesune slide
  v hlavní linii a opačný směr dopočítá automaticky. Volba „Konec“ přesune
  aktuální slide na konec, „Začátek“ na začátek. Hlavní linie nemá cykly.
- U hlavního slidu zaškrtněte jeho backupy. U backupu lze stejnou vazbu upravit
  z opačné strany v **Backup pro / návrat k**. Jeden backup může patřit k více
  hlavním slidům; výchozí návrat v presenteru vede ke slidu, odkud byl vyvolán.
  Nepřiřazený backup zůstává dostupný v celkové knihovně. Odstranění slidu
  odstraní jeho vazby; poslední hlavní slide odstranit nelze.
- **Uložit do projektu** uloží celý deck v jedné projektové operaci a vytvoří
  jeho verzi v Gitu. Samotné psaní, náhled a uložení nemění divácký výstup.
  **Spustit uloženou prezentaci** zahájí novou relaci presenteru z uložené
  verze a nabídne role displejů. Neuložený koncept spustit nelze.

Při chybě uložení zůstává koncept i identita operace v editoru. Tlačítko
**Opakovat stejné uložení** opakuje tutéž operaci; nevytváří další commit po
ztraceném potvrzení. **Znovu načíst** po potvrzení opuštění konceptu obnoví
případnou připravenou operaci a načte aktuální projekt. Při změně HEAD se cizí
úpravy nepřepisují. Po restartu aplikace otevřete uloženou prezentaci z editoru
znovu; pozice a dočasná cesta presenteru se neukládají.

Jde o základní desktopový editor: nejvýše 100 slidů, 12 odrážek po 500 znacích,
256 KiB vložené tapety na slide a přibližně 1 MiB na celý dokument. Při importu
má obrázek nejvýše 10 MiB a 8192 pixelů v každém rozměru; editor jej zmenší
nejvýše na 960 × 540 a podle velikosti dále. Dlouhý obsah je nutné zkrátit nebo
rozdělit do více slidů. Editorový náhled je 16:9, presenter přebírá poměr
projekčního displeje. Nejde o plný graf zanořených scénářů, animace ani editor PPTX.

### Formát a ukládání

Deck je běžný projektový dokument `artifacts/<id>/content.md` s blokem
`fpw-presentation-v1` obsahujícím JSON a metadaty spravovanými existujícím
editorem artefaktů. Každý slide má stabilní UUID, typ `main`/`backup`, `title`,
`bullets`, `notes`, `background`, `foreground`, `wallpaper`, `next` a `backups`.
Volitelná pole `repeat` (boolean, výchozí `false`) a `reveal` (`all` nebo `step`,
výchozí `all`) určují přehrávání; starší dokumenty zůstávají čitelné.
`Previous` a opačné přiřazení backupu jsou odvozené pohledy, nikoli druhá kopie
stejné vazby. Formát není export pro publikum: obsahuje i poznámky a backupy.
Divácké API vrací pouze vizuální obsah výslovně promítnutého slidu.

Zápis adaptuje `Artifacts.save` → `Workspace.transact`; crash boundaries,
serializace zápisů a recovery zůstávají podle
[ADR 0003](adr/0003-coordinated-operation.md). Validace editoru před zápisem
ověřuje ID, cíle vazeb, souvislou hlavní linii, barvy a limity. Ručně poškozený
dokument se v editoru označí jako neplatný a automaticky se neopravuje.
Tento formát nerozšiřuje obecný validátor projektových dokumentů o celé schéma
prezentace; nejde o dokončení Disclosure Presenter MVP z roadmapy 22C.

## 11. Výběr a postup během prezentace

Levá páčka vodorovně vybírá další slide z dostupné hlavní linie. Náhled je
soukromý; promítnutí potvrďte tlačítkem **A** (tlačítko 0 standardního gamepadu)
nebo **Zobrazit další slide**. Pravá páčka mění záložky a výběr backupu.
Každé gesto vyžaduje návrat do neutrální polohy; držení tlačítka neopakuje akci.
Šipka doprava a tlačítko **Další** promítnou právě vybranou možnost.

Vybraný hlavní slide se přesune za aktuální pozici v dočasném pořadí.
Přeskočené slidy zůstávají na později. Již dokončený slide se bez povoleného
opakování nenabízí a nelze jej znovu promítnout ani navigací zpět; pravidlo
platí také pro backupy. Výjimkou je návrat z backupu: výchozí další volba
je slide, ze kterého byl backup otevřen, i když byl již dokončen.
Výběrem jiného slidu lze tento návrat přeskočit.

V postupném režimu první promítnutí ukáže první odrážku. Další potvrzení
přidá jednu odrážku a ponechá předchozí viditelné. Po odbočce se pokračuje
následujícím dosud neodhaleným řádkem; nedokončený slide zůstává dostupný.
Po posledním řádku se bez povoleného opakování vyřadí. Výjimečný návrat z backupu
na již dokončený slide ukáže všechny jeho řádky. Opakování odhalené řádky
neresetuje. Prázdný slide se dokončí prvním promítnutím.

Počet odhalených řádků a navštívené slidy platí pro jednu relaci. Nové spuštění
nebo reload je vynuluje; uložený deck se navigací nemění. Selhání potvrzení
výstupu neposune místní postup; při ztracené odpovědi zkontrolujte veřejné okno.
