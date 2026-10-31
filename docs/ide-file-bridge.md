<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# IDE bridge přes běžné lokální soubory

## Panel úkolů, zpráv a podkladů

Od verze **0.3.0** rozšíření nabízí čtyři pohledy v activity baru Workspace.
Postup zapnutí podkladů, formát pravidel, lidské review a lokální předání
agentovi popisuje [návod rozšíření](../extensions/workspace-bridge/README.md#panel-workspace-od-verze-030).
Backend i VSIX musí být aktualizované; po instalaci obnovte okno IDE.
Dosavadní párování a cesty zůstávají zachované. Generický aktualizační VSIX
neobsahuje credential. Podklady povoluje pouze člověk ve Workspace pro
jednotlivý projekt; samotná aktualizace toto oprávnění nezapne.
Kontrakt, recovery a rozsah ověření: [DEV-03](ide-workspace-sidebar.md).

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

Od **0.4.1** rozšíření samo nabídne novou verzi z aktualizovaného backendu
a po kliknutí na **Aktualizovat** nainstaluje generický VSIX do běžícího
profilu. Obnovení okna vyžaduje zvláštní potvrzení. Ruční kontrola a volba
automatické instalace: [návod aktualizace](../extensions/workspace-bridge/README.md#aktualizace-od-verze-041).
Níže uvedený ruční postup zůstává potřebný pro první přechod ze starší verze.

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

### Kontrakt a recovery updateru (hotfix PLAN-QUEUE-02)

Reuse/adapt: stávající `IdeBridge.package()` vytváří generický VSIX;
`connectionRequest()` zachovává autentizaci, TLS/CA a podepsanou lokální
discovery podle ADR 0060. Nová akce `extension-update` vrací jen identitu
a verzi, na explicitní požadavek také VSIX a SHA-256. Instalaci provede
[oficiální příkaz IDE](https://code.visualstudio.com/api/references/commands)
`workbench.extensions.installExtension`; vlastní installer ani shell se
nepřidává. Token je nadále kontrolovaný běžným connection endpointem včetně
expirace a revokace. Oprávnění k projektům se nemění. SHA-256 kontroluje
integritu přenosu; není nezávislým podpisem vydavatele. Backend je důvěryhodný
zdroj aktualizačního kódu.

Updater povoluje jen vyšší stabilní číselnou verzi stejného rozšíření,
omezuje balíček na 2 MiB, ověřuje SHA-256 a shodu metadat mezi kontrolou
a stažením. Dočasný adresář je privátní, soubor má 0600 a po skončení
instalačního příkazu se odstraní. Při změně verze během stahování se
instalace odmítne. Souběžné kontroly jednoho hostu se sloučí; automatické
pokusy včetně odmítnuté nabídky a chyb mají hodinový odstup. Ruční kontrola
odstup obchází. Zastaralý backend chybu zapíše do výstupu, sync pokračuje.

Crash boundaries: před předáním ověřeného VSIX installeru se instalace
nemění; chyba stahování či checksumu ponechá starou verzi. Při pádu procesu
může zůstat privátní dočasný soubor bez credentialu. Atomické nahrazení
a recovery instalace vlastní IDE. Po chybě installeru se úspěch nehlásí
a ruční kontrola dovolí opakování. Po úspěšné instalaci a před obnovením
okna běží původní kód; další kontrola v témže hostu nabídne obnovení bez
opakované instalace. Při restartu hostu se verze znovu porovná, případné
opakování stejné instalace je bezpečné. Projektový filesystem, Git, index
a journal tato operace nemění; recovery transakcí podle ADR 0003/0060
zůstává beze změny. Nové párování se nevytváří.

Ověření hotfixu 31. 10. 2026: cílená sada bridge/panelu 32 testů OK;
závěrečný `python3 -m unittest discover -s tests -v` 1166 testů,
40 skipped, OK. Node testy pokrývají potvrzení instalace a obnovení,
checksum, nesprávnou identitu, změnu verze, downgrade, souběh, selhání
installeru a retry. `scripts/ide_bridge_smoke.py --update` ověřil v
izolovaném profilu VSCodia skutečný instalační příkaz z testovacího VSIX
0.4.0 se stejným updaterem na 0.4.1 a následnou synchronizaci; dialogy byly
řízené testem a obnovení odložené. Nejde o automatický bootstrap původní
0.4.0 bez updateru ani o lidskou akceptaci v běžném profilu.

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
Ruční synchronizace od verze 0.2.3 hlásí počet synchronizovaných projektů,
zastaralých zadání a chyb. Zastaralé zadání, chyba části projektů i nulový
počet přiřazení vyvolají varování. Od verze **0.2.4** synchronizace také
automaticky obnovuje zadání již přiřazených schema-v2 projektů. Ponechá
potvrzený repozitář, lokální složku či `.code-workspace` a instrukce; nový
projekt ani změnu cíle sama nepotvrzuje. Auto Sync změnu načte při nejbližším
úspěšném cyklu (obvykle do 10 sekund), ruční synchronizace provede totéž.
Nejprve doručí čekající zprávy pod původní revizí. Má-li fronta více než
20 zpráv, další cykly ji postupně vyprázdní a pak obnoví zadání.
Viditelné TODO původní relace se otevře nad novým exportem.
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
Změna projektového HEAD označí relaci jako stale. Rozšíření 0.2.4 vytvoří
novou připnutou relaci pro stejné přiřazení; původní snapshot ani zprávy
nepřepisuje a nepřenáší do nové revize. Rozpracovaná obnova je uložená v
SecretStorage, takže restart dokončí také mapování či bind se ztracenou
odpovědí. Při odvolání přístupu nebo souběžné změně cíle obnova selže;
ruční kontrola patří do **Workspace: Nastavení projektů**.
Schema-v1 a starší rozšíření nadále vyžadují ruční obnovení přiřazení.
Zprávy zapsané do staré schránky až po přepnutí zůstávají v historické
schránce pro ruční posouzení. Nové zprávy zapisujte do nové relace.
Obnova souborů sama nepředává změnu do již běžící konverzace coding agenta;
agent musí číst aktuální export. Spouštění a řízené předání agentům je
samostatný navazující kontrakt DEV-02/DEV-04.

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
