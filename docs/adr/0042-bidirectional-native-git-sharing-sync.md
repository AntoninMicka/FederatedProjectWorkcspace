<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0042 — Obousměrná interní synchronizace nativním Gitem

Datum: 2026-10-23. Stav: přijato a implementováno v
`F-M5-SHARING-SYNC-01`; automatické ověření prošlo, fyzická desktop ↔ LXC
akceptace obou směrů, návratu po restartu a zachování divergence prošla.

Doplnění 2026-10-26: ADR 0056 rozšiřuje tutéž obousměrnou operaci a její
durable journal o projektová RW chatová vlákna. Git pravidla níže se nemění;
chatový payload má vlastní fast-forward/fork strategii.

## Kontext a rozsah

Katalog z ADR 0041 oznamuje jen UUID a název projektu. ADR 0040 požaduje pro
`same-team` automatický obousměrný přenos všech projektů a jejich větví a pro
`same-company` jen projekty a větve povolené místní maticí. Starší ADR 0038
řeší pouze podepsaný směr primary → read-only replica. Nový řez jej neruší jako
recovery základ, ale nesmí jednosměrný grant vydávat za cílový interní sync.

`external`, federace identit/rolí, automatický merge, řešení konfliktu a export
bez historie jsou mimo tuto dávku. Synchronizace dat sama neuděluje lokálnímu
uživateli projektovou roli.

## Reuse rozhodnutí

- **Reuse:** Git CLI a `git_transfer.validate_history`, Ed25519 node identity,
  peer CA a HTTPS ochrany, `Administration` schema v6, katalog, projektový
  writer lock, Journal/Index a `ProjectCreation` registrace.
- **Adapt:** `project_replication` signed bounded bundle a lost-response vzor
  na symetrickou výměnu inventur a volitelných bundle; node-local SQLite
  journal uchová přesný request i response. Přenos zůstává `git bundle`, ne
  vlastní serializace commitů.
- **Reject:** automatický merge/rebase, force push, kopírování worktree,
  synchronizace `.git` adresáře, nový Git writer, SSH heslo a browser bearer.
  Smart-HTTP server se nyní nepřidává: stávající připnutý node endpoint a
  bundle zachovávají menší síťovou plochu a již ověřené recovery hranice.

## Scope a protokol

Jedna operace se týká jednoho project UUID. Obě strany podepíší inventuru
`refs/heads/*` ve tvaru ref + commit ID. `same-team` smí exportovat všechny
větve všech dostupných projektů. `same-company` smí exportovat pouze projekt s
lokálním záznamem matice a větve po aplikaci `selected-only` nebo
`all-except-hidden`. Příjem dat je dovolen jen od schváleného peeru se stejnou
interní úrovní; `external` a `unspecified` jsou fail-closed.

Liší-li se inventura od posledního potvrzeného přenosu, strana přiloží jediný
bounded nativní `git bundle` s přesně vyjmenovanými povolenými refs. Jinak se
přenese jen malá inventura. Odpověď používá stejný formát a může nést bundle
opačného směru, takže serverový dynamický klient nemusí znát zpětný endpoint.
Podpis váže operation ID, oba uzly, project UUID, scope, všechny heady,
velikost a SHA-256 bundle. Browser API credential není node credential.

Každý dosažitelný commit každého přijatého refu projde `validate_history`.
Povoleny jsou `public`, `project` a `confidential`; `local-only`, neklasifikovaný
soubor, symlink, submodule, neplatný přechod nebo překročení limitu se odmítne.

## Refs, divergence a lokální oprávnění

Chybějící projekt lze z validovaného bundle zaregistrovat jako běžný lokální
projekt. Chybějící větev lze založit. Existující větev se změní jen když je
její současný head předkem kandidáta; protější starší head nic nepřepisuje.
Při divergenci zůstane lokální větev beze změny a kandidát se zachová pod
`refs/federation/incoming/<peer UUID>/<branch>`. Nikdy se automaticky
nemerguje, nerebasuje ani force-updateuje.

Přenos projektu neobchází lokální RBAC. Nově přijatý projekt lze číst podle
lokálního účtu a role; lokální zápis nadále vyžaduje místní oprávnění. Tato
dávka nefederuje credentials, session ani automaticky nevytváří členství.

## Persistentní vrstvy a recovery

1. Git-backed `Administration` je autorita trustu, sharing level a lokálního
   exportního scope; změna matice po přípravě zneplatní neodeslaný request.
2. Projektový Git je autorita obsahu a refů. Aktualizace jsou serializované
   project writer lockem; aktuální větev používá pending journal marker.
3. Node-local sync SQLite journal drží přesný podepsaný request/bundle a na
   příjmu přesnou odpověď. Není policy autoritou ani projektovým indexem.
4. Staging refs a bundle jsou obnovitelný pracovní stav. Projektový SQLite
   Index se po změně aktuální větve přestaví z nového HEAD.

Pád před durable inbound záznamem nemá účinek. Po něm lze tentýž operation ID
opakovat jen se shodnými bajty. Pád před změnou refů ponechá staging; po části
bezpečných ref update se retry dopočítá ze stejného kandidáta. Po změně aktuální
větve se recovery vždy roll-forward dokončí checkoutem a rebuildem indexu.
Přesná odpověď se uloží před odesláním; ztracená odpověď proto vrátí při retry
stejné potvrzení a bundle. Odlišný payload pod stejným operation ID se odmítne.

Ruční spuštění běží ve volatilním workeru, ale používá tentýž durable journal.
Požadavek na zrušení je kooperativní: před přípravou, před síťovým přenosem a
před lokální publikací zastaví další krok a ponechá outbound záznam pro bezpečný
retry. Vzdálený uzel už mohl přijatý request publikovat, proto zrušení nikdy
neprovádí destruktivní rollback; následující synchronizace rozdíl znovu
zrekonsoliduje. Pád procesu ukončí volatilní worker a existující journal se
obnovuje stejnými pravidly jako dosud.

Automatický scheduler nesmí po přechodné chybě prvního průchodu skončit. Chybu
registru nebo katalogu po startu zachytí na hranici celého průchodu, nejvýše za
pět sekund pokus zopakuje a po úspěchu se vrátí k běžnému intervalu. Jednotlivé
projektové chyby nadále izoluje uvnitř průchodu.

## Omezení

Limit zůstává 500 dosažitelných commitů na validovaný head a 64 MiB na jeden
bundle. První verze přenáší celé povolené refy, nikoli thin bundle; inventura
zabraňuje opakovanému přenosu při nezměněných headech. Retence dokončených
journalů, automatické řešení divergence, shallow/partial clone a smart Git
HTTP/SSH transport zůstávají navazující optimalizace, nikoli podmínka tohoto
bezpečného řezu.
