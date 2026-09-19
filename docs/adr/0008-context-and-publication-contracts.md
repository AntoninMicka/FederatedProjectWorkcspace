<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0008 — Backend, Role, Context Manifest a publikace

Datum: 2026-09-09. Stav: přijato jako **designed** pro M0-08; přesné snapshoty a dvoufázová revalidace Context Builderu jsou implementované jako lokální PoC ve F-M2-CONTEXT-01. F-M2-OLLAMA-01 navazuje lokálním PoC Ollama adapteru a trvalého run recordu; F-M2-CHAT-01/02 propojují node-local thread store, Context Manifest, Ollama adapter, projektové záznamy a desktopové UI. F-M2-SUMMARY-01 implementuje a lokálně PoC validuje níže popsaný summarizer, bezpečný náhled a potvrzenou publikaci; skutečný Qt/WebEngine smoke a živý model zůstávají podmíněné prostředím. F-M3-BACKEND-01-A uzavírá provider-neutral aplikační kontrakt a kompatibilní migraci existující Ollamy; implementace tohoto rozhraní zůstává v navazujících úkolech B/C. Nejde o úplné RBAC, externího providera ani synchronizační službu.

## Rozsah a návaznost

Zpřesňuje [ARCHITECTURE](../../ARCHITECTURE.md), [FEDERATION](../../FEDERATION.md) a [SECURITY](../../SECURITY.md). Zachovává koordinaci a crash boundaries [ADR 0003](0003-coordinated-operation.md) i rozdělení konfigurace [ADR 0004](0004-project-node-config.md). Nemění existující validátory ani schéma project.json/node.json. Kontrakty níže jsou logické v1; jejich budoucí serializace musí mít explicitní verzi, odmítat neznámé verze a nesmí potichu migrovat data.

Reuse: zachovat Workspace, validaci celého kandidátního stromu a compare-and-swap (CAS). Nové LLM kontrakty nejsou důvod přepisovat storage ani přebírat cizí adapter. Přesná serializace a její testy vzniknou v M2/M3, propojení publikace v M1/M5.

## Backend a role

| Kontrakt | Povinný význam |
| --- | --- |
| BackendDefinition | Stabilní ID, revize definice, název, typ adapteru/provider, model nebo pravidlo jeho výběru; deklarované účely (např. role execution, orchestrator chat, extraction), formáty a limity. Přenositelná definice neobsahuje secrets ani soukromé adresy uzlu. |
| BackendBinding | Lokální vazba definice na spravující node ID, endpoint, skutečný model, ověřené capabilities, dostupnost a execution boundary. Credentials pouze jako lokální opaque reference mimo Git; binding se automaticky nesynchronizuje. |
| ExecutionBoundary | `same-node`: zpracování i obsah zůstávají na původním uzlu; `private-network`: explicitní připnutá služba v privátní síti, která není lokální ani federovaným peerem; `trusted-federation`: konkrétní autentizovaný a povolený peer; `external-provider`: konkrétní externí služba. Localhost proxy sama nedokládá same-node. Přesměrování ani další zpracovatel nesmějí nepozorovaně změnit schválený cíl. |
| RoleDefinition | Stabilní ID a revize, verzovaná šablona instrukcí, povolené zdroje, povinné/volitelné vstupy, výstupní formát, požadované capabilities, preference modelu/backendu a omezení privacy. Projektový override má vlastní revizi a dohledatelný základ. |

Role zahrnují creator, opponent, analyst, researcher, editor, extractor, summarizer, classifier a issue-spotter. Role ani projektový override neudělují uživateli další oprávnění. Backend preference není souhlas s přenosem. Efektivní povolení je průnik aktuálních oprávnění uživatele, projektu, uzlu, role a pravidel cíle; zákaz má přednost. Stejná capability může existovat ve všech třech boundaries. Dostupnost ani nízká cena nejsou autorizace.

Pro Ollama znamená `same-node` pouze explicitní číselný loopback endpoint na
původním uzlu; hostname `localhost`, LAN adresa ani proxy tuto boundary
nedokládají. `private-network` používá výhradně číselnou privátní IP, HTTPS,
připnutý SHA-256 certifikátu a stabilní ID cílového uzlu/služby. DNS se pro tuto
boundary nepoužívá. Redirect je zakázán a změna adresy, pinu, modelu či identity
je změnou bindingu vyžadující nový Context Manifest. `local-only` smí pouze na
`same-node`; důvěryhodná LAN není výjimka. Binding je node-local mimo projektový
Git a nesmí obsahovat credentials. Jeho soubor se publikuje atomickým nahrazením
po `fsync` dat i adresáře; při každém načtení se kontroluje vlastník, režim,
velikost a celý kontrakt, takže restart nepřebírá nevalidovaný cíl. Adapter nemá
implicitní LAN/cloud fallback.
Ollama dispatch přijímá pouze autorizovaný Context Builder handoff nesoucí run ID
a přesný Target. Node-local SQLite journal potvrdí stav `dispatching` před prvním
síťovým bajtem; timeout či ztracená odpověď přejdou do `unknown` a stejný run se
automaticky neopakuje. Známé HTTP/redirect/response odmítnutí je `failed` a také
vyžaduje nový explicitní run. U `private-network` se TLS spojení naváže a pin
certifikátu ověří ještě před odesláním requestu. Úspěšná odpověď je durable a
opakované načtení stejného run ID ji vrátí bez dalšího volání.

Usage a billing jsou dvě samostatné volitelné capabilities. Výsledek přehledu nese stav (available, unsupported, forbidden, unavailable, stale), rozsah (run/project/account), zdroj, období, čas zjištění a jednotky; peněžní údaj také měnu a rozlišení hlášené hodnoty/odhadu s verzí ceníku. Chybějící hodnota není nula. Právo generate nezahrnuje účetní souhrny. Výpadek přehledu nemění routing ani cost policy; její vlastní požadavky se stále vyhodnotí. Obnovování/cache a provider API zůstávají M3-UB-01.

