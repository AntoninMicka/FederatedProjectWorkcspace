<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO

Dávka `COMP-02 — Lokální Julia runner a publikace výsledků` byla znovu otevřena
uživatelským požadavkem na jednokrokový onboarding přímo z archivu. Evidence
předchozí akceptace je v [WORK_LOG.md](WORK_LOG.md); větev zůstává
`feature/comp-02-julia-runner` s cílem jediného PR do `develop`.

- [x] [completed] **COMP-02-I — onboarding přímo z archivu (implemented).**
  `./run.sh julia-setup ARCHIV.tar.gz` ověří, bezpečně rozbalí a připne známý
  oficiální archiv bez ruční cesty k runtime; recovery a cílené chybové testy
  jsou doplněné.
- [ ] [in progress] **COMP-02-J — závěrečná regrese a obnovená akceptace
  (PoC validated).** Jednokrokový příkaz nad skutečným oficiálním archivem
  prošel, shodné opakování vrátilo `reused:true` a fyzický izolovaný výpočet s
  publikací uspěl. Zbývá dokončit celou unit sadu po poslední změně.
