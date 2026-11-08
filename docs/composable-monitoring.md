<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Sledování ze samostatných bloků

V projektu otevřete **Nástroje → Sledování a zprávy**. Nová hlavní část má
šest samostatných přehledů. Starší definice a jejich historie zůstávají
v rozbalovací části **Starší sledování a dvoufázový editor**. Nové bloky
starý sběr automaticky nepřevádějí ani nezastavují. Pro tentýž kanál proto
před zapnutím nového příjmu pozastavte původní odběr na dotčeném uzlu.

| Přehled | Obsah |
| --- | --- |
| Zdroje | RSS/Atom URL, interval, přístupové a retenční podmínky; také uložené dotazy webového hledání na vyžádání. |
| Filtry | Výběr více kanálů, pravidla a cílový pool. Více filtrů může přispívat do stejného poolu. |
| Pooly zpráv | Počet zpráv, jejich obsahové verze, pozorující uzly, důvody výběru a poslední potvrzený příjem synchronizace. |
| Zpracování zpráv | Více vstupních poolů, volitelná webová hledání, zadání, způsob a místní či konkrétní vzdálený uzel. |
| Komplexní úlohy | Sestava sdílených bloků; výběr existujících, vytvoření nových přímo z editoru a návrh pomocí LLM. |
| Výsledky a běhy | Návrhy a vydané zprávy, běhy celé úlohy i jednotlivých zpracování, chyby a unknown příjem. |

U každého bloku je klikací využití. U úlohy se započítají i nepřímé vazby,
například kanál filtru, který plní zvolený pool. Sdílená definice se při
připojení nekopíruje. Historický běh zachová připnutou definici i vstupy;
pozdější změna společného bloku jej nepřepisuje.

## Doporučený postup

1. Založte pool a RSS kanály; u kanálu vyplňte podmínky přístupu a uchování.
2. Vytvořte filtr, vyberte kanály a cílový pool. Jednoduchý editor nabízí
   výrazy a regex; bez nich přijímá všechny položky po deduplikaci. Pokročilé
   existující postupy zachová přesně, jejich kroky tímto stručným editorem
   nepřepisuje. Konektory a izolovaný regex mají původní bezpečnostní limity.
3. Založte zpracování nad jedním či více pooly. Pro hledání nejdřív přidejte
   zdroj typu Webové hledání a následně jej vyberte ve zpracování.
4. V komplexní úloze vyberte existující bloky nebo použijte **Vytvořit nové**.
   Po uložení nového bloku se vrátíte do rozpracované sestavy. Závislosti
   se dohledávají přes jejich ID; úprava společného filtru nevyžaduje ručně
   přepisovat seznam kanálů všech navazujících úloh.
5. Sběr zapněte na každém zapojeném uzlu. Neexistuje výhradní těžař ani
   volba RSS leadera. Místní souhlas se váže na revize zdroje, filtrů a poolů;
   po jejich změně je potřeba potvrdit aktuální konfiguraci znovu.
6. Spusťte zpracování nebo celou úlohu. Běh úlohy připraví návrhy svých
   místních zpracování; u jiného uzlu ukáže waiting-executor. Nový vzdálený
   dispatch protokol se tím nezavádí. Jednotlivé návrhy můžete posoudit a vydat.

RSS má vlastní interval a nevolá LLM. Zpracování může běžet ručně nebo
jednou denně ve zvoleném místním čase a časové zóně. Denní slot má stabilní
identitu; restart jej nespustí podruhé. Po výpadku se provede nejvýše aktuální
splatný slot, nevyrábí se zpětně řada zmeškaných vydání. Webové hledání nemá vlastní periodický sběr; spouští se až jako vstup
konkrétního sestavení zprávy, případně také při aktivovaném denním zpracování.
Uložení rozvrhu jej neaktivuje; aktivace zpracování je samostatná místní akce.

## Sestavení pomocí LLM

**Sestavit pomocí LLM** předá nastavenému modelu popis, katalog a uzavřený
kontrakt bloků. Používá existující Ollama binding a backend run journal;
bez nastaveného dostupného modelu nevytváří náhradní předstíraný výsledek.
ContextBuilder před dispatch kontroluje privacy; local-only katalog nesmí
odejít ani na private-network model. Model nedostává credentials.

