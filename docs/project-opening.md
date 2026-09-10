# Projekty v desktopu

## Vytvoření nového projektu

Spusťte `./run.sh desktop` (z instalovaného balíku `federated-workspace-poc`). V horní nativní liště zvolte **Nový projekt…**. Vyplňte název a absolutní cestu nové složky, případně vyberte jejího rodiče tlačítkem **Vybrat nadřazenou složku…**. Název projektu je popisek; název cílové složky lze upravit nezávisle. Klikněte na **Vytvořit a otevřít**.

Cílová složka ještě nesmí existovat, ani prázdná. Její rodič musí existovat, patřit vám a nebýt zapisovatelný jinými uživateli. Aplikace vytvoří prázdný projekt s `project.json` a prvním commitem, zaregistruje jej a otevře. Zobrazí název, commit a zprávu o prázdném seznamu artefaktů. JSON ani Git příkazy zadávat nemusíte. Zavřete a znovu spusťte desktop; projekt zůstane v seznamu. Dokument vytvoříte tlačítkem **Markdown editor…**.

Výchozí `node.json` vznikne při prvním potvrzeném vytvoření v `$XDG_STATE_HOME/federated-workspace/`, jinak `~/.local/state/federated-workspace/`. Pouhé spuštění bez projektu nic neinicializuje. Vedle konfigurace se ukládá soukromý adresář `.node.json.operations` s uzlovým journalem a receipts. Projektový stav vznikne vedle cílové složky jako `.workspace-state-<project UUID>`; zůstává mimo Git na stejném filesystemu. Tyto stavové složky nejsou cache a nemají se mazat.

V průběhu vytváření je další vytvoření a běžné zavření okna dočasně zakázané; po dokončení lze okno zavřít. Při násilném ukončení se dříve potvrzená operace při příštím běžném startu obnoví. Po chybě je dostupné také **Dokončit přerušené vytvoření**. Pokud se mezitím změnil cíl nebo konfigurace, aplikace změny zachová a zobrazí chybu; nepřepisujte ani nemažte journal kvůli jejímu obejití. Zrušení konfliktní pending operace ještě nemá vlastní UI. Osiřelé soukromé staging složky `.workspace-create-*` po přerušení před zápisem záměru se automaticky nemažou.

Kontrakt, idempotence a hranice recovery: [ADR 0015](adr/0015-project-creation.md). Jde o lokální Linux PoC, nikoli produkční správu identit nebo úplné recovery po výpadku napájení.

## Jiný uzel a již registrované projekty

Explicitní konfiguraci lze vybrat z checkoutu:

```sh
./run.sh desktop --node /absolutni/cesta/node.json
```

Z nově sestaveného a nainstalovaného balíku:

```sh
federated-workspace-poc --node /absolutni/cesta/node.json
```

Bez `--node` se používá výchozí uzel popsaný výše; bez registrací je seznam prázdný. Relativní cesta se vyhodnocuje vůči adresáři volajícího. V okně vyberte ID a klikněte na **Otevřít**. Zobrazí se název projektu, commit ID a názvy/ID artefaktů z tohoto commitu; prázdný projekt má vlastní hlášení. Markdown dokumenty otevřete nativním editorem; registry zatím nemají vlastní zobrazení. Při chybě se předchozí výsledek vymaže.

## Markdown editor a checklisty

Vyberte projekt v seznamu a klikněte na **Markdown editor…**. V dialogu vyberte existující dokument nebo **Nový dokument**, vyplňte název a text a stiskněte **Uložit**. V záložce **Metadata** lze upravit popis a štítky (jeden na řádek); uložená metadata včetně původu, autora a data vytvoření jsou také vidět pouze pro čtení. Prázdný popis či seznam štítků jejich hodnotu vyčistí. Obsah a metadata se uloží společně do Gitu. Rozpracovaný text před uložením existuje pouze v okně.

