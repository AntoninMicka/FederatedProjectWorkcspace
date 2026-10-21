<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Release 0.1.0 — veřejné vydání

Veřejné vydání bylo publikováno 2026-10-21. Tag `v0.1.0` ukazuje na merge
commit `3ebdc40d0a0caf03d31850875fe847c3f0202185` PR #74 v `main`. Autoritativní
verze zůstává v `VERSION`; níže jsou dokončené kontroly a přesné hashe veřejných
artefaktů. Build proběhl na Ubuntu 26.04.1 LTS arm64 s Pythonem 3.14.4; strom
merge commitu je shodný s validovaným stromem čistého kandidáta `d24ad26`.

## Rozsah kandidáta

- source archiv `federated-workspace-poc-0.1.0.tar.gz`;
- nebundlovaný Debian balík `federated-workspace-poc_0.1.0_all.deb`;
- ruční update channel popsaný v README;
- žádný AppImage, container image, wheel/venv bundle, model ani Qt/Chromium
  runtime uvnitř artefaktů.

## Před sestavením

- [x] release větev vychází z akceptovaného `develop` a pracovní strom je čistý;
- [x] `VERSION`, changelog, názvy artefaktů a `.deb` control uvádějí `0.1.0`;
- [x] aktuální distribuční allowlist, SPDX, provenance, notices a dependency
  register byly znovu posouzeny proti přesnému kandidátnímu commitu;
- [x] skutečný cílový runtime obsahuje a dokládá Segno 1.6.6;
- [x] nejsou přítomné credentials, privátní katalog, lokální projekty ani
  neveřejná release evidence.

## Ověření kandidáta

- [x] `python3 -m unittest discover -s tests -v`;
- [x] balicí a licenční testy včetně skutečného `dpkg-deb`;
- [x] relevantní skutečný desktop/WebEngine a dpkg lifecycle smoke;
- [x] source archiv je reprodukovatelný a každý člen odpovídá
  `MANIFEST.sha256.json`;
- [x] `.deb` control, obsah, notices, spouštěč, instalace, upgrade a odstranění
  odpovídají dokumentovanému rozsahu;
- [x] oba artefakty vznikly ze stejného čistého commitu a jejich SHA-256 jsou
  zaznamenané spolu s build platformou.

## Publikace

- [x] uživatel schválil konkrétní kandidát a jeho omezení;
- [x] PR `release/0.1.0 -> main` prošel CI a byl sloučen;
- [x] tag `v0.1.0` ukazuje přesně na schválený release commit;
- [x] GitHub Release obsahuje changelog, oba ověřené artefakty a SHA-256;
- [x] release metadata neuvádějí neexistující DOI, archivaci ani dokončenou
  produkční či cílovou akceptaci.

## Veřejné artefakty

- `federated-workspace-poc-0.1.0.tar.gz` —
  `8e6c73f85dbc53f77cdbddfe3dd90da7f376ca2cb72cc43b18de1cb391bfb012`;
- `federated-workspace-poc_0.1.0_all.deb` —
  `783a651e1939a1308c18514f3b911726ecaf0cf09e527d5918a2fd6be5cad984`.

Po publikaci byly oba artefakty z GitHub Release znovu staženy a ověřeny proti
publikovanému `SHA256SUMS`. Release je dostupný na
<https://github.com/AntoninMicka/FederatedProjectWorkcspace/releases/tag/v0.1.0>.

Při pádu buildu se žádný existující cílový soubor nepřepisuje. Neúplné lokální
dočasné soubory `.package-*` lze po ověření, že žádný build neběží, odstranit a
build zopakovat. Tag a veřejný release se nevytvářejí jako recovery kroky.
