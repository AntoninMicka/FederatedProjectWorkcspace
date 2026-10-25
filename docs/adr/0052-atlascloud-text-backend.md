<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0052: AtlasCloud textový backend přes přesnou modelovou nabídku

- Stav: přijaté pro implementaci
- Datum: 2026-10-25
- Dávka: `F-M3-ATLASCLOUD-01`

## Kontext

AtlasCloud nabízí více wire protokolů na společném hostu, ale ne každý model
podporuje každý z nich. Oficiální dokumentace
[LLM protokolů](https://www.atlascloud.ai/docs/llm-protocols) uvádí OpenAI Chat
Completions, Responses, Anthropic Messages a Gemini a požaduje kontrolu
`supported_apis` konkrétního modelu. Workspace proto nesmí považovat AtlasCloud za jeden
univerzálně OpenAI-kompatibilní endpoint ani odvozovat protokol z názvu modelu.

Společný katalog `F-M3-MODEL-CATALOG-01` již odděluje providerovou nabídku,
protokol, capabilities a binding. AtlasCloud adapter tento kontrakt použije;
nebude zavádět vlastní router, fallback ani druhý znalostní katalog.

## Rozhodnutí

První řez podporuje pouze wire protokol `openai-responses-v1` na pevném
endpointu `https://api.atlascloud.ai/v1/responses`. Adapter má ID
`atlascloud-responses`, boundary `external-provider` a target
`api.atlascloud.ai`. Chat Completions, Anthropic Messages, Gemini, media, MCP,
CLI a billing API jsou samostatné budoucí adaptéry nebo feature dávky.

Binding nese přesný `offer_id`, providerový model, protokol, revizi reviewované
znalosti, credential revizi, capability snapshot a limity. Uložení bindingu
vyžaduje, aby společný reviewovaný katalog obsahoval stejnou AtlasCloud
nabídku a protokol. `generate-text` a `text-output` musí být pravdivě
podporované; JSON a streaming lze zapnout pouze pokud je katalog rovněž
potvrzuje. Neznámá nebo konfliktní capability je nepodporovaná.

Veřejná dokumentace v době implementace nedokládá stabilní autentizovaný
model-discovery endpoint se striktním response schématem. První řez proto
neprovádí síťové discovery: nabídka vzniká explicitním review/importem ve
společném katalogu. UI to označí jako reviewovanou znalost, nikoli živou
dostupnost. Až doložené discovery bude samostatné rozšíření.

## Request, response a chyby

Request používá celý autorizovaný Context Manifest payload jako jeden textový
vstup, `store: false`, `truncation: disabled`, přesný model a limit výstupu.
JSON přidá pouze `text.format = json_object`. Stream je povolen jen při
binding capability `streaming` a musí skončit přesným `response.completed`;
keep-alive SSE komentáře se ignorují. Finální odpověď musí obsahovat přesně
jednu textovou message a model musí odpovídat bindingu. Usage se uloží pouze
pro validní nezáporné počty tokenů.

Redirect je zakázán. HTTP odmítnutí včetně 429 je známé selhání bez skrytého
retry. Timeout, přerušený transport nebo stream bez finální odpovědi přejde do
durable `unknown`; stejný run se automaticky neodešle znovu. Tím se projektové
pravidlo liší od obecného providerového doporučení exponenciálního retry.

## Persistentní vrstvy a recovery

- `atlascloud-binding.json` je atomicky publikovaný node-local binding bez
  secretu; pád před `replace` ponechá starý binding, po `replace` je nový
  binding autoritativní.
- `atlascloud-credentials.sqlite` je write-only credential store. Nový secret
  se uloží před bindingem; selhání bindingu nový credential odstraní. Starý
  credential se odstraní až po úspěšném zveřejnění nového bindingu.
- `atlascloud-runs.sqlite` je autoritativní journal providerových účinků.
  `prepared` ještě neznamená odeslání, `dispatching` se po restartu čte jako
  `unknown`, `succeeded` se vrací idempotentně a `failed` vyžaduje nový run.
- Projektový Git se mění až samostatnou potvrzenou publikací výstupu. Katalog,
  credential, binding ani provider run nejsou projektové artefakty.

## Reuse a odmítnuté varianty

Adapter reuse/adaptuje `BackendRegistry`, `BackendRuns`, Context Manifest,
externí preview/confirmation, provider-neutral katalog a bounded Responses SSE
parser. Nepřebírá provider SDK ani MCP server a nepřidává runtime závislost.
Odmítáme obecný proxy adapter s uživatelským URL, implicitní Chat Completions
fallback, automatický retry 429, capabilities podle názvu a synchronizaci
API klíče nebo availability přes projektový Git.
