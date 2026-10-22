<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0038 — Osobní replikace projektu mezi dvěma uzly

Datum: 2026-10-22. Stav: přijato jako implementační kontrakt
`F-M5-PERSONAL-SYNC-01-A`; runtime implementace ještě neexistuje.

## Kontext a rozsah

První praktický řez ADR 0037 má jednomu člověku zpřístupnit automatickou
read-only repliku projektu mezi dvěma vlastními uzly. Dnešní přenos vytvoří
nový LXC projekt přes SSH a dovolí pouze historii složenou z `public` entit.
Umí připnout peer identity, vytvořit přesný Git bundle, uchovat jej v odchozím
SQLite journalu a bezpečně zaregistrovat nový projekt. Neumí však aktualizovat
existující projekt, udržovat desired state ani pokračovat automaticky bez
interaktivního SSH/askpass.

Tato dávka nepřidává centrální identitu, MFA, sdílené účty, obecný policy
engine, multi-master ani automatické řešení divergence. Jeden uzel je
`primary`, druhý `read-only-replica`; směr lze změnit až samostatnou budoucí
operací převzetí primární role.

## Reuse rozhodnutí

- **Reuse:** `Administration` peer trust, Ed25519 `MappingSignatures`, aktivní
  oboustranné mapování účtů, `Projects`, Git CLI ochrany, `ProjectCreation`,
  Workspace writer lock a obnovitelný `Index`.
- **Adapt:** `git_transfer` pro bundle, validaci úplné historie a přijímací
  staging; `transfer_outbox` pro přesný durable payload a lost-response retry;
  stávající webovou stránku Federace a TLS CA uloženou přes `trust_ca`.
- **Rewrite v úzkém rozsahu:** jednorázový SSH import nenabízí neinteraktivní
  obousměrný transport ani update existujícího projektu. Nahradí jej pouze pro
  replikaci bounded HTTPS endpoint sdílený serverovým webem a desktopovým
  `NetworkBackend`; SSH zůstane nástrojem deploye a ručního původního přenosu.
- **Reject:** nový Git writer, message broker, obecný synchronizační framework
  a přímé převzetí nalezených externích synchronizačních komponent. Soukromá
  inventura nepřinesla komponentu kompatibilní s Git autoritou, současným
  journalem, privacy a licenčními podmínkami; žádný její kód ani název se
  nepřebírá.

`validate_rights` z ADR 0021 zůstává použitelným fail-closed validátorem
portable ACL, ale současný projekt takový úplný manifest nevytváří a validátor
nedokazuje vazbu na všechny bajty dosažitelné Git historie. Osobní řez proto
nesmí jeho samotné zavolání vydávat za autorizaci přenosu.

## Autority a grant

Federační Git registr `Administration` se verzovaně rozšíří o replikační
záznamy. Autoritativní specifikace grantu váže alespoň:

- stabilní grant ID a verzi schématu;
- ID a role obou uzlů (`primary`, `read-only-replica`);
- ID obou mapovaných lokálních účtů a ID aktivního mapování;
- project UUID, přesný ref (v první verzi `refs/heads/main`) a směr;
- dovolené privacy třídy a akce `read`/`replicate`;
- revizi identity obou peerů.

Specifikaci nezávisle potvrdí oba uzly stejným podpisovým/pin protokolem jako
mapování účtů. Zdrojové potvrzení smí vzniknout jen z lokální relace vlastníka
projektu (`project.json.author_id`) nebo lokálního `project-admin`; potvrzení
transportu navíc vyžaduje lokálního správce uzlu. V osobním desktopovém režimu
mohou obě pravomoci náležet témuž ověřenému OS uživateli. Příjemce potvrzuje
umístění read-only repliky a účast svého uzlu. Peer trust, mapping, grant i
lokální zapnutí musí být současně aktivní; žádná z těchto vrstev sama
replikaci nepovolí.

Grant je úzkou project-scope origin autorizací tohoto osobního řezu. Každý
odesílaný commit se znovu sémanticky validuje, všechny jeho entity musí mít
privacy obsaženou v grantu a `local-only` je bez výjimky odmítnuto. Odesílatel
i příjemce nezávisle projdou celý dosažitelný graf přesného refu. Budoucí
portable per-entity ACL nebo obecný policy engine mohou grant dále zúžit, ale
nepotřebují měnit jeho stabilní identitu.

Lokální `enabled`/`paused` stav je autoritou pouze pro účast daného uzlu a
publikuje se atomicky s jeho kopií grantu. Revokace je podepsaný tombstone a
zastaví nové operace; již vydané bajty ani nezávislé kopie neslibuje smazat.

