# Bezpečnost — počáteční threat model

| Vstup / hranice | Riziko | Požadovaná kontrola | Stav |
| --- | --- | --- | --- |
| Webová stránka → desktop API | Neoprávněné Git/LLM operace | IPC nebo loopback HTTP s tokenem, Host/Origin validací, CSRF ochranou | návrh |
| Soubor → storage | Path traversal, symlink, škodlivý parser vstup | Omezené kořenové cesty, validace, limity velikosti a schémat | návrh |
| Peer → projekt | Neoprávněný přenos a škodlivá konfigurace Gitu | Node autentizace, aktuální RBAC, izolovaný import, zákaz cizích hooků a helperů | návrh |
| Zdroj → LLM | Prompt injection a únik kontextu | Zdroj jako data, aplikační privacy filtr, náhled kontextu | návrh |
| Desktop disk → jiný uživatel | Únik credentials | Systémové úložiště klíčů, restriktivní práva, token mimo logy/URL | návrh |
| Restart → stav projektu | Ztracený zápis / zastaralý index | Journal operací, validace a obnova podle commit ID | částečný PoC |

Lokální HTTP není implementováno. Token by byl náhodný pro každé spuštění, předaný chráněným kanálem; CORS nenahrazuje autentizaci. Síťový federační endpoint vyžaduje samostatnou autentizaci a TLS.

Testovací Git wrapper používá seznam argumentů bez shellu, vypíná globální/system konfiguraci, hooky a interaktivní prompt v řízeném experimentu. To není kompletní sandbox pro nedůvěryhodné repozitáře; produkční vrstva musí také řídit lokální konfiguraci, Git attributes/filtry, transporty, velikost vstupů a souběh operací.

Revokace brání budoucímu autorizovanému přenosu; nemůže vzít zpět již stažená offline data. Backup musí zahrnout autoritativní lokální stav, nejen obnovitelný index.
