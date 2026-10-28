<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Workspace file bridge

Rozšíření pro desktopové VS Code / VSCodium. Aplikace Workspace připraví
projektově omezený VSIX. Po instalaci spusťte `Workspace: Propojit projekt`,
potvrďte server a vyberte odpovídající zdrojový Git repozitář.

`Workspace: Otevřít komunikační soubory` otevře TODO a zkopíruje cestu ke
složce mimo Git. Složka obsahuje TODO.md, INSTRUCTIONS.md, snapshot.json,
inbox/ a receipts/. Zprávy lze vytvářet příkazem nebo obyčejným zápisem JSON.
Synchronizace probíhá každých 10 sekund, také po restartu IDE. Dokončení je
návrh; o akceptaci rozhoduje člověk ve Workspace. Změna zadání vyžaduje nové
propojení. Odvolání přístupu je v aplikaci Workspace.

VSIX obsahuje přístupový údaj: nesdílejte jej ani nevkládejte do Gitu.
Po instalaci jej odstraňte z Downloads. Pro soukromou certifikační autoritu
vyberte CA při propojení; TLS ověření se nevypíná. Credentials se ukládají do
SecretStorage editoru. Linux a Windows používají stejný Node adaptér;
fyzická podpora jednotlivých OS a IDE vyžaduje samostatné ověření.

Webový Workspace podporován přes HTTPS. Rozšíření samo běží v lokálním IDE,
nikoli v prohlížeči. První verze nepodporuje Remote SSH, WSL ani Codespaces.
Soubory poskytují kontext dalším pluginům; bridge nespouští coding agenta
ani automaticky nerozšiřuje jeho oprávnění na cestu mimo pracovní adresář.
