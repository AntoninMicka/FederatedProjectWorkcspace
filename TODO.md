<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M2-CHAT-LANGUAGE-01: explicitní jazyk odpovědi

Původ: roadmapa M2 a uživatelské zjištění, že Gemma někdy odpovídá slovensky
místo česky. Cílová úroveň: **designed → PoC validated**. Větev:
`feature/f-m2-chat-language-01`, základ/cíl PR: `develop`.

Výstupem je provider-neutral BCP 47 preference s precedence
`uzel → projekt → vlákno → běh`, viditelná v promptu a dohledatelná v Context
Manifestu, provider requestu a durable turn provenance. Rozsah nezahrnuje
automatický překlad, heuristickou opravu ani garanci, že model požadavek dodrží.

## Úkoly dávky

- [x] [completed] **F-M2-CHAT-LANGUAGE-01-A — Policy a recovery kontrakt
  (úroveň: designed).** ADR 0036 definuje precedence, BCP 47 materializaci,
  persistentní hranice, `unverified` compliance a zákaz skrytého překladu.
- [x] [completed] **F-M2-CHAT-LANGUAGE-01-B — Context, provider request a
  provenance (úroveň: implemented).** Atomická node/project policy, preference
  vlákna a jazyk turnu jsou restartově trvalé; payload, Context Manifest a
  Ollama/OpenAI provider request vážou konkrétní tag a zdroj. Chat schema v5 se
  migruje z podporovaných verzí a retry kontroluje shodu jazyka.
- [x] [completed] **F-M2-CHAT-LANGUAGE-01-C — Sdílené webové UI (úroveň:
  implemented).** Prompt nabízí děděnou nebo explicitní BCP 47 volbu pro běh,
  nastavení umí uložit uzel/projekt/vlákno a odpověď ukazuje požadovaný jazyk i
  pravdivý stav „shoda neověřena“.
- [ ] [in progress] **F-M2-CHAT-LANGUAGE-01-D — Ověření a fyzická akceptace
  (cílová úroveň: PoC validated).** Cílené testy policy, migrace, manifestu,
  adapterů, služby, snapshotu, restartu a lokálního API jsou úspěšné včetně
  loopback běhu mimo sandbox; JavaScript prošel `node --check`. První úplný běh
  odhalil strict snapshot schema, po opravě na v2 prošla celá sada: 693 testů,
  28 přeskočených. Zbývá na reálné Gemmě ověřit `cs-CZ`, pokračování vlákna,
  jednorázový jiný jazyk a restart bez skrytého překladu.

## Akceptační podmínky

- precedence uzel/projekt/vlákno/běh je deterministická a restartově trvalá;
- skutečný běh nese konkrétní normalizovaný BCP 47 tag v manifestu, provider
  requestu a turn provenance;
- UI neprezentuje jazyk jako garantovaný a providerovu odchylku nemění;
- cílené i úplné automatické testy projdou a fyzický Gemma scénář potvrdí
  uživatel.
