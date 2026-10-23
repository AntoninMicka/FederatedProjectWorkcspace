<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Správa uživatelů a evidence federace

Po běžném webovém deploy otevřete aplikaci stávajícím přístupovým klíčem.
Tento klíč zůstává lokálním bootstrap/recovery správcem federace; nesdílejte jej
s běžnými uživateli. Tlačítko **Uživatelé a federace** otevře samostatné
záložky Uživatelé a Federace s oddělenými tabulkami účtů, uzlů a mapování.

Vytvořte uživatele a bezpečně mu předejte jednorázově zobrazený přístupový klíč.
Člen nemá automaticky přístup k žádnému projektu. V jeho řádku přidělte
projektové role a uložte oprávnění. Čtenář, recenzent, editor a správce projektu
zatím mají webové čtení přidělených projektů; webový editor není implementován.
Správce uzlu spravuje uživatele a vytváří projekty. Správce federace navíc
spravuje evidenci důvěry uzlů. Správci mají přístup ke všem síťově dostupným
projektům uzlu; ochrana local-only zůstává platná pro všechny.

Vypnutí Aktivní účet ihned odmítne další požadavek s jeho klíčem. **Nový klíč**
zneplatní předchozí klíč při publikaci změny. Ztracený nový klíč vygenerujte
znovu. Vlastní administrátorský účet nelze touto obrazovkou deaktivovat ani
zbavit jeho role. Bootstrap klíč tímto UI nelze odvolat; zůstává samostatnou
lokální recovery credential spravovanou deployem.

Peer vyžaduje UUID uzlu, HTTPS adresu a SHA-256 otisk veřejného klíče ověřený
nezávislou cestou. Nový peer čeká na explicitní schválení. Schválení pouze
eviduje lokální rozhodnutí: neprovádí handshake ani neověřuje dostupnost,
nepřenáší uživatele a neuděluje jeho uživatelům lokální přístup. Samostatný
katalogový přenos popsaný níže začne až nad schváleným peerem a policy
projektů. Síťová synchronizace projektového obsahu, automatické doručování
revokací a řešení divergence zůstávají otevřenou částí M5. Přihlášení
vzdáleným účtem se nezavádí.

Identita uživatele má vlastní stabilní UUID a home_node_id, oddělené od
lokální role, členství a credential. Uživatelské UUID se nesmí při budoucí
distribuci nahrazovat lokálním jménem ani UUID uzlu. Kvalifikovaná identita
je dvojice (node_id, user_id); stejné jméno ani UUID uživatele samo účet neslučuje.

## Desktop a lokální přihlášení

Desktop má jedinou identitu uživatele, pod kterým běží aplikace. Zachovává
persistentní author UUID z ProjectCreation a autentizovaný nativní process token;
nevytváří další uživatelské účty ani nepřijímá webové klíče. V jeho správě je
jeden účet bez tlačítek pro vytváření/rotaci účtů. Web může mít více vlastních
lokálních účtů. Mapování nikdy nerozšiřuje login: na každém webovém uzlu se
přihlašujte pouze jeho vlastní credential, na desktopu svou OS session.
Hesla, digesty hesel/klíčů, tokeny, session ani soukromé klíče se nepřenášejí.

## Oboustranné mapování bez přenosu credentials

Nový prázdný desktop vytvoří node.json při prvním otevření správy; první
projekt není podmínkou nastavení federace. Inicializace používá stejný uzlový
zámek a author journal jako ProjectCreation, publikuje kompletní soubor bez
přepsání a zachovává jeho UUID při opakování. Nedokončené vytvoření projektu
se neobchází novou konfigurací. Poškozený node.json nebo chybějící konfigurace
existujícího federačního registru se nenahrazuje novou identitou: zobrazí chybu
a vyžaduje obnovu původní konfigurace.

Hlášení správy zůstává viditelné při scrollování dialogu. Neplatné pole,
nevybraný projekt i chyba odpovědi API mají explicitní hlášení; neplatné pole
se označí a dostane fokus. Po chybě zápisu načtěte správu znovu před retry.

Ve Federaci je otisk vlastního Ed25519 klíče uzlu. Otisk znamená SHA-256
nad DER SubjectPublicKeyInfo, nikoli otisk TLS certifikátu. Před přidáním
peeru jej ověřte nezávislou cestou. Oba uzly musí evidovat a schválit druhý uzel.

Na prvním uzlu navrhněte mapování aktivního lokálního účtu na UUID vlastního
účtu druhého uzlu a vyberte společné projektové UUID. Potvrďte za tento uzel.
Výsledný podepsaný JSON předejte druhému správci; ten jej vloží do Ověřit
a přijmout. Druhý správce samostatně potvrdí totožné mapování a svůj podepsaný
JSON vrátí prvnímu uzlu k ověření. Teprve po přijetí obou podpisů je mapování
na daném uzlu aktivní. Potvrzení podepisuje správce pouze za vlastní uzel;
nejde o lokální checkbox, kterým by mohl potvrdit druhou stranu. JSON obsahuje
pouze UUID mapování, dvě kvalifikované identity, rozsah projektů, rozhodnutí,
veřejný klíč a podpis. Nepřenáší lokální administrátorské role ani credentials.
Rozsah nebo účty se nemění pod existujícím ID; vytvořte nový návrh.