### Provider-neutral aplikační kontrakt v1

F-M3-BACKEND-01 zachová `ContextBuilder`, `Target` a `DispatchHandoff` jako
provider-neutral bezpečnostní hranici. Nad nimi zavede následující malé interní
kontrakty; nejde o nové projektové entity ani o provider discovery:

| Kontrakt | Povinný význam a validace |
| --- | --- |
| `BackendBinding` | Striktně verzovaná node-local konfigurace s `binding_id`, `revision`, `adapter_id`, boundary, přesným endpointem/cílem a modelem. Providerová pole validuje parser konkrétního adapteru. Z bindingu vzniká dosavadní `Target`; jeho identita, boundary ani model se nesmějí po autorizaci změnit. |
| `BackendCapabilities` | Neměnný, striktně verzovaný výsledek průniku capabilities deklarovaných adapterem a ověřených pro konkrétní revizi bindingu. V1 zná pouze `generate-text` a výstupní formáty `text` a `json`; neznámá capability, formát, schema verze nebo neověřená podpora se odmítne. Usage a billing zůstávají samostatná pozdější rozšíření, nikoli implicitní součást generování. |
| `RoleDefinition` | Neměnná registrace `role_id` a `revision`, instrukce, požadovaných capabilities, výstupního formátu a privacy omezení. V1 registruje dosavadní task role `summarizer`, `extractor` a `metadata-advisor`; role z requestu musí přesně odpovídat podporované revizi služby. `brainstorming` zůstává klasifikací vlákna, nikoli rolí. Role nevybírá adapter, neuděluje oprávnění a sama nemění execution boundary. |
| `BackendAdapter` | Adapter má stabilní `adapter_id`; validuje/normalizuje vlastní binding, deklaruje capabilities a z autorizovaného handoffu deterministicky připraví finální provider request. `prepare` trvale sváže run ID s adapterem, binding/target revizí, capability/role revizí, manifest hashem a digestem skutečného requestu; `dispatch` provede nejvýše jeden povolený externí účinek a vrátí normalizovanou odpověď. |
| `BackendRunStore` | Jediná node-local autorita stavu backendového běhu mimo projektový Git. Zachová stavy a právě-jednou hranici níže; klíč runu nesmí být sdílen jiným adapterem, bindingem, rolí, capability sadou, manifestem nebo request digestem. |

Aplikační služba nejprve načte binding přes společný registr adapterů, pro
role-based task vyžádá konkrétní roli a pro každý běh požadované capabilities a
až potom sestaví Context Manifest. Běžný chat bez task role vyžaduje přímo
`generate-text`; jeho klasifikace vlákna se do role nepřevádí. Registr
odmítne neznámý `adapter_id`, roli, revizi, capability i nejednoznačný binding;
nezkouší jiný adapter, model ani endpoint. Bezprostředně před dispatch znovu
načte stejnou revizi bindingu a ověří `Target`, capabilities, roli, autorizovaný
handoff a provider request digest. Providerový transport nikdy nedostane
Workspace, credentials jiného adapteru ani možnost sám doplnit kontext.

Chat, souhrn, extrakce a návrh metadat budou používat stejný orchestrátor
`prepare/dispatch/status`; jejich vlastní task journal a publikační recovery
zůstávají oddělené. Validace strukturovaného JSON výstupu patří nadále službě a
jejímu uzavřenému schématu, zatímco adapter ověřuje transportní obálku, model,
velikost a deklarovaný formát. Tím se obecný adapter nestává druhou autoritou
artefaktů, tasků ani rolí.

### Kompatibilní migrace Ollamy

Existující `ollama-binding.json` se schématem v1 zůstane kanonickým node-local
vstupem a nebude se při načtení automaticky přepisovat. Kompatibilní parser jej
normalizuje jako `BackendBinding(adapter_id="ollama")`; jeho `binding_id`,
`revision`, endpoint, model, target ID, TLS pin i význam `same-node` a
`private-network` zůstávají beze změny. Změna kterékoliv z těchto hodnot nadále
vyžaduje novou revizi a nový Context Manifest. První implementace nepřidává
další binding ani automatický výběr mezi backendy.

Současný `ollama-runs.sqlite` zůstane autoritativním run storem. Případná
schema migrace je lokální, transakční a doplňuje provider-neutral identitu;
nepřejmenovává run ID ani nepřepisuje request digest, odpověď nebo stav.
Dokončený historický běh je pouze čitelný jako legacy Ollama evidence.
`dispatching` a `unknown` zůstávají `unknown` a nikdy se automaticky neopakují.
Legacy `prepared` lze dokončit jen tehdy, pokud se z původního handoffu a
nezměněného Ollama bindingu znovu odvodí shodný request digest; jinak se odmítne
a uživatel musí založit nový run. Selhání migrace ponechá původní databázi
čitelnou předchozí implementací a nesmí částečně publikovat novou konfiguraci.

Context Manifest v této dávce nemění schéma: přesný `binding_id`, jeho revize,
boundary, target a model už dnes vážou autorizovaný obsah k cíli. Identita
adapteru, capability a role se doplní do provider-neutral run evidence a digestu
requestu. Změna manifestu bude nutná teprve pro přenosný BackendDefinition,
externí provider nebo jiný nový údaj ovlivňující autorizaci; taková změna musí
mít vlastní verzi a migrační rozhodnutí.

## Context Manifest a odeslání

Každý LLM běh včetně lokálního má manifest. Manifest identifikuje **konkrétní připravený požadavek**, nikoli pouze seznam názvů dokumentů.

