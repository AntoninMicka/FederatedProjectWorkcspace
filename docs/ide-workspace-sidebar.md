<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# DEV-03 — panel Workspace v lokálním VS Code/VSCodiu

Schválený UI/review řez, 31. 10. 2026: **implemented**, lokální
integrační a nativní extension-host ověření **PoC validated**.
Větev `feature/dev-03-workspace-sidebar`, základ `develop` `7954000`
po merge DEV-01 v PR #115, cíl jediného PR `develop`.
Aktuální plán a stav drží kanonický Workspace projekt; tento dokument
specifikuje kontrakt a recovery, není druhým seznamem aktuálních úkolů.

## Rozsah a závislosti

Úkoly: strom projekt / milník / dávka / úkol, filtr otevřených položek,
detail v editorové ploše s popisem, checklistem a závislostmi.
Zprávy: projektová zpráva, dotaz, návrh dokončení a částečného splnění;
oddělené čekání na odeslání, doručení, review a výsledek review.
Podklady: katalog a bezpečné otevření explicitně vybraného připnutého textu.
Pravidla: exportovaná projektová/directory/task pravidla a lokální AGENTS.md,
s původem, revizí a rozsahem; kopírování explicitního předání úkolu agentovi.

Reuse/adapt: extension `extensions/workspace-bridge`, ordinary-file mailbox,
parent connection / mapping, `IdeBridge`, `Projects`, `ArtifactActions`,
validátor task graphu a jediný `Workspace.transact` writer. Nový transport,
provider, coding-agent runtime, FUSE a FileSystemProvider se nezavádějí.
Nativní Tree View doplní bezpečný detail bez spustitelného projektového HTML.
Viz [Tree View API](https://code.visualstudio.com/api/extension-guides/tree-view)
a [Webview API](https://code.visualstudio.com/api/extension-guides/webview).

Původní široká DEV-03 zahrnovala spuštění agenta a závisela na DEV-02.
Uživatel schválil samostatný UI/review řez: jeho předpoklady jsou dokončené
DEV-01 a DEV-IDE-TODO-01. Provider-neutral run contract a spouštění agenta
zůstávají DEV-02/DEV-04, nevydávají se za implementované tímto panelem.
Původní scope a provenance se zachovají při upřesnění kanonické DEV-03.

## Kontrakty a ochrana obsahu

Panel používá pouze credentialem autorizované aktuální mapování. Nativní
scoped exchange rozšíří o read-only panel/document akce; credential nepovolí
review ani obecné projektové API. Dokument je explicitně vybraný artifact ID,
nikoli volná filesystem cesta. Pinned i současná metadata musí dovolovat
export; local-only, neznámá identita, změněná relace a nepovolený projekt
se odmítnou. Export dokumentů je samostatný příznak mapování `export_documents`,
výchozí false. Oprávnění rozšiřuje pouze člověk ve Workspace; parent IDE
credential si jej nemůže přidělit. Text má limit 1 MiB, přesné UTF-8 bajty,
SHA-256 a revizi.
Binární obsah se nespouští ani nepřevádí na aktivní HTML.

Exportované texty zůstávají v privátní schránce mimo Git. Soubory se ukládají
pod content digestem s neutrální příponou; vstup neřídí lokální cestu. Manifest
se publikuje až po úplných souborech. Detail tasku escapuje všechny texty,
zakazuje skripty, síť a command URI. Lokální soubor se otevírá pouze uvnitř
ověřeného kořene mapovaného repozitáře, po kontrole realpath a symlinků.

Pravidla Workspace se explicitně označují tagem `agent-rules`. Markdown text
má projektový rozsah; strukturované JSON pravidlo používá
`fpw-agent-rules-v1`, `scope` a `body`. Scope je project, directory s bezpečnou
relativní cestou nebo task s existujícím task ID. Export nenahrazuje lokální
AGENTS.md a netvrdí, že jej běžící agent načetl. Rozpory se nepřekrývají tiše.
INSTRUCTIONS.md zůstává rozcestníkem transportu a zpřístupněných pravidel.

Zpráva nese message ID, project/task scope, připnutou revizi a skutečný
repository HEAD. Project scope je `task_id: null` a pouze obecná zpráva.
Review provádí oprávněný člověk ve Workspace, nikoli IDE credential.
Přijetí completion/progress se váže na nezměněný projektový HEAD a přesný
task/checklist; mění pouze schválený cíl. Stale proposal se neaplikuje.
Částečné splnění nesmí označit celý úkol za dokončený.

## Crash boundaries

Původní credential/mapping/mailbox recovery zůstává podle
[ADR 0060](adr/0060-local-file-ide-bridge.md). Dokumenty jsou content-addressed;
pád před manifestem zanechá nejvýše neodkazované soubory. Pád po manifestu
nevytvoří smíšenou revizi. Starší relace a zprávy se nemažou; ztracená odpověď
neznamená novou zprávu s jiným ID. Nedostupnost se odliší od aktuálního cache.
Při změně zadání během psaní se zpráva uloží jako neodeslaný koncept,
nikoli automaticky do nové revize.

Review přechází přes dva autoritativní journály: bridge SQLite nejprve
uloží explicitní review intent a operation ID; nativní Workspace transakce
provede schválenou změnu podle ADR 0003. Po native receiptu bridge publikuje
review outcome. Žádný SQLite writer lock se nedrží přes Workspace lock.
Pád před intentem nemá účinek; po intentu se obnoví stejná operace; po
projektovém commitu se výsledek dohledá přes native receipt, nikoli druhý
commit. Odmítnutí a odpověď bez projektové změny se zapíší jednou bridge
transakcí. UI zpřístupní obnovu připraveného review; nebude je vydávat za
dokončené ani bez nového požadavku spouštět jiné rozhodnutí.

## Ověření a hranice

Ověřit izolaci projektů, privacy a revoke, stale task/checklist, replay,
všechny review crash boundaries, nedostupné spojení a obnovu IDE relace.
Ověřit skutečné provedení Node UI akcí nad lokálním HTTP backendem,
bezpečnost detailů a cest, úplný VSIX a instalaci v izolovaném IDE profilu.
VS Code, VSCodium a nepřítomné platformy se evidují zvlášť. Celá závěrečná
unittest brána a diff kontrola následují po poslední relevantní změně.

### Provedené integrační a platformní kontroly

Cílená brána: 84 testů OK, 6 podmíněných skipů; navíc samostatně ověřeno
rozšířené webové review s reálným editor účtem. `tests/test_ide_bridge_panel.py`
pokrývá scoped dokumenty, explicitní export scope, zákaz self-grantu, privacy,
revokaci, projektové zprávy, checklist/frontmatter/fenced bloky, stale a replay,
šest crash boundaries review, intent-only stale recovery a spustitelné UI review.
Node integrace používá skutečný HTTP backend a filesystem, pouze API plochy
editoru je nahrazené: dva izolované projekty, detail/CSP, přesné dokumenty,
pravidla včetně cest s mezerami, traversal/symlink, úplnost manifestu,
review/outcome a remap, koncept při změně revize a odvolání přístupu.

Skutečné oddělené extension-host smoke prošlo na **Linux ARM64**:
**VSCodium 1.105.17075** a **VS Code 1.144.0** (přenosný oficiální build).
V každém případě skutečná instalace VSIX, aktivace sidebaru a otevření
activity containeru, restart backendu na jiném portu bez nového párování,
mapování a ordinary-file receipt/retry, projektový Git beze změn.
Nejde o ruční proklikání kompletního toku v uživatelově běžném profilu.
Windows/macOS, remote SSH/WSL/browser-only a produkční release nejsou ověřené.

Podrobný uživatelský postup drží [README rozšíření](../extensions/workspace-bridge/README.md#panel-workspace-od-verze-030).
Nové párování není potřeba: aktualizovat backend a generický VSIX stejného
ID, obnovit okno IDE a explicitně povolit dokumenty v nastavení Workspace.
Akceptace uživatelského toku a doručení zdrojového PR jsou oddělené kroky.

Závěrečná celá sada po poslední relevantní změně chování/testů/config:
`python3 -m unittest discover -s tests -v` — **1 114 testů OK, 39 podmíněných
skipů**, 269,264 s. Následující úpravy jsou pouze dokumentace a evidence.
`node --check` prošel pro sidebar, extension a emitované společné UI;
kontrola lokálních dokumentačních odkazů a `git diff --check` bez chyb.
Generický VSIX 0.3.0 neobsahuje pairing credential; instalace do místního
běžného profilu VSCodia dokončena a seznam rozšíření potvrzuje verzi 0.3.0.
Okno uživatele ani jeho běžný backend nebyly restartovány. Pro ruční
akceptaci je třeba restartovat backend, obnovit okno IDE a projít úkol →
podklad/pravidla → zpráva → review → výsledek. Akceptace ani zdrojový
commit/push/PR/merge nebyly provedeny automaticky.
