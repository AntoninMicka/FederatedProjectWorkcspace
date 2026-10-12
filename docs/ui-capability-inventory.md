<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Frontend shell a hranice desktopových capability

Tento dokument eviduje stav dávky `UX-UNIFIED-01`. Autoritativní projektová
data ani crash recovery se touto změnou nemění. Webový server a desktopový
WebEngine používají stejné `HTML` a `CSS` ze `spikes/desktop_ui.py`; varianty
smějí přidat pouze bootstrap autentizace a capability konkrétního uzlu.

## Společný frontend

- Katalog projektů, otevření projektu, sidebar, náhledy, chat, workflow,
  souhrny, extrakce, metadata, obrazové běhy, nastavení backendů, CMS a správa
  uzlu mají jediný DOM/CSS zdroj.
- Serverový bootstrap v `spikes/web_server.py` přidává přihlášení přístupovým
  klíčem, session/RBAC a serverové capability; společný import zdroje na webu
  navíc fail-closed nepovolí `local-only`.
- Desktopový bootstrap v `spikes/desktop_management.py` spoléhá na procesní
  token přidávaný WebEngine interceptorem a zpřístupní capability důvěryhodného
  single-user uzlu.
- Chybějící capability je skrytá deklarativním selektorem nebo atributem
  `hidden`; společný JavaScript nesmí selhat kvůli odstraněnému DOM prvku.

## Qt/PySide hranice

Qt zůstává oprávněný tam, kde je nutná integrace s lokálním OS nebo lifecyclem:

- výběr a oprava cesty lokálního projektu přes systémový file dialog,
- správa lokálního síťového procesu a test jeho endpointu,
- nasazení LXC uzlu a sledování lokálního workeru,
- přenos projektu využívající lokální credentials/proces,
- systémový askpass a otevření schváleného odkazu v systémovém prohlížeči,
- lifecycle okna, WebEngine procesu, signálů a bezpečného ukončení workerů.

Import jednotlivého zdroje je převeden na společnou samostatnou stránku
otevíranou z panelu Podklady. Používá stejný bounded endpoint, operation ID a
`Sources`/Workspace recovery v obou variantách; původní Qt dialog a toolbar
vstup byly odstraněny. HTML file input dál vyvolá platformní picker, ale
nevytváří paralelní workflow.

Historie podporovaného Markdown dokumentu je převedena na společnou read-only
alternativní stránku dokumentu, otevřenou z jeho akčního menu v seznamu
Podkladů. Web i desktop používají stejné HEAD-bound endpointy
`ArtifactHistory`; server navíc fail-closed odmítá projekt obsahující
`local-only`. Původní Qt `HistoryDialog` byl po dosažení parity odstraněn.

Akční menu existujícího dokumentu dále otevírá společnou stránku pro editaci
obsahu, názvu, souboru, popisu a štítků a potvrzené smazání; obě varianty
používají stejné `Artifacts` transakce. Kopírování ID je lokální UI akce.
Vytvoření nového dokumentu a hlavního TODO zatím zůstává v Qt editoru, takže
jeho úplné odstranění čeká na pozdější paritu těchto dvou vstupů.

Vytvoření projektu je nyní také společné: stránka Projekty vyžaduje serverový
náhled a potvrzení, zatímco Qt zůstává pouze systémovým pickerem přesné prázdné
složky. Picker vydá omezenou in-process capability vázanou na operation ID;
web nikdy nepřijímá cestu ani tento token a používá nakonfigurovaný projects
root. Původní `CreationDialog` a jeho paralelní toolbar vstup byly odstraněny.

Import NotebookLM je nyní také společný: samostatnou stránku vyvolá tlačítko v
levém panelu a stejné autorizované endpointy vedou preview, plán a potvrzení na
webu i desktopu.
Web smí zadat jen server-local cestu a nepovoluje `local-only`; desktopový Qt
shell vydá rendereru pouze náhodnou in-process capability pro jeden pickerem
vybraný archiv a volitelný přesný cíl. Původní `NotebookLMImportDialog` a jeho
toolbar vstup byly odstraněny. Autoritou zůstává `ProjectCreation` journal dle
ADR 0029; HTTP adaptér nepřidává writer ani persistentní vrstvu.

Zbývající vytvoření dokumentu/TODO není desktop-only z principu a jeho Qt
dialog se nemá dále rozšiřovat jako paralelní UI. Úplné převedení vyžaduje
společné autorizované HTTP workflow a recovery kontrakt.

## Ověřovací kontrakt

- `WEB_HTML == HTML` a `WEB_CSS == CSS`.
- Desktop management servíruje stejný `HTML` a `CSS` bez `.replace(...)`.
- Webový JavaScript obsahuje explicitní serverový bootstrap a poté celý
  společný aplikační JavaScript.
- Desktopový bootstrap pouze odemyká deklarované lokální capability.
- Reálný Qt/WebEngine smoke a živé nasazení na Turris zůstávají samostatnou
  platformní akceptací.
