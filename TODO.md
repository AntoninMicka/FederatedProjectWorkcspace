<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-EXTERNAL-01: První externí provider a řízené volání

Milník M3; jedna dávka, jedna feature větev, jeden PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## F-M3-EXTERNAL-01 — První externí provider, context preview a privacy filtr

- Stav: [ ] [in progress]; aktivováno po začlenění PR #35 dne 2026-09-19.
- Původ: roadmapa M3 a backlog `F-M3-EXTERNAL-01`; uživatelský požadavek znovu využít textové a případně obrazové providery z AI Production Studia a navrhnout řízené návrhy volání přes Ollamu.
- Skutečná větev: `feature/f-m3-external-01-first-provider`, založená z `develop` (`eb828fe`); jediný budoucí PR do `develop`.
- Výstup: jeden explicitně zvolený externí textový provider přes společný backend kontrakt, credential reference mimo Git, přesný context preview a lidsky potvrzený dispatch; Ollama může pouze navrhnout strukturovanou akci, nikoli sama provést síťové volání.
- Mimo rozsah: usage/billing (`M3-UB-01`), automatický routing nebo fallback, obecný agent/tool runtime, synchronizace credentialů, multi-role workflow a produkční obrazový pipeline. Obrazové capability se v této dávce pouze vyhodnotí a případná implementace přejde do `F-M3-MEDIA-01`.
- Recovery: schválení váže přesný manifest, payload, provider/binding/model a credential reference; durable `dispatching` vznikne před sítí, ztracená odpověď je `unknown` bez automatického retry. Credential hodnota se neukládá do manifestu, run evidence, logu ani Gitu.
- Akceptace: `local-only` je odmítnuto před preview/dispatch; project/confidential vyžadují explicitní policy a lidské potvrzení přesných bajtů a cíle; stale HEAD, změna targetu/modelu/credential reference/policy nebo návrhu Ollamy zneplatní schválení; provider nemůže doplnit skrytý kontext; timeout/lost response se neopakuje a lokální Ollama dál funguje bez externí konfigurace.

- [x] [completed] **F-M3-EXTERNAL-01-A — Reuse, provider a tool-call kontrakt (cílová úroveň: designed).** Soukromé textové/obrazové adaptéry byly posouzeny pouze jako zdroj konceptů; bez doložené licence se kód nepřebírá a automatický provider pool, dynamický odhad capability, polykání chyb ani obecné URL downloady se nereusují. [ADR 0008](docs/adr/0008-context-and-publication-contracts.md#první-externí-provider-a-řízený-návrh-volání) volí první textový `openai-responses` adapter, opaque node-local credential reference, přesný request/response a durable recovery kontrakt. `ExternalCallProposal` z Ollamy je pouze striktní nedůvěryhodný návrh; aplikace znovu autorizuje, vytvoří manifest/preview a vyžádá samostatné lidské potvrzení. Obrázky přecházejí do `F-M3-MEDIA-01`, usage/billing zůstává `M3-UB-01`. Ověření: oficiální Responses/Images API dokumentace, kontrola reuse hranice a dokumentační diff dne 2026-09-19; živé API dosud nevoláno.
- [ ] [in progress] **F-M3-EXTERNAL-01-B — Credential reference a externí textový adapter (cílová úroveň: implemented).** Přidat node-local credential lifecycle bez vracení secretu do DOM a první adapter pro text/JSON. Zachovat přesný target, limity, timeout, response validaci a společný run store bez implicitního fallbacku.
- [ ] [planned] **F-M3-EXTERNAL-01-C — Context preview, privacy policy a potvrzený dispatch (cílová úroveň: PoC validated).** Zobrazit přesné odesílané vstupy, privacy, provider/model a odhadovaný rozsah bez credentials; po potvrzení znovu ověřit HEAD, autoritu, policy, binding a payload a pokrýt restart/stale/unknown/odmítnutí.
- [ ] [planned] **F-M3-EXTERNAL-01-D — Ollama návrh externího volání a integrační akceptace (cílová úroveň: PoC validated).** Lokální Ollama smí navrhnout pouze validovanou `ExternalCallProposal` s účelem, rolí, požadovanou capability a explicitním výběrem zdrojů. Aplikace sestaví nový Context Manifest a vyžádá lidské potvrzení; návrh se nikdy nespouští automaticky. Ověřit prompt injection, neznámou akci/provider, změnu návrhu, zamítnutí, nedostupnou Ollamu i providera a plnou sadu.
