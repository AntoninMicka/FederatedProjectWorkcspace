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

Následující existující Qt dialogy nejsou desktop-only z principu a nesmějí být
dále rozšiřovány jako paralelní UI: vytvoření projektu, import NotebookLM a
zbývající vytvoření dokumentu/TODO. Jejich backendové
služby zůstávají znovupoužitelné. V této dávce byl sjednocen shell, import
zdroje a historie; úplné převedení zbývajících starších desktopových vstupů na
společné autorizované HTTP workflow vyžaduje samostatné mutující API a recovery
kontrakt a není vydáváno za dokončené.

## Ověřovací kontrakt

- `WEB_HTML == HTML` a `WEB_CSS == CSS`.
- Desktop management servíruje stejný `HTML` a `CSS` bez `.replace(...)`.
- Webový JavaScript obsahuje explicitní serverový bootstrap a poté celý
  společný aplikační JavaScript.
- Desktopový bootstrap pouze odemyká deklarované lokální capability.
- Reálný Qt/WebEngine smoke a živé nasazení na Turris zůstávají samostatnou
  platformní akceptací.
