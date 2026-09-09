# Federovaný projektový LLM workspace
## Master Checklist / základní roadmapa

Aktuální milník: **M0 — Architecture spike**. Operativní úkoly, chyby a ověřovací kroky jsou v [TODO.md](TODO.md); pravidla vývoje v [AGENTS.md](AGENTS.md).

Tento dokument drží strategii, milníky, gates a původní katalog požadavků. Nové implementační podrobnosti patří do TODO. Nezaškrtnuté požadavky neznamenají, že se již přijatá architektonická rozhodnutí znovu otevírají. U dokončených bodů rozlišujeme **designed** a **PoC validated**; ani jeden stav sám o sobě neznamená produkční implementaci. M1–M6 zůstávají otevřené i tam, kde existuje související M0 experiment.

Podpůrnou IP, publikační a crowdfundingovou agendu drží [IP roadmapa](<docs/IP/IP, Defensive Publication & Crowdfunding Roadmap.md>) a její dva registry. Navazuje na významná architektonická rozhodnutí (FTO screening a posouzení disclosure), veřejné releases (archivace commit/tag/release a případného DOI) a přípravu kampaně (Gate C0, IP freeze a crowdfunding readiness). Tyto kontroly nemění pořadí M0–M6 ani neprokazují splnění produktových gates. Technické integrační úkoly jsou v TODO; administrativa zůstává v `docs/IP`.

## 0. Cíl MVP

- [ ] Definovat systém jako **self-hosted projektový workspace** provozovatelný primárně:
  - [ ] na Turris Omnia,
  - [ ] v LXC kontejneru,
  - [ ] jako desktopovou aplikaci s vlastním lokálním uzlem,
  - [ ] případně později na běžném Linux serveru / workstation.
- [ ] Jeden uzel = samostatně provozovatelná instance.
- [ ] Desktopová aplikace je plnohodnotný uzel federace s lokálním backendem a daty; umí samostatný provoz i připojení k dalším uzlům.
- [ ] Více uzlů = federace definovaných důvěryhodných uzlů.
- [ ] Projektová data primárně ukládat jako **soubory verzované Gitem**.
- [ ] Oddělit:
  - [ ] projektová data,
  - [ ] metadata,
  - [ ] uživatele,
  - [ ] role,
  - [ ] LLM backendy,
  - [ ] historii rozhodnutí,
  - [ ] generované snapshoty.
- [ ] Umožnit používat více LLM providerů s jasně definovanými rolemi.
- [ ] Core orchestrace systému nesmí být závislá na dostupnosti LLM; deterministický aplikační orchestrátor musí fungovat i bez lokálního nebo externího modelu.
- [ ] Konverzační orchestraci („orchestrator chat“) navrhnout jako volitelnou LLM vrstvu nad deterministickým aplikačním orchestrátorem.
- [ ] Nedostupnost lokálního LLM nesmí způsobit tichý fallback na externího providera; změna execution boundary musí být explicitně povolená policy.
- [ ] Lokální Ollama používat primárně jako:
  - [ ] klasifikátor,
  - [ ] extraktor,
  - [ ] sumarizátor,
  - [ ] filtr kontextu,
  - [ ] případně anonymizátor/redaktor před odesláním dat ven,
  - [ ] volitelně orchestrator chat / planner, pokud je lokální model dostupný.
- [ ] Externím LLM neposílat automaticky celý projekt, ale pouze **sestavený kontext potřebný pro konkrétní úlohu**.

---

# 1. Průzkum a recyklace existujících řešení

## 1A. Inventura vlastních projektů

- [ ] Projít existující vlastní projekty a vytvořit katalog potenciálně znovupoužitelných komponent.
- [ ] U každé komponenty evidovat:
  - [ ] zdrojový projekt,
  - [ ] cestu/repository,
  - [ ] účel,
  - [ ] jazyk/framework,
  - [ ] závislosti,
  - [ ] licenci,
  - [ ] stav,
  - [ ] vhodnost pro reuse,
  - [ ] nutné úpravy.
- [ ] Zmapovat existující řešení pro:
  - [ ] federaci uzlů,
  - [ ] ZeroTier/WireGuard networking,
  - [ ] správu uzlů,
  - [ ] uživatele a autentizaci,
  - [ ] role/RBAC,
  - [ ] Git operace,
  - [ ] REST API,
  - [ ] frontend,
  - [ ] správu konfigurace,
  - [ ] import/export,
  - [ ] práci s Ollama,
  - [ ] externí LLM API,
  - [ ] práci s dokumenty,
  - [ ] audit/logování.

## 1B. Evidence kandidátních řešení

- [x] Zavést `reuse-catalog` — evidence kandidátů existuje v REUSE_CATALOG.md; inventura vlastních projektů zůstává otevřená.
- [ ] Každému kandidátu přiřadit stav:
  - [ ] `candidate`
  - [ ] `evaluate`
  - [ ] `reuse`
  - [ ] `adapt`
  - [ ] `reject`
- [ ] Evidovat důvod rozhodnutí.
- [ ] Nepřenášet komponenty automaticky – nejprve posoudit kompatibilitu s novou architekturou.

---

# 2. Datový model projektu

## 2A. Git jako primární projektový datastore

