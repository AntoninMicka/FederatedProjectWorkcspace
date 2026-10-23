<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# TODO — F-M5-PROJECT-CATALOG-01: federovaný katalog existence projektů

Původ: uživatelský požadavek 23. 10. 2026 zahájit přenosy úzkou první fází,
která přenáší pouze existenci projektů; navazuje na F-M5-PERSONAL-SYNC-01-UI4,
ADR 0037 a ADR 0040. Cílová úroveň: **implemented**. Větev:
`feature/f-m5-project-catalog-01`, základ `develop` na merge commitu `61df652`
(PR #79), cíl PR: `develop`.

Dávka přenese mezi schválenými peery pouze UUID a název projektu. Na příjmu
vznikne node-local projekce vzdáleného katalogu, nikoli lokální projekt,
registrace v `node.json`, Git repozitář, větev, obsah, historie, popis, ACL ani
oprávnění. `same-team` oznamuje všechny dostupné lokální projekty,
`same-company` a `external` pouze projekty povolené maticí. Interní úrovně se
synchronizují automaticky, `external` pouze výslovnou akcí uživatele.

## Úkoly dávky

- [x] [completed] **F-M5-PROJECT-CATALOG-01-A — předání sloučené předchozí
  dávky a kontrakt katalogu (cílová úroveň: designed).** Předchozí větev byla
  již sloučena uživatelem, proto je její administrativní uzavření výjimečně
  prvním krokem této nové dávky. Evidence implementace byla přesunuta do
  WORK_LOG, nedokončená fyzická akceptace do BACKLOG a TODO nyní drží jedinou
  aktivní feature. ADR 0041 vymezuje minimální payload, autoritu matice,
  podepsanou výměnu, persistentní hranice a zákaz vytvořit lokální projekt.
  Reuse: adaptují se `Administration`, `Projects`, připnutá Ed25519 identita,
  peer CA a HTTPS vzor replikace; Git bundle, projektový Workspace/Journal,
  SSH přenos a externí knihovna byly odmítnuty jako zbytečné pro katalog.
- [x] [completed] **F-M5-PROJECT-CATALOG-01-B — podepsaná obousměrná výměna
  katalogu (cílová úroveň: implemented).** Jeden bounded HTTPS request posílá
  katalog volajícího a vrací podepsaný katalog protistrany. Obě strany znovu
  ověřují schválený peer, připnutý fingerprint, source/recipient Node UUID a
  aktuální sharing policy. Payload má nejvýše 256 položek a každá obsahuje jen
  `id` a `title`. Browser token, Origin a nepřesný Host se na node endpointu
  odmítají.
- [x] [completed] **F-M5-PROJECT-CATALOG-01-C — durable projekce a recovery
  (cílová úroveň: implemented).** Node-local `federation-catalog.sqlite`
  přiděluje odchozímu obsahu monotónní revizi a atomicky drží poslední katalog
  každého peeru. Stejná revize s jiným obsahem selže, starší opožděná revize se
  ignoruje a novější jednou nahradí projekci. Pád před SQLite commitem nezmění
  stav; po commitu lze ztracenou odpověď bezpečně zopakovat. Projektový Git,
  `node.json` ani obnovitelný projektový index nejsou zapisovány.
- [x] [completed] **F-M5-PROJECT-CATALOG-01-D — automatika a sdílené UI
  (cílová úroveň: implemented).** Desktop i server spouštějí katalogový
  scheduler po 60 sekundách pro dosažitelné `same-team` a `same-company` peery.
  Dynamický serverový záznam klienta odpoví katalogem při spojení desktopu.
  `external` scheduler vynechá a přenos spouští pouze tlačítko. Stránka Sdílení
  projektů ukazuje pravdivý stav katalogu a vzdálené záznamy odděleně od
  místních projektů.
- [ ] [in progress] **F-M5-PROJECT-CATALOG-01-E — úplné a fyzické ověření
  (cílová úroveň: implemented).** Cílených 5 testů ověřuje obousměrnou výměnu,
  filtr `same-company`/`external`, revokaci, zákaz automatického external toku,
  monotónní projekci, absenci lokální registrace a bounded endpoint bez browser
  credentialu. Změněné Python moduly prošly `py_compile` a oba generované
  JavaScripty `node --check`. Širší administrační/webová/desktopová sada:
  **88 testů úspěšně, 6 přeskočeno**. Úplná sada:
  **728 testů úspěšně, 28 přeskočeno**. Zbývá fyzicky potvrdit desktop ↔ LXC
  katalog na skutečných projektech; žádný deploy ani fyzický přenos zatím
  nebyl v této větvi proveden.

## K předání do backlogu

- [ ] [planned] **F-M5-SHARING-SYNC-01 — obousměrná synchronizace obsahu pro
  same-team a same-company.** Nad ověřeným katalogem přidat přenos povolených
  větví a historie, divergence-safe příjem a offline recovery. Existence v
  katalogu sama nikdy neuděluje právo obsah stáhnout nebo otevřít.
- [ ] [planned] **F-M5-EXTERNAL-EXPORT-01 — externí datový balíček a styčný
  uživatel.** Ruční oznámení existence projektu není datový export. Datový
  balíček bez vlastní historie, volitelné patche exportní větve, styčný
  uživatel a přímý/souborový kanál zůstávají samostatnou feature.

## Akceptační podmínky

- příjem obsahuje pouze UUID a název projektů povolených úrovní a maticí;
- přijatá existence nevytvoří lokální projekt, Git, členství ani oprávnění;
- identity, podpis, TLS pin, přesní účastníci a aktuální trust se ověřují na
  obou stranách a revokovaný nebo `unspecified` peer nic nepřenese;
- retry, ztracená odpověď a opožděný snapshot nevrátí projekci ke staršímu
  obsahu ani nevytvoří duplicitu;
- `same-team` a `same-company` se obnovují automaticky, `external` pouze na
  výslovný pokyn;
- cílené i úplné testy projdou a fyzický desktop ↔ LXC scénář zobrazí vzdálené
  projekty bez vytvoření jejich lokálních repozitářů.
