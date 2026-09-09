# IP, Defensive Publication & Crowdfunding Roadmap

## Začlenění do repozitáře — designed

Produktové milníky M0–M6 a jejich gates drží [master roadmapa](<../../Federovaný projektový LLM workspace – Master Checklist - základní roadmapa.md>), implementační práci [TODO](../../TODO.md). Aktuální M0 ani jeho pořadí tato podpůrná roadmapa nemění.

Podle [integračního pokynu](<ip integration instruction>) jsou provozními dokumenty tato dlouhodobá roadmapa, [Patent Risk Register](PATENT_RISK_REGISTER.md) a [Defensive Disclosures](DEFENSIVE_DISCLOSURES.md). Pokyn zůstává zachován jako zdroj. IP/FTO evidence patří do prvního registru, příprava a stav zveřejnění do druhého; crowdfundingové checklisty zůstávají zde.

Stav integrace k 2026-09-09: registry jsou založené, patentový watchlist je **neověřený** a disclosure ID jsou pouze rezervované náměty. Nebyla provedena patentová rešerše, claim analysis ani publikace, release či DOI. Založení registrů není důkaz FTO ani veřejného prior art. Nezaškrtnuté body níže jsou cíle/checklisty; dokončení vyžaduje uvedený důkaz. Operativní položky používají stavy a úrovně z TODO.

Vazby na vývoj:

| Událost | IP / publikační návaznost |
| --- | --- |
| Významná změna architektury, zejména M0 kontrakty | Screening podle sekce 3, záznam do patentového registru, posouzení disclosure; případná změna architektury vyžaduje doložené rozhodnutí/ADR. |
| Významný veřejný release kteréhokoli M | Review podle sekcí 6–11 a 30; propojit commit, tag, release, disclosure a případné DOI. |
| Příprava kampaně | Samostatný Gate C0, IP freeze ze sekce 20 a readiness ze sekce 31; neznamenají dokončení produktových gates. |

## Účel dokumentu

Tento dokument definuje podpůrnou roadmapu pro:

1. průběžné sledování patentových rizik a Freedom to Operate,
2. vytváření defensive prior art během vývoje,
3. archivaci veřejných technických milníků,
4. přípravu podkladů pro DOI publikace,
5. dohledatelné propojení Git historie, release, technické dokumentace a DOI,
6. přípravu crowdfundingové kampaně na financování dalšího vývoje.

Tato roadmapa není primární produktovou roadmapou. Má být napojena na hlavní vývoj pouze v místech, kde vzniká významná nová technická architektura, veřejný release nebo crowdfundingový milestone.

---

# 1. Základní IP strategie

## 1.1 Cíl

Primární cíl není vytvořit patentový monopol, ale:

- [ ] zachovat dlouhodobou **Freedom to Operate**,
- [ ] omezit riziko, že třetí strana později získá patent na řešení již veřejně používané projektem,
- [ ] vytvářet průkazný veřejný prior art,
- [ ] zachovat možnost design-around při nalezení relevantního patentu,
- [ ] zabránit nechtěnému převzetí patentového rizika přes externí komponenty nebo contributory,
- [ ] zachovat otevřený charakter produktu.

## 1.2 Základní princip

Každá významná technická inovace má projít rozhodnutím:

`implementovat → zveřejnit jako defensive prior art → případně nezveřejnit / konzultovat patentovou ochranu`

Výchozí strategie projektu:

`open source + defensive publication + průběžný FTO screening`

Vlastní patentová přihláška je výjimka, nikoli výchozí stav.

---

# 2. Patent Risk Register

Založeno (implemented — dokumentační registr): [PATENT_RISK_REGISTER.md](PATENT_RISK_REGISTER.md). Ověřené patentové rodiny se doplní po screeningu; počáteční watchlist není výsledkem rešerše.

## 2.1 Evidovaná pole

Pro každou relevantní patentovou rodinu evidovat:

- [ ] identifikátor patentu / přihlášky,
- [ ] název,
- [ ] vlastník / přihlašovatel,
- [ ] priority date,
- [ ] filing date,
- [ ] publication date,
- [ ] jurisdikce,
- [ ] family members,
- [ ] aktuální status:
  - [ ] pending,
  - [ ] granted,
  - [ ] expired,
  - [ ] abandoned,
  - [ ] unknown,