**Stav M0:** autoritativní Git a lokální index jsou přijatý návrh. `spikes/storage.py` má PoC validated obnovu indexu validovaného commitu a kontrolu jeho ID vůči HEAD. Index zatím obsahuje pouze ID/název entity; úplné dotazy nad metadaty a vztahy ani jednotná aplikační operace nejsou hotové.

- [ ] Jeden projekt reprezentovat Git repozitářem.
- [x] Definovat základní adresářovou strukturu — designed pro M0 v DATA_MODEL.md; schéma project.json zbývá.
- [ ] Oddělit:
  - [ ] aktivní projektové dokumenty,
  - [ ] zdroje,
  - [ ] metadata,
  - [ ] rozhodnutí,
  - [ ] hypotézy,
  - [ ] úkoly,
  - [ ] LLM výstupy,
  - [ ] snapshoty,
  - [ ] statická aktiva.
- [ ] Stanovit pravidla automatických commitů.
- [ ] Umožnit ruční commit s komentářem.
- [ ] Evidovat autora změny.
- [ ] Připravit mechanismus řešení konfliktů.
- [ ] Projektová metadata a registry verzovat v Gitu jako autoritativní data.
- [ ] SQLite používat jako lokální, z Gitu obnovitelný index pro dotazy a vztahy; databázový soubor nesynchronizovat.
- [ ] SQLite index neslouží k řešení souběžných změn ani merge konfliktů; ty řešit nad autoritativními soubory před aktualizací indexu.
- [ ] Změny projektových metadat zapisovat přes soubory v Gitu; index aktualizovat po úspěšném commitu/merge a při startu ověřit jeho verzi vůči HEAD.
- [ ] Oddělit obnovitelný projektový index od autoritativního lokálního stavu uzlu (identita, credentials, rozpracované operace).
- [ ] Každou entitu registru ukládat do samostatného souboru se stabilním ID; společné seznamy generovat z indexu.
- [ ] Rozdělení registrů omezuje kolize změn různých entit; souběžné změny stejné entity stále vyžadují sloučení a validaci.
- [ ] Index označit ID indexovaného commitu; při nesouladu jej obnovit a do té doby nezobrazovat zastaralé výsledky jako aktuální. Rozpracované změny zobrazovat odděleně od indexu commitnutého stavu.
- [ ] Po merge validovat schémata, unikátnost ID a vztahy; textově čistý merge nemusí být významově správný.

## 2B. Typy souborů

- [ ] Markdown jako primární formát pro:
  - [ ] teze,
  - [ ] poznámky,
  - [ ] analýzy,
  - [ ] rozhodnutí,
  - [ ] checklisty,
  - [ ] jednodušší projektové dokumenty.
- [ ] JSON/YAML pro:
  - [ ] strukturovaná metadata,
  - [ ] konfiguraci,
  - [ ] registry,
  - [ ] vztahy mezi objekty,
  - [ ] strojově zpracovávané projektové entity.
- [ ] PDF používat jako:
  - [ ] časový snapshot,
  - [ ] externí dokument,
  - [ ] neměnný zdroj,
  - [ ] archivní výstup.
- [ ] Binární/static assets:
  - [ ] obrázky,
  - [ ] schémata,
  - [ ] přílohy,
  - [ ] případně CAD a další projektové soubory.

## 2C. Uložení metadat podle formátu

**Stav M0: PoC validated.** Frontmatter/sidecar parser, společné schéma, registry po entitách a kontrola vztahů jsou implementované v `spikes/metadata.py`. Zachování bajtů importu a obnova souborových změn jsou ověřené. Níže uvedené aplikační schopnosti zůstávají otevřené do integrace; neimplementovat znovu jejich PoC. Přejmenování v journalu není ověřením distribuovaného merge.

- [ ] Pro editovatelné projektové Markdown dokumenty používat YAML frontmatter jako jediné místo autoritativních metadat dokumentu.
- [ ] Importované zdroje, které mají zůstat beze změny, zachovat v původních bajtech včetně Markdownu; jejich projektová metadata uložit do sidecaru.
- [ ] Pro PDF, obrázky a další formáty bez vhodných editovatelných metadat použít sidecar se stabilním ID artefaktu.
- [x] V M0 určit povinná pole, verzi schématu a konvenci umístění sidecaru; vazbu založit na stabilním ID s evidencí aktuální cesty souboru — PoC validated, ADR 0002.
- [ ] Přejmenování nebo smazání artefaktu promítnout do sidecaru a odkazů v jednom commitu; před commitem ověřit konzistenci.
- [x] Navrhnout obnovu přerušené změny souboru a sidecaru — PoC validated pomocí journalu (ADR 0002); integrace celé operace s commitem je otevřená.
- [ ] Konflikty změna–smazání, přejmenování–úprava a osiřelý sidecar řešit explicitně; metadata nesmějí být tiše zahozena.
- [ ] Metadata neduplikovat mezi frontmatter a sidecarem; použít společné logické schéma pro oba způsoby uložení.
- [ ] Strukturované entity registrů ukládat jako JSON s vlastními poli ID a verze schématu; nepřidávat k nim duplicitní sidecar.

## 2D. Verzovací filtry

