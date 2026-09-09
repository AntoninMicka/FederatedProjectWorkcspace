# Otevření projektu v desktopu

Desktop M1-01 čte již registrované projekty. Z checkoutu:

```sh
./run.sh desktop --node /absolutni/cesta/node.json
```

Z nově sestaveného a nainstalovaného balíku:

```sh
federated-workspace-poc --node /absolutni/cesta/node.json
```

Bez `--node` funguje ověření spojení a zobrazí se prázdný seznam. Relativní cesta se vyhodnocuje vůči adresáři volajícího. V okně vyberte ID a klikněte na **Otevřít**. Zobrazí se název projektu, commit ID a názvy/ID artefaktů z tohoto commitu; prázdný projekt má vlastní hlášení. Registry a obsah souborů zatím nemají vlastní zobrazení. Při chybě se předchozí výsledek vymaže.

## Existující data

`node.json` zůstává mimo projektový Git. Příklad (nahraďte absolutní cesty):

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

Při otevření mohou vzniknout lokální `journal.sqlite`, `writer.lock` a `index.sqlite`. Nový lock/index mají 0600. Existující stavové soubory musejí být soukromé běžné soubory bez hardlinků; aplikace jim automaticky nemění práva. Chybějící/stale index se obnoví z validovaného HEAD. Pending operace vyžaduje samostatnou obnovu podle ADR 0003; neplatný či poškozený index se nevydává za aktuální. Kvůli chybě nemažte journal.

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

Po spuštění ověřte otevření, název, commit a „První poznámka“. Zavřete aplikaci a spusťte vypsaný příkaz znovu; údaje zůstanou stejné. Editor a vytváření/registrace projektu v UI navazují samostatně. Limity a recovery: [ADR 0014](adr/0014-project-read.md).