| Část manifestu | Povinný obsah |
| --- | --- |
| Identita | Verze kontraktu, manifest ID, run ID, project ID, žádající user ID, původní node ID, čas vytvoření. ID uživatele musí být navázané na ověřenou session. |
| Role a cíl | ID/revize role a override, backend definition/binding revize, požadovaný a skutečně zvolený model, execution boundary a identita cíle. Neznámou přesnou verzi provider modelu přiznat. |
| Vstupy | Projektový commit ID; pro každý zdroj entity ID, cesta, blob ID, privacy, vybraná část a transformace. Instrukce, explicitní dotaz, vybrané zprávy a dosud necommitnuté vstupy mají vlastní neměnný snapshot a hash bajtů; nepředstírají Git verzi. |
| Připravený obsah | Pořadí zpráv/rolí, přesné texty, přílohy a parametry ovlivňující generování. Uchované finální obsahové bajty a jejich SHA-256, typ/kódování a velikost; odkazy na uchované přílohy s hash a velikostí. Credentials a transportní autentizační hlavičky se nearchivují. |
| Rozhodnutí | Revize použitých politik, povolený rozsah, vyhodnocení privacy a cost policy, zahrnuté/vynechané volitelné vstupy s důvodem, potvrzení výběru a případné explicitní reklasifikace. Audit nesmí zpřístupnit identitu či obsah zdrojů, které čtenář nesmí vidět. |

Hash bez uchovaných bajtů neumožňuje rekonstrukci. Plný manifest a snapshoty jsou chráněný lokální stav mimo projektový Git, se stejnými či přísnějšími oprávněními než vstupy. Jejich retence nesmí být zaměňována s obnovitelným indexem. Redigovaný/exportovaný audit musí přiznat, že není plně reprodukovatelný. Reprodukce požadavku nezaručuje stejný výstup modelu. Schválený výstup může do Gitu nést manifest ID/hash a bezpečnou provenance; úplný manifest se nepřikládá automaticky.

Tok: `UI / volitelný orchestrator chat → application orchestrator → Context Builder / workflow → backend adapter`.

1. Aplikační orchestrátor ověří session, požadovanou akci a oprávnění. Funguje bez LLM. Chat navrhuje strukturované akce; nedostává přímý přístup ke Gitu, shellu ani oprávnění obcházet aplikační služby.
2. Context Builder kontroluje právo číst ještě před načtením zdroje, vytvoří snapshot a deterministicky vybere povolený kontext. LLM může navrhnout výběr, ale jeho vlastní vstup vyžaduje manifest a stejnou kontrolu. Nesmí být povinným předpokladem Context Builderu.
3. Vyhodnotí skutečný cíl a privacy všech vstupů včetně uživatelského dotazu. Odvozeniny dědí nejpřísnější omezení a průnik přístupů zdrojů. Shrnutí ani prompt nemění klasifikaci. Překročení limitu nesmí tiše zahodit povinný vstup; vyžaduje změnu výběru. Volitelné vynechání je viditelné v manifestu.
4. Adapter připraví finální obsah požadavku bez síťového odeslání. Po kontrole formátů/limitů se zafixují bajty a manifest; žádné skryté přidání konverzace, vzdálené přílohy nebo instrukcí po schválení.
5. Bezprostředně před odesláním aplikace znovu ověří aktuální autorizaci, binding/cíl, policy a shodu bajtů s manifestem. Lokální změny policy a přechod do odesílání musí sdílet synchronizaci. Změna relevantních podmínek znamená odmítnutí a nové posouzení, případně nový manifest/souhlas. Odvolání po skutečném odeslání nemůže stáhnout již předaná data.
6. Adapter provede pouze schválené generate; vrátí výstup, stav, dostupné usage a provider request/model ID. Výstup je nedůvěryhodný návrh. Uložení jako projektový artefakt vyžaduje validaci, oprávnění a explicitní přijetí přes běžnou zápisovou operaci.

F-M2-CONTEXT-01 realizuje kroky 2–5 jako backendově neutrální read-only PoC v
`spikes/context_builder.py`. `prepare` pod projektovým writer lockem fixuje HEAD,
explicitně vybrané projektové a ad-hoc bajty, jejich velikosti/SHA-256, privacy,
autoritu, policy revision a přesný binding/cíl. Obsah je součástí kanonického
payloadu; samotný hash není snapshot. `authorize_for_dispatch` pod stejným
zámkem znovu ověří HEAD, session/user/node, čtecí oprávnění, policy, binding,
cíl, privacy a shodu bajtů a vydá pouze handoff. Nic neposílá ani trvale
nezapisuje run. Volitelný nedostupný vstup je uveden s důvodem; chybějící
povinný vstup operaci odmítne. Skutečný adapter musí před sítí použít právě tento
handoff a dodat vlastní durable přechod `dispatching`/`unknown`.

Fallback je ve výchozím stavu zakázaný. Explicitní pravidlo může povolit náhradní backend/cíl a nákladový rozsah; i potom se sestaví nový manifest a znovu ověří celý požadavek. Uživatelský výběr backendu nepřebíjí zákaz projektu. `local-only` nikdy nejde na peer ani provider bez explicitní, oprávněné a auditované reklasifikace konkrétních dat. Pouhé potvrzení „odeslat“ nestačí.

Lokální run record rozlišuje prepared, authorized, dispatching, succeeded, failed, cancelled a unknown. Přechod dispatching se trvale zaznamená před síťovým pokusem. Pád v této fázi nebo ztráta odpovědi znamená unknown, pokud provider nedoloží výsledek; není důvod automaticky opakovat potenciálně placený požadavek. Cancel requested není potvrzené cancelled. Ollama PoC tyto hranice realizuje vlastním node-local journalem; každý další adapter je musí doložit samostatně. Git journal z ADR 0003 nezajišťuje právě-jednou síťové volání.

## Lokální živé vlákno, zprávy a turn