Odvolání vytvoří podepsaný JSON, který předejte druhému uzlu stejně jako
potvrzení. Tombstone zůstává uložený i při doručení před starším potvrzením;
stará potvrzení jej neaktivují. Odvolání důvěry peeru trvale odvolá související
mapování, opětovné schválení peeru stará mapování neoživí. Bez automatického
transportu změna druhý uzel neinformuje sama; doručení je nyní ruční/offline.
Uložený podepsaný soubor lze znovu zobrazit po ztrátě odpovědi/restartu.

Osobní replikace používá pouze aktivní oboustranné mapování účtů. Správce
vybere schválený peer a projekt, nastaví privacy třídy bez `local-only`
a výslovně potvrdí, že tento uzel je primary a protější uzel read-only
replica pro `refs/heads/main`. Podepsaný grant se stejně jako mapování ručně
přenese a potvrdí na obou uzlech; pouhá dosažitelnost nebo důvěra peeru
synchronizaci nepovolí.

Po obou potvrzeních lze grant zapnout. Backend pak každých 60 sekund zkouší
omezený podepsaný HTTPS přenos; tlačítko Synchronizovat nyní provede stejný
pokus okamžitě. Stav rozlišuje čekání, offline uzel, odmítnutí, revokaci,
konflikt a poslední úspěšný HEAD. Zastavení nepřenáší další změny, revokace
grant trvale ukončí. Read-only replika skrývá editační akce a server každý
zápis přes Workspace znovu odmítá; zápisy se provádějí na primary.

## Katalog existence projektů

Stránka **Federace → Sdílení projektů** nejprve vymění jen UUID a název
projektu. `same-team` automaticky oznamuje všechny dostupné místní projekty,
`same-company` jen projekty zapnuté v matici. U `external` se stejný minimální
katalog odešle pouze tlačítkem **Odeslat existenci**. Katalog sám nemění
nastavení větví ani nepovoluje čtení obsahu.

Jeden podepsaný HTTPS požadavek vymění katalog oběma směry. Desktop periodicky
kontaktuje svůj server; serverový záznam dynamického klienta proto nemusí mít
vlastní adresu. P2P uzel se známou HTTPS adresou může synchronizaci zahájit
sám. Stav a tabulka **Projekty oznámené peery** jsou node-local informace.
Takový řádek nelze otevřít jako místní projekt a nevzniká mu Git repozitář,
členství ani oprávnění.

Katalog má limit 256 projektů na peer. Nedostupná místní registrace bez
ověřitelného committed názvu se neoznámí. Pending, revoked a migrační
`unspecified` peer nic nepřenese. Podpis připnuté node identity, oba Node UUID,
TLS CA a aktuální policy se ověřují při každé výměně; browserový přístupový
klíč se na node endpoint neposílá.

## Obousměrná synchronizace interního obsahu

`same-team` po katalogu automaticky synchronizuje všechny lokální projekty a
jejich `refs/heads/*`. `same-company` používá pouze projekty zapnuté v matici a
na každé straně aplikuje její lokální `selected-only` nebo
`all-except-hidden`. Výběr je exportní policy daného uzlu; protější uzel si
nemůže vzdálenou větev sám zpřístupnit. `external` tento protokol nikdy
nespouští.

Přenos používá nativní `git bundle`, zachovává původní commit ID a předává jen
validované větve. První přenos může zaregistrovat chybějící projekt. Existující
větev se pouze založí nebo fast-forwarduje. Když se obě strany změnily z téhož
základu, aktuální větev zůstane beze změny a protější head se uloží pod
`refs/federation/incoming/<peer>/<operation>/<branch>`. Stav **Divergence
zachována** proto není merge ani chyba vedoucí k přepsání; konflikt se musí
vyřešit vědomým lokálním Git/uživatelským workflow.

Desktop může použít tlačítko **Synchronizovat obsah** a stejný reconcile běží
po 60 sekundách automaticky. Jeden požadavek může nést bundle desktop → server
a odpověď bundle server → desktop, takže dynamická serverová strana nepotřebuje
adresu klienta. Nezměněný obsah si vymění jen podepsané inventury headů.

Každý dosažitelný commit se znovu validuje. Přenos podporuje `public`,
`project` a `confidential`; jakýkoli `local-only`, neklasifikovaný historický
soubor, symlink, submodule nebo neplatný metadata transition celý bundle
odmítne. Synchronizace projektu nevytváří lokální členství ani nepřenáší
credentials/session. Lokální zápis nadále vyžaduje místní RBAC.

