<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Správa uživatelů a evidence federace

Po běžném webovém deploy otevřete aplikaci stávajícím přístupovým klíčem.
Tento klíč zůstává lokálním bootstrap/recovery správcem federace; nesdílejte jej
s běžnými uživateli. Tlačítko **Uživatelé a federace** otevře správu.

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
nepřenáší projekty/uživatele a neuděluje jeho uživatelům lokální přístup.
Síťová synchronizace, podepsaná distribuce identit a revokací, řešení divergence
a přihlášení vzdálenou identitou zůstávají otevřenou částí M5.

Identita uživatele má vlastní stabilní UUID a home_node_id, oddělené od
lokální role, členství a credential. Uživatelské UUID se nesmí při budoucí
distribuci nahrazovat lokálním jménem ani UUID uzlu. Verze záznamu a Git historie
umožňují navázat distribuční protokol; neprokazují implementaci federovaného RBAC.

## Persistence a recovery

Vedle node.json vzniká privátní `.node.json.administration/`. `registry.git`
je samostatný autoritativní Git registr správy uzlu, nikoli projektový index.
Lokální credentials.sqlite ukládá pouze SHA-256 digesty náhodných klíčů a
opaque credential reference; neposílá se peerům. Ani celý registr nelze
automaticky exportovat: obsahuje lokální role a credential reference.
Záloha musí zachovat node.json, registr, credentials a původní bootstrap klíč;
přeinstalace kódu tyto soubory nemění.

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