F-M2-CHAT-01 zavádí autoritativní node-local thread store mimo projektový Git.
Není obnovitelným indexem, backendovým run storem ani projektovým artefaktem a
automaticky se nesynchronizuje. V1 má explicitní verzi schématu a odmítá
neznámou verzi nebo poškozené vazby. Každé vlákno nese stabilní UUID, vlastnící
node/user UUID, klasifikaci (výchozí `brainstorming`), stav active/archived,
čas vytvoření a monotónní revizi. Čas je informativní; autoritativní pořadí tvoří
transakčně přidělené celé pořadové číslo v rámci vlákna.

Zpráva je po potvrzení neměnná: stabilní UUID, thread ID, pořadí, role `user`
nebo `assistant`, přesné UTF-8 bajty, jejich SHA-256, privacy, autor a čas přijetí.
Oprava vytváří novou zprávu s vazbou na předchůdce; nepřepisuje historii.
UI draft není zpráva ani auditní záznam, v první verzi zůstává jen v paměti a po
pádu se může ztratit. Credentials, skryté provider instrukce a provider session
tokeny do thread store nepatří. Limity velikosti zprávy, počtu vybraných zpráv a
celého manifestu se kontrolují před trvalým přijetím nebo dispatch handoffem.

Jeden turn váže právě jednu uživatelskou zprávu, volitelný backendový run ID a
nejvýše jednu assistant zprávu. Jeho lokální stav je `prepared`, `run-bound`,
`completed`, `failed`, `cancelled` nebo `unknown`; není náhradou detailního stavu
backendového runu. Uživatelská zpráva a `prepared` turn vzniknou jednou SQLite
transakcí. Následně se vytvoří nový run a jeho ID se připne k turnu ještě před
dispatch. Pád před vznikem run recordu znamená bezpečně neodeslaný prepared turn.
Po připnutí se při obnově načte durable backendový stav: `dispatching` nebo
`unknown` se nikdy automaticky neopakuje, `failed` nevytvoří assistant zprávu a
`succeeded` lze idempotentně dokončit. Assistant zpráva a stav `completed`
vzniknou jednou thread-store transakcí s unikátní vazbou na turn; opakovaná
reconciliation tak nevytvoří duplikát.

Pokračování konverzace není implicitní přeposlání celého vlákna. Každý nový běh
explicitně vybere seřazené message UUID a jejich přesné bajty; Context Manifest
nese thread ID/revizi, message ID/pořadí/hash/privacy a nový uživatelský vstup.
Před dispatch se znovu ověří vlastník, nezměněná revize/výběr, privacy, policy a
přesný backend binding/model/boundary. Změna cíle vytváří nový manifest a run,
nikoli fallback. Projektové zdroje případně vybrané pro jednotlivý run zůstávají
samostatnými manifest inputs; v této dávce tím vlákno nevzniká jako projektový
artefakt ani nezískává trvalé přiřazení k projektu.

V1 uchovává potvrzená vlákna, zprávy a turny bez automatického časového mazání.
Archivace pouze skryje vlákno z běžného seznamu. Budoucí explicitní purge musí
být oprávněná operace vlastníka, odmítnout aktivní či neurčitý run, auditovat
rozsah a respektovat vazby na manifest/run; není součástí první implementace.
Provozní limit nebo nedostatek místa musí odmítnout nový zápis, nikoli tiše
odstraňovat starší kontext. Projektový snapshot či odvozený artefakt a jeho
retence patří do F-M2-CHAT-02 a běžného Workspace lifecycle.

Implementace F-M2-CHAT-01 v `spikes/chat_threads.py` používá samostatný SQLite
soubor s vlastněným režimem 0600 ve vlastněném stavovém adresáři 0700,
`foreign_keys=ON`, `synchronous=FULL` a `BEGIN IMMEDIATE` pro serializované
přechody. Při otevření kontroluje přesnou sadu tabulek/sloupců a verzi schématu;
neznámý, neúplný, symlinkovaný nebo příliš otevřený stav odmítne. Jde o
backendově neutrální storage/recovery vrstvu. `spikes/chat_service.py` váže nový
turn na explicitně seřazený výběr zpráv; manifest nese thread ID, revizi a
message ID, následně se revize před autorizací znovu ověří. Desktop ukládá
node-local Ollama binding a zobrazuje lokálně trvalé vlákno. UI nepřidává
projektové artefakty, neprovádí automatický retry neurčitého běhu a nepoužívá
náhradní cíl.
Ollama adapter z konverzačního payloadu deterministicky dekóduje přesné UTF-8
bajty a sestaví čitelný transcript `User`/`Assistant`; interní JSON a Base64
nepředává modelu jako uživatelský text. Odvozený request zůstává spolu s hashem
manifestu součástí durable request digestu.

## Projektové přiřazení, otisk a odvozený Markdown — F-M2-CHAT-02

Explicitní přiřazení živého vlákna k projektu je node-local pracovní vazba,
nikoli automatická publikace historie. Thread store je její autorita a v nové
verzi schématu uchová nejvýše jedno `project_id` spolu s revizí přiřazení.
Přiřazení vyžaduje aktuálně registrovaný a čitelný projekt, stejného vlastníka
vlákna a explicitní uživatelskou akci. Změna projektu zvýší revizi vlákna;
nepřenáší starší projektové artefakty ani nemaže již publikované otisky. Po
restartu se vazba znovu ověří proti registraci projektu. Cizí, odstraněný nebo
nově nedostupný projekt se zobrazí jako stale vazba a nesmí dodat kontext ani
umožnit publikaci.

Projektový otisk je nový artefakt `kind: snapshot`, `provenance: snapshot` se
standardním sidecarem a verzovaným souborem `snapshot.md`. Nepřidává neznámá
pole do metadata v1/v2. Markdown obsahuje čitelný transcript a jeden omezený,
kanonický JSON záznam `fpw-chat-snapshot-v1`, z něhož je transcript
deterministicky odvozen a při čtení znovu ověřen. Záznam nese:

- snapshot/artifact, project, thread ID a přesnou thread revizi,
- druh `full` nebo `delta`, seřazené message ID/sequence/role, přesné UTF-8
  bajty, SHA-256, privacy, autora a čas,
