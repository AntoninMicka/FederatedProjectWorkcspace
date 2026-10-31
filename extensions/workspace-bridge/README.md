<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Workspace file bridge

Připojte lokální VS Code/VSCodium k webovému nebo desktopovému Workspace.
Aplikace připraví VSIX v **Nastavení → IDE a editory**. Po instalaci spusťte
**Workspace: Připojit Workspace**. Tento krok ještě nevyžaduje projekt.

**Workspace: Nastavení projektů** vybere projekty, které chcete propagovat,
a přiřadí jim lokální složku či `.code-workspace` a Git repozitář.
**Workspace: Přiřadit projekt v IDE** změní cíl jednotlivého projektu.
Přiřazení lze spravovat také v tabulce na stránce Workspace; lokální cíl
potvrdíte v IDE. Jeden editor synchronizuje více samostatných projektů.
Nastavení **Workspace bridge → Auto Sync** umožní vypnout automatický sync.
Od verze 0.2.4 sync také obnoví změněné zadání již přiřazeného schema-v2
projektu při zachování cílového repozitáře a instrukcí. Nejprve doručí
čekající zprávy pod původní revizí; nová revize dostane vlastní schránku.
Viditelné původní TODO se otevře v nové revizi. Staré soubory i receipts
zůstávají zachované. Restart dokončí rozpracované mapování bez nového
párování; změna cíle či odvolání přístupu se automaticky neobchází.
Zprávy vytvořené ve staré schránce po přepnutí vyžadují ruční posouzení.
Aktualizace exportu sama nevkládá nové zadání do běžící konverzace agenta.

**Workspace: Otevřít komunikační soubory** nabídne projekt, otevře jeho TODO
a zkopíruje cestu ke složce mimo Git. Ta obsahuje TODO.md, INSTRUCTIONS.md,
snapshot.json, inbox/ a receipts/. Zprávy vytvoří příkaz **Workspace: Odeslat
výsledek nebo dotaz** nebo obyčejný zápis JSON podle instrukcí. Dokončení je
návrh k posouzení ve Workspace. Automatický sync běží po 10 sekundách
u všech lokálně přiřazených projektů a obnoví se po restartu IDE.

VSIX obsahuje přístupový údaj: nesdílejte jej ani nevkládejte do Gitu,
po instalaci ho smažte. Přístup lze ve Workspace odvolat pro celý editor
nebo pro jednotlivé mapování. Credentials jsou v SecretStorage. Soukromou
CA lze vybrat při připojení; TLS validace se nevypíná. Starší projektové
VSIX schema-v1 zůstávají podporované. V jednom profilu je aktivní jedno
připojení Workspace, obsahující více projektových mapování.

Instalace a aktivace jsou ověřené na Linux ARM64 v izolovaných profilech
VSCodium 1.105.17075 a VS Code 1.144.0. Windows a macOS vyžadují samostatné ověření. Webový Workspace funguje přes HTTPS, rozšíření běží
v lokálním IDE. Remote SSH, WSL a browser-only IDE nejsou podporované.
Bridge nespouští coding agenta ani mu automaticky nepřidává práva k souborům.

Od verze 0.2.2 se přechodná odpověď `503 server busy` opakuje nejvýše třikrát
s odstupem 250, 500 a 1000 ms. Trvalé vytížení se zobrazí jako chyba;
jiné HTTP chyby ani nejasné síťové selhání se automaticky neopakují.

Od verze 0.2.1 se při restartu aktualizovaného desktopu automaticky obnoví
jeho adresa z lokální podepsané discovery. Uložené projekty a credentials
zůstávají zachované, včetně propojení vytvořených starší verzí. Obecný VSIX
bez pairing.json lze použít pro aktualizaci stejného profilu bez párování.
Při vypnutém desktopu stav ukazuje čekání na spuštění; Auto Sync opakuje pokus
každých 10 sekund. Odvolání a 30denní expirace zůstávají platné. Podrobný
postup a omezení: docs/ide-file-bridge.md ve zdrojovém repozitáři.

