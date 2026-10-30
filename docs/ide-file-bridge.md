<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# IDE bridge přes běžné lokální soubory

## Připojení editoru k Workspace

Otevřete **Nastavení → IDE a editory** v levém panelu. Jde o samostatnou
stránku, dostupnou i bez otevřeného projektu. Pojmenujte připojení, vyberte
VS Code nebo VSCodium a použijte **Nainstalovat a připojit editor**.

Desktop po nativním potvrzení použije `code` / `codium --install-extension`.
Web stáhne VSIX; v lokálním IDE zvolte Extensions → Install from VSIX.
Balíček uložte mimo Git a po instalaci smažte, obsahuje přístupový údaj
s platností 30 dní. V IDE spusťte **Workspace: Připojit Workspace** a potvrďte
server a připojení. Žádný projekt ani repozitář při tom nemusíte vybrat.
Pro soukromou CA lze vybrat certifikát; TLS ověření se nevypíná.

Připojení dovoluje zobrazit katalog aktuálně oprávněných projektů a výslovně
nastavit jejich propagaci. Nezpřístupňuje obecné API ani automaticky
neexportuje obsah všech projektů. Obsah local-only a read-only repliky se
v novém mapování odmítají. Credentials jsou v SecretStorage editoru.

## Restart desktopu a aktualizace bez nového párování

Od rozšíření **0.2.1** a odpovídajícího desktopu se změna portu při restartu
obnovuje automaticky. Připojení, přiřazené projekty, credentials i komunikační
soubory zůstávají zachované. Při vypnutém desktopu rozšíření čeká; při zapnutém
Auto Sync se po jeho spuštění připojí při nejbližší synchronizaci (10 sekund).
Při vypnutém Auto Sync použijte **Workspace: Synchronizovat zprávy**.

Stávající uživatel aktualizuje desktop a rozšíření jednou. Pro aktualizaci
rozšíření **bez nového přístupového údaje** vytvořte z opraveného checkoutu
obecný balíček a nainstalujte ho do stejného profilu VSCodia:

```bash
python3 -c "from pathlib import Path; from spikes.ide_bridge import IdeBridge; Path('/tmp/workspace-bridge-update.vsix').write_bytes(IdeBridge(Path('/tmp/unused-node.json')).package())"
codium --install-extension /tmp/workspace-bridge-update.vsix --force
```

Pak ve VSCodiu spusťte **Developer: Reload Window** a spusťte aktualizovaný
desktop se stejnými daty uzlu. Znovu nepárujte ani nenastavujte projekty;
obecný balíček neobsahuje `pairing.json` a zachovává dosavadní SecretStorage
na stejném ID rozšíření. Starší desktop bez této opravy sám adresu neobnoví.
Odvolání a dosavadní 30denní platnost credentialu platí i nadále.

Desktop při startu obnoví podepsané adresy existujících připojení v
`~/.local/state/federated-workspace/ide-discovery/<connection-or-session-id>.json`.
Umístění je společné pro lokální desktop i IDE nezávisle na `XDG_STATE_HOME`;
ID oddělují více uzlů. Adresář vyžaduje 0700, soubory 0600 a stejného vlastníka,
bez symlinků a mimo Git. Soubor obsahuje pouze ID, přesnou loopback adresu a
HMAC podpis, žádný token ani projektový obsah. Rozšíření ověří podpis pomocí
již uloženého credentialu před odesláním požadavku. Poškozená discovery se
odmítne; pro HTTPS se lokální discovery vůbec nepoužívá.

## Projekty a jejich přiřazení

Na stránce **IDE a editory** vyberte připojený editor. Tabulka obsahuje:

- projekt Workspace a přepínač **Propagovat**;
- **Projekt v IDE** — konkrétní složku nebo cestu k `.code-workspace`;
- volitelnou identitu repozitáře (přesná URL origin nebo absolutní cesta)
  a instrukce pro tento projekt;
- stav přiřazení, akce **Uložit přiřazení** a **Zprávy**.

Cesty označují počítač s IDE, nikoli filesystem webového serveru. Cíl lze
ponechat prázdný a dokončit jej v rozšíření. Změna mapování založí novou
připnutou relaci a odvolá starou; zprávy a receipts staré relace se neztratí.
Stejný editor může mít současně přiřazeno více projektů. Každý má vlastní
souborovou schránku a vlastní revizi zadání.