- [ ] Navrhnout normalizační pipeline před commitem.
- [ ] Odstraňovat nedeterministická metadata tam, kde je to bezpečné.
- [ ] Stabilizovat formát JSON/YAML.
- [ ] Normalizovat Markdown.
- [ ] Oddělit obsah od automaticky generovaných metadat.
- [ ] Pro velké binární soubory zvážit Git LFS.
- [ ] Připravit diff-friendly reprezentaci vybraných komplikovaných formátů.

---

# 3. Metadata a zdrojování

## 3A. Metadata dokumentu

- [ ] Každému souboru umožnit přiřadit:
  - [ ] ID,
  - [ ] název,
  - [ ] stručný popis,
  - [ ] typ,
  - [ ] autora,
  - [ ] datum vzniku,
  - [ ] datum importu,
  - [ ] zdroj,
  - [ ] URL/reference,
  - [ ] tagy,
  - [ ] vztahy k ostatním dokumentům.
- [ ] Popis umožnit:
  - [ ] zadat ručně,
  - [ ] automaticky vygenerovat přes Ollama,
  - [ ] automaticky aktualizovat pouze po potvrzení uživatelem.

## 3B. Provenance

- [ ] Rozlišovat:
  - [ ] primární zdroj,
  - [ ] uživatelský dokument,
  - [ ] externí zdroj,
  - [ ] LLM-generated,
  - [ ] LLM-transformed,
  - [ ] snapshot.
- [ ] U LLM výstupu ukládat:
  - [ ] backend,
  - [ ] model,
  - [ ] roli,
  - [ ] čas,
  - [ ] vstupní artefakty,
  - [ ] prompt/template,
  - [ ] případně parametry inference.
- [ ] Umožnit dohledat:
  **„Z čeho tento závěr vznikl?“**

---

# 4. Projektové registry

- [ ] Zavést registr předpokladů.
- [ ] Zavést registr hypotéz.
- [ ] Zavést registr otevřených otázek.
- [ ] Zavést registr rizik.
- [ ] Zavést decision log.
- [ ] Zavést registr zamítnutých variant.
- [ ] Zavést registr externích zdrojů.
- [ ] Zavést registr témat vyžadujících odborné ověření.
- [ ] Zavést registr úkolů.
- [ ] Umožnit vztahy typu:
  - [ ] dokument → předpoklad,
  - [ ] předpoklad → rozhodnutí,
  - [ ] zdroj → tvrzení,
  - [ ] riziko → rozhodnutí,
  - [ ] otázka → odpověď,
  - [ ] rozhodnutí → následné úkoly.
- [ ] Připravit možnost pozdějšího impact analysis:
  **„Která rozhodnutí jsou ovlivněna změnou tohoto předpokladu?“**

---

# 5. Uživatelé, identity a RBAC

## 5A. Federovaní uživatelé

- [ ] Navrhnout globální identitu uživatele v rámci federace.
- [ ] Oddělit:
  - [ ] identitu uživatele,
  - [ ] členství v projektu,
  - [ ] projektové role,
  - [ ] lokální oprávnění uzlu.
- [ ] Definovat mechanismus distribuce uživatelů mezi uzly.
- [ ] Definovat řešení konfliktu změn identity.
- [ ] Definovat deaktivaci/revokaci uživatele.

## 5B. Role uživatelů

- [ ] Minimální RBAC:
  - [ ] federation-admin,
  - [ ] node-admin,
  - [ ] project-admin,
  - [ ] editor,
  - [ ] reviewer,
  - [ ] reader.
- [ ] Oprávnění řídit minimálně pro:
  - [ ] projekty,
  - [ ] soubory,
  - [ ] Git operace,
  - [ ] LLM backendy,
  - [ ] federaci,
  - [ ] export,
  - [ ] administraci.

---

# 6. Federace uzlů

## 6A. Node model

- [ ] Každému uzlu přidělit stabilní Node ID.
- [ ] Rozlišovat způsob nasazení uzlu: Turris/LXC, Linux server a desktop.
- [ ] Používat společný model identity, oprávnění a federační protokol pro všechny způsoby nasazení.
- [ ] Desktop považovat za přerušovaně dostupný uzel; chod ostatních uzlů nesmí záviset na jeho dostupnosti.
- [ ] Evidovat:
  - [ ] jméno,
  - [ ] adresy,
  - [ ] veřejný klíč,
  - [ ] capabilities,
  - [ ] dostupné backendy,
  - [ ] projekty,
  - [ ] stav synchronizace.
- [ ] Definovat trust model mezi uzly.

## 6B. Transport

- [ ] Primárně předpokládat privátní overlay síť.
- [ ] Podporovat ZeroTier.
- [ ] Připravit architekturu kompatibilní s WireGuardem.
- [ ] Nevázat aplikační federaci přímo na konkrétní VPN technologii.

## 6C. Synchronizace

- [ ] Git používat pro synchronizaci projektových artefaktů.
- [ ] Samostatně řešit synchronizaci:
  - [ ] uživatelů,
  - [ ] node konfigurace,
  - [ ] federation metadata.
- [ ] Definovat:
  - [ ] pull,
  - [ ] push,
  - [ ] divergence,
  - [ ] konflikt,
  - [ ] offline node,
  - [ ] návrat uzlu po delší době.