- [ ] relevantní nezávislé claims,
- [ ] komponenta projektu, které se mohou týkat,
- [ ] míra překryvu,
- [ ] aktuální design-around,
- [ ] rozhodnutí,
- [ ] poslední datum kontroly,
- [ ] datum příští kontroly.

## 2.2 Počáteční watchlist

Počáteční náměty jsou založené v registru jako PR-001 až PR-009. Níže zůstává otevřené jejich ověření:

- [ ] Airia — privacy / sensitivity / model routing,
- [ ] Cisco — RAG chunk filtering podle RBAC,
- [ ] AT&T — interoperable GenAI orchestration,
- [ ] Citibank — gateway / agent routing,
- [ ] Citibank — explainable model routing + audit,
- [ ] Microsoft EP4657277 — multi-LLM consent,
- [ ] Microsoft provenance PCT / případná EP fáze,
- [ ] AI provenance + version control,
- [ ] decentralizované agentní governance systémy.

---

# 3. FTO workflow během vývoje

## 3.1 Trigger pro FTO kontrolu

FTO screening provést vždy, pokud změna přidává nebo zásadně mění:

- [ ] LLM routing,
- [ ] automatický výběr modelu,
- [ ] privacy classification,
- [ ] RBAC nad LLM kontextem,
- [ ] RAG / embedding retrieval,
- [ ] federované vykonávání inference,
- [ ] Context Manifest,
- [ ] provenance,
- [ ] automatické předávání kontextu mezi LLM agenty,
- [ ] consent workflow,
- [ ] multi-agent orchestration,
- [ ] cryptographic binding výsledků,
- [ ] autonomní agentní plánování.

## 3.2 Vývojový postup

Před implementací významné funkce:

`feature proposal`

→ identifikace technických mechanismů

→ kontrola `PATENT_RISK_REGISTER.md`

→ rychlá patentová rešerše

→ rozhodnutí:

- [ ] bez relevantního konfliktu,
- [ ] nízké riziko,
- [ ] design-around,
- [ ] vyžaduje hlubší claim analysis,
- [ ] funkci odložit.

Teprve potom:

`implementation`

## 3.3 Design-around invariants

Pokud se nezmění po nové patentové rešerši, zachovat:

- [ ] **authorization before routing**,
- [ ] dostupnost backendu nesmí rozšiřovat povolenou trust boundary,
- [ ] privacy classification není dynamický permission score,
- [ ] explicitní reklasifikace dat,
- [ ] RBAC nad autoritativními artefakty před retrievalem,
- [ ] RAG/index není autoritou pro přístupová práva,
- [ ] LLM planner nenahrazuje deterministic application orchestrator,
- [ ] multi-role workflow pracuje přes explicitní artefakty a Context Manifest,
- [ ] provenance primárně na úrovni run / artifact / revision / manifest,
- [ ] absence backendu vede k fail-closed výsledku, nikoli k automatickému snížení security boundary.

---

# 4. Defensive Publication workflow

## 4.1 Co publikovat

Defensive disclosure má popisovat zejména:

- [ ] technický problém,
- [ ] architekturu,
- [ ] datové struktury,
- [ ] sekvenční diagramy,
- [ ] state machine,
- [ ] failure modes,
- [ ] bezpečnostní invariants,
- [ ] alternativní embodiments,
- [ ] příklady konfigurací,
- [ ] interoperabilitu,
- [ ] vztah jednotlivých komponent.

Disclosure nemá být pouze marketingový popis.

Musí být dostatečně konkrétní, aby odborník dokázal princip realizovat.

## 4.2 Co zachytit v každém disclosure

Minimální obsah:

- [ ] název,
- [ ] číslo/verze disclosure,
- [ ] datum,
- [ ] autoři,
- [ ] související Git commit,
- [ ] související release/tag,
- [ ] stav implementace,
- [ ] architektonický problém,
- [ ] technické řešení,
- [ ] hlavní komponenty,
- [ ] datové toky,
- [ ] algoritmus / state machine tam, kde je relevantní,
- [ ] alternativní varianty,
- [ ] bezpečnostní vlastnosti,
- [ ] failure/fallback scénáře,
- [ ] související veřejná dokumentace,
- [ ] známý prior art,
- [ ] známé patentové rizikové oblasti.

