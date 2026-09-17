<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Bezpečnost — počáteční threat model

| Vstup / hranice | Riziko | Požadovaná kontrola | Stav |
| --- | --- | --- | --- |
| Webová stránka → desktop API | Neoprávněné Git/LLM operace | IPC nebo loopback HTTP s tokenem, Host/Origin validací, CSRF ochranou | protokolový PoC, ADR 0006; statický Qt/WebEngine PoC ADR 0007; integrace artefaktů zbývá |
| Soubor → storage | Path traversal, symlink, škodlivý parser vstup | Omezené kořenové cesty, validace, limity velikosti a schémat | PoC; bez ochrany proti závodícím FS změnám |
| Peer → projekt | Neoprávněný přenos a škodlivá konfigurace Gitu | Node autentizace, aktuální RBAC, izolovaný import, zákaz cizích hooků a helperů | návrh |
| Zdroj → LLM | Prompt injection a únik kontextu | Zdroj jako data, aplikační privacy filtr, náhled kontextu | návrh |
| Desktop disk → jiný uživatel | Únik credentials | Systémové úložiště klíčů, restriktivní práva, token mimo logy/URL | návrh |
| Restart → stav projektu | Ztracený zápis / zastaralý index | Journal operací, validace a obnova podle commit ID | Linux PoC přes Workspace, ADR 0003; produkční ochrany otevřené |

Lokální HTTP a Unix socket jsou ověřeny izolovaným experimentem [ADR 0006](docs/adr/0006-local-api-transport.md). Token se mění při každém startu; desktopové PoC předává token přímo nativnímu request interceptoru v témže procesu, bez zveřejnění v UI; skutečný WebEngine ověřuje [ADR 0007](docs/adr/0007-desktop-poc.md). Bezpečné zobrazení nedůvěryhodných artefaktů a produkční integrace zůstávají otevřené. CORS nenahrazuje autentizaci. Síťový federační endpoint vyžaduje samostatnou autentizaci a TLS.

Testovací Git wrapper používá seznam argumentů bez shellu, vypíná globální/system konfiguraci, hooky a interaktivní prompt v řízeném experimentu. To není kompletní sandbox pro nedůvěryhodné repozitáře; produkční vrstva musí také řídit lokální konfiguraci, Git attributes/filtry, transporty, velikost vstupů a souběh operací.

Revokace brání budoucímu autorizovanému přenosu; nemůže vzít zpět již stažená offline data. Backup musí zahrnout autoritativní lokální stav, nejen obnovitelný index.

Souborový journal a jeho limity jsou popsány v [ADR 0002](docs/adr/0002-metadata-journal.md). Journal vyžaduje soukromý adresář mimo projekt; obsahuje i celé bajty rozpracovaných souborů a nesmí se synchronizovat.

[Workspace PoC](docs/adr/0003-coordinated-operation.md) sdílí zámek se souborovým journalem a při pending operaci odmítá čtení. Samostatný Index ani Git wrapper tuto aplikační ochranu nevynucují. Všichni kooperující účastníci musí používat stejný Workspace a stavový adresář; koordinace není RBAC engine ani ochrana před nekooperačním filesystemovým závodem.

## Kontext a hranice důvěry M0-08

[ADR 0008](docs/adr/0008-context-and-publication-contracts.md) váže autorizaci na přesné bajty a cíl před odesláním, chrání manifest stejně jako vstupy a zakazuje implicitní fallback i přenos local-only odvozenin. Zohledňuje také zakázaný obsah v Git historii. Jde o designed kontrakt; metadata validátor ani transportní PoC tyto kontroly nevynucují.

## Externí vztahy a řízené sdílení — plánované požadavky

Níže je návrh pro plánované moduly, nikoli implementované ochrany. Nezavádí nový runtime ani nemění stávající privacy třídy; implementaci a testy drží BACKLOG ER-01 až ER-08.

