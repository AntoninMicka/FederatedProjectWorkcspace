<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# X/Twitter — připravená implementace PoC, neověřeno

MON-08-11, 16. 11. 2026. Uživatel výslovně vyžádal implementaci **bez
testování**. Nebyly spuštěny testy, aplikace, API smoke, placený request ani
aktivace. Není to PoC validated ani připravenost pro produkci. Implementace
je oddělená ve větvi `feature/x-twitter-poc`, závislé na zdrojovém základu
`d7254be`; lokální develop tento kontrakt konektorů ještě neobsahoval.
Před PR je nutné začlenit závislost a samostatně dohodnout ověření.

## Rozhraní podle veřejné dokumentace

- Účet podle číselného ID: `GET https://api.x.com/2/users/{id}/tweets`.
  Neprovádí se účtované dohledávání uživatelského jména.
- Recent search: `GET https://api.x.com/2/tweets/search/recent`, dotaz do
  512 znaků, bez přepnutí na full archive.
- Parametry `post.fields=created_at,edit_controls,withheld`, stránkování
  přes `pagination_token` pro účet a `next_token` pro recent search.
  Žádné expansions uživatelů, metrik ani automatické dodatečné requesty.
- Nejvýše 10–100 položek na stránku a 1–5 stránek. První explicitní okno
  má 1–167 hodin; další čtení používá uložený `since_id`. Pevný konec okna
  je 30 sekund před zahájením, aby se stránky vztahovaly ke stejnému výběru.
  Překročený stránkovací limit je neúplný read, nikoliv kompletní období.
- Kurzory starší než sedm dnů nejsou tiše použity pro neúplný recent search.
  PoC vyžaduje nové explicitní odběrové okno; historii nedotahuje scrapingem.
- Oficiální cena post read byla při kontrole 16. 11. 2026 0,005 USD/resource.
  Výchozí sazba je 5000 mikroUSD, uživatel ověřuje sazbu v konzoli před
  povolením. Místní rozpočet je rezervace podle zadané sazby, nikoliv důkaz
  skutečného účtu nebo zůstatku kreditů. Nastavte i limit u poskytovatele.

