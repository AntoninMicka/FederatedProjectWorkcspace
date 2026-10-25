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
deklarovaného protokolu konkrétního modelu. Oficiální
[AtlasCloud MCP server](https://github.com/AtlasCloudAI/mcp-server) používá
veřejný `GET /api/v1/models`, jeho `supported_protocols` a providerové pořadí.
Workspace proto nesmí považovat AtlasCloud za jeden univerzálně
OpenAI-kompatibilní endpoint ani odvozovat protokol z názvu modelu.

Společný katalog `F-M3-MODEL-CATALOG-01` již odděluje providerovou nabídku,
protokol, capabilities a binding. AtlasCloud adapter tento kontrakt použije;
nebude zavádět vlastní router, fallback ani druhý znalostní katalog.

## Rozhodnutí

První řez podporuje providerem deklarované `openai-chat-completions-v1` a
`openai-responses-v1` na jejich pevných oficiálních endpointech. Adapter má ID
`atlascloud-text`, boundary `external-provider` a target `api.atlascloud.ai`.
Anthropic Messages, Gemini, media, MCP, CLI a billing API jsou samostatné
budoucí adaptéry nebo feature dávky.

Binding nese přesný `offer_id`, providerový model, protokol, revizi znalostní
vrstvy, credential revizi, capability snapshot a limity. Uložení bindingu
vyžaduje stejnou čerstvě objevenou AtlasCloud nabídku a protokol.
`generate-text` a `text-output` musí být podporované; JSON se odvodí pouze z
providerového `json_mode` nebo `structured_outputs`, streaming z doloženého
pravidla podporovaného wire protokolu. Neznámá nebo konfliktní capability je
nepodporovaná.

UI nejprve přijme credential a výslovně načte živý AtlasCloud katalog; uživatel
modelové ID ani capabilities ručně nepřepisuje. Discovery je read-only a
neukládá credential ani nevytváří binding. Protokol a capabilities představují
backendový modifikátor obecného modelu: určují endpoint, request/response tvar,
JSON a streaming pro konkrétní AtlasCloud nabídku. Teprve samostatné potvrzení
vybrané nabídky uloží API klíč a přesný binding. Discovery ani změna katalogu
existující binding automaticky nepřepne.

## Request, response a chyby

Request používá celý autorizovaný Context Manifest payload jako jeden textový
vstup, přesný model a limit výstupu. Backendový modifikátor jej pro Chat
Completions vloží do jediné user message a používá `max_tokens` a
`response_format`; pro Responses používá `input`, `max_output_tokens`,
`store: false`, `truncation: disabled` a `text.format`. Stream je povolen jen
při capability `streaming` a musí mít protokolem předepsaný terminální event.
Finální odpověď musí obsahovat právě jednu textovou volbu/message a model musí
odpovídat bindingu. Usage se uloží pouze pro validní nezáporné počty tokenů.

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
- `model-discovery-*` drží poslední úplný AtlasCloud snapshot. Neúspěšný refresh
  nepřepíše poslední validní data; pro nový binding se přijme jen čerstvá
  dostupná nabídka. Snapshot neobsahuje credential.
- Projektový Git se mění až samostatnou potvrzenou publikací výstupu. Katalog,
  credential, binding ani provider run nejsou projektové artefakty.

## Reuse a odmítnuté varianty

Adapter reuse/adaptuje `BackendRegistry`, `BackendRuns`, Context Manifest,
externí preview/confirmation, provider-neutral katalog a bounded SSE parsery.
Veřejný AtlasCloud MCP server byl použit jako ověřený zdroj discovery a
protokolového tvaru, jeho kód ani runtime závislost se nepřebírají. Odmítáme
obecný proxy adapter s uživatelským URL, implicitní protokolový fallback,
ruční přepis živého modelového katalogu, automatický retry 429, capabilities
podle názvu a synchronizaci API klíče nebo availability přes projektový Git.