| Vstup / hranice | Riziko | Požadovaná kontrola | Stav |
| --- | --- | --- | --- |
| Partner → projekt | Záměna osoby, organizace, účtu a oprávnění | Stabilní identity, časové vztahy, explicitní příjemci; kontakt neuděluje RBAC | návrh |
| Presenter → publikum | Únik poznámek, rozhodovacího scénáře, očekávaných odpovědí, skrytých backupů nebo zdrojového modelu | Publikum dostává pouze explicitně schválený payload, ne celý deck/scénář skrytý pomocí CSS; focus, navigace, preview a nácvik používají samostatné řízení výstupu a nevytvářejí disclosure | návrh |
| Komunikace → externí příjemce | Chybná adresa, reply-all, citace nebo příloha | Náhled skutečných příjemců a bajtů, kontrola policy těsně před přenosem; adresářové návrhy nejsou souhlas | návrh |
| Mail/pozvánka → UI a LLM | Aktivní HTML, tracking, příloha nebo prompt injection | Sanitizace a izolace, vzdálené zdroje standardně vypnuté, omezení příloh; obsah je data, nikoli instrukce | návrh |
| Restart → SMTP/audience | Duplicitní odeslání nebo falešný auditní úspěch | Durable operation record, ID události, explicitní unknown, žádný automatický resend při neurčitém výsledku | návrh |
| Git/federace → další uzel | Únik přes historii, kontakt nebo metadata sdílení | Autorizovat celou přenášenou množinu včetně historie; selektivní projekce a oddělené trust boundaries | návrh |

### Policy není semafor

- Green/orange/red jsou varování pro řečníka; nezastupují public/project/confidential/local-only, přístupová práva ani účelové omezení.
- Před promítnutím, odesláním, exportem pro partnera i sdílením pozvánky je nutné ověřit actor, příjemce, přesnou revizi, scope a povolenou hranici. `local-only` nesmí být zobrazeno externímu publiku nebo předáno dál bez explicitní oprávněné reklasifikace.
- „Přesto zobrazit“ smí obejít jen měkké upozornění na expozici, nikdy autorizační zákaz. U povoleného red obsahu je nutné explicitní potvrzení; zkontrolovaný zelený hlavní deck neobchází tutéž kontrolu.
- Dřívější sdílení, kladná reciprocita ani označení NDA nejsou samostatná autorizace. Podmínky přijatých informací se zachovávají; LLM je nesmí samo uvolnit nebo reklasifikovat.

### Bezpečný výstup a komunikace

- Publikum ani export nedostanou skryté poznámky, nepoužité backupy, nedovolené zdroje či embedded metadata. Změna payloadu po potvrzení vyžaduje nové posouzení. Při přerušení spojení musí být dostupné zatemnění nebo neutrální slide; odpojené zobrazení nesmí potvrdit novou expozici.
- Před přenosem se kontrolují To/Cc/Bcc, citovaná korespondence, sdílené adresy a rozšiřování příjemců. Bcc a soukromá historie nesmějí uniknout do veřejného decku, pozvánky ani sdíleného projektového logu.
- IMAP/SMTP/CalDAV/CardDAV vyžadují ověřené TLS a vhodnou autentizaci. Hesla a OAuth tokeny patří do lokálního secret store mimo Git, adresář partnerů, URL a logy; jejich obnova a revokace nesmí tiše přejít na slabší režim.
- Příchozí obsah nesmí automaticky odesílat odpovědi, potvrzovat pozvánky, párovat identity, importovat soukromé zprávy do sdíleného projektu nebo měnit policy. Vzdálené obrázky a link previews se bez povolení nenačítají.

### Audit, retence a federace

- Disclosure ledger eviduje pozorovanou akci a kvalitu důkazu, ne garantované znalosti protistrany. Samotný export není doručení a přijetí SMTP serverem není přečtení.
- Append-only v aplikačním API nezaručuje nezměnitelnost Gitu. Návrh musí určit detekci změn nebo podpisy, správu klíčů, zálohy a kontrolované opravy; bez jejich ověření nelze používat označení forenzně nezměnitelný audit.
- Samotná metadata „komu, co a kdy“ mohou být citlivá. Je nutné je minimalizovat, řídit jejich retenci a případnou autorizovanou redakci odděleně od běžných uživatelských oprav; nevynucovat neomezené uchovávání osobních údajů.
- `.gitignore`, barevný štítek ani aplikační filtr neodstraní obsah ze starší Git historie. Celý citlivý projekt se nesmí přenést uzlu oprávněnému pouze k prezentaci; použije se oddělený autorizovaný export nebo projekce. Revokace neodstraní již předané offline kopie.
- Osobní katalog a mail se nesynchronizují automaticky na všechny uzly. Oprávnění, detekci konfliktů a neúplnou historii je nutné řešit i při offline návratu. Stejné event ID s jiným obsahem je konflikt, ne „poslední vyhrává“.
- LLM poradce používá jen autorizovaný kontext a explicitní Context Manifest. Nesmí skrytě odeslat komunikaci externímu modelu, vypnout varování podle domnělé reciprocity ani nahradit deterministickou autorizaci.
