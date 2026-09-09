# ADR 0014 — Otevření registrovaného projektu v M1

Stav: přijato pro omezenou integraci M1-01. Navazuje na ADR 0003, 0004 a 0013; nepřidává projektové mutace ani nový storage protokol.

Desktop přijímá explicitní lokální `--node SOUBOR`. Registrace se znovu validují při každém požadavku; prohlížeč dostává jen ID a smí otevřít pouze registrované ID, nikoli cestu. Bez konfigurace ukazuje prázdný seznam. Backendová služba Projects není závislá na HTTP ani Qt. Stávající token/Host/Origin ochrany platí i pro POST `/v1/projects` a `/v1/projects/open`; POST slouží ke čtení s existujícím autentizačním kontraktem.

Projekt musí být existující vlastněný běžný Git kořen; state je existující soukromý adresář 0700 na stejném filesystemu, oddělený podle konfigurace v1. Nepřijímají se symlink adresáře ani nebezpečné existující stavové soubory (symlink, hardlink, cizí vlastník, přístup jiných uživatelů). Projektové `project.json` musí být pravidelný blob v HEAD, podporované verze a se shodným ID; pracovní soubor se musí shodovat s tímto blobem. Nevalidní konfigurace nevytváří runtime stav. Inicializace/registrace/migrace projektu zůstává samostatný úkol V-08.

## Hranice zápisů a recovery

- Před validací registrace a konfigurace se nic nezapisuje.
- Konstrukce Workspace může vytvořit writer.lock, SQLite journal s vlastníkem a prázdný index v registrovaném state. Journal používá existující transakční inicializaci a zámek. Pád před dokončením inicializace nevytváří projektovou operaci; příští otevření opakuje inicializaci. Existující journal ani pending payloady se nemažou.
- Pod společným zámkem se odmítne pending operace; otevření nikdy automaticky nevolá recover ani nemění HEAD/projektové soubory.
- Chybějící/stale index se obnovuje stávající validací a SQLite transakcí: pád před commit transakce ponechá předchozí/žádnou projekci, po commitu kompletní projekci s commit ID. Příští otevření kontrolu opakuje. Indexace nepřepisuje autoritativní journal.
- Název projektu, artefakty a commit se kontrolují jako jeden výsledek pod zámkem. Změna HEAD během čtení vede k chybě; po uvolnění zámku je výsledek explicitně snímkem uvedeného commitu. Nekooperující Git/FS změny nejsou produkčně vyřešené (V-06).

Validace celého artefaktového snapshotu i porovnání id/title s indexem probíhají při otevření. Poškozená/nevalidní projekce nevrací staré řádky; SQLite poškození vede k chybě, ne k automatickému mazání databází. Seznam filtruje artefakty, registry zatím nemají UI. Změny necommitnutého obsahu nejsou vydávány za uložené artefakty. UI vykresluje názvy a ID přes textContent a při výběru/chybě odstraní starý výsledek.

Rozsah: kontrolované malé lokální projekty, jeden uživatel, stávající loopback PoC. Seznam registrací používá stabilní ID; jméno se načte až po otevření. Nejde o plné RBAC, produkční Git sandbox, kompletní deadline requestu, editor ani synchronizaci. Nově vytvářené lock/index soubory mají 0600; starým souborům se práva automaticky nemění. Důkazy a další krok jsou v TODO.