- [ ] MVP navrhnout jako **eventual consistency**, nikoli distribuovanou transakční DB.
- [ ] Na desktop synchronizovat pouze vybrané projekty, ke kterým má uživatel oprávnění.
- [ ] Lokální úpravy a commity umožnit i offline; po připojení znovu ověřit oprávnění a synchronizovat.
- [ ] Při divergenci zachovat obě historie a nabídnout řešení konfliktu bez tichého přepsání změn.
- [ ] Synchronizaci bezpečně obnovit po uspání, ukončení aplikace nebo výpadku sítě.
- [ ] V M0 určit topologii MVP, výběr synchronizačního peeru a pravidla větví; oddělit důvěru mezi uzly od směrování synchronizace.
- [ ] Již v M0 navrhnout UI konfliktu s verzemi „moje“, „příchozí“ a společným základem, náhledem výsledku a možností řešení odložit.
- [ ] Pro binární soubory nabídnout výběr verze nebo zachování obou jako samostatných artefaktů.
- [ ] Nevyřešený merge nepublikovat jako aktuální projektový stav; zachovat původní data a zobrazit blokovanou synchronizaci.

---

# 7. LLM backend abstraction

## 7A. Backend registry

- [ ] Vytvořit abstraktní definici LLM backendu.
- [ ] Backend definovat nezávisle na projektu.
- [ ] Každý uzel spravuje vlastní backendy.
- [ ] Backend může být:
  - [ ] Ollama,
  - [ ] OpenAI-compatible API,
  - [ ] konkrétní cloud provider,
  - [ ] budoucí vlastní adapter.
- [ ] U backendu evidovat:
  - [ ] endpoint,
  - [ ] provider,
  - [ ] model,
  - [ ] capabilities,
  - [ ] limity,
  - [ ] privacy classification,
  - [ ] cenu/cost policy,
  - [ ] účel/capabilities použití (např. orchestrator chat, role execution, extraction/summarization, Context Builder).
- [ ] Oddělit účel backendu od jeho execution boundary.
- [ ] Rozlišovat minimálně execution boundary:
  - [ ] `same-node`,
  - [ ] `trusted-federation`,
  - [ ] `external-provider`.
- [ ] Dostupnost backendu nesmí sama změnit autorizaci ani povolenou trust boundary.

## 7B. Secrets

- [ ] API klíče nikdy neukládat do projektového Gitu.
- [ ] Secrets držet lokálně na uzlu.
- [ ] Backend konfiguraci rozdělit na:
  - [ ] synchronizovatelnou definici,
  - [ ] lokální credentials.

---

# 8. LLM role

- [ ] Role definovat nezávisle na konkrétním modelu.
- [ ] Základní role:
  - [ ] creator,
  - [ ] opponent,
  - [ ] analyst,
  - [ ] researcher,
  - [ ] editor,
  - [ ] extractor,
  - [ ] summarizer,
  - [ ] issue-spotter.
- [ ] Role obsahuje:
  - [ ] system prompt,
  - [ ] povolené zdroje,
  - [ ] požadovaný typ kontextu,
  - [ ] preferovaný backend/model,
  - [ ] privacy policy,
  - [ ] očekávaný formát výstupu.
- [ ] Umožnit projektové override rolí.
- [ ] Umožnit uživateli pro konkrétní běh změnit backend.
- [ ] Umožnit vynutit procesní oddělení:
  - [ ] creator ≠ opponent backend,
  - [ ] opponent nevidí pracovní historii creator role.

---

# 9. Lokální Ollama pipeline

- [ ] Ollama je volitelná lokální inteligentní vrstva, nikoli systémová závislost uzlu.
- [ ] Uzel bez Ollamy musí zachovat plnou základní projektovou funkcionalitu přes deterministické UI/příkazy/workflow.
- [ ] Pokud Ollama obsluhuje orchestrator chat, pouze interpretuje požadavek/plán; provedení operací zůstává v deterministickém aplikačním orchestrátoru pod RBAC, privacy policy a validací.
- [ ] Fallback orchestrator chatu konfigurovat explicitně, minimálně jako `disabled | external | selected-backend`; výchozí chování nesmí být tichý externí fallback.

## 9A. Ingest

- [ ] Import dokumentu.
- [ ] Extrakce textu.
- [ ] Identifikace typu dokumentu.
- [ ] Generování stručného popisu.
- [ ] Extrakce tagů.
- [ ] Extrakce potenciálních entit.
- [ ] Chunking.
- [ ] Uložení výsledných metadat.

## 9B. Context filter

- [ ] Uživatel zadá úlohu.
- [ ] Systém určí požadovanou LLM roli.
- [ ] Lokální model vyhledá relevantní projektové artefakty.
- [ ] Lokální model sestaví kandidátní kontext.
- [ ] Privacy filtr odstraní data, která nesmí odejít.
- [ ] Uživatel může před odesláním zobrazit:
  **„Co přesně bude odesláno externímu LLM?“**
- [ ] Teprve následně volat externí backend.

## 9C. Privacy classes

- [ ] Zavést například:
  - [ ] `public`
  - [ ] `project`
  - [ ] `confidential`
  - [ ] `local-only`