- pro příslušné turny turn ID, run ID, assistant message ID a manifest ID,
- nejpřísnější privacy všech zahrnutých zpráv a SHA-256 kanonického záznamu,
- u `delta` navíc artifact ID a hash kanonického záznamu základu, základní a
  výslednou thread revizi a navazující rozsah sequence.

`full` je samostatně čitelný a obsahuje všechny zvolené zprávy od počátku
vlákna do jedné potvrzené revize. `delta` obsahuje pouze souvislé nové zprávy po
revizi kompletního nebo delta základu. Před přípravou journalu se základ načte z
aktuálního validovaného projektového HEAD, ověří se jeho druh, project/thread ID,
kanonický hash a přesné pokračování sequence. Chybějící, změněný, cizí nebo
nesouvislý základ operaci odmítne; delta se nikdy nepovýší na full. Otisk je po
publikaci obsahově neměnný. Nový výběr či oprava vytváří nové UUID; běžné
anotace mohou vzniknout jen novou verzí metadat bez změny kanonického záznamu.

Samostatný výstup úkolu je `kind: document` a `provenance: llm-generated` nebo
`llm-transformed`. Jeho editovatelný Markdown před vlastním tělem nese omezenou
provenance obálku `fpw-chat-output-v1`: source thread/revision, přesná message a
turn/run/manifest ID, případný snapshot artifact ID/hash a privacy vstupů.
Projektová metadata používají vztah `derived-from` na existující snapshot,
pokud je snapshot součástí stejné nebo starší validované projektové verze.
Editace dokumentu zachová tuto původní obálku; změna zdrojového výběru je nový
odvozený výstup, nikoli přepsání historie chatu. Výstup dědí nejpřísnější
privacy zahrnutých zpráv a vstupů; oslabení vyžaduje samostatnou autorizovanou
reklasifikaci mimo tuto dávku.

Publikace reuse/adaptuje jedinou Workspace operaci z ADR 0003. Request předem
fixuje operation ID, expected HEAD, thread ID/revizi, výběr, výsledné UUID/cesty
a přesné cílové bajty. Pod writer lockem se znovu ověří projektový HEAD,
vlastník, přiřazení a nezměněná revize/výběr; celý kandidátní strom a přechod se
validují před uložením journalu. Pád před CAS nepublikuje částečný otisk či
dokument. Po CAS recovery rozpozná stejný commit, dokončí index/receipt a
nevytvoří druhé UUID ani commit. Git commit a node-local thread DB nejsou jedna
transakce: publikovaný snapshot je neměnný záznam zvolené revize, nikoli příslib,
že živé vlákno zůstalo beze změny. Credentials, backend binding, provider
session token a úplný soukromý Context Manifest se nepublikují.

Reuse rozhodnutí: adaptovat `ChatThreads`, `Artifacts`, striktní metadata a
`Workspace`/Journal/Index. Nová databáze, content-addressed store, Markdown
parser nebo externí komponenta nejsou potřeba; posouzené obecné Git utility
nenahrazují koordinovaný Workspace lifecycle této publikační cesty.

Implementace F-M2-CHAT-02-B v `spikes/chat_records.py` tento kontrakt realizuje
pro přiřazení a full/delta snapshoty. `ChatThreads` migruje přesné schéma v1 na
v2 v jedné SQLite transakci, ukládá `project_id`, revizi přiřazení a manifest ID
turnu; samotná DB se do projektu nekopíruje. `ChatRecords` před založením
journalu ověří registrovaný projekt, expected HEAD, vlastníka, přiřazení a
thread revizi. Delta navíc čte a validuje kanonický záznam základu z aktuálního
HEAD. Snapshot a jeho privacy jsou po publikaci neměnné přechodovým validátorem;
opakování stejného operation ID používá běžný Workspace receipt/recovery.
F-M2-CHAT-02-C doplňuje editovatelný `fpw-chat-output-v1`. Jeho omezená
kanonická obálka nese thread revizi, vybrané message ID, odpovídající
turn/run/manifest vazby, privacy a volitelný snapshot ID/hash; běžný Markdown
za obálkou zůstává editovatelný. Přechodový validátor odmítne odstranění nebo
změnu původní obálky. Autentizované desktopové API/UI provádí explicitní
přiřazení, full snapshot a uložení poslední odpovědi, poté načte nový projektový
HEAD. Průběžný stav LLM požadavku je u promptu, nikoli ve scrollující historii.

## Lokální summarizer, náhled a potvrzená publikace — F-M2-SUMMARY-01

První summarizer je explicitní jednorázový úkol, nikoli background indexace ani
automatický metadata hook. Kanonický request `fpw-summary-request-v1` nese
stabilní task/run/manifest ID, project ID a expected HEAD, verzi role
`summarizer-v1`, přesný same-node cíl a volitelný uživatelský focus. Focus je
samostatný UTF-8 vstup nejvýše 16 KiB s explicitní privacy a je zahrnutý v
manifestu; není skrytou instrukcí mimo request. V1 přijímá právě
jeden ze dvou druhů seřazeného výběru:

- jeden až 64 projektových artifact ID z jediného validovaného HEAD, nebo
- jedno vlastní živé vlákno s přesnou revizí a jedním až 64 seřazenými message
  ID.

Smíšený výběr projektových artefaktů a zpráv v jednom běhu v1 nepodporuje;
nesmí být emulován skrytým přidáním vstupů. Aplikace sestaví čitelnou,
verzovanou instrukci role a fixuje ji spolu s přesnými vstupními bajty v
Context Manifestu. První implementace přijímá pouze binding s execution
boundary `same-node`; nedostupnost lokálního backendu neaktivuje LAN ani cloud
fallback. Oprávněné entity odvozuje z aktuální aplikační autority,
nikoli z klientem deklarovaného seznamu. Platí existující limit kontextu 16 MiB;
výstup musí být neprázdný UTF-8 Markdown nejvýše 1 MiB. Překročení limitu,
nečitelný vstup nebo změna výběru vyžaduje nový task a manifest, nikoli tiché
zkrácení. V1 nepoužívá embeddings, RAG ani automatickou volbu zdrojů.

