<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — MOD-01-UI: publikační CMS ve Workspace

Uživatelský follow-up z 2026-09-30 před vytvořením PR rozšířil stejnou modulovou
feature. Větev zůstává `feature/mod-01-publication-registry`, základ/cíl PR je
`develop`. Původní MOD-01 evidence zůstává v
[WORK_LOG](WORK_LOG.md#mod-01--kontrakt-externě-verzovaných-modulů--2026-09-29);
PR dosud nebyl vytvořen ani sloučen.

- [x] [completed] **MOD-01-UI-A (designed)** — vymezit úzké spuštění dvou CMS
  capabilities bez zavedení obecného plugin runtime; [ADR 0027](docs/adr/0027-pinned-publication-cms-invocation.md).
- [x] [completed] **MOD-01-UI-B (implemented)** — přidat node-local binding,
  kontrolu čisté připnuté revize, shodného manifestu a reviewovaných runtime
  hashů a izolované spuštění pevného entrypointu modulu.
- [x] [completed] **MOD-01-UI-C (implemented)** — přidat desktopové i
  administrátorské webové UI pro editaci tří domén, přesný request, sandboxed
  HTML náhled a samostatné potvrzení generování.
- [x] [completed] **MOD-01-UI-D (PoC validated)** — serializovat generování,
  uchovat potvrzený request a receipt v SQLite journalu a obnovit pád mezi
  odvozeným výstupem a atomickým uložením node-local konfigurace. Cílená sada
  služby, UI, HTTPS RBAC a manifestu prošla 33 testy, 3 skutečné Qt/WebEngine
  testy byly přeskočeny. Celá sada `python3 -m unittest discover -s tests -v`
  prošla 363 testy, z toho 22 podmíněných testů přeskočeno. JavaScript prošel
  `node --check`; lokální integrace s izolovanou čistou kopií skutečného modulu
  ověřila preview i potvrzené generování všech tří webů.
- [x] [completed] **MOD-01-UI-E (implemented)** — nahradit ruční cestu a Git pin
  automatickou detekcí přítomnosti modulu a explicitním Povolit/Zakázat.
  Kompatibilita používá identitu/verzi manifestu, přesnou reviewovanou deklaraci
  capabilities a runtime SHA-256; CMS zůstává node-local a nadprojektové.
  Cílená sada prošla 35 testy se 3 podmíněně přeskočenými, celý Workspace 365
  testy s 22 přeskočenými. Skutečný rozpracovaný modul byl bez Git kontroly
  automaticky nalezen, povolen a použit pro preview ve verzi 0.3.0.
- [ ] [planned] **MOD-01-UI-F (designed)** — zobrazit skutečný stav deploymentů
  a odděleně potvrdit jejich vytvoření nebo aktualizaci přes konkrétní provider
  adapter. Prvním adapterem má být Cloudflare; pracovní návrh propojeného
  projektového výstupu, stavů a recovery je v
  [diskusním nástřelu](docs/publication-site-set-cloudflare-outline.md). Přesný
  Cloudflare runtime, credential hranice a cílové účty/projekty zatím nejsou
  určeny; lokální `dist/sites` se za deployment nevydává.

Generování je pouze lokální. Deployment, DNS, TLS a cache zůstávají neověřené;
externí create/update nesmí být implementován bez výslovného provider kontraktu
a `unknown` recovery hranice.
