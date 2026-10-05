<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M3-MEDIA-01: Externí obrazové capability

Milník M3; jedna dávka, větev `feature/f-m3-media-01`, budoucí PR do `develop`.
[Roadmapa](<Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>) · [Backlog](BACKLOG.md) · [Historie](WORK_LOG.md) · [Pravidla](AGENTS.md)

## Rozsah a hranice

- Stav dávky: [ ] [in progress]; původně aktivována 2026-09-21 z commitu
  `8171923` po PR #43/#44. Po začlenění MOD-01-UI v PR #45 byla existující
  nepushnutá větev 2026-10-05 rebasována na aktuální `develop` `d4a83d2`;
  aktivační commit zůstává prvním feature commitem jako `51dbb44`.
- Původ: roadmapa M3, ADR 0008 a backlogová položka `F-M3-MEDIA-01`.
- Výstup: provider-neutral explicitní obrazová capability s OpenAI Images a
  ComfyUI jako oddělenými adaptery, bezpečným preview, potvrzeným dispatch,
  bounded přijetím výsledných bajtů a samostatnou explicitní publikací obrázku
  jako projektového artefaktu s provenance.
- Hranice: obrazový request není textový chatový dispatch. První verze nebude
  stahovat libovolnou providerovou URL, odvozovat capability jen z názvu modelu
  ani dovolovat Ollamě síťovou akci automaticky vykonat. Usage/billing zůstává
  v M3-UB-01; webové hledání, obecný multimodální chat a creator/opponent
  workflow nejsou součástí dávky.
- ComfyUI hranice: používat pouze explicitně nakonfigurovaný `same-node` nebo
  schválený privátní endpoint. Workspace smí odeslat jen verzovanou allowlisted
  workflow šablonu a validované parametry; LLM nesmí dodat ani spustit libovolný
  workflow či custom node. Výsledek se váže na konkrétní `prompt_id`, historii,
  výstupní identitu a endpoint. Nejde o fallback za OpenAI ani naopak.
- Persistentní vrstvy a recovery: provider run a approval jsou node-local
  durable evidence mimo projektový Git; výsledné bajty se stanou autoritativním
  projektovým artefaktem až explicitní Workspace publikací. `dispatching` je
  durable před sítí, ztracený výsledek zůstává `unknown` bez automatického
  retry. Pád před publikací nesmí vytvořit artefakt, pád během publikace se
  obnovuje stávajícím Workspace journalem bez druhého providerového účinku.
- Reuse: adaptovat Context Manifest, provider-neutral capabilities, OpenAI
  credential/binding a run journal, external approval a source/artifact import;
  pro ComfyUI použít pouze dokumentovaný serverový protokol nad vlastní novou
  integrační vrstvou.
  Soukromá inventura slouží jen ke srovnání konceptu; její kód ani soukromé
  názvy se nepřebírají. Nový framework ani obecný downloader se nezavádí.

## Aktivní části dávky

- [x] [completed] **F-M3-MEDIA-01-A — Kontrakt, provider/licenční review a
  reuse (designed).** ADR 0008 uzavírá v1 pouze jako `generate-image` s jedním
  PNG výsledkem; `image-to-text`, editace/maska a multimodální chat jsou
  odložené capability. OpenAI Images přijímá jen inline base64, ComfyUI používá
  verzovanou allowlisted workflow šablonu a bounded `/prompt` → `/history` →
  `/view` tok bez LLM workflow/custom nodes a bez fallbacku. Jsou fixované
  prompt/response limity, tři rozměry, PNG/IHDR/chunk validace, přesný request,
  privacy, provenance, samostatný BLOB run journal a Workspace crash boundaries.
  Reuse adaptuje interní kontrakty a oficiální protokoly; cizí kód se nekopíruje.
- [x] [completed] **F-M3-MEDIA-01-B — Adapter, durable dispatch a bezpečné
  přijetí výsledku (implemented).** Implementovat pouze capability schválené v
  části A, samostatné OpenAI/ComfyUI bindingy, přesný potvrzovaný request a
  bounded validaci výsledných bajtů.
  Providerová URL se v první verzi nepoužije, není-li v A navržena úzce omezená
  a doložená bezpečná varianta. Timeout, chyba, neplatná data a ztracená odpověď
  musí mít jednoznačný durable stav bez skrytého retry nebo fallbacku. Hotovo:
  samostatný media registr, OpenAI Images a ComfyUI binding/adapter, allowlisted
  workflow substituce, přesná execution/request identita, mode-0600 SQLite BLOB
  journal a striktní PNG/CRC/IHDR/rozměrová validace. OpenAI nepřijímá URL ani
  seed, ComfyUI vyžaduje seed a kvalitu ponechává workflow; známá neplatná data
  končí `failed`, nejistota po dispatchi `unknown` bez retry. Ověření 2026-09-21:
  cíleně 8 testů OK; úplná sada 362 testů OK, 22 podmíněných smoke testů přeskočeno
  (první sandboxový běh měl 27 očekávaných socket permission chyb, opakování s
  povolenými lokálními sockety prošlo).
