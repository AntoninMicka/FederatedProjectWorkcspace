<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0037 — Identity, policy a automatická replikace federace

Datum: 2026-10-22. Stav: přijat cílový architektonický směr dávky
`UX-FEDERATION-02`; detailní návrh a runtime implementace jsou odloženy.

## Kontext

Dosavadní ADR 0021 odděluje lokální účty, peer trust, oboustranná mapování a
portable ACL, ale omezuje server nasazený desktopem na jediného vlastníka a
nespouští automatickou replikaci. Cílový model má podporovat více uživatelů
jednoho desktopového uzlu, obecné serverové uzly, hierarchickou správu a
automatickou federaci projektů uvnitř schválené skupiny. Návrh nesmí zaměnit
síťovou dosažitelnost, správní roli ani členství ve skupině za přístup k datům.

## Identity a druhy skupin

Uživatel je stabilní kvalifikovaný principal `(authority_id, subject_id)`, v UI
například `U1@A`. Jiný uzel drží pouze projekci stejného principalu pro
autorizaci, provenance a audit; nevytváří mu novou identitu ani nepřebírá
autoritu nad credentials. Hesla, password digesty, MFA secrets, session a
soukromé klíče se nefederují.

Budoucí centrální autorita A může poskytovat identity `U1@A`, `U2@A` a podepsané
skupinové claims všem uzlům. Z hlediska namespace a podpisové identity se může
tvářit jako specializovaný uzel s capability `identity-authority`, ale tím
nezískává capability projektového úložiště. Úplná LDAP/SCIM, OIDC a WebAuthn/TOTP
integrace je odložena do `AUTH-CENTRAL-01`.

Lokálně autoritativní účet smí získat správní pravomoc nejvýše `node-admin`.
Role `network-group-admin` a `network-admin`, které působí nad hranicí jednoho
uzlu, jsou platné pouze jako aktuální, ověřitelné tvrzení centrálního registru.
Lokální kopie takového tvrzení je pouze časově omezená projekce podle offline
pravidel níže; uzel ji nesmí vydat, povýšit ani po expiraci prodloužit.

Model rozlišuje:

- **network group** — schválenou množinu uzlů se společnou správou;
- **user group** — množinu kvalifikovaných uživatelů pro přidělování práv;
- **replication set** — konkrétní uzly a role pro automatickou repliku projektu;
- **project membership/ACL** — práva principalů ke konkrétním datům.

Stejný název ani členství v jedné z těchto množin automaticky nezakládá členství
v jiné. Síť, VPN ani discovery nejsou autoritou identity nebo oprávnění.

## Správní role a hranice pravomocí

Kanonické role budou verzované; pracovní názvy odpovídají uživatelskému návrhu:

- `network-admin` spravuje nejvyšší control plane federace, network groups,
  jmenování jejich správců a odvolání uzlů;
- `network-group-admin` spravuje členství uzlů ve vybrané network group a smí
  přijmout nebo odebrat uzel z federované skupiny;
- `node-admin` spravuje lokální uživatele a user groups uzlu a nastavuje
  transportní obálku mezi celými uzly;
- `group-admin` spravuje konkrétní user group, její členství a pravidla, podle
  nichž lze skupině udělit přístup zvenku;
- `user` řídí sdílení vlastních projektů; delegovaný `project-admin` může řídit
  projekt pouze v rozsahu výslovného projektu a udělených akcí.

Strop `node-admin` se týká autority lokálního účtu, nikoli pořadí všech rolí na
jedné ose: `group-admin` a `project-admin` jsou užší delegace omezené konkrétní
user group nebo projektem. Vyšší federační role `network-group-admin` a
`network-admin` bez centrálního registru nevznikají.

Federaci ostrovních uzlů bez centrálního registru řídí jejich `node-admin`.
Každý rozhoduje pouze za vlastní uzel; společný federační stav vzniká z
ověřených uzlových rozhodnutí, nikoli tím, že by se lokální správce jednoho uzlu
prohlásil za správce celé sítě. Přesný podpisový a quorum kontrakt zůstává
součástí návrhu policy a automatické federace.

Správní role samy neudělují `read`, `write` ani `export` k projektovým datům.
`network-admin`, `network-group-admin` a `node-admin` mohou připravit cestu a
maximální obálku přenosu, ale projekt se nepřenese bez odpovídajícího rozhodnutí
vlastníka nebo `project-admin`. Ani vlastník projektu nemůže přenosem překročit
privacy, policy uzlu nebo cílovou přijímací policy.

## Jednotné vyhodnocení policy

Jeden verzovaný policy engine vyhodnocuje oddělené akce `read`, `write`,
`review`, `manage`, `export`, `receive`, `replicate` a `delegate`. Efektivní
akce jsou průnikem origin ACL, privacy, aktivního trust/scope, node transportní
policy, project/branch policy, přijímací policy a lokálních práv uživatele.
Neznámá verze, chybějící vstup nebo konflikt znamenají deny. `local-only` nikdy
neopustí zdrojový uzel a příjemce může původní práva pouze zúžit.

Každé rozhodnutí musí vrátit vysvětlitelný důvod a přesné revize všech vstupních
politik. Změna členství, role nebo policy vytváří novou revizi; nepřepisuje
historické rozhodnutí.

## Automatická replikace

