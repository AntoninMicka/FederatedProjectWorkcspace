<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-MEDIA-01: Externí obrazové capability

Milník M3; jedna dávka, větev `feature/f-m3-media-01`, budoucí PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; aktivována 2026-09-21 z `develop` po začlenění
  F-M3-CHAT-DIRECT-01 v PR #43 (`32cf743`) a jeho acceptance PR #44
  (`8171923`). Větev `feature/f-m3-media-01` vznikla z commitu `8171923`.
- Původ: roadmapa M3, ADR 0008 a backlogová položka `F-M3-MEDIA-01`.
- Výstup: provider-neutral explicitní obrazová capability s bezpečným preview,
  potvrzeným externím dispatch, bounded přijetím výsledných bajtů a samostatnou
  explicitní publikací obrázku jako projektového artefaktu s provenance.
- Hranice: obrazový request není textový chatový dispatch. První verze nebude
  stahovat libovolnou providerovou URL, odvozovat capability jen z názvu modelu
  ani dovolovat Ollamě síťovou akci automaticky vykonat. Usage/billing zůstává
  v M3-UB-01; webové hledání, obecný multimodální chat a creator/opponent
  workflow nejsou součástí dávky.
- Persistentní vrstvy a recovery: provider run a approval jsou node-local
  durable evidence mimo projektový Git; výsledné bajty se stanou autoritativním
  projektovým artefaktem až explicitní Workspace publikací. `dispatching` je
  durable před sítí, ztracený výsledek zůstává `unknown` bez automatického
  retry. Pád před publikací nesmí vytvořit artefakt, pád během publikace se
  obnovuje stávajícím Workspace journalem bez druhého providerového účinku.
- Reuse: adaptovat Context Manifest, provider-neutral capabilities, OpenAI
  credential/binding a run journal, external approval a source/artifact import.
  Soukromá inventura slouží jen ke srovnání konceptu; její kód ani soukromé
  názvy se nepřebírají. Nový framework ani obecný downloader se nezavádí.

## Aktivní části dávky

- [ ] [in progress] **F-M3-MEDIA-01-A — Kontrakt, provider/licenční review a
  reuse (designed).** Ověřit aktuální oficiální provider rozhraní a podporované
  modelové capability. Rozhodnout, zda první verze zahrne pouze `generate-image`,
  nebo také oddělené `image-to-text`; uzavřít přesné vstupy, MIME, rozměry,
  byte/event limity, request/response hash, provenance, privacy, preview,
  publikaci a crash boundaries. Zaznamenat reuse/adapt/reject a případnou změnu
  ADR bez kopírování neveřejné funkčnosti.
- [ ] [planned] **F-M3-MEDIA-01-B — Adapter, durable dispatch a bezpečné
  přijetí výsledku (implemented).** Implementovat pouze capability schválené v
  části A, přesný potvrzovaný request a bounded validaci výsledných bajtů.
  Providerová URL se v první verzi nepoužije, není-li v A navržena úzce omezená
  a doložená bezpečná varianta. Timeout, chyba, neplatná data a ztracená odpověď
  musí mít jednoznačný durable stav bez skrytého retry nebo fallbacku.
- [ ] [planned] **F-M3-MEDIA-01-C — UI a explicitní publikace artefaktu
  (implemented).** Přidat bezpečný preview vstupů i výsledku, privacy souhlas a
  oddělenou publikaci přes Workspace se zdrojovým hashem, provider/run identitou
  a provenance. Ollama může obrazovou akci jen navrhnout; uživatel ji musí
  samostatně potvrdit. Desktop a oprávněný web musí zachovat stejné serverové
  autorizační hranice.
- [ ] [planned] **F-M3-MEDIA-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Ověřit MIME/magic bytes, rozměry a limity, secrets,
  RBAC/privacy, přesný request, malformed/oversized výsledek, timeout,
  `unknown`, restart a vědomý nový run, idempotentní publikaci a provenance.
  Spustit úplnou sadu a relevantní skutečný UI/provider smoke; neprovedené živé
  ověření ponechat výslovně otevřené. Závěrečný úklid evidence provést v této
  feature větvi před jejím jediným PR.