- [ ] `local-only` chápat jako `same-node`: neposílat jej jinému federovanému uzlu ani externímu providerovi bez explicitní reklasifikace.
- [ ] Pro ostatní privacy třídy určit povolené execution boundaries projektovou/user policy.
- [ ] Kontrolu provádět aplikačně, nikoli pouze promptem pro LLM.
- [ ] Výpadek nebo nedostupnost backendu nesmí automaticky rozšířit povolenou execution boundary.

---

# 10. Context builder

- [ ] Vytvořit samostatnou službu/modul Context Builder.
- [ ] Vstupy:
  - [ ] úloha,
  - [ ] uživatel,
  - [ ] role,
  - [ ] projekt,
  - [ ] vybraný backend,
  - [ ] execution boundary a capabilities cílového backendu/uzlu.
- [ ] Výstup:
  - [ ] system instructions,
  - [ ] relevantní artefakty,
  - [ ] metadata,
  - [ ] explicitní otázka.
- [ ] Podporovat:
  - [ ] automatický context,
  - [ ] ruční výběr souborů,
  - [ ] kombinaci obou.
- [ ] Evidovat manifest použitého kontextu včetně execution boundary (`same-node` / `trusted-federation` / `external-provider`).
- [ ] Umožnit později přesně rekonstruovat LLM request i místo/trust boundary jeho vykonání.

---

# 11. Workflow engine

## MVP

- [ ] Jednorázové spuštění role nad vybranými artefakty.
- [ ] Uložení výsledku jako nového artefaktu.
- [ ] Možnost výsledek:
  - [ ] přijmout,
  - [ ] zamítnout,
  - [ ] upravit,
  - [ ] předat jiné roli.

## Další fáze

- [ ] Podporovat workflow:

`creator → opponent → analyst → human decision`

- [ ] Podporovat:

`návrh → oponentura → analýza → ověření → rozhodnutí → nový návrh`

- [ ] Každý krok musí mít explicitní vstupní artefakty.
- [ ] Nepřenášet implicitně kompletní historii předchozí role.
- [ ] Umožnit checkpoint člověka mezi jednotlivými rolemi.

---

# 12. Webové UI

## MVP obrazovky

- [ ] Login.
- [ ] Seznam projektů.
- [ ] Project dashboard.
- [ ] File browser.
- [ ] Markdown editor/viewer.
- [ ] Metadata editor.
- [ ] Git history.
- [ ] LLM action panel.
- [ ] Context preview.
- [ ] Výběr:
  - [ ] role,
  - [ ] backendu,
  - [ ] modelu.
- [ ] Správa registrů.
- [ ] Node administration.
- [ ] Federation status.
- [ ] User/RBAC administration.

## UX princip

- [ ] Projekt nesmí působit primárně jako „chat s AI“.
- [ ] Chat je pouze jeden z možných pohledů.
- [ ] Orchestrator chat je volitelný; bez dostupného/povoleného LLM musí stejné základní projektové operace zůstat dostupné deterministickým UI/workflow.
- [ ] Hlavní objekty jsou:
  **artefakty – zdroje – tvrzení – rozhodnutí – úkoly – role.**

---

# 12A. Desktopová aplikace jako uzel sítě

- [ ] Sdílet aplikační jádro a UI s webovou/serverovou variantou.
- [ ] Přibalit lokální backend pro správu projektů, Git operace, metadata a federaci.
- [ ] Umožnit založení a editaci lokálního projektu bez dostupnosti jiného uzlu.
- [ ] Ukládat projektové repozitáře a stav uzlu do persistentního uživatelského adresáře.
- [ ] Zachovat Node ID a lokální data při aktualizaci aplikace.
- [ ] Přidat připojení k federaci přes ověření identity a schválení důvěry mezi uzly.
- [ ] Zobrazovat dostupnost ostatních uzlů, poslední synchronizaci, čekající změny a konflikty.
- [ ] Umožnit ruční synchronizaci a nastavit automatickou synchronizaci při dostupném spojení.
- [ ] Umožnit lokální Ollama backend i povolené vzdálené backendy; UI musí zobrazit jejich dostupnost.
- [ ] Offline zpřístupnit lokální artefakty a lokální backendy; u vzdálených akcí jasně zobrazit nedostupnost.
- [ ] Stanovit chování při zavření okna: ukončení uzlu nebo volitelný běh na pozadí.
- [ ] Lokální API zpřístupnit pouze aplikaci přes autentizované lokální spojení; síťový endpoint federace spravovat odděleně.
- [ ] V M0 posoudit lokální socket/IPC oproti HTTP na loopbacku podle zvoleného desktopového obalu.
- [ ] Při použití HTTP vázat lokální API pouze na loopback, ověřovat Host a povolený Origin a zavést ochranu proti CSRF; CORS nepovažovat za autentizaci.
- [ ] Vyžadovat náhodný token pro každé spuštění lokálního API, předat jej aplikaci chráněným kanálem a nevkládat jej do URL ani logů.
- [ ] Pokud je token předáván souborem, omezit přístup na uživatele aplikace (na Unixu režim 0600, na Windows odpovídající ACL).
- [ ] Ověřit odmítnutí požadavků bez tokenu, s neplatným tokenem a z nepovolené webové stránky.
- [ ] Credentials ukládat do úložiště přihlašovacích údajů operačního systému, mimo projektový Git a synchronizaci.
- [ ] V M0 vybrat první podporovaný desktopový OS a technologii balení; posoudit Linux, Windows a macOS.
- [ ] Připravit instalaci, aktualizace, migrace dat a odinstalaci s explicitní volbou zachování dat.

