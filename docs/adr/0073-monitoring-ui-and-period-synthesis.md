<!-- SPDX-FileCopyrightText: 2026 Antonín Mička -->
<!-- SPDX-License-Identifier: MPL-2.0 -->
# ADR 0073 — Sledování ve Workspace a periodické zprávy

Datum: 2026-11-05. Stav: lokální implementace MON-05 k review.

## Rozsah a autorita

Základ implementace je `10e8a277ef37d469c012375baa0ff425ce6017f6`
(origin/develop po MON-04, PR #139), větev `feature/mon-05-monitoring-ui`.
Kanonický projekt `c898b941-8eb0-4406-8dad-6e2b96c06d59`, packet
`83395a0fdb33763c35bc8585f22b6000406cbd08f56eb824a3d9606130eb976f`,
export `abc844398141439cf98e8e3f942e19ae5831b1f9d2cf49b04ae20d7ff2548289`
(queue revision 219, stale=false) předává rozšířený MON-05. Mapování a devět
připnutých podkladů byly ověřeny. MON-06 a automatická lidská akceptace nejsou
součástí této změny. Autoritativní plán zůstává ve Workspace.

## Rozhodnutí a uživatelský tok

Nástroje → Sledování umožňují vytvořit, upravit, pozastavit a obnovit sledování,
zvolit podklady, schválené veřejné HTTPS zdroje, kalendářní období a samostatné
zadání reportu pro každé období. Výstupy → Zprávy obsahují návrhy i vydání
vedle existujících prezentací. Podrobný text je dostupný přímo a jako Markdown.
Týdenní přehled zdůrazňuje změny a opravy; měsíc význam a možné průlomy;
čtvrtletí trendy a benchmarky; rok vývoj, regrese, limity a rozpracované studie.
Delší zprávy vznikají z připnutých doménových podkladů, nikoli slepením kratších
reportů. Předchozí vydání stejného druhu a revize zadání je baseline.
Událost s datem za koncem periody se označí jako budoucí kontext; týdenní
výběr ji nevydává za novinku sledovaného období a její skóre není pokrokem.

Deterministický režim funguje bez LLM. Volitelný modelový režim používá přesně
schválený nastavený binding, roli summarizer a Context Manifest s konkrétním
výběrem podkladů. Chybějící model, změna cíle, neúplný výsledek a unknown nejsou
nahrazovány implicitním fallbackem. Výsledek nese assisted provenance, hash
manifestu a odpovědi. Samotné zdroje nikdy automaticky nevytvářejí potvrzené
události ani skóre. Bez doložené změny je to ve zprávě výslovně uvedeno.
Převod konkrétního doménového cíle a validace benchmarků patří MON-06.

Běžící desktop/HTTPS backend vlastní jeden periodický worker (tick každých
10 sekund); po restartu pokračuje přes původní journal. Není to systémový
časovač: při vypnuté aplikaci nepracuje, po startu dohání uzavřená období.
Nejstarší nevydaný report blokuje novější stejného druhu; různá období mají
samostatnou historii. Jeden tick prochází nejvýše 128 dosud nedokončených období; již vydaná
počáteční období přeskočí a zachová jejich původní receipts.
Vydání vyžaduje lidské potvrzení přesného digestu kandidáta. Odmítnutí a známé
chyby dovolují explicitní nový attempt původních vstupů; unknown vyžaduje
samostatné dohledání původního účinku, nikdy automatické opakování.

Oprava vydaného reportu připraví nový kandidát z aktuálních podkladů pro stejné
období a původní task revizi. Rezervace navazuje na konkrétní opravený snapshot;
jedna revize nemůže mít dvě konkurenční opravy. Oprava vyžaduje nové lidské
vydání. Původní zpráva i deck zůstávají neměnné a UI upozorňuje na novější
vydanou opravu. Změna zadání vyžaduje vlastní nové období/revizi sledování.

Volitelný návrh prezentace je skutečný dokument existujícího editoru/presenteru.
Vzniká z přesných bajtů vydané zprávy, reference a hash jsou v poznámkách slidů.
Má vlastní idempotentní receipt; nevydává se za nové schválení zprávy. Otevření
presenteru zůstává v desktopu. HTTP uživatel může dokument vytvořit a prohlížet.

## Uživatelský postup

1. Otevřete projekt a Nástroje → Sledování → Nové sledování. Vyplňte název,
   cíl, počátek a časovou zónu. Vyberte projektové podklady nebo veřejné HTTPS
   URL. Pro webové zdroje potvrďte konkrétní podmínky přístupu a uchování.
2. V Období a zadání reportů zapněte požadované periody a upravte jejich
   jednotlivá zadání. Vyberte pravidlový přehled nebo nastavený model; případně
   Zpráva + navázaný návrh prezentace. Uložení aktivuje schválenou konfiguraci.
3. Worker připravuje uzavřená období při běžícím backendu. Spustit nyní umožní
   vybrat poslední uzavřený týden/měsíc/čtvrtletí/rok. Datum začátku neurčuje
   otevřený neúplný report. Detail ukazuje poslední a příští periodu i stavy sběru.
4. Ve Výstupy → Zprávy otevřete návrh. Zkontrolujte celý text, zdroje,
   srovnávací vydání a omezení; teprve zaškrtnutí schválení zpřístupní Vydat
   zprávu. Export Markdown nevyžaduje vydání. Odmítnutý návrh nemění historii.
5. Navázanou prezentaci otevřete v desktopovém editoru. Tlačítko Zdrojová zpráva
   vede zpět k reportu. Vytvořit / otevřít prezentaci funguje i dodatečně.
   Připravit opravu z aktuálních podkladů vytváří další návrh, který znovu čeká
   na vydání. Starý report i deck zůstávají čitelné.

Po instalaci nových zdrojů je nutný nový start backendu; již otevřený proces
nepřebírá změny Python modulů. Není nutné ručně zadávat technická ID či JSON.
Při unknown běhu nejprve dohledávejte původní účinek podle zachovaného journalu;
UI jej nemění na úspěch ani nenabízí slepé opakování. Oprava konfigurace modelu
vyžaduje nový souhlas s přesným cílem. Známý neúspěšný report lze explicitně
opakovat jen při zachované původní revizi aktivního zadání.

## Soukromí a oprávnění

Deklarace `fpw-monitoring-watch-v1` je verzovaný projektový dokument. Sama
neopravňuje ke sběru ani dispatchi: node-local journal drží souhlas s přesným
hashem konfigurace. Import, replika nebo obecný editor artefaktu souhlas
nepřenášejí; změna hashe jej zneplatní. Souhlas se zapisuje až po dokončení
bootstrapu a opětovném ověření aktuální deklarace. Pause/resume zachovává task
revizi, ale má vlastní explicitní souhlas. Změna parametrů vytvoří task revizi.

Sledování nesmí snížit soukromí vybraných podkladů; dodatečné citované důkazy
se znovu kontrolují. Local-only nepovoluje webový sběr a ContextBuilder odmítá
přenos mimo stejný uzel. Síťové UI nevrací projekt s local-only artefakty.
Každý HTTP požadavek kontroluje autentizaci a členství; konfigurace, spuštění,
vydání a opakování navíc vyžadují node-admin a zapisovatelný projekt. Projektový
editor tak nemůže delegovat node-local credentials do běhu na pozadí.
Soukromé identity a credentials se do projektové deklarace nekopírují.

## Crash boundaries a recovery

Platí původní writer/recovery podle [ADR 0068](0068-manual-reporting-transactions.md),
collector podle [ADR 0069](0069-reporting-source-collector.md), model podle
[ADR 0071](0071-reporting-proposals-and-review.md) a run podle
[ADR 0072](0072-reporting-scheduler-and-run-recovery.md). Rozšíření:

1. Deklarace, pravidla, collector policy, škála a task vznikají přes původní
   Workspace.transact v deterministických samostatných operacích. Pád mezi
   kroky nedává souhlas k dispatchi; opakování původního save obnoví receipts.
   Neexistuje druhý writer ani transakce předstírající atomický vícekrokový save.
2. Souhlas je poslední zápis do privátního journalu. Pád po Git commitu před
   souhlasem ponechá viditelné neaktivované zadání. Změna deklarace při bootstrapu
   souhlas odmítne. Migrace owned journalu v1→v2 zachová běhy/cutoffs a přidá
   prázdné souhlasy v jediné SQLite transakci; neznámý owner/schéma selže.
3. Sběr má vlastní stabilní run/import IDs před zmrazením reporting intentu.
   Pád po síťovém účinku řeší collector journal; failed/unknown se automaticky
   neopakuje. Dokončený import se dohledá původním Workspace receiptem.
4. Reporting run poté zmrazí input_head, cutoff, baseline a task. Modelový
   attempt má vlastní BackendRuns; sanitizovaný manifest je samostatný Git
   artefakt po úspěchu. Pád mezi dispatchí a stage nepovoluje další dispatch:
   po expiraci lease je collecting unknown. Nový známý retry má nové attempt ID.
5. Stage ukládá úplné bajty kandidáta, publikace používá schválený digest a
   původní report operation ID. Pád před/po Git CAS řeší původní journal/receipt.
   Oprava má oddělenou rezervaci připnutého předchůdce a stejnou review bránu.
6. Prezentace je další samostatná operace. Její selhání nezneplatňuje již vydaný
   report. Opakované vytvoření dohledá receipt, nepřepíše ruční změny decku.
   Ukončení backendu nepovažuje nedoběhlý worker za čistý shutdown.

## Reuse a ověření

Reuse/adapt: ReportingScheduler, SourceCollector, ContextBuilder/OllamaAdapter,
Reporting/Workspace.transact, Projects/Artifacts, PresentationDocuments a sdílené
UI/RBAC. Druhý scheduler journal, writer, provider SDK a automatický publisher
by duplikovaly existující autoritu a byly odmítnuty. Veřejná i dostupná soukromá
inventura nepřinesly důvod přenášet externí kód.

Ověření pokrývá dvě období/restart, přesné review, idempotentní vydání/deck,
opravy bez přepisu, budoucí události pouze jako kontext, modelovou provenance, unknown bez retry, neúplnou odpověď
bez fallbacku, sběr bez potvrzení tvrzení, migraci journalu a HTTP RBAC.
Izolovaný WebEngine průchod ověřuje formulář → report → vydání → existující
editor prezentací. Výsledky běhů jsou uváděny odděleně od manuální akceptace
na skutečném profilu uživatele; tato ADR ji sama nedokládá.
