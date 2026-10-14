<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — IMP-01 — Explicitní jednorázový import z Google Drive

Původ: roadmapa sekce 3C a připravená dávka v BACKLOGu. Cílová úroveň:
**designed → implemented**. Aktivní větev:
`feature/imp-01-google-drive-import`, základ a cíl jediného PR: `develop` na
merge commitu PR #65 `a09538e`.

## Rozsah feature

Uživatel v systémovém Google Pickeru vědomě vybere jednotlivé soubory nebo
jednu složku z osobního Drive a před lokální publikací zkontroluje přesný plán.
Blob soubory se importují v původních bajtech; Google Docs, Sheets a Slides se
exportují do výslovně zobrazeného podporovaného formátu a provenance odlišuje
zdrojový MIME typ, revizi, čas vzniku a exportní transformaci. Import nezapíná
synchronizaci, neprochází celý Drive a nic do Drive nezapisuje.

Mimo rozsah jsou Shared Drives, průběžná synchronizace, zápis zpět, obecný
cloudový file manager a široké `drive.readonly`/`drive` scopes. První PoC
použije per-file `drive.file`, systémový prohlížeč a bounded výběr.

## Persistentní hranice a recovery

OAuth client a refresh/access token jsou node-local secrets mimo projektový
Git. Durable import journal před stažením připne projekt/HEAD, uživatele,
credential revizi, vybraná file ID, metadata/revize, exportní mapování, limity
a digest potvrzeného plánu. Stažené bajty jdou do soukromého stagingu; před
jedinou Workspace publikací se znovu ověří Drive revize, lokální oprávnění a
HEAD. Pád před Workspace commitem zachová obnovitelný staging, pád během
publikace řeší existující Workspace journal a po commitu se index obnoví z
HEAD. Neurčitá externí mutace nevzniká, protože Drive se pouze čte; změněný či
odvolaný přístup operaci zastaví bez částečné projektové publikace.

## Úkoly

- [x] [completed] **IMP-01-A — OAuth/Picker kontrakt, reuse a ADR
  (designed).** Ověřit aktuální Google `drive.file`, Picker, download/export
  a 10MiB exportní limit; vymezit credential ownership, redirect/state/PKCE,
  folder traversal, formáty, budgety, provenance a crash boundaries.
- [x] [completed] **IMP-01-B — Bounded Drive adapter a durable staging
  (implemented).** Implementovat metadata, rekurzivní bounded výběr, raw
  download/export, revizní revalidaci, token refresh/revocation a idempotentní
  journal bez logování tokenů nebo providerových odpovědí.
- [x] [completed] **IMP-01-C — Atomická projektová publikace
  (implemented).** Adaptovat Sources/Workspace na jednu potvrzenou dávku,
  zachovat přesné bajty a SHA-256, exportní provenance, duplicate/supersedes
  rozhodnutí a jeden commit bez částečného importu.
- [ ] [in progress] **IMP-01-D — Sdílené UI/API a akceptace
  (implemented).** Přidat explicitní připojení/picker, polling výsledku,
  bezpečný náhled a potvrzení pro desktop i web, RBAC/privacy, cílené recovery
  a HTTPS testy, plnou sadu a fyzickou akceptaci skutečného osobního Drive.

## Aktuální výsledek a ověření

- **A — designed/completed:** [ADR 0032](docs/adr/0032-google-drive-import.md)
  připíná `drive.file`, systémový prohlížeč, PKCE/state, raw/export mapování,
  budgety a recovery. [Reuse katalog](REUSE_CATALOG.md) dokládá adaptaci
  existujícího Workspace/Sources/UI bez provider SDK.
- **B — implemented/completed:** `spikes/google_drive_import.py` drží
  actor-scoped credentials/tokeny mimo Git, bounded folder traversal, metadata
  revalidaci před/po downloadu, 10MiB exportní limit, 16MiB file limit, 64MiB
  dávku a explicitně obnovitelný staging.
- **C — implemented/completed:** `Sources.import_sources` publikuje 1–20 zdrojů
  jednou Workspace operací a commitem. Metadata v2 rozlišují source/export MIME;
  index v3 se atomicky přestaví z v2. Fake-provider testy ověřují raw a PDF
  export, duplicitu/supersedes, stale HEAD, změnu revize, odvolání, limit a
  recovery bez druhého downloadu.
- **D — implemented, akceptace otevřená:** sdílená desktop/web stránka má
  přívětivého průvodce prvním přihlášením i importem, jednorázové nastavení
  OAuth s přesnou callback adresou, návrat z nastavení, systémový Picker/popup,
  stavový postup, bezpečný seznam vybraných položek, explicitní potvrzení a
  obnovu. Chybové stavy vysvětlují zrušené přihlášení i zablokované popup okno;
  UI připomíná, že heslo zůstává u Googlu a samotný výběr projekt nemění. HTTPS
  test ověřuje callback, `drive.file`, webový zákaz `local-only` a RBAC.
  První fyzický pokus odhalil Google `redirect_uri_mismatch`: desktop nyní
  používá kořenový loopback redirect požadovaný klientem typu `Desktop app`,
  zatímco web zachovává přesnou HTTPS callback cestu; oba callbacky mají
  samostatný integrační test. Druhý fyzický pokus dosáhl Google consent gate,
  ale účet ještě nebyl povolen mezi `Audience → Test users`; průvodce i návod
  nyní tuto podmínku režimu Testing uvádějí. Úspěšný fyzický průchod se
  skutečným účtem zatím chybí; postup je v
  [docs/google-drive-import.md](docs/google-drive-import.md).
- Ověření 2026-10-14: `node --check` generovaného `app.js`; cílené Drive,
  indexové, desktopové a HTTPS testy; úplná sada
  `python3 -m unittest discover -s tests -v` — **541 OK, 24 skipped**. Skipped
  scénáře vyžadují reálný WebEngine, privátní Takeout vzorek nebo volitelný
  native probe a nejsou vydávány za fyzickou Drive akceptaci.

## Podmínky dokončení

- Bez uživatelského Picker výběru se Drive neprochází; aplikace žádá pouze
  `drive.file` a zobrazuje přesný lokální dopad před vytvořením artefaktů.
- Blob bajty se zachovají, nativní export je viditelná transformace a čas
  zdroje není zaměněn za čas importu.
- Změněný výběr/revize, odvolaný přístup, limit, duplicita, stale HEAD nebo pád
  nevytvoří částečný či skrytě opakovaný projektový import.
- Cílené testy, celá sada, `git diff --check` a fyzická desktop/web akceptace
  odpovídají dosaženému stavu.

## K předání do backlogu

Zatím bez nových odkladů.
