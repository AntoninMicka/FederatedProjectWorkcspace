"""Recoverable creation of a new local project, separate from artifact mutations."""
from contextlib import contextmanager
import ctypes
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import time
from uuid import uuid4

from spikes.configuration import local_path, overlap, parse_node, parse_project, read_config
from spikes.journal import sync_dir
from spikes.metadata import uuid
from spikes.projects import directory
from spikes.storage import Git
from spikes.workspace import Workspace

STAGES = ('prepared', 'built', 'ready', 'root-published', 'state-published',
          'indexed', 'node-published', 'completed')


class CreationConflict(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise CreationConflict(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def default_node_path():
    base = os.environ.get('XDG_STATE_HOME')
    if not base or not Path(base).is_absolute():
        base = Path.home() / '.local' / 'state'
    return Path(base) / 'federated-workspace' / 'node.json'


def identity(path):
    info = path.lstat()
    check(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid(), 'Neplatná pracovní složka.')
    return [info.st_dev, info.st_ino]


def regular(path, *, private=True):
    info = path.lstat()
    mask = 0o077 if private else 0o022
    check(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
          and not info.st_mode & mask, 'Neplatný vlastník, typ nebo práva lokálního souboru.')


def rename_new(source, target):
    """Linux atomic directory publication: never replace even an empty directory."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(target), 1):
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    sync_dir(target.parent)
    if source.parent != target.parent:
        sync_dir(source.parent)


def sync_tree(root):
    for parent, dirs, files in os.walk(root, topdown=False, followlinks=False):
        for name in files:
            fd = os.open(Path(parent) / name, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        sync_dir(parent)


class ProjectCreation:
    def __init__(self, node_path, *, timeout=60):
        self.node_path = Path(node_path).absolute()
        self.runtime = self.node_path.parent / ('.' + self.node_path.name + '.operations')
        self.database = self.runtime / 'creation.sqlite'
        self.timeout = timeout

    def _node(self):
        if not os.path.lexists(self.node_path):
            return None, None
        regular(self.node_path, private=False)
        data = read_config(self.node_path)
        return data, parse_node(data, location=self.node_path)

    @contextmanager
    def _locked(self):
        check(self.node_path == self.node_path.resolve(), 'Konfigurace uzlu nesmí vést přes symlink.')
        before, node = self._node()
        if node:
            for binding in node['projects']:
                for key in ('root', 'state_dir'):
                    check(not overlap(self.runtime, local_path(binding[key])),
                          'Journal uzlu musí být mimo projekt a jeho stav.')
        missing, parent = [], self.node_path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        directory(parent)
        for path in reversed(missing):
            path.mkdir(mode=0o700)
            sync_dir(path.parent)
        self.runtime.mkdir(mode=0o700, exist_ok=True)
        directory(self.runtime, private=True)
        sync_dir(self.runtime.parent)
        for path in self.runtime.iterdir():
            regular(path)
        fd = os.open(self.runtime / 'writer.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CreationConflict('Jiná operace uzlu právě probíhá. Zkuste to později.') from exc
            fd = os.open(self.database, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            db = sqlite3.connect(self.database, timeout=2)
            try:
                db.execute('PRAGMA synchronous=FULL')
                version = db.execute('PRAGMA user_version').fetchone()[0]
                check(version in (0, 1), 'Nepodporovaná verze journalu vytváření.')
                db.executescript('''
                    CREATE TABLE IF NOT EXISTS local_author (id TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS creations (
                        id TEXT PRIMARY KEY, record TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0);
                    CREATE UNIQUE INDEX IF NOT EXISTS one_pending_creation ON creations(done) WHERE done=0;
                    PRAGMA user_version=1;
                ''')
                if db.execute('SELECT id FROM local_author').fetchone() is None:
                    db.execute('INSERT INTO local_author VALUES (?)', (str(uuid4()),))
                db.commit()
                sync_dir(self.runtime)
                yield db
            finally:
                db.close()

    def author_id(self):
        """Reuse the durable local author, never substitute the node UUID."""
        with self._locked() as db:
            return db.execute('SELECT id FROM local_author').fetchone()[0]

    def _save(self, db, record, *, done=False):
        db.execute('INSERT OR REPLACE INTO creations VALUES (?, ?, ?)',
                   (record['operation_id'], json.dumps(record), int(done)))
        db.commit()

    def create(self, title, root, operation_id, *, checkpoint=lambda stage: None):
        uuid(operation_id)
        check(isinstance(title, str) and bool(title.strip()) and len(title) <= 200
              and not any(ord(c) < 32 for c in title), 'Zadejte název projektu (nejvýše 200 znaků).')
        root = Path(root)
        check(root.is_absolute() and root == local_path(str(root)), 'Zadejte absolutní cestu bez symlinků.')
        directory(root.parent)
        deadline = time.monotonic() + self.timeout
        with self._locked() as db:
            row = db.execute('SELECT record, done FROM creations WHERE id=?', (operation_id,)).fetchone()
            if row:
                record = json.loads(row[0])
                check(record['root'] == str(root) and record['title'] == title,
                      'ID operace už patří jinému požadavku.')
                if row[1]:
                    return record['receipt']
                return self._finish(db, record, deadline, checkpoint)
            check(not db.execute('SELECT 1 FROM creations WHERE done=0').fetchone(),
                  'Nejprve dokončete přerušené vytvoření projektu.')
            check(not os.path.lexists(root), 'Cílová složka už existuje. Vyberte novou složku.')
            before, node = self._node()
            node = node or dict(schema_version=1, id=str(uuid4()), name='Lokální uzel', projects=[])
            project_id = str(uuid4())
            state = root.parent / ('.workspace-state-' + project_id)
            check(not os.path.lexists(state), 'Cílový lokální stav již existuje.')
            node['projects'].append(dict(project_id=project_id, root=str(root), state_dir=str(state)))
            after = encoded(node)
            parse_node(after, location=self.node_path)
            for binding in node['projects']:
                for key in ('root', 'state_dir'):
                    check(not overlap(self.runtime, local_path(binding[key])),
                          'Projekt ani stav nesmí překrývat journal uzlu.')
            meta = dict(schema_version=1, id=project_id, title=title,
                        created_at=datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
                        author_id=db.execute('SELECT id FROM local_author').fetchone()[0])
            parse_project(encoded(meta))
            stage = Path(tempfile.mkdtemp(prefix='.workspace-create-' + operation_id + '-', dir=root.parent))
            (stage / 'repo').mkdir(mode=0o700)
            (stage / 'state').mkdir(mode=0o700)
            sync_dir(stage)
            sync_dir(stage.parent)
            record = dict(operation_id=operation_id, title=title, root=str(root), state=str(state),
                          stage=str(stage), stage_identity=identity(stage), meta=meta,
                          before=before.decode() if before is not None else None, after=after.decode(),
                          ready=False, receipt=None)
            self._save(db, record)
            checkpoint('prepared')
            return self._finish(db, record, deadline, checkpoint)

    def recover(self, *, checkpoint=lambda stage: None):
        if not self.database.exists():
            return None
        deadline = time.monotonic() + self.timeout
        with self._locked() as db:
            row = db.execute('SELECT record FROM creations WHERE done=0').fetchone()
            return self._finish(db, json.loads(row[0]), deadline, checkpoint) if row else None

    def _finish(self, db, record, deadline, checkpoint):
        def boundary(stage):
            if time.monotonic() >= deadline:
                raise TimeoutError('Vytvoření překročilo časový limit; operace zůstala k obnově.')
            checkpoint(stage)

        root, state, stage = (Path(record[k]) for k in ('root', 'state', 'stage'))
        directory(root.parent)
        check(stage.parent == root.parent and stage.name.startswith('.workspace-create-' + record['operation_id'] + '-')
              and identity(stage) == record['stage_identity'], 'Pracovní složka operace se změnila.')
        before, _ = self._node()
        check(before in (None if record['before'] is None else record['before'].encode(), record['after'].encode()),
              'Konfigurace uzlu se mezitím změnila. Cizí změny byly zachovány.')
        if not record['ready']:
            check(not os.path.lexists(root) and not os.path.lexists(state), 'Cíl přerušené operace je obsazený.')
            check({p.name for p in stage.iterdir()} <= {'repo', 'state'}, 'Pracovní složka má cizí soubory.')
            # Before ready, these are solely unpublished disposable files owned by the recorded staging inode.
            if (stage / 'repo').exists():
                check(not (stage / 'repo').is_symlink(), 'Neplatný staging projektu.')
                shutil.rmtree(stage / 'repo')
            (stage / 'repo').mkdir(mode=0o700)
            check(not list((stage / 'state').iterdir()), 'Pracovní stav není prázdný.')
            repo = stage / 'repo'
            (repo / 'project.json').write_bytes(encoded(record['meta']))
            git = Git(repo, deadline=deadline)
            git.run('init', '--template=', '--initial-branch=main')
            (repo / '.git').chmod(0o700)
            git.run('add', '--', 'project.json')
            author = record['meta']['author_id']
            date = record['meta']['created_at']
            git.run('commit', '-m', 'Initialize project\n\nWorkspace-Creation: ' + record['operation_id'],
                    env_extra=dict(GIT_AUTHOR_NAME='Local user', GIT_COMMITTER_NAME='Local user',
                                   GIT_AUTHOR_EMAIL=author + '@local.invalid', GIT_COMMITTER_EMAIL=author + '@local.invalid',
                                   GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date))
            commit = git.head()
            sync_tree(stage)
            boundary('built')
            record.update(ready=True, commit_id=commit, root_identity=identity(repo),
                          state_identity=identity(stage / 'state'))
            self._save(db, record)
            boundary('ready')
        for name, target, expected in [('repo', root, record['root_identity']),
                                       ('state', state, record['state_identity'])]:
            source = stage / name
            if os.path.lexists(source):
                check(identity(source) == expected, 'Pracovní data operace se změnila.')
                rename_new(source, target)
            check(identity(target) == expected, 'Cílovou složku nahradila jiná data.')
            boundary('root-published' if name == 'repo' else 'state-published')
        git = Git(root, deadline=deadline)
        check(git.head() == record['commit_id'] and not git.run('status', '--porcelain', '--untracked-files=all').stdout,
              'Nově založený projekt byl mezitím změněn; změny byly zachovány.')
        check(read_config(root / 'project.json') == encoded(record['meta']), 'Projektová konfigurace byla změněna.')
        ws = Workspace(root, state)
        ws.git = git
        result = ws.read_project(record['meta']['id'])
        boundary('indexed')
        self._publish_node(record)
        boundary('node-published')
        record['receipt'] = dict(operation_id=record['operation_id'], id=result['id'],
                                 title=result['title'], commit_id=result['commit_id'])
        self._save(db, record, done=True)
        # Receipt is authoritative even if optional staging cleanup is interrupted.
        try:
            stage.rmdir()
            sync_dir(stage.parent)
        except OSError:
            pass  # Never delete unexpected files; retained for later explicit cleanup.
        checkpoint('completed')
        return record['receipt']

    def _publish_node(self, record):
        before, _ = self._node()
        after = record['after'].encode()
        if before == after:
            return
        check(before == (None if record['before'] is None else record['before'].encode()),
              'Konfigurace uzlu se mezitím změnila; nebyla přepsána.')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix='.node-write-', dir=self.node_path.parent, delete=False) as file:
                temporary = Path(file.name)
                file.write(after)
                file.flush()
                os.fsync(file.fileno())
            if before is None:
                rename_new(temporary, self.node_path)
            else:
                os.replace(temporary, self.node_path)
            sync_dir(self.node_path.parent)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
