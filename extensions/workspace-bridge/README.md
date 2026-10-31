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

První fyzicky ověřený profil je Linux/VSCodium. Windows a VS Code vyžadují
samostatné ověření. Webový Workspace funguje přes HTTPS, rozšíření běží
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
