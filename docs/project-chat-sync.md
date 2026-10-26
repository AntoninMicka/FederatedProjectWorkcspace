<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Synchronizace projektových chatů

Projektové chaty se synchronizují automaticky spolu s obsahem projektu. Ve
Správě federace použijte u povoleného projektu stejnou akci **Push**, **Pull**
nebo **Sync** jako pro dokumenty a Git historii; samostatný přenos chatů se
nenastavuje.

Podmínkou je schválený interní peer a povolené sdílení projektu. U
klient–server vztahu se účet mapuje automaticky z vazby vytvořené přihlášením
desktopu k serveru; serverový účet musí být aktivní a mít přístup k projektu.
Ruční bilaterální mapování vlastníka je potřeba jen pro P2P vztah. Na druhém
uzlu se chat objeví v běžném seznamu přiřazených chatů. Enrollment vazba
určuje transportního příjemce, nikoli jediného čtenáře historie.

Postranní seznam zobrazuje zvlášť **Projektová vlákna** a **Nezařazená · pouze
tento uzel**. Shodu po synchronizaci lze očekávat pouze u přenositelných vláken
přiřazených danému projektu. Nezařazená vlákna nemají projektovou autoritu pro
sdílení a nesmí se svévolně připojit k právě otevřenému projektu.

Po dokončení ukazuje buňka projektu počet chatů sdílených a přijatých tímto
uzlem. Chybějící enrollment vazba nebo P2P mapování jsou hlášeny výslovně; Git
synchronizace sama není důkaz přenosu chatů. Otevřený panel Chaty se po místním
dokončení obnoví automaticky a kliknutí na záložku Chaty vždy načte současný
stav z uzlu, takže lze výsledek obnovit i na protistraně, která synchronizaci
nespustila.

Na webovém uzlu vidí všechny aktivní účty s přístupem k projektu stejnou
množinu jeho vláken bez ohledu na účet použitý při enrollmentu. `reader` má
read-only pohled, `editor` a `project-admin` mohou v projektových vláknech
pokračovat a měnit je. Nezařazená vlákna jsou nadále viditelná jen svému
místnímu vlastníkovi.

Při souběžném pokračování stejného vlákna se zachovají obě verze. Jedna zůstane
pod původním ID a druhá se objeví jako označený zapisovatelný fork. Další sync
stejnou dvojici sjednotí na obou uzlech bez přepsání odpovědí.

Vlákna obsahující `local-only` zprávu, rozpracovaný modelový turn a nezařazená
vlákna zůstávají na původním uzlu. Provider credentials, session, runtime
evidence a run journal se nepřenášejí. Podrobnosti a recovery hranice uvádí
[ADR 0056](adr/0056-project-chat-rw-sync.md).