---

# 5. Defensive Disclosure Registry

Založeno (implemented — dokumentační registr): [DEFENSIVE_DISCLOSURES.md](DEFENSIVE_DISCLOSURES.md). Seznam námětů není hotový disclosure dokument.

Registry entry:

```yaml
id: DD-001
title:
status: draft | published | superseded
created:
published:
git_commit:
git_tag:
github_release:
doi:
related_architecture:
related_adrs:
related_patent_risks:
supersedes:
```

## 5.1 Doporučené první disclosures

- [ ] DD-001 — Core artifact-centric architecture
- [ ] DD-002 — Git authoritative state + rebuildable index + recoverable operation
- [ ] DD-003 — Context Manifest
- [ ] DD-004 — Execution boundaries and fail-closed backend selection
- [ ] DD-005 — Federated backend capability model
- [ ] DD-006 — Deterministic orchestrator + optional LLM orchestrator chat
- [ ] DD-007 — Multi-role artifact-based process isolation
- [ ] DD-008 — Bidirectional external client / Open WebUI integration
- [ ] DD-009 — Provenance and reproducible LLM execution
- [ ] DD-010 — Federation trust and offline operation

Disclosure lze slučovat, pokud samostatná publikace nedává technický smysl.

---

# 6. Git jako primární archivní osa

## 6.1 Main branch

Veřejně dostupná `main` větev je průběžným veřejným záznamem vývoje.

Pro významná disclosure však nestačí spoléhat pouze na pohyblivý stav `main`.

## 6.2 Immutable publication point

Ke každému významnému technickému zveřejnění vytvořit Git tag:

`defensive-disclosure-YYYY-MM-DD-NN`

nebo:

`dd-001-v1.0`

Tag odkazuje na konkrétní commit.

## 6.3 Checklist před tagem

- [ ] pracovní strom clean,
- [ ] testy úspěšné,
- [ ] disclosure dokument dokončen,
- [ ] architektura odpovídá implementaci,
- [ ] nejsou zveřejněny credentials/secrets,
- [ ] copyright/licence zkontrolována,
- [ ] third-party licence zkontrolovány,
- [ ] patent risk register aktualizován,
- [ ] relevantní ADR propojeny,
- [ ] disclosure registry aktualizováno,
- [ ] commit hash zaznamenán v disclosure.

---

# 7. Release workflow

Pro každý významný defensive-publication milestone:

`development`

→ dokumentace

→ FTO review

→ disclosure freeze

→ commit do `main`

→ Git tag

→ GitHub Release

→ DOI archival package

→ DOI publikace

→ zpětné propojení DOI do repozitáře

## 7.1 GitHub Release obsah

- [ ] release notes,
- [ ] odkaz na disclosure,
- [ ] commit hash,
- [ ] tag,
- [ ] seznam relevantních ADR,
- [ ] technické diagramy,
- [ ] případně source archive,
- [ ] případně PDF snapshot disclosure.

---

# 8. Průběžná příprava DOI podkladů

DOI se nemá vytvářet zpětně z chaotického stavu projektu.

Podklady se připravují průběžně během vývoje.

## 8.1 Metadata soubor

Vytvořit například:

`CITATION.cff`

a/nebo:

`.zenodo.json`

Podle zvoleného archivačního systému.

## 8.2 Průběžně evidovat

- [ ] název projektu,
- [ ] autoři,
- [ ] ORCID, pokud bude používán,
- [ ] licence,
- [ ] repository URL,
- [ ] popis projektu,
- [ ] keywords,
- [ ] verzi,
- [ ] release date,
- [ ] related identifiers,
- [ ] funding/crowdfunding acknowledgment,
- [ ] contributor credits.

## 8.3 Release metadata

Každý publikovatelný release musí mít:

- [ ] jednoznačnou verzi,
- [ ] Git tag,
- [ ] commit hash,
- [ ] datum,
- [ ] autora/maintainery,
- [ ] licenci,
- [ ] changelog,
- [ ] technický popis,
- [ ] disclosure ID,
- [ ] seznam souvisejících dokumentů.