---

# 13. API

- [ ] Definovat interní REST API.
- [ ] Oddělit endpointy:
  - [ ] `/projects`
  - [ ] `/artifacts`
  - [ ] `/git`
  - [ ] `/users`
  - [ ] `/roles`
  - [ ] `/backends`
  - [ ] `/llm`
  - [ ] `/workflows`
  - [ ] `/federation`
  - [ ] `/nodes`
- [ ] Připravit API tak, aby frontend nebyl těsně svázán s implementací backendu.
- [ ] API verzovat od začátku.

---

# 14. Turris Omnia / LXC deployment

- [ ] Vytvořit minimální LXC image/container setup.
- [ ] Oddělit persistentní:
  - [ ] Git repositories,
  - [ ] DB,
  - [ ] config,
  - [ ] secrets,
  - [ ] cache.
- [ ] Ollama považovat za samostatnou volitelnou službu/backend; její absence nesmí degradovat uzel pod základní non-LLM funkcionalitu.
- [ ] Nevyžadovat, aby velký LLM běžel přímo na Turrisu.
- [ ] Umožnit Ollama endpoint na:
  - [ ] stejném uzlu,
  - [ ] LAN serveru,
  - [ ] výkonném federovaném uzlu.
- [ ] Připravit systemd/procd startup.
- [ ] Healthcheck.
- [ ] Backup.
- [ ] Restore.
- [ ] Upgrade/migration mechanismus.

---

# 15. Bezpečnost

- [ ] Threat model.
- [ ] TLS i uvnitř overlay sítě.
- [ ] Node authentication.
- [ ] User authentication.
- [ ] RBAC.
- [ ] Secrets management.
- [ ] Audit log.
- [ ] Rate limiting.
- [ ] Validace uploadů.
- [ ] Ochrana proti path traversal.
- [ ] Ochrana Git command invocation.
- [ ] LLM prompt injection považovat za bezpečnostní problém.
- [ ] Externí dokument nikdy automaticky nepovažovat za důvěryhodnou instrukci.
- [ ] Privacy policy aplikovat před LLM requestem.

---

# 16. Audit a reprodukovatelnost LLM

- [ ] Pro každý významný LLM výstup evidovat:
  - [ ] uživatele,
  - [ ] čas,
  - [ ] roli,
  - [ ] backend,
  - [ ] model,
  - [ ] vstupní artefakty,
  - [ ] verze vstupních artefaktů,
  - [ ] prompt template,
  - [ ] výsledný artefakt.
- [ ] Umožnit odpovědět:

**Kdo, kdy, pomocí čeho a z jakých zdrojů tento text/závěr vytvořil?**

---

# 17. MVP – doporučené pořadí implementace

## Milestone M0 – Architecture spike

Zahájeno 2026-09-09. Důkazy: [ADR 0001](docs/adr/0001-m0-baseline.md), [ADR 0002](docs/adr/0002-metadata-journal.md) a `tests/`. Aktuálně ověřeno 19 testů; podrobné výsledky a zbývající kroky drží [TODO.md](TODO.md). **Gate M0 zůstává otevřený.**

- [x] Návrh layoutu a hranic autoritativních projektových dat / lokálního stavu — designed v DATA_MODEL a ARCHITECTURE.
- [x] Artefaktová metadata, frontmatter/sidecar, registry a obnova SQLite indexu — PoC validated; úplné schéma projektu/uzlu zbývá.
- [x] Obnova souborových změn před commitem — Linux PoC validated, včetně pádu procesu; nejde o celou aplikační transakci.
- [x] Popsat uživatelský scénář konfliktu a ověřit divergenci stejné entity — designed + Git CLI PoC validated; UI není implementované.
- [x] Vymezit společné jádro desktopu/serveru a výchozí jeden backendový proces — designed. Jazyk, obal UI a balení zůstávají otevřené.
- [x] Počáteční threat model — designed v SECURITY; ověření transportu a produkčních ochran zbývá.
- [ ] Uzavřít datové kontrakty projektu/uzlu a návrhové kontrakty Backend, Role a Context Manifest; současné návrhy zachovat.
- [ ] Uzavřít kontrakt `UI / orchestrator chat → application orchestrator → Context Builder / workflow → LLM backend`: deterministický orchestrátor funguje bez LLM, orchestrator chat je volitelná capability a externí/federovaný fallback vyžaduje explicitní policy.
- [ ] V M0 rozlišit backend capability od execution boundary a ověřit návrh pro uzel bez LLM, uzel s lokální Ollamou, zakázaný externí fallback, explicitně povolený externí backend, trusted-federation backend a `local-only` kontext.
- [ ] Propojit journal, validaci, Git commit a index do jedné obnovitelné operace se společným řízením přístupu.
- [ ] Doplnit návrh pravidel větví a ověřit konflikty obsahu/sidecaru včetně sémanticky neplatného merge. Implementace síťové federace zůstává M5.
- [ ] Ověřit bezpečný lokální transport/API pro desktop podle SECURITY a sekce 12A.
- [ ] Uzavřít Git implementaci na základě porovnání C++/libgit2 s existujícím Git CLI PoC, včetně autentizace a distribuce závislostí.
- [ ] Ověřit Turris Omnia/LXC a desktop: paměť, start, instalaci a provoz.
- [ ] Uzavřít stack, první desktopový OS, obal sdíleného UI a životní cyklus backendu. Linux je navržený první cíl; Qt/WebView kandidát. Hybrid C++/Python vyžaduje doložený přínos; podrobnosti porovnání jsou v TODO M0-03 až M0-06.
- [ ] Zaznamenat konečná rozhodnutí a vyhodnotit připravenost pro M1.

