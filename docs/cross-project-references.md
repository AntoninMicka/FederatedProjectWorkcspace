<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Připnuté meziprojektové reference — XREF-01

První řez poskytuje CLI a Python službu mezi lokálně registrovanými projekty.
Reference zobrazuje konkrétní revizi zdrojového artefaktu read-only. Novější
obsah nabídne, ale nepřevezme bez potvrzeného repinu. Nový GUI formulář tento
řez nepřidává; generický prohlížeč dokumentů může zobrazit JSON deskriptor.

## Sdílení podkladu — XREF-02

Od XREF-02-A vyžaduje nová reference explicitní sdílení ve zdrojovém
projektu ([ADR 0086](adr/0086-cross-project-artifact-sharing.md)). Editor
zdroje vytvoří záznam sdílení jednoho artefaktu. Záznam určuje povolené cílové
projekty, původce a důvod. Připojení v cíli pak uvede ID sdílení a vlastní
důvod použití. Resolver při každém použití ověří, že sdílení trvá a uvádí
právě tento cíl. Oprávnění uživatele k oběma projektům tím nenahrazuje.
Reference v1 vytvořené před XREF-02 zůstávají čitelné jako `share: null`.
Volba `--purpose output` označí artefakt jako výstup projektu pro jeho
odběratele, výchozí `share` je běžné sdílení podkladu.

```sh
python3 -m spikes.cross_references --node NODE share-preview SOURCE_PROJECT SHARE_ID ARTIFACT 'Důvod sdílení' --target TARGET_PROJECT > share.json
python3 -m spikes.cross_references --node NODE share-write share.json --operation-id OPERATION_UUID --sha256 PREVIEW_SHA256 --confirm
```

Sdílení a připojení jsou dvě samostatné potvrzené operace ve dvou
repozitářích. Sdílení bez připojené reference je platný mezistav.

V běžném Workspace UI (XREF-02-B):

- **Sdílet do projektu** v menu podkladu nabídne jen projekty, které
  přihlášený uživatel vidí. Zvolíte účel (sdílení nebo výstup projektu)
  a důvod. Dialog ukáže i dosavadní sdílení tohoto podkladu a jeho použití
  v dostupných projektech.
- **Připojit z jiného projektu** v Podkladech ukáže podklady sdílené do
  otevřeného projektu, včetně výstupů. Po výběru zadáte název a důvod použití.
- Oba kroky nejdřív ukážou přesný serverový náhled (cíle, revize, SHA-256,
  privacy) a uloží se až po zaškrtnutí potvrzení. Opakované potvrzení
  používá stejné operation ID.
- Připojený podklad je v seznamu označený **Sdílené · jen ke čtení**.
  Otevře se připnutá revize s původem (zdrojový projekt, revize, soubor,
  důvod, kdo sdílel a připojil) a stavem zdroje. Nedostupný, smazaný nebo
  odvolaný zdroj se ukáže jako stav, ne jako chyba. Úpravy a mazání
  reference nabídka nenabízí.
- Záznamy sdílení se v seznamu podkladů nezobrazují; jsou vidět v dialogu
  sdílení u konkrétního podkladu.

Správa a použití (XREF-02-C):

- Pokud ve zdroji vznikne novější revize, otevřený sdílený podklad dál
  ukazuje původní připnutou verzi a nabídne **Porovnat a aktualizovat**.
  Náhled ukáže rozdíl obou revizí. Aktualizace platí jen pro tuto referenci,
  dřívější úkoly a manifesty nemění.
- **Vytvořit vlastní kopii** vytvoří upravitelný podklad s trvalým původem.
- **Odebrat z projektu** smaže jen odkaz v cíli; zdroj a sdílení zůstávají.
- Ve zdroji v dialogu **Sdílet do projektu** tlačítko **Ukončit sdílení**
  ukončí sdílení pro všechny jeho cíle. Ukončení je konečné. Zabrání dalšímu
  zobrazení, kopii i použití v AI kontextu, ale už vytvořené kopie v cílech
  zpětně neodstraní.
- Sdílený podklad lze vybrat mezi podklady úkolu či konverzace (označení
  „sdílené, jen ke čtení“). Manifest nese přesný pin a sdílení; po ukončení
  sdílení se úkol s tímto vstupem odmítne.

