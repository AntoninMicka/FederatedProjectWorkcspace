<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# Předání fronty a dokončení úkolů — PLAN-QUEUE-02

Větev: `feature/plan-queue-02`, základ `33f5cde` / PR #119. Implementační
kontrakt a recovery: [ADR 0062](adr/0062-pinned-queue-handoff.md).
Aktuální plán drží Workspace, tento soubor je uživatelský návod.

## Předání

1. Restartujte backend s novými zdroji a aktualizujte rozšíření stejného ID
   na 0.4.0. Obnovte okno VSCodia; existující credentials, mapování, schránky
   a historie se zachovávají.
2. Ve Workspace v Nastavení → IDE vyberte připojení a aktuální mapping
   projektu s povoleným exportem podkladů. V roadmapě znovu ověřte frontu,
   pokud se změnil plánový commit. Vyberte konkrétní tasky rozpracované dávky.
3. Stiskněte **Předat frontu do IDE**, zvolte mapping (při více mapováních jeho
   ID) a zadejte přesný `git rev-parse HEAD` cílového zdrojového repozitáře.
   Výsledek ukáže packet ID nebo blockery. Nesouhlas s HEAD, chybějící podklad
   nebo vypnutý export se nesmějí vydávat za úspěšné předání.
4. Ve VSCodiu synchronizujte Workspace. Pohled **Fronta úkolů** zachová
   pořadí; ukazuje zahajitelnost, agentní hlášení a lidské přijetí. Navazující
   položka je jen k prohlížení. U zahajitelné položky použijte **Předat položku
   fronty agentovi**. Do schránky se zkopírují cesty manifestu, AGENT.md a inboxu.
5. Agent musí explicitně načíst manifest, AGENT.md, exportovaná scoped pravidla
   i místní AGENTS.md. Konflikty pravidel sám tiše nepřekrývá. Manifest obsahuje
   původní snapshot; queue.json je zvlášť poslední známý stav. Při nedostupném
   spojení se stav nesmí považovat za nově potvrzený.

## Hlášení agenta a přijetí člověkem

Agent zapíše UTF-8 JSON do dočasného souboru a atomicky jej přejmenuje na
`inbox/<message_id>.json`. Příklad je schéma, nikoli skutečný výsledek testů:

```json
{
  "message_id": "UUID",
  "task_id": "TASK-01",
  "kind": "completed",
  "body": "Konkrétní shrnutí implementace a omezení",
  "revision": "přesné manifest.revision",
  "repository_commit": "skutečný Git HEAD zdrojů",
  "queue_packet_id": "SHA-256 připnutého manifestu",
  "reported_by": "agent",
  "evidence": {
    "tests": "Skutečně provedené kontroly a výsledky, nebo výslovně neprovedeno",
    "diff": "Commit nebo přesný odkaz/popisek diffu k review"
  }
}
```

Má-li úkol checklist, je třeba doplnit existující explicitní `checklist`
seznam `{index, checked}`; celý úkol nelze přijmout s nesplněnými podmínkami.
Každý nový report má vlastní UUID. Původní zpráva se po odeslání nepřepisuje.
Označení `reported_by` je deklarace původu, nikoli kryptografická identita.

Po synchronizaci agentní hlášení pouze nastaví samostatný příznak. Člověk
ve Workspace otevře **Nastavení → IDE → zprávy projektu**, posoudí shrnutí,
testy, diff a vybraný task/checklist a použije **Přijmout po posouzení** nebo
**Odmítnout**. Teprve přijetí mění původní roadmapu a zaznamená lidskou akceptaci.
Není potřeba další povinné potvrzení v IDE. Následující synchronizace vrátí
výsledek do pluginu; Workspace fronta ukáže odděleně agentní a uživatelský flag.

Přijetí A může odblokovat B, přestože původní manifest zůstává stejný.
Server uzná jen přesný řetězec přijetí z tohoto packetu; jiné změny plánu
vyžadují explicitní review a nové předání. Pokud v průběhu práce agent zároveň
změní jiný task/roadmapu, nesmí se starý balíček automaticky přeznačit za current.
Container s otevřenými potomky nelze dokončit místo nich; zařaďte jeho tasky.

## Chyba a obnova

Při unknown/timeoutu nejprve načtěte stav a původní receipts. Stejné UUID se
stejnými bajty je idempotentní; jiné bajty se stejným UUID se odmítnou. Při
připraveném review obnovte jeho původní operation ID přes **Dokončit připravené
review**; nevytvářejte nový pokus o přijetí. Bloby poškozené nebo změněné mimo
exportní cache vyžadují posouzení, nikoli automatické přepsání.

Při změně pracovní fronty, cizím commitu, revokaci či změně scope publikuje
nový balíček oprávněný uživatel Workspace. Aktivní mapping se kvůli packetu
automaticky nepřepáruje. Zachovejte původní zprávy a credentials a opravte
konkrétní stale stav; nevracejte starý port a nevytvářejte druhý živý TODO.

## Akceptace

Automatické ověření a izolovaný native host jsou technické důkazy. Ručně
ověřte v běžném profilu celý tok A → B: export včetně podkladů, B nejprve
pouze k zobrazení, agentní report A, uživatelské přijetí A ve Workspace,
zobrazení oddělených flags a odblokování B. Opakovaná synchronizace nesmí
vytvořit další commit. Odmítnutí nesmí označit úkol za dokončený.

Zdroj schváleného zadání: projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
`PLAN-QUEUE-02`, HEAD `7e62e086fe010c4af0fef208946572a9d5e5c33f`,
exportní revize `d260870402c0ca5f48231320928793cc9d9b16848a4f4aa5fcf973903bd9c7f5`.
Task zůstává otevřený do lidské akceptace; tento návod jeho stav nemění.

## Technické výsledky implementačního řezu, 31. 10. 2026

Finální `python3 -m unittest discover -s tests -v`: **1164 testů, 40 skipped,
OK**, 300,781 s. Cílené backend/Node/HTTP/review testy prošly, včetně řízených
přerušení a samostatného subprocess testu determinismu packet ID se dvěma
různými Python hash seedy. Syntaxe Pythonu a sdíleného JS, dokumentační odkazy
a `git diff --check` prošly.

Izolovaný skutečný VS Code extension host nainstaloval VSIX 0.4.0, aktivoval
rozšíření a nové příkazy, ověřil mapování, ordinary-file receipt/retry a obnovu
po změně loopback portu bez nového párování. Samostatná Node integrace používá
skutečné HTTP a filesystem pro celý tok publikace → cache/hardlinky → agentní
inbox → lidské review → flags fronty → A/B/C. Tyto dvě úrovně důkazů nejsou
ruční akceptací plného toku v běžném VSCodium profilu. Ta zůstává otevřená.

Běžný uživatelský backend ani IDE profil se v rámci implementace neaktualizoval.
Generický VSIX pro ruční aktualizaci neobsahuje pairing ani credentials.
Autoritativní `PLAN-QUEUE-02` zůstává otevřený; zdrojový commit/push/PR/merge
se neprovedl. Schválené uzavření `PLAN-QUEUE-01` bylo samostatnou nativní
plánovou operací a není zaměňováno s novou implementační akceptací.
