<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Náprava P1 z auditu souběhu, 11. 11. 2026

Rozsah tvoří A01–A06 z [auditu](concurrency-audit-2026-11-11.md),
výslovně zadaný uživatelem nad větví `feature/rss-direct-pilot`, výchozí
HEAD `6607602`. Jde o opravu zdrojů, nikoli změnu Workspace plánu,
akceptaci MON-08 nebo důkaz nasazení na Omnia.

## Změněné vlastnictví

| Nález | Implementovaná hranice |
| --- | --- |
| A01 | Explicitní routy provider execution, status a control mají oddělené HTTP/browser domény. Konfigurace zachovává vlastní nativní zámky a kontrolu binding/manifest revize. Autentizace a celé tělo požadavku předcházejí provider vlastnictví. |
| A02 | Monitoring execution má samostatnou omezenou doménu; view a control na ni nečekají. Nativní scheduler leases a pravidla publikace/cancel zůstávají autoritou. |
| A03 | Explicitně inventarizovaná projektová čtení nepoužívají HTTP writer mutex. Inicializovaný index se čte pod SH; případná obnova uvolní SH a získá EX s novou validací. Těžká validace neměnného Git snapshotu probíhá mimo zámek, závěr znovu kontroluje HEAD, větev i pending stav. |
| A04 | Jeden selector přijímá TLS handshake a celé hlavičky před přidělením aplikačního workeru. Neúplné hlavičky ani handshake nedrží aplikační kapacitu. Samostatná běžná kapacita chrání rezervovaný worker pro explicitní diagnostické/control routy a statické assets. |
| A05 | Julia získává sdílený filesystemový execution slot před založením workeru i před nativním dispatch. Limit platí napříč instancemi a procesy; start failure a dokončení uvolňují FD. |
| A06 | Reporting i Julia getters používají SQLite mode=ro, query_only a čtecí BEGIN. Reporting constructor validuje existující schéma čtením; pouze známá stará vlastněná schémata přecházejí do explicitní migrace. Čtení nezakládá chybějící Julia store. |

Přesný seznam rout je v `spikes/http_admission_policy.py`; žádná klasifikace
podle názvového suffixu. Zápisy nad stejnými nativními daty jsou stále
serializované. Protokol, RBAC, privacy, CAS a potvrzení účinků se nemění.

## Kapacita a recovery

Vstupní vrstva má nejvýše 64 čekajících socketů, každý nejvýše 64 KiB prefixu,
tedy nejvýše 4 MiB těchto bufferů. Idle hlavičky mají limit 1 s, handshake
2 s, absolutní původní rozpočet požadavku 60 s se po předání workeru
neobnovuje. Přetečení vrací 503, příliš velké hlavičky 431 před dispatch.
Počet aplikačních workerů se nezvyšuje. Předběžná klasifikace neposkytuje
autorizaci; tu stále ověřuje handler. OAuth callback a libovolné GET nejsou
statické assets a nemají rezervovaný slot.

Julia má výchozí execution kapacitu 1, nastavitelnou přes službu `max_workers`.
Je to explicitní konzervativní rozpočet souběžných procesů, nikoli zámek
čtenářů nebo tvrzení, že Julia principiálně vyžaduje jediné spuštění.
Slot ukládá před dispatch fsyncnutý operation-ID hint mimo projektový Git.
Hint pouze ukazuje do původního run journalu, který zůstává autoritou.
Odmítnutí kapacity nemění prepared intent a je `not-started`.
Po pádu vlastníka zmizí flock, ale dispatching/cancel_requested/unknown
záznam brání opětovnému použití kapacity pro nový účinek. Nezařazená aktivní
operace rovněž blokuje nové spuštění. Neprovádí se automatický replay.
Pokud nativní reconciliation neumí prokázat terminální výsledek a ponechá
unknown, slot zůstává blokován; tato změna nepřidává automatické potvrzení
ani administrátorské mazání neznámého účinku.

Projektový storage protokol podle [ADR 0003](adr/0003-coordinated-operation.md)
se nemění: před commitem rozhoduje journal, po commitu lze index obnovit
z Git. Pád při validaci snapshotu nemá projektový účinek. Při SH → EX
se zámek nepovyšuje na místě; po novém získání se opakují kontroly.
Bridge/queue pravidla [ADR 0060](adr/0060-local-file-ide-bridge.md) a
[0062](adr/0062-pinned-queue-handoff.md) zůstávají zachována.

Monitoring run zachovává synchronní HTTP kontrakt a samostatnou jedinou
execution doménu. Oprava nebuduje druhý persistentní job systém. Cancel je
dostupný, ale nativně stále nesmí vydávat issuing/unknown publikaci za
bezpečně zrušenou. Čtecí HTTP kapacita je nadále omezená pro zachování
ostatní obsluhy; úplné odstranění resource admission není cílem.

## Ověření a hranice důkazu

`tests.test_concurrency_p1` ověřuje souběžné HTTP execution/status/control,
neúplná těla a hlavičky, skutečný TLS handshake, meze bufferů a odmítnutí
před dispatch. Dále testuje skutečný monitoring scheduler, projektové čtení
s paralelním zápisem a odmítnutím změněného HEAD, SQLite getters při writer
reservation, Julia kapacitu napříč instancemi/procesy, start failure a
osiřelý/unknown dispatch. Nativní stream test ověřuje stop během změny
konfigurace; původní binding-race test dál odmítá dispatch se změněným binding.

Závěrečný společný běh 19 explicitně vybraných modulů: **405 testů, OK,
14 skipped**, 262,155 s. Zahrnuje `test_concurrency_p1`, `test_local_api`,
`test_http_ui_admission`, `test_project_http_ownership`, `test_journal`,
`test_workspace`, `test_projects`, `test_index_projection`,
`test_reporting_scheduler`, `test_julia_computation`, `test_task_stream`,
`test_monitoring`, `test_monitoring_ownership`, `test_monitoring_http`,
`test_web_server`, `test_chat_service`, `test_http_deadline`,
`test_backend_availability` a `test_federation_http_ownership`.
Jde o cílenou regresi, nikoli celou repozitářovou sadu. Automatické
lokální testy nejsou ruční akceptací běžného profilu, výpadkem napájení,
restartem používaného backendu ani ověřením vzdáleného nasazení. P2/P3 nálezy
z původního auditu tato změna neprohlašuje za dokončené.