V IDE nabídne **Workspace: Nastavení projektů** výběr propagovaných projektů.
Novým projektům přiřadíte otevřenou složku, jinou složku nebo `.code-workspace`
a jeho Git repozitář. **Workspace: Přiřadit projekt v IDE** umožní změnit cíl
již nastaveného projektu. Potvrzené změny uvidíte také v tabulce Workspace
po obnovení. Přidání ze stránky aplikace vyžaduje v IDE potvrdit lokální cíl;
server nemůže sám otevřít libovolnou lokální složku.

Nastavení rozšíření **Workspace bridge → Auto Sync** řídí automatickou
synchronizaci. Výběr projektů a cíle spravují uvedené dva příkazy. Otevření
TODO a odeslání zprávy nabídne při více přiřazeních výběr konkrétního projektu.
Rozšíření v jednom profilu používá jedno aktivní připojení Workspace; přepnutí
na nové připojení odstraní starý aktivní credential, soubory ponechá.

## Soubory, zprávy a obnova

**Workspace: Otevřít komunikační soubory** otevře TODO vybraného projektu
a zkopíruje cestu ke složce v privátním globalStorage editoru mimo Git:

```text
sessions/<session-id>/
  TODO.md
  INSTRUCTIONS.md
  snapshot.json
  STATUS.json
  inbox/<message-id>.json
  receipts/<message-id>.json
```

TODO/instrukce jsou export připnuté revize a lokální úpravy se při sync
nahradí. Kanonické definice i z included dokumentů drží snapshot.json.
Nevzniká další verzovaný plán. Soubory lze výslovně předat coding agentovi,
pokud má oprávnění k této cestě; bridge mu oprávnění automaticky nepřidává.

Výsledek nebo dotaz odešlete přes **Workspace: Odeslat výsledek nebo dotaz**.
Další plugin může zapsat JSON do `inbox/` s novým UUID jako názvem souboru:

```json
{
  "message_id": "550e8400-e29b-41d4-a716-446655440000",
  "task_id": "TASK-01",
  "kind": "clarification",
  "body": "Má výstup zahrnovat také export?",
  "revision": "<snapshot.revision>",
  "repository_commit": "<skutečný git rev-parse HEAD>"
}
```

Povolené kind jsou completed, clarification a message. Text má nejvýše
16 KiB. Zapisujte do dočasného `.tmp` a hotový soubor zveřejněte
přejmenováním. Odeslané ID a payload neměňte, oprava dostane nové ID.
Synchronizace každých 10 sekund i po restartu IDE projde všechna lokálně
přiřazená mapování; chyba jednoho projektu nezastaví ostatní. Ruční příkaz
**Workspace: Synchronizovat zprávy** provede totéž ihned.

`received` v receipts potvrzuje trvalé přijetí, nikoli splnění úkolu. Zprávy
otevřete tlačítkem **Zprávy** u projektu v tabulce. Člověk posoudí důkazy
a případně upraví autoritativní TODO existujícím editorem Workspace.
Změna projektového HEAD označí relaci jako stale. Uložte nové přiřazení
nad aktuální revizí a potvrďte je v IDE; staré zprávy se nepřenesou automaticky.

Vypnutí propagace odvolá jen dané mapování. **Odvolat připojení** zablokuje
celý editor včetně všech jeho mapování. **Workspace: Odpojit lokální bridge**
zastaví lokální sync a odstraní aktivní credential; pro úplné odpojení
odvolejte přístup také na serveru. Soubory a zprávy zůstávají zachovány.
Ztráta odpovědi při zápisu mapování, bind nebo zprávy je bezpečně opakovatelná.
Při ztrátě instalační odpovědi může zůstat nepoužité připojení; odvolejte je
v přehledu a připravte nové.

Původní projektové balíčky schema-v1 fungují i po aktualizaci rozšíření.
Jejich zprávy a akci odvolání najdete pod **Zprávy** u odpovídajícího projektu.
Nové propojení se vytváří ve dvou úrovních (schema-v2).

První profil je lokální Linux/VSCodium s webovým nebo desktopovým Workspace.
Windows, VS Code a nativní Qt instalační klikání vyžadují samostatnou fyzickou
akceptaci. Remote SSH, WSL, Codespaces a browser-only IDE nejsou podporované.
Bridge nespouští Codex ani jiného agenta a nepřidává MCP/FUSE/virtuální FS.

Skutečný izolovaný smoke: `python3 -m scripts.ide_bridge_smoke --editor codium`.
Výsledky drží TODO, po uzavření WORK_LOG. Recovery a autoritu vymezuje
[ADR 0060](adr/0060-local-file-ide-bridge.md).