### Node-local task a síťový běh

Backendově neutrální task journal je autorita pracovního requestu, přesného
manifestu, náhledu a potvrzení publikace. Je node-local mimo projektový Git,
má striktně verzované SQLite schéma, vlastněný soubor 0600 ve stavovém adresáři
0700 a serializované přechody. Nejde o obnovitelný projektový index ani o kopii
projektových dat. Ukládá request digest, přesné manifest a payload bytes/hash,
privacy, stav, výstup/hash a případný fixovaný publikační request/receipt.
Credentials, provider session tokeny a transportní hlavičky neukládá.

Stavy jsou `prepared`, `run-bound`, `succeeded`, `failed`, `cancelled`,
`unknown`, `publishing` a `published`. `cancelled` je bezpečné jen před
dispatch nebo po doloženém potvrzení backendu, nikoli po pouhém požadavku na
zrušení. Task vznikne trvale před vazbou na backendový run.
Context Builder připraví a bezprostředně před odesláním znovu autorizuje přesný
handoff. Existující `OllamaRuns` zůstává jedinou autoritou síťového účinku:
`dispatching` či ztracená odpověď znamená `unknown` a žádný automatický retry.
Pád po úspěchu backendu, ale před uložením preview se obnoví opětovným čtením
stejného succeeded runu; nevznikne druhé volání. Validní odpověď se jako bounded
preview uloží do task journalu a zobrazí se jako nedůvěryhodný Markdown bez
aktivního HTML. Preview samo nemění Git, index ani metadata projektu.

### Potvrzení a projektový artefakt

Uživatel potvrzuje přesný preview SHA-256, cílové artifact UUID, title,
operation ID a expected HEAD. Tím se task atomicky přepne do `publishing` a
fixuje se request digest; před voláním Workspace se tasková SQL transakce
uzavře, aby nevzniklo vzájemné držení zámků. Jiný publish request pro stejný
task se odmítne. Workspace pod svým writer lockem znovu ověří expected HEAD,
projekt, oprávnění, původní entity či thread/message revizi, manifest a preview
hash. Poté publikuje `kind: document`, `provenance: llm-generated` se sidecarem
a Markdownem obsahujícím omezenou kanonickou obálku `fpw-summary-v1`.

Obálka nese task/run/manifest ID a hash, role ID/revizi, project commit,
seřazené bezpečné source reference s ID/hash/privacy, binding/model/target,
preview hash a výslednou privacy. Úplné vstupní bajty, celý soukromý manifest a
credentials se do artefaktu nekopírují. Projektové vstupy dostanou vztah
`summarizes`; message ID z node-local chatu zůstávají pouze v obálce. Privacy
artefaktu je nejpřísnější privacy vstupů a focusu. Shrnutí ji samo nesnižuje.
Pozdější běžná editace mění čitelnou část dokumentu v nové Git verzi, ale
přechodový validátor zachová původní `fpw-summary-v1` obálku beze změny.

Crash boundaries záměrně oddělují LLM a Git:

1. před durable `run-bound` nevznikl síťový účinek; po něm se stav rekonciluje
   podle `OllamaRuns`, nikoli opakováním volání,
2. před Workspace journalem není projektový zápis připraven a task může zůstat
   bezpečně `succeeded` nebo `publishing`,
3. journal před CAS vlastní přesné výsledné bajty; pád před posunem refu nic
   nepublikuje,
4. po CAS Workspace recovery dokončí index/receipt bez druhého commitu a stejný
   receipt následně idempotentně dokončí task jako `published`.

Reuse/adapt rozhodnutí: rozšířit Context Builder o verzovaný task/role vstup,
reuse jeho manifest a revalidaci, `OllamaBindings`/`OllamaAdapter`/`OllamaRuns`
pro přesný lokální cíl a síťový lifecycle a Workspace/Artifacts/metadata pro
jedinou projektovou publikační cestu. Task journal adaptuje striktní SQLite vzor
`ChatThreads`, ale nesdílí jeho tabulky ani význam. Existující chatový output
kontrakt lze adaptovat pro kanonickou obálku a její neměnnost. Obecné backendové
utility ze soukromé inventury nepřinášejí potřebný manifest, autorizaci ani
recovery a jejich licence nejsou pro přenos doložené; kód se nepřebírá. Nová
vektorová databáze, message queue, parser, externí framework ani další
projektové úložiště nejsou potřeba.

## Lokální strukturovaná extrakce — F-M2-EXTRACT-01

Extractor je explicitní jednorázový úkol nad stejnou autorizační a recovery
hranicí jako summarizer. Kanonický `fpw-extraction-request-v1` nese stabilní
task/run/manifest ID, project ID a expected HEAD, `extractor-v1`, přesný
same-node binding, právě jeden artifact nebo thread/message výběr a předem
zvolené `schema_id`/`schema_revision`. V1 nepřijímá uživatelské JSON Schema,
automaticky nevolí schéma ani zdroje a nepoužívá RAG. Volitelný focus zůstává
samostatným manifestovaným vstupem nejvýše 16 KiB s vlastní privacy.

Podporovaný katalog v1 je záměrně uzavřený:

- `facts` / `facts-v1`: přesný objekt `{"schema":"facts-v1","items":[...]}`;
  každá položka má právě `statement` a `source_ids`,
- `action-items` / `action-items-v1`: přesný objekt
  `{"schema":"action-items-v1","items":[...]}`; každá položka má právě
  `title`, `details` a `source_ids`.

