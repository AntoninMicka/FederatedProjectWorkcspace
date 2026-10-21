<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0032 — Explicitní jednorázový import z Google Drive

Datum: 2026-10-14. Stav: přijato pro IMP-01; implementováno, fyzická akceptace
skutečného osobního Drive čeká.

## Rozhodnutí

První konektor používá systémový prohlížeč, OAuth Authorization Code s PKCE,
jednorázový Google One Picker a pouze per-file scope `drive.file`. Uživatel
vybere nejvýše 20 jednotlivých souborů nebo jednu složku. Složka se po výběru
projde klientsky přes `files.list` s limity 50 složek, hloubkou 5 a 10 stranami;
Shared Drives se odmítají. Konektor neprochází celý účet, nezapisuje do Drive a
nezavádí synchronizaci.

Blob Markdown/PDF/PNG/JPEG se stahují přes `files.get?alt=media` a publikují v
přijatých bajtech. Nativní Docs/Sheets/Slides se přes `files.export` převádějí
do PDF. Náhled vždy ukáže zdrojový MIME typ, exportní MIME typ, revizi, čas
vzniku, název, cílový projekt, privacy a limity. Providerův limit jednoho
exportu je 10 MiB; lokální limit jednoho souboru je 16 MiB, celé dávky 64 MiB.

OAuth client, refresh/access token, selection state, journal a staging jsou v
soukromém node-local adresáři mimo projektový Git. Token je vázaný na aktéra a
revizi credential konfigurace. Callback přijme pouze krátce žijící uložený
`state`; redirect URI sestaví server ze své ověřené authority. Providerové
odpovědi ani tokeny se nelogují a redirecty z Google API se nenásledují.

## Publikace a recovery

Preview revaliduje metadata a HEAD, rozpozná stejnou URL+revizi jako blokující
duplicitu a jediného předchůdce jiné revize nabídne jako `supersedes`.
Potvrzení uloží journal před sítí, po každém souboru publikuje fsyncnutý staging
záznam a před i po downloadu porovná Drive metadata. Změna revize, odvolání,
limit nebo stale HEAD skončí bez projektového commitu.

Všechny soubory potvrzeného výběru vstoupí do jedné existující Workspace
operace a jednoho Git commitu. Pád před commitem ponechá staging k explicitní
obnově; opakované operation ID znovu použije stejné artifact ID a receipt. Pád
uvnitř Workspace publikace řeší ADR 0003. Po commitu lze index v3 obnovit z
HEAD. Import nemá externí mutaci, kterou by bylo třeba kompenzovat.

## Odmítnuté varianty

- `drive.readonly` nebo `drive`: širší přístup není pro uživatelský výběr nutný.
- Vestavěný provider login ve WebEngine: přihlášení a Picker patří systémovému
  prohlížeči, workspace dostane jen callback.
- Automatický Drive crawler, Shared Drives, sync a write-back: jsou mimo
  jednorázový import a vyžadovaly by jiné oprávnění i lifecycle.
- Označit PDF export za původní obsah: provenance musí nést oba MIME typy a hash
  skutečně importovaného PDF.

## Ověřené podklady

- [OAuth scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth)
- [Desktop/mobile Picker](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker)
- [Download a export](https://developers.google.com/workspace/drive/api/guides/manage-downloads)
- [Vyhledávání souborů](https://developers.google.com/workspace/drive/api/guides/search-files)
- [files.list](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/list)

