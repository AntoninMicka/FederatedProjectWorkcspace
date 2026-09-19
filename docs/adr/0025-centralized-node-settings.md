<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# ADR 0025 — Centralizovaná nastavení uzlu

Datum: 2026-09-19. Stav: přijato jako designed pro F-UX-SETTINGS-01.

## Kontext a rozhodnutí

Ollama binding se dnes edituje přímo v projektovém chatu, ačkoliv platí pro celý
uzel a používají jej také souhrny, extrakce a návrhy metadat. S přibývajícími
schopnostmi by další lokální formuláře směšovaly pracovní kontext s konfigurací.

Desktop proto dostane samostatnou stránku **Nastavení**, dostupnou z globální
navigace i bez otevřeného projektu. První sekce „Lokální AI backend“ obsahuje
jediný editační formulář současného Ollama bindingu. Chat zobrazuje pouze stav
backendu a odkaz do této sekce. Přechod do nastavení si v paměti stránky uchová
návratový kontext; návrat obnoví seznam projektů nebo otevřený projekt a jeho
aktivní panel, ale neobchází nové načtení stavů ze serveru.

Stejná stránka obsahuje vstup do existující správy uživatelů a federace.
Samotný administrační dialog, `/v1/administration`, role a potvrzovací workflow
se nemění; odstraňuje se pouze samostatné plovoucí tlačítko mimo informační
architekturu. Desktop používá svůj dosavadní lokální federation-admin kontrakt,
zatímco web sekci zobrazí pouze přihlášenému `node-admin` nebo
`federation-admin`. Skrytí vstupu nenahrazuje serverovou autorizaci.

Nastavení je vlastnost uzlu, nikoli projektu. Nezapisuje se do projektového Gitu,
nejde do projektového indexu ani federace a nesmí být vydáváno za projektové
oprávnění. Credentials, privátní klíče a budoucí tajemství zůstávají mimo tento
formulář a vyžadují vlastní credential lifecycle; stránka je nebude vracet do
DOM. Projektová nastavení případně dostanou oddělenou, výslovně označenou sekci.

## Uložení a chyby

UI dál volá autentizované same-origin `/v1/chat/status` a
`/v1/chat/configure`. Server zůstává autoritou validace `OllamaBinding` a
`OllamaBindings.save` jedinou autoritou atomického node-local zápisu. Nevalidní
požadavek, chyba zápisu nebo ztracená odpověď nesmí změnit hodnoty zobrazené jako
potvrzené; UI znovu načte serverový stav nebo jasně ponechá výsledek jako
nepotvrzený. Žádný Git/Workspace journal nevzniká, protože projektová data se
nemění.

`same-node` nadále znamená číselný loopback HTTP endpoint. `private-network`
nadále vyžaduje číselnou privátní HTTPS adresu, stabilní ID cíle a SHA-256 pin
certifikátu. Přesun formuláře nemění privacy autorizaci, nezavádí discovery,
fallback ani automatické testovací volání backendu.

## Reuse a hranice první verze

Adaptují se stávající DOM navigace a bezpečné `textContent` vykreslení,
`ChatService`, `OllamaBinding` a `OllamaBindings`; nepřidává se router, knihovna
komponent ani nová persistence. První verze pouze přesune existující binding a
připraví strukturu pro další uzlová nastavení. Existující uživatelská a
federační správa se pouze zpřístupní ze stejné stránky; její storage a recovery
se nemění. Dávka neřeší nový credential lifecycle, synchronizaci, více backendů,
routerový autostart ani projektové nastavení.

Akceptace vyžaduje přístup bez projektu i z otevřeného projektu, právě jeden
formulář, zachování hodnot po navigaci/restartu, odmítnutí neplatných hranic a
endpointů bez ztráty posledního platného bindingu a bezpečné zobrazení chyby.
Skutečný Ollama běh není nutný k ověření přesunu nastavení.
