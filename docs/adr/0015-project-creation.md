# ADR 0015 — Vytvoření a registrace projektu

Stav: přijato pro M1-02, omezený Linux PoC. Doplňuje inicializaci, kterou ADR 0003/0004 výslovně vynechaly. Další změny existujícího projektu nadále řídí Workspace.

## Vstup a lokální autorita

Nativní Qt dialog přijímá název a dosud neexistující cílovou složku. HTTP/JavaScript nemá mutující endpoint ani most pro libovolné cesty. Služba vytváření je nezávislá na Qt. Native controller při potvrzení přidělí operation UUID; opakování stejného ID/parametrů vrací stejný receipt, jiné parametry se odmítají. Jeden uzel má jeden neblokující procesní flock a nejvýše jednu nedokončenou operaci. Druhý klient dostane busy/pending chybu. Ztráta odpovědi neznamená nový pokus s novým ID: při restartu se obnoví uložená operace.

Výchozí konfigurace je `$XDG_STATE_HOME/federated-workspace/node.json` (jinak `~/.local/state/federated-workspace/node.json`). Pouhé zobrazení bez registrace nic nevytváří; první potvrzené vytvoření založí lokální konfiguraci. `--node` ji explicitně nahrazuje. Vedle ní je soukromý adresář operací s SQLite journalem, odděleným od projektového journalu i obnovitelného indexu. Drží lokální author UUID a receipts; není v projektovém Gitu. Author UUID není Node UUID ani síťová identita. Node ID i project ID jsou stabilní a nevznikají znovu při recovery.

Cesty jsou absolutní, bez symlinků, kořeny/stavy disjunktní vůči všem registracím i konfiguraci/journalu uzlu. Cílový rodič musí existovat a být vlastněný uživatelem bez zápisu jiných uživatelů. Lokální stav vzniká vedle projektu pod skrytým jménem s project UUID, na stejném filesystemu. Existující cíl se nikdy nepoužívá ani nepřepisuje. Registrace již existujícího cizího projektu/migrace zůstává samostatná práce.

## Crash boundaries před implementací

| Hranice | Recovery |
| --- | --- |
| Před `prepared` | Pouze lokální bootstrap journalu a případná prázdná soukromá staging složka. Projekt ani registrace neexistují. Osiřelá staging složka se nemaže bez doloženého vlastnictví; retence V-07. |
| `prepared` | Journal obsahuje UUID, parametry, přesné původní/cílové bajty node konfigurace, projektová metadata a staging inode/dev. Lze znovu sestavit pouze tento soukromý, dosud nepublikovaný staging. |
| `built`, před uložením `ready` | Vlastní rozpracovaný staging lze znovu sestavit; deterministická metadata/autor/čas dávají stejný initial commit. Žádný existující projekt není upravován. |
| `ready` | Commit ID a inode připraveného repo/state jsou uložené; již se nepřestavují. Publikace používá Linux renameat2 RENAME_NOREPLACE a fsync rodiče. |
| `root-published`, `state-published` | Chybějící staging cesta a shoda inode/dev cíle prokazují dokončený rename i před uložením dalšího stavu. Cizí cíl/změna dat znamenají konflikt, ne overwrite. |
| `indexed` | Journal/index projektu se inicializují stávajícím Workspace až na konečném umístění, aby owner nebyl navázán na staging. Rebuild transakce je opakovatelný dle ADR 0014. |
| `node-published` | Node JSON se nahradí atomicky z kompletního fsync souboru pouze při shodě původních bajtů pod zámkem; nový soubor se publikuje bez přepisu existujícího cíle. Pokud již odpovídá cílovým bajtům, recovery pokračuje bez druhé registrace. Cizí změna se zachová a recovery odmítne pokračovat. |
| `completed` | Receipt je trvale uložen; stejné ID/parametry vrací stejný výsledek bez zápisů. Staging po dokončení lze uklidit pouze dle uloženého vlastnictví; selhání tohoto volitelného úklidu neruší receipt. |

Do projektu jde pouze `project.json` a počáteční Git commit s explicitním lokálním autorem, nikoli node konfigurace nebo credentials. Nový projekt je záměrně prázdný. Úplná validace konfigurace a první projekce předchází registraci.

## Běh a omezení

GUI má jedinou pracovní úlohu mimo Qt event loop; při běhu zakáže další vytvoření a běžné zavření je do dokončení zakázané. Obnova dříve potvrzené operace se při restartu spustí automaticky, chyba se zobrazí v nativním okně. Worker má celkový deadline pro aplikační kroky a Git subprocessy; timeout zachová pending operaci. Zámek je neblokující a SQLite čekání omezené. Nejde o preempci libovolného blokujícího filesystemového syscallu ani důkaz výpadku napájení.

Tím je vymezen nativní mutující vstup potřebný pro M1-02. Obecný mutující HTTP protokol, klientské retry/receipt API pro editor, produkční RBAC a odolnost proti nekooperujícím FS útočníkům zůstávají V-10/V-06. Stejný node/root/state musí sdílet všichni kooperující klienti. Nezavádí se nový framework, Git adapter ani druhý backendový proces. Reuse: konfigurační validátory, Git, Workspace a fsync/flock vzor stávajícího journalu; uzlový journal má jiný lifecycle než projektové změny.

Ověření: `tests/test_project_creation.py` prochází procesními pády na všech uvedených checkpointech, native dialogem i skutečným běžným startem s automatickou obnovou. Test `.deb` ověřuje vytvoření a zachování dat po odinstalaci. Aktuální výsledky a zbylá omezení drží [WORK_LOG](../../WORK_LOG.md).
