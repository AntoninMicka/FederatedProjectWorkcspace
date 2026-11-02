<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0065: Přímé textové konektory Claude, Gemini a Grok

- Stav: přijaté pro implementaci
- Datum: 2026-11-02
- Dávka: návrh `F-M3-PROVIDERS-02`; ve Workspace zatím není založená

## Kontext

Uživatel požaduje přímé konektory pro Claude, Google Gemini API a xAI Grok.
[ADR 0052](0052-atlascloud-text-backend.md) ponechal Anthropic Messages a Gemini
jako samostatné budoucí protokoly. OpenAI a AtlasCloud mají každý vlastní
binding, credential store, katalog a dispatch přes více než 650 řádků; třetí až
pátá kopie by znásobila místa, kde se může lišit obnova po pádu.

## Rozhodnutí

Společná vrstva `spikes/direct_provider.py` drží binding, credentials, journal,
katalog, dispatch a HTTP přenos. Poskytovatel dodá pouze `ProviderSpec` se svým
wire formátem v `claude_backend.py`, `gemini_backend.py` a `xai_backend.py`.
Výčet je v `direct_registry.py`. OpenAI a AtlasCloud se v tomto řezu nemigrují,
aby se neměnilo ověřené chování.

Pravidla konektoru:

- Klíč vkládá uživatel. Přihlášení jménem a heslem ani skriptování webové konzole
  se odmítají jako neoficiální cesta s přístupem k celému účtu.
- Host a endpoint jsou pevné a jediný povolený; přesměrování se odmítá. Secret je
  pouze v hlavičce, nikdy v URL. Tělo chybové odpovědi se nečte ani neukládá.
- Modely pocházejí z živého seznamu; žádný model není zadrátovaný. Běh je přišpendlen
  k přesné nabídce a neprovádí se žádný fallback na jiný model, včetně serverového.
- Odpověď musí být úplná: zkrácení, odmítnutí nebo neznámý důvod
  ukončení jsou selhání, nikoli úspěch.
- Provider SDK se nepoužívá. Projekt má jen dvě běhové závislosti a přesné řízení
  účinku jednoho běhu; opakování, které SDK standardně provádí, je tu zakázané.
- Context Manifest, privacy kontrola, náhled a potvrzení zůstávají sdílenou cestou
  externího dispatchu; `local-only` se odmítá před sestavením požadavku.

## Persistentní vrstvy a recovery

- `<adapter>-binding.json` je atomicky publikovaný node-local binding bez secretu.
  Pád před `replace` ponechá starý binding, po něm platí nový.
- `<adapter>-credentials.sqlite`: nový secret se uloží před bindingem. Výjimka při
  ukládání bindingu jej odstraní. Pád mezi oběma kroky zanechá nepoužitý secret pod
  nedosažitelnou referencí; je to stejná hranice jako v ADR 0052 a neovlivní běh.
  Starý secret se maže až po publikaci nového bindingu.
- `<adapter>-runs.sqlite` je autoritativní journal. `prepared` ještě neznamená
  odeslání. `dispatching` se před síťovým voláním trvale zapíše a po restartu se čte
  jako neznámý výsledek. Timeout, ztráta spojení a stream bez dokončení končí
  `unknown` bez opakování, `succeeded` se vrací idempotentně, `failed` vyžaduje nový
  běh. Takové chování je závazné i tam, kde provider doporučuje opakování.
- `model-discovery-*` drží poslední úplný snapshot. Selhání kterékoli stránky
  nepřepíše poslední validní data.
- `backend-reset-<adapter>.json` řídí odstranění: nejdřív binding, potom secret;
  nedokončený reset blokuje konfiguraci i dispatch, dokud se nezopakuje.
- Projektový Git se mění až samostatnou potvrzenou publikací výstupu.

## Reuse

Reuse: `BackendRuns`, `BackendRegistry`, `RunSelection`, provider-neutral katalog,
`BackendResetJournal`, externí náhled a schválení. Adapt: tvar bindingu a catalog
flow z AtlasCloud. Reject: provider SDK a OpenAI-kompatibilní vrstva pro Claude
a Gemini, protože by zakrývaly důvod ukončení jednotlivých providerů.

## Důsledky a limity

Stav je **implemented**. HTTP přenos je ověřen proti lokálnímu serveru a wire formáty
proti dokumentaci providerů k 2. 11. 2026. Volání reálných API ověřeno nebylo a
vyžaduje klíče. Známé limity:

- **Claude** nenárokuje `json-output`: API nabízí jen `json_schema` s
  `additionalProperties: false` a úlohy schéma nepředávají. Funguje chat, ne úlohy.
  Klíč musí být vázaný na workspace, hlavička `anthropic-workspace-id` se neposílá.
- **Gemini** používá `generateContent`, který dokumentace označuje za plně podporovaný
  bez data ukončení. `streaming` se hlásí jen, pokud jej seznam metod uvádí; jinak
  běží odpověď bez streamu. Modely bez textového výstupu se vylučují podle názvu.
- **Grok** vyžaduje `store: false` a přesnou shodu modelu v odpovědi. Pokud živé API
  vrací pro konkrétní ID jiné jméno, běh selže uzavřeně; je to první věc k ověření.
- Při selhání streamu mohl uživatel už vidět část textu; uložený výsledek ji neobsahuje.
- Binding nese capability uloženého modelu. Modelu vybranému pro jednotlivý běh se
  capability ověřují v `RunSelection` proti jeho nabídce.
