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