`items` obsahuje 0 až 128 objektů. Texty jsou neprázdné, bez NUL, `title`
nejvýše 200 bajtů UTF-8 a ostatní textové pole nejvýše 4096 bajtů. Každý
`source_ids` je neprázdný seřazený unikátní seznam UUID z explicitně vybraných
zdrojů; focus ID není zdrojová reference. Parser přijímá právě jeden UTF-8 JSON
objekt nejvýše 1 MiB, odmítá Markdown fence, trailing data, duplicitní klíče,
neznámá pole, špatný schema tag, chybějící pole a nečíselné konstanty. Teprve
po této validaci uloží task journal kanonické JSON bajty a jejich SHA-256 jako
preview; původní provider response zůstává dohledatelná pouze v odděleném
`OllamaRuns`. Nevalidní známá odpověď je `failed`, nikoli preview k potvrzení.

Potvrzení váže task ID, preview hash, artifact ID, title, operation ID a
expected HEAD. Workspace znovu ověří původní zdroje či přesnou thread revizi,
manifest, schema revision a nejpřísnější privacy. Publikuje neměnný
`kind: source`, `provenance: llm-generated`, soubor `extraction.json` jako
kanonický objekt `fpw-extraction-v1` s omezenou provenance (task/run/manifest a
hash, role/schema, project commit, bezpečné source ID/hash/privacy, přesný cíl,
preview hash/privacy) a validovanými daty. Projektové vstupy dostanou vztah
`derived-from`; message ID zůstanou pouze v obálce. Celý výstup je neměnný pod
stejným UUID stejně jako jiné source artefakty; oprava nebo jiné schéma znamená
nový task a nové UUID.

Task journal adaptuje schéma a přechody `SummaryTasks`, ale extractor má vlastní
store a význam, aby se role, validátor a publikace nemohly zaměnit. Reuse
ContextBuilderu, Ollama binding/run lifecycle, Workspace a omezeného JSON
parseru/UUID primitiv z `metadata.py` je přímý; summarizer orchestrace se
adaptuje společnými malými helpery pouze tam, kde nezamlží odlišnou validaci.
Soukromě inventarizovaný jednoduchý Ollama klient ani externí schema framework
neřeší manifest, oprávnění, přesný recovery lifecycle či omezený katalog; kód
se nepřebírá a nová runtime závislost nevzniká. Crash boundaries jsou stejné:
`unknown` síťový účinek se neopakuje, preview nemění Git a stejný publish
request po pádu před/po CAS pouze dokončí Workspace receipt a task.

## Lokální návrhy popisu a štítků — F-M2-META-AI-01

Metadata advisor je explicitní jednorázový návrh pro právě jeden artefakt,
nikoli background hook ani oprávnění modelu zapisovat do projektu. Kanonický
`fpw-metadata-suggestion-request-v1` váže task/run/manifest ID, project ID,
expected HEAD, jediné artifact ID, roli `metadata-advisor-v1` a přesný
`same-node` binding. Server do Context Manifestu vloží přesné bajty obsahu a
kanonický snapshot aktuálních polí `title`, `description`, `tags`, `kind`,
`privacy` a `provenance`; jejich hash je součástí tasku. Model nedostane možnost
navrhovat změnu title, privacy, provenance, druhu ani identity artefaktu. V1
nevybírá artefakty automaticky, neprochází celý projekt a nepoužívá RAG.

Odpověď je jediný striktní JSON objekt nejvýše 1 MiB s přesným tvarem
`{"schema":"metadata-suggestions-v1","description":string|null,"tags":[]}`.
Description je buď `null` (bez návrhu), nebo oříznutý neprázdný UTF-8 text bez
NUL nejvýše 4096 bajtů. Tags obsahují nejvýše 16 oříznutých neprázdných UTF-8
řetězců bez řídicích znaků, každý nejvýše 64 bajtů; duplicity podle Unicode
`casefold` se odmítnou. Markdown fence, trailing data, duplicitní klíče,
neznámá pole, neplatný schema tag a překročení limitu znamenají `failed`, ne
náhled. Prázdný seznam je platný stav „žádné nové štítky“, nikoli pokyn smazat
stávající hodnoty. Validovaný výstup se kanonizuje a uloží jako node-local
preview oddělené od projektového Gitu.

UI ukáže přesný původní a navržený popis a množiny existujících a nových
štítků bezpečným textovým vykreslením. Popis se nikdy nepřepíše automaticky;
uživatel jej musí samostatně zaškrtnout, zvlášť pokud již existuje ruční
hodnota. U štítků uživatel vybírá podmnožinu nových návrhů, která se přidá ke
stávajícím štítkům v jejich původním pořadí. V1 štítky automaticky
neodstraňuje ani nepřejmenovává. Potvrzení musí vybrat alespoň jednu skutečnou
změnu a nese task ID, preview SHA-256, project/artifact ID, expected HEAD,
operation ID, boolean pro popis a přesný seznam vybraných navržených tagů.

Workspace před journalem znovu ověří HEAD, celý původní metadata snapshot a
hash obsahu. Zachová všechna jiná pole včetně privacy a provenance a připraví
jedinou změnu stávajícího sidecaru nebo frontmatteru. Kandidátní strom projde
standardní validací metadat; stejný operation ID po pádu obnoví stejný commit a
receipt. Změněný HEAD či metadata vyžadují nový návrh, aby starý diff nepřepsal
ruční práci. Task se fixuje do `publishing` před Workspace, po potvrzeném
receiptu do `published`; síťový stav `unknown` se automaticky neopakuje.

Reuse/adapt rozhodnutí: použít Context Builder, `OllamaBindings`/adapter/run
lifecycle, striktní JSON/UUID primitiva a Workspace/Journal/Index; adaptovat
oddělený task/preview vzor extractoru a metadata patch z `Artifacts.save` tak,
aby fungoval pro validovaný artefakt bez změny obsahu. Přímé volání editoru se
odmítá, protože vyžaduje Markdown body a neumí potvrzení AI preview pro source
artefakty. Nová databáze, schema framework, tagovací knihovna, vektorová DB ani
externí klient nejsou potřeba. Soukromá inventura nenabízí komponentu s tímto
Context Manifest, potvrzením a recovery kontraktem; žádný kód se nepřebírá.