**Gate M0:** existuje zaznamenaná volba stacku podložená PoC, schéma autoritativních dat a obnovy indexu, návrh bezpečného lokálního API a průchod scénářem konfliktu stejné entity i dvojice soubor–sidecar. Je uzavřen kontrakt deterministické orchestrace bez LLM, volitelného orchestrator chatu a execution boundaries; dostupnost backendu nesmí sama měnit autorizaci ani trust policy. Implementace federace zůstává v M5.

## Milestone M1 – Single-node project workspace

- [ ] LXC deployment.
- [ ] Jeden uživatel.
- [ ] Jeden projekt.
- [ ] Git repository.
- [ ] Markdown/JSON/PDF/assets.
- [ ] Metadata.
- [ ] Git history.
- [ ] Web UI.
- [ ] Desktopové balení se spuštěním lokálního uzlu a sdíleným UI.
- [ ] Ověření lokální práce bez sítě a zachování dat po restartu desktopové aplikace.
- [ ] Ověření obnovy projektového indexu z Gitu a konzistence metadat po přejmenování či smazání artefaktu.
- [ ] Ověření obnovy po přerušení zápisu artefaktu/sidecaru a po commitu před aktualizací indexu; import neměnného zdroje musí zachovat jeho původní bajty.

**Gate M1:** systém je použitelný jako projektový Git-backed knowledge workspace bez LLM v LXC i v desktopové aplikaci na prvním podporovaném OS.

## Milestone M2 – Local AI

- [ ] Ollama backend.
- [ ] Summarizer.
- [ ] Extractor.
- [ ] Auto-description.
- [ ] Tagging.
- [ ] Context builder.

**Gate M2:** systém dokáže při dostupném lokálním LLM lokálně zpracovat projekt a sestavit relevantní kontext; bez lokálního LLM zůstává funkční M1 workspace a orchestrator chat je pouze nedostupná volitelná capability.

## Milestone M3 – External LLM

- [ ] Backend abstraction.
- [ ] První externí provider.
- [ ] Role.
- [ ] Context preview.
- [ ] Privacy filter.
- [ ] Provenance.

**Gate M3:** lze bezpečně předat omezený projektový kontext vybranému LLM.

## Milestone M4 – Multi-role workflow

- [ ] Creator.
- [ ] Opponent.
- [ ] Analyst.
- [ ] Editor.
- [ ] Workflow handoff.
- [ ] Human approval.
- [ ] Artifact-based context isolation.

**Gate M4:** lze provést nezávislou oponenturu bez sdílení původní konverzační historie.

## Milestone M5 – Federation

- [ ] Node identity.
- [ ] Trust.
- [ ] Git sync.
- [ ] Shared users.
- [ ] Node-local backend registry.
- [ ] Federation status.
- [ ] Offline/reconnect.

- [ ] Ověřit synchronizaci desktopového a Turris/LXC nebo Linux serverového uzlu.
- [ ] Ověřit souběžné úpravy stejného souboru a stejné entity registru během offline provozu desktopu a následné řešení konfliktu.
- [ ] Ověřit konflikty změna–smazání a přejmenování–úprava u artefaktu se sidecarem, validaci vztahů po merge a aktualizaci indexu až po vyřešení konfliktů.
- [ ] Ověřit návrat desktopu po uspání a odmítnutí synchronizace při odvolané důvěře/oprávnění.

**Gate M5:** desktopový a serverový uzel mohou sdílet projekt a uživatele, používat rozdílné LLM backendy a synchronizovat změny po offline práci bez ztráty historie.

## Milestone M6 – Project intelligence

- [ ] Assumption registry.
- [ ] Decision log.
- [ ] Risk register.
- [ ] Source registry.
- [ ] Relations.
- [ ] Impact analysis.
- [ ] Advanced context selection.

**Gate M6:** systém už není pouze „Git + LLM“, ale projektový knowledge/decision engine.

---

# 18. Explicitně odložit za MVP

- [ ] Vector DB jako povinnou komponentu.
- [ ] Komplexní distribuovanou databázi.
- [ ] Real-time collaborative editing.
- [ ] Kubernetes.
- [ ] Automatický multi-agent swarm.
- [ ] Autonomní změny projektových dokumentů bez potvrzení člověkem.
- [ ] Vlastní model training.
- [ ] Plnohodnotný replacement GitHub/GitLab.
- [ ] Automatickou synchronizaci secrets.
- [ ] Mobilní aplikaci.