---

# 9. DOI publication checklist

## 9.1 Před publikací

- [ ] GitHub release existuje.
- [ ] Release odpovídá konkrétnímu tagu.
- [ ] Tag odpovídá konkrétnímu commit SHA.
- [ ] Defensive Disclosure má finální verzi.
- [ ] Disclosure obsahuje release/tag/commit.
- [ ] Metadata autorů jsou správná.
- [ ] Licence je explicitní.
- [ ] Funding informace jsou aktuální.
- [ ] Citation metadata jsou aktuální.
- [ ] Patent Risk Register byl aktualizován.
- [ ] Dokument neobsahuje tajné informace.

## 9.2 Po publikaci DOI

- [ ] DOI uložit do disclosure.
- [ ] DOI uložit do `DEFENSIVE_DISCLOSURES.md`.
- [ ] DOI doplnit do release notes.
- [ ] DOI doplnit do README/CITATION podle relevance.
- [ ] DOI propojit se správným tagem.
- [ ] DOI uložit do changelogu.
- [ ] commitnout DOI metadata zpět do `main`.

---

# 10. Kontrola propojení Git ↔ Release ↔ DOI

Každý archivovaný technický milestone musí vytvořit uzavřený řetězec:

`Git commit`

↕  
`Git tag`

↕  
`GitHub Release`

↕  
`Defensive Disclosure`

↕  
`DOI`

↕  
`Patent Risk Register`

## 10.1 Integrity checklist

Musí být možné z libovolného bodu dohledat ostatní:

### Z Git commitu

- [ ] najdu tag,
- [ ] najdu release,
- [ ] najdu disclosure,
- [ ] najdu DOI.

### Z disclosure

- [ ] najdu commit,
- [ ] najdu tag,
- [ ] najdu release,
- [ ] najdu DOI,
- [ ] najdu relevantní ADR,
- [ ] najdu související patent risks.

### Z DOI

- [ ] najdu repository,
- [ ] najdu release,
- [ ] najdu přesnou verzi,
- [ ] najdu licence,
- [ ] najdu autory.

---

# 11. Cadence IP/archivační kontroly

## Při každém významném architektonickém rozhodnutí

- [ ] zhodnotit FTO dopad,
- [ ] aktualizovat Patent Risk Register,
- [ ] zvážit nový disclosure.

## Před každým významným release

- [ ] FTO review,
- [ ] disclosure review,
- [ ] DOI readiness review.

## Doporučená periodická kontrola

Například každé 3–6 měsíců:

- [ ] status watchlist patentů,
- [ ] nové EP/PCT family members,
- [ ] nově udělené claims,
- [ ] nové relevantní přihlášky,
- [ ] změny ve vlastní architektuře.

---

# 12. Open-source readiness

Před veřejným stabilním releasem:

- [x] Licence MPL-2.0 je uvedena v [LICENSE](../../LICENSE) a [CONTRIBUTING.md](../../CONTRIBUTING.md) — implemented, ověřeno čtením souborů.

Původní návrh posoudit Apache-2.0 není přijatou změnou licence; integrace zachovává existující MPL-2.0. Zbývající readiness kontroly:

- [ ] vytvořit `NOTICE`, pokud je potřeba,
- [ ] dependency licence review,
- [x] Základní contributor policy a `CONTRIBUTING.md` existují — implemented; příspěvky pod MPL-2.0, samostatná CLA nyní není vyžadována.
- [ ] Doplnit explicitní rozhodnutí o DCO; existence CONTRIBUTING není dokončený audit práv ke všem příspěvkům.
- [ ] security disclosure policy,
- [ ] copyright notices,
- [ ] třetí strany / assets audit.

---

# 13. Crowdfunding roadmap

## 13.1 Gate C0 — Produktová připravenost

Před přípravou kampaně musí existovat:

- [ ] funkční demonstrátor nebo velmi přesvědčivý PoC,
- [ ] veřejná roadmapa,
- [ ] technická architektura,
- [ ] jasný open-source model,
- [ ] licence nebo alespoň finální rozhodnutí o licenci,
- [ ] základní dokumentace,
- [ ] definovaný rozsah financovaného vývoje,
- [ ] realistický plán po skončení kampaně.

