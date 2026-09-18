<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-CHAT-02: Projektová vlákna, otisky a Markdown výstupy

Milník M2; Gate M1 zůstává otevřený kvůli odložené cílové restartové akceptaci M1-07. Jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M2-CHAT-02 — Projektová vlákna, otisky a Markdown výstupy

- Stav: [ ] [in progress]; cílová úroveň PoC validated.
- Původ: uživatelské doplnění plánu 2026-09-15; roadmapa §11A a navazující Git-backed artefakty/provenance.
- Skutečná větev: `feature/f-m2-chat-02-project-records`, založená z `develop` (`5dec3a8`, PR #29 začleněn); jediný budoucí PR do `develop`.
- Výstup: explicitní přiřazení živého vlákna k projektu, neměnný kompletní nebo rozdílový otisk a samostatné editovatelné Markdown výstupy.
- Mimo rozsah: automatická publikace každého soukromého chatu, credentials/provider session tokeny v Gitu, federovaná synchronizace a vydávání rozdílu bez ověřeného základu za úplný záznam.
- Závislosti: F-M2-CHAT-01 je začleněná PR #29; F-M1-META-02/F-M1-SOURCE-02 a standardní Workspace/Journal/Git/index lifecycle jsou v `develop`.
- Akceptace: živé vlákno lze po restartu navázat ke správnému projektu; full snapshot je samostatně čitelný, delta nese ID/hash základu a fail-closed kontrolu; odvozený Markdown zachová thread/run/message/manifest provenance a nejpřísnější privacy; expected HEAD, idempotentní retry a recovery před/po commitu jsou otestované.

- [x] [completed] **F-M2-CHAT-02-A — Kontrakt přiřazení, full/delta otisku a odvozeného výstupu (designed, 2026-09-18).** ADR 0008 definuje node-local projektovou vazbu, `fpw-chat-snapshot-v1` v čitelném Markdownu, samostatný full a fail-closed delta záznam s kanonickým hashem základu, `fpw-chat-output-v1`, nejpřísnější privacy a standardní expected-HEAD/Journal/CAS/index recovery. Reuse review volí stávající ChatThreads/metadata/Artifacts/Workspace a odmítá novou storage i paralelní Git lifecycle.
- [x] [completed] **F-M2-CHAT-02-B — Projektové záznamy a recovery (implemented, 2026-09-18).** `ChatThreads` migruje v1→v2 a trvale váže vlákno na registrovaný projekt i turn na Context Manifest; `ChatRecords` publikuje neměnné full/delta `fpw-chat-snapshot-v1` přes expected HEAD a standardní Workspace journal/CAS/index. Delta ověřuje existenci, project/thread ID, kanonický hash a souvislou sequence základu před journalem; retry po pádu vrací jediný commit/receipt. Cíleně ověřeno 12 testy úložiště a záznamů, návaznost 4 testy orchestrace; celá sada `251 OK, 22 skipped`.
- [x] [completed] **F-M2-CHAT-02-C — Markdown výstup, desktop UI a akceptace (PoC validated, 2026-09-18).** `fpw-chat-output-v1` ukládá vybranou odpověď jako editovatelný dokument s thread/message/turn/run/manifest provenance, nejpřísnější privacy a volitelným vztahem na snapshot; další editace nesmí odstranit ani změnit původní obálku. Autentizované desktopové API a UI nabízí explicitní přiřazení, full otisk a uložení poslední odpovědi; po zápisu obnoví projektový HEAD. Stav „Odesílám/Model přemýšlí“ je přímo pod promptem a nezmizí při scrollování historie. Ověřeno restartem služby, stale HEAD, pádem po journal prepare, idempotentním retry, rebuildem indexu, cílenými API/UI testy a celou sadou `253 OK, 22 skipped`; reálný Qt/WebEngine smoke zůstal přeskočen podle opt-in podmínky testu.

### Povinné recovery hranice

- Node-local thread store zůstává autoritou živého vlákna; Git záznam je explicitní projektová reprezentace, nikoli synchronizovaná kopie provozního SQLite.
- Před commitem drží přesný kandidát a request digest Workspace journal; po posunu refu lze index obnovit z validovaného HEAD bez opakované publikace.
- Delta se publikuje pouze proti existujícímu základu se shodným ID/hash; jinak operace končí před journalem/commitem.

### K předání do backlogu

- [ ] [planned] **F-UX-SETTINGS-01 — Centralizovaná stránka nastavení (cílová úroveň: designed → implemented).** Původ: uživatelský požadavek 2026-09-18. Navrhnout společné místo pro aplikační a backendová nastavení a následně do něj přesunout současné inline nastavení Ollama; zachovat node-local uložení, privacy hranice, validaci a bezpečný návrat při chybě. Neprovádět jako vedlejší zásah do F-M2-CHAT-02.