Návrh rozlišuje nové či upravené bloky a použití existujících. Jednotlivé
bloky lze upravit formulářem. **Uložit posouzenou sestavu** používá jedinou
Reporting/Workspace transakci. Nic neaktivuje ani nevydává. Změněný HEAD,
neexistující reference, chybný typ vazby nebo snížení privacy se odmítnou.

## Pooly a federace

Definice jsou neměnné Reporting revize v Gitu. Obsah poolů, členství,
pozorování a rozpracované nové běhy jsou v samostatném `message-pools/pools.sqlite`
pod privátním reporting runtime adresářem uzlu. Jde o autoritativní data,
nikoli rebuildovatelný projektový index. Chybějící nebo cizí DB se nesmí
nahradit prázdnou kolekcí. Databáze se mezi uzly nekopíruje.

Původní podepsaná synchronizace projektu přenáší pooly jako logický sidecar
exchange verze 3. Je podporován úplný **same-team / all** projektový scope.
Vybrané větve same-company pooly nepřenášejí. Oba uzly musí mít tuto verzi
implementace; starší příjemce nový formát odmítne. Původní přenos bez poolů
zůstává exchange v2. Při nevyřešené divergenci projektových definic zůstane
pool přenos čekat na vyřešení Git konfliktu. Příjem nemění lokální granty
ani rozpracované běhy.

Stejná položka z více uzlů má jednu obsahovou revizi a více pozorování.
Stejné URL v poolu seskupuje příspěvky více filtrů; rozdílné obsahy se
zachovávají jako verze bez odhadu, která je nejnovější. GUI je označí jako
více obsahových verzí. Zpracování položku ostatním spotřebitelům neodebere.
Přenesené členství musí odpovídat skutečnému filtru, jeho revizi a poolu.
Local-only členství ani obsah se neexportují.

Jeden sidecar je omezen na 8 MiB a 20 000 záznamů. Při překročení přenos
viditelně selže; stránkování zatím není implementováno. Kolekce po dobu
své retence poskytuje vstupy zpráv, jejich časované expirace se po startu
uklidí před čtením či přenosem. Nevybrané texty se do této DB ani Gitu
neukládají. Jde o retenci kolekce, nikoli garanci odstranění vydaných zpráv,
modelových auditů, dokončených sync payloadů v původním transportním journalu,
cizích záloh či historických raw feedů původního monitoringu. Nová publikace
ukládá text posouzené zprávy a audit referencí/hashů, nikoli celý pool.

## Obnova a ověření

Crash boundaries a reuse popisuje [ADR 0082](adr/0082-composable-monitoring-and-message-pools.md).
Známá přechodná chyba zdroje zůstává chybou a další kontrola respektuje
interval i Retry-After/backoff. Přerušený HTTP dispatch je unknown a blokuje další automatický GET stejného
kanálu. Po posouzení lze příjem uzavřít jako opuštěný a povolit další
kontrolu. Tím se původní neznámý výsledek nemění na úspěch. Příjemce sloučí
pool transakčně a opakování stejného přenosu nevytvoří duplicity. U modelu
unknown znamená samostatné posouzení, nikoli automatický nový pokus.

Testy používají izolované projekty, syntetické feedy, řízené hodiny a
modelové transporty. Neprokazují fyzické nasazení na Omnii, dostupnost
skutečných RSS kanálů ani lidskou akceptaci MON-08-12.

Ověření finálního zdrojového stavu:

- `python3 -m unittest discover -s tests -v`: 1 805 testů, OK, 54 přeskočeno.
- Samostatný běh s `M0_DESKTOP_TEST=1`: 3 skutečné Qt/WebEngine scénáře OK
  (nové katalogy a inline sestava, původní editor, review/publish/presenter).
- Izolované HTTPS/RBAC scénáře jsou také součástí plné sady.
- Sdílený monitoring JavaScript prošel `node --check`; odkazy v dotčených
  návodech a whitespace celého diffu včetně nových souborů jsou zkontrolované.

Výsledky nejsou ruční akceptací běžného profilu ani nasazením na Omnii.