**Gate C0:** lze přesně vysvětlit, co již existuje a co bude crowdfunding financovat.

---

# 14. Crowdfunding – positioning

## 14.1 Definovat hlavní sdělení

- [ ] Jaký problém produkt řeší?
- [ ] Pro koho?
- [ ] Proč nestačí ChatGPT / NotebookLM / Open WebUI?
- [ ] Proč federovaný/open-source přístup?
- [ ] Jaká je výhoda artifact-centric architektury?
- [ ] Jak projekt chrání soukromá data?
- [ ] Jak funguje více nezávislých LLM rolí?
- [ ] Co může fungovat zcela lokálně?
- [ ] Co je cílem crowdfundingu?
- [ ] Co bude po kampani veřejné?

---

# 15. Crowdfunding – scope financování

Připravit přesný seznam financovaných milestones.

Následující balíčky jsou návrhy financování, nikoli nové produktové milníky nebo závazek. A odpovídá M1, B převážně M2 (provenance navazuje na M3), C M3/M4 a D federaci M5 a integraci ze sekce 21 master roadmapy. Desktopový základ zůstává v M1; v D může být financováno jeho federační rozšíření. Přesný rozsah i pořadí integrace Open WebUI zbývá určit před kampaní.

### Funding milestone A

- [ ] stable single-node workspace,
- [ ] Git project management,
- [ ] artifact browser/editor,
- [ ] metadata,
- [ ] release packaging.

### Funding milestone B

- [ ] Ollama integration,
- [ ] Context Builder,
- [ ] provenance,
- [ ] local AI workflow.

### Funding milestone C

- [ ] external LLM abstraction,
- [ ] multi-role workflow,
- [ ] creator/opponent process.

### Funding milestone D

- [ ] federation,
- [ ] federované rozšíření desktopového uzlu (základ již patří do M1),
- [ ] external/Open WebUI integration.

---

# 16. Crowdfunding budget

Před spuštěním zveřejnit realistický rozpočet:

- [ ] vývoj,
- [ ] infrastruktura,
- [ ] hosting,
- [ ] testovací hardware,
- [ ] UX/design,
- [ ] bezpečnostní review,
- [ ] právní/IP konzultace,
- [ ] účetnictví,
- [ ] crowdfunding platform fees,
- [ ] payment processing,
- [ ] daně,
- [ ] rezerva,
- [ ] případné odměny.

U každé významné položky určit:

- [ ] minimum,
- [ ] očekávanou hodnotu,
- [ ] maximum.

---

# 17. Funding target

Definovat:

- [ ] minimální funding threshold,
- [ ] target,
- [ ] stretch goals,
- [ ] scope při nedosažení stretch goals,
- [ ] co je možné financovat z vlastních zdrojů,
- [ ] které funkce budou odloženy.

Vyhnout se slibu funkcí bez vazby na dostupný rozpočet.

---

# 18. Crowdfunding rewards

Preferovat odměny, které nevytvářejí dlouhodobý logistický závazek.

Možnosti:

- [ ] supporter credit,
- [ ] contributor/supporter badge,
- [ ] jméno v supporters file,
- [ ] early testing access,
- [ ] voting/advisory participation,
- [ ] online workshop,
- [ ] architecture seminar,
- [ ] installation/support session,
- [ ] sponsor attribution.

Vyhodnotit velmi opatrně:

- [ ] lifetime hosting,
- [ ] lifetime support,
- [ ] fyzické produkty,
- [ ] individuální custom development.

---

# 19. Crowdfunding legal/IP readiness

Před kampaní:

- [ ] potvrdit vlastnictví současného kódu,
- [ ] zkontrolovat licence dependencies,
- [ ] zkontrolovat trademark/název projektu,
- [ ] určit provozovatele kampaně,
- [ ] posoudit daňové dopady,
- [ ] určit podmínky odměn,
- [ ] připravit privacy policy pro mailing/supporter data,
- [ ] připravit Terms / FAQ,
- [ ] zveřejnit open-source licenci,
- [ ] připravit FTO status statement bez nepodložených právních garancí.

