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
