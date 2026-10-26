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
  (PoC validated).** Zbývá celá unit sada po poslední změně a praktické spuštění
  příkazu nad skutečným oficiálním archivem.