Nepoužívat formulace typu:

„produkt neporušuje žádný patent“.

Preferovat:

„projekt průběžně sleduje relevantní veřejně dostupný prior art a patentové rodiny“.

---

# 20. Defensive publication před crowdfundingem

Před veřejnou kampaní provést speciální IP freeze.

## Checklist

- [ ] určit, která nová technická řešení kampaň zveřejní,
- [ ] doplnit technické disclosures,
- [ ] udělat FTO screening,
- [ ] commitnout dokumentaci,
- [ ] označit publication tag,
- [ ] vytvořit GitHub Release,
- [ ] případně vytvořit DOI,
- [ ] teprve potom zveřejnit detailní crowdfundingové materiály.

**Gate:** crowdfunding nesmí být první okamžik, kdy je zásadní technická inovace veřejně popsána bez archivovaného podkladu.

---

# 21. Crowdfunding campaign assets

Připravit:

- [ ] landing page,
- [ ] krátké demo video,
- [ ] dlouhé technické demo,
- [ ] architektonický diagram,
- [ ] roadmapu,
- [ ] funding breakdown,
- [ ] FAQ,
- [ ] screenshoty,
- [ ] use-case scénáře,
- [ ] open-source vysvětlení,
- [ ] privacy/security vysvětlení,
- [ ] team/author profile,
- [ ] timeline,
- [ ] risk section,
- [ ] stretch goals.

---

# 22. Demo scénář

Crowdfunding demo by mělo ukázat skutečný produktový diferenciátor.

Doporučený scénář:

1. uživatel otevře projekt,
2. vybere verzované projektové zdroje,
3. Context Builder vytvoří explicitní context,
4. creator připraví návrh,
5. opponent dostane pouze přijatý artefakt a vlastní Context Manifest,
6. vznikne nezávislá oponentura,
7. oba výsledky jsou verzované,
8. provenance ukáže přesné zdroje,
9. workspace funguje i bez externího LLM,
10. případně se ukáže federovaný nebo Open WebUI workflow.

---

# 23. Pre-launch checklist

Nejméně několik týdnů před spuštěním:

- [ ] cílová platforma vybrána,
- [ ] platební možnosti ověřeny,
- [ ] účetnictví a daně konzultovány,
- [ ] landing page hotová,
- [ ] video hotové,
- [ ] demo stabilní,
- [ ] FAQ hotové,
- [ ] budget hotový,
- [ ] roadmapa hotová,
- [ ] GitHub veřejně připravený,
- [ ] licence hotová,
- [ ] defensive disclosure publikováno,
- [ ] DOI workflow ověřeno,
- [ ] mailing/contact mechanismus,
- [ ] community channels,
- [ ] press/media list,
- [ ] launch-day komunikační plán.

---

# 24. Launch checklist

V den spuštění:

- [ ] ověřit dostupnost repository,
- [ ] ověřit odkazy,
- [ ] ověřit DOI/release odkazy,
- [ ] ověřit demo,
- [ ] publikovat kampaň,
- [ ] publikovat announcement,
- [ ] informovat existující komunitu,
- [ ] monitorovat technické problémy,
- [ ] odpovídat na otázky,
- [ ] evidovat opakující se FAQ,
- [ ] aktualizovat FAQ a dokumentaci.

---

# 25. Průběh kampaně

- [ ] pravidelné development updates,
- [ ] veřejné Git commits/releases,
- [ ] transparentní progress vůči milestone,
- [ ] zveřejňovat nové defensive disclosures při významných technických změnách,
- [ ] nepřislíbit nové stretch goals bez odhadu nákladů,
- [ ] sledovat community feedback,
- [ ] přetavovat feedback do backlogu,
- [ ] rozlišovat funded scope od future ideas.

---

# 26. Po kampani

Po úspěšné kampani:

- [ ] publikovat finální funding report,
- [ ] potvrdit funded roadmap,
- [ ] označit crowdfunding baseline Git tag,
- [ ] archivovat baseline release,
- [ ] vytvořit/připojit DOI,
- [ ] evidovat funding v citation metadata,
- [ ] založit veřejný milestone tracker,
- [ ] pravidelně zveřejňovat progress,
- [ ] aktualizovat budget burn,
- [ ] zveřejnit změny scope,
- [ ] průběžně aktualizovat Patent Risk Register.

