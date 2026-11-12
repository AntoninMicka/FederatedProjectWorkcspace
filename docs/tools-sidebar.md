<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->

# Nástroje: společný strom a položková menu

Levá lišta používá řádky a menu **⋮** ze stejného vzoru jako Podklady a Zdroje.
Jediný strom má rozbalitelné kategorie: Julia modely a výpočty, zdroje pro těžbu,
filtry, pooly, zpracování a komplexní úlohy. Výběr vpravo otevře vlastní
obrazovku položky; její menu otevře příslušný samostatný editor. Komplexní
úloha otevře [agregát tabulek](monitoring-entity-workspaces.md), bez vlastního
editoru bloku. Julia modely
zachovávají náhled, editaci, přípravu běhu a nativní smazání s potvrzením.
Starší formuláře a migrační panel byly z aktuálního GUI odstraněny;
historie a explicitní servisní/recovery API zůstávají zachované.

Ikona **Nový nástroj** otevírá společné menu: nový Julia model, zdroj pro těžbu,
filtr, pool, zpracování, komplexní úloha a sestavení pomocí LLM.
Duplicitní obecná tlačítka založení v pravé části jsou odstraněna. Inline založení
závislosti uvnitř rozpracované sestavy zůstává zachováno. Import Julia souboru
zůstává pod vedlejší importní ikonou. Esc zavře nové menu a vrátí fokus na ikonu.

Smazání aktuálních bloků vyžaduje potvrzení. Menu vysvětlí blokaci při využití
nebo přerušeném převodu; backend stejná pravidla kontroluje nezávisle na UI.
Nevzniká automatický retry, nové spuštění, souhlas s modelem ani změna placementu.
Režim jen pro čtení a ochrana konceptů používají původní guardy.

Definice odstraněných bloků zůstávají v historii, dřívější běhy a výstupy se
neztrácejí. Podrobnosti, kompatibilita uzlů a crash recovery:
[ADR 0082](adr/0082-composable-monitoring-and-message-pools.md#odstranění-definice-z-aktuálního-katalogu--11-11-2026).
Všechny uzly musí před přenosem smazané definice podporovat nový marker.

Historická evidence před odstraněním starších formulářů: ověření zahrnuje
Node testy leave/project/permission guardů, nativní zablokované
smazání, stale revizi a recovery, skutečný podepsaný přenos i HTTP/RBAC. Čtyři
skutečné Qt průchody ověřily strom/menu, vytvoření všech nových typů, editaci,
smazání úlohy a filtru, zakázané smazání používaného poolu, starší formuláře a
Julia editor s ochranou konceptu. Další Qt kroky smazaly oba stupně staršího
zadání i původní sledování a ověřily zachovanou vydanou zprávu a prezentaci. Plná sada ani živé nasazení nebyly provedeny.

Finální cílené ověření tohoto řezu: 60 backendových/integracních testů,
11 dalších testů (včetně obou přerušení po ref update; 1 volitelný skip)
a 4 skutečné Qt scénáře prošly. Celkem 75 testů, 1 skip. Doplněná stale-head
aserce prošla i samostatně. `node --check` a `git diff --check` prošly. Změny
zůstávají lokální, bez source commitu, restartu služby nebo vzdáleného nasazení.

## Menu mimo rámeček seznamu

Položková menu sdílejí společné zobrazení také s Podklady, Zdroji, nastavením
a ostatními seznamy. Posuvný seznam menu neořezává. Otevřené je vždy jen jedno;
poloha se přizpůsobí okrajům okna a dlouhé menu může mít vlastní posuvník.
Esc vrátí fokus na spouštěč, šipky přecházejí mezi dostupnými akcemi. Kliknutí
mimo menu, posun seznamu, resize nebo odstranění řádku menu zavřou.

Zobrazení používá [Popover API a horní vrstvu HTML](https://html.spec.whatwg.org/multipage/popover.html).
Starší prohlížeč bez API použije dočasné přesunutí původního obsahu do těla
stránky a vrácení před obsluhou akce; listenery a vlastníci položek se nemění.
Nový Qt test ověřuje hit-test všech akcí přes hranici posuvného/transformovaného
kontejneru v obou větvích, rohy viewportu, klávesnici, jedinou otevřenou nabídku,
statické akce i úklid po odstranění řádku. Čtyři další skutečné Qt scénáře
ověřily původní akce v Nástrojích, starších sledováních a RSS čtečce. Všech
pět průchodů prošlo; `node --check` a `git diff --check` prošly. Plná sada pro
tuto lokální vizuální opravu nebyla opakována.

## Výstupy

Stejný seznam s položkovými menu používají také
[konkrétní vydání zpráv](report-outputs.md). Výběr vydání otevírá jeho text;
nepřepíná na zdrojovou úlohu ani obecný seznam běhů. Název obsahuje uložené
datum a čas sestavení.

Detail vydané zprávy nabízí [odvozenou prezentaci](report-output-presentations.md)
bez dalšího výzkumu, s přesným source pinem, zpětnými odkazy a viditelným
zastaráním po opravě zdroje. Vytvoření vyžaduje samostatné potvrzení.