## Transport a protokol operace

Automatická synchronizace nepoužívá SSH heslo ani browserový bearer token.
Serverový `WebHandler` a desktopový `NetworkBackend` vystaví jediný bounded
HTTPS endpoint pro stav/příjem replikační operace. Klient ověří uloženou CA a
node identity; žádost obsahuje kanonická metadata operace a Ed25519 podpis
zdrojového uzlu. Podpis váže operation ID, grant ID/revizi, oba uzly, project
UUID, ref, očekávaný base commit, candidate HEAD, velikost a SHA-256 bundle.
Příjemce znovu ověří aktivní peer, mapping a grant a vrátí podepsaný durable
receipt. Operation ID a digest zajišťují deduplikaci bez spoléhání na hodiny.

Přenáší se pouze objektový graf nutný pro validovaný fast-forward. Limity první
verze zůstávají nejvýše 500 dosažitelných commitů a 64 MiB bundle. Endpoint
přijímá bounded binární payload odděleně od běžného JSON/browser API; nesmí
zvýšit obecný limit webových requestů ani zpřístupnit projekty přes probe.

## Persistentní vrstvy a recovery

Autority zůstávají oddělené:

1. Git registry `Administration` je autoritou peerů, mappingů, grantů,
   revokací a lokálního desired state; jeho publish zůstává flock + ref CAS.
2. Projektový Git je autoritou replikovaných dat.
3. Projektový `journal.sqlite` dostane jediný pending marker externí replikační
   operace. Všechny běžné čtecí a zapisovací cesty jej musí respektovat; lokální
   zápis do read-only repliky se odmítá i mimo UI.
4. Node-local SQLite transfer journal mimo projektový Git uchovává přesný
   bundle, request, receipt a transportní stav. Není projektovým indexem ani
   policy autoritou.
5. Přijímací staging a dočasný Git ref jsou obnovitelný pracovní stav.
   Projektový SQLite `Index` je pouze projekce výsledného HEAD.

Pořadí locků je node-local transfer journal → project writer lock; během
síťového čekání se project writer lock nedrží. Odesílatel nejprve jednou uloží
přesný bundle a request do outboxu a teprve potom volá síť. Příjemce před změnou
Gitu pod writer lockem zapíše pending marker s operation ID, request digest,
expected base a candidate HEAD.

Přijímací recovery používá následující hranice:

- před durable requestem není co obnovovat;
- po requestu a před staging refem lze tentýž bundle bezpečně znovu přijmout;
- po vytvoření staging refu se z něj znovu ověří digest, grant a celý graf;
- `refs/heads/main` se změní jediným CAS pouze pokud stále odpovídá expected
  base; divergence ponechá staging a viditelný konflikt, nikdy merge;
- po úspěšném CAS je nový Git commit autoritou a operace se pouze roll-forward
  dokončí checkoutem, fsync, obnovou indexu a durable receiptem;
- ztracená odpověď vede ke status/retry stejného operation ID; příjemce vrátí
  stejný receipt a odesílatel teprve potom označí outbox za dokončený.

První vytvoření repliky reuseuje izolovaný import a `ProjectCreation` journal;
grant a read-only guard musejí být durable dříve, než se projekt objeví v
katalogu jako použitelná replika. Aktualizace existující repliky nesmí používat
`Workspace.transact`, protože nevytváří nový lokální commit; rozšíří společný
journal o výslovně rozpoznaný externí operation kind a recovery. Neznámý kind
se odmítne, nikoli heuristicky opraví.

## Stav a UI

Odvozený stav synchronizace je `disabled`, `idle`, `pending`, `offline`,
`rejected`, `conflict` nebo `error`; receipt navíc nese poslední úspěšné HEAD.
UI může stav zobrazit a vyžádat zapnutí, pauzu nebo revokaci, ale není autoritou
policy ani dokončení. Read-only replika blokuje editory a všechny aplikační
writery serverově; přímý zásah mimo aplikaci se projeví jako dirty/divergent a
automatika jej nepřepíše.

## Omezení a navazující práce

Scheduler, přesná frekvence pollingu a uživatelské ovládání patří do dalších
úkolů stejné dávky. Převzetí primární role, multi-master, automatický merge,
retence dokončených bundle a plný portable ACL/policy model zůstávají mimo
tento řez. Tento ADR není důkaz runtime implementace ani fyzické dostupnosti
desktopového HTTPS endpointu.
