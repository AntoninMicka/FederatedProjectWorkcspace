<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Release 0.1.0 — příprava a předání

Tento dokument je veřejný checklist kandidáta, nikoli důkaz, že release už byl
publikován. Autoritativní verze je v `VERSION`; release commit, tag, datum a
hashe se nesmějí doplnit odhadem.

## Rozsah kandidáta

- source archiv `federated-workspace-poc-0.1.0.tar.gz`;
- nebundlovaný Debian balík `federated-workspace-poc_0.1.0_all.deb`;
- ruční update channel popsaný v README;
- žádný AppImage, container image, wheel/venv bundle, model ani Qt/Chromium
  runtime uvnitř artefaktů.

## Před sestavením

- [ ] release větev vychází z akceptovaného `develop` a pracovní strom je čistý;
- [ ] `VERSION`, changelog, názvy artefaktů a `.deb` control uvádějí `0.1.0`;
- [ ] aktuální distribuční allowlist, SPDX, provenance, notices a dependency
  register byly znovu posouzeny proti přesnému kandidátnímu commitu;
- [ ] skutečný cílový runtime obsahuje a dokládá Segno 1.6.6;
- [ ] nejsou přítomné credentials, privátní katalog, lokální projekty ani
  neveřejná release evidence.

## Ověření kandidáta

- [ ] `python3 -m unittest discover -s tests -v`;
- [ ] balicí a licenční testy včetně skutečného `dpkg-deb`;
- [ ] relevantní skutečný desktop/WebEngine a dpkg lifecycle smoke;
- [ ] source archiv je reprodukovatelný a každý člen odpovídá
  `MANIFEST.sha256.json`;
- [ ] `.deb` control, obsah, notices, spouštěč, instalace, upgrade a odstranění
  odpovídají dokumentovanému rozsahu;
- [ ] oba artefakty vznikly ze stejného čistého commitu a jejich SHA-256 jsou
  zaznamenané spolu s build platformou.

## Publikace

- [ ] uživatel schválil konkrétní kandidát a jeho omezení;
- [ ] PR `release/0.1.0 -> main` prošel CI a byl sloučen;
- [ ] tag `v0.1.0` ukazuje přesně na schválený release commit;
- [ ] GitHub Release obsahuje changelog, oba ověřené artefakty a SHA-256;
- [ ] release metadata neuvádějí neexistující DOI, archivaci ani dokončenou
  produkční či cílovou akceptaci.

Při pádu buildu se žádný existující cílový soubor nepřepisuje. Neúplné lokální
dočasné soubory `.package-*` lze po ověření, že žádný build neběží, odstranit a
build zopakovat. Tag a veřejný release se nevytvářejí jako recovery kroky.