Checklist pište přímo jako `- [ ] Úkol` a `- [x] Hotovo`, případně použijte **Přidat položku checklistu**. Panel vpravo umožňuje položky zaškrtávat; změnu potvrďte tlačítkem **Uložit**. Text uvnitř fenced code bloků se jako checklist nezobrazuje. Editor zobrazuje zdrojový Markdown, ne HTML náhled.

**Hlavní TODO…** v horní liště otevře hlavní seznam projektu. Při prvním použití nabídne návrh, který vznikne až uložením. Stejné tlačítko vždy míří na stejný dokument, i když změníte jeho název. Vedle něj můžete mít další dokumenty s vlastními checklisty.

Při chybě uložení text zůstane v okně a **Zopakovat uložení** použije původní požadavek. **Znovu načíst / obnovit** načte aktuální projekt a dokončí připravený zápis; před opuštěním rozepsaného textu žádá potvrzení. Při souběžné změně projektu si text před opětovným načtením zkopírujte, automatické sloučení editor zatím neumí. Po pádu desktopu znovu otevřete editor daného projektu; potvrzené pending uložení se obnoví. Pouhé otevření webového přehledu pending zápis nedokončuje.

Levý panel má dvě záložky **TODO** a **Zdroje / artefakty**. Druhá zobrazuje názvy a ID všech uložených artefaktů projektu včetně zdrojů (například PDF); seznam je pouze pro čtení. Záložky přepnete kliknutím, šipkami vlevo/vpravo nebo klávesami Home/End. Volba zůstává zachovaná při obnově dat a přepnutí projektu v tomto okně; po restartu se otevře TODO. Při přepnutí projektu či chybě se starý obsah obou záložek vymaže.

Po otevření projektu je hlavní TODO také v levém panelu: názvy položek, stav zaškrtnutí a počet hotových úkolů. Odsazené checklisty tvoří podúkoly; větve lze sbalit a rozbalit. Checkboxy zde slouží jen pro čtení, úpravy dělejte v editoru. Přehled ukazuje uložený Git stav a po uložení v editoru se obnoví. Po externí změně použijte **Otevřít** znovu. Neexistující TODO a dokument bez checklistů mají vlastní hlášení. U velkého seznamu se zobrazí prvních 1000 položek s upozorněním.

Ověření pro uživatele: vytvořte hlavní TODO, zaškrtněte položku, uložte, zavřete a znovu spusťte desktop. Otevřete **Hlavní TODO…** a ověřte text i zaškrtnutí. Editor podporuje document artefakty v Markdownu do 1 MiB těla. Podrobný kontrakt a limity: [ADR 0016](adr/0016-markdown-editor.md).

## Historie dokumentu

V Markdown editoru vyberte uložený dokument a klikněte na **Historie…**. Seznam verzí uvádí datum, autora, krátké ID commitu a zprávu. Vyberte **Starší / výchozí verzi** a **Zobrazenou verzi**, potom **Zobrazit a porovnat**.

Záložky ukazují původní obsah zobrazené verze, její metadata, rozdíl uložených souborů a úplnou zprávu commitu. Pro samotné prohlédnutí jediné verze můžete v obou seznamech vybrat stejný commit. Rozepsaný text zůstává v editoru zachovaný a historie jej neukládá ani nepřepisuje. U nového dosud neuloženého dokumentu je tlačítko historie nedostupné.

Historie je pouze pro čtení. Při změně projektu nebo pending operaci dialog zobrazí chybu; zavřete historii a použijte obnovu/nové načtení editoru, po zachování rozepsaného textu. Neplatné starší verze jsou označené a nelze je zobrazit jako validní dokument. Seznam ukazuje nejvýše 100 záznamů, případné zkrácení oznámí. Podrobnosti: [ADR 0017](adr/0017-artifact-history.md).

## Existující data

`node.json` zůstává mimo projektový Git. Pro zapisující operace musí jít o váš běžný soubor bez symlinků/hardlinků a bez práva zápisu jiných uživatelů; nové konfigurace mají 0600. Příklad (nahraďte absolutní cesty):