Zařazení uzlu do network group samo nereplikuje žádný projekt. Vlastník nebo
oprávněný `project-admin` explicitně zařadí projekt do replication setu, jehož
uzly, směr, branch/ref scope, privacy a akce již dovolují všechny nadřazené
politiky. Po tomto schválení běžné přenosy probíhají automaticky.

První implementační úroveň používá jeden primární zapisující uzel a automatické
read-only repliky. Převzetí primární role je samostatná autorizovaná operace;
multi-master zůstává budoucí rozšíření. Automatika smí provést validovaný
fast-forward. Divergence, neplatný kandidát, změněná policy, neúplná historie
nebo revokace vytvoří viditelný konflikt a nesmějí být automaticky sloučeny.

Autorizovaný cílový uzel v první verzi ukládá čitelná data. End-to-end šifrování
proti administrátorovi cílového uzlu je odloženo; transportní šifrování a běžná
ochrana dat v klidu tím nejsou zrušeny.

## Offline, revokace a odstranění

Podepsaná projekce identity, členství a politiky je bez spojení platná osm hodin.
Předem schválená policy smí limit zvýšit nejvýše na 24 hodin; vypršelá autorita
si nesmí sama prodloužit platnost během výpadku. Centrálně vydané role
`network-group-admin` a `network-admin` lze během tohoto okna použít pouze v
posledním dovoleném rozsahu. Bez centrálního registru řídí ostrovní federaci
`node-admin` jednotlivých uzlů. Nové exporty, zvýšení oprávnění a změny federace
vyžadují aktuální autoritu. Po expiraci se nové účinky zastaví a rozpracovaný
stav se zachová pro bezpečné pokračování.

Revokace zastaví budoucí přenosy a přístupy a může vyžádat best-effort odstranění
spravované repliky s potvrzením. Potvrzení nedokládá smazání nezávislé kopie,
zálohy nebo dříve exportovaných bajtů; systém takovou záruku nesmí tvrdit.

## Desktopový uzel a recovery

Jeden fyzický desktop je jeden uzel s jednou node identity a systémovou node
službou. Každá uživatelská UI instance jedná pouze za právě přihlášený OS účet,
který služba ověří lokálním IPC; uživatelský proces nesmí dodat vlastní údaj o
UID jako autoritu. Sdílené uzlové úložiště vynucuje policy před vydáním dat.

Nouzový přístup používá lokální OS autoritu `root` nebo zvláštní systémový účet
jen k vyvolání recovery mechanismu. Nejde o běžné webové přihlášení root heslem.
Recovery vydá časově a účelově omezenou session, je výrazně auditovaná a sama
neuděluje čtení všech projektů. Kopie centrálního hesla, password digestu nebo
TOTP secretu není recovery.

## Persistence a migrační hranice

Registry identit, skupin, policies a replication intents mají odlišnou autoritu
od projektového Gitu a obnovitelného projektového indexu. Budoucí implementace
musí před zápisem popsat journal, CAS, podpisy, atomicitu jednotlivých registrů
a recovery při částečném přenosu; tento návrh žádný nový runtime zápis nezavádí.

Toto rozhodnutí ruší trvalé osobní omezení serveru nasazeného desktopem z ADR
0021. Původ nasazení se zachová jako auditní/bootstrap provenance, ale server lze
explicitně převést na obecný víceuživatelský uzel. Současné bearer přihlášení,
registry v2 a public-only přenos se touto dokumentací samy nemění.

## Etapizace implementace

První implementační řez je záměrně menší než cílový model tohoto ADR. Pro
potřebu jednoho správce propojí dva jeho uzly, použije jejich existující lokální
účty a roli `node-admin`, vyžádá ruční schválení peeru i konkrétního projektu a
udržuje jednu read-only repliku z jednoho primárního zapisujícího uzlu.

Tento řez nezavádí centrální registr, MFA, sdílené uživatele, síťové správní
role, obecný policy engine ani multi-master. Nad existujícím peer trust,
oboustranným mapováním účtů a portable ACL smí přidat pouze úzký podepsaný grant
pro přesnou dvojici uzlů, projekt, ref a směr replikace. Autorizace pokrývá celý
dosažitelný Git graf a `local-only` se vždy odmítne. Tento grant nesmí obejít
privacy/ACL ani se vydávat za splnění celého Gate M5. Detailní cílový návrh
zůstává otevřený pod původními ID `UX-FEDERATION-02-B` až
`UX-FEDERATION-02-E` a `AUTH-CENTRAL-01`.
Konkrétní autority, transport a crash recovery tohoto omezeného řezu uzavírá
[ADR 0038](0038-personal-project-replication.md).

## Zbývající rozhodnutí

Následující otázky zůstávají záměrně otevřené. Návrh z nich zatím neodvozuje
další capability stropy, zákazy ani povinnou implementační variantu; rozhodnou
se až podle konkrétních scénářů a zjištění v dalších částech návrhu. To nemění
již přijaté fail-closed hranice pro neznámou policy, `local-only`, credentials
a neautorizovaný přenos.

- přesný lifecycle vlastnictví projektu při více vlastnících nebo deaktivaci;
- protokol a oprávnění pro bezpečné převzetí primární role;
- strojové schéma policy, precedence explicitního deny a dědičnost;
- přesný offline režim čtení podle privacy třídy;
- recovery operace, jejich limity a schvalování;
- implementační dávky pro účty/MFA, policy engine, registry skupin a replikaci.