```sh
python3 -m spikes.cross_references --node NODE revoke-preview SOURCE_PROJECT SHARE_ID > revoke.json
python3 -m spikes.cross_references --node NODE revoke revoke.json --operation-id OPERATION_UUID --sha256 PREVIEW_SHA256 --confirm
python3 -m spikes.cross_references --node NODE detach-preview TARGET_PROJECT REFERENCE_ID > detach.json
python3 -m spikes.cross_references --node NODE detach detach.json --operation-id OPERATION_UUID --sha256 PREVIEW_SHA256 --confirm
```

HTTP: `/v1/sharing/overview`, `/v1/sharing/share/preview|confirm`,
`/v1/sharing/attach/preview|confirm`, `/v1/sharing/reference/view`,
`/v1/sharing/repin|fork|detach|revoke/preview|confirm`. Každý
požadavek běží s identitou a rozsahem přihlášeného uživatele.

## Vyzkoušení bez zásahu do existujících projektů

Z kořene checkoutu spusť ukázku s novým, dosud neexistujícím adresářem:

```sh
python3 -m scripts.reference_demo /tmp/fpw-reference-demo
```

Vzniknou dva syntetické projekty a samostatný node config. Ukázka sdílí
podklad do příjemce, vytvoří referenci, změní zdroj a vypíše `state: newer-available` spolu s původním
`pinned_text: První připnutá revize.`. Nic neposílá modelu ani do Workspace.

Prohlédni soubory:

- `01-pinned-view.json`: původní připnuté zobrazení.
- `02-newer-offered.json`: stejný obsah, nabídka nové revize v `newer`.
- `context-manifest.json` a `context-payload.json`: manifest a skutečné bajty
  původní revize po ověřené přípravě i kontrole dispatch.
- `update-preview.json`: přesný návrh repinu k review.
- `demo.json`: vygenerované identifikátory a `explicit_update_command`.

Po posouzení návrhu spusť vypsaný `explicit_update_command`. Následný příkaz
`view` s node, target project ID a reference ID z `demo.json` zobrazí druhou
revizi. Nejde o test normálního profilu ani lidskou akceptaci úkolu.

## CLI nad registrovanými projekty

```sh
python3 -m spikes.cross_references --node NODE pin SOURCE_PROJECT ARTIFACT > pin.json
python3 -m spikes.cross_references --node NODE preview TARGET_PROJECT NEW_REFERENCE_ID pin.json 'Název odkazu' --share SHARE_ID --reason 'Důvod použití' > preview.json
python3 -m spikes.cross_references --node NODE write preview.json --operation-id OPERATION_UUID --sha256 PREVIEW_SHA256 --confirm
python3 -m spikes.cross_references --node NODE view TARGET_PROJECT REFERENCE_ID
python3 -m spikes.cross_references --node NODE index TARGET_PROJECT
```

Identifikátory jsou UUID. Preview odpověď má `value` a `sha256`; writer vyžaduje
právě tento digest a explicitní `--confirm`. HEAD zdroje/cíle zjistí služba.
Přerušenou odpověď opakuj se stejným operation ID a stejným preview.
CLI běží jako lokální vlastník uzlu a předpokládá jeho důvěryhodné OS oprávnění.
ChatService místo toho používá identitu přihlášeného uživatele a delegovaný
rozsah requestu; obecná oprávnění účtu tento rozsah nerozšíří.

Pro repin ulož `newer` z online view jako pin JSON, vytvoř preview se stejným
reference ID a `--update` a potvrď nový digest. Soubor pin může být přímo
objekt nebo ověřená CLI obálka `value`/`sha256`. Změna jiného artefaktu ve
zdrojovém projektu sama nabídku aktualizace nevytvoří.

Explicitní kopie má samostatný krok:

```sh
python3 -m spikes.cross_references --node NODE fork-preview TARGET_PROJECT REFERENCE_ID NEW_ARTIFACT_ID > fork.json
python3 -m spikes.cross_references --node NODE fork fork.json --operation-id OPERATION_UUID --sha256 PREVIEW_SHA256 --confirm
```

Fork má nové ID a neměnnou provenance připnutého zdroje. Markdown dokument
lze lokálně upravovat; ostatní obsah je raw Source. Původní reference zůstává
připnutá a fork se sám neaktualizuje.

