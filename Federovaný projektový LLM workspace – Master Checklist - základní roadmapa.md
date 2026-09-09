# Federovaný projektový LLM workspace
## Master Checklist / základní roadmapa

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
- [ ] Lokální Ollama používat primárně jako:
  - [ ] klasifikátor,
  - [ ] extraktor,
  - [ ] sumarizátor,
  - [ ] filtr kontextu,
  - [ ] případně anonymizátor/redaktor před odesláním dat ven.
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

- [ ] Zavést `reuse-catalog`.
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

- [ ] Jeden projekt reprezentovat Git repozitářem.
- [ ] Definovat základní adresářovou strukturu.
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

- [ ] Pro editovatelné projektové Markdown dokumenty používat YAML frontmatter jako jediné místo autoritativních metadat dokumentu.
- [ ] Importované zdroje, které mají zůstat beze změny, zachovat v původních bajtech včetně Markdownu; jejich projektová metadata uložit do sidecaru.
- [ ] Pro PDF, obrázky a další formáty bez vhodných editovatelných metadat použít sidecar se stabilním ID artefaktu.
- [ ] V M0 určit povinná pole, verzi schématu a konvenci umístění sidecaru; vazbu založit na stabilním ID s evidencí aktuální cesty souboru.
- [ ] Přejmenování nebo smazání artefaktu promítnout do sidecaru a odkazů v jednom commitu; před commitem ověřit konzistenci.
- [ ] Git commit nepovažovat za transakci pracovního adresáře: pro přerušené změny souboru a sidecaru navrhnout obnovu po pádu.
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
  - [ ] cenu/cost policy.

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
- [ ] `local-only` nikdy neposílat externímu backendu.
- [ ] Kontrolu provádět aplikačně, nikoli pouze promptem pro LLM.

---

# 10. Context builder

- [ ] Vytvořit samostatnou službu/modul Context Builder.
- [ ] Vstupy:
  - [ ] úloha,
  - [ ] uživatel,
  - [ ] role,
  - [ ] projekt,
  - [ ] vybraný backend.
- [ ] Výstup:
  - [ ] system instructions,
  - [ ] relevantní artefakty,
  - [ ] metadata,
  - [ ] explicitní otázka.
- [ ] Podporovat:
  - [ ] automatický context,
  - [ ] ruční výběr souborů,
  - [ ] kombinaci obou.
- [ ] Evidovat manifest použitého kontextu.
- [ ] Umožnit později přesně rekonstruovat LLM request.

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
- [ ] Ollama považovat za samostatnou službu/backend.
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

- [ ] Datový model.
- [ ] Repo layout.
- [ ] Artifact metadata.
- [ ] Backend abstraction.
- [ ] Role abstraction.
- [ ] Federation model.
- [ ] Společné jádro pro serverový a desktopový uzel.
- [ ] Výběr prvního desktopového OS, obalu UI a životního cyklu lokálního backendu.
- [ ] Definovat frontmatter/sidecar schéma, soubory entit registrů a obnovu SQLite indexu.
- [ ] Navrhnout a projít uživatelský scénář konfliktu po offline úpravách dvou uzlů.
- [ ] Ověřit bezpečný transport mezi desktopovým UI a lokálním backendem.
- [ ] Vyhodnotit C++ jádro s libgit2 krátkým PoC: commit, větvení, merge konflikt, přerušení operace a sestavení na cílovém Turris/LXC a desktopu.
- [ ] Výchozí návrh MVP držet jako jeden backendový proces s oddělenými moduly pro storage, federaci a LLM; jazyk určit v M0.
- [ ] Hybrid C++ + Python daemon přijmout pouze při doloženém přínosu oproti jednomu backendu; zaznamenat náklady balení, IPC, diagnostiky, obnovy po pádu a aktualizací.
- [ ] libgit2 posoudit proti bezpečnému volání Git CLI bez shellu přes společné Git rozhraní; ověřit autentizaci, podporované operace a distribuci závislostí.
- [ ] Porovnat paměť, start, instalaci a provoz na cílovém Turrisu/LXC i desktopu; samotná preference jazyka není podmínkou rozdělení do více procesů.
- [ ] Vyhodnotit sdílené webové UI v desktopovém WebView, včetně Qt obalu; konkrétní frontendový framework vybrat až po ověření.
- [ ] Výslednou volbu stacku a případné hranice procesů zaznamenat jako architektonické rozhodnutí.
- [ ] Threat model.

**Gate M0:** existuje zaznamenaná volba stacku podložená PoC, schéma autoritativních dat a obnovy indexu, návrh bezpečného lokálního API a průchod scénářem konfliktu stejné entity i dvojice soubor–sidecar. Implementace federace zůstává v M5.

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

**Gate M2:** systém dokáže lokálně zpracovat projekt a sestavit relevantní kontext.

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

# 19. První úkoly pro Codium

- [ ] `ARCHITECTURE.md`
- [ ] `DATA_MODEL.md`
- [ ] `FEDERATION.md`
- [ ] `SECURITY.md`
- [ ] `REUSE_CATALOG.md`
- [ ] vytvořit skeleton repository
- [ ] vytvořit LXC development deployment
- [ ] vytvořit desktopový launcher a balení se společným aplikačním jádrem
- [ ] implementovat persistentní identitu a lokální úložiště desktopového uzlu
- [ ] implementovat Project model
- [ ] implementovat Artifact model
- [ ] implementovat Git service
- [ ] implementovat YAML frontmatter pro Markdown a sidecar pro ostatní artefakty
- [ ] implementovat obnovitelný SQLite index projektových metadat
- [ ] implementovat Markdown viewer/editor
- [ ] implementovat základní Git history UI
- [ ] implementovat Ollama adapter
- [ ] implementovat auto-summary/description
- [ ] implementovat Role model
- [ ] implementovat Backend model
- [ ] implementovat Context Builder PoC

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