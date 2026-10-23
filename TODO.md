<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — UX-WEB-NAV-01 — webové kategorie Výstupy a Federace

Dávka byla 23. 10. 2026 aktivována na větvi
`feature/ux-web-nav-01` z `develop` na commitu `d15cec3` (PR #83). Cílem
jediného PR do `develop` je doplnit do serverového webu plnohodnotné navigační
kategorie Výstupy a Federace nad existujícími bezpečnými projekcemi. Dnešní
přechodové desktopové nástroje, nativní ovladače a nová zapisovací autorita se
na serverový web nepřenášejí.

- [x] [completed] **UX-WEB-NAV-01-A — webová informační architektura
  (cílová úroveň: designed → implemented).** Doplnit obě kategorie do
  sdílené navigace, vymezit jejich dostupnost bez/s otevřeným projektem a
  zachovat mobilní i klávesnicový kontrakt faceliftu.
- [x] [completed] **UX-WEB-NAV-01-B — bezpečné webové projekce (cílová úroveň:
  implemented → PoC validated).** Výstupy zobrazí existující projektové
  definice bez skrytého prohledání projektu. Federace zobrazí
  existující uzly, úrovně sdílení a projektovou matici bez credentials,
  soukromých klíčů nebo nativních transportních akcí.
- [ ] [in progress] **UX-WEB-NAV-01-C — ověření a předání (cílová úroveň: PoC
  validated).** Pokrýt webové API, UI stav, RBAC/privacy a regresní chování
  cílenými testy, spustit úplnou testovací sadu a aktualizovat evidence dávky.
  Automatické ověření 23. 10. 2026: **751 testů úspěšně, 28 přeskočeno**;
  změněné Python moduly prošly `py_compile`, generovaný webový JavaScript
  `node --check` a `git diff --check` je bez chyb. Zbývá fyzický průchod
  nasazeného serverového webu na široké a mobilní šířce: otevřít projektové
  Výstupy a správcovskou Federaci, ověřit klávesnicovou navigaci a absenci
  desktopových síťových/LXC akcí.

## Hranice a akceptace

- Výstupy a Federace jsou samostatné, dosažitelné webové kategorie ve
  stávajícím pořadí a vizuálním vzoru navigace.
- Výstupy vyžadují otevřený projekt; Federace je uzlová kategorie dostupná i
  bez otevřeného projektu.
- Web nepředstírá plnou správu funkcí, které zatím existují jen jako nativní
  desktopový workflow, a neobchází stávající RBAC, privacy ani potvrzení.
- Zobrazení funguje na desktopové i úzké šířce, klávesnicí a bez regresí
  současných sekcí.