Odkazy: [pricing](https://docs.x.com/x-api/getting-started/pricing),
[recent search](https://docs.x.com/x-api/posts/search-recent-posts),
[user posts](https://docs.x.com/x-api/users/get-posts).
Přístup konkrétního účtu, tokenu a placeného plánu nebyl zkoušen.
Správa seznamů přímo na X, stream, OAuth přihlášení/refresh a compliance
API nejsou součástí tohoto read-only řezu. Odběry zde znamenají místní
seznam vybraných účtů a dotazů; žádný follow/list write na platformě.

## UI a použití po následném ověření

1. Ve **Zdroje → X/Twitter** správce zadá bearer token, měsíční místní
   limit, sazbu, datum kontroly ceníku a maximální rozsah readu. Uložení
   nevolá X API. Token se ve statusu nikdy nevrací.
2. Přidá místní odběr: název, účet/dotaz, počáteční okno, retence 1–30 dnů,
   posouzené podmínky licence a odstraňování. Odběr i placené čtení musejí
   být povoleny místně. Jsou vypnuté, dokud to správce neudělá výslovně.
3. V projektu vytvoří zdroj typu **X/Twitter**, vybere odběr podle názvu,
   připojí levný filtr a cílový pool. Do Git definice jde pouze místní UUID
   odběru a otisk účtu/dotazu, okna, retence a podmínek; ne token.
4. V detailu zdroje použije **Načíst X do poolů — placené**. Před readem
   vidí přesný zdroj a horní rezervaci ceny. Zdroj bez filtru/poolu se
   nenačte. Existující RSS aktivace se na X nepřenese a RSS worker X
   výslovně přeskočí. Placený read nemá automatický rozvrh ani retry.
5. **Dokončit původní načtení X** používá stejné operation ID a může pouze
   dokončit staging/import stejného pokusu. Nejistý HTTP efekt neopakuje.
   Správce může ponechat unresolved požadavek jako unknown, bez vrácení
   rezervace. Nové placené čtení vyžaduje nový výslovný požadavek.

Změna významu odběru změní jeho otisk. Projektový zdroj se musí výslovně
aktualizovat; na jiném uzlu nelze pod stejným UUID nenápadně použít jiný
účet či dotaz. Místní token, rozpočet, kurzory ani odběry se nesynchronizují.
Sdílení obsahu poolů nadále podléhá původní privacy a retenci projektu.

## Persistence a crash boundaries

Reuse/adapt: společný SourceConnector/SourceContext, `fpw-source-item-v1`,
levný filter engine, immutable pool entries, existující pool transakce,
node-private vlastnictví souborů, fsync a SQLite ownership wrapper.
Nezavádí se druhá **projektová synchronizační** databáze. Místní X SQLite
je účtovací/effect journal a konfigurace; nesmí se kopírovat mezi uzly ani
považovat za obnovitelný projektový index. Token je oddělený mode-0600 soubor
v owned mode-0700 adresáři, nikoliv šifrovaný credential vault.

- Nový credential soubor se fsyncne před transakčním odkazem z konfigurace.
  Pád před odkazem zanechá nepoužitý soubor; nezmění původní konfiguraci.
  Po commitu existuje odkazovaný soubor. Staré tokenové sloty se automaticky
  nemažou; rotaci a odstranění nepotřebných slotů provádí správce místně.
- Před HTTP se uloží původní intent a rezervace maxima `počet × stránky ×
  sazba`. Prepared/dispatching/unknown má trvalé operation ID. Po pádu
  nelze stejný HTTP request automaticky znovu poslat. Rezervace zůstává
  konzervativně započtená i při chybě nebo menším výsledku.
- Po úplném readu se normalizovaný batch uloží do dočasného stagingu,
  nejdéle jeden den a nikdy déle než retence odběru. Jeho HTTP obsah ani
  provider error body se nelogují; neukládá se raw response ani token.
- Pool a potvrzení místního intake se ukládají jednou původní FULL
  transakcí. Pád před ní umožní dokončit stejný staging bez placeného
  replay; po ní lze vrátit původní receipt. Kurzoru se postup potvrdí až
  po commitu poolu samostatným idempotentním acknowledge. Nezávislá Git
  změna mimo daný source/filter/pool import neblokuje; změna jeho metodiky
  vyžaduje explicitní posouzení stagingu.
- Staging se po TTL maže přes secure-delete transakci při běžící údržbě
  monitoringu a přístupu ke službě. Bez běžícího backendu není časový purge
  garantován; provozní snapshoty, zálohy a médium tímto nejsou mazány.
  Budget/journal zůstává bez textů. Neomezený růst je odmítnut při 10 000
  operacích; jejich bezpečné archivování je následný provozní krok.

Normalizace ponechává neznámé datum/autor/title jako null a nevydává signál
za ověřený fakt. Kořenem identity je první ID dostupné edit history; aktuální
ID a známé aliasy jsou pouze provenance. Kanonická URL používá kořen, takže
oprava zůstává obsahovou revizí stejné položky. Pokud historie v odpovědi
chybí, její kontinuita se nevymýšlí. Chybějící položka na stránce není smazání.
Withheld nebo částečná errors odpověď odmítne celý read jako nedostupný či
neúplný; není to úspěšný nulový nález a nespouští se fallback.

## Smazání a hranice PoC

Správce může podle známého post ID odstranit surové místní staging/pool
kopie. Nejdřív se uloží místní tombstone; pak se idempotentně odstraní texty.
Pád mezi těmito kroky dokončí následující údržba. Známé aliasy se zablokují
pro další místní import včetně příjmu původního signed sidecaru. Nejde o nový
federovaný compliance protokol: ostatní uzly vyžadují stejný provozní zásah.
Zveřejněné odvozené zprávy a Git historie se automaticky nepřepisují.
Před reálnou aktivací je nutné přijmout tyto konkrétní hranice retence/licence;
PoC neprokazuje úplné odstranění obsahu ve všech spravovaných kopiích.

## Stav ověření

Podle výslovného pokynu uživatele nebyly spuštěny unit/integration/browser
ani živé API testy. Statická kontrola diffu nenahrazuje runtime ověření.
MON-08-11 zůstává otevřený; bez ověření účtu, budgetu, chybových a recovery
cest nelze výsledek označit jako PoC validated nebo doporučit PR.
