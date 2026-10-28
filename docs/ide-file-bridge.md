<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# IDE bridge přes běžné lokální soubory

V projektu otevřete **Úkoly → Propojení s VS Code / VSCodium**. Vyplňte
přesnou URL `git remote get-url origin` zdrojového repozitáře nebo jeho
absolutní lokální cestu a instrukce pro relaci. Plán musí mít stabilní task ID
podle [plánovacího kontraktu](task-planning.md). Žádný agent se nespustí.

Klikněte na **Připravit instalaci a propojení**. Desktop po nativním potvrzení
použije dostupné `code` / `codium --install-extension`. Web stáhne VSIX;
nainstalujte jej lokálně přes Extensions → Install from VSIX. Uložte jej mimo
Git a po instalaci smažte: obsahuje projektově omezený token s platností 30 dní.
Při reinstalaci existujícího rozšíření spusťte příkaz Propojit projekt ručně.

V IDE potvrďte **Workspace: Propojit projekt**, server/projekt a vyberte
zdrojový repozitář. Jeho identita musí přesně souhlasit se zadáním. Pro HTTPS
se standardně použije systémová důvěra, vlastní CA lze vybrat ze souboru.
Žádná volba nevypíná ověření certifikátu. Obsah local-only se neexportuje;
to platí i pro desktop. Přístupové údaje jsou v SecretStorage, ne ve schránce.

Příkaz **Workspace: Otevřít komunikační soubory** otevře TODO a zkopíruje
absolutní cestu ke složce. Je v globalStorage editoru, mimo zdrojový repozitář:

```text
sessions/<session-id>/
  TODO.md
  INSTRUCTIONS.md
  snapshot.json
  STATUS.json
  inbox/<message-id>.json
  receipts/<message-id>.json
```

TODO/instrukce jsou export a lokální úpravy se při sync nahradí. Zdrojové
kanonické definice i z included dokumentů drží snapshot.json. Nejde o další
verzovaný plán. Soubory lze explicitně předat coding agentovi, pokud jeho
oprávnění dovolují přístup k této cestě; bridge mu práva automaticky nepřidává.

Výsledek nebo dotaz odešlete přes **Workspace: Odeslat výsledek nebo dotaz**.
Jiný plugin může napsat JSON do `inbox/` s novým UUID jako názvem souboru:

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

Povolené kind jsou completed, clarification a message. Zpráva má nejvýše
16 KiB textu. Zapisujte do dočasného `.tmp` a hotový soubor zveřejněte
přejmenováním. Již odeslané ID a payload neměňte; opravná zpráva dostane nové
ID. Plugin prochází schránku každých 10 sekund i po restartu IDE; ruční
**Workspace: Synchronizovat zprávy** provede totéž ihned.

`received` v receipts potvrzuje trvalé přijetí, nikoli splnění úkolu. Aplikace
načte zprávy akcí **Načíst propojení a zprávy**. Člověk posoudí uvedené důkazy
a výsledek a případně upraví TODO existujícím editorem. Změna projektového
HEAD označí relaci jako stale a nové zprávy mají stale receipt. Vytvořte nové
propojení nad aktuálním zadáním; stará zpráva se nepřenese automaticky.

**Odvolat propojení** v aplikaci zneplatní serverový přístup. Příkaz
**Workspace: Odpojit lokální bridge** zastaví lokální synchronizaci a odstraní
aktivní credential; soubory i zprávy ponechá. Pro úplné odpojení proveďte obojí.
Při ztrátě odpovědi bridge bezpečně opakuje stejnou zprávu, backend nezdvojí
její přijetí. Při ztrátě instalační odpovědi může vzniknout nepoužitá relace;
odvolejte ji v přehledu a připravte novou.

První verze je pro lokální desktopové IDE s webovým nebo desktopovým
Workspace. Remote SSH, WSL, Codespaces a browser-only IDE nejsou podporované.
Windows adaptér je připravený, fyzická instalace a Windows ACL nejsou ověřeny.
Nespouští se Codex ani jiný coding agent a nepřidává se MCP/FUSE/virtuální FS.

Reprodukovatelný skutečný smoke v izolovaném profilu (vyžaduje dostupné GUI):
`python3 -m scripts.ide_bridge_smoke --editor codium`.
Výsledky ověření jsou v TODO, po uzavření dávky ve WORK_LOG.
Recovery a autoritu podrobně popisuje [ADR 0060](adr/0060-local-file-ide-bridge.md).
