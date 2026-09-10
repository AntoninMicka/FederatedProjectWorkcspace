# ADR 0004 — Minimální konfigurace projektu a uzlu

Datum: 2026-09-09. Stav: přijato pro M0-02, samostatná validace PoC validated; produkční konfigurace otevřená.

## Kontrakt v1

`project.json` je přenositelné autoritativní projektové metadata v Gitu. Povinná pole: `schema_version: 1`, `id` (kanonické UUID), `title` (neprázdný text), `created_at` (UTC RFC3339 s koncovým Z), `author_id` (kanonické UUID). Volitelné `description` je text. Projektové ID se nemění při přesunu, klonování ani migraci. Autorovo ID není důkaz identity ani oprávnění.

`node.json` je lokální autoritativní konfigurace mimo všechny registrované projektové kořeny. Povinná pole: `schema_version: 1`, `id` (stabilní Node UUID), `name` (neprázdný text), `projects` (seznam lokálních vazeb). Vazba má přesně `project_id`, `root` a `state_dir`. UUID jsou jedinečná v seznamu; všechny kořeny a stavové adresáře jsou absolutní Linux cesty, po rozlišení existujících symlinků vzájemně disjunktní (ani vnořené). Cesty s `..`, řídicími znaky a komponentou `.git` se odmítají. Soubory/adresáře nemusí zatím existovat; existence projektu a shoda s jeho project.json se ověřují až při aplikačním otevření.

Volitelné `identity_credential_ref` má tvar `credential:<identifikátor>` (1–128 ASCII písmen/číslic/teček/pomlček/podtržítek, první znak alfanumerický). Je to neprůhledný lokální odkaz, ne klíč ani cesta k souboru. Neurčuje konkrétní úložiště secrets. Ověření existence klíče a jeho vazby na Node ID zbývá. Nepřítomnost odkazu umožňuje lokální uzel bez nakonfigurované síťové identity; neuděluje důvěru ani oprávnění k federaci.

Obě schémata odmítají neznámá pole, nesprávné typy, duplicitní JSON klíče a neznámou verzi (včetně boolean místo integer). Projekt nemá pole pro lokální cesty, Node ID, credentials ani backendy. Tento kontrakt však není detektor tajemství ve volném textu ani scanner celého Gitu. Node konfigurace ani credential odkazy se se sdíleným projektem nesynchronizují.

## Verze a migrace

Verze projektu a uzlu jsou nezávislé na schématu artefaktů. V1 je první podporovaná verze; staré experimenty bez project.json nejsou implicitní „v0“. Chybějící konfiguraci ani neznámou verzi validátor nedoplňuje a nepřepisuje.

Budoucí migrace musí explicitně určit zdrojovou/cílovou verzi, zachovat ID a původní data při chybě a validovat výsledek. Projektová migrace projde standardním serializovaným journal → Git → index lifecycle; lokální konfigurace potřebuje samostatný obnovitelný zápis mimo Git. Konkrétní transformace vznikne teprve s novou verzí; v tomto úkolu není automatická migrace ani inicializace.

## Rozsah, reuse a ověření

Adaptovat omezený JSON parser, UUID a timestamp validaci z `spikes/metadata.py`. `spikes/configuration.py` je jediné spustitelné schéma konfigurace; nevytvářet paralelní JSON Schema, které by se mohlo rozcházet s validátorem. Nové read-only CLI kontroluje explicitně zvolený typ konfiguračního souboru, velikost a umístění node.json. Žádné zápisy ani nové crash boundaries nevznikají.

Stávající `check_project`, Workspace, Git snapshot a Index nadále validují pouze projekci artefaktů/registrů. Změna jejich kontraktu a zápis konfigurace musí navázat samostatně na ADR 0003; nezpřísňovat potichu původní experimenty. Backend/Role/Context Manifest kontrakty zůstávají M0-08, federace a distribuce uživatelů M5.

Ověřit platnou konfiguraci, neplatné a budoucí verze, chybějící/zakázaná pole, UUID/datum, parserové limity, duplicitní registrace, překryv cest a symlink aliasy, node.json uvnitř projektu a CLI exit kódy bez změny vstupů. Testy nedokládají RBAC, vault, migraci ani zabezpečení vůči závodícím filesystemovým změnám.

Ověření: `python3 -m unittest discover -s tests -v` prošlo včetně nového `tests/test_configuration.py`; aktuální počty a výsledky jsou ve WORK_LOG u M0-02. Ověřeny i CLI/wrapper a zachování bajtů vstupních souborů. Shellová syntaxe ověřena přes `bash -n run.sh`.