## Autorizace, offline stav a Context Manifest

Zobrazení vyžaduje živé oprávnění k oběma projektům. Efektivní privacy je
nejsilnější z místní reference, připnuté revize a aktuálního zdroje. Odvolaný
přístup, známé smazání, neplatný pin nebo pending source operace odmítnou
čtení i při existující cache. `--online-only` zakáže offline fallback.

Při nedostupném registrovaném source repozitáři může `view` použít soukromou
cache, pokud místní oprávnění stále platí. Výsledek je `offline-stale`,
`stale: true`, `privacy_unverified: true`; aktuální source privacy tehdy
nelze potvrdit. Tento obsah se nesmí použít pro Context Manifest, fork ani
externí boundary. Cache se ukládá mimo projektový Git a jeho autoritativní
state; ztráta cache nepoškodí referenci. Zjištěné smazání nebo ukončení
sdílení zanechá v cache náhrobek pro všechny účty uzlu. Při pozdějším výpadku
zdroje se pak uložená kopie nezobrazí (XREF-02-D, ADR 0086).

V UI se offline kopie zobrazí s časem posledního ověření a privacy označenou
„neověřeno“. Bez ověřené kopie se ukáže stav `source-offline`. Pokud zdroj
na uzlu není registrovaný nebo k němu uživatel nemá přístup, například po
synchronizaci samotného cílového projektu, ukáže se `source-inaccessible`
bez obsahu. Zůstává jen volba odebrat odkaz. Úkol nebo zpráva se
nedostupným sdíleným vstupem se odmítne hláškou se stavem sdílení.

Index obsahuje pouze místní deskriptor. `index` živě doplní autorizovanou
dostupnost; nepovolený zdroj vrátí jen jako unavailable. ContextBuilder při
explicitním ProjectInput vyřeší referenci na přesné zdrojové bajty a manifest
obsahuje pin, zdrojový HEAD, revizi oprávnění, hash deskriptoru a privacy.
Před dispatch vše ověří znovu. Změna source HEAD i bez změny připnutých bajtů
vyžaduje novou přípravu. Editace/projekce přes referenci a reference na další
referenci jsou odmítnuty; pro editaci je určen explicitní fork.

Recovery, verzovaný formát a omezení revokace již získaných kopií popisuje
[ADR 0070](adr/0070-local-artifact-references.md). Rozpracovaný target intent
obnovuje původní Workspace journal bez opakovaného čtení zdroje.

## Důkazy a plánovací podklad

Rozsah odpovídá exportu projektu `c898b941-8eb0-4406-8dad-6e2b96c06d59`,
queue revision 202, project HEAD `03f4f27c6d399f2774b6c9c0b24ec827a1c44f1a`,
snapshot revision `e1d346bf43041e8fc9ac40edb72adb17f9d5a9d35df1bc8333df12c0b91847be`,
packet `e252ecbf19a8d590c1a9d69f603a7a1312beb230891e23e657a5eb26612c7861`.
Při zahájení byl export current/synchronized a source baseline
`1f4171bcdffeae43931aa1feb2dd3ebc3ccea09d` odpovídal develop po merge MON-02.
Toto je návrh výsledku k review; autoritativní akceptace ve Workspace zůstává
samostatným lidským krokem. Vzdálené reference patří M5.

Při závěrečné kontrole bridge hlásil `stale: true` a odmítnutí synchronizace
HTTP 422 (`failed_at: 2026-11-04T21:49:58.062Z`). Uvedený export tedy dokládá
zadání při zahájení; aktuální plánovací stav a doručení výsledku nejsou
potvrzené. Tato změna plánovací stav nepřepisuje.

Ověřeno: 21 testů `tests.test_cross_references` (včetně CLI, delegovaného
scope, revokace, privacy, cache, Context Manifestu, forku, rebuild indexu a
procesových pádů), 105 existujících chatových testů a skutečný běh syntetické
ukázky včetně následného potvrzeného CLI repinu a explicitního forku.
Závěrečná celá sada `python3 -m unittest discover -s tests -v`:
**1 546 testů za 512,606 s, OK, 44 skipped**. Běžela s povolenými lokálními
sockety pro existující integrační HTTP testy. `git diff --check`, whitespace
nových souborů a relativní odkazy nových návodů prošly.
