# ADR 0002 — Validace metadat a obnova souborových operací

Datum: 2026-09-09. Stav: implementováno jako Linux M0 PoC, produkční integrace otevřená.

## Rozhodnutí

`spikes/metadata.py` je spustitelné schéma v1 pro artefakty a registry. Sdílí jej pracovní strom, journal a index konkrétního Git commitu. Nevaliduje zatím project.json, uživatele, konfiguraci federace ani LLM manifesty.

YAML zpracovává PyYAML 6.0.3 s vlastním SafeLoaderem. Odmítáme duplicitní klíče, aliasy, kotvy, explicitní tagy a merge klíče; datum se čte jako text. JSON také odmítá duplicitní klíče a nečíselné konstanty. Limity experimentu: 64 KiB metadat, hloubka 16, 16 MiB na soubor, 64 MiB a 10 000 souborů na projekci. Rozšíření pro velké přílohy bude vyžadovat streamování.

`spikes/journal.py` ukládá původní a cílové bajty změněných souborů do SQLite journalu mimo projekt. Tento journal je autoritativní rozpracovaná operace, nikoli obnovitelný index. Musí být v soukromém adresáři na stejném souborovém systému jako projekt. Journal vážeme na absolutní cestu projektu.

Tok operace: zámek zapisujícího procesu → načtení projekce → validace navrženého výsledku → trvalý journal → postupná náhrada souborů s fsync → validace výsledku → vyčištění journalu. Teprve poté volající vytváří Git commit a obnovuje index. Připravená operace se při obnově dokončuje dopředu. Při odlišné uživatelské změně se zastaví a uchová journal pro ruční rozhodnutí. Žádná automatická volba vítězné verze.

## Ověření

`python3 -m unittest discover -s tests -v`: 19 testů prošlo. CLI `python3 -m spikes.check_project` bylo navíc ověřeno na platné projekci (exit 0) a osiřelém sidecaru (exit 1).

Testy ukončují pomocný proces přes `os._exit` po uložení záměru, po každém ze dvou zápisů, před vyčištěním journalu i po něm. Pokrývají také přerušenou obnovu, přejmenování, smazání, pozdější editaci, odmítnutí smazání odkazovaného artefaktu, symlink a import binárních bajtů přes recovery → Git commit → index. Jde o pád procesu, nikoli simulaci výpadku napájení/filesystému.

## Hranice PoC

- Zámek koordinuje pouze volající Journal. Editor, Git operace a čtenáři budoucí aplikace musí respektovat stejný životní cyklus; při pending operaci se projekt nesmí commitovat ani zpřístupnit jako konzistentní pracovní stav.
- Přímý `Git.commit` zatím nemá napojení na journal a používá testovací identitu. Není určen k samostatnému produkčnímu použití.
- Kontroly cest chrání proti statickým symlinkům, nikoli proti závodící změně souborového systému jiným procesem. PoC předpokládá soukromý projekt a kooperujícího jediného zapisovatele.
- Přesun projektu s pending journalem, síťový souborový systém, Windows, ztráta disku a rollback nejsou implementovány.
- Neměnné zdroje se při importu neparsují ani nenormalizují. Práva souborů nejsou součástí obnovované historie; nové zápisy dostávají režim 0600.

## Podklady

- [PyYAML: SafeLoader a vlastní konstruktory](https://pyyaml.org/wiki/PyYAMLDocumentation)
- [Python os: replace a fsync](https://docs.python.org/3/library/os.html)
- [Python sqlite3: transakce](https://docs.python.org/3/library/sqlite3.html)
