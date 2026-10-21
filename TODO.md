<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — V-11 / release 0.1.0

Aktivní release dávka připravuje první veřejné vydání `0.1.0` z aktuálního
`develop` po akceptovaném faceliftu. Skutečná větev je `release/0.1.0`, základ
je commit `9fb4262` (PR #72) a cílem předávacího PR je `main`. Stará vzdálená
větev `release/0.1.0-prep` je plně obsažená v `develop` a nepoužije se ani
nepřepíše.

Rozsah vydání je omezený na deterministický zdrojový archiv a nebundlovaný
Linux `.deb`, jehož runtime závislosti dodává operační systém. Dávka nepřidává
AppImage, kontejner, vlastní Python/Qt/Chromium runtime, podepsaný repozitář ani
automatické aktualizace a neoznačuje PoC za production-ready. Tag `v0.1.0`,
GitHub Release, push, PR a merge se provedou pouze po samostatném výslovném
souhlasu nad ověřeným kandidátem.

- [x] [completed] **V-11-A — jediný kontrakt verze a release balíčků
  (cílová úroveň: implemented).** Zavést jediný validovaný údaj `0.1.0`, použít
  jej jako výchozí verzi `.deb`, propsat jej do verzovaného názvu a kořene
  zdrojového archivu a testy odmítnout nesoulad či neplatnou verzi. Zachovat
  explicitní `--version` pouze pro vědomé sestavení jiného kandidáta. Soubor
  `VERSION` je jediný výchozí zdroj; explicitní kandidátní verze se propíše do
  názvu/kořene, `.deb` control i obou vnitřních kopií `VERSION`.
- [x] [completed] **V-11-B — aktuální distribuční a compliance review
  (cílová úroveň: designed → PoC validated).** Znovu inventarizovat dnešní
  allowlist source/`.deb`, provenance, notices a nebundlované runtime
  závislosti. Uzavřít novou závislost Segno pro skutečný cílový profil a
  oddělit historický audit commitu `128928e9` od kandidáta 0.1.0. CE-01 zůstane
  otevřené do sestavení finálních artefaktů z přesného čistého commitu.
  Allowlist má 257 regulárních UTF-8 souborů plus generovaný manifest a bez
  binárního/vendovaného payloadu; Ubuntu 26.04.1 arm64 poskytuje Segno jako
  `python3-segno 1.6.6-2` s BSD-3-Clause notice.
- [x] [completed] **V-11-C — release notes a uživatelské předání
  (cílová úroveň: implemented).** Přidat changelog/release notes s hlavními
  schopnostmi, podporovaným distribučním rozsahem, instalací/upgrade cestou,
  známými limity a bezpečnostními hranicemi. Nevymýšlet DOI, archivní ID,
  autory ani stav cílových ověření. Přidány `CHANGELOG.md`, veřejný release
  checklist a aktualizované příklady sestavení/instalace v README.
- [ ] [in progress] **V-11-D — kandidát a regresní důkazy
  (cílová úroveň: PoC validated).** Na finálním diffu spustit úplnou sadu,
  balicí/licenční testy a relevantní desktopový/dpkg smoke. Z čistého přesného
  commitu vytvořit source archiv a `.deb`, ověřit manifest, obsah/control,
  notices a SHA-256 a zaznamenat platformu a výsledky bez soukromých údajů.
  Po opravě dvou vazeb rozšířeného desktop smoku prošlo 667 testů, 27 opt-in
  scénářů bylo přeskočeno; samostatně prošel rozbalený WebEngine smoke i
  izolovaný `.deb` install/upgrade/start/purge se zachováním dat. Preflight
  obou artefaktů a 257 položek manifestu prošel, ale jeho hashe nejsou release
  důkaz: čistý commit `ecacde57` při sběru přesného runtime inventáře odhalil,
  že `python3-segno 1.6.6-2` je architekturně nezávislý balík `all`, nikoli
  `arm64`. Oprava evidence čeká na navazující commit a nové čisté sestavení.
- [ ] [planned] **V-11-E — doručení veřejného vydání
  (cílová úroveň: implemented).** Po uživatelském potvrzení kandidáta pushnout
  release větev, otevřít jediný PR `release/0.1.0 -> main`, po jeho merge
  vytvořit immutable tag `v0.1.0` na přesném release commitu a odpovídající
  GitHub Release s ověřenými artefakty a hashi. Bez těchto důkazů netvrdit, že
  vydání existuje.

## Podmínky dokončení

- verze, názvy balíčků, `.deb` metadata, release notes, tag a hashe si
  neodporují;
- oba artefakty vzniknou ze stejného čistého release commitu a source manifest
  odpovídá skutečným bajtům;
- aktuální distribuční set projde SPDX, provenance, notices a licenčními
  kontrolami pro deklarovaný nebundlovaný rozsah;
- úplná sada a relevantní instalační/desktopové kontroly mají skutečný
  zaznamenaný výsledek; neprovedené cílové testy zůstávají přiznané;
- zveřejnění, tag a merge se neprovedou bez samostatného potvrzení uživatele.
