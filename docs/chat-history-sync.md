<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Synchronizace historie chatů

V panelu **Chaty** zvolte **Synchronizovat**, cílový mapovaný účet a konkrétní
vlákna. Cíl se nabídne pouze tehdy, když je peer schválený, interní, má přímý
HTTPS endpoint a bilaterální mapování obsahuje běžícího uživatele tohoto uzlu.

Projektová vlákna musí být zahrnuta ve scope mapování. Nezařazená vlákna lze
poslat jen peeru `same-team`. Vlákno s `local-only` zprávou nebo právě běžícím
turnem se neodešle celé. Přenos nikdy neposílá API klíče, backendové session ani
lokální run journal.

Přijaté položky jsou ve větvi **Synchronizované historie**. Jsou pouze pro
čtení: nelze v nich pokračovat, spustit historický modelový běh, archivovat je
ani je vydávat za lokální vlákno. Více verzí stejného původního vlákna se
zobrazí jako odlišné zachované snapshoty.

Pokud se po odeslání ztratí odpověď, dialog ukáže operaci `unknown`. Volba
**Ověřit stejnou operaci** odešle beze změny dříve uložený podepsaný balík.
Nevytvoří balík z aktuálnější historie. `prepared` znamená, že síťový request
ještě nezačal; `rejected` je explicitní odmítnutí peerem; `succeeded` má
ověřenou podepsanou účtenku.

Návrh, hranice recovery a omezení popisuje
[ADR 0056](adr/0056-read-only-chat-history-sync.md).
