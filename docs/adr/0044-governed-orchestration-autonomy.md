<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0044 — Řízená autonomie orchestračních akcí

Datum: 2026-10-23. Stav: přijato; základ registru a durable fronty je
implementován v rozpracované dávce `F-M4-AUTONOMY-01`.

## Kontext a rozhodnutí

Jednotlivé workflow již mají přesné Context Manifesty, potvrzení a vlastní
journaly, ale nemají společný kontrakt pro ruční nebo bounded automatické
řazení kroků. Přidává se proto uzavřený action registry a node-local fronta.
Registry deklaruje přesnou verzi akce, účinek, permissions, dovolené privacy,
požadované vstupy, maximální cost, automatizovatelnost a potvrzení. Neznámý
typ/verze, chybějící handler nebo změněný descriptor se odmítne; neexistuje
fallback podle podobného názvu nebo schopnosti.

Planner i LLM jsou nedůvěryhodní navrhovatelé. Připravený plán má nejprve stav
`proposed`. Uživatel musí v připojeném UI potvrdit digest přesného plánu,
režimu `manual`/`automatic` a budgetu; samotné plannerem uvedené
`mode=automatic` frontu neaktivuje. Změna dosud nevykonaného plánu zahodí
všechna potvrzení a vrátí jej do `proposed`.

Každý krok před dispatch znovu ověří descriptor, oprávnění, privacy, expected
Git HEAD, závislosti, cost a časový budget. Automaticky smí projít pouze akce,
jejíž descriptor to výslovně povoluje a nevyžaduje potvrzení. Ruční režim
vyžaduje potvrzení každého kroku. Globální i workflow pause jsou
deterministické; ztráta UI pozastaví běžící frontu a resume vyžaduje znovu
připojené UI.

## Nepřekročitelný lokální checkpoint

Akce s účinkem `local-content-create` musí mít confirmation
`exact-local-output` a nesmí být automatizovatelná. Její vstup předem váže
přesný cíl, content type, SHA-256 obsahu, privacy a neprázdnou provenance.
Approval digest navíc váže workflow, krok a přesnou revizi descriptoru. Každý
další lokální výstup je jiný krok s jiným approval; countdown, aktivace plánu
ani označení modelu `final` jej nenahrazují.

Fronta sama obsah nevytváří. Reviewovaný handler po tomto checkpointu volá
existující doménovou service, která si ponechá vlastní Workspace journal,
validaci a potvrzení. Stejně zůstávají přísnější existující hranice externích
requestů, publikace, změn a mazání.

## Persistence a recovery

`autonomy-queue.sqlite` je node-local autorita plánu, pořadí, approval digestů,
budgetu a stavů fronty. Má vlastněný adresář 0700, soubor 0600 a SQLite
`synchronous=FULL`. Není projektovým indexem, nesynchronizuje se a nezapisuje
projektový Git. Registry je staticky reviewovaná konfigurace; doménové
journaly zůstávají autoritou vlastních účinků.

- Pád ve `proposed`, `awaiting-approval` nebo terminálním stavu nezpůsobí
  dispatch; UI je po restartu vždy odpojené.
- `queued` nebo `running` bez zahájeného účinku se po restartu změní na
  `paused` a vyžaduje připojení UI a resume.
- Před voláním handleru se krok durable přepne do `dispatching`. Pokud restart
  najde `dispatching`, krok i workflow jsou `unknown`; fronta jej sama nikdy
  neopakuje. Doménový adapter může později dodat vlastní explicitní
  reconciliation, ale obecná fronta z absence výsledku úspěch nehádá.
- Známá výjimka handleru končí `failed`. Úspěšný bounded JSON výsledek se
  uloží jako mezivýsledek a teprve další vědomé volání může postoupit frontu.
- Cancel mění pouze dosud nezahájené kroky; právě `dispatching` účinek nelze
  vydávat za odvolaný.

## Reuse a hranice první verze

Implementace reuse/adaptuje striktní parsery a statické katalogy
`output_capabilities`, vlastněný SQLite journal `RoleWorkflows`, přesné approval
digests a `dispatching/unknown` recovery z output/backend executorů. Nepřebírá
se agent framework, message queue, provider pool ani druhý projektový writer.
Soukromá inventura neposkytuje komponentu se stejným Context Manifest, RBAC,
privacy, per-output approval a recovery kontraktem, proto se z ní nekopíruje
kód ani názvy.

První registry obsahuje typy read-only analýza, externí request, rolový handoff
a lokální artefakt. Jde o orchestrační obálku a testovací integrační kontrakt,
nikoli ještě zapojení automatického hledání `F-M3-SEARCH-03`, obecný background
worker nebo autonomní publikaci. Viditelné desktop/web ovládání a konkrétní
produkční adaptéry jsou další části téže dávky a její aktuální stav eviduje
[TODO](../../TODO.md).