## Panel Workspace od verze 0.3.0

Po aktualizaci stejného profilu použijte **Developer: Reload Window**.
V activity baru otevřete **Workspace**: čtyři pohledy zobrazují **Úkoly**,
**Zprávy**, **Podklady** a **Pravidla agentů**. U úkolů lze filtrovat otevřené
položky a otevřít bezpečný detail s checklistem a závislostmi. Akce úkolu
nabízí zprávu, dotaz, částečné splnění checklistu nebo návrh dokončení.
Na projektu lze odeslat obecnou zprávu bez úkolu. Rozpracovaná zpráva se při
změně revize během psaní zachová jako neodeslaný koncept.

Podklady a exportovaná pravidla jsou výchozím stavem vypnuté. Člověk je
povolí zvlášť pro projekt v **Workspace → Nastavení → IDE a editory →
Podklady a pravidla**. IDE credential si toto oprávnění nemůže přidělit.
Při zachování stejného lokálního cíle sync převezme nové mapování; při
změně cíle je nutné nové potvrzení. Aktualizujte také backend Workspace.

Podklady ukazují dokumenty odkazované vybraným úkolem; příkaz **Workspace:
Zobrazit všechny podklady** rozšíří katalog. Otevírá se ověřená UTF-8 kopie
s neutrální příponou `.txt` mimo Git, nejvýše 1 MiB na soubor. Binární,
local-only a neplatný obsah se nevydává. Historie zpráv je omezená na 100
položek a velikost panelu; starší záznamy zůstávají v bridge databázi.

Pravidla Workspace musí mít tag `agent-rules`. Markdown má projektový rozsah.
Strukturovaný JSON může vypadat takto:

```json
{"schema":"fpw-agent-rules-v1","scope":{"kind":"directory","path":"src"},"body":"Používej existující komponenty."}
```

Další scope jsou `{"kind":"project"}` a `{"kind":"task","task_id":"TASK-01"}`.
Panel přidá lokální AGENTS.md z ověřeného repozitáře. Žádný AGENTS.md nepřepisuje.
**Workspace: Zkopírovat předání úkolu a pravidel** uloží neměnné kopie a manifest
`fpw-ide-context-v1`, potom zkopíruje jeho cestu. Rozpory pravidel zůstávají
viditelné bez automatické priority. Manifest má privacy `local-only`;
nevytváří souhlas s externím LLM ani nespouští agenta.

Návrhy posuzuje člověk ve Workspace v přehledu zpráv připojení. Může přidat
poznámku, přijmout nebo odmítnout. Dokončení a checklist zapisuje jediný
nativní writer až po ověření původního HEAD. Zastaralý návrh se neaplikuje;
částečný checklist nedokončí celý úkol. Při přerušení review je dostupná
obnova stejné operace. Výsledek se vrací do panelu IDE po synchronizaci.

## Fronta od verze 0.4.0

Workspace připraví neměnný balíček fronty přes **Předat frontu do IDE**.
Povolte export podkladů v aktuálním mappingu; následně synchronizujte IDE.
Pohled **Fronta úkolů** rozlišuje zahajitelné položky, navazující pouze pro
náhled, agentní hlášení a lidské přijetí. Předání agentovi kopíruje cesty
manifestu a AGENT.md. Agent hlásí splnění ordinary-file zprávou; oprávněný
člověk ji přijímá ve Workspace. Doručení není dokončení.

Podklady se ověřují hashy a znovu používají z pinned exportní cache přes
hardlink, bezpečný symlink nebo copy fallback. Nepropojují se s pracovními
soubory Workspace. Balíček se kvůli změně plánu tiše nepřepisuje a mapping
s aktivním packetem se automaticky nepřipíná na jiný commit.
Podrobný postup, completion schema a recovery: `docs/ide-queue-handoff.md`
v projektu Workspace; architektonické hranice: ADR 0062.
