# ADR 0003 — Koordinovaná operace nad journalem, Gitem a indexem

Datum: 2026-09-09. Stav: přijato a PoC validated pro Linux M0-01; produkční stack zůstává otevřený.

## Rozhodnutí a reuse

Adaptovat existující Journal (validace, bajty, fsync a flock), Git CLI wrapper a Index. Nad nimi zavést `Workspace` jako společný vstup pro zápis, obnovu a čtení. Samostatné experimentální API zůstávají pro původní testy; nejsou aplikační cestou. ADR 0002 zůstává historií souborového experimentu.

SQLite journal mimo projekt drží společně souborový záměr a metadata operace: UUID, výchozí HEAD, větev, vlastněné cesty, explicitní autor/committer, zpráva, stav a výsledný commit ID. Dokončený záznam zůstane jako receipt, souborové payloady se odstraní až po indexaci. Projektový SQLite index zůstává obnovitelnou projekcí.

## Crash boundaries a recovery (před implementací)

| Hranice | Trvalý stav a očekávaná obnova |
| --- | --- |
| Před potvrzením záměru | Žádné projektové soubory ani HEAD se nezměnily; neexistuje připravená operace. |
| `prepared`, během náhrady jednotlivých souborů | Metadata operace a původní/cílové bajty jsou v jedné SQLite transakci; journal dokončí zápisy dopředu, cizí editaci zachová a odmítne pokračovat. |
| `files-applied` | Payloady stále existují. Zkontrolovat HEAD, cizí změny a validaci, vytvořit commit jen z vlastněných cest nad výchozím stromem. |
| Commit objekt vznikl, jeho ID ještě není v journalu | Větev se neposunula; případný osiřelý objekt není publikovaným commitem. Lze znovu připravit kandidáta. |
| `commit-ready` | Kandidát a jeho ID jsou trvale v journalu před posunem větve. Větev aktualizovat compare-and-swap z výchozího HEAD. |
| Větev posunuta, stav `committed` ještě nezapsán | HEAD rovný uloženému kandidátu znamená již publikovaný commit; nevytvářet druhý. Jiný HEAD/větev znamená konflikt. |
| `committed`, před/během indexace | Obnovit Git staging index na kandidáta a SQLite projekci z validovaného HEAD; cizí staging nepřepsat. |
| `indexed`, před úklidem | Indexaci lze bezpečně opakovat. Dokončený receipt a smazání payloadů potvrdit atomicky. |
| Po úklidu | Další recover je no-op; chybějící/stale projektový index lze obnovit z HEAD. |

Zámek pokrývá celý životní cyklus a sdílí jej Journal i Workspace. Čtení přes Workspace při pending operaci odmítne publikovat stav; samotný nízkoúrovňový Index nezná journal. Nový zápis nejprve vyžaduje čistý pracovní strom a staging; nerozlišitelné cizí změny bezpečně odmítá. Obnova kontroluje i původní větev a cizí staging. Posun větve používá očekávaný starý HEAD, nikoli force update.

## Rozsah a limity

PoC pro kontrolovaný lokální Linux repozitář s existujícím commitem a běžnou větví; inicializace projektu, detached/unborn HEAD, worktrees, probíhající merge/rebase a síťová publikace nejsou součástí. Všichni aplikační účastníci musí sdílet jediný stavový adresář a zámek. Nekooperující editor/Git může být detekován, ale není tím vyřešen závodící útočník nad filesystemem. Bez záruky výpadku napájení, obnovy po ztrátě disku nebo přesunu pending projektu.

## Ověření

`python3 -m unittest discover -s tests -v`: **32 testů prošlo** na vývojovém Linux hostu (19 původních + 13 nových). `tests/test_workspace.py` pokrývá skutečné `os._exit` na 12 hranicích od prepared po úklid a další pády během opakované recovery. Pád před potvrzením záměru je ověřen výjimkou a rollbackem SQLite transakce.

Ověřeny přesné bajty a cesty commitu, explicitní autor i committer, jediný rodič a absence duplicitního commitu, import/rename/delete, odmítnutí neplatného/no-op vstupu a chybějící identity, změna HEAD/větve i návrat publikovaného HEAD, cizí editace/staging před a po commitu, selhání indexace a obnova smazané projekce po znovuotevření. Dva subprocess zapisovatelé sdílejí zámek; druhý naváže na commit prvního. Čtení přes Workspace při pending stavu selže. Low-level API ani nekooperační závody nejsou tímto pokryté.

Soukromý Git staging index se skládá přes `hash-object` a `update-index` přímo z journalových bajtů; nejde přes `git add --all` ani obsahové clean filtry. Změněné soubory mají Git mód 100644, stejně jako souborový journal nepřenáší původní filesystemová práva. SQLite spojení Indexu se explicitně zavírají; integrační testy odhalily dřívější ResourceWarning při jejich ponechání garbage collectoru.

Zbývá produkční řízení všech vstupů a bezpečnost cizích Git konfigurací podle TODO V-06, úklid osiřelých dočasných staging souborů/objektů a retence receipts podle V-07. Testovací checkpointy neběží uvnitř Git/SQLite syscalls; nedokládají recovery po násilném přerušení libovolného podprocesu ani po výpadku napájení.