---

# 19. Operativní práce a návaznost na implementaci

Konkrétní úkoly byly přesunuty do [TODO.md](TODO.md), včetně původních položek pro deployment, desktop, Project/Artifact/Git služby, UI, Ollama, role a Context Builder. Zde se již neduplikuje jejich průběžný stav.

- [x] Pracovní architektonické dokumenty, ADR, reuse katalog a kostra experimentů — designed / implemented.
- [x] Frontmatter/sidecar validátor, obnovitelný index, souborový journal a CLI kontrola projekce — implemented v M0; ověření a limity viz ADR 0002 a TODO.
- [ ] Integrovaná aplikace a nasazení podle M1; existující experimenty adaptovat podle finálního stacku.

---

# 20. Definice prvního skutečně použitelného prototypu

První prototyp je hotový, pokud lze:

- [ ] založit projekt,
- [ ] přidat Markdown/PDF/JSON/obrázek,
- [ ] soubor popsat ručně nebo přes Ollama,
- [ ] commitnout změny do Gitu,
- [ ] zobrazit historii,
- [ ] vybrat několik dokumentů,
- [ ] nechat Ollama sestavit jejich stručný relevantní kontext,
- [ ] zobrazit uživateli přesně tento kontext,
- [ ] vybrat roli,
- [ ] vybrat externí LLM backend,
- [ ] odeslat kontext,
- [ ] uložit odpověď jako nový verzovaný artefakt,
- [ ] zaznamenat, z jakých zdrojů odpověď vznikla.

**Federace ještě není podmínkou prvního prototypu.**

První prototyp ověřit i jako samostatně běžící desktopovou aplikaci s lokálními daty.

Teprve po ověření tohoto workflow propojit desktopový a serverový uzel a řešit synchronizaci, distribuované identity a konflikty.

---

# 21. Ollama / Open WebUI – obousměrná integrace

Vedle použití Ollamy jako interního backendu workspace umožnit také opačný směr integrace: federovaný projektový workspace může vystupovat jako zdroj kontextu, nástrojů a projektových artefaktů pro externí LLM rozhraní, zejména Ollama/Open WebUI.

- [ ] Navrhnout integrační API nezávislé na konkrétním UI klientovi.
- [ ] Umožnit přístup z Ollama/Open WebUI k vybranému projektu v rozsahu oprávnění přihlášeného uživatele.
- [ ] Umožnit z externího LLM rozhraní:
  - [ ] vybrat projekt,
  - [ ] vyhledat projektové artefakty,
  - [ ] načíst explicitně vybraný kontext,
  - [ ] použít Context Builder workspace,
  - [ ] získat Context Manifest,
  - [ ] pracovat s projektovými registry a vztahy v rozsahu povolených capabilities.
- [ ] Zachovat stejné RBAC, privacy a execution-boundary kontroly jako při použití interního UI.
- [ ] Externí klient nesmí získat přímý neomezený přístup k projektovému Git repozitáři nebo filesystemu.

## Zpětný zápis výsledků

- [ ] Umožnit vrátit výsledek práce z Ollama/Open WebUI zpět do workspace.
- [ ] Výsledek importovat jako explicitní artefakt nebo návrh změny, nikoli jako automatickou modifikaci existujícího projektového obsahu.
- [ ] U importovaného výsledku evidovat provenance minimálně:
  - [ ] zdrojovou integraci,
  - [ ] uživatele,
  - [ ] projekt,
  - [ ] backend/model, pokud je znám,
  - [ ] čas,
  - [ ] použité vstupní artefakty / Context Manifest, pokud jsou dostupné,
  - [ ] původní conversation/run ID, pokud jej integrace poskytuje.
- [ ] Výsledek může být následně:
  - [ ] uložen jako nový artefakt,
  - [ ] připojen jako návrh k existujícímu artefaktu,
  - [ ] předán projektové LLM roli,
  - [ ] použit jako vstup workflow,
  - [ ] přijat, upraven nebo zamítnut člověkem.
- [ ] Zápis do autoritativních projektových dat musí vždy projít standardní aplikační cestou:
  `integration → authorization → validation → application orchestrator → Git operation → index`.
- [ ] Open WebUI ani jiný externí LLM klient nesmí obcházet aplikační orchestrátor, Git lifecycle, audit nebo human-approval pravidla.

## Integrační princip

Integrace má být obousměrná:

`workspace → Context Builder → Ollama / Open WebUI → LLM`

a

`LLM / Open WebUI → návrh/výsledek → workspace → validace → verzovaný artefakt`

Open WebUI tedy může sloužit jako alternativní konverzační frontend nad projektovými daty, ale **workspace zůstává autoritou pro projektová data, oprávnění, provenance, rozhodnutí a verzování**.

Integrace nesmí vytvořit druhý paralelní systém projektového stavu uvnitř Open WebUI. Konverzační historie může zůstat vlastnictvím externího klienta; do workspace se vracejí explicitně vybrané výsledky, artefakty a jejich dohledatelná provenance.