## Práva spolu s daty

[ADR 0021](adr/0021-local-accounts-and-bilateral-mapping.md) definuje povinný
portable rights manifest: projektový a datový commit, UUID každé entity,
privacy a granty původních kvalifikovaných identit s explicitními akcemi.
Při přenosu zachovat tyto bajty/principaly a omezení; nepřepsat ACL cílovým
účtem. Chybějící nebo neznámá ACL se odmítá. Local-only se nepřenáší ani
s aktivním mapováním. Efektivní oprávnění je průnik přeneseného grantu,
rozsahu ověřeného mapování, místního členství/role a místní politiky; reader
nemůže získat write tím, že protější účet je editor. Členství a privacy se
kontrolují na obou stranách před přenosem i před zpřístupněním.

Obecný portable rights manifest a policy engine zůstávají otevřenou částí M5.
Implementovaná osobní replikace je užší: grant autorizuje celý validovaný Git
graf jednoho projektu a povolené privacy třídy mezi dvěma určenými uzly.
Není důkazem obecné federace jednotlivých artefaktů, sdílené identity ani SSO.

## Persistence a recovery

Vedle node.json vzniká privátní `.node.json.administration/`. `registry.git`
je samostatný autoritativní Git registr správy uzlu, nikoli projektový index.
Lokální credentials.sqlite ukládá pouze SHA-256 digesty náhodných klíčů a
opaque credential reference; neposílá se peerům. Ani celý registr nelze
automaticky exportovat: obsahuje lokální role a credential reference.
Záloha musí zachovat node.json, registr, credentials a původní bootstrap klíč;
přeinstalace kódu tyto soubory nemění.

Vedle něj může vzniknout `.node.json.network/federation-catalog.sqlite`.
Obsahuje odchozí revize, poslední přijatou projekci a provozní stav peerů.
Nejde o projektový index ani další autoritu projektů. Novější snapshot
atomicky nahradí starší, opožděná revize se ignoruje a stejná revize s jiným
obsahem se odmítne. Ztrátu odpovědi lze bezpečně napravit opakováním výměny.

Obousměrný obsah používá ve stejné privátní síťové složce
`federation-content-sync.sqlite`. Outbound řádek drží přesné podepsané bajty do
potvrzené odpovědi; inbound řádek váže operation ID na jediný request a stejnou
durable odpověď. Projektový Git zůstává autoritou dat. Změna aktuální větve je
navíc krytá projektovým journalem a po CAS se recovery dokončí roll-forward
checkoutem a obnovou indexu. Tento SQLite není projektový index ani policy
autorita a nemá se kopírovat mezi uzly.

Registr v2 přidal samostatnou tabulku mapování a v3 podepsané replikační granty
s lokálním desired state. V1 i v2 se pod stejným flock/CAS migrují do v3 bez
změny uživatelských UUID či credentials. Pád ponechá buď původní verzi, nebo
kompletní v3; další start migraci dokončí. `federation-key.pem` a
`federation-key.identity` zůstávají mimo Git v privátním adresáři správy.
Při prvním vytvoření se publikuje klíč a potom jeho public identity marker;
opakováním lze doplnit marker ke stejnému klíči. Ztráta klíče při existujícím
markeru se odmítne bez generování nové identity. Zálohujte oba soubory.

Zápis drží uzlový flock, validuje celý registr a očekávaný Git commit.
Registry se publikuje jednou atomickou CAS změnou Git ref, bez pracovní kopie
či obnovitelného SQLite indexu. Před publikací jsou objekty flushnuté, ref má
zapnuté Git fsync. Pád před změnou ref zachová předchozí stav; neodkazované
objekty nemají oprávnění. Pád po změně ref znamená novou autoritativní verzi.
Při ztracené odpovědi správu znovu načtěte před dalším zápisem; stale commit
se odmítá. Credentials se zapisují před registrem: osiřelá credential po pádu
nedává přístup, dokud na ni aktivní uživatel v registru neodkazuje. Starý klíč
při rotaci platí do změny ref, potom jen nový. Výměna/pin peer klíče vyžaduje
nové lidské rozhodnutí, žádný automatický trust-on-first-use.

Webové vytvoření projektu adaptuje ProjectCreation a recovery ADR 0015.
Formulář má operation_id a opakování na stejné stránce vrátí stejný receipt.
Restart serveru obnoví existující journal před otevřením listeneru; konflikt
cizích dat start odmítne a data zachová. Po reloadu stránky nebo restartu
nejprve zkontrolujte katalog, pokud se odpověď na vytvoření ztratila.

Reuse: adaptujeme Git CLI, node schéma, ProjectCreation, Projects a stávající
Host/Origin/Bearer kontrakt. Nevytváříme druhý backend ani alternativní projektový
index. Nový registr odděluje správu uzlu od projektových zápisů podle ADR 0003,
0015 a 0020. Rozsah je development implementace, nikoli production-ready federace.
