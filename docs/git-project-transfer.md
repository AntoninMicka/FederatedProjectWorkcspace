<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->
# První přenos projektu nativním Gitem

Nejprve aktualizujte aplikaci na LXC, aby obsahovala příjem Git transferu.
V desktopové liště otevřete **Přenést veřejný projekt…**, vyberte čistý projekt,
zapamatovaný schválený LXC uzel a jeho důvěryhodnou veřejnou CA. Výslovné
potvrzení autorizuje přenos celé historie včetně autorů/zpráv commitů.

## Rozsah první verze

Pouze jednosměrné založení nového projektu desktop→LXC. Stejné UUID i původní
Git commity zůstávají zachované. Existující projekt nebo kolize UUID/cesty se
nepřepisují. Není automatický merge, aktualizace existujícího projektu ani
kontinuální synchronizace. Nepřenášejí se hooky, Git config, jiné větve/tagy,
node identita, credentials, SQLite index nebo journal.

Historie musí být úplná, ne shallow; všechny dosažitelné commity mají validní
project.json se stejným UUID, pravidelné klasifikované soubory pouze pod
artifacts/registries, validní metadata/vztahy a pouze public entity. Jakýkoli
historický project/confidential/local-only obsah přenos zastaví. Změna privacy
jen v HEAD nestačí a funkce data automaticky nereklasifikuje. Historické ACL pro
neveřejná data zůstávají návrhovým problémem, ne implementovaným oprávněním.
Projektové názvy, autorství a commit messages musí uživatel posoudit před
potvrzením; program neprovádí klasifikaci tajemství v jejich volném textu.

Git CLI má hooksPath=/dev/null a vypnuté replace objects pro transfer příkazy.
Z čistého source HEAD vznikne izolovaný export jediné větve a Git bundle.
Před odesláním se validuje přesně jeho historie, ne jen HEAD. Limit je 500
commitů, 64 MiB bundle a existující limity snapshotů. Nativní fetch z bundle
na LXC používá incoming ref v nové izolované složce; opět se validuje celá
historie. Výsledek se registruje přes stávající ProjectCreation recovery.

TLS/podepsaný probe a oba schválené peery s původními piny chrání volbu uzlů.
SSH setup autorizuje správce přijímajícího uzlu; public přenos nepotřebuje
udělit cizímu účtu lokální login ani rozšířit projektové mapování. Pro budoucí
neveřejný přenos bude nutný validovaný historický ACL/scope protokol.

## Crash boundaries a omezení recovery

Source export drží stávající project writer lock; zdroj nemění. Na LXC je
intent a digest spolu se stagingem v soukromém `.git-transfers` vedle node.json,
nikoli v projektovém Gitu. Příjem je serializovaný lokálním transfer lockem.
Nový repo/ref/checkout se připraví před přesunem do projektové cesty; potom
registrace používá journal ADR 0015 a lokální index se obnoví z HEAD.

Pád před publikací repozitáře může zanechat neúplnou staged složku. Retry ji
nepřepisuje a zastaví se pro ruční recovery; automatické obnovení každého Git
checkout checkpointu ještě není implementované. Pád po přesunu repo dovolí
pokračovat stejnou registrací, pokud cíl zůstal nezměněný. Cizí úpravy nebo
jiný intent/digest se odmítají. Zdroj musí při retry zůstat stejný; opakovaný
export není garantován jako byte-identický bundle napříč verzemi Gitu, takže
ztracená odpověď může vyžadovat kontrolu cílového katalogu místo slepého retry.
Lokální durable journal celého přenosu zatím není implementovaný.

Uživatelský souhlas se změnou cíle není souhlas s přepisem cizích dat. Operace
se označuje jako implemented/unverified, nikoli PoC validated či production-ready.
Nové testy, GUI ověření ani skutečný přenos nebyly agentem spuštěny.