- [x] [completed] **F-M3-MEDIA-01-C — UI a explicitní publikace artefaktu
  (implemented).** Přidat bezpečný preview vstupů i výsledku, privacy souhlas a
  oddělenou publikaci přes Workspace se zdrojovým hashem, provider/run identitou
  a provenance. Ollama může obrazovou akci jen navrhnout; uživatel ji musí
  samostatně potvrdit. Desktop a oprávněný web musí zachovat stejné serverové
  autorizační hranice. Průběžně 2026-09-21: desktop i web sdílejí node-local
  nastavení ComfyUI; administrace ukládá atomicky mode-0600 pouze validovaný
  verzovaný API workflow, jeho hash, mapu allowlisted parametrů a explicitní
  output node. Dokončeno 2026-10-05: desktop i web mají oddělený
  preview → potvrzený dispatch → validovaný PNG preview → potvrzenou Workspace
  publikaci. Approval, Context Manifest a run přežijí restart; publikace používá
  původní durable BLOB bez druhého providerového účinku a zapisuje striktní
  metadata schema v3 s binding/run/workflow/output provenance bez promptu.
  OpenAI Images má samostatný explicitní binding nad již uloženým credentialem;
  status ani UI secret nevrací a `local-only` odmítne mimo same-node ComfyUI.
  Web vyžaduje editor/project-admin nebo node admin a konfiguraci smí měnit jen
  node admin. Ověření: 29 cílených media/desktop/web testů OK, 3 podmíněné
  Qt/WebEngine smoke přeskočeny; úplná sada 383 testů OK, 22 přeskočeno.
  JavaScript prošel `node --check`, `git diff --check` je čistý. Skutečný
  Qt/WebEngine a živý OpenAI/ComfyUI smoke zůstávají otevřené v části D; obecný
  kompoziční router z roadmapy 2E.1 zůstává mimo rozsah této dávky.
- [ ] [planned] **F-M3-MEDIA-01-D — Regrese, dokumentace a akceptace
  (PoC validated).** Ověřit MIME/magic bytes, rozměry a limity, secrets,
  RBAC/privacy, přesný request, malformed/oversized výsledek, timeout,
  `unknown`, restart a vědomý nový run, idempotentní publikaci a provenance.
  Spustit úplnou sadu a relevantní skutečný UI/provider smoke; neprovedené živé
  ověření ponechat výslovně otevřené. Závěrečný úklid evidence provést v této
  feature větvi před jejím jediným PR.

## K předání do backlogu

- [ ] [planned] **F-M4-OUTPUT-ROUTER-01 — Deklarativní katalog výstupních
  capability a kompoziční router (cílová úroveň: designed → PoC validated).**
  Uživatelský požadavek z 2026-10-05 je zanesen v roadmapě 2E.1. První dávka má
  dodat verzovaný statický descriptor pro renderery i nástroje, fail-closed
  katalog a read-only návrh typovaného plan/step DAG bez spuštění. Navazující
  execution musí skládat explicitní artefakty a materializované mezivýstupy,
  například účetní data → schválený Julia skript → tabulka/graf → prezentace,
  se samostatnými Context Manifest/run contracty, privacy, receipts, preview a
  potvrzeními. Ollama smí plán navrhnout, nikoli sama spouštět pluginy, měnit
  modely/bindingy nebo oslabit oprávnění. Položka není součástí akceptace
  F-M3-MEDIA-01; tato dávka zachová pouze kompatibilní capability metadata.
- [ ] [planned] **F-M5-CHAT-XMPP-01 — Oddělený interní a veřejný XMPP adaptér
  (cílová úroveň: designed → PoC validated).** Doplnění uživatelského požadavku
  z 2026-10-05 k existujícím F-M5-TRUST-01, F-M5-CHAT-01/02 a ER-00 až ER-03 je
  zanesené v roadmapě 22D. Interní XMPP smí obsloužit pouze konkrétní bilaterální
  vztahy `same-company-same-team` a `same-company`; nejde o změnu profilů na
  obecný pořadový žebříček. Veřejný federovaný XMPP je oddělený vnější kanál s
  vlastní doménou, účty, credentials, úložištěm, moderací a disclosure policy.
  Mezi hranicemi není implicitní bridge a vnější zprávy nesmějí automaticky
  získat projektový kontext ani spustit LLM, plugin nebo nástroj. Před PoC
  uzavřít identity/JID mapping, durable delivery a `unknown`, MUC, přílohy,
  DNS/TLS, server-to-server interoperabilitu, end-to-end šifrování, retenci,
  anti-spam a explicitní import/přeposlání s provenance a privacy. Položka není
  součástí akceptace F-M3-MEDIA-01.