```json
{
  "schema_version": 1,
  "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "name": "Lokální desktop",
  "projects": [{
    "project_id": "11111111-1111-4111-8111-111111111111",
    "root": "/absolutni/cesta/projekt",
    "state_dir": "/absolutni/cesta/lokalni-stav"
  }]
}
```

Kořen projektu musí být vlastní běžný Git repozitář s commitem na větvi a následujícím commitnutým `project.json` (stejné ID jako v registraci):

```json
{
  "schema_version": 1,
  "id": "11111111-1111-4111-8111-111111111111",
  "title": "První projekt",
  "created_at": "2026-09-09T12:00:00Z",
  "author_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
}
```

Autor ID je metadata, nikoli oprávnění. Schéma a požadavky na artefakty popisuje [datový model](../DATA_MODEL.md); konfigurace [ADR 0004](adr/0004-project-node-config.md). Staré storage demo bez `project.json` není automaticky migrováno.

Stavový adresář musí již existovat, patřit běžnému uživateli a mít práva 0700; kořen projektu a `.git` nesmějí být zapisovatelné jinými uživateli. Root/state musí být vzájemně oddělené, bez symlinků a na stejném filesystemu. Použijte existující stav daného projektu, pokud už má journal — nepřesměrujte jej na prázdný adresář kvůli obejití pending operace. Všechny aplikace nad stejným projektem musí sdílet stejný stav a zámek.

Při otevření mohou vzniknout lokální `journal.sqlite`, `writer.lock` a `index.sqlite`. Nový lock/index mají 0600. Existující stavové soubory musejí být soukromé běžné soubory bez hardlinků; aplikace jim automaticky nemění práva. Chybějící/stale index se obnoví z validovaného HEAD. Pending operaci obnoví otevření nativního editoru podle ADR 0003; neplatný či poškozený index se nevydává za aktuální. Kvůli chybě nemažte journal.

## Izolovaná ukázka bez zásahu do existujících projektů

Z kořene checkoutu spusťte následující blok Pythonem s PyYAML 6.0.3 (`python3`, případně `.venv/bin/python`). Vytvoří pouze vlastní adresář pod `/tmp`, ukázkový Git projekt a oddělený stav; vytiskne příkaz pro spuštění. Data zůstanou pro restart desktopu, systém je může později odstranit jako dočasná.

```sh
python3 - <<'PY'
import json
from pathlib import Path
import shlex
import tempfile
from spikes.storage import Git

base = Path(tempfile.mkdtemp(prefix='workspace-m1-'))
root, state = base / 'project', base / 'state'
root.mkdir(mode=0o755)
state.mkdir(mode=0o700)
project_id = '11111111-1111-4111-8111-111111111111'
author_id = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
meta = dict(schema_version=1, id=project_id, title='První projekt',
            created_at='2026-09-09T12:00:00Z', author_id=author_id)
(root / 'project.json').write_text(json.dumps(meta), encoding='utf-8')
folder = root / 'artifacts' / project_id
folder.mkdir(parents=True)
artifact = dict(meta, title='První poznámka', kind='document', privacy='project', provenance='user')
(folder / 'note.md').write_text('---\n' + json.dumps(artifact) + '\n---\nObsah poznámky.\n', encoding='utf-8')
git = Git(root)
git.run('init', '--initial-branch=main')
(root / '.git').chmod(0o755)
git.commit('Initialize isolated desktop example')
node = base / 'node.json'
node.write_text(json.dumps(dict(schema_version=1, id=author_id, name='Ukázkový uzel',
    projects=[dict(project_id=project_id, root=str(root), state_dir=str(state))])), encoding='utf-8')
print('./run.sh desktop --node ' + shlex.quote(str(node)))
PY
```

Po spuštění ověřte otevření, název, commit a „První poznámka“. Zavřete aplikaci a spusťte vypsaný příkaz znovu; údaje zůstanou stejné. Tlačítkem **Markdown editor…** otevřete a upravte poznámku; po uložení a restartu ověřte změněný obsah. Limity a recovery: [ADR 0014](adr/0014-project-read.md).