Implementace F-M2-META-AI-01-B používá `MetadataSuggestionService` nad
společnou preview orchestrací, ale vlastní SQLite task store. Serverový hook
přidává kanonický metadata snapshot jako ad-hoc vstup se stejnou privacy jako
artefakt; klient určuje pouze jeho nové UUID, nikoli obsah. Striktní validátor
ukládá až kanonický návrh a projekce preview vrací původní hodnoty a přesný diff
bez projektového zápisu. Summary a extractor bez hooku zachovávají původní
payload i chování.

## Větve a publikace při změně HEAD

Publikace zde znamená posun autoritativní projektové větve **na jednom uzlu**. Není současně síťovým odesláním ani atomickou transakcí všech peerů. Projekt má explicitně zvolený plný ref (výchozí pro nový projekt `refs/heads/main`); nepředpokládat, že každý existující projekt používá main. Detached/unborn HEAD a probíhající merge/rebase dosavadní Workspace odmítá.

Přijaté peer refs a kandidáti jsou oddělení od projektové větve. Jméno větve nedokládá identitu peeru; příjem musí navázat commit na autentizovaný přenos a povolený projekt. Cizí objekty se nejprve validují v izolovaném prostoru. Fetch nesmí sám posunout projektovou větev ani index. Přenos celého Gitu zpřístupní i historii: před síťovým přenosem musí být povolen celý dosažitelný obsah, nejen současný strom. Projekt s local-only nebo jiným zakázaným historickým obsahem nelze sdílet běžným clone/push; případný filtrovaný export je samostatná explicitní operace, nikoli přepsání historie tohoto projektu.

Zápisový záměr nese operation ID, project ID, plný ref, expected HEAD, vlastněné cesty, autora a kandidáta. Uživatelské řešení konfliktu je vázané na přesné base/mine/theirs commit IDs. Pod společným zámkem se ověří oprávnění, čistý/povolený lokální stav a celý kandidátní strom (schéma, ID, obsah/sidecar, vztahy). Fast-forward vyžaduje stejné kontroly jako merge. Divergentní historie se slučuje commitem se dvěma rodiči; konfliktní rodiče se nezahazují a force-push se nepoužívá.

Kandidát se uloží do journalu **před** CAS posunem refu z expected HEAD. Změna refu nebo HEAD znamená konflikt; kandidát nesmí přepsat novou historii. Nový pokus načte nový základ, znovu sestaví a validuje kandidáta; původní lidské schválení odlišného konfliktu nepřebírá automaticky. Pending stav se řeší recovery/explicitním vyřešením, nikoli smazáním journalu. Abort zachová vstupní historie i cizí práci.

Crash boundaries z ADR 0003 zůstávají: před CAS není kandidát publikovaný; po CAS recovery rozpozná uložený kandidát, nevytváří duplicitní commit a dokončí index/receipt. Při jiném HEAD/větvi se zastaví s konfliktem. Index lze obnovit z validovaného publikovaného commitu; pending nebo stale projekce nesmí vydávat data za aktuální. Produkční merge musí tento lifecycle adaptovat v M5; dnešní Workspace merge neimplementuje. Nejde o ochranu proti nekooperujícímu procesu měnícímu filesystem nebo Git ref mimo aplikační zámek.

## Návrhová kontrola scénářů

Tabulka je review rozhodnutí, nikoli záznam spuštěných testů.

| Situace | Očekávané rozhodnutí |
| --- | --- |
| Uzel bez LLM | Projektové operace fungují, AI akce hlásí nedostupnost. |
| Lokální Ollama se schopností sumarizace | Po autorizaci a manifestu lze použít same-node; není nutný orchestrator chat. |
| Lokální backend nedostupný, cloud fallback nepovolený | Neodeslat; nabídnout změnu dostupnosti/výběru v mezích policy. |
| Explicitně povolený cloud a project data | Odeslat pouze při oprávnění, povolené boundary, cost policy a manifestu pro tento cíl. |
| Důvěryhodný peer a project data | Důvěra nestačí: ověřit uživatele/projekt/cíl a policy, vytvořit manifest. |
| local-only vstup nebo jeho shrnutí na peer/cloud | Odmítnout; nejprve explicitní oprávněná reklasifikace. |
| Role opponent navazuje na creator | Nový běh a manifest pouze s explicitně předanými artefakty; nepřidat celou konverzaci. |
| Policy/cíl změněný po náhledu | Zastavit odeslání a znovu vyhodnotit, nepoužít staré schválení. |
| Timeout po zahájení odesílání | Unknown, žádný automatický placený retry po restartu. |
| Billing nedostupný nebo bez oprávnění | Ukázat odpovídající stav; ne nulu, neposkytnout účetní data běžnému uživateli. |
| HEAD změněný po přípravě merge | CAS odmítne publikaci; nový základ a nové posouzení řešení. |
| Textově čistý merge s neplatným vztahem | Nepublikovat; starý index zachovat a nepovažovat za aktuální vůči jinému HEAD. |
| Zakázaný obsah pouze ve staré Git historii | Odmítnout přenos dosažitelných objektů, kontrola HEAD samotného nestačí. |

Návazná akceptace: M1/V-10 integrují klientské operation ID a receipts; M2 ověří manifest, přesné bajty a zákaz fallbacku; M3/M4 role, autorizaci a hranice; M3-UB-01 přehledy; M5 publikaci, historický rozsah přenosu a revokaci. Před implementací rozpracovat tyto scénáře do testů včetně selhání a restartu. Gate review M0-09 musí nadále zohlednit otevřené M0-05/M0-06.