---

# 27. Crowdfunding transparency

Doporučený veřejný reporting:

- [ ] dosažené milestones,
- [ ] změny roadmapy,
- [ ] nové releases,
- [ ] defensive publications,
- [ ] zásadní architektonická rozhodnutí,
- [ ] hlavní rizika,
- [ ] přibližný stav financování,
- [ ] důvody významných zpoždění nebo změn scope.

---

# 28. Vazba na hlavní projektovou roadmapu

Tato roadmapa se nemá stát druhým produktovým backlogem.

Do hlavního `TODO.md` přenášet pouze konkrétní integrace:

- [x] Vytvoření IP registrů — implemented; dokončená integrace je evidována v TODO jako IP-00.
- [ ] implementace release metadata,
- [ ] vytvoření citation metadata,
- [ ] automatizace archive/release workflow,
- [ ] integrace DOI,
- [ ] crowdfunding milestone příprava.

Strategie produktu zůstává v hlavní roadmapě a jeho operativní implementace v TODO. Zbývající integrační práce je vedena jako IP-01 až IP-03 v TODO; patentové kontroly, jednotlivé disclosures a administrativa kampaně se tam nekopírují.

---

# 29. Doporučené automatizace

Později zvážit CI workflow:

### Release integrity check

Automaticky ověřit:

- [ ] tag odpovídá release,
- [ ] working tree byl při release čistý,
- [ ] disclosure reference existuje,
- [ ] CITATION metadata mají správnou verzi,
- [ ] licence existuje,
- [ ] changelog obsahuje release,
- [ ] disclosure registry obsahuje release.

### DOI readiness check

Před označením release:

- [ ] version consistency,
- [ ] author metadata,
- [ ] release date,
- [ ] licence,
- [ ] repository URL,
- [ ] disclosure ID.

### IP reminder

Při změně vybraných oblastí:

`context / llm / routing / federation / provenance / rbac / security`

zobrazit developer checklist:

**„Vyžaduje tato změna FTO review nebo nový defensive disclosure?“**

---

# 30. Definition of Done – Defensive Publication

Defensive disclosure je považováno za dokončené pouze pokud:

- [ ] technický popis je dostatečně konkrétní,
- [ ] dokument odpovídá implementaci nebo explicitně označenému návrhu,
- [ ] existuje veřejný commit,
- [ ] existuje immutable tag,
- [ ] existuje release nebo obdobný veřejný publication point,
- [ ] je známé datum publikace,
- [ ] je evidováno v disclosure registry,
- [ ] je propojeno s Patent Risk Register,
- [ ] pokud je vytvořeno DOI, je propojení obousměrné,
- [ ] další vývoj může jednoznačně určit, co již bylo veřejně zveřejněno.

---

# 31. Definition of Ready – Crowdfunding

Crowdfunding lze spustit, pokud:

- [ ] existuje věrohodný demonstrátor,
- [ ] je jasně oddělen hotový a financovaný scope,
- [ ] existuje realistický rozpočet,
- [ ] licence a open-source model jsou jasné,
- [ ] repository je připravené pro veřejnost,
- [ ] zásadní technické mechanismy byly archivovány jako prior art,
- [ ] byl proveden baseline FTO screening,
- [ ] existuje veřejná roadmapa,
- [ ] demo a marketingová tvrzení odpovídají skutečnosti,
- [ ] jsou připravené campaign assets,
- [ ] jsou vyřešeny základní účetní, daňové a právní otázky,
- [ ] existuje plán komunikace a reportingu po kampani.

---

# 32. Strategický výsledek

Cílový stav:

`open development`

+ `traceable Git history`

+ `periodic defensive publication`

+ `immutable release tags`

+ `archived/DOI releases`

+ `living Patent Risk Register`

+ `baseline and periodic FTO reviews`

+ `transparent crowdfunding`

Výsledkem nemá být patentové portfolio, ale **dobře zdokumentovaný veřejný technický vývoj s průkaznými daty zveřejnění a snižovaným rizikem pozdějšího patentového lock-inu**.